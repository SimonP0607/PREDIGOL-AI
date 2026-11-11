# IA-034 · Cuánto cuesta cada camino de decisión, y si Opus solo sale por regla

Fecha: 11 nov 2026. Estado: **en el código**. Sin migración, sin interruptor y sin columnas nuevas: lee y no escribe. Es la pieza INT-T01 del Plan Maestro de PrediGol Intelligence 2026. Lo vigila `tests/unit/test_cost_paths.py`.

## 1. Qué mide

`fbi.ai.cost_paths` (`cost-paths-v1`, aritmética pura) reparte **cada fila de `ai.usage`** de una ventana en un solo camino, por su prompt:

| Camino | Partes | Qué es |
| --- | --- | --- |
| Producción | `review`, `brief` | `review-v2` (Sonnet en L2 y Opus en L3, en tiempo real o por Batch) y su lectura del partido, `brief-v8` (Haiku) |
| Deliberación en sombra | `match_agent`, `stats_agent`, `player_agent`, `council`, `escalation` | los agentes Partido, Estadísticas y Jugadores, el Council y sus escaladas a Opus (`council-opus-v1`), en el LAB |
| Research / Exa | `search`, `extraction` | las búsquedas de Exa y la extracción de lo que encuentran (`extract-v1`, `extract-v2/v3`) |
| Crónicas | `chronicle` | la crónica de lectores **si** alguna de sus llamadas estuviera en `ai.usage` |
| Resto | `learning`, `postmortem`, `lab`, `other` | aprendizaje, patrones, post-mortems, la batería y las sondas del LAB |

De cada camino y cada parte da: llamadas (y cuántas no acabaron `ok`), coste y su parte del total, **partidos** (los `fixture_id` de sus llamadas), **candidatos** (las selecciones de las filas de `ai.pick_reviews` de sus motores que guardan el id de la llamada: `llm` para producción, los tres motores de la sombra para la deliberación), coste por partido y por candidato, Batch, caché y lo que ahorraron. Cada cifra va con su n.

**Opus solo por regla.** Cada llamada a Opus con la regla que el código dejó registrada y dónde:

* producción: `ai.pick_reviews.output` de la revisión `llm` que guarda la llamada, con `tier = final` y el `role` del ciclo — `pick` (selección del día o pierna de la combinada: `L3_pick`), `contradiction` (reglas y modelo intermedio se contradicen: `L3_contradiction`) o `candidate` (el brief vio un cambio material y es la mejor selección del partido: `L3_material`);
* sombra: `ai.agent_tasks.route` de la tarea, con `action = CALL` y la escalada E1-E7 de `router-v1` que se disparó;
* LAB: `ai.batch_items.context` del ítem (la base `k_escalated` de la batería adversarial: una prueba del prompt, no una decisión).

Una llamada a Opus sin nada de eso se cuenta como **sin regla**, con su coste y sus ids.

**El total cuadra.** El script lee las filas y la suma propia del libro en **una sola instantánea** (`REPEATABLE READ`, solo lectura) y el informe dice la diferencia, a la millonésima de dólar.

## 2. Cómo se corre

```
python -m scripts.ia_cost_paths                                       # vista previa: los últimos 14 días, en español
python -m scripts.ia_cost_paths --since 2026-10-28 --until 2026-11-11 # días UTC completos
python -m scripts.ia_cost_paths --json                                # el informe entero en JSON
```

Sale con 0 si el total es el del libro al céntimo y toda llamada a Opus tiene regla; con 1 si no; con 2 si no puede correr.

## 3. Resultados

Corrida en producción, en solo lectura, el **11 nov 2026 hacia las 05:32 UTC**, dentro de `predigol-worker` (copiado a `/tmp` y borrado después). Ventana: **28-oct 00:00 UTC a 11-nov 00:00 UTC (14 días)**.

**El total cuadra**: 8.390 llamadas y US$ 65,763695 según el informe; 8.390 y US$ 65,763695 según la suma propia de `ai.usage`. Diferencia **0,000000**. Ninguna llamada de la ventana acabó en un estado distinto de `ok`.

