# Sede neutral (Plan Maestro, fase F0, defecto 1)

**Qué es.** Un partido de una final, de un torneo de selecciones o de una fase final a sede única **no se juega en casa de nadie**, y
hasta hoy los modelos lo trataban como si el equipo nombrado «local» jugara ante su gente. Esta entrega **reconoce** esos partidos
con una regla basada en pruebas (`neutral-v1`), **guarda el veredicto con su razón**, y lo mide con un backtest antes/después. Los
modelos **no lo leen** hasta que una persona enciende un interruptor, y el interruptor solo se deja encender si el backtest salió
«justificado». **Desplegar esto no cambia ninguna probabilidad**: queda APAGADO.

## El problema que corrige

`core.fixtures.is_neutral` y `core.competitions.neutral_venue` los leen el Elo, los modelos de goles, el logit ordenado y el paquete
de contexto de la IA, pero **ninguna ingesta los escribía**: valían `false` en todas partes. Una final de Champions, una final de Copa
del Rey, una semifinal en Wembley, un partido de Mundial en un tercer país: todos se modelaban con ventaja de local (un término de
«ventaja local» en el Elo y en los modelos de goles, una constante local en el logit).

Marcar «neutral» no es girar un interruptor. El proveedor no lo dice; el id de estadio que da está viejo o compartido (conserva el
del club cuando juega fuera; un mismo id nombra estadios distintos). Y **un «neutral» equivocado le quita a un partido de verdad
local su ventaja real**. Por eso: regla que exige **pruebas positivas**, veredicto guardado con sus pruebas, y modelos que solo lo
leen si una persona lo decide tras un backtest («no cambies modelos sin prueba»).

## Qué escribe (y qué no)

Migración **0081** (aditiva; con respaldo y prueba de restauración antes, como todas):

| Objeto | Para qué |
|---|---|
| `core.fixture_venue_class` | Un veredicto por (partido, versión de regla): neutral sí/no, el **código de razón** (`basis`), la **prueba** (estadio, su país y cómo se supo, presencia de cada lado, ronda) y cuándo se decidió. Es una tabla **derivada**: se reescribe si cambian los hechos (un estadio que se nombra después). Los partidos de **liga doméstica no tienen fila**: nunca son neutrales por regla. |
| `analytics.neutral_rule_runs` | Los backtests antes/después: huella de las etiquetas sobre las que se hicieron, parámetros fijados de antemano, métricas de los dos brazos y el **veredicto** (`justified` / `not_justified` / `inconclusive`) calculado por aritmética. **Solo-añadir.** |
| `analytics.neutral_rule_promotion` | El **interruptor**, como historial de decisiones: la fila más nueva dice qué regla leen los modelos (o ninguna, si es un `retire`). **Vacía tras la migración = APAGADO.** Solo-añadir. |

Nada existente se reescribe. Un `UPDATE` o `DELETE` sobre las dos tablas de decisiones lo rechaza la base de datos (el disparador
`analytics.refuse_change()` de la migración 0079, que esta no toca).

Además, **la ingesta escribe un veredicto por cada partido no liguero que guarda** (`ingestion/apply.py`), en una subtransacción: si
el clasificador falla, el fallo queda en el registro (`neutral.classify_failed`) y **no cuesta el partido**. Escribir veredictos no
cambia nada que un modelo lea mientras el interruptor esté apagado.

## La regla `neutral-v1` (congelada)

**Precisión primero.** Un partido es neutral solo con una **prueba positiva**; «sin pruebas» significa *no neutral*, nunca «quizá».
No usa marcadores: solo estado, estadio y ronda. Una versión nueva de la regla sería `neutral-v2`, con su propio backtest.

* **Liga doméstica:** nunca neutral.
* **Dos selecciones:** el país del estadio contra los dos países. En un tercer país → `third_country`. En el de cualquiera de las
  dos (anfitrión) → no neutral. Estadio sin país → no neutral (`venue_country_unknown`).
* **Dos clubes:** primero un **veto**: si el estadio es de los habituales de alguno (leído de sus partidos de liga en casa de los
  cuatro años previos), el que el proveedor da como propio, o —salvo en final o semifinal— está en la misma ciudad, **no** es
  neutral. Después, una de estas pruebas:
  * `third_country`: estadio en un país que no es de ninguno de los dos;
  * `decider_ground`: final o partido por el tercer puesto, a partido único, en un estadio que no es casa de ninguno;
  * `semi_pair_ground`: semifinal a partido único cuya «gemela» se juega en el **mismo** estadio en menos de 3 días (una final
    four). Una semifinal sola no prueba nada;
  * `shared_ground`: varios partidos de la misma competición, de al menos tres locales distintos, en un mismo estadio en pocas
    semanas, y ese estadio no es casa de ninguno de los dos (en competiciones de varios países, además, que no esté en el país de
    ninguno: un estadio nacional que varios clubes de un país toman prestado es su casa).
