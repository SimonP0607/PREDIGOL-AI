# Secretos de PrediGol: dónde viven y cómo se rotan

Fecha: 26 oct 2026 (plan de seguridad, fase S3). Aplica al servidor (`deploy/vps`), al portátil del dueño y a las cuentas de los proveedores.

`SECURITY_ACTION: la rotación de la clave de API-Football está en el plan de seguridad (paquete S1.d): se hace con el dueño presente, y no a mano.`

Este documento nombra los secretos y dice cómo se reponen; **nunca lleva un valor**. Si un secreto se ha filtrado, empieza por la Guía 6 de
`GUIAS_RESPUESTA_INCIDENTES.md` (qué revocar primero y dónde mirar el uso). Aquí está el cómo se repone cada uno.

## Reglas

* Ningún secreto va en Git, en una imagen de Docker, en un log, en un chat, en una captura de pantalla ni en la URL de una petición.
* En el servidor hay dos ficheros de entorno, los dos de root y con permisos 600, y un tercer fichero con el token de las copias:
  * `/etc/predigol/predigol.env`: los del servidor (base de datos, PITR, avisos, Healthchecks). Lo leen los scripts.
    Ningún contenedor de la aplicación lo recibe entero.
  * `/etc/predigol/app.env`: los de la aplicación (`FBI_*`). Lo reciben la API, el worker y los comandos `ops`.
  * `/root/.config/rclone/rclone.conf`: el token de las copias externas.
* `install.sh` **genera** las cuatro contraseñas de la base, `PITR_CIPHER_PASS` y `FBI_AUTH_SECRET_KEY` de un servidor nuevo: nadie las
  teclea ni las ve en pantalla. Las dos que no existen en ninguna otra copia, `PITR_CIPHER_PASS` y `FBI_AUTH_SECRET_KEY`, salen del
  servidor en el fichero cifrado de `predigolctl secrets-export` (más abajo, «Copia de los secretos»).
* Un valor que da un proveedor (token, clave, URL) se crea en su panel y se copia al servidor sin pasar por un chat ni por una captura.
  Los paquetes de rotación lo leen de un fichero (modo 600) y solo dicen «sí» o «no»: nunca el valor ni su huella.
* Ficheros temporales con secretos, que se borran en cuanto se usan: `/root/r2.env` (los tokens de R2, solo mientras dura un alta o una
  rotación); `/root/secrets-<fecha>.tar.age`, cuando ya está copiado al portátil; `/root/predigol-credentials/<correo>.txt` (la contraseña
  temporal de una cuenta nueva); la carpeta `incoming/` de un paquete de rotación (su `step_cleanup.sh` sobrescribe y borra lo que haya).
  En el portátil, `r2.env`, `r2.drill.env`, `age.key` y `apifootball_new.key` se borran cuando el valor ya está en el gestor y comprobado.
* Las copias fechadas de los ficheros de entorno (por ejemplo `predigol.env.before-r2-<fecha>` o las `.bak`) guardan secretos ya muertos
  y otros todavía vivos. No se copian a ninguna parte y se borran todas juntas, con el OK del dueño, cuando ya no hacen falta.
* El portátil guarda los suyos en `.env` del backend (600) y en `~/.fbi/` (600).
* Cada cuenta de proveedor tiene una contraseña única y segundo paso, y sus códigos de recuperación están en el gestor del dueño.

## Inventario

