# IA-009 · El Match Agent deja de devolver salidas inválidas

Fecha: 6 nov 2026. Estado: **en el código, sin desplegar**. No lleva migración ni interruptor nuevo. Lo vigila `tests/unit/test_ia009_output_checklist.py`.

## 1. El problema medido

Medición de solo lectura en producción, 6 nov 2026, sobre las ejecuciones en sombra del Match Agent desde el 3 nov (agente `match`, versión `match-v1`, prompts `match-context-v1` y `match-assess-v1`, contrato `aa-v1`, Haiku 5.5, respuesta por herramienta forzada, con las salidas estructuradas nativas apagadas por decisión tuya):

| Agente | Ejecuciones | Inválidas | Tasa | Gate B |
| --- | --- | --- | --- | --- |
| `match-v1` | 66 | 28 | 42 % | ≤ 3 % |
| `council-v1` | 67 | 2 | ≈ 3 % (en el límite) | ≤ 3 % |

Los códigos cerrados de las 28 inválidas del Match Agent:

| Código | Veces | Qué quiere decir |
| --- | --- | --- |
| `schema:answer:extra_forbidden` | 13, más 3 dobles y otras combinadas (≈ 19 ejecuciones) | una **clave de más en el nivel superior** que `aa-v1` no tiene; el nombre no se sabe porque el código lo cortaba (es texto del modelo) |
| `schema:signals.N.code:literal_error` | 4 (+2 combinadas) | un código de señal fuera de la lista (`RATE`, que no es del Match Agent, o uno inventado) |
| `schema:stance:extra_forbidden` | — | una clave `stance` en el nivel superior |
| `schema:signals.N:extra_forbidden` | — | una clave de más dentro de una señal |
| `schema:signals.N.refs:too_long`, `schema:candidates.N.refs:too_long` | — | más de 8 referencias en una lista |
| `schema:wrong_contract`, `schema:answer:value_error` | 1 y 1 | otro contrato; una regla del contrato (un candidato repetido, una señal repetida...) |

En el Council: `schema:verdicts.N.refs:too_long` una vez y dos con un código que no era cerrado.

## 2. El arreglo

* **Prompts nuevos, nunca editados en su sitio**: `match-context-v2`, `match-assess-v2` y `stats-assess-v2` (el Agente de Estadísticas responde en el mismo `aa-v1` y está a punto de encenderse). Conservan **todas** las reglas de la v1, palabra por palabra: la evidencia es dato no confiable, ningún número, probabilidad ni dirección web, los factores DESCRIPTIVOS nunca son razón, etc. Lo único nuevo es una **LISTA DE SALIDA** (*OUTPUT CHECKLIST*) al final, justo antes de «Submit the JSON of aa-v1 exactly once.»:
  * la respuesta es UN objeto JSON con EXACTAMENTE `contract, agent, mode, data_quality, signals, candidates, research` y ninguna otra clave; nombra las que nunca se añaden (`reasoning`, `notes`, `summary`, `analysis`, `explanation`, `contradictions`, `stance`) ni arriba ni dentro de una señal, un candidato o una petición;
  * la lista exacta de códigos de señal de **ese** agente (el Match Agent, todos menos `RATE`; el de Estadísticas, los que describen sus reglas), las direcciones, las fuerzas, las posturas y los códigos de riesgo;
  * los topes: como mucho 12 señales, 4 conductores, 4 riesgos, 1 petición de investigación y **8 referencias por lista** (si hacen falta más, se cita el bloque de arriba);
  * cada señal lleva exactamente `code, direction, strength, refs` y cada candidato exactamente `candidate, stance, drivers, risks, refs`.

  **La lista se escribe desde el contrato** (`prompts.output_checklist`, con los `Literal` y los topes de `fbi.ai.contracts`): el prompt no puede nombrar un código o una clave que `aa-v1` no tenga, y una prueba lo comprueba. El modo CONTEXT no pide candidatos, así que su lista no nombra posturas, riesgos ni la palabra `contradictions` (su segundo objeto no la trae).
