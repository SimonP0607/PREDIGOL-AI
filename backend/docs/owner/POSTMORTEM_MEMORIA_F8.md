# Post-mortem único y memoria con confianza: lo que PrediGol aprende de cada partido, en un solo sitio (Plan Maestro, fase F8)

**Qué es.** Después de un partido, PrediGol apuntaba lo aprendido en **tres** sitios que no coincidían, medía el valor de un precio de **dos**
maneras y repartía la memoria de equipos, árbitros, entrenadores y mercados en **cuatro** rincones de la consola, sin decir cuánto fiarse de
cada número. Medido en producción el 23 de octubre de 2026: `ai.postmortems` (`pm-v1.1`, por partido) tenía 1.139 filas,
`ai.pick_postmortems` (`pm-v2`, por selección) 2.487 e `intel.postmortems` (`pm-v3`, por decisión) 78, y solo 20 selecciones estaban en dos
de ellas. Cada pantalla, cada lección diaria y cada búsqueda de patrones elegía una y contaba otra cosa; los picks que ven los usuarios
estaban solo en `pm-v2`; y el promedio de córners de un equipo con tres partidos se veía igual que el de uno con trescientos.

F8 deja **una sola de cada cosa**:

* **Un post-mortem** (`pm-v6`): una fila por selección, armada **por reglas** (sin IA y sin coste), con las mismas preguntas para todas, venga
  de la capa de decisión, de la IA o de lo que ven los usuarios.
* **Un CLV** (`clv-v1`) y **un cierre de referencia con nombre**, guardado junto a cada número.
* **Una memoria** (`memory-v4`) con **confianza** y **evidencia** en cada fila, y tres aspectos nuevos por equipo y por liga: córners,
  tarjetas y goles esperados, con los pesos de la contracción **medidos** sobre los partidos guardados.
* **Una página** de la consola (`/admin/memory`, «Memoria») en vez de cuatro sitios.

**F8 no cambia ningún modelo, pronóstico, decisión, pick ni liquidación, ni el modo SHADOW; no pide nada al proveedor (0 peticiones); no
gasta IA, salvo las narrativas opcionales de abajo y dentro del tope diario de siempre; y no muestra nada a ningún usuario.** Lo aprendido de
un partido tampoco puede colarse en lo que se dice antes de otro: ningún lector de antes del partido lee post-mortems, memoria ni notas de
aprendizaje, y una prueba permanente lo vigila.

Lo que **no** es: no es una señal (no alimenta ningún modelo ni filtro); una derrota nunca reentrena nada (va a la memoria, y solo un patrón
sobre muchos casos llega a una hipótesis); y todavía **no se inyecta en el paquete de la IA** (decisión tuya, abajo).

*Los nombres.* El plan hablaba de `pm-v3` y de «memoria v2»; esos nombres ya estaban usados (F0 y F3 escribieron `pm-v4` y `pm-v5`, y
`memory-v2` y `memory-v3`), así que el canónico es **`pm-v6`** y la memoria es **`memory-v4`**.

## Qué escribe (y qué no)

Una migración, solo aditiva:

| Migración | Objeto | Para qué |
|---|---|---|
| **0091** | `intel.postmortems` (existía: 104 filas de `pm-v3` a `pm-v5`) | Gana columnas **opcionales**: la selección (`market_key`, `selection`, `line`), por qué se estudió (`roles`), la revisión que tuvo (`review_id`, `review_decision`, `review_verdict`), la clase de la pérdida (`loss_class`), los precios (`odds`, `close_odds`, `p_model`, `p_market`, `p_close`), el movimiento de precio y el CLV. `decision_id` pasa a ser opcional (una selección puede no tener decisión). **Las 104 filas de antes no se tocan.** Sigue siendo solo-añadir (un disparador rechaza cambiar o borrar). |
| | `intel.selection_postmortems` | Vista: la fila más reciente de cada selección (`pm-v6` y posteriores). Es lo que leen las pantallas y el aprendizaje. |
| | `intel.match_postmortems` | Una fila por partido y versión: lo que antes guardaba `ai.postmortems` (la evidencia de la IA frente a quién jugó de verdad; el pronóstico 1X2 frente al cierre del mercado). Solo se añade. |
| | `ai.postmortem_narratives` | La narrativa corta que escribe un modelo de lenguaje sobre las pérdidas que importan, **aparte** del post-mortem: este se arma por reglas a coste cero y la narrativa es opcional y de pago. Solo se añade. |
| | `intel.entity_memory` (existía: 5.624 filas) | Gana `confidence` (0 a 1) y `evidence_ref` (en qué se apoya la fila). Ambas, nulas en todo lo escrito antes. |
| | `intel.entity_memory_latest` | Vista: por entidad, aspecto y día, la fila de la versión **más nueva** de la memoria. La regla «gana la más nueva» vive en un solo sitio. |

Nada de lo que ya existe cambia en lo que dice: `ai.postmortems`, `ai.pick_postmortems` y `ai.memory_events` siguen ahí, legibles; las dos
primeras **dejan de recibir filas nuevas** (un interruptor las devuelve, abajo). Los permisos los aplica `predigolctl deploy` con el mecanismo
de siempre (la API solo lee; el worker escribe). No hay claves foráneas hacia `core.fixtures` —por la misma razón que en la 0090:
`fixtures_sync` mantiene una transacción de escritura de unos 27 minutos cuatro veces al día— y la migración solo toca dos tablas pequeñas,
así que no necesita bloquear nada grande; si no consigue un bloqueo en 10 segundos falla entera, sin dejar nada a medias.

## Lo que se midió antes de construir (producción, solo lectura, 23 oct 2026)

| Medida | Resultado |
|---|---|
| Los tres post-mortems | `pm-v1.1`: 1.139 partidos. `pm-v2`: **2.487 selecciones** (9–22 oct): 2.453 revisadas, 936 por el modelo de lenguaje, 479 rechazadas, 94 piernas de parlay y 90 picks del día. `pm-v3`: **78 decisiones**. Solo 20 selecciones en dos. |
| La capa de decisión frente a la IA | La capa de decisión juzga **2–20 selecciones al día**, la IA ≈ 190. En 14 días, una sola selección terminó en CAUTELA o mejor (ninguna aprobada) y 217 estuvieron entre las 20 mejores INVESTIGACIONES de su día. |
| El mismo precio, visto por partes distintas | Una selección llega a PrediGol con hasta **tres precios**: el que vio un usuario (pick del día, pierna de parlay), el que congeló la capa de decisión y el que leyó el revisor de la IA. En 14 días **coinciden solo en el 31 %** de los pares ítem/revisión y en el 36 % de los pares decisión/revisión; la diferencia media es de 2,6 a 3,7 %, **mayor que la banda de ±1 %** con la que se etiqueta un CLV. |
| Dos CLV | `pm-v2`: movimiento frente al último precio de la misma casa, umbral −3 %. `pm-v3`: consenso sin margen, ±1 %. El aprendizaje comparaba cosas que no eran iguales. |
| La memoria | Solo `memory-v1` (entrenadores, jugadores, árbitros, mercados) y sin confianza ni córners, tarjetas o goles esperados. Cuatro lugares en la consola: Intelligence, la capa de decisión, el analista de IA y Evolución. |
| Un pariente que ya existía | `ai.memory_events` (13.197 filas): el registro de hechos que alimenta los patrones de la IA; no es un post-mortem y no se toca. |

