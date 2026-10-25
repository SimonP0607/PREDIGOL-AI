#!/bin/sh
# PrediGol — autoprueba de la red de Gitleaks (plan de seguridad, R07 / S1.c).
#
#   security/selftest.sh
#
# Crea un repositorio de juguete en una carpeta temporal, le pone el hook de pre-commit de la guarda y comprueba, con secretos FALSOS fabricados al
# momento (ninguno está escrito en este fichero ni en el historial: se componen en cada ejecución), que:
#   - lo que tiene aspecto de secreto real se BLOQUEA, y lo para la regla esperada (incluida la clave de 32 hexadecimales con poca entropía, que la
#     regla genérica de fábrica deja pasar);
#   - los marcadores de las plantillas, las referencias ${VAR}, los valores vacíos o cortos y las constantes de las pruebas PASAN;
#   - SKIP_GITLEAKS=1 y GITLEAKS_REQUIRED=1 se portan como dice security/README.md;
#   - security/scan.sh range e history ven lo que el hook no vio (un commit hecho con --no-verify) y no dan «limpio» con un rango que no existe.
# Se ejecuta al instalar la guarda en una máquina, cada vez que cambia .gitleaks.toml y en la CI. No toca el repositorio desde el que se lanza.
#
# Salida: 0 todo se comporta como debe · 1 algo falla · 2 no se pudo preparar la prueba.
# Variables: GITLEAKS_BIN (binario), PREDIGOL_GUARD_DIR (carpeta con .githooks/, security/, .gitleaks.toml; por defecto la raíz de este repo).
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
GUARD=${PREDIGOL_GUARD_DIR:-$(cd "$HERE/.." && pwd)}
HOOKS="$GUARD/.githooks"
[ -f "$HOOKS/pre-commit" ] && [ -f "$GUARD/security/scan.sh" ] && [ -f "$GUARD/.gitleaks.toml" ] \
  || { echo "selftest: faltan piezas de la guarda en $GUARD (.githooks/pre-commit, security/scan.sh, .gitleaks.toml)" >&2; exit 2; }
command -v git > /dev/null 2>&1 || { echo "selftest: git no está en el PATH" >&2; exit 2; }
T=$(mktemp -d 2> /dev/null) || { echo "selftest: no pude crear una carpeta temporal" >&2; exit 2; }
cleanup() { cd / 2> /dev/null; chmod -R u+w "$T" 2> /dev/null; rm -rf "$T"; }
trap cleanup EXIT
trap 'exit 2' INT TERM
export PREDIGOL_GUARD_DIR="$GUARD"
unset SKIP_GITLEAKS GITLEAKS_REQUIRED
ESC=$(printf '\033')

# ---------- valores falsos, fabricados al momento ----------------------------------------------------------------------------------------------
# Una cadena al azar no debe contener, por casualidad, una de las palabras de relleno que la configuración deja pasar a propósito.
FILLER='change example your placeholder replace dummy fake redacted todo tbd sample xxxx 0000 test secret none null unset empty password rehearsal'
clean() { # imprime $1 si no contiene ninguna palabra de relleno
  lc=$(printf '%s' "$1" | tr 'A-Z' 'a-z')
  for fw in $FILLER; do case $lc in *"$fw"*) return 1 ;; esac; done
  printf '%s' "$1"
}
rnd() { # rnd <alfabeto para tr> <longitud>
  while :; do
    v=$(LC_ALL=C tr -dc "$1" < /dev/urandom | head -c "$2")
    [ "${#v}" -eq "$2" ] || continue
    clean "$v" && return 0
  done
}
rnd_hex() { rnd 'a-f0-9' "$1"; }
rnd_alnum() { rnd 'A-Za-z0-9' "$1"; }
rnd_digits() { rnd '1-9' "$1"; }
rnd_url() { rnd 'A-Za-z0-9_-' "$1"; }

# ---------- el repositorio de juguete -----------------------------------------------------------------------------------------------------------
R="$T/repo"
mkdir -p "$R" && cd "$R" || exit 2
git init -q . || { echo "selftest: git init falló" >&2; exit 2; }
git config user.name selftest
git config user.email selftest@example.invalid
git config commit.gpgsign false
git config core.autocrlf false
git config core.hooksPath "$HOOKS"
git commit -q --allow-empty --no-verify -m base || { echo "selftest: no pude crear el commit base" >&2; exit 2; }