| Secreto | Dónde | Quién lo usa | Si se filtra | Cómo se cambia |
|---|---|---|---|---|
| `FBI_APIFOOTBALL_KEY` | `app.env` | el worker (la API nunca llama al proveedor) | gasto de la cuota diaria del plan | «API-Football» |
| `FBI_AUTH_SECRET_KEY` | `app.env` | la API | con una copia de la base, descifra los segundos factores y falsifica códigos de recuperación | «`FBI_AUTH_SECRET_KEY`» |
| `FBI_SENTRY_DSN` | `app.env` | la API y el worker | mandar errores falsos y gastar la cuota de Sentry; no lee nada | «Sentry» |
| `FBI_VAPID_PRIVATE_KEY` | `app.env`, vacía hasta la acción P12 del plan UX | el messenger firma con ella los avisos a los dispositivos; la API solo deriva de ella la clave pública que da a los navegadores | mandar avisos en nombre de PrediGol a los dispositivos que los activaron (no lee nada) | «Clave VAPID de los avisos» |
| `FBI_RESEND_API_KEY`, `FBI_RESEND_WEBHOOK_SECRET` | `app.env`, vacíos hasta que el dueño abre la cuenta de Resend (P2 y P3 del plan UX) | el messenger manda con la clave los correos a los lectores (la API solo mira que esté puesta); la API comprueba con el secreto la firma de los avisos de Resend | con la clave, correos en nombre del dominio de PrediGol y su cuota gastada; con el secreto, falsos avisos de rebote o de spam que dejan a lectores sin correo | «Resend (correo)» |
| `FBI_AI_KEY_ANTHROPIC` (en la Console, `worker-prod`), `FBI_AI_KEY_ANTHROPIC_LAB` (`worker-lab`), `EXA_API_KEY` | `app.env` | el worker (la IA; la clave del LAB, solo las sondas y pruebas del LAB); la API solo mira que estén puestas | gasto a tu nombre en esos proveedores, acotado por el tope de cada workspace en la Console (190 y 20 USD) | «Claves de Anthropic y de Exa» |
| `FBI_TELEGRAM_BOT_TOKEN`, `FBI_TELEGRAM_CHAT_ID` | `app.env`, vacíos a propósito | el notificador del producto, si se rellenan | nada, mientras estén vacíos | «Bot de avisos» |
| `POSTGRES_ADMIN_PASSWORD` | `predigol.env` | solo el operador, dentro del contenedor de la base | control total de la base (no tiene puerto público) | «Contraseñas de la base» |
| `POSTGRES_PASSWORD` (el dueño de la base, `fbi`) | `predigol.env` | migraciones, copias y mantenimiento | escribir y cambiar el esquema | «Contraseñas de la base» |
| `POSTGRES_WORKER_PASSWORD`, `POSTGRES_API_PASSWORD` | `predigol.env` | el worker y la API | lo que puede hacer ese rol (`db/grants.sql`) | «Contraseñas de la base» |
| `PITR_CIPHER_PASS` | `predigol.env` y `secrets-export` | pgBackRest | con acceso al cubo, leer el PITR; **perderla es perder el PITR** | «Cifrado del PITR» |
| `PITR_S3_KEY`, `PITR_S3_KEY_SECRET` (token `predigol-pitr`) | `predigol.env` | pgBackRest, dentro del contenedor de la base | leer o borrar `pitr/` (cifrado) | «Tokens de R2» |
| `PREDIGOL_ALERT_BOT_TOKEN`, `PREDIGOL_ALERT_CHAT_ID` | `predigol.env` | los scripts de avisos; ningún contenedor | mandar mensajes como el bot (falsos avisos) | «Bot de avisos» |
| `HC_PING_*` (siete URLs) | `predigol.env` | los temporizadores | falsos «todo bien» que esconden una caída, o falsas alarmas | «URLs de Healthchecks.io» |
| Token `predigol-copias` (el remoto de rclone) | `/root/.config/rclone/rclone.conf` (600) | `backup.sh` y `raw-sync.sh` | subir y leer las copias externas (cifradas con age) y el RAW; los candados impiden borrar o sobrescribir lo ya subido, pero puede borrar `pitr/` | «Tokens de R2» |
| Certificado de origen de Cloudflare (solo con `PREDIGOL_TLS_MODE=origin`) | `/etc/predigol/origin/key.pem` (600) | Caddy | suplantar el origen ante Cloudflare | «Certificado de origen de Cloudflare» |
| Clave privada `age` | gestor del dueño y copia sin conexión; **nunca en el servidor** | el dueño, para abrir las copias | con acceso al cubo, leer las copias externas | «Clave `age`» |
| Token `predigol-lectura` | gestor; en el portátil, solo durante un simulacro | el simulacro de restauración | leer las copias cifradas; no puede escribir ni borrar | «Tokens de R2» |
| `secrets-<fecha>.tar.age` | gestor y copia sin conexión; en el servidor, hasta copiarlo | el dueño | nada sin la clave privada `age` | «Copia de los secretos» |
| Contraseña, TOTP y códigos de recuperación del dueño | gestor y teléfono | inicio de sesión en la aplicación | entrar como SUPER_ADMIN | Guía 4 y «Sesiones» |
| Llave SSH del servidor | portátil del dueño | acceso al servidor | acceso root | «Llave SSH» |
| Cuentas de los proveedores | gestor del dueño | el dueño | quien entre cambia lo que ese proveedor controla (DNS, servidor, cubos) | «Cuentas de los proveedores» |

