# Fase 3 del Plan Maestro IA · El multiagente en sombra: Orchestrator, Match Agent y Council

Fecha: 3 nov 2026. Estado: **construida y probada, todavía sin desplegar; se despliega apagada (con la migración 0119) y se enciende solo cuando haya pasado el gate A y hayas hecho la acción 15** (la fase lleva una sola migración, la 0119). Fuente: Plan Maestro IA (aprobado), fase 3 y secciones 9, 11, 17, 18, 22, 23, 24, 31 y 34.

Este documento dice lo que hace el código y **lo vigila una prueba** (`tests/unit/test_ia_fase3_docs.py`): si una cifra de aquí y una constante del código dejan de coincidir, la prueba falla hasta que se corrija una de las dos. Lo que es tuyo (claves, topes de la Console) está en `IA_ACCIONES_MANUALES.md`; la fase anterior, en `IA_FASE2.md`; la de los paquetes y los contratos, en `IA_FASE1.md`; el punto de partida medido, en `IA_BASELINE_F0.md`.

## 1. Qué es la Fase 3 y qué no toca

El objetivo del plan para esta fase es **correr el multiagente de goles y resultado en sombra, en el LAB, sobre una muestra de los partidos con candidatos**, y comparar lo que dice con lo que dicen la IA de hoy y las reglas. «En sombra» quiere decir tres cosas, todas vigiladas por pruebas: lo que escribe no lo lee ninguna decisión ni ningún usuario; cada llamada a un modelo se paga en el workspace del LAB, no en el de producción; y un fallo suyo nunca detiene el cálculo de los picks (cae a las reglas). El Orchestrator no inventa nada: el servidor nombra las selecciones (`c1`, `c2`...), los modelos solo contestan con códigos de vocabularios cerrados (`aa-v1`, `cd-v1`) y todo número que un modelo lee lo ha escrito el servidor.

| Pieza | Qué hace | Dónde está |
| --- | --- | --- |
| Interruptores | tres palabras (`FBI_AI_ENGINES`, `FBI_AI_SHADOW_SAMPLE`, `FBI_AI_AGENTS`) y la propiedad `orchestrate` | `ai/config.py`, `ai/gates.py` |
| Brazos y asignación | a qué brazo va cada partido, una vez y para siempre | `ai/arms.py`, migración `0119` |
| Orchestrator | la vuelta que elige las pasadas, llama a los agentes y escribe la sombra | `ai/orchestrator.py`, `ai/orchestrator_store.py` |
| Match Agent | señales y una postura por selección, contrato `aa-v1` | `ai/agents/match.py`, `ai/contracts/assessment.py` |
| Contradicciones | el detector `contra-v1` de las contradicciones C01 a C08 | `ai/contra.py` |
| Council | un veredicto por selección, contrato `cd-v1` | `ai/agents/council.py`, `ai/contracts/council.py` |
| Router | qué modelo, qué esfuerzo y cuándo Opus (`router-v1`) | `ai/router.py` |
| Guardas | concurrencia, circuito, reintentos, plazo de T-15 y pausa de un brazo | `ai/runtime.py` |
| Trabajo del worker | `ai_orchestrate`, un ciclo de tipo `orchestrate` por vuelta | `apps/worker/scheduler.py` |
| Auditoría de fugas | las reglas nuevas `agent_known` y `shadow_review_known` | `intel/leakage.py` |
| Consola | los tres motores de la sombra en las listas de motores | `api/services/ai_layer.py`, `web/src/live/AiLayerLive.tsx` |

**No toca**: probabilidades, calibradores, modelos estadísticos, umbrales, filtros, picks ni nada de lo que ve un usuario. Con los valores de serie (los tres interruptores apagados) el worker mira cada 5 minutos si la sombra está encendida, ve que no, y no abre ni una conexión. Los motores `ma-v1`, `ma-v1-h` y `cs-v1` **nunca llegan al filtro 6** de la capa de decisión: la decisión lee solo las revisiones `combined` y `rules` (`intel/decision.py`), y cada lector de `ai.pick_reviews` que cuenta una cifra de producción nombra los motores de producción (`rules`, `llm`, `combined`) para que una fila de la sombra no mueva ninguna: así lo hacen `ai/gate_a.py`, `ai/costs.py`, `ai/gate_research.py`, `ai/postmortem.py`, `ai/shadow.py` e `intel/match_review.py`, y una prueba (`tests/unit/test_engine_filter_guard.py`) falla si aparece un lector nuevo que no lo haga. La fase tampoco escribe en `ai.evidence` ni en `ai.fixture_passes`: los agentes de la sombra no buscan, no llaman a MCP y no investigan.

## 2. Los tres interruptores y la vuelta atrás

La sombra necesita **las tres palabras a la vez**. Si falta una, o si `FBI_AI_MODE` vale `off`, la propiedad `orchestrate` es falsa y el trabajo no hace nada. Cada palabra, como las demás del servicio, se valida recortando, nunca lanza un error, y un error de tecleo apaga: la sombra gasta dinero, así que una palabra que el código no conoce solo puede dejarla como estaba.

| Variable | De serie | Qué dice | Activación del plan | Vuelta atrás |
| --- | --- | --- | --- | --- |
| `FBI_AI_ENGINES` | `rules,llm` | los motores que revisan, separados por comas, sin importar mayúsculas ni espacios; `rules` y `llm` están siempre (la línea base de producción) y la lista solo puede **añadir** `ma-v1`, `ma-v1-h` y `cs-v1`; un nombre que no es ninguno se descarta | `rules,llm,ma-v1,ma-v1-h` | `rules,llm` |
| `FBI_AI_SHADOW_SAMPLE` | `0` | la parte de los partidos con candidatos sobre la que corre la sombra, de 0 a 1 (`0.3` es el 30 %); más de 1 cuenta como 1, menos de 0 como 0 y lo que no es un número, como 0 | `0.3` | `0` |
| `FBI_AI_AGENTS` | vacío | los agentes que pueden correr: `match` y `council` (otro nombre se descarta); el Orchestrator necesita los dos | `match,council` | vacío o quitar uno |