PASS=0
FAIL=0
ok() { PASS=$((PASS + 1)); printf '  OK     %s\n' "$1"; }
bad() { FAIL=$((FAIL + 1)); printf '  FALLA  %s\n' "$1"; }
w() { # w <fichero> <línea>... : escribe las líneas (crea las carpetas)
  f=$1
  shift
  mkdir -p "$(dirname "$f")"
  : > "$f"
  for l in "$@"; do printf '%s\n' "$l" >> "$f"; done
}
rules_seen() { printf '%s\n' "$OUT" | sed -n 's/^RuleID:[[:space:]]*//p' | tr -d '\r' | sort -u | tr '\n' ' '; }
commit_try() { # confirma lo que hay en el directorio de trabajo; deja el resultado en RC y OUT (sin colores)
  git add -A > /dev/null 2>&1
  OUT=$(git commit -q -m selftest 2>&1)
  RC=$?
  OUT=$(printf '%s' "$OUT" | sed "s/${ESC}\[[0-9;]*m//g")
}
back_to_head() { git reset -q --hard HEAD > /dev/null 2>&1; git clean -fdq > /dev/null 2>&1; }
expect_block() { # <etiqueta> <regla(s) esperada(s), separadas por |>
  commit_try
  if [ "$RC" -ne 0 ] && printf '%s\n' "$OUT" | grep -Eq "^RuleID:[[:space:]]+($2)([[:space:]]|\$)"; then
    ok "se bloquea: $1 [$(rules_seen)]"
  elif [ "$RC" -ne 0 ]; then
    bad "se bloquea, pero por otra regla: $1 (esperada: $2; vistas: $(rules_seen))"
  else
    bad "NO se bloquea: $1"
  fi
  back_to_head
}
expect_pass() { # <etiqueta>
  commit_try
  if [ "$RC" -eq 0 ]; then
    ok "pasa: $1"
  else
    bad "se bloquea y no debería: $1 (reglas: $(rules_seen))"
    back_to_head
  fi
}

echo "selftest: guarda en $GUARD"
echo "selftest: $(${GITLEAKS_BIN:-gitleaks} version 2> /dev/null | tr -d '\r' | head -n 1 | sed 's/^/gitleaks /')"
echo
echo "1) Lo que parece un secreto real se bloquea"
LOWE=$(printf 'a1b2c3d4%.0s' 1 2 3 4) # 32 hexadecimales con solo 8 símbolos distintos: entropía 3,0 < 3,5 (la regla genérica de fábrica lo ignora)
w settings.env "API_FOOTBALL_KEY=$LOWE"
expect_block "clave de API-Football de 32 hexadecimales con poca entropía" "predigol-apifootball-key"
w app.env "FBI_APIFOOTBALL_KEY=$(rnd_hex 32)"
expect_block "FBI_APIFOOTBALL_KEY con 32 hexadecimales al azar" "predigol-apifootball-key|predigol-secret-by-name"
w client.py "headers = {\"x-apisports-key\": \"$(rnd_hex 32)\"}"
expect_block "cabecera x-apisports-key con la clave dentro del código" "predigol-apifootball-key|generic-api-key"
w db.env "POSTGRES_PASSWORD=$(rnd_alnum 24)"
expect_block "POSTGRES_PASSWORD con una contraseña generada" "predigol-secret-by-name"
w auth.env "FBI_AUTH_SECRET_KEY=$(rnd_url 43)"
expect_block "FBI_AUTH_SECRET_KEY con 43 caracteres al azar" "predigol-secret-by-name|generic-api-key"
w src/svc.py "api_key = \"$(rnd_alnum 40)\""
expect_block "api_key con un valor al azar en el código (regla genérica de fábrica)" "generic-api-key"
w ci.env "GITHUB_TOKEN=ghp_$(rnd_alnum 36)"
expect_block "token de GitHub con su formato (regla de formato de fábrica)" "github-pat"
w bot.env "FBI_TELEGRAM_BOT_TOKEN=$(rnd_digits 10):A$(rnd_url 34)"
expect_block "token de bot de Telegram con su formato" "telegram-bot-api-token|predigol-secret-by-name"
w src/auth.py "TEST_AUTH_KEY = \"$(rnd_alnum 44)\""
expect_block "la constante de prueba (TEST_AUTH_KEY) FUERA de la carpeta de pruebas" "generic-api-key"
{
  printf -- '-----BEGIN %s-----\n' "PRIVATE KEY"
  rnd_alnum 90
  printf '\n-----END %s-----\n' "PRIVATE KEY"
} > id_demo.pem
expect_block "bloque de clave privada" "private-key"
w src/dsn.py "URL = \"postgresql://fbi:$(rnd_alnum 12)@localhost:5433/fbi\""
expect_block "contraseña dentro de una URL de base de datos, en el código (aunque sea localhost)" "predigol-db-url-password"
w deploy/prod.env "FBI_DATABASE_URL=postgresql+psycopg://fbi:$(rnd_alnum 20)@db.interno:5432/fbi"
expect_block "FBI_DATABASE_URL con la contraseña escrita" "predigol-db-url-password"
w tests/unit/test_remote.py "URL = \"postgresql://fbi:$(rnd_alnum 12)@db.interno:5432/fbi\""
expect_block "URL de base de datos con host que NO es local, aunque esté en tests/" "predigol-db-url-password"
w ping.env "HC_URL=https://hc-ping.com/$(rnd_hex 8)-$(rnd_hex 4)-$(rnd_hex 4)-$(rnd_hex 4)-$(rnd_hex 12)"
expect_block "URL de ping de Healthchecks.io" "predigol-healthchecks-ping-url"
w mail.env "MAIL_TOKEN=re_$(rnd_alnum 8)_$(rnd_alnum 24)"
expect_block "clave de Resend por su formato (re_...)" "predigol-resend-api-key"
w supa.env "SUPA=sb_secret_$(rnd_url 30)"
expect_block "clave secreta de Supabase por su formato (sb_secret_...)" "predigol-supabase-secret-key"
w setenv.ps1 "\$env:FBI_AUTH_SECRET_KEY = \"$(rnd_alnum 43)\""
expect_block "asignación de PowerShell (\$env:NOMBRE = valor)" "predigol-secret-by-name|generic-api-key"
w boot.py "os.environ[\"FBI_AUTH_SECRET_KEY\"] = \"$(rnd_alnum 43)\""
expect_block "os.environ[\"NOMBRE\"] = valor en Python" "predigol-secret-by-name|generic-api-key"
w run.sh "docker run --rm -e POSTGRES_PASSWORD=$(rnd_alnum 24) postgres:16"
expect_block "docker run -e NOMBRE=valor" "predigol-secret-by-name"
w ci.yml "env:" "  - POSTGRES_PASSWORD=$(rnd_alnum 24)"
expect_block "lista YAML - NOMBRE=valor" "predigol-secret-by-name"

