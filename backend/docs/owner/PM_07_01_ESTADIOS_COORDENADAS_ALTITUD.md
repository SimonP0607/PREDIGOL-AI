# PM-07-01 · ¿Están cargadas las coordenadas y la altitud de los estadios?

Plan Maestro PM, ola 1. Medición de solo lectura del **20-nov-2026, 01:35–01:38 UTC** (backend `75dbfec880cd`, migración 0167),
0 peticiones. Código del PR que deja esta guía: OPS-010.

## Respuesta corta

**No.** El código de AD-H04 (IA-076, `fbi/venues/`, migración 0144) está en producción, pero **nunca se ejecutó la carga**:

| Tabla o vista | Filas |
|---|---:|
| `core.venues` (estadios del proveedor) | 7.161 |
| `core.venue_geo_loads` (cargas de Wikidata) | **0** |
| `core.venue_geo` / `core.venue_geo_live` (coordenadas y altitud) | **0** |
| `core.fixture_venue_links` (estadio deducido de partidos sin id) | **0** |
| `core.venue_review_queue` / `_decisions` | 0 / 0 |

No hay instantánea de Wikidata en el servidor (`/srv/lab/venues/` no existe). Por tanto el **0 %** de los estadios tiene
coordenadas y altitud, en todas las prioridades editoriales (P0 a P3).

## Lo que sí hay: partidos con estadio identificado

Partidos de las competiciones seguidas, no cancelados, con saque entre hace 365 días y dentro de 14 (`core.fixture_venue_resolved`):

| Prioridad | Competiciones | Partidos | Con estadio | % | Estadios distintos |
|---|---:|---:|---:|---:|---:|
| P0 Colombia | 2 | 715 | 337 | 47,1 | 24 |
| P1 internacionales | 20 | 3.324 | 404 | 12,2 | 191 |
| P2 países prioritarios | 58 | 14.881 | 7.786 | 52,3 | 741 |
| P3 resto | 47 | 18.004 | 5.407 | 30,0 | 559 |
| **Total** | 127 | 36.924 | 13.934 | 37,7 | 1.309 |

De los 22.990 sin estadio, 13.519 traen el nombre del estadio sin su id (los resolvería `venue_geo link`, aún no ejecutado) y
9.471 no traen nada. En los próximos 14 días: 575 de 1.366 partidos tienen estadio del proveedor (42 %). Por competición:
Primera A 258 de 425, Primera B 79 de 290, Champions 61 de 297, Libertadores 5 de 155, Premier 371 de 400 (detalle en la
evidencia del plan, `reports/plan/ejecucion/PM-07-01.md`).

## Consulta reproducible

```
docker exec predigol-postgres psql -U postgres -d fbi -c "SET default_transaction_read_only=on" -c "SET statement_timeout='90s'" -c "
SELECT (SELECT count(*) FROM core.venues) venues, (SELECT count(*) FROM core.venue_geo_loads) loads,
       (SELECT count(*) FROM core.venue_geo_live WHERE latitude IS NOT NULL) with_coords,
       (SELECT count(*) FROM core.venue_geo_live WHERE elevation_m IS NOT NULL) with_elevation,
       (SELECT count(*) FROM core.fixture_venue_links) links"
```

o, con el mismo resultado y en JSON, `docker exec predigol-worker python -m scripts.venue_geo status` (solo lee).
El desglose por competición usa `core.fixture_venue_resolved` unido a `core.venue_geo_live` por `venue_id`.

## Qué sigue

PM-07-02 (cascada de coordenadas con procedencia y precisión por fila) depende de esta medición y de la captura de la licencia
de Wikidata por el dueño (DM-09). La carga se hace con los pasos de `scripts/venue_geo.py` (`fetch` → `load --dem --apply` →
`link --apply`), que escriben: van en su propia tarea, no en esta.

## Vuelta atrás

No hay nada que revertir: la medición solo lee.