Aparte, `FBI_AI_ORCHESTRATE_MINUTES` (de serie 5, nunca menos de 1) dice cada cuánto mira el trabajo `ai_orchestrate`; no es un interruptor.

**La secuencia exacta para encender**, y solo en este orden:

1. Que el gate A haya dado `PASA` y que hayas hecho la **acción 15** (sección 12): sin ella el LAB tiene su sobre de la fase 0 (15 US$) y la sombra se parará sola por dinero.
2. Que el worker tenga la clave del LAB (`FBI_AI_KEY_ANTHROPIC_LAB`) y los tres modelos de los niveles con los nombres del router (`FBI_AI_MODEL_BULK`, `FBI_AI_MODEL_ANALYSIS` y `FBI_AI_MODEL_FINAL`, que valen Haiku, Sonnet y Opus 5.5): si el modelo configurado de un nivel no es el del router, esa tarea no se pregunta y se anota `model_not_configured`.
3. Con una copia fechada de `app.env`, poner las tres palabras: `FBI_AI_ENGINES=rules,llm,ma-v1,ma-v1-h`, `FBI_AI_SHADOW_SAMPLE=0.3` y `FBI_AI_AGENTS=match,council`, y reiniciar el worker (un cambio en `app.env` rige cuando se reinicia).
4. Mirar la primera vuelta: una fila de `ai.cycles` de tipo `orchestrate` con `skipped` vacío en sus cuentas.

La muestra se fija antes de arrancar y no se cambia a mitad del experimento: subirla solo **añade** partidos (sección 4). Las tres palabras entran en el libro de palabras del propietario (`ai.feature_gates`, gate `switches`) solo cuando se mueven de su valor de serie: el día que se encienden es un día en que cambió la configuración, y el día en que se despliega el código que las conoce no lo es.

| Qué quieres deshacer | Cómo | Qué se conserva |
| --- | --- | --- |
| Que la sombra corra | `FBI_AI_SHADOW_SAMPLE=0` (o `FBI_AI_ENGINES=rules,llm`) y reiniciar el worker | todo lo escrito: tareas, ejecuciones, estados y revisiones, para el análisis |
| Un brazo concreto | quitar su motor de `FBI_AI_ENGINES` | las asignaciones: volver a ponerlo no redistribuye los grupos |
| Que la sombra gaste | cerrar el sobre del LAB (`FBI_AI_LAB_MONTHLY_BUDGET_USD=0`): la vuelta se para con `no_envelope` | todo lo escrito |
| Toda la fase | las dos palabras de arriba; después, si hiciera falta, la versión anterior del código sobre la 0119 (sección 3) | tablas, columnas y filas: nada se borra |

## 3. La migración 0119 y cómo se despliega

La 0119 es **aditiva** y hace tres cosas:

| Qué | Cómo |
| --- | --- |
| `ai.pick_reviews` | la restricción `pick_reviews_engine_check` admite además `ma-v1`, `ma-v1-h` y `cs-v1`; las filas escritas no se tocan |
| `ai.cycles` | la restricción `cycles_kind_check` admite además `orchestrate`: el trabajo tiene su propia fila en el libro de ciclos y un fallo suyo no puede deshacer el ciclo del paquete ni el del análisis |
| `ai.shadow_assignments` | tabla nueva, solo-anexar (`shadow_assignments_append_only`): experimento, partido, cubo, si está en la muestra, si va a COUNCIL SOLO, la parte de la muestra vigente ese día y cuándo se asignó; sin claves foráneas, y con dos restricciones que repiten la regla del código (`shadow_assignments_sample_rule` y `shadow_assignments_solo_is_sampled`) |

Espera como máximo 10 segundos un bloqueo (`SET LOCAL lock_timeout`) y toca primero las dos tablas ocupadas, así que si no consigue el bloqueo se para antes de haber hecho nada. `ai.pick_reviews` es la que se valida entera al ampliar la lista: son 115.220 filas medidas el 25 oct 2026 (`IA_BASELINE_F0.md`), una pasada por la tabla con el bloqueo tomado solo ese rato.

**Cómo se despliega.** Por la cadena de lanzamientos de siempre (`backend/deploy/release/`): comprobación de hashes, precomprobación de solo lectura, **copia de seguridad y prueba de restauración de esa misma copia**, despliegue con `predigolctl` (que aplica la migración), prueba de humo, verificación y seguimientos a los 10, 30 y 60 minutos; se detiene en el primer fallo y no deshace nada por sí sola. Lo que hace falta de la fase es que la verificación del lanzamiento compruebe los tres objetos de la 0119 y que `FBI_AI_ENGINES`, `FBI_AI_SHADOW_SAMPLE` y `FBI_AI_AGENTS` sigan sin definir en el worker. Las cifras de ese lanzamiento (minutos de la copia, segundos de la restauración, comprobaciones en verde) se anotan cuando ocurra; hoy no hay ninguna que declarar.

