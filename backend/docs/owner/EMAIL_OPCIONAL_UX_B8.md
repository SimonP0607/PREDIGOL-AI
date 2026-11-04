# B8 · Email opcional: el resumen semanal por correo, solo para quien lo pide

Una vez por semana, a quien lo pida en su perfil, un correo corto: cómo terminaron los picks que guardó, los partidos de sus
equipos de los próximos siete días y las Novedades. Se pide aparte, en una casilla que nunca viene marcada; se deja en un clic
desde cualquier resumen; y sale por un remitente propio, en otro dominio que el de los correos de la cuenta, para que un
resumen marcado como spam no arrastre a los de seguridad. **Nace apagado.**

## 1. Qué ve el cliente

- **En Perfil → Notificaciones**, debajo de los correos de la cuenta, «Resumen semanal»: un interruptor que empieza apagado,
  con la frase de la Política de tratamiento («Quiero recibir por correo el resumen semanal de PrediGol: mis picks de la semana
  y cómo terminaron, los partidos de mis equipos y las novedades. Puedo darme de baja en un clic desde cualquier resumen o en
  mi perfil.») y cómo llega («Llega una vez por semana, desde las 9:00 de tu zona horaria…»). Encendido dice «Lo pediste el …»;
  apagado después de pedirlo, «Te diste de baja el …».
- **Solo aparece cuando el resumen puede llegar de verdad** (su interruptor, el correo encendido y el remitente comercial).
  Quien ya lo pidió lo sigue viendo, para poder darse de baja.
- **El correo, «Tu semana en PrediGol».** Cuántos de los picks que guardó terminaron en la semana (ganados, perdidos y
  devueltos: solo cuentas; las unidades y los porcentajes viven en Mis picks, con su muestra), cuántos partidos juegan sus
  equipos en los próximos siete días (o la invitación a elegirlos si aún no sigue ninguno), las Novedades de la semana por su
  título, el botón «Ver Mis picks» y, al pie, por qué lo recibe («Recibes este resumen porque lo pediste en tu perfil.») y
  «Darte de baja en un clic». Sin cuotas, sin promesas, sin urgencia, sin píxeles. En su idioma, español o inglés.
- **La baja.** El botón de baja de su programa de correo (Gmail, Outlook…) la hace sin abrir nada (RFC 8058). El enlace del
  pie abre `/unsubscribe`, que no hace nada al abrirse (un escáner de enlaces no da de baja a nadie) y da de baja con un toque,
  sin iniciar sesión: «Listo: ya no recibirás el resumen semanal…». Una segunda vez dice que ya se había dado de baja; un enlace
  que no es de PrediGol o tiene más de un año lo dice y lleva a Notificaciones.
- **En Privacidad**, la decisión aparece en «Lo que aceptaste» con su fecha y su versión (desde el perfil o desde un correo),
  como opcional y con el camino a Notificaciones; nunca con el aviso de retirar la autorización del servicio.
- Todo en español y en inglés.

## 2. Línea base

Antes de B8 PrediGol no mandaba nada comercial: solo los correos de la cuenta (A5, A7, A8, A14 y los cambios legales). El
consentimiento `marketing_email` estaba previsto desde A4, pero no existían ni la casilla, ni el trabajo, ni la baja.

## 3. Lo que nunca cambia

- **PrediGol Intelligence no se toca.** El trabajo solo lee los picks que el lector guardó (los ya liquidados) y los partidos
  de sus equipos; no lee ni escribe modelos, probabilidades, picks publicados ni estados de la IA. Las pruebas de aislamiento
  cubren los módulos nuevos (ninguno llama a un modelo de lenguaje ni a internet) y el messenger sigue con el rol de la API.
- **Los correos de la cuenta no cambian**: su remitente, sus categorías y sus límites. Lo comercial va el último de la cola y
  nunca por el remitente de la cuenta.
- **Nada personal en la cola:** el resumen se guarda como cuentas y los identificadores de Novedades; ni nombres, ni
  direcciones, ni cuotas. El enlace de baja se fabrica al enviar y no se guarda.
- **La puerta de consentimientos sigue pidiendo solo los cuatro obligatorios:** el resumen nunca está en la puerta ni marcado
  de antemano.

## 4. Lo nuevo por dentro

- **Migración 0105.** Dos listas de la base aprenden una palabra cada una: la cola acepta la categoría `marketing` y los
  consentimientos el origen `email` (la decisión tomada desde un correo). Ninguna tabla ni columna nueva. Bajarla se niega
  mientras haya un correo comercial en la cola o una decisión tomada desde un correo.
