# Auditoría de candidatos (F17) y rangos de cuota (F12) — 9 oct 2026

Datos tomados del servidor el 9 oct entre las 17:15 y las 17:25 UTC, solo con lectura. **No se cambió ningún modelo
ni ninguna regla:** lo que sigue son hechos y patrones estadísticos, y las hipótesis van al ciclo formal
(observación → patrón → hipótesis → experimento → backtesting → sombra → comparación con el mercado → promoción
manual del dueño).

## 1. Las «791 selecciones calificadas» de la captura

La lista «Todas las selecciones calificadas» es el tablero de picks en **vista previa sombra**. Muestra una tarjeta por
selección (partido, mercado, selección, línea), con el precio de **ahora** y el EV a ese precio. El número de la
captura depende de la ventana y de los filtros. Hoy, con 72 h y sin filtros, el tablero tenía **4.834 tarjetas en 481
partidos**. Lo que muestra:

| Hallazgo | Cifra | Clase |
|---|---|---|
| Tarjetas por partido | media 10, máximo 23 | **DUPLICACIÓN** |
| Partidos con 2+ tarjetas que apuestan al mismo lado (1X2 local + DC 1X + AH local…) | 273 de 481 | **MERCADOS CORRELACIONADOS** |
| Partidos con 2+ líneas del mismo mercado y selección (Over 3.0 / 3.25 / 3.5 / 4.0…) | 331 de 481 | **LÍNEAS SIMILARES** |
| Tarjetas de picks hechos por las versiones duplicadas 258–260 | 2.117 (44 %) | **MÚLTIPLES MODELOS / DUPLICADO** |
| Tarjetas de las versiones del portátil 249–251 | 768 (16 %) | **MÚLTIPLES VERSIONES** |
| Precio con más de 1 h (envejeciendo) o fuera de la ventana del filtro de valor (rancio) | 1.543 / 2.972 de 4.834 | **DATOS VIEJOS** |
| EV declarado: mediana / p90 / p99 / máximo | 15,8 % / 39,5 % / 78,6 % / 141 % | **EDGES ABSURDOS** |
| Tarjetas con EV > 30 % | 882 | **EDGES ABSURDOS** |

Ejemplos con el EV más alto: Nantes – Reims AH Visitante −0,75 a 4,35 (modelo 59 %, mercado 20 %, EV +141 %) y
Excelsior Virton – Hasselt Menos de 1,5 a 4,72 (modelo 49 %, mercado 18 %, EV +130 %). **Ningún mercado líquido
regala +100 % de EV.** Es el modelo el que está mal donde discrepa tanto, no el mercado.

## 2. ¿Es real el EV? — 8.822 selecciones ya liquidadas

Se toma la última evaluación antes del saque de cada selección y versión, para no contar dos veces las
reevaluaciones:

| EV declarado | n | Acierto real | P. modelo | P. mercado | ROI | Valor de línea (bruto / sin margen) |
|---|---:|---:|---:|---:|---:|---|
| 5–10 % | 1.856 | 40,7 % | 48,1 % | 42,7 % | −7,9 % | +2,4 % / −3,7 % |
| 10–20 % | 2.446 | 40,6 % | 50,4 % | 41,7 % | −4,1 % | +1,4 % / −4,2 % |
| 20–40 % | 2.506 | 41,5 % | 55,4 % | 40,5 % | +0,7 % | +1,9 % / −5,1 % |
| ≥ 40 % | 2.014 | 32,8 % | 59,9 % | 33,0 % | −5,5 % | +3,0 % / −6,0 % |

**Hecho:** en todos los tramos, el acierto real coincide con la probabilidad del **mercado** (con una diferencia de
0,2 a 2,0 puntos), no con la del modelo (entre 7 y 27 puntos por encima). El EV declarado no aparece en los
resultados, y el valor sin margen frente al último precio prepartido es negativo en todos los tramos. Las cuotas
tomadas son buenas en bruto (+1,4 a +3,0 % sobre el cierre del mismo bookmaker), pero no bastan para compensar.

**Clase:** MODEL_ERROR sistemático por sobreconfianza (calibración frente al mercado). No es mala suerte.

## 3. F12 — por rango de cuota

| Rango (cuota tomada) | n | Acierto | P. modelo | P. mercado | Implícita | ROI | Valor de línea |
|---|---:|---:|---:|---:|---:|---:|---:|
| 1,20–1,49 | 0 | — | — | — | — | — | — |
| 1,50–1,79 | 1.782 | 58,8 % | 74,0 % | 59,9 % | 61,4 % | **+2,3 %** | +1,9 % |
| 1,80–2,19 | 1.767 | 50,9 % | 63,2 % | 49,0 % | 50,6 % | **+4,1 %** | +2,3 % |
| 2,20–2,99 | 2.075 | 36,9 % | 52,7 % | 37,9 % | 39,8 % | −5,6 % | +2,2 % |
| 3,00–4,99 | 3.067 | 23,4 % | 37,6 % | 24,4 % | 26,5 % | −9,7 % | +2,1 % |
| 5,00+ | 131 | 15,3 % | 29,9 % | 17,7 % | 20,0 % | −26,3 % | +3,2 % |