**Por qué se puede desplegar apagada, y cómo se baja.** El código de antes no escribe los motores nuevos ni el tipo de ciclo nuevo y no conoce la tabla. Bajar con `alembic downgrade` (una herramienta de desarrollo) borra `ai.shadow_assignments`, cierra como fallidos los ciclos `orchestrate` que sigan corriendo y devuelve las dos listas **sin validar**; las revisiones ya escritas con un motor de la sombra se quedan (una revisión es evidencia). **Una advertencia:** la vuelta atrás normal son las palabras de la sección 2, no desplegar la versión anterior. Los lectores de producción que ahora nombran sus motores eran, en la versión anterior, lectores que no filtraban por motor; con filas de la sombra ya escritas, esa versión las contaría en cuatro cifras (el gate A, los costes, el estudio de partidos terminados y el de revisiones de un partido). Por eso, si se llega a desplegar atrás con la sombra ya corrida, esas cuatro cifras se leen sabiendo que hay filas de más.

## 4. Los siete brazos y la regla de asignación

El plan compara siete brazos sobre las mismas selecciones. Cuatro no cuestan nada que el Orchestrator tenga que correr, porque son lo que producción ya calcula; tres son motores de la sombra, que sí corren.

| Brazo | Motor | Muestra | Quién lo calcula |
| --- | --- | --- | --- |
| MODELO SOLO, FILTRO DE BRECHA | (no es una revisión) | 100 % | producción |
| REGLAS | `rules` | 100 % | producción |
| IA ACTUAL | `llm` | su cobertura | producción |
| MULTIAGENTE | `ma-v1` | la muestra | el Orchestrator: Match Agent, contradicciones y Council Sonnet (Opus por regla) |
| MULTIAGENTE + COUNCIL HAIKU | `ma-v1-h` | la misma muestra | lo mismo con Haiku de juez, el mismo calendario y las mismas reglas de Opus |
| COUNCIL SOLO | `cs-v1` | la mitad de la muestra (el 15 % de todos los partidos con la muestra al 30 %) | el Council Sonnet leyendo la vista compacta sin especialistas |

**La regla de asignación** (`ai/arms.py`, versión `arms-v1`; no se edita, se versiona):

* El cubo de un partido es el número de 0 a 9.999 que sale de los primeros ocho bytes (en orden grande) de `sha256("<sal>:<fixture_id>")` módulo 10.000. La sal del experimento es **`ma-shadow-v1`**. No usa `hash()` (que Python cambia en cada arranque) ni reloj ni estado: es el mismo en cualquier worker.
* Un partido está en la muestra cuando `cubo < parte × 10.000`, comparado de forma exacta. Las muestras son **anidadas**: un partido de la muestra al 30 % está en la del 50 %, así que subir la parte solo añade partidos.
* Un partido de la muestra corre `ma-v1` y `ma-v1-h`; corre además `cs-v1` si un **segundo** hash, `sha256("<sal>:cs:<fixture_id>")` reducido igual, cae en la primera mitad de los cubos. Son dos textos distintos, así que COUNCIL SOLO no es la mitad baja de la muestra sino una mitad repartida como el resto.
* La asignación se escribe **una vez y antes de gastar nada** (el Orchestrator confirma la transacción antes de la primera llamada). La primera fila de un partido manda y no cambia nunca: «ningún partido cambia de grupo». Un partido visto con la muestra al 30 % y fuera de ella sigue fuera aunque subas la parte al 50 %; solo los partidos vistos después se asignan con la parte nueva. La tabla se niega a guardar una fila que contradiga la regla.
* `FBI_AI_ENGINES` puede estrechar los brazos sin tocar los grupos: la asignación dice en qué está un partido y `runnable` dice qué corre hoy. Como la activación del plan no nombra `cs-v1`, **COUNCIL SOLO no corre hasta que lo añadas** (sección 13, D1).

## 5. El Orchestrator: qué hace cada vuelta

El trabajo `ai_orchestrate` (cada 5 minutos, un solo ejemplar a la vez, sin tomar el cerrojo del ciclo de análisis, sin el límite de tiempo de los otros trabajos) abre una fila de `ai.cycles` de tipo `orchestrate`, llama a `orchestrator.run` con 20 pasadas como máximo y 240 segundos para empezar pasadas nuevas, y cierra la fila con el informe. **Nunca lanza un error al reloj del worker**: lo que sale mal con un partido se deshace, se cuenta en `failed_open` y la vuelta sigue.

1. **Trabajo.** Las pasadas de la capa que guardaron un paquete antes del inicio, terminaron bien (`ok` o `partial`) en los últimos 2 días, cuyo partido aún no ha empezado, que producción revisó con al menos una selección (una revisión `rules` de ese paquete) y que no tienen todavía sombra. Primero las que aún pueden terminar antes de T-15. Se asigna cada partido a su brazo y se confirma; solo corren los de la muestra y solo los motores que `runnable` permite.
2. **Candidatos.** Exactamente las selecciones que producción revisó en esa pasada, con las tres puntuaciones y las cuotas justa y mínima de las **reglas**: ningún modelo escribe un número. Los nombres `c1`...`c12` son una función pura de las selecciones (primero la familia, luego el mercado, la selección y la línea; si hay más de 12 se quedan las de mayor valor esperado). Solo se nombran las familias de goles y resultado (`1X2`, `DC`, `AH`, `OU`, `BTTS`); córners y tarjetas se anotan como `family_not_read` y no se revisan.
3. **Llamadas**, siempre por el mismo sitio (`usage.call_json` con `lab=True`; las pasadas lejanas, por el Batch, más abajo) y en este orden: el Match Agent en modo CONTEXT y en modo EVALUATION, una vez por partido; el detector `contra-v1` sobre todo el paquete; el Council de cada brazo (`ma-v1` y `ma-v1-h` leen la misma vista con las posturas del Match Agent; `cs-v1` la lee sin ellas); y, solo para las selecciones en que se dispara una regla E1 a E7, Opus (sección 6).
4. **Escritura**, una transacción por partido: las tareas y ejecuciones (`ai.agent_tasks`, `ai.agent_runs`), **una** fila de `ai.match_runs` con `run_kind = 'shadow'` (la vista `ai.match_state` solo lee `live`) y **una** revisión de `ai.pick_reviews` con `mode = 'shadow'` por selección y motor. Las llamadas en sí ya están en `ai.usage`, escritas por `call_json` por su cuenta: sobreviven a un deshacer del partido.
5. **Cuando no se puede preguntar a ningún modelo** (el paquete está bloqueado, no hay selección que nombrar, la porción del partido pasa su tope, todos los brazos están pausados) se escribe igualmente el estado con el motivo y una revisión de reserva por selección y motor (`ABSTAIN`, estado `fallback`, confianza 0), para que la pasada no se vuelva a elegir y la comparación la cuente como lo que fue.

