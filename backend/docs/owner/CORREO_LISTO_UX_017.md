# UX-017 · Correo listo para encender

Plan de cierre de la UX, tarea 4.1. **Una migración (0123), sin interruptor nuevo, sin IA y sin servicios externos nuevos.** Se
añaden las plantillas de correo que faltaban, una categoría que el lector puede apagar («Avisos del servicio»), un tope propio
para esa categoría y el recordatorio de activación a las 72 horas. **El correo sigue apagado**: con `FBI_EMAIL_SEND` apagado la
cola se llena y no sale nada, y esta tarea no lo enciende. Lo que sí deja es todo lo que se necesita para encenderlo: las
plantillas, los topes, el buzón de pruebas y la tabla de DNS exacta de abajo.

> Estado de esta entrega: **hecho en código; no desplegado.** Hasta que se despliegue y tú hagas P2 y P3, ningún lector recibe
> ninguno de estos correos.

## 1. Qué cambia para un lector

Siete correos nuevos, cada uno en español o inglés según su cuenta, con la misma forma de siempre (una columna, texto de 16 px,
botón de 44 px, sin imágenes ni píxel de apertura ni enlaces rastreados):

| Correo | Categoría | Cuándo sale | ¿Lo puede apagar? |
| --- | --- | --- | --- |
| **Bienvenida** | Tu cuenta | Al activar su cuenta desde la invitación. Dice cuándo termina su prueba (un solo correo, no dos) y que PrediGol no garantiza resultados. | No |
| **Recordatorio de activación** | Tu cuenta | **Uno solo**, 72 horas después de que salió la invitación, si todavía no la usó. Lleva el **mismo enlace** de la invitación y caduca igual (7 días desde que salió): no lo alarga. | No |
| **Inicio de la prueba** | Membresía | Cuando tú le das una prueba a una cuenta que ya existía y no la tenía. Dice hasta cuándo. | Sí |
| **Pago registrado / membresía renovada** | Membresía | Cuando registras su pago. Dice hasta cuándo queda activa. Un clic repetido no manda dos. | Sí |
| **Mantenimiento programado** | Avisos del servicio | Cuando haya un mantenimiento (los escribirá la consola de comunicados, tarea 4.3). Dice desde cuándo y hasta cuándo. | Sí |
| **Incidencia resuelta** | Avisos del servicio | Cuando una incidencia termine (4.3). | Sí |
| **Cambio importante** | Avisos del servicio | Un cambio de PrediGol explicado en Novedades (4.3). **Es lo crítico**: llega aunque el lector haya apagado la categoría. | **No** (es el único de su categoría) |

- En **Perfil → Notificaciones** aparece un interruptor nuevo, «Avisos del servicio», junto a Membresía y Soporte. Lo de su cuenta,
  su seguridad, sus solicitudes sobre sus datos y los cambios de los textos legales sigue llegando siempre.
- El texto de los correos **no lleva montos, precios ni tarjetas**, no promete resultados y no imprime la dirección del lector.
  Una instantánea de cada plantilla en cada idioma (`tests/snapshots/email_templates_ux017.json`) hace que cambiar una palabra
  sea una decisión escrita, no un descuido.
- Una dirección que rebotó no recibe nada, ni siquiera lo crítico; una que marcó un correo como spam recibe solo lo
  imprescindible (cuenta, seguridad, privacidad, textos legales), como antes.

## 2. Qué cambia para ti

- **El recordatorio de 72 horas** lo escribe el messenger al inicio de cada ciclo de 5 minutos. Solo mira cuentas
  **invitadas** (nunca activadas) con la invitación sin usar, sin reemplazar y sin caducar; salta las que rebotaron o se
  quejaron y no hace nada con `FBI_SELF_SERVICE` apagado (sin interruptor no hay enlaces). Es **uno por invitación**: si tú
  reenvías la invitación desde la consola, esa nueva invitación tiene su propio recordatorio; el lector que pide un enlace nuevo
  desde la página de uno vencido ya lo pidió él.
