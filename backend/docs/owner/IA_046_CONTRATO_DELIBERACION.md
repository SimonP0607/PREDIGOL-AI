# IA-046 · Contrato de la deliberación (`INT-C01`)

**Qué es.** El contrato escrito de cómo deliberan los agentes antes de una decisión: qué hace cada voz, qué lee y qué no, qué se comparte, cómo se resuelve cada situación, cuándo se abstiene el sistema y dónde está la frontera entre el código y la IA. Concreta la sección 5.C del Plan Maestro de Intelligence 2026 y describe **el código de `main` tal como está hoy** (10-nov-2026, commit `77518df0`). Las piezas `INT-C02` a `INT-C09` se miden contra él.

**Cómo leerlo.** **HOY** = lo hace el código ahora, en sombra: nada de esto toca una decisión publicada. **OBJETIVO (Cxx)** = lo fija el plan y lo construye la pieza indicada; hoy no existe. **Vn** = una violación: el código hace hoy algo que el contrato prohíbe (sección 10).

**Quién lo vigila.** `tests/unit/test_deliberation_contract.py` falla si un agente recibe un dato que su porción le niega, si un agente recibe la postura de otro, si la etapa de contexto de `decision-v2` puede subir un estado o si el Council puede escribir una probabilidad. Las violaciones de hoy están marcadas `xfail(strict=True)`: cuando se corrijan, la prueba obliga a quitar la marca y su línea de la sección 10.

**Gate.** Tu revisión de este contrato. No cambia comportamiento: es documento y pruebas.

**Lo esencial.**

1. Los números van del modelo a la decisión sin pasar por ningún agente. Ninguna salida de la deliberación tiene un campo donde quepa un número, y la decisión solo lee del Council una palabra.
2. Las posturas van solo al juez. En una ronda real cada agente recibe exactamente la misma pregunta digan lo que digan los demás.
3. La evidencia solo puede bajar un estado, y hoy no llega a ninguna decisión que se publique.
4. Hoy el juez decide todos los casos. Resolver por reglas los casos claros y pedir una sola búsqueda es trabajo de `INT-C05`.
5. Hay tres violaciones, todas en los hallazgos que se entregan a los agentes. La importante es V1: el agente Jugadores, hoy apagado, recibiría la probabilidad del modelo y la del mercado.

## 1. El contrato en seis reglas

| # | Regla | Estado |
| --- | --- | --- |
| 1 | Cada voz lee solo su porción del paquete (`SLICE_BLOCKS`, `fbi/ai/contracts/mcp.py`). | HOY, con tres violaciones en los hallazgos que se le entregan (V1 a V3). |
| 2 | Las posturas van solo al juez. Ningún agente recibe lo que dijo otro y no hay conversación entre ellos. | HOY. |
| 3 | Una pasada estructurada por punto de control y una búsqueda dirigida como mucho. | HOY el tope. La búsqueda misma es OBJETIVO (C05 con B02). |
| 4 | El código clasifica cada candidato y el juez solo resuelve lo que las reglas no resuelven. | OBJETIVO (C05). Hoy el juez se llama siempre. |
| 5 | La deliberación entra en la decisión solo como un estado tipado que solo puede bajar. | HOY en `decision-v2`, que está en sombra. «Sin evidencia no hay RECOMENDADO» es OBJETIVO (C06). |
| 6 | La IA nunca escribe una probabilidad, nunca cambia un umbral y nunca aprueba lo que un gate rechazó. | HOY. |

## 2. Las voces y el juez