## Cómo se rota cada uno

Siempre: copia antes (`predigolctl backup`), fuera de partidos en vivo, con aviso al dueño si el cambio recrea un
contenedor, y una línea en el registro de cambios del dueño (qué, cuándo, por qué). Después, `predigolctl secrets-export` (ver «Copia de
los secretos»), para que el fichero cifrado lleve el valor nuevo.

**API-Football.** Está empaquetada y ensayada (paquete S1.d del plan de seguridad: `step_precheck.sh`, `step_apply.sh` con su `--dry-run`,
`step_verify.sh`, `step_cleanup.sh` y `step_revert.sh`); no se hace a mano. El proveedor guarda **una** clave por cuenta: «Regenerate»
(API-Football → Account → My Access) crea la nueva y mata la anterior en ese instante. Lo delicado no es cambiar el fichero sino los 5–8
minutos entre el clic del dueño y el worker nuevo con la clave nueva, en los que el worker no puede pedir datos (la API no se entera).
El paquete, antes de tocar nada, comprueba que el proveedor acepta la clave nueva; guarda una copia fechada de `app.env`; cambia **una**
línea; recrea **solo el worker** (el único que llama al proveedor; un reinicio no basta, porque el contenedor lee `app.env` al crearse); y
no imprime ninguna clave. Se elige una hora con pocos partidos en juego, a más de 15 minutos de un comienzo. La API toma la clave nueva
en el próximo despliegue que la recree. La clave nueva se guarda también en el gestor.

**`FBI_AUTH_SECRET_KEY`.** Solo si se filtró. Protege únicamente el segundo factor: los secretos TOTP están cifrados con ella y los códigos
de recuperación se guardan como un HMAC con ella. Al cambiarla, nadie puede usar su segundo factor ni sus códigos:

1. `predigolctl accounts mfa-reset --all` (cada cuenta vuelve a configurar su autenticador al entrar);
2. clave nueva: `openssl rand -base64 32` en `app.env`;
3. `predigolctl up`; `predigolctl accounts revoke-sessions --all`.

Los tres pasos seguidos y sin entrar en la aplicación entre medias: un segundo factor configurado entre el 1 y el 3 quedaría sellado con
la clave vieja y habría que borrarlo otra vez (`predigolctl accounts mfa-reset --email TU_CORREO`). El dueño configura el suyo en el
siguiente inicio de sesión, porque es obligatorio para SUPER_ADMIN. Una restauración necesita la **misma** clave que tenía la base que se
restaura (por eso va en `secrets-export`); si se perdiera, el remedio es este mismo procedimiento y lo único que se pierde son los segundos
factores.

**Contraseñas de la base.** Son cuatro (`postgres`, `fbi`, `predigol_worker`, `predigol_api`) y las cuatro están en
`predigol.env`. El `docker-compose.yml` entrega cada una **dos veces**: a quien se conecta con ella (la URL de la API,
del worker o de `ops`) y al propio servicio `postgres` (`POSTGRES_PASSWORD` y `PREDIGOL_DB_*_PASSWORD`), que solo las
lee cuando el volumen es nuevo. Es a propósito: un servidor nuevo, o una recuperación desde cero, nace con las
contraseñas que el fichero tiene en ese momento. La consecuencia es que **cambiar una en el fichero cambia la receta del
contenedor `postgres`**: el siguiente `predigolctl up` o `deploy` recrea PostgreSQL (del orden de un minuto en el que
las peticiones que necesitan la base fallan; la API se reconecta sola) además de recrear a quien usa ese rol. No basta
con "recrear la API", y por eso se planifica como un paso propio, con aviso al dueño, y en este orden:

