# IA-077 · Uruguay, Venezuela, Copa Colombia y Primera B: qué sirve el proveedor y cómo seguirlas (AD-H08)

Pieza AD-H08 del plan de la arquitectura definitiva 2026, **decisión n.º 10** del dueño (aprobada el 16-nov-2026): seguir estas
cuatro competiciones si API-Football tiene datos y caben en el presupuesto. Es **solo configuración**: dos lotes nuevos en
`config/expansion.yaml` (el camino vigente desde la P3; `config/competitions.yaml` está obsoleto y aplicarlo apagaría casi todo) y
una opción nueva de vuelta atrás en `scripts.expand_leagues` (`--untrack`). **Desplegar este cambio no sigue nada**: las cuatro
continúan con `is_tracked = false` hasta que tú ejecutes el paso del §4 en el servidor. Sin migración, sin interruptor, sin efecto en
el lector, sin proveedor ni plan nuevos.

La medición es de solo lectura en producción, del **17-nov-2026**: catálogo y banderas de cobertura entre las 00:30 y las 03:30 UTC, y
una sonda al proveedor a las **03:26 UTC** con el cliente del propio código dentro del worker: **8 peticiones** (por liga, el
calendario de la temporada 2026 y el detalle de sus 20 últimos partidos terminados), sin guardar nada en RAW, juzgadas con las mismas
reglas de `scripts.probe_leagues`. Las órdenes están en `docs/owner/lab/IA_077/`.

## 1. Qué tiene cada una (20 últimos partidos terminados de 2026)

