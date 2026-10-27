# Simulacros de avisos de PrediGol

Fecha: 26 oct 2026 · Fase S3.5 del plan de seguridad (R03) · Para el dueño, que mira el móvil mientras la sesión provoca los avisos.

Un simulacro hace llegar a tu móvil el mensaje de un aviso, sin que el problema sea cierto, para comprobar tres cosas: que
**llega**, que llega con su gravedad y sus palabras, y que el ciclo «se abre → se recuerda → se recupera» funciona. R03
(«ninguna alerta llega a nadie») se cierra cuando cada aviso de S3 se ha provocado una vez y llegó en **menos de 10
minutos** (los de Healthchecks, dentro de su margen), con la hora apuntada. La prueba es el **acta** del final de este
documento.

Todas las horas son UTC (Bogotá = UTC−5): las 14:05 de tu móvil son las 19:05 UTC. Los comandos los ejecuta la sesión en
el servidor (`ssh predigol`); si alguna vez prefieres ejecutarlos tú, son los mismos.

## Lo que te toca

Casi todo lo hace la sesión. En total son unos 30 minutos, y tú sobre todo miras el móvil:

* **Ten el móvil en la mano**, con Telegram abierto en el chat del bot de avisos y el sonido puesto.
* **No escribas nada en el servidor.** La sesión te dice en el chat qué va a enviar antes de cada paso.
* **Haz capturas del chat, en orden**, cuando la sesión te lo pida: que se vean el texto y la hora de cada mensaje. No hace
  falta una por mensaje: los 36 de golpe caben en unas pocas capturas desplazando el chat.
* **Dos cosas con tus manos:** crear antes, y borrar al final, el monitor temporal de la Tabla C; y mirar tu correo, donde
  llegan los tres avisos que no vienen por el bot de Telegram (el del monitor externo, el de Sentry y el de GitHub).

**Cómo reconocer un simulacro.** Los mensajes del servidor empiezan por «SIMULACRO ·» y su número de incidente empieza por 9
(`INC-AAAA-901` en adelante); el error de Sentry y el pull request de GitHub también llevan la palabra. Los de Healthchecks y
el del monitor externo no pueden llevarla (los escriben ellos): la sesión te dice cuál va a provocar justo antes. **Si llega
algo que ella no anunció, dilo: se mira primero eso, porque puede ser un aviso de verdad.**

## Qué prueba un simulacro y qué no

El simulacro repite el mensaje de cada aviso con el mismo código y el mismo bot que usan los avisos de verdad
(`alerts_lib.sh`), sobre un registro de borrador: el registro real de incidentes y los avisos abiertos no se tocan, y
ninguna comprobación se ejecuta. Eso prueba lo que **solo producción puede probar**: que el mensaje llega a tu móvil, con su
gravedad y sus palabras, y que abrir, recordar y recuperar funcionan con el bot real.

Lo que **no** prueba es que la comprobación real salte cuando el problema es real. Para eso habría que parar un
contenedor, llenar el disco o forzar un umbral, y en producción eso abriría un incidente de verdad. Es la diferencia con el
«umbral forzado» que escribía el plan: en producción lo sustituye la repetición del mensaje por el bot real, y que cada
comprobación detecta su problema se prueba en el ensayo (Staging v2) y en las pruebas automáticas del repositorio; el
estado de cada una está en el plan de ejecución de S3.

## Antes de la sesión

Esta sesión va **después** de S2 (los temporizadores de copia y PITR ya informan) y de instalar el paquete de S3 en
producción (S3.1 a S3.3 del plan de ejecución): sin él el servidor no tiene `alert-drill`. La sesión comprueba, y tú
confirmas lo que solo tú ves:

1. **El canal.** `predigolctl alert-test` envía un mensaje de prueba y dice con qué bot salió: debe decir
   `the server's alert bot`, el de `PREDIGOL_ALERT_*`. Tú confirmas que llegó.
2. **El ensayo en seco.** La sesión corre el registro entero y cada check de Healthchecks con `--dry-run`, que no envía ni
   escribe nada: el registro muestra sus 36 mensajes, y cada check dice si su URL de ping está puesta en `predigol.env`
   (sin imprimirla) o qué variable falta.

   ```bash
   predigolctl alert-drill --all --dry-run
   for c in health backup restore-test raw-sync pitr pitr-test maint; do predigolctl alert-drill --healthchecks "$c" --dry-run; done
   ```

