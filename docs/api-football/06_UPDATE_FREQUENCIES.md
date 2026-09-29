# Frecuencias de actualización

Dos columnas distintas y no hay que confundirlas: **cada cuánto cambia el dato en el proveedor**
y **cada cuánto tiene sentido que lo pidamos nosotros**. La segunda depende de para qué lo
usamos, no solo de la primera.

## 1. Tabla oficial + nuestra decisión

| Dataset | Frecuencia del proveedor | Llamadas recomendadas (proveedor) | **Nuestro sondeo** |
|---|---|---:|---|
| `/timezone` | nunca | 1 cuando haga falta | una vez, en el arranque |
| `/countries` | al añadir un país nuevo | 1/día | 1/mes |
| `/leagues` (+coverage) | varias veces al día | 1/hora | **1/semana** + 1 antes de cada tier |
| `/leagues/seasons` | al añadir una liga | 1/día | 1/mes |
| `/teams`, `/venues`, `/teams/countries` | varias veces/semana | 1/día | 1 por liga-temporada, en el backfill |
| `/teams/statistics` | 2/día | 1/día con partido, si no 1/semana | no se usa (derivable) |
| `/standings` | **cada hora** | 1/hora con partido en juego, si no 1/día | **1/día** por liga seguida |
| `/fixtures/rounds` | cada día | 1/día | 1 por liga-temporada |
| `/fixtures` | **cada 15 s** | 1/min con partido en juego, si no 1/día | **12/día** (sync) + 1/min en vivo |
| `/fixtures?live=` | cada 15 s | 1/min | **1/min** solo con partido seguido en juego |
| `/fixtures/headtohead` | cada 15 s | 1/min / 1/día | no se usa (derivable de nuestro histórico) |
| `/fixtures/statistics` | **cada minuto** | 1/min en juego, si no 1/día | 1 post-partido vía `ids=` |
| `/fixtures/events` | **cada 15 s** | 1/min en juego, si no 1/día | 1/min en vivo; 1 post-partido vía `ids=` |
| `/fixtures/lineups` | **cada 15 min** | 1/15 min en juego, si no 1/día | **2 sondeos** en T-45…T-20 |
| `/fixtures/players` | cada minuto | 1/min en juego, si no 1/día | 1 post-partido vía `ids=` |
| `/injuries` | **cada 4 h** | 1/día | **1/día** por liga seguida |
| `/predictions` | cada hora | 1/hora | no se usa en producción |
| `/coachs`, `/transfers`, `/trophies`, `/sidelined` | varias veces/semana | 1/día | no se usa hoy |
| `/players`, `/players/profiles`, `/players/squads`, `/players/teams` | varias veces/semana | 1/día–1/semana | opcional, fuera del backfill por defecto |
| `/odds` (pre) | **cada 3 h** | **1 cada 3 h** | **6 ventanas** T-72h…T-3h |
| `/odds/mapping` | cada día | 1/día | 1/día si activamos pre-filtro |
| `/odds/live` | **cada 5 s** (rango 5–60 s) | — | **1 near-close** en T-15…T-5 |
| `/odds/bets`, `/odds/live/bets`, `/odds/bookmakers` | varias veces/semana | 1/día | 1/mes |
| `/status` | — | — | 1/día (gratis) |

## 2. Por qué no sondeamos a la frecuencia del proveedor

**Las cuotas pre-partido se refrescan cada 3 horas.** Pedirlas cada 30 minutos devuelve el mismo
precio seis veces y gasta seis peticiones. Nuestras 6 ventanas (T-72h, T-48h, T-24h, T-12h, T-6h,
T-3h) están alineadas con esa cadencia: cada una cae en un ciclo distinto del proveedor.

**Las alineaciones salen entre 20 y 40 minutos antes.** Un solo sondeo puede caer antes de que
existan. Dos (T-45 y T-20) cubren la ventana sin desperdiciar.

**El marcador en vivo cambia cada 15 segundos pero nuestro pipeline no.** No operamos in-play: el
near-close es la última decisión. Sondear el marcador cada minuto solo sirve para el timeline de
la UI, y eso puede esperar al post-partido.

**El detalle post-partido se pide una vez, en lote.** `/fixtures?ids=` con 20 partidos sustituye
80 peticiones a los cuatro endpoints dedicados. La única razón para usarlos sueltos es en vivo.

## 3. La advertencia que gobierna todo

> *"If you exceed your allowed request rate per minute, either through continuous excessive usage
> or by generating abnormal traffic spikes, your access may be temporarily or permanently blocked
> by our firewall without prior notice."*

No es solo la cuota diaria. Un backfill que dispare 450 peticiones en un minuto de forma sostenida
es exactamente "abnormal traffic spike". Nuestro `TokenBucket` reparte, y para el backfill
conviene quedarse holgadamente por debajo del límite del plan en vez de pegarse a él.

## 4. Latencia real que hay que asumir

> *"Not all competitions have livescore available and only have final result. In this case, the
> status remains in NS and will be updated in the minutes/hours following the match (this can take
> up to 48 hours, depending on the competition)."*

Un partido en `NS` una hora después del pitido **no es un fallo nuestro**. Puede tardar 48 horas.
Por eso el sync de resultados mira hacia atrás y por eso la UI dice "awaiting result" en vez de
inventar. En Ultra, mirar 3 días atrás cuesta 3 peticiones y cierra el problema.
