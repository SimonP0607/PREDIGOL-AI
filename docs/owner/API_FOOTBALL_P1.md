# P1 · API-Football: los cuatro endpoints parciales, completados y verificados (5 oct 2026)

Mandato: completar `/venues`, `/players`, `/players/teams` y `/odds/mapping`, y verificar standings, fixtures,
equipos, jugadores, lesiones, alineaciones y cuotas con datos reales. Resultado: el contrato queda en **32 FULL,
6 COVERED, 0 PARTIAL, 0 MISSING** (`docs/owner/API_FOOTBALL_ENDPOINT_MATRIX.md`, regenerada). Código: backend
`ebdb9e2`, `382091e`, `0a97891`; frontend `a2a4b72`, `9be8559`. Migración `0065`.

## 1. Lo que cambió, endpoint por endpoint

| Endpoint | Antes | Ahora | Medido |
|---|---|---|---|
| `/odds/mapping` | se guardaba a diario; nadie lo leía | el planificador de captura lo lee como **anulación de una cobertura obsoleta** (un partido listado se pide aunque la temporada diga "sin cuotas"); estado de precio, frescura y calidad: listado = cubierto | ver §2 |
| `/venues` | solo auditorías | feed por id para los estadios de las temporadas actuales sin describir en 90 días; `core.venues.image_url`; el partido guarda el estadio **tal como lo nombra su payload** aunque no traiga id | 43 pedidos, 34 descritos; 213.541 partidos con nombre de estadio (antes 0 sin id) |
| `/players` | guardado y auditado, no se mostraba | la ficha del jugador muestra el agregado del proveedor (etiquetado, con su rating y procedencia) bajo el de PrediGol; barrido semanal con ≥ 6 días entre barridos | ver §3 |
| `/players/teams` | solo auditorías | `core.player_team_seasons` (instantánea por cambio); feed cada 60 días y al momento si cambian sus traspasos; "Trayectoria" en la ficha | primer llenado en marcha: 100 jugadores, 589 filas |

## 2. `/odds/mapping`: por qué **no** se usa para saltar partidos

La idea original (`value.py`) era pedir solo los partidos que el mapping lista. Medido el 5 oct sobre los 160
partidos seguidos de las próximas 96 h: 76 tenían precio; **10 de esos 76 no estaban en el último listado**, y
cuatro ya tenían cuotas capturadas **25–86 minutos antes** de que se leyera el listado (19:11 UTC del 4 oct). El
listado diario va por detrás de los precios: filtrar por él habría perdido esos precios para ahorrar ~43
peticiones vacías al día (0,07 % del presupuesto interno). Decisión registrada en el código
(`scripts/capture_odds.UPCOMING_SQL`) y en el contrato.

Uso real: (a) un partido listado se pide aunque la cobertura de su temporada diga "sin cuotas" (hoy 0 casos: 38
partidos en temporadas sin cuotas, ninguno listado); (b) el estado de precio y la frescura de cuotas dejan de decir
"no cubierto" de un partido listado; (c) calidad: "listado y sin precio" es nuestro, "nunca listado" es del proveedor.

Arreglos hallados al conectarlo:

* **Barridos paginados truncados en silencio**: todo feed paginado paraba en 30 páginas; el mapping tenía 29. Ahora
  cada feed tiene su tope (mapping 200) y un barrido cortado queda como error en su comprobación y en la ejecución.
* **"Último pedido" leído solo del índice RAW** (4 lugares: estado de precio, frescura de cuotas, cobertura,
  calidad). El índice guarda una vez una respuesta idéntica, así que un partido sin cuotas preguntado varias veces
  parecía "no preguntado" (y se contaba como fallo nuestro). Ahora se lee también `market.odds_asks`.

## 3. `/players`: el barrido semanal, verificado

El barrido `w202641` escribió 0 filas. Comprobado contra RAW: de 3.200 páginas, **3.192 idénticas byte a byte** al
barrido anterior y las 8 restantes solo cambiaban el bloque de nacimiento de un jugador (dato de perfil, no de
temporada) — 0 filas es correcto. La causa del gasto: la semana ISO permitió dos barridos **separados 7 horas**
(domingo 18:46–21:46 y lunes 01:50–04:46 UTC): 3.200 peticiones sin información nueva. Arreglo: una temporada no se
vuelve a barrer antes de 6 días.

## 4. Errores de PrediGol encontrados y corregidos (con respaldo previo)