- **La frase de la casilla** entra en la Política de tratamiento: versión `2026-10-27-draft2`, cambio **no material** (nadie
  tiene que aceptar de nuevo; sigue siendo un borrador pendiente del abogado, P5).
- **`fbi/messaging/digest.py`, el trabajo semanal del messenger.** Cada lector tiene su día (su número de cuenta módulo 7, de
  lunes a domingo) y el resumen sale desde las 9:00 de su zona; como mucho 30 al día (`FBI_DIGEST_DAILY_CAP`), por debajo del
  tope de la cola (90; Resend Free deja 100); uno por lector y semana; ni al dueño ni al robot; ni a una dirección que rebotó o
  se quejó. Antes de salir, cada resumen comprueba otra vez el consentimiento, el interruptor y el remitente: quien se dio de
  baja hace un minuto no lo recibe (queda como «suprimido»).
- **`fbi/messaging/unsubscribe.py`, el enlace de baja:** la cuenta, el día y una firma (HMAC con una subclave de
  `FBI_AUTH_SECRET_KEY`); vale un año. `POST /api/v1/email/unsubscribe?t=…` es el botón del programa de correo (RFC 8058: el
  enlace solo puede ir en la dirección; el registro de la API guarda la ruta sin la consulta y Sentry no la recibe) y
  `POST /api/v1/email/unsubscribe/link`, el de la página, con el enlace en el cuerpo, nunca en una dirección. Como mucho 20
  enlaces que no valen por cliente en 15 minutos. Cada resumen lleva las cabeceras `List-Unsubscribe` y
  `List-Unsubscribe-Post`.
- **Web:** el interruptor en Notificaciones, la página pública `/unsubscribe` (como `/unlock`), la fila opcional en Privacidad
  y el nombre «Resumen semanal (comercial, con consentimiento)» en Admin → Mensajes.
- **Eventos:** `notification_enabled` y `notification_disabled` con la categoría `digest`, ya en el catálogo cerrado de A6.
- **Interruptores (`app.env`):** `FBI_DIGEST` (nace apagado), `FBI_DIGEST_FROM` (el remitente comercial, en otro dominio que
  `FBI_EMAIL_FROM`) y `FBI_DIGEST_DAILY_CAP` (30).

## 5. Decisiones que tomé

- **Solo cuentas, no unidades.** El plan decía «tus picks y su resultado en unidades», pero desde B5 las unidades y el
  rendimiento van siempre con su muestra; en un correo irían sin ella. El resumen cuenta y lleva a Mis picks.
- **Las Novedades van dentro del resumen,** hasta tres títulos de la semana, y no en correos sueltos: así el lector no recibe
  más correos de los que pidió.
- **El remitente comercial tiene que estar en otro dominio** (por ejemplo `novedades.tudominio.com` frente a
  `correo.tudominio.com`). Sin eso no se ofrece la casilla ni sale nada: es la separación de flujos del plan, comprobada por el
  código y no solo escrita.
- **La casilla solo se ofrece cuando puede cumplir.** Con `FBI_DIGEST` apagado, el correo apagado o sin remitente comercial,
  el perfil no la muestra y la API rechaza pedirla (422 `not_offered`). Darse de baja se puede siempre.
- **La página de baja pide un toque:** un enlace que diera de baja al abrirse lo dispararía cualquier escáner de seguridad de
  correo. El botón del programa de correo no abre nada.
- **El día de cada lector** sale de su número de cuenta, para repartir los envíos por la semana sin guardar nada nuevo.
- **Desviación del plan: una migración.** El plan decía «base de datos: ninguna nueva». La 0105 no crea tablas ni columnas:
  amplía las dos listas que la base ya comprobaba, lo mínimo para guardar un correo comercial y una baja con su origen.

## 6. Pruebas

