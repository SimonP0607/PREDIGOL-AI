# A14 · Ayuda y soporte

Plan Maestro UX, sección 32 (Ayuda y soporte), ficha A14 y gate G10. Rama `ux/a14`. **Migración `0102`** (la ficha decía
«ninguna nueva»: ver la decisión 1). Con 10 a 200 clientes el soporte es humano: un centro de ayuda para que el cliente
encuentre la respuesta solo, mensajes que te llegan con su contexto y WhatsApp para lo urgente. El bot con IA espera a que haya
volumen repetitivo (C2).

## 1. Qué ve el cliente

| Dónde | Qué ve | Regla |
| --- | --- | --- |
| **Ayuda** (`/help`) | **23 preguntas** en ES y EN en los ocho grupos del plan (Empezar; Cuenta y acceso; Membresía y pagos; Picks y parlays; Mis picks y liquidación; Notificaciones e instalación; Privacidad y datos; Juego responsable), cada una se abre en su sitio y algunas llevan a la página que hace lo que explican (tu perfil, el glosario, Mis picks, «Juego responsable»); **una búsqueda** sin acentos ni mayúsculas («contrasena» encuentra «contraseña»); «Más ayuda» (glosario, «Juego responsable», «Privacidad y datos» y el **recorrido de 4 pasos**, que pasa aquí desde el glosario); **«Escríbenos»** | A **dos toques de cualquier pantalla**: el menú de la cuenta → «Ayuda». También con la membresía **vencida o suspendida** (las rutas que una cuenta limitada abre ya la incluían desde A8). `/help#faq-renew` abre esa pregunta |
| **Tus mensajes** | Arriba en Ayuda, si ya te escribió: cada mensaje con su número, fecha y estado («Esperando respuesta», «Respondido», «Cerrado») | Solo los suyos |
| **«Reportar un problema»** | Una hoja desde abajo en el teléfono y desde el lado en el computador: **seis opciones grandes** (No puedo entrar o pagué y no accedo · Mi cuenta o mi membresía · Algo no funciona · Un dato está mal · Una sugerencia · Una reclamación), cada una con cuándo le respondes; el texto (**hasta 2.000 caracteres**, con contador) y, antes de enviar, **qué va con él**: la pantalla, la versión de PrediGol, el tipo de dispositivo, si usa la app instalada y la referencia del último error. «Nunca tu contraseña ni lo que escribiste en otros formularios» | Al enviar: el número del mensaje y **hasta cuándo le respondes** («a más tardar el 26 de octubre, 23:59»). «Mis datos personales» no abre un mensaje: lleva a «Privacidad y datos», donde la solicitud tiene su plazo legal (A4) |
| **Desde un error** | Cada error que muestra una página (`ErrorState`) ofrece «Reportar un problema», con la **referencia de ese error** ya puesta | Nunca en tu consola |
| **Desde un partido** | Al pie: «¿Ves un dato incorrecto? Avísanos», con el partido ya enlazado | Categoría «Un dato está mal» |
| **El mensaje** (`/help/messages/N`) | El hilo con tus respuestas (las que anotas de WhatsApp o de un correo lo dicen), su estado y, mientras nadie respondió, hasta cuándo; puede añadir algo o cerrarlo («Ya está resuelto»). Cerrado, la pregunta opcional **«¿Qué tan fácil fue resolverlo?»** (de «Muy difícil» a «Muy fácil»), una vez | El de otro lector, o uno que no existe, dice lo mismo: no está. El botón del correo lleva aquí |
| **Escríbenos** | «Reportar un problema» y, **cuando los des**, WhatsApp (abre el chat con la primera línea escrita) y el correo de respuesta | Con los mensajes apagados (`FBI_SUPPORT=0`) quedan WhatsApp y el correo |
| **Entrada** (`/login`) | «¿No puedes entrar?» con WhatsApp y el correo, **solo cuando los hayas dado** | Para quien no puede entrar: el caso urgente de la sección 32 |

## 2. Qué ves tú: Soporte en la consola (`/admin/support`)

- **Arriba, cuatro cifras:** esperan respuesta · fuera de plazo · urgentes · abiertos.
- **Una sola bandeja** con los mensajes y las **solicitudes de privacidad** de A4: primero lo que espera respuesta, por
  prioridad (urgente, alta, media, baja) y el más antiguo primero. Filtros por estado, categoría y prioridad.
