# IA-047 · Banco de repetición de deliberaciones (`INT-C02`)

**Qué es.** Un banco de las ejecuciones guardadas de la sombra que se pueden volver a preguntar **exactamente como se preguntaron**, y el arnés que las vuelve a preguntar por el Batch del LAB (a mitad de precio), con los resultados en tablas propias. Sirve para comparar variantes de un agente o del Council (`INT-C03`, `INT-C05`) con los mismos datos y sin esperar días de sombra. El gate de esta pieza es «reproducibilidad suficiente para comparar variantes»: la variante actual, preguntada otra vez, dice lo mismo que dijo la sombra, tanto como coinciden dos repeticiones de la misma llamada.

**Fase 1 (esta entrega): construido sin gastar.** No se llamó a ningún modelo. Lo único que se ejecutó en producción fue una lectura (sesión de solo lectura) que reconstruyó el banco y calculó el plan y su coste.

**Lo esencial.**

1. De las 1.191 ejecuciones pagadas de la sombra (4 al 11-nov), **489 se rehacen byte a byte**: las 307 del Council con Sonnet (`ma-v1`), las 166 del Council con Haiku (`ma-v1-h`), 7 + 7 del agente Partido en vigor (`match-v5`) y 2 de Estadísticas (`stats-v4`). **Ningún** paquete, porción, vista, identidad o petición de la versión en vigor dejó de reconstruirse.
2. Las otras 702 quedan fuera con su motivo: 688 son de versiones anteriores de los agentes (Partido v1 a v4, Estadísticas v2 y v3) y 14 son escaladas a Opus, que esta versión del banco no incluye.
3. Hoy solo el Council tiene muestra para el gate (837 y 421 unidades). Partido y Estadísticas quedan **INSUFICIENTE**: al ritmo del 10 y 11-nov (3 o 4 evaluaciones de Partido al día) la evaluación de Partido llegaría a 200 unidades hacia el 20 de diciembre.
4. **Primera ejecución: unos US$ 4,11** (prudente 4,63; máximo absoluto 19,77) por 764 preguntas a precio de Batch. Cabe con holgura: el LAB lleva US$ 7,14 de 55 en noviembre y, aun en el peor caso, le quedan 28,09, más que los 20,68 que el banco reserva a la sombra hasta fin de mes. Con ese estado del LAB no puede provocar un `budget_stop`, y el plan lo vuelve a comprobar en el momento de enviar: si no cabe, no envía nada.
5. No toca la sombra ni mueve el Gate B: no escribe en `ai.agent_runs` ni en ninguna tabla que el Gate B o la auditoría de fugas lean, no cambia ningún agente, prompt, esquema, modelo, interruptor, sobre ni la muestra.

## 1. Qué se midió (solo lectura, 11-nov-2026 14:16 UTC)

Dentro del contenedor del worker, con el código desplegado de los agentes y el código nuevo del banco, en una sesión `default_transaction_read_only=on`. Se leyeron las ejecuciones pagadas de la sombra (`ai.agent_runs`, `run_kind = 'shadow'`, estado `ok`, `abstain` o `invalid`) empezadas desde el 4-nov 00:00 de Bogotá: **1.191 ejecuciones de 307 pasadas**. Duración: 140 s.

| Ámbito | Leídas | En el banco | Fuera (motivo) | Unidades guardadas | Partidos |
| --- | ---: | ---: | --- | ---: | ---: |
| Council Sonnet (`council/ma-v1`) | 307 | **307** | — | 837 | 142 |
| Council Haiku (`council/ma-v1-h`) | 166 | **166** | — | 421 | 110 |
| Partido, contexto (`match/context`) | 307 | 7 | 300 versión que ya no está en vigor | 7 | 7 |
| Partido, evaluación (`match/evaluation`) | 307 | 7 | 300 versión que ya no está en vigor | 10 | 7 |
| Estadísticas (`stats/evaluation`) | 90 | 2 | 88 versión que ya no está en vigor | 7 | 2 |
| Escaladas a Opus | 14 | 0 | 14 fuera del banco v1 | — | — |

