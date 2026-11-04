# A5 · Email transaccional y messenger

Plan Maestro UX, fase A5 (migración **0096**; el plan la numeró 0095, que tomó A4). El correo nace **apagado**: con el
interruptor `FBI_EMAIL_SEND` apagado la cola se llena y **no sale nada**. Se enciende solo después de tus acciones P2,
P3 y P14 y de una prueba real a Gmail y a Outlook.

## 1. Qué cambia para un lector

| Dónde | Qué ve |
| --- | --- |
| Perfil → **Notificaciones** | Qué correos le enviamos, por categoría. **Siempre** llegan los de su cuenta, su seguridad, sus solicitudes sobre sus datos y los cambios de los textos legales; **membresía** (A8) y **soporte** (A14) los puede apagar. Si su correo rebotó o marcó un correo nuestro como spam, el bloque se lo dice y por qué no le llega nada. El aviso en el teléfono (push) llega en B7. |
| Su correo | Cuando abre una solicitud de privacidad: el acuse con su número y la fecha límite legal; cuando respondes: el aviso de que hay respuesta. **Nunca** se copian en el correo sus palabras ni las tuyas: el botón lleva a su perfil (`/profile#privacy`), donde las lee con su sesión. Cuando un texto legal cambie de forma importante (ya publicado y con la puerta de consentimiento encendida): un aviso con qué cambió. |

Los correos son de una columna, con texto de 16 px y un botón de 44 px, en español o inglés según su cuenta; sin
imágenes, sin píxel de apertura y sin enlaces rastreados.

## 2. Qué cambia para ti

- **Consola → Mensajes** (`/admin/messages`, junto a Usuarios): si el envío está encendido, cuántos salieron hoy de cuántos
  permitidos, los últimos 7 días por estado (en cola, enviado, falló, rebotó, marcado como spam, no enviado) y los
  últimos mensajes: a quién, qué plantilla, su estado, los intentos y el código corto del error del proveedor. **Ver**
  muestra el mensaje como saldría ahora (asunto, texto y el enlace del botón).
- **Avisos nuevos** (te llegan por el canal de avisos cuando esté P14; mientras tanto quedan en la consola como
  «skipped»): solo recuentos y un enlace a la consola, **nunca** el correo, el alias ni las palabras de un lector.

| Aviso | Cuándo |
| --- | --- |
| `ticket_new` | Llegó una solicitud nueva (privacidad hoy; soporte desde A14), con el plazo más cercano |
| `privacy_due` | Una vez al día mientras haya solicitudes de privacidad a 3 días hábiles o menos de su plazo legal, o ya vencidas |
| `outbox_failing` | Una vez al día si fallaron correos en 24 h, si hay correos esperando más de 1 h con el envío encendido, o si el envío está encendido sin clave de Resend |
| `synthetic_failed` | El recorrido sintético falló 2 veces seguidas (una vez por racha) |
| `membership_due`, `ai_user_budget` | Reservados: los escriben A8 y A11 |

- **El messenger** es un proceso propio (contenedor `predigol-messenger`, la misma imagen del backend) con el **rol de
  la API** en la base de datos: no lee nada de PrediGol Intelligence (una prueba lo comprueba), y el worker no puede
  leer la cola ni las preferencias. Trabaja en ciclos de 5 minutos, cada uno una fila del registro de trabajos
  (`messenger_cycle`, en la página Sistema); si se cae, el vigilante de corridas lo cierra y te avisa
  (`run_recovered`), y tres ciclos fallidos seguidos son un `job_failing`.
- **Reintentos:** 1 min, 5 min, 30 min, 2 h y 12 h; después, «falló». Un rechazo definitivo (dirección inválida) falla
  al momento; un problema de la clave o del dominio para la tanda y espera (te llega `outbox_failing`); la cuota diaria
  de Resend espera a la medianoche UTC sin gastar intentos. Tope propio: **90 correos al día** (Resend Free permite 100).
- **Rebotes y quejas:** el webhook firmado de Resend marca el mensaje y la dirección; a una dirección que rebotó no se
  le envía nada más, y a una que marcó spam solo lo imprescindible (cuenta, seguridad, privacidad, legal).

