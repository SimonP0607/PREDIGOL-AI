# Cuotas en vivo: qué capturamos, quién las usa y cuánto cuestan (6 oct 2026)

Medido el 6 oct 2026 sobre la base del portátil, en solo lectura y sin ninguna petición al proveedor. La captura en vivo
está activa desde el 1 oct 2026 a las 01:38 UTC. **No se ha cambiado ni borrado nada.** Qué hacer con la captura es
decisión del dueño.

## 1. Qué se captura por partido

| Qué | Medido (94 partidos observados de principio a fin, 1–6 oct) |
|---|---|
| Consultas a `/odds/live` | Una cada 30 s, porque el proveedor refresca cada ~31 s. Una sola llamada trae todos los partidos en juego del mundo, y se guardan solo los que seguimos. |
| Capturas por partido | ~231 lecturas en ~119 min observados; en ~198 de ellas cambia al menos un precio |
| Precios leídos en cada captura | ~611 combinaciones de mercado, selección y línea, repartidas en ~66 mercados |
| Filas guardadas (solo los cambios) | **15.851 por partido** (mediana 15.804, p90 22.455, máximo 35.937): ~11 % de lo leído |
| Por tipo de competición | liga 15.481 · copas y selecciones 20.281 (Liga de Naciones 25.940) · amistosos 11.398 |
| Tamaño | 306 B por fila en PostgreSQL con sus 4 índices, o sea **4,86 MB por partido**; más 1,25 MB de RAW en gzip y 49 KB de estados |
| Partidos con cuotas en vivo | 65 % de los seguidos: ligas 78 %, amistosos 36 %, copas y selecciones 81 % (135 partidos con el worker encendido) |

Aparte de las cuotas está el seguimiento del partido: marcador, minuto y eventos, que se consultan en `/fixtures` cada
60 s. Guarda ~19 filas de estado y ~0,17 MB de RAW por partido. Es pequeño y es lo que cierra los resultados rápido.

## 2. Qué mercados

Se guardan **145 mercados distintos**; el catálogo en vivo del proveedor tiene 266. Solo 5 están mapeados a un mercado
nuestro:

| Mercado mapeado | % de las filas |
|---|---:|
| Más/Menos (OU) | 6,10 |
| Hándicap asiático (AH) | 5,68 |
| 1X2 | 1,12 |
| Doble oportunidad (DC) | 0,80 |
| Ambos marcan (BTTS) | 0,62 |
| **Los 5 juntos** | **14,3** |
| Solo la línea principal de los 5 | 2,7 |

El **85,7 %** restante son mercados que ningún modelo usa:

* córners (Match Corners 6,6 %, Asian Corners, Total Corners, "carrera al córner N");
* marcador exacto (5,8 %);
* hándicap a 3 vías (4,2 %);
* goles del partido;
* goleadores ("anytime" 3,3 %, goleador 3,1 %, 2 o más goles 2,7 %);
* mercados de jugador (tiros, asistencias, tarjetas);
* intervalos ("próximos 10 minutos");
* mercados de cada mitad.

## 3. Quién usa estos datos

**Ningún modelo.** La captura en vivo es un circuito separado por diseño: `LiveCaptureService` solo puede escribir
`market.live_odds_snapshots` y `market.live_fixture_states`, y `tests/unit/test_live_prematch_separation.py` lo
vigila.

Solo leen cuotas pre-partido (`odds_snapshots`, `final_prematch_odds`, `historical_odds`, `market_consensus`):

* las features, los modelos y el backtest;
* el consenso de mercado;
* la auditoría de picks, cuyo precio de cierre es el último consenso antes del inicio;
* la regla MODEL_READY;
* la puerta de datos (`truth/gate.py`), donde el dataset `live` figura como NOT_USED.

Sí las leen:

* la página **En vivo** y la portada (1X2 y Más/Menos, línea principal, últimos 30 min);
* el panel en vivo del **Centro de partido** (últimas cotizaciones de todos los mercados y movimientos de los 5
  mapeados);
* los contadores de frescura del admin y de la auditoría de verdad.

Detalle medido: `/odds/live` a veces lista un partido unos minutos antes del inicio. Pasó en 83 de 152 partidos; la
mediana fue 4 min antes. Para picks pre-partido no hace falta, porque el cierre ya sale del consenso pre-partido.

## 4. Qué ligas usan los modelos y por qué

La evaluación contra el mercado (estudio V2, `scripts/research_v2.py`) usa las ligas domésticas cuyas temporadas de
validación (2023) **y** de prueba (2024) son MODEL_READY. Hoy son cinco: **Premier League, LaLiga, Serie A,
Bundesliga y Ligue 1**. No se eligieron a mano: las selecciona `research/loop.py::model_ready` con la clasificación de
`validation/historical.py`.

MODEL_READY exige, a la vez:

* resultados ≥ 95 %;
* integridad ≥ 98 %;
* **precio de mercado ≥ 60 %**;
* Elo ≥ 95 %;
* al menos 50 partidos.