* **Club contra selección, tipo desconocido, sin estadio nombrado:** no neutral.

El proveedor repite ids de estadio para estadios distintos, así que el estadio se identifica por **lo que el payload nombra**
(`venue_name`, `venue_city`); el id solo cuenta donde se comprobó que apunta al mismo estadio (`fbi.core.places` compara nombres).

**Resultado sobre la copia de datos (47.897 partidos no ligueros):** 1.896 neutrales (4 %): `third_country` 1.698,
`decider_ground` 124, `shared_ground` 44, `semi_pair_ground` 30. No neutrales: `home_ground` 23.984, `no_venue` 9.970,
`no_evidence` 7.242, `home_country` 2.899, `venue_country_unknown` 1.549, `away_ground` 285, `away_country` 59,
`country_unknown` 9, `mixed_sides` 4. Los 17.212 partidos sin estadio o sin pruebas **siguen modelados con ventaja de local**.

## El interruptor

* **Apagado** (`analytics.neutral_rule_promotion` vacía, o la última fila es `retire`): ningún modelo lee un veredicto. Es el
  estado tras desplegar.
* **Encendido:** la fila más nueva es un `promote` que cita una corrida del backtest. Los modelos leen el veredicto **solo de la
  regla que esa fila nombra**.
* **Qué deja encender:** solo una corrida `justified`, y solo si las etiquetas guardadas **no han cambiado** desde esa corrida
  (huella `label_state`). Si cambian, hay que repetir el backtest.
* **Quién:** una persona (`--by NOMBRE`), con una razón de al menos 10 caracteres. Nunca se enciende sola.
* **Volver atrás:** `retire`. Los veredictos se conservan; los modelos vuelven a leer «ningún partido es neutral».

## Cómo se mide: protocolo `neutral-ab-v1` (fijado antes de mirar ningún resultado)

Mismo conjunto de partidos, recorrido en el tiempo (*walk-forward*), en dos brazos: **antes** (ningún partido neutral, como hoy) y
**después** (con los veredictos). Toda la configuración está fijada en el código; cambiar cualquier parte es un protocolo nuevo.

| Capa | Qué mide | Por qué así |
|---|---|---|
| **Principal** | Elo + logit ordenado agrupado, todas las competiciones, desde 2018-07-01. En un partido etiquetado se quita la ventaja local como la quita el propio Elo; el mapeo (pendiente y umbrales) se ajusta **solo con partidos no etiquetados**, idéntico en los dos brazos. | Un modelo con término local propio *aprendería* de los propios resultados del partido neutral, curaría cualquier etiqueta equivocada y **nunca podría mostrar daño**. Así, si el partido sí tenía ventaja local, el brazo que la quitó sale penalizado. El logit de producción no sirve: se entrena con ligas, donde nada es neutral, y se niega a valorar un partido neutral. |
| **Guardia** | Los modelos de goles de producción (Poisson y Dixon-Coles), por competición, ajustados como los ajusta el pronóstico real. | Es lo que el interruptor cambia en producción. Cubre pocos partidos (una competición necesita 100 resultados en dos años): puede mostrar daño, no demostrar seguridad. |
| **Control** | Todos los demás partidos, con el mismo mapeo en los dos brazos. | La regla solo cambia partidos etiquetados; el resto solo puede diferir por los ratings, y no debe ser a peor. |

**Veredicto por aritmética** (log loss del 1X2, que es una regla de puntuación propia; Brier, RPS y error de calibración se
informan al lado; la incertidumbre es un *bootstrap* que remuestrea **días enteros de partidos**, porque los de un día comparten
torneo, ratings y estadio):

* `justified`: ninguna capa muestra daño, y el extremo alto del intervalo del 95 % de (después − antes) en los partidos neutrales
  queda por debajo de **0,005** («no empeora»; puede mejorar), y el del control por debajo de **0,0005**;
* `not_justified`: alguna capa muestra daño (intervalo entero por encima de cero);
* `inconclusive`: ninguna de las dos (pocos partidos neutrales valorados, o intervalo demasiado ancho).

El margen 0,005 es un tercio de lo que debería ganar quitar una ventaja local que no existe (≈ 0,015) y menos del 1 % del propio log loss.
Bases de prueba con menos de 100 partidos se muestran pero **no se juzgan por sí solas**.

