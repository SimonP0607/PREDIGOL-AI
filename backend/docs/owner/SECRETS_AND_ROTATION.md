# Secretos de PrediGol: dónde viven y cómo se rotan

Fecha: 7 oct 2026. Aplica al servidor (`deploy/vps`) y al portátil mientras siga en marcha.

`SECURITY_ACTION: rotación de API-Football recomendada posteriormente. No rotarla sin autorización.`

## Reglas

* Ningún secreto va en Git, en una imagen de Docker, en un log, en un chat ni en la URL de una petición.
* En el servidor hay dos ficheros, los dos de root y con permisos 600:
  * `/etc/predigol/predigol.env`: los del servidor (base de datos, PITR, copias, avisos). Lo leen los scripts.
    Ningún contenedor de la aplicación lo recibe entero.
  * `/etc/predigol/app.env`: los de la aplicación (`FBI_*`). Lo reciben la API, el worker y los comandos `ops`.
* `install.sh` **genera** todas las contraseñas y claves. Nadie las teclea ni las ve en pantalla. El dueño las copia
  del fichero a su gestor de contraseñas una vez.
* El portátil guarda los suyos en `.env` del backend (600) y en `~/.fbi/` (600).

## Inventario

| Secreto | Dónde | Quién lo usa | Si se filtra |
|---|---|---|---|
| Clave de API-Football (`FBI_APIFOOTBALL_KEY`) | `app.env` | worker | gasto de cuota ajena; **rotación pendiente de autorización** |
| `FBI_AUTH_SECRET_KEY` | `app.env` | API | permite descifrar los secretos TOTP y falsificar códigos de recuperación de quien tenga la base |
| Contraseña de `postgres` (`POSTGRES_ADMIN_PASSWORD`) | `predigol.env` | solo el operador, dentro del contenedor | control total de la base (no tiene puerto público) |
| Contraseña del dueño de la base `fbi` (`POSTGRES_PASSWORD`) | `predigol.env` | migraciones, copias, mantenimiento | escribir y cambiar el esquema |
| `POSTGRES_WORKER_PASSWORD`, `POSTGRES_API_PASSWORD` | `predigol.env` | worker y API | lo que puede hacer ese rol (`db/grants.sql`) |
| `PITR_CIPHER_PASS` | `predigol.env` | pgBackRest | sin él, las copias PITR no se pueden leer: **perderlo es perder el PITR** |
| `PITR_S3_KEY` / `PITR_S3_KEY_SECRET` (token de R2) | `predigol.env` | pgBackRest | leer o borrar el repositorio PITR (cifrado) |
| Remoto de rclone (token de R2) | `/root/.config/rclone/rclone.conf` (600) | `backup.sh`, `raw-sync.sh` | leer o borrar las copias externas (cifradas con age) y el RAW |
| Clave privada `age` | **solo** en el gestor del dueño, nunca en el servidor | descifrar copias | leer las copias externas |
| Bot de Telegram (`FBI_TELEGRAM_BOT_TOKEN`) | `app.env` | avisos | enviar mensajes como el bot |
| URL de Healthchecks (`HC_PING_*`) | `predigol.env` | temporizadores | falsos "todo bien" |
| Certificado de origen de Cloudflare (si `PREDIGOL_TLS_MODE=origin`) | `/etc/predigol/origin/key.pem` (600) | Caddy | suplantar el origen ante Cloudflare |
| Contraseña, TOTP y códigos de recuperación del dueño | gestor del dueño y su teléfono | inicio de sesión | entrar como SUPER_ADMIN |
| Llave SSH del servidor | portátil del dueño | acceso al servidor | acceso root |

## Cómo se rota cada uno

Siempre: copia antes (`predigolctl backup`), fuera de partidos en vivo, y una línea en el registro de cambios del
dueño (qué, cuándo, por qué).

**API-Football.** Solo con autorización. Se crea la clave nueva en el panel del proveedor (sin abrir páginas que
muestren la clave en pantalla compartida), se pone en `app.env`, `predigolctl up` recrea el worker y se comprueba
el primer ciclo en `predigolctl logs worker`. Después se revoca la antigua.

**`FBI_AUTH_SECRET_KEY`.** Solo si se filtró. Los secretos TOTP están cifrados con ella, así que al cambiarla
nadie puede usar su segundo factor:

1. `predigolctl accounts mfa-reset --all` (cada cuenta vuelve a configurar su autenticador al entrar);
2. clave nueva: `openssl rand -base64 32` en `app.env`;
3. `predigolctl up`; `predigolctl accounts revoke-sessions --all`.

El dueño configura el suyo en el siguiente inicio de sesión, porque es obligatorio para SUPER_ADMIN.

**Contraseñas de la base.** El volumen inicial solo las lee la primera vez, así que se cambian en la base y en el
fichero:

```
docker exec -it predigol-postgres psql -U postgres -d postgres -c "\password predigol_api"
nano /etc/predigol/predigol.env      # la misma contraseña en POSTGRES_API_PASSWORD
predigolctl up                        # recrea la API con la URL nueva
```

Igual con `predigol_worker` (recrea el worker) y `fbi` (lo usan `ops`, las copias y el mantenimiento).

**Cifrado del PITR (`PITR_CIPHER_PASS`).** Un repositorio no cambia de clave. Para rotarla:

1. ruta nueva (`PITR_S3_PATH=/pgbackrest-2027`) y frase nueva en `predigol.env`;
2. `predigolctl up` (reinicia la base unos segundos);
3. `predigolctl pitr init && predigolctl pitr backup`.

La frase antigua se guarda hasta que caduquen las copias del repositorio antiguo (4 completas, ≈ 4 semanas). Solo
entonces se borra esa ruta en R2.

**Tokens de R2 (PITR y rclone).** Token nuevo en Cloudflare con permiso solo sobre ese bucket. Se cambia en
`predigol.env` (PITR, y luego `predigolctl up`) o con `rclone config` (copias). Se comprueba con
`predigolctl pitr status` y `predigolctl backup`, y después se revoca el antiguo.

**Clave `age`.** `age-keygen` en una máquina de confianza. La pública nueva va en `BACKUP_AGE_RECIPIENT`. La privada
antigua se guarda mientras haya copias cifradas con ella (12 meses con la retención actual).

**Sesiones.** `predigolctl accounts revoke-sessions --all` cierra todas. Cada cuenta puede cerrar las suyas en
Perfil → Seguridad, y el dueño las de cualquiera en Admin → Usuarios.

## Calendario propuesto

| Qué | Cuándo |
|---|---|
| API-Football | cuando el dueño lo autorice (pendiente) |
| Contraseñas de la base y tokens de R2 | una vez al año, o al cambiar quién tiene acceso |
| Clave `age` | cada 2 años |
| `FBI_AUTH_SECRET_KEY`, `PITR_CIPHER_PASS` | solo si hay sospecha de filtración |
| Revisión de este inventario | con cada fase nueva |
