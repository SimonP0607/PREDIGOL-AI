# IA-064 · Validación estricta de las salidas de todos los agentes y textos

Pieza AD-A02 (P0, ola 1) del plan maestro de la arquitectura definitiva 2026. Código nuevo: `backend/src/fbi/ai/outputs.py` (el validador común, `output-guard-v1`, y su verificador de forma de textos, `text-guard-v1`). Se aplica en los dos sitios por donde vuelve **toda** respuesta de un modelo: `ai/usage.py` (`call_json`, tiempo real) y `ai/batch.py` (`_resolve`, la vía Batch). Un interruptor nuevo, `FBI_AI_OUTPUT_GUARD`, que nace en `default`. **Sin migración.**

## 1. Por qué

Cada agente y cada generador de texto ya leía su respuesta a su manera. Unos son estrictos (los contratos `aa-v1`, `cd-v1`, `claim-v2`…), otros indulgentes a propósito: el brief recorta un resumen de 512 caracteres a 500 y, al hacerlo, también **acepta** una respuesta con campos que el esquema no tiene. Faltaba un suelo común que ninguna función pudiera olvidar: que nada de un modelo se guarde sin esquema cerrado y que ningún texto libre se guarde sin cita o sin verificador.

## 2. Qué hace (cinco reglas)

1. **Esquema cerrado.** La respuesta se compara con el esquema que se envió en esa misma petición: objeto donde toca, todos los campos presentes, **ningún campo que el esquema no tenga**, el tipo JSON de cada valor (un `true` no es un número, `"3"` no es un entero), cada valor de una lista cerrada dentro de su lista. Las longitudes y los recuentos no se miran aquí: los sigue mirando (o recortando) el lector de cada superficie, como siempre.
2. **Ningún texto libre sin apoyo.** Cada texto libre de cada esquema está declarado con lo que lo apoya: una **cita** literal que el servidor vuelve a encontrar (`quote`), **referencias** que el servidor comprueba (`refs`), **hechos** de su propia lista comprobados frase a frase (`facts`), **cifras** comprobadas contra la entrada (`numbers`), un **identificador** o una **fecha** que el servidor resuelve (`id`, `date`) o, para la prosa que solo lee el dueño, el verificador de forma **`text-guard-v1`** (`shape`: sin enlaces, sin marcado HTML o de herramientas, sin órdenes a una máquina, sin caracteres invisibles). Ojo: `shape` dice que el texto es **seguro de guardar**, no que sea **verdad**.
3. **Fallo cerrado.** Una respuesta que no cumple 1 o 2 no llega a quien la pidió: `call_json` la devuelve como `invalid_output` (el mismo código que ya usaba el proveedor cuando el modelo no rellenaba su formulario; todas las funciones ya lo manejan) y la vía Batch le pasa a su manejador el mismo error.
4. **Registro de rechazos con motivo cerrado.** La fila de la llamada en `ai.usage` (de solo añadido) dice `status = 'invalid_output'` y `error = 'output_guard: <motivo>@<campo>; …'`. Los motivos son una lista cerrada (`extra_field`, `missing_field`, `wrong_type`, `not_in_enum`, `not_an_object`, `too_few_items`, `too_deep`, `text_link`, `text_markup`, `text_order`, `text_control`, `repeat_after_invalid`) y el campo va con los nombres **del esquema**: nunca un valor ni una clave inventada por el modelo (una respuesta puede ser de un atacante). Cada superficie sigue guardando en su tabla lo que ya guardaba.
5. **Un contenido inválido no se paga dos veces.** Antes de llamar, se mira en `ai.usage` si la misma entrada, del mismo prompt, al mismo modelo y en el mismo espacio, ya dio una respuesta inválida en los últimos 14 días: si es así, no se llama (no se paga ni se escribe fila). El brief conserva su comportamiento aceptado de **un** reintento con la nota de lo que falló (y su propia tabla ya no vuelve a pedir esa entrada); los experimentos (batería, banco de repetición, sondas) piden a propósito y no se miran.