Las 7 + 7 de Partido son del 10 y 11-nov (`match-v5` empezó el 10-nov); las del Council van del 4 al 11-nov, porque `council-v1` no ha cambiado. El último cambio de una optimización que da forma a la petición fue el 27-oct (el gate `batch`), antes de la primera ejecución de la sombra: ninguna queda fuera por eso.

**Lo que dijo la sombra** (las palabras que el gate compara). Council Sonnet: 680 DOWNGRADE (81 %), 95 REJECT (11 %), 44 ABSTAIN (5 %) y 18 APPROVE (2 %). Council Haiku: 207 DOWNGRADE (49 %), 163 ABSTAIN (39 %), 44 REJECT (10 %) y 7 APPROVE (2 %). Partido `match-v5`: 6 CONCERN, 2 NEUTRAL, 1 REJECT_SIGNAL y 1 SUPPORT. Respuestas guardadas que no se sostuvieron: 1 de 307 en Sonnet (0,3 %) y **9 de 166 en Haiku (5,4 %)**.

## 2. Qué se construyó

**El banco** (`fbi/ai/replay/bank.py`, solo lectura). Una ejecución entra si el código en vigor rehace, byte a byte, todo aquello de lo que se hizo su pregunta, y lo demuestra con los hashes que guardó la sombra:

1. el agente, su versión, prompt, esquema, modelo y esfuerzo son los del registro en vigor para su tarea;
2. el estado de la pasada en la sombra (`ai.match_runs`) nombra el mismo paquete, y el paquete guardado se deriva otra vez con su versión y su código de modelo en el mismo `package_hash` (con la segunda lectura de la auditoría de fugas cuando los pronósticos de conteos aún no eran visibles);
3. la porción del agente se corta otra vez en su `slice_hash`;
4. los candidatos se nombran como los nombró la pasada: las revisiones `rules` de ese paquete escritas antes de la ejecución y, con Estadísticas encendido, las decisiones de las familias que el estado lista;
5. los hallazgos de `contra-v1` se detectan otra vez y, para el Council, su vista se rehace sobre las respuestas guardadas de los agentes de esa pasada (lo que leyó como `A:<etiqueta>`);
6. la identidad de la tarea es su `idem_key` y el hash de la petición es el `input_hash` que el registro de gastos (`ai.usage`) guardó de la llamada;
7. ninguna optimización que da forma a la petición cambió después de la ejecución.

Si algo falla, la ejecución queda fuera con **un código cerrado** (`escalation_out_of_bank`, `version_not_in_force`, `package_not_rebuilt`, `slice_not_rebuilt`, `input_not_rebuilt`, `request_not_rebuilt`… 25 en total, en `bank.REASONS`). Una pasada que no se puede derivar deja fuera sus ejecuciones con su código y nunca para a las demás.

**El arnés** (`fbi/ai/replay/harness.py`).

- **Plan**: qué se preguntaría (cada ejecución del banco, **dos veces**) y cuánto costaría: el coste previsto (los tokens de la llamada guardada a precio de Batch, sin descuento de caché), uno prudente (la respuesta un 50 % más larga), el peor caso (cada respuesta escribe su máximo de tokens) y lo que reserva la cola. No escribe nada.
- **Ejecución**: el plan en **un solo lote** del LAB, todo o nada, solo si: (a) tú lo confirmas (`--confirm-owner`); (b) está registrado el protocolo `proto-int-c02-v1`; (c) el LAB tiene clave, sobre y, para cada ejecución, **el mismo modelo** con el que corrió (nunca se pregunta a otro); (d) el coste prudente cabe en el tope de la ejecución (`--max-usd`, 5 por defecto, nunca más de 15); y (e) el peor caso cabe en lo que le queda al LAB después de reservar para la sombra dos días típicos por cada día que falta del mes. Volver a pedir la misma selección encuentra lo ya enviado: nada se paga dos veces.
- **Respuestas**: el sondeo del worker (`ai_batch_poll`) guarda la respuesta tal cual en su ítem del lote, como hace con la sombra; la recogida (`report`) la lee con el lector del propio agente contra la porción o la vista reconstruidas, como la lee la sombra, y la anota en las tablas del banco. Si entre el envío y la recogida un despliegue cambia el agente en vigor y la entrada ya no se rehace, la respuesta se queda en su ítem sin recoger y el informe lo dice (`not_rebuilt`, con su código); nunca se anota como una repetición inválida.

