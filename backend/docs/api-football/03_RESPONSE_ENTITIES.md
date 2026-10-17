# Entidades de respuesta

Estructura de las respuestas que nos importan y **qué id permite enlazar con qué**. Los campos
listados son los que aparecen en la documentación oficial y/o los que nuestros normalizadores
(`src/fbi/providers/api_football/`) leen de payloads reales.

Envoltorio común de toda respuesta:

```
{ get, parameters{}, errors[] | {}, results, paging{current,total}, response[] }
```

`errors` llega como **lista vacía** cuando todo va bien y como **objeto** (`{"plan": "..."}`,
`{"requests": "..."}`) cuando hay problema — dentro de un HTTP 200.

## Fixture — `/fixtures`

```
Fixture
├── fixture   { id, referee, timezone, date, timestamp,
│               periods{first,second}, venue{id,name,city},
│               status{long,short,elapsed,extra} }        ← extra: nuevo en 3.9.3
├── league    { id, name, country, logo, flag, season, round, standings }  ← standings: 3.9.3
├── teams     { home{id,name,logo,winner}, away{…} }
├── goals     { home, away }                               ← marcador FINAL (incluye prórroga)
└── score     { halftime{}, fulltime{}, extratime{}, penalty{} }
```

**Con `id` o `ids` la respuesta añade, para cada partido:** `events[]`, `lineups[]`,
`statistics[]`, `players[]` — los mismos objetos que devuelven los cuatro endpoints dedicados.

**Clave para nosotros:** `goals` es el marcador tras prórroga. El marcador de 90 minutos —el que
liquida 1X2, O/U y BTTS— es `goals − extratime`. Ya está resuelto en la migración 0020.

| Enlace | Campo |
|---|---|
| → League | `league.id` + `league.season` |
| → Team | `teams.home.id`, `teams.away.id` |
| → Venue | `fixture.venue.id` |
| ← todo lo de partido | `fixture.id` |

## Events — `/fixtures/events` o inline

```
Event { time{elapsed,extra}, team{id,name,logo},
        player{id,name}, assist{id,name},
        type, detail, comments }
```

`type` ∈ `Goal` · `Card` · `subst` · `Var`.
`detail` ∈ Normal Goal, Own Goal, Penalty, Missed Penalty, Yellow Card, Red card,
Substitution N, Goal cancelled, Penalty confirmed.
**VAR solo desde 2020-21.** El orden del array es la secuencia del partido: lo preservamos como
`seq` porque el proveedor no da un id de evento.

## Lineups — `/fixtures/lineups` o inline

```
Lineup { team{id,name,logo,colors{player{primary,number,border},goalkeeper{…}}},
         formation, coach{id,name,photo},
         startXI[ {player{id,name,number,pos,grid}} ],
         substitutes[ {player{…}} ] }
```

`grid` es `"X:Y"`: X = línea desde la portería, Y = de izquierda a derecha. El **coach viene aquí
y solo aquí** dentro del detalle de partido (`/coachs` es el endpoint de carrera).

## Statistics (equipo) — `/fixtures/statistics` o inline

```
TeamStats { team{id,name,logo}, statistics[ {type, value} ] }
```

16 tipos oficiales: Shots on Goal, Shots off Goal, Shots insidebox, Shots outsidebox, Total Shots,
Blocked Shots, Fouls, Corner Kicks, Offsides, Ball Possession, Yellow Cards, Red Cards,
Goalkeeper Saves, Total passes, Passes accurate, Passes %.

`value` es heterogéneo: entero, `null`, o cadena con `%` (posesión, pases %). `Passes %` es
derivable y no lo guardamos. Con `half=true` (**desde 2024**) llegan además los parciales.

## Players (por partido) — `/fixtures/players` o inline

```
FixturePlayers { team{…}, players[ { player{id,name,photo},
                 statistics[ { games{minutes,number,position,rating,captain,substitute},
                               offsides, shots{total,on}, goals{total,conceded,assists,saves},
                               passes{total,key,accuracy}, tackles{total,blocks,interceptions},
                               duels{total,won}, dribbles{attempts,success,past},
                               fouls{drawn,committed}, cards{yellow,red},
                               penalty{won,commited,scored,missed,saved} } ] } ] }
```

