# REVIEW PREDIGOL — matriz de trabajo (11 oct 2026)

Fuente: `REVIEW PREDIGOL.pdf/.docx` (19 puntos UX + bloque backend). Esta matriz se actualiza al cerrar cada fase.
Estados: **HECHO** (implementado, probado y desplegado), **PARCIAL** (implementado en parte; se dice qué falta),
**BLOQUEADO** (falta algo que no depende del código: credencial, datos, decisión del dueño).

Baseline (11 oct 06:25 UTC): servidor `f021c44` / web `f7f7ea6`, esquema 0075, 5 contenedores sanos, un solo worker.
Backup `review-p0-baseline` + restore test lanzados antes de tocar nada.

## Hallazgos del baseline (datos reales del servidor)

| Hallazgo | Dato | Clase |
|---|---|---|
| Rayo Vallecano – Athletic (10 oct, LaLiga) | El proveedor sigue informando `INT` 17 h después del saque (releído a las 05:18 del 11 oct) | Pendiente del proveedor |
| 4 partidos `NS` muy pasados de hora (Primera A, Irlanda ×2, Sub-19) | Releídos hoy: el proveedor sigue diciendo `NS` | Pendiente del proveedor |
| Sporting JAX – Birmingham Legion (USL) | `FT` con saque el 14 oct: el proveedor movió la fecha después de darlo por terminado | Conflicto del proveedor |
| Picks abiertos en partidos que no van a tener resultado normal | 173 en `NS` vencidos, 162 en `INT`, 134 en `ABD`, 38 en `PST` | Regla de liquidación ausente |
| Estadísticas de equipo duplicadas | 5.329 partidos con filas de dos fuentes (API-Football y football-data); la vista no elige una | Bug propio |
| Bajas desactualizadas | 268 filas de jugadores que el proveedor ya no reporta siguen mostrándose | Bug propio |
| Errores HTTP de la API (96 h) | Ningún 4xx/5xx en el Match Center; 2× 500 en Admin → Analítica → Competiciones (consulta cancelada a los 10 s) | Bug propio |
| Calificación de picks | La evidencia del backtest no distingue la línea: un OU 3,5 se califica con la evidencia del OU 2,5 | Bug propio |
| Cuotas capturadas vs mostradas | Solo 5 tipos de apuesta se normalizan (1X2, OU, BTTS, AH, DC); el resto queda en RAW | Limitación |
| Captura «near-close» | Desactivada por diseño, pero la Cronología la marca como fallo | Presentación errónea |

## Matriz

