# IA-074 · Matriz de marcadores única por partido: todos los mercados de goles coherentes (AD-B04)

Pieza AD-B04 del plan de la arquitectura definitiva 2026 (responsable: Modelos). Un modelo de goles (Poisson o Dixon-Coles) dice todo lo que sabe de un partido en **una sola distribución del marcador final**. Esta pieza deriva de esa matriz **todos los mercados de goles a la vez**, de modo que son coherentes entre sí por construcción. También mide en producción, solo leyendo, cuánto se separa de esa matriz lo que hoy publica cada mercado. **En sombra:** nada que decida, publique o sirva a un lector la usa todavía; el primero en hacerlo será la cifra única (AD-B05), con su propia versión. Ningún modelo de lenguaje toca un número. Sin migración. No toca `decision-v1`, ni los paquetes de modelos (su huella sigue en `9a7bec97caec`), ni `web/`, ni la API.

## 1. Qué hace

`fbi/forecasting/score_matrix.py` (`matrix-v1`), funciones puras (sin base de datos ni reloj):

- **`build`**: la matriz a partir de los goles esperados de cada equipo y, en Dixon-Coles, su corrección de marcadores bajos (ρ). Usa la aritmética del propio modelo (`fbi/models/scoring.py`), el mismo corte a 10-10, la masa que queda fuera renormalizada **y declarada**. Un ρ fuera del rango válido se **rechaza** (`InvalidCorrectionError`) como lo rechaza el modelo; nunca se recorta, porque recortarlo sería otro modelo.
- **`derive`**: todos los mercados del menú, cada selección con su probabilidad de ganar y de devolución:

| Mercado | Selecciones | Líneas |
| --- | --- | --- |
| 1X2 | Local / Empate / Visitante | — |
| Doble oportunidad (DC) | 1X / X2 / 12 (sumas del 1X2) | — |
| Empate no acción (DNB) | Local / Visitante; el empate devuelve la apuesta | — |
| Más/menos goles (OU) | Más / Menos | las 26 líneas de 0,5 a 6,75 |
| Ambos marcan (BTTS) | Sí / No | — |
| Goles de un equipo (OU_HOME, OU_AWAY) | Más / Menos | de 0,5 a 3,5 |
| Hándicap asiático (AH) | Local / Visitante; la línea es la de la selección | las 45 líneas de −5,5 a +5,5, cada una como par completo |
| Hándicap europeo (EH) | Local / Empate / Visitante; la línea se aplica al local | −3 a +3 (sin el 0, que es el 1X2) |

Las líneas enteras pueden devolver la apuesta; las de **cuarto** (x,25 y x,75) son media apuesta en cada línea vecina, así que pueden ganar o perder la mitad. Es la convención de `fbi/models/lines.py`, que esta pieza reutiliza, y la de la liquidación (`fbi/picks/settlement.py`). Se puede pedir cualquier otra línea múltiplo de 0,25 (por ejemplo, las que cotiza el mercado).

- **`coherence`**: las reglas que cumple un conjunto coherente.
  - Cada mercado completo suma 1, con devoluciones incluidas, y la devolución es la misma en los dos lados.
  - La doble oportunidad es la suma del 1X2.
  - El empate no acción es el hándicap 0 y devuelve exactamente en el empate.
  - Local −0,5 es la victoria local y local +0,5 es 1X; el europeo +1 local es el asiático +0,5 local.
  - Las escaleras de líneas son monótonas en lo que se gana y en lo que no se pierde.
  - Se cumplen las cotas entre mercados: ambos marcan − empate ≤ más de 2,5 ≤ ambos marcan + local + visitante; ambos marcan ≤ más de 1,5; menos de 1,5 ≤ ambos marcan «No»; local + visitante ≤ más de 0,5; menos de 0,5 ≤ empate.
- **`compare`** y **`published_coherence`**: lo que se publica, puesto al lado de la matriz y comprobado con esas mismas reglas.

## 2. Pruebas

- **Regresión:** las 7 filas que guardan hoy los modelos (1X2, 2,5 y ambos marcan) salen idénticas, con una diferencia de menos de 1e-12 en 7 casos que incluyen goles esperados extremos y ρ positivos y negativos.
- **Coherencia:** las reglas de arriba se cumplen siempre: 0 violaciones en esos 7 casos y en una rejilla de 36 combinaciones de goles esperados entre 0,2 y 4,2.
- **Paridad con el simulador** (`fbi/simulator`, `sim-v1`): leyendo la misma distribución, los 222 mercados de tiempo completo coinciden con una diferencia de menos de 1e-12. Con la matriz del modelo (corte 10-10) frente a la del simulador (corte por mitades), la diferencia es de menos de 1e-5, que es lo que mueve el corte.
- **Paridad con la liquidación** (`tests/unit/test_lines_agree_with_settlement.py`, ampliado): goles por equipo (9 líneas, enteras y de cuarto, de los dos equipos), empate no acción y hándicap europeo (6 líneas) liquidan igual que `fbi/picks` sobre todos los marcadores de la matriz. Para el europeo, que `fbi/picks` no tiene, se comprueba frente al 1X2 liquidado con los goles de ventaja sumados.
- **Rechazos:** un ρ inválido, unos goles esperados no positivos, una matriz que no es una distribución, una línea que no es múltiplo de 0,25 y un europeo no entero.

