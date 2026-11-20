# PM-13-03 · Paquetes de partido guardados solo cuando cambian (BE-065)

Plan Maestro PM, ola 2, bloque 13 (higiene de base). Interruptor `FBI_PACKET_STORE_STABLE`, **apagado** por omisión. No borra ni
cambia ninguna fila (`ai.match_packets` es de solo añadido).

## El defecto

`store_packet` (`fbi.ai.packet`) ya reutiliza el último paquete del partido cuando su huella es la misma. Pero la huella cambiaba en
cada construcción: el bloque `schedule.calendar` lleva `home.age_hours` y `away.age_hours`, las horas desde que se leyó el calendario
de cada equipo, con un decimal. La regla del propio módulo dice que un paquete no lleva campos de edad («las edades se calculan al
leerlo»); esos dos se colaron con `packet-v7`.

## Medido antes (20-nov-2026, solo lectura)

| Medida | Valor |
| --- | --- |
| `ai.match_packets` | 2,8 GB (427 MB de tabla, el resto TOAST), 226.000 filas |
| Paquetes nuevos al día (6 a 19-nov) | 1.527 a 13.339 (17 a 159 MB) |
| Versiones por partido jugado en los 7 días anteriores | 65,4 (438 partidos, 28.625 paquetes) |
| Tamaño medio de un paquete reciente | 12,9 kB |
| Bloque que cambia frente al paquete anterior (400 últimos) | `schedule` en los 400; **solo** `schedule` en 186 |
| Iguales al anterior sin los dos `age_hours` (1.496 últimos) | **695 (46,5 %)** |
| Hueco entre versiones (p10 / p50 / p90) | 15 / 75 / 195 min |

## El cambio

Con el interruptor encendido, antes de insertar se compara el paquete con el último guardado del partido **sin los dos `age_hours`**
(`stable_hash`). Si son iguales, se devuelve el id de esa fila, igual que cuando la huella entera coincide. Lo demás cuenta: cualquier
otro campo, la versión del paquete y la lista `missing`. Solo se compara con el **último** paquete, así que la última fila sigue siendo
siempre el contexto actual.

- Lo que la IA lee no cambia: el constructor no se toca y la pasada usa el paquete que construyó.
- La fila reutilizada conserva el `age_hours` de cuando se guardó; la edad al leerla es `as_of` menos `fetched_at`, que el paquete lleva.
- La cadencia del ciclo (`_free`: cada 1 h el mismo día, cada 3 h si falta más de un día) leía el `as_of` del último paquete guardado.
  Un paquete reutilizado no lo mueve, así que el ciclo pregunta también a `last_built`, que recuerda en el proceso del worker la última
  construcción respondida con un paquete ya guardado. Sin eso, un partido sin cambios se reconstruiría cada 15 minutos. Tras reiniciar
  el worker la memoria empieza vacía: como mucho, una construcción de más por partido.

Ahorro esperado: alrededor del 46 % de las filas nuevas (≈ 30–75 MB al día según el calendario). Es la medida de una muestra, no una
garantía: se mide tras encender.

## Encendido (con el kit auditado, PM-15-03 o cuando el dueño lo decida)

1. Copia fechada: `cp /etc/predigol/app.env /etc/predigol/app.env.before-pm1303-$(date -u +%Y%m%dT%H%MZ)`.
2. `FBI_PACKET_STORE_STABLE=on` en `/etc/predigol/app.env` y `predigolctl up` (hay que reiniciar el worker).
3. Fuera de copias (03:30–05:00 UTC), de `fixtures_sync` (03:55, 09:55, 15:55, 21:55 UTC) y de cadenas de despliegue.

## Comprobación (solo lectura)

```
SELECT built_at::date d, count(*) packets, count(DISTINCT fixture_id) fx,
       round(count(*)::numeric / count(DISTINCT fixture_id), 1) per_fx
  FROM ai.match_packets WHERE id > (SELECT max(id) FROM ai.match_packets) - 140000
   AND built_at >= now() - interval '14 days' GROUP BY 1 ORDER BY 1;
```

Antes y después del encendido, con días de calendario parecido. También: `ai_cycle` sigue anotando `packets_not_due` (la cadencia no se
rompió) y `predigolctl status` sin avisos nuevos.

## Reversión

`FBI_PACKET_STORE_STABLE=off` (o quitar la línea) y `predigolctl up`. Nada guardado cambia. Si hace falta, PR de `revert`.

## Cierre

Siete días encendido sin incidentes, versiones por partido antes y después, memoria del worker antes y después (PM-13-05) y el
documento de estado actualizado.

## Consultas calientes y autovacuum (segunda parte de PM-13-03)

`pg_stat_statements` desde el 9-nov-2026 (20-nov, solo lectura), por tiempo total:

| # | Consulta | Llamadas | Media | Total |
| --- | --- | --- | --- | --- |
| 1 | `INSERT INTO core.fixture_facts … NOT EXISTS (… core.fixture_facts_latest …)` (`fbi.ingestion.fixture_facts`) | 807.211 | 171,9 ms | 38,5 h |
| 2 | `WITH made AS (… models.predictions …), newest AS …` (lectura de predicciones por partido) | 11,75 M | 5,3 ms | 17,2 h |
| 3 | lectura lateral de `market.odds_snapshots` por casa, mercado, selección y línea | 11,68 M | 3,9 ms | 12,5 h |

La primera recorre la vista `core.fixture_facts_latest` entera (`DISTINCT ON` de 271.606 filas, 483 ms en un `EXPLAIN ANALYZE`) para
mirar un solo partido: se corrige en el segundo PR de BE-065. Las otras dos ya usan índices (98–99 % en caché); lo que pesa es el
número de llamadas, y bajarlo es cambiar a lecturas por lotes en código de otras zonas: queda propuesto, no hecho.

Autovacuum: las tres tablas de este bloque son de solo añadido (0 actualizaciones y 0 borrados) y el autovacuum por inserciones corre
(`ai.match_packets`, 18 veces; último el 19-nov). No se cambia ningún umbral.