## 3. El interruptor `FBI_AI_OUTPUT_GUARD`

| Palabra | Qué hace |
| --- | --- |
| `default` (por defecto; cualquier palabra desconocida también) | Cada superficie en su modo. **Rechaza** en las que no ve ninguna persona: los agentes de la sombra (`aa-v1`, `pa-v1`, `cd-v1`, `pmr-v1`, `la-v1`), Research v2 (`claim-v1`), el extractor en cuarentena (`claim-v2`), `patterns-v1` y las sondas del LAB. **Solo marca** en las que llegan a una vista (del lector o de administración): brief, revisión de picks, narrativas, post-mortems, notas de aprendizaje, `pick-why` y `extract-v1`. Marcar = la respuesta pasa como siempre y la fila de `ai.usage` lleva `output_guard(shadow): …`. |
| `shadow` | Ninguna superficie rechaza; todas solo marcan. **Es la vuelta atrás.** |
| `enforce` | Todas rechazan, también las que ve una persona. Es tu decisión, cuando hayas visto lo que marcan. |

Una petición «fijada» (`pinned`: un experimento) no se toca nunca, en ningún modo. El trabajo `ai_switches` anota la palabra en el libro de interruptores solo cuando deja de ser `default`.

## 4. Inventario (16-nov-2026)

La prueba estática `tests/unit/test_ai_outputs.py` recorre todo `backend/src/fbi` y exige que cada sitio que construye una petición, llama a un modelo o encola una tarea de Batch esté en la lista: **38 sitios**, 17 esquemas, todos cerrados (un objeto sin `additionalProperties: false`, un campo opcional o un nodo sin tipo hacen fallar la prueba) y cada texto libre declarado. `fbi/chronicle` y `fbi/council` no llaman a ningún modelo (la crónica usa `narrative`; el Council por reglas es código).

| Superficie (versión) | Dónde se pide | ¿La ve una persona? | Modo por defecto |
| --- | --- | --- | --- |
| `extract-v1` | `ai/collectors.py` | sí (alimenta `evidence` del paquete) | marca |
| `claim-v1` (`extract-v3`) | `ai/extract_v2.py`, `ai/entity_research.py` | no (Research v2 en sombra) | rechaza |
| `claim-v2` (`extract-v4`) | `ai/quarantine.py` | no | rechaza |
| `aa-v1` (match, stats) · `pa-v1` (player) · `cd-v1` (council) | `ai/agents/*` | no (LAB, sombra) | rechaza |
| `pmr-v1` · `la-v1` | `ai/agents/pmr.py`, `analyst.py` | vista de administración, contenido marcado como no fiable | rechaza |
| `brief-v8` | `ai/brief.py` | sí | marca |
| `review-v2` | `ai/review.py` | sí | marca |
| `postmortem-v3` · `pick-postmortem-v4` · `learning-v2` | `ai/postmortem.py`, `pick_postmortem.py`, `pm_narratives.py`, `learning.py` | vista de administración | marca |
| `patterns-v1` | `ai/patterns.py` | informe del trabajo | rechaza |
| narrativa (`user-narrative-v3`) | `narrative/job.py` | sí | marca |
| `pick-why-v1` | `narrator/` | informe del narrador | marca |
| sondas del LAB | `ai/lab.py` | no | experimento (no se toca) |

**Textos libres que solo tienen el verificador de forma (`shape`), sin cita ni referencias** — 16 campos, la lista exacta que fija la prueba: `brief-v8: summary`; `extract-v1: items[].claim`; `la-v1: hypotheses[].title, .hypothesis, .rationale`; `learning-v2: lessons[].title, .body`; `patterns-v1: hypotheses[].title, .hypothesis, .rationale`; `pick-postmortem-v4: summary, lessons[]`; `postmortem-v3: summary, lessons[]`; `pmr-v1: narrative`; `review-v2: reason` (el servidor la sustituye por la suya al recalcular la decisión). El resto (cerca de 60 campos) tiene cita, referencias, hechos, cifras o es un identificador. Que `brief-v8: summary` y `extract-v1: claim` sigan aquí es lo que la ficha ya decía: el brief se retira con la crónica única (AD-F02) y `extract-v1` lo sustituye `extract-v4` (AD-A01).