## El resultado real

**Sobre qué:** copia **de solo lectura** de las tablas deportivas (sin usuarios ni cuentas) de la base del portátil, **al
2026-10-09** (245.844 partidos, 228.881 jugados) en una base de trabajo aparte. **No es producción.** Código: commit `37ba93e`.
Corrida completa de 4,6 min. **Se hizo una vez y se repitió otra, idéntica, solo para comprobar reproducibilidad: los dos
resultados son iguales campo por campo** (corridas #1 y #2 de esa base). Resultado completo (corrida #2) en
[`SEDE_NEUTRAL_F0_D1_resultado.json`](SEDE_NEUTRAL_F0_D1_resultado.json).

**Veredicto: JUSTIFICADO**, por el criterio fijado de antemano («los partidos neutrales no empeoran con la regla; los demás
tampoco»).

Ventana: 2018-07-01 … 2026-10-09. De 1.762 partidos etiquetados en la ventana, 1.288 los pudieron valorar los dos brazos en la
capa principal.

| Capa | Partidos | Log loss antes → después | Diferencia (IC 95 %) | Brier | Error de calibración (ECE) | Local sobrevalorado* |
|---|---:|---|---|---|---|---|
| Principal (Elo + logit) | 1.288 | 1,0127 → 1,0047 | **−0,0080** (−0,0180 … +0,0028) | 0,6061 → 0,6010 | 0,0106 → 0,0171 | +0,053 → −0,023 |
| Guardia: Dixon-Coles | 769 | 1,0295 → 1,0207 | **−0,0087** (−0,0250 … +0,0077) | 0,6189 → 0,6121 | 0,0243 → 0,0123 | +0,063 → −0,031 |
| Guardia: Poisson | 783 | 1,0247 → 1,0166 | **−0,0081** (−0,0251 … +0,0074) | 0,6151 → 0,6092 | 0,0221 → 0,0158 | +0,061 → −0,033 |
| Control (todo lo demás) | 193.826 | 1,0148 → 1,0148 | −0,0000 (−0,0000 … +0,0000) | 0,6077 → 0,6077 | 0,0083 → 0,0084 | +0,003 → +0,003 |

\* Probabilidad media que el modelo daba al local menos la frecuencia con la que ganó, en puntos de probabilidad (+0,053 = 5,3
puntos de más). Log loss y Brier: **más bajo es mejor**; una diferencia negativa significa que la regla ayuda.

Por tipo de prueba (capa principal):

| Prueba | Partidos | Log loss antes → después | Diferencia (IC 95 %) | Local sobrevalorado |
|---|---:|---|---|---|
| `third_country` | 1.090 | 1,0172 → 1,0082 | −0,0089 (−0,0207 … +0,0023) | +0,051 → −0,026 |
| `decider_ground` | 124 | 1,0464 → 1,0304 | −0,0160 (−0,0487 … +0,0166) | +0,105 → +0,031 |
| `shared_ground` | 44 | 0,9208 → 0,9163 | −0,0045 (−0,0443 … +0,0351) | +0,083 → +0,011 |
| `semi_pair_ground` | 30 | 0,8474 → 0,8990 | **+0,0517** (−0,0102 … +0,1122) | −0,112 → −0,182 |

### Cómo leerlo (lo bueno y lo dudoso)

**Lo bueno.**

* Los tres modelos independientes —el Elo agrupado y los dos modelos de goles de producción— mejoran en la misma dirección y casi
  lo mismo (≈ 0,008–0,009 de log loss por partido neutral).
* El defecto que motivó el cambio se ve en los datos: **antes**, el modelo daba al «local» de un partido neutral entre 5 y 6 puntos
  de probabilidad más de los que ganó (en finales, 10).
* **Ninguna capa muestra daño** (con la salvedad 4 de abajo): los 193.826 partidos que la regla no toca quedan iguales hasta la
  cuarta cifra.

**Lo dudoso (para que decidas con los ojos abiertos).**

1. **La mejora no está demostrada, solo que no empeora.** El intervalo incluye el cero en todas las capas. Lo que se fijó de antemano
   era «no peor que +0,005» y se cumple (el extremo alto es +0,0028), pero «mejor» no se puede afirmar con estos datos.
2. **La mejora es la mitad de lo esperado** (≈ 0,008 frente a ≈ 0,015 si el local neutral no tuviera ventaja alguna). Y **se pasa de
   frenada**: el local pasa de estar sobrevalorado en 5,3 puntos a estar infravalorado en 2,3. En los partidos neutrales el equipo
   nombrado primero todavía gana algo más que el segundo (39,6 % frente a 44,0 % en el resto): la regla le quita *toda* su ventaja y
   la real es pequeña pero no cero. Una variante que conserve una fracción de la ventaja sería una regla/protocolo nuevo; **no se
   probó ni se ajustó nada con este resultado** (sería ajustar sobre la misma muestra).
3. **El error de calibración sube en la capa principal** (0,0106 → 0,0171) aunque el log loss baja: es el mismo exceso de corrección
   (el sesgo cambia de signo). Con 1.288 partidos el ECE es ruidoso; en los dos modelos de goles de producción **baja** (0,0243 → 0,0123 y
   0,0221 → 0,0158).
4. **`semi_pair_ground` empeora en estimación puntual** (+0,0517), pero son **30 partidos** y su intervalo (−0,0102 … +0,1122) incluye
   el cero. El protocolo no juzga una prueba con menos de 100 partidos por sí sola; queda anotado para vigilarlo con datos de
   producción.
5. **Cobertura:** de 1.762 partidos etiquetados, 474 no los valoró la capa principal (un equipo con menos de 10 partidos con rating) y
   los modelos de goles solo cubren ≈ 770 (670 pertenecen a competiciones sin 100 resultados en dos años, 186 con un equipo sin
   partidos en esa ventana y 123 con más de 250 equipos). Lo que no se valoró no está en ningún brazo.
6. **Las etiquetas no son estrictamente «de entonces»:** la regla vio el estadio que el payload nombra *hoy* (si se corrigió después
   del partido, es el corregido). Un pronóstico hecho antes del partido tenía casi toda esa información, no toda.

**Mi lectura (la decisión es tuya, como pide el plan):** el riesgo de encenderlo es bajo —el criterio pactado se cumple, el control no
se mueve, y se apaga con un comando—, pero la ganancia esperada es modesta y no está probada. Dejarlo apagado es seguir como hoy.

## Qué cambia al encenderlo

Con la copia de datos: **1.896 partidos se leen como neutrales** (1.852 jugados, 15 por jugar y 29 cancelados, aplazados o adjudicados). Los
que más pesan: AFC Champions League Elite 232, UEFA Champions League Women 152, Mundial 141, CONCACAF Nations League 89, UEFA
Europa Conference League 84, Clasificación Mundial Asia 82, UEFA U21 74, CAF Confederation Cup 73.

* **Elo:** un partido neutral actualiza los ratings **sin ventaja local** (el mismo marcador no es la misma información) y se
  predice sin ella. Cambian los ratings de los equipos que jugaron partidos neutrales.
* **Modelos de goles (Poisson, Dixon-Coles):** sin ventaja local, en el entrenamiento y en la predicción de un partido neutral.
* **Logit ordenado de producción:** **sigue sin valorar partidos neutrales** (se entrena con ligas, donde nada es neutral, y su
  constante local no se puede separar de los umbrales); lo deja anotado como motivo en el informe (`report.uncovered`).
  Consecuencia: un pronóstico de logit **ya hecho** para un partido que ahora sería neutral **no se retira** (un pronóstico es un
  registro) y sigue siendo el más nuevo de ese modelo hasta el pitido. El ensayo de `promote` cuenta cuántos hay.
* **Paquete de la IA:** `fixture.neutral` y el contexto de viaje del partido reflejan el veredicto.
* **Huellas (hashes):** solo si hay un partido neutral en el conjunto, la huella de entrenamiento, de predicción y del Elo añaden una
  marca (`|n`, `|target-neutral`). Con el interruptor apagado **nada cambia**; encendido, las características y pronósticos guardados
  se vuelven a identificar con la huella nueva.
* **Tras encenderlo hay que reconstruir:** `python -m scripts.build_features --elo-only --apply` y después
  `python -m scripts.build_features --apply`, para que lo que leen los modelos coincida con lo que van a valorar.

**Versiones de modelo nuevas al desplegar (con o sin encender):** este defecto toca el código de `models`/`features`/`predictions`/
`backtesting`, igual que el defecto 2. La versión de un modelo se identifica por la huella de ese código, así que **el despliegue abre
versiones nuevas de los modelos y su evidencia prospectiva empieza de cero**. Ocurre **una sola vez** por despliegue (ya estaba
previsto por el defecto 2) y no es una probabilidad distinta: es la misma matemática con otro nombre.

## Cómo se usa (desde `backend/`)

Todo lo que escribe es **ensayo** hasta que se pide.

```bash
python -m scripts.neutral_rule show                       # el interruptor, su historial, los veredictos y las últimas corridas
python -m scripts.neutral_rule classify                   # ensayo: los partidos sin veredicto (nada se escribe)
python -m scripts.neutral_rule classify --all             # ensayo: decidir de nuevo todos (¿cambiaría algo?)
python -m scripts.neutral_rule classify --apply           # escribir (por tandas de 2.000, con commit por tanda: se puede cortar y seguir)
python -m scripts.neutral_rule backtest --out r.json      # corre el backtest sin guardarlo
python -m scripts.neutral_rule backtest --apply --out r.json   # ... y guarda la corrida (necesita TODOS los veredictos)
python -m scripts.neutral_rule promote --run N --reason "por qué"                     # ensayo: qué cambiaría
python -m scripts.neutral_rule promote --run N --reason "por qué" --by NOMBRE --confirm   # TU decisión: encender
python -m scripts.neutral_rule retire --reason "por qué" [--by NOMBRE --confirm]      # apagar (ensayo si no hay --confirm)
```

* `backtest` **se niega** si falta algún veredicto (un backtest sobre parte de las etiquetas no dice nada de la regla) y
  `backtest --apply` se niega con código sin confirmar en git (`--allow-dirty` lo salta). En el contenedor de producción no hay
  `git`, así que no estorba; la versión de código viene de `FBI_CODE_VERSION`, que `predigolctl` fija con la versión del despliegue.
  **Fuera de un despliegue, fíjala** (`FBI_CODE_VERSION=$(git rev-parse --short=12 HEAD)`) o la corrida queda registrada como
  `unknown` (la primera de la copia lo quedó; la repetición, no).
* `--confirm` exige `--by NOMBRE` (queda registrado) y una razón de ≥ 10 caracteres.
* Códigos de salida: 0 hecho (o ensayo), 2 argumentos mal, 3 negado (corrida no justificada, etiquetas cambiadas, falta algo).

## Primer despliegue

1. Respaldo verificado y prueba de restauración (regla del proyecto), worker parado, migración 0081 con `lock_timeout`, permisos,
   reinicio, salud. Todo sigue en **SHADOW**.
2. `python -m scripts.neutral_rule show` → «The switch is OFF» y 0 veredictos.
3. `python -m scripts.neutral_rule classify` (ensayo) y luego `classify --apply`: rellena el histórico (≈ 48.000 filas; en la copia, decidirlas
   tardó ≈ 2 min). Desde ahí la ingesta mantiene los veredictos al día.
4. `python -m scripts.neutral_rule backtest --apply --out neutral_ab_produccion.json` (≈ 5 min). **Con datos de producción**, porque
   `promote` solo acepta una corrida cuyas etiquetas sean las que hay guardadas en esa base; la corrida de la copia es la prueba que
   justifica desplegar, no la que enciende.
5. Se te presenta ese resultado. **Solo si lo apruebas:** `promote --run N --reason "..."` (ensayo) → `--by NOMBRE --confirm`, y los
   dos `build_features` de arriba. Si algo no te gusta: `retire`.

## Límites conocidos

* Las etiquetas son hechos estáticos del estadio (no dependen del resultado), pero no son estrictamente «de entonces».
* 17.212 partidos sin estadio nombrado o sin pruebas siguen con ventaja de local (se prefirió no etiquetar que etiquetar mal).
* La regla puede equivocarse **del lado inseguro** en un caso: una final en el estadio de un finalista bajo otro nombre (p. ej., la
  final de la Libertadores 2023 en el Maracanã, casa del Fluminense) se llama neutral. Por eso el backtest se lee sobre los partidos
  que la regla cambia, con la prueba de cada uno guardada (`evidence`).
* El backtest mide el Elo agrupado y los modelos de goles; **no** el logit de producción (que no valora partidos neutrales).
* Un pronóstico de logit ya hecho sobrevive al interruptor hasta el pitido (arriba).
* Un partido de liga jugado fuera de su país es raro y no se etiqueta (las ligas son el núcleo del sistema).

## Cómo deshacerlo

* **Apagar sin tocar nada más:** `retire` (con `--confirm`). Los veredictos y el historial quedan; los modelos leen otra vez «ningún
  partido es neutral». Luego los dos `build_features`.
* **Quitar el mecanismo:** `alembic downgrade 0080` borra las tres tablas (las dos de decisiones: **exportarlas antes** si ya hubo
  una promoción). Hacerlo junto con el código anterior; con el código nuevo y sin tablas, la ingesta anotaría cada fallo del
  clasificador en el registro (`neutral.classify_failed`) sin perder partidos. Hacer antes el respaldo habitual.