| | Venezuela Primera (299) | Primera B COL (240) | Uruguay Primera (268) | Copa Colombia (241) |
| --- | ---: | ---: | ---: | ---: |
| Partidos 2026 / terminados / por jugar | 231 / 227 / **3** (21-22 nov) | 290 / 286 / **0** (4 aplazados) | 289 / 289 / **0** | 72 / 70 / **2** (17-18 nov) |
| Muestra (fechas) | 20 (24-oct a 12-nov) | 20 (29-oct a 16-nov) | 20 (25-oct a 16-nov) | 20 (29-jul a 11-nov) |
| Resultados sin resolver | 0 | 0 | 0 | 0 |
| Eventos | 20/20 | 20/20 | 20/20 | 20/20 |
| Las dos alineaciones con 11 titulares | **20/20 (1,00)** | **19/20 (0,95)** | **14/20 (0,70)** | **13/20 (0,65)** |
| Estadísticas de equipo | 0/20 | 0/20 | **20/20** | 0/20 |
| Estadísticas de jugador | 0/20 | 0/20 | 0/20 | 0/20 |
| Goles de los eventos = marcador (partidos en 90') | 20/20 | 20/20 | 20/20 | 15/16 (un 1-2 con un solo gol en eventos) |
| Banderas del proveedor 2026 (eventos, alineaciones, estadística equipo/jugador, tabla, bajas, cuotas) | sí, sí, no/no, sí, no, sí | sí, sí, no/no, sí, no, sí | sí, sí, **sí**/no, sí, no, sí | sí, sí, no/no, sí, no, sí |
| Casas de apuestas de media | sin medir | sin medir | 8,8 (10 partidos, informe de capacidad del 5-oct) | sin medir |
| Temporadas que lista el proveedor | 16 (2011-2026) | 11 (2016-2026) | 15 (2012-2026) | 8 (2019-2026) |

**2027 aún no existe en el proveedor**: el `/leagues` del 17-nov (00:28 UTC) no lista ninguna temporada 2027 de las cuatro. Las cuatro
están ya en el catálogo (`core.competitions` ids 76, 50, 59 y 51), sin seguir, y no tienen ni un partido guardado.

**Lectura:**
* Las cuatro sirven **marcador, eventos y alineaciones** coherentes (0 resultados sin resolver; goles = eventos en 75 de 76 partidos
  en 90'). Sirven a los modelos de resultados (Elo, Poisson) y al mercado.
* **Ninguna tiene estadística de jugador**, así que no se ofrece ningún mercado de jugador en ellas (decisión n.º 7). Solo Uruguay
  tiene estadística de equipo.
* Con la regla de datos de la tanda 1 (alineaciones completas en ≥ 80 %, goles = eventos en ≥ 95 %) **pasan Venezuela y Primera B**;
  **Uruguay (0,70) y Copa Colombia (0,65) quedan por debajo**, y Copa Colombia es una copa, no una liga.
* La parte de calendario de esa regla (≥ 25 partidos por jugar o temporada hasta 2027) **no la cumple ninguna hoy**: entre las cuatro
  quedan 5 partidos de 2026. Su valor empieza con la temporada 2027.

**Contradicciones con lo que se sabía (para que no se arrastren):**
* La ficha decía que Copa Colombia y Primera B «salieron sin alineaciones» con **1 partido** por competición. Con 20 partidos: Primera B
  tiene alineaciones completas en 19 y alguna alineación en 20; Copa Colombia, completas en 13 y alguna en 19. Aquel dato de n = 1 no
  era representativo.
* El informe de la P3 (5-oct) contaba a Uruguay entre las ligas con alineaciones ≥ 80 %; en sus 20 últimos partidos (25-oct a 16-nov,
  el final de temporada) es 0,70. Son ventanas distintas; ninguna de las dos es «la verdad» de la liga entera.
* Partidos por jugar: la ficha decía 1, 3, 2 y 0 (16-nov); el 17-nov son 0, 3, 2 y 0 (Uruguay jugó su último el 16-nov).

## 2. Qué cambia en el código

* `config/expansion.yaml`:
  * tres candidatas nuevas (Venezuela 299, Primera B 240, Copa Colombia 241; Uruguay ya era la n.º 2), con el nombre y el país que da
    el proveedor: `expand_leagues` se niega a seguir una liga cuyo nombre o país no coincidan, así que un id equivocado se para ahí;
  * **lote 3** (nivel 7): Venezuela y Primera B, las que pasan la regla de datos;
  * **lote 4** (nivel 8): Uruguay y Copa Colombia, por tu decisión n.º 10 aunque estén por debajo de la regla (Uruguay por su
    estadística de equipo; Copa Colombia porque es la copa de los clubes de la Primera A que ya seguimos: su calendario y rotaciones);
  * cada liga lleva su medición (`measured`: cuotas de los 20 partidos, banderas del proveedor y casas) y un comentario con la fecha.
  Partirlas en dos lotes permite seguir las que pasan sin arrastrar las que no, y medir un día entre uno y otro, como exige el fichero.
* `scripts/expand_leagues.py`: opción `--untrack`, la vuelta atrás de un lote (§5). Mismas comprobaciones, deja `is_tracked = false`
  solo en las ligas del lote y no borra nada. Antes no había forma de deshacer un lote sin escribir SQL a mano.
* Pruebas: `tests/unit/test_expansion_batches_ia077.py` (los dos lotes, nombres, niveles, que la medición esté y sea coherente con la
  regla, que ninguna declare estadística de jugador, `--untrack` en seco) y una prueba de integración en
  `tests/integration/test_league_expansion.py` (los lotes reales: ensayo, `--apply`, `--untrack --apply`; nada más cambia).

**Qué no cambia:** nada de lo que hoy se sigue, ni `decision-v1`, ni umbrales, ni picks, ni interruptores, ni el lector. Los lotes 1
y 2 quedan igual.

## 3. Coste en peticiones

Con lo medido del 10 al 16-nov (7 días, semana de ventana FIFA, 136 competiciones seguidas, 447 partidos):

* **por liga y día**, 6,1 peticiones (calendario `fixtures_sync` 3,2 + tabla y bajas `context_refresh` 2,9);
* **por partido**, 24,8 (cuotas pre-partido y su libro, alineaciones previas, lectura final, detalle y resultados); 42,7 si además
  contara toda la captura en vivo (que hoy es una consulta global por ciclo, no una por partido);
* los **feeds de referencia** (perfiles, entrenadores, estadísticas de temporada) trabajan con una asignación fija: una liga nueva les
  da trabajo, no más cupo. Si crecieran en proporción, serían ~65 por liga y día.

| | Partidos por día en temporada (2026) | Peticiones por día | Tope prudente | Historia 2018-2026, una vez |
| --- | ---: | ---: | ---: | ---: |
| Lote 3 (VEN + Primera B) | 1,75 | **≈ 55** | ≈ 90 | ≈ 300 |
| Lote 4 (URU + Copa Colombia) | 1,39 | **≈ 47** | ≈ 72 | ≈ 220 |
| Las cuatro | 3,1 | **≈ 100** | ≈ 160; ≈ 420 con referencia proporcional | ≈ 520 |
| Día punta (≈ 12 partidos) | | ≈ 320 | ≈ 540; ≈ 800 con referencia | |

La historia se calcula con el tamaño de las temporadas 2026 (calendario, tabla y equipos por temporada, más el detalle de 20 partidos
por petición); el planificador la precia con 380 partidos por temporada y un 35 % de margen, así que dirá más (§4, paso 5, 0 peticiones).

**Presupuesto:** el contador del código trabaja con **60.000/día** (`min(daily_budget, per_day_limit)`; el plan Ultra son 75.000). Del
17-oct al 16-nov (31 días): media 17.999, mediana 16.327. Las cuatro suman ~0,6 % de la media (2,3 % en el peor caso con referencia
proporcional): **caben con cualquiera de las dos cifras** y no cargan a los sobres de IA 185 / 35 / 55. Aviso aparte, no causado por
esto: el **29-oct el contador llegó al tope (60.000)**; los otros 30 días no pasaron de 23.430. No investigué la causa (coincide con la
fecha en que vencía la suscripción según `API_CAPACITY.md`, pero eso es una hipótesis).

## 4. Cómo se activa (tú, en el servidor, tras desplegar)

**Recomendación: esperar a que el proveedor publique 2027.** Hoy seguir cualquiera de las dos solo trae los 5 partidos que quedan de
2026. El catálogo se refresca solo cada día (`catalogue_refresh`): el día que el ensayo del paso 1 diga `current 2027`, la temporada
nueva existe. Si prefieres empezar ya (para tener cuotas de los 3 partidos de Venezuela), los pasos son los mismos.

Siempre **fuera de una `fixtures_sync`** (03:41, 09:41, 15:41 y 21:41 UTC; deja 20 min) y **nunca entre las 03:50 y las 05:00 UTC**.
Todo lo de abajo gasta **0 peticiones** salvo la consulta de estado del paso 3 (1, a `/status`) y la historia (paso 6).

1. Ensayo del lote 3, no escribe nada:
   ```
   docker exec -w /app predigol-worker python -m scripts.expand_leagues --batch 3
   ```
   Debe listar 299 y 240 con `known True`, `tracked False` y terminar en `dry run (track): re-run with --apply`. Si dice `REFUSED`, no
   sigas: el proveedor ha cambiado el nombre o el país de alguna, y hay que corregir `config/expansion.yaml` en un PR.
2. Seguir el lote 3:
   ```
   docker exec -w /app predigol-worker python -m scripts.expand_leagues --batch 3 --apply
   ```
   Imprime `tracked in run N: {...}` con 2 competiciones actualizadas. Seguidas: 136 → 138. Desde ese momento el worker las trata como
   cualquier liga seguida (calendario, cuotas pre-partido y en vivo, tablas, referencia).
3. **Medir un día completo** (UTC) antes del lote 4: consumo del día (`docker exec -w /app predigol-worker python -m scripts.capture_odds
   status`, línea «requests issued today») comparado con los días anteriores, y que sus partidos tengan cuotas. El criterio de cierre de
   la pieza: **≤ 1.000 peticiones** añadidas en el día medido.
4. Lote 4, igual: `... --batch 4` (ensayo) y `... --batch 4 --apply`. Al seguirlo, Uruguay pasa a llamarse en el catálogo «Primera
   División» (el nombre del proveedor) en lugar de «Primera División - Apertura»; su peso de Elo no cambia.
5. Precio de la historia, 0 peticiones: `docker exec -w /app predigol-worker python -m scripts.migration plan --tiers 7` (y `--tiers 8`
   para el lote 4).
6. Historia (opcional, mejor cuando ya hayas decidido quedarte con el lote): `... python -m scripts.migration seed --tiers 7 --yes` y
   `... python -m scripts.migration run --yes --until-done` (nunca gasta la reserva en vivo). Es un tramo propio, como los lotes 1 y 2.

## 5. Cómo se revierte

* **Dejar de seguir un lote** (0 peticiones, no borra partidos, cuotas, tablas ni historia; el worker deja de preguntar por ellas):
  ```
  docker exec -w /app predigol-worker python -m scripts.expand_leagues --batch 4 --untrack            # ensayo
  docker exec -w /app predigol-worker python -m scripts.expand_leagues --batch 4 --untrack --apply    # hecho
  ```
  Solo cambian las dos ligas del lote; queda una fila `league_expansion` en el registro de ejecuciones con `untrack: true`.
* **Quitar los lotes del fichero**: un PR que borre los lotes 3 y 4 de `config/expansion.yaml`. No hace falta para dejar de seguirlas
  (eso es el punto anterior) y no toca la base de datos.
* Si ya sembraste su historia (paso 6) y la quitas antes de que termine, `python -m scripts.migration status` muestra las unidades
  pendientes del nivel; no lo he probado en producción.

## 6. Lote 4 aplicado y medido (OPS-014, Plan Maestro PM, prerrequisito de PM-03-02)

**Aprobación:** decisión n.º 10 del dueño (16-nov-2026) y autorización definitiva del 17-nov-2026, «Lotes de expansión 3 y 4 … el 4 tras
un día UTC completo de medida» (estado de ejecución del Plan AD). El lote 3 se siguió el 17-nov a las 13:52 UTC (run 187486); su día
completo fue el 18-nov. Sin sesión del Plan AD activa ni PR abierto sobre `config/expansion.yaml` cuando se aplicó.

**Aplicado** el 20-nov-2026 con el paso del §4 (0 peticiones), fuera de `fixtures_sync` y de copias:

* 14:24 UTC, ensayo `expand_leagues --batch 4`: 241 «Copa Colombia» (8 temporadas) y 268 «Primera División» (15), actual 2026, nombres y
  países iguales a los del proveedor.
* **14:25:29 UTC, `--apply`: run 200930** (`league_expansion`): 2 competiciones y 23 temporadas actualizadas, nivel 8. Seguidas
  **138 → 140**.

**Primeras horas:** la `fixtures_sync` de las 16:58 UTC pidió 116 calendarios (114 antes) y guardó Copa Colombia (72 partidos, todos
terminados: la edición 2026 acabó el 18-nov) y Uruguay (297; 5 por jugar). Los tres partidos de Uruguay del 20-nov (19:30 UTC) quedaron
con eventos y alineaciones; dos con cuotas (342 y 326 lecturas) y uno (1650503) pedido 1 vez sin precio del proveedor.

**Días completos medidos** (23-nov, 22:44 UTC, solo lectura; `quota_lanes report`, `raw.provider_endpoint_usage`,
`raw.ingestion_runs`, `raw.ingestion_payloads`, `analytics.coverage_cells`):

| Día UTC | Peticiones del día (contador / libro) | Respuestas atribuibles al lote (por `league` / por `fixture`) | Partidos del lote | Carril limitado |
| --- | ---: | ---: | ---: | --- |
| 21-nov | 20.259 / 20.185 | 4 (`/standings` 2, `/fixtures` 1, `/injuries` 1) / 7 (`/odds` 5, `/predictions` 2) | 0 | ninguno |
| 22-nov | 16.951 / 16.948 | 2 (`/fixtures`, `/standings`) / 7 (`/odds`) | 0 | ninguno |

Días anteriores sin el lote (libro): 12.718 a 23.104 (14 al 19-nov). Las respuestas atribuibles son una **cota inferior** (el índice del
RAW no repite una respuesta idéntica) y no cuentan la referencia, que trabaja con su asignación fija; aun multiplicadas por diez quedan
muy por debajo del criterio de cierre (**≤ 1.000 peticiones añadidas en el día medido**): **cumplido** en los dos días. Ningún carril
habría limitado (los carriles siguen apagados).

**Capturas:** los dos partidos de Uruguay del 23-nov tenían 1.980 y 1.988 lecturas de cuotas (6 peticiones cada uno), alineaciones y,
el terminado, eventos. Próximo: 27-nov 23:30 UTC.

**Nivel de cobertura** (`coverage-levels-v1`, recálculo del 21-nov 08:00 UTC, 295 partidos terminados de Uruguay 2026): eventos,
alineaciones y árbitro **A**; córners, tiros, tiros a puerta y amarillas **D** (54 de 295: solo los partidos recientes traen estadística
de equipo, aunque la sonda de IA-077 vio 20 de 20); faltas, xG y jugador **D** (0). **Copa Colombia no tiene celdas todavía**: el
recálculo incremental solo toma competiciones con un partido terminado en 48 h, y el completo del domingo 22-nov acabó «aborted» dos
veces (08:40 y 11:20 UTC); se graduará en el próximo completo (29-nov) o con `scripts.availability_refresh --only 3613`.

Vuelta atrás, si hiciera falta: §5 (`--batch 4 --untrack --apply`; no borra nada).