Una vuelta es **idempotente**: la segunda sobre las mismas pasadas no encuentra nada que hacer. Cada tarea lleva una clave de idempotencia (`idem-v1`); una pregunta ya guardada se lee y no se paga otra vez, y una pregunta idéntica de los dos brazos del multiagente (la de Opus) se hace una vez y se reparte. Dos trabajadores que escriban a la vez la misma pasada: el segundo ve la fila del primero y no guarda nada.

**El calendario de Batch.** Una pasada `first` o `pre` con el partido lejos (la regla de la cola: la pasada es `first` o `pre`, faltan al menos `FBI_AI_BATCH_MIN_LEAD_MINUTES`, 240 de serie, y la puerta `batch` cubre el modelo de **todos** los niveles que la pasada usa) viaja por la API de lotes del LAB, a mitad de precio. Se decide **una vez** y queda escrito en sus tareas (`route.mode = 'batch'`): una pasada es síncrona o de Batch, nunca las dos, y una pasada de Batch **no vuelve nunca al tiempo real**. Las pasadas `final` y las cercanas siguen como siempre. No hay interruptor nuevo: lo enciende la puerta `batch` (o `FBI_AI_BATCH`) que ya existe.

La pasada es una máquina de estados que avanza una vuelta tras otra (la vuelta corre cada 5 minutos y recoge la pasada en cuanto ninguno de sus ítems sigue abierto):

| Etapa | Qué se pregunta | Cuándo |
| --- | --- | --- |
| 1 | el Match Agent en CONTEXT y EVALUATION (Haiku) y el Council que no lee posturas (`cs-v1`) | tras **una** comprobación de toda la pasada, a mitad de precio, contra lo que queda del día del LAB: si no cabe no se encola nada |
| 2 | el Council de `ma-v1` y `ma-v1-h`, con las posturas guardadas de la etapa 1 | cuando la etapa 1 está liquidada |
| 3 | Opus, solo para las selecciones en que se dispara una regla E1 a E7 | cuando la etapa 2 está liquidada; las horas al inicio que leen las reglas se congelan en la primera tarea de Opus |

Cada tarea se guarda `queued` (`ai.agent_tasks`, con el identificador de su ítem de lote en `route` y su `batch_id`) en la misma transacción que su ítem, y **el mismo ciclo del trabajo envía el lote** (`flush`): un lote que se queda `submitting` es lo que el sondeo da por no enviado a los 30 minutos. El sondeo (`ai_batch_poll`) guarda la **respuesta cruda** en el ítem (`lab.settle_lab`, rama `shadow`); la etapa siguiente la valida contra la vista que reconstruye del paquete guardado, con las mismas funciones que en tiempo real, y la pasada **se escribe cuando se liquida su última etapa**, con el mismo escritor: las tareas pasan por `queued`, `running` y `done` con sus ejecuciones, **una** fila `shadow` de `ai.match_runs` y las revisiones, con la misma forma que las de una pasada en tiempo real (una prueba compara las dos filas a fila). Lo que sale mal es un brazo `fallback` con su código y sin cobro: `batch_errored`, `batch_canceled`, `batch_expired`, `batch_abandoned` (un ítem que nunca se envió se vuelve a pedir a la cola, que tiene su límite de intentos), `batch_missing`, `batch_refused_<motivo>`; un límite del workspace (400 o 429) es **agotado**: no se encola más. Una etapa que ya no se puede encolar (faltan menos de 160 minutos) o un ítem que sigue abierto a 100 minutos del inicio (donde empieza la pasada `final`) termina la pasada como `batch_too_late`: queda escrita, con `final.too_late` verdadero, y nunca se pregunta en tiempo real. Las tareas en cola de un partido que ya empezó se cierran `expired` (`kickoff_passed`), y si el paquete de una pasada que espera cambió, se cierra sin preguntar de nuevo (`package_changed`).

**El informe** (`Report.to_json()`, solo cuentas y códigos; es lo que guarda `ai.cycles.counts`): `skipped` (`off` si la sombra está apagada), `considered`, `sampled`, `ran`, `not_run`, `failed_open`, `calls`, `cost_usd`, `invalid`, `budget_stop`, `circuit_open`, `paused`, `too_late`, `escalated`, `escalation_skipped`, `reused`, `queued` (tareas enviadas al Batch en la vuelta), `waiting` (pasadas que esperan un ítem), `settled` (tareas de Batch leídas al escribir su pasada) y `abandoned` (tareas dadas por perdidas por el plazo). El ciclo queda `ok` si nada falló, `partial` si alguna pasada falló y otras corrieron, y `failed` si ninguna corrió.

