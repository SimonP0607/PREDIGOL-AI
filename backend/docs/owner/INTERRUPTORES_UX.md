# Interruptores de la capa de usuario (plan de cierre UX, fase 0 · UX-003)

*Un solo lugar para saber qué está encendido, qué nace apagado y qué tarea del dueño lo enciende. Las explicaciones largas están
en la guía de cada fase; aquí solo está el mapa. Los valores reales viven en `/etc/predigol/app.env` (root, 600) y nunca en Git ni en
un chat. La plantilla con todas las líneas es `deploy/vps/app.env.example`; una prueba (`tests/unit/test_user_layer_map.py`) impide
que una variable de esta tabla falte en la plantilla o desaparezca del código.*

## Cómo se cambia uno

1. Editar la línea en `/etc/predigol/app.env` (con la copia fechada y el candado de siempre).
2. Recrear lo que la lee, según la columna «Lo lee»: `predigolctl up` recrea lo que cambió. Cada guía dice qué contenedores.
3. Comprobar en la app (con la cuenta del dueño) que se ve lo que debe y anotarlo en el estado del plan.

Los secretos (claves de Resend, de Sentry, VAPID, tokens) se escriben en el servidor, nunca se pegan en el chat.

## Los que nacen apagados

| Interruptor | Fase | Lo lee | Qué enciende | Se enciende con |
| --- | --- | --- | --- | --- |
| `FBI_CONSENT_GATE` | A4 | API | Las cuatro casillas al primer ingreso y ante un cambio material de los textos | El abogado revisa los textos (P5) y se publica una versión con `draft: false`. `drafts` es solo para QA |
| `FBI_EMAIL_SEND` | A5 | Mensajero | Que los correos de la cola salgan por Resend | Resend y DNS (P2, P3) y la prueba a Gmail y Outlook |
| `FBI_RESEND_API_KEY`, `FBI_RESEND_WEBHOOK_SECRET` | A5 | Mensajero (clave), API (webhook) | La clave de envío y el secreto de los rebotes | P2 |
| `FBI_EMAIL_FROM`, `FBI_EMAIL_REPLY_TO` | A5 | Mensajero | Remitente en el subdominio de envío y dirección de respuesta | P2, P3 |
| `FBI_SELF_SERVICE` | A7 | API y mensajero | Invitaciones, recuperar contraseña y desbloqueo por enlace | Cuando el correo ya pasó su prueba real |
| `FBI_SIGNUP` | UX-038 | API | Que una persona cree su propia cuenta (`/register`) y confirme su correo. Solo abre si además están el correo (`FBI_SELF_SERVICE`), la puerta de consentimientos final (`FBI_CONSENT_GATE=1` y sin textos en borrador), la membresía exigida (`FBI_MEMBERSHIP_ENFORCE=1`) y el pago listo (titular y llave Bre-B o QR, un precio y los términos de compra sin borrador: lo mismo que mantiene cerrado el «ya pagué», UX-099); si falta algo, la puerta sigue cerrada y la web no ofrece «Crear cuenta». Guía `REGISTRO_PROPIO_UX_038.md` | Textos legales definitivos (P5), correo con su prueba real, y la solicitud de acceso con pago manual lista |
| `FBI_SIGNUP_DAILY_CAP`, `FBI_SIGNUP_PURGE` | UX-038 | API y mensajero | El tope diario de cuentas nuevas (100 si falta; al llegar, la puerta se pausa sola) y el cierre de las cuentas que nunca confirmaron su correo en siete días (`dry` cuenta, `on` cierra, `off` no hace nada) | Opcionales; `FBI_SIGNUP_PURGE=on` tras mirar un par de días el conteo en `dry` |
| `FBI_PRODUCT_EVENTS` | A6 | API y mensajero | Registrar el uso (`consent` solo con quien lo permite, `on` a todos) | La casilla de analítica ya existe (UX-008); queda la decisión del abogado (P5) para `on` |
| `FBI_MEMBERSHIP_ENFORCE` | A8 | API | Que una membresía vencida, suspendida o inexistente limite el acceso | Precio y términos listos (P6) y cada cuenta viva con su periodo: desde UX-063 una cuenta sin periodo también queda limitada (403 `membership_required`), porque quien se registra no recibe prueba gratis; para las cuentas que ya existían, `python -m scripts.accounts grant-trial --days N --reason «…» --apply` (UX-086) les da una prueba temporal sin tocar a nadie más |
| `FBI_SUPPORT_WHATSAPP` | A8, A14 | API | El botón de renovar, el contacto de Ayuda y los correos de membresía | P7 (el número, solo dígitos con el prefijo del país) |
| `FBI_PAYMENT_HOLDER`, `FBI_PAYMENT_BREB_KEY`, `FBI_PAYMENT_QR_FILE` | UX-090 | API | Los datos para pagar: el nombre del titular, la llave Bre-B y la imagen del QR de Nequi (una ruta como `/app/data/payment/nequi.png`; la imagen va en `/srv/predigol/payment/` del servidor, PNG, JPG o WebP de hasta 2 MB). Mientras falten (el titular y, al menos, la llave o el QR), el precio o los términos de compra definitivos, el aviso «ya pagué» no se abre y la web no muestra ningún dato de pago | El dueño: titular, llave y QR; el abogado: términos de compra definitivos (P5) |
| `FBI_AI_USER_MONTHLY_BUDGET_USD`, `FBI_USER_NARRATIVE` | A11, UX-025 | Worker y API | La crónica de cada partido escrita con IA (`shadow` y luego `on`; guía `CRONICA_UX_025.md`) | P8 (presupuesto de 20 US$ aprobado) y la revisión de unas 50 crónicas |
| `FBI_TRANSPARENCY` | A12 | API | La página de Transparencia para los lectores | P9 (el dueño la revisa) |
| `FBI_ODDS_STATUS` | Plan maestro 2026, ola 8 (BE-038, UX-123) | API | «Estado de los precios» (`/odds/status`) y su enlace desde Cuotas | Cuando el dueño lo revise en producción; tiene más sentido junto al explorador de Cuotas (`FBI_ODDS_EXPLORER`) |
| `FBI_HELP_ASSISTANT` | Plan maestro 2026, ola 11 (UX-128) | API | El asistente de Ayuda: responde solo con el contenido de Ayuda y del glosario; nunca sobre un pick ni una apuesta | El dueño revisa sus textos |
| `FBI_TELEGRAM_CHANNEL_URL` | Plan maestro 2026, ola 11 (UX-128) | API | El canal oficial de Telegram en el contacto de Ayuda. Solo aparece con el enlace público (`https://t.me/…`) **y** con `telegram` en `FBI_SUPPORT_CHANNELS` | El dueño tiene el enlace oficial del canal (es público: no es un secreto) |
| `FBI_NEWS_FEED` | Plan maestro 2026, ola 13 (BE-040, UX-130) | API | La sección Noticias (`/news`) y su entrada en «Más» | Hay noticias reales leyéndose (`FBI_NEWS_USERS` encendido) y el dueño la revisó |
| `FBI_INBOX` | Plan maestro 2026, ola 14 (BE-041, UX-131) | API y mensajero | La bandeja de Avisos (`/inbox`) y la campana: lo que ya se envió al lector, con leído y sin leer | La migración 0137 ya está desplegada y el dueño la revisó |
| `FBI_ODDS_BY_MATCH` | Plan maestro unificado (BE-045, UX-141) | API | Cuotas abre en la vista «Por partido» (láminas C01, C02, C06) con «Mi parlay» al lado; el explorador por familias sigue a un toque («Por mercado») | La sesión UX lo enciende tras verificarlo (cubierto por la aprobación del plan del 16-nov-2026). **Encendido el 16-nov-2026, 22:41 UTC** |
| `FBI_NAV_V2` | Plan maestro unificado (BE-045, UX-152) | API | Barra del teléfono Inicio · Partidos · Noticias · Picks · Más y la barra de escritorio nueva (D-01, D-02) | Aprobado (D-01, D-02); se enciende tras verificarlo. **Encendido el 16-nov-2026, 22:41 UTC** |
| `FBI_SEARCH` | Plan maestro unificado (BE-045, UX-153) | API | El buscador global del lector en la barra superior (maqueta 14) | Se enciende tras verificarlo. **Encendido el 16-nov-2026, 22:41 UTC** |
| `FBI_PROFILES` | Plan maestro unificado (BE-045, UX-154 a UX-157) | API | Las páginas de club, selección y jugador, y «Equipos» (maquetas 11–13, D-03) | Se enciende tras verificarlo con datos reales. **Encendido el 16-nov-2026, 22:41 UTC** |
| `FBI_NEWS_V2` | Plan maestro unificado (BE-045, UX-158 a UX-161) | API | Noticias como la dibujan las maquetas 08–10; solo con `FBI_NEWS_FEED` | Datos, derechos y pruebas listos |
| `FBI_MATCH_INTELLIGENCE` | Plan maestro unificado (BE-045, UX-162 a UX-166) | API | La pestaña «Intelligence» del partido para lectores (proyección pública del contrato C-01) | **El dueño**, con la autorización de publicación de Intelligence |
| `FBI_STATS_AGG` | Plan de estadísticas avanzadas (EA-003 a EA-006) | Worker | El cálculo nocturno (07:20 UTC) de los documentos de estadísticas en `analytics.stat_documents` (migración 0167): percentiles, pulso, goles por intervalo, supervivencia del 0-0, estados de partido y tendencias. Solo base de datos; no pregunta nada al proveedor ni usa IA | Primero del orden aprobado (D-EA-3): tras desplegar la migración 0167 |
| `FBI_STATS_V2` | Plan de estadísticas avanzadas (EA-102 a EA-107, EA-203; C-13) | API | Perfiles avanzados de equipo y jugador, comparaciones y las estadísticas del partido (maquetas V2·1 a V2·7 y V2·11) | Tras una pasada nocturna completa y la verificación (D-EA-3) |
| `FBI_MARKET_PROBS` | Plan de estadísticas avanzadas (EA-201, EA-202; C-14) | API | Las probabilidades por mercado en «Mercados» (V2·8): modelo solo en mercados evaluables; lo que está en calibración, solo para el dueño (D-EA-2) | Tras verificarlo (D-EA-3) |
| `FBI_PARLAY_MARKETS_V2` | Plan de estadísticas avanzadas (EA-501 a EA-503) | API | Mi parlay acepta los mercados que el catálogo IA-070 puede liquidar, con precio vigente y 3 casas; sin cambiar su diseño ni sus reglas | Tras verificar la liquidación (D-EA-3) |
| `FBI_PLAYER_MARKETS` | Plan de estadísticas avanzadas (EA-306, EA-401; C-15) | API | Los mercados de jugador del partido y el explorador «Jugadores»; la cifra del motor de jugadores, solo para el dueño | Último del orden; solo cuando el catálogo lo permita (D-EA-3) |
| `FBI_DIGEST`, `FBI_DIGEST_FROM` | B8 | API y mensajero | El resumen semanal para quien lo pide | Correo encendido y un remitente en otro dominio (P3) |
| `FBI_VAPID_PRIVATE_KEY` | B7 | API y mensajero | Los avisos en el dispositivo (sin la clave no se ofrece nada) | P12 |
| `FBI_VAPID_SUBJECT` | B7 | API y mensajero | El contacto (`mailto:` o `https:`) que ven los servicios de push; si falta, la dirección pública de la web | Opcional, con P12 |
| `FBI_SENTRY_DSN`, `FBI_SENTRY_WEB_DSN` | A2 | API, worker, mensajero | Enviar errores a Sentry (el de la web nunca llega al navegador) | P1 |
| `FBI_SYNTHETIC_BASE_URL`, `FBI_SYNTHETIC_EMAIL`, `FBI_SYNTHETIC_PASSWORD` | A2 | Worker | El recorrido de un lector de prueba cada 15 minutos | Una cuenta de lector dedicada, creada por el dueño |
| `FBI_TELEGRAM_BOT_TOKEN`, `FBI_TELEGRAM_CHAT_ID` | S3 | API y worker | Los avisos de la app al dueño | P14: primero `FBI_NOTIFY_PICKS=off` (siguiente fila), después el token y el chat |
| `FBI_NOTIFY_PICKS` | UX-023 | Worker | `off` deja fuera de tu chat los avisos de picks en sombra y de liquidación; los de tickets, vencimientos y operación siguen. Encendido por defecto | Ponlo en `off` **antes** de dar el token (P14). Lo ya apuntado sobre picks queda en cola sin tocarse; volver a `on` los enviaría |