`statistics` es un array pero en el contexto de un partido tiene un solo elemento.
`rating` es del proveedor, calculado contra jugadores de la misma posición — **caja negra**: si se
usa como feature, hay que calibrarlo antes, no consumirlo crudo.

## Standings — `/standings`

```
Standing { league{ id, name, country, season,
           standings[[ { rank, team{id,name,logo}, points, goalsDiff, group, form,
                         status, description,
                         all{played,win,draw,lose,goals{for,against}},
                         home{…}, away{…}, update } ]] } }
```

`standings` es **array de arrays**: un grupo por sub-array. `home`/`away` son desgloses que hoy
ignoramos. `description` dice la consecuencia de la posición (Champions, descenso…).

## Injuries — `/injuries`

```
Injury { player{id,name,photo,type,reason},
         team{id,name,logo}, fixture{id,timezone,date,timestamp},
         league{id,season,name,country,logo,flag} }
```

`type` ∈ `Missing Fixture` · `Questionable`. **Desde abril 2021.**

## Odds pre-match — `/odds`

```
Odds { league{…}, fixture{id,timezone,date,timestamp}, update,
       bookmakers[ { id, name, bets[ { id, name,
                     values[ {value, odd} ] } ] } ] }
```

## Odds in-play — `/odds/live`

```
LiveOdds { fixture{id,status{elapsed,seconds}}, league{…},
           teams{home{id,name,goals},away{…}},
           status{stopped, blocked, finished},
           update,
           odds[ { id, name, values[ {value, odd, handicap, main, suspended} ] } ] }
```

Diferencias que importan: aquí sí hay `handicap`, `main` (cuál de dos valores idénticos vale) y
`suspended` por valor, más `status.blocked` a nivel de partido. **No hay `bookmakers`**: es un
agregado. Y **no hay historia**.

## Leagues + coverage — `/leagues`

```
League { league{id,name,type,logo},
         country{name,code,flag},
         seasons[ { year, start, end, current,
                    coverage{ fixtures{events,lineups,statistics_fixtures,statistics_players},
                              standings, players, top_scorers, top_assists, top_cards,
                              injuries, predictions, odds } } ] }
```

**Una sola llamada sin parámetros devuelve el catálogo entero**: en nuestra cuenta, 8.751 filas
(liga, temporada) con sus flags. Es la unidad que hace que todo lo demás sea planificable.

## Predictions — `/predictions`

```
Prediction { predictions{ winner{id,name,comment}, win_or_draw,
                          under_over, goals{home,away}, advice, percent{home,draw,away} },
             league{…}, teams{home{…,last_5{…},league{…}}, away{…}},
             comparison{form,att,def,poisson_distribution,h2h,goals,total},
             h2h[ …fixtures… ] }
```

Declarado por el proveedor: *"The predictions are made using several algorithms including the
poisson distribution, comparison of team statistics, last matches, players etc… **Bookmakers odds
are not used to make these predictions**"*. Eso lo hace interesante como tercer punto de
comparación y **descalificado** como fuente de nuestras probabilidades.

## Ids que cosen el grafo

| Id | Estable | Aparece en |
|---|---|---|
| `fixture.id` | *"The fixtures ids are unique and specific to each fixture. In no case an ID will change."* | fixtures, events, lineups, statistics, players, injuries, odds, predictions, h2h |
| `league.id` | *"unique… and leagues keep it across all seasons"* | leagues, fixtures, standings, teams, players, injuries, odds |
| `team.id` | *"unique… teams keep it among all the leagues/cups"* | teams, fixtures, standings, lineups, events, statistics, transfers, squads |
| `player.id` | *"unique… players keep it among all the teams"* | players, lineups, events, injuries, transfers, trophies, sidelined |
| `coach.id` | — | coachs, lineups, trophies, sidelined |
| `venue.id` | *"unique in the API"* | venues, teams, fixtures |
| `bookmaker.id` | — | odds, odds/bookmakers |
| `bet.id` | **dos catálogos incompatibles** | odds/bets (pre) vs odds/live/bets (in-play) |
