# Matriz de parámetros

Qué endpoint acepta qué. **No se extrapola entre endpoints**: un nombre igual no significa el
mismo comportamiento. `R` obligatorio · `•` opcional · vacío = no existe ahí.

## 2.1 Los parámetros transversales

| Param | leagues | teams | teams/stats | venues | standings | fixtures | f/h2h | f/stats | f/events | f/lineups | f/players | injuries | players | odds | odds/live |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| `id` | • | • | | • | | • | | | | | | | • | | |
| `ids` | | | | | | • ≤20 | | | | | | • ≤20 | | | |
| `league` | | • | R | | • | • | • | | | | | • | • | • | • |
| `season` | • | • | R | | **R** | • | • | | | | | •¹ | •² | • | ✗³ |
| `team` | • | | R | | • | • | | • | • | • | • | • | • | | |
| `player` | | | | | | | | | • | • | | • | | | |
| `fixture` | | | | | | | | R | R | R | R | • | | • | • |
| `date` | | | • | | | • | • | | | | | • | | • | |
| `from`/`to` | | | | | | • | • | | | | | | | | |
| `next`/`last` | •⁴ | | | | | • ≤2 | • | | | | | | | | |
| `live` | | | | | | • | | | | | | | | | |
| `round` | | | | | | • | | | | | | | | | |
| `status` | | | | | | • | • | | | | | | | | |
| `venue` | | • | | | | • | • | | | | | | | | |
| `timezone` | | | | | | • | • | | | | | • | | • | |
| `page` | | | | | | | | | | | | | • 20 | • 10 | |
| `search` | • ≥3 | • ≥3 | | • ≥3 | | | | | | | | | • ≥4⁵ | | |
| `bookmaker` | | | | | | | | | | | | | | • | |
| `bet` | | | | | | | | | | | | | | • | • |
| `type` | • | | | | | | | • | • | • | | | | | |
| `code` | • | • | | | | | | | | | | | | | |
| `country` | • | • | | • | | | | | | | | | | | |
| `current` | • | | | | | | | | | | | | | | |
| `half` | | | | | | | | • | | | | | | | |

¹ `/injuries`: `season` es **obligatorio cuando se usa `league`, `team` o `player`**.
² `/players`: `season` **requiere** `id`, `league` o `team`.
³ `/odds/live`: la documentación marca `league` con *"In this endpoint the season parameter is..."*
  — el filtro de temporada no aplica porque solo hay partidos en curso.
⁴ `/leagues` solo tiene `last` (≤2 caracteres, "las X últimas ligas añadidas"), no `next`.
⁵ `/players`: `search` (≥4) **requiere** `league` o `team`. `/players/profiles`: `search` ≥4 suelto.

## 2.2 Límites de lote

| Endpoint | Parámetro | Máximo | Formato |
|---|---|---|---|
| `/fixtures` | `ids` | **20** | `id-id-id` |
| `/injuries` | `ids` | **20** (ids de *fixtures*) | `id-id-id` |
| `/trophies` | `players`, `coachs` | **20** cada uno | `id-id-id` |
| `/sidelined` | `players`, `coachs` | **20** cada uno | `id-id-id` |
| `/fixtures` | `live` | sin máximo documentado | `all` o `id-id` (ids de liga) |
| `/fixtures`, `/fixtures/headtohead` | `status` | varios | `NS` o `NS-PST-FT` |

El único `ids` que nos interesa hoy es el de `/fixtures`, y está **verificado en nuestra cuenta**:
devuelve los 4 bloques de detalle para los 20 partidos.

## 2.3 Combinabilidad declarada

| Endpoint | Lo que dice la documentación |
|---|---|
| `/countries` | *"All the parameters of this endpoint can be used together"* |
| `/leagues` | *"Most of the parameters… can be used together"* |
| `/teams` | *"All… can be used together"* · **requiere ≥1** |
| `/venues` | *"All… can be used together"* · **requiere ≥1** |
| `/standings` | *"Most…"* |
| `/injuries` | *"All… can be used together"* · **requiere ≥1** |
| `/fixtures` | ejemplos oficiales mezclan `date+league+season`, `league+next`, `venue+next`, `league+last+status`, `team+last+timezone`, `team+season+from+to`, `league+season+round` |
| `/players/squads` | **requiere ≥1** (`team` → plantilla; `player` → equipos) |
| `/teams/seasons`, `/players/teams`, `/predictions`, `/fixtures/*` | **requieren ≥1** obligatorio concreto |

## 2.4 Paginación real

Solo cuatro endpoints paginan, y con tamaños distintos:

| Endpoint | Resultados/página | Consecuencia |
|---|---|---|
| `/players` | **20** | una liga-temporada de ~500 jugadores = ~25 peticiones |
| `/players/profiles` | **250** | el catálogo entero de jugadores son miles de páginas |
| `/odds` | **10** | un partido con muchas casas puede ocupar más de una página |
| `/odds/mapping` | **100** | — |

Todo lo demás devuelve `paging {current:1, total:1}`. **Nuestro cliente pagina `/odds` hasta 10
páginas como red de seguridad**; medido, un partido cabe en una.

## 2.5 Trampas

1. **`season` es un entero de 4 dígitos** y significa la temporada que *empieza* ese año:
   2018 = 2018-19. Una liga de año natural (MLS, Brasil) usa el mismo esquema.
2. **`status` acepta varios valores unidos por guion**, igual que `ids`. No es una lista CSV.
3. **`date`, `from`, `to` son `YYYY-MM-DD`**; el `timezone` cambia a qué día pertenece un partido
   nocturno. Si se mezclan zonas entre peticiones, el mismo partido puede aparecer en dos días.
   Nosotros pedimos siempre en UTC y no pasamos `timezone`.
4. **`type` en `/fixtures/statistics` filtra por nombre de estadística** (`type=Total Shots`), no
   por categoría.
5. **`/odds/bets` y `/odds/live/bets` tienen catálogos de ids distintos e incompatibles.** Un id
   de bet de in-play no vale en pre-match ni al revés. Confundirlos devuelve vacío, no error.
