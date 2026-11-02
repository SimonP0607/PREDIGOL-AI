# El ciclo de las familias en sombra (F11): decidir, liquidar, aprender y recordar · guía del propietario

*Escrita el 25 de octubre de 2026. Describe código que ya está escrito y probado en la rama de trabajo y que **está apagado por defecto**: mientras `FBI_FAMILY_DECISIONS` no valga `shadow`, el servidor no hace nada de lo que sigue y la pestaña «Familias» solo enseña lo que ya estuviera escrito. Todo lee y escribe en la base de datos propia: cero peticiones al proveedor, cero IA, y ningún modelo, pronóstico, precio, pick ni página de usuario lee lo que se escribe.*

## 1. En pocas palabras

* Las familias (goles por mitad, córners, tarjetas y amarillas) ya pronostican cada partido con modelos propios (F10, `FAMILIAS_F10.md`, versión `family-v1`), pero ese pronóstico era solo una cifra guardada: nadie lo juzgaba como se juzga un pick. F11 le da el mismo recorrido que tiene un pick, **en sombra**: decidir, liquidar, aprender de cada decisión y recordar.
* El recorrido son **cuatro pasos del worker**, cada uno con una versión propia (`decision-fam-v1`, `outcome-fam-v1`, `pm-fam-v1`, `memory-fam-v1`) y tablas propias, aparte de las del resto del sistema: lo que escribe una familia nunca se mezcla con lo que el sistema usa para sus picks.
* **Una familia no recomienda nada.** Lo máximo que decide es una *investigación* (nunca un pick, ni un premium ni una combinada) y su apuesta es **cero**. Ningún usuario ve nada de esto, y una prueba (`test_decision_version_guard.py`) obliga a cada lector de decisiones a decir qué versión lee, para que ninguno lea el de las familias por descuido.
* Se enciende con **una sola variable**, sin desplegar nada más: `FBI_FAMILY_DECISIONS=shadow`. Se apaga con `off`; lo ya escrito se queda como registro.
* Para verlo: *Administración → Aprendizaje → Familias* (`/admin/learning#tab=families`). Con el interruptor apagado y sin nada escrito enseña «Sin pasadas» y las tablas vacías.

## 2. El interruptor

| Valor de `FBI_FAMILY_DECISIONS` | Qué hace el worker |
|---|---|
| `off` (por omisión, y cualquier valor desconocido) | nada: el trabajo de decisión y el de la noche siguen como antes de las familias, sin ningún paso suyo y sin ninguna clave suya en su registro |
| `shadow` | una pasada de decisión por hora y, de noche, la liquidación, el post-mortem y la memoria |

El worker lo lee de su entorno: tras cambiarlo en `/etc/predigol/app.env` hay que reiniciar el worker, como con los demás interruptores de ese archivo (la plantilla es `deploy/vps/app.env.example`). Las tablas del post-mortem y de la memoria las crea la migración `0118`, que va en el siguiente despliegue; la API de la pestaña también la necesita. Quitarlo es poner `off` y reiniciar el worker: no hay nada que deshacer.

**Verlo antes de encenderlo.** Con el interruptor apagado se puede ver qué escribiría la primera pasada sin escribirlo: `python -m scripts.families decide`. Corre la misma pasada que el worker (los pronósticos de las familias de las próximas 36 horas, los precios que las casas ofrecían en ese momento y los diez filtros) con una sesión de la base de datos que no puede escribir: cero peticiones al proveedor, cero IA. Cuenta el embudo (pronósticos → selecciones con precio → candidatas → decisiones juzgadas → filas que escribiría), el reparto por familia, estado y motivo, lo que les falta saber con las búsquedas que costaría servirlo y una línea por decisión; si no hay nada que decidir, dice en qué paso se agotó. `--at` repite un momento (uno pasado dice lo que habría dicho entonces), `--fixture` mira un solo partido, `--top` limita las líneas del texto y `--json` lo da todo. Solo lee tablas que ya existen: no necesita la migración `0118`. No sustituye a la pestaña «Familias»: esa enseña lo que se escribió y esto lo que se escribiría.

## 3. Los cuatro pasos

| Paso | Paso del worker | Cuándo corre | Versión | Dónde escribe |
|---|---|---|---|---|
| Decidir | `families` (dentro de `intel_decide`) | una vez por hora, en la primera pasada de cada hora del trabajo que viene cada 15 minutos, **después** de elegir los picks del día | `decision-fam-v1` | `intel.decisions`, sin pick |
| Liquidar | `family_outcomes` (dentro de `intel_nightly`) | de noche, a las 07:50 hora de Bogotá | `outcome-fam-v1` | `intel.decision_outcomes` |
| Post-mortem | `family_postmortems` (dentro de `intel_nightly`) | de noche, justo después de liquidar | `pm-fam-v1` | `intel.family_postmortems` |
| Recordar | `family_memory` (dentro de `intel_nightly`) | de noche, el último | `memory-fam-v1` | `intel.family_memory` (y la vista `intel.family_memory_latest`) |

