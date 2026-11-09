# PICKS: la evidencia antes de cambiar nada (plan PICKS, F2)

Cinco preguntas del plan PICKS (C1 a C5) con una sola herramienta de solo lectura, `scripts/research_picks_calibration.py`. Nada cambia en producción: la herramienta solo lee, y cada decisión que proponga pasa por ti.

Las cifras se rellenan **con la corrida en producción**. Hasta entonces, los resultados dicen «pendiente» y no se adelanta ningún número.

## Cómo se corre

En el servidor, dentro del contenedor del worker (la herramienta abre su conexión en solo lectura):

```
docker exec -w /app predigol-worker python -m scripts.research_picks_calibration                # todas las selecciones liquidadas
docker exec -w /app predigol-worker python -m scripts.research_picks_calibration --days 60      # solo los últimos 60 días
docker exec -w /app predigol-worker python -m scripts.research_picks_calibration --json > picks_f2.json
```

## La muestra

Las selecciones en sombra ya liquidadas, una por selección y modelo: el **último pick antes del inicio** de cada partido, mercado, lado, línea y modelo, ganado o perdido (sin nulos, devueltos ni medios resultados). Es la misma población que usa Intelligence para calibrar.

Q2 tiene además su propia muestra: **todos los partidos terminados** con pronóstico y mercado, no solo los que el modelo señaló, porque un pick señalado siempre tiene al modelo por encima del mercado. Para «menos de 2,5» y «ambos marcan: no» se toman el último pronóstico real de cada modelo antes del inicio (sin backtests), el último consenso del mercado antes del inicio con el método del motor (Shin) y el resultado a los 90 minutos.

## La probabilidad calibrada, fuera de muestra

`cal-logit2-v1` se reajusta como lo valida producción: cada día de Bogotá se puntúa con un ajuste hecho solo con lo liquidado **antes** de que empezara ese día (ventana de 28 días, al menos 500 selecciones). Ninguna selección se puntúa con un ajuste que la haya visto.

## Criterios, fijados antes de mirar

- Una cifra cuenta con **al menos 300 selecciones liquidadas** en su grupo.
- Cada rendimiento lleva su **IC 95 % por bootstrap de partidos** (las selecciones de un mismo partido ganan o pierden juntas): 1.000 remuestras, semilla 20261108.
- Una propuesta sale solo del intervalo, nunca del valor puntual.

| Pregunta | Qué mide | Qué se propone si se cumple |
| --- | --- | --- |
| Q1 (C1, C2) | Por mercado: probabilidad cruda y calibrada frente al acierto (media y ECE), y el rendimiento de las dos reglas: la del tablero (VE crudo ≥ 5 %, ventaja ≥ 2 pp, cuota 1,50 a 5,00) y la de Intelligence (VE calibrado ≥ 2 %) | Mostrar la calibrada donde su ECE sea menor que la de la cruda. Una regla cuyo intervalo quede entero por debajo de 0 no publica |
| Q2 (C4) | El síntoma: cuánto del lado bajo («menos de», «no») hay entre lo señalado. El diagnóstico, sobre todos los partidos: cuánto se inclina el modelo frente al mercado (media de modelo menos mercado), qué pasó de verdad y quién quedó más cerca, por competición y con los recién llegados aparte | Una inclinación de 3 pp o más hacia cualquier lado, con 300 partidos o más, un intervalo que no incluye el 0 y el modelo más lejos que el mercado de lo que pasó, se informa como sesgo a corregir en el modelo, siempre a través de su puerta. Si el modelo se inclina y acierta, no es un sesgo que corregir |
| Q3 (C3, S3) | El tope de cuota con la probabilidad calibrada: cada tramo por separado, fuera de muestra | El tope de 3,00 sube hasta el techo de un tramo solo si ese tramo tiene 300 selecciones o más, un intervalo entero por encima de 0 y un valor de línea medio de 0 o más |
| Q4 (C3) | Los grandes desacuerdos (modelo 15 pp o más por encima del mercado) según cómo se movió el mercado después (valor de línea; fuerte si es del 10 % o más) | Un desacuerdo con el mercado moviéndose fuerte en contra pasa a riesgo visible si su intervalo queda entero por debajo del de los demás |
| Q5 (C5) | El rendimiento de la regla calibrada al precio tomado frente al precio justo del mercado (1 / probabilidad del mercado), y la diferencia en puntos | La tarjeta dice cuántos puntos del rendimiento vienen solo del precio. Se da en puntos y no como parte del rendimiento, porque esa parte cambia de sentido cuando el rendimiento es negativo |

«Recién llegado»: un equipo que juega esta temporada en una competición que tuvo temporada anterior registrada y en la que ese equipo no jugó (ascendidos, entre otros).

## Resultados

Corrida del 9-nov-2026 con `--days 45`, que cubre desde que empezó el motor: 75.273 selecciones liquidadas, 68.992 con calibrada fuera de muestra, y 15.348 pronósticos de 3.840 partidos para Q2. ROI con su IC 95 % por bootstrap de partidos.

### Q1 (C1, C2): probabilidad cruda y calibrada

