# IA-082 · Motor de escenarios competitivos (`scenarios-v2`)

Pieza **AD-B02** del plan de la arquitectura definitiva 2026 (ola 3, ruta crítica AD-B01 → AD-B02 → AD-F01). Calcula, para cada equipo
de una competición con reglamento codificado (IA-072), **qué se juega**: sus objetivos según el reglamento (título, clasificación,
playoff, plazas continentales, ascenso, evitar el descenso…), **qué está ya decidido matemáticamente** —demostrado, no estimado— y,
para lo que sigue abierto, **qué probabilidad tiene** cuando se juegan los partidos que faltan con nuestro modelo de goles.

Sustituye **en sombra** a `stakes-v5` (`fbi/ai/context.py`), que lee la descripción que el proveedor pone a cada fila y escribió «no
tiene nada en juego» de equipos que aún se jugaban la clasificación. **No retira nada**: `stakes-v5` y `scenarios-v1` siguen como
están y siguen siendo lo que leen los paquetes y las crónicas. No usa ningún modelo de lenguaje, ni internet, ni ninguna API de pago.
**No cambia nada de lo que ve el lector, ni picks, ni probabilidades publicadas, ni `decision-v1`.**

## 1. Qué hace, en una frase por parte

| Parte | Dónde | Qué hace |
| --- | --- | --- |
| Motor | `fbi/competitions/scenarios.py` | Lee el reglamento, arma cada tabla que decide algo (fase, grupos, tabla anual), certifica lo decidido y simula el resto. Puro: no toca la base de datos. |
| Datos y modelo | `fbi/competitions/scenario_store.py` | Lee la temporada **tal como se conocía en un momento**, ajusta nuestro modelo Dixon-Coles y guarda las lecturas. Interruptor `FBI_SCENARIOS`. |
| Comparación | `fbi/competitions/scenario_compare.py` | Dice qué afirmaciones de `stakes-v5` contradice el motor, lado por lado. |
| Repetición | `fbi/competitions/scenario_replay.py` | Recorre una temporada cerrada jornada a jornada y comprueba que nada de lo «decidido» resultó falso. |
| Registro | tabla `intel.scenario_readings` (migración **0147**) | Cada lectura en sombra, de solo añadido. |
| Mando | `scripts/ia_scenarios.py` | `read`, `compare`, `replay` (solo lectura) y `run` (el paso en sombra). |

## 2. Cuándo dice «decidido»

Cada objetivo se escribe como «terminar entre los N primeros» de una tabla: el título es N = 1; «clasificar entre los 8» es N = 8;
evitar los tres últimos de veinte es terminar entre los 17 primeros. Para un equipo:

- **Conseguido** si, en su peor caso —pierde todo lo que le queda—, menos de N rivales pueden terminar **con tantos puntos o más**.
- **Descartado** si, en su mejor caso —gana todo lo que le queda—, al menos N rivales terminan **con más puntos**.
- **Abierto** en cualquier otro caso.

Un **empate a puntos cuenta siempre en contra de la afirmación**. Por eso no hace falta saber cómo acabará ningún desempate (diferencia
de goles, enfrentamientos directos, fair play, sorteo): lo demostrado lo es pase lo que pase. Cuando dos rivales que importan se
enfrentan entre sí, el motor recorre exactamente los tres resultados (con más de 10 de esos partidos usa una cota más prudente, que
nunca afirma de más). Cuando ya se jugó todo, decide el orden final con los desempates del propio reglamento; un empate que solo
resuelve un sorteo o un partido de desempate queda abierto.

También cuenta: **sanciones de puntos** (se pasan como ajuste), **partidos aplazados** (siguen pendientes) y **partidos que aún no están
en el calendario** (si el reglamento dice 38 y hay 37, el que falta puede ganarse o perderse contra cualquiera). Si la tabla del
proveedor y los resultados no suman lo mismo para un club, se certifican las dos versiones y solo se afirma lo que ambas demuestran.

Lo que **nunca** se decide:

- una zona que el reglamento marca **condicional** (una plaza continental que depende de quién gane la copa): se dice dónde está el
  equipo respecto a esos puestos, pero no se afirma la plaza;
- una tabla que el motor no calcula todavía (un **promedio** de varias temporadas, una tabla que suma **eliminatorias**) o una fase de
  grupos cuyos grupos no se pueden identificar: se lista con su motivo y no se afirma nada;
- una competición sin reglamento codificado: estado **`reglamento_no_codificado`**, sin objetivos.