## 3. Medición en producción (solo lectura, 17-nov-2026, 02:28 UTC)

Comando nuevo `python -m scripts.ia_score_matrix check --hours 72 --json`, con conexión de solo lectura. Muestra: **67 partidos** de las 72 h siguientes con pronóstico en la página; **89 matrices** de Poisson y Dixon-Coles. Los goles esperados se recuperan de las 7 filas guardadas del propio modelo (`fbi.simulator.consistency.invert`), con un **residuo máximo de 1e-6**: es la aritmética del modelo resuelta sobre sus propios números, sin ajustar nada.

| Qué se compara | Muestra | Resultado |
| --- | ---: | --- |
| Filas guardadas del modelo (1X2, todas las líneas de más/menos y de hándicap, doble oportunidad, ambos marcan) frente a la matriz | 4.417 filas | diferencia máxima **1e-6** (el redondeo a 6 decimales): lo que guardan los modelos ya sale de una matriz |
| Coherencia de los 89 conjuntos de la matriz | 89 | **0** violaciones |
| Coherencia de las filas guardadas | 89 | **0** violaciones |
| Página (`forecast-v1`) «Sin calibrar» frente a la matriz del mismo modelo | 137 | mediana 0, máximo 0,36 pp (otro momento del modelo) |
| Página «Calibrado» frente a la matriz del mismo modelo | 52 | mediana 2,9–3,3 pp, máximo 14,9 pp: es la calibración, como está diseñada |
| Coherencia de la página, sus mercados juntos | 67 | **0** violaciones (con la reescalada por mercado, las cotas entre 1X2, ambos marcan y 2,5 se cumplieron) |
| Decisiones (`decision-v1`, `p_cal` de cada selección) frente a la matriz del mismo modelo | 211 | mediana 8,8–12,3 pp según el mercado |
| **Coherencia de las decisiones de un mismo partido** | 34 partidos | **13 incoherentes (38 %)**: 67 escaleras no monótonas, 3 1X2 que no suman 1 (uno suma 0,626), 3 hándicaps de ±0,5 distintos de su 1X2, 1 doble oportunidad distinta de la suma |

**Lectura:**

- La matriz ya está detrás de los números brutos que guardan los modelos.
- La incoherencia nace en la **calibración selección por selección** de la capa de decisión: cada selección se calibra por separado y su devolución sigue siendo la del modelo, y por eso las líneas de un mismo partido dejan de ser monótonas y el 1X2 deja de sumar 1.
- La página es coherente en los tres mercados que cubre, pero cada uno con su propio modelo y calibración, y no cubre el resto.
- Esto es lo que AD-B05 debe resolver: **una matriz y una calibración coherente para toda salida**.

## 4. Lo que no se hizo y por qué

- **Guardar los parámetros (λ local, λ visitante, ρ, versión) de cada lectura**, que la ficha pedía con migración: no es imprescindible para la sombra. Hoy se recuperan de las filas guardadas con un residuo de 1e-6, sin ajustar nada. Si se quieren guardar, será con la migración `0144_…` cuando la cifra única (AD-B05) los lea; esta pieza no la crea.
- **La matriz en el escritor del pronóstico:** ningún lector la consume hasta AD-B05, que la usará con su propia versión (`forecast-v2`).
- **`elo_ologit`** no tiene matriz (solo da un 1X2): sigue como comparación, nunca como fuente de la matriz.

## 5. Qué no cambia

Los modelos y su huella, las filas que guardan, `fbi/models/lines.py`, el simulador, la página, `decision-v1`, los picks y la API. El comando nuevo solo lee: la conexión rechaza escrituras y no pide nada a ningún proveedor ni modelo.

## 6. Cómo se repite y cómo se revierte

```
docker exec -w /app predigol-worker python -m scripts.ia_score_matrix check --hours 72          # resumen legible
docker exec -w /app predigol-worker python -m scripts.ia_score_matrix check --hours 72 --json   # el informe completo
```

Revertir el PR. No hay migración, ni interruptor, ni datos escritos.
