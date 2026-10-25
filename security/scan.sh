#!/bin/sh
# PrediGol — Gitleaks con la configuración del monorepo (plan de seguridad, R07). Los valores NUNCA se imprimen (--redact=100).
#
#   security/scan.sh staged             lo que está en el índice (lo que usa el hook de pre-commit)
#   security/scan.sh history            todo el historial de todas las ramas y etiquetas
#   security/scan.sh range <base> <head>  los commits de base..head (la puerta de un lanzamiento)
#
# Salida: 0 limpio · 1 hay hallazgos · 2 el escáner no pudo mirar (nunca es luz verde).
# GITLEAKS_BIN=<ruta> elige el binario (si no, el del PATH y, al final, security/bin/ de la carpeta de la guarda); GITLEAKS_REPORT=<fichero.json> guarda el informe
# (redactado) de history y range. PREDIGOL_GUARD_DIR=<carpeta> dice dónde están .gitleaks.toml, .gitleaksignore y security/GITLEAKS_VERSION cuando no es el
# propio repositorio (el portátil del dueño usa una copia de la guarda para clones que aún no la tienen); por defecto es la raíz del repo.
set -u
MODE=${1:-}
ROOT=$(git rev-parse --show-toplevel 2> /dev/null) || { echo "scan.sh: no estoy dentro de un repositorio git" >&2; exit 2; }
GUARD=${PREDIGOL_GUARD_DIR:-$ROOT}
CONFIG="$GUARD/.gitleaks.toml"
IGNORE="$GUARD/.gitleaksignore"
[ -f "$CONFIG" ] || { echo "scan.sh: falta $CONFIG" >&2; exit 2; }
BIN=${GITLEAKS_BIN:-}
if [ -z "$BIN" ] || [ ! -x "$BIN" ]; then BIN=$(command -v gitleaks 2> /dev/null || command -v gitleaks.exe 2> /dev/null || true); fi
if [ -z "$BIN" ] || [ ! -x "$BIN" ]; then
  for c in "$GUARD/security/bin/gitleaks" "$GUARD/security/bin/gitleaks.exe"; do [ -x "$c" ] && BIN=$c && break; done
fi
if [ -z "$BIN" ] || [ ! -x "$BIN" ]; then
  echo "scan.sh: no encuentro gitleaks (pon GITLEAKS_BIN o ponlo en el PATH; security/README.md, «Instalar»)" >&2
  exit 2
fi
WANT=$(sed -n 's/^version=//p' "$GUARD/security/GITLEAKS_VERSION" 2> /dev/null | head -n 1)
GOT=$("$BIN" version 2> /dev/null | tr -d '\r' | head -n 1)
case "$GOT" in [0-9]*) [ -z "$WANT" ] || [ "$GOT" = "$WANT" ] || echo "scan.sh: aviso, gitleaks es $GOT y el fijado es $WANT" >&2 ;; esac
BASE=${2:-}
HEADREF=${3:-}
case "$MODE" in
  staged) set -- git --pre-commit --staged ;;
  history) set -- git ;;
  range)
    [ -n "$BASE" ] && [ -n "$HEADREF" ] || { echo "uso: scan.sh range <base> <head>" >&2; exit 2; }
    # un rango que no existe no debe dar «limpio»: gitleaks saldría con 0 sin haber mirado nada
    git rev-parse --verify --quiet "$BASE^{commit}" > /dev/null && git rev-parse --verify --quiet "$HEADREF^{commit}" > /dev/null \
      || { echo "scan.sh: $BASE o $HEADREF no son commits de este repositorio" >&2; exit 2; }
    set -- git "--log-opts=$BASE..$HEADREF"
    ;;
  *)
    echo "uso: scan.sh staged | history | range <base> <head>" >&2
    exit 2
    ;;
esac
# un clon superficial no tiene todo el historial: no se puede decir «limpio»
if [ "$MODE" != staged ] && [ "$(git rev-parse --is-shallow-repository 2> /dev/null)" = true ]; then
  echo "scan.sh: este clon es superficial (shallow); el escaneo del historial sería incompleto (git fetch --unshallow)" >&2
  exit 2
fi
REPORT=""
if [ -n "${GITLEAKS_REPORT:-}" ] && [ "$MODE" != staged ]; then REPORT="--report-format=json --report-path=$GITLEAKS_REPORT"; fi
# shellcheck disable=SC2086
"$BIN" "$@" --redact=100 --no-banner --log-level=warn -v --exit-code=42 -c "$CONFIG" -i "$IGNORE" $REPORT "$ROOT"
rc=$?
case $rc in
  0) exit 0 ;;
  42) exit 1 ;;
  *)
    echo "scan.sh: gitleaks no pudo correr (salida $rc)" >&2
    exit 2
    ;;
esac