| Hallazgo | Alcance | Corrección | Traza |
|---|---|---|---|
| El id de estadio **0** ("sin id" del proveedor) se tomaba como un estadio | 1.046 partidos de **154 estadios distintos** apuntaban a una sola fila; un partido de Bundesliga se mostraba en "Estadio Banorte, Mexico City" | los parsers descartan el 0; los partidos dejan de apuntar a esa fila (la fila se conserva) | 1.046 filas en `audit.data_repairs` (`venue_id_zero`) |
| Un bloque de estadio de un partido **renombraba** el estadio | el último nombre de partido sobrescribía el oficial (p. ej. un Milan–Como jugado en Perth trae el id de San Siro y dice "Optus Stadium") | `ensure_venues` nunca cambia un estadio conocido; 364 nombres y 307 ciudades restaurados desde el payload que describió cada estadio (verificado por hash) | 671 filas `venue_name_from_source` |
| La cabecera del partido confiaba en el id | — | muestra el estadio que nombra el payload del partido; los detalles (aforo, superficie) solo si el id apunta a ese mismo estadio (por palabras distintivas, sin adivinar renombres) | tests `test_same_place.py` |
| Auditoría de cuotas: falso HIGH | 280 precios "distintos" en un partido | el proveedor sirvió a las 12:49 una respuesta sellada 08:14 aunque su dato ya era de 12:17 (caché); ahora se compara el sello de la respuesta capturada, no la hora de captura | test en `test_truth_compare.py` |

Respaldos antes de tocar datos: `PRE_P1_ENDPOINTS_20261005` (dump 602,8 MB verificado, RAW 851 MB, etiquetas,
instantánea de 113 tablas) y `PRE_VENUE_REPAIR_20261005` (dump 604,7 MB). Relleno de estadios: ejecución 9699,
0 peticiones, 2.703 payloads verificados, 213.541 filas (solo las columnas nuevas).

## 5. Verificación con datos reales (auditoría de verdad nº 7, 15:19 UTC, 371 peticiones, 0 fallos)

| Área | Comprobado | Coincide | Hallazgos | Lectura |
|---|---:|---:|---|---|
| Competiciones | 124 | 124 | — | |
| Fixtures (36.095 en 144 temporadas) | 261.927 campos | 261.912 | **12 altos**, 6 bajos, 2 info | 12 partidos de Segunda División cuyo horario cambió el proveedor **después** de nuestra lectura de las 11:18 (sincronización cada 6 h) — ver §6 |
| Resultados | 442.490 | 442.483 | 24 medios | 23 contradicciones/incoherencias del propio proveedor (sin resultado por diseño); 1 descanso pendiente |
| Standings | 2.514 | 2.502 | 3 medios, 64 bajos | Serie B: puntos/puesto de Juve Stabia y Catanzaro (cambio posterior del proveedor) |
| Equipos | 8.213 | 8.212 | 1 bajo | |
| Jugadores | 68.482 | 46.301 | 2 medios, 10 bajos | 22.000 jugadores de alineaciones sin fecha de nacimiento/nacionalidad: perfil no servido aún |
| Lesiones | 19 | 19 | — | |
| Alineaciones | 105 | 82 | 24 medios, 17 bajos | verificado contra RAW: **48** jugadores que en nuestra lectura venían **sin id** y el proveedor identificó después, 5 cambios del proveedor, **0** pérdidas nuestras |
| Cuotas | 342 | 331 | 1 alto, 1 medio, 22 bajos | el alto era el falso positivo de §4 (ya corregido) |
| Eventos / estadísticas | 78 / 120 partidos | 44 / 83 | medios | para P2 |
| Elo | 209.997 | 209.997 | — | |

## 6. Pendiente de confirmar en esta fase

* Los 12 altos de Segunda División: sincronización manual de fixtures lanzada a las 15:34 UTC (≈102 peticiones);
  se re-verifican al terminar.
* `/odds/mapping` con el nuevo tope: el barrido diario toca ~18:11 UTC.
* `/players/teams`: primer llenado ~30.756 peticiones a ≤100 por ejecución (≈6–7 días), sin tocar la reserva en vivo.

## 7. Incidente operativo

El equipo se reinició a las 14:41 UTC. Docker Desktop 4.89 no arrancaba: no podía renombrar los sockets que dejó la
sesión anterior ("The file cannot be accessed by the system") y cada intento fallido dejaba otros nuevos. Se
borraron solo esos sockets de ejecución (Docker los recrea; contenedores, imágenes y volúmenes intactos) y se
levantó la pila con `scripts/dev-up`: base de datos, API, worker y web en marcha a las 15:03 UTC (22 min sin
captura). El diálogo de Docker ofrecía "Reset to factory defaults": **no se usó** (habría borrado la base de datos).