- **Cambio estructural:** no hay ninguno. La sobreestimación del modelo es parecida en todos los rangos (entre 12 y
  16 puntos), y el mercado acierta en todos con una diferencia de 1 a 2,5 puntos. Por eso **no conviene especializar
  modelos por rango.** El problema es la calibración, que es la misma en todas partes, y no la forma del modelo en
  cada rango.
- **Patrón conocido (sesgo favorito–longshot):** los favoritos (1,50–2,19) salen ligeramente rentables (+2 a +4 %,
  3.549 selecciones) y las cuotas altas, claramente perdedoras (−10 % de 3,00 a 4,99 y −26 % desde 5,00). Es
  coherente con la literatura, pero el ROI de +2 a +4 % tiene un error típico de unos ±2,5 puntos con esta muestra.
  Queda como **hipótesis H-F12-1**.
- No hay picks entre 1,20 y 1,49. La regla de valor los excluye en la práctica, porque con cuotas tan bajas el EV
  mínimo casi nunca se alcanza.

## 4. Por mercado y modelo (selecciones liquidadas)

| Modelo | 1X2 | AH | DC | OU | BTTS |
|---|---|---|---|---|---|
| dixon_coles | −16,4 % (395) | −11,3 % (1.555) | −11,7 % (120) | +2,1 % (1.681) | +0,3 % (283) |
| poisson | −13,0 % (379) | −8,8 % (1.666) | −18,6 % (124) | +4,0 % (1.780) | +2,1 % (301) |
| elo_ologit | **+4,2 % (538)** | — | — | — | — |

`elo_ologit` es el único modelo cuya probabilidad en 1X2 está cerca del acierto real: 36,5 % de modelo frente a
32,7 % de acierto y 29,5 % de mercado. Los modelos de goles pierden en los mercados de resultado (1X2, AH, DC) y
quedan cerca de cero en los de goles (OU, BTTS).

## 5. Hipótesis para el ciclo formal (ninguna aplicada)

| Id | Hipótesis | Experimento propuesto | Qué cambiaría |
|---|---|---|---|
| H-F17-1 | Encoger la probabilidad del modelo hacia la del mercado (p = α·modelo + (1−α)·mercado, con α estimado *walk-forward*) elimina el EV ilusorio sin perder las selecciones con valor real | Backtest *walk-forward* de α por mercado → 30 días en sombra → comparación con el mercado (log loss, ROI, CLV) | modelos (calibración) |
| H-F17-2 | Un tope de discrepancia (\|p_modelo − p_mercado\| > 0,15 → no seleccionar) quita casi todas las selecciones que pierden por sobreconfianza | Reproducir la regla sobre las 8.822 liquidadas → sombra | reglas de decisión |
| H-F17-3 | Agrupar por partido (una sola selección por lado y mercado) reduce la correlación sin perder ROI | Simulación sobre el histórico | motor de picks |
| H-F12-1 | El sesgo favorito–longshot da un margen pequeño pero real entre 1,50 y 2,19 | Ampliar la muestra (≥ 6.000) y validar con un intervalo de confianza; luego sombra | reglas de decisión |
| H-F18-1 | Los empates de `elo_ologit` tienen valor (+7,3 %, 237 selecciones, ±12 puntos) | **Seguir observando**: hace falta una muestra 4 veces mayor antes de pasar a hipótesis formal | — |

Promoverlas es decisión del dueño, y siempre con experimento y prueba previa.

## 6. Lo que sí se corrigió hoy (sin tocar modelos ni reglas)

- El tablero y los picks del día muestran **una tarjeta por selección** y **una por partido**. Los picks que ya
  empezaron se muestran tal como se tomaron (`started`), sin volver a calcular su precio.
- Cada pick tiene su **valor de línea** frente al último precio prepartido del mismo bookmaker (14.801 calculados).
  Así, el CLV aproximado queda medido en cada pick y no solo en los post-mortems.
- La **cadena de decisión** en cada tarjeta deja claro que es un pick de evaluación (elegido por el modelo → lo que
  dijo la IA → no publicado → liquidado).
- **Pendiente, por decisión del dueño:** que el tablero y los picks del día dejen de considerar los picks de las
  versiones duplicadas 258–260. Esas filas no se han borrado; la instrucción fue auditarlas antes.
