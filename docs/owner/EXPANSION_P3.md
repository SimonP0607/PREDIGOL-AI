# P3 · +50 ligas por tandas: validación medida y tanda 1 (5 oct 2026)

Mandato: añadir las 50 ligas adicionales **solo después de validar consumo, cobertura y calidad**, de forma
progresiva. Código: backend `1d0caca` (sonda), `8a89f85` (tandas). Lista de candidatas: `config/expansion.yaml`
(las 50 del informe de capacidad, `API_CAPACITY.md`).

**Resultado medido (5 oct, 17:30 UTC):**

* **Validación previa hecha con datos reales**: consumo (el recurrente usa ~10 % del presupuesto interno), cobertura
  y calidad de las 50 candidatas con una sonda de 156 peticiones. Los datos que sirve el proveedor son **coherentes**
  en todas (0 resultados sin resolver; goles = eventos en 48 de 50), pero **41 no tienen estadísticas** de equipo ni
  de jugador y **14 no tienen alineaciones**.
* **Tanda 1 activa**: 8 de las 50 que pasan la regla de datos + la Apertura paraguaya (la otra mitad de la temporada
  de la Clausura) → **9 ligas seguidas** (124 → 133). Historia 2018–2026: 81 temporadas, **18.657 partidos
  terminados, 100 % con resultado, 18.655 aprobados** por la validación histórica; 1.807 peticiones.
* **Sin regresión**: auditoría de verdad nº 10 con la tanda dentro, **0 críticos / 0 altos**; registro **14/14
  FRESH**; los 7 partidos próximos de la tanda ya tienen cuotas.
* **Tanda 2: no hoy.** Se decide tras un día completo medido con la tanda 1 (consumo real por liga, cuotas en cada
  ventana, frescura). Las demás candidatas no pasan hoy la regla de datos o esperan a su división completa o a su
  próxima temporada (§5). Añadirlas ahora solo inflaría el número de ligas.

## 1. Consumo: hay margen

| Medida | Valor |
|---|---|
| Plan | Ultra, 75.000 peticiones/día; presupuesto interno 60.000, contado en la base de datos y compartido por todos los procesos |
| Consumo de hoy (5 oct, hasta 16:39 UTC) | 32.805, de los que ~20.000 son cargas únicas (relleno de personas 10.397, migración de historia, auditorías) |
| Recurrente medido (últimas 24 h, sin cargas únicas) | ~6.000/día: cuotas pre-partido 2.696, cuotas en vivo 1.307, seguimiento en vivo 682, calendario 306, contexto 227, resto < 100 |
| Modelo de coste (capacidad, 5 oct) | fijo 1.334 + 32,3 por liga + 12,7 por partido y día |
| +50 ligas (modelo) | ~8.300/día normal, ~11.400 en el día P95: 19 % del presupuesto interno |

La API no es el límite. Lo son la calidad de datos de las ligas menores (abajo) y el almacenamiento (`STORAGE_FORECAST.md`).

## 2. Cobertura y calidad: lo que el proveedor sirve de verdad (sonda, 156 peticiones)

`python -m scripts.probe_leagues` pidió, para la temporada actual de cada candidata, su calendario, el detalle de los
20 últimos partidos terminados y su tabla (runs 10035 y 10055; cada respuesta en RAW). Informe:
`data/expansion/20261005T165323Z-probe/PROBE.md`.