## 3. Lo que necesito de ti (cuando toque encenderlo; no antes)

- **P2 · Resend (Free)** — si no la creaste ya en la tarea S0-4 del plan de seguridad:
  1. Crea la cuenta y activa su verificación en dos pasos.
  2. *Domains → Add domain*: un **subdominio de envío**, por ejemplo `correo.predigolai.com` (dime cuál por el chat:
     no es secreto). En *Domain settings* deja **apagados** el seguimiento de aperturas y de clics.
  3. *API Keys → Create*: permiso **Sending access**, limitado a ese dominio. No la pegues en el chat.
  4. *Webhooks → Add endpoint*: `https://predigolai.com/api/v1/webhooks/resend`, con los eventos `email.bounced`,
     `email.complained`, `email.suppressed` y `email.failed`. Copia su *signing secret* (`whsec_…`). Tampoco al chat.
- **P3 · DNS:** en el panel DNS vigente (Hostinger hoy; Cloudflare si el plan de seguridad ya lo movió) crea los
  registros SPF y DKIM que Resend muestre para el subdominio y un DMARC con `p=none`
  (`_dmarc.predigolai.com TXT "v=DMARC1; p=none; rua=mailto:<tu correo>"`). Mándame una captura o confírmalo: lo
  compruebo con una consulta DNS pública.
- **P14 · Canal de avisos (Telegram):** es S3 del plan de seguridad; cuando esté, los avisos de la sección 2 te llegan.
- **Las claves**, en `/etc/predigol/app.env` y nunca en el chat (fichero del plan de seguridad: copia fechada antes,
  candado de despliegue y una ventana propia, como los otros editores):
  `FBI_EMAIL_FROM="PrediGol <avisos@correo.predigolai.com>"`, `FBI_RESEND_API_KEY=…`, `FBI_RESEND_WEBHOOK_SECRET=…` y,
  al final, `FBI_EMAIL_SEND=1`. Se recrean la API (lee el secreto del webhook) y el messenger.

## 4. La prueba real (criterio de terminado de A5)

1. Con el envío encendido: `python -m scripts.email_test queue --user <tu correo de Gmail>` (en el contenedor de
   operaciones) pone en la cola el mensaje de ejemplo para tu cuenta; `python -m scripts.email_test status <id>` dice
   si salió. En Gmail, *Mostrar original*: `SPF: PASS`, `DKIM: PASS`, `DMARC: PASS`. Lo mismo con una cuenta de
   prueba con dirección de Outlook.
2. **Un rebote marcado por el webhook:** una cuenta de prueba con la dirección `bounced@resend.dev` (la de pruebas de
   Resend), su mensaje de ejemplo y, en la consola, el mensaje en «Rebotó» y la cuenta con su correo bloqueado. Luego
   esa cuenta se desactiva.
3. Cada envío queda en la cola con su estado; los avisos nuevos te llegan por Telegram.

## 5. Vuelta atrás

`FBI_EMAIL_SEND=0` en `app.env` y recrear el messenger (la cola se conserva y nada sale), o
`docker compose stop messenger`. El código vuelve atrás con el despliegue anterior; la migración 0096 solo se deshace
mientras la cola y las preferencias estén vacías (un correo enviado es un registro).

## 6. Privacidad

- Se guarda de cada mensaje: plantilla, idioma, sus parámetros cortos (número de solicitud, plazo, documento), estado,
  intentos, id del proveedor y código del último error. **No** se guardan el cuerpo, el nombre ni la dirección (se
  leen de la cuenta al enviar), ni secretos ni tokens (el código los rechaza).
- Resend recibe la dirección, el asunto y el cuerpo de cada mensaje: es un **encargado** que debe figurar en la
  política de tratamiento (tema 3 del abogado, P5: transmisión o transferencia internacional).
- Conservación prevista de la cola: 12 meses. La purga **no es automática**: se construye antes de que la primera fila
  cumpla 12 meses y se ejecuta con tu visto bueno, como manda el plan para todo borrado.
