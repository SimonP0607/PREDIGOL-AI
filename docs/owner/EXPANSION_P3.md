# P3 · +50 ligas por tandas: validación medida y tanda 1 (5 oct 2026)

Mandato: añadir las 50 ligas adicionales **solo después de validar consumo, cobertura y calidad**, de forma
progresiva. Código: backend `1d0caca` (sonda), `8a89f85` (tandas). Lista de candidatas: `config/expansion.yaml`
(las 50 del informe de capacidad, `API_CAPACITY.md`).

__RESULT__

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
   __MIGRATION__

## 5. Qué falta para la tanda 2

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
