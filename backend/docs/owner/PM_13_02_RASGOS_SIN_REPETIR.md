# PM-13-02 · Conjuntos de rasgos sin repetir tras cada despliegue (BE-064)

Plan Maestro PM, ola 2, bloque 13 (higiene de base). Interruptor `FBI_FEATURE_SETS_BY_MODEL_CODE`, **apagado** por omisión. No borra
ni cambia ninguna fila: solo deja de escribir conjuntos repetidos hacia adelante.

## El defecto

El pronóstico de la tubería de picks (`fbi.predictions.forecast`) guarda un conjunto nuevo de rasgos de un partido salvo que el último
guardado tenga la misma huella de entradas (`input_hash`) **y** el mismo `code_version`. Ese `code_version` era el commit del
repositorio, que cambia en cada despliegue aunque solo se toque una página o una guía. Tras cada despliegue, la primera pasada volvía
a escribir el vector de cada partido próximo, con las mismas entradas y los mismos valores, y sus 43 filas en
`features.fixture_features` (la tabla mayor de la base: 4,4 GB, 43,6 millones de filas el 20-nov-2026).

## Medido antes (20-nov-2026, 06:50 UTC, solo lectura)

| Periodo (por `data_cutoff`) | Conjuntos `fv2.1.0` | Misma huella que el anterior, otro commit | % |
| --- | --- | --- | --- |
| 6 a 20-nov (14 días y medio) | 125.054 | 11.776 | 9,4 % |
| 17 a 20-nov (4 a 14 despliegues al día) | 32.139 | 5.852 | 18,2 % |

Con la misma huella **y** el mismo commit no hay ninguno: esa repetición ya la evitaba el código. Crecimiento de la tabla de valores:
entre 130.000 y 430.000 filas al día (43 por conjunto). Linaje antes del cambio: las 1.000 últimas predicciones `elo_ologit` en
tiempo real tienen todas un conjunto guardado con su `feature_set_hash`.

## El cambio

Con el interruptor encendido, la tubería (`fbi.picks.feature_code`) le dice al pronóstico, como `code_version`, el **primer commit que
ejecutó el código de modelos vigente**: el `code_version` de la versión más antigua de `models.model_versions` cuyo nombre termina en
`@<model_code_version>`. Mientras no exista ninguna versión de ese código de modelos, el commit actual. El código de modelos
(`fbi.core.version.MODEL_PACKAGES`: `models`, `features`, `predictions`, `backtesting`, `domain`) es el que calcula los rasgos, así que:

- un despliegue que no toca esos paquetes ya no reescribe los conjuntos;
- uno que sí los toca sigue escribiéndolos, como debe.

El cambio vive en `fbi.picks`, **fuera** de los paquetes de modelos: tocar uno de ellos renueva la versión de todos los modelos
(`tests/unit/test_model_code_version.py`). Por eso no se tocaron `features/store.py` ni `engine.py`, que la ficha nombraba.

Lo que no cambia: las predicciones se siguen guardando con la huella de entradas, que es la misma; las versiones de modelo se siguen
identificando por la huella del código. Una versión que se cree más tarde con el mismo código de modelos anota ese primer commit en vez
del actual (los dos son commits del mismo código de modelos).

## Encendido (con el kit auditado, PM-15-03 o cuando el dueño lo decida)

1. Copia fechada: `cp /etc/predigol/app.env /etc/predigol/app.env.before-pm1302-$(date -u +%Y%m%dT%H%MZ)`.
2. Añadir `FBI_FEATURE_SETS_BY_MODEL_CODE=on` a `/etc/predigol/app.env` y `predigolctl up` (hay que reiniciar el worker).
3. Fuera de copias (03:30–05:00 UTC), de `fixtures_sync` (03:55, 09:55, 15:55, 21:55 UTC) y de cadenas de despliegue.

La primera pasada tras encender escribe un conjunto por partido próximo (el commit nombrado cambia una vez); desde ahí, ninguno más por
despliegue.

## Comprobación (solo lectura)

```
SELECT data_cutoff::date d, count(*) sets,
       count(*) FILTER (WHERE prev_hash = input_hash AND prev_cv <> code_version) same_hash_new_commit
  FROM (SELECT data_cutoff, input_hash, code_version,
               lag(input_hash) OVER w prev_hash, lag(code_version) OVER w prev_cv
          FROM features.feature_sets WHERE feature_version = 'fv2.1.0'
        WINDOW w AS (PARTITION BY fixture_id ORDER BY data_cutoff, id)) s
 WHERE data_cutoff >= now() - interval '8 days' GROUP BY 1 ORDER BY 1;
```

`same_hash_new_commit` debe quedar en 0 desde el día siguiente al encendido salvo en los despliegues que cambian el código de modelos.
Linaje: las 1.000 últimas predicciones `elo_ologit` en tiempo real deben seguir teniendo todas su conjunto
(`EXISTS (SELECT 1 FROM features.feature_sets s WHERE s.fixture_id = p.fixture_id AND s.input_hash = p.feature_set_hash)`).

## Reversión

`FBI_FEATURE_SETS_BY_MODEL_CODE=off` (o quitar la línea) y `predigolctl up`: vuelve el commit actual. Nada guardado cambia. Si hace
falta, PR de `revert`.

## Cierre

Siete días encendido sin incidentes, la consulta de arriba antes y después, la memoria del worker antes y después (PM-13-05) y el
documento de estado actualizado.

## Lo que queda fuera (seguimiento para la sesión de Intelligence)

La repetición mayor no es la del commit. `input_hash` es una huella **global**: suma cada resultado que el motor consume en cualquier
competición, así que cambia cada vez que termina un partido en cualquier parte, aunque nada cambie para los dos equipos del partido.
El 20-nov-2026, de 1.500 conjuntos de las últimas 12 horas con huella distinta a la anterior, **1.472 (98,1 %) tenían los mismos 43
valores**. Arreglarlo exige una huella por partido (equipos, liga y lo que cada rasgo lee), que cambia el significado de
`input_hash`, el linaje de las predicciones `elo_ologit` y probablemente la versión de rasgos: es una decisión del código de modelos,
no de higiene, y no se hizo aquí.