echo
echo "2) Lo que no es un secreto pasa"
w deploy/compose.yml \
  'services:' \
  '  db:' \
  '    environment:' \
  '      POSTGRES_PASSWORD: ${POSTGRES_PASSWORD:-changeme}' \
  '      FBI_DATABASE_URL: postgresql+psycopg://fbi:${POSTGRES_PASSWORD}@db:5432/fbi' \
  '    command: : "${PITR_CIPHER_PASS:?define PITR_CIPHER_PASS}"'
expect_pass "referencias \${VAR}, con valor por defecto y con aviso, en un compose"
w templates/app.env.example \
  'FBI_AUTH_SECRET_KEY=' \
  'FBI_APIFOOTBALL_KEY=' \
  'FBI_LOG_LEVEL=information-level-here' \
  'POSTGRES_PASSWORD=<generate-with-openssl-rand>' \
  'FBI_TELEGRAM_BOT_TOKEN=<token-from-botfather>' \
  'RESEND_API_KEY=your-resend-key-here' \
  'EXA_API_KEY=change-me-please-now'
expect_pass "plantilla con valores vacíos (el siguiente renglón no cuenta), marcadores <así> y rellenos"
w short.env 'POSTGRES_PASSWORD=dev'
expect_pass "un valor corto (no es una clave generada)"
w src/client.py \
  'headers = {"x-apisports-key": settings.api_football_key}' \
  'API_FOOTBALL_KEY_FILE = "/run/secrets/api_football_key"'
expect_pass "la clave llega de la configuración o de un fichero, no está escrita"
w tests/test_auth.py \
  "TEST_AUTH_KEY = \"$(rnd_alnum 44)\"" \
  "SECRET = \"$(rnd_alnum 40)\"" \
  "payload = {\"password\": \"$(rnd_alnum 16)\"}"
expect_pass "las constantes fijas de las suites de pruebas (carpeta tests/, solo con esos nombres)"
w README.md 'Texto normal, sin nada que esconder: la clave se pide al proveedor y se guarda en el gestor de contraseñas.'
expect_pass "texto normal"
w tests/unit/test_redact.py "URL = \"postgresql://fbi:$(rnd_alnum 12)@localhost:5433/fbi\""
expect_pass "URL de prueba con contraseña de mentira y host local, en tests/ (ensayo de redacción de registros)"
w deploy/urls.env \
  'FBI_DATABASE_URL=postgresql+psycopg://fbi:${POSTGRES_PASSWORD}@db:5432/fbi' \
  'FBI_DATABASE_URL_RO=postgresql+psycopg://fbi_ro@db:5432/fbi' \
  'REDIS_URL=redis://localhost:6379/0' \
  'HC_URL=https://hc-ping.com/<uuid-de-healthchecks>' \
  'HC_URL_VACIA=https://hc-ping.com/00000000-0000-0000-0000-000000000000'