3. **La hora.** `date -u` en el servidor y la hora de tu móvil más 5 horas no difieren más de un minuto.
4. **Healthchecks (tú).** Los siete checks existen con el periodo y el margen de la Tabla B, y el botón de prueba de la
   integración con Telegram hace llegar un mensaje.
5. **Sentry, el monitor externo y GitHub (tú).** El proyecto de Sentry tiene la regla «issue nuevo → correo», el monitor
   externo vigila `https://predigolai.com/health` y te escribe por correo, y GitHub te manda por correo las comprobaciones
   fallidas (Ajustes → Notificaciones → Actions).

## Tabla A · Los avisos del servidor, uno por uno

Cada fila es un mensaje que el servidor puede enviar. **#** es el número del aviso en el catálogo del plan (sección 20);
«—» marca los que el servidor envía y el catálogo no numera (no tienen fila en el acta). El mensaje lleva valores de ejemplo
en lugar de los recuentos reales, y llega así: `PrediGol (nombre-del-servidor): SIMULACRO · [SEV1] clave: texto (INC-AAAA-9NN)`.

**●** = lo envía `alert-drill --all`: el mensaje de apertura de cada fila marcada, uno cada 3 segundos y sin mensajes de
recuperación. Las filas sin marca son otras gravedades de un aviso que ya está en el registro; se envían de una en una.
Un servicio (`<nombre>`) vale por los cinco (postgres, api, worker, web y caddy): el código es el mismo y solo cambia el
nombre.

| # | Clave | Gravedad | Mensaje | `--all` |
|---|---|---|---|---|
| 28 | `admin.denied` | SEV2 | 34 respuestas 401/403 en rutas de administrador en 10 min | ● |
| 5 | `api.login` | SEV1 | `/auth/me` responde 200 sin sesión: el inicio de sesión no se está exigiendo | ● |
| 5 | `api.login` | SEV3 | la comprobación de `/auth/me` no encuentra la ruta (¿cambió la API?) |  |
| 23 | `auth.bruteforce` | SEV2 | 34 inicios de sesión fallidos en 5 min | ● |
| 24 | `auth.locked` | SEV3 | 2 cuenta(s) en espera en la última hora (id 0,0) | ● |
| 25 | `auth.newdevice` | SEV2 | inicio de sesión de administrador desde un navegador nuevo (id 0) | ● |
| 26 | `auth.privileged` | SEV1 | 1 cambio(s) de rol, MFA o contraseña, 1 hecho(s) por otra cuenta que no es la del dueño (id 0) | ● |
| 26 | `auth.privileged` | SEV2 | 1 cambio(s) de rol, MFA o contraseña (id 0) | ● |
| — | `backup.local` | SEV2 | la copia local más reciente tiene más de 26 h | ● |
| — | `backup.locks` | SEV1 | falló la última comprobación de los candados del cubo: las copias fuera del servidor podrían borrarse | ● |
| — | `backup.locks` | SEV3 | los candados del cubo se comprobaron por última vez hace 12 días |  |
| 13 | `backup.offsite` | SEV1 | la copia más reciente fuera del servidor tiene más de 3 días |  |
| 13 | `backup.offsite` | SEV2 | la copia más reciente fuera del servidor tiene 30 h | ● |
| 13 | `backup.offsite` | SEV3 | todavía no hay ninguna copia verificada fuera del servidor |  |
| 32 | `config.drift` | SEV2 | cambió la configuración respecto a la línea base: Caddyfile | ● |
| 10 | `db.connections` | SEV2 | PostgreSQL usa el 85 % de las conexiones | ● |
| 8 | `disk.forecast` | SEV2 | al ritmo actual el disco llega al 90 % en unos 9 días (+4600 MB/día) | ● |
| 8 | `disk.usage` | SEV1 | el disco está al 91 % | ● |
| 8 | `disk.usage` | SEV2 | el disco está al 83 % | ● |
| 9 | `host.resources` | SEV2 | el servidor está sobrecargado: CPU robada al 22 % durante 15 min | ● |
| — | `incidents.dump` | SEV3 | 3 línea(s) nueva(s) del registro de incidentes no se pudieron copiar a la base (el fichero `state/incidents.jsonl` las conserva; log: incident-dump) | ● |
| 17 | `ingest.live` | SEV2 | 3 partido(s) en juego y la última captura en vivo fue hace 14 min | ● |
| 17 | `ingest.runs` | SEV2 | 25 ejecuciones de ingesta fallidas en la última hora | ● |
| 19 | `picks.review` | SEV3 | 2 pick(s) de 1 partido(s) terminados esperan revisión (el motivo está en `picks.pick_results.review_reason`) | ● |
| 19 | `picks.unsettled` | SEV2 | 3 pick(s) de 2 partido(s) terminados hace más de 3 h siguen sin liquidar (el más antiguo espera 25 h) | ● |
| — | `pitr.backup` | SEV2 | la copia base PITR tiene más de 26 h | ● |
| 15 | `pitr.test` | SEV2 | falló la última verificación del repositorio PITR | ● |
| 14 | `pitr.wal` | SEV1 | el archivado de WAL hacia el repositorio PITR está fallando | ● |
| 18 | `provider.quota` | SEV2 | el presupuesto diario de API-Football va por el 93 % | ● |
| 16 | `raw.full` | SEV2 | la última pasada completa del RAW fue hace 6 días | ● |
| 16 | `raw.sync` | SEV2 | el almacén RAW se copió fuera del servidor por última vez hace 14 h | ● |
| 15 | `restore.test` | SEV2 | el último ensayo de restauración falló | ● |
| 2 | `svc.<nombre>` | SEV1 | el contenedor `<nombre>` no está sano (parado) | ● |
| 4 | `svc.<nombre>.loop` | SEV1 | el contenedor `<nombre>` se ha reiniciado 4 veces en 12 min | ● |
| 11 | `tls.origin` | SEV1 | el certificado caduca en 5 días |  |
| 11 | `tls.origin` | SEV2 | el certificado caduca en 15 días | ● |
| — | `web.degraded` | SEV2 | la API informa salud degradada (detalle en `health.json`) | ● |
| 6 | `web.errors5xx` | SEV2 | 31 errores 5xx en 5 min | ● |
| 2 | `web.health` | SEV1 | la web no responde en `/health` | ● |
| 2 | `web.login` | SEV1 | la web no responde en `/login` | ● |
| 2 | `worker.heartbeat` | SEV1 | el worker dejó de latir; lo reinicié | ● |