| Voz | Hoy | Función | Lee | No lee | Entrega |
| --- | --- | --- | --- | --- | --- |
| **Partido** (`match-v5`, Haiku 5.5) | En sombra, con `match` en `FBI_AI_AGENTS`. Tiene dos tareas: contexto y evaluación. | Da las señales del partido y una postura por candidato de goles y resultado. | Porción `match`: `header`, `shared` sin datos de conteos, `market` y `models` de goles y resultado, y `evidence` (el índice entero). En la evaluación lee además sus candidatos con los números del servidor y los hallazgos de `contra-v1` que los tocan. | Córners, tarjetas y familias de conteos, direcciones web, datos de usuarios, el stake y lo que digan los otros agentes. | `aa-v1`: señales y postura en códigos (SUPPORT, NEUTRAL, CONCERN o REJECT_SIGNAL) con referencias `E:` y `P:`. Como mucho, una petición de investigación de la lista cerrada. |
| **Estadísticas** (`stats-v4`, Haiku 5.5) | En sombra, solo si `stats` está en `FBI_AI_AGENTS`. | Hace lo mismo para los córners y las tarjetas del partido completo: árbitro, estilos y tasas. | Porción `stats`: `header`, `shared` ligero con el árbitro completo y las tasas de cada equipo, `families` (pronósticos de córners y tarjetas) y `evidence` sin traspasos. También sus candidatos con sus números, la regla de liquidación y los hallazgos que los tocan. | Los bloques de precio y de modelo de goles y resultado, las selecciones de goles y resultado, el cara a cara, la forma, el Elo, los escenarios y los traspasos (V3). | `aa-v1`, sin petición de investigación (se rechaza). |
| **Jugadores** (`player-v1`, Haiku 5.5) | Construido y **apagado**. Lo enciende `INT-C04`. | Dice si quién juega favorece o perjudica cada candidato de goles y resultado. | Porción `player`: `header`, `shared` (solo ausencias, alineaciones, historial de jugadores sin faltas ni tarjetas y calidad de los datos) y `evidence` sobre jugadores. Sus candidatos le llegan solo con nombre, familia, mercado, selección y línea. | Probabilidad, precio y valor (V1). Tampoco ningún otro bloque: ni el calendario, ni lo que se juega cada equipo, ni el clima (V2). | `pa-v1`: postura con dirección y sin fuerza. No puede pedir investigación. |
| **Council** (`council-v1`, juez) | En sombra en tres brazos: `ma-v1` (Sonnet), `ma-v1-h` (Haiku, retador) y `cs-v1` (Sonnet sin especialistas, solo si `FBI_AI_ENGINES` lo nombra). Opus entra solo por las reglas E1 a E7. | Juez: da un veredicto por candidato. | La vista `council-view-v1`, de menos de 10.000 tokens: los candidatos con sus números (solo lectura), las posturas de todos los agentes (`A:<etiqueta>`), los hallazgos de `contra-v1` (también C08), el bloque compartido resumido y el índice de evidencia sin dominio. | Nada que no esté en la vista: ni direcciones, ni el dominio de la evidencia, ni texto de fuera sin la marca de no fiable. | `cd-v1`: APPROVE, DOWNGRADE, REJECT o ABSTAIN, con confianza, códigos y referencias, y como mucho una petición de investigación. Nunca un número. |
| **Protocolo** (`council-protocol-v1`) | Código en sombra que solo produce un informe (`python -m scripts.ia_council_v2`). Nada que decide lo importa. | Pesa las posturas, detecta contradicciones entre voces, dice si haría falta una ronda de investigación y propone un estado sin juez. | Las evaluaciones guardadas de Partido y Estadísticas sobre el mismo paquete, los números de cada candidato, las señales de mercado y los veredictos del juez. | Jugadores (no lo pesa) ni ningún texto de un modelo. | Un ajuste `ctx-adj-v1` sin número, con la puntuación y los pesos aparte, en el informe. |

**Qué ve cada voz del modelo y del precio.** Todo en solo lectura: ninguna voz escribe un número.

| Voz | Del modelo | Del precio | Del valor |
| --- | --- | --- | --- |
| Partido | La probabilidad de cada modelo con su intervalo y si está calibrada, el pronóstico, y la probabilidad de cada candidato con su intervalo. | Por selección: probabilidad sin margen, mejor cuota, casa, margen, movimiento, dispersión, número de casas y apertura. Por candidato: cuota, número de casas y hora del precio. | El edge y el EV de cada candidato. |
| Estadísticas | Los pronósticos `family-v1` de córners y tarjetas y la probabilidad de cada candidato suyo con su intervalo. | Solo los de sus candidatos: cuota, probabilidad de mercado, número de casas y hora del precio. | El edge y el EV de sus candidatos. |
| Jugadores | Nada. | Nada. | Nada. Hoy un hallazgo C06 le llevaría la probabilidad del modelo y la del mercado (V1). |
| Council | Probabilidad, intervalo, calibración y modelo de cada candidato. | Probabilidad sin margen, cuota, casa, número de casas, edad del precio, movimiento, dispersión y apertura. | El edge y el EV. |

## 3. Lo que se comparte