1. se para a quien usa el rol (el worker, si es `predigol_worker`);
2. `ALTER ROLE` con la contraseña nueva, con la base viva (el único momento en que se puede);
3. se cambia esa línea de `predigol.env` (con copia fechada del fichero antes);
4. se recrea `postgres` desde el fichero y después el servicio que usa el rol;
5. se comprueba: el rol entra con la nueva, la antigua se rechaza y `predigolctl up` ya no quiere recrear nada.

Para `predigol_worker` está empaquetado y ensayado (paquete S1.e del plan de seguridad: `step_precheck.sh`,
`step_apply.sh`, `step_verify.sh`, `step_revert.sh` y `step_cleanup.sh`): la contraseña nueva se genera en el
servidor, la base recibe solo su verificador SCRAM, nadie la teclea ni la ve, y si algo falla vuelve a la antigua. No
se hace a mano con `\password` y `nano`: la contraseña pasaría por una pantalla, un historial de terminal o un
portapapeles.

Si se restaura PITR a un punto **anterior** a una rotación, el rol vuelve con la contraseña antigua mientras el
fichero tiene la nueva y el servicio que lo usa no entra. Se detecta con `step_verify.sh` (o con cualquier login de
prueba) y se arregla dándole otra vez al rol la contraseña que tiene el fichero. Una recuperación desde cero no tiene
ese problema: toma las contraseñas del fichero.

Las copias fechadas de `predigol.env` guardan la contraseña antigua (ya muerta) y todos los demás secretos vivos del
fichero: se borran con las demás copias `.bak`, con el OK del dueño.

**Cifrado del PITR (`PITR_CIPHER_PASS`).** Un repositorio no cambia de clave. Para rotarla:

1. ruta nueva (`PITR_S3_PATH=/pgbackrest-2027`) y frase nueva en `predigol.env`;
2. `predigolctl up`: como `PITR_*` forma parte de la receta del contenedor, recrea PostgreSQL (del orden de un minuto sin base), así que
   se hace con aviso al dueño;
3. `predigolctl pitr init && predigolctl pitr backup`.

Hoy no hay paquete para esto (solo hace falta si la frase se filtra): si llega el caso, se prepara y se ensaya como el de la contraseña
de `predigol_worker`, para que la frase nueva no pase por una pantalla. La frase antigua se guarda hasta que caduquen las copias del
repositorio antiguo (4 completas, ≈ 4 semanas): mientras tanto se conserva también el fichero cifrado de `secrets-export` que la lleva.
Solo entonces se borra esa ruta en R2.

**Tokens de R2 (copias, PITR y lectura).** Son tres, los tres limitados al cubo `predigol-backups` (Cloudflare → R2 Object Storage →
Manage API tokens; R2 no puede limitar un token a una carpeta, así que los dos de escritura pueden borrar `pitr/`; en `dumps/`, `raw/` y
`audit/` los candados impiden borrar o sobrescribir, y quitarlos exige entrar al panel de Cloudflare). Al crear uno nuevo, el panel
enseña su identificador y su secreto **una sola vez**: se copian directamente al sitio que toque, nunca a un chat.

* `predigol-copias` (Object Read & Write; lo usan `backup.sh` y `raw-sync.sh`):
  1. token nuevo en Cloudflare con el mismo permiso y el mismo cubo;
  2. un `/root/r2.env` nuevo (`umask 077` antes de crearlo; modo 600) con `R2_ACCOUNT_ID`, `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`,
     `R2_BUCKET=predigol-backups` y `AGE_RECIPIENT` (la clave **pública**: es el valor de `BACKUP_AGE_RECIPIENT` en `predigol.env`), cada
     valor justo después del `=`, sin espacios ni comillas;
  3. `bin/r2-setup.sh /root/r2.env --check-only`, que reescribe el remoto `r2` con el ajuste `no_head` (R2 contesta con un error 501 a lo
     que rclone 1.60 pregunta tras cada subida; sin ese ajuste cada copia se registraría como fallida) y vuelve a probar el cubo y sus
     bloqueos; no uses `rclone config` a mano;
  4. `predigolctl backup`: una copia sube con el token nuevo;
  5. se revoca el token antiguo en Cloudflare y se borra `/root/r2.env`.