| # | Punto | Componente | Problema | Solución | Test | Estado |
|---|---|---|---|---|---|---|
| 1 | Inicio: ruido en Picks del día | `DailyItemCard`, `DecisionChain` | Modelo, «No publicado», «Liquidado» duplicado | Usuario: liga, hora, partido, marcador, estado y lo que dijo la IA; admin: además el modelo y la publicación; nadie ve «Liquidado» (el resultado va al pie). La cuota se elige como en Cuotas | `DecisionChain.test.tsx` (renderizado por audiencia) | HECHO (web `6571aee`) |
| 2 | Parlay del día / multi-día | `ParlayRecordCard` | «ABIERTO» y «En juego» a la vez | Un solo resultado: En juego / Ganado / Perdido (Anulado si ocurre); una pierna perdida lo decide | `outcome.test.ts` | HECHO (web `6571aee`) |
| 3 | Partidos: fechas y filtros | `DayNav`, filtros | El tercer chip repite hoy; faltan país/categoría | Hoy · Mañana · «lun, 13 oct» · Otra fecha; país, categoría (liga, copa, continental, selecciones, femenino, juvenil) y equipo | `facets.test.ts`, `model.test.ts`, e2e `responsive.spec.ts` (390 px) | HECHO (web `39f7623` + corrección `d98a106`) |
| 4 | **Match Center (crítico)** | `MatchPage`, `SummaryTab`, `PicksTab` | Picks mezclados en Resumen; en vivo la lectura parece nueva | Pestaña Picks propia; Resumen prepartido: Intelligence → Mejores cuotas → H2H → resto; en vivo: Eventos primero, luego la lectura del día | e2e `user.spec.ts`, QA visual | HECHO (web `4f24dea`) |
| 5 | Estadísticas | `StatsTab`, `/matches/{id}/profile` | Solo puntos y goles; filas de dos fuentes mezcladas | Una fuente por partido (P0) y, prepartido, todo lo que la API da de los dos equipos según cobertura (n por métrica, sin inventar ceros); en vivo, todas las líneas | `test_review_p1_profile.py`, `profile.test.ts` | HECHO (`e8a124c`, web `fca216e`) |
| 6 | Cuota seleccionable en todas partes | `SelectablePrice` | Solo Mercados permitía Guardar/Agregar | Un componente: Resumen, Mercados, Picks, pestaña Picks del partido, Inicio (picks del día y mejores cuotas), parlays | e2e `user.spec.ts` (`selectable-price`), `parlay.test.ts` | HECHO (web `fca216e`, `6571aee`, `cac2345`) |
| 7 | Alineaciones y bajas | `LineupsTab`, API | «una hora antes» fijo; bajas sin foto ni detalle | Texto según el reloj; resumen de temporada de convocados y bajas con foto; alineaciones pedidas cada 10 min desde 75 min antes | `test_review_p1_center.py`, `test_live_match.py` | HECHO (`5944868`, `666e497`) |
| 8 | Avanzado/Auditoría | admin match, `StatsTab` | Bloques de error; stats completas solo admin | Avisos con responsable y código; las estadísticas completas también para usuarios | `test_match_state.py`, `timelineText.test.ts` | HECHO (P0 + web `fca216e`) |
| 9 | Enfrentamientos directos | admin Contexto | Columnas separadas, scroll horizontal | Lista compacta | QA visual | HECHO (web `fca216e`) |
| 10 | Cronología vs Mercados | Mercados | Cuotas capturadas que no se ven | Cada captura en Mercados con sus cotizaciones y casas, las mismas cifras que la Cronología | `test_review_p1_profile.py` (markets), `books.test.ts` | HECHO (`e8a124c`, web `fca216e`) |
| 11 | En vivo | `LivePage` | Sin buscador ni filtros | Buscador, país, liga, género; primero los partidos con picks de PrediGol | `live/filters.test.ts` | HECHO (web `35f8d65`) |
| 12 | Picks: día e historial | `PicksPage`, `DayNav` | Encabezado y días pasados básicos | El día como en Inicio y navegación de días con resumen | `days.test.ts` | HECHO (web `3190d99`) |
| 13 | Picks: 24 h y bloques de 15 | `PicksPage` | 72 h por defecto, miles de tarjetas | 24 h al llegar; páginas de 15 | `filters.test.ts`, `pager.test.ts` | HECHO (web `3190d99`) |
| 14 | Ya empezaron hoy | `PicksPage`, `/picks/started` | Sin filtros ni paginación | Lista propia con filtros (competición, mercado, estado) y páginas de 15 | `test_review_p2_picks.py`, `started.test.ts` | HECHO (`fd4f2b0`, web `3190d99` + corrección `e3c20f6`) |
| 15 | Parlays: motivo y armador | Parlays, `/parlays/build` | Sin motivo por pierna ni armador | Cada selección dice por qué está; armador automático con filtros del usuario y la regla de los parlays de PrediGol; guardar o editar | `test_parlay_builder.py`, `test_review_p4_builder.py`, `builderForm.test.ts`, `render.test.tsx` | HECHO (`1bd0ed2`, web `5045fff`) |
| 16 | Armar el tuyo | Parlays | — | Se mantiene; el armador automático puede cargar su parlay en «Mi parlay» para cambiarlo | QA visual (local, 1440 px) | HECHO |
| 17 | Cuotas ≠ Picks | `OddsPage`, `/odds/best?picks=false` | Casi igual a Picks; 48 h | Solo el mejor precio frente al justo (sin tarjetas de picks); 24 h; búsqueda, país, competición, solo sobre el justo, orden, páginas de 15 | `odds/filters.test.ts`, `test_product_endpoints.py` | HECHO (`fc14241`, web `a6fccca`) |
| 18 | Selección de cuota animada | odds UI | Solo en Cuotas | Mismo patrón (oro + ✓, animación) en todas las vistas con cuotas | ver punto 6 | HECHO |
| 19 | Mis picks: gráficas | `Recap` | Solo totales | «Tu recapitulación»: ganancia acumulada y por día, cuota media, rangos de cuota, rachas, mercados; animadas | `recapData.test.ts` | HECHO (web `b675a59`) |
| B1 | Picks de cuotas altas | selección diaria, parlays, armador | Valor sin filtros extra; cuotas medias 2,85–4,43; ningún pick revisado por la IA al elegirse | `risk-v1` (cuota ≤ 3,00, walk-forward) y `context-v2`: el pick del día solo tras la pasada del día de PrediGol Intelligence, con el día leído entero; embudo trazable `/admin/picks/funnel` | `test_review_p5_selection.py`, `test_selection_funnel.py`, `test_parlay_builder.py`, `FunnelPanel.test.tsx`, `FunnelLine.test.tsx` | HECHO (`20c5f4b`, `fea8369`, `450dc00`; web `76c567a`, `fad763f`, `30cabcc`) |
| B2 | Partidos «esperando resultado» | worker, API, liquidación | Proveedor que no actualiza; sin clasificar; picks abiertos sin fin | Clasificación por responsable (`ResultWait`), reintento por antigüedad de lectura con espera 25 min/2 h/6 h, `settle-v3`: nulo a las 72 h del saque tomado; regresión de todos los estados de extremo a extremo | `test_the_repair_asks_the_match_read_longest_ago_first_and_a_fresh_read_waits`, `test_picks.py` (settle-v3), `test_pick_pipeline.py`, `test_review_p5_states.py` (FT, AET, PEN, CANC, PST, ABD, AWD, WO, SUSP, INT, 72 h) | HECHO (P0 + `5e00839`) |
| B3 | Más mercados | odds, modelos | Solo 1X2/OU/BTTS/AH/DC | Auditoría de cobertura, liquidez y datos para liquidar (goles por equipo y córners primero; remates y paradas no viables: una casa); backtest de goles por equipo (`research_team_totals`); nada se activa sin backtest | `test_research_team_totals.py`; datos | PARCIAL (falta lo que no se puede hacer hoy: 30 días en sombra y la decisión del dueño) |
| B4 | IA objetiva con contexto | IA | Picks sin pasar por Intelligence ni noticias | Evidencia clasificada por el servidor (confirmada / probable / rumor / contradictoria / desactualizada) congelada con cada pick; pasada del día obligatoria; la búsqueda de noticias va primero a los candidatos del set | `test_review_p5_selection.py`, `test_ai_v2.py` (orden de la web) | HECHO (`450dc00`, `15f2ec8`) |