- **Un paquete por partido y pasada, con su hora de conocimiento.** `mcp-v1` (versión `package-v3`) se deriva sin modelos del paquete guardado de la pasada. Su `known_at` es la hora de la pasada, y el paquete se rechaza si algo dentro lleva un sello posterior (`PackageLeakError`). La evidencia recuperada o publicada después de esa hora queda fuera y se cuenta. Todas las porciones salen del mismo paquete (mismo hash y misma hora), y cada petición dice como «ahora» esa hora, nunca la del reloj.
- **Cada voz recibe su porción.** El código la corta (`fbi/ai/package.py`) con un tope de 18.000 tokens. Si después de los recortes del plan no cabe, a ese agente no se le pregunta; si la que no cabe es la de Partido, que también es la base de la vista del Council, no corre la pasada. La evidencia llega como índice (id, clase, estado, fuente, fecha y un resumen marcado como no fiable), nunca como dirección.
- **Las posturas van solo hacia el juez.** El orden de una pasada (`fbi/ai/orchestrator.py`) es: Partido contexto, Partido evaluación, Estadísticas, Jugadores, el detector con las posturas, el Council de cada brazo y Opus si una regla lo pide. Los agentes reciben los hallazgos calculados **antes de que nadie hable** (`contra0`: C01 a C07, sin C08). Solo el Council lee el desacuerdo entre agentes (C08) y las posturas (`A:match_evaluation`, `A:stats_evaluation`, `A:player_evaluation`). Las peticiones de los agentes no tienen por dónde recibir una postura, y toda ruta del orquestador, también la del Batch, les entrega `contra0`.
- **No hay conversación.** En cada pasada hay una pregunta por agente y modo, y un Council por brazo. Un segundo Council solo es posible después de una investigación que admita el router, y eso hoy no ocurre en la sombra.

## 4. Cada situación y cómo se resuelve

El plan pide que el código clasifique cada candidato antes de llamar a un juez. Hoy el código calcula casi todas las señales, pero **el juez se llama en todos los casos** y nada de lo calculado se aplica como regla.

| Situación (plan 5.C) | HOY en el código | OBJETIVO |
| --- | --- | --- |
| No hay candidato estadístico. | No se delibera. La sombra solo trabaja las pasadas en las que producción revisó al menos una selección, y sin candidato que nombrar no pregunta a nadie (`no_candidate_to_name`). El candidato es la selección que revisó producción, todavía no la cifra única. | Candidato a partir de la cifra única (A03). |
| Las voces coinciden y ningún hecho verificado va en contra: CONFIRMA. | Decide el juez. El protocolo calcula un estado sin juez solo para el informe: CONFIRMA si la puntuación ponderada llega a 0,5. Mientras ninguna versión esté promovida todas las voces pesan 0 y el protocolo dice SIN_COUNCIL. | CONFIRMA por regla, sin juez (C05). |
| Un hecho oficial o confirmado va en contra: BLOQUEA. | Lo cubren dos reglas de código en la etapa de contexto de la decisión: una baja clave en el lado elegido con las alineaciones ya vistas lleva a RECHAZADO, y sin alineaciones a CAUTELA. Además, `contra-v1` marca C01 y C02 como confirmados y, a menos de 6 h del partido, escala a Opus (E2). El Council decide igualmente. | BLOQUEA por regla (C05). Cuando E6 esté validado, el hecho entra en el modelo y este recalcula (A08). |
| Desacuerdo entre voces, o de una voz con el modelo, apoyado solo en algo reportado o en un rumor: una búsqueda, y FALTA_INFO si no se aclara. | El desacuerdo se calcula (C08 entre agentes; AA1, AM1 y AM2 en el protocolo) y se le entrega al juez. El protocolo dice si haría falta una ronda, pero no busca nada, y la investigación que pide un modelo se ignora en la sombra (`research_ask_ignored`). Ninguna regla mira todavía si la postura se apoya solo en algo reportado. | Una búsqueda dirigida con una pregunta cerrada, una vez. Si la respuesta es oficial o confirmada decide la regla; si no, FALTA_INFO (C05 con B02; el estado de cada afirmación lo dan B04 y B06). |
| La postura se apoya solo en lo que el modelo ya lee, o en un movimiento del precio que ya ocurrió: no pesa. | Solo en el informe del protocolo. Con KN1 (todo lo que mueve la postura ya lo lee el modelo) la postura no empuja: cuenta como una voz neutral. KN2 (el precio ya se movió en ese sentido) se registra, pero no se descuenta. | Se descuenta por regla (C05). |
| El modelo y el mercado difieren en más de 20 puntos y ningún hecho lo explica: RESERVA. | `contra-v1` lo marca (C06, brecha mayor que 0,20) y el router escala a Opus (E6). Nada lo convierte en RESERVA. | RESERVA por regla (C05). |
| Hay hechos verificados en ambos sentidos: decide el juez. | El juez decide todos los casos: Sonnet (`ma-v1`), Haiku (`ma-v1-h`) y Sonnet sin especialistas (`cs-v1`, si está encendido). | El juez solo en este caso (C05). |