```bash
predigolctl alert-drill --list                         # todo lo que puede enviar, y el orden del registro
predigolctl alert-drill backup.offsite SEV1            # una gravedad que --all no envía
predigolctl alert-drill worker.heartbeat --reminder    # un SEV1 completo: apertura, recordatorio y recuperación
predigolctl alert-drill disk.usage SEV2 --hold 30      # un aviso completo; el «recuperado» llega a los 30 segundos
predigolctl alert-drill --all --pause 5                # el registro entero, un mensaje cada 5 segundos
```

Sin `--hold`, el «recuperado» llega a los 20 segundos y dice «tras 0 min»: es normal, el simulacro dura 20 segundos. Una
gravedad que el aviso nunca tiene (`disk.usage SEV3`) se rechaza antes de enviar nada.

## Tabla B · Los siete checks de Healthchecks

Healthchecks avisa por su propia integración con Telegram: otro remitente que nuestro bot, y no depende del servidor. El
simulacro envía el ping `/fail` del check (Healthchecks lo da por caído y te escribe) y, a los 20 segundos, el ping normal
(llega el «UP»). Las URLs de ping son secretos: no se imprimen en ningún sitio. Periodo y margen son los del plan.

| Check | Variable (`predigol.env`) | Aviso | Periodo · margen | Se provoca con |
|---|---|---|---|---|
| `health` | `HC_PING_HEALTH` | 3 | 5 min · 10 min | `predigolctl alert-drill --healthchecks health` |
| `backup` | `HC_PING_BACKUP` | 12 | 1 día · 2 h | `predigolctl alert-drill --healthchecks backup` |
| `restore-test` | `HC_PING_RESTORE_TEST` | 15 | 7 días · 6 h | `predigolctl alert-drill --healthchecks restore-test` |
| `raw-sync` | `HC_PING_RAW_SYNC` | 16 | el de su temporizador · un periodo | `predigolctl alert-drill --healthchecks raw-sync` |
| `pitr` | `HC_PING_PITR` | 12 | 1 día · 3 h | `predigolctl alert-drill --healthchecks pitr` |
| `pitr-test` | `HC_PING_PITR_TEST` | 15 | el de su temporizador · un periodo | `predigolctl alert-drill --healthchecks pitr-test` |
| `maint` | `HC_PING_MAINT` | 16 | 1 día · 2 h | `predigolctl alert-drill --healthchecks maint` |

