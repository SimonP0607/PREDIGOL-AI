# PrediGol en un VPS: web + PWA, 24/7

Kit preparado y ensayado el 7 oct 2026 con los datos reales (saneados) del portátil. **No se ha contratado ni
publicado nada.** Lo que cuesta dinero o expone la plataforma (servidor, dominio, R2, Cloudflare, avisos) lo decide y
lo contrata el dueño (§2).

## 1. Qué corre en el servidor

```
Usuario ──HTTPS──▶ Cloudflare (DNS, proxy, TLS, anti-bots; solo cachea estáticos)
                     └──▶ Caddy :443 (certificado; cabeceras de seguridad; IP real del cliente; 1 MB por petición)
                            ├── /api/*, /health ──▶ api    FastAPI, 2 procesos, 8 conexiones de lectura cada uno
                            └── el resto ────────▶ web    Node: la app y la PWA
                     worker (uno solo) ──HTTPS──▶ API-Football
                     postgres 16 + pgBackRest ──WAL continuo, cifrado──▶ Cloudflare R2 (PITR)
                     copias diarias (pg_dump) ──age──▶ R2        RAW ──rclone, solo añade──▶ R2

/srv/predigol/   pgdata · raw · backups/db · pgbackrest-spool · caddy · state
/etc/predigol/   predigol.env (servidor) · app.env (aplicación) · origin/ (certificado de origen)   root, 600
```

* Un `docker compose` (`docker-compose.yml`): PostgreSQL 16 con pgBackRest, API, worker, web y Caddy.
* Cada servicio se reinicia solo si se cae. systemd levanta el conjunto al arrancar la máquina, comprueba que volvió
  y avisa.
* **Roles de la base, cada uno con su contraseña** (`db/grants.sql`):

  | Rol | Uso |
  |---|---|
  | `postgres` | solo el operador, dentro del contenedor |
  | `fbi` | dueño de los datos: migraciones, copias, mantenimiento |
  | `predigol_worker` | el worker: lee y escribe datos; nada de cuentas ni de esquema |
  | `predigol_api` | la API: lee; escribe solo cuentas, registros del usuario y la consola |

  Ningún servicio usa un superusuario.

**Servidor recomendado: Contabo Cloud VPS 6** (6 vCPU, 12 GB, 200 GB SSD, US Central). Los motivos, los precios y
las alternativas están en `docs/owner/INFRA_DECISION_2026-10-07.md`.

* Base de datos: 8,4 GB, 49,8 millones de filas y 117 tablas. RAW: 0,8 GB y 81.739 ficheros.
* Crece ≈ 0,14 GB/día: ≈ 75–80 GB en el servidor a 12 meses y ≈ 130 GB a 24.

## 2. Lo que decide y contrata el dueño

| Qué | Para qué | Coste (7 oct 2026) |
|---|---|---|
| Contabo Cloud VPS 6, US Central, Ubuntu 24.04, **pago mensual** | todo PrediGol | $11,00/mes ($9,20 con 24 meses) |
| Dominio | la dirección pública | ≈ $11/año |
| Cloudflare Free | DNS, proxy, TLS, anti-bots y DDoS | $0 |
| Cloudflare R2 (un bucket, tres tokens: copias, PITR y lectura) | PITR, copias cifradas y RAW fuera del servidor | 10 GB gratis, luego $0,015/GB-mes |
| Una clave `age` (la genera el dueño y guarda la privada) | cifrar las copias antes de salir | $0 |
| Healthchecks.io, UptimeRobot, Sentry Developer, bot de Telegram | avisos | $0 |
| API-Football Ultra | los datos | ya se renueva sola |

`SECURITY_ACTION: la rotación de la clave de API-Football está en el plan de seguridad (paquete S1.d): se hace con el dueño presente, y no a mano.`
Cómo se rota cada secreto: `docs/owner/SECRETS_AND_ROTATION.md`.

## 3. Instalación (≈ 1,5 horas)

1. **Medir la máquina, antes de nada.** Por SSH con llave:
   ```
   git clone -b feature/predigol-ux-rbac /root/backend.bundle /opt/predigol/backend    # bundles: paso 3
   sudo /opt/predigol/backend/deploy/vps/bin/bench.sh --out /root/bench-dia1.json
   ```
   Mide CPU (y el *steal* bajo carga), disco 4k, fsync, RAM y red, unos 6 minutos. Si sale **FAIL**, se cancela el
   contrato mensual y se pasa al plan B (Cloud VPS Plus 4 u OVH VPS-3).
2. **Acceso.** Entra por SSH con llave, no con contraseña. Cuando la llave funcione, pon `PasswordAuthentication no`.
3. **Código, sin GitHub.** Los dos repositorios viajan como bundles git desde el portátil:
   ```
   # portátil
   git -C ~/projects/football-intelligence-v2 bundle create /tmp/backend.bundle feature/predigol-ux-rbac
   git -C ~/projects/football-intelligence-hub bundle create /tmp/web.bundle feature/predigol-ux-rbac
   scp /tmp/backend.bundle /tmp/web.bundle root@SERVIDOR:/root/
   # servidor
   git clone -b feature/predigol-ux-rbac /root/web.bundle /opt/predigol/web
   ```