- **Cada mensaje** dice quién (nombre y correo), su categoría y prioridad, cuándo llegó, **hasta cuándo responder** (o el
  plazo legal, si es de privacidad), si está fuera de plazo, y al abrirlo **su contexto** (pantalla, referencia del error —la
  que buscas en el registro del servidor—, versión, dispositivo, app instalada, enlace al partido), el hilo y cuándo llegó tu
  primera respuesta.
- **Responder** de tres formas: **aquí** (al lector le avisamos por correo), **anotar lo hablado por WhatsApp** o **anotar un
  correo** (en esos dos no sale correo: ya hablaron), y dejarlo respondido, abierto (sigues con él) o cerrado.
- Una **solicitud de privacidad** se responde con sus reglas legales (el plazo y la única prórroga) y, si es de borrado, con
  la anonimización después de la respuesta, como en Usuarios.
- Cada respuesta es una escritura de administrador auditada.

## 3. Lo que nunca cambia

- **La capa de usuario consume la inteligencia; no la altera.** Un mensaje no toca ningún pick, probabilidad, estado, modelo,
  umbral, liquidación ni dato de PrediGol Intelligence: solo escribe en las tablas del propio lector. «Un dato está mal» te
  avisa a ti; nada se corrige solo.
- **El worker de Intelligence no lee nada de `customer`** (`grants.sql`, desde A4) y **ninguna IA lee los mensajes**.
- **Sin estados inventados:** «Esperando respuesta», «Respondido» y «Cerrado» son los de la base; «hasta cuándo» es la regla de
  su categoría.
- La analítica de producto solo cuenta el evento `ticket_created` con la categoría (nunca el texto), y solo para los mensajes
  de soporte: una solicitud de privacidad no se mide.

## 4. Datos

- **Migración `0102`**, aditiva: `customer.support_tickets` (de A4) gana `category` (`access`, `account`, `technical`,
  `wrong_data`, `suggestion`, `complaint`; `privacy` para las solicitudes de privacidad y solo para ellas), `context` (un objeto
  de **2 KB como mucho** con lo de la tabla de arriba; solo en mensajes de soporte) y `effort` (1 a 5, una vez, con el mensaje
  cerrado); `customer.ticket_messages` gana `channel` (`web`, `email`, `whatsapp`). Las solicitudes de antes quedan como
  `privacy` y sus mensajes como `web`. La categoría y el contexto **no cambian** después de escritos (la guarda de A4 se amplía).
- **El código de antes sigue funcionando** sobre la `0102` (escribe una solicitud sin categoría y un disparador se la pone): se
  puede volver al código anterior sin tocar la base.
- **La bajada se niega** mientras exista un mensaje de soporte o uno anotado de WhatsApp o de un correo (borraría lo que los
  lectores dijeron); sin ellos, quita las columnas y deja la guarda de la `0095`.
- **`grants.sql` no cambia:** la API ya podía insertar y actualizar mensajes y solicitudes e insertar sus mensajes (A4); nunca
  borrar.
- **Exportación:** el lector recibe sus mensajes con su contexto, el hilo y su respuesta sobre la facilidad.
- **Anonimización (A7):** sus mensajes abiertos **se cierran** (no queda nadie a quien responder); el hilo **se conserva**, como
  el de las solicitudes de privacidad, hasta la respuesta del abogado (P5: ¿se borra el texto de solicitudes y mensajes al
  anonimizar?).
- **Retención de 24 meses tras cerrar** (ficha): la purga se construye antes de que el primer mensaje cumpla 24 meses cerrado
  (octubre de 2028 como pronto), primero en seco y con tu visto bueno, y con la respuesta de P5 para las solicitudes de
  privacidad.

## 5. Categorías, prioridades y primera respuesta (sección 32)

| Categoría | Prioridad | Primera respuesta | Aviso al dueño |
| --- | --- | --- | --- |
| Acceso (pagó y no entra, enlace caducado) | **Urgente** | **El mismo día**: hasta las 23:59 de Bogotá; si llega desde las 20:00, al día siguiente antes del mediodía | **Al momento** (`ticket_new`) |
| Cuenta o membresía | Alta | 24 h | En el recuento de la mañana |
| Error técnico | Alta | 24 h | En el recuento de la mañana |
| Reclamación | Alta | 24 h | En el recuento de la mañana |
| Dato incorrecto | Media | 48 h | En el recuento de la mañana |
| Sugerencia | Baja | Una semana (la respuesta en Novedades llega con B6) | En el recuento de la mañana |
| Privacidad (por «Privacidad y datos») | Alta | Plazo legal: 10 días hábiles las consultas, 15 los reclamos | **Al momento**, y `privacy_due` 3 días hábiles antes (A5) |

