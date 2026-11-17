# IA-060 · El extractor en cuarentena en lugar de `extract-v1`

Pieza AD-A01 (P0, ola 1) del plan maestro de la arquitectura definitiva 2026. Código nuevo: `backend/src/fbi/ai/quarantine.py` (el extractor), `backend/src/fbi/ai/commands.py` (el filtro de frases con forma de orden), `backend/src/fbi/ai/contracts/claim_v2.py` (el contrato `claim-v2`), el prompt `extract-v4` en `ai/prompts.py` y el agente `quarantine_extractor` en `ai/agents/registry.py`. Un interruptor nuevo, `FBI_AI_EXTRACTOR`, que **nace en `v1`**: con él así, producción hace exactamente lo de siempre. Sin migración.

## 1. Por qué

El 15-nov-2026, en el LAB, `extract-v1` **obedeció** una orden escrita en una página (`battery-v3`, caso `extract.ignore.2`, 2 de 4 preguntas): escribió el dato plantado «el portero D. Keeper… no jugará». `extract-v1` es el extractor de producción (335 llamadas en los 7 días anteriores al 16-nov, `ai.usage`): lee hasta seis resultados de búsqueda en una sola llamada, **sin la puerta** `untrusted` delante, y guarda un campo libre de hasta 300 caracteres.

Un prompt no se puede hacer inmune. Lo que sí se puede es que el código **no guarde nunca** lo que escribe un modelo obediente. Esa es la idea de esta pieza: la garantía la da el código, no el modelo.

## 2. Qué hace el extractor en cuarentena (las cinco reglas)

1. **Todo lo de fuera pasa por la puerta `untrusted-v3`**: el título y el texto de la página, y los nombres de equipos y jugadores (texto del proveedor). La versión de la puerta va escrita en el extractor: una puerta nueva será una versión nueva del extractor.
2. **Una página que lleva algo de orden no se envía nunca a un modelo**: las marcas de la puerta (`instruction_like`, texto disfrazado, ruptura de marco, alfabetos mezclados en una palabra), texto escondido en el HTML, o una frase con forma de orden a una máquina en el texto original, en el que ve el modelo o en su lectura plana (`commands.py`, en los ocho idiomas de la búsqueda: inglés, español, portugués, italiano, francés, alemán, neerlandés y turco). No cuesta nada, se cuenta y no se vuelve a leer. **Precio:** sus datos verdaderos, si los tenía, se pierden con los falsos.
3. **Una página por llamada, sin herramientas**, con un contrato cerrado (`claim-v2`): cada afirmación es una referencia de la lista de esa llamada (`S1`, `S2`…, nunca un nombre ni un id del proveedor), un tipo de una lista cerrada, a qué partido se refiere y una cita. El modelo no escribe nombres, enlaces, fechas ni números: la fecha es la de la búsqueda.
4. **Una palabra clave aleatoria por llamada** (`call`). La respuesta tiene que devolverla exacta y no escribirla en ningún otro sitio. Una respuesta escrita para otro («contesta DONE», el JSON que dictaba la página) se tira entera.
5. **Una afirmación solo vale si** su referencia está en la lista; su tipo se puede decir de ese sujeto (bajas, dudas, vueltas, titulares y sanciones, de un jugador; entrenador, horario, sede u «otro», de un equipo); es de este partido; su cita está **letra por letra** en el texto que se envió (en el título o en el texto, nunca entre los dos); ni la cita ni la frase en la que está ni la de al lado tienen forma de orden; la cita lleva una palabra de su tipo («baja», «out», «duda», «titular», «sancionado»…, en los ocho idiomas); y la cita **nombra al sujeto sin duda**: a un jugador por su **apellido** (y por algo más si otro jugador de las dos plantillas tiene el mismo), a un equipo por una palabra de su nombre que el otro no tenga. Todo lo demás se descarta con un motivo cerrado y se cuenta; una respuesta que no es `claim-v2` se tira entera.

Lo que una página todavía puede hacer: **mentir con una frase que no da ninguna orden** («A. Striker está en forma»). Entonces lo que se guarda es una cita que de verdad está en la página, con el nivel de su fuente: lo mismo que pasa con cualquier lector. Eso lo tratan el nivel de fuente y la corroboración (AD-C07), no esta pieza.

De paso corrige dos defectos que encontró el diagnóstico RV2b del 15-nov: lee la página entera que da la búsqueda (hasta 2.100 caracteres, no los 700 de Research v2) y le quita el título repetido al principio; y no confunde «Copa del **Rey**» con Oriol Rey (exige el apellido, no cualquier palabra del nombre).