`pitr` es la copia diaria del PITR, que también va a R2: por eso comparte el aviso 12 con `backup`. El simulacro prueba
el canal con el `/fail`; que Healthchecks también avisa cuando el latido **no llega** lo prueba el silencio del latido
(más abajo).

## Tabla C · Los avisos que se provocan fuera del servidor

Tres avisos no salen del servidor, así que `alert-drill` no los puede enviar. Se provocan de verdad, con un disparo
inocuo:

| # | Aviso | Cómo se provoca | Quién | Dónde llega | Cómo se deshace |
|---|---|---|---|---|---|
| 1 | La web no responde desde fuera | Un monitor temporal contra una ruta que no existe (`https://predigolai.com/simulacro-no-existe`; la sesión comprueba antes que responde 404). El monitor real sigue vigilando `/health` | Tú; la sesión te da los clics de tu monitor | Tu correo | Borras el monitor temporal |
| 7 | Excepción nueva | `predigolctl sentry-drill`: un error inventado, con huella propia, enviado con el SDK y los ajustes de la API. Sentry abre un issue nuevo (`SentryDrillError`) | La sesión | Tu correo (Sentry) | Marcas el issue como resuelto en Sentry |
| 33 | Secreto en un commit | Una rama de prueba con un secreto **inventado** y un pull request borrador hacia `main`: el paso de Gitleaks de la CI corre en los pull request, y falla | La sesión | Tu correo (GitHub avisa de la comprobación fallida) | Se cierra el pull request y se borra la rama; `main` no se toca |

El monitor mira cada pocos minutos (cada 5 en UptimeRobot Free) y avisa tras dos comprobaciones seguidas con fallo. Si tu
monitor externo es el de Sentry (el plan gratuito admite uno solo), no se crea otro: durante unos minutos se cambia la
dirección del único a la ruta que no existe y después se devuelve a `/health`. La sesión te lo dice clic a clic cuando
llegue el momento, y no se da por terminado hasta ver que `/health` vuelve a estar vigilado.

El secreto inventado es una línea `api_key = "…"` con 40 caracteres al azar, en un fichero fuera de las carpetas de pruebas:
la forma genérica que la autoprueba `security/selftest.sh` comprueba que Gitleaks bloquea, y que no es la de ningún
proveedor, para que ni GitHub ni nadie lo tome por una credencial real. La sesión lo hace en una copia aparte, no en tu
copia de trabajo, y para esa única confirmación se salta el gancho local de Gitleaks (`SKIP_GITLEAKS=1`).

## El orden de la sesión

**1. Tú, 15 minutos antes: el monitor temporal.** Lo creas como dice la fila 1 de la Tabla C. Es el aviso más lento (el
monitor tarda dos comprobaciones en avisar), así que va primero y lo demás se hace mientras tanto.

**2. La sesión: el canal.** Un mensaje de prueba, y otra vez el ensayo en seco del registro, justo antes de enviar. Tú
confirmas que el mensaje llegó.

```bash
predigolctl alert-test
predigolctl alert-drill --all --dry-run
```

**3. La sesión: el registro entero.** Los 36 mensajes de apertura, uno cada 3 segundos (unos 2 minutos). Si Telegram
rechaza tres seguidos, se detiene y dice cuáles faltan. Tú haces las capturas.

```bash
predigolctl alert-drill --all
```

**4. La sesión: dos avisos con su ciclo completo.** El SEV1 del worker con su recordatorio (el que en la vida real se repite
cada hora) y un SEV2 con su «recuperado».

```bash
predigolctl alert-drill worker.heartbeat --reminder
predigolctl alert-drill disk.usage SEV2
```

**5. La sesión: los siete checks de Healthchecks,** uno detrás de otro. Llega el «DOWN» y, a los 20 segundos, el «UP».

```bash
for c in health backup restore-test raw-sync pitr pitr-test maint; do predigolctl alert-drill --healthchecks "$c"; done
```