«Fuera de plazo» = pasó la hora de su primera respuesta sin ninguna tuya (o, en privacidad, pasó el plazo legal).

## 6. El correo y los avisos

- **Correos al lector** (cola de A5): el **acuse** al escribir y un aviso con cada respuesta **escrita aquí**. Dicen el número,
  de qué trata y hasta cuándo respondes; **nunca las palabras** de ninguno de los dos —la cola no guarda cuerpos y el correo no
  copia tu respuesta: el botón lleva al mensaje en PrediGol—, como las respuestas de privacidad. El lector puede apagar los
  correos de soporte en su perfil (categoría opcional de A5). Un acuse que espera en la cola más de 2 días, o un aviso de
  respuesta más de 7, ya no sale. **Mientras `FBI_EMAIL_SEND=0`, ninguno sale** (esperan en la cola).
- **Avisos a ti** (notificador): `ticket_new` **al momento** con un mensaje urgente o una solicitud de privacidad nueva, y cada
  mañana (desde las 07:00 de Bogotá) **el recuento** de los mensajes que esperan tu respuesta y cuántos pasaron su plazo. Solo
  cifras y el enlace a la consola, nunca un correo, un nombre ni las palabras del lector. **Te llegarán cuando exista el canal
  (P14)**, y P14 espera al interruptor del hallazgo 16 (nadie pone `FBI_TELEGRAM_*` en `app.env` hasta entonces). Hasta
  entonces la rutina diaria del plan: abrir Soporte un par de minutos al día.

## 7. Línea base de producción (26-oct-2026, 13:04 UTC, solo lectura)

| Medida | Valor |
| --- | --- |
| Revisión | `0094`: las tablas de soporte **no existen** en producción (llegan con A4) — hoy no hay ningún canal de soporte |
| Cuentas | 1 de administrador activa y 1 desactivada; 6 de lector, todas desactivadas (6 entraron en los últimos 30 días) |
| Avisos al dueño aceptados | Los 8 tipos de antes de A5 (`ticket_new` llega con la `0096`) |
| Avisos en cola, 7 días | `pick_settled` 77.089 y `shadow_pick` 76.730 en cola (hallazgo 16); `run_recovered` 16, `ai_budget` 1 y `worker_down` 1 omitidos |
| Respuestas de la API, 24 h | 1.768 correctas, 14 de cliente (4xx) y **2 errores de servidor**, ambos de tu consola (`/admin/picks/settlement` y `/admin/overview`); **ningún error en las páginas de los lectores** |
| Referencias de petición | 12 caracteres: la forma que el contexto acepta |
| `app.env` | Sin `FBI_SUPPORT_WHATSAPP` (P7), sin `FBI_EMAIL_REPLY_TO`, sin `FBI_EMAIL_SEND` y sin `FBI_SUPPORT` (sin la línea = encendido) |

Los dos errores de la consola son del plan de Intelligence (ajenos a UX): anotados en el estado para esa sesión.

## 8. Interruptor y vuelta atrás

- **`FBI_SUPPORT`** (en `app.env`, encendido mientras falta la línea). **`=0`** y recrear la API: desaparecen «Reportar un
  problema» y la escritura de mensajes (404 `not_available`); **quedan** Ayuda, su contacto (WhatsApp, correo), las solicitudes
  de privacidad y la lectura de los mensajes ya escritos, y **tú puedes seguir respondiéndolos**.
- **Volver al código anterior** no necesita tocar la base (sección 4). La bajada de la `0102` solo se permite sin mensajes de
  soporte.

## 9. Seguridad y privacidad

- Cada lector **solo ve y toca sus mensajes**: el de otro es «no existe» (404), igual que uno inexistente. La bandeja es **solo
  de un SUPER_ADMIN** (403 para un lector). Las escrituras exigen la cabecera del propio sitio (403 desde otra web).
- **Texto libre limitado:** 2.000 caracteres por mensaje del lector (4.000 los tuyos), **3 mensajes abiertos** a la vez y
  **10 nuevos en 24 h** por lector, 50 por hilo; **sin adjuntos** en el bloque A.
- **Contexto acotado**, comprobado otra vez en el servidor: solo las seis claves de la tabla, cada una con su forma; la pantalla
  **sin su consulta**, y las páginas de los enlaces de un uso (`/activate`, `/reset-password`, `/unlock`) solo por su nombre;
  **nunca** contraseñas, tokens, direcciones, IP ni el contenido de otros formularios. No guarda un seudónimo: el mensaje ya es
  de su cuenta.