## El post-mortem único (`pm-v6`)

**Qué se estudia.** Una selección (partido, mercado, selección, línea) se estudia cuando **alguien la miró**: la capa de decisión (su última
decisión antes del inicio, si llegó a CAUTELA o más, o es una de las 20 mejores INVESTIGACIONES de un día de Bogotá ya terminado: así la capa
aprende aunque no apruebe nada), un pick del día o la pierna de un parlay (lo que vieron los usuarios), una selección que revisó un modelo de
lenguaje, o cualquier selección revisada de un partido en el que la IA trabajó ese día. La fila lleva `roles` con todos los motivos.

**Cuándo.** Tres horas después del inicio del partido (los eventos, las estadísticas y las alineaciones llegan después del pitido final) y
**una sola vez** (un índice único lo garantiza: ejecutarlo otra vez no escribe nada). Mira los últimos 7 días y hasta 400 selecciones por
corrida.

**Qué responde**, siempre con números guardados y nunca con lo que pasó después del inicio mezclado con lo que se sabía antes:

| Pregunta | Cómo se responde |
|---|---|
| ¿Era bueno el precio? | Por el **CLV** (`clv-v1`): más de +1 % es BUENO, menos de −1 % MALO, entre medias NEUTRO; sin precio de cierre, DESCONOCIDO. Es la **calidad de la decisión**; nunca es el resultado. |
| ¿Fue suerte o decisión? (`verdict`) | Calidad × resultado: ganó con precio bueno o neutro, **MERECIDO**; ganó con precio malo, **SUERTE**; perdió con precio bueno o neutro, **VARIANZA**; perdió con precio malo, **ERROR**; push o nula, **NULO**; sin cierre, **SIN_DATOS**. |
| ¿Qué decidió la revisión de la IA? (`review_verdict`) | Aparte y sin mezclar: aprobada y ganó/perdió, con cautela y ganó/perdió, rechazada y habría ganado, rechazada con acierto, sin revisión y ganó/perdió, push. |
| ¿Por qué se perdió? (`loss_class`) | La **primera que aplica**: datos, ejecución, contexto, mercado, modelo, varianza normal, desconocida. |
| ¿Qué pasó en el partido que el modelo no podía ver? (`causes`) | Rojas (minuto y de quién), penaltis convertidos o fallados (los de una tanda no cuentan), gol temprano, cambios tempranos, tarjetas frente a lo que suele sacar su árbitro (por persona), y lo que los goles esperados dicen que merecía el partido. |
| Las diez preguntas de la IA y las ocho de la capa de decisión | Qué se esperaba, qué pasó, qué decía el modelo, qué información había, qué señal se ignoró, cómo se movió el precio, qué ausencia clave hubo, si cambió la alineación, qué incertidumbre había y cuánto fue varianza; más las de la capa de decisión (probabilidad, precio, mercado, lo no visto, contexto, suerte o decisión, aprendizaje, cambio). |

**Qué precio se toma.** Un orden fijo, **ítem → decisión → revisión**: el que vio el usuario, si lo hubo; si no, el que congeló la capa de
decisión (con su casa y su momento); si no, el que leyó el revisor. Los tres se guardan (`evidence.prices`), el elegido se nombra
(`evidence.price_from`) y `python -m scripts.postmortems status` cuenta cuántas veces importa la elección.

**El partido entero.** `intel.match_postmortems` guarda, una vez por partido, lo que `ai.postmortems` guardaba: el marcador, la evidencia de
la IA contrastada con las alineaciones (un jugador dado por baja que salió de titular; un titular habitual ausente sin aviso) y el pronóstico
1X2 del modelo frente al cierre del mercado.

**Una derrota nunca cambia nada.** El resultado de una selección va a la memoria (y de la memoria a los patrones de la IA); solo un patrón
sobre muchos casos, con su muestra mínima y z ≥ 3 (ya existía), puede llegar a una hipótesis, y de ahí a un experimento, una puerta y una
promoción explícita tuya.

## Un solo CLV y un solo cierre de referencia

* **El CLV** es siempre `cuota × p_cierre − 1` (`clv-v1`, `fbi.market.closing_value`), con `p_cierre` la probabilidad sin margen (Shin) del
  último consenso antes del inicio. Lo escribían ya `intel.decision_outcomes`, la auditoría de picks, la puerta walk-forward y la evaluación
  de la IA; ahora lo usa también cada post-mortem.
* **El movimiento de precio** (`cuota / cierre de la misma casa − 1`) **no es CLV**: lleva el margen de la casa en los dos precios, así que
  con un margen de cierre típico −3 % de movimiento son ≈ −7 % de CLV. Se guarda aparte (`price_move`) y nunca se promedia con un CLV.
* **El cierre de referencia** es el **último consenso sin margen capturado antes del inicio** (`last-shin-consensus-before-kickoff`,
  `fbi.market.closing_reference`): una mediana de ≈ 175 minutos antes del inicio. El otro candidato es el último precio del propio proveedor
  en la misma casa: mediana ≈ 85 minutos antes y presente en el 72 % de los partidos. **No cambié el cierre en silencio.** Cada post-mortem
  guarda `close_minutes_to_ko` y marca `far` cuando el cierre es más de 120 minutos anterior al inicio (en ese caso el CLV es valor frente a un
  precio casi de cierre, como en el resto del sistema), y `python -m scripts.postmortems closes --days 15` mide los dos cierres **sobre las
  mismas selecciones**: en cuántas existe cada uno, a qué distancia del inicio, y cuánto cambia la etiqueta (BUENO / NEUTRO / MALO) según cuál
  se use. Qué cierre manda lo decides tú (abajo).

## La memoria (`memory-v4`)

**Una fila** es el estado acumulado de una entidad en un aspecto un día (zona de Bogotá): un equipo, una competición, un mercado, un árbitro
(la persona, no el texto del proveedor), un entrenador (por id) o un jugador; y su aspecto (decisiones por mercado, disciplina, perfil,
disponibilidad, córners, tarjetas, goles esperados).

