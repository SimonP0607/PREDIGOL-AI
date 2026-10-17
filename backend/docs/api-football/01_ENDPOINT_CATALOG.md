# Catálogo de endpoints — Football v3.9.3

39 operaciones (38 documentadas + `/status`). Todas **GET**. Base `https://v3.football.api-sports.io`.
`REQ` = parámetro obligatorio. "≥1" = el endpoint exige al menos un parámetro.

## Referencia (LEVEL 0)

| # | Path | Propósito | Parámetros | Paginación | Notas |
|---|---|---|---|---|---|
| 1 | `/timezone` | zonas horarias válidas para `timezone` | ninguno | no | no se actualiza nunca |
| 2 | `/countries` | países disponibles | `name`, `code` (2–6), `search` (=3) | no | `name`/`code` usables como filtro en otros endpoints; todos combinables |
| 3 | `/leagues` | ligas y copas **+ objeto `coverage`** | `id`, `name`, `country`, `code`, `season`, `team`, `type` (league\|cup), `current` (true\|false), `search` (≥3), `last` (≤2) | no | **la unidad más valiosa del catálogo**: una llamada da todas las ligas × temporadas con sus flags |
| 4 | `/leagues/seasons` | años disponibles | ninguno | no | temporada = clave de 4 dígitos; 2018 significa 2018-19 |
| 5 | `/teams/countries` | países con equipos | ninguno | no | — |
| 6 | `/odds/bookmakers` | catálogo de casas | `id`, `search` (=3) | no | ids usables como filtro en `/odds` |
| 7 | `/odds/bets` | catálogo de mercados **pre-match** | `id`, `search` (=3) | no | **no compatible con `/odds/live`** |
| 8 | `/odds/live/bets` | catálogo de mercados **in-play** (137) | `id`, `search` (=3) | no | **no compatible con `/odds`** |
| 9 | `/status` | plan, consumo, suscripción | ninguno | no | **no consume cuota** |

## Metadatos de partido (LEVEL 1)

| # | Path | Propósito | Parámetros | Paginación | Notas |
|---|---|---|---|---|---|
| 10 | `/teams` | equipos | `id`, `name`, `league`, `season`, `country`, `code` (=3), `venue`, `search` (≥3) | no | ≥1; todos combinables |
| 11 | `/teams/seasons` | temporadas de un equipo | `team` REQ | no | — |
| 12 | `/teams/statistics` | agregados de temporada de un equipo | `league` REQ, `season` REQ, `team` REQ, `date` | no | `date` = calcular hasta esa fecha. 3.9.3 añade Goals Over/Under |
| 13 | `/venues` | estadios | `id`, `name`, `city`, `country`, `search` (≥3) | no | ≥1; todos combinables |
| 14 | `/standings` | clasificaciones | `league`, `season` REQ, `team` | no | varias tablas por año posibles (grupos, apertura/clausura) |
| 15 | `/fixtures/rounds` | jornadas | `league` REQ, `season` REQ, `current`, `dates`, `timezone` | no | `dates=true` (3.9.3) añade fechas de cada jornada |
| 16 | `/fixtures` | **el partido** | `id`, `ids` (≤20), `live` (all\|id-id), `date`, `league`, `season`, `team`, `last` (≤2), `next` (≤2), `from`, `to`, `round`, `status` (uno o varios), `venue`, `timezone` | no | **con `id`/`ids` devuelve events + lineups + statistics + players en la misma respuesta**; con `live` devuelve events |
| 17 | `/fixtures/headtohead` | enfrentamientos directos | `h2h` REQ (`ID-ID`), `date`, `league`, `season`, `last`, `next`, `from`, `to`, `status`, `venue`, `timezone` | no | — |

## Eventos de partido (LEVEL 2)

| # | Path | Propósito | Parámetros | Paginación | Notas |
|---|---|---|---|---|---|
| 18 | `/fixtures/statistics` | 16 estadísticas por equipo | `fixture` REQ, `team`, `type`, `half` | no | **`half=true` solo desde la temporada 2024** |
| 19 | `/fixtures/events` | goles, tarjetas, cambios, VAR | `fixture` REQ, `team`, `player`, `type` | no | **VAR desde 2020-21** |
| 20 | `/fixtures/lineups` | formación, XI, banquillo, rejilla, colores | `fixture` REQ, `team`, `player`, `type` | no | disponibles **20–40 min antes** si la liga lo cubre; si no, después del partido con retraso variable |
| 21 | `/fixtures/players` | estadísticas por jugador y partido | `fixture` REQ, `team` | no | incluye `rating` del proveedor |