expect_pass "URLs con \${VAR}, sin contraseña, marcadores y el uuid de relleno"
w setenv_ok.ps1 '$env:FBI_AUTH_SECRET_KEY = $env:SECRETO_DEL_GESTOR' '$env:POSTGRES_PASSWORD = (Get-Content $ruta)'
expect_pass "PowerShell que toma el valor de otra variable o de un fichero"
w allowed.py "API_FOOTBALL_KEY = \"$LOWE\"  # gitleaks:allow - valor de ejemplo de la documentación"
expect_pass "una sola línea marcada con # gitleaks:allow y su motivo"

echo
echo "3) SKIP_GITLEAKS y GITLEAKS_REQUIRED"
w skip.env "POSTGRES_PASSWORD=$(rnd_alnum 24)"
SKIP_GITLEAKS=1
export SKIP_GITLEAKS
commit_try
unset SKIP_GITLEAKS
if [ "$RC" -eq 0 ] && printf '%s' "$OUT" | grep -q "SKIP_GITLEAKS=1"; then ok "SKIP_GITLEAKS=1 omite el escaneo a propósito y lo dice"; else bad "SKIP_GITLEAKS=1 no se porta como debe (salida $RC)"; fi
w noscan.env "POSTGRES_PASSWORD=$(rnd_alnum 24)"
mkdir -p "$T/sin_guarda"
PREDIGOL_GUARD_DIR="$T/sin_guarda"
export PREDIGOL_GUARD_DIR
commit_try
if [ "$RC" -eq 0 ] && printf '%s' "$OUT" | grep -q "NO se ha escaneado"; then ok "si el escáner no puede correr, avisa claramente y deja pasar"; else bad "escáner caído: no avisó o bloqueó (salida $RC)"; fi
w noscan2.env "POSTGRES_PASSWORD=$(rnd_alnum 24)"
GITLEAKS_REQUIRED=1
export GITLEAKS_REQUIRED
commit_try
unset GITLEAKS_REQUIRED
if [ "$RC" -ne 0 ]; then ok "GITLEAKS_REQUIRED=1 bloquea cuando el escáner no puede correr"; else bad "GITLEAKS_REQUIRED=1 no bloqueó"; fi
back_to_head
PREDIGOL_GUARD_DIR="$GUARD"
export PREDIGOL_GUARD_DIR

echo
echo "4) scan.sh ve lo que el hook no vio"
SCANSH="$GUARD/security/scan.sh"
w late.env "POSTGRES_PASSWORD=$(rnd_alnum 24)"
git add -A > /dev/null 2>&1
git commit -q --no-verify -m "se salta el hook" > /dev/null 2>&1
sh "$SCANSH" range HEAD~1 HEAD > /dev/null 2>&1
rc=$?
if [ "$rc" -eq 1 ]; then ok "scan.sh range encuentra el secreto del commit hecho con --no-verify"; else bad "scan.sh range no lo encontró (salida $rc)"; fi
sh "$SCANSH" history > /dev/null 2>&1
rc=$?
if [ "$rc" -eq 1 ]; then ok "scan.sh history encuentra el secreto"; else bad "scan.sh history no lo encontró (salida $rc)"; fi
sh "$SCANSH" range HEAD HEAD > /dev/null 2>&1
rc=$?
if [ "$rc" -eq 0 ]; then ok "un rango vacío da limpio (salida 0)"; else bad "un rango vacío no dio 0 (salida $rc)"; fi
sh "$SCANSH" range no_existe_1 no_existe_2 > /dev/null 2>&1
rc=$?
if [ "$rc" -eq 2 ]; then ok "un rango que no existe NO da limpio (salida 2)"; else bad "un rango que no existe dio salida $rc (debe ser 2)"; fi

echo
TOTAL=$((PASS + FAIL))
if [ "$FAIL" -eq 0 ]; then
  echo "selftest: $PASS de $TOTAL comprobaciones bien - la red de Gitleaks se porta como debe"
  exit 0
fi
echo "selftest: FALLAN $FAIL de $TOTAL comprobaciones - no te fíes del hook hasta arreglarlo (security/README.md)" >&2
exit 1
