# Fase 4 del Plan Maestro IA · El Agente de Estadísticas en sombra: córners y tarjetas

Fecha: 3 nov 2026. Estado: **construida y probada, todavía sin desplegar; no lleva migración y se enciende con una sola palabra más, `stats`, cuando la sombra de la fase 3 ya esté corriendo**. Fuente: Plan Maestro IA (aprobado), fase 4 y secciones 9, 10, 12, 22 y 34, y la arquitectura multiagente (sección 10).

Este documento dice lo que hace el código y **lo vigila una prueba** (`tests/unit/test_ia_fase4_docs.py`): si una cifra de aquí y una constante del código dejan de coincidir, la prueba falla hasta que se corrija una de las dos. La fase que esta amplía está en `IA_FASE3.md`; la de los paquetes y los contratos, en `IA_FASE1.md`; lo que es tuyo (claves, topes de la Console), en `IA_ACCIONES_MANUALES.md`.

## 1. Qué es la Fase 4 y qué no toca

El plan pide **añadir a la sombra de la fase 3 un segundo especialista, el Agente de Estadísticas, que evalúa los córners y las tarjetas del partido completo**, y medirlo durante 14 días antes de que nadie lo lea como evidencia. Es la misma sombra: el mismo Orchestrator, el mismo LAB, los mismos tres motores (`ma-v1`, `ma-v1-h` y `cs-v1`), el mismo calendario de Batch y las mismas guardas. Lo que se añade es una tarea más por partido (la del agente), las selecciones de córners y tarjetas en los nombres `c4`, `c5`... que el servidor da, una evaluación más (`A:stats_evaluation`) en la vista del Council de los dos brazos que leen evaluaciones, y un informe que mide todo eso sin juzgarlo.

| Pieza | Qué hace | Dónde está |
| --- | --- | --- |
| Agente de Estadísticas | una postura por selección de córners o tarjetas, contrato `aa-v1`, Haiku | `ai/agents/stats.py`, `ai/contracts/assessment.py` |
| Prompt | `stats-assess-v3` (desde IA-018; nació como `stats-assess-v1` y fue `stats-assess-v2` desde IA-009): la evidencia es dato, solo códigos, ningún número, y termina con la lista de salida cerrada (`IA_009_SALIDAS_INVALIDAS.md`) que desde IA-018 da los códigos exactos de este agente y las referencias citables del paquete (`IA_018_VALIDEZ_STATS.md`) | `ai/prompts.py` |
| Nombres | `cand-names-v2`: los de goles y resultado no cambian y los recuentos los siguen | `ai/agents/common.py` |
| Factores descriptivos | qué puede mencionar y nunca dar como razón; las dos relaciones del plan | `ai/stats_factors.py` |
| Contradicciones por familia | C05 y C08 leídas por familia (cobertura y cuenta) | `ai/contra.py` |
| Registro | agente `stats` / `stats-v3` (desde IA-018; nació como `stats-v1` y fue `stats-v2` desde IA-009), RETADOR | `ai/agents/registry.py` |
| Orchestrator | la tarea, la porción `stats`, el Batch y el estado de la pasada | `ai/orchestrator.py` |
| Informe de recuentos | CLV, abstenciones, Brier y log loss contra el mercado, sin veredicto | `ai/shadow.py`, `scripts/ia_counts_report.py` |

**No toca**: probabilidades, calibradores, modelos estadísticos, umbrales, filtros, picks ni nada de lo que ve un usuario; ni los motores de `ai.pick_reviews` (no hay motor nuevo, sección 8); ni `ai.evidence` ni `ai.fixture_passes`. Con `stats` fuera de `FBI_AI_AGENTS` la pasada es **la misma que escribió la fase 3**: ninguna fila del agente, ningún candidato de córners o tarjetas, los mismos nombres y las mismas peticiones del Match Agent (una prueba lo compara byte a byte). Los lectores de producción dan las mismas cifras antes y después de una vuelta con el agente encendido (`tests/integration/test_orchestrator_stats.py`).

