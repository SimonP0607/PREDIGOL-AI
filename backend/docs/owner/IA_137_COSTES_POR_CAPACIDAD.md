# IA-137 · Costes por capacidad, «pagar una vez» y corte por pieza al 95 %

Fecha: 17 nov 2026. Pieza AD-K05 del plan de la arquitectura definitiva 2026. Cambia **el panel de costes** (un bloque nuevo) y **dos piezas en sombra** (texto de noticias y crónica única), que ahora dejan de llamar al modelo al 95 % de su tope del mes. Sin migración, sin cambios en la web y sin ningún efecto en el lector.

## 1. Qué hace

* **Cada dólar del mes queda atribuido a una capacidad** (`fbi.ai.capability_costs`, `capability-costs-v1`). Hasta hoy solo las piezas nuevas tenían capacidad (registro de IA-058); el resto del gasto (revisión de producción, brief, búsquedas, extracción, deliberación en sombra…) no tenía dueño. Ahora cada fila de los dos libros (`ai.usage` con su sobre, y el libro de lectores) se da, por este orden:
  1. a una capacidad del registro de IA-058, si es de su mismo sobre (`chronicle_v4`, `battery_v4`, `news_text_shadow`, `replay_regression`…);
  2. a un componente conocido que los caminos de IA-034 no nombran (el narrador del pick `pick-why-`, los agentes de la sombra por su prompt `match-v`, `stats-v`, `player-v`);
  3. al camino y parte de IA-034 (`production.review`, `production.brief`, `research.search`, `research.extraction`, `deliberation.council`…), con las mismas palabras que el informe de coste por camino.
  4. Lo que no cae en nada queda como **`sin_capacidad`**, con su prompt, propósito, nivel y agente, para poder nombrarlo. **El criterio de cierre de AD-K05 es que el mes no tenga ninguna fila así** (`complete: true`).
* **Cuadre con los libros.** La suma de las filas se compara con la suma propia de `ai.usage` y del libro de lectores, leída aparte: el informe da la diferencia a la millonésima y si es menor de un centavo (`reconciles`).
* **Batch, caché y «pagar una vez», por capacidad.** Para cada capacidad: qué parte de sus llamadas fue por Message Batch (`batch_share`), qué parte de su entrada salió de la caché de prompts (`cache_read_share`) y **cuántas llamadas pagadas repitieron una entrada ya pagada este mes** (mismo prompt y misma huella de entrada: `repeat_calls`, `repeat_usd`). En la extracción de páginas esa cifra es la de «pagar una vez cada página leída» y debe ser 0 (la investigación unificada ya identifica la página por su huella y su dirección canónica). En una búsqueda puede ser un refresco legítimo cuando la respuesta caducó: se muestra, no se juzga.
* **Corte por pieza al 95 %** (`capability_budget.piece_allows`, `piece-cut-v1`). Las dos piezas nuevas que llaman solas al modelo preguntan antes de cada llamada:
  * **texto propio de noticias en sombra** (`news_text_shadow`, tope 2,00 del LAB): para en 1,90;
  * **crónica única en sombra** (`chronicle_v4`, tope 14,00 de producción): para cuando lo gastado en el mes más la llamada siguiente llega a 13,30. Sigue además su tope diario de 1,00.
  * **Falla cerrado:** si no se puede leer el gasto del mes, si la capacidad no está en el registro o si su tope es 0, **no llama**.
* **Avisos al 80 % y al 95 %, probados en cada sobre.** Una prueba recorre producción, Exa y LAB por separado (79,99 %, 80 %, 94,99 %, 95 %, 110 %) y comprueba que cada sobre avisa solo por sí mismo.

Dónde se ve: panel de costes (vista privada), bloque nuevo **`attribution`**. Si su lectura falla, el bloque dice `read_failed` y el resto del panel sigue igual. Por consola: `python -m scripts.ia_capability_costs` (mes en curso) o con `--from 2026-11-01 --to 2026-11-16`; solo lectura; sale con 0 si el mes está completo y con 1 si no.

## 2. Qué no cambia

* **Sobres y techo conjunto, igual.** 185 / 35 / 55 con techo conjunto de 190 vigente, pendiente de su confirmación. Este cambio **solo mide y muestra**; no toca ningún sobre, umbral ni tope del registro (`capability-budget-v1` sigue igual).
* El presupuesto de Intelligence (`budget_v3`) sigue decidiendo cada llamada. El corte por pieza se añade por delante; nunca permite gastar más.
* Ninguna ruta, modelo, interruptor ni umbral lee la atribución (`"decides": false`). Ningún proveedor nuevo.

## 3. Lo que queda

* **Medición en producción pendiente.** El 17-nov no se pudo consultar producción desde esta sesión. Tras el despliegue, el panel (o `scripts.ia_capability_costs`) da la primera cifra real: qué parte del mes queda `sin_capacidad` y cuánto se pagó dos veces.
* La batería (`battery_v4`) y el banco de repetición (`replay_regression`) se lanzan a mano y con confirmación: no llevan el corte automático.

## 4. Cómo se apaga o se revierte

* El bloque `attribution` es solo lectura: revertir el cambio lo quita.
* Para volver al corte anterior de las dos piezas (noticias al 100 %, crónica sin tope mensual), se revierte este cambio; ningún registro se pierde.