**Confianza y evidencia.** Cada fila dice **cuánto fiarse** (`confidence`, de 0 a 1) y **en qué se apoya** (`evidence_ref`: los partidos, las
decisiones y los post-mortems que la forman; los 40 más recientes). La confianza es la **muestra efectiva** sobre ella misma más una
constante, `n / (n + k)`: 0 sin evidencia, un medio cuando la muestra vale `k`, nunca 1. La muestra es efectiva porque **cada pieza de
evidencia pierde la mitad de su peso tras una vida media** (un árbitro tiene un estilo que dura un año; la disponibilidad de un jugador, unos
meses). La muestra efectiva se arrastra de una fila a la siguiente con los días que hay entre las dos, de modo que la fila de un día dice
cuánto de la memoria es reciente. Son **convenciones de la memoria, no parámetros de un modelo**:

| Memoria | Vida media | Constante `k` (la confianza es ½ con…) |
|---|---|---|
| Decisiones de un equipo | 90 días | 30 decisiones |
| Decisiones de una competición | 90 días | 60 decisiones |
| Decisiones de un mercado | 180 días | 100 decisiones |
| Árbitro (persona) | 365 días | 20 partidos |
| Entrenador (por id) | 365 días | 10 partidos |
| Jugador (disponibilidad) | 120 días | 5 bajas informadas |
| Córners, tarjetas y goles esperados **de un equipo** | 180 días | **15 / 38 / 10 partidos** (el peso de la liga, abajo) |
| Córners, tarjetas y goles esperados **de una liga** | 365 días | 60 partidos |

**Córners, tarjetas y goles esperados.** Un equipo con dos partidos que sumaron 14 córners no «promedia siete»: dos partidos dicen poco. Las
cifras de un equipo (lo que produce y lo que concede por partido) se **contraen hacia la media de su liga**: `propio_contraído =
(córners ponderados + m × media de la liga) / (partidos ponderados + m)`, de modo que un equipo con pocos partidos es la media de su liga y
uno con muchos es él mismo. Un equipo que jugó en dos competiciones se contrae a la media de ambas ponderada por sus partidos en cada una. La
media de la liga sale de la fila propia de la competición (`competición × córners`). Y, como la constante de la confianza es esa misma `m`,
**la confianza de una fila de estas es exactamente la parte de la cifra mostrada que es del propio equipo; el resto es de su liga**
(`propio_contraído = confianza × propio + (1 − confianza) × liga`, comprobado en las pruebas).

**Los pesos de la contracción, medidos y no supuestos.** El borrador usaba 6, 9 y 7 «por cómo se comporta el fútbol». Con
`python -m scripts.memory priors` se miden sobre los partidos guardados: cuánto varía una cifra de un partido a otro **dentro** de un equipo,
cuánto difieren **entre sí** los equipos de una misma competición, y su cociente (de varianzas) es **cuántos partidos vale la media de la
liga**. Sobre los **34.611 partidos terminados de los últimos 365 días** (23 oct; equipos con ≥ 5 partidos que reportan la cifra, en
competiciones con ≥ 8 de esos equipos; solo lectura):

| Cifra | Competiciones | Equipos | Actuaciones | Desviación de un partido | Desviación entre equipos | `m` lo que produce / lo que concede | Se usa |
|---|---|---|---|---|---|---|---|
| Córners | 89 | 1.721 | 39.526 | 2,75 | 0,70 | 15,3 / 14,7 | **15** (antes 6) |
| Tarjetas | 90 | 1.839 | 43.609 | 1,45 | 0,24 | 37,0 / 38,5 | **38** (antes 9) |
| Goles esperados | 68 | 1.310 | 26.901 | 0,78 | 0,28 | 7,9 / 11,4 | **10** (antes 7) |

Es decir: el ruido de un partido es cuatro veces la diferencia típica entre dos equipos de la misma liga en córners, seis en tarjetas y
casi tres en goles esperados, y por eso la media de la liga vale tanto. **Aguanta cuando cambian la ventana y los mínimos:**

| Variante | Córners | Tarjetas | Goles esperados |
|---|---|---|---|
| 365 días (la de arriba) | 15,3 / 14,7 | 37,0 / 38,5 | 7,9 / 11,4 |
| 730 días | 15,7 / 15,7 | 34,2 / 31,5 | 7,9 / 11,8 |
| 180 días | 16,1 / 15,7 | 46,4 / 65,5 (ruidosa) | 7,1 / 12,9 |
| 365 días, ≥ 10 partidos y ≥ 12 equipos | 15,5 / 15,3 | 38,5 / 41,4 | 7,9 / 12,7 |
| 400 días, ≥ 3 partidos y ≥ 6 equipos | 14,2 / 14,4 | 41,1 / 38,8 | 7,7 / 10,6 |

En goles esperados lo que un equipo **crea** (≈ 8) se mide con más firmeza que lo que **permite** (11 a 13); se usa un solo peso, 10,
porque para un equipo a 0,3 goles de su liga y con diez partidos la diferencia entre 8 y 12 mueve la cifra contraída menos de 0,02 goles.
Con los pesos anteriores, un equipo con diez partidos de tarjetas era un 53 % él mismo; con el medido lo es un **21 %**: la media de la liga
pesa cuatro veces más de lo que se había supuesto. **Esto mide cuánto pesa la liga; no prueba que la memoria sirva para predecir**, y por eso
ningún modelo la lee.

**Su propio linaje.** `memory-v4` **no continúa ninguna versión anterior**: sus filas se construyen desde el primer día de su linaje
(**13 de octubre de 2026**), día a día, con los datos como están hoy, y el «estado anterior» de cada fila es la fila anterior de `memory-v4`.
Las filas de versiones anteriores se quedan como historia y nunca se leen para construir una nueva. El paso nocturno **no escribe nada hasta
que el linaje ha empezado** (una noche que lo empezara sola dejaría a cada entidad con un estado que olvida los días anteriores): primero se
reconstruye (abajo).

**Novedades tardías.** Una fila no se reescribe nunca. Un partido que se liquida, una estadística o un post-mortem que llegan *después* de
escrita la fila de su día se anotan en la fila del día en que se supieron (`delta.late[<día>]`) y pesan lo que pesa su día, no el día en que
se supieron. El paso nocturno construye la fila de ayer y mira los 3 días anteriores.

**La memoria de la IA** (`ai.memory_events`, el registro de hechos de donde salen los patrones) se sigue alimentando, ahora **derivada de
las filas canónicas** y con **las mismas claves de deduplicación** de siempre: los patrones no cuentan nada dos veces ni dejan de contar lo que
contaban.

## La página «Memoria» de la consola

`/admin/memory` (Admin → Memoria) reúne en **una sola página** lo que estaba en cuatro sitios (las pestañas y paneles de memoria de PrediGol
Intelligence, de la capa de decisión de IA, del analista de IA y de Evolución desaparecieron). Solo lectura: nada de aquí cambia un pick, una
probabilidad ni un modelo. Cinco secciones:

* **Entidades:** equipos, ligas, mercados, árbitros, entrenadores y jugadores, **una fila por serie**, con la versión de la memoria que la
  escribió, la **confianza**, la **muestra**, **en qué se apoya** (cuántos partidos o decisiones y post-mortems, los más recientes enlazados) y
  las cifras: por ejemplo «propios 5,40, del rival 4,10 por partido (liga 4,80)» en córners. Una serie escrita antes de `memory-v4` dice
  «ninguna» en la confianza (no se inventa un porcentaje). Se filtra por tipo, por aspecto y por texto.
* **Partidos:** los que miró, antes y después.
* **Post-mortems:** el de cada selección, una vez.
* **Notas de aprendizaje:** lo que apuntó el ciclo diario de la IA (cada nota nombra la versión de las reglas que la escribió).
* **Hallazgos de investigación:** lo que concluyó la investigación de modelos y cuándo.

La API (solo administrador): `GET /api/v1/admin/intelligence/memory` (filtros de tipo, aspecto y texto) y
`GET /api/v1/admin/intelligence/memory/{tipo}/{id}` (la historia de una entidad). Textos en español e inglés.

## La IA y el aprendizaje

* **Ciclo de aprendizaje de la IA** (`ai_learn`, 07:35 Bogotá = 12:35 UTC): estudia las selecciones, después los partidos y después escribe
  las narrativas; **cada paso confirma lo suyo y falla por separado** (un fallo deja el ciclo en estado «parcial» y el resto sigue).
  `pm-v1.1` y `pm-v2` **ya no se escriben**; con `FBI_AI_LEGACY_POSTMORTEMS=1` vuelven, y entonces **después** de los canónicos, para que los
  eventos de memoria pertenezcan a las filas canónicas y nada se recuerde dos veces.
* **Ciclo nocturno de Intelligence** (`intel_nightly`, 07:50 Bogotá = 12:50 UTC): su paso «postmortems» hace lo mismo; **el primero de los dos
  que corra escribe y el otro lo encuentra hecho** (la fila es única). Después construye la memoria de ayer.
* Las lecciones (`learning-v1.2`), el informe diario, los patrones, las pantallas de la IA y el resumen de un partido **leen el canónico**.
* **Narrativas** (`pmn-v1`, `ai.postmortem_narratives`): solo para las pérdidas que alguien querría ver explicadas —una selección que la IA
  aprobó o aprobó con cautela y perdió, una que rechazó y habría ganado, o una que nadie revisó y un usuario vio perder—. Primero las pérdidas
  de picks del día, con el modelo intermedio (como máximo 3 por corrida); el resto, con el económico (como máximo **12 por corrida** en total);
  los partidos más recientes primero y dentro de los últimos 7 días. **El presupuesto del día manda** (si se agota, no se escribe) y sin un
  modelo configurado no se lee nada. Una selección que solo juzgó la capa de decisión no tiene narrativa (no hay revisión de la IA que
  explicar). **No es un gasto nuevo:** `pm-v2` ya pedía exactamente estas narrativas (los mismos límites, el mismo mensaje, el mismo modelo
  para cada caso). Medido en producción en los últimos 14 días: las llamadas de los post-mortems de la IA (`purpose = postmortem`) son 22
  al día con el modelo económico (12 de selecciones, que es el tope, y unas 10 de partido, de `pm-v1.1`), **≈ 0,012 US$ al día** (308
  llamadas, 0,18 US$ en total: ≈ 0,4 US$ al mes), y una sola con el modelo intermedio. Con F8 el gasto baja un poco: el texto en prosa de
  cada partido ya no se pide (el partido se revisa por reglas; los 1.139 textos escritos siguen legibles). Sigue dentro del tope de
  siempre (6 US$ al día, 180 al mes) y el libro de uso de la IA lo muestra con su propósito.
* **La memoria no se inyecta en el paquete de la IA** (decisión 17, abajo): subiría el coste y habría que auditar la fuga primero.

## Qué ve cada quien

* **Un usuario:** nada nuevo. La tarjeta de análisis de un partido (`GET /api/v1/matches/{id}/analysis`) no alcanza ninguno de estos objetos
  (lo prueba el aislamiento, abajo).
* **El administrador:** la página Memoria y los mismos datos por la API del administrador.

## Reglas que se respetan

1. **Una fila, una vez y solo se añade.** Un índice único impide dos filas de la misma versión para la misma selección; ejecutar la carga dos
   veces no escribe nada la segunda. Una selección cuyos hechos no se pueden armar se informa y no impide escribir las demás. Estudiar nunca
   hace `commit` de la transacción de quien llama.
2. **Lo de antes del partido y lo de después no se mezclan.** Los precios y los paquetes son de antes del inicio; el resultado, los eventos y
   las estadísticas, de después.
3. **Aislamiento.** Lo aprendido (post-mortems de todas las generaciones, narrativas, memoria, eventos de memoria y notas de aprendizaje) **no
   es entrada de nada que se diga antes de un partido**. Lo vigila `tests/unit/test_postmortem_isolation.py` (46 comprobaciones, con listas
   cerradas y la razón de cada entrada): los 20 archivos que nombran estos objetos; los 2 archivos de antes del partido que pueden nombrarlos
   (`picks/resettlement.py` solo **cuenta** las filas hechas sobre un resultado corregido; `market/closing_value.py` lo nombra en un
   comentario); quién puede importar cada uno de los 17 módulos (44 importadores); las únicas migraciones que nombran las tablas; las
   funciones de los dos ciclos donde se traen las lecciones (nunca las que preparan un partido); que cada constructor escribe solo sus tablas y
   nunca un hecho de un partido; y que las pantallas y órdenes que miran no escriben. Ni un archivo de los paquetes del modelo, el pronóstico,
   los picks, los precios, las cuotas, la investigación o los avisos, ni del dossier, la capa de decisión, el paquete de la IA, los prompts, el
   revisor, el filtro de calidad o el día, nombra o importa nada de esto. Para un usuario, la tarjeta de un partido no alcanza nada (se lee a
   través de las constantes y funciones que usa), y todas las rutas de los tres routers que sirven las lecciones son de la consola del
   administrador. Se comprobó **rompiendo cada puerta a propósito** (un nombre en un comentario, una importación, una importación a nivel de
   módulo en el ciclo de la IA, una escritura sobre un hecho de un partido, una lectura en la re-liquidación, una llamada a la memoria desde la
   tarjeta): las seis se detectaron.
4. **Una derrota nunca cambia un modelo.** Va a la memoria; solo un patrón sobre muchos casos llega a una hipótesis.
5. **Lo derivado se reconstruye.** Nada de lo que dice el proveedor se toca; el post-mortem y la memoria salen de lo guardado.
6. **Si un resultado se corrige después**, el post-mortem hecho con el resultado de entonces **no se reescribe** (es solo-añadir): la
   re-liquidación lo **cuenta** («construido sobre el resultado viejo», `picks.resettlements`) y reconstruirlo exige una versión nueva. Hasta
   hoy `core.fixture_result_revisions` tiene **0 correcciones registradas**, así que no hay nada que reconstruir.