## 2. El interruptor y la vuelta atrás

No hay variable nueva: el agente es una palabra más de la lista que ya existía.

| Variable | De serie | Qué dice | Activación | Vuelta atrás |
| --- | --- | --- | --- | --- |
| `FBI_AI_AGENTS` | vacío | los agentes que pueden correr: `match`, `council` y `stats` (otro nombre se descarta); el Orchestrator sigue necesitando `match` y `council`, y `stats` por sí solo no enciende nada | `match,council,stats` | `match,council` |

**La secuencia para encender**, y solo con la sombra de la fase 3 ya encendida (sus tres palabras y la acción 15 de `IA_FASE3.md`, secciones 2 y 12):

1. Con una copia fechada de `app.env`, cambiar `FBI_AI_AGENTS=match,council` por `FBI_AI_AGENTS=match,council,stats` y reiniciar el worker.
2. Mirar la primera vuelta: en `ai.agent_tasks` una tarea de agente `stats` por partido que tenga córners o tarjetas, y en `ai.match_runs.model_status` el bloque `stats`.

**La vuelta atrás** es quitar `stats` de la lista y reiniciar el worker: las pasadas siguientes son exactamente las de la fase 3. Lo escrito se queda (tareas, ejecuciones y revisiones, para el análisis); las revisiones de córners y tarjetas ya escritas no se tocan. Una pasada de Batch que estaba en vuelo **conserva el estado de `stats` con el que empezó** (`route.stats`, sección 7): sus claves de idempotencia dependen de los nombres, y cambiar la palabra a mitad de pasada la volvería otra pregunta.

## 3. Sin migración

La fase **no lleva migración** (la última sigue siendo la 0119) y por tanto no cambia nada que desplegar en la base de datos. Lo que necesitaba guardar ya tiene sitio: las tareas y ejecuciones del agente caben en `ai.agent_tasks` y `ai.agent_runs` (sus columnas no restringen el nombre del agente), las revisiones en `ai.pick_reviews` con los motores de la sombra, y los factores descriptivos en `intel.context_factors`, el libro de solo-anexar que acepta cualquier clave de factor. Una migración `0120` no hizo falta.

## 4. El Agente de Estadísticas: qué pregunta y qué hace el servidor con la respuesta

| Quién | Tarea | Modelo | Esfuerzo | Prompt | Contrato |
| --- | --- | --- | --- | --- | --- |
| Agente de Estadísticas | evaluación | Haiku (`claude-haiku-5-5`) | `medium` | `stats-assess-v3` | `aa-v1` |

El modelo y el esfuerzo los fija el router (`router-v1`: la tarea se llama `evaluation`, la misma del Match Agent), nunca el agente. El agente tiene **una sola tarea**, sin modo CONTEXT: las señales del partido son las del Match Agent, y una respuesta en otro modo se rechaza. Lee la porción `stats` del paquete (`mcp-v1`, tope de 18.000 tokens: si no cabe, la tarea se salta y se anota `stats_slice_over_its_cap`) y, en una segunda línea, lo que se le pregunta ahora: el modo, el momento, los minutos al inicio, los candidatos **por su nombre** con los números que el servidor ya conocía, la regla de liquidación de cada familia y las relaciones sin probar.

Lo que el servidor hace con la respuesta, y no solo el prompt:

* **Una respuesta que no es `aa-v1`** (con un campo de probabilidad, cuota, dirección web o frase) no existe: el contrato no tiene sitio donde ponerlo. Lo demás es lo de la fase 3: una respuesta sobre una selección que no se preguntó, a la que le falta una que sí o que cita una referencia que no existe se descarta entera; una postura que no descansa en nada pasa a `NEUTRAL`.
* **Un agente distinto, otro modo o una petición de investigación** invalidan la respuesta: el agente se abstiene, el Council lee las demás evaluaciones y las reglas siguen decidiendo. Las respuestas inválidas se cuentan como las de los otros agentes (`invalid`).
* **Un factor DESCRIPTIVO nunca es razón** (sección 6): la postura que descansa solo en uno baja a `NEUTRAL` y el cambio se dice con el código `rests_only_on_descriptive_factor`.
* **Los córners de una parte nunca entran** (sección 5), y la regla de las tarjetas es la del catálogo (`cards_lines_ft@v1`): cada tarjeta mostrada cuenta una, la roja tras la segunda amarilla cuenta como la roja que es y solo los 90 minutos.