- **La categoría «servicio» tiene un tope propio dentro del tope del día:** **40 correos de servicio al día** (UTC), ajustable
  con `FBI_EMAIL_SERVICE_DAILY_CAP`, y nunca por encima de los 90 del día en total (`FBI_EMAIL_DAILY_CAP`; el plan gratis de
  Resend permite 100). Los de cuenta y seguridad van primero en la cola y **nunca** los frena este tope. Cuando se alcanza, los
  de servicio que quedan en la cola **esperan hasta las 00:05 UTC del día siguiente** sin gastar intentos: un aviso a muchos
  lectores se reparte entre días en vez de comerse el cupo de lo que importa. Un aviso de mantenimiento que ya pasó de su hora
  se descarta como «tarde» en vez de enviarse (lo mismo que ya hacían los demás).
- **Lo masivo va en la app y en Telegram; por correo solo lo crítico.** Esa política (plan 4.3: comunicados desde la consola)
  usa estas plantillas y este tope; aquí no se manda nada masivo.
- **Buzón de pruebas.** `python -m scripts.email_test queue --user <tu correo> --all` pone en la cola **una muestra de cada
  correo** que un lector puede recibir (todos menos la invitación, que lleva el enlace de una cuenta concreta, y el resumen
  semanal, que necesita el consentimiento del lector). Las fechas de las muestras se corren a los días siguientes a «ahora»
  para que una muestra que espera en la cola no se descarte como tarde. `status <id>` dice cómo salió cada una.
- **Consola → Mensajes** nombra las plantillas nuevas en español o inglés; el resto no cambia.

## 3. Lo que necesito de ti (cuando toque encenderlo; no antes)

No hay nada que hacer hasta que esto esté desplegado. Cuando lo esté, **P2** y **P3** (las mismas del correo de A5) son lo único
que falta:

### P2 · Resend (plan gratis)

1. Cuenta de Resend con verificación en dos pasos (si no la creaste ya).
2. *Domains → Add domain*: un **subdominio de envío**, por ejemplo `correo.predigolai.com` (Resend recomienda enviar desde un
   subdominio para aislar la reputación; dime cuál elegiste por el chat, no es secreto).
3. Deja **apagados** el seguimiento de aperturas y de clics: es el valor por defecto de Resend, solo no lo enciendas.
4. *API Keys → Create*, permiso **Sending access** limitado a ese dominio. **No la pegues en el chat.**
5. *Webhooks → Add endpoint*: `https://predigolai.com/api/v1/webhooks/resend`, con `email.bounced`, `email.complained`,
   `email.suppressed` y `email.failed`. Copia su *signing secret* (`whsec_…`). **Tampoco al chat.**

### P3 · DNS: la tabla exacta

Resend te muestra, al añadir el dominio, los registros que debes crear. Su forma es siempre esta (fuente: la referencia de la API
de Resend, «Create domain», y su guía de DMARC); **los valores exactos los muestra tu pantalla de Resend y se copian tal cual**,
sobre todo la clave DKIM, que es larga y única de tu dominio:

| # | Para qué | Tipo | Nombre (host) | Valor | Prioridad |
| --- | --- | --- | --- | --- | --- |
| 1 | **DKIM** (firma del correo) | `TXT` | `resend._domainkey` | `p=MIGf…` (la clave pública larga que muestra Resend) | — |
| 2 | **SPF** (quién puede enviar) | `TXT` | `send` | `v=spf1 include:amazonses.com ~all` | — |
| 3 | **Retorno de rebotes** (Return-Path) | `MX` | `send` | `feedback-smtp.us-east-1.amazonses.com` | `10` |
| 4 | **DMARC** (política, la creas tú) | `TXT` | `_dmarc` (en `predigolai.com`) | `v=DMARC1; p=none; rua=mailto:<tu correo>;` | — |

Detalles que evitan el error más común:

- **Con un subdominio de envío** (`correo.predigolai.com`) Resend muestra los nombres de los registros 1 a 3 con el subdominio
  incluido, por ejemplo `resend._domainkey.correo` y `send.correo`. Copia el nombre como lo muestre su pantalla: es la fuente de
  verdad. Algunos paneles añaden solos el dominio al final; si el tuyo lo hace, no lo escribas dos veces.
- **Cloudflare:** cada registro va en *DNS only* (nube gris, proxy **apagado**); si el proxy está encendido Resend no lo verifica.
  **Hostinger:** el mismo panel de zona DNS, con el mismo tipo, nombre y valor.