## P0 — cerrado el 11 oct 2026 (07:15 UTC)

Desplegado: backend `32c0b1c`, web `92cd1f8` (respaldo previo `predigol-20261011T070120Z-pre-deploy-32c0b1cfa0fc`).
Respaldo de referencia `predigol-20261011T062502Z-review-p0-baseline` (732 MB, sha256 95eba91c…) y su restore test:
PASSED en 282 s (revisión 0075, 245.908 partidos, 64.234 picks).

Verificado con datos reales tras el despliegue:

* 4 partidos vencidos sin resultado, los 4 `provider_pending` (el proveedor sigue informando INT/NS); tareas sanas.
* Rayo – Athletic (9166): `provider_pending`, última lectura 05:18 UTC; Cronología con 2 capturas fuera de ventana
  (387 y 401 cotizaciones) que antes no aparecían, near-close «desactivada por diseño», inicio «visto en juego».
* Barcelona – Getafe (9168) y 9166: estadísticas de una sola fuente (api-football), bajas con foto (10/10 y 5/5).
* `settle-v3`: 0 registros afectados hoy (ningún pick abierto supera las 72 h sin resultado); la regla rige desde ya.
* Analítica → Competiciones 9,0 s y Cobertura 19,2 s (antes: 500 a los 10–15 s).

## P1 — Match Center (cerrado el 11 oct, 14:59 UTC)

Desplegado: backend `e8a124c`, `5944868`, `666e497`; web `4f24dea`, `fca216e`. Verificado con datos reales:

* Perfil prepartido calculado en 0,08–0,15 s, cada métrica con su n (cobertura); sin datos no hay cero inventado.
* Mercados: las capturas coinciden con la Cronología — 9168: [414, 441, 451, 454, 454, 430] cotizaciones;
  9166: [387, 401, 403, 403, 405, 405].
* Alineaciones con resumen de temporada: 43/43 y 42/45 jugadores; tarea `prematch_lineups` con 118 ejecuciones a las 14:59.