| Camino | Coste (parte) | Llamadas | Partidos | Por partido | Candidatos | Por candidato |
| --- | --- | --- | --- | --- | --- | --- |
| Producción | US$ 45,70 (69,5 %) | 4.630 | 1.496 | US$ 0,0305 | 833 | US$ 0,0549 |
| · `review` (`review-v2`) | US$ 34,38 | 944 | 483 | US$ 0,0712 | 833 | US$ 0,0413 |
| · `brief` (`brief-v8`) | US$ 11,32 | 3.686 | 1.496 | US$ 0,0076 | — | — |
| Deliberación en sombra | US$ 5,40 (8,2 %) | 1.178 | 139 | US$ 0,0388 | 435 | US$ 0,0124 |
| Research / Exa | US$ 11,69 (17,8 %) | 1.535 | 393 | US$ 0,0298 | — | — |
| Crónicas (en `ai.usage`) | US$ 0,00 | 0 | — | — | — | — |
| Resto | US$ 2,98 (4,5 %) | 1.047 | 117 | — | — | — |

* **`review-v2`**: Sonnet 761 llamadas (US$ 17,92), Opus 183 (US$ 16,45). Las 944 llamadas tienen su fila de revisión.
* **Deliberación**: Match Agent 608 llamadas (US$ 0,92), Estadísticas 89 (US$ 0,17, 50 partidos), Council 467 (US$ 3,42: Sonnet 304 por US$ 3,31 y Haiku 163 por US$ 0,12), escaladas a Opus 14 (US$ 0,88, 9 partidos). El agente de Jugadores no tuvo llamadas.
* **Research / Exa**: 736 búsquedas de Exa (US$ 11,04, 393 partidos) y 799 extracciones (US$ 0,65).
* **Resto**: aprendizaje y patrones 28 (US$ 0,95), post-mortems 177 (US$ 0,36), LAB 842 (US$ 1,67, todas por Batch).
* **Crónicas**: escriben en su propio libro, `ai.user_usage`, que el informe lee **al lado** del total y nunca dentro: 1.306 llamadas, US$ 2,23 (`user-narrative-v3` 1.282 por US$ 2,19; `v2` 24 por US$ 0,04).

**Opus solo por regla: sí, 233 de 233 (US$ 17,79).**

| Camino · regla | Dónde está registrada | Llamadas | Coste |
| --- | --- | --- | --- |
| Producción · `L3_pick` | `ai.pick_reviews.output` | 116 | US$ 10,19 |
| Producción · `L3_material` | `ai.pick_reviews.output` | 52 | US$ 4,93 |
| Producción · `L3_contradiction` | `ai.pick_reviews.output` | 15 | US$ 1,33 |
| Sombra · E6 | `ai.agent_tasks.route` | 12 | US$ 0,78 |
| Sombra · E7 | `ai.agent_tasks.route` | 2 | US$ 0,10 |
| LAB · batería | `ai.batch_items.context` | 36 | US$ 0,45 |

Ninguna llamada a Opus sin regla. Ojo: producción no usa las reglas E1-E7 del router (esas son de la sombra); usa sus tres condiciones de L3, registradas en cada revisión.

**Batch y caché.**

* `review-v2`: 507 de 944 llamadas por Batch (53,7 %, todas de Sonnet), que ahorraron US$ 9,55 frente a tiempo real. **Ninguna llamada de Opus va por Batch**: el gate `batch` (su evidencia más reciente, del 27-oct) cubre solo Haiku y Sonnet. 116 llamadas de Opus (US$ 10,28) se hicieron en tiempo real aunque la tabla del plan las deja esperar (revisión de un candidato o de un pick con 4 h o más hasta el saque): por Batch habrían costado la mitad, unos **US$ 5,14 menos en 14 días (≈ US$ 11 al mes)**, si el gate llegara a cubrir Opus.
* Deliberación: 628 de 1.178 llamadas por Batch (53,3 %), que ahorraron US$ 2,09.
* Caché leída (tokens de entrada servidos desde la caché): `brief` 24,0 % (98,2 % de sus llamadas la leen), `review` 12,7 %, Council 42,6 %, extracción 22,8 %. Lo que ahorró: US$ 1,59 en `brief`, US$ 2,36 en `review`, US$ 1,15 en la deliberación.

