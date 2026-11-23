# PM-09-06 · Tabla esperada con el xG del proveedor (BE-083), en sombra

Plan Maestro PM, bloque 9 (OP-13). Código BE-083. **En sombra**: ninguna ruta, página ni paquete la lee, ni con el interruptor
encendido. Es una cifra que puede leerse como pronóstico, así que **espera la firma de publicación del dueño (DM-14)**.

## Qué es

Los puntos que cada equipo habría sumado según el xG de sus partidos ya jugados (`fbi.stats.expected_table`, `expected-table-v1`):

* partidos: los terminados de la temporada con resultado registrado y con el xG de **los dos** equipos
  (`core.fixture_team_stats.expected_goals`, fuente `api-football`, la fila más nueva de cada lado). Un partido sin el xG de los dos se
  deja fuera y se cuenta (`without_xg`);
* goles de cada equipo como Poisson de media su xG, independientes; P(ganar), P(empatar) y P(perder) sumando los marcadores;
* puntos esperados de un partido = 3 · P(ganar) + P(empatar); los de un equipo, su suma, al lado de los puntos que de verdad sacó en esos
  mismos partidos;
* margen del 95 %: 1,96 · √(Σ varianzas) de los puntos de cada partido bajo el mismo modelo. Dice cuánto pueden separarse los puntos reales
  de los esperados solo por azar, no cuán bueno es un equipo;
* orden: puntos esperados, diferencia de xG, xG a favor y nombre (es una tabla de medias: no se aplica ningún desempate del reglamento).

Rótulo obligatorio: **«xG de API-Football»**. El xG es una caja negra del proveedor: **nunca es una señal de valor** y nada que decida,
ponga precio o juzgue un pick lo importa.

## Cuándo aparecería

Solo en ligas (`core.competitions.type = 'league'`) cuya celda `xg` de la matriz (`analytics.coverage_cells`, fase `todas`, recálculo
nocturno de PM-02-03) esté en **B o superior**. Si no: `sin_cobertura`, `sin_medir` (la matriz aún no la midió) o `no_es_liga`. Con la
visibilidad distinta de `visible` la orden enseña el estado y los recuentos, pero no las filas.

## Órdenes (solo lectura, 0 peticiones)

```
docker exec predigol-worker python -m scripts.expected_table eligible
docker exec predigol-worker python -m scripts.expected_table show --league 39 --season 2025
docker exec predigol-worker python -m scripts.expected_table check --league 39 --season 2025
```

`eligible` lista la última temporada graduada de cada competición seguida con su nivel de xG y su visibilidad. `check` recalcula cada
equipo con una consulta distinta (subconsultas correlacionadas) y con la distribución de Skellam de SciPy (diferencia de dos Poisson), y
sale con 1 si encuentra una diferencia.

## Interruptor

`FBI_EXPECTED_TABLE` (apagado por omisión, documentado en `deploy/vps/app.env.example`). Encenderlo no enseña nada a nadie mientras no
exista un lector; el lector (página de competición, I07) se hace solo tras la firma DM-14, con el contrato C-13 en versión menor.

## Vuelta atrás

Nada que deshacer: no escribe, no tiene tablas ni tareas. Si hiciera falta, PR de `revert`.
