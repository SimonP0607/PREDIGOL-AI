# Fase 5 del Plan Maestro IA · Después del resultado: atribución, Revisor posterior y Analista de aprendizaje

Fecha: 3 nov 2026. Estado: **construida y probada, todavía sin desplegar; se despliega apagada (con la migración 0120) y se enciende con dos palabras de `app.env`, una para la atribución y el Revisor posterior y otra para el Analista de aprendizaje** (la fase lleva una sola migración, la 0120). Fuente: Plan Maestro IA (aprobado), fase 5 y secciones 12, 13, 24, 25 y 34.

Este documento dice lo que hace el código y **lo vigila una prueba** (`tests/unit/test_ia_fase5_docs.py`): si una cifra de aquí y una constante del código dejan de coincidir, la prueba falla hasta que se corrija una de las dos. La fase anterior está en `IA_FASE3.md` (la sombra que aquí se atribuye); lo que es tuyo (claves, topes de la Console), en `IA_ACCIONES_MANUALES.md`; el punto de partida medido, en `IA_BASELINE_F0.md`.

## 1. Qué es la Fase 5 y qué no toca

El objetivo del plan para esta fase es **cerrar el ciclo después del resultado**: saber, de cada selección liquidada que la sombra revisó, qué agente, en qué versión, acertó o falló; clasificar el error con las mismas palabras que el post-mortem; y proponer, una vez por semana, hipótesis sobre una versión de un agente apoyadas en esas atribuciones. Tres reglas, todas vigiladas por pruebas: **la aritmética la hace el código** (si una postura acertó, falló o no tomó partido, hacia el resultado y hacia la línea de cierre, nunca un modelo); **lo que mide el sistema es el código que escribió el agente, no su prosa**; y **nada de lo que escribe esta fase lo lee un pick, un filtro, una decisión, un usuario ni un gate de producción**.

| Pieza | Qué hace | Dónde está |
| --- | --- | --- |
| Atribución mecánica `attr-v1` | por cada selección liquidada que revisó un motor de la sombra, una fila por agente, versión y señal: acierto, fallo o anulado, hacia el cierre, calibración y clase del error. Sin modelo | `ai/agents/attribution.py`, migración `0120` |
| Revisor posterior `pmr-v1` | la clase de los fallos que el código dejó `UNKNOWN` (una segunda fila, nunca una corrección) y una narrativa corta para ti. Lotes, LAB | `ai/agents/pmr.py`, `ai/contracts/postmatch.py` |
| Analista de aprendizaje `la-v1` | una vez por semana, como mucho cinco hipótesis, cada una de una versión de un agente y citando las atribuciones en que se apoya. Solo propone. Lotes, LAB | `ai/agents/analyst.py`, `ai/contracts/learning.py` |
| Camino al modelo | solo la API de lotes, solo el LAB, solo si el LAB tiene sobre | `ai/agents/lab_batch.py` |
| Rol de la base | `predigol_learning`: puede insertar hipótesis y nada más | `deploy/vps/db/roles.sql`, `deploy/vps/db/grants.sql` |
| Enganches | la atribución en el paso diario `ai_learn`; el Analista en el semanal `intel_weekly` | `ai/cycle.py`, `intel/cycle.py` |
| Script | recalcular días anteriores y leer la cobertura que pide el gate B | `scripts/ia_attribution.py` |
| Consola | la ruta `/admin/ai/attribution` y la pestaña Atribución de Aprendizaje | `api/services/ai_attribution.py`, `web/src/live/AttributionPanel.tsx` |

**No toca**: probabilidades, calibradores, modelos estadísticos, umbrales, filtros, picks ni nada que vea un usuario. La tabla nueva solo la leen el propio código de la fase (la regla, el Revisor, el Analista y la Consola); una prueba (`tests/unit/test_attribution_readers.py`) falla si aparece un lector nuevo. La atribución escribe únicamente en `intel.agent_attributions`: una prueba de integración toma la huella de todas las demás tablas antes y después y exige que no se mueva ninguna. Los dos agentes entran en el registro como retadores (`pmr` nace junto a `post_match_reviewer` y `la` junto a `learning_analyst`) y solo los releva una fila que tú firmes.