## 3. «Sin objetivo demostrado»

El hecho `SIN_OBJETIVO_DEMOSTRADO` es el único que autorizará decir «a este equipo ya no le queda nada en juego» (lo usará AD-F01). Solo
se emite cuando **todos** los objetivos de **todas** las tablas del equipo están decididos y demostrados, ninguna zona que podría
alcanzar es condicional, no queda ninguna tabla de la competición sin calcular y el reglamento no tiene huecos declarados en formato,
plazas continentales, ascenso, descenso o playoff. Si no, sale `demostrado: false` con los motivos.

Consecuencia honesta, a 16-nov-2026: con los reglamentos codificados hoy, el hecho solo puede salir en la **Liga MX** y para los
eliminados de la fase liga de la **Champions**. En las cinco grandes ligas europeas lo impide el hueco de plazas UEFA (no codificadas
por AD-B01); en Brasil, las plazas de Sudamericana que «bajan» de puesto; en Argentina, el descenso (Estatuto AFA no leído); en
Colombia, la tabla de descenso por promedio, que aún no se calcula. Es el comportamiento seguro: preferimos no afirmar a afirmar mal.

## 4. Qué se simula

Con una distribución de marcadores para cada partido que falta, se juegan **2.000 temporadas** con semilla fija (el resultado es
reproducible) y cada tabla final se ordena con los desempates del reglamento. La probabilidad de un objetivo es la parte de temporadas
en que se cumple. El modelo es el **mismo Dixon-Coles** del pronóstico en tiempo real, reajustado por competición con los resultados
conocidos tres horas después de cada saque y con la ventana, el decaimiento y la penalización de la especificación que usted promovió
(`analytics.promoted_forecast_spec`); si la corrección Dixon-Coles no vale para un partido, se usa el Poisson de la misma
especificación. Si un equipo no tiene resultados en la ventana, la tabla sale sin simulación y se dice. No se escribe nada en `models`.

Comprobación interna: algo **demostrado** tiene que salir con probabilidad 0 o 1 exactas en la simulación. Si no, se retira la
afirmación y la lectura lo cuenta (`contradicciones`). La probabilidad nunca es una afirmación por sí sola: 0,999 sin demostrar sigue
siendo «abierto».

## 5. Qué devuelve por equipo

Por cada objetivo: `objetivo` (`titulo`, `clasificacion`, `plaza_de_playoff`, `plaza_continental`, `ascenso`, `evitar_descenso`,
`evitar_promocion_de_descenso`, `evitar_eliminacion`), `puestos`, `estado` (`conseguido` / `descartado` / `abierto`), `decidido`
(`valor`, `demostrado`, `motivos`), `probabilidad`, `necesita` (puntos actuales, máximos, partidos que quedan y **los puntos con los que
lo asegura pase lo que pase**) y `depende_de` (`de_si_mismo` si puede asegurarlo con sus resultados, `de_otros` si no, y los rivales
directos). Para cada partido de la semana siguiente, qué hace cada resultado: por ejemplo, «con una victoria Millonarios se clasifica
pase lo que pase; con empate o derrota sigue abierto». `stakes_for()` lo aplana en la forma `stakes[]` del contrato del partido.

## 6. Qué se midió (16-nov-2026)

**Temporadas cerradas recorridas jornada a jornada** (cada día de partidos; datos de producción en solo lectura; la verdad es la tabla
final del proveedor o, cuando dos tablas de la temporada tienen los mismos clubes, el reglamento aplicado a todos los resultados):

| Competición | Días | Afirmaciones comprobadas | Falsas | Objetivos decididos | Mediana de días de antelación |
| --- | --- | --- | --- | --- | --- |
| Premier League 2025/26 | 114 | 929 | **0** | 40 de 40 | 23 |
| LaLiga 2025/26 | 144 | 1.333 | **0** | 60 de 60 | 23 |
| Serie A 2025/26 | 132 | 1.888 | **0** | 80 de 80 | 21 |
| Bundesliga 2025/26 | 102 | 1.017 | **0** | 54 de 54 | 18 |
| Ligue 1 2025/26 | 100 | 1.017 | **0** | 54 de 54 | 19 |
| Liga MX 2025/26 (Apertura y Clausura) | 113 | 881 | **0** | 54 | 68 |
| Colombia 2026, fases I de Liga I y II | 193 | 375 | **0** | 40 | 13 |
| Argentina 2026, zonas y tabla general | 168 | 2.320 | **0** | 150 | 17 |
| MLS 2026, conferencias y Supporters' Shield | 96 | 1.641 | **0** | 90 | 16 |
| **Total** | | **11.401** | **0** | | |

