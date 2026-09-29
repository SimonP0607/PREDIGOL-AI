# Cobertura histórica real

La pregunta no es "¿hay histórico?" sino "¿desde cuándo, para qué liga y con qué granularidad?".

## 1. Fronteras temporales duras (declaradas por el proveedor)

| Dato | Desde | Fuente textual |
|---|---|---|
| **Cuotas pre-partido** | **T-14 días, historia de 7 días** | *"We provide pre-match odds between 1 and 14 days before the fixture. We keep a 7-days history"* |
| **Cuotas en vivo** | **nunca** | *"No history is stored"* |
| **Lesiones** | **abril 2021** | *"Being a new endpoint, the data is only available from April 2021"* |
| **Eventos VAR** | **2020-21** | *"VAR events are available from the 2020-2021 season"* |
| **Estadísticas por mitad** | **2024** | *"Data start from 2024 season for half parameter"* |
| **Rejilla y colores de alineación** | 3.8.1 (2023) | changelog; *"As a new feature, some irregularities may occur"* |
| Temporadas de jugadores | 1966 en el ejemplo oficial | `/players/seasons` — pero con enormes huecos |

**Consecuencia inmediata:** pedir `/injuries` para 2018, 2019 o 2020 gasta peticiones y devuelve
vacío. Nuestro `config/migration.yaml` ya lo evita con `since_season: 2020`, que deberíamos
ajustar a **2021**.

## 2. Lo que decide de verdad: `coverage` por liga-temporada

`/leagues` devuelve, para **cada temporada de cada liga**, once banderas:

```
fixtures.events · fixtures.lineups · fixtures.statistics_fixtures · fixtures.statistics_players
standings · players · top_scorers · top_assists · top_cards · injuries · predictions · odds
```

Tres advertencias oficiales, todas importantes:

1. *"The values returned by the coverage indicate the data available **at the moment you call the
   API**, so for a competition that has not yet started, it is normal to have all the features set
   to False."* → la cobertura de la temporada en curso se mide mal si se consulta pronto.
2. *"The coverage of a competition can vary from season to season and **values set to True do not
   guarantee 100% data availability**."* → `true` es condición necesaria, no suficiente. La
   validación por tier (§8 del plan de migración) no es opcional.
3. *"Some competitions, such as the friendlies, are exceptions to the coverage indicated in the
   leagues endpoint."* → los amistosos mienten en las dos direcciones.

**Medido en nuestra cuenta (29 sep 2026):** 8.751 filas (liga, temporada). Para las 72
competiciones de nuestro plan: **643 competición-temporadas verificadas, 0 sin verificar** — 69
competiciones con 9 temporadas (2018–2026), Libertadores y Sudamericana con 8 (2019–2026),
Conference League con 6 (2021–2026).

## 3. Granularidad por categoría

| Categoría | Profundidad | Depende de liga | Limitado por plan | Completo o parcial |
|---|---|---|---|---|
| Fixtures + marcadores | la que diga `seasons[]` de cada liga | sí | **sí en Free** (±1 día); sin límite en Ultra | completo donde hay temporada |
| Events | ≥ temporada con `events:true`; VAR ≥ 2020-21 | sí | no | parcial: VAR es reciente |
| Lineups | `lineups:true` | sí | no | parcial: en ligas menores llegan tras el partido |
| Fixture statistics | `statistics_fixtures:true`; mitades ≥ 2024 | sí | no | parcial |
| Player statistics | `statistics_players:true` | sí | no | parcial |
| Standings | `standings:true` | sí | no | completo; varias tablas por año |
| Injuries | **≥ abril 2021** y `injuries:true` | sí | no | parcial por definición |
| Odds | **14 días / 7 de historia** | sí (`odds:true`) | no | **inexistente como histórico** |
| Transfers / Trophies / Sidelined | carrera completa declarada | no | no | sin fecha de corte publicada |
| Predictions | solo partidos con datos suficientes | sí | no | no es histórico, es pronóstico vigente |

## 4. Qué significa para el backfill

- **Lo que se puede reconstruir hoy:** fixtures, resultados, eventos, alineaciones, estadísticas
  de equipo y de jugador, clasificaciones, para 643 competición-temporadas.
- **Lo que nunca se podrá reconstruir:** el precio que tenía un partido de 2019. Ese histórico
  viene de Football-Data.co.uk (ya importado: 345.964 cuotas, 5.329 partidos) y solo cubre las
  ligas que ese archivo publica.
- **Lo que se degrada hacia atrás:** lesiones (nada antes de 2021), VAR (nada antes de 2020-21),
  mitades (nada antes de 2024). Cualquier feature que los use tiene que declarar su ventana, no
  rellenar con ceros.
- **Nuestra serie de cuotas propia empieza el 25 sep 2026.** Todo lo anterior es de terceros. Eso
  es un hecho permanente del proyecto, no una fase.
