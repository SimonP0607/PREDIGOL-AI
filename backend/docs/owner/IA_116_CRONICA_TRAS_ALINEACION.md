# IA-116 · La crónica tras la alineación y el porqué de cada selección (`lineup-update-v1`, `selection-why-v1`)

Pieza **AD-F03** del plan de la arquitectura definitiva 2026. Nace **apagada** (`FBI_CHRONICLE_LINEUP=off`) y, encendida, va **en
sombra**: escribe en `ai.chronicles`, que ningún lector ve. **No usa ningún modelo de lenguaje ni gasta nada**: todo es plantilla.
No cambia `decision-v1`, ni probabilidades, ni picks, ni umbrales, ni el ciclo de evaluaciones (E3 sigue siendo solo código y debe durar
menos de 2 minutos; esta pieza va después y aparte).

## Qué hace

Cada 2 minutos, para cada **E3** del ciclo de evaluaciones (`intel.eval_runs`, la evaluación al llegar la alineación oficial) de un partido
que ya tiene crónica única, escribe **una versión nueva** de esa crónica:

- **Las secciones de la crónica, tal como estaban** (verificadas por `chronicle-verify-v1`). La versión anterior no se toca nunca: la
  tabla es de solo añadido.
- **El párrafo de la alineación** (`actualizacion`, `lineup-update-v1`), por plantilla y con su hora (hora de Bogotá): la hora a la que se
  conoció la alineación y, para cada jugador que el plan ya nombraba (una baja, una duda, el máximo goleador), lo que dice la alineación:
  titular, suplente o fuera de la convocatoria. Cada frase cita el hecho del plan y el de la alineación (`A:home`, `A:away`).
- **Las frases que la alineación deja viejas** (`superseded`): si la crónica decía «X es baja» y X es titular, esa frase queda marcada
  como superada por la actualización, a su hora. No se reescribe.
- **El porqué de cada selección** que E3 juzgó (`selecciones`, `selection-why-v1`): una frase desde el registro de decision-v2 tal como E3
  lo dejó (estado y motivo, en palabras), y después las frases de la crónica sobre ese mercado **citadas por su índice** (sección y
  número) y copiadas tal cual; si una de ellas quedó superada, se cita la frase de la actualización en su lugar. **Cada frase lleva su
  origen** (`decision`, `chronicle` o `update`); una frase sin origen no se escribe (el trabajo falla ese partido y lo cuenta).

Un nombre que la alineación escribe de otra forma no se adivina: queda en `unplaced`.

## Qué no hace

No llama a ningún modelo (el porqué «con modelo pequeño fuera de la ventana de E3» que permite la ficha **no se ha construido**: no hace
falta para el criterio). No dice cifras de probabilidad, ni «valor», «apuesta», «pick», «seguro»: las plantillas están comprobadas contra
la lista de palabras vetadas del verificador. No toca la crónica de lectores (`user-narrative-v3`).

## Cómo se enciende, se apaga y se revierte

- Encender en sombra: `FBI_CHRONICLE_LINEUP=shadow` en el servidor y reiniciar el worker. Solo tiene efecto si también está
  `FBI_CHRONICLE_V4=shadow` (hace falta una crónica) y `FBI_EVAL_CYCLE=shadow` (hace falta E3).
- Apagar: `FBI_CHRONICLE_LINEUP=off` (o quitar la línea) y reiniciar. Las filas escritas quedan; la crónica vigente vuelve a ser la
  última que no es una actualización.
- Sin migración. Cada fila de actualización: `route = none`, coste 0, `custom_id = lineup-update:<E3>` (nunca dos veces).

## Criterio de cierre y cómo se mide

- 100 % de los partidos con alineación oficial **y crónica** en sombra tienen párrafo con hora: `metrics.kind = lineup_update` por cada
  E3 (`metrics.latency_from_lineup_ms` mide cuánto tardó desde que se vio la alineación).
- 0 frases de explicación sin origen: `metrics.without_origin = 0` en cada fila (y el trabajo se niega a escribir si no).

Probado sin base de datos (`tests/unit/test_chronicle_update.py`, el caso trampa «lesionado que acaba titular» en
`tests/unit/test_chronicle_traps.py`) y con base de datos (`tests/integration/test_chronicle_ia116_db.py`).
