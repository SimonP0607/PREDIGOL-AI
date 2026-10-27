# B7 · Avisos en el dispositivo, recordatorios e instalación guiada

Avisos útiles en el teléfono o el computador del cliente, pedidos en el momento justo y con límites: el resultado de lo que
guardó, las alineaciones de sus equipos, un resumen al día, los recordatorios que él pide con la campana de un partido y su
cuenta. Nunca de 22:00 a 08:00 en su zona (salvo sus recordatorios), como máximo 3 al día de resultados, alineaciones y
resúmenes, y se apagan en un toque. PrediGol los envía solo, con sus propias claves VAPID: **sin proveedor intermedio y sin
coste**. **Nacen sin poder ofrecerse hasta que pongas la clave (P12, sección 9)**: hasta entonces ningún cliente ve nada nuevo.

## 1. Qué ve el cliente

- **Nunca al abrir.** PrediGol jamás pide el permiso al entrar. Lo ofrece **después de un momento**: al seguir a un equipo
  (la estrella) o al guardar un pick, con una tarjeta propia al pie de la pantalla —«¿Te avisamos de las alineaciones de
  Millonarios?», «¿Te avisamos cuando se resuelva tu pick?»— que dice los límites y tiene **«Ahora no»** junto a
  **«Activar avisos»**. Solo «Activar avisos» lleva a la pregunta del navegador. «Ahora no» (o la cruz) la aparta de ese
  dispositivo 30 días. Una sola tarjeta pregunta algo en cada visita: si salió esta, la encuesta del mes (B6) espera a otra.
- **La campana del partido.** En la cabecera de un partido que no ha empezado y empieza dentro de 7 días: «Avísame antes de
  que empiece», 15 minutos, 30 minutos o 1 hora antes, y «Quitar aviso». Llega aunque sea de noche (lo pidió él). La estrella
  sigue a un equipo y ordena Inicio; la campana pide un aviso de ese partido: son cosas distintas, y la hoja lo dice.
- **En el perfil, «Notificaciones»**, debajo de los correos: «Avisos en tus dispositivos» con el estado de **este**
  dispositivo (los recibe, no los recibe, los bloqueó —y cómo permitirlos en Android y en iPhone—, no puede, o un iPhone en
  Safari), las cuatro categorías con su interruptor (resultado de lo que guardas, alineaciones de tus equipos, resumen del
  día, tu cuenta), sus reglas, **sus dispositivos** («Chrome en Android · app instalada · último aviso entregado hace 2 h»,
  «este dispositivo» marcado, «Quitar» en cada uno) y «Enviar un aviso de prueba» (3 al día).
- **iPhone y iPad.** Allí los avisos solo llegan a PrediGol **instalada** en la pantalla de inicio (iOS 16.4 o posterior). En
  Safari, en lugar de un botón que no funcionaría, PrediGol enseña los tres pasos (Compartir → «Agregar a Inicio» → abrirla
  desde su icono y activar los avisos en el perfil).
- **La instalación guiada en Android y en el computador.** Chrome y Edge ofrecen su propia ventana de instalación; PrediGol la
  guarda y la muestra solo cuando el cliente la pide («Instalar PrediGol» en «Más»), nunca al abrir.
- **Cada aviso abre su pantalla:** el resultado, el Postpartido del partido o Mis picks; las alineaciones, su pestaña; el
  recordatorio y el resumen, el partido o Inicio; la cuenta, su bloque del perfil. Siempre una pantalla de PrediGol.
- **Ayuda** gana dos preguntas («¿Puedo recibir avisos en el teléfono?» y «¿Por qué no me llegan los avisos en el
  iPhone?»), que solo se ven mientras los avisos están disponibles.
- **Lo importante también va por correo.** El aviso de membresía a 1 día es un extra: los correos de 7 días antes y del día
  del vencimiento siguen como en A8. El aviso de un acceso desde un dispositivo nuevo va por correo (cuando el correo de
  cuenta está encendido, A7) y, además, a los dispositivos.
- Todo en español y en inglés: las palabras de cada aviso, en el idioma de la cuenta.

## 2. Línea base

Antes de B7 PrediGol no enviaba ningún aviso al dispositivo: el service worker solo hacía la app instalable y servía la
página sin conexión. No había dónde guardar un dispositivo ni una campana.

## 3. Lo que nunca cambia