**6. La sesión: lo de fuera.** El error inventado de Sentry y el pull request de prueba de Gitleaks (Tabla C).

```bash
predigolctl sentry-drill
```

**7. Tú: el correo.** Esperas los tres correos (monitor, Sentry, GitHub) y haces una captura de cada uno con su hora a la
vista.

**8. La sesión: lo enviado, como filas del acta.**

```bash
predigolctl alert-drill --evidence
```

Cada simulacro deja una línea en `/srv/predigol/state/drills.jsonl` con la hora UTC del disparo y las etapas que Telegram
aceptó (apertura, recordatorio, recuperado). `--evidence` la muestra como filas, y de ahí sale la columna «Disparo» del
acta; la hora de «Recibido» sale de tus capturas.

## El silencio del latido (recomendado)

Es la única prueba de que el aviso llega **aunque el servidor no pueda avisar**: si el VPS muere, `healthcheck.sh` no
habla, y es Healthchecks quien se da cuenta de que dejó de recibir su latido. Se puede hacer en esta sesión o en otra.
Durante esos 15 minutos nadie vigila el servidor: la sesión lo vigila a mano y no se despliega nada.

```bash
systemd-run --on-active=17m systemctl start predigol-health.timer
systemctl stop predigol-health.timer
```

La primera línea es la red de seguridad: a los 17 minutos el temporizador vuelve a arrancar solo, pase lo que pase con la
sesión. Healthchecks da el check `health` por caído 15 minutos después del último latido (periodo de 5 minutos más margen de
10) y te escribe; al volver el latido, llega el «UP». En el acta (fila 3), el disparo es la hora de `systemctl stop` y el
límite es el margen del check, no los 10 minutos.

## Si un aviso no llega en 10 minutos

1. **¿Es el chat o es el aviso?** Mira que el bot no esté silenciado y que sea el chat correcto, y que el mensaje de
   `alert-test` sí esté.
2. **El servidor.** Si Telegram rechazó un mensaje, el comando termina con error y dice cuál «was NOT taken»; justo encima,
   curl da el código: 401 o 404 es un token malo o revocado; 400 o 403, que el bot no puede escribir en ese chat.
3. **Healthchecks.** En el panel del check, su historial debe mostrar el `/fail`. Si está y no llegó nada, falla la
   integración con Telegram (otro remitente que nuestro bot), no nuestro bot.
4. **El correo.** Mira la carpeta de spam, y el panel del monitor, de Sentry o la pestaña Actions de GitHub.
5. **Un aviso que no llega no se da por bueno.** Se corrige la causa y se repite solo ese aviso. El acta lleva la hora del
   segundo intento y una nota del fallo.

## Al terminar

* **Tú:** borras el monitor temporal y marcas como resuelto el issue de prueba de Sentry (un clic).
* **La sesión:** cierra el pull request y borra la rama de Gitleaks, y comprueba que el temporizador del monitor del
  servidor está activo y que los simulacros no dejaron incidentes.

```bash
systemctl is-active predigol-health.timer
predigolctl incident list
```

* El primer comando debe decir `active`. El segundo no debe mostrar ningún `INC-…-9NN`: los simulacros no abren
  incidentes reales.
* **La sesión** rellena el acta con las horas de `--evidence`, tus capturas y tus correos, y la guarda en el proyecto
  (`S3_ACTA_SIMULACROS_AAAAMMDD.md`). Aquí queda la hoja en blanco.

## Acta de simulacros

Esta es la hoja en blanco de los 34 avisos del catálogo. R03 se cierra cuando los 26 avisos de S3 tienen su «OK» y su
«Min» por debajo de 10 (los de Healthchecks, dentro de su margen). Los ocho avisos de fases posteriores (IA, S4, S9, S10 y
S11) se provocan al cerrar su fase y se suman a esta misma tabla.

Cada columna: **Disparo** = hora UTC del disparo (de `--evidence`); **Recibido** = hora UTC que se ve en tu captura (la del
móvil más 5 horas); **Min** = minutos entre las dos; **Canal** = bot del servidor, Healthchecks o correo; **Captura** = el
fichero de la captura; **OK** = sí, si llegó con su gravedad y sus palabras dentro del plazo.

