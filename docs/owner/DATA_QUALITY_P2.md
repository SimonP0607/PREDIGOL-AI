# P2 · Calidad de datos: 0 críticos/altos, datasets actuales y trazables (5 oct 2026)

Mandato: dejar **0 errores críticos/altos**, datasets **actuales y trazables**, y no entrenar con datos dudosos.
Código: backend `b7168d3`, `7c04c9c` (be-93) y `2739b21`, `8bf1409`, `a518a27`, `c7a1bd9`, `9d1214f`, `629dad7`,
`616e6a3`, `6143d19` (0066), `e9741e7` (be-94..100). Tests: 1.623 en verde (18 nuevos en esta fase).

**Resultado medido (5 oct, 16:39 UTC):**

* Libro de evidencias: **0 críticos y 0 altos** abiertos o vigilados (de 1 OPEN alto + 3 MONITOR altos al empezar).
* Auditorías de verdad nº 8 y nº 9 (374 peticiones cada una, 0 fallos, muestras distintas): **0 críticos, 0 altos**
  en las 16 áreas.
* Registro de datasets: **14/14 FRESH** (al empezar: 2 INCOMPLETE y 1 STALE).
* Linaje: **0 filas sin payload** en las 10 tablas que leen modelos y páginas (antes 15.385 filas de tablas).
* `DATASET_V2` reconstruido: **VALIDATED** (todas las puertas en *pass* o *note*). No es MODEL_READY: promoverlo y
  descongelar la investigación son decisiones del dueño. Ningún modelo puede entrenar hasta entonces (lo impone el
  código: `require_model_ready`).

## 1. El libro de evidencias: de dónde salen los "0 altos"

| Estado / severidad | Inicio de P2 (5 oct, ~15:20 UTC) | Ahora |
|---|---:|---:|
| OPEN crítico | 0 | 0 |
| OPEN alto | 1 (E-792) | **0** |
| MONITOR alto | 3 (E-1248..E-1250) | **0** |
| OPEN medio | 10 | 11 |
| OPEN bajo / info | 93 / 1 | 93 / 1 |

Ningún alto se cerró cambiando un umbral para que pase. Los cuatro cambiaron de severidad porque la regla que los
clasificaba medía mal el **impacto** (código `b7168d3`, con tests), y cada uno queda abierto o vigilado con su
evidencia:

* **E-792** (Ligue 1 2025, tabla final 16/18): nuestros 308 partidos, 307 resultados y los 306 de Football-Data
  coinciden al 100 %. La diferencia es la tabla **del proveedor**, que no cuenta el partido 1388000 (abandonado y
  homologado 0-0 por la LFP el 28 may 2026; decisión oficial registrada). Un hueco solo del proveedor, con el resto de
  comprobaciones ≥ 99,5 %, es **medio**, no alto. Sigue OPEN.
* **E-1248..E-1250** (RAW): los mismos 3 ficheros dañados del 4 oct (escritos antes del arreglo del almacén, ningún
  modelo los lee); las verificaciones completas de las 15:42 (45.396 payloads) y las 16:37 (56.126) no encontraron
  ninguno nuevo. Pasan a **bajo/MONITOR**.
  El RAW no se repara nunca: se documenta.
* Auditoría de cuotas: el "alto" de la ronda 7 era un falso positivo de la auditoría (comparaba la hora de captura,
  no el sello de la respuesta en caché del proveedor). Corregido en P1.

## 2. Auditorías re-ejecutadas con datos reales