## Cómo corre

* **Worker:** no hay trabajos nuevos ni horarios nuevos: el post-mortem va dentro de `ai_learn` y de `intel_nightly`, que ya corrían, y la
  memoria dentro de `intel_nightly`. Se puede frenar la parte antigua o la nueva sin desplegar: `FBI_AI_LEGACY_POSTMORTEMS` (arriba) devuelve
  los dos post-mortems antiguos; la memoria no escribe nada mientras no exista el linaje.
* **A mano, desde `backend/`** (0 peticiones al proveedor, 0 llamadas a un modelo; `build` y `rebuild` son un ensayo en seco hasta
  `--apply`):

```bash
python -m scripts.postmortems status                   # lo escrito por versión, fuente y veredicto; los precios; lo que falta
python -m scripts.postmortems coverage --days 15       # selecciones del universo y estudiadas, día a día (Bogotá)
python -m scripts.postmortems closes --days 15         # los dos cierres, medidos sobre las mismas selecciones
python -m scripts.postmortems build                    # ensayo en seco: lo que escribiría una pasada del worker (7 días)
python -m scripts.postmortems build --days 15 --apply  # la carga: 400 selecciones por commit; después los partidos
python -m scripts.memory status                        # filas por versión, el linaje, la confianza por tipo de memoria
python -m scripts.memory coverage --days 15            # día a día: partidos que reportan cada cifra y filas escritas
python -m scripts.memory rebuild                       # ensayo en seco del linaje (13 de octubre a ayer): no escribe nada
python -m scripts.memory rebuild --apply               # escribirlo, un commit por día; se puede cortar (--max-seconds) y repetir
python -m scripts.memory audit --sample 100 --seed 1   # recalcula una muestra desde cero y compara con lo guardado
python -m scripts.memory priors --days 365             # cuántos partidos vale la media de una liga (solo lectura)
```

**Cómo leerlos.** `status` de post-mortems cuenta además **cuántas veces la misma selección llega con un precio distinto** según quién la
cotizó: es lo que dice cuánto importa el orden ítem → decisión → revisión. `closes` termina con una frase que compara las dos etiquetas de
precio (cuántas veces coinciden y, cuando no, cuál dice «peor»). `rebuild` en seco dice cuánto crecería la tabla. `audit` de la memoria
**termina con error** si lo guardado no es lo que dicen los datos; una diferencia es un día cuyo dato cambió después de anotarlo (una
estadística que llegó más tarde de los 3 días que mira la noche): la memoria nunca reescribe una fila, así que la diferencia se queda y se
muestra. `priors` imprime la tabla de los pesos medidos junto a los que usa la memoria.

## Tamaño y coste (estimación; se mide al terminar la carga)

Filas actuales en producción (con índices): `ai.pick_postmortems` 2.004 bytes por fila, `ai.postmortems` 1.668, `intel.postmortems` 2.206
(104 filas), `intel.entity_memory` 711 (5.624 filas), `ai.memory_events` 602 (13.197 filas).

| Qué | Cuánto al día | Peso | Al día |
|---|---|---|---|
| Post-mortems de selección (`pm-v6`) | ≈ 180–200 (las 178 diarias de `pm-v2` más las 20 mejores INVESTIGACIONES) | ≈ 2,2 KB | ≈ 0,4–0,45 MB |
| Post-mortems de partido | ≈ 80 | ≈ 1,7 KB | ≈ 0,14 MB |
| Narrativas | ≤ 12 | ≈ 1 KB | ≈ 0,01 MB |
| Memoria `memory-v4` | ≈ 1.000–1.500 filas (≈ 500 de equipo, ≈ 100 de liga y el resto de decisiones, árbitros, entrenadores y jugadores) | ≈ 0,6–0,9 KB | ≈ 0,7–1,2 MB |
| **Total** | | | **≈ 1,3–1,9 MB al día (unos 550 MB al año)** |

Es menos del 0,1 % del crecimiento diario actual del disco (+3.535 MB al día); el aviso de disco que ya existía no cambia. La carga inicial
(15 días de post-mortems y la memoria del 13 de octubre a ayer) se estima en pocos minutos de cómputo y alrededor de 20–30 MB. Coste en
proveedor: **0 peticiones**. Coste en IA: **ningún gasto nuevo** (las narrativas opcionales son las que `pm-v2` ya pedía: ≈ 0,4 US$ al
mes entre todas las de los post-mortems, y a la baja).


## Resultado de la prueba general

Puerta de calidad completa sobre el árbol de F8 (23 oct 2026, 15:28–16:02 UTC; el backend corre contra un PostgreSQL 16 real):

| Puerta | Resultado | Tras F7 |
|---|---|---|
| `ruff check .` | sin hallazgos | sin hallazgos |
| `mypy` (estricto) | **426 archivos, sin errores** | 421 |
| `mypy .` (todo: también pruebas, scripts y migraciones) | **983 archivos, sin errores** | 961 |
| Batería del backend (`pytest`) | **4.464 pasan, 4 omitidas, 0 fallan** (8 min) | 4.277 pasan, 4 omitidas |
| Web: `bun run lint` | 0 errores (26 avisos que ya estaban; ninguno en un archivo de F8) | 0 errores |
| Web: `bun run typecheck` | sin errores | sin errores |
| Web: `bun test src` | **556 pasan, 0 fallan** (58 archivos) | 537 (56) |
| Web: construcción de producción (`NITRO_PRESET=node-server VITE_DATA_MODE=live`) | correcta | correcta |

Son **187 pruebas más** en el backend y **19 más** en la web que tras F7. Las 4 omitidas son las mismas de entonces (pruebas de
independencia previa al partido que se omiten en los módulos sin código fuente que analizar).

**Lo que encontró la puerta** (la primera pasada completa de la batería sobre el árbol de F8 no tuvo ningún fallo; lo que sigue lo
encontraron la comprobación de tipos de todo el árbol y la lectura de lo que hace una vuelta atrás):

* **El tipado de todo el árbol.** `mypy .` no se había corrido entero desde F7 (las pasadas de F8 eran archivo por archivo, donde mypy
  dice cosas distintas) y halló 31 errores en archivos de F8: comentarios que silenciaban un error que ya no existía (nueve, en las pruebas
  del post-mortem, las narrativas, la memoria y sus órdenes), dos variables que guardaban primero un número y luego una medición
  (`scripts.memory priors` y su prueba) y tres nombres que se tomaban de un módulo que los importa y no del que los define. Sin ningún
  cambio de comportamiento; arreglado antes de seguir.
