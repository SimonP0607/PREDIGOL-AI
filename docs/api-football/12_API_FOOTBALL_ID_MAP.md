# Catálogos de ids

No se copian miles de ids a Markdown. Los catálogos grandes viven donde se pueden consultar; aquí
está el mapa de dónde está cada cosa y lo que hay que saber de memoria.

## 1. Dónde vive cada catálogo

| Catálogo | Tamaño | Dónde | Cómo se actualiza |
|---|---:|---|---|
| Ligas × temporadas + cobertura | **8.751 filas** | `raw.league_coverage` (base de datos) | `/leagues` sin filtros, 1 petición |
| Nuestras 72 competiciones | 72 | `config/migration.yaml` | a mano, verificado con NAME CHECK |
| Competiciones catalogadas | 77 | `core.competitions` | importadas del sistema heredado + `/leagues` |
| **Casas de apuestas** | **33** | `catalogues/bookmakers.json` | `/odds/bookmakers`, 1 petición |
| **Mercados pre-match** | **338** | `catalogues/bets_prematch.json` | `/odds/bets`, 1 petición |
| **Mercados in-play** | **266** | `catalogues/bets_inplay.json` | `/odds/live/bets`, 1 petición |
| Equipos, jugadores, sedes | decenas de miles | dashboard del proveedor (sección *Ids*) | no los replicamos |

Los tres JSON se bajaron el 29 sep 2026 y sus payloads están indexados con linaje
(`f4286cbf1698`, `e16a16747fcc`, `db92283b3562`).

## 2. Ids de mercado que usamos (pre-match)

| bet id | Nombre del proveedor | Nuestra clave | Estado en V2 |
|---:|---|---|---|
| 1 | Match Winner | `1X2` | ✅ capturado |
| 5 | Goals Over/Under | `OU` | ✅ capturado |
| 8 | Both Teams Score | `BTTS` | ✅ capturado |
| 12 | Double Chance | `DC` | ✅ capturado |
| **4** | **Asian Handicap** | `AH` | ⚠️ **se parsea y se descarta**: no hay fila en `market.markets` |
| 2 | Home/Away | — | no se usa |
| 13 | First Half Winner | — | no se usa |
| 6 / 26 | Goals O/U 1ª / 2ª parte | — | no se usa |
| 10 | Exact Score | — | no se usa |

**338 mercados existen; nosotros escribimos 4 a mano.** El más interesante de los que faltan es el
**4 (Asian Handicap)**, porque permite derivar probabilidades implícitas 1X2 con menos margen que
el 1X2 directo. Ya lo estamos pidiendo y tirando en cada captura.

## 3. Casas relevantes (de las 33)

| id | Nombre | Papel |
|---:|---|---|
| **4** | **Pinnacle** | el baseline. Es el cierre contra el que se mide todo |
| 3 | Betfair | exchange: casi sin margen, útil como verdad alternativa |
| 2 | Marathonbet | sharp |
| 5 | SBO | sharp asiática |
| 8 | Bet365 | volumen |
| 11 | 1xBet | volumen |
| 7 | William Hill | volumen |
| 32 | Betano | volumen |
| 36 | BetVictor | volumen |

En la captura real del 25 sep aparecieron **9 casas** para un partido de Segunda: exactamente
estas. `market.bookmakers` tiene 33 filas del backup heredado y los campos `is_sharp` y
`consensus_weight` **nunca se han escrito** — se llenan a mano o no significan nada.

## 4. Los dos catálogos de bets son incompatibles

Textual: los ids de `/odds/bets` *"can be used in endpoint odds as filters, but are **not
compatible** with endpoint odds/live"*, y al revés. Un id de in-play usado en pre-match no da
error: **devuelve vacío**. Es una fuente de bugs silenciosos y por eso los guardamos en ficheros
separados con nombres distintos.

## 5. Ids que no replicamos, y por qué

- **Equipos y jugadores:** decenas de miles, estables de por vida (*"teams keep it among all the
  leagues"*, *"players keep it among all the teams"*). Llegan dentro de cada fixture; no hace
  falta un catálogo aparte.
- **Sedes:** llegan dentro del fixture.
- **Entrenadores:** llegan dentro de la alineación.

Lo único que sí conviene bajar algún día es `/players/profiles` para poner nombre a los 605.363
`provider_player_id` que ya tenemos colgando sin entidad (ver `09_V2_GAP_ANALYSIS.md`, P2).