Ningún objetivo decidido cambió de estado después (0 «vueltas atrás»), y al terminar cada tabla no quedó nada abierto.

**Lo demostrado frente a la simulación**: en esas temporadas y en las de 2026 en curso (Brasileirão, Champions, Premier, LaLiga), cada
cuatro días de partidos, con el Dixon-Coles ajustado en ese momento y 500 temporadas simuladas: 285 lecturas, 305 tablas, 16.592
objetivos, 2.504 decididos y **0 contradicciones** (todo lo demostrado salió con 0 o 1 exactos).

**Comparación con `stakes-v5`** en la jornada real de seis ligas codificadas: 62 partidos (Colombia fecha 19 del Clausura, 14-nov;
Brasileirão 18-20 nov; Argentina, Liga MX, Bundesliga y Premier 5-9 nov), el último paquete antes de cada saque, 124 lados. `stakes-v5`
se recalculó con la función de producción sobre la misma foto de la tabla (en los paquetes del 5-8 nov aún constaban v2-v4):

| | Lados |
| --- | --- |
| `stakes-v5` dice «no se juega nada» | 58 |
| … y el motor **demuestra un objetivo abierto** (contradicción) | **16** (14 con probabilidad entre 1 % y 99 %) |
| … solo queda abierta una zona condicional | 8 |
| … todo lo codificado está decidido, pero no se puede demostrar «sin objetivo» | 26 |
| … el motor lo demuestra (`SIN_OBJETIVO_DEMOSTRADO`, Liga MX) | 8 |

Ejemplos de contradicción: Flamengo y Palmeiras, el título (86 % y 14 %); Millonarios, Once Caldas e Independiente Medellín, la
clasificación del Clausura; Boca Juniors y Rosario Central, la tabla general argentina; Toluca y Tijuana, la liguilla. De las 18 crónicas
de lectores de esos partidos que dicen «nada en juego» o similar, **8** hablan de un partido donde el paquete afirmaba «cerrado» para un
lado que el motor demuestra abierto.

**Los cinco casos del Doc 1**: Millonarios y Once Caldas (27 puntos, un partido) salen **abiertos** —con una victoria Millonarios lo
asegura—; Nürnberg (Frauen-Bundesliga), FC Cajamarca (Perú), Chipre (Nations League) y Växjö (Damallsvenskan) salen
`reglamento_no_codificado`, sin objetivo afirmado. Están fijados como prueba (`tests/unit/test_scenarios_real_ia082.py`).

## 7. Encender, apagar, revertir

- **Por defecto está apagado** (`FBI_SCENARIOS=off` en el código). Con `FBI_SCENARIOS=shadow` (y reiniciar el worker), el trabajo
  `scenarios_shadow` escribe cada 6 horas una lectura por temporada codificada en juego, solo si algo cambió desde la anterior. Ningún
  lector la lee. Apagar: volver a `off` (o quitar la línea) y reiniciar el worker; lo escrito se queda.
- **Migración 0147**: crea `intel.scenario_readings` y su función de rechazo; no escribe datos. Bajarla borra la tabla.
- **A mano, solo lectura**: `python -m scripts.ia_scenarios read --league 239 --season 2026`,
  `... compare --since 2026-11-14 --until 2026-11-20`, `... replay --league 39 --season 2025`.
- **Vuelta atrás**: dejar de leer `scenarios-v2` devuelve todo a `scenarios-v1`/`stakes-v5`, que no se han tocado. La retirada de
  `stakes-v5` es posterior y la decide usted cuando AD-F01 y C-01 entrega 2 lean este motor.

## 8. Límites que conviene saber

- Las plazas continentales de las ligas europeas, los descensos argentinos, los promedios colombianos y las eliminatorias no están
  codificados o no se calculan: allí el motor no afirma y lo dice.
- La cota prudente (más de 10 enfrentamientos directos que importan) puede dejar «abierto» algo que ya está decidido; nunca al revés.
  En las repeticiones hubo filas que la usaron (296 lecturas de objetivo en la Premier, 812 en Argentina); ninguna dio una afirmación
  falsa y al final de cada temporada todo quedó decidido.
- La simulación hereda los límites del modelo de goles (no sabe de lesiones ni de rotaciones); por eso nunca decide nada.
- El calendario es el que existía en el momento (un partido creado después no está), y los resultados, los registrados hasta entonces.