- El contacto público (`/api/v1/support/contact`) solo da lo que tú publicas: el número de WhatsApp y el correo de respuesta.

## 10. Rendimiento

Todo vive en tablas del lector, con los índices de A4 (por lector y por plazo): con 10 a 200 clientes son decenas o cientos de
filas. La bandeja lee hasta 200 mensajes con su hilo; las cifras de arriba, los abiertos. **Medido en QA** (26-oct, 63 mensajes
y solicitudes con 92 mensajes en sus hilos, a través del servidor web; mediana de 10 llamadas): Ayuda del lector (`GET
/me/support`) **10 ms**, enviar un mensaje **30 ms**, la bandeja entera del dueño **17 ms**, el contacto público **4 ms**.

## 11. Decisiones que tomé (desviaciones deliberadas, escritas)

1. **Una migración pequeña (`0102`)** aunque la ficha decía «ninguna nueva»: la tabla del plan (sección 13) ya pedía
   «categoría, prioridad, contexto», pero la `0095` de A4 solo hizo lo de privacidad. Son cuatro columnas aditivas. **Números:**
   A14 toma la `0102`; B6 pasa a la `0103`, B7 a la `0104`, B11 a la `0105` y C1, si llega su disparador, a la `0107` (la `0106`
   es de F11).
2. **La prioridad no se guarda:** sale de la categoría, que no cambia (no hay recategorización en el bloque A).
3. **«El mismo día» es hasta las 23:59 de Bogotá**, y desde las 20:00 el día siguiente antes del mediodía (una promesa de media
   hora no se cumple).
4. **El correo no copia la respuesta** (regla de A5: la cola no guarda cuerpos): avisa con el número y lleva a PrediGol.
5. **Aviso al momento solo para lo urgente y lo de privacidad;** lo demás va en el recuento de la mañana (el plan solo pide el
   aviso inmediato para lo urgente).
6. **Una pregunta de privacidad no es un mensaje:** va a «Privacidad y datos», donde tiene su plazo legal y sus reglas (A4); en
   tu bandeja aparecen juntos.
7. **Cerrado es definitivo:** si el problema sigue, el lector abre otro mensaje (el cerrado lo dice). La facilidad se pregunta
   una vez, quien sea que lo cierre.
8. **Límites contra el abuso** que la ficha no fijaba: 3 abiertos, 10 al día, 50 por hilo.
9. **Ayuda pide haber entrado**, como el glosario; quien no puede entrar tiene el contacto en la pantalla de entrada.
10. **El recorrido de 4 pasos se mudó** del glosario a Ayuda (A13 lo dejó allí «hasta que exista `/help`»).
11. **Al anonimizar** se cierran sus mensajes abiertos (A7 conservaba el hilo de privacidad; ahora también el de soporte).
12. **«Más»** (la quinta celda de la barra) llega con A15: hasta entonces el menú de la cuenta es el camino de dos toques.

## 12. Pruebas

| Prueba | Qué demuestra |
| --- | --- |
| `tests/unit/test_customer_support.py` (33) | Prioridad y primera respuesta de cada categoría (las 20:00 y las 23:59 de Bogotá incluidas); cuándo un mensaje o una solicitud está fuera de plazo; el contexto: solo sus seis claves con su forma, nada más (16 casos rechazados: consulta en la ruta, una URL, un correo, una contraseña, un formulario…), las páginas de los enlaces de un uso por su nombre; el interruptor; lo que se comprueba antes de tocar la base; los contratos; los dos correos (número, tema y momento; nunca una palabra del hilo) |
| `tests/integration/test_customer_support.py` (11) | Un mensaje por HTTP con su contexto, su acuse en la cola y su evento en una transacción; cada lector solo lo suyo (404), sin sesión 401, desde otra web 403, la bandeja 403 para un lector; el hilo, el cierre y la facilidad una vez; 3 abiertos y 10 al día; la bandeja en orden con las solicitudes de privacidad y sus filtros; responder aquí encola el correo y anotar WhatsApp no; fuera de plazo; el aviso urgente al momento y el recuento de la mañana sin datos del lector; la exportación y la anonimización; el interruptor |
| `tests/integration/test_migration_0102_customer_support.py` | La `0102` sobre la `0101`: nada más cambia, las solicitudes de antes quedan como privacidad, **el código de antes sigue escribiendo**, lo que las columnas rechazan, la guarda (categoría y contexto fijos, la facilidad una vez), la bajada negada con mensajes y limpia sin ellos, y otra vez arriba |
| `tests/unit/test_user_layer_isolation.py` | Las rutas nuevas del lector no importan ningún cliente de modelos ni HTTP; el messenger sigue sin alcanzar Intelligence |
| `web/src/product/support/support.test.tsx` (11) | El contexto en la web (ruta sin consulta, la referencia del último error solo si es reciente, nunca la de una sesión caducada); las 23 preguntas en los dos idiomas y la búsqueda; las categorías y sus palabras; cada error ofrece «Reportar un problema» |
| `web/e2e/support.spec.ts` (6) | Ayuda en dos toques desde tres pantallas; un mensaje desde Ayuda con su contexto, respondido en Soporte, leído, cerrado y valorado (y, con el messenger de QA, los dos correos en el buzón con el número y sin las palabras); desde un error con su referencia y desde un partido con el partido; la hoja a 320 px (opciones grandes, etiquetas, al alcance del dedo, axe 0); los lectores separados; el contacto en la entrada; `FBI_SUPPORT=0` |
| `membership.spec.ts`, `onboarding.spec.ts`, `responsive.spec.ts`, `a11y.spec.ts` | Una cuenta limitada abre Ayuda y escribe; el recorrido sale de Ayuda; `/help` en el recorrido de anchos de teléfono y en axe |