4. **Preparar la máquina.** `sudo /opt/predigol/backend/deploy/vps/bin/install.sh` instala:
   * Docker oficial, el cortafuegos (SSH, 80, 443), fail2ban y las actualizaciones de seguridad;
   * 4 GB de swap; jq, age, rclone y openssl; las carpetas de `/srv/predigol`;
   * los dos ficheros de ajustes con **todas las contraseñas y claves generadas** (nadie las teclea);
   * límites de CPU a la medida de la máquina; los servicios y temporizadores de systemd; `predigolctl`.

   Copia de `/etc/predigol/*.env` a tu gestor de contraseñas: las de la base, `PITR_CIPHER_PASS` (sin ella no se
   puede leer el PITR) y `FBI_AUTH_SECRET_KEY`.
5. **Ajustes.**
   * `predigol.env`: dominio, R2 para el PITR (`PITR_S3_*`), copias (`BACKUP_RCLONE_REMOTE`,
     `BACKUP_AGE_RECIPIENT`, `RAW_RCLONE_REMOTE`, tras `rclone config`), Healthchecks (`HC_PING_*`).
   * `app.env`: la clave de API-Football y el bot de Telegram.
   * Desde el portátil, sin teclear ni mostrar ningún valor: `deploy/cutover/push-app-env.sh predigol` copia al
     `app.env` del servidor lo que ya existe en el `.env` del portátil: API-Football (clave, plan, presupuesto),
     las ventanas de captura de cuotas, `FBI_AUTH_SECRET_KEY` (los autenticadores de las cuentas siguen valiendo
     tras el corte) y la capa de IA (`FBI_AI_*`, `EXA_API_KEY`). Solo muestra los nombres.
   * Sin dominio todavía: ver §3 bis.
6. **Cloudflare.**
   * Registros `A`/`AAAA` del dominio con proxy (naranja). SSL/TLS en **Full (strict)**.
   * Certificado de origen de Cloudflare en `/etc/predigol/origin/` y `PREDIGOL_TLS_MODE=origin`. Sin él, Caddy usa
     Let's Encrypt, que necesita el proxy apagado al emitir.
   * `predigolctl cloudflare trust` (la IP real del cliente viene de Cloudflare) y `predigolctl cloudflare firewall`
     (80/443 solo desde Cloudflare).
   * Caché: solo estáticos. Nunca `/api/*`.
7. **Datos.** Si vienen del portátil, el corte (§4) va **antes** del primer despliegue.
8. **Arrancar.** `predigolctl deploy`: construye con la versión exacta del código, copia previa, migra, aplica
   permisos, arranca y espera a que todo esté sano.
9. **PITR.** `predigolctl pitr init && predigolctl pitr backup`. Tras un corte ya lo hace `import`.
10. **Cuenta del dueño.**
    ```
    predigolctl create-user --email TU@CORREO --role SUPER_ADMIN --name "Tu nombre"
    ```
    * La contraseña queda en `/root/predigol-credentials/<correo>.txt` (600). Guárdala y borra el fichero.
    * En el primer inicio de sesión la app pide la verificación en dos pasos: escanea el QR con la app
      autenticadora y guarda los 10 códigos de recuperación. Es obligatoria para SUPER_ADMIN.
11. **Comprobar.** `predigolctl status` y `predigolctl health`; `https://DOMINIO/health` dice `"ok"`; la PWA se
    instala en Android y en iPhone (§10).
12. **Avisos.** Healthchecks.io: un check por tarea (`HC_PING_*`). UptimeRobot vigila `https://DOMINIO/health` y
    busca `"ok"`. Telegram: el bot de avisos del servidor (`PREDIGOL_ALERT_BOT_TOKEN` y `PREDIGOL_ALERT_CHAT_ID` de
    `predigol.env`, siempre los dos); si faltan, se usa el de la aplicación (`FBI_TELEGRAM_BOT_TOKEN` y
    `FBI_TELEGRAM_CHAT_ID` de `app.env`). `predigolctl alert-test` comprueba que llega y dice qué bot lo envió. Sentry
    (errores de la API y del worker, sin datos personales): el DSN de un proyecto en `FBI_SENTRY_DSN` de `app.env`.
    Cómo se ensaya cada aviso, uno a uno y sin que el problema sea cierto: `docs/owner/SIMULACROS_AVISOS.md`.

## 3 bis. Sin dominio todavía (solo la IP)

Se puede montar, ensayar y hacer el corte antes de tener dominio:

* `predigol.env`: `PREDIGOL_DOMAIN=<IPv4 del servidor>` y `PREDIGOL_TLS_MODE=internal`.
* Caddy firma el certificado de esa IP con su propia autoridad (`caddy/tls-internal.caddy`). El monitor, el humo de
  `release.sh` y la prueba de carga confían en esa raíz (`$PREDIGOL_DATA/caddy/data/caddy/pki/authorities/local/
  root.crt`).
* El navegador avisa ("no es privada") hasta que se confíe en esa raíz. La PWA y el acceso público necesitan el
  dominio.
* El día del dominio: `PREDIGOL_DOMAIN=dominio`, `PREDIGOL_TLS_MODE=acme` (o `origin` con Cloudflare) y
  `predigolctl deploy`. La web se reconstruye con su nueva dirección y las sesiones abiertas por IP dejan de valer.

## 4. Corte desde el portátil, sin dos workers a la vez