**Lo que escribe cada revisión.** El veredicto del Council (o el de Opus donde Opus contestó), la confianza como número fijo (`LOW` 0,35, `MEDIUM` 0,60, `HIGH` 0,85; sin veredicto, 0), los conductores, los riesgos, las referencias, las contradicciones que tocan la selección y, para los motores con Match Agent, la postura de cada evaluación. La versión del motor nombra lo que lo compone: `ma-v1+match-v1+council-v1+contra-v1+router-v1`, o `cs-v1+council-v1+router-v1`. El estado de una revisión es `ok`, `fallback`, `invalid_output`, `failed` u `over_budget`.

## 6. El Match Agent y el Council: contratos y modelos

El modelo y el esfuerzo de cada tarea **los fija el router** (`router-v1`), nunca el agente, y no cambian llamada a llamada.

| Quién | Tarea | Modelo | Esfuerzo | Prompt | Contrato |
| --- | --- | --- | --- | --- | --- |
| Match Agent | contexto | Haiku (`claude-haiku-5-5`) | `low` | `match-context-v1` | `aa-v1` |
| Match Agent | evaluación | Haiku (`claude-haiku-5-5`) | `medium` | `match-assess-v1` | `aa-v1` |
| Council | veredicto | Sonnet (`claude-sonnet-5-5`) | `medium` | `council-v1` | `cd-v1` |
| Council | escalada | Opus (`claude-opus-5-5`) | `medium` | `council-opus-v1` | `cd-v1` |
| Council (brazo `ma-v1-h`) | veredicto | Haiku | `medium` | `council-v1` | `cd-v1` |

Los dos agentes nacen **RETADORES** en el registro (`match-v1`, `council-v1`) y solo llegan a campeones por una fila que firmes en `intel.promotions`. Un cambio de prompt, de esquema, de modelo o de esfuerzo es una versión nueva anotada en el libro; una etiqueta de prompt no nombra nunca dos textos.

**`aa-v1`** (Match Agent): hasta 12 señales y 12 candidatos, y como mucho 8 referencias, 4 conductores y 4 riesgos por candidato. Cada postura es `SUPPORT`, `NEUTRAL`, `CONCERN` o `REJECT_SIGNAL`. Puede pedir una investigación de un tema de la lista cerrada (`availability`, `confirmation`, `preview`), nunca una consulta. **`cd-v1`** (Council): un veredicto por selección (`APPROVE`, `DOWNGRADE`, `REJECT` o `ABSTAIN`) con su confianza (`LOW`, `MEDIUM`, `HIGH`), hasta 4 conductores y 4 riesgos, y hasta 8 referencias; como mucho una petición de investigación. Ninguno de los dos tiene campo para una probabilidad, una cuota, una apuesta, una dirección web, una consulta o SQL, ni para pedir Opus: lo que no tiene campo no se puede escribir.

**Lo que hace el servidor con la respuesta** (`check` de cada contrato): una respuesta sobre una selección que no se preguntó, a la que le falta una que sí o que cita una referencia que no existe se descarta entera y vale como no contestada (el Council lee las demás, o decide el revisor de reglas). Una postura que no descansa en nada pasa a `NEUTRAL`, y un `APPROVE` sin un conductor y una referencia que se sostenga, o un `REJECT` o `DOWNGRADE` sin motivo y referencia, pasan a `ABSTAIN`. Una postura cuya única referencia es una evidencia marcada como orden a un modelo (`instruction_like`) baja a `NEUTRAL`. **Un veredicto del Council nunca sube un estado**: el filtro 6 combina como siempre, gana el más conservador (y en la sombra ni siquiera llega a él).

**El texto de fuera es dato.** Los resúmenes de las evidencias viajan en bloques `untrusted`, cada prompt de sistema dice que lo son y que no obedecen, y la vista del Council nunca lleva una dirección web. Las pruebas de la fase meten órdenes en las evidencias y comprueban que el veredicto y las filas no cambian.

**La vista del Council** (`council-view-v1`) es la porción del partido digerida para juzgar, de menos de **10.000** tokens reales: si no cabe, se recorta en un orden fijo (detalles del cara a cara, la forma y la clasificación; los resúmenes a 120 y a 60 caracteres; y, al final, las evidencias PROBABLE o RUMOR menos relevantes) y nunca se recortan los candidatos con sus números, las contradicciones, las posturas, la evidencia de quién puede jugar ni las ausencias y las alineaciones. Si aun así no cabe, no se llama (`view_too_large`) y decide el revisor de reglas.

**Opus.** Solo para las selecciones en que una regla **E1 a E7** de `router-v1` dispara, calculada por código desde el paquete, el veredicto del Council y las contradicciones; ningún modelo la pide. Opus recibe esas selecciones con la regla como código y la primera lectura de Sonnet, y su veredicto **sustituye** al de Sonnet solo para ellas. El tope es de **3 llamadas por día de Bogotá** (`router-v1`, ámbito sombra), compartido por los dos brazos del multiagente; una escalada que no cabe deja el veredicto de la primera ronda y se anota como `escalation_skipped`. COUNCIL SOLO no se escala nunca. En esta fase solo pueden dispararse E2, E3, E4, E6 y E7 (sección 13, D4).

## 7. Las contradicciones C01 a C08

`contra-v1` (`ai/contra.py`) es **código**: decide si existe una contradicción, sin modelo, sin base de datos y sin reloj, y lo que el paquete no tiene no se rellena con un valor por defecto sino que deja la regla en `input_missing`. No copia nunca un texto que vino de fuera. Los umbrales son valores de partida que se calibran en la sombra; dos de ellos son los del router, para que haya un solo número.

