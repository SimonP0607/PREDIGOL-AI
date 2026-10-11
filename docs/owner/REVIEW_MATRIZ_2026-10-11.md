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
| 1 | Inicio: ruido en Picks del día | `DailyItemCard`, `DecisionChain` | Modelo, «No publicado», «Liquidado» duplicado | Usuario: liga, hora, partido, marcador, estado, IA; admin: además el modelo; nadie ve «Liquidado» repetido | unit + e2e | PENDIENTE |
| 2 | Parlay del día / multi-día | `ParlayRecordCard` | «ABIERTO» y «En juego» a la vez | Un solo estado: En juego / Ganado / Perdido | unit | PENDIENTE |
| 3 | Partidos: fechas y filtros | `DayNav`, filtros | El tercer chip repite hoy; faltan país/categoría | Hoy · Mañana · fecha absoluta; país, categoría, equipo | unit | PENDIENTE |
| 4 | **Match Center (crítico)** | `MatchPage`, `SummaryTab` | Picks mezclados en Resumen; en vivo la lectura parece nueva | Pestaña Picks; Resumen por estado | unit + e2e | PENDIENTE |
| 5 | Estadísticas | `StatsTab`, API | Solo puntos y goles; filas de dos fuentes mezcladas | P0: una fuente por partido (API-Football primero). Falta: estadísticas prepartido completas según cobertura | `test_one_statistics_source_per_match_api_football_first` | PARCIAL |
| 6 | Mercados: cuota seleccionable | odds UI | Solo Mercados permite Guardar/Agregar | Un componente para todas las cuotas | unit | PENDIENTE |
| 7 | Alineaciones y bajas | `LineupsTab`, API | «una hora antes» fijo; bajas sin foto ni detalle | P0: texto según el reloj (`lineups_usually_60m` / `lineups_not_published` / `lineups_none`); bajas actuales con foto y posición en la API. Falta: fotos y resumen de jugador en pantalla | `test_the_lineups_reason_depends_on_the_kickoff`, `test_only_the_current_absences_before_the_match_every_one_after` | PARCIAL |
| 8 | Avanzado/Auditoría | admin match | Bloques de error; stats completas solo admin | P0: el aviso naranja nombra al responsable (proveedor / nosotros), secciones vacías en español, error real vs «sin predicción», 500 de Analítica corregido. Falta: stats completas para usuarios | `test_match_state.py` (result_wait), `timelineText.test.ts` | PARCIAL |
| 9 | Enfrentamientos directos | admin Contexto | Columnas separadas, scroll horizontal | Tabla compacta | unit | PENDIENTE |
| 10 | Cronología vs Mercados | timeline, Mercados | Cuotas capturadas que no se ven | P0: Cronología veraz (capturas fuera de ventana listadas, near-close «por diseño», consultas sin cuotas). Falta: correspondencia visible en Mercados | `tests/unit/test_timeline.py` | PARCIAL |
| 11 | En vivo | `LivePage` | Sin buscador ni filtros | Buscador, país/liga/género, primero los de PrediGol | unit | PENDIENTE |
| 12 | Picks: día e historial | `PicksPage` | Encabezado y días pasados básicos | Encabezado con fecha y navegación clara | e2e | PENDIENTE |
| 13 | Picks: 24 h y bloques de 15 | `PicksPage` | 72 h por defecto, miles de tarjetas | 24 h; páginas de 15 | unit | PENDIENTE |
| 14 | Ya empezaron hoy | `PicksPage` | Sin filtros ni paginación | Filtros + páginas de 15 | unit | PENDIENTE |
| 15 | Parlays: motivo y armador | Parlays | Sin motivo por pierna ni armador | Motivo por pierna; armador automático con correlación | unit + api | PENDIENTE |
| 16 | Armar el tuyo | Parlays | — | Se mantiene | e2e | PENDIENTE |
| 17 | Cuotas ≠ Picks | `OddsPage` | Casi igual a Picks; 48 h | Mejor precio vs justo; 24 h; filtros | unit | PENDIENTE |
| 18 | Selección de cuota animada | odds UI | Solo en Cuotas | Mismo patrón en todas las vistas | unit | PENDIENTE |
| 19 | Mis picks: gráficas | `MyPicksPage`, API | Solo totales | Métricas y gráficas | unit + api | PENDIENTE |
| B1 | Picks de cuotas altas | selección diaria | Valor sin filtros extra | Embudo trazable con contexto de la IA | unit + datos | PENDIENTE |
| B2 | Partidos «esperando resultado» | worker, API, liquidación | Proveedor que no actualiza; sin clasificar; picks abiertos sin fin | Clasificación por responsable (`ResultWait`), reintento por antigüedad de lectura con espera 25 min/2 h/6 h, `settle-v3`: nulo a las 72 h del saque tomado | `test_the_repair_asks_the_match_read_longest_ago_first_and_a_fresh_read_waits`, `test_picks.py` (settle-v3), `test_pick_pipeline.py` | HECHO |
| B3 | Más mercados | odds, modelos | Solo 1X2/OU/BTTS/AH/DC | Auditoría de cobertura; nada se activa sin backtest | datos | PENDIENTE |
| B4 | IA objetiva con contexto | IA | Picks sin pasar por Intelligence | Evidencia estructurada obligatoria para el pick principal | unit | PENDIENTE |

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
