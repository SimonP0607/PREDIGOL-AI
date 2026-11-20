# PM-04-03 · Recortar los barridos que nadie lee (BE-062)

Plan Maestro PM, bloque 4 (peticiones e ingesta), ola 2. Interruptor **`FBI_REFERENCE_TRIMS`**, apagado por defecto: apagado, todo
es exactamente como antes. Sin migración, sin tablas ni permisos nuevos. Complementa los carriles (PM-04-01/02,
`PM_04_CARRILES_DEL_CUPO.md`): los techos del plan para la referencia (9.000) y los históricos (6.000) solo caben con estos recortes.

## Qué cambia con el interruptor encendido

| Barrido | Antes | Con `FBI_REFERENCE_TRIMS=on` | ¿Quién lo lee? |
| --- | --- | --- | --- |
| `/predictions` | 3 lecturas por partido (48 h, 24 h y 3 h antes) | **1**, al entrar en las 48 h (un partido visto más tarde se pide una vez al verse) | Solo el panel de administración «Predicción del proveedor» (`center.provider_prediction`, «Admin only»); ningún modelo (una prueba lo impide) |
| `/teams/statistics` | Diaria si el equipo juega en < 24 h; semanal si no | **Semanal** para todos | Nadie en el producto: `core.team_season_stats` solo lo leen la auditoría de contraste (`fbi.api.audits.team_stats`) y el registro de la verdad |
| `/players` (agregado de temporada) | Semanal, todas las competiciones a la vez (lunes) | **Mensual**, cada competición en su día del mes (`provider_league_id % 28 + 1`), nunca a menos de 20 días de la anterior | Página de jugador «según el proveedor» y el paquete de Intelligence (las plantillas): **conservan todos sus campos**, con un dato de hasta un mes |
| Ronda de plantillas (`/players/squads`) | Semanal, todos los equipos el lunes | Semanal, **repartida en los siete días** (`provider_team_id % 7`: un séptimo el lunes y otro cada día; un día perdido se recupera al siguiente) | Página de equipo, Intelligence: mismo volumen, sin el pico del lunes |

Lo que **no** se recorta: ningún campo, ninguna tabla, ningún endpoint que lea una pantalla. El contrato de la página de jugador y el del
panel del proveedor no cambian (no se toca la API).

## Por qué estos y no otros

Inventario del 19-nov (`03_inventario_api_football.md`): `/players` es la suma del detalle por partido que ya se guarda (unos 30
campos sin lector); `/teams/statistics` lo calcula PrediGol con sus partidos; `/predictions` es la opinión del proveedor. La restricción
«/players solo P0 a P2» de la ficha **queda para PM-04-04**: la prioridad editorial (P0–P4) vive en el anexo A del plan y en la matriz
de PM-02-03, no en el código; aquí se recorta la frecuencia para todas.

## Antes (medido el 20-nov-2026 07:33 UTC, solo lectura)

| Barrido | Medida | Al día |
| --- | --- | --- |
| `/predictions` | 1.407 lecturas en 7 días (513 a 48 h, 459 a 24 h, 435 a 3 h) | ≈ 201 |
| `/teams/statistics` | 8.905 objetivos; 8.664 consultados en 7 días (pico el martes 17-nov: 3.929) | ≈ 1.270 + las diarias de quien juega |
| `/players` | 3.831 páginas la semana 47 (3.200 la 40; crece con las competiciones) | ≈ 547 |
| `/players/squads` | 2.878 equipos la semana 47, todos el lunes | ≈ 411 (todo el lunes) |

## Ahorro esperado (estimado con lo de arriba; se mide con el contador)

| Barrido | Ahorro |
| --- | --- |
| `/predictions` | ≈ 128 al día (2 de cada 3 lecturas) |
| `/teams/statistics` | las lecturas diarias de los equipos que juegan en < 24 h: ≈ 150–300 al día |
| `/players` | ≈ 420 al día (de semanal a mensual) |
| **Total** | **≈ 700–850 al día** (la ficha estimaba 800–1.500 sin medir por endpoint) |

Además desaparece el pico del lunes: `/players` y plantillas sumaban ≈ 6.700 peticiones el lunes (el carril de históricos, 6.533 el
16-nov); con los recortes, ≈ 130 + 411 al día repartidos.

## Medir antes y después con el contador (PM-01-02)

`raw.provider_endpoint_usage` cuenta cada petición por endpoint desde el 20-nov 05:42 UTC. Siete días completos con el interruptor
apagado (21 a 27-nov) son el **antes**; siete días tras encenderlo, el **después**:

```sql
SET default_transaction_read_only = on;
SELECT usage_date, endpoint, sum(requests)
  FROM raw.provider_endpoint_usage
 WHERE endpoint IN ('/predictions', '/teams/statistics', '/players', '/players/squads')
   AND usage_date >= current_date - 14
 GROUP BY 1, 2 ORDER BY 1, 2;
```

Criterio de aceptación: el ahorro medido así y ninguna pantalla sin su dato (la página de jugador sigue con sus campos «según el
proveedor»; el panel del proveedor tiene su lectura desde las 48 h).

## Encender y volver atrás

Copia fechada de `/etc/predigol/app.env`, añadir `FBI_REFERENCE_TRIMS=on`, `predigolctl up` (el worker lo lee al pedir cada barrido).
Apagar: `off` (o quitar la línea) y `predigolctl up`. Al apagar, todo vuelve al calendario anterior: la siguiente ronda semanal de
`/players` sale con su generación semanal.

Seguimiento: el mensaje del panel de administración vacío dice «se pide a 48, 24 y 3 h»; con el recorte es «a 48 h». Está en
`fbi/api/services/center.py` (zona compartida): se corrige cuando se encienda el interruptor, con su reserva de zona.

## Cuotas de 240, 299 y 667 (PM-01-04): la causa no estaba en la captura

La sonda de PM-01-04 (20-nov 06:43 UTC) clasificó Primera B (240), Primera División de Venezuela (299) y Amistosos de clubes (667)
como «no se pidió». Medido el 20-nov 07:11 UTC (solo lectura):

| Competición | Terminados en 30 días | Pedidos | Por qué no se pidieron los demás |
| --- | --- | --- | --- |
| 240 | 32 | 4 | Seguida desde el **17-nov 13:52 UTC** (lote 3); sus filas de partido se crearon a las 16:12, después de que se jugaran los 28 anteriores. Los 4 partidos que estaban en la base a tiempo (19 y 20-nov) se pidieron y tenían cuotas |
| 299 | 21 | 0 | Igual: seguida desde el 17-nov; los 21 se jugaron antes. Desde entonces ya se piden (primera petición el 18-nov 21:34) |
| 667 | 72 | 40 | Los 32 sin pedir son amistosos que el proveedor **publicó después de jugarse** (filas creadas el 17-nov 10:54 para partidos del 4 al 15-nov) o a 4 minutos del saque (12-nov). Los 40 que llegaron a tiempo se pidieron todos |

La captura (`scripts/capture_odds.py`, zona Cuotas) **no tiene defecto**: pide todo partido seguido que está en la base a tiempo.
El error estaba en la medida: la sonda contaba como «no pedidos» partidos que no se podían pedir. Este PR corrige la sonda
(`scripts/coverage_probe.py`, BE-053 del mismo plan): solo cuentan los partidos cuya fila llegó a la base al menos 60 min antes del
saque; los demás se cuentan aparte («N terminados entraron tarde en la base») y, si son todos, la causa es `entraron_tarde`. Con esta
regla, las tres competiciones pasan a `coincide`. La repetición de la sonda del 26/27-nov ya lo usará.