El texto de fuera es dato: las evidencias viajan en bloques `untrusted`, el prompt de sistema dice que lo son, y una postura cuya única referencia es un resumen marcado como orden a un modelo (`instruction_like`) baja a `NEUTRAL`. Las pruebas de la fase meten órdenes en las evidencias y en los nombres de los árbitros y comprueban que lo escrito no cambia.

## 5. Los nombres de los candidatos y lo que nunca se nombra

`cand-names-v2` (`name_with_counts`) se usa solo cuando `stats` está encendido. Los nombres de goles y resultado son **exactamente** los de `cand-names-v1`, así que nada ya guardado cambia de nombre; después de ellos van, en el orden de las familias, el mercado, la selección y la línea, las selecciones de córners y tarjetas del partido completo. El contrato admite 12 nombres: goles y resultado conservan los suyos y los recuentos ocupan los sitios que quedan, el mayor valor esperado primero (`beyond_the_limit` para el resto).

Un mercado de una parte (`CORNERS_OU_1H`: cualquier clave con `1H`, `2H`, `HT`, `FH`, `SH`, `H1`, `H2` o `HALF` en sus partes) **nunca se nombra**: se anota `period_not_settleable`, porque el catálogo no puede liquidarlo (`corners_1h@v1` dice `no_period_data`: el proveedor da los córners como un total del partido) y el propietario no ha elegido una convención para las tarjetas de una parte. Las familias que ningún agente lee siguen como `family_not_read`. Los nombres son una función pura de las selecciones, no del orden en que llegaron.

**De dónde salen los recuentos (IA-014, `fam-counts-v1`).** Producción no revisa córners ni tarjetas: las revisiones `rules` de `ai.pick_reviews` son las de los picks de goles y resultado. Por eso, del 6 al 7 de noviembre de 2026, con `stats` encendido, el agente corrió **0 veces** (`model_status.stats.note = no_count_to_assess` en todas las pasadas). Desde IA-014, con `stats` encendido, la pasada añade a lo revisado por producción las decisiones de las familias (`intel.decisions`, `decision-fam-v1`) del partido conocidas **hasta el momento de la pasada** (`known_at <= known_at` del paquete; nunca una escrita después): la más reciente de cada mercado y modelo, solo de los mercados del partido completo de `COUNT_MARKETS` (`CORNERS_OU`, `CORNERS_OU_HOME/AWAY`, `CORNERS_1X2` con `corners_ft@v1`; lo mismo de `CARDS_*` con `cards_lines_ft@v1`; ni partes, ni amarillas, ni goles de una parte). Los números que lee el agente son los de la decisión (probabilidad, cuota, casas, momento del precio, valor esperado bruto); no hay pick detrás (`pick_id` nulo). Los nombres de goles y resultado no cambian (`cand-names-v2` es la misma función). El estado de la pasada guarda `model_status.stats.counts = {source, decisions}` y cada fila de un candidato de familia (`candidates`, revisiones de la sombra) lleva su `decision_id`, de modo que lo preguntado se deriva de nuevo byte a byte. Una pasada del Batch que empezó antes de IA-014 (sin `route.counts`) se reanuda sin ellos. Límite: una pasada solo existe donde producción revisó algo (`pending`), y una familia no escribe fila cuando un mercado deja de tener valor, así que su última decisión sigue contando hasta el momento de la pasada.

**Opus no ve los recuentos.** Las reglas E1 a E7 de `router-v1` se calculan solo sobre las selecciones de goles y resultado: las 3 llamadas diarias de Opus son del Council de las selecciones que el plan escaló, y un recuento cuyas reglas nadie ha medido no las gasta.

