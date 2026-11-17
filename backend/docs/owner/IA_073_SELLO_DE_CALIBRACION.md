# IA-073 · Sello de calibración estable y calibración completa del núcleo (AD-B03)

Pieza AD-B03 del plan de la arquitectura definitiva 2026 (responsable: Modelos). Corrige el pronóstico que **alterna entre «Calibrado» y «Sin calibrar»** de una pasada a otra sin que cambie nada de fondo, y deja el inventario y el plan de calibración de las cifras del núcleo que siguen sin calibrar. **Lo que ve el lector no cambia**: `forecast-v1` (la página del partido, el paquete de la IA y todos sus lectores) sigue igual, con los mismos números y las mismas filas. El sello estable se escribe **en sombra**, al lado, con su propia versión (`forecast-v1-seal`), que no lee ningún lector. **No se ajusta, promociona ni retira ningún calibrador**: eso lo firma el dueño. No toca `decision-v1`, ni los paquetes de modelos, ni `web/`, ni la API. Sin migración.

## 1. Por qué alterna (medido en producción, solo lectura, 16-nov-2026 por la noche, hora de Bogotá)

**El caso que vio UX** (partido 170072, Arsenal W – London City, saque el 15-nov a las 16:30 UTC), conjuntos del 1X2 que guardó `forecast-v1`:

| Momento (UTC) | Sello | Motivo | Local | Precio usado (captura) |
| --- | --- | --- | ---: | --- |
| 13-nov 16:33 | Calibrado | campeón #652 | 0,584 | 13-nov 16:33 |
| 13-nov 22:34 | **Sin calibrar** | `needs_price` | 0,785 | — |
| 14-nov 16:30 | Calibrado | campeón #652 | 0,600 | 14-nov 16:30 |
| 14-nov 22:32 | **Sin calibrar** | `needs_price` | 0,785 | — |
| 15-nov 04:33 | Calibrado | campeón #652 | 0,599 | 15-nov 04:30 |
| 15-nov 10:35 | Calibrado | campeón #652 | 0,588 | 15-nov 10:30 |

El consenso de ese partido se capturó una vez al día (16:30 UTC) hasta el día del partido. **Seis horas después de cada captura** la siguiente pasada del pipeline ya no encuentra un precio «fresco» (`MAX_MARKET_AGE` = 6 h en `fbi/forecasting/market_view.py`), y escribe el mismo número del modelo como «Sin calibrar». Con la captura siguiente vuelve a «Calibrado». El modelo, su versión y el campeón no cambiaron: solo la edad del precio pasó de seis horas. **La causa que la ficha daba como probable queda verificada.**

**La causa es general, no de un partido.** Últimos 7 días de `forecast-v1` (`models.match_forecasts`):

- 6.654 conjuntos de mercado (1X2, más/menos 2,5, ambos marcan) de 450 partidos; **3.245 (48,8 %) «Sin calibrar», todos por `needs_price`**. Ninguno por `no_champion`: los tres mercados tienen campeón para todos sus modelos.
- De los 1.178 mercados pronosticados, **893 (75,8 %) cambiaron de sello al menos una vez** (345 de 450 partidos). Hubo **4.496 cambios**, todos entre `champion` y `needs_price` y **ninguno con cambio de modelo**.
- Los conjuntos `needs_price` del 1X2 tenían un precio de 6 a 12 h en 707 casos, de 12 a 24 h en 1, de más de 72 h en 6, y **ninguno en 436** (el mercado aún no había abierto).
- Entre dos capturas seguidas del mismo consenso (1X2 local, 1.443 pares, partidos de los últimos 7 días), la probabilidad sin margen se movió de media **0,70 pp** con 1–6 h de hueco, **1,09 pp** con 6–12 h, **1,02 pp** con 12–24 h y **0,87 pp** con 24–48 h. Un precio de ayer dice casi lo mismo que uno de hace una hora; huecos de más de 4 días hubo 11 de 1.443.