* **Un hueco en la vuelta atrás de la migración** que ninguna prueba veía: se deshacía bien en esquema, pero dejaba las filas de
  `memory-v4`, y el código de antes (`memory-v3`) toma «la última fila de cualquier versión» como el estado que continúa. Se encontró
  leyendo el código al que vuelve una vuelta atrás. Ahora la migración retira esas filas (se reconstruyen con un comando) y la prueba lo
  comprueba; la prueba se verificó quitando la corrección: falla. (La migración aún no estaba aplicada en ningún sitio.)
* **«Entrenador por ID» no tenía una prueba propia:** el código ya lo hacía (la memoria lee el `coach_id` de la alineación) y nadie lo
  comprobaba. Ahora la hay (y falla si la clave pasa a ser el nombre).

**Que las puertas de aislamiento muerden.** `test_postmortem_isolation.py` (46 comprobaciones) se verificó rompiendo cada puerta a
propósito (un nombre en un comentario, una importación, una importación a nivel de módulo en el ciclo de la IA, una escritura sobre un
hecho de un partido, una lectura en la re-liquidación, una llamada a la memoria desde la tarjeta del partido): **6 de 6 detectadas**.

**La batería se repitió entera sobre el árbol final** (después de la corrección de la migración, de la prueba del entrenador y de la
prueba que amarra los documentos al código, que suma 4): ver la primera fila de la tabla.

## Resultado en producción

**Pendiente: todavía no se ha desplegado.** Se anota aquí al terminar F8.10: la copia verificada y la prueba de restauración, el
despliegue de la 0091, la carga de 15 días de post-mortems, la reconstrucción de la memoria desde el 13 de octubre, las auditorías, los
tamaños reales y las comprobaciones de la API en producción.

## Verificación de los criterios del plan

| Criterio de «hecho» | Resultado | Prueba |
|---|---|---|
| Un solo post-mortem (el plan: `pm-v3` canónico y `pm-v1` / `pm-v2` congelados, de solo lectura) | sí: **`pm-v6`**, para todo lo que PrediGol miró, venga de donde venga; los dos primeros solo se escriben con el interruptor y sus filas siguen legibles | `test_the_learning_cycle_studies_each_selection_and_each_match_once_and_leaves_the_frozen_writers_alone`, `test_the_one_post_mortem_judges_what_only_the_ai_looked_at_as_the_first_post_mortem_by_selection_did`, `test_a_selection_three_parts_priced_is_studied_once_with_the_price_a_person_saw_and_the_other_two_beside_it`, `test_a_selection_only_the_ai_looked_at_and_one_only_the_decision_layer_judged_are_studied_too` |
| Una doble versión de post-mortem no duplica conteos | sí: una selección tiene una fila por versión (índice único), la vista da la más reciente, los eventos de memoria no se duplican con los dos escritores, y un partido de tanda no cuenta los penales de la tanda | `test_the_two_writers_leave_one_memory_event_per_selection_not_two`, `test_the_switch_brings_the_two_first_post_mortems_back_after_the_one_and_nothing_is_remembered_twice`, `test_a_run_that_finds_everything_written_writes_nothing_and_the_unique_index_holds_the_line`, `test_the_view_gives_the_newest_post_mortem_of_each_selection_and_the_decision_stays_on_the_row`, `test_the_current_post_mortem_judges_a_shootout_match_without_its_kicks_and_the_readers_take_the_newest` |
| El delta tardío está presente | sí: una liquidación, una estadística o un post-mortem que llegan después de escrita la fila de su día se anotan y pesan lo de su día; reconstruir de cero da el mismo estado que acumular noche a noche | `test_a_decision_settled_after_its_day_was_written_is_booked_the_next_day`, `test_a_statistic_that_arrives_late_reaches_the_referee`, `test_a_night_the_worker_missed_is_caught_up_as_late_news`, `test_the_cumulative_state_equals_a_recomputation_whenever_the_news_arrives`, `test_a_statistic_that_arrives_after_the_night_is_booked_with_the_weight_of_its_own_day` |
| Una única fuente de CLV en todo el sistema | sí en el código: **una definición** (`clv-v1`) y **un cierre con nombre**; el movimiento de precio se guarda aparte y no se llama CLV. Qué cierre manda lo decides tú (decisión 16); hoy es el consenso, el que ya usaba el resto del sistema | `test_the_same_price_and_close_give_the_same_clv_in_every_place`, `test_the_close_is_the_last_shin_consensus_before_kickoff_and_nothing_else`, `test_the_close_of_a_selection_is_the_one_the_outcome_of_a_decision_uses`, `test_a_post_mortem_row_reads_with_its_clv_and_its_price_move_apart`, `test_a_margin_is_not_a_market_move`, `test_the_legacy_clv_key_is_not_read` |
| Memoria con `confidence` (por muestra y recencia) y `evidence_ref` | sí; una fila de antes dice «ninguna» y se sigue leyendo | `test_the_confidence_is_nothing_without_evidence_one_half_at_k_and_never_certainty`, `test_a_piece_of_evidence_loses_half_its_weight_after_the_half_life`, `test_every_row_the_memory_writes_says_how_far_to_trust_it`, `test_the_decision_rows_name_their_decisions_and_the_post_mortem_that_judged_each`, `test_a_row_rests_on_decisions_or_on_matches_never_on_both`, `test_the_row_of_a_version_before_memory_v4_has_no_confidence_and_is_still_read` |
| Aspectos nuevos: córners, tarjetas y goles esperados del equipo, con contracción a la media de la liga | sí, con los pesos **medidos** (15 / 38 / 10) y la confianza igual a la parte propia de la cifra | `test_a_team_with_two_matches_is_close_to_its_league_and_one_with_many_is_itself`, `test_a_team_that_played_in_two_leagues_is_shrunk_to_the_mean_of_both_weighted_by_its_matches`, `test_the_confidence_of_a_figure_is_the_share_of_it_that_is_the_team_itself_and_the_rest_is_its_league`, `test_the_weights_are_the_ones_measured_on_the_stored_matches_not_the_first_guess`, `test_a_day_of_matches_writes_the_figures_of_its_teams_and_its_league_each_with_its_confidence_and_its_matches` |
| Árbitro por ID y entrenador por ID | sí: dos escrituras de un mismo nombre son una persona; quien el proveedor nombra sin persona se guarda como `p<id del proveedor>`; una alineación sin entrenador no es un entrenador | `test_one_person_is_one_entity_whatever_the_spellings`, `test_a_merge_rebooks_the_days_inside_the_late_window_to_the_right_person`, `test_a_coach_is_one_entity_by_his_id_whatever_his_name_is_spelled_and_one_the_provider_names_without_a_person_keeps_the_providers_id` |
| La memoria nueva empieza el 13 de octubre | el constructor está probado (día a día, se puede cortar y repetir, idempotente, y el paso nocturno **espera** a que exista el linaje); **en producción: pendiente (F8.10)** | `test_the_lineage_is_built_day_by_day_from_its_first_day_and_a_second_run_finds_it_built`, `test_a_rebuild_with_a_budget_stops_between_days_and_the_next_run_goes_on`, `test_a_rebuild_commits_each_day_as_it_goes`, `test_the_nightly_step_waits_for_the_lineage_and_continues_it`, `test_the_first_day_of_the_lineage_needs_no_rows_before_it` |
| `ai_learn` deja de producir `pm-v1` y `pm-v2`; `intel_nightly` ampliado | sí: ambos ciclos estudian lo mismo, el primero que corre escribe y el otro lo encuentra hecho; un fallo del post-mortem no frena el resto del aprendizaje | `test_the_learning_cycle_studies_each_selection_and_each_match_once_and_leaves_the_frozen_writers_alone`, `test_a_post_mortem_that_fails_does_not_stop_what_the_rest_of_the_cycle_learns`, `test_the_nightly_step_studies_what_the_cycle_left_and_finds_the_rest_done` |
| Administrador: la memoria en un solo lugar (hoy está en 4) | sí: la página `/admin/memory`; las pestañas y paneles de los otros cuatro sitios desaparecieron | `MemoryEntities.test.tsx` (6), `memoryText.test.ts` (13) y la prueba de extremo a extremo «Memory: the entities with their version, confidence and evidence, and every other kind of memory in one page» |
| Una migración, y se deshace | sí: la 0091 es aditiva, deja intactas las filas de antes y, al deshacerla, retira lo que escribió `pm-v6` y `memory-v4` | `test_0091_extends_the_postmortems_keeps_the_old_row_and_comes_back_out` |
| Coste 0 | sí: ningún gasto nuevo (las narrativas son las que `pm-v2` ya pedía, con los mismos límites) y, sin un modelo configurado, no se lee ni se escribe nada | `test_without_a_model_nothing_is_read_and_nothing_is_written`, `test_a_run_writes_at_most_what_its_limits_allow_and_the_picks_of_the_day_come_first`, `test_a_model_that_fails_leaves_the_post_mortem_whole_and_the_call_on_the_ledger` |
| «La IA del día siguiente lee la memoria en vez de recalcular» | **no, a propósito** (decisión 17, abajo): la memoria no entra en el paquete de la IA | `test_postmortem_isolation.py`: nada de antes del partido nombra ni importa la memoria |
| Lo aprendido no es entrada de nada que se diga antes de otro partido (F14) | sí: 46 comprobaciones, 6 de 6 puertas rotas a propósito detectadas. La auditoría nocturna de fuga (`leak-audit-v6`) no cambia: ningún paquete lleva estos objetos | `tests/unit/test_postmortem_isolation.py` |

