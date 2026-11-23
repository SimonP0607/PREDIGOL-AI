# PM-12-06 · Los modelos evaluados por competición y por nivel de cobertura (IA-152)

Plan Maestro PM, bloque 12. Código IA-152. **Privado**: no cambia picks, modelos, umbrales ni probabilidades; `FBI_PICKS_SOURCE` sigue
apagado. Dos interruptores, los dos **apagados** por omisión.

## Qué mide

`fbi.coverage.model_segments` (`segments-v1`) puntúa lo que ya está guardado contra el resultado de los 90 minutos (`reg_goals_*`):

| Fuente | Qué es | Tabla |
| --- | --- | --- |
| `forecast` | lo que se enseña a un lector: el último juego de `forecast-v1` conocido antes del saque | `models.match_forecasts` |
| `prediction` | la cifra de cada modelo en tiempo real: el último juego de cada modelo antes del saque | `models.predictions` (sin sesión de backtest) |
| `backtest` | una sesión del LAB, ejecución por ejecución | `analytics.backtest_samples` |

Mercados: 1X2, más/menos 2,5 y ambos marcan. Un partido cuenta solo con todas las selecciones del mercado.

Por cada fuente, modelo y mercado, y por segmento (global, cada competición, cada nivel resumen de la matriz —`A`, `B`, `B*`, `C`…—
o `sin_medir`): partidos y días, log loss medio con su intervalo del 95 % (se remuestrean días enteros de Bogotá, 2.000 veces), Brier,
RPS (1X2) y la **habilidad**: log loss del modelo menos el de las frecuencias propias del segmento (negativo es mejor), con su intervalo.

## El veredicto de una competición

* `insuficiente`: menos de **300** partidos (la muestra que AD-K02 pide a una celda). No se da un número como juicio: se dice «insuficiente».
* `sin_habilidad`: con la muestra, el extremo superior del intervalo de la habilidad no queda por debajo de cero.
* `apta`: con la muestra y mejor que sus propias frecuencias.

Una competición sin fila no tiene veredicto: **toda competición nueva nace «no autorizada»**. Un «apta» no es una prueba de ventaja sobre
el mercado (eso lo mide el tablero semanal de PM-12-01).

## Reproducción

`check` comprueba que, por fuente, modelo y mercado, los partidos y la suma ponderada del log loss y del Brier de los segmentos devuelven
la cifra global, por competición y por nivel; con `--session N`, además, que la cifra global de cada ejecución de una sesión del LAB es
la que el servidor guardó en `analytics.backtest_runs` (tolerancia de `scripts.lab_reproduce`).

## Órdenes

```
docker exec predigol-worker python -m scripts.model_segments show --kind competition --top 40   # solo lectura
docker exec predigol-worker python -m scripts.model_segments check --session 4                  # solo lectura; sale con 1 si no reproduce
docker exec predigol-worker python -m scripts.model_segments verdicts --league 239              # lo que leería el estado 5
docker exec predigol-worker python -m scripts.model_segments run                                # calcula y guarda el informe
```

## Interruptores

* `FBI_MODEL_SEGMENTS` (apagado): con `=1`, una vez por semana ISO (los lunes, al final del proceso nocturno de la matriz,
  `scripts.availability_refresh`, con su fila `model_segments` en el libro de ejecuciones) se calcula y se guarda el informe en
  `analytics.evaluation_reports` (`kind = 'segments'`) y `analytics.evaluation_segments` (solo se añaden filas; nunca se cambian ni se
  borran). `--evaluation-only` lo corre a mano.
* `FBI_PROB_BY_COMPETITION` (apagado): con `=1`, el estado 5 de C-16 (`prob_authorised`, detrás de `FBI_AVAILABILITY`) exige además
  que el último informe llame `apta` al mercado en esa competición. Solo cambia lo que dice C-16; ningún pick ni modelo lo lee.
  Encenderlo solo con el kit y cuando exista al menos un informe.

## Tablas y permisos

Migración `0172`: `analytics.evaluation_reports` y `analytics.evaluation_segments`, solo aditivas; `grants.sql` da al worker
`SELECT, INSERT` (nunca `UPDATE` ni `DELETE`) y a la API solo lectura. El downgrade se niega si hay medidas.

## Vuelta atrás

Apagar los interruptores (sin despliegue). Si hiciera falta, PR de `revert` (las tablas quedan; no se borra ninguna medida).