- **PrediGol Intelligence no se toca.** Ni modelos, ni probabilidades, ni umbrales, ni picks, ni liquidación, ni estados de
  la IA. Los avisos **leen** lo que ya existe (lo que el cliente guardó y su liquidación, las alineaciones del partido, los
  favoritos) y nada de Intelligence lee las tablas nuevas: el trabajador de la IA no tiene permiso sobre ellas
  (`test_db_roles.py`), el messenger no carga ningún módulo de Intelligence y ninguna ruta de cliente importa un cliente HTTP
  (`test_user_layer_isolation.py`): solo el messenger llama a un servicio de push.
- **Las seis rutas de cliente responden igual** (la instantánea de forma no cambia).
- **Nada personal de más:** de cada navegador se guardan su dirección de push y las dos claves que el estándar W3C da para
  cifrar un aviso solo para él (`p256dh`, su clave pública, y `auth`); su familia y su sistema como palabras de una lista
  cerrada, nunca el user agent; ni IP. No son credenciales: no abren nada de PrediGol ni de la cuenta, y un servicio de push
  no acepta nada en esa dirección sin la firma de PrediGol. **Nunca salen de la base**: ni en la exportación del cliente, ni
  en los logs, ni en Sentry.
- **Las palabras de un aviso** nunca llevan una cuota, un importe ni un dato sensible: el resultado («Ganado: tu pick de
  Nacional–Millonarios»), el partido, la hora, la cuenta. Una prueba lo comprueba en los dos idiomas.

## 4. Lo nuevo por dentro

- **Migración 0104** (el plan la numeraba 0102; la cadena real la corrió): `customer.push_subscriptions` (un navegador por
  fila, revocado y nunca editado: por el cliente, por su servicio —404 o 410—, por otra cuenta que toma el mismo navegador o
  tras fallar 20 veces seguidas; una sola fila viva por dirección), `customer.match_alerts` (la campana: 15, 30 o 60
  minutos, una por partido; se va con el partido) y `customer.push_notices` (la cola: un aviso por cliente y clave —nunca dos
  veces, tenga los dispositivos que tenga—, sus palabras, la pantalla que abre —una ruta de PrediGol, nunca otra web, ni
  siquiera `//host`—, desde cuándo puede salir, hasta cuándo sirve y su destino: enviado a N dispositivos o descartado y
  por qué), y `customer.preferences.push_off` (las categorías apagadas). Las tablas rechazan lo que no deben guardar y no
  dejan borrar una cuenta que las tenga (se anonimiza, A7). Bajarla se niega en cuanto hay un dispositivo, una campana, un
  aviso o una categoría apagada.
- **El envío, propio:** `fbi/messaging/push.py` cifra cada aviso para su navegador (RFC 8291, aes128gcm; la prueba reproduce
  byte a byte el ejemplo del propio RFC) y lo firma con la clave VAPID de PrediGol (RFC 8292: un JWT ES256 sobre el origen
  del servicio de push, 12 horas). Solo se llama a los servicios de push conocidos (Google, Mozilla, Apple, Microsoft); una
  dirección de otro sitio nunca recibe una petición (se rechaza al suscribir y otra vez al enviar).
- **Los trabajos del messenger** (`fbi/messaging/push_jobs.py`), al empezar cada ciclo: `pick_result_alerts` (un pick o
  parlay liquidado en el último día), `lineup_alerts` (alineaciones confirmadas de los dos equipos de un partido de un
  favorito, en las 3 horas antes), `match_reminders` (la campana, a su minuto), el resumen del día (de 09:00 a 12:00 en la
  zona del cliente, uno al día) y el vencimiento de mañana; y `push_dispatch` en cada tick: horas silenciosas, caducidad,
  categoría apagada, el máximo diario, a cada dispositivo vivo, 5xx o 429 se reintenta cada 5 minutos mientras sirva.
- **API:** `GET /me/push`, `POST /me/push/devices`, `POST /me/push/devices/stop`, `PUT /me/push/categories`,
  `POST /me/push/test`, `GET/PUT/DELETE /me/match-alerts/{partido}` y `GET /admin/product/push`.
- **Web:** `public/sw.js` (los manejadores `push` y `notificationclick`: cada push muestra una notificación —Safari retira
  el permiso si no—, la misma etiqueta reemplaza la anterior y un toque abre su pantalla), `lib/push.ts`, la tarjeta de la
  oferta, `InstallGuide`, la campana, el bloque del perfil, la tarjeta del dueño y los eventos `notification_enabled`,
  `notification_opened` y `notification_disabled` (con las categorías de los avisos en el catálogo de A6).