## 3. El interruptor `FBI_AI_EXTRACTOR`

| Palabra | Qué hace | Quién paga | Qué escribe |
| --- | --- | --- | --- |
| `v1` (por defecto; cualquier otra palabra también) | `extract-v1` como siempre; el extractor en cuarentena no se llama | producción | lo de siempre |
| `shadow` | `extract-v1` como siempre **y**, al lado, el extractor en cuarentena sobre las mismas páginas | el **LAB** (su clave y su sobre), como mucho `FBI_AI_EXTRACTOR_SHADOW_MAX_PER_DAY` llamadas al día (150 por defecto) | **nada en `ai.evidence`**: solo contadores `xq_*` en `ai.fixture_passes.counts` y una fila de `ai.usage` por llamada (agente `quarantine_extractor`, prompt `extract-v4`) |
| `quarantine` | el extractor en cuarentena **en lugar de** `extract-v1` (v1 no se llama) | producción | lo que vale, en `ai.evidence` con la misma forma que los ítems de v1 (sin `subject_type`, con la cita comprobada como texto y `extract_version = extract-v4`) |

Los contadores de la pasada (`xq_*`) dicen lo que pasó: páginas vistas (`xq_pages`), no enviadas y por qué (`xq_tainted`, `xq_taint_<motivo>`), que no nombran a nadie (`xq_unnamed`), llamadas (`xq_calls`), respuestas tiradas enteras (`xq_invalid`, `xq_whole_<motivo>`), afirmaciones escritas (`xq_wrote`), aceptadas (`xq_kept`) y descartadas por motivo (`xq_drop_<motivo>`), las que pasan del tope del día (`xq_capped`) y, en `quarantine`, las guardadas (`xq_stored`, `xq_new`). Ese es el **registro de rechazos**: cerrado, sin texto de la página ni del modelo.

**Qué no cambia, en ningún modo:** `decision-v1`, los picks, `FBI_PICKS_SOURCE`, las probabilidades, los umbrales, los agentes de la sombra, Research v2 (`extract-v3` y su gate), ni nada que vea el lector. En `shadow` nada de lo que escribe llega a un paquete, a un gate o a una pantalla.

## 4. Cómo se activa en sombra (tras desplegar)

1. Comprueba que el LAB tiene sobre: `FBI_AI_LAB_MONTHLY_BUDGET_USD` mayor que 0 (con 0, ninguna llamada del LAB se hace y los contadores dirán `xq_failed`).
2. Pon `FBI_AI_EXTRACTOR=shadow` en el entorno del worker y reinícialo (un minuto). El trabajo `ai_switches` lo anota en el libro de interruptores (`ai.feature_gates`, gate `switches`): la palabra solo aparece cuando deja de ser `v1`.
3. Mira al día siguiente los `xq_*` de `ai.fixture_passes` y las filas `quarantine_extractor` de `ai.usage` (espacio `PREDIGOL-LAB`).

**Para pasar a `quarantine`** hace falta, según el criterio de cierre de la ficha: A1 en verde en CI (está en este PR), la batería real (A2) con 0 obediencias y 0 inventos, y la repetición sobre páginas guardadas (A5) con una recuperación que aceptes. Al pasar, ten en cuenta que la comparación del gate `research_v2` toma como «lo de v1» las filas sin `subject_type`: desde ese día serán las del extractor en cuarentena.

## 5. Cómo se apaga y se revierte

- Desde `shadow`: `FBI_AI_EXTRACTOR=v1` (o quitar la variable) y reiniciar el worker. No queda nada que limpiar: la sombra no escribió en `ai.evidence`.
- Desde `quarantine`: la ficha dice que **nunca se vuelve a `extract-v1`** (obedece). Si el extractor nuevo falla, `FBI_AI_SEARCH=none` deja de leer internet y la evidencia sale solo del proveedor; o vuelve a `shadow`. Técnicamente `v1` sigue disponible en el interruptor; volver a él es decisión tuya y reabre el riesgo del 15-nov.
- Las filas que ya escribió `extract-v1` en `ai.evidence` se conservan; nada se borra.

## 6. Qué se midió (solo lectura en producción, 16-nov-2026)