| Medida (20 últimos partidos terminados de cada una de las 50) | Resultado |
|---|---|
| Resultados sin resolver | **0** en las 50 |
| Goles de los eventos = marcador (partidos terminados en 90') | 1,0 en 48; 0,95 en 2 (Non League South, 2. SNL) |
| Eventos | ≥ 0,85 en las 50 |
| Alineaciones con 11 titulares | 1,0 en 7; ≥ 0,8 en 18; **0 en 14** |
| Estadísticas de equipo | en 9 (≥ 0,85 en 5) |
| Estadísticas de jugador | en 4 |

Además se sondearon dos "compañeras" (la otra mitad o el otro grupo de una candidata): Apertura paraguaya (250): datos
0,90; Serie C grupo B (942): alineaciones 0,55.

**Lectura:** los datos que hay son **coherentes** (0 resultados sin resolver, goles = eventos), pero **41 de las 50 no
tienen estadísticas de equipo ni de jugador**: son marcador, eventos y (a veces) alineaciones. Con la regla del propio
sistema para migrar historia (`fbi.migration.selection`: 3 temporadas con eventos, alineaciones y las dos
estadísticas) solo 2 candidatas la cumplirían. Sirven a los modelos de resultados (Elo, Poisson) y al mercado, no al
modelo de features ricas.

## 3. Regla de la tanda 1 y por qué estas ligas

Liga de clubes; en sus 20 últimos partidos: eventos, alineaciones con 11 titulares ≥ 80 %, goles = marcador ≥ 95 %,
0 resultados sin resolver; ≥ 25 partidos por jugar o temporada hasta 2027; ≥ 7 casas de media (sonda de capacidad).

| Liga | Datos | Alineaciones | Por jugar | Casas | |
|---|---:|---:|---:|---:|---|
| División Profesional Clausura (252, PAR) | 0,99 | 0,95 | 58 | 8,5 | |
| División Profesional Apertura (250, PAR) | 0,90 | 0,90 | 0 | – | la otra mitad de la temporada de 252 (el proveedor la parte en dos ids): sin ella, la historia de los clubes paraguayos tendría medio año vacío |
| Veikkausliiga (244, FIN) | 0,95 | 1,00 | 27 | 8,2 | |
| J2 League (99, JPN) | 0,50 | 1,00 | 290 | 8,9 | |
| J3 League (100, JPN) | 0,48 | 0,90 | 290 | 8,8 | |
| Championship (180, SCO) | 0,50 | 1,00 | 138 | 7,3 | |
| League One (183, SCO) | 0,49 | 0,95 | 136 | 7,0 | |
| USL Championship (255, USA) | 0,50 | 1,00 | 40 | 7,9 | |
| 2. liga (506, SVK) | 0,46 | 0,85 | 152 | 8,8 | |

De las 18 candidatas con alineaciones ≥ 80 %, quedan fuera de la tanda 1, con la razón medida: First League RUS (236)
— datos 0,71 pero 2,9 casas de media; Primera URU (268), Torneo Federal A (134), First Division IRL (358), J-League Cup
(101), Serie C BRA (75) — temporada a punto de acabar (≤ 16 partidos por jugar); Botola Pro (200) — el proveedor lista
31 partidos para una liga de 16 equipos (calendario incompleto); Serie C italiana (138) y 2. Division noruega (474) —
su grupo pasa pero el otro no (0,55 y 0,75): una división se añade entera o no se añade, porque un club que cambia de
grupo rompería su historia; Juegos Asiáticos (803) — selecciones, terminado. Las otras 32 no llegan al 80 % de
alineaciones.

## 4. Activación de la tanda 1

1. **Respaldo** `PRE_P3_BATCH1_20261005` (volcado verificado, RAW 64.039 entradas, etiquetas en ambos repositorios).
2. **Seguimiento** (`python -m scripts.expand_leagues --batch 1 --apply`, run 10063, 0 peticiones): 8 competiciones
   nuevas y 1 actualizada (USL ya estaba en el catálogo, sin seguir), 107 temporadas creadas desde el `/leagues` en
   disco; seguidas 124 → **133**; ninguna otra competición cambió de estado. Logos y banderas desde RAW (0 peticiones).
3. **Historia** como su propio nivel de migración (nivel 5): 81 temporadas, ~30.780 partidos, **1.789 peticiones**
   presupuestadas (calendarios 81, detalle 1.539, tablas 80, equipos 81, lesiones 7), 99 MB de RAW.
   Ejecutada entre 17:02 y 17:25 UTC por el motor de migración (y el job del worker en paralelo, con la cuota
   compartida): **1.807 peticiones** reales (calendarios 108, detalle 1.531, tablas 80, equipos 81, lesiones 7), 0
   rechazadas, 0 fallidas, más de 558.000 filas escritas. Una unidad (Championship escocesa 2021) quedó "running" cuando el worker
   se reinició a mitad (despliegue be-99); el motor la retomó solo (`STALE_RUNNING`): **hecha el 5 oct a las 18:22:25
   UTC** (unidad 171537, run 10340, segundo intento, 1 petición). La temporada tiene 186 partidos, todos terminados con
   resultado, eventos y alineaciones (comprobado el 6 oct tras el apagado).

| Liga | Temporadas | Partidos | Terminados | Con resultado | Con eventos | Con alineaciones | Con estadísticas |
|---|---:|---:|---:|---:|---:|---:|---:|
| J2 League (99) | 9 (2018–2026) | 3.929 | 3.639 | 3.639 | 3.636 | 3.591 | 0 |
| J3 League (100) | 9 | 2.928 | 2.638 | 2.638 | 2.624 | 2.361 | 0 |
| Championship SCO (180) | 9 | 1.605 | 1.424 | 1.424 | 1.424 | 1.424 | 0 |
| League One SCO (183) | 9 | 1.636 | 1.414 | 1.414 | 1.413 | 1.404 | 0 |
| Veikkausliiga (244) | 9 | 1.524 | 1.497 | 1.497 | 1.497 | 1.497 | 1.000 |
| Apertura PAR (250) | 9 | 1.146 | 1.145 | 1.145 | 1.145 | 1.145 | 131 |
| Clausura PAR (252) | 9 | 1.087 | 1.029 | 1.029 | 1.029 | 1.023 | 206 |
| USL Championship (255) | 9 | 4.082 | 4.034 | 4.034 | 4.034 | 4.034 | 20 |
| 2. liga SVK (506) | 9 | 1.990 | 1.837 | 1.837 | 1.652 | 1.651 | 0 |
| **Total** | **81** | **19.927** | **18.657** | **18.657 (100 %)** | | | |

4. **Validación de lo cargado (0 peticiones salvo la auditoría):**
   * Validación histórica: de los 18.657 partidos terminados, **18.655 HISTORICAL_APPROVED** y 2 en cuarentena; las
     81 temporadas quedan **PARTIAL** con una única razón: sin precios históricos (el proveedor no los da; ver §5).
   * Elo recalculado: 228.632 partidos (antes 209.997), 2 filas por partido en todas las ligas nuevas.
   * Auditoría de verdad nº 10 (17:25 UTC, 392 peticiones, 0 fallos): **0 críticos, 0 altos**; 133/133
     competiciones; calendarios de 153 temporadas 283.700/283.704 campos iguales; resultados 480.480/480.487 (las
     diferencias son las incoherencias y contradicciones del proveedor ya conocidas, una más en las ligas nuevas).
   * Registro: **14/14 datasets FRESH** con la tanda dentro.
   * Cuotas: los 7 partidos de la tanda en las próximas 72 h (Veikkausliiga 3, Clausura paraguaya 4) ya tienen precio
     capturado (7/7) en su primera ventana, sin tocar el planificador.
   * Calidad: 34.068 avisos *info* `INCOMPLETE_LINEUP` (alineaciones de ligas menores sin posición o rejilla para
     algún jugador; nada se inventa) y 35 *warning*.

## 5. Qué falta para la tanda 2

* **Trabajo de fondo que trae la tanda** (lo absorbe la asignación normal de los feeds de referencia, 300 peticiones
  cada 30 min y nunca la reserva en vivo): 2.274 perfiles de jugadores de sus alineaciones, entrenadores y
  estadísticas de temporada de sus equipos.
* **Un día completo medido** con la tanda 1 dentro: peticiones reales por liga y partido contra el modelo de coste,
  cobertura de cuotas de sus partidos (precio en cada ventana alcanzada) y frescura en el registro. Hasta entonces no
  se añade la tanda 2.
* **Candidatas para la tanda 2** (pasan la regla de datos; esperan por otra razón): Serie C italiana entera (si B y C
  suben de 0,55 en alineaciones), 2. Division noruega entera (474 + 473), First League rusa si su liquidez sube de 2,9
  casas. Las ligas que terminan ahora (Uruguay, Federal A, Irlanda, Serie C brasileña, J-League Cup) se reconsideran al
  empezar su próxima temporada, con una sonda nueva.
* **Ligas solo de resultados** (sin alineaciones ni estadísticas; 14 con alineaciones 0): no aportan al modelo de
  features ni a un pick defendible hoy. Añadirlas solo infla el número de ligas: quedan fuera mientras no cambie su
  cobertura (la sonda se puede repetir en cualquier momento por 3 peticiones por liga).
* **Precios históricos:** la historia migrada de estas ligas no tiene cuotas (el proveedor solo da ~7 días), así que
  sus temporadas pasadas quedarán PARTIAL para juzgar contra el mercado; servirán para entrenar modelos de resultados
  y, desde hoy, cada partido suyo se captura con precio. Football-Data publica cuotas históricas de tres de ellas
  (Championship y League One escocesas, Veikkausliiga): importarlas es una descarga externa que requiere tu permiso.

## 6. Tras el apagado del 5–6 oct (comprobado el 6 oct, 01:50 UTC)

El equipo estuvo apagado de 18:38 UTC del 5 oct a 01:12 UTC del 6 oct (hueco de captura de 6 h 57 min; detalle en
`OFFLINE_RECOVERY_2026-10-06.md`). Estado real de la tanda 1 después del catch-up:

* 9 ligas seguidas (nivel 5), 81 temporadas, 19.927 partidos; **0 terminados sin resultado, 0 atrasados**. Unidades
  de migración de la tanda: **1.223 hechas** (calendarios 81, equipos 81, tablas 80, lesiones 7, detalle 974), ninguna
  pendiente ni en curso; en todo el sistema, 29.554 hechas y 0 pendientes.
* Los 2 partidos de la Clausura paraguaya jugados durante el apagado tienen resultado, detalle y su último precio
  pre-partido recuperado después del partido (aparte, nunca usable por un pick); sus ventanas near-close y en vivo
  se perdieron y están marcadas.
* Validación histórica (01:46 UTC): las 81 temporadas siguen `PARTIAL` (sin cuotas históricas); 18.655 aprobados y
  2 en cuarentena, sin cambios.
* **El día completo de medición que pide la tanda 2 vuelve a empezar**: el apagado cortó el del 5 oct. Se mide desde
  el 6 oct 01:34 UTC (worker de nuevo en marcha).