Fuera de partidos en juego y con el ensayo del servidor en verde (§11). Si el servidor tuvo un ensayo con datos, se
vacía antes: `predigolctl stop` y se borran `pgdata` y `raw` de ese ensayo. `import` solo escribe en una base vacía.

1. **Portátil: mantenimiento y parar el worker.** `scripts/dev-down worker`. Desde aquí el portátil no captura.
   Nunca puede haber dos workers encendidos: cada uno tendría su base, gastarían cuota y divergirían.
2. **Portátil: la copia final.** `deploy/cutover/export.sh` (en WSL, desde el backend).
   * Se niega si el worker sigue vivo o latió hace menos de 2 minutos.
   * Deja la marca `~/.fbi/worker-moved-to-server`: desde ese momento `scripts/dev-up` no arranca un worker en el
     portátil (ni tras un reinicio).
   * Cuenta cada tabla antes y después.
   * Hace `pg_dump` dentro del contenedor y empaqueta el RAW.
   * Escribe `~/cutover/<fecha>/` con `db.dump`, `raw.tar`, `manifest.json` y `SHA256SUMS`.
3. **Copiar al servidor.** `scp -r ~/cutover/<fecha> root@SERVIDOR:/root/import/`.
4. **Servidor: importar.** `predigolctl import /root/import/<fecha>`.
   * Antes de tocar nada comprueba los sha256 y que la base esté vacía.
   * Restaura como `fbi`, aplica los permisos y compara **cada** tabla con el manifiesto.
   * Extrae el RAW sin sobrescribir y cierra todas las sesiones del portátil.
   * Con PITR configurado, crea el *stanza* y una copia completa: la ventana de recuperación empieza ahí.
5. **Servidor: arrancar.** `predigolctl deploy` migra desde la revisión importada y arranca el worker. Su catch-up,
   anclado al ledger, recupera lo que vencía mientras tanto.
6. **Comprobar.** `predigolctl status`, la página System de la consola, `predigolctl backup` y la primera captura en
   vivo.
7. **DNS.** Ahora, no antes: el dominio apunta al servidor (proxy de Cloudflare). Prueba desde fuera, desde la PWA en
   Android y en iPhone, y que solo hay un worker latiendo (`raw.worker_heartbeats`).
8. **Cuentas.** Pasadas las pruebas:
   * las de QA, apagadas: `predigolctl accounts disable --domain predigol.local --confirm`;
   * el dueño elige una contraseña nueva al entrar (`predigolctl accounts require-password-change --email TU@CORREO`)
     y configura su segundo factor.
9. **Portátil.** Queda 7 días como respaldo frío, con el worker parado.

Vuelta atrás: mientras no se borre nada en el portátil, con el worker del servidor parado (`predigolctl stop`),
se borra la marca (`rm ~/.fbi/worker-moved-to-server`), se enciende allí el worker (`scripts/dev-up worker`) y se
devuelve el DNS. El servidor se vacía y se repite.

## 5. Operación diaria

| Comando | Qué hace |
|---|---|
| `predigolctl status` / `health` | contenedores, versiones y veredicto del monitor / el monitor, ahora |
| `predigolctl logs worker` | logs en vivo de un servicio |
| `predigolctl backup` / `restore-test` | copia / prueba de restauración, ahora |
| `predigolctl pitr status\|backup\|verify\|test` | el repositorio PITR |
| `predigolctl secrets-export` | los secretos del servidor en un fichero cifrado con la clave pública del dueño; no imprime ningún valor |
| `predigolctl alert-test` | un mensaje de prueba a tu Telegram, por el mismo camino que usan los avisos; dice qué bot lo envió y no imprime ningún token |
| `predigolctl alert-drill --list\|KEY\|--all\|--healthchecks NAME\|--evidence` | un simulacro: el mensaje de un aviso (o de todos) a tu Telegram por el bot de verdad, sin que el problema sea cierto; lo lanza la sesión en la ventana y tú miras el teléfono (`docs/owner/SIMULACROS_AVISOS.md`) |
| `predigolctl sentry-drill` | UN error inventado a Sentry, con los ajustes de la API, para ver llegar el aviso de «excepción nueva»; no imprime el DSN |
| `predigolctl config-baseline [--status]` | toma la línea base del aviso «cambió la configuración» (solo huellas; imprime los nombres de los ficheros que mueve); `--status` no cambia nada |
| `predigolctl incident list\|show\|note\|severity\|open\|close …` | el registro de incidentes: la causa, los usuarios afectados, el cierre (`docs/owner/GUIAS_RESPUESTA_INCIDENTES.md`) |
| `predigolctl accounts list\|unlock\|mfa-reset\|revoke-sessions …` | cuentas, desde la terminal |
| `predigolctl maint` | particiones por delante y retención de restos, con copia verificada |
| `predigolctl psql` | consola de la base en solo lectura |
| `predigolctl stop` / `up` | parar o levantar el conjunto; no se pierde nada |

Temporizadores (`systemctl list-timers 'predigol*'`):

