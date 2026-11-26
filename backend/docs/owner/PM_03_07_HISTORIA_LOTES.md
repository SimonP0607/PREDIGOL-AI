# PM-03-07 · Historia de las competiciones nuevas (OPS-019, Plan Maestro PM)

**Qué es.** Sin historia no hay Elo, forma ni frecuencias en las competiciones que se dieron de alta con los lotes 3 a 9 de `config/expansion.yaml`.
Esta guía carga esa historia con el planificador de migración que ya existe (`scripts.migration`), por lotes, **sin llaves ni privilegios nuevos y
sin tocar el trabajo en vivo**. El único cambio de código es la opción `--depth N` de `plan`, `capacity` y `seed` (OPS-019).

**Decisión DM-03 (Plan Maestro PM, aprobada el 19-nov-2026).** Dos temporadas de historia en las prioridades P0 a P2: la temporada en curso
más las dos completadas anteriores (hoy 2026, 2025 y 2024), es decir `--depth 2`. Sin `--depth` el plan carga las ocho de los primeros niveles
(`seasons.target_depth`), que no es lo decidido para estas competiciones. La pirámide inglesa 5 a 7 (lote 9, prioridad P4) queda **sin
historia** salvo orden nueva del dueño.

## 1. Cómo se carga (por lote, de noche, 0 peticiones hasta el paso 3)

Todo dentro del contenedor del worker (`docker exec -w /app predigol-worker …`). Nivel de migración de cada lote: lote 3 = 7, lote 4 = 8,
lote 5 = 9, lote 6 = 10, lote 7 = 11, lote 8 = 12, lote 9 = 13.

1. **Precio** (lee la base y los flags del proveedor; no pide nada):
   `python -m scripts.migration plan --tiers <N> --depth 2`. Muestra temporadas, partidos y peticiones por tipo de unidad y comprueba nombres.
2. **Sembrar** (escribe las unidades pendientes; no pide nada; se puede repetir, no duplica):
   `python -m scripts.migration seed --tiers <N> --depth 2 --yes`.
3. **Gastar**: lo hace solo el `historical_backfill` del worker (cada hora), que procesa las unidades pendientes con lo que sobra después de la
   reserva de lo vivo (`live_reserve`) y con un máximo de 1.500 por pasada. Es el carril `historicos` (techo 8.000 al día, el planificado
   de referencia es 6.533 el lunes). Se siembra **de noche (21:00 a 03:00 UTC)** y **un lote por noche**, y nunca dentro de 03:30–05:00 UTC.
4. **Seguir**: `python -m scripts.migration status` (unidades hechas/pendientes por nivel), `python -m scripts.quota_lanes report --days 2`
   (carril `historicos` del día contra su techo) y `python -m scripts.capture_odds status` (contador del día).
5. **Validar** (solo base de datos): `python -m scripts.availability_refresh --only <ids internos de las competiciones del lote>` para que la
   matriz de cobertura vea los partidos nuevos, y `python -m scripts.validate_history` (una pasada completa, hasta 10 min) fuera de
   `fixtures_sync` y de las copias. Criterio de aceptación: sin partidos terminados con estado incoherente en esas competiciones.

## 2. Reglas de cada noche

* Antes de sembrar: `capture_odds status` y `quota_lanes report` deben mostrar el día por debajo del 80 % del límite del plan y ningún carril
  limitado; si no, se espera a la noche siguiente.
* Si `plan --depth 2` da más de ≈ 3.000 peticiones para un lote (un tercio del techo de `historicos`), no se siembra esa noche: se anota la cifra y se decide con el coordinador (el mayor hasta hoy, el lote 5, cuesta 721 con las ocho temporadas).
* No se siembra con una cadena de despliegue en curso, ni a menos de 20 minutos de una `fixtures_sync` (`:58`).
* Reversión: las lecturas no dejan nada que deshacer; las unidades pendientes se pueden detener dejando de sembrar. No se borra nada.

## 3. Estado

Ver el informe `ejecucion/PM-03-07.md` del plan (cifras de cada lote, horas UTC y peticiones gastadas).
