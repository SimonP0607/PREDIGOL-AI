# F9 — El catálogo de mercados por familia

Guía del dueño. Qué hace F9, cómo se lee la matriz, qué no hace, cómo ponerlo en producción y cómo quitarlo.

## 1. En una frase

Hasta F8 PrediGol conocía cinco mercados (1X2, Over/Under de goles, Ambos marcan, Doble oportunidad y Hándicap asiático). El
proveedor ofrece 338 tipos de apuesta. F9 no modela ninguno nuevo: **pone en orden qué es cada apuesta, con qué dato se
liquida y si hay precios y resultados suficientes para que valga la pena un modelo**, y lo deja escrito en una matriz que se
renueva sola cada semana. Los modelos de goles por mitad, córners y tarjetas son F10; la liquidación y la decisión por
familia son F11.

## 2. Qué se construyó

* **Reglas de liquidación** (`market.settlement_rules`, 20 reglas, de las que 18 pueden liquidar). Una regla es *una medida de
  un partido terminado* —los goles de la primera parte, los córners del partido, las tarjetas contadas como líneas— en una
  convención y una versión. La regla no liquida (eso es F11): dice **con qué número se compara la línea** y si ese número
  existe. **Una regla nunca se edita ni se borra** (lo impide la base de datos); una convención nueva es una versión nueva
  (`cards_lines_ft@v2`) y la vieja conserva su fila.
* **Claves nuevas** en `market.markets` (`OU_1H`, `CORNERS_OU`, `CARDS_OU_HOME`, `YELLOW_OU_1H`, `SOT_1X2`…): salen solas de lo
  que la taxonomía ya sabe de cada apuesta y de la regla que la liquida, de modo que **solo existe una clave para una apuesta
  que se puede liquidar** y dos apuestas que son el mismo mercado (el proveedor lista «Corners. Double Chance» dos veces)
  comparten clave. **Una clave en el catálogo no es un mercado seguido ni modelado**: nacen con `is_tracked = false` y
  `is_model_enabled = false`, así que el flujo de los cinco mercados, los contadores de calidad y las pruebas que cuentan el
  catálogo ven lo mismo que siempre.
* **La vista `market.fixture_outcomes`**: una fila por partido terminado con el marcador a los 90 minutos, las dos partes,
  córners, tiros, tiros a puerta, faltas, fueras de juego, paradas y las tarjetas por parte y por convención. **Un dato que
  nadie dio es desconocido, nunca cero**, y tras la prórroga las estadísticas del partido son desconocidas (el proveedor no
  dice si su total incluye la media hora extra). Un marcador al descanso que falta o que no puede ser (3-0 al descanso, 1-0 al
  final) no inventa partes.
* **La matriz** (`market.catalogue_runs`): 42 filas por familia (A Resultado, B Goles, C Córners, D Tarjetas, E Jugadores, F
  Porteros, G Tiros/faltas/fueras de juego, H Futuros, Z Otros); cada una de las 338 apuestas está en exactamente una fila.
  Se calcula **fuera de línea** (la corrida semanal y `python -m scripts.markets matrix --store`); la página solo lee la última,
  así que abrirla no cuesta nada.
* **`discovery-v3`**: el descubrimiento semanal mide la cobertura del dato que liquida una apuesta sobre
  `market.fixture_outcomes` (ya no la adivina) y lee cada apuesta con su regla; una apuesta que ninguna regla puede liquidar
  nunca pasa a RESEARCH. Las tarjetas por mitad, que quedaban «hasta medirlas», se miden.
* **La página** «Matriz de mercados por familia», en la consola de administración, bajo «Mercados» (solo lectura).
* **F8.11**: la auditoría de historiales (`python -m scripts.player_history audit`) cuenta, mes a mes, las hojas de alineación
  que parecen cruzadas por el historial (al menos 5 hombres de una hoja cuyo único partido con el club donde figuran fue ese,
  contra el club al que vuelven). Es una cifra para la decisión 9; no corrige nada.

## 3. Cómo se lee la matriz

Cada fila tiene un **veredicto**, una **prioridad** (solo si el veredicto es «por investigar») y un **motivo**.

| Veredicto | Significa |
|---|---|
| LISTO | modelado y con ventaja validada fuera de muestra (hoy ninguno: ningún mercado la tiene) |
| PARCIAL | modelado y en sombra, **sin** ventaja validada (los cinco de hoy) |
| POR INVESTIGAR | hay precio y dato para medirlo; la prioridad dice por dónde empezar |
| NO VIABLE | hoy no se puede o no vale la pena, y el motivo dice por qué |

Lo que decide cada fila, con las cifras exactas del código (`matrix-v1`):

* **Precios de los últimos 8 días** (las cuotas que el reloj de precios ya estructura) y **resultados de los últimos 365 días**
  de las competiciones seguidas. Para las apuestas cuyos precios aún no se guardan, el precio sale del último descubrimiento
  semanal y la fila lo marca como «estimado».
