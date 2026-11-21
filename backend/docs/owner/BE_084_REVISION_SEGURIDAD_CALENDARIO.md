# BE-084 · Revisión de seguridad del testigo del calendario suscribible (PM-14-06)

Plan Maestro PM, tarea **PM-14-06** (OP-43). Estado: **código en `main` tras `FBI_CALENDAR_FEED` apagado; pendiente de aprobación de la
sesión de seguridad y del dueño.** Mientras no se apruebe este documento, el interruptor no se enciende.

Firmas que se piden al final (sección 8): sesión de seguridad y dueño.

## 1. Qué es

Un lector pide en su cuenta un **enlace secreto iCalendar** (`https://<dominio>/api/v1/calendar/feed/<secreto>.ics`) y lo pega en Google
Calendar, Apple Calendar u Outlook. El cliente de calendario lo lee cada pocas horas, sin sesión, y muestra los partidos de los equipos
que el lector sigue (`customer.favorites`, tipo `team`): 14 días atrás y 120 adelante, como mucho 400 partidos.

| Pieza | Dónde |
|---|---|
| Tabla `customer.calendar_feeds` (migración 0171) y permisos | `migrations/versions/0171_calendar_feeds.py`, `deploy/vps/db/grants.sql` |
| Secreto, huella, alta, revocación, última lectura, borrado | `src/fbi/customer/calendar_feed.py` |
| Archivo iCalendar (RFC 5545) | `src/fbi/api/services/calendar_feed.py` |
| Rutas | `src/fbi/api/routers/calendar_feed.py` (montadas en `src/fbi/api/app.py`) |
| Interruptor | `FBI_CALENDAR_FEED` en `src/fbi/api/switches.py` (apagado: todas las rutas responden 404) |

Rutas:

- `GET /api/v1/me/calendar-feed` (sesión, mismo sitio): si hay enlace vivo, desde cuándo, última lectura y cuántos equipos lleva. Nunca el secreto.
- `POST /api/v1/me/calendar-feed` (sesión, mismo sitio): enlace nuevo; el anterior queda revocado (`replaced`). El secreto va **solo** en esta respuesta (`path`).
- `DELETE /api/v1/me/calendar-feed` (sesión, mismo sitio): revoca (`reader`).
- `GET /api/v1/calendar/feed/{secreto}.ics` (**pública**, sin sesión ni cabecera de mismo sitio: un cliente de calendario no las lleva). El secreto es la autenticación.

## 2. El testigo, según buenas prácticas

