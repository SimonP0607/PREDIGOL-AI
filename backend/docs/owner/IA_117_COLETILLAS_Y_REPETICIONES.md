# IA-117 · Coletillas y repeticiones de la crónica (`repeat-check-v1`)

Pieza **AD-F04**. Es una regla dentro del verificador de la crónica única (`chronicle-v4`), **sin modelo y sin coste**. Interruptor
`FBI_CHRONICLE_REPEAT`: **`shadow` por defecto** (mide y no quita nada), `on` (quita) u `off` (no mide). Como toda la crónica única está en
sombra (`FBI_CHRONICLE_V4`), nada de esto llega a un lector en ningún caso.

## Por qué

En 14 días de textos de hoy (Doc 1, n = 2.684 briefs): «alineaciones no confirmadas» en el 96 %, «sin datos suficientes» en el 56–60 %,
jerga interna en el 80–83 %, y casi la misma longitud en todos los partidos. Manda la plantilla, no la información.

## Qué mide en cada crónica (queda en `metrics.repetition`)

- **La plantilla** de cada frase: la frase con los nombres, los números y las cifras enmascarados («<n> suma # puntos en # partidos»), y
  en qué parte de las crónicas recientes de otros partidos aparece (las 300 más nuevas de 14 días, una por partido).
- **Coletilla**: una fórmula de la lista cerrada (alineaciones no confirmadas, sin datos suficientes, «el modelo», «la sombra», «el
  sistema», «muestra pequeña», «habrá que ver», «partido igualado»…) o una plantilla presente en al menos el **30 %** de las recientes.
- **Repetición**: la misma frase, con sus nombres y números, que ya dijo la crónica anterior de uno de los dos equipos.
- Si la crónica **abre con lo que cambió**: su primera frase cita un hecho que el plan anterior del partido no tenía.
- Las tasas: `generic_rate` (coletillas / frases) y `repeat_rate` (repetidas / frases).

Con menos de 20 crónicas recientes medidas, la parte de cada plantilla no se calcula (no diría nada).

## Qué hace con `on`

Quita la frase que es plantilla de al menos el 30 % de las recientes o que repite la crónica anterior del equipo, **como una frase sin
apoyo**: queda en `dropped` con su motivo («coletilla: …», «repetida: …»), y la versión del verificador pasa a ser `chronicle-verify-v2`.
**Nunca quita una frase que cita un hecho obligatorio** del plan (un objetivo demostrado, una baja clave, una noticia confirmada): se cuenta
como `exempt`. Si quita todas, la crónica se abstiene con `VERIFICACION_VACIA`.

## Umbrales: propuestos, sin firmar

30 % de plantilla, 10 % de coletillas por crónica, 10 % de repeticiones por crónica, mínimo 20 crónicas. Están en el protocolo de AD-F06
(`fbi/chronicle/protocol.py`, ver IA-118) para que el dueño los firme. Hasta esa firma, **no se recomienda poner `on`**.

## Lo que falta medir

La repetición sobre los textos de producción de 14 días (briefs y crónicas de lectores, antes y después) **no se pudo correr** el
17-nov-2026: el acceso de solo lectura a producción no estaba disponible desde esta sesión. Queda como primer paso tras desplegar
(ver la entrega del PR). No se inventa ninguna cifra.

## Apagar y revertir

`FBI_CHRONICLE_REPEAT=off` y reiniciar el worker: no mide ni quita. Las crónicas guardadas no cambian. Sin migración.