## 5. Una búsqueda dirigida como mucho

**HOY** el tope está en el código, pero la búsqueda no:

- **Contratos.** Partido puede pedir **una** investigación por respuesta (`aa-v1`): un tema de la lista cerrada (`availability`, `confirmation` o `preview`), nunca una consulta. El Council también puede pedir una (`cd-v1`). Estadísticas no puede (se rechaza) y Jugadores no tiene campo para ello.
- **Protocolo** (`council-research-v1`). Como mucho **una ronda por partido** con **2 temas** del catálogo. Solo cuando hay una contradicción material (o C07), algo en juego (un EV de al menos 0,02, o un edge de 0,01 si no hay EV) y al menos 20 min hasta el saque. Solo produce un informe.
- **Router** (`router-v1`). Admite una investigación solo con un tema de la lista, sin evidencia vigente, con 20 min o más hasta el saque y con presupuesto. Permite un segundo Council por partido y pasada solo después de una investigación admitida, y nunca más de dos.
- **Orquestador.** En la sombra no se sirve ninguna investigación: solo se cuenta.

**OBJETIVO** (C05 con B02): una búsqueda dirigida a dominios oficiales, con una pregunta cerrada y una sola vez, y un Council por reglas que la lea. El plan habla de «una búsqueda como máximo por candidato» y el protocolo cuenta hoy una ronda por partido: C05 tiene que fijar cuál de las dos.

## 6. Cuándo decide el juez

**HOY** el juez decide siempre que un brazo está activo y su vista cabe, con un veredicto por candidato. Si la vista no cabe, no se le llama (`view_too_large`). `check` convierte en ABSTAIN dos veredictos sin apoyo: un APPROVE sin un código y una referencia a una postura o a un bloque, y un DOWNGRADE o REJECT sin un código y una referencia que exista.

Opus solo entra para los candidatos en que salta una regla, y en la sombra hace como mucho 3 llamadas al día entre los dos brazos. Su veredicto sustituye al primero solo en esos candidatos. Ningún modelo puede pedir Opus. Las reglas son:

- **E1**: el pick del día o una pata de la combinada principal, con confianza baja o media.
- **E2**: una noticia confirmada sobre el candidato a menos de 6 h del partido.
- **E3**: una alineación oficial que deja fuera a 4 titulares habituales o más.
- **E4**: un C08 que el Council resolvió con confianza baja.
- **E5**: un C07 que sigue sin resolverse después de investigar.
- **E6**: una brecha entre modelo y mercado mayor que 0,20.
- **E7**: una aprobación con confianza baja.

E1 y E5 no pueden saltar en la sombra.

**OBJETIVO** (C05): el juez solo en la última fila de la tabla de la sección 4, con Sonnet, y Opus solo por su regla.

## 7. La abstención

**HOY, por código y sin gastar en IA:**

- No se llama a ningún modelo si el paquete está bloqueado, es decir, si los datos de la competición no sirven para pronosticar (`PRODUCT_ONLY`, `INSUFFICIENT`) o el partido está en cuarentena.
- No se delibera si no hay candidato.
- A un agente cuya porción no cabe no se le pregunta. Al Council cuya vista no cabe, tampoco.
- No se hace ninguna llamada que no pueda terminar antes de T-15.
- La pasada no corre si el presupuesto del LAB no alcanza.

**HOY, la IA se abstiene:**

- Una respuesta inválida equivale a que ese agente se abstiene: el Council lee a los demás y la tubería cuantitativa no lo nota.
- El Council puede responder ABSTAIN, y `check` convierte en ABSTAIN un veredicto sin apoyo. En `ctx-adj-v1` eso es FALTA_INFO.

**HOY en `decision-v2` (sombra):**

- Queda en ABSTAIN la selección sin calibrador campeón, la que no tiene EV calibrado con precio, la de un mercado cuya ventaja no está validada fuera de muestra (`edge-gate-v1`, que la valida por mercado y modelo, no por liga) y la de una familia no promovida.
- Un precio de más de 3 h pasa a WATCH. En un punto de control final, un precio de más de 30 min pasa a CAUTION.
- FALTA_INFO pasa a WATCH, sea cual sea la pasada.
- Un partido en cuarentena pasa a REJECTED.