| Tarea | Cuándo |
|---|---|
| monitor | cada 5 min |
| avisos de seguridad (inicios de sesión, cuentas, 401 y 403 del panel) | cada 5 min |
| copia del registro de incidentes a la base | cada 10 min |
| resumen semanal de incidentes | lunes 13:11 UTC (08:11 en Bogotá) |
| PITR: copia completa el domingo, diferencial el resto | 03:30 UTC |
| copia `pg_dump` cifrada fuera | 04:15 UTC |
| mantenimiento (particiones, retención) | 05:30 UTC |
| prueba de restauración del volcado | lunes 06:00 UTC |
| verificación del repositorio PITR | miércoles 05:00 UTC |
| prueba real de PITR (restaurar a un punto en un servidor desechable) | primer martes del mes, 06:00 UTC |
| RAW fuera del servidor | cada hora, minuto :20 |

El monitor revisa:

* contenedores (también los que se reinician en bucle), HTTPS, el latido del worker (lo reinicia como mucho una vez por hora) y la captura en vivo;
* disco (aviso al 85 %) y su previsión, memoria, swap, carga, *steal* de CPU, conexiones de la base;
* el archivo de WAL, la edad de las copias, la verificación y la prueba del PITR;
* la cuota de API-Football, ejecuciones atascadas o fallidas, errores 5xx, el certificado;
* que `/api/v1/auth/me` sin sesión conteste 401 y los resultados que llevan horas sin liquidarse;
* que el Caddyfile, compose, los ficheros de entorno, la configuración de `sshd` y las unidades de systemd del kit sigan
  como en su línea base (`state/config.sha256`, solo huellas). La toman solos `predigolctl deploy` y `rollback` al
  terminar; a mano, como último paso de un cambio a mano, `predigolctl config-baseline` (con `--status` solo mira y
  nombra los ficheros que difieren). Hasta que se toma la primera, ese aviso calla.

Avisa solo cuando cambia el estado: UN mensaje al abrirse un problema (`[SEV1] clave: texto (INC-2026-014)`), un
recordatorio cada hora mientras un SEV1 siga abierto y UN mensaje de «recuperado» al cerrarse. Los 502 de un despliegue o de
una vuelta atrás no cuentan. Cada problema es un incidente del registro (`state/incidents.jsonl`, que el temporizador de 10
minutos copia a `audit.incident_events`, para que viaje en las copias de la base). `security-alerts.sh` suma lo que sale de la
auditoría de la aplicación y del registro de Caddy: picos de inicios de sesión fallidos, cuentas en espera, un administrador
desde un dispositivo nuevo, cambios de rol o de contraseña de otra cuenta y picos de 401 y 403 en las rutas de administración.
Un aviso que no puede evaluarse (la base no contesta) no cierra los que ya estaban abiertos. La lista completa y qué hacer
ante cada uno: `docs/owner/GUIAS_RESPUESTA_INCIDENTES.md`.

## 6. Actualizar y volver atrás

Desde el portátil, una orden: `deploy/release.sh --host predigol` (un host de `~/.ssh/config`).

1. Exige los dos repositorios limpios y empujados a sus repositorios bare locales.
2. Pasa las puertas: ruff, mypy, pytest, lint, typecheck, tests y build de la web.
3. Empaqueta los bundles con sha256 y los lleva por SSH.
4. En el servidor pone exactamente esos commits y ejecuta `predigolctl deploy`.
5. Hace las pruebas de humo: `/health`, `/login`, HSTS, `/api/v1/auth/me` → 401, `/docs` → 404.

`predigolctl deploy`:

* hace una copia `pre-deploy`;
* migra con 5 intentos. Si falla, no toca lo que está en marcha;
* recrea solo lo que cambió. La base solo se reinicia si cambió su imagen;
* espera a que todo esté sano y pasa el monitor.

**Un cambio en `Caddyfile` o en `caddy/` no se aplica solo.** `predigolctl deploy` no recrea Caddy: el compose monta `./Caddyfile` como un solo
fichero, `git checkout` lo sustituye por otro con otro inodo y el contenedor sigue viendo el viejo. Tras ese despliegue: validar el fichero nuevo
(`caddy validate` con la imagen que corre), `compose up -d --no-deps --force-recreate caddy` y comprobar que el sha256 de `/etc/caddy/Caddyfile`
dentro del contenedor es el del checkout (detalle en `docs/security/R02_SERVER_FUNCTIONS.md`, «Cómo se despliega»).

`predigolctl rollback` arranca la versión anterior en segundos (sus imágenes se conservan). La base **no** se baja
de versión sola; si la versión anterior necesita el esquema anterior, se decide con el dueño (`alembic downgrade` o
la copia `pre-deploy`).

## 7. Copias y desastres

| Capa | Qué | Retención |
|---|---|---|
| PITR (pgBackRest → R2) | WAL continuo (máx. 5 min de retraso) + completa semanal y diferencial diaria, cifrado AES-256 | 4 completas (≈ 4 semanas) |
| Volcado diario | `pg_dump` leído entero, sha256, recuentos; fuera cifrado con `age` | servidor: 3 días + 2 semanas; R2: 14 días, 8 domingos, 12 primeros de mes (los caduca el cubo, no el servidor) |
| RAW | `rclone copy --immutable`: solo añade, nunca modifica ni borra fuera | indefinida |

Pruebas automáticas: el volcado se restaura cada lunes en un PostgreSQL sin red; el PITR se verifica cada miércoles y
se restaura de verdad a un punto cada mes.

### Copias fuera del servidor (R2)