| Mercado | n | Acierto | Cruda (ECE) | Calibrada (ECE) | Mercado (ECE) | Regla del tablero | Regla calibrada |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1X2 | 8.233 | 31,9 % | 38,1 % (0,062) | 31,5 % (0,005) | 31,1 % (0,012) | −1,8 % [−6,3; +2,4] | +3,5 % [−3,9; +10,7], n 1.750 |
| Hándicap asiático | 27.001 | 38,9 % | 49,8 % (0,109) | 38,6 % (0,011) | 39,1 % (0,018) | **−7,3 % [−12,4; −2,0]** | −1,6 % [−7,1; +3,8], n 4.959 |
| Ambos marcan | 3.701 | 46,2 % | 54,6 % (0,084) | 45,9 % (0,013) | 44,8 % (0,025) | −1,2 % [−6,2; +4,2] | +0,9 % [−9,9; +10,8], n 1.075 |
| Doble oportunidad | 1.576 | 45,5 % | 56,3 % (0,109) | 44,9 % (0,018) | 45,5 % (0,044) | −7,2 % [−14,2; +0,3] | +3,1 %, n 278 (muestra corta) |
| Más/menos goles | 28.481 | 38,8 % | 51,7 % (0,129) | 39,9 % (0,012) | 40,2 % (0,015) | **−11,1 % [−15,9; −6,5]** | −0,9 % [−12,3; +10,7], n 2.904 |

El valor de línea medio de la regla calibrada es negativo en los cinco mercados (de −0,4 % a −4,5 %).

**Decisión propuesta:**

- Mostrar la probabilidad calibrada en todos los mercados: la cruda exagera de 7 a 13 puntos y la calibrada queda a la altura del mercado.
- La regla del tablero no publica en hándicap asiático ni en goles, porque su intervalo queda entero por debajo de 0.
- Ninguna regla calibrada tiene un intervalo por encima de 0 ni valor de línea positivo, así que edge-gate-v1 no aprobaría ningún mercado. Hoy no se publica nada, y está bien.

### Q2 (C4): el sesgo de goles

Síntoma: entre lo señalado, el 74 % de los picks de goles es «menos de» y el 81 % de ambos marcan es «no».

Diagnóstico, sobre todos los partidos terminados con pronóstico y mercado:

| Modelo y mercado | Partidos | Modelo | Mercado | Pasó | Inclinación | ¿Sesgo? |
| --- | --- | --- | --- | --- | --- | --- |
| Dixon-Coles, menos de 2,5 | 3.836 | 48,0 % | 43,6 % | 44,2 % | +4,4 pp [4,1; 4,7] | **Sí** |
| Poisson, menos de 2,5 | 3.841 | 47,9 % | 43,6 % | 44,2 % | +4,4 pp [4,0; 4,7] | **Sí** |
| Dixon-Coles, ambos marcan «no» | 3.833 | 47,6 % | 44,0 % | 44,8 % | +3,6 pp [3,3; 3,9] | **Sí** |
| Poisson, ambos marcan «no» | 3.838 | 48,0 % | 44,0 % | 44,8 % | +4,0 pp [3,7; 4,2] | **Sí** |

**Decisión propuesta:** los dos modelos de goles prevén menos goles de los que hay, y el mercado acierta mejor. Es un sesgo que hay que corregir en el modelo, a través de su puerta. Por competición no se puede afirmar todavía: ninguna llega a 300 partidos (la mayor, la Premier League, tiene 116), y los recién llegados tampoco.

### Q3 (C3, S3): el tope de 3,00

| Tramo de cuota | n | ROI | Valor de línea |
| --- | --- | --- | --- |
| hasta 1,70 | 3.553 | +1,0 % [−3,3; +5,5] | −1,3 % |
| 1,70 a 2,50 | 5.009 | −0,3 % [−5,4; +4,9] | −1,0 % |
| 2,50 a 3,00 | 1.321 | −1,3 % [−10,4; +8,1] | −2,9 % |
| 3,00 a 3,50 | 580 | −5,9 % [−22,4; +10,7] | −2,6 % |
| 3,50 a 4,00 | 232 | +3,9 % (muestra corta) | −2,7 % |
| 4,00 a 5,00 | 233 | −3,2 % (muestra corta) | −2,3 % |
| más de 5,00 | 38 | muestra corta | −5,0 % |

**Decisión propuesta:** el tope de 3,00 se mantiene. Ningún tramo por encima tiene 300 selecciones con un intervalo por encima de 0 y valor de línea positivo.

### Q4 (C3): grandes desacuerdos y el mercado en contra

Con el modelo 15 pp o más por encima del mercado:

- Si el mercado se movió fuerte en contra (valor de línea de −10 % o menos): −17,8 % [−31,2; −4,0], n 2.518, valor de línea medio −16,8 %.
- El resto: −2,3 % [−9,1; +4,2], n 11.975.

**Decisión propuesta:** el criterio, que pedía intervalos separados, no se cumple: se solapan entre −9,1 % y −4,0 %. Pero el primer grupo pierde con un intervalo entero por debajo de 0. Queda como candidato a riesgo visible; se repite la medida con más datos.

### Q5 (C5): el precio

- La regla calibrada, al precio tomado: −0,3 % [−4,9; +4,2].
- La misma regla, al precio justo del mercado: +1,8 % [−2,9; +6,2].
- Diferencia: **−2,0 puntos**.

**Decisión propuesta:** el precio no aporta valor, cuesta unos 2 puntos, que es el margen de las casas. La tarjeta no debe presentar el precio como fuente de valor.
