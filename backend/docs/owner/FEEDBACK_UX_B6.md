# B6 · Feedback y Novedades: saber si PrediGol le sirve al cliente y contarle qué cambia

Una pregunta al mes, un «¿Te sirvió?» al final de cada análisis y de cada explicación, y una página de Novedades que cuenta lo
que cambia en PrediGol. Todo se salta con un toque, nada da premio y la opinión mejora el producto: **nunca entra en los
modelos**.

## 1. Qué ve el cliente

- **La pregunta del mes.** «¿Qué tan útil te resultó PrediGol este mes?», del 1 («Nada útil») al 5 («Muy útil»). Aparece en una
  tarjeta al pie de la pantalla (sobre la barra de abajo y el botón del parlay en el teléfono; abajo a la izquierda en el
  escritorio), unos segundos después de un **momento útil**: abrir el Análisis PrediGol de un partido, ver el Postpartido de un
  partido terminado o mirar en Mis picks un pick ya liquidado. No le quita el foco a lo que estaba leyendo ni tapa la página.
- **Lo que sigue a la nota.** Con 1, 2 o 3, «¿Qué faltó?»; con 4 o 5, «¿Qué fue lo más útil?». Las dos son opcionales, de hasta
  1.000 caracteres, y la tarjeta avisa: «Sin datos personales: si escribes un correo o un teléfono, lo quitamos». Tras «Enviar»,
  «¡Gracias!» y el camino a Novedades.
- **Se salta con un toque.** «Ahora no» o la cruz la cierran, y entonces no vuelve en 30 días. Si el cliente la ignora y sigue
  navegando, se va con la página siguiente y puede volver en otra visita.
- **Cuándo no aparece nunca:** más de una vez cada 30 días (contados desde la última respuesta o cierre); en la primera semana
  de la cuenta; al entrar; en una visita en la que algo falló (un error a la vista, un error del servidor, la API sin respuesta);
  al dueño, ni siquiera en «Ver como usuario»; mientras está abierta la tarjeta del recorrido guiado.
- **«¿Te sirvió?».** Al final del Análisis PrediGol (sea la narrativa o los hechos: «¿Te sirvió este análisis?») y al final de
  «¿Por qué PrediGol eligió este pick?» («¿Te sirvió esta explicación?»), justo antes del aviso que cierra la explicación. «Sí»
  o «No», con la respuesta del cliente marcada; puede cambiarla y cuenta la última. Tras un «No», «Cuéntanos qué faltó» abre una
  sugerencia (A14) cuando los mensajes a PrediGol están encendidos.
- **Novedades (`/updates`).** En «Más», después de Glosario, con un punto dorado mientras haya una entrada que el cliente no ha
  visto (en la barra de abajo, en el menú «Más» del escritorio y en la fila de Novedades; un lector de pantalla oye «hay
  novedades»). Al abrirla, el punto desaparece. Cada entrada lleva su fecha, su título, lo que cambió y el camino para verlo; una
  entrada dice «Gracias a los comentarios de los lectores» **solo** cuando nació de ellos (hoy ninguna). Al pie, «Enviar una
  sugerencia».
- Todo en español y en inglés.

## 2. Línea base

Antes de B6 no existía ningún canal de opinión: ni encuesta, ni votos, ni una página que contara los cambios. La base de datos no
tenía dónde guardarlos (la migración 0103 crea la tabla).

## 3. Lo que nunca cambia

- **PrediGol Intelligence no se toca.** Ni modelos, ni probabilidades, ni umbrales, ni picks, ni liquidación, ni estados de la
  IA. Nada de Intelligence lee las respuestas: el trabajador de la IA no tiene permiso sobre la tabla (`test_db_roles.py`) y las
  pruebas de aislamiento cubren los módulos nuevos (ninguno llama a un modelo de lenguaje ni a internet).
- **Las seis rutas de cliente responden igual** (la instantánea de forma no cambia).
- **Nada personal:** la tabla guarda la nota, el comentario sin direcciones ni números largos, y dónde se preguntó (el momento y
  la ruta de la página, nada más); ni IP, ni correo, ni el navegador.

## 4. Lo nuevo por dentro

- **Migración 0103: `customer.feedback`.** Una fila por respuesta a la encuesta (`csat`, nota 1–5 y comentario opcional), por
  cierre (`csat_skipped`) y por «¿Te sirvió?» (`helpful`: lo leído —`reading`, `narrative`, `explanation` o, cuando llegue B9,
  `explain`—, su identificador y sí o no). La tabla rechaza lo que nunca debe guardar (una encuesta sin nota, un comentario en un
  voto, dos votos sobre lo mismo, un comentario de más de 1.000 caracteres, un contexto que no es un objeto) y no deja borrar una
  cuenta que tenga respuestas (se anonimiza, A7). Bajar la migración se niega en cuanto hay respuestas.
- **`fbi/customer/feedback.py` y `routers/feedback.py`:** `GET/POST /me/feedback/survey` y `POST /me/feedback/survey/skip` (409
  `survey_not_due` si no toca), `GET/PUT /me/feedback/helpful` (300 votos al día como máximo), `GET/POST /me/updates/seen` (la
  última entrada de Novedades vista, una marca `updates:<id>` junto a las pistas del cliente) y `GET /admin/product/feedback`.
  La encuesta y los votos son medición del producto: pasan por la puerta del consentimiento, nunca por la de la membresía.
- **Web:** `CsatPrompt` (la tarjeta), `HelpfulVote` (la pregunta), `/updates` con su contenido traducido en el repositorio
  (`web/src/product/updates/updates.ts` y los catálogos), el punto de «Más» y la tarjeta «Opinión de los lectores» en
  `/admin/product`.