## 2. La regla nueva del sello (`seal-v1`, `fbi/forecasting/seal.py`)

Una cifra es **`calibrada`** cuando, y solo cuando, su mercado y modelo tienen un **calibrador campeón vigente** (validado por `calib-gate-v1` y no retirado) que se puede aplicar. Para un campeón `logit2` (todos los de hoy), con el **consenso sin margen más reciente de los últimos 4 días** (el horizonte del pronóstico, `HORIZON`), tenga la edad que tenga dentro de esa ventana. Si no, es **`sin_calibrar`** con su motivo:

| Motivo | En palabras |
| --- | --- |
| `no_champion` | sin calibrador validado para este mercado y modelo |
| `needs_price` | el calibrador necesita el precio del mercado y aún no hay ninguno |
| `not_applicable` | el calibrador no se puede aplicar a estos números |

Así el sello **solo cambia cuando cambia su causa**: se promociona o retira un campeón, llega el primer precio del partido o, rara vez, el precio supera los 4 días. **Nunca depende de la hora ni del orden de las pasadas.** Cada lectura guarda la hora del precio que usó (`market_as_of`), así que se puede decir «calibrada con el precio de las 16:30».

**Repetición en producción** (los mismos 6.654 conjuntos de 7 días, recalculando el sello con la regla nueva en cada momento):

| | `forecast-v1` (hoy) | `seal-v1` |
| --- | ---: | ---: |
| Conjuntos «Sin calibrar» | 3.245 (48,8 %) | **1.227 (18,4 %)**, todos sin ningún precio en 4 días |
| Cambios de sello | 4.496 | **703**, todos de «Sin calibrar» a «Calibrado» al llegar el primer precio |
| Cambios de sello **sin cambio de motivo** | 4.496 | **0** |
| Mercados con algún cambio | 893 | 703 (uno como mucho cada uno) |

Por mercado, pasan de «Sin calibrar» a «Calibrado» 713 conjuntos del 1X2 (quedan 442 sin calibrar), 649 de ambos marcan (quedan 382) y 656 de más/menos 2,5 (quedan 403). Límite de la medida: se recalcula en los momentos en que `forecast-v1` escribió un conjunto, no en cada pasada. Con la regla nueva solo hay cambios cuando llega un precio, cuando un precio supera 4 días o cuando cambia un campeón, y los tres son cambios de motivo.

## 3. Qué cambia en el código

- **`fbi/forecasting/seal.py`** (nuevo, puro): la regla, el sello en palabras del contrato (`calibrada` / `sin_calibrar`, las de `fbi/api/contracts/intelligence/vocab.py`), sus motivos y la prueba de repetición (`changes`, `unexplained`: cuántos cambios de sello hubo sin cambio de motivo; el cierre pide 0).
- **`fbi/forecasting/match_forecast.py`**: con `FBI_FORECAST_SEAL=shadow` (valor por defecto en código) cada pasada escribe también `forecast-v1-seal`. Es la misma función, con los mismos números del modelo y el precio leído en la ventana de 4 días en vez de 6 h. Va en un punto de guardado propio, **después** de `forecast-v1`: si falla, `forecast-v1` se escribe igual y el fallo queda en el resumen de la pasada. Solo se escribe cuando algo cambia, como `forecast-v1`.
- **`fbi/forecasting/market_view.py`**: `forecast_market(..., version=)` solo lleva la versión a la huella (`input_hash`); por defecto es `forecast-v1` y calcula exactamente lo mismo que antes (lo prueba un test).
- **`fbi/forecasting/market_reader.py`**: `read_consensus(..., max_age=)`, por defecto las 6 h de siempre.
- **`fbi/research/protocol.py`**: protocolo preregistrado **`AD-B03` (`proto-ad-b03-v1`)**, con su huella fijada en `tests/unit/test_research_protocols.py`. Es el que juzgará el sello estable antes de que el dueño firme su paso a la cifra única (sección 5).

## 4. Inventario: las cifras del núcleo y su calibración

