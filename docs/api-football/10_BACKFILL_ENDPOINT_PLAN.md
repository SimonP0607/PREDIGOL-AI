# Qué descargamos en el backfill — y para qué

Regla: **si nadie puede nombrar la funcionalidad que usa un dato, no se descarga.**

## 1. Tier 1 — obligatorio

| Unidad | Endpoint | Peticiones | ¿Qué funcionalidad lo usa? |
|---|---|---:|---|
| `league_coverage` | `/leagues` | 1 | decide todas las demás unidades; sin esto se planifica a ciegas |
| `fixtures_season` | `/fixtures?league&season` | 1/temporada | **todo**: Elo, Poisson, Dixon-Coles, pi-ratings, features, backtesting, Match Center |
| `fixture_details` | `/fixtures?ids=` (≤20) | 1/20 partidos | shares de tiros y tiros a puerta (fv2), forma residual, xG-lite, modelo con alineaciones, timeline de la UI |
| `standings_season` | `/standings` | 1/temporada | contexto de liga en features; página Analytics; validación cruzada del número de partidos |
| `injuries_season` | `/injuries?league&season` | 1/temporada **≥2021** | fuerza sensible a bajas (P1 del roadmap) |

**Total tier 1 (6 competiciones × 9 temporadas): 1.120 peticiones.**
**Total tiers 1–3 (72 competiciones): 11.611** (15.675 con margen del 35 %).

## 2. Lo que sale del tier obligatorio

| Unidad | Estado | Motivo |
|---|---|---|
| `teams_season` (`/teams`) | **fuera hasta que exista normalizador** | hoy gasta 643 peticiones y escribe **0 filas**. Bajarlo sin normalizador es gastar por nada. Cuando exista, es P2: da país, año de fundación, sede y escudo. |
| `players_season` (`/players`) | **fuera** | ~25 peticiones por liga-temporada (paginado 20) para un agregado que ya es derivable del detalle por partido |
| `/fixtures/rounds` | fuera | `league.round` ya viene en cada fixture |
| `/teams/statistics` | fuera | 100 % derivable |
| `/predictions` | fuera de producción | RESEARCH_ONLY |
| `/players/topscorers` y hermanos | fuera | derivables |
| `/fixtures/headtohead` | fuera | derivable de `core.fixtures` |
| `/odds` histórico | **imposible** | 7 días de historia. Viene de Football-Data.co.uk |
| `/transfers`, `/trophies`, `/sidelined`, `/coachs`, `/venues`, `/players/profiles`, `/players/squads` | fuera | ninguna funcionalidad planificada los usa hoy |
| `/countries`, `/timezone`, `/leagues/seasons`, `/teams/countries` | fuera | referencia que no necesitamos persistir |

## 3. Catálogos: 3 peticiones que sí valen la pena

| Endpoint | Peticiones | Para qué |
|---|---:|---|
| `/odds/bookmakers` | 1 | sustituir `market.bookmakers` del backup heredado por el catálogo real |
| `/odds/bets` | 1 | saber qué mercados pre-match existen; hoy tenemos 4 escritos a mano y tiramos el hándicap asiático |
| `/odds/live/bets` | 1 | mismo problema en in-play; catálogo distinto e incompatible |

**Se hacen una vez, antes del tier 2.** Son la condición previa para arreglar el hueco P1 del
hándicap asiático.

## 4. Orden de ejecución

```
1. league_coverage            (1 petición)      → verifica el plan
2. catálogos de mercado       (3 peticiones)    → bookmakers + bets + live bets
3. tier 1: fixtures_season    → expande a fixture_details automáticamente
4. tier 1: fixture_details    → el 82 % del coste
5. tier 1: standings + injuries
6. VALIDACIÓN DE CALIDAD      (§8 del plan de migración) + backup
7. features + walk-forward + reproducción + comparación con el mercado
8. tier 2, validación, backup
9. tier 3, validación, backup
```

Cada unidad es una fila en `raw.backfill_tasks` con estado. Se puede apagar el PC y continuar:
una unidad `running` huérfana más de 30 minutos se reanuda sola.

## 5. Validación antes de pasar al siguiente tier

- Número de partidos por temporada contra `results`/`paging` del proveedor y contra los partidos
  jugados de la clasificación.
- 0 partidos `finished` sin fila de resultado.
- Goles de eventos = marcador final (salvo partidos adjudicados).
- Tiros a puerta ≤ tiros; posesión local + visitante = 100 ± 1.
- 11 titulares por lado; minutos coherentes con cambios y rojas.
- Cada fila normalizada apunta a un payload cuyo fichero re-hashea.
- **Nuevo:** registrar los `unknown_stat_types` en vez de solo loguearlos, y marcar los valores
  incoherentes en vez de anularlos en silencio.

## 6. Reajustes que este análisis obliga a hacer en `config/migration.yaml`

| Clave | Ahora | Debería ser | Por qué |
|---|---|---|---|
| `injuries_season.since_season` | 2020 | **2021** | el proveedor no tiene nada antes de abril de 2021 |
| `teams_season` | `PRODUCT_REQUIRED`, se planifica | **fuera hasta que haya normalizador** | escribe 0 filas |
| `players_season` | `OPTIONAL` | igual, pero documentar que es derivable | — |
| `details_per_fixture_kb` | 7 (estimado) | **3,8 (medido)** | sonda del 29 sep |
| — | — | añadir `odds_catalogues` (3 peticiones) | arreglar el hueco del hándicap asiático |

**Ninguno de estos cambios se ha aplicado todavía**: esta misión era entender, no implementar.