| Requisito | Cómo se cumple |
|---|---|
| Aleatorio | `secrets.token_urlsafe(32)`: 32 bytes del generador del sistema operativo, 256 bits, 43 caracteres URL-safe. No deriva del id, del correo ni de la hora. |
| Guardado con hash | La fila guarda `link_sha256` (SHA-256 en 64 hex, único). El secreto no se guarda en ningún sitio. Con 256 bits de entropía no hace falta sal ni hash lento (el mismo criterio que `auth.account_tokens`, `fbi.auth.tokens.token_id`): una copia robada de la tabla no abre ningún calendario. |
| Revocable | El lector revoca cuando quiere; un enlace nuevo revoca el anterior en la misma transacción; el motivo `owner` queda para que el dueño revoque uno (hoy desde el contenedor con `fbi.customer.calendar_feed.revoke(..., why="owner")`; sin ruta de consola); anonimizar la cuenta borra todos sus enlaces (`fbi.auth.anonymize`, A7). Índice único parcial: como mucho **un enlace vivo por lector**. |
| Solo lectura | La ruta pública solo devuelve el archivo. No abre sesión, no cambia favoritos ni nada de la cuenta, no da acceso a ninguna otra ruta. Su única escritura es `last_read_at`, como mucho una vez por hora. |
| Sin datos personales en la URL | La URL lleva solo el secreto. Ni id de usuario, ni correo, ni nombre, ni equipos. |
| Sin datos personales ni de juego en el archivo | El archivo lleva partidos (equipos, competición, jornada, estadio, hora, estado). **No** lleva el nombre del lector (el calendario se llama «PrediGol · Mis equipos»), ni cuotas, probabilidades, picks, enlaces que inicien sesión ni correos. Lo vigila una prueba. |
| Respuesta indistinguible | Secreto mal formado, desconocido o revocado: el mismo 404. Un mal formado no llega a la base de datos. |
| Fuerza bruta | Inviable (2^256). Aun así, 20 fallos en 15 minutos por dirección dejan esa dirección en 429 el resto de la ventana (`MISSES`, en memoria de cada proceso de la API, como `fbi.auth.throttle`). |
| Tiempo constante | La búsqueda es por la huella en un índice único: el atacante no controla la preimagen, así que el tiempo no revela nada útil del secreto. |
| Cabeceras | `Cache-Control: no-store`, `Referrer-Policy: no-referrer`, `X-Content-Type-Options: nosniff` (de la API), `X-Robots-Tag: noindex, nofollow`, `Content-Type: text/calendar; charset=utf-8`. |
| Registros de la API | La línea `api.request` escribe la ruta con el secreto cambiado por `<secreto>` (`calendar_feed.redact`). Probado. |
| Derechos del lector | La exportación de datos (`/me/export`) lista sus enlaces (creado, revocado y motivo, última lectura), nunca el secreto ni su huella. |
| Permisos de base | `grants.sql`: la API puede INSERT, UPDATE, DELETE en `customer.calendar_feeds`; el worker no ve `customer` (probado en `test_db_roles.py`). |

## 3. Amenazas y lo que queda

| Amenaza | Mitigación | Riesgo que queda |
|---|---|---|
| El lector comparte o pierde el enlace | Revocación inmediata; la página le enseña la última lectura; el archivo vale poco (qué equipos sigue y sus partidos, que son públicos) | Quien tenga el enlace ve qué equipos sigue el lector hasta que lo revoque |
| El proveedor del calendario guarda la URL (Google, Apple, Microsoft) | Es la naturaleza del servicio y lo decide el lector; revocar corta las lecturas | El secreto vive en los servidores de ese proveedor. Texto informativo en la página (UX) antes de encender |
| **El registro de accesos de Caddy** (`/data/access.log`, JSON con la URI completa) | **Pendiente**: filtro de registro (sección 4). Es requisito para encender | Hoy el secreto quedaría en `access.log` (5 × 20 MiB, en el servidor) |
| Registros de Cloudflare (si hace de proxy) | Fuera de nuestro control; Cloudflare ve la URL como ve todo el tráfico | Aceptado si el dueño mantiene Cloudflare; anotarlo |
| Sentry | Las peticiones sin error no se envían; una excepción en esta ruta podría llevar la URL | Pedir a seguridad que confirme el filtro de datos de Sentry (`before_send`) o añadir la ruta |
| Inyección en el archivo (nombres de equipo raros del proveedor) | Escape de TEXT de RFC 5545 (barra, punto y coma, coma, saltos), sin caracteres de control, líneas plegadas a 75 octetos | Ninguno conocido |
| Carga (clientes que leen cada pocas horas) | Una consulta indexada de favoritos y otra de partidos con `LIMIT 400`; `REFRESH-INTERVAL` de 6 h | Si la carga crece: caché en memoria por huella (propuesta, no hecha) |
| CSRF / IDOR en la gestión | Rutas de gestión con sesión y `same_site_only`; solo actúan sobre la cuenta de la sesión | Ninguno conocido |
| Carrera al crear dos a la vez | Índice único parcial; la segunda recibe 409 `calendar_feed_busy` | Ninguno |
| Enlaces olvidados | — | Propuesta: revocar solo los enlaces sin lectura en 12 meses (decisión del dueño) |