* Un precio necesita **al menos 2 casas**: una sola casa es el precio, no una referencia para medirlo (motivo `thin_price`).
* Prioridad **alta**: cobertura de precio de 80 % o más de los partidos con precio **y** al menos 5.000 partidos con el
  resultado que la liquida. **Media**: un tercio o más y al menos 1.000 partidos. **Baja**: el resto.
* Algunas filas son juicio, no medida, y se marcan «fijado a mano»: los totales por equipo (rechazados por el backtest del
  P5) y el marcador exacto (poca información).

Motivos más frecuentes: `no_period_data` (el dato existe solo como total del partido: **los córners de una parte no se pueden
liquidar** con nada que guardemos), `no_prices_in_window` (sin precios esta semana), `not_extracted` (la plataforma aún no
guarda sus precios), `player_level` (se liquida con datos de un jugador), `out_of_scope` (tiempo, especiales, otros deportes),
`rejected_backtest`, `low_information`, `thin_price`, `after_parent` (se mide después del total).

## 4. Las reglas de liquidación

| Regla | Qué mide |
|---|---|
| `goals_ft@v1` | marcador a los 90 minutos (la prórroga y los penaltis nunca cuentan) |
| `goals_1h@v1`, `goals_2h@v1` | goles de cada parte (la segunda es el marcador a los 90 menos el del descanso) |
| `goals_halves@v1` | las dos partes a la vez (HT/FT, mitad con más goles) |
| `corners_ft@v1` | córners del partido |
| `corners_1h@v1`, `corners_2h@v1` | **no liquidables** (`no_period_data`): escritas para que se sepa que no existe el dato |
| `cards_lines_ft@v1`, `cards_lines_1h@v1`, `cards_lines_2h@v1` | cada tarjeta mostrada cuenta una (la roja tras segunda amarilla cuenta como la roja que es) |
| `yellow_ft@v1`, `yellow_1h@v1`, `yellow_2h@v1` | solo amarillas |
| `red_ft@v1` | expulsiones (directas y por doble amarilla) |
| `cards_points_ft@v1` | puntos de tarjetas: 10 por amarilla, 25 por roja directa, 15 más por la roja tras segunda amarilla |
| `shots_ft@v1`, `shots_on_target_ft@v1`, `fouls_ft@v1`, `offsides_ft@v1`, `saves_ft@v1` | totales del partido |

**Por qué las tarjetas tienen varias reglas.** Las casas no cuentan las tarjetas igual (algunas cuentan cada tarjeta, otras
puntos, otras no cuentan la roja que sigue a una segunda amarilla) y el proveedor no dice qué convención lleva «Cards
Over/Under». Por eso cada convención es una regla con su versión, la apuesta se enlaza con la mejor lectura de su nombre, y la
matriz informa **en cuántos partidos las convenciones liquidarían distinto** (los partidos con expulsión). Las tarjetas por
parte solo se pueden contar desde los eventos clasificados (`core.fixture_event_kinds`), que cubren unos 400 días.

## 5. Cómo se usa

```
python -m scripts.markets status          # el catálogo tal como lo tiene la base, la última matriz, deriva (solo lectura)
python -m scripts.markets sync            # simulacro: qué cambiaría escribir el catálogo
python -m scripts.markets sync --apply    # escribe reglas y claves que faltan y enlaza las definiciones
python -m scripts.markets matrix          # construye la matriz con los datos reales y la imprime (no escribe)
python -m scripts.markets matrix --store  # y la guarda: es la que lee la página
```

`sync` **nunca sobrescribe**: un valor que la base tiene y difiere del código se informa como DERIVA y se deja; una regla
que difiere de la guardada se **rechaza**. La corrida semanal ejecuta, en este orden, el catálogo, el descubrimiento y la matriz;
si un paso falla, los otros siguen y la corrida queda «parcial» con el error escrito.

## 6. Lo que F9 no hace

No crea ningún modelo, no activa ningún mercado, no cambia ninguna decisión ni ningún pick, no pide nada al proveedor y no
toca el flujo de los cinco mercados. Las claves nuevas existen pero no se siguen (`is_tracked = false`) ni se modelan
(`is_model_enabled = false`). Todo sigue en SHADOW hasta que lo apruebes.

## 7. Cómo se pone en producción y cómo se quita

Se despliega con `predigolctl deploy` fuera de las ventanas de `fixtures_sync`. La migración **0092 solo agrega estructura**
(dos tablas, una vista, un disparador y una llave foránea; no escribe ni una fila). Antes de aplicarla: copia verificada y
prueba de restauración. Después: `python -m scripts.markets sync --apply` y `python -m scripts.markets matrix --store`.
Para quitarla: volver al código anterior y `alembic downgrade 0091` (probado hacia abajo y hacia arriba en pruebas); mientras
tanto la base no pierde nada de lo que tenía.

## 8. Lo que queda abierto (tuyo)

* La **convención de tarjetas** que adoptará F11 para liquidar «Cards Over/Under»: la matriz mide cuánto pesa la diferencia;
  hasta que lo decidas ningún pick de tarjetas se liquida.
* Si quieres **tarjetas por parte con más historial** (hoy unos 400 días): reconstruir `core.fixture_event_kinds` más atrás
  es una lectura de eventos ya guardados, sin pedir nada al proveedor.
