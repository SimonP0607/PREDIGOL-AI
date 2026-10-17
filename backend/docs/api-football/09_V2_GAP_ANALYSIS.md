# Gap analysis — API vs V2

Auditoría de `~/projects/football-intelligence-v2` del 29 sep 2026 (solo lectura). Estados:
`COMPLETE` · `PARTIAL` · `MISSING` · `NOT_NEEDED`.

## 1. Qué llamamos hoy

**9 paths distintos**, a través de 13 métodos del proveedor:
`/leagues` · `/fixtures` (4 usos: league+season, date, ids=, +from/to) · `/odds` · `/odds/live` ·
`/standings` · `/injuries` · `/teams` · `/players` · `/status`.

De los 39 endpoints de la API, tocamos 9. De los 30 restantes, **24 son NOT_NEEDED** por diseño y
**6 son huecos reales**.

## 2. La tabla

| Capacidad de la API | Soporte V2 | Qué falta | Prioridad |
|---|---|---|---|
| Fixtures + marcadores | **COMPLETE** | — | — |
| Marcador de 90' separado de prórroga | **COMPLETE** | mejor que el proveedor (0020) | — |
| Detalle por `ids=` (events/lineups/stats/players) | **COMPLETE** | 17 + 12 + 26 campos mapeados | — |
| Cobertura por liga-temporada | **COMPLETE** | `raw.league_coverage`, 12 flags | — |
| Standings | **PARTIAL** | solo el bloque `all`; se ignoran `home`/`away`, `goalsDiff`, `description` | **P2** |
| Injuries | **COMPLETE** | — | ajustar `since_season` a 2021 |
| Odds pre-match | **PARTIAL** | **el hándicap asiático se parsea y se tira**: `market.markets` solo tiene 1X2/BTTS/OU/DC, así que el bet id 4 se descarta en el borde de la BD en cada captura | **P1** |
| Odds in-play (near-close) | **PARTIAL** | la tabla **no tiene `payload_hash`**: es la única fila del sistema sin linaje | **P0** |
| Teams (identidad) | **MISSING** | `/teams` se guarda en crudo y escribe **0 filas**; `core.teams` solo tiene id+nombre; `country`, `founded`, `logo_url`, `venue_id` siempre NULL | **P2** |
| Venues | **PARTIAL** | sin `country` ni `capacity`; un venue sin id de proveedor no se crea | P3 |
| Players (identidad) | **MISSING** | `/players` se guarda en crudo y escribe **0 filas**; `core.players` no tiene un solo escritor. Los `provider_player_id` de eventos/alineaciones/estadísticas **no tienen FK a ninguna tabla de jugadores** | **P2** |
| Coaches | **PARTIAL** | denormalizado en `fixture_lineups` (id + nombre); sin entidad ni carrera | P3 |
| `fixture.extra` (descuento por mitad, 3.9.3) | **MISSING** | campo nuevo, no se lee | P3 |
| `league.standings` (booleano, 3.9.3) | **MISSING** | campo nuevo, no se lee | P3 |
| `has_fixtures` de `/leagues` | **MISSING** | se parsea y **nunca se persiste** | P3 |
| Temporadas no-actuales de `/leagues` | **MISSING** | `refresh-seasons` guarda **solo la temporada current** y descarta el resto de la respuesta | **P2** |
| `unknown_stat_types` | **PARTIAL** | se detectan y solo se **loguean**; sin columna ni fila de auditoría | P3 |
| Valores incoherentes (tiros a puerta > tiros…) | **PARTIAL** | se anulan en silencio, no se marcan | **P1** |
| Transfers / Trophies / Sidelined | **MISSING** | sin tabla, sin código | NOT_NEEDED hoy |
| Predictions | **MISSING** | deliberado | RESEARCH_ONLY |
| Bookmakers / Bets (catálogos) | **PARTIAL** | `market.bookmakers` viene del backup heredado; `market.markets` es un enum de 4 entradas escrito a mano. **Nunca llamamos `/odds/bookmakers` ni `/odds/bets`** | **P1** |
| H2H, Top scorers, Teams statistics, Rounds, Timezone, Countries, Squads, Profiles | **MISSING** | derivables o sin uso | NOT_NEEDED |
| `/odds/mapping` | **MISSING** | podría evitar pedir cuotas de partidos sin precio | P3 |

## 3. Tablas sin un solo escritor (9)

`core.team_season_memberships` · `core.team_season_stats` · `core.players` ·
`features.feature_values` · `models.calibrators` · `picks.pick_line_value` ·
`analytics.bankroll_ledger` · `audit.data_quality_checks` · `audit.decision_audit`

No son todas un problema: `feature_values` y `bankroll_ledger` fueron diseño temprano superado.
Pero **`models.calibrators` vacía explica por qué cada pick lleva `calibrator_id = NULL`**, y
**`picks.pick_line_value` vacía significa que no estamos midiendo CLV por pick** aunque la tabla
exista y la API la lea.

## 4. Los cinco huecos que de verdad importan

1. **`near_close_snapshots` sin `payload_hash`** (P0). Es el precio con el que se compara la
   decisión final y es la única fila del sistema que no puede señalar el fichero del que salió. La
   cadena de auditoría tiene un eslabón de menos justo donde más cuenta.
2. **El hándicap asiático se descarta en silencio** (P1). Lo pedimos, llega, se parsea, y muere al
   escribir porque `market.markets` no lo tiene. Es la vía más directa a probabilidades implícitas
   de mercado (Hegarty & Whelan 2025) y la estamos tirando en cada captura.
3. **Catálogos de casas y mercados escritos a mano** (P1). Dos llamadas (`/odds/bookmakers`,
   `/odds/bets`) sustituyen un enum heredado y nos dirían qué mercados existen de verdad.
4. **Valores incoherentes anulados sin marca** (P1). `shots_on_target > shots` se convierte en
   NULL y nadie se entera. Debería quedar registrado: es señal de calidad del proveedor.
5. **Identidad de jugadores ausente** (P2). Tenemos 3.360 filas de estadísticas por partido
   colgando de ids sueltos. Sin `core.players`, cualquier feature de plantilla, lesión o rotación
   se apoya en enteros sin nombre.

## 5. Lo que NO hay que cambiar

- No llamar a `/fixtures/statistics|events|lineups|players` por separado en el backfill: `ids=`
  ya los trae y cuesta 80 veces menos.
- No bajar `/teams/statistics`: es 100 % derivable de nuestros partidos, y el propio código
  documenta el bug de promedios del sistema heredado que eso causó.
- No bajar `/predictions` para producción.
- No usar los widgets.