## Los que nacen encendidos (se apagan con `=0`, sin desplegar)

`FBI_ONBOARDING` y `FBI_PERSONALIZATION` (A13) · `FBI_GUIDES` (UX-032, el recorrido y las guías de cada pantalla) · `FBI_SUPPORT` (A14) · `FBI_FEEDBACK` (B6) · `FBI_PUSH` (B7, sin efecto sin clave) ·
`FBI_EXPLAIN` (B9) · `FBI_LIFECYCLE` (B11) · `FBI_FORECAST_USERS`, `FBI_CALENDAR_USERS`, `FBI_KNOWLEDGE_USERS`,
`FBI_READING_USERS`, `FBI_NEWS_USERS` (A9, A10).

## Con valor fijo o en seco

| Variable | Valor si falta | Qué controla |
| --- | --- | --- |
| `FBI_EVENTS_PURGE` | `dry` | Contar sin borrar; `on` borra a los 90 días (eventos) y 13 meses (totales), también feedback, avisos y estados |
| `FBI_LINKS_PURGE` | `dry` | Los enlaces de un solo uso ya vencidos |
| `FBI_EMAIL_DAILY_CAP` | 90 | Correos por día (Resend gratis envía 100) |
| `FBI_DIGEST_DAILY_CAP` | 30 | Resúmenes por día |
| `FBI_TRIAL_DAYS` | 20 | Prueba de una cuenta nueva, entre 7 y 20 |
| `FBI_MEMBERSHIP_PRICE_COP` | 150000 | Precio mensual en pesos colombianos que ve el lector; `0` o `off` esconde esa moneda |
| `FBI_MEMBERSHIP_PRICE_USD` | 50 | Precio mensual en dólares que ve el lector; `0` o `off` esconde esa moneda |
| `FBI_LOYALTY_PERCENT` | 20 | Descuento por fidelidad que propone la consola en cada pago de quien ya pagó los meses indicados; `0` o `off` lo apaga |
| `FBI_LOYALTY_AFTER_MONTHS` | 2 | Meses pagados (de 1 a 24) desde los que aplica el descuento por fidelidad |
| `FBI_MEMBERSHIP_CURRENCY` | COP | Moneda que propone la consola al registrar un pago |
| `FBI_USER_NARRATIVE_MINUTES` | 10 | Cada cuánto el worker busca narrativas por escribir |
| `FBI_PRODUCT_MIN_SUBJECTS` | 20 | Lectores activos mínimos para mostrar cifras globales |
| `FBI_EVENTS_RATE_LIMIT` | 120 | Eventos por minuto y cliente |
| `FBI_MONITORING_RATE_LIMIT`, `FBI_MONITORING_HOURLY_CAP`, `FBI_MONITORING_DAILY_CAP` | 20 · 10 · 20 | Lo que deja pasar el túnel de Sentry de la web |
| `FBI_SENTRY_ENVIRONMENT` | `FBI_ENV` (production en el servidor) | La etiqueta de entorno de los dos proyectos de Sentry |