Los cuatro son **redundantes con `/fixtures?ids=`** salvo en vivo (ver `11_LIVE_ENDPOINT_PLAN.md`).

## Jugadores y plantillas (LEVEL 3)

| # | Path | Propósito | Parámetros | Paginación | Notas |
|---|---|---|---|---|---|
| 22 | `/injuries` | ausencias (lesión, sanción, duda) | `league`, `season` (REQ con league/team/player), `fixture`, `team`, `player`, `date`, `ids` (≤20 **fixtures**), `timezone` | no | ≥1; **solo desde abril 2021**; dos tipos: Missing Fixture / Questionable |
| 23 | `/players` | estadísticas de jugador por liga-temporada | `id`, `team`, `league`, `season`, `search` (≥4), `page` | **sí, 20/página** | `season` requiere id/league/team; `search` requiere league o team |
| 24 | `/players/profiles` | ficha de todos los jugadores | `player`, `search` (≥4), `page` | **sí, 250/página** | nuevo en 3.9.3 |
| 25 | `/players/seasons` | temporadas con estadísticas | `player` | no | — |
| 26 | `/players/squads` | plantilla actual de un equipo | `team`, `player` | no | ≥1; **solo plantilla actual**, no histórica |
| 27 | `/players/teams` | equipos de la carrera de un jugador | `player` REQ | no | nuevo en 3.9.3 |
| 28 | `/coachs` | entrenadores y su carrera | `id`, `team`, `search` (≥3) | no | — |
| 29 | `/transfers` | traspasos | `player`, `team` | no | — |
| 30 | `/trophies` | títulos | `player`, `players` (≤20), `coach`, `coachs` (≤20) | no | lotes de 20 desde 3.9.3 |
| 31 | `/sidelined` | historial de bajas | `player`, `players` (≤20), `coach`, `coachs` (≤20) | no | lotes de 20 desde 3.9.3 |
| 32–35 | `/players/topscorers`, `/topassists`, `/topyellowcards`, `/topredcards` | 20 mejores | `league` REQ, `season` REQ | no | derivables de `/fixtures?ids=` |

## Mercado (LEVEL 4) y vivo (LEVEL 5)

| # | Path | Propósito | Parámetros | Paginación | Notas |
|---|---|---|---|---|---|
| 36 | `/odds` | cuotas pre-partido | `fixture`, `league`, `season`, `date`, `timezone`, `page`, `bookmaker`, `bet` | **sí, 10/página** | **solo 1–14 días antes; historia de 7 días**; actualiza cada 3 h |
| 37 | `/odds/mapping` | qué fixtures tienen cuotas | `page` | **sí, 100/página** | ahorra pedir `/odds` de partidos sin precio |
| 38 | `/odds/live` | cuotas en juego | `fixture`, `league`, `bet` | no | fixtures presentes entre T-15 y T-5 min y hasta 5–20 min tras el final; **sin historia**; `status.blocked`/`suspended`/`main` por valor |
| 39 | `/fixtures?live=` | marcador en vivo + eventos | `live=all` o `live=id-id` | no | misma operación 16, modo vivo |

## Estados de partido (tabla oficial completa)

`TBD` · `NS` (Scheduled) — `1H` `HT` `2H` `ET` `BT` `P` `SUSP` `INT` `LIVE` (In Play) —
`FT` `AET` `PEN` (Finished) — `PST` (Postponed) · `CANC` (Cancelled) · `ABD` (Abandoned) ·
`AWD` (Technical Loss) · `WO` (WalkOver) (Not Played).

`HT` está documentado como *"Finished in the regular time"*, lo cual es un error de la
documentación: es el descanso. `LIVE` se usa *"in very rare cases"* cuando no hay minuto ni mitad.
`TBD`, `PST` y `CANC` se revisan y actualizan a diario.
