# PM-04-04 · Profundidad de la referencia por nivel de cobertura y prioridad (BE-063)

Plan Maestro PM, bloque 4 (peticiones e ingesta). Interruptor **`FBI_REFERENCE_DEPTH`**, apagado por defecto: apagado, todas las
competiciones son `completa` y la referencia pide exactamente lo de antes. Sin migración, sin tablas ni permisos nuevos; 0 peticiones.
Construye sobre la matriz de disponibilidad (PM-02-03, `analytics.coverage_cells` y `analytics.market_availability`) y sobre los
recortes de PM-04-03 (`PM_04_03_RECORTES_DE_BARRIDOS.md`): aquí entra la parte «`/players` solo P0 a P2» que allí no se pudo hacer.

## Regla (ficha, campo 6)

| Profundidad | Cuándo | Qué pide la referencia por equipo o persona |
| --- | --- | --- |
| `completa` | P0 o P1, o nivel A o B | todo lo de hoy: plantilla, entrenador, traspasos, perfiles que faltan, trofeos, bajas históricas (`/sidelined`), trayectorias (`/players/teams`) y `/players` de temporada (si es P0–P2) |
| `media` | nivel C | plantilla, entrenador, traspasos y perfiles que faltan; `/players` de temporada si es P0–P2 |
| `minima` | nivel D, o sin muestra (`MI`) o sin medir, sin P0/P1 | plantilla (`/players/squads`) y entrenador (`/coachs`) |

* **Nivel** de una competición: el resumen (`fbi.coverage.levels.summary_level`) de su última temporada con muestra, el mismo que enseña
  el directorio de C-16. Una competición que la matriz aún no ha medido cuenta como `MI`: un lote nuevo es `minima` hasta que la pasada
  nocturna lo mida (salvo P0/P1). Una competición **sin prioridad y sin fila** es `completa` (nada se sabe, nada se baja).
* **Prioridad**: `backend/config/coverage/prioridad_editorial.yaml` (anexo A aprobado; 226 competiciones con id). Se cambia por PR.
* Un equipo o una persona que juega en varias competiciones seguidas toma la más profunda; un amistoso o una competición no seguida no
  cuenta.
* Lo que no cambia con ninguna profundidad: plantillas, entrenadores (`coachs`, `coachs_by_id`), listas de temporada (rondas,
  goleadores), predicciones, estadísticas de equipo, estadios, catálogos de cuotas.
* La matriz se lee una vez por pasada de la referencia (caché de 1 h). El worker pasa `fbi.coverage.depth.current` a
  `refresh_reference` y a `seed_player_seasons`; la ingesta no importa `fbi.coverage` (regla de arquitectura).

## Antes de encenderlo (solo lectura, 0 peticiones)

```
docker exec predigol-api python -m scripts.reference_refresh --depths   # profundidad de cada competición seguida, nivel y prioridad
docker exec predigol-api python -m scripts.reference_refresh --plan     # lo pendiente por feed (con el interruptor como esté)
```

Comprobar que `without_row` es 0 para las competiciones seguidas (la primera pasada completa de la matriz es la del domingo
22-nov-2026; las incrementales solo miden las que jugaron en 48 h). Una competición seguida que hoy funciona y saliera `minima` por falta
de fila se rebajaría sin dato: no encender hasta que todas tengan fila.

## Encendido y vuelta atrás

Kit auditado (PM-15-03): copia fechada de `app.env`, `FBI_REFERENCE_DEPTH=on`, `predigolctl up`. Vuelta atrás: `off` (o quitar la
línea) y `predigolctl up`; no hay nada que deshacer en la base (solo deja de pedir; lo guardado se conserva).

## Medida del criterio de aceptación

«Los lotes nuevos de nivel D gastan menos de 5 peticiones por equipo en el primer llenado.» Con `minima` se piden 2 por equipo en la
referencia y la plantilla (entrenador y plantilla); se cuenta con el contador por endpoint (PM-01-02) el primer día de un lote
(lotes 5 a 9, PM-03-01):

```
SET default_transaction_read_only = on; SET statement_timeout = '60s';
SELECT usage_date, job, endpoint, sum(requests) FROM raw.provider_endpoint_usage
 WHERE usage_date >= '<día de alta del lote>' AND usage_date < '<día de alta>'::date + 2
   AND job IN ('reference_refresh', 'backfill') GROUP BY 1, 2, 3 ORDER BY 1, 4 DESC;
```

Dividir lo de `/coachs`, `/transfers`, `/trophies`, `/sidelined`, `/players/teams`, `/players/profiles` y `/players/squads` por los
equipos nuevos del lote. Ahorro esperado (ficha, campo 13): ≈ 69.000 peticiones del primer llenado de los lotes 5 a 9 (supuesto de
120 por equipo).
