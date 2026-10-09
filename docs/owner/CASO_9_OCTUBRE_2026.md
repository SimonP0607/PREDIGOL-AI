# Caso de estudio: los 5 picks del día del 9 oct 2026

Conjunto de **evaluación** (sombra) del viernes 9 oct, hora de Bogotá. Los picks del día no son recomendaciones
publicadas: son lo que la regla cuantitativa elige entre los picks en sombra, con la revisión de la IA al lado.
Datos leídos en el servidor el 9 oct entre las 16:55 y las 17:25 UTC. Horas en UTC (Bogotá = UTC − 5).

## 1. Los cinco, tal como se registraron

| # | Partido (liga) | Saque | Selección | Elegido (etapa) | Cuota congelada | P. modelo | P. mercado | EV | Resultado (90') | P&L |
|---|---|---|---|---|---:|---:|---:|---:|---|---:|
| 1 | Daejeon Citizen – Jeonbuk (K League 1) | 05:00 | Empate | 8 oct 05:02 (T-24h) | 3,61 Pinnacle | 28,9 % | 26,3 % | +4,5 % | 2-1 · perdido | −1,00 |
| 2 | Kashiwa Reysol – Vissel Kobe (J1) | 10:00 | Gana Vissel Kobe | 8 oct 13:59 (T-24h) | 3,32 1xBet | 39,3 % | 28,3 % | +30,5 % | 4-2 · perdido | −1,00 |
| 3 | Hangzhou – Shanghai SIPG (Super League) | 12:00 | Empate | 8 oct 13:59 (T-24h) | 4,00 Betfair | 29,0 % | 23,7 % | +15,9 % | 2-4 · perdido | −1,00 |
| 4 | Osaka – Kanazawa (J3) | 10:00 | Gana Osaka | 8 oct 13:59 (T-24h) | 2,26 Dafabet | 47,9 % | 41,8 % | +8,2 % | 1-1 · perdido | −1,00 |
| 5 | Sichuan Jiuniu – Henan (Super League) | 11:35 | Empate | 8 oct 13:59 (T-24h) | 3,70 Betfair | 28,9 % | 26,1 % | +6,9 % | 2-2 · **ganado** | +2,70 |

**Total: 1 ganado, 4 perdidos, 0 pendientes; −1,30 u** (5 u apostadas a 1 u cada una). Las cinco son del modelo
`elo_ologit` (versión 251, la del portátil antes del corte), todas 1X2; tres son empates.

La captura de pantalla mostraba Hangzhou – Shanghai como «Pendiente»: terminó a las 13:58:18 y se liquidó en la
pasada de picks de las 14:04, visible hacia las 14:07. **Con el arreglo de hoy (`ba645ac`) se liquida en el minuto
en que el seguimiento en vivo ve el final**, y la espera queda registrada (Admin → Picks → Liquidación).

## 2. ¿Fue mala suerte o mala decisión?

**El mercado se movió a favor en 2 de 5 y no en contra en ninguno:**

| # | Cuota tomada | Último precio prepartido, mismo bookmaker | Valor de línea | P. mercado al elegir → antes del saque |
|---|---:|---:|---:|---|
| 1 | 3,61 | 3,61 (44 min antes) | 0,0 % | 26,3 % → 26,3 % (estable) |
| 2 | 3,32 | 3,14 (70 min antes) | **+5,7 %** | 28,3 % → 29,9 % (a favor) |
| 3 | 4,00 | — (el proveedor ya no lo tenía) | — | 23,7 % → 23,5 % (estable) |
| 4 | 2,26 | 2,15 (69 min antes) | **+5,1 %** | 41,8 % → 44,0 % (a favor) |
| 5 | 3,70 | 3,70 (187 min antes) | 0,0 % | 26,1 % → 26,0 % (estable) |

Ese «último precio prepartido» no se ha validado como el precio de cierre; por eso se llama valor de línea y no CLV.