**La medida** (`fbi/ai/replay/measure.py`): la regla de la sección 3.

**Tablas propias** (migración `0135_replay_bank.py`, solo anexar): `ai.replay_bank_items` (cada ejecución mirada, dentro o fuera con su código), `ai.replay_runs` (cada ejecución con gasto confirmada), `ai.replay_results` (cada respuesta de una repetición) y `ai.replay_assessments` (cada veredicto, con la evidencia para recalcularlo).

**Un módulo compartido tocado, y por qué es imprescindible**: `fbi/ai/lab.py`, una rama de tres líneas en `settle_lab` para el tipo `replay`. El sondeo del worker entrega cada respuesta del LAB a `settle_lab`; sin esa rama, la respuesta de una repetición se perdería después de pagada (`handler_failed`). La rama no cambia nada de lo que hacen las otras (sondas, equivalencia, sombra, batería).

**Script**: `python -m scripts.ia_replay_bank build | plan | run | report` (sección 6).

## 3. La regla: reproducibilidad suficiente para comparar variantes

Se escribe antes de ver datos (`replay-measure-v1`, borrador del protocolo `proto-int-c02-v1`).

- **La unidad**: una palabra de una respuesta guardada, con tres lecturas: la guardada (S) y dos repeticiones de la misma petición (R1, R2). La palabra es la postura de cada candidato (Partido, Estadísticas, Jugadores: SUPPORT, NEUTRAL, CONCERN, REJECT_SIGNAL), el veredicto de cada candidato (Council: APPROVE, DOWNGRADE, REJECT, ABSTAIN; según el contrato de IA-046 equivale uno a uno a la palabra de `ctx-adj-v1` y a su efecto en `decision-v2`) o, en el contexto de Partido, el conjunto de sus señales.
- **Cambio** (la regla del Gate A, con lo guardado en el lugar de la variante): sobre las unidades con las tres lecturas válidas, las veces que S difiere de R1 **no pueden ser más** que las veces que R2 difiere de R1.
- **Validez**: las repeticiones que no se sostienen son como mucho el 3 % y como mucho 1 punto más que las guardadas que no se sostuvieron.
- **Muestra**: al menos 200 unidades completas de al menos 30 partidos por ámbito. Con menos, INSUFICIENTE, nunca PASA.
- **Se informa, no decide**: la diferencia con su intervalo del 95 % por remuestreo de partidos, el cambio frente a las dos repeticiones, qué palabras se mueven y hacia dónde, el acuerdo de la confianza del Council y el coste real.

**Lo que hay que saber de esta regla.** Si la repetición fuera perfecta, los dos recuentos tienen la misma esperanza y la regla pasa algo más de la mitad de las veces (lo comprueba una simulación en las pruebas). Es la misma propiedad de la regla del Gate A. Por eso el informe da el intervalo: un NO PASA con el intervalo por encima de 0 es un fallo claro; uno cuyo intervalo cubre 0 dice que la muestra no distingue. El protocolo no permite repetir el lote para buscar un PASA: una medición nueva usa ejecuciones guardadas nuevas, se decide antes de mirar y se informan las dos.

**Lo que ya se sabe del Council Haiku.** Sus respuestas guardadas no se sostienen en el 5,4 % de los casos: si las repeticiones siguen igual, el ámbito `ma-v1-h` dará NO PASA por validez. No será un fallo del banco, sino el mismo dato que vigila el Gate B (3 % por agente y versión).