Un solo cubo (`predigol-backups`), con carpetas que se bloquean y caducan cada una a su manera. R2 no tiene el Object Lock
de S3: tiene *bucket locks* por prefijo, que impiden borrar y sobrescribir hasta que vence el plazo, y reglas de caducidad
que borran después. Las pone el dueño (quitarlas exige un token de administración que **no está en el servidor**).

| Prefijo | Qué | Bloqueo | Caduca |
|---|---|---|---|
| `dumps/daily/` | todo volcado: el del temporizador y el previo a cada despliegue | 14 días | día 15 |
| `dumps/weekly/` | el del temporizador de un domingo | 8 semanas | día 57 |
| `dumps/monthly/` | el del temporizador del día 1 | 12 meses | día 396 |
| `raw/` | el RAW, con su misma ruta (`api-football/AAAA/MM/DD/…`) | indefinido | nunca |
| `audit/` | (fase S8) | 12 meses | día 396 |
| `pitr/` | pgBackRest | **ninguno**: pgBackRest borra sus copias caducadas | lo hace él |
| `_probe/` | pruebas de `r2-setup.sh` | ninguno | — |

`bin/offsite-tiers.sh` decide los niveles de un volcado solo por su nombre. `backup.sh` cifra con la clave **pública**
`age`, sube a cada nivel, comprueba el tamaño allí y solo entonces marca la copia como verificada
(`offsite.verified_at` en su `.json`); **nunca borra nada fuera** (el candado lo rechazaría) y avisa si encuentra una copia
mucho más vieja que su nivel (falta la regla de caducidad). El `.json` que viaja con el volcado lleva el sha256 del fichero
cifrado: quien lo baja lo prueba antes de descifrar.

En el servidor, un volcado cuya copia nunca se verificó se conserva aunque las reglas de rotación lo soltarían (puede ser el
único), pero solo mientras ningún volcado **más nuevo** haya llegado al cubo y solo los `BACKUP_KEEP_UNVERIFIED` (6) más
recientes: un cubo inalcanzable durante semanas no puede llenar el disco con volcados de 1,4 GB (el aviso salta a las 26 h).

Puesta en marcha (una vez; el dueño ha creado antes el cubo, los dos tokens —«copias» y «PITR», ambos *Object Read & Write*
solo sobre ese cubo—, los bloqueos y las reglas, y su par `age` en su portátil):

1. `/root/r2.env` (600): `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET`, `AGE_RECIPIENT`
   (y, para S2b, `R2_PITR_ACCESS_KEY_ID`, `R2_PITR_SECRET_ACCESS_KEY`). Nunca la clave privada: el script la rechaza.
2. `bin/r2-setup.sh /root/r2.env --check-only`: configura rclone (fichero 600, sin claves en la línea de órdenes), prueba el
   cubo y **prueba los candados**. Sin `--check-only`, además escribe `BACKUP_RCLONE_REMOTE=r2:<cubo>`,
   `BACKUP_AGE_RECIPIENT` y `RAW_RCLONE_REMOTE=r2:<cubo>/raw` en `predigol.env` (copia `.before-r2-<fecha>`), hace un
   volcado `r2-first` y descarga su hash.
3. Primera pasada del RAW (unos 290 000 ficheros, 2,5 GB): `RAW_SYNC_TRANSFERS=16 predigolctl raw-sync --full`. Después
   `raw-sync.sh` corre cada hora y solo mira las carpetas de **hoy y ayer** (UTC) de cada proveedor, porque el almacén
   escribe `<proveedor>/AAAA/MM/DD/` por el día de la captura: así lo que cobra R2 por listar no crece con la edad del
   almacén (rclone lista el destino una vez por carpeta, y el almacén gana ~12 000 ficheros al día). Una vez al día
   (`RAW_SYNC_FULL_HOURS`, 24) hace una pasada **completa**, la red de seguridad para lo que aparezca en otro sitio (una
   importación de un almacén antiguo). Una pasada que sigue en marcha cuando toca la siguiente no es un fallo: la
   siguiente se salta. Deja `state/raw-sync.json` (cuándo, de qué tipo, cuándo fue la última completa, cuántos ficheros y
   cuántos vacíos de los últimos 7 días); si una pasada falla, su registro queda en `state/raw-sync.last-failure.log`.
4. `bin/r2-lock-check.sh [--tier daily|weekly|monthly|raw]`: sube un fichero de prueba a cada prefijo e intenta borrarlo y
   sobrescribirlo; ambas cosas deben fallar. Corre solo cada domingo con el volcado semanal; `state/lock-check.json` lo lee
   `healthcheck.sh` (un fallo es **problema**). Los ficheros de prueba se quedan hasta que vence su candado.
5. En el portátil del dueño (la clave privada no sale de allí): `bin/r2-restore-drill.sh r2.env age.key [--tier weekly]`
   baja el último volcado del nivel, prueba su hash, lo descifra, lo restaura en un PostgreSQL sin red y compara versión
   y recuentos. Imprime y guarda en un JSON el tiempo de cada fase (descarga, descifrado, arranque, carga, restauración y
   verificación): es el RTO medido. Con `--save-encrypted CARPETA` deja además allí el volcado **cifrado** y su manifiesto
   (lo que se copia al disco externo para la copia mensual sin conexión); el volcado en claro no sale del contenedor. El
   volcado entra en el contenedor como un flujo `tar` (`docker cp -`), no como un montaje de carpeta, así que sirve cualquier
   `docker`, también el de Windows visto desde WSL, donde un montaje de una carpeta de WSL no llega al motor.