## Lo que se decidió distinto del plan (y los límites que conviene conocer)

* **Los nombres.** `pm-v6` y `memory-v4`, no `pm-v3` y «memoria v2»: esos números ya los habían usado F0 y F3.
* **Una fila por selección, no por decisión.** El plan hablaba de pasar a un post-mortem por decisión; medido, la capa de decisión juzga
  2–20 selecciones al día y la IA ≈ 190, y los picks que ven los usuarios estaban solo en `pm-v2`. Por eso la fila es la **selección** y la
  decisión es opcional. Las 104 filas de `pm-v3` a `pm-v5` se quedan como estaban, por decisión.
* **La memoria no se inyecta en el paquete de la IA** (el plan: «la IA del día siguiente lee memoria en vez de recalcular»). Motivos: (1)
  subiría los tokens de cada paquete, de cada partido, contra un tope de 180 US$ al mes (hoy ≈ 6.400 por paquete; F6 ya los subió ×1,49);
  (2) lo aprendido de resultados es justo lo que no debe entrar en un paquete sin una regla de fuga que lo audite (`memory_known`), y esa
  regla no existe porque ningún paquete lo lleva; (3) las cifras de la memoria miden cuánto pesa una liga, **no que predigan algo**. Hoy la
  leen la consola, el informe diario, las notas de aprendizaje y la búsqueda de patrones. Decisión 17.
* **El post-mortem sale de reglas y la narrativa es aparte.** Antes eran una sola fila (`ai.pick_postmortems.narrative`) y una narrativa que
  no se escribía dejaba el post-mortem a medias. Ahora nada que lea un post-mortem espera, depende ni paga a un modelo.
* **El texto en prosa de cada partido ya no se pide a un modelo** (`pm-v1.1` lo hacía, ≈ 10 llamadas al día): el partido se revisa por reglas.
  Los 1.139 textos escritos siguen legibles. Ver «Lo que decides tú».
* **Los pesos de la contracción se midieron en vez de suponerse:** 15 / 38 / 10 y no los 6 / 9 / 7 del borrador (tabla arriba). Y la
  confianza de una cifra de equipo es exactamente la parte de la cifra que es suya: lo que enseña la consola es lo que hay.
* **Su propio linaje.** `memory-v4` empieza el 13 de octubre y no continúa ninguna versión anterior; las filas de antes son historia. No se
  amplía hacia atrás: tener 12 meses obligaría a reconstruir bajo una **versión nueva** de la memoria (decisión 17).
* **Los post-mortems se cargan de 15 días atrás (9–22 de octubre).** Antes de la capa de IA no hay paquetes, revisiones ni picks guardados y
  no se pueden hacer las mismas preguntas. Los de `pm-v1.1` (1.139 partidos) y `pm-v2` (2.487 selecciones) no se reescriben.
* **Un resultado corregido después no reescribe un post-mortem** (la tabla es solo-añadir): la re-liquidación lo cuenta y rehacerlo exige una
  versión nueva. `core.fixture_result_revisions` tiene hoy **0 correcciones registradas**, así que no hay nada que rehacer.
* **Una novedad llega a la memoria hasta 3 días después.** Una estadística que llega más tarde no se anota en la fila de su día (la
  memoria nunca reescribe); `audit` la muestra.
* **La memoria de un jugador sigue siendo su disponibilidad** (bajas informadas y si jugó igual). El plan no pedía rendimiento por jugador.
* **El cierre del CLV no se cambió en silencio:** cada post-mortem guarda a cuántos minutos del inicio se capturó su cierre y se mide el
  otro candidato sobre las mismas selecciones (decisión 16).

## Cómo estrenarlo en producción (y qué te aviso antes de cada paso)

1. Copia verificada y **prueba de restauración** antes de migrar. La 0091 solo altera dos tablas pequeñas (`intel.postmortems`, 104 filas, e
   `intel.entity_memory`, 5.624) y crea cuatro objetos nuevos; no tiene claves foráneas hacia `core.fixtures` ni toca nada grande, y si no
   consigue un bloqueo en 10 segundos falla entera sin dejar nada a medias. Aun así se hace fuera de las horas del trabajo de partidos
   (01:03, 07:03, 13:03 y 19:03 UTC, con su transacción de unos 27 minutos) y de los ciclos de las 12:35–13:00 UTC.