- **Para ti, en `/admin/product`:** «Avisos en los dispositivos»: si están disponibles, cuántos clientes los reciben y en qué
  navegadores, y los avisos de los últimos 7 días por tipo, enviados y descartados. Recuentos, nunca quién. Los avisos
  enviados son una anti-métrica: sirven para ver el ruido, no para subirlos.
- **Conservación:** los avisos 90 días y los dispositivos revocados 30, con el interruptor de purga de la analítica
  (`FBI_EVENTS_PURGE`: en seco mientras no lo enciendas). La exportación del cliente incluye sus dispositivos (sin dirección
  ni claves), sus campanas y sus avisos; anonimizar una cuenta borra todo.

## 5. Decisiones que tomé

1. **Sin `pywebpush`:** el plan lo nombraba. Lo escribí con las dos librerías que ya están (`cryptography` y `httpx`): ni una
   dependencia nueva ni su licencia, y el cifrado se prueba contra el ejemplo del RFC.
2. **Disponibles por defecto, pero sin clave no hay nada:** `FBI_PUSH` está encendido mientras falte la línea (aprobaste el
   plan) y aun así nada se ofrece ni se envía hasta que pongas `FBI_VAPID_PRIVATE_KEY`. `FBI_PUSH=0` lo apaga todo sin
   desplegar.
3. **El resumen del día** es la categoría «análisis o pick relevante» del plan: un aviso por la mañana con el primer partido
   de hoy de sus equipos o ligas y cuántos más hay, que lleva a su análisis. Nunca inventa un pick.
4. **El máximo diario (3)** cuenta resultados, alineaciones y resúmenes; los de la cuenta, los recordatorios que el cliente
   pide y su prueba no cuentan. Lo que ya esperaba desde la noche sale primero.
5. **Horas silenciosas fijas** de 22:00 a 08:00 en la zona de la cuenta; lo que cae dentro espera a las 08:00 y se descarta si
   ya no sirve (unas alineaciones de un partido que ya empezó).
6. **Novedades no anuncia los avisos todavía:** su regla es contar solo lo que un lector ya puede ver. La entrada llega con
   la primera prueba en dispositivos reales, tras P12.
7. **Una pregunta por visita:** la oferta de avisos y la encuesta de B6 comparten la marca de la visita.

## 6. Pruebas

- **Backend:** el cifrado contra el ejemplo del RFC 8291 y lo que solo lee su dispositivo, la cabecera VAPID verificada con
  la clave pública, los servicios conocidos y las direcciones rechazadas, las respuestas de un servicio (201, 404, 410, 413,
  429, 5xx) (34 pruebas); las horas silenciosas en la zona del cliente, su día, el interruptor, los límites y las palabras de
  cada aviso en los dos idiomas, sin cuotas ni importes, cada pantalla una ruta de PrediGol (41); de integración, contra la
  base y con la sesión real, sin red: nada sin clave, los dispositivos (el mismo navegador, otra cuenta, el máximo de 10),
  categorías, prueba, campana, cada trabajo una vez y solo a quien tiene dispositivo y la categoría encendida, el envío
  cifrado a cada dispositivo, horas silenciosas, caducidad, máximo diario, 404/410, 5xx, el dispositivo que falla siempre,
  exportación, anonimización, purga y la vista del dueño (12); la migración 0104 en una base desechable (todo lo que rechaza
  y la bajada); los roles de la base (el trabajador sin acceso; la API con sus permisos y secuencias); la guarda de esquema
  de privacidad y la de aislamiento (solo el messenger llama a un servicio de push).
- **Web:** `lib/push.ts` con un navegador simulado (el iPhone en Safari, la pregunta del navegador primero y dentro del
  toque, la clave de PrediGol, otra clave, la denegación, apagar, «este dispositivo» solo mientras es de la cuenta);
  `public/sw.js` real (cada push muestra una notificación, el mensaje ilegible, las direcciones de otra web o `//host`, el
  toque que lleva a una ventana abierta o abre otra); la tarjeta, la campana, el bloque del perfil y la tarjeta del dueño.
