# PM-05-02 · Relleno nocturno de las mitades de 2024 a 2026 (guía de seguimiento)

Plan Maestro PM, ola 3. Código del relleno: BE-098 (`scripts/period_backfill.py`); endurecimiento y seguimiento: OPS-027.
Interruptor: `FBI_STATS_BY_PERIOD_FILL` (encendido el 25-nov-2026 12:00 UTC con el kit `pm-switch-20261124`).

## Qué es

Un proceso aparte (`python -m scripts.period_backfill run --scheduled`) que lanza el planificador del worker. Pide
`GET /fixtures/statistics?fixture=&half=true` una vez por partido terminado desde el 1-ene-2024 de las competiciones que la matriz de
disponibilidad gradúa A o B en córners, los más nuevos primero, a 1,5 s entre peticiones (≈ 28 al minuto medidas), y guarda las cuatro
filas por partido (`core.fixture_team_stats_period`) y su fila de pregunta (`core.fixture_period_asks`, canal `backfill`). Lo ya pedido
no se vuelve a pedir: el relleno **se reanuda solo** donde quedó, también tras un reinicio del worker.

## Cómo está contenido (todo medido)

| Qué | Valor | Dónde |
| --- | --- | --- |
| Memoria del proceso | tope de espacio de direcciones 384 MiB, `oom_score_adj` 1000 (el núcleo lo mata a él primero), `nice` 10, un hilo de BLAS, 2 arenas de `malloc`; pico medido 61,7 MiB | `cap_memory` |
| Margen que pide el worker para arrancarlo | 128 MiB libres en el contenedor (el doble del pico) | `period_stats.FILL_HEADROOM_MIB` |
| Tiempo en la base de datos | `statement_timeout` 60 s (300 s en `plan` y `report`) | `main` |
| Horario | 22:30 a 03:25 UTC; nunca 03:30–05:00 (copias a las 03:50) | `Guard` |
| Tope de la noche | 5.000 peticiones desde las 22:30, sumando todos los arranques | `night_room` |
| Tope del día UTC | 5.000 (`raw.provider_endpoint_usage`, job `period_backfill`) | `Guard` |
| Presupuesto del proveedor | para al 60 % del presupuesto interno (36.000 de 60.000) o al llegar a la reserva de emergencia (7.000), lo que ocurra antes | `Guard.total_limit` |
| Carril `historicos` (8.000) | para a 100 del techo; los lunes deja a la ronda semanal de jugadores (`historical_backfill`, desde las 00:10 UTC; 6.616 el 23-nov) sus 6.700, así que el lunes el relleno pide como mucho 1.200 | `Guard.lane_reserve` |
| Orden de parada | archivo `PARAR_period_backfill` o `SIGTERM` (ver abajo) | `Guard.stop_ordered` |
| Reintentos | a las 22:30, a las :10 de las 23, 0, 1 y 2, y 4 minutos después de cada arranque del worker dentro del horario; uno a la vez | `scheduler` |

El carril `ampliacion` (sondas de ligas nuevas, 5.000) y `historicos` pausan los dos al 60 % del presupuesto: si el día se acerca a ese
punto se detienen juntos y la reserva de emergencia queda para las vitales.

## Orden de parada (sin reiniciar nada)

```
docker exec predigol-worker touch /app/data/raw/PARAR_period_backfill     # para en la siguiente petición; los arranques siguientes no hacen nada
docker exec predigol-worker rm /app/data/raw/PARAR_period_backfill          # lo deja seguir en el siguiente arranque
docker exec predigol-worker pkill -TERM -f scripts.period_backfill           # lo mismo, por señal: termina la petición en curso y cierra su fila
```

Lo ya guardado se conserva. Apagar `FBI_STATS_BY_PERIOD_FILL` (y `predigolctl up`) lo detiene también, pero recrea el worker.

## Seguimiento (solo lectura)

```
docker exec predigol-worker python -m scripts.period_backfill plan      # lo que queda, noches y fecha de fin estimada
docker exec predigol-worker python -m scripts.period_backfill report    # por competición: pedidos, con las dos mitades, % de éxito, % ya pedido
```

Cada noche: la fila `period_backfill` de `raw.ingestion_runs` (`params.report`, `memory_peak_mib`, `seconds`, `guard` con el motivo de
parada), el total del día en `raw.provider_quota`, el carril en `raw.provider_endpoint_usage` y la memoria del contenedor.

## Criterios de la ficha

* Relleno terminado: `plan` da `left = 0` (o solo las competiciones «cerradas» por la regla DM-13).
* Porcentaje de éxito por competición, para publicarlo en la matriz: `report`.
* Cierre: siete noches medidas con duración y `memory.peak`, sin incidentes.