- **Un solo SPF por nombre:** si ya existe un `TXT` con `v=spf1` en ese mismo nombre, no crees otro; avísame y lo fusionamos.
- **El DMARC** (fila 4) se crea una sola vez para `predigolai.com` y cubre los subdominios; empieza en `p=none` (solo observa).
  Resend recomienda subirlo a `p=quarantine` y luego a `reject` **solo cuando compruebes que todo tu correo legítimo pasa**;
  eso no se hace en esta tarea.
- Los registros pueden tardar en propagarse. Cuando Resend marque el dominio como *Verified*, lo compruebo con una consulta
  pública (por ejemplo `nslookup -type=TXT resend._domainkey.correo.predigolai.com`). Mándame una captura o confírmalo.
- Si vas a recibir correo en la misma dirección (por ejemplo `soporte@predigolai.com`), **no toques el `MX` del dominio raíz**:
  los de arriba van en el subdominio `send` y no lo afectan.

### Las claves (en `/etc/predigol/app.env`, nunca en el chat)

`FBI_EMAIL_FROM="PrediGol <avisos@correo.predigolai.com>"`, `FBI_RESEND_API_KEY=…`, `FBI_RESEND_WEBHOOK_SECRET=…` y, **al
final**, `FBI_EMAIL_SEND=1`. Opcional: `FBI_EMAIL_SERVICE_DAILY_CAP=40` (ya es el valor por defecto). Con copia fechada antes,
candado de despliegue y recreando la API y el messenger, como los otros editores del plan de seguridad.

## 4. La prueba real (antes de dar el correo por encendido)

1. Con el envío encendido y desde tu cuenta de dueño: `python -m scripts.email_test queue --user <tu correo> --all`.
   Salen quince muestras; ábrelas en **Gmail y en Outlook** (una cuenta de prueba con dirección de Outlook) y mira *Mostrar
   original*: `SPF: PASS`, `DKIM: PASS`, `DMARC: PASS`.
2. Mira cada una en el teléfono (320 px de ancho): una columna, botón grande, sin cortes. Las fechas aparecen en tu zona
   horaria y en el idioma de la cuenta.
3. Un rebote marcado por el webhook, como en A5: una cuenta de prueba con `bounced@resend.dev`; la consola la muestra en
   «Rebotó» y la cuenta con el correo bloqueado.
4. Comprueba que Perfil → Notificaciones muestra «Avisos del servicio» y que apagarlo detiene un mantenimiento de muestra pero
   **no** un «cambio importante».

## 5. Vuelta atrás

- `FBI_EMAIL_SEND=0` en `app.env` y recrear el messenger: la cola se conserva y nada sale (o `docker compose stop messenger`).
- El código vuelve atrás con el despliegue anterior. La migración **0123** solo se deshace mientras la cola no tenga ningún
  correo de servicio y ningún lector haya apagado la categoría (un correo enviado es un registro); con ellos, el código vuelve
  y las dos listas se quedan.
- Esta migración **no escribe ninguna fila ni añade columnas**: cambia dos listas de valores permitidos (la de la cola y la de
  lo que un lector puede apagar) bajo `lock_timeout = '10s'`, sobre tablas pequeñas.

## 6. Privacidad y límites

- De cada correo nuevo la cola guarda solo la plantilla, el idioma y un parámetro corto (el fin de la prueba o de la
  membresía, las horas de un mantenimiento, el número de una entrada de Novedades, el número del enlace de la invitación). **No**
  se guarda el cuerpo, el nombre ni la dirección, ni montos, ni referencias de pago, ni ningún enlace (se hace al enviar).
- No hay pasarela de pagos: el correo de pago registrado confirma que **tú** registraste el pago y hasta cuándo; no cobra nada.
- **Lo que esta tarea no hace:** no enciende el correo, no manda comunicados masivos (4.3), no cambia ningún pick ni ninguna
  probabilidad ni nada de PrediGol Intelligence, y no escribe a nadie por Telegram. El recordatorio de las 72 horas no se manda a
  quien ya activó su cuenta, a quien pidió otro enlace, ni a una dirección que rebotó o se quejó.