| Auditoría (5 oct) | Peticiones | Resultado |
|---|---:|---|
| Validación *golden* (7 competiciones × 3 temporadas, decisiones oficiales) | 42 | **20/21 GOLDEN_VALIDATED**. Ligue 1 2025 NEEDS_REVIEW: tabla final del proveedor 16/18 (no cuenta el 0-0 homologado de 1388000); nuestros partidos, resultados y Football-Data al 100 % |
| Integridad RAW (todo el almacén, re-hash) | 0 | 56.126 payloads, **3 dañados** (los mismos del 4 oct: 2 vacíos `/odds/live`, 1 ausente `/fixtures`), 0 nuevos |
| Auditoría de verdad nº 8 (proveedor contra base de datos, todas las áreas) | 374 | **0 críticos, 0 altos**. Competiciones 124/124; fixtures 261.667/261.671; resultados 442.230/442.236; tablas 2.502/2.514; equipos 8.212/8.213; lesiones 21/21; Elo 210.000/210.000; cuotas 335/345 (17 precios que el proveedor publicó después de nuestra última captura, 3 movidos). Los medios se explican en §6 |
| Auditoría de verdad nº 9 (otra muestra, tras `9d1214f` y `616e6a3`, 16:50 UTC) | 374 | **0 críticos, 0 altos**. Jugadores 68.461/68.483 (el hueco del proveedor ya no cuenta como nuestro); eventos 51/80 con 10 medios y 35 bajos (las sustituciones renumeradas ya cuentan como bajo); estadísticas de equipo 102/120 y alineaciones 83/104 con revisiones del proveedor posteriores a nuestra lectura (ver §6) |

## 3. Errores de PrediGol encontrados y corregidos en P2 (con respaldo previo)

| Hallazgo | Alcance | Corrección | Traza |
|---|---|---|---|
| **Tablas sin linaje**: `core.standings.payload_hash` llegó con la revisión 0048; lo escrito antes no nombraba su payload | 15.385 filas en 840 instantáneas (77 % de la tabla) | cada instantánea se compara, valor a valor, con el `/standings` de su liga y temporada leído en su mismo instante (786) o el anterior más reciente (54), verificado contra su hash; solo entonces se escribe el hash. **840/840 trazadas**; 17 instantáneas antiguas eran subconjuntos de su payload (515 filas que el escritor anterior descartó: una fila por equipo) — **completadas** después desde ese mismo payload (17 filas `standings_dropped_tables`, la regla de `refresh_tables --legacy`; respaldo `PRE_STANDINGS_COMPLETE_20261005`; nada actualizado ni borrado) | 840 filas `standings_lineage` en `audit.data_repairs`; respaldo `PRE_STANDINGS_LINEAGE_20261005` |
| **Un partido que el proveedor cambia de competición no se movía** (la actualización nunca tocaba `competition_season_id`) | latente; 1 caso real (E-466: Panamá–Nueva Zelanda pasó de Amistosos a la Kirin Cup) | sigue al proveedor entre temporadas seguidas (`fixture_competition` en `audit.data_repairs`); si la nueva competición no se sigue, la fila se queda y se marca (`STALE_DATA`, campo `competition`) sin inventar una temporada | 3 tests nuevos |
| **Vivo "STALE" en el descanso**: una respuesta idéntica conserva su primera hora de índice | el registro marcaba STALE un partido en juego leído cada minuto | cuenta como lectura una pasada completa del seguidor dentro de su ventana | 3 tests nuevos; el registro pasó a FRESH |
| **Personas nunca descritas** (P2, be-93) | 6.260 jugadores y 4.137 entrenadores de alineaciones sin perfil | petición por id, con presupuesto y sin tocar la reserva en vivo: 6.249 perfiles de jugador y 7.306 filas de entrenador escritos | `reference_refresh` 15:48–16:29 UTC, 10.397 peticiones |
| Plantillas "nunca leídas" (be-93) | 300 equipos | eran respuestas vacías del proveedor: ahora UNAVAILABLE (del proveedor), no un fallo nuestro | test `test_people_freshness.py` |
| Auditoría: medios que no lo eran | 36 eventos (sustituciones renumeradas por el proveedor), 18 "estadísticas ausentes" (el proveedor no da ningún valor), 20.566 "perfiles nunca pedidos" (pedidos; el proveedor no tiene el dato) | se clasifican como lo que son (bajo / nada que guardar / info del proveedor); lo nuestro sigue siendo medio | `9d1214f`, `616e6a3`, 3 tests |
| Registro: decía que los modelos entrenan con la versión LEGACY | texto de las 9 filas de datasets de modelo | ninguna versión es MODEL_READY: nombra la más reciente (DATASET_V2, VALIDATED) | `629dad7`, 1 test |

## 4. Datasets actuales: el registro de los 14 datasets