Cada paso es **un paso aparte** del trabajo que lo lleva. El de decidir es el último del trabajo de decisión, así que no retrasa los picks del día; los de la noche van cada uno justo después del paso del sistema al que siguen (liquidar tras liquidar, post-mortem tras post-mortem, memoria tras memoria), de modo que cuando leen, lo que necesitan ya está escrito. Si uno falla, el trabajo lo apunta en su registro (queda «parcial» y dice, por ejemplo, `families: …`), los demás pasos siguen y el resto del sistema no se entera. Los fallos se ven en el bloque «El ciclo» de la pestaña. Las tablas son de solo añadir (como las del resto de la capa de decisión): una regla que cambia es una versión nueva (`decision-fam-v2`, `pm-fam-v2`…) y las filas de la anterior se quedan tal como se escribieron.

## 4. Cómo decide una familia

Cada hora el worker lee los pronósticos de las familias de los partidos de las **próximas 36 horas** y los precios que las casas ofrecían en ese momento, y se queda con las selecciones que cumplen **todo** esto (es la regla de las apuestas simuladas del criterio de F11.5, `CRITERIO_FAMILIAS_F11.md`, leída en el momento de la decisión):

* una línea sin devolución posible (sin línea, o con «medio»);
* un tipo de apuesta para el que se puede construir un consenso de las casas: más/menos, ambos marcan, par/impar, empate no apuesta y 1X2;
* **3 casas completas o más** detrás del precio (una casa completa cotiza todas las opciones de esa línea, con un margen de 1,25 como mucho);
* un **valor visto de al menos 3 %** al mejor precio (probabilidad del modelo × cuota − 1);
* y solo **la mejor línea** de cada mercado de cada partido por modelo: las líneas de un mercado son la misma pregunta vista varias veces.

A cada selección le pasa lo mismo que a un pick: los **diez filtros** de la capa de decisión (`PREDIGOL_INTELLIGENCE.md`, sección 5), su puntuación y su apuesta. Lo que cambia es lo que las familias son todavía:

* **El estado nunca pasa de investigación.** El resultado es `INVESTIGACION` (la familia ve valor y se mide) o `RECHAZADO` (algún filtro la frena y la fila dice cuál). Si el juez diera un estado más alto, se le baja a investigación y la fila lo dice con `family_shadow_only`. Toda fila lleva además `family_research`: «familia en investigación», el estado de partida de todas.
* **La apuesta es cero.** Sin calibrador no hay apuesta, y el tope de la investigación es cero de todos modos (`stake-v1`).
* **Lo que no se aplica, a propósito:** la edad del pronóstico (una familia guarda un pronóstico nuevo solo cuando una probabilidad se mueve medio punto, así que uno viejo es uno que se mantuvo), la anchura del intervalo (ninguna familia declara intervalo todavía; se juzgará el día que lo haga) y la correlación (las familias no compiten por el partido: no pasan de investigación).
* **La probabilidad es la del modelo, sin calibrar.** Es el número del propio modelo de la familia, y el juez le aplica el calibrador que conozca; las familias no tienen ninguno. No es una recomendación.

Una decisión se **revisa** cuando cambia lo que la familia ve (un pronóstico que se mueve, un precio nuevo): la revisión es una fila nueva, no se reescribe la anterior. Por eso un mismo partido puede tener varias filas para el mismo modelo y mercado; la pestaña muestra siempre la última y cuenta cuántas hubo.

**Lo que la decisión no sabía: pedir investigación.** La IA del sistema puede pedirle al servidor que investigue un partido (nombra un tema de una lista cerrada y el servidor decide si y cuándo; nunca escribe la búsqueda). Esa puerta es para los picks que el sistema preselecciona: una selección de una familia no tiene pick ni revisión de la IA, y nadie estaba ahí para pedirlo. Por eso cada decisión de una familia lleva **un registro más entre sus filtros**, `research` (versión `research-fam-v1`), que hace esa misma petición por cuenta del servidor, en el momento de decidir, y la deja escrita **sin servirla**:

* **Qué le faltaba saber**, cosa por cosa, con su estado en el momento de la decisión (`KNOWN` sabida, `PARTIAL` en parte, `MISSING` falta) y, si se sabía, desde cuándo. Son tres cosas posibles: *el árbitro designado* y *las alineaciones confirmadas*, que trae el proveedor sin ninguna búsqueda, y *el contexto de fuera* (bajas y previa), lo único que solo una búsqueda mejora. Cada familia pide las suyas: los goles por mitad y los córners, alineaciones y contexto (dependen de quién juega); las tarjetas y las amarillas, árbitro y contexto (su modelo multiplica la media por el factor del árbitro cuando hay uno designado). El contexto es la palabra que ya usan los diez filtros: completo es sabido, parcial es en parte, y limitado, pendiente o IA apagada es que falta.
* **Qué costaría averiguarlo:** las búsquedas de la búsqueda escalonada de la IA, una por nivel; el contexto abarca los tres niveles, así que son 3 búsquedas. Son las que necesitaría esa selección: la búsqueda de un nivel sirve a todas las selecciones del mismo partido, y tres selecciones de un partido no cuestan tres veces. Lo que solo trae el proveedor no cuesta ninguna.
* **Que no se sirve:** `served` es falso y, cuando lo que falta se pediría a una búsqueda, `unserved` dice `family_shadow`. Las familias deciden en sombra, sus decisiones no llegan a nadie, y las búsquedas y el presupuesto del día son tuyos (decisión 12 del estado del plan). El día que una familia salga de la sombra y permitas el gasto, servir la petición será un paso aparte, añadido con su razón a la vista; este registro es lo que leería.
* **Qué factores podrían explicarla:** los factores de contexto del registro (`fbi.intel.factors`) que un experimento de F12 podría probar contra esa familia, con la versión de cada uno y su estado en el momento de decidir: la *táctica observable* para los goles por mitad y los córners; los *escenarios de tabla y de eliminatoria* para los goles por mitad, las tarjetas y las amarillas; el *descanso y congestión* para los goles por mitad. Son hipótesis para empezar un experimento, no resultados: un factor es descriptivo hasta que una persona valida un experimento suyo, y ningún modelo de una familia lee ninguno.

El registro es **informativo**: no cambia el estado, ni los motivos, ni la puntuación, ni la apuesta de la decisión (una prueba compara la decisión con y sin el registro), no lee noticias, no llama al proveedor y no gasta dinero. Lee el árbitro y los factores **tal como estaban en el momento de la decisión**: un árbitro designado después no cuenta, igual que una alineación leída después. Si esa lectura falla, la decisión se escribe igual, sin el registro (o, si lo que falla es el registro de factores, con todos sin validar y diciéndolo). Y se actualiza **solo cuando se escribe una fila nueva** de la decisión por otra razón (un pronóstico que se mueve, un precio nuevo, un cambio de contexto, un punto de control): una alineación que llega entre dos filas se verá en la siguiente. Se ve en la columna «Qué le falta saber» de la pestaña y, en el detalle de la decisión, como el filtro «Pedir investigación».

## 5. Cómo se liquida

De noche, el worker liquida las decisiones de los partidos que terminaron **30 horas** atrás o más (las estadísticas de las tarjetas se asientan unas 26 horas después del partido) y que no pasaron de hace **30 días**. Cada decisión se liquida **con los conteos del partido**, no con un pick: las familias no tienen picks. La regla que la califica es la de su mercado:

| Regla | Qué cuenta |
|---|---|
| `goals_1h@v1` | los goles de la primera parte (el marcador al descanso) |
| `goals_2h@v1` | los goles de la segunda parte (los de los 90 minutos menos los del descanso) |
| `goals_halves@v1` | las dos partes a la vez (descanso/final, mitad con más goles) |
| `corners_ft@v1` | los córners del partido (sin cifra tras la prórroga: el proveedor no dice si su total incluye la media hora extra) |
| `cards_lines_ft@v1` | cada tarjeta mostrada cuenta una: cada amarilla y cada roja (la roja que sigue a una segunda amarilla cuenta como la roja que es) |
| `yellow_ft@v1` | solo amarillas: la primera de un par cuenta; la roja que la sigue, no |

El proveedor no dice qué convención usan las casas detrás de «Tarjetas más/menos»: la regla de `cards_lines_ft@v1` es una convención nuestra, y la pestaña lo avisa en la tarjeta de la familia.

* **Un conteo desconocido no se lee como una derrota.** La decisión queda sin liquidar y se reintenta en la pasada siguiente.
* **El beneficio es por unidad** a la cuota de la propia decisión: gana, cuota − 1; media ganada, (cuota − 1) / 2; devuelta o anulada, 0; media perdida, −½; pierde, −1. Como la apuesta de una familia es cero, no hay beneficio «apostado»: es lo que habría dado una unidad.
* **El valor de cierre** (`clv-v1`, la única definición del sistema) compara el precio de la decisión con el consenso de las casas del último momento antes del inicio, con las mismas 3 casas completas como mínimo. Sin consenso no hay valor de cierre y la decisión se liquida igual.