2. Vigilancia de bloqueos (`lockwatch`) durante el despliegue y las cargas, con su registro.
3. `predigolctl deploy`: respaldo propio, migración, permisos, reinicio y salud. Con las tablas nuevas vacías todo se comporta como antes, salvo
   que el ciclo de aprendizaje de la IA y el nocturno pasan a escribir `pm-v6` y dejan de escribir `pm-v1.1` y `pm-v2`.
4. **Carga de post-mortems** de los últimos 15 días: `python -m scripts.postmortems build --days 15 --apply` (400 selecciones por commit,
   después los partidos; 0 peticiones, 0 llamadas a un modelo). Antes, un ensayo en seco para ver cuánto escribiría y cuánto tarda.
   Después `status`, `coverage --days 15` y `closes --days 15`.
5. **Reconstrucción de la memoria**: `python -m scripts.memory rebuild` (ensayo en seco: dice cuánto crece la tabla) y después
   `rebuild --apply` (del 13 de octubre a ayer, un commit por día; si se corta se repite). Después `audit --sample 100 --seed 1` y
   `status`. Se hace **antes de la noche siguiente** (07:50 Bogotá) para que el paso nocturno encuentre el linaje y lo continúe.
6. Se miden los tamaños reales de las tablas y el disco.
7. Tú abres la página «Memoria» de la consola. No hace falta nada más para que sea correcto.
8. Se vigila (abajo) y se anota aquí el «Resultado en producción».

## Cómo deshacerlo

* **Volver a escribir también los dos post-mortems antiguos:** `FBI_AI_LEGACY_POSTMORTEMS=1` en `/etc/predigol/app.env` y reiniciar el
  worker (solo para volver atrás; los escribe **después** del canónico y nada se recuerda dos veces).
* **Pausar solo esta escritura sin desplegar: no hay un interruptor.** Es derivada, pequeña (≈ 1,3–1,9 MB al día), está aislada de todo lo
  que se dice antes de un partido y un fallo suyo no frena nada (cada paso del ciclo falla por separado). Las narrativas no se leen ni se
  escriben si no hay un modelo configurado.
* **Quitarlo todo:** `predigolctl rollback` a la versión anterior del código y `alembic downgrade 0090`, que borra las vistas, las tablas
  nuevas, las columnas nuevas, las filas de `pm-v6` y las de `memory-v4`. Lo que se pierde es lo derivado: se vuelve a construir con
  `scripts.postmortems build` y `scripts.memory rebuild`, pero no la historia de versiones de cada selección (cuándo cambió y qué decía
  antes), y **las narrativas son texto pagado: se exportan antes** si alguien las ha citado. Lo de antes —las 104 filas de `pm-v3` a
  `pm-v5`, los 1.139 y 2.487 post-mortems de la IA, las 5.624 filas de la memoria vieja y los 13.197 eventos de memoria— no se toca. Los
  eventos de memoria que escribió el canónico se quedan (son hechos con las claves de siempre: si vuelven los escritores antiguos, no se
  duplican).

## Lo que decides tú

* **16. ¿Contra qué cierre se mide el valor de un precio (el CLV)?** Hoy: el último consenso del mercado sin margen antes del inicio
  (mediana ≈ 175 minutos antes), que es el que ya usaba el resto del sistema. La alternativa es el último precio del propio proveedor en la
  misma casa (mediana ≈ 85 minutos antes, en el 72 % de los partidos y con el margen de la casa dentro: sería un movimiento de precio, no un
  CLV). `python -m scripts.postmortems closes --days 15` los mide sobre las mismas selecciones, y tras cargar los 15 días anoto aquí el
  resultado. Mi sugerencia: **mantener el consenso** (cubre todo y es comparable con la historia) y mirar el movimiento aparte, que ya se
  guarda. Si cambiara, sería una versión nueva del post-mortem (`pm-v7`), nunca un cambio silencioso.
* **17. ¿Entra la memoria en el paquete de la IA, y hasta dónde llega su historia?** (a) **No, por ahora** (lo que queda al desplegar): se ve
  en la consola, la usan el informe diario, las notas y los patrones, y no cuesta nada más. (b) **Sí**: un resumen corto por equipo, árbitro
  y entrenador con su confianza; sube los tokens de cada paquete y exige antes la regla `memory_known` en la auditoría de fuga y unas
  semanas de filas `memory-v4`. En cuanto a la historia, la memoria nueva empieza el 13 de octubre (lo que decía el plan); si prefieres
  12 meses, se reconstruye bajo una **versión nueva** (`memory-v5`): no pierde nada y cuesta poco cómputo y ≈ 30 MB. Mi sugerencia: (a), y
  decidir con tres semanas de memoria a la vista.
* **Los pesos de la contracción (15 / 38 / 10)** los apliqué yo, medidos sobre los partidos guardados; no hace falta que decidas nada, pero
  cambiarlos sería una versión nueva de la memoria. Es informativo.
* **¿Quieres de vuelta el texto en prosa por partido?** (≈ 10 llamadas al día, ≈ 0,006 US$ al día.) Hoy no se pide: el partido se revisa
  por reglas. Si lo echas en falta, es una narrativa más con el mismo tope.
* Nada más de F8 pide una decisión tuya. (Las dos propuestas que F3 dejó prometidas para esta fase —reparar la entrada de las alineaciones
  cruzadas por el proveedor y subir `fixtures_sync` por bloques— son las decisiones 9 y 11 del estado del plan; las escribo al terminar
  F8.10.)

## Lo que queda vigilado tras desplegar

1. `python -m scripts.postmortems coverage --days 15`: que cada día tenga estudiadas casi todas las selecciones de su universo (menos las
   de las últimas tres horas, que esperan), y `status`: las filas por versión, fuente y veredicto, y cuántas veces importa el orden de
   precios.
2. `python -m scripts.memory status` y `audit`: el linaje empieza el 13 de octubre y llega a ayer; el paso nocturno escribe cada mañana la
   fila del día; y `audit` termina bien o muestra solo series cuyo dato cambió después de anotarlo.
3. Las corridas de `ai_learn` e `intel_nightly` en el libro: ni «parcial» ni errores, y el gasto de IA de los post-mortems en torno a
   0,01 US$ al día.
4. El tamaño real de las tablas tras la carga y tras una semana (la estimación de arriba, ≈ 1,3–1,9 MB al día, se confirma o se corrige).
5. La auditoría nocturna de fuga: sin cambios (`leak-audit-v6`, 0 violaciones salvo el patrón conocido de `forecast_known`) y el aviso de
   disco del servidor, que F8 no debe mover.