**OBJETIVO** (C06, con A06):

- Sin deliberación válida, o con FALTA_INFO, el candidato queda como mucho en WATCH. Hoy SIN_COUNCIL y CONFIRMA tienen el mismo efecto: ninguno.
- Si en la pasada final sigue faltando información, el sistema se abstiene.
- Con el precio caducado o movido, se pasa a WATCH o se abstiene, a partir del precio del libro y su edad.
- Con los datos en cuarentena, se abstiene; hoy se rechaza.
- Sin ventaja validada para el par de liga y mercado, se abstiene.

## 8. El estado de evidencia tipado: solo puede bajar

- **La palabra.** `ctx-adj-v1` (`fbi/intel/context_adjustment.py`) traduce el veredicto del Council a una de cinco palabras: APPROVE pasa a CONFIRMA, DOWNGRADE a RESERVA, REJECT a BLOQUEA, ABSTAIN respondido a FALTA_INFO, y si no hubo respuesta queda SIN_COUNCIL. El ajuste lleva la gravedad (otra palabra), los códigos, los hallazgos, las ids de la evidencia y los disensos. Ningún número.
- **El efecto en `decision-v2`** (etapa 6, contexto). BLOQUEA lleva a REJECTED, RESERVA a CAUTION y FALTA_INFO a WATCH; CONFIRMA y SIN_COUNCIL no hacen nada. Se aplica el efecto más conservador, así que nunca sube un estado. `decision-v2` solo lee del ajuste la palabra, y la gravedad solo para el texto. La puerta de la ventaja lee el estado **sin** el contexto, para que un contexto negativo nunca saque a una selección de ABSTAIN. Y el Council nunca saca a una selección de la competencia de su partido, así que tampoco puede subir a otra.
- **En `decision-v1`.** `proposed_effect` aplica la misma tabla en el informe de sombra y tampoco sube nunca.
- **Quién lo lee hoy.** Nadie que decida. `decision-v1`, el motor activo, solo lee las revisiones `combined` y `rules`, de modo que el Council de la sombra no llega a ningún pick. `decision-v2` está en sombra, y su repetición de jornadas puede incluir el ajuste (`--council ma-v1`).
- **OBJETIVO.** Con C06, CONFIRMA y SIN_COUNCIL dejan de valer lo mismo: RECOMENDADO exigirá una deliberación válida. Con C07 llega la revisión con la alineación oficial, que solo puede bajar un estado o retirar la selección.

## 9. La frontera entre el código y la IA

- **El código calcula** probabilidades, calibración, margen, valor esperado, CLV, umbrales, edad del precio, estado y vigencia de cada afirmación, contradicciones (`contra-v1`, `council-contra-v1`), pesos (`council-weights-v1`), qué se investiga (`council-research-v1`, `router-v1`), cuándo se escala y el estado final (`decision-v2`).
- **La IA** extrae afirmaciones con su cita, toma posturas tipadas con referencias, juzga y escribe la crónica.
- **Cómo se garantiza hoy:**
  - `aa-v1`, `pa-v1` y `cd-v1` no tienen ningún campo numérico. `FORBIDDEN_WORDS` impide nombres como probability, odds, price, stake, edge, ev, url, query o sql, y cualquier campo desconocido se rechaza (`extra="forbid"`).
  - Los números del candidato los pone el servidor desde el paquete. La confianza que se guarda en `ai.pick_reviews` es un número fijo por palabra (0,35, 0,60 o 0,85) que elige el servidor y que ninguna decisión lee.
  - Los umbrales son constantes de código versionado: `fbi/intel/decision.py` (EV mínimo 0,02, edge mínimo 0,01), los parámetros de `contra-v1` y `router-v1` y las constantes del protocolo. Ninguna salida de un modelo lleva un umbral.
  - Los pesos del protocolo están acotados entre 0,5 y 1,5 y son 0 sin una promoción firmada por ti.
  - Ningún modelo pide Opus ni escribe una consulta o una dirección: la escalada va por reglas y una petición de investigación es un tema de una lista cerrada.

## 10. Violaciones conocidas (vigiladas)

Las tres están en el mismo sitio: `fbi.ai.agents.match._findings`, la función que entrega los hallazgos a Partido, Estadísticas y Jugadores. Recorta los candidatos a los del agente y quita las referencias que su porción no tiene, pero **deja el hallazgo y sus números**. Ninguna toca producción hoy: Jugadores está apagado y Estadísticas solo corre en sombra si está encendido.

