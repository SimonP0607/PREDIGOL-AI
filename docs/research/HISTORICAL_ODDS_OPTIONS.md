# Cuotas históricas — opciones para el backtest económico (P3)

**Fecha:** 2026-09-06 · **Estado:** análisis para decisión · **Decide:** el propietario
**Contexto:** API-Football conserva 7 días de `/odds` y 0 días de `/odds/live`. Sin una
fuente externa, el primer backtest económico serio con captura propia llega en 6–9 meses.

Lo que se ha podido verificar en fuentes públicas está marcado como **[verificado]**; lo que
requiere iniciar sesión, pagar o ejecutar JavaScript está marcado como **[no verificable aquí]**
y se dice cuál sería la comprobación. **Nada de esto se ha contratado ni descargado.**

---

## 0. Qué necesita el backtest, exactamente

| Requisito | Por qué |
|---|---|
| Precio **con timestamp** antes del saque | sin él no hay serie temporal ni corte point-in-time |
| Un precio **cerca del cierre** identificable | para medir valor de línea; sin él sólo hay accuracy |
| Varias casas o un exchange líquido | para desvigar y para no medir contra una sola casa |
| 1X2 como mínimo; OU 2.5 y BTTS deseables | son los tres mercados del legacy y del dominio V2 |
| ≥ 3 temporadas de las 9 ligas objetivo | para walk-forward con varias ventanas |
| Formato documentado y licencia que permita uso privado | reproducibilidad y legalidad |

---

## 1. Betfair Exchange Historical Data

**Qué es.** El histórico del Stream API del exchange, empaquetado en TAR de JSON comprimido
(`.bz2`), un fichero por mercado, con mensajes `mcm` ordenados en el tiempo
(`pt` epoch ms, `marketDefinition`, `rc` con `ltp`/`tv`/`batb`/`batl`, `inPlay`).
**[verificado]** en la guía de Betfair Data Scientists y en la especificación pública.

| Criterio | Hallazgo |
|---|---|
| Coverage / fútbol | **[verificado]** El hub de Betfair AU lista "soccer" entre los deportes del histórico. |
| Mercados | Los que cotiza el exchange: Match Odds (1X2), Over/Under, Correct Score, BTTS… **[no verificable aquí]** cuáles vienen en cada paquete de soccer sin abrir un TAR. |
| Casas / exchange | Es **un exchange**, no una casa: precios de intercambio con margen ≈ 0 y comisión aparte. No compara directo con cuotas de bookmaker; hay que traducir (precio exchange ≈ probabilidad justa + comisión). |
| Granularidad | **[verificado]** BASIC: intervalos de **1 minuto**, sólo `ltp`, **sin volumen**. ADVANCED: **1 segundo**, ladder top-3, con volumen. PRO: ticks de **50 ms**, ladder completo, volumen. |
| Volumen / liquidez | Sólo en ADVANCED y PRO. En BASIC **no hay volumen**: no se puede saber si un `ltp` es líquido o un trade suelto. |
| Profundidad histórica | **[verificado]** "desde 2016" (nuevo Stream API); datos previos por otras vías. |
| Formato | JSON por línea dentro de `.bz2` dentro de `.tar`; parsers open source (`betfair_data`, `betfairlightweight`). |
| Coste | **[verificado]** BASIC es gratuito (hay que "comprar" el periodo a 0). ADVANCED/PRO son de pago por deporte y mes; **la cifra sólo se ve con sesión iniciada en historicdata.betfair.com** (la web exige JavaScript). |
| Licencia | **[no verificable aquí]** — los T&C están detrás del login. Comprobar antes de descargar: uso no comercial, prohibición de redistribución. |
| Idoneidad para backtest | **Alta para línea de cierre y evolución pre-partido** si el mercado tiene liquidez (grandes ligas sí; ligas menores, dudoso). Pre-partido a 1 min es más que suficiente para nuestra cadencia de 6 ventanas. |
| Dificultad de integración | Media: parser, mapeo de eventos Betfair → fixtures API-Football (nombres, no ids), traducción exchange → bookmaker. |