## 4. Coste de la primera ejecución y el sobre del LAB

Plan calculado en producción el 11-nov 14:16 UTC con la selección por defecto (como mucho 200 ejecuciones por ámbito, dos preguntas cada una, precio de Batch):

| Ámbito | Ejecuciones | Preguntas | Previsto | Prudente | Peor caso |
| --- | ---: | ---: | ---: | ---: | ---: |
| Council Sonnet | 200 | 400 | US$ 3,84 | 4,30 | 18,91 |
| Council Haiku | 166 | 332 | 0,23 | 0,28 | 0,79 |
| Partido, contexto | 7 | 14 | 0,02 | 0,02 | 0,03 |
| Partido, evaluación | 7 | 14 | 0,02 | 0,03 | 0,03 |
| Estadísticas | 2 | 4 | 0,01 | 0,01 | 0,01 |
| **Total** | **382** | **764** | **4,11** | **4,63** | **19,77** |

**El LAB en noviembre** (`budget_v3.lab_day`): asignación US$ 55, gastado 7,14, quedan 47,86, día típico 0,52. El banco reserva para la sombra 2 × 0,52 × 20 días que faltan = **20,68**. Aun si cada respuesta escribiera su máximo, quedarían **28,09**: el plan no tiene bloqueos. La sombra solo se para por dinero si el LAB no puede abrir el día (lo que queda del mes no llega a un día típico) o si lo que queda no cubre la estimación de un partido (unos céntimos); con 28 dólares libres no ocurre ninguna de las dos. El gasto del banco cuenta en el mes del LAB, que el Gate B compara con su sobre de 55: 7,14 + 4,11 + lo que gaste la sombra el resto del mes sigue muy por debajo.

**Las 489 a la vez**: previsto 6,18, prudente 6,95 y peor caso 29,90. El peor caso dejaría al LAB 17,96, menos que la reserva de la sombra: por eso el límite por defecto es de 200 por ámbito.

**Comparado con la ficha** («unos US$ 2,4 por variante y por mes»): una pregunta del Council Sonnet cuesta unos US$ 0,0096 a precio de Batch. La primera ejecución pregunta cada ejecución dos veces (la segunda es la vara de medir); una variante posterior pregunta una vez y se compara con esas repeticiones, así que cuesta la mitad.

**Un hallazgo de paso**: la cola del Batch reserva para estas preguntas US$ 3,18, menos que el coste previsto (4,11), porque `batch.estimate_cost` cuenta 1,3 tokens por cada 4 caracteres y un paquete JSON tiene más (el propio paquete mide 2,34 tokens reales por cada 4 caracteres, `package.REAL_PER_APPROX`). No se cambia aquí (es un módulo compartido); mientras un lote está abierto, el día del LAB parece aproximadamente un dólar más rico de lo que es, y la reserva para la sombra lo absorbe.

## 5. Qué no cambia, y por qué no mueve el Gate B

- **Ninguna fila** en `ai.agent_runs`, `ai.agent_tasks`, `ai.match_runs`, `ai.pick_reviews` ni `ai.feature_gates` (una prueba lee el código del banco y falla si escribe en otra tabla que no sea suya). Lo que el Gate B cuenta (inválidas por agente y versión, pagos duplicados, atribución, agentes que corrieron, batería) y lo que audita la auditoría de fugas cada noche sale de esas tablas, no de las del banco.
- **El ancla del Gate B** se mueve con la primera ejecución de la sombra, un cambio de los gates de optimización, un cambio de tus interruptores, una versión nueva de un agente en la sombra o un cambio declarado. El banco no hace ninguna de esas cosas: no publica versiones, no cambia interruptores ni la muestra, y sus veredictos van a su propia tabla, no a `ai.feature_gates`.
- **Ningún agente, prompt, esquema, modelo ni esfuerzo cambia.** Cada petición sale **fijada** (`pinned`), con los interruptores aplicados una vez como se aplican a la sombra. En `ai.usage` y en los lotes las preguntas del banco llevan su propia etiqueta (`replay-bank-v1`), sin partido y sin agente: ningún panel de costes las atribuye a la sombra ni a un partido.
- **Lecturas de solo lectura**: `build`, `plan`, `run` sin `--confirm-owner` y `report --no-record` abren una sesión que no puede escribir.