- **#2 y #4:** el mercado acabó acercándose a lo que veía el modelo. Fueron decisiones razonables que perdieron
  (4-2 y 1-1). Son variación normal.
- **#1 y #5:** son empates con una ventaja pequeña (2,6 y 2,8 puntos) que el mercado no confirmó. Una se ganó y
  otra se perdió. Tampoco dicen nada por separado.
- **#3:** solo `elo_ologit` veía el empate en 29 %. Dixon-Coles daba 23,1 %, Poisson 22,0 % y el mercado 23,7 %.
  Es la elección más débil del día: un modelo contra todos.

## 3. Lo que dijo la IA antes del saque

Cuando se eligieron (el 8 de octubre) todavía no había revisión. La última revisión antes de cada saque, del 9 de
octubre, fue **REBAJAR en los cinco casos**:

| # | Motor | Confianza | Motivo (resumen) |
|---|---|---:|---|
| 1 | Sonnet | 0,55 | ventaja pequeña, sin contexto que la respalde ni la contradiga |
| 2 | Opus | 0,62 | los modelos la apoyan, pero 10,7 puntos frente a un mercado estable es demasiado; ni el xG ni el historial directo la respaldan |
| 3 | Opus | 0,62 | solo `elo_ologit` ve el empate; los otros modelos y el mercado le dan 22-24 % |
| 4 | Sonnet | 0,55 | hay valor en el local, pero la ventaja es alta, los intervalos son amplios y faltan alineaciones y bajas |
| 5 | Sonnet | 0,60 | la ventaja del empate sale solo de Elo; Poisson y el mercado no la confirman |

**La IA no cambió el conjunto, y eso es correcto.** Está en modo sombra: su decisión se registra al lado y solo
puede sacar o reordenar una selección cuando el dueño activa el modo forzado *y* la IA ha superado su propia
prueba en sombra. En la pantalla, sin embargo, los cinco aparecían como «Picks del día» sin decir que la revisión
los había rebajado. **La fase 16 corrige esto:** cada tarjeta muestra la cadena completa (elegido por el modelo →
revisado por la IA → no publicado → liquidado).

## 4. Aprendizajes (observaciones, no reglas)

1. **El modelo sobreestima cuando discrepa del mercado.** En 8.822 selecciones liquidadas (la última antes del
   saque por selección y versión), el acierto real sigue a la probabilidad del mercado y no a la del modelo:
   con EV declarado ≥ 40 % el modelo decía 59,9 %, el mercado 33,0 % y se acertó el 32,8 %. Esto es un patrón
   estadístico; está documentado en `AUDITORIA_CANDIDATOS_Y_CUOTAS_2026-10-09.md`.
2. **Los empates de `elo_ologit`** van 237 selecciones, 25,7 % de acierto, ROI +7,3 %. El error típico de ese ROI
   es de unos ±12 puntos, así que **no es significativo**. Queda como *patrón en observación*, no como hipótesis.
3. **La revisión de la IA rebajó los cinco y cuatro perdieron.** Una sola jornada no prueba nada. La comparación
   correcta es la que ya hace la IA en sombra (sus decisiones contra el resultado y contra el mercado, en muestras
   de cientos), y es la que decide si algún día puede pasar a modo forzado.
4. **Volumen de picks:** el mismo empate de Daejeon tuvo 9 picks antes del saque y el partido tuvo 156, porque se
   reevalúa en cada captura y cada modelo. El tablero y los picks del día ya muestran uno por selección (y uno
   por partido). La depuración del histórico está en la auditoría de candidatos.

## 5. Estado del registro de estos cinco

- Cada uno es un registro congelado. Desde la migración 0074, un trigger impide cambiar el precio, la hora, las
  probabilidades o el EV.
- El post-mortem del #1 ya existe (variación normal, valor de línea +0,8 % frente a 3,61). Los del #2 al #5 se
  escriben mañana a las 07:35 Bogotá, cuando se cumplen tres horas desde el último saque, y quedan enlazados a este
  día.