## P2 + P3 — Picks, Inicio, Partidos, En vivo (cerrado el 11 oct, 15:35 UTC)

Desplegado: backend `fd4f2b0`, web `35f8d65` (veredicto del despliegue: ok). Verificado con datos reales:

* `/picks/started`: usuario vacío y honesto (`no_started_picks`: no hay modelo calificado); vista previa del dueño
  1.398 picks que ya empezaron hoy (94 páginas de 15) en 42 competiciones, en 1,0 s.
* Picks: 24 h = 1.139 selecciones (76 páginas) frente a 1.646 con 72 h; 1,7–1,9 s.
* Partidos de hoy: 179 en 63 competiciones de 48 países; categorías liga 176, copa 2, continental 1.
* En vivo: 31 partidos, 28 con picks de la vista previa (van primero), 23 países.
* **Bug encontrado con datos reales:** los 389 picks en juego tenían `result_status = 'pending'` (no `null`), así que
  el filtro «En juego» no mostraba ninguno. Corregido en `e3c20f6` con test de regresión (`started.test.ts`).

## P4 — Parlays, Cuotas, selección de cuota, Mis picks (desplegado el 11 oct, 16:02 UTC)

Desplegado: backend `fc14241` (respaldo previo `predigol-20261011T155746Z-pre-deploy-fc142416399a`), web `6967916`.
QA visual local (390 y 1440 px) con datos de prueba en una base local. Verificado con datos reales a las 16:05 UTC:

* Armador, vista previa del dueño (24 h, 2–4): 4 selecciones, cuota 163,03, acertar todas (prudente) 4,2 %, mercado
  0,6 %; embudo 739 con valor → 337 combinables → 62 partidos; 2,4 s la primera vez, 0,6–0,8 s después. Todas las
  reglas comprobadas en cada respuesta (partidos y equipos distintos, ≤ 2 por competición, ≥ 3 casas, intervalo
  ≤ 40 puntos, VE > 0, ventana, mercados, rango de cuota y tope total).
* Usuario: `no_valid_parlay` / `no_candidates` en 0,03 s — sin modelo calificado no hay parlay que armar.
* Filtros: solo Goles 72 h 3–5 → 3 selecciones a 8,98; cuota 1,5–2,5 con tope 10 → 3 selecciones a 8,68.
* `/odds/best` 24 h 1X2: 0,04 s sin picks frente a 0,62 s con picks (78 partidos, 12 destacados).
* **Hallazgo para B1:** el armador, con la regla actual, elige piernas a 4,01 / 4,84 / 4,00 donde el modelo da
  18–19 puntos más que el mercado. Es la misma regla de los parlays de PrediGol: el gusto por cuotas altas viene de
  la sobreconfianza del modelo (auditoría del 9 oct). Se trata en P5 con evidencia, no a ojo.


## P5 — Backend, modelos e IA (B1–B4)

Detalle y evidencia: `docs/owner/P5_SELECCION_RIESGO_CONTEXTO.md`. Desplegado: backend `5e00839`, web `fc879ff`
(16:50 UTC; respaldo previo `predigol-20261011T164349Z-pre-deploy-5e00839b6c83`, restore test OK). Sin migraciones.

* **B1, riesgo (`risk-v1`):** cuotas 3,00–5,00 = −13,1 % (IC 95 % −22,4 % a −2,8 %; valor de línea −8,9 %) sobre
  16.114 selecciones; el walk-forward eligió un tope de 2,20–3,00 todos los días. Se adopta 3,00 sin afirmar beneficio.
* **B1/B4, contexto:** desde el 9 oct ningún pick del día tuvo la pasada del día de la IA antes de elegirse; el set se
  llenaba con los primeros partidos del día a T−24h. `daily-set-v5` (`context-v2`): pasada del día obligatoria y set
  elegido con el día leído entero (06:00 Bogotá como muy tarde); la búsqueda de noticias va primero a los candidatos.
* **Embudo trazable** con datos reales (v4): 921 selecciones → valor 85 → **riesgo 40 (45 por encima de 3,00)** → IA
  40. Armador: piernas a 2,10–2,55 (antes 4,01–4,84).
* **B2:** regresión de estados de extremo a extremo (`test_review_p5_states.py`).
* **B3:** auditoría (goles por equipo 100 % de partidos con 6,7 casas; córners 95 %; remates y paradas, una casa) y
  backtest de goles por equipo en curso; nada se activa.