## 4. Lo que pide a la sesión de seguridad (antes de encender)

1. **Filtro del registro de Caddy** (zona de seguridad y despliegue: no se toca en este PR). Propuesta para el bloque `log` de
   `deploy/vps/Caddyfile`, a validar con `caddy validate` en la versión instalada:

   ```
   log {
   	output file /data/access.log {
   		roll_size 20MiB
   		roll_keep 5
   	}
   	format filter {
   		wrap json
   		fields {
   			request>uri regexp "^/api/v1/calendar/feed/[A-Za-z0-9_-]+\.ics" "/api/v1/calendar/feed/<secreto>.ics"
   		}
   	}
   }
   ```

2. Confirmar que Sentry no recibe la URL de esta ruta (o añadir el mismo cambio por `<secreto>` en su `before_send`).
3. Aprobar los requisitos de la sección 2 y el riesgo que queda de la sección 3 (Cloudflare, proveedor del calendario).
4. Decidir la caducidad por falta de uso (opcional).

## 5. Lo que pide al dueño

- Aprobar la revisión (sección 8).
- El texto informativo de la página (UX): «Cualquiera con este enlace ve los partidos de tus equipos. Tu calendario (Google, Apple,
  Microsoft) lo guarda. Puedes revocarlo cuando quieras.» Si el abogado lo pide, dentro de la consulta DM-08 («encargados en el
  extranjero»): el lector entrega la URL a su proveedor de calendario por decisión propia.
- Validar la suscripción en los tres clientes en preproducción o con su cuenta (Google Calendar «Desde URL», Apple Calendar «Nueva
  suscripción», Outlook «Suscribirse desde la web»).

## 6. Cómo se probó

- `tests/unit/test_calendar_feed.py`: secreto de 256 bits y solo huella; secretos mal formados rechazados sin tocar la base;
  interruptor apagado por omisión; el secreto no llega al registro; el archivo pasa las comprobaciones de RFC 5545 que aplican los
  clientes (CRLF, líneas ≤ 75 octetos sin partir caracteres UTF-8, VCALENDAR, VERSION, PRODID, cada VEVENT con UID, DTSTAMP, DTSTART y
  SUMMARY), estados (confirmado, por definir, aplazado o cancelado), escape y nada de cuotas, probabilidades, picks ni enlaces.
- `tests/integration/test_calendar_feed_api.py` (PostgreSQL 16): apagado, 404 en todo; encendido, el enlace lee solo los partidos de
  los equipos seguidos y en la ventana, la base guarda solo la huella, un enlace nuevo revoca el anterior, revocar lo corta, otro lector
  no ve el enlace, 20 fallos dan 429, la exportación no lleva el secreto ni la huella, anonimizar borra los enlaces.
- Archivo de 50 partidos leído sin errores por la biblioteca `icalendar` 6.1.0 (lectura externa, fuera del repositorio).
- La validación en Google, Apple y Outlook queda para el dueño (sección 5): no se puede hacer sin una cuenta y el interruptor encendido.

## 7. Encendido y vuelta atrás

Encender (PM-15-03, con kit auditado): filtro de Caddy aplicado y comprobado; copia fechada de `app.env`; `FBI_CALENDAR_FEED=1`;
`predigolctl up`. La página de la cuenta (UX, `web/src/product/profile/`) se construye después de esta aprobación, con el texto de la
sección 5. Vuelta atrás: `FBI_CALENDAR_FEED=0` y `predigolctl up` (todas las rutas vuelven a 404 al instante; los enlaces quedan en la
tabla sin lector y valen de nuevo si se vuelve a encender; para invalidarlos todos, revocarlos con `revoked_why = 'owner'`).
La tabla no se borra.

## 8. Aprobaciones

| Quién | Decisión | Fecha |
|---|---|---|
| Sesión de seguridad | pendiente | |
| Dueño | pendiente | |