Pasan 16 temporadas: esas 5 ligas de 2022 a 2024 y la Liga de Naciones de la UEFA 2026. De las 942 temporadas
PARTIAL, **912 fallan solo por "precios 0 %"**. API-Football guarda las cuotas pre-partido 7 días, y los precios
históricos que tenemos vienen de Football-Data.co.uk (5.329 partidos de esas 5 ligas). Sin precios no se puede
demostrar que un modelo le gana al mercado, y esa es la condición para publicar. Un modelo puede aprender de una
temporada PARTIAL, pero no puede ser juzgado en ella.

Las temporadas actuales irán cruzando el 60 % con nuestra propia captura pre-partido (desde el 25 sep). Proyección con
el calendario real, suponiendo un servidor 24/7 que pone precio al ~95 % de los partidos. Con el worker encendido se
midió 93 % en ligas: 81 de 87 partidos, y 81 de los 83 que el proveedor lista con cuotas.

| Mes estimado en que pasa a MODEL_READY | Temporadas actuales | De ellas, ligas domésticas |
|---|---:|---:|
| oct 2026 | 1 | 0 |
| nov 2026 | 5 | 4 |
| dic 2026 | 14 | 14 |
| ene 2027 | 15 | 15 |
| feb 2027 | 6 | 6 |
| mar 2027 | 4 | 4 |
| abr 2027 | 2 | 2 |
| No llega esta temporada: demasiado jugado sin precio (p. ej. Argentina, MLS, Colombia, Brasil Serie A); llegará con la siguiente | 33 | 26 |
| Sin cobertura de cuotas en el proveedor | 53 | 10 |

Con la captura tal como fue (máquina apagada a ratos), solo 21 de esas 47 llegarían en esas fechas. Por eso importa el
24/7. Otra vía es importar más CSV históricos de Football-Data.co.uk (segundas divisiones y otras ligas), que pondría
más temporadas pasadas en MODEL_READY. Descargarlos necesita permiso del dueño.

## 5. Crecimiento del disco

Método: el calendario real de las 133 competiciones seguidas en los últimos 365 días (34.059 partidos, del 7 oct 2025
al 6 oct 2026), repetido desde hoy con los días de la semana alineados, y los parámetros medidos arriba.

Supuestos:

* 12 GB de sistema, Docker, logs y swap;
* 1 GB de WAL;
* un volcado local;
* el RAW en el mismo disco;
* el resto del crecimiento por partido según `STORAGE_FORECAST.md`;
* +50 ligas = +37,4 partidos al día (informe de capacidad) con el mismo reparto.

En "copas y selecciones" se usa la media general (65 %, 15.851 filas), porque su muestra la dominan 12 partidos de la
Liga de Naciones.

| Por año, 133 ligas | GB |
|---|---:|
| Cuotas en vivo: 318 M filas en PostgreSQL | 97,4 |
| Cuotas en vivo: RAW de `/odds/live` | 25,0 |
| Cuotas en vivo: estados | 1,0 |
| **Total cuotas en vivo** (≈ 72 % de todo el crecimiento) | **≈ 125** |
| Todo lo demás de PrediGol | ≈ 48 |

Efecto fin de semana: un sábado medio añade **1,19 GB** con cuotas en vivo y 0,32 GB sin ellas. De martes a jueves,
0,25 GB. El día más pesado del calendario llega a 2,24 GB.

Fecha en que se llega a cada tamaño de disco. 90 GB es el 90 % de un VPS de 100 GB; 180 GB, el de uno de 200 GB:

| Escenario | 133 ligas: 90 GB | 133 ligas: 180 GB | 133 ligas: disco a 12 meses | 183 ligas: 90 GB | 183 ligas: 180 GB | 183 ligas: disco a 12 meses |
|---|---|---|---:|---|---|---:|
| Como hoy: todos los mercados | 20 feb 2027 | 3 sep 2027 | 199 GB | 18 ene 2027 | 9 may 2027 | 269 GB |
| Como hoy con retención de 90 días a Parquet | 4 abr 2027 | 1 may 2028 | 130 GB | 7 feb 2027 | 25 oct 2027 | 172 GB |
| Solo los 5 mercados mapeados | 16 jul 2027 | 20 jul 2028 | 114 GB | 10 abr 2027 | 16 ene 2028 | 149 GB |
| Solo la línea principal de los 5 | 19 ago 2027 | oct 2028 | 102 GB | 5 may 2027 | 12 mar 2028 | 133 GB |
| Lo anterior, con el RAW en vivo fuera del VPS (R2) | 20 ene 2028 | 30 sep 2029 | 77 GB | 31 ago 2027 | 26 nov 2028 | 98 GB |
| **Sin cuotas en vivo** | **14 feb 2028** | más de 3 años | **73 GB** | 19 sep 2027 | 2 feb 2029 | 92 GB |