`healthcheck.sh` vigila: el último volcado verificado fuera tiene menos de 26 h, el RAW se sincronizó hace menos de 3 h
(aviso) o 12 h (problema), la última pasada completa del RAW tiene menos de 36 h (aviso) o 5 días (problema), no hay
ficheros vacíos nuevos en el RAW y los candados se probaron hace menos de 10 días.

### Copia de los secretos

Sin `PITR_CIPHER_PASS` el repositorio PITR no se puede leer, y sin `FBI_AUTH_SECRET_KEY` los secretos TOTP de las cuentas no
se pueden descifrar; ninguna de las dos está en otra copia. `predigolctl secrets-export` empaqueta `predigol.env`, `app.env` y
la configuración de rclone en **un solo fichero**, cifrado con la clave **pública** `age` del dueño (`BACKUP_AGE_RECIPIENT`):

```
predigolctl secrets-export                  /root/secrets-<fecha>.tar.age (600)
predigolctl secrets-export --out DIR        en otra carpeta
```

No imprime ningún valor ni su hash, y no escribe nunca una copia en claro en el disco (`tar` va directo a `age`). Dentro lleva
un `MANIFEST.txt` con los **nombres** de los ajustes (cuáles tienen valor y cuáles están vacíos) y las rutas que tienen en el
servidor. Sin la clave privada, que solo está en el portátil y en el gestor del dueño, el fichero es ruido: puede viajar,
guardarse en el gestor como adjunto e ir a la copia sin conexión. Se copia al portátil, se guarda y **se borra del servidor**
(lo que contiene ya está en claro en el servidor: dejarlo no protege nada). Se repite cada vez que se rota un secreto.
Para abrirlo, en el portátil: `age -d -i clave.txt secrets-<fecha>.tar.age > secrets.tar` y `tar -xf secrets.tar`; los
ficheros salen bajo `bundle/` con las rutas del servidor. Ninguna restauración exige teclear un valor.

### Podar Docker

Cada despliegue construye imágenes de ~1 GB y la caché de construcción crece. `bin/prune.sh` (`predigolctl prune
[--dry-run]`; `deploy` lo ejecuta al terminar) conserva siempre las imágenes que usa algún contenedor, las de
`state/versions.env`, las de los tres últimos despliegues —nuevas **y anteriores**: `predigolctl rollback` las necesita— y
las tres más recientes de cada servicio (dos de PostgreSQL); quita el resto, las imágenes huérfanas de más de 24 h y la
caché por encima de 4 GB. Nunca corre mientras un despliegue, una vuelta atrás o una importación tienen su cerrojo.

Los **volúmenes** no se podan por regla. `bin/prune.sh --volumes NOMBRE[,NOMBRE] --confirm` borra solo los que se nombran, y
solo si ninguno lo usa un contenedor, ninguno es del proyecto `predigol` y el último volcado tiene una copia verificada
fuera de menos de 26 h. Antes se inspecciona cada uno y el dueño ve la lista: lo borrado no vuelve.

Cada poda (también la de volúmenes; no la de `--dry-run`) deja constancia en `state/prune.json`:
`{"at": "<UTC ISO>", "freed_bytes": N, "items": ["image predigol-web:abc", "volume xyz", ...]}`, más el detalle (imágenes y
volúmenes quitados, porcentaje de disco antes y después). El informe de almacenamiento lo lee y la consola lo muestra como
«Última limpieza». `freed_bytes` es lo que baja el disco usado (`df`) durante la poda: es aproximado, porque otros procesos
escriben a la vez, y nunca es negativo. Un volumen que Docker no pudo quitar se dice en el registro, no entra en el fichero y
la salida es 1. Si no se puede escribir el fichero, `prune.sh` lo dice, no deja ningún temporal y sale con 1 (lo limpiado
sigue limpio; solo falta la constancia).

**Si se pierde la base o el servidor:**

1. Servidor nuevo y §3, pasos 1–6, con los **mismos** `PITR_*` y `PITR_CIPHER_PASS` (del gestor de contraseñas).
2. `predigolctl pitr recover --confirm` restaura desde R2 hasta el último WAL archivado, o hasta un momento:
   `--time "2026-10-08 12:00:00+00"`.
   * Si hay una carpeta de datos, la aparta (`pgdata.before-recover-<fecha>`); nunca la borra.
   * Arranca la base en una línea temporal nueva, levanta el resto y hace una copia completa.
3. RAW: `rclone copy r2:CUBO/raw /srv/predigol/raw --exclude '_lockcheck/**'` y `chown -R 1000:1000 /srv/predigol/raw`.
4. `predigolctl health`.

Sin PITR, el último volcado: se baja con rclone, se descifra con `age -d` en una máquina con la clave, y se usa
`predigolctl import` con su `manifest.json`.

Para recuperar solo unos datos (un borrado por error), `predigolctl pitr restore --time …` levanta una copia aparte
en `127.0.0.1:55432`, sin tocar la base en marcha.

## 8. Seguridad

* **Entrada:**
  * Cloudflare delante; el cortafuegos solo acepta 80/443 desde Cloudflare;
  * PostgreSQL, la API y la web no publican puertos;
  * 1 MB por petición en Caddy, 256 KiB en la API.
