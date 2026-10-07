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
| Cloudflare R2 (un bucket, dos tokens) | PITR, copias cifradas y RAW fuera del servidor | 10 GB gratis, luego $0,015/GB-mes |
| Una clave `age` (la genera el dueño y guarda la privada) | cifrar las copias antes de salir | $0 |
| Healthchecks.io, UptimeRobot, Sentry Developer, bot de Telegram | avisos | $0 |
| API-Football Ultra | los datos | ya se renueva sola |

`SECURITY_ACTION: rotación de API-Football recomendada posteriormente. No rotarla sin autorización.` Cómo se rota
cada secreto: `docs/owner/SECRETS_AND_ROTATION.md`.

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
   * `predigol.env`: dominio, `PREDIGOL_ACME_EMAIL`, R2 para el PITR (`PITR_S3_*`), copias (`BACKUP_RCLONE_REMOTE`,
     `BACKUP_AGE_RECIPIENT`, `RAW_RCLONE_REMOTE`, tras `rclone config`), Healthchecks (`HC_PING_*`).
   * `app.env`: la clave de API-Football y el bot de Telegram.
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
    busca `"ok"`. Telegram con `FBI_TELEGRAM_BOT_TOKEN` y `FBI_TELEGRAM_CHAT_ID`.

## 4. Corte desde el portátil, sin dos workers a la vez

Fuera de partidos en juego y con el ensayo del servidor en verde (§11). Si el servidor tuvo un ensayo con datos, se
vacía antes: `predigolctl stop` y se borran `pgdata` y `raw` de ese ensayo. `import` solo escribe en una base vacía.

1. **Portátil: mantenimiento y parar el worker.** `scripts/dev-down worker`. Desde aquí el portátil no captura.
   Nunca puede haber dos workers encendidos: cada uno tendría su base, gastarían cuota y divergirían.
2. **Portátil: la copia final.** `deploy/cutover/export.sh` (en WSL, desde el backend).
   * Se niega si el worker sigue vivo o latió hace menos de 2 minutos.
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
8. **Portátil.** Queda 7 días como respaldo frío, con el worker parado.

Vuelta atrás: mientras no se borre nada en el portátil, basta con encender allí el worker (`scripts/dev-up worker`)
y devolver el DNS. El servidor se vacía y se repite.

## 5. Operación diaria

| Comando | Qué hace |
|---|---|
| `predigolctl status` / `health` | contenedores, versiones y veredicto del monitor / el monitor, ahora |
| `predigolctl logs worker` | logs en vivo de un servicio |
| `predigolctl backup` / `restore-test` | copia / prueba de restauración, ahora |
| `predigolctl pitr status\|backup\|verify\|test` | el repositorio PITR |
| `predigolctl accounts list\|unlock\|mfa-reset\|revoke-sessions …` | cuentas, desde la terminal |
| `predigolctl maint` | particiones por delante y retención de restos, con copia verificada |
| `predigolctl psql` | consola de la base en solo lectura |
| `predigolctl stop` / `up` | parar o levantar el conjunto; no se pierde nada |

Temporizadores (`systemctl list-timers 'predigol*'`):

| Tarea | Cuándo |
|---|---|
| monitor | cada 5 min |
| PITR: copia completa el domingo, diferencial el resto | 03:30 UTC |
| copia `pg_dump` cifrada fuera | 04:15 UTC |
| mantenimiento (particiones, retención) | 05:30 UTC |
| prueba de restauración del volcado | lunes 06:00 UTC |
| verificación del repositorio PITR | miércoles 05:00 UTC |
| prueba real de PITR (restaurar a un punto en un servidor desechable) | primer martes del mes, 06:00 UTC |
| RAW fuera del servidor | cada hora, minuto :20 |

El monitor revisa:

* contenedores, HTTPS, el latido del worker (lo reinicia como mucho una vez por hora) y la captura en vivo;
* disco (aviso al 85 %) y su previsión, memoria, swap, carga, *steal* de CPU, conexiones de la base;
* el archivo de WAL, la edad de las copias, la verificación y la prueba del PITR;
* la cuota de API-Football, ejecuciones atascadas o fallidas, errores 5xx, el certificado.

Avisa solo cuando cambia el estado.

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

`predigolctl rollback` arranca la versión anterior en segundos (sus imágenes se conservan). La base **no** se baja
de versión sola; si la versión anterior necesita el esquema anterior, se decide con el dueño (`alembic downgrade` o
la copia `pre-deploy`).

## 7. Copias y desastres

| Capa | Qué | Retención |
|---|---|---|
| PITR (pgBackRest → R2) | WAL continuo (máx. 5 min de retraso) + completa semanal y diferencial diaria, cifrado AES-256 | 4 completas (≈ 4 semanas) |
| Volcado diario | `pg_dump` leído entero, sha256, recuentos; fuera cifrado con `age` | servidor: 3 días + 2 semanas; R2: 14 días, 8 domingos, 12 primeros de mes |
| RAW | `rclone copy --immutable`: solo añade, nunca modifica ni borra fuera | indefinida |

Pruebas automáticas: el volcado se restaura cada lunes en un PostgreSQL sin red; el PITR se verifica cada miércoles y
se restaura de verdad a un punto cada mes.

**Si se pierde la base o el servidor:**

1. Servidor nuevo y §3, pasos 1–6, con los **mismos** `PITR_*` y `PITR_CIPHER_PASS` (del gestor de contraseñas).
2. `predigolctl pitr recover --confirm` restaura desde R2 hasta el último WAL archivado, o hasta un momento:
   `--time "2026-10-08 12:00:00+00"`.
   * Si hay una carpeta de datos, la aparta (`pgdata.before-recover-<fecha>`); nunca la borra.
   * Arranca la base en una línea temporal nueva, levanta el resto y hace una copia completa.
3. RAW: `rclone copy REMOTO/raw /srv/predigol/raw` y `chown -R 1000:1000 /srv/predigol/raw`.
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

ENSAYO_PENDIENTE

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
| `bin/healthcheck.sh`, `post-boot.sh` | monitor y comprobación tras arrancar |
| `bin/import.sh` | el corte, en el servidor |
| `bin/bench.sh` | medir la máquina el día 1 |
| `bin/loadtest.sh`, `loadtest.py` | la prueba de carga del ensayo |
| `bin/cloudflare-ips.sh`, `maint.sh` | Cloudflare delante; mantenimiento diario |
| `systemd/` | arranque al encender y temporizadores |
| `rehearsal/` | solo para ensayos: simulador del proveedor y S3 local; nunca en el servidor |
| `../cutover/export.sh`, `../release.sh` | en el portátil: la copia final del corte; el despliegue sin GitHub |