## 6. Cómo se usa

1. Desplegar el código (la migración 0135 y la rama de `settle_lab`). **Una ejecución con gasto solo desde la imagen desplegada**: con un worker anterior, el sondeo no conocería el tipo `replay` y la respuesta se perdería.
2. El agente principal registra `proto-int-c02-v1` en un PR propio (sin él, `run --confirm-owner` se niega).
3. `python -m scripts.ia_replay_bank plan`: qué se preguntaría, cuánto costaría y si hay algún bloqueo.
4. `python -m scripts.ia_replay_bank run --confirm-owner`: un lote del LAB. Opciones: `--scope`, `--limit-per-scope`, `--max-usd`, `--days` o `--since`/`--until`.
5. Esperar al lote (hasta 24 h; el sondeo del worker recoge cada 5 minutos) y `python -m scripts.ia_replay_bank report`: recoge las respuestas y da el veredicto de cada ámbito; lo anota en `ai.replay_assessments` solo si dice algo nuevo.

Códigos de salida: 0 hecho (en `report`, todos los ámbitos PASA), 1 algún ámbito NO PASA o INSUFICIENTE, 2 no se pudo (ver `blockers`), 3 respuestas aún en camino.

## 7. Lo que no se puede medir hoy y los límites

- **Partido y Estadísticas**: con la versión en vigor hay 7 + 7 y 2 ejecuciones guardadas. Al ritmo del 10 y 11-nov (unas 5 unidades de evaluación de Partido al día), la evaluación de Partido llegaría a 200 unidades hacia el 20 de diciembre; su contexto y Estadísticas, hacia principios de enero. Depende del volumen de la sombra, que cambia mucho (el 7-nov tuvo 148 pasadas; el 10-nov, 8). Para comparar variantes de `INT-C03` antes, una versión 2 del banco podría admitir **pasadas** en vez de ejecuciones: las 307 pasadas se rehacen byte a byte, así que una variante de Partido se podría preguntar sobre ellas y compararse con la repetición de la variante actual (sin la respuesta guardada). No está construido.
- **Opus** queda fuera de esta versión (14 escaladas): su pregunta depende de la primera ronda del Council y de las reglas que saltaron.
- **Caché**: las estimaciones no descuentan la caché; si en el lote se lee, el coste real será menor.
- **Tiempo real frente a Batch**: 144 de las 307 ejecuciones del Council Sonnet se hicieron en tiempo real y las repeticiones van por Batch. Si el banco da NO PASA, separar por vía es lo primero que hay que mirar.
- **El proveedor** puede cambiar el modelo detrás del mismo nombre; el banco lo vería como un NO PASA. Para eso sirve.

## 8. Vuelta atrás

- **Código**: revertir el PR. La rama de `settle_lab` desaparece y nada más depende del banco.
- **Datos**: la migración 0135 baja borrando sus cuatro tablas; el banco se reconstruye de la sombra, que nunca se borra. Lo pagado queda en `ai.usage` y `ai.batch_items`.
- **Gasto**: sin `--confirm-owner` no se gasta nada; con él, el tope es el de la ejecución y nunca más de US$ 15.

## 9. Ficheros

- `backend/src/fbi/ai/replay/__init__.py`, `bank.py`, `measure.py`, `harness.py`
- `backend/src/fbi/ai/lab.py` (la rama `replay` de `settle_lab`)
- `backend/migrations/versions/0135_replay_bank.py`
- `backend/scripts/ia_replay_bank.py`
- `backend/tests/unit/test_replay_bank.py`, `test_replay_measure.py`, `test_replay_harness.py`, `test_replay_script.py`
- `backend/tests/integration/test_migration_0135.py`, `test_replay_bank_db.py`