## 2. Los dos interruptores y la vuelta atrás

Los dos están **apagados de serie**. Cada palabra se valida como las demás del servicio: se recorta, no importan las mayúsculas, `1`, `on`, `true` y `yes` encienden, y cualquier otra cosa (un error de tecleo incluido) apaga.

| Variable | De serie | Qué enciende | Dónde corre | Vuelta atrás |
| --- | --- | --- | --- | --- |
| `FBI_AI_PM_REVIEWER` | apagada | la atribución mecánica y el Revisor posterior | el paso diario `ai_learn` (07:35 de Bogotá): atribuye ayer y hoy; después manda los casos al lote del LAB | `0` |
| `FBI_AI_LEARNING_ANALYST` | apagada | el Analista de aprendizaje | el paso semanal `intel_weekly` (lunes), antes de la matriz | `0` |

El Revisor y el Analista son independientes: se puede encender la atribución sola y mirarla en la Consola antes de gastar nada en un modelo (sin clave ni sobre del LAB, el Revisor no pregunta y la atribución queda igual). Las dos palabras entran en el libro de palabras del propietario (`ai.feature_gates`, gate `switches`) solo cuando están encendidas: apagadas son el valor de serie, y un valor de serie no es un día en que cambió la configuración.

**La secuencia para encender**, y solo en este orden:

1. Desplegar la fase apagada (sección 3) y comprobar que la migración 0120 está aplicada.
2. Si quieres que el Analista escriba como el rol que no puede promover nada (sección 6), que el operador haya ejecutado `deploy/vps/db/roles.sql` y `grants.sql`.
3. Con una copia fechada de `app.env`, poner `FBI_AI_PM_REVIEWER=1` y reiniciar el worker. La primera mañana atribuye ayer y hoy. Para los días anteriores, `ia_attribution recompute` (sección 8).
4. Para el Revisor, que el LAB tenga clave y sobre (`FBI_AI_KEY_ANTHROPIC_LAB`, `FBI_AI_LAB_MONTHLY_BUDGET_USD`) y que los modelos de los niveles sean los del router: si el modelo configurado de un nivel no es el del router, esa tarea no se pregunta.
5. Cuando haya atribuciones de varios días y al menos 30 posturas en una semana, `FBI_AI_LEARNING_ANALYST=1` y reiniciar el worker. El primer lunes manda la semana al lote; las hipótesis se escriben cuando el sondeo trae la respuesta.

| Qué quieres deshacer | Cómo | Qué se conserva |
| --- | --- | --- |
| Que se atribuya y se revise | `FBI_AI_PM_REVIEWER=0` y reiniciar el worker | todo lo escrito: las atribuciones, las narrativas y las filas de refinamiento |
| Que el Analista proponga | `FBI_AI_LEARNING_ANALYST=0` y reiniciar el worker | las hipótesis ya escritas, con su agente y versión: tú las rechazas o las dejas |
| Toda la fase | las dos palabras a `0`; después, si hiciera falta, la versión anterior del código sobre la 0120 (sección 3) | tablas, columnas y filas: nada se borra |

## 3. La migración 0120 y cómo se despliega

La 0120 es **aditiva** y hace tres cosas:

| Qué | Cómo |
| --- | --- |
| `intel.agent_attributions` | tabla nueva, solo-anexar (`agent_attributions_append_only`, con la misma función de guarda `intel.refuse_change()` que sus hermanas): una fila por selección, motor, agente, versión de agente, señal, versión de la regla y quién clasificó (`code` o `pmr-v1`). Sin claves foráneas |
| `analytics.research_hypotheses` | las columnas `agent` y `agent_version`, nulas, las dos o ninguna (`research_hypotheses_agent_pair`) |
| `analytics.experiments` | las mismas dos columnas con la misma regla (`experiments_agent_pair`) |