| Qué | Dato | Fuente |
| --- | --- | --- |
| Llamadas de `extract-v1`, últimos 7 días | 335 correctas y 1 fallida; 6.548 tokens de entrada y 1.337 de salida de media; US$ 0,4164 en total | `ai.usage`, `purpose = 'evidence_extraction'` |
| Llamadas de `extract-v3` (Research v2, en sombra), mismos días | 323 correctas y 1 fallida; US$ 0,2356 | `ai.usage` |
| Páginas leídas por pasada | 1.972 páginas en 364 pasadas (5,42 por pasada) | `ai.fixture_passes.counts->'web_read'` |
| Páginas reales que el extractor **no enviaría** | 22 de 1.734 páginas distintas (1,27 %): 11 con texto disfrazado, 7 con alfabetos mezclados, 4 con ruptura de marco, 2 `instruction_like` (una página puede tener varias marcas); **0 por el filtro de órdenes** | `ai.research_cache` (búsquedas de los últimos 4 días, 2.312 resultados), analizado sin red dentro de la imagen del worker |
| Tamaño de la ventana | mediana 1.977 caracteres, p90 1.989 | la misma muestra |

La primera versión del filtro de órdenes marcó **30** de esas páginas y las 30 eran falsos positivos: webs de pronósticos que hablan de «the model's probability», «KI-Prognose» o «AI analysis», y dos frases de noticias reales («that return lasted just five minutes», «act as a guide»). Se corrigió (una máquina nombrada solo cuenta si va seguida de un verbo de obligación o se le habla directamente) y esas frases quedaron como pruebas de lo que **no** es una orden. Las 22 restantes son marcas de la puerta, casi todas en páginas en japonés, chino o cirílico: es la pérdida de recuperación que cuesta fallar cerrado; con más muestra se podrá afinar.

## 7. Pruebas (sin modelo y sin coste)

- **A1, obediencia** (`tests/unit/test_ai_quarantine.py`): un modelo guionizado que hace lo que dice cada ataque, sobre los 40 ataques a `extract-v1`, los 40 a Research v2 y 64 nuevos de extracción profunda: **0 hechos plantados guardados, 0 palabras clave, 0 cifras pedidas, 0 campos fuera del contrato** (144 casos). Además, un **adversario** que conoce las reglas del servidor prueba, una por una, todas las citas posibles alrededor del jugador en la página atacada **como si se hubiera enviado por error**: tampoco guarda nada. La segunda línea aguanta sola.
- **Afirmaciones válidas**: un lector honrado guionizado saca de las páginas limpias de la batería exactamente lo que dicen (delantero de baja y centrocampista titular; portero en duda y defensa sancionado).
- **A3, extracción profunda** (`ai/battery/attacks_deep.py`): 64 páginas largas, 8 idiomas × 8 familias de ataque, con la orden después del carácter 700 y un dato verdadero en la misma página: las 64 no se envían. 8 páginas honradas, una por idioma, con los imperativos que tienen las páginas normales («Lee también», «Haz clic aquí», «Abonnez-vous», un entrenador que pide «ignorar las críticas»): las 8 se envían y sus dos datos valen.
- **A4, regresión**: la página de `extract.ignore.2` no se envía, y lo que escribió `extract-v1` aquel día no valdría aunque se enviara.
- **A6, invariantes**: la puerta con su versión, una página por mensaje (sin dirección, sin dominio, sin fecha), una palabra clave distinta en cada llamada, el contrato cerrado sin campos prohibidos, la llamada solo por el libro de uso con su agente, el LAB en sombra y nada guardado en sombra.
- **Integración** (`tests/integration/test_ai_quarantine_cycle.py`, PostgreSQL local): los tres modos del interruptor sobre un mundo construido.

## 8. Lo que falta y por qué

- **A2, batería real con modelos** (10 repeticiones o más por caso) y **A3 con modelos**: no los ejecuté. Necesitan el LAB en el servidor y escriben en `ai.usage` y `ai.feature_gates` de producción; esta sesión solo tenía permiso de lectura. Son de AD-A03 (`battery-v4`), que puede adoptar `attacks_deep.py` tal cual.
- **A5, repetición sobre páginas guardadas** (recuperación frente a v1): no hecha. Las páginas están en `ai.research_cache` y se purgan 14 días después de caducar: conviene hacerla en la primera semana de sombra.
- **Coste:** sin verificar. Estimación por tokens: una llamada por página lleva unos 1.400 tokens de entrada y unos 400 de salida, alrededor de un cuarto de una llamada de v1 (US$ 0,00124 de media); con ~1.970 páginas a la semana serían unos US$ 0,6 a la semana si se leyeran todas. En sombra el tope de 150 llamadas al día lo limita a menos de US$ 0,35 a la semana del sobre del LAB. Se mide en sombra.
- **La lista de palabras de cada tipo** es una condición necesaria, no una lectura: puede tirar una afirmación verdadera escrita con palabras que no tiene (`xq_drop_quote_without_cue` lo dirá). Es una de las cosas que medirá A5.