* `predigol-pitr` (Object Read & Write; lo usa pgBackRest): token nuevo con el mismo permiso; copia fechada de `predigol.env`; se
  cambian `PITR_S3_KEY` y `PITR_S3_KEY_SECRET`; `predigolctl up` recrea PostgreSQL (del orden de un minuto sin base, porque `PITR_*` es
  parte de la receta del contenedor), así que se hace con aviso al dueño; se comprueba con `predigolctl pitr status` y
  `predigolctl pitr backup`, y después se revoca el antiguo. `bin/pitr-enable.sh` no sirve para esto: se niega si el PITR ya está activo.
* `predigol-lectura` (Object Read only; es del simulacro de restauración y nunca va al servidor): token nuevo, se guarda en el gestor, se
  revoca el antiguo. En el portátil solo existe mientras dura un simulacro (`r2.drill.env`).

**Clave `age`.** La privada vive en el gestor del dueño (una nota segura) y en la copia sin conexión, y **nunca** en el servidor ni en un
chat; la pública (`BACKUP_AGE_RECIPIENT`) no es secreta. Para rotarla (cada 2 años, o si la privada se filtró):

1. `age-keygen` en una máquina de confianza (el portátil); la privada nueva va al gestor y a la copia sin conexión antes de seguir;
2. la pública nueva en `BACKUP_AGE_RECIPIENT` de `predigol.env` (los scripts la leen en cada ejecución: no hay que reiniciar nada);
3. `predigolctl backup`, y en el portátil `r2-restore-drill.sh` con la clave nueva: la copia nueva se abre;
4. `predigolctl secrets-export`: el fichero de los secretos queda cifrado para la clave nueva.

La privada antigua se guarda mientras haya copias cifradas con ella: 13 meses (lo más que viven las copias en el cubo: 396 días). Si lo
que se filtró fue la privada, las copias ya subidas no se pueden volver a cifrar (están bloqueadas): solo importa para quien además llegue
al cubo (Guía 6).

**Bot de avisos (Telegram).** Hay dos bots posibles y hoy solo se usa el primero. El **del servidor** (`PREDIGOL_ALERT_BOT_TOKEN` y
`PREDIGOL_ALERT_CHAT_ID` en `predigol.env`) manda todos los avisos del plan de seguridad; ningún contenedor lo recibe. El **de la
aplicación** (`FBI_TELEGRAM_BOT_TOKEN` y `FBI_TELEGRAM_CHAT_ID` en `app.env`) se deja vacío a propósito: si se rellenara, el notificador
del producto mandaría a ese chat los miles de avisos de picks que tiene en cola. Si el del servidor no está completo (el token **y** su
chat), los scripts prueban con el de la aplicación; si tampoco, no mandan nada y reintentan en su siguiente pasada. Para cambiar el token:

1. en Telegram, @BotFather → `/revoke` → eliges el bot: te da el token nuevo en el momento y **el viejo deja de valer al instante** (es la
   excepción de «revocar primero»: no hay avisos hasta el paso 3);
2. copia fechada de `predigol.env` y el token nuevo en `PREDIGOL_ALERT_BOT_TOKEN` (el chat no cambia);
3. `predigolctl alert-test`: tiene que decir que el bot del servidor tomó el mensaje, y el mensaje tiene que llegar a tu móvil.

No hay que reiniciar nada: los scripts y los temporizadores leen `predigol.env` en cada ejecución, y los avisos que se quedaron esperando
salen en la siguiente pasada. Con el token se pueden mandar mensajes como el bot y leer lo que alguien le escriba, pero no los mensajes que
el bot ya envió.

**URLs de Healthchecks.io.** Son siete (`HC_PING_HEALTH`, `HC_PING_BACKUP`, `HC_PING_RESTORE_TEST`, `HC_PING_RAW_SYNC`, `HC_PING_PITR`,
`HC_PING_PITR_TEST` y `HC_PING_MAINT`), una por tarea, con la forma `https://hc-ping.com/<identificador>` (sin barra final ni `/start` ni
`/fail`: los scripts los añaden). La URL **es** el secreto: quien la tenga puede decir «todo bien» y esconder una caída, o «fallo» y dar
falsas alarmas. Healthchecks.io **no deja cambiar** el identificador de un check, así que se sustituye el check entero, de uno en uno:

1. en healthchecks.io, página del check (Check Details) → «Create a Copy…»: la copia nace con otra URL y con el mismo nombre, horario y
   avisos; comprueba también el margen (grace time);
2. la URL nueva en su línea `HC_PING_*` de `predigol.env` (con copia fechada antes);
3. espera a la siguiente ejecución de esa tarea (para el monitor, `predigolctl health`): la copia pasa a «up»;
4. borra el check antiguo: desde ese momento su URL no sirve a nadie.

No hay que reiniciar nada. Si se filtra `predigol.env` entero, se repite con los siete.

**Sentry (`FBI_SENTRY_DSN`).** El DSN solo deja mandar eventos, pero aquí vive en el servidor y quien lo tenga puede llenar el proyecto de
errores falsos y gastar la cuota. En Sentry → Settings → Projects → el proyecto → Client Keys (DSN): se crea una clave nueva, su DSN va
a `app.env` (copia fechada antes), `predigolctl up` recrea la API y el worker (unos segundos de 502 en la API) y después se desactiva la
clave antigua. Sentry no recibe cookies, cuerpos de petición, IP ni variables locales (`src/fbi/core/sentry.py`).

**Resend (correo).** Si las líneas están vacías en `app.env`, no hay nada que rotar. La clave (`FBI_RESEND_API_KEY`) se crea en
Resend → API Keys, con permiso solo de envío y solo para el dominio de PrediGol, y va a `app.env` sin que se vea en pantalla, con copia
fechada antes; `predigolctl up` recrea la API y el messenger (unos segundos de 502 en la API); en Admin → Mensajes se comprueba que el
siguiente correo sale, y después se borra la clave antigua en Resend. El secreto de los avisos (`FBI_RESEND_WEBHOOK_SECRET`) es el de
firma del endpoint de PrediGol en Resend → Webhooks: se crea otro endpoint con la misma dirección y los mismos eventos, su secreto va a
`app.env` igual, `predigolctl up`, y se borra el endpoint viejo; un aviso firmado con el secreto viejo se rechaza (la API responde 401 y
Resend lo reintenta). El alta y la prueba real están en `docs/owner/EMAIL_MENSAJERIA_UX_A5.md`.

**Clave VAPID de los avisos (`FBI_VAPID_PRIVATE_KEY`).** Si la línea no está en `app.env`, no hay nada que rotar. Solo si se
filtró: es la clave con la que los navegadores reconocen a PrediGol, y al cambiarla cada navegador tiene que volver a activar los
avisos (Perfil → Notificaciones). Se quita la línea vieja de `app.env` (copia fechada antes) y se genera otra dentro de un fichero de
root, sin que pase por la pantalla, con los pasos 1 a 6 de `docs/owner/AVISOS_UX_B7.md`, sección 9 (el último,
`predigolctl config-baseline`); después se recrean la API y el messenger.

**Claves de Anthropic y de Exa.** Si la línea está vacía en `app.env`, no hay nada que rotar. La clave nueva de Claude
(`FBI_AI_KEY_ANTHROPIC`, `FBI_AI_KEY_ANTHROPIC_LAB`) se crea en la Console, dentro de su workspace (`worker-prod` en PREDIGOL,
`worker-lab` en PREDIGOL-LAB), y se pone en `app.env` sin que se vea en pantalla (`IA_ACCIONES_MANUALES.md`, acciones 5 a 7), con copia
fechada de `app.env` antes; la de Exa (`EXA_API_KEY`) se crea en su panel y se pone igual. `predigolctl up` recrea la API y el worker
(unos segundos de 502 en la API); en Usage se comprueba que la clave nueva suma peticiones y en `predigolctl logs worker`, el primer ciclo
de IA. A las 48 horas, con la antigua en 0 peticiones, se **desactiva** (Disable); nunca se borra (Delete), porque la archiva para siempre
y no tiene vuelta. Si el motivo es una filtración, la antigua se desactiva en cuanto la nueva funciona, sin esperar las 48 horas. Pon
también en la consola de cada proveedor un límite de gasto mensual: si la clave se filtra, es lo que acota el daño; el presupuesto de la
aplicación no lo ve quien use la clave por fuera. El libro de la IA guarda solo el *nombre* de la clave y del workspace, nunca la clave.