| Dataset | Estado | Cobertura nuestra | Hueco del proveedor | Al empezar P2 |
|---|---|---:|---:|---|
| fixtures | FRESH | 100 % | 0 % | FRESH |
| results | FRESH | 100 % | 0,4 % (2 partidos que el proveedor no cerró; 6 contradicciones suyas) | FRESH |
| live | FRESH | 100 % | 0 % | **STALE** (falso: ver §3) |
| standings | FRESH | 100 % | 0 % | FRESH |
| injuries | FRESH | 100 % | 92 % (el proveedor no cubre lesiones en 12 de 13 temporadas con partido en 48 h) | FRESH |
| lineups | FRESH | 100 % | 13 % | FRESH |
| match_detail | FRESH | 100 % | 0 % | FRESH |
| odds_prematch | FRESH | 100 % | 45 % (partidos que ninguna casa cotiza aún) | FRESH |
| elo | FRESH | 100 % | 0 % | FRESH |
| teams | FRESH | 99,95 % | 0 % | FRESH |
| players | FRESH | 100 % | 0,02 % | **INCOMPLETE** (3.783 sin leer) |
| squads | FRESH | 100 % | 12 % | FRESH |
| coaches | FRESH | 100 % | 54 % (el proveedor no tiene fecha de nacimiento ni nacionalidad de 2.943 entrenadores) | **INCOMPLETE** (4.206 sin leer) |
| coverage | FRESH | 100 % | 0 % | FRESH |

"Cobertura nuestra" es la parte fresca de lo que nos toca; lo que el proveedor no tiene (su bandera de cobertura o su
retraso) se cuenta aparte y no contra nosotros. Corregido también el texto del registro: decía que los modelos entrenan
con la versión LEGACY cuando ninguna es MODEL_READY (elegía una fila cualquiera); ahora nombra la más reciente
(`629dad7`).

## 5. Trazabilidad: cada fila apunta al payload que la escribió

Medido después de la reparación, en las tablas que leen los modelos y las páginas: filas sin hash y filas cuyo hash
no está en el índice RAW.

| Tabla | Filas | Sin hash | Hash fuera de RAW |
|---|---:|---:|---:|
| `core.fixtures` | 225.753 | 0 | 0 |
| `core.fixture_results` | 209.995 | 0 | 0 |
| `core.standings` | 19.963 | **0** (antes 15.385) | 0 |
| `core.fixture_events` | 2.942.797 | 0 | 0 |
| `core.fixture_lineups` | 400.036 | 0 | 0 |
| `core.fixture_team_stats` | 347.766 | 0 | 0 |
| `core.fixture_player_stats` | 5.218.464 | 0 | 0 |
| `core.player_absences` | 183.551 | 0 | 0 |
| `market.odds_snapshots` | 184.101 | 0 | 0 |
| `market.historical_odds` (Football-Data) | 345.964 | 0 | 0 |

Toda fila de esas tablas apunta a un payload guardado e íntegro (salvo los 3 ficheros dañados del 4 oct, que ninguna de
ellas usa). La migración de prueba (`fbi.migration.dryrun`) también pasa ya el hash al escribir tablas.

## 6. Lo que queda abierto y por qué no bloquea

**Medios del libro de evidencias (11 OPEN), por responsable:**

| Responsable | Entradas | Qué son | Por qué no bloquea |
|---|---|---|---|
| Proveedor (7) | E-017, E-470, E-481, E-636, E-791, E-792, E-923 | tablas del proveedor que no cuentan partidos ya jugados (265, Ligue 1 2025), su tabla y sus partidos con equipos distintos (ACL Two, Sudamericana), 155 personas con dos ids, un resultado AET con bloques contradictorios | nuestros datos coinciden con los partidos y resultados; nada se "corrige" inventando |
| PrediGol (2) | E-318, E-465 | temporadas pasadas de Amistosos (10) y Amistosos de clubes (667) nunca migradas | **decisión de diseño** (`NO_HISTORY_WORTH_KEEPING`): los amistosos se siguen por sus cuotas pero su historia no se migra (peso Elo 0). Propuesta: que el dueño las marque ACCEPTED |
| PrediGol (1) | E-466 | el partido 1632353 sigue en Amistosos aunque el proveedor lo pasó a la Kirin Cup | el código ya sigue estos cambios (§3); seguir la Kirin Cup o aceptar el cambio es decisión del dueño |
| Ya determinado: del proveedor (1) | E-469 | 2 nombres de equipo repetidos en un país con ids distintos | comprobado con `/teams?id` (4 peticiones): cada par es **un solo club** que el proveedor partió en dos ids (Nyasa Big Bullets 4596/4599: mismo nombre, país y estadio; St Blazey 12112/28344). No se fusiona solo: un alias en el mapa de equipos (continuidad de Elo de 12 y 5 partidos) es decisión tuya |