## 6. Los factores DESCRIPTIVOS

Un factor es DESCRIPTIVO mientras una persona no lo valida con un experimento (`python -m scripts.context_factors`); el sistema solo escribe filas DESCRIPTIVO y una restricción de la base de datos rechaza una VALIDATED que no sea de una persona. Para el agente hay dos clases:

* **Los factores del paquete** (la táctica observable, el descanso y la congestión, el cara a cara ponderado): su estado es el del registro (`shared.factors.<clave>.status`). El que no está VALIDATED bloquea su bloque (`shared.tactics`, `shared.schedule`...) y su código de conductor (`TACTICS`, `SCHEDULE`, `H2H`): una postura cuyas referencias están todas dentro de un bloque bloqueado, o cuyos conductores son solo esos códigos, baja a `NEUTRAL`. Una señal sobre uno de esos bloques solo puede ser `NEUTRAL` y `LOW`.
* **Las dos relaciones del plan**: `pressure_shots_corners` (presión, tiros, córners) e `intensity_fouls_cards` (intensidad, faltas, tarjetas). Se registran en `intel.context_factors` como DESCRIPTIVO, con el experimento que las probaría, **una sola vez** (idempotente: la clave única parcial `(factor, version)` ignora un segundo intento) y fallando en abierto, al empezar cada vuelta con `stats` encendido. El agente puede mencionarlas como señal `RATE` con dirección `NEUTRAL` y fuerza `LOW`; una postura nunca descansa en ellas. No están en el catálogo `fbi.intel.factors.CATALOGUE` a propósito: ese catálogo construye el bloque `factors` de **todos** los paquetes y ampliarlo cambiaría lo que lee cualquier revisor. Que existan en el registro no las valida: el F11.6 midió que los totales de goles, córners y tarjetas casi no dependen unos de otros, y nadie ha probado estas relaciones.

## 7. En la sombra: qué lee el Council, el Batch y las fugas

* **Quién lee la evaluación.** Solo los dos motores que ya leían evaluaciones (`ma-v1` y `ma-v1-h`); `cs-v1` no la lee, y por eso comparar los dos con `cs-v1` aísla lo que aporta el agente. Su `engine_version` gana `+stats-v3` cuando el agente está encendido (`ma-v1+match-v4+stats-v3+council-v1+contra-v1+router-v1`; con las versiones de antes de IA-009 era `+stats-v1` detrás de `match-v1`, hasta IA-014 iba detrás de `match-v2` y hasta IA-018 era `+stats-v2` detrás de `match-v3`); con `stats` apagado son exactamente las de la fase 3. La evaluación se cita como `A:stats_evaluation`. Las revisiones de producción (`rules`, `llm`, `combined`) no leen nada de esto y los lectores de `ai.pick_reviews` siguen nombrando sus motores.
* **Contradicciones.** Sobre los recuentos corren las mismas reglas (sección 9). Las cifras del servidor de cada revisión (cuota, probabilidades, valor esperado, cuota justa y mínima) son las de las reglas de producción, copiadas, nunca de un modelo.
* **El calendario de Batch** vale igual que para el Match Agent: la tarea del agente va en la etapa 1, a mitad de precio, en la misma comprobación de toda la pasada, y la etapa 2 (el Council de los brazos que leen evaluaciones) espera a que esté liquidada. La pasada guarda en `route.stats` si el agente estaba encendido cuando se encoló, y ese valor manda hasta que se escribe.
* **Presupuesto y plazos.** La estimación de la pasada suma la tarea del agente antes de gastar nada, y la pausa de un brazo (`pausing`) tiene en cuenta el modelo del agente; el plazo de T-15, el circuito y los cerrojos son los de la sección 8 de `IA_FASE3.md`. Si el partido no tiene ningún recuento que evaluar, no se crea la tarea y el estado de la pasada lo dice (`no_count_to_assess`).
* **Fugas.** `agent_known` y `shadow_review_known` leen al agente como a los otros: su ejecución nombra la porción que leyó, un paquete anterior a ella y evidencia que ya se conocía. Una prueba de integración las ejecuta con una pasada completa del agente y las dos salen con filas y sin violaciones. Además, `slice_known` comparaba la porción guardada en el estado con **todas** las porciones del paquete y el Orchestrator de la fase 3 guardaba solo la que usaba; ahora guarda todas (sección 10, D6).