La tabla es idempotente por una clave única (`agent_attributions_once`): lo calculado en vivo y lo recalculado por lote escriben las mismas filas y la segunda en llegar no escribe nada. Un refinamiento del Revisor es **una fila más** (`classified_by = 'pmr-v1'`, `basis_id` apunta a la del código) y solo puede haber uno por fila (`agent_attributions_one_refinement`); la fila del código no se toca jamás. Las restricciones repiten la regla del código: un fallo siempre tiene clase y lo demás no, y un refinamiento solo refina un fallo.

Espera como máximo 10 segundos un bloqueo (`SET LOCAL lock_timeout`) y toca primero las dos tablas ocupadas, así que si no consigue el bloqueo se para antes de haber hecho nada. Las dos tablas existentes son pequeñas (cientos de filas) y ninguna la lee la capa de decisión. No escribe ninguna fila, no nombra ningún rol y no borra nada.

**Cómo se despliega.** Por la cadena de lanzamientos de siempre (`backend/deploy/release/`): hashes, precomprobación de solo lectura, copia de seguridad con prueba de restauración, despliegue con `predigolctl` (que aplica la migración), prueba de humo, verificación y seguimientos; se detiene en el primer fallo. Las cifras de ese lanzamiento se anotan cuando ocurra; hoy no hay ninguna que declarar.

**Por qué se puede desplegar apagada, y cómo se baja.** El código de antes no conoce la tabla ni las columnas. Bajar con `alembic downgrade` (una herramienta de desarrollo) borra la tabla y las columnas; las atribuciones se pueden volver a calcular de las revisiones de la sombra, que se quedan. La vuelta atrás normal son las palabras de la sección 2, no desplegar la versión anterior.

## 4. La regla de atribución `attr-v1`

La regla es una función pura de las filas que lee (`rows_for`) y la escribe igual el paso diario (`source = 'live'`) y el recálculo de un día anterior (`source = 'batch'`). Lee la postura que el Orchestrator guardó **antes del saque inicial**: el veredicto del Council, la postura del Match Agent y la del Statistics Agent y, cuando su ejecución está guardada, las señales que las movieron.

| Postura | Palabras | Resultado |
| --- | --- | --- |
| a favor | `APPROVE`, `SUPPORT` | `HIT` si la selección ganó (`win`, `half_win`), `MISS` si perdió (`loss`, `half_loss`) |
| en contra | `DOWNGRADE`, `REJECT`, `CONCERN`, `REJECT_SIGNAL` | lo contrario: `HIT` si perdió, `MISS` si ganó |
| sin partido | `ABSTAIN`, `NEUTRAL` | `VOID`, igual que una selección anulada o devuelta (`push`, `void`) |

* **Hacia el cierre.** El signo del CLV del post-mortem `pm-v6` dice si la postura apuntó hacia donde se movió la línea de cierre («hacia el cierre» del plan).
* **Calibración.** Comparación de Brier entre la probabilidad del modelo y la del cierre justo (la del mercado si no hay cierre): `MODEL_BETTER`, `MARKET_BETTER` o `EQUAL`.
* **Clase del fallo**, con las palabras del post-mortem (`MODEL_ERROR`, `CONTEXT_ERROR`, `DATA_ERROR`, `MARKET_ERROR`, `EXECUTION_ERROR`, `NORMAL_VARIANCE`, `UNKNOWN`; `NONE` para un acierto y un anulado): la del propio post-mortem para una postura a favor que perdió; para una en contra que ganó, `NORMAL_VARIANCE` si el CLV fue negativo y `UNKNOWN` si no. Las `UNKNOWN` son las únicas que el Revisor puede clasificar.
* La versión de cada agente sale del pase que se registró (`ai.match_runs.agents`), no del código de hoy: una hipótesis sobre `council-v1` se apoya en filas de `council-v1`.