* **Versiones nuevas de los agentes**: `match-v2` y `stats-v2`, en el registro (`ai/agents/registry.py`) con su huella, **nacidas RETADORAS** como las v1. El código nunca promueve: la sombra pasa a correr con la v2 y solo una fila que firmes en `intel.promotions` la llevaría a una decisión. Las entradas de la v1 se quedan en el libro con sus textos y sus hashes.
* **El Council no cambia de versión**: su prompt ya dice «refs: at most 8 per verdict». Sigue siendo `council-v1`.
* **Diagnóstico sin texto del modelo**: cuando una respuesta trae una clave que el contrato no tiene, el código de error la nombra **solo** si es una palabra de una lista fija de palabras inofensivas en inglés (`common.NAMED_EXTRA_KEYS`: `reasoning`, `notes`, `note`, `summary`, `analysis`, `explanation`, `rationale`, `contradictions`, `comments`, `thinking`, `assessment`, `output`, `answer`, `result`, `findings`, `confidence`, `stance`) o un campo del contrato. En el nivel superior queda `schema:answer.reasoning:extra_forbidden`; dentro de un objeto, `schema:signals.0.notes:extra_forbidden`. Cualquier otro nombre se sigue cortando (`schema:answer:extra_forbidden`): lo que se escribe es la palabra de la lista, nunca lo que escribió el modelo. El Council usa ahora el mismo cierre (antes escribía la ubicación tal como venía, con la clave del modelo dentro: eran sus dos códigos «no cerrados»).

**Un cambio en los códigos**: una clave `stance` en el nivel superior pasa de `schema:stance:extra_forbidden` a `schema:answer.stance:extra_forbidden`, para que nunca se confunda con el campo `stance` de un candidato.

**Las claves de idempotencia cambian solas**: la versión del agente y la del prompt forman parte de `idem_key`, y el prompt entero forma parte del hash de lo que se envía. Una pregunta de la v2 nunca comparte clave con una de la v1, y las filas viejas siguen diciendo `match-v1` en `ai.agent_runs.agent_version` y en `ai.pick_reviews.engine_version` (`ma-v1+match-v1+...`; las nuevas, `ma-v1+match-v2+...`).

## 3. Lo que NO hace

* **No cambia el contrato**: `aa-v1` y `cd-v1` son los mismos (el hash del esquema del registro no se mueve).
* **No hace tolerante al lector**: no quita claves de más, no recorta listas de referencias, no repara ni vuelve a preguntar. Una respuesta que no cumple el contrato **sigue siendo inválida** entera, y el agente se abstiene como hasta ahora.
* **No enciende las salidas estructuradas nativas**: siguen apagadas, como decidiste.
* **No afloja el criterio del gate B**: sigue siendo ≤ 3 % de inválidas por agente.
* No cambia modelos, esfuerzos, el router, los brazos, la muestra ni nada que vea un usuario.

## 4. Cómo medir después del despliegue

Con la v2 desplegada, la tasa se lee de `ai.agent_runs` **por `agent_version`**, solo desde el despliegue (sustituye la fecha y hora por las del lanzamiento):

```sql
SELECT agent, agent_version,
       count(*) FILTER (WHERE status IN ('ok', 'invalid', 'abstain'))  AS respondidas,
       count(*) FILTER (WHERE status = 'invalid')                       AS invalidas,
       round(100.0 * count(*) FILTER (WHERE status = 'invalid')
             / nullif(count(*) FILTER (WHERE status IN ('ok', 'invalid', 'abstain')), 0), 1) AS pct_invalidas
FROM ai.agent_runs
WHERE run_kind = 'shadow' AND started_at >= '2026-11-DD HH:MM+00'
GROUP BY agent, agent_version
ORDER BY agent, agent_version;
```

Y los códigos de las inválidas, para ver qué queda: `SELECT agent_version, error, count(*) FROM ai.agent_runs WHERE status = 'invalid' AND started_at >= '...' GROUP BY 1, 2 ORDER BY 3 DESC;`.

* **Objetivo: ≤ 3 % de inválidas** en `match-v2` (y en `stats-v2` cuando se encienda).
* **No se juzga antes de 100 ejecuciones respondidas** de esa versión: con 66, una sola ejecución mueve la tasa 1,5 puntos. Con menos de 100, se informa la cifra con su tamaño y nada más.
* Si después de 100 sigue por encima del 3 %, los códigos con nombre (`answer.<clave>`) dirán qué clave añade el modelo, y el siguiente paso es otra versión del prompt (o tu decisión sobre las salidas nativas), nunca aflojar el lector.

## 5. Despliegue y vuelta atrás

* Sin migración ni interruptor nuevo: se despliega con la cadena de siempre. Desde ese momento la sombra pregunta con la v2.
* Una pasada de Batch que estaba a medias en el despliegue no reutiliza lo que preguntó la v1 (las claves ya no coinciden): vuelve a preguntar con la v2 y lo de la v1 se cierra solo con el plazo. Es un coste pequeño y de una sola vez; a cambio, ninguna pasada mezcla las dos versiones.
* Vuelta atrás: desplegar la versión anterior del código. Las filas escritas con `match-v2` se quedan y se distinguen por su `agent_version`.