- **Para ti, en `/admin/product`:** las respuestas del periodo (30, 90 o 365 días) con su n, la media, el CSAT (la parte de 4 y
  5), cada nota con su número y su porcentaje, las respuestas de 1 o 2, los cierres sin responder, los lectores **EN RIESGO**
  (última nota de 2 o menos en 30 días: la señal que B11 usará para que el soporte los atienda), «¿Te sirvió?» por tipo de
  lectura y los comentarios más recientes **sin quién los escribió**. Con menos de 30 respuestas la tarjeta avisa de que la
  muestra es pequeña.
- **Interruptor `FBI_FEEDBACK`:** encendido mientras la línea no está; `FBI_FEEDBACK=0` quita la encuesta y los votos sin
  desplegar (las respuestas se quedan; Novedades sigue).
- **Lo que guarda la cuenta:** las respuestas van en la copia de sus datos (A4) y se borran al anonimizar la cuenta; pasados 24
  meses, el ciclo del messenger las cuenta o las borra con el mismo interruptor de retención que los eventos de producto
  (`FBI_EVENTS_PURGE`: `dry` mientras no esté, que cuenta y no borra).
- **Eventos:** `feedback_submitted` (la nota) y `analysis_helpful_voted` (sí o no), los dos ya en el catálogo cerrado de A6.

## 5. Decisiones que tomé

- **Nunca en la primera semana de la cuenta.** «¿Qué tan útil te resultó PrediGol este mes?» no es una pregunta para quien llegó
  hace diez minutos; el plan no lo prohibía, pero tampoco tiene sentido preguntarlo antes de que el cliente use el producto.
- **Doce segundos después del momento útil**, con la página a la vista: el cliente lee lo que abrió y no se le interrumpe a
  media frase. Ignorada, se va con la página siguiente y cuenta como ofrecida en esa visita.
- **Qué es «un error»:** un error a la vista del cliente, una respuesta 5xx, la API inalcanzable o una respuesta rota. Tras
  cualquiera de ellos, la encuesta espera a otra visita (la pestaña).
- **Los momentos útiles son tres:** el Análisis de un partido con su lectura a la vista, el Postpartido de un partido terminado y
  Mis picks con un pick liquidado. Ni el Inicio ni la entrada.
- **El dueño no responde.** Ni la encuesta ni «¿Te sirvió?» aparecen en una cuenta de administrador, ni en «Ver como usuario»: su
  opinión no debe mezclarse con la de los clientes.
- **Qué se vota:** la lectura o su narrativa, por partido; la explicación, por pick. «Explícame» queda reservado para B9.
- **El comentario no guarda direcciones ni números largos:** un correo, una dirección web o siete cifras seguidas (un teléfono,
  un documento) se sustituyen por «[dato quitado]» antes de guardar.
- **Novedades solo cuenta lo que el cliente puede ver hoy,** con la fecha en que salió; algo apagado para los clientes espera a
  encenderse para aparecer. «Gracias a los comentarios de los lectores» solo cuando sea verdad.
- **Sin NPS por ahora:** el plan lo deja para cuando haya más de unas 100 respuestas por trimestre.

## 6. Pruebas

- **Backend:** unitarias (`test_feedback_rules.py`: el comentario limpio, el contexto, el identificador de una entrada de
  Novedades, el interruptor, los plazos); integración con base real (`test_customer_feedback.py`: los 30 días, la primera semana,
  un voto por cosa leída y el último cuenta, el interruptor apagado, Novedades vista, la vista del dueño frente a SQL escrito en
  la prueba, la copia de datos, la anonimización y la retención); la migración (`test_migration_0103_customer_feedback.py`: nada
  cambia en las demás tablas, cada rechazo de la tabla, la bajada negada con respuestas); los permisos (`test_db_roles.py`); la
  copia de datos (`test_customer_privacy_api.py`).
- **Web (unitarias):** la frecuencia (120 días de visitas: una encuesta cada 30 días, ninguna en un día con error, ninguna dos
  veces en una visita), que solo los tres momentos útiles la traen, la tarjeta (la escala de cinco botones de opción con su
  nombre, la pregunta según la nota, el contador, nada modal), «¿Te sirvió?», Novedades (identificadores, orden, textos en los dos
  idiomas, enlaces que existen, el punto) y la tarjeta del dueño.
- **e2e (`feedback.spec.ts`, proyecto `feedback`):** la encuesta tras abrir un análisis, respondida con el teclado, con el
  comentario limpio y el contexto en la base; que no vuelve; a 320 px sobre la barra, con objetivos de 44 px y axe limpio,
  cerrada con «Ahora no»; nunca tras un error aunque toque; nunca en la primera semana; los votos de la lectura y de la
  explicación guardados con su contexto y el último que cuenta; Novedades y su punto; `/admin/product`; y, con
  `FBI_FEEDBACK=0`, nada que preguntar.

## 7. Puertas

PUERTAS_B6

## 8. Despliegue

Backend y web juntos (el contrato cruza los dos), con la migración 0103: **copia → prueba de restauración → migración →
validación → despliegue**. Va en el paquete `ux-b7` junto con B7 (una sola tanda de puertas y de e2e para los dos), sobre
`ux-b5`. **Vuelta atrás:** `FBI_FEEDBACK=0` en `app.env` (con su copia fechada y, al final, `predigolctl config-baseline`, el
último paso de cualquier cambio en un fichero de entorno desde `sec-s3`) quita las preguntas sin desplegar y las respuestas se
quedan; la web anterior funciona con este backend (la API es aditiva). La bajada de la 0103 solo es posible mientras no haya
respuestas.

## 9. Acción manual

Ninguna. Cuando quieras, mira la tarjeta «Opinión de los lectores» en `/admin/product`.