**Certificado de origen de Cloudflare.** Solo con `PREDIGOL_TLS_MODE=origin`. En Cloudflare → SSL/TLS → Origin Server se crea otro
certificado; `cert.pem` y `key.pem` nuevos van a `/etc/predigol/origin/` (600), se reinicia Caddy (`docker restart predigol-caddy`,
unos segundos sin HTTPS) y se revoca el antiguo en Cloudflare. La fase S5 (DNS, Cloudflare y correo) revisa este procedimiento.

**Copia de los secretos.** `predigolctl secrets-export` (o `--out DIR`) empaqueta `predigol.env`, `app.env` y la configuración de rclone en
**un solo fichero**, `/root/secrets-<fecha>.tar.age` (600), cifrado con la clave **pública** `age` del dueño: no imprime ningún valor ni
su huella y no escribe nunca una copia en claro. Dentro lleva un `MANIFEST.txt` con los **nombres** de los ajustes (cuáles tienen valor y
cuáles están vacíos). Se repite cada vez que se rota un secreto, y cada vez: se copia al portátil, se guarda en el gestor (como adjunto) y
en la copia sin conexión, y **se borra del servidor** (lo que contiene ya está en claro en el servidor: dejarlo no protege nada). El
fichero anterior se conserva mientras exista algo que solo él pueda abrir (por ejemplo, un repositorio PITR con la frase antigua). Para
abrirlo, en el portátil: `age -d -i clave.txt secrets-<fecha>.tar.age > secrets.tar` y `tar -xf secrets.tar`.

**Llave SSH.** Hoy es una sola llave de root, que usan a la vez el dueño, los scripts y los agentes. La fase S4 la sustituye por una llave
por actor: un usuario personal del dueño con `sudo`, `predigol-ops` sin permisos de escritura y root solo desde la consola de Contabo. Hasta
entonces, si se pierde o se filtra: se quita su pública de `/root/.ssh/authorized_keys` (desde la consola de Contabo si ya no entras) y se
pone otra.

**Cuentas de los proveedores.** Cloudflare, Contabo, Hostinger, GitHub, Healthchecks.io, Sentry, Telegram, API-Football, Anthropic, Exa y Resend:
contraseña única en el gestor, segundo paso activado con una aplicación autenticadora (no por SMS) y los códigos de recuperación en el
gestor. Los tokens de API de esas cuentas (los de R2, el de GitHub) se revisan en la misma pasada que el resto del inventario.

**Sesiones.** `predigolctl accounts revoke-sessions --all` cierra todas. Cada cuenta puede cerrar las suyas en
Perfil → Seguridad, y el dueño las de cualquiera en Admin → Usuarios.

## Calendario propuesto

| Qué | Cuándo |
|---|---|
| Claves de Claude | una vez al año, al cambiar quién tiene acceso al servidor o ante una sospecha de filtración; la antigua se desactiva a las 48 h (de inmediato si hubo filtración) |
| API-Football | la primera vez, con el paquete S1.d (el dueño regenera la clave en el panel); después, una vez al año o al renovar el plan |
| Contraseñas de la base, tokens de R2, bot de avisos, URLs de Healthchecks.io, DSN de Sentry, clave de Exa, clave y secreto de Resend | una vez al año, o al cambiar quién tiene acceso |
| Clave `age` | cada 2 años |
| `FBI_AUTH_SECRET_KEY`, `PITR_CIPHER_PASS`, `FBI_VAPID_PRIVATE_KEY` | solo si hay sospecha de filtración |
| Revisión de este inventario | con cada fase nueva del plan de seguridad (S4 cambia las llaves SSH, S8 reparte `app.env` por servicio) y cada trimestre desde S15 |