* **API:**
  * sin `/docs` ni `/openapi.json`; `/health` sin detalles;
  * cookie `__Host-predigol_session`: `Secure`, `HttpOnly`, `SameSite=Strict`;
  * CSRF: cabecera propia y comprobación de origen;
  * límites por IP, por cuenta y por inicio de sesión;
  * auditoría de cada escritura del Admin Console.
* **Cuentas:**
  * sin registro público: las crea el dueño;
  * segundo factor TOTP con QR y 10 códigos de recuperación, obligatorio para SUPER_ADMIN;
  * bloqueo progresivo tras 5 fallos; contraseña temporal que se cambia al entrar;
  * sesiones de 7 días (24 h para administradores) con caducidad por inactividad y revocación;
  * historial de accesos en Perfil → Seguridad.
* **Base de datos:** un rol por servicio y ninguno superusuario (§1).
* **Cabeceras:** HSTS de un año; CSP (este origen, Google Fonts y `media.api-sports.io`); sin incrustar.
* **Funciones de servidor de la web (R02):** en `/_serverFn/*` Caddy solo deja pasar una llamada de la propia app (cabecera `x-tsr-serverFn: true`,
  sin `Sec-Fetch-Mode: navigate`, sin pedir `text/html`); lo demás recibe un 403 vacío con CSP `default-src 'none'`. Es un filtro, no
  autenticación. Detalle y pruebas: `docs/security/R02_SERVER_FUNCTIONS.md`, `bin/serverfn-matrix.sh`, `bin/serverfn-probe.sh`.
* **Secretos:** solo en `/etc/predigol/*.env` (600), generados por `install.sh`; nada en imágenes, Git ni logs.
  Detalle: `docs/owner/SECRETS_AND_ROTATION.md`.

## 9. Reinicios y caídas

* Al arrancar la máquina, Docker devuelve los contenedores y `predigol.service` deja el conjunto en las versiones del
  último despliegue (también la de la imagen de la base). `predigol-post-boot.service` espera a que esté sano y avisa.
* PostgreSQL corre bajo `tini`. Si el repositorio PITR no responde, el WAL espera en cola (máx. 4 GiB) y el monitor
  avisa: la base no se reinicia por eso.
* El worker no pierde trabajo programado: el catch-up anclado al ledger rehace lo vencido. Lo que no se recupera son
  los ticks en vivo de los minutos sin máquina, porque `/odds/live` no guarda historia.
* Reinicio planificado: fuera de partidos en vivo, `reboot` y después `predigolctl status`.

## 10. La PWA

* **Instalar.** Android (Chrome): menú → "Instalar app". iPhone (Safari): Compartir → "Añadir a pantalla de inicio".
* **Qué guarda:** solo los archivos de la app. Nunca la API (cuotas, picks, en vivo, resultados, cuenta) ni una
  página. Sin conexión muestra "Sin conexión", nunca una copia vieja.
* **Actualizaciones controladas:** una versión nueva espera a que la persona pulse "Actualizar". Un despliegue nunca
  rompe una pestaña abierta: si faltan los archivos viejos, la página se recarga una vez.
* Notificaciones push: no incluidas.

## 11. Ensayo realizado (7 oct 2026)

En un sandbox de 2 vCPU con el mismo `docker-compose.yml`, el mismo `Caddyfile` y los **datos reales saneados**
del portátil (8,4 GB, 117 tablas, 49,8 millones de filas, 81.739 ficheros RAW; sin cuentas ni datos personales). Lo
que cambiaba (`rehearsal/`): el dominio `predigol.localhost` con la autoridad local de Caddy, un simulador vacío de
API-Football (sin clave ni peticiones) y un S3 local en lugar de R2.

| Prueba | Resultado |
|---|---|
| `export.sh` sobre una copia del "portátil" | OK: 117 tablas, 49.763.561 filas, nada cambió durante el volcado |
| `import`: sha256, restauración como `fbi`, cada tabla comparada, RAW, sesiones, stanza + copia completa PITR | OK en 5 min |
| Despliegue sobre lo importado (migraciones 0069 → 0071 con datos reales) y desde cero (0001 → 0071) | OK |
| PITR: copia completa (8,8 GB → 1,1 GB cifrados) | 62 s |
| PITR: verificación del repositorio; restauración a un punto en un servidor desechable | OK |
| Desastre: carpeta de la base borrada → `pitr recover --name` | base abierta en 69 s, línea temporal 2; las 118 tablas como en el punto de restauración; el marcador escrito después no está |
| Linaje del RAW | 72.174 de 72.287 payloads con su fichero y su tamaño; 112 posteriores a la copia (esperado); 1 fichero vacío en el portátil (§ riesgos) |
| Caída de PostgreSQL (SIGKILL al postmaster) | vuelve solo en 7 s, datos intactos |
| Reinicio (el demonio Docker cae y vuelve; `up` y post-boot) | todo vuelve solo; el monitor avisó del WAL sin archivar mientras el S3 estaba parado, y se recuperó solo |
| `rollback` | 3 s; sano en 9 s |
| Copias cifradas fuera, rotación, prueba de restauración del volcado, RAW inmutable | OK |
| Playwright contra HTTPS con datos reales (anónimo, USER es/en, admin, seguridad y 2FA, preferencias, móvil, PWA) | 61 de 62. Falla Admin → Analítica: su primera carga pasa de los 20 s del test en 2 vCPU (informes de 4–9 s). Después queda 5 min en caché |
| Carga, 200 personas a la vez con sesión (3–10 s entre páginas) | 0 errores; p50 20 ms, p95 139 ms, p99 280 ms; 62 peticiones/s |