## 5. Qué se midió (solo lectura en producción, 16-nov-2026)

| Qué | Dato | Fuente |
| --- | --- | --- |
| Respuestas inválidas en 7 días | **0** en producción y en la sombra; solo 2 de `replay-bank-v1` (experimento, 1.022 llamadas) | `ai.usage` por `prompt_version` y `status` |
| Entradas pedidas otra vez tras una inválida, 14 días | 0 (las 2 del banco de repetición no se repitieron) | `ai.usage` |
| Volumen de `ai.usage` en 14 días | 9.457 filas: la consulta de la regla 5 usa el índice por fecha | `ai.usage` |
| Briefs de modelo sin su narrativa (el lector indulgente pone la de reglas) | **52 de 2.601** (2,0 %) en 14 días: con `enforce` serían `missing_field@narrative` y el partido tendría el brief por reglas | `ai.match_briefs`, `engine = 'llm'`, `content->>'narrative_engine' = 'rules'` |
| `text-guard-v1` sobre textos **ya guardados** (lo que el sistema aceptó) | brief: **3 de 1.500** resúmenes (14 días) llevan marcado de herramienta filtrado (`</summary> <parameter name="context">…`): respuestas rotas que el lector indulgente aceptó; revisiones 0 de 853; post-mortems 0 de 72; narrativas de post-mortem 0 de 299; notas de aprendizaje 0 de 112; hipótesis 0 de 71; narrativas del lector: 1 de 437 decía «www.maxifoot.fr» al atribuir un rumor (por eso un `www.` sin esquema **no** cuenta como enlace) | `ai.match_briefs`, `ai.pick_reviews`, `ai.pick_postmortems`, `ai.postmortem_narratives`, `ai.learning_notes`, `analytics.research_hypotheses`, `ai.user_narratives`; analizado sin red en la imagen del worker |

Límite de esta medición: son textos ya guardados (después de la limpieza de cada lector), así que mide los **falsos positivos** sobre lo aceptado, no cuántas respuestas crudas rechazaría la regla 1. Eso lo dirán las marcas `output_guard(shadow)` de `ai.usage` en los próximos días.

## 6. Qué cambia y qué no

- **No cambia:** ninguna probabilidad, pick, umbral, `decision-v1`, `FBI_PICKS_SOURCE`, prompt, modelo ni versión registrada; nada de lo que ve el lector (las superficies que ve una persona solo marcan); los experimentos.
- **Cambia, en la sombra:** una respuesta de agente con un campo de más, un tipo erróneo o prosa con una orden, un enlace o marcado ya no se guarda. Antes, el analista de aprendizaje limpiaba un `</untrusted>` o un carácter nulo de un título y guardaba el resto; ahora la hipótesis entera se rechaza con su motivo (las pruebas `test_learning_analyst.py` lo dicen así). Research v2 cuenta la respuesta rechazada en `v2_invalid` como antes y su fila de `ai.usage` dice `invalid_output` en lugar de `ok`.

## 7. Cómo se activa, se apaga y se revierte

- Tras desplegar no hace falta nada: el modo `default` ya está en marcha. Mira las filas de `ai.usage` con `error LIKE 'output_guard%'`.
- Para que las superficies del lector también rechacen: `FBI_AI_OUTPUT_GUARD=enforce` y reiniciar el worker (un minuto). Antes, revisa las marcas: por lo medido, un 2 % de los briefs de modelo (los que no traen su narrativa) y unos 3 de cada 1.500 (marcado filtrado) pasarían al brief por reglas, y esa misma entrada no se volvería a pedir.
- Para quitar todo rechazo: `FBI_AI_OUTPUT_GUARD=shadow` y reiniciar el worker. No hay datos que limpiar: nada se borró; las filas de `ai.usage` se conservan.
- Volver al código anterior es revertir el PR: el validador no escribe en ninguna tabla propia.