- **V1**: Jugadores recibe probabilidad y precio. Un C06 (brecha entre modelo y mercado mayor que 0,20) le llega con `gap`, `detail.p_model` y `detail.p_market`. Eso va contra su porción, su contrato `pa-v1` y lo que dice su propio módulo («no probability, no price, no edge»). Es la más grave, porque es justo el anclaje al mercado que el plan quiere evitar.
- **V2**: Jugadores recibe hallazgos que se apoyan en bloques que no lee: C03 (los días hasta otro partido, que salen del calendario), C04 (lo que se juega cada equipo) y C07 sobre evidencia de una clase que no lee (el clima).
- **V3**: Estadísticas recibe un C07 sobre evidencia de traspasos, una clase que su porción excluye.

**Arreglo propuesto** (no se hace aquí): que `_findings` entregue un hallazgo solo si todo aquello en lo que se apoya está en la porción del agente, y que a Jugadores nunca le lleguen `gap` ni los números del detalle. V1 y V2 conviene corregirlas antes de encender Jugadores (C04): está apagado, así que no se mueve ninguna medición. V3 cambia la entrada de Estadísticas en sombra, así que va con su siguiente versión, después del Gate B.

## 11. Huecos que deben cerrar las piezas siguientes

Hoy no son violaciones, pero rompen el contrato en cuanto se encienda o cambie algo:

- **`ctx-adj-v1` no conoce la etiqueta `player_evaluation`.** Con Jugadores encendido rechazaría las filas de sombra que traen su postura, y las contaría como rechazadas, no como SIN_COUNCIL. Hay que corregirlo antes de C04 y C06.
- **El protocolo solo pesa a Partido y Estadísticas.** `council-weights-v1` y la lectura de evaluaciones `aa-v1` dejan fuera a Jugadores. Lo resuelven C04 y C05.
- **C05 (árbitro permisivo) no se evalúa**, porque ningún constructor escribe `shared.referee.multiplier`. Si alguno lo escribe, la porción de Partido lo dejaría pasar (no está entre las claves de conteos que se quitan), y Partido leería un dato de tarjetas.
- **Una búsqueda por partido o por candidato.** El plan y el protocolo no dicen lo mismo (sección 5). Lo fija C05.
- **La abstención del plan** (sección 7): la cuarentena, el precio en la pasada final, FALTA_INFO en la pasada final y SIN_COUNCIL. Es trabajo de C06.

## 12. Cómo se vigila

`tests/unit/test_deliberation_contract.py` construye un partido en el que salta toda regla de `contra-v1` que hoy tiene entrada (C01, C02, C03, C04, C06 y C07; C05 no la tiene), con candidatos de todas las familias y una brecha de 25 puntos, y lee cada petición tal como la lee el modelo.

| Lo que fija el contrato | Qué comprueba la prueba |
| --- | --- |
| Cada voz lee su porción. | Que la porción sea la suya, con los bloques de `SLICE_BLOCKS`, las claves de su vista y sus clases de evidencia; los campos de cada candidato y las claves de lo que se pregunta; que no llegue ningún dato de otra familia; y que los hallazgos solo vengan de su porción (V1 a V3, en `xfail`). |
| Las posturas van solo al juez. | Las firmas de las peticiones. Tres rondas reales del orquestador con respuestas distintas dan a cada agente la misma pregunta. En el código fuente, toda ruta, también la del Batch, entrega `contra0`. Y el juez lee todas las posturas y el C08. |
| Un paquete, una hora. | Mismo hash y misma hora en todas las porciones; «ahora» es la hora de la pasada; un sello posterior se rechaza y una página leída después queda fuera. |
| La IA no escribe números. | Que `aa-v1`, `pa-v1` y `cd-v1` no tengan campos numéricos ni nombres prohibidos; que el Council no pueda escribir una probabilidad, una cuota, un umbral ni una palabra que suba un estado; que `ctx-adj-v1` no lleve números; y que `decision-v2` solo lea la palabra. |
| Solo baja. | Que ninguna palabra apunte por encima de donde ya está la selección; que en una rejilla de 200 casos por palabra, con cada una de las cuatro gravedades, el estado nunca suba, ningún número cambie y la gravedad no mueva el estado; y que ningún par de palabras levante a otra selección del partido. |
| Una búsqueda como mucho. | Los contratos, la ronda del protocolo y el router. |
| La guía dice lo que hace el código. | Las versiones, los bloques de cada voz, los umbrales y las violaciones declaradas en la sección 10. |
