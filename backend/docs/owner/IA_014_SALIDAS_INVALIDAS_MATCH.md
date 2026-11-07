# IA-014 · El Match Agent v3 contra las salidas inválidas que le quedaban a la v2

Fecha: 7 nov 2026. Estado: **en el código, sin desplegar**. No lleva migración ni interruptor nuevo. Lo vigila `tests/unit/test_ia014_match_invalid_outputs.py`. Viene de IA-009 (`IA_009_SALIDAS_INVALIDAS.md`), que bajó la tasa del 42 % al 8 %.

## 1. Lo medido

Medición de solo lectura en producción, del 6 nov 16:55 al 7 nov 15:00 UTC, sobre las ejecuciones en sombra respondidas del Match Agent `match-v2` (prompts `match-context-v2` y `match-assess-v2`, contrato `aa-v1`, Haiku 5.5, salidas estructuradas nativas apagadas):

| Agente | Respondidas | Inválidas | Tasa | Gate B |
| --- | --- | --- | --- | --- |
| `match-v2` | 250 | 20 | 8,0 % | ≤ 3 % |
| `council-v1` | — | — | 2,3 % | ≤ 3 % (bien) |

| Código | Ejecuciones | Diagnóstico desde el código |
| --- | --- | --- |
| `schema:answer:extra_forbidden` | 8 | una clave de más en el nivel superior que **no** está en la lista de palabras de IA-009, así que su nombre se cortó y no se sabe cuál es. Candidatas: claves del segundo objeto del mensaje copiadas a la respuesta (`now`, `minutes_to_kickoff`, `package_age_minutes`), un envoltorio o el esquema devuelto (`input`, `properties`, `type`), o prosa (`verdict`, `reason`...) |
| `reference_not_in_the_package` | 4 | una referencia que el paquete no tiene. El modelo solo veía ejemplos de rutas en el prompt (`P:shared.referee`, `P:shared.travel`...), que no existen en todos los paquetes, y nunca la lista real de los suyos |
| `schema:signals.N.code:literal_error` | 3 | un código de señal fuera de la lista (un riesgo usado como señal, o una palabra propia como «lesiones» o «clasificación») |
| `schema:answer:value_error` | 2 | una regla de forma del contrato; con la lista de salida de la v2 lo más probable es una señal (código, dirección) repetida, que la lista no decía |
| `schema:signals.1.refs:too_long` | 1 | nueve referencias en una lista |
| `schema:answer.stance:extra_forbidden` | 1 | `stance` en el nivel superior |

## 2. Qué cambia

* **El mensaje trae la lista de referencias del paquete** (`citable`, en el segundo objeto): los `E:<id>` de todas sus evidencias y los `P:<ruta>` de sus bloques hasta tres claves de profundidad (`P:shared.absences.home`). La escribe el **código** desde el paquete (`common.citable_refs`), nunca el modelo, y cada referencia de la lista es una que el lector acepta (lo comprueba una prueba). Coste: en el paquete sintético de las pruebas son 69 referencias, unos 800 tokens de entrada por llamada según el estimador del paquete (≈ 10 % del corte `match`), en la parte del mensaje que no se cachea.
* **Prompts nuevos**: `match-context-v3` y `match-assess-v3`. Las reglas y la tarea son las de la v2 palabra por palabra; la lista de salida (`output_checklist(citable=True)`) añade:
  * toda referencia se copia **exactamente** de `citable`; nada más es referencia (ni un elemento de lista como `P:evidence.0`, ni una clave del segundo objeto, ni `A:`); si el bloque no está, se cita el de arriba o se deja la señal;
  * una sola señal por pareja (código, dirección), y qué código toma un tema sin código propio (lesiones → `ABSENCES`, clasificación y elo → `FORM`...); en la evaluación, que un riesgo nunca es una señal ni un conductor;
  * nunca se copian a la respuesta las claves del segundo objeto (se nombran);
  * «cuéntalas: 9 son demasiadas» para las referencias.
* **Versión nueva del agente**: `match-v3`, en el registro con su huella, **nacida RETADORA** (fase `IA-014`). El código no promueve. `engine_version` pasa a `ma-v1+match-v3+...`.
* **El Agente de Estadísticas no cambia**: su lista de salida es la de IA-009 byte a byte (la prueba lo comprueba), así que sigue en `stats-assess-v2` / `stats-v2`. El Council sigue en `council-v1`.
* **Diagnóstico más fino, siempre con palabras del servidor**:
  * la lista fija de claves con nombre crece (`common.NAMED_EXTRA_KEYS_IA014`, unas 70 palabras: las claves del segundo objeto, envoltorios, prosa habitual, campos en singular). Lo que se escribe sigue siendo la palabra de la lista; cualquier otro nombre se corta como antes;
  * una respuesta rechazada lleva además códigos `why:` que dicen lo que la ubicación sola no dice, sin copiar nada del modelo: el tipo JSON de una clave sin nombre (`why:answer:extra_text`, `extra_object`...), qué regla de forma rompió (`why:answer:signal_twice`, `candidate_twice`, `context_with_candidates`), qué es un código fuera de su lista (`why:signals.0.code:risk_code`, `case`, `stance`, `other`...) y de qué clase es una referencia inexistente (`why:refs:evidence_not_in_package`, `into_a_list`, `below_a_block`, `second_object`, `assessment_ref`, `root_unknown`). Nunca cambian lo que vale: la respuesta la rechazan el contrato o `check`, no ellos.

## 3. Lo que NO hace

* No cambia el contrato `aa-v1` (el hash del esquema del registro es el mismo), no hace tolerante al lector (no quita claves ni recorta listas) y no enciende las salidas estructuradas nativas.
* **No construye el turno de reparación** (volver a preguntar una vez al mismo modelo con solo los códigos cerrados). No cabe sin tocar `orchestrator.py`: el agente no hace llamadas (las hace `_Runner.ask`), y una pregunta distinta es otra tarea con su propia identidad e `idem_key`, su comprobación de presupuesto y, en el calendario Batch, una etapa más. Es el **siguiente paso** si la v3 no baja del 3 %: una tarea `match/<modo>` con intento 2 registrada aparte, para que el banco siga informando la validez al primer intento (`valid_first_attempt` de `eval-bench-v1`).
* No cambia modelos, esfuerzos, router, brazos ni nada que vea un usuario.

## 4. Cómo medir

Con la v3 desplegada, por `agent_version` y solo desde la hora del despliegue (la consulta de `IA_009_SALIDAS_INVALIDAS.md`, sección 4, con `agent_version = 'match-v3'`), y los códigos de las inválidas con `SELECT error, count(*) ... GROUP BY 1`.

* **Objetivo: ≤ 3 % de inválidas en `match-v3`.**
* **No se juzga antes de 100 ejecuciones respondidas** de `match-v3` (con 100, cada inválida mueve la tasa un punto). Con menos, se informa la cifra con su tamaño y nada más.
* Si sigue por encima, los códigos `answer.<palabra>` y `why:` dicen qué queda; el siguiente paso es el turno de reparación (sección 3), otra versión del prompt o tu decisión sobre las salidas nativas, nunca aflojar el lector.

## 5. Despliegue y vuelta atrás

Sin migración ni interruptor: la cadena de siempre. Las claves de idempotencia cambian con la versión: una pasada de Batch a medias vuelve a preguntar con la v3 una vez. Vuelta atrás: desplegar el código anterior; las filas de `match-v3` se distinguen por `agent_version`.