## 5. El Revisor posterior `pmr-v1`

Solo corre en el lote del LAB. Cada día, tras atribuir, toma los casos de los últimos 7 días que aún no tienen narrativa `pmr-v1` y que valen la pena (un fallo que el código dejó `UNKNOWN`, o una aprobación del Council que perdió), hasta 12 por vuelta, y los manda en un lote: **Haiku** escribe la narrativa de un caso y **Sonnet** la de una pérdida que vale la pena explicar (un APPROVE del Council que perdió), a lo sumo cuatro al día. El servidor le da cada caso con un nombre que puede citar y con el resultado y la clase **del servidor**; el modelo contesta con códigos y una narrativa de a lo sumo 900 caracteres.

Todo lo que el modelo puede cambiar se comprueba antes de escribir, y lo que no pasa se descarta y se cuenta, el resto se queda: una fila que no se le dio, un resultado distinto del del servidor, una clase para una fila que el código ya había clasificado, una referencia que no se le ofreció. Un modelo que no contesta, o contesta un disparate, deja la atribución como estaba. El texto ajeno que lee (notas del post-mortem de a lo sumo 240 caracteres) pasa por `fbi.ai.untrusted`: no es una instrucción jamás. La narrativa se guarda aparte (`ai.postmortem_narratives`, versión `pmr-v1`), se te muestra y **no se mide ni la lee nada**; la narrativa de siempre (`pick-postmortem-v4`) sigue donde estaba y la Consola la sigue leyendo igual.

## 6. El Analista de aprendizaje `la-v1` y el rol que no puede promover

Cada lunes, el Analista toma las atribuciones de los últimos 7 días del código, agrupadas por agente, versión, motor, señal, resultado y clase (conteos, y los ids de hasta 3 filas que ilustran cada grupo; como mucho 80 grupos) y las hipótesis que ya propuso. Si la semana tiene menos de 30 posturas no manda nada y lo anota (`too_few_stances`). Si no, lo manda al lote del LAB (Sonnet) y, cuando el sondeo trae la respuesta, el servidor comprueba cada hipótesis antes de escribirla:

* el agente y la versión tienen que estar entre los que la semana atribuye (una versión que nadie corrió no puede ser el sujeto de una hipótesis);
* **cada atribución que cita tiene que existir, habérsele ofrecido y ser de ese agente y de esa versión** (una hipótesis sobre `council-v1` no se apoya en filas de `match-v1`); una hipótesis que no cita nada no cumple el contrato y una con citas que no valen se descarta y se cuenta;
* su texto es del modelo: no confiable, normalizado y acortado al entrar, se te muestra y nunca es una instrucción;
* a lo sumo cinco hipótesis por semana, cada una con título de 5 a 160 caracteres y texto de a lo sumo 600.

Cada una entra como `PROPOSED` en `analytics.research_hypotheses` con su agente y versión. El experimento que describe (diseño, métrica, familia, qué varía, muestra) se guarda **como borrador dentro de la evidencia de la hipótesis**: las filas de `analytics.experiments` las escribe quien corre un experimento. **Solo propone**: no acepta, no corre, no promueve.

**El rol.** La escritura se hace con el rol de la base `predigol_learning` (sin acceso por sí mismo, se llega con `SET LOCAL ROLE`) cuando el clúster lo tiene: puede leer e insertar hipótesis y no puede escribir ni una fila en `intel.promotions`. Es la base de datos la que dice lo que el Analista puede escribir, no el prompt, y una prueba de integración lo comprueba intentándolo. El rol lo crea el operador (`db/roles.sql`; `grants.sql` le da sus permisos y se salta con un aviso si el rol no existe).

## 7. Lo que muestra la Consola