## 8. Motores y lectores: qué se decidió

El plan (sección 22) cuenta siete brazos y el agente no es uno de ellos: es una **entrada más del Council** de los brazos que ya existen. No hay motor nuevo, así que la restricción `pick_reviews_engine_check` no cambia y no hace falta migración. Las revisiones de córners y tarjetas de los tres motores llevan el mercado en su fila como las demás. El gate `ai-gate-v2` no las lee: su liquidación (`market_outcome`) rechaza un recuento, por lo que ni un córner ni una tarjeta puede mover el veredicto de goles y resultado. Los recuentos se miden aparte (sección 9).

## 9. Contradicciones por familia: C05 y C08

C01 a C08 no cambian (`IA_FASE3.md`, sección 7). Lo nuevo es que el estado de la pasada guarda, para cada familia que tiene candidatos, **qué reglas se pudieron evaluar y cuáles dispararon**: `coverage_by_family` (`evaluated`, `input_missing` o `not_applicable`) y `tally_by_family`, en `ai.match_runs.model_status.stats.contra`. Un cero de una regla que no pudo evaluarse no se lee como un «no hay contradicción».

| Regla | En córners y tarjetas |
| --- | --- |
| C05 (el árbitro tolerante baja las tarjetas Over) | **`input_missing` para tarjetas** y `not_applicable` para córners. Ningún constructor escribe `shared.referee.multiplier`: el multiplicador vive dentro de los pronósticos de `family-v1` y no se guarda. Inventar uno a partir de otras cifras sería una estadística que nadie midió, así que la regla no dispara hasta que el paquete lo lleve |
| C08 (una evaluación apoya y otra objeta selecciones alineadas) | solo se evalúa entre evaluaciones **de la misma familia**; el Match Agent no evalúa recuentos y el agente no evalúa goles, así que entre familias no puede dispararse y se anota |
| C06 | se evalúa para una familia cuando todos sus candidatos tienen la probabilidad del modelo y la del mercado |

## 10. Lo que se puede medir para el gate B

El gate B pide 14 días de evaluaciones. `shadow.counts_report(conn, score, at=...)` (a la que se le da el marcador de las familias, `fbi.families.score`, para que `fbi.ai` no lo importe; y `python -m scripts.ia_counts_report`, que solo lee) devuelve, para cada motor de la sombra, sobre las revisiones de **córners y tarjetas del partido completo** ya liquidadas y escritas antes del inicio:

| Cifra | Cómo se lee |
| --- | --- |
| CLV por evaluación | `by_stance`: las cifras del brazo separadas por la postura que el agente dio (`SUPPORT`, `NEUTRAL`, `CONCERN`, `REJECT_SIGNAL`) o `none` si el motor no leyó ninguna (`cs-v1`); cada una con el CLV del sistema (`fbi.market.closing_value`) |
| abstenciones | `abstentions`: las revisiones `ABSTAIN`, las que el brazo no contestó (`no_answer`) y la tasa |
| Brier y log loss contra el mercado | `versus_market`: ambos del modelo y del mercado sobre **las mismas filas** y la ganancia de uno sobre otro |
| por decisión y por familia | `by_decision` (aprobadas, rebajadas, rechazadas, abstenidas) y `by_family` (córners y tarjetas) |
| lo que se dejó fuera | `left_out`: `half`, `ungradable` (un recuento desconocido o sin liquidar nunca se lee como cero) y `unreadable` |
| los días de evidencia | `evidence`: los días con evaluaciones frente a los 14 que el plan pide |

**El veredicto es siempre `not_judged`** y el informe no se guarda: el plan dice «nunca forzar PASS», nadie fuerza uno desde aquí y el agente no llega a ninguna decisión. Comparar `ma-v1` con `cs-v1` sobre las mismas selecciones es lo que aísla lo que el agente aporta; ninguna de estas cifras tiene todavía una muestra.