| Código | Se dispara cuando | Toca |
| --- | --- | --- |
| C01 | falta un jugador clave de un lado (no su portero titular) | Over, ambos marcan y la victoria de ese lado |
| C02 | falta el portero titular de un lado | Under y que no marquen ambos |
| C03 | juega otra competición a 3 días o menos y, con el once oficial, hay al menos 4 titulares habituales fuera de él | la victoria de ese lado |
| C04 | el lado no se juega nada (`pressure` es `settled`) | la victoria de ese lado |
| C05 | el multiplicador del árbitro es menor que 0,85 | Over de tarjetas |
| C06 | la distancia entre el modelo y el mercado supera 0,20 | esa selección |
| C07 | dos o más evidencias CONTRADICTORY sobre el mismo sujeto | todas las selecciones |
| C08 | una evaluación apoya y otra, distinta, objeta o rechaza selecciones alineadas | las dos selecciones |

**C05 todavía no puede dispararse**: ningún constructor escribe el multiplicador del árbitro en el paquete (vive dentro de los pronósticos de las familias), así que la regla dice `input_missing` hasta que el paquete lo lleve. Tampoco C03 se evalúa con la porción de estadísticas, que no trae las cifras de los titulares.

## 8. Las guardas de ejecución

Todas están en `ai/runtime.py`, sin base de datos, sin red y sin reloj propio, de modo que cada umbral se prueba por los dos lados. El Orchestrator tiene **un** juego de cerrojos y **un** circuito por proceso (uno por vuelta olvidaría que un modelo estaba caído).

| Guarda | Qué hace |
| --- | --- |
| Concurrencia | a la vez como mucho 4 llamadas de Haiku, 3 de Sonnet y 1 de Opus; una llamada espera hasta 20 s un hueco y, si no lo hay, la tarea se salta (`no_slot`) |
| Circuito (uno por modelo) | se abre con 5 fallos seguidos, o con más del 20 % de fallos en 10 minutos si hay al menos 10 llamadas; abierto, rechaza toda llamada 5 minutos y después deja pasar **una** de prueba; decide el revisor de reglas |
| Reintentos | solo fallos de transporte (`timeout`, `unavailable`, `rate_limited`), como mucho 3 reintentos tras el primer intento, con esperas de 1, 2 y 4 segundos (tope de 8); nunca otro modelo ni otra petición. Una salida inválida, una negativa, un presupuesto agotado o un límite de gasto no se reintentan |
| Plazo de T-15 | una pasada no empieza si no puede terminar estrictamente antes de las 15 minutos previos al inicio (se espera que dure 3 minutos); cada llamada acota su espera al tiempo que queda menos 5 segundos, y no se hace con menos de 10 segundos |
| Pausa de un brazo | un brazo no corre en la pasada si el circuito de su modelo está abierto, si pasa del 3 % de salidas inválidas en el día con al menos 34 pasadas (con menos, una sola mala no pausa el día) o si no le queda sobre |

Qué cuenta como fallo del proveedor y qué como respuesta del modelo lo dice una tabla del propio módulo: una salida inválida o una negativa son respuesta, no caída, y no abren el circuito; una llamada que no se hizo (presupuesto, configuración) no le dice nada al circuito. Una pasada pausada **no** cambia de modelo ni de petición: el brazo se salta y ese día sale entero del análisis de ese brazo.

## 9. El presupuesto

La sombra gasta en el workspace del LAB, con la clave del LAB y dentro de su sobre. **El LAB crece solo mientras dura esta etapa**: en las fases 3 a 8 el tope de la Console de PREDIGOL-LAB es de **60** US$ y el sobre interno del servidor (`FBI_AI_LAB_MONTHLY_BUDGET_USD`) de **55** (acción 15); en la fase 9 vuelven a 20 y 15 (acción 16). El plan estima el LAB en ≈ 1,7 US$ al día (≈ 51 al mes) con el calendario de producción; **no hay medición propia de esta fase todavía**.

* **Antes de cada partido**, la estimación de todo lo que va a preguntar (precio completo, con un 10 % de margen porque la vista del Council aún no tiene las posturas) se compara con lo que queda del día del LAB (`budget_v3.lab_day`). El LAB corre un día entero o no corre: sus motivos de parar son `no_envelope`, `api_limit`, `yields_to_production`, `allocation_spent`, y `insufficient` si el partido no cabe en lo que queda. La vuelta **se detiene y no escribe nada de ese partido**.
* **En el Batch** la comprobación es sobre la estimación de **toda la pasada** a mitad de precio (`batch.estimate_cost`), antes de encolar nada, y cuenta las reservas de los ítems abiertos (`budget_v3.lab_day`); cada ítem vuelve a pasar el control de la cola (`BatchQueue.add`). Un ítem de la sombra queda en el libro con el propósito `other` (el único que la cola del LAB liquida con `lab.settle_lab`), no con `pick_review` ni `match_analysis`.
* **Si producción cede los días**: el LAB cede primero, por días enteros, para que producción y LAB sumen como mucho el techo conjunto; el modelo nunca se cambia por dinero.
* **Un límite de gasto de Anthropic** (un 400 «workspace API usage limits» o un 429 `enforced_spend_limit_reached`) se trata como **agotado**: la llamada se convierte en `over_budget`, la vuelta termina con `budget_stop` en `exhausted`, no se vuelve a preguntar y el libro guarda un enfriamiento (30 minutos, que se duplica hasta 6 horas).
* **Los topes del router** (por porcentaje de la asignación y de 3 llamadas de Opus al día) se aplican; el de las 3 llamadas es el que muerde (sección 13, D5).
* La pregunta se hace también contra el estado del presupuesto de **producción**: si producción no deja el nivel (Haiku, Sonnet u Opus), la tarea se salta con `tier_<nivel>_not_allowed`.

## 10. Las reglas de fuga `agent_known` y `shadow_review_known`