| # | Aviso | Fase | Se dispara con | Disparo (UTC) | Recibido (UTC) | Min | Canal | Captura | OK |
|---|---|---|---|---|---|---|---|---|---|
| 1 | La web no responde desde fuera | S3 | Monitor temporal (Tabla C) |  |  |  |  |  |  |
| 2 | Un componente cae (API, web, worker o base) | S3 | `svc.<nombre>`, `web.health`, `web.login`, `worker.heartbeat` |  |  |  |  |  |  |
| 3 | El VPS deja de latir | S3 | Healthchecks `health`; el silencio del latido |  |  |  |  |  |  |
| 4 | Contenedor reiniciándose en bucle | S3 | `svc.<nombre>.loop` |  |  |  |  |  |  |
| 5 | Login roto | S3 | `api.login` |  |  |  |  |  |  |
| 6 | Errores 5xx | S3 | `web.errors5xx` |  |  |  |  |  |  |
| 7 | Excepción nueva | S3 | `predigolctl sentry-drill` (Tabla C) |  |  |  |  |  |  |
| 8 | Disco | S3 | `disk.usage` (SEV1 y SEV2), `disk.forecast` |  |  |  |  |  |  |
| 9 | Memoria, carga o CPU robada por el host | S3 | `host.resources` |  |  |  |  |  |  |
| 10 | Conexiones a PostgreSQL | S3 | `db.connections` |  |  |  |  |  |  |
| 11 | Certificado del origen | S3 | `tls.origin` |  |  |  |  |  |  |
| 12 | Copia diaria no llega a R2 | S3 | Healthchecks `backup`, `pitr` |  |  |  |  |  |  |
| 13 | Dump en R2 demasiado antiguo | S3 | `backup.offsite` |  |  |  |  |  |  |
| 14 | WAL del PITR atrasado | S3 | `pitr.wal` |  |  |  |  |  |  |
| 15 | Prueba de restauración o del PITR falla | S3 | `restore.test`, `pitr.test`; Healthchecks `restore-test`, `pitr-test` |  |  |  |  |  |  |
| 16 | Sync del RAW o mantenimiento no corren | S3 | `raw.sync`, `raw.full`; Healthchecks `raw-sync`, `maint` |  |  |  |  |  |  |
| 17 | Ingesta parada | S3 | `ingest.live`, `ingest.runs` |  |  |  |  |  |  |
| 18 | Cuota de API-Football | S3 | `provider.quota` |  |  |  |  |  |  |
| 19 | Resultados sin liquidar | S3 | `picks.unsettled`, `picks.review` |  |  |  |  |  |  |
| 20 | Errores o timeouts de la IA | IA | Al cerrar la fase de IA |  |  |  |  |  |  |
| 21 | Gasto de IA | IA | Al cerrar la fase de IA |  |  |  |  |  |  |
| 22 | La IA intenta subir un pick | IA | Al cerrar la fase de IA |  |  |  |  |  |  |
| 23 | Pico de logins fallidos | S3 | `auth.bruteforce` |  |  |  |  |  |  |
| 24 | Cuenta en espera de 60 min | S3 | `auth.locked` |  |  |  |  |  |  |
| 25 | Admin desde un dispositivo nuevo | S3 | `auth.newdevice` |  |  |  |  |  |  |
| 26 | Cambio de rol, nuevo SUPER_ADMIN, reset de MFA o de contraseña de otra cuenta | S3 | `auth.privileged` (SEV1 y SEV2) |  |  |  |  |  |  |
| 27 | Uso del modo sudo | S9 | Al cerrar S9 |  |  |  |  |  |  |
| 28 | Pico de 401 y 403 en rutas ADMIN | S3 | `admin.denied` |  |  |  |  |  |  |
| 29 | Pico de 429 por clase | S10 | Al cerrar S10 |  |  |  |  |  |  |
| 30 | Inicio de sesión SSH en el host | S4 | Al cerrar S4 |  |  |  |  |  |  |
| 31 | Orden rechazada en `predigol-ops` | S4 | Al cerrar S4 |  |  |  |  |  |  |
| 32 | Cambio en la configuración de seguridad | S3 | `config.drift` |  |  |  |  |  |  |
| 33 | Secreto en un commit | S3 | Rama de prueba de Gitleaks (Tabla C) |  |  |  |  |  |  |
| 34 | Vulnerabilidad crítica o alta en dependencias o imágenes | S11 | Al cerrar S11 |  |  |  |  |  |  |