**Lo que hay que comprobar antes de decidir (coste 0, sin descargar gigas):**
1. Con una cuenta, "comprar" **un solo mes BASIC de soccer** (gratis) y abrir el TAR: ¿vienen las 9 ligas? ¿Match Odds y Over/Under 2.5? ¿cuánto pesa un mes?
2. Ver en la misma pantalla el **precio real** de ADVANCED para soccer.
3. Leer los T&C del portal.

**Riesgo específico:** el exchange es una fuente distinta de la que capturamos (bookmakers vía
API-Football). Un backtest sobre Betfair mide "¿habría batido al exchange?", no "¿habría batido a
Bet365?". Es una pregunta válida y más exigente, pero es otra pregunta.

---

## 2. Football-Data.co.uk

**Qué es.** CSV por liga y temporada con resultados y cuotas de varias casas, gratuito.

| Criterio | Hallazgo |
|---|---|
| Coverage / fútbol | **[verificado]** 22+ ligas europeas; las 9 objetivo están (E0, SP1, I1, D1, F1, N1, P1, B1; la Champions no). Resultados desde los 90; cuotas desde ~2000. |
| Mercados | **[verificado]** 1X2, Over/Under 2.5, hándicap asiático. **No** BTTS. |
| Casas | **[verificado]** Bet365, Pinnacle (`PS*`), William Hill, Bwin, Interwetten, VC/Bet Victor…, más `Max`/`Avg` de agregador. |
| Granularidad | **Un snapshot por partido** (recogido "viernes tarde para el fin de semana, martes para entre semana") y, en temporadas recientes, **columnas de cierre** (`*C`, p. ej. `PSCH`/`B365CH`). **[no verificable aquí]** la temporada exacta desde la que existen las columnas de cierre: el `notes.txt` actual del sitio lo indica (el sitio devolvió 503 al consultarlo). |
| Timestamps | **No hay timestamp** por cuota. Sabes que es "de apertura" o "de cierre", no cuándo. |
| Volumen | No aplica. |
| Formato | CSV plano. Trivial. |
| Coste | Gratuito. |
| Licencia | Uso personal; no hay licencia formal publicada. Sin redistribución. |
| Idoneidad para backtest | **Alta para un backtest de cierre** (Pinnacle closing es la referencia estándar del sector). **Nula para evolución temporal**: no sirve para simular nuestras ventanas T−72h…T−3h. |
| Dificultad | Baja: mapeo de nombres de equipo → `core.teams` es lo único laborioso. |

---

## 3. The Odds API — histórico

**Qué es.** Snapshots del agregador de cuotas de bookmakers, por API, con histórico.

| Criterio | Hallazgo |
|---|---|
| Coverage / fútbol | Ligas principales; **[no verificable aquí]** la lista exacta de ligas con histórico. Un mercado/casa sólo tiene histórico desde que se añadió al API en vivo. |
| Mercados | h2h (1X2), totals (OU), spreads. **No** BTTS en general. |
| Casas | Bookmakers por región (UK/EU/US/AU); Pinnacle incluido en EU. |
| Granularidad | **[verificado]** snapshots cada **10 min desde 2020-06-06**, cada **5 min desde 2022-09**. Con timestamp real. |
| Profundidad | 2020-06 → hoy. ~6 temporadas. |
| Formato | JSON por API; cada snapshot histórico cuesta **10× créditos × mercados × regiones**. |
| Coste | **[verificado]** planes con histórico: **$30/mes (20k créditos)**, **$59 (100k)**, **$119 (5M)**, **$249 (15M)**. |
| Estimación para nosotros | Reconstruir 6 ventanas × 1 mercado × 1 región = 60 créditos por partido. 9 ligas × ~340 partidos/temporada × 3 temporadas ≈ 9.200 partidos ≈ **550k créditos** → el plan de $119 durante un mes, o $59 durante seis. |
| Licencia | Comercial estándar de API; uso interno permitido. |
| Idoneidad | **Alta para reproducir nuestra cadencia** sobre bookmakers reales con timestamps. Es lo más parecido a lo que capturamos nosotros. |
| Dificultad | Baja–media: mismo tipo de payload que ya normalizamos; mapeo de ids de partido por nombre+fecha. |