## Lo que no está en `app.env`

`FBI_WEB_BASE_URL` (que arma los enlaces de los correos) y `FBI_API_CORS_ORIGINS` salen del compose: `https://${PREDIGOL_DOMAIN}`, con
`PREDIGOL_DOMAIN` en `/etc/predigol/predigol.env`. La versión que ven Sentry y el soporte sale de la imagen de la web
(`VITE_APP_VERSION`, el argumento de construcción que pone `PREDIGOL_WEB_VERSION`).

## Estado en producción (5-nov-2026)

En `app.env` no hay ninguna línea de esta capa: todo corre con el valor por defecto. Es decir, los de «nacen apagados» siguen apagados y
los de «nacen encendidos» siguen encendidos. Comprobado leyendo solo los nombres de las variables, nunca sus valores.

## Estado en producción (16-nov-2026)

El dueño aprobó encender las funciones del plan maestro UX/UI 2026. Desde el 16-nov-2026 a las 00:58 UTC `app.env` lleva
`FBI_ODDS_STATUS`, `FBI_HELP_ASSISTANT`, `FBI_NEWS_FEED` y `FBI_INBOX` encendidos (copia fechada
`app.env.before-ux-flags-20261116T005809Z`; se recrearon la API y el mensajero, no el worker; referencia de configuración
tomada al final). Comprobado dentro de los contenedores y, con la sesión del dueño, en `/auth/me` y en cada pantalla.
`FBI_TELEGRAM_CHANNEL_URL` sigue sin línea: falta el enlace oficial del canal. `FBI_PICKS_SOURCE` sigue sin línea (apagado).
Para volver atrás: quitar la línea (o `=0`) y recrear la API y el mensajero.

Desde el 16-nov-2026 a las 22:41 UTC, con la aprobación del plan maestro unificado (decisiones D-01 a D-03), `app.env` lleva
además `FBI_ODDS_BY_MATCH`, `FBI_NAV_V2`, `FBI_SEARCH` y `FBI_PROFILES` encendidos (copia fechada
`app.env.before-ux-unified-20261116T224053Z`; bajo el candado de despliegue; se recrearon la API y el mensajero, no el worker;
referencia de configuración tomada al final). Comprobado dentro del contenedor (`fbi.api.switches`) y, con la sesión del dueño,
en `/auth/me`, Inicio, Cuotas «Por partido», Equipos, el buscador y un perfil de club y de jugador con datos reales.
Siguen sin línea (apagados): `FBI_NEWS_V2` (abogado, datos y derechos), `FBI_MATCH_INTELLIGENCE` (decisión del dueño),
`FBI_TRANSPARENCY` (D-05) y `FBI_PICKS_SOURCE`. Para volver atrás, lo mismo: quitar la línea (o `=0`) y recrear la API y el
mensajero; con `FBI_NAV_V2` apagado vuelve la barra de siempre y con `FBI_ODDS_BY_MATCH` apagado, el explorador de Cuotas.
