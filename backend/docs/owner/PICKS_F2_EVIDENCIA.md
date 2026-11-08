# PICKS: la evidencia antes de cambiar nada (plan PICKS, F2)

Cinco preguntas del plan PICKS (C1 a C5) con una sola herramienta de solo lectura, `scripts/research_picks_calibration.py`. Nada cambia en producción: la herramienta solo lee, y cada decisión que proponga pasa por ti.

Las cifras se rellenan **con la corrida en producción**. Hasta entonces, los resultados dicen «pendiente» y no se adelanta ningún número.

## Cómo se corre

```
python -m scripts.research_picks_calibration                # todas las selecciones liquidadas
python -m scripts.research_picks_calibration --days 60      # solo los últimos 60 días
python -m scripts.research_picks_calibration --json > f2.json
```

## La muestra

Las selecciones en sombra ya liquidadas, una por selección y modelo: el **último pick antes del inicio** de cada partido, mercado, lado, línea y modelo, ganado o perdido (sin nulos, devueltos ni medios resultados). Es la misma población que usa Intelligence para calibrar.

## La probabilidad calibrada, fuera de muestra

`cal-logit2-v1` se reajusta como lo valida producción: cada día de Bogotá se puntúa con un ajuste hecho solo con lo liquidado **antes** de que empezara ese día (ventana de 28 días, al menos 500 selecciones). Ninguna selección se puntúa con un ajuste que la haya visto.

## Criterios, fijados antes de mirar

- Una cifra cuenta con **al menos 300 selecciones liquidadas** en su grupo.
- Cada rendimiento lleva su **IC 95 % por bootstrap de partidos** (las selecciones de un mismo partido ganan o pierden juntas): 1.000 remuestras, semilla 20261108.
- Una propuesta sale solo del intervalo, nunca del valor puntual.

| Pregunta | Qué mide | Qué se propone si se cumple |
| --- | --- | --- |
| Q1 (C1, C2) | Por mercado: probabilidad cruda y calibrada frente al acierto (media y ECE), y el rendimiento de las dos reglas: la del tablero (VE crudo ≥ 5 %, ventaja ≥ 2 pp, cuota 1,50 a 5,00) y la de Intelligence (VE calibrado ≥ 2 %) | Mostrar la calibrada donde su ECE sea menor que la de la cruda. Una regla cuyo intervalo quede entero por debajo de 0 no publica |
| Q2 (C4) | En goles y ambos marcan: cuánto se señala el lado bajo («menos de», «no») y cuánto se inclina el modelo frente al mercado, por competición y con los recién llegados aparte | Una inclinación de 3 pp o más en una competición con 300 selecciones o más se informa como sesgo a corregir en el modelo, siempre a través de su puerta |
| Q3 (C3, S3) | El tope de cuota con la probabilidad calibrada: cada tramo por separado, fuera de muestra | El tope de 3,00 sube hasta el techo de un tramo solo si ese tramo tiene 300 selecciones o más, un intervalo entero por encima de 0 y un valor de línea medio de 0 o más |
| Q4 (C3) | Los grandes desacuerdos (modelo 15 pp o más por encima del mercado) según cómo se movió el mercado después (valor de línea; fuerte si es del 10 % o más) | Un desacuerdo con el mercado moviéndose fuerte en contra pasa a riesgo visible si su intervalo queda entero por debajo del de los demás |
| Q5 (C5) | El rendimiento de la regla calibrada al precio tomado frente al precio justo del mercado (1 / probabilidad del mercado) | La tarjeta dice qué parte del valor es solo el precio |

«Recién llegado»: un equipo que juega esta temporada en una competición que tuvo temporada anterior registrada y en la que ese equipo no jugó (ascendidos, entre otros).

## Resultados

| Pregunta | Fecha de la corrida | Cifra e intervalo | Decisión propuesta |
| --- | --- | --- | --- |
| Q1 | pendiente | pendiente | pendiente |
| Q2 | pendiente | pendiente | pendiente |
| Q3 | pendiente | pendiente | pendiente |
| Q4 | pendiente | pendiente | pendiente |
| Q5 | pendiente | pendiente | pendiente |