## 4. Lo que significa para el ahorro de INT-C09

INT-C09 estima unos **US$ 85 al mes**: `review-v2` y `brief-v8` «suman unos 107 al mes» y la deliberación a cobertura completa «unos 20». Con estos 14 días:

* `review-v2` + `brief-v8` cuestan **US$ 45,70 en 14 días ≈ US$ 97,9 al mes** (`review-v2` ≈ 73,7; `brief-v8` ≈ 24,3). Es un hecho medido; el mes real dependerá de la carga del calendario.
* La deliberación cuesta **US$ 0,0388 por partido** en la sombra (139 partidos, el 28,8 % de los 483 que `review-v2` revisó). **Hipótesis**: a cobertura completa, con el mismo coste por partido y la misma parte por Batch, serían 483 × 0,0388 ≈ **US$ 18,8 en 14 días ≈ US$ 40 al mes**, el doble de lo que supone INT-C09.
* Con eso el ahorro sería del orden de **US$ 58 al mes** (97,9 − 40,2), no de 85. Si `brief-v8` siguiera escribiendo la lectura de los 1.013 partidos sin candidato, el ahorro bajaría a unos US$ 33 al mes.

Por qué la extrapolación va por partido y no por candidato: casi todo lo que paga la deliberación es por partido y pase (los agentes y el Council leen el partido entero), y los «candidatos» de cada camino no son la misma cosa (la sombra nombra todas las selecciones que las reglas revisaron en el pase, más las familias de córners y tarjetas: 3,1 por partido; `review-v2` solo las que el modelo revisó: 1,7). El brazo `ma-v1-h` (Council con Haiku) pesa unos US$ 0,26 al mes: retirarlo (INT-T04) no mueve esta cuenta.

## 5. Dos hallazgos de paso (sin tocar)

* **El panel de costes exagera el ahorro de la caché de Haiku.** `fbi.ai.costs_v3.savings` suma los tokens de todas las llamadas de un día y un modelo y los vuelve a precio como si fueran **una** llamada; Haiku 5.5 cobra cinco veces más por encima de 100.000 tokens **por prompt**, así que la suma cae en el precio largo y aparece un «ahorro» que no existe. La primera corrida de este informe, que aún sumaba así (ventana 28-oct 05:07 a 11-nov 05:07 UTC), daba US$ 51,73 de «ahorro» de caché en `brief-v8`, más de cuatro veces lo que costó; llamada a llamada, en la ventana del apartado 3, son US$ 1,59. Este informe precia **llamada a llamada**. Corregir el panel es otra pieza.
* **Batch para Opus** necesita evidencia nueva del gate `batch` con Opus en la lista (`scripts/ia_probe.py`); hoy todo L3 va en tiempo real.

## 6. Lo que NO hace

* No decide nada (`"decides": false`), no cambia rutas, modelos, interruptores ni umbrales, y no escribe en ninguna tabla.
* No añade el camino de decisión ni el `trace_id` a `ai.usage` (eso pide columnas nuevas): los reconstruye leyendo las filas de revisión, de tareas y de lotes que ya existen.
* La caché y el Batch se miden con lo que `ai.usage` guarda (`cached_tokens`, `cache_write_tokens`, `batch_id`); lo que «podía esperar» usa la tabla del plan (rol y 4 h hasta el saque), no el pase, que `ai.usage` no guarda.
* No mezcla la IA de los lectores con la de Intelligence (plan UX, A11): solo `fbi.ai.cost_paths_readers` nombra `ai.user_usage`, para enseñar el gasto de las crónicas al lado del total; `tests/unit/test_user_layer_isolation.py` lo lista con esa razón y nada de Intelligence importa el informe.
