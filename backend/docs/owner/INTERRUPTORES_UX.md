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
| `FBI_SIGNUP` | UX-038 | API | Que una persona cree su propia cuenta (`/register`) y confirme su correo. Solo abre si además están el correo (`FBI_SELF_SERVICE`), la puerta de consentimientos final (`FBI_CONSENT_GATE=1` y sin textos en borrador) y la membresía exigida (`FBI_MEMBERSHIP_ENFORCE=1`); si falta algo, la puerta sigue cerrada y la web no ofrece «Crear cuenta». Guía `REGISTRO_PROPIO_UX_038.md` | Textos legales definitivos (P5), correo con su prueba real, y la solicitud de acceso con pago manual lista |
| `FBI_SIGNUP_DAILY_CAP`, `FBI_SIGNUP_PURGE` | UX-038 | API y mensajero | El tope diario de cuentas nuevas (100 si falta; al llegar, la puerta se pausa sola) y el cierre de las cuentas que nunca confirmaron su correo en siete días (`dry` cuenta, `on` cierra, `off` no hace nada) | Opcionales; `FBI_SIGNUP_PURGE=on` tras mirar un par de días el conteo en `dry` |
| `FBI_PRODUCT_EVENTS` | A6 | API y mensajero | Registrar el uso (`consent` solo con quien lo permite, `on` a todos) | La casilla de analítica ya existe (UX-008); queda la decisión del abogado (P5) para `on` |
| `FBI_MEMBERSHIP_ENFORCE` | A8 | API | Que una membresía vencida limite el acceso | Precio y términos listos (P6) y cada cuenta con su periodo |
| `FBI_SUPPORT_WHATSAPP` | A8, A14 | API | El botón de renovar, el contacto de Ayuda y los correos de membresía | P7 (el número, solo dígitos con el prefijo del país) |
| `FBI_AI_USER_MONTHLY_BUDGET_USD`, `FBI_USER_NARRATIVE` | A11, UX-025 | Worker y API | La crónica de cada partido escrita con IA (`shadow` y luego `on`; guía `CRONICA_UX_025.md`) | P8 (presupuesto de 20 US$ aprobado) y la revisión de unas 50 crónicas |
| `FBI_TRANSPARENCY` | A12 | API | La página de Transparencia para los lectores | P9 (el dueño la revisa) |
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