La auditoría nocturna (a las 07:50 de Bogotá) gana dos reglas de código, que se suman a `slice_known`. `review_known` solo mira la revisión que una decisión enlaza y la sombra no llega a ninguna decisión, así que no basta.

| Regla | Qué prueba, una comprobación por fila |
| --- | --- |
| `agent_known` | cada ejecución de un agente que empezó ese día (menos las de la batería) sabía solo lo de su momento: su `known_at` no es posterior a su inicio ni al inicio del partido; el paquete que nombra es del mismo partido en ese momento y de un paquete guardado antes; cada evidencia que cita existe y se recogió (y se publicó, si tiene fecha) antes; y la ejecución que leyó (el Council lee las evaluaciones) es del mismo partido y había terminado |
| `shadow_review_known` | cada revisión de `ma-v1`, `ma-v1-h` y `cs-v1` escrita ese día nombra un paquete del mismo partido cuyo momento y guardado no son posteriores, se escribió antes del inicio y cita solo evidencia que existe y se conocía en el momento de ese paquete |

`shadow_review_known` es **la única regla cuyo silencio significa algo**: el gate B pide verla con filas cada noche mientras la sombra está encendida («con n > 0»). La regla no llama violación a cero filas (una noche con la sombra apagada no tiene ninguna), pero guarda el cero en `intel.audit_checks.n_checked` y el gate B lo lee ahí: `passes_gate` solo da por limpia una noche de esa regla si hubo más de 0 filas y ninguna violación.

## 11. Lo que muestra la Consola

* **Operación → Trabajo de la IA → Revisiones**: el filtro de motor ofrece `combined` (de serie), `rules`, `llm`, `ma-v1`, `ma-v1-h` y `cs-v1`; al elegir uno de la sombra sale una nota («motor en sombra: sus revisiones se guardan para evaluarlo y nunca llegan a la capa de decisión ni a los usuarios»), y la revisión se abre con su motor y la marca Shadow. Los nombres son «Multiagente (sombra)», «Multiagente + Council Haiku (sombra)» y «Council solo (sombra)».
* **Aprendizaje → La IA frente al modelo**: el informe de sombra se escribe también por motor de la sombra, pero solo cuando ya se ha liquidado algún partido que revisó (no deja filas vacías).
* **Operación → Agentes**: el registro con `match` y `council` como retadores, la cola de tareas y ejecuciones, los ciclos y las reglas de la auditoría (`slice_known`, `agent_known`, `review_known` y `shadow_review_known`), y el expediente de un partido con sus tareas y ejecuciones.
* La última vuelta de cada tipo de ciclo, con el informe de la sombra en sus cuentas, sale con las demás en el estado de la capa de IA.

**Lo que la Consola todavía no tiene** (sección 14): las vistas Contradicciones, Agentes con coste y latencia por partido, el expediente con Match y Council y Sombra con brazos y muestras.

## 12. Lo que pide el gate B y tu acción 15

El gate B (la sombra funcional tras 14 días de las fases 3 a 5) no tiene hoy un comando que lo evalúe; cada exigencia se lee donde dice la tabla, y ninguna se declara sin evidencia real.

| Exigencia del plan | Dónde se lee | Estado |
| --- | --- | --- |
| 0 violaciones en `slice_known`, `agent_known`, `review_known` y `shadow_review_known` (esta, con n > 0) | `intel.audit_checks`, cada noche | construido |
| batería adversaria en verde | `ia_battery` | la batería (`battery-v2`) tiene tres objetivos y **ninguno es el Match Agent ni el Council** (sección 13, D6) |
| Research v2 con ≥ 95 % de las evidencias de v1 | `ia_research_gate` | construido (fase 2) |
| 0 pasadas `final` fuera de plazo por el Orchestrator | `too_late` y `ai.agent_runs` | el Orchestrator no empieza una pasada que no puede terminar antes de T-15; la métrica se lee de sus cuentas |
| ≤ 3 % de salidas inválidas por agente | `ai.agent_runs` (estado `invalid`) | se lee de la tabla |
| 0 pagos duplicados (misma `idem_key`) | índice único `ai_agent_runs_paid_once` | lo impone la base de datos |
| LAB dentro de su sobre, con los días excluidos ≤ los previstos al arrancar | `budget_v3.lab_day`, `paused` y `budget_stop` del informe | se lee de las cuentas |
| atribución en ≥ 95 % de los partidos liquidados con ejecuciones | (post-mortem de la fase 5) | **no construido**: no se puede medir todavía |

**Tu acción 15** (`IA_ACCIONES_MANUALES.md`): al empezar la fase 3, en la Console, PREDIGOL-LAB pasa a un tope mensual de `60` con avisos en 30, 42, 51 y 57; en el servidor, `FBI_AI_LAB_MONTHLY_BUDGET_USD=55` y reinicio del worker. Te la pediré cuando el gate A haya pasado; es lo que bloquea el arranque de la sombra. No hay más acciones tuyas nuevas en esta fase.

## 13. Desviaciones y límites declarados

Lo que el código hace distinto del plan, o menos que el plan, sin disimularlo:

| Id | Qué | Qué hacer |
| --- | --- | --- |
| D1 | **COUNCIL SOLO es un tercer motor de la sombra, `cs-v1`, que el ejecutor añadió.** El plan lo cuenta entre los siete brazos (sección 22) pero el texto de la fase 3 y su migración nombran solo `ma-v1` y `ma-v1-h`; el código lo implementa como motor, con su Council Sonnet sin especialistas, y la 0119 lo admite en la restricción de motores | **Aceptarlo o quitarlo es decisión tuya.** No corre mientras no lo pongas en `FBI_AI_ENGINES`; quitarlo del todo sería un cambio de código y una revisión de migración nueva |
| D2 | **El calendario de Batch está construido, con límites declarados.** Las pasadas `first` y `pre` lejanas van por la API de lotes a mitad de precio y `final` y las cercanas en tiempo real (sección 5). Límites: el sondeo guarda la respuesta **cruda** del ítem y las ejecuciones de `ai.agent_runs` (que no se pueden corregir) se escriben al final, cuando la etapa siguiente la valida; el libro de `ai.usage` anota esas llamadas con el propósito `other`; `cs-v1` pregunta en la etapa 1 porque no lee posturas; un lote puede tardar y una pasada que no se liquida a T-100 se pierde como `batch_too_late` (una muestra menos), y el coste real a mitad de precio **no está medido** | medir en la primera semana el coste por pasada y la tasa de `batch_too_late` (`ai.agent_runs` con `error` que empieza por `batch_`) antes de fiarse de la estimación del plan |
| D3 | **Las peticiones de investigación se ignoran en la sombra.** Ni la del Match Agent ni la del Council se atienden (el Council no hace segunda ronda); se cuentan las del Match Agent (`research_ask_ignored`) y los temas quedan en el estado de la pasada. El plan pedía atenderlas en ≤ 10 % de las llamadas del Council | queda para cuando la sombra pase a atender peticiones |
| D4 | **E1 y E5 no pueden dispararse.** La sombra no sabe qué es el pick del día ni las patas del parlay principal, y no hay investigación posterior; Opus solo se ve alcanzado por E2, E3, E4, E6 y E7. Tampoco C05 se dispara (sección 7) | seguimiento |
| D5 | **Los topes por porcentaje del router se miden contra la asignación mensual del LAB, no contra la del día.** El router los define como una parte de la asignación del día (Haiku 30 %, Council 65 %, Opus 30 % en la sombra); el Orchestrator le pasa la asignación del mes, así que esos tres topes casi nunca muerden. Lo que de verdad acota el día es el tope de 3 llamadas de Opus y lo que queda del día del LAB | corregirlo es un cambio de código, no de configuración; mientras tanto el gasto lo acota el sobre del LAB |
| D6 | **La batería adversaria no cubre los prompts nuevos.** El plan pide al menos 40 casos por cada prompt que lee texto ajeno; `battery-v2` tiene tres objetivos (`review`, `extract`, `claims`). Los agentes de la fase sí tienen pruebas de órdenes metidas en la evidencia, pero no son la batería | seguimiento; el gate B pide la batería «en verde» y hoy eso no incluye estos prompts |
| D7 | **«`SKIP LOCKED` con dos trabajadores» no existe.** La vuelta es de un solo ejemplar (`max_instances=1`) y las tareas del Batch las lee un solo proceso: no hay una cola que dos trabajadores se repartan. Lo que sí hay: la asignación a dos trabajadores a la vez no se bloquea, y la segunda escritura de una misma pasada no guarda nada | no hace falta mientras haya un solo trabajador |
| D8 | **La atribución del gate B no se puede medir:** depende del post-mortem de la fase 5 | espera a la fase 5 |

## 14. Las pruebas y lo que falta

**Pruebas.** Una por pieza, todas sin modelo ni red (el proveedor de pruebas `FakeProvider`):

| Pieza | Prueba |
| --- | --- |
| Interruptores | `tests/unit/test_ai_shadow_switches.py` |
| Migración | `tests/unit/test_migration_0119.py` y `tests/integration/test_migration_0119.py` |
| Asignación | `tests/unit/test_arms.py` y `tests/integration/test_arms_assignment.py` |
| Guardas | `tests/unit/test_ai_runtime.py` |
| Contradicciones | `tests/unit/test_ai_contra.py` |
| Match Agent y Council | `tests/unit/test_ai_agents_match.py`, `tests/unit/test_ai_agents_council.py` y `tests/unit/test_ai_agents_common.py` |
| Orchestrator | `tests/unit/test_orchestrator.py` y `tests/integration/test_orchestrator.py` |
| Calendario de Batch | `tests/unit/test_orchestrator_batch.py` y `tests/integration/test_orchestrator_batch.py` |
| Trabajo del worker | `tests/unit/test_worker_ai_orchestrate.py` |
| Nada de la sombra mueve producción | `tests/unit/test_engine_filter_guard.py` y `tests/integration/test_shadow_engines_readers.py` |
| Reglas de fuga | `tests/unit/test_leakage_agent_rules.py` y `tests/integration/test_agent_shadow_leak_audit.py` |
| Este documento | `tests/unit/test_ia_fase3_docs.py` |

**Lo que falta.** La fase está **terminada en el código y sin desplegar**. Queda, por el orden del plan:

| Falta | Quién | Qué lo cierra |
| --- | --- | --- |
| Que pase el gate A | el tiempo | `ia_gate evaluate --record` con `PASA` |
| Desplegar la fase apagada | yo, con tu palabra | la cadena de lanzamiento con copia, restauración y verificación en verde |
| La acción 15 | tú | el panel en 60 y Operación → Costes en 55 |
| Encender la sombra | yo, con tu palabra | la secuencia de la sección 2 y la primera vuelta de tipo `orchestrate` |
| 14 días de sombra estable | el tiempo | las exigencias de la sección 12 |
| Las vistas de la Consola: Contradicciones, Agentes (ejecuciones, coste, latencia), el expediente con Match y Council y Sombra con brazos y muestras | yo | páginas nuevas sobre las tablas de arriba |
| Los casos de la batería para los prompts del Match Agent y del Council | yo | un objetivo nuevo en `ia_battery` |
| La estadística de la sombra (informe de sombra por brazos con intervalos) | yo | la fase 4 y siguientes |