## 13. Puertas

Sobre los árboles finales (backend `c6250bfd`, web `3e27931c`; con esta guía solo cambia `docs/owner`):

| Puerta | Resultado |
| --- | --- |
| Backend | ruff limpio; mypy estricto (500 ficheros) y sobre el árbol entero (1.187) sin errores; **5.913 pruebas** pasan (4 se saltan solas), 11 min 42 s |
| Web | lint 0 errores (los mismos 26 avisos de antes); tipos limpios; **873 pruebas**; build de producción |
| e2e, con narrativa y transparencia encendidas, mensajes encendidos y un WhatsApp de QA | **152 / 2 / 13** (39,0 min). Los 2 fallos, de carga: el armador de Parlays seguía cargando a los 20 s a 1180 × 820 y 844 × 390; repetidos con un proceso: **2 / 2** |
| e2e «como arranca producción» (narrativa apagada, transparencia cerrada, sin WhatsApp) | **152 / 2 / 13** (33,5 min). Los 2 fallos, de memoria de la máquina de pruebas (el núcleo cerró el navegador: «memory cgroup out of memory, chrome-headless»); repetidos con un proceso: **2 / 2** |
| e2e con el autoservicio y el messenger de QA (cuenta, bienvenida, anónimo y soporte) | **33 / 0 / 2** (5,0 min): el acuse y el aviso de respuesta llegan al buzón con el número y el enlace, **sin las palabras** de ninguno |
| e2e con la puerta de membresía encendida | **2 / 0**: una cuenta limitada abre Ayuda y escribe |
| e2e con `FBI_SUPPORT=0` | **1 / 0**: sin mensajes, Ayuda, su contacto y la lectura siguen |
| Accesibilidad (axe, WCAG 2.2 AA) | `/help` a 1440 y 390 px y la hoja a 320 px: **0 incumplimientos** |
| Gitleaks del rango | **0** (los commits de A14 y esta guía) |

Los 13 saltados son los de siempre: los 4 de la app instalada (piden la build de producción), los 5 del autoservicio (corren
en su configuración, arriba), los 2 del glosario que su proyecto de teléfono no ejecuta, el de la membresía limitada y el de
`FBI_SUPPORT=0` (los dos corren en las suyas, arriba).

## 14. Despliegue

- Va **después de A13**, en su propia ventana. Antes: **copia verificada y prueba de restauración**; la `0102` se reencadena
  sobre la última migración desplegada (la `0101` de A13, sobre la `0113` si la IA desplegó antes), sin tocar las ya aplicadas.
- `app.env` **no cambia**: sin la línea, los mensajes están encendidos. `app.env.example` documenta `FBI_SUPPORT`.
- Verificación: revisión `0102`; las cuatro columnas y el disparador; `/api/v1/support/contact` responde 200 sin sesión;
  `/api/v1/me/support` 401 sin sesión; un mensaje de prueba con tu cuenta de lector de P10 (A16), respondido y cerrado.

## 15. Acción manual

**Ninguna nueva.** Lo que completa G10 en producción:

- **P7** (WhatsApp Business): el contacto de Ayuda y de la entrada. Sin él, solo «Reportar un problema».
- **P14** (canal de avisos): para que el aviso de un mensaje urgente te llegue. Sin él, Soporte a diario.
- **P2 y P3** (correo): para que salgan los acuses y los avisos de respuesta.