En las opciones de 5 mercados el RAW sigue guardando la respuesta completa del proveedor, porque es la evidencia;
por eso pesa lo mismo que hoy si se queda en el VPS.

## 6. Dinero

En un VPS de 100 GB al que se le sube el plan al llegar al 90 %: OVH VPS-3 (100 GB) cuesta €10,40/mes y VPS-4 (200 GB)
€19,96/mes. Son precios de 12 meses, sin IVA, leídos el 6 oct. OVH no tiene VPS de más de 200 GB.

| Ahorro de no capturar cuotas en vivo | 133 ligas | 183 ligas | 233 ligas |
|---|---:|---:|---:|
| Año 1 en OVH: con todo el VPS-4 hace falta desde feb 2027; sin cuotas en vivo, el VPS-3 basta el año | **€76,48 (≈ $86)** | €76,48 | €66,92 |
| Año 1, pagando por GB (volumen Hetzner €0,044/GB-mes por encima de 100 GB) | €14 | €30 | €46 |
| Año 2, pagando por GB (con todo ya no cabe en ningún VPS de OVH) | €95 | €139 | €179 |
| Año 1 / año 2 si la base estuviera en AWS RDS gp3 de una zona | $67 / $203 | $94 / $284 | $121 / $366 |
| Año 1 / año 2 en RDS Multi-AZ | $134 / $406 | $188 / $569 | $242 / $731 |
| Copias externas en R2 (RAW + 17 volcados), año 1 / año 2 | $6 / $19 | $9 / $26 | $11 / $34 |

Además, las cuotas en vivo son ~2.200–2.900 llamadas al día, alrededor del 30 % del consumo recurrente. En Ultra no
cuestan nada extra. Cuando termine la carga histórica podrían ser lo que impida bajar a Pro ($19, 7.500 al día; hoy
pagamos Ultra, $29): ~$120 al año. Habría que verificarlo entonces.

**Lectura:** en un VPS el ahorro en dinero es modesto, unos $86 el primer año. Lo que de verdad cambia es lo
operativo:

* con cuotas en vivo, el VPS de 100 GB se llena en ~4,5 meses;
* el de 200 GB, que es el mayor de OVH, se llena en 11 meses (7 con +50 ligas);
* las copias y restauraciones pasan a mover ~100 GB más de tabla e índices al año.

## 7. Opciones (decide el dueño)

| Opción | Disco al año (133 ligas) | Qué se pierde |
|---|---:|---|
| A. Dejar de capturar cuotas en vivo | 0 | Los precios en vivo de la página En vivo y del Centro de partido; el marcador y los eventos siguen |
| B. Guardar solo la línea principal de 1X2, OU, AH, DC y BTTS, con el RAW en vivo en R2 | ~4 GB en el VPS + ~25 GB en R2 (≈ $0,40 al mes) | Los otros 140 mercados en vivo, que no usa nadie |
| C. Guardar todo y activar la retención diseñada (90 días en PostgreSQL y luego Parquet), con el RAW en R2 | 27–30 GB fijos en PostgreSQL (38–42 GB con +50 ligas) + ~2,6 GB al año de Parquet | Nada; deja abierta una futura investigación en vivo |
| D. Seguir como hoy | ~125 GB | — |

Recomendación técnica para un producto de picks pre-partido: **B**, o **A** si la página En vivo puede quedarse sin
cuotas. B y A necesitan un cambio pequeño de código: un interruptor y un filtro de mercados para la captura en vivo,
con sus tests. Lo ya capturado (1,82 M filas, 0,53 GB) se conserva: no se borra nada sin autorización.

## 8. Lo que corrige

`STORAGE_FORECAST.md` (5 oct) estimaba 147 MB/día de precios en vivo, con 43 % de partidos con cuotas en vivo y 13.727
filas por partido. Esa muestra tenía días con el worker apagado. Con partidos completos y horas con el worker
encendido salen 65 %, 15.851 filas y 306 B/fila: **~270 MB/día de media en PostgreSQL más ~70 MB/día de RAW**.

`DEPLOYMENT_COSTS.md` proponía como MVP el VPS-2 de 75 GB. Con la captura en vivo actual llegaría al 90 % el 9 ene
2027; sin cuotas en vivo, el 28 ago 2027.

## 9. Cómo se midió

Consultas de solo lectura sobre:

* `market.live_odds_snapshots`: filas, mercados, partidos, elapsed y status;
* `market.live_fixture_states`: lecturas por partido;
* `raw.ingestion_payloads` con el ledger: bytes por trabajo y por día;
* los tamaños de las particiones (`pg_total_relation_size`);
* un `COPY` de un día de cuotas en vivo comprimido con zlib-6 (el formato de `pg_dump -Fc`): 8,1 B por fila;
* `analytics.competition_data_scores`;
* el calendario de `core.fixtures`.

El modelo día a día es un script de la sesión; sus parámetros son los de esta página.