**De dónde salían «20 de 34».** Era una muestra: las 34 selecciones del núcleo que juzgó la repetición del 10-nov con la cifra común (IA-053). 14 salieron «Calibrado» y **las 20 «Sin calibrar» lo eran todas por `needs_price`**, es decir, por la misma regla de las 6 h. No faltaba ningún calibrador.

**Inventario por mercado y modelo** (campeones vigentes en `intel.calibrators` / `intel.promotions`, leído el 16-nov):

| Mercado | Modelo | Campeón | Log loss calibrado / bruto / mercado | ECE | n fuera de muestra (días) | Sello con `seal-v1` |
| --- | --- | --- | --- | ---: | ---: | --- |
| 1X2 | elo_ologit | #733 logit2 (16-nov) | 0,5832 / 0,5916 / 0,5826 | 0,013 | 3.296 (36) | calibrada si hay precio en 4 días |
| 1X2 | dixon_coles | #730 logit2 (16-nov) | 0,5943 / 0,6088 / 0,5941 | 0,009 | 2.959 (36) | ídem |
| 1X2 | poisson | #736 logit2 (16-nov) | 0,6031 / 0,6189 / 0,6031 | 0,011 | 2.588 (35) | ídem |
| Más/menos | dixon_coles | #718 logit2 (15-nov) | 0,6222 / 0,6657 / 0,6215 | 0,007 | 14.706 (39) | ídem (todas las líneas: el calibrador es por mercado) |
| Más/menos | poisson | #721 logit2 (15-nov) | 0,6215 / 0,6651 / 0,6206 | 0,010 | 14.910 (39) | ídem |
| Ambos marcan | dixon_coles | #709 logit2 (15-nov) | 0,6841 / 0,6993 / 0,6848 | 0,010 | 1.930 (32) | ídem |
| Ambos marcan | poisson | #688 logit2 (11-nov) | 0,6826 / 0,7005 / 0,6826 | 0,015 | 1.936 (29) | ídem |
| Hándicap asiático | dixon_coles | #739 logit2 (16-nov) | 0,6135 / 0,6593 / 0,6118 | 0,012 | 14.051 (40) | fuera de la vista hoy (AD-B05) |
| Hándicap asiático | poisson | #742 logit2 (16-nov) | 0,6139 / 0,6590 / 0,6125 | 0,009 | 14.206 (40) | fuera de la vista hoy (AD-B05) |
| Doble oportunidad | dixon_coles | ninguno: el mejor ajuste no llega a la muestra (886 de 1.500) | 0,6407 / 0,6960 / 0,6410 | 0,021 | 886 (28) | `sin_calibrar` (`no_champion`) si se calibrara sola |
| Doble oportunidad | poisson | ninguno: 811 de 1.500 | 0,6367 / 0,6895 / 0,6379 | 0,020 | 811 (27) | ídem |

Ningún mercado tiene ventaja validada (`market_edge` NOT_VALIDATED en los 11). Ningún campeón le gana al mercado sin margen: es el resultado conocido.

**Lo que sigue sin calibrar y el plan de cada caso** (en el LAB, bajo el protocolo `AD-B03`; **nada se promociona sin tu firma**):

| Qué | Cuántas (7 días) | Por qué | Plan |
| --- | ---: | --- | --- |
| Cifras con campeón y precio de 6 h a 4 días | 2.018 conjuntos | La regla de las 6 h | **Resuelto en sombra** por `seal-v1`. El protocolo mide si la cifra calibrada con un precio envejecido sigue ganando al modelo sin calibrar y no pierde más de 0,005 frente a la de precio fresco. Si pasa, tú firmas su paso a la cifra única (AD-B05). |
| Cifras sin ningún precio todavía | 1.227 conjuntos | El mercado no ha abierto: un `logit2` no se puede aplicar | Quedan `sin_calibrar` (`needs_price`) con su motivo, que es la respuesta honrada. Plan: un retador `platt` sin mercado, ajustado y validado por walk-forward con `calib-gate-v1`, **solo como CHALLENGER**. |
| Doble oportunidad | — | Sin campeón (falta muestra) | Se **deriva** de la 1X2 calibrada (1X = L + E, X2 = E + V, 12 = L + V), como decidió IA-035, sin calibrador propio. Coherente por construcción con la matriz de IA-074. |
| Hándicap asiático y las demás líneas de goles | — | La vista (`MARKETS`) solo cubre 1X2, 2,5 y ambos marcan | El campeón de su mercado aplicado sobre la matriz de marcadores (IA-074), cuando la cifra única las cubra (AD-B05), evaluado con este mismo protocolo. |