---

## 4. Otros

| Fuente | Veredicto corto |
|---|---|
| **OddsPortal** (scraping) | Cobertura enorme y cuotas de apertura/cierre por casa, pero **sin API y con ToS que prohíben el scraping**. Descartado por licencia. |
| **Sportmonks Premium Odds** | Feed de pago orientado a *live/prematch actual*; el histórico es limitado y el precio es de nivel empresa. No aporta sobre The Odds API para este caso. |
| **Kaggle / mirrors** | Reempaquetados de football-data.co.uk. Misma información, licencia peor definida. |
| **Captura propia** (ya construida) | Coste 0, timestamps exactos, **exactamente** las casas y ventanas que operaremos. Única fuente que mide lo que el sistema hará en producción. Desventaja: 6–9 meses hasta tener 3 temporadas… y nunca las tendrá de años pasados. |

---

## 5. Recomendación provisional

```
HÍBRIDO, en este orden y con esta condición:

1. Captura propia — ya en marcha. Es la única verdad sobre lo que operaremos. No se negocia.
2. Football-Data.co.uk (gratis) — HOY: backtest de LÍNEA DE CIERRE sobre 3+ temporadas de las 8
   ligas domésticas con Pinnacle closing. Responde "¿el modelo bate al cierre?" en días, no meses.
   No responde nada sobre evolución temporal.
3. The Odds API ($59–119, uno o pocos meses) — SI el punto 2 muestra señal: reconstruir nuestras
   6 ventanas sobre bookmakers reales desde 2020 y validar la cadencia y el edge por ventana.
4. Betfair BASIC (gratis) — como fuente de VALIDACIÓN de "cierre": comparar nuestro
   near_close_snapshot (T−12 min) con el ltp del exchange a T−0 en los mismos partidos, y
   sólo entonces poner is_validated_close = true con close_validation_method = 'betfair_ltp_t0'.
   ADVANCED/PRO no hacen falta para eso.
```

**Por qué no "Betfair = nuestro histórico":** es gratuito, sí, pero (a) BASIC no trae volumen y
un `ltp` sin volumen en una liga menor puede ser un trade de 2 €; (b) es un exchange, no un
bookmaker: mide otra cosa; (c) el precio de ADVANCED y la licencia no se pueden ver sin login.
Sirve, y mucho, **para validar el cierre**, que es justo el hueco que tenemos. No para
sustituir a la captura.

**Por qué The Odds API antes que Betfair ADVANCED:** timestamps reales, bookmakers reales, misma
forma de dato que ya normalizamos, y el coste está publicado y acotado.

**Decisiones que son tuyas (implican gasto o cuenta):** abrir cuenta en Betfair para el BASIC
gratuito; contratar The Odds API cuando el backtest de cierre lo justifique. Ninguna de las dos
se ha hecho.

---

## Fuentes

- Betfair Data Scientists — [Historic Data Site](https://betfair-datascientists.github.io/data/usingHistoricDataSite/)
- Betfair Developer Program — [What data is provided by the Historical Data service?](https://support.developer.betfair.com/hc/en-us/articles/360002407732-What-data-is-provided-by-the-Historical-Data-service)
- Betfair Hub AU — [Historical data sources](https://www.betfair.com.au/hub/education/how-to-model/historical-data-sources/)
- Harry — [Betfair Historical Tar Files and How to Analyze Them](https://medium.com/@harryh359/betfair-historical-tar-files-and-how-to-analyze-them-1db6f23bff2b)
- The Odds API — [Historical odds (guide v4)](https://the-odds-api.com/liveapi/guides/v4/#historical-odds) · [Pricing](https://the-odds-api.com/)
- Football-Data.co.uk — [notes.txt (copia en GitHub)](https://github.com/kokosing/autobet/blob/master/data/www.football-data.co.uk/notes.txt) · [Data](https://www.football-data.co.uk/data.php)