## 6. Qué aprende de cada decisión (el post-mortem)

Un partido puede tener varias revisiones de la misma decisión, y estudiarlas todas contaría un partido tantas veces como se movió su precio. El post-mortem estudia **la que quedó en pie**: la última de cada modelo, mercado y partido, y solo si esa última palabra fue una selección (una investigación) y no un rechazo. Las revisiones se liquidan todas, pero solo la última se estudia; cuántas hubo queda en la evidencia de la fila.

Pregunta dos cosas, con las definiciones del post-mortem del resto del sistema:

* **La calidad del precio** (nunca la del resultado): el valor de cierre por encima de +1 % es `GOOD`, por debajo de −1 % es `BAD`, entre medias `NEUTRAL`, y sin cierre `UNKNOWN`.
* **El veredicto**, que separa la suerte de la decisión cruzando calidad y resultado:

| Resultado | Calidad del precio | Veredicto | Qué enseña |
|---|---|---|---|
| ganó | buena o neutra | `MERECIDO` | decisión y resultado alineados: se suma a la memoria de la familia, nada que cambiar |
| ganó | mala | `SUERTE` | ganó con el precio peor que el cierre: no enseña nada a favor del modelo |
| perdió | buena o neutra | `VARIANZA` | decisión con precio bueno o neutro que perdió: varianza; no se toca el modelo |
| perdió | mala | `ERROR` | precio peor que el cierre y perdió: a revisar en el patrón del mercado de la familia, no por este partido |
| devuelta o anulada | cualquiera | `NULO` | sin resultado que juzgar (devuelta o anulada) |
| cualquiera | sin cierre | `SIN_DATOS` | sin cierre para juzgar el precio de la decisión |

Además apunta lo que pasó en el partido y el modelo no podía ver (una roja, un penalti, un gol pronto, un cambio pronto; para las tarjetas, lo que mostró el árbitro frente a lo que suele mostrar), el número sobre el que se calificó la línea y por cuánto la pasó, y las respuestas en español con cifras guardadas: la probabilidad que dijo la familia (sin calibrar) frente a la de las casas en la decisión y en el cierre. Lee solo lo guardado: la decisión, su liquidación y los eventos y estadísticas del partido. Cero peticiones, cero IA.

## 7. Qué recuerda (la memoria)

Una decisión sola no cambia nada. La memoria es donde los post-mortems se vuelven un historial: los suma por **familia**, por **mercado**, por **competición** y por **árbitro**, sobre todo lo que tiene (`all`) y sobre los partidos de los últimos **28 días** (`recent`). Una competición o un árbitro necesitan al menos 3 post-mortems para existir (con uno o dos serían una anécdota que solo mete ruido en una consola); una familia o un mercado, uno.

Para cada entidad guarda cuántas decisiones estudió y cuántas se ganaron o perdieron de lleno; la **tasa de acierto** frente a lo que la familia **dijo** que acertaría (la media de sus probabilidades) y la diferencia entre ambas, con su `z` (−2 o menos es una familia que prometió mucho más de lo que dio); el valor de cierre medio; lo que habría dado una unidad en cada decisión; y cuántos veredictos de cada clase hubo. La **confianza** va de 0 a 1 y vale `n_eff / (n_eff + 30)`, donde `n_eff` suma, por decisión, `0,5` elevado a la edad en días entre 60: una decisión pierde la mitad de su peso cada **60 días**. Los 28, los 60 y los 30 son convenciones de la memoria, no parámetros de ningún modelo; cambiar uno es `memory-fam-v2`.

Escribe de noche, y una entidad solo escribe una foto nueva si tiene post-mortems que la anterior no tenía: una noche sin nada nuevo no escribe nada. Como mucho una foto por entidad y por día de Bogotá. La memoria de las familias **no es** la memoria del resto del sistema (`POSTMORTEM_MEMORIA_F8.md`): esa la leen el informe del día, los patrones y las lecciones que recibe la IA, y una capa de investigación con pronósticos sin calibrar no debe mover sus tamaños de muestra. Esta alimenta una consola y tus decisiones.

## 8. La pestaña «Familias»

Solo la ve un administrador (`GET /admin/intelligence/families`; solo lee, sin escribir nada). De arriba abajo:

* **El ciclo.** Los cuatro pasos con la última vez que trabajaron de verdad (un cuarto de hora en el que no tocaba pasada no cuenta), su estado y, si falló, el error. Mira los últimos **7 días**. Arriba, el modo: «En shadow», «Apagado» o «Sin pasadas».
* **Una tarjeta por familia.** Cuántas selecciones y cuántos rechazos tiene su última palabra, cuántas están liquidadas y cuántas abiertas, el reparto de resultados y de veredictos, las reglas con las que se liquidan (con el aviso de las tarjetas) y lo que recuerda la familia.
* **La última palabra de cada una.** Una fila por modelo, mercado y partido: la última decisión que escribió la familia antes del inicio. Se ve el mercado y la selección con su línea, la cuota, la probabilidad de la familia (sin calibrar) frente a la del mercado, el valor bruto que veía, el estado, **lo que le faltaba saber** (cada cosa con su estado, las búsquedas que costaría, que no se sirve y los factores que podrían explicarla; «Sin registro» para una decisión anterior a ese registro), la regla que la liquida, el resultado (con el beneficio y el valor de cierre) y el post-mortem. Pulsando una fila se abre el detalle de la decisión (los filtros que aplicó, el pronóstico que citó, su post-mortem).
* **Lo que recuerdan.** La memoria por familia, mercado, competición y árbitro: todas las familias y todos los mercados y, de las competiciones y de los árbitros, los 25 con más post-mortems de cada tipo, con la fecha a la que está al día.

Los filtros son la familia, el estado y la ventana de partidos (por omisión 14 días, como mucho 120).

**En la ficha de un partido.** La vista previa del administrador del bloque «Pronóstico PrediGol» trae, junto al valor y los picks, una sección «Familias» con lo que las cuatro familias pronostican de ese partido (versión `family-v1`): mercado por mercado y línea por línea, con la cuota justa (1 / probabilidad) y la regla que liquidaría una apuesta en ese mercado. Es la cifra que esta pestaña juzga después: aquí ves lo que dijo la familia, allá lo que hizo con ello. Ningún usuario la recibe.

## 9. Cómo leerla, y cómo no

* **El valor bruto que ve la familia no es ventaja.** Por construcción es de al menos 3 % y casi siempre es sesgo del propio modelo: elegir la mejor línea escoge justo los mayores desacuerdos con el mercado. Lo que mide si un precio estaba bien es el **valor de cierre**.
* **El rendimiento por unidad es suerte mientras haya pocas decisiones.** Con 300 apuestas tiene entre ±4 y ±6 puntos de error (`CRITERIO_FAMILIAS_F11.md`, sección 3). Mira antes el valor de cierre medio, la brecha entre lo que acertó y lo que dijo y la confianza.
* **Una brecha grande con muchas muestras merece investigación; con pocas es ruido.** Para eso está la confianza.
* **El cierre no está demostrado como el cierre real**: es el último consenso capturado antes del inicio.
* **Los córners no tienen datos por mitad** (el proveedor da el total del partido) y la convención de las tarjetas es nuestra.
* **Nada de esto promueve una familia.** Qué familia pasa a algo más que sombra lo decides tú, con las puertas del plan (`CRITERIO_FAMILIAS_F11.md`, `PROMOCIONES_F12.md`).

## 10. Lo que decides tú

1. **¿Encender `FBI_FAMILY_DECISIONS=shadow`?** Es lo que cierra F11 («una familia completa el ciclo en sombra»). Antes de decidir, mira qué escribiría con `python -m scripts.families decide` (sección 2). Mi recomendación es encenderlo cuando se despliegue la migración `0118`: cuesta una lectura por hora y una pasada nocturna, no usa IA ni peticiones al proveedor, es reversible con `off` y solo lo ve un administrador. Hasta entonces el criterio de F11.5 (`CRITERIO_FAMILIAS_F11.md`) seguirá midiendo las apuestas simuladas por separado. (Decisión 30 del estado del plan.)
2. **¿Los pronósticos de las familias a los usuarios?** No lo propongo: son sin calibrar y no hay ninguna cifra todavía de que valgan algo. (Decisión 22 del estado del plan.)
3. **¿Relajar la regla de «una selección por partido» entre familias?** Hoy no (`DEPENDENCIA_FAMILIAS_F11.md`). (Decisión 26.)
4. **¿Servir algún día las peticiones de investigación de una familia?** Hoy no se sirve ninguna y no hace falta decidirlo: el registro de lo que le faltaba saber ya está escrito en cada decisión. Servirlas exige que la familia salga de la sombra y que permitas el gasto de búsquedas (decisión 12); hasta entonces es solo un dato para que veas qué pediría y cuánto costaría.
