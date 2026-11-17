# IA-138 · Memoria: una sola capa de lectura, retiradas como propuesta

Fecha: 17 nov 2026. Pieza AD-K06 del plan de la arquitectura definitiva 2026. Cambia **dónde viven las consultas que leen la memoria**; no cambia lo que se lee ni lo que se escribe. Sin migración, sin cambios en la web, sin efecto en el lector.

## 1. Qué hace

* **Cuatro almacenes, una capa de lectura** (`fbi.memoryread`, `memory-read-v1`). PrediGol guarda lo que recuerda en cuatro sitios: el registro de eventos de la IA (`ai.memory_events`), la memoria por entidad (`intel.entity_memory`, memory-v4), la memoria de las familias (`intel.family_memory`) y el conocimiento de partidos terminados (`intel.match_knowledge`). Hasta hoy cada lector (consola de la IA, consola de Intelligence, consola de familias, página del partido terminado, informe diario, patrones…) tenía su propia consulta. Ahora **las doce consultas que leen memoria están en un solo módulo**, cada una con su almacén y su lector.
* **Paridad comprobada.** Cada consulta se movió letra por letra; su huella sha256 quedó fijada en una prueba frente a la versión anterior (`chain5-FINAL`). Cada lector lee exactamente lo mismo que antes.
* **Una guarda.** Ningún otro módulo de `src/fbi` puede leer esos almacenes, salvo los escritores que leen su propia historia para continuarla y el almacén de conocimiento `ks-v1` (lectura por registros en sombra, el siguiente paso). Si alguien añade una consulta fuera de la capa, la prueba falla.
* **Inventario** (`memoryread.inventory()`): para cada almacén, su escritor, su versión, quién lo lee y si está cerrado.

## 2. Qué no cambia

* **No se borra nada ni se deja de escribir nada.** Los cuatro almacenes siguen escribiéndose y leyéndose como hasta hoy. Ninguna tabla cambia.
* Ningún lector ve otra cosa: mismas consultas, mismos resultados.

## 3. Las retiradas, como propuesta para usted

Lo que podría dejar de escribirse queda como **borrador de propuesta** en el registro de AD-K07 (`fbi.proposals.drafts`), con su evidencia medida el 16-nov-2026:

| Propuesta | Evidencia | Estado |
| --- | --- | --- |
| Dejar de escribir las **tarjetas de análisis** (`fbi.ai.analysis`, `match-analysis-v1`) | 79.336 filas en 14 días para 1.382 partidos (57 por partido); ≈ 215 k filas; repiten las del brief; **un lector aún las lee** (`picks.user_status`) | paridad pendiente |
| Dejar de llamar a **patrones con modelo** (`patterns-v1`) | US$ 0,81 del 1 al 15-nov; ninguna hipótesis llegó a regla | paridad pendiente |
| Dejar las **notas diarias de aprendizaje** (`learning-v1.2`) | US$ 0,18 del 1 al 15-nov; la evaluación posterior única y el tablero cubren la pregunta | paridad pendiente |

Una retirada **no se puede firmar** hasta que se compare lo que leen sus lectores antes y después (`parity = igual`). Las tablas se conservan siempre; la fecha de cierre de un almacén solo se anota cuando usted firma su retirada.

Para registrarlas: `python -m scripts.ia_proposals drafts` (muestra el plan) y `--write` (las añade, pendientes de su firma).

## 4. Cómo se revierte

Revertir este cambio devuelve cada consulta a su módulo; las consultas son idénticas, así que nada cambia para ningún lector.
