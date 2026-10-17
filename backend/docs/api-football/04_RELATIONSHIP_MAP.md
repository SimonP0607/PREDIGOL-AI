# Mapa relacional — la API y nuestro modelo

## 1. El grafo del proveedor, centrado en lo que nos sirve

```
Country ──┐
          ├─> League ──> Season ──> coverage{11 flags}
Seasons ──┘      │
                 ├─> Standings          (1 liga-temporada : N grupos : N equipos)
                 ├─> Rounds             (1 : N jornadas)
                 ├─> TopScorers/…       (derivable, no se usa)
                 │
                 └─> Fixture  ◄── Venue      (N fixtures : 1 venue)
                        │     ◄── Team ×2    (N fixtures : 2 teams)
                        │
                        ├─> Events            (1 : N, ordenados)
                        ├─> Lineups           (1 : 2)  ──> LineupPlayer (1 : ~18)
                        │                      └──> Coach (1 : 1, denormalizado)
                        ├─> TeamStatistics    (1 : 2 × 16 métricas)
                        ├─> PlayerStatistics  (1 : ~30 jugadores × 26 métricas)
                        ├─> Injuries          (1 : N ausencias)
                        ├─> Odds pre-match    (1 : N casas : N mercados : N valores)
                        ├─> Odds in-play      (1 : N mercados agregados, SIN casa)
                        └─> Predictions       (1 : 1)

Team ──> Players (squad actual)   ──> Transfers   (1 : N)
     ──> Coach                     ──> Trophies    (1 : N)
     ──> TeamStatistics (temporada)──> Sidelined   (1 : N)
```

**Los cinco recuadros de la izquierda del diagrama oficial son un espejismo de coste**: `Events`,
`Lineups`, `Fixtures Statistics` y `Players Statistics` cuelgan de `Fixtures` como endpoints
propios, pero `/fixtures?ids=` los entrega **dentro del mismo objeto**. Para el backfill no son
cuatro ramas, son campos.

## 2. Cardinalidades que cambian decisiones

| Relación | Cardinalidad | Por qué importa |
|---|---|---|
| League : Season | 1 : N (hasta ~16 en nuestro catálogo) | la profundidad la decide `coverage`, no nuestro deseo |
| Season : Fixture | 1 : 240–460 | el coste del detalle es lineal en partidos, no en ligas |
| Fixture : detalle | 1 : 1 respuesta si se usa `ids=` | **1 petición por cada 20 partidos** |
| Fixture : PlayerStats | 1 : ~28–36 filas | el 90 % del volumen de filas del backfill |
| Fixture : Odds(pre) | 1 : ~9 casas × ~15 mercados | pero **solo dentro de la ventana de 14 días** |
| Fixture : Odds(live) | 1 : N mercados **sin casa** | no comparable con pre-match: es un agregado |
| Team : Season | N : N | `team_season_memberships` existe en V2 y está vacía |
| Player : Team | N : N por temporada | *"a player has statistics for 2 teams in the same season in case of transfers"* |
| Standing : Group | 1 liga-temporada : N tablas | apertura/clausura y fases de grupos rompen "una tabla por liga" |

## 3. Cómo encaja en el modelo de V2

```
API                          V2 (esquema.tabla)
────────────────────────────────────────────────────────────────
/leagues                  →  core.competitions + core.competition_seasons
  └─ coverage             →  raw.league_coverage            ✅
/fixtures?league&season   →  core.fixtures + core.fixture_results   ✅
  ├─ teams inline         →  core.teams        (solo id + nombre)  🟡
  └─ venue inline         →  core.venues       (sin país ni aforo) 🟡
/fixtures?ids=            →  core.fixture_team_stats                ✅
  ├─ events               →  core.fixture_events                    ✅
  ├─ lineups              →  core.fixture_lineups + _lineup_players ✅
  │   └─ coach            →  columnas en fixture_lineups (sin entidad) 🟡
  └─ players              →  core.fixture_player_stats              ✅
/standings                →  core.standings    (solo bloque `all`)  🟡
/injuries                 →  core.player_absences                   ✅
/teams                    →  ✗ payload guardado, 0 filas            ❌
/players                  →  ✗ payload guardado, 0 filas            ❌
/odds                     →  market.odds_snapshots                  ✅
/odds/live                →  market.near_close_snapshots (sin linaje) 🟡
/coachs /transfers /trophies /sidelined /predictions
/teams/statistics /h2h /venues /players/squads /profiles /teams
                          →  ✗ nada                                 ❌
```

Detalle campo a campo y prioridades: `09_V2_GAP_ANALYSIS.md`.

## 4. Dónde nuestro modelo se separa del proveedor a propósito

1. **Marcador de 90 minutos.** El proveedor da `goals` (incluye prórroga). Nosotros derivamos
   `reg_goals_*` y redefinimos `outcome_1x2`, `total_goals` y `btts` sobre él, porque es lo que
   liquidan los mercados. El marcador final se conserva para los ratings.
2. **`team_side` en vez de `team.id`.** Guardamos home/away resuelto, no el id crudo, para que una
   fila de estadística no pueda pertenecer a un equipo que no juega el partido.
3. **`source` en cada tabla de detalle.** El mismo partido puede tener estadísticas de
   API-Football y de Football-Data; la clave primaria incluye la fuente y la precedencia es
   explícita.
4. **Linaje obligatorio.** Cada fila normalizada apunta a un `payload_hash` cuyo fichero
   re-hashea. El proveedor no ofrece nada parecido; es nuestra defensa contra "de dónde salió
   este número".
5. **Instante de captura.** El proveedor da `update` por bloque de cuotas; nosotros guardamos
   `captured_at` propio y `minutes_to_ko`, porque el CLV depende de cuándo lo vimos nosotros.