## 5. El protocolo preregistrado `AD-B03` (resumen)

- **Pregunta:** ¿la cifra calibrada con un precio de más de 6 h sigue pronosticando mejor que el modelo sin calibrar y casi tan bien como la calibrada con un precio fresco?
- **Datos:** las lecturas de `forecast-v1-seal` que se escriban desde el despliegue, de partidos ya liquidados. Es fuera de muestra por construcción (el campeón se ajustó antes).
- **Métrica:** la diferencia pareada del log loss (calibrada con precio envejecido menos sin calibrar) por día, con intervalo del 95 % por bootstrap de días. Se mide en dos tramos de edad (6–24 h y 24–96 h) y en los tres mercados.
- **Pasa** si en todos los tramos y mercados el límite superior es < 0, el ECE es ≤ 0,03 y la diferencia frente al precio fresco es ≤ 0,005. **Rechaza** si falla cualquiera: ese tramo vuelve a `sin_calibrar` en la cifra única, y una ventana más corta exige un protocolo v2 registrado antes de mirar.
- **Muestra mínima:** 1.500 partidos-mercado y 5 días por tramo y mercado. Se evalúa **una sola vez**: el primer día que se llegue a esa muestra, o el 31-ene-2027.

## 6. Qué no cambia

- `forecast-v1` y todo lo que la ve: la página, el paquete y los textos de la IA, la transparencia, `decision-v2` con la cifra común y el comando `match_forecast`. Todos leen `version = 'forecast-v1'` (un test lo comprueba en cada lector que nombra la tabla).
- `decision-v1`, sus umbrales, los picks, `FBI_PICKS_SOURCE` (apagado), los calibradores y sus roles, la calibración nocturna, los modelos y su huella (`9a7bec97caec`).
- **Aviso, sin tocar:** la calibración nocturna (`run_calibration`) sigue promocionando campeones por sí sola (`decided_by = 'system'`) cuando pasan `calib-gate-v1`; así entraron los campeones de la tabla. El plan pide tu firma para cada promoción (AD-K07). Esta pieza no lo cambia: lo señalo para AD-K07.

## 7. Cómo se apaga y cómo se revierte

- **Apagar la sombra:** `FBI_FORECAST_SEAL=off` en el entorno del worker y reiniciarlo. Deja de escribirse `forecast-v1-seal`; lo escrito queda (solo añadido) y nadie lo lee.
- **Revertir:** revertir el PR. No hay migración ni datos que deshacer: las filas de `forecast-v1-seal` quedan como histórico de la sombra.

## 8. Comprobaciones tras desplegar (solo lectura)

```sql
-- la sombra se escribe y su sello no alterna (cambios de sello por mercado en las últimas 48 h)
WITH s AS (SELECT DISTINCT fixture_id, market_key, line, known_at, calibration FROM models.match_forecasts
            WHERE version = 'forecast-v1-seal' AND known_at >= now() - interval '48 hours'),
     t AS (SELECT *, lag(calibration) OVER (PARTITION BY fixture_id, market_key, line ORDER BY known_at) AS pc FROM s)
SELECT count(*) FILTER (WHERE pc IS NOT NULL AND pc <> calibration) AS cambios,
       count(*) FILTER (WHERE pc = 'CALIBRATED' AND calibration = 'UNCALIBRATED') AS de_calibrada_a_sin  -- se espera 0 salvo campeón retirado
  FROM t;
```