**Fallos que encontró el ensayo y quedaron corregidos:**

* La base entraba en un bucle de reinicios en cuanto el repositorio PITR fallaba. pgBackRest dejaba procesos
  huérfanos y PostgreSQL, como PID 1, los tomaba por propios. Ahora corre bajo `tini`.
* `import` comparaba con el manifiesto una sola tabla, no todas (en el ensayo anterior también). Además fallaba al
  cerrar sesiones de un esquema anterior.
* Cada despliegue reiniciaba PostgreSQL. Ahora su imagen solo cambia si cambia su definición.
* La API abría una conexión por petición, sin límite. Con 200 personas se agotaron las conexiones: 30 % de errores y
  p95 de 12 s. Ahora usa un pool acotado y guarda unos segundos lo que es igual para todos.
* La lista de cuotas superaba los 30 s con los datos reales; la frescura de plantillas tardaba 10 s; la búsqueda
  recorría todos los partidos. Ahora tardan milisegundos.
* Perfil → Seguridad mostraba las acciones del historial sin traducir.
* Otros menores: `export.sh` (pipefail), nombre del `archive_command`, CA del S3 en la restauración, límites de CPU
  por encima de los vCPU de la máquina, primera pasada del monitor.

**Lo que solo se puede probar en el servidor real (FASE 12 del día 1):**

* `bench.sh` en la máquina comprada;
* Cloudflare con certificado de origen, o Let's Encrypt;
* R2 real, Telegram y Healthchecks;
* el arranque con systemd;
* la prueba de carga desde fuera (aquí el generador compartía los 2 vCPU con el servidor);
* `pitr test` y la prueba del volcado con los datos completos, que necesitan el doble de disco que este sandbox.

Resultados completos: `docs/owner/BETA_DEPLOY_REPORT_2026-10-07.md`.

## 12. Ficheros

| Fichero | Qué es |
|---|---|
| `docker-compose.yml`, `Caddyfile`, `caddy/` | el conjunto, HTTPS y rutas |
| `postgres/` | imagen de PostgreSQL con pgBackRest (entrada, archivo de WAL, PITR) |
| `db/initdb`, `db/grants.sql` | roles y permisos de la base |
| `predigol.env.example`, `app.env.example` | todos los ajustes, sin secretos |
| `bin/install.sh` | prepara un Ubuntu 24.04 nuevo, una vez |
| `bin/predigolctl` | el mando |
| `bin/backup.sh`, `restore-test.sh`, `raw-sync.sh`, `pitr.sh` | copias, PITR y sus pruebas |
| `bin/secrets-export.sh` | los secretos del servidor en un fichero cifrado solo para el dueño (§7) |
| `bin/offsite-tiers.sh`, `r2-setup.sh`, `r2-lock-check.sh`, `r2-restore-drill.sh` | copias fuera: niveles, puesta en marcha, prueba de los candados y simulacro de restauración (en el portátil del dueño) |
| `bin/prune.sh` | poda de imágenes y caché de Docker; volúmenes solo con nombre y confirmación |
| `bin/healthcheck.sh`, `post-boot.sh` | monitor y comprobación tras arrancar |
| `bin/alerts_lib.sh`, `alerts_checks.sh` | los avisos de S3: la máquina de estados (un mensaje por cambio, recordatorio de SEV1, «recuperado», registro de incidentes) y las comprobaciones que el monitor no tenía |
| `bin/config-baseline.sh` | la línea base del aviso «cambió la configuración»: la toman el despliegue y la vuelta atrás; también `predigolctl config-baseline` |
| `bin/security-alerts.sh`, `security_alerts_sql.sh` | avisos de seguridad que salen de la auditoría de la aplicación y del registro de Caddy; las consultas solo cuentan y listan ids, nunca correos ni direcciones |
| `bin/weekly-summary.sh` | el resumen de los lunes: incidentes de 7 días por gravedad, el más largo, lo que sigue abierto |
| `bin/incident.sh`, `incident-dump.sh` | el registro de incidentes: la pluma del dueño (`predigolctl incident`) y su copia a la base cada 10 minutos |
| `bin/alert-test.sh`, `alert-drill.sh`, `../../scripts/sentry_drill.py` | probar el camino de los avisos: un mensaje de prueba, los simulacros de cada aviso y el error inventado a Sentry |
| `bin/import.sh` | el corte, en el servidor |
| `bin/bench.sh` | medir la máquina el día 1 |
| `bin/loadtest.sh`, `loadtest.py` | la prueba de carga del ensayo |
| `bin/cloudflare-ips.sh`, `maint.sh` | Cloudflare delante; mantenimiento diario |
| `bin/serverfn-matrix.sh`, `serverfn-probe.sh` | probar desde fuera la regla de `/_serverFn/*` (R02): casos con resultado esperado y marcador inocuo |
| `systemd/` | arranque al encender y temporizadores |
| `rehearsal/` | solo para ensayos: simulador del proveedor y S3 local; nunca en el servidor |
| `../cutover/export.sh`, `../release.sh` | en el portátil: la copia final del corte; el despliegue sin GitHub |