* **Aprendizaje → Atribución** (`/admin/ai/attribution`, de 1 a 60 días, 14 de serie): los dos interruptores con sus versiones; la **cobertura** (partidos con atribución sobre los partidos terminados que revisó un motor de la sombra, y lo mismo por selección) frente a la barra del 95 % del plan, **como cifra y nunca como veredicto** (cero partidos es un guion, no un 100 %); aciertos, fallos y anulados por agente, versión y motor; las clases de los fallos, con cuántos refinó el Revisor; los post-mortems con lo que hizo cada agente y la narrativa; y las hipótesis con su agente, su versión, las atribuciones que citan y el experimento borrador.
* **Aprendizaje → Experimentos** (Evolución): cada hipótesis que nombra un agente lo muestra con su versión.
* **Operación → Agentes**: el registro con `pmr` y `la` como retadores.

Todo es solo lectura: no llama a un modelo, no escribe nada y no decide ningún gate. Los textos están en español e inglés con las mismas claves.

## 8. El script `ia_attribution` y lo que pide el gate B

El gate B pide, entre otras cosas, **atribución en ≥ 95 %** de los partidos liquidados con ejecuciones. Desde esta fase se puede medir:

| Comando | Qué hace |
| --- | --- |
| `python -m scripts.ia_attribution coverage` | la parte de los partidos de los últimos 14 días con atribuciones (no escribe). Sale con 0 si llega al 95 %, 1 si no, 3 si todavía no hay ningún partido que juzgar y 2 si no puede correr (un día mal escrito) |
| `python -m scripts.ia_attribution scoreboard` | aciertos y fallos por agente, versión y motor |
| `python -m scripts.ia_attribution recompute --from AAAA-MM-DD --to AAAA-MM-DD` | atribuye días anteriores de la sombra (`batch`); con `--dry-run`, lo mismo deshecho al final, para ver cuántas filas escribiría |

Se corre donde corre el worker. El recálculo aplica la misma regla que el paso diario y deja en paz lo que ya existe, así que puede correrse dos veces. No llama a un modelo y no lee ni cambia nada de producción.

**Qué hace falta de evidencia real**, y nada se declara hasta tenerla: **14 días de atribuciones** y **dos informes semanales** del Analista (dos lunes con su paso `learning_analyst` en las cuentas de la vuelta semanal). Como el paso diario solo atribuye con `FBI_AI_PM_REVIEWER` encendida, los 14 días salen de encenderla 14 días o de `recompute` sobre los días que la sombra ya escribió.

## 9. Las métricas

| Métrica | Dónde se lee |
| --- | --- |
| % de post-mortems con atribución | Atribución → Cobertura, o `ia_attribution coverage` |
| Aciertos y fallos por agente y versión | Atribución → tabla de aciertos, o `ia_attribution scoreboard` |
| Fallos por clase, y cuántos refinó el Revisor | Atribución → clases |
| Hipótesis propuestas y aceptadas por agente y versión | Atribución → hipótesis (aceptadas son las que pasaron de `PROPOSED`: `ACCEPTED`, `RUNNING`, `SHADOW`, `DONE` y `PROMOTED`) |
| Coste del Revisor y del Analista | el libro de gasto del LAB (`ai.usage`, propósitos `postmortem` y `learning`) |

## 10. Desviaciones y límites declarados

Lo que el código hace distinto del plan, o menos que el plan, sin disimularlo:

| Id | Qué | Qué hacer |
| --- | --- | --- |
| D1 | **La atribución va detrás de `FBI_AI_PM_REVIEWER`.** El plan la pide mecánica y sin modelo, y lo es, pero el paso diario solo la calcula si esa palabra está encendida; sin ella no hay filas y los 14 días del gate B no se acumulan | encenderla pronto (cuesta solo base de datos si el LAB no tiene clave) o recalcular con `ia_attribution recompute` |
| D2 | **Los agentes de esta fase tienen ids propios, `pmr` y `la`**, y relevan a `post_match_reviewer` y `learning_analyst` (los de hoy) solo por una fila tuya; no los sustituyen | firmar o no la promoción es decisión tuya |
| D3 | **El rol `predigol_learning` existe solo cuando el operador ejecuta `roles.sql`.** Sin él, el Analista escribe con el rol del worker, que tampoco puede firmar una promoción de un agente (lo impide la política de filas de la 0111) pero no es el rol mínimo | ejecutar `roles.sql` y `grants.sql` antes de encender el Analista |
| D4 | **El experimento que propone el Analista es un borrador dentro de la evidencia de la hipótesis**, no una fila de `analytics.experiments`: esa tabla no tiene un estado de borrador y la escribe quien corre el experimento | cuando se acepte la hipótesis, se crea el experimento a partir del borrador |
| D5 | **El coste no está medido.** El lote vale la mitad, pero el coste real del Revisor y del Analista no se ha visto con datos | medir la primera semana en el libro del LAB |
| D6 | **La batería adversaria no cubre los dos prompts nuevos.** El plan pide al menos 40 casos por cada prompt que lee texto ajeno; `battery-v2` no tiene un objetivo para ellos. Sí hay pruebas de órdenes metidas en el texto que lee cada agente (no cambian ninguna fila ni ningún resultado), pero no son la batería | seguimiento, como D6 de `IA_FASE3.md` |
| D7 | **Solo lo que se atribuye pasa por la regla**: los motores de producción (`rules`, `llm`, `combined`) no tienen agentes que atribuir, y los de la sombra solo aparecen mientras la sombra corre | nada que hacer |

## 11. Las pruebas y lo que falta

**Pruebas.** Todas sin modelo ni red (el proveedor de pruebas `FakeProvider` y el lote `FakeBatches`):

| Pieza | Prueba |
| --- | --- |
| Migración | `tests/unit/test_migration_0120.py` y `tests/integration/test_migration_0120.py` |
| Regla de atribución | `tests/unit/test_agent_attribution.py` y `tests/integration/test_agent_attribution.py` |
| Revisor posterior | `tests/unit/test_pmr_pure.py` y `tests/integration/test_pmr.py` |
| Analista de aprendizaje | `tests/unit/test_analyst_pure.py` y `tests/integration/test_learning_analyst.py` |
| El rol no promueve | `tests/integration/test_learning_role.py` |
| Nadie más lee la tabla | `tests/unit/test_attribution_readers.py` |
| Despliegue, interruptores y variables | `tests/unit/test_phase5_deploy.py` y `tests/unit/test_switch_words.py` |
| Script | `tests/integration/test_ia_attribution_script.py` |
| Consola | `tests/integration/test_ai_attribution_api.py` y `web/src/live/AttributionPanel.test.tsx` |
| Este documento | `tests/unit/test_ia_fase5_docs.py` |

**Lo que falta.** La fase está **terminada en el código y sin desplegar**. Queda, por el orden del plan:

| Falta | Quién | Qué lo cierra |
| --- | --- | --- |
| Desplegar la fase apagada | yo, con tu palabra | la cadena de lanzamiento con copia, restauración y verificación en verde |
| Ejecutar `roles.sql` y `grants.sql` | el operador | el rol `predigol_learning` en el clúster |
| Encender `FBI_AI_PM_REVIEWER` | yo, con tu palabra | la secuencia de la sección 2 y las primeras filas en la pestaña Atribución |
| 14 días de atribuciones | el tiempo | `ia_attribution coverage` en 0 |
| Encender `FBI_AI_LEARNING_ANALYST` y dos informes semanales | yo, con tu palabra; el tiempo | dos lunes con hipótesis propuestas por versión |
| Los casos de la batería para los dos prompts | yo | un objetivo nuevo en `ia_battery` |