## 11. Desviaciones y límites declarados

| Id | Qué | Qué hacer |
| --- | --- | --- |
| D1 | **No hay vista de recuentos en la Consola.** El informe se lee con el script o con `shadow.counts_report`; la pestaña «Sombra» de la fase 3 sigue sin existir | pasa a las vistas de la Consola que `IA_FASE3.md` ya declara pendientes |
| D2 | **C05 no puede dispararse** (sección 9) y C08 no cruza familias | construir el multiplicador del árbitro en el paquete es una decisión de datos, no de esta fase |
| D3 | **El Council no sabe que hay recuentos.** Su prompt (`council-v1`) es el de la fase 3: lee la evaluación como una más y sus candidatos como los demás, sin instrucciones propias de córners y tarjetas | si los 14 días lo piden, un `council-v2` es una versión nueva en el libro |
| D4 | **Opus no escala los recuentos** (sección 5): ni E2 ni E6 se disparan para ellos | se revisa con los 14 días, no antes |
| D5 | **Pocas selecciones y pocas casas.** Con 3 casas de apuestas por partido, muchos partidos tienen pocos recuentos con cuota y probabilidad, y las cifras de la sección 10 pueden tardar en tener muestra | el informe lo dice (`n`, `evidence.days`); nadie lo lee antes de los 14 días |
| D6 | **Corrección de una falla de la fase 3, visible incluso con `stats` apagado.** El Orchestrator guardaba en `ai.match_runs.slices` solo la porción que leía el Match Agent, y la regla `slice_known` comparaba contra todas las del paquete y marcaba esa fila como violación. Ahora guarda todas (`match` y `stats`); es el único cambio que se ve con el agente apagado | ninguna: una prueba lo mantiene y `slice_known` sale limpia |
| D7 | **La batería adversaria no cubre `stats-assess-v2`** (ni cubría la v1), como tampoco cubre los prompts de la fase 3 (`IA_FASE3.md`, D6); la fase sí lleva sus propias pruebas de órdenes metidas en la evidencia | cerrado por `battery-v3` (IA-010), que hoy pregunta `stats-assess-v3` |
| D8 | **Una pasada de Batch en vuelo conserva el estado de `stats`** con el que se encoló aunque la palabra cambie | por diseño (sección 2) |

## 12. Las pruebas y lo que falta

| Pieza | Prueba |
| --- | --- |
| El agente (contrato, lectura, adversarias, factores) | `tests/unit/test_ai_agents_stats.py` |
| El agente en el Orchestrator (tiempo real, Batch, fugas, lectores) | `tests/integration/test_orchestrator_stats.py` |
| Contradicciones por familia | `tests/unit/test_ai_contra.py` |
| El informe de recuentos | `tests/unit/test_ai_shadow_counts.py` y `tests/integration/test_orchestrator_stats.py` |
| Registro y vista de agentes | `tests/unit/test_ai_registry.py` y `tests/integration/test_ai_agents_api.py` |
| Interruptores | `tests/unit/test_ai_shadow_switches.py` |
| Este documento | `tests/unit/test_ia_fase4_docs.py` |

**Lo que falta.** La fase está **terminada en el código y sin desplegar**; como no lleva migración, se despliega con la cadena de lanzamientos de siempre (`backend/deploy/release/`) y `stats` fuera de la lista. Después:

| Falta | Quién | Qué lo cierra |
| --- | --- | --- |
| Que la sombra de la fase 3 esté corriendo (gate A, acción 15) | el tiempo y tú | `IA_FASE3.md`, secciones 2 y 12 |
| Encender `stats` | yo, con tu palabra | la secuencia de la sección 2 |
| 14 días de evaluaciones | el tiempo | `scripts/ia_counts_report.py` con `evidence.enough_days` verdadero y una persona que lo lea |
| Vista de recuentos en la Consola | yo | D1 |