- **Backend:** unitarias (`test_messaging_digest_unit.py`: las frases en español e inglés, solo cuentas y nunca una cuota; el
  pie comercial; el enlace firmado —otra cuenta, otro día, una letra cambiada, más de un año, del futuro o sin la clave del
  servidor: nadie—; el remitente en otro dominio; cuándo se ofrece; el día y la hora; el tope del día); integración con base
  real (`test_messaging_digest.py`: la casilla ofrecida solo cuando puede llegar y pedirla apagado rechazado; solo lo reciben
  quienes lo pidieron, en su día, desde las 9:00 de su zona, una vez por semana, ni el dueño ni el robot ni una dirección que
  rebotó; el tope del día; lo que dice escrito como cuentas; su remitente, sus cabeceras y su enlace; la comprobación al
  salir; lo de la cuenta primero; la baja en un clic sin sesión, una segunda que no cambia nada y una falsificada que no hace
  nada; la página con el enlace en el cuerpo y solo desde las páginas de PrediGol; el corte tras enlaces que no valen); la
  migración (`test_migration_0105_customer_marketing.py`: nada más cambia, cada lista sigue cerrada, la bajada negada); los
  textos legales y las plantillas.
- **Web (unitarias):** `digest.test.tsx` (el interruptor solo cuando se ofrece, apagado de inicio, la frase, desde cuándo;
  Privacidad con lo opcional solo una vez decidido y su camino a Notificaciones; cada origen de una decisión con su texto; la
  consola; los textos de la baja), `updates.test.tsx` (la copia de Novedades del servidor es la misma lista con los mismos
  títulos), `account.test.tsx` y `support.test.tsx` (`/unsubscribe` pública y sin lo que sigue a su dirección).
- **e2e (`digest.spec.ts`, proyecto `digest`):** apagado, la casilla no está, pedirla se rechaza y Privacidad muestra los
  cuatro; encendido con el messenger de QA, la casilla, el resumen por su remitente con las cabeceras, la página de baja sin
  sesión (nada al abrirla, un toque, una segunda vez, un enlace falso), el clic del programa de correo y Privacidad; a 320 px,
  con axe limpio y objetivos de 44 px.

## 7. Puertas

Puertas sobre el árbol integrado del PR #21 (`feat/UX-001`, 4-nov-2026), el que se desplegará:

- Backend: `ruff check .` limpio; `mypy` estricto (597 ficheros) y `mypy .` (1.492 ficheros) sin errores; pruebas unitarias **7.904 pasan, 16 omitidas**;
  migraciones 0095 a 0106 con una sola cabeza (0106, colgada de la 0119).
- Web: lint 0 errores (26 avisos que ya existían), tipos de la web y del e2e, **1.456 pruebas pasan, 0 fallan**, build.
- Seguridad: autoprueba de Gitleaks 41 de 41; escaneo de todo el historial limpio.
- CI del PR #21: Convenciones del PR, web, `ruff + mypy`, `scan` y secretos en verde; `pytest` con PostgreSQL 16 y la corrida de integración
  completa se anotan en el PR al terminar. El e2e de esta fase se repite sobre el árbol integrado antes del despliegue.

## 8. Despliegue

Backend y web juntos (el contrato cruza los dos), con la migración 0105: **copia → prueba de restauración → migración →
validación → despliegue**. Nace apagado: desplegar no manda nada a nadie. **Vuelta atrás:** `FBI_DIGEST=0` en `app.env` (con su
copia fechada y, al final, `predigolctl config-baseline`, el último paso de cualquier cambio en un fichero de entorno desde
`sec-s3`): no entra nada más en la cola y lo que esté en ella no sale; las decisiones de los lectores se quedan. La web anterior
funciona con este backend (la API es aditiva). La bajada de la 0105 solo es posible sin correos comerciales en la cola ni
decisiones tomadas desde un correo.

## 9. Acción manual

Ninguna hasta que decidas encenderlo. Cuando lo decidas:

1. Antes, el correo de A5 encendido y con su prueba real (P2 y P3).
2. En Resend, un segundo dominio de envío para lo comercial (por ejemplo `novedades.tudominio.com`), verificado con sus
   registros SPF, DKIM y DMARC (el plan lo deja dentro de P3: «si se usa un subdominio comercial aparte, sus registros DNS entran
   en P3»).
3. En `/etc/predigol/app.env` (copia fechada y candado de despliegue): `FBI_DIGEST_FROM=PrediGol <resumen@novedades.tudominio.com>`
   y `FBI_DIGEST=1`; se recrean la API y el messenger y, al final, `predigolctl config-baseline`.
4. Comprobación: en tu perfil aparece «Resumen semanal»; lo pides desde una cuenta de prueba tuya; en Admin → Mensajes ves el
   resumen en la cola el día de esa cuenta y luego enviado; llega por el remitente comercial y el botón de baja de Gmail la da
   de baja.