- **E2E (`notifications.spec.ts`):** con el permiso y la suscripción simulados y un servicio de push de pruebas en
  127.0.0.1:9996: el aviso de prueba recorre el camino real (API → cola → messenger) y llega cifrado solo para ese navegador
  (se descifra en la prueba con su clave privada), firmado con la clave de PrediGol; la oferta tras seguir un equipo, «Ahora
  no», la campana, el iPhone en Safari, el navegador bloqueado, Ayuda y la tarjeta del dueño; y sin clave, que nada se
  ofrece en ninguna parte.

## 7. Puertas

PUERTAS_B7

## 8. Despliegue

- **Paquete `ux-b7`:** B6 y B7 juntos (una sola tanda de puertas y de e2e para los dos), sobre `ux-b5`, con las migraciones 0103
  y 0104.
- **Migración 0104:** BACKUP → RESTORE TEST → MIGRATION → VALIDATION → DEPLOY, con la copia restaurada y sus conteos antes de
  migrar.
- **Nace sin poder ofrecerse:** sin `FBI_VAPID_PRIVATE_KEY` la API dice «no disponible», la web no muestra nada nuevo y el
  messenger no envía. La verificación tras desplegar lo comprueba en producción, dentro de la API y del messenger
  (`fbi.customer.push.available()` responde que no; de la clave no se lee ni se muestra nada).
- **Vuelta atrás:** `FBI_PUSH=0` en `app.env` (con su copia fechada y, al final, `predigolctl config-baseline`) y recrear la API
  y el messenger (nada se envía y todo se oculta; lo guardado se conserva); el código vuelve con el despliegue anterior y su `sw.js` (los navegadores lo actualizan solos).

## 9. Acción manual: P12, la clave VAPID

Solo tú, en el servidor, con el candado de despliegue libre (que no haya un despliegue en curso). La clave privada **nunca**
pasa por la pantalla, el chat ni el repositorio: se genera dentro de un fichero que solo root lee y se añade a `app.env` sin
mostrarla.

1. Copia fechada de `app.env` y comprueba que no hay ya una clave (debe decir `0`):

   ```
   sudo cp -p /etc/predigol/app.env /etc/predigol/app.env.$(date +%Y%m%d-%H%M)
   sudo grep -c '^FBI_VAPID_PRIVATE_KEY=' /etc/predigol/app.env
   ```

2. Genera el par dentro de un fichero de root y añade la línea privada a `app.env`:

   ```
   sudo sh -c 'umask 077; docker exec predigol-api python -m scripts.vapid_keys > /root/predigol-vapid.txt'
   sudo sh -c 'grep "^FBI_VAPID_PRIVATE_KEY=" /root/predigol-vapid.txt >> /etc/predigol/app.env'
   ```

3. La línea **pública** sí me la puedes mandar por el chat (no es secreta; la compruebo contra lo que dice la API):

   ```
   sudo grep '^# public key' /root/predigol-vapid.txt
   ```

4. Borra el fichero temporal (la clave ya está en `app.env`, que tiene su copia fechada):

   ```
   sudo shred -u /root/predigol-vapid.txt
   ```

5. Toma la referencia de la configuración, para que el aviso «la configuración cambió» del plan de seguridad no salte por
   este cambio (es el último paso de cualquier cambio en un fichero de entorno):

   ```
   sudo predigolctl config-baseline
   ```

6. Dime «listo». Yo recreo la API y el messenger en un momento tranquilo del servidor (sin tocar el worker de
   Intelligence) y compruebo por lectura, dentro de los dos contenedores, que los avisos están disponibles con esa clave
   pública y que el messenger no registra errores.
7. **La prueba real (criterio de terminado de B7):** en tu teléfono —un Android con Chrome y un iPhone con PrediGol instalada
   (iOS 16.4 o posterior)—, Perfil → Notificaciones → «Activar en este dispositivo» y «Enviar un aviso de prueba»: llega en
   segundos y al tocarlo abre tu perfil. Después, en los días siguientes, las cinco categorías: la campana de un partido (15
   minutos antes), un pick guardado que se liquida, las alineaciones de un equipo que sigues, el resumen de la mañana y la
   cuenta (entrar desde un navegador nuevo). Ninguno debe llegar entre las 22:00 y las 08:00 salvo el recordatorio, y
   ninguno dos veces. Con eso, la entrada de Novedades.

Si algún día la clave se filtrara: se genera otra igual (pasos 1 a 6, quitando antes la línea vieja de `app.env`) y cada
navegador tiene que volver a activar los avisos.
