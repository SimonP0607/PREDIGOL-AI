# Modelo de coste en peticiones

Clases: **CHEAP** ≤ 1/día global · **MODERATE** 1 por liga-temporada · **EXPENSIVE** 1 por partido
o por equipo · **VERY_EXPENSIVE** paginado o por jugador.

## 1. Coste unitario

| Endpoint | Unidad natural | Peticiones | Clase |
|---|---|---:|---|
| `/timezone`, `/countries`, `/leagues/seasons`, `/teams/countries` | global | 1 | CHEAP |
| `/leagues` (sin filtro) | **todo el catálogo** | **1** | CHEAP |
| `/odds/bets`, `/odds/live/bets`, `/odds/bookmakers` | global | 1 | CHEAP |
| `/status` | global | **0** (no cuenta) | CHEAP |
| `/fixtures?league&season` | liga-temporada | 1 | MODERATE |
| `/standings`, `/fixtures/rounds`, `/injuries?league&season`, `/teams?league&season` | liga-temporada | 1 | MODERATE |
| **`/fixtures?ids=`** | **20 partidos** | **1** | MODERATE |
| `/fixtures?id=` | 1 partido | 1 | EXPENSIVE |
| `/fixtures/statistics\|events\|lineups\|players` | 1 partido cada uno | **4 por partido** | EXPENSIVE |
| `/predictions` | 1 partido | 1 | EXPENSIVE |
| `/odds?fixture=` | 1 partido, 1 instante | 1 (≈1 página) | EXPENSIVE |
| `/teams/statistics` | equipo-liga-temporada | 1 (×20 equipos) | EXPENSIVE |
| `/players?league&season` | liga-temporada | **~25** (20/página) | VERY_EXPENSIVE |
| `/players/profiles` | catálogo global | **miles** (250/página) | VERY_EXPENSIVE |
| `/transfers`, `/trophies`, `/sidelined`, `/coachs` | por jugador/entrenador | 1 (lotes de 20 en trophies/sidelined) | VERY_EXPENSIVE a escala |

## 2. El multiplicador que decide todo

```
detalle de partido CON ids=  :  1 petición / 20 partidos  = 0,05 por partido
detalle de partido SIN ids=  :  4 peticiones / partido    = 4,00 por partido
                                                            ────────────────
                                                            ×80
```

Sobre la migración completa: **9.565 peticiones con `ids=` frente a 754.764 sin él** (×79). El
total pasa de 11.611 a 756.810 (×65). Es la diferencia entre horas y meses.

**Verificado disponible en esta cuenta el 29 sep 2026.**

## 3. Coste de la migración histórica (cobertura verificada)

643 competición-temporadas · 190.313 partidos · 72 competiciones.

| Unidad | Peticiones | % |
|---|---:|---:|
| `fixture_details` (lotes de 20) | 9.565 | 82,4 % |
| `teams_season` | 643 | 5,5 % |
| `standings_season` | 632 | 5,4 % |
| `fixtures_season` | 624 | 5,4 % |
| `injuries_season` | 146 | 1,3 % |
| `league_coverage` | 1 | 0,0 % |
| **Total** | **11.611** | |
| **Con margen del 35 %** | **15.675** | |

Por tier: **T1 1.119 · T2 4.925 · T3 5.566**.
Opcional (`players_season`): +22.536 → 34.147 en total (46.099 con margen).

**Almacenamiento:** medido 3,8 KB/partido comprimido para el detalle (la estimación era 7 KB) →
el almacén raw rondará **~700 MB** para las 72 competiciones, no 1,3 GB.

## 4. Días de backfill por plan

Disponible/día = cuota × 0,90 − vivo_medio × 1,35.

| Plan | Cuota/día | Con `ids=` | Sin `ids=` |
|---|---:|---:|---:|
| Free | 100 | nunca | nunca |
| Pro | 7.500 | **2,5 días** | 163,9 días |
| **Ultra (nuestro)** | 75.000 | **0,2 días** (unas horas) | 15,3 días |
| Mega | 150.000 | 0,1 días | 7,6 días |

Con Ultra y `ids=`, **el backfill completo cabe en una tarde**. El cuello de botella deja de ser
la cuota y pasa a ser el ritmo por minuto y el tiempo de normalización.

## 5. Coste de la operación en vivo

Modelo: temporada repartida en 280 días, el día más cargado concentra el 35 % de los partidos de
la semana.

| Alcance | Competiciones | Partidos/temporada | Día medio | Día pico |
|---|---:|---:|---:|---:|
| Tiers 1–2 | 36 | 11.023 | **384** | **819** |
| Tiers 1–3 | 72 | 21.265 | 736 | 1.572 |

Desglose del día pico (tiers 1–2): cuotas pre-partido 579 · near-close 96 · alineaciones 40 ·
detalle post-partido 20 · lesiones 36 · clasificaciones 36 · syncs 12.

**Holgura con Ultra:** (75.000 − 819 × 1,35) / 75.000 = **98,5 %** con tiers 1–2, **97,2 %** con
las 72. La operación en vivo no es el problema; nunca lo fue.

## 6. Lo que NO vamos a gastar

| Endpoint | Coste si lo hiciéramos | Por qué no |
|---|---:|---|
| `/players?league&season` en 643 temporadas | ~16.000 | las estadísticas por partido ya vienen en `ids=`; el agregado de temporada es derivable |
| `/players/profiles` completo | miles | solo aporta foto y fecha de nacimiento |
| `/teams/statistics` por equipo-temporada | ~12.800 | 100 % derivable de nuestros propios partidos |
| `/predictions` por partido | 190.313 | no es nuestra fuente de probabilidades |
| `/fixtures/headtohead` | 1 por par | derivable de `core.fixtures` |
| `/players/topscorers` × 4 | 2.572 | derivable de `fixture_player_stats` |

Total evitado: **~220.000 peticiones** que no compran ninguna funcionalidad que no tengamos.