**Medios de la auditoría nº 8 (sin culpa asignada por la auditoría v1; analizados uno a uno):**

* *Eventos* (36): partidos de 2019–2020 cuyas sustituciones el proveedor **renumeró** después de nuestra lectura
  ("Substitution 5" → "Substitution 1": mismo minuto, equipo y jugador). La auditoría ya lo trata como un único hallazgo
  bajo por partido (`9d1214f`).
* *Estadísticas de equipo* (28 + 18): el proveedor revisó cifras después de nuestra lectura posterior al partido
  (p. ej. pases 444 → 434 y tarjetas rojas 0 → vacío en 1493152, verificado contra el RAW de las 00:58 UTC); y 18 lados
  para los que el proveedor no da ningún valor, que ya no cuentan como "falta en la base de datos".
* *Alineaciones* (26 + 2): jugadores que en nuestra lectura venían sin id y el proveedor identificó después, y un partido
  de Serie A femenina (1601259) cuyas alineaciones el proveedor publicó más de 21 h después del partido.
* *Resultados* (17 incoherentes + 6 contradicciones): bloques de marcador del propio proveedor que no cuadran; las 6
  contradicciones no tienen fila de resultado (por diseño) y quedan fuera de modelos, Elo y liquidación.
* *Jugadores* (2): fecha de nacimiento y nacionalidad faltan en 20.577 de 68.435 jugadores de alineaciones. 20.566 de
  ellos ya se pidieron por id y su perfil dice `"birth": {"date": null}` (verificado en RAW): es hueco del proveedor.
  La auditoría lo atribuía a "perfiles nunca pedidos"; ahora separa lo nuestro (nunca pedido, medio) de lo suyo
  (pedido y sin el dato, info) (`616e6a3`).

**Mejora aplicada después (migración 0066):** una segunda lectura del detalle 26 h después del inicio del partido
recoge esas revisiones tardías del proveedor (estadísticas, ids de jugadores, alineaciones publicadas tarde) por ~1
petición cada 20 partidos. Cada lectura queda en `core.detail_asks` (partido y etapa: *settled* a +150 min, *late* a
+26 h), porque una respuesta idéntica conserva su primera hora de índice y sin ese registro se volvería a pedir en
bucle. Tests: `test_a_finished_match_is_read_again_a_day_later_once_…`, `test_a_late_read_is_asked_once_…`.

**Historia de tablas (completada):** las 17 instantáneas antiguas (29 sep–4 oct) a las que el escritor anterior a 0048
había quitado 515 filas (un equipo en dos tablas: Apertura/Clausura, grupos de Argentina, Colombia, Perú, periodos de
la Eerste Divisie) se completaron desde su propio payload, en su mismo instante y con su hash (`e9741e7`, 0
peticiones). Una nueva pasada en seco da 0 instantáneas incompletas de 991.

## 7. Respaldos, despliegues y consumo

* **Respaldos antes de tocar datos:** `PRE_STANDINGS_LINEAGE_20261005` — volcado de 607,6 MB (1.201 entradas,
  SHA-256 registrado), RAW de 865,7 MB (63.532 entradas; `tar` avisó de que la carpeta de hoy cambiaba mientras se leía:
  el RAW solo crece), etiquetas en ambos repositorios e instantánea de 62 endpoints de la API.
* **Despliegues:** be-94 (16:29 UTC), be-95 (16:36), be-96 y be-97 (16:50); API 200 y worker reiniciado en cada
  uno. Sin migraciones.
* **Peticiones de P2:** 10.397 (personas por id) + 748 (auditorías nº 8 y nº 9) + 42 (*golden*) = 11.187. Consumo del día a las
  16:39 UTC: 32.805 de 60.000 internas (75.000 del plan); la reserva en vivo nunca se tocó.
* **Libro:** E-466 actualizado con la corrección y sus tests (sigue OPEN: la decisión sobre la Kirin Cup es del dueño).
  Ninguna entrada se marcó ACCEPTED (decisión del dueño).
