# Postpartido (Match Knowledge): lo que un partido terminado resultó ser, en nueve capas y aparte de lo que se dijo antes (Plan Maestro, fase F7)

**Qué es.** Cuando un partido termina, lo que PrediGol sabe de él está repartido en una docena de tablas que escriben trabajos distintos en
momentos distintos: el resultado y sus correcciones, las estadísticas de los equipos, la lista de eventos, las hojas de alineación y las
cifras de cada jugador, las cuotas desde la apertura hasta el cierre, las decisiones y los picks con su desenlace y el post-mortem. Cada
pantalla o proceso que quería saber «qué pasó en este partido» lo armaba otra vez con sus propias reglas, y la lista de eventos del
proveedor trae cosas que no son lo que parecen: una tanda de penales llega como goles en el minuto 120, un autogol viene archivado bajo el
equipo que lo recibe y una doble amarilla son dos líneas. F7 deja **un objeto por partido terminado**, armado **por reglas** (sin IA, sin
coste y sin pedirle nada al proveedor), en **nueve capas**; cada capa dice de qué está hecha, cuándo se supo y hasta dónde se puede confiar
en ella.

**F7 no cambia ningún modelo, pronóstico, decisión, pick ni liquidación, ni el modo SHADOW; no pide nada al proveedor (0 peticiones) ni
gasta IA (0 US$); y no muestra nada a ningún usuario hasta que tú lo decidas.** Conocer cómo terminó un partido tampoco puede colarse en
lo que se dice antes de otro: ningún lector de antes del partido puede leerlo, y una prueba lo vigila.

> **Después de F8 (23 oct 2026):** lo que este documento anuncia «para F8» quedó así. El post-mortem es **uno solo** (`pm-v6`) y la capa 9
> de este objeto lee el más reciente de cada selección; el CLV tiene una sola definición y **un cierre de referencia con nombre** (el
> último consenso sin margen antes del inicio, `fbi.market.closing_reference`), y los dos cierres se miden sobre las mismas selecciones con
> `python -m scripts.postmortems closes` para que lo decidas con números. La memoria (`memory-v4`) y el post-mortem **no leen** este objeto:
> se arman de los datos del partido con su propia regla «a fecha», y ninguno entra en un paquete de la IA (por eso tampoco hay una regla
> nueva en la auditoría de fuga: una prueba de aislamiento, `tests/unit/test_postmortem_isolation.py`, es la extensión de la de aquí).
> Ver `docs/owner/POSTMORTEM_MEMORIA_F8.md`.

Lo que **no** es: no es una señal (no alimenta ningún modelo); no inventa (una capa que no se puede armar dice que falta, y por qué); no es
un registro de lo que PrediGol dijo antes (eso son `models.match_forecasts`, `intel.decisions` y `picks.*`): es lo que el partido resultó
ser.

## Qué escribe (y qué no)

Dos migraciones, solo aditivas:

| Migración | Objeto | Para qué |
|---|---|---|
| **0089** | `core.fixture_event_kinds` | Qué es cada línea de la lista de eventos del proveedor (gol, autogol, penal, lanzamiento de la tanda, segunda amarilla, decisión del VAR…), en qué periodo del partido cae y a qué equipo cuenta. Es una tabla **derivada**: se reescribe sola cuando cambia la lista del partido o las reglas; perderla pierde una lectura, no un dato del proveedor. Sin claves foráneas. |
| **0090** | `intel.match_knowledge` | Una fila por construcción de un partido terminado: las nueve capas (en JSON), la calidad, la completitud, cuándo se supo cada cosa y dos huellas (una de lo que se leyó y otra de lo que dice). **Solo se añade:** un disparador (`match_knowledge_append_only`) rechaza cambiar o borrar una fila. Si el proveedor corrige un resultado, el partido recibe una fila nueva que nombra la que reemplaza; la más reciente es lo que el partido es hoy y las anteriores, lo que fue. Sin claves foráneas. |
| | `intel.match_knowledge_latest` | Vista: la fila más reciente de cada partido y versión. |

Nada de lo que ya existe cambia: ni una columna, ni un disparador, ni un bloqueo sobre `core.fixture_events` o `core.fixtures`. Las capas de
picks y de post-mortem **copian** lo que PrediGol ya decidió y cómo le fue; no deciden nada. Permisos (`deploy/vps/db/grants.sql`, que
`predigolctl deploy` aplica): la API solo lee las dos tablas y la vista; el worker inserta en `intel.match_knowledge` (cambiarla o borrarla
se lo rechaza el disparador también a él) y escribe y borra las líneas de `core.fixture_event_kinds`.

Reglas de escritura (`mk-v1`, código en `fbi.knowledge`):

1. **Cuándo:** un partido se arma cuando está terminado **y asentado**: 26 horas después del inicio, cuando el proveedor ya hizo su última
   relectura del resultado. Antes, la API dice «todavía no está asentado» en vez de dejar un hueco.
2. **Qué partidos:** los de las competiciones que PrediGol sigue. En producción, los 38.121 partidos terminados de los últimos 400 días lo
   son: ninguno queda fuera.
3. **Cuándo se vuelve a armar:** solo cuando cambia lo que dicen los hechos (una huella del **contenido**, no de los momentos en que se
   bajó) o cuando cambian las reglas. Que el proveedor relea un partido y encuentre lo mismo no añade ninguna fila.
4. **Qué pasa si algo falla:** un partido que falla se anota y no frena a los demás; el trabajo entero no frena nada más de PrediGol.
5. **Nada se inventa:** una capa que no se puede armar queda `missing` con un código que dice por qué; una armada con menos de lo necesario
   queda `partial` y dice qué falta; la de contexto externo queda `off`.

## Las nueve capas, y cuántos partidos las tienen

Medido sobre **todos** los partidos terminados y asentados de los últimos 400 días: **38.121** (producción, solo lectura, 23 oct 2026):

| Capa | Qué cuenta | Partidos que la tienen |
|---|---|---|
| **1 · Resultado** | marcador a los 90 minutos, al descanso, tras el tiempo extra y en la tanda; quién ganó; si fue en campo neutral; si el proveedor lo corrigió después; en una eliminatoria, el global y cómo se decidió (solo en el partido que la cierra) | 38.118 (los 3 restantes no tienen fila de resultado) |
| **2 · Estadísticas de los equipos** | tiros, a puerta, córners, faltas, fueras de juego, tarjetas, posesión, pases, goles esperados (xG)…; **una cifra que el proveedor no dio queda vacía, nunca en cero** | 24.172 (63,4 %) |
| **3 · Eventos** | cada gol, tarjeta y decisión del VAR, en orden y con su periodo; los goles por periodo; y si la lista cuadra con el resultado | 34.559 completa y 176 con reservas (90,7 % y 0,5 %); sin eventos, 3.386 (8,9 %) |
| **4 · Jugadores** | cuántos figuran, cuántos jugaron, titulares y suplentes que entraron; los tres mejor valorados de cada equipo; el capitán; cuántos goles no traen jugador | 23.300 completa y 26 con reservas (61,1 % y 0,1 %) |
| **5 · Táctica e historia del marcador** | formaciones y cambios (minuto y ventaja en ese momento); quién fue por delante y cuántos minutos, cuántas veces cambió la ventaja, primer y último gol, primera expulsión | 23.696 completa y 13.734 sin formación (62,2 % y 36,0 %); 691 sin nada (1,8 %) |
| **6 · Mercado** | la probabilidad de cada desenlace **sin el margen de las casas, de la apertura al cierre** (resultado, más/menos, ambos marcan y hándicap); y, solo para ti, los últimos precios del proveedor | 2.024 (5,3 %): el reloj de precios empezó el 25-sep (septiembre 2 %, octubre 88 %) |
| **7 · Contexto externo** | noticias de después del partido, con IA | **apagada** (decisión tuya, abajo) |
| **8 · Picks y decisiones** | lo que PrediGol decidió de ese partido y cómo le fue (estado, desenlace, ganancia, CLV). **Solo administrador** | 1.732 (4,5 %): los partidos con decisión o pick, casi todos de octubre (77 % de los del mes) |
| **9 · Post-mortem** | los post-mortems de esas decisiones. **Solo administrador** | 37 (0,1 %): los post-mortems en producción son de la versión `pm-v3`, desde el 14-oct |

**Completo, parcial, mínimo.** Un partido es **completo** si el resultado y las tres capas de hechos (estadísticas, eventos y jugadores) están
bien armados; **mínimo** si no hay resultado o faltan las tres; **parcial** en medio. El mercado, los picks y el post-mortem no cuentan para
ser completo (un partido de hace un año puede ser completo sin haber tenido nunca un precio guardado). Resultado: **23.174 completos
(60,8 %), 11.559 parciales (30,3 %) y 3.388 mínimos (8,9 %).**

Por mes de inicio (porcentaje de partidos; «estadísticas», «eventos» y «jugadores» son los que tienen esa capa armada, completa o con
reservas):

| Mes | Partidos | Completos | Parciales | Mínimos | Estadísticas | Eventos | Jugadores |
|---|---|---|---|---|---|---|---|
| 2025-09 | 1.725 | 60 | 38 | 2 | 61 | 98 | 60 |
| 2025-10 | 2.719 | 74 | 25 | 0 | 75 | 100 | 74 |
| 2025-11 | 2.714 | 79 | 20 | 0 | 80 | 100 | 79 |
| 2025-12 | 1.800 | 88 | 12 | 0 | 89 | 100 | 88 |
| 2026-01 | 3.293 | 46 | 35 | 19 | 48 | 81 | 46 |
| 2026-02 | 3.706 | 58 | 23 | 20 | 59 | 80 | 58 |
| 2026-03 | 2.852 | 75 | 20 | 6 | 77 | 94 | 75 |
| 2026-04 | 2.876 | 87 | 13 | 0 | 88 | 100 | 87 |
| 2026-05 | 2.493 | 75 | 25 | 0 | 79 | 100 | 76 |
| 2026-06 | 886 | 26 | 65 | 9 | 31 | 91 | 27 |
| 2026-07 | 4.134 | 14 | 61 | 25 | 16 | 75 | 15 |
| 2026-08 | 3.563 | 55 | 39 | 7 | 61 | 93 | 56 |
| 2026-09 | 3.131 | 63 | 25 | 12 | 69 | 88 | 64 |
| 2026-10 | 2.229 | 65 | 29 | 6 | 70 | 94 | 66 |

Los meses bajos no son un fallo de PrediGol: son los que traen muchos amistosos de clubes y rondas previas continentales, donde el proveedor
casi no da estadísticas (en julio, 3.401 de los 4.134 partidos son de tipo continental —3.131 de ellos, amistosos de clubes— y solo el 7 %
trae estadísticas; en las ligas locales las trae el 90–98 %).

## Por qué faltan datos en algunos partidos

Faltan porque el proveedor no los da, no porque PrediGol los pierda; y una parte (la que el proveedor dice cubrir) se podría volver a pedir. Se
cruzó cada partido con las banderas de cobertura que el propio proveedor declara para su competición y temporada (producción, solo lectura,
23 oct 2026):

| Capa | Partidos sin ella | El proveedor dice que **no** la cubre | El proveedor dice que **sí** la cubre y no la tenemos |
|---|---|---|---|
| Eventos | 3.386 | 0 | **3.386**: todos de copas (continentales 2.871 de 10.040 partidos, copas nacionales 325 de 2.039, de selecciones 190 de 1.273); en las ligas, 0 de 24.769 |
| Estadísticas de los equipos | 13.949 | 9.145 sin filas (y en otros 373 sí tenemos, aunque no las declare) | **1.735** sin filas; además, 3.069 partidos tienen filas pero sin ninguna cifra |
| Jugadores | 14.795 | 10.403 | **4.392** |

En total, **7.716 partidos (20,2 %) tienen un hueco que el proveedor dice cubrir** (eventos, estadísticas o jugadores), y 1.156 de ellos son de
los últimos 60 días. Rellenarlos sería volver a pedir el detalle de esos partidos al proveedor, 20 partidos por petición: unas **386
peticiones** (0,6 % de un día del tope de 60.000). **F7 promete 0 peticiones y no lo he hecho: es una decisión tuya** (abajo). Una cosa
pesa en ella: PrediGol ya vuelve a leer el detalle de cada partido terminado a los +150 minutos y a las +26 horas (una petición por cada 20
partidos), pero solo durante los 7 días siguientes al partido y solo desde el 5-oct; lo que quedó con hueco fuera de esa ventana no se vuelve a
pedir nunca.

## Los eventos: qué es cada línea (`events-v1`)

El proveedor lista, en el orden en que ocurrieron, goles, tarjetas, cambios y decisiones del VAR como texto. Lo que se midió en producción
(3,2 millones de líneas) y cómo lo lee PrediGol:

| Lo que manda el proveedor | Cómo lo lee `events-v1` |
|---|---|
| Una **tanda de penales** llega como líneas «Gol / Penal» en el minuto 120 (10.908 en toda la historia) | lanzamientos de la tanda (`shootout_goal`, `shootout_miss`), en su propio periodo `PEN`: **no son goles del partido** |
| Un **autogol** viene archivado bajo el equipo que RECIBE el gol (1.154 partidos cuyo único gol fue un autogol) | cuenta para el equipo que lo recibe; el jugador pertenece al otro equipo |
| Una **segunda amarilla** son dos líneas: amarilla y roja del mismo jugador en el mismo minuto (18.676 casos) | la roja del par es `second_yellow` (cuenta como expulsión) y la amarilla del par queda unida a ella |
| Una **roja de un jugador que ya tenía una amarilla en otro minuto** (1.529 casos) | se deja como roja con la bandera `after_yellow`: la lista no dice si fue segunda amarilla o directa y **no se adivina** |
| El **VAR que anula un gol quita el gol de la lista** y deja la decisión sola (2.251 de 2.253 casos) | la decisión es un hecho del partido (`var_goal_cancelled`, minuto y lado); no se enlaza con ningún gol ni se resta del marcador |
| Algunas líneas **no nombran a nadie** (3.303 goles normales en los últimos 400 días) | cuentan como goles, no se dan a ningún jugador y la capa de jugadores cuenta cuántos fueron |
| El minuto no es el periodo: **73 partidos de tiempo reglamentario traen minutos sobre 90** | un minuto sobre 90 es tiempo extra solo en un partido que fue a tiempo extra; en otro es el descuento del segundo tiempo |

Ninguna línea se descarta, y una palabra que `events-v1` no conoce se cuenta sin interpretarla (nunca como suposición). De las 505.302 líneas
de las 38.121 construcciones, ninguna quedó como «otro» ni como «tarjeta sin tipo»; solo 75 decisiones del VAR (en 74 partidos) traen
palabras que no se conocen y quedan como «VAR, otro». Cuánto cuadra la lista con el resultado, partido a partido:

| Comprobación (partidos con eventos, últimos 400 días) | Concuerda | No concuerda |
|---|---|---|
| Goles de los 90 minutos de la lista = resultado | 34.626 de 34.732 (99,7 %) | 106 |
| Goles del primer tiempo = marcador del descanso | 34.645 de 34.725 (99,8 %) | 80 |
| Goles del tiempo extra = final − reglamentario | 565 de 592 (95,4 %) | 27 (listas incompletas, p. ej. 2 eventos en un partido con prórroga) |
| Lanzamientos de la tanda = resultado de la tanda | 65 de 68 (95,6 %) | 3; solo el 17 % de las tandas trae sus lanzamientos listados |
| Tarjetas de los eventos = las de las estadísticas | 22.076 de 23.570 (93,7 %) | 1.494 |

La auditoría del normalizador sobre 34.777 partidos (23 oct) dio 99,70 % para los 90 minutos, 99,77 % para el descanso y 98,59 % para el tiempo
extra. Esta última compara con la columna de tiempo extra del resultado (en cerca del 5 % de los partidos con prórroga esa columna es un
total acumulado, revisión 0031); la tabla de arriba compara con el marcador final menos el reglamentario, que es lo que usa la capa, por eso
la cifra es otra. De los 106 que no cuadran a los 90 minutos, a la lista le faltan goles en 60 y le sobran en 45 (19 con un gol que nadie
marcó, 15 con un «Penal cancelado» del VAR…). Esos partidos quedan con la duda «los goles de la lista no suman el resultado» y su historia
del marcador no se cuenta: se dice, no se inventa.

## Las cuotas: hoy hay dos cierres

La capa del mercado guarda dos cosas distintas, y conviene que lo sepas porque **el plan decía «CLV» y aquí no hay un solo cierre**:

* **El cierre del consenso** (la última lectura del reloj de precios antes del inicio): queda a **175 minutos** del inicio (mediana; de 175 a
  179 en el 80 % central de 1.513 partidos de 14 días). Es lo que ve el usuario si lo enciendes, como probabilidad, y es contra lo que se mide
  hoy el CLV de las decisiones.
* **Los últimos precios del proveedor** (`final`, que el proveedor aún tiene tras el partido): están mucho más cerca del inicio (mediana de
  **85 minutos**, el 90 % de ellos a menos de 218), pero solo existen para el **72 % de los partidos** (1.928 de 2.686 de los últimos 30 días).
  Son un precio, no una probabilidad: **los ves tú; un usuario no los recibe** (la API los quita).

Hasta que F8 deje una sola fuente para el CLV, los dos se guardan y se rotulan; no se promedian ni se elige uno en silencio.

## Un partido real

Partidos de los últimos días, armados «en seco» (sin escribir nada) para ver cómo queda el objeto:

**Santa Fe 2–1 Jaguares** (Primera A, Colombia, 22 oct; partido 21369), completo:

* *Resultado:* 2–1, descanso 1–0, ganó el local; tres goles y ambos marcaron.
* *Estadísticas:* tiros 17–15 (a puerta 6–2), posesión 50–50, goles esperados 0,79–1,09.
* *Eventos:* 16 líneas: goles de Fagúndez (5', pase de Rodallega, y 81') y de Rentería (90+2', pase de Jopito), tres amarillas y diez cambios; por
  periodo, 1T 1–0 y 2T 1–1; la lista cuadra con el resultado.
* *Jugadores:* el mejor valorado, Fagúndez (8,7 y dos goles); del visitante, Rentería (7,7).
* *Táctica:* 4-2-3-1 los dos; el local fue por delante 85 de los 90 minutos y estuvieron empatados 5.
* *Mercado:* la probabilidad del triunfo local pasó de 70,4 % a 78,4 % de la apertura (19-oct) al cierre (176 minutos antes); más de 2,5 goles, de
  54,0 % a 66,3 %; ambos marcan, de 45,5 % a 49,9 %. Último precio del proveedor (solo tú): local 1,24, empate 5,60, visitante 10,00, a 77 minutos.
* *Solo administrador:* 27 decisiones sobre 23 líneas (21 rechazadas y 2 en investigación, que ganaron), 81 picks en sombra y 2 post-mortems con
  veredicto SUERTE.

**Flamengo 0–0 Estudiantes L.P.** (Libertadores, 23 oct; partido 20288), el caso difícil: eliminatoria a dos partidos, global 0–0, decidida en
penales (2–3, pasa el visitante). Los nueve lanzamientos de la tanda quedan en su periodo y suman 2–3 **sin tocar el 0–0**. Una expulsión del
visitante al minuto 50 es de un jugador que ya tenía una amarilla en el 35: la lista no dice si fue segunda amarilla o roja directa y queda como
roja con `after_yellow`. Las tarjetas de los eventos no coinciden con las de las estadísticas y el postpartido lo dice («Lo que no pudimos
confirmar»).

**Kolos Kovalivka – Zorya Luhansk** (amistoso de clubes, 4 oct; partido 603724): el proveedor dio el resultado y nada más (ni eventos, ni
estadísticas, ni jugadores). Queda guardado tal cual, **mínimo**, y la pantalla lo dice en vez de rellenarlo.

## Qué ve cada quien

* **Un usuario: nada, hasta que tú enciendas `FBI_KNOWLEDGE_USERS=1`** (y reinicies la API). La API contesta «no disponible» y la web no pinta
  ni un hueco.
* **Si lo enciendes para los usuarios**, ven el bloque «Postpartido» en el Resumen de un partido terminado: etiquetas de lo notable (se resolvió
  en tiempo extra o en penales, remontada, campo neutral, resultado corregido), «Cómo fue el marcador» (quién iba por delante, primer y último
  gol, cambios de ventaja, primera expulsión), «Lo que esperaba el mercado» (la probabilidad de las casas sin su margen, de la primera lectura
  de la semana a la última antes del inicio, con lo que ocurrió marcado), «Los mejores del partido», «Formaciones y cambios», y la etiqueta
  Completo / Parcial / Mínimo con «Lo que no pudimos confirmar». **Sin cuotas, sin picks, sin decisiones, sin post-mortems y sin nada de cómo
  PrediGol se juzgó a sí mismo.** Mientras un partido terminado no está asentado, ven «El postpartido se arma unas horas después del final»;
  los demás motivos de que no haya objeto (no terminó, no se sigue la competición, aún no se armó) no se les muestran.
* **Tú (SUPER_ADMIN) con «Modo de evaluación» encendido:** el mismo bloque con la insignia MODO EVALUACIÓN, en todos los estados (cargando,
  error, sin armar y por qué) y un plegable «Cómo está guardado (solo administrador)»: la versión guardada y la cadena de versiones del
  partido, las huellas, las nueve capas tal como están guardadas (las de contexto, picks y post-mortem son tuyas), los últimos precios del
  proveedor y los datos crudos. Con «Ver como USUARIO» ves lo que vería un usuario.
* **API:** `GET /api/v1/matches/{id}/knowledge`; con `?preview=shadow` (solo SUPER_ADMIN; cualquier otro rol recibe 403) añade la fila tal
  como está guardada, sus fuentes, la cadena de reconstrucciones y los precios. Ninguna ruta construye una fila, llama al proveedor ni puede
  cambiar un pick.
* **Un partido sin postpartido** dice por qué, con un código estable y en este orden: `not_finished`, `not_followed`, `not_settled_yet`,
  `no_build_yet`.

## La IA y el postpartido

Nada cambia: F7 no toca `packet-v8`, `brief-v8` ni `leak-audit-v6`, y su gasto de IA es 0. **La IA no lee Match Knowledge** (no existe un
camino de él a un paquete, y la prueba de aislamiento lo guarda). No hay una regla nueva en la auditoría nocturna de fuga porque no hay nada
que comprobar todavía; cuando F8 deje que un bloque de antes del partido cite el postpartido (la memoria de un equipo, de un árbitro…),
entrará con su regla: lo citado existe, no es posterior al momento del paquete y es de un partido que ya había terminado entonces.

## Reglas que se respetan

1. **Es lo que el partido resultó ser, no lo que se dijo antes.** Nada de los modelos, los pronósticos, la capa de decisión, el motor de
   picks, el dossier ni el paquete de la IA lee las tablas ni importa el código que las escribe. Una prueba
   (`tests/unit/test_knowledge_isolation.py`) guarda cuatro puertas: solo los archivos listados nombran las tablas; nada que arme o juzgue
   una vista de antes del partido (más de cien archivos) puede nombrarlas ni importarlas; el paquete de F7 no importa nada de PrediGol salvo
   la lectura de lados local/visitante y el constructor escribe **exactamente** sus dos tablas y ningún hecho de un partido; y la página del
   partido no escribe nada. Se comprobó con 12 mutaciones (añadir una lectura en la capa de decisión, un `UPDATE` en la página…): las 12
   rompen la prueba.
2. **Solo se añade, y cada cosa dice cuándo se supo.** Una fila nunca se edita ni se borra. Un partido que cambia recibe otra que nombra la que
   reemplaza, y un índice único deja que cada fila sea reemplazada una sola vez (el worker y una persona en la consola no pueden añadir las
   dos «la siguiente»). Un partido que va de A a B y vuelve a A tiene tres filas, y la tercera es un hecho propio.
3. **La misma lectura da el mismo resultado.** Reconstruir con las mismas entradas dio otro hash de contenido en **0 de 38.121** partidos, y
   la huella de un partido no depende de la zona horaria ni del formato de fecha de la sesión que la toma.
4. **No se inventa.** Capa que falta → `missing` y el código; menos de lo necesario → `partial` y qué falta; palabras que `events-v1` no
   conoce → se cuentan sin interpretar; una lista de eventos que no cuadra con el resultado → «no pudimos confirmarlo» y la historia del
   marcador no se cuenta. Una cifra que el proveedor no dio es nula, nunca cero.
5. **Un usuario no recibe precios.** Los últimos precios del proveedor los quita la API de toda respuesta que no sea la vista previa del
   administrador, y cada campo que un usuario puede ver está nombrado en un modelo del contrato: un campo que el constructor añada mañana no
   le llega hasta que alguien lo añada allí.
6. **Un fallo no frena nada y se apaga sin desplegar** (abajo).

## Cómo corre

* **Worker:** un trabajo propio, `match_knowledge`, cada 30 minutos sobre los últimos 10 días (hasta 300 partidos y 4 minutos por pasada), y un
  **barrido** diario a las 10:30 UTC sobre los últimos 400 días (hasta 15 minutos y sin tope de partidos): atrapa una corrección del resultado
  que el proveedor haga semanas después, una regla que cambió o un partido que se perdió. Escribe una corrida en el libro
  (`raw.ingestion_runs`) **solo si construyó, falló o se cortó**: una media hora sin novedades no deja fila. El vigilante de corridas lo
  conoce (plazo de 20 minutos). Se apaga **sin desplegar** con `FBI_MATCH_KNOWLEDGE=0` en `/etc/predigol/app.env` y reiniciando el worker (la
  API, `FBI_KNOWLEDGE_USERS`, necesita su propio reinicio). Los ajustes finos son `FBI_MATCH_KNOWLEDGE_{MINUTES,DAYS,SWEEP_DAYS,PER_RUN,RUN_SECONDS,SWEEP_SECONDS}`.
* **A mano, desde `backend/`** (0 peticiones al proveedor; `build` es un ensayo en seco hasta `--apply`):

```bash
python -m scripts.match_knowledge status                         # cobertura, tamaño de las tablas, últimas corridas del trabajo
python -m scripts.match_knowledge coverage --days 400            # partidos con construcción, qué tan completos, líneas de eventos leídas
python -m scripts.match_knowledge build                          # ensayo en seco: lo que construiría una pasada del worker (10 días)
python -m scripts.match_knowledge build --apply                  # construirlo
python -m scripts.match_knowledge build --days 400 --apply       # la carga inicial: un commit por cada 200 partidos
python -m scripts.match_knowledge build --fixture 21369 --apply  # uno o más partidos, de cualquier edad (solo terminados)
python -m scripts.match_knowledge audit --sample 200 --seed 1    # los criterios del plan, sobre lo guardado y una muestra reconstruida
python -m scripts.match_knowledge show 21369                     # la construcción más reciente, capa por capa
python -m scripts.match_knowledge show 21369 --json --fresh      # la fila entera, y si construirla hoy diría lo mismo
```

`audit` solo lee y **termina con error** si falla un criterio: menos de 95 % de los partidos terminados de las competiciones seguidas con una
construcción; una fila cuyo hash de contenido no es el de sus propias capas; una fila al día que construirla hoy diría distinto (**cambió una
regla y no su versión**); o líneas de eventos rancias. Además cuenta los partidos construidos más de cinco veces (`flapping`): son los que
tienen entradas que no paran de cambiar.

## Lo que se midió antes de estrenar (producción, solo lectura, 23 oct 2026)

Un ensayo en seco sobre **todos** los partidos candidatos de los últimos 400 días (38.121, con la sesión de la base en solo lectura: no se
escribió nada):

| Medida | Resultado |
|---|---|
| Partidos leídos y armados | **38.121 de 38.121, 0 fallos**; la API lee las 38.121 filas con sus modelos sin un error |
| Determinismo | reconstruir con las mismas entradas dio otro hash en **0** partidos; las 38.121 huellas son distintas entre sí |
| Tiempo | huella 1,1 ms por partido; lectura 3,2 ms de media (p99 15,9); construcción 0,93 ms (p99 2,7): la carga entera es cuestión de minutos de cómputo más la escritura |
| Peso de una fila | 2.978 bytes de JSON de media (p99 5.095, máximo 7.055), unos 1.190 comprimidos; las 38.121 filas son **113,5 MB en texto y unos 45 MB comprimidas** |
| Líneas de eventos | 505.302 líneas (13,3 por partido) |
| Completitud | completos 23.174 (60,8 %), parciales 11.559 (30,3 %), mínimos 3.388 (8,9 %) |
| Crecimiento (estimado) | ≈ 91 partidos terminados al día × unos 3 KB, más ≈ 1.200 líneas de eventos: **≈ 0,5 MB al día** (se confirma la primera semana) |
| Disco (estimado) | la carga inicial es del orden de 150 MB entre filas, líneas e índices (se mide al terminar): ≈ 5 % de un día de crecimiento actual (+3.167 MB/día); el aviso de disco que ya existía no cambia |

## Resultado de la prueba general

Puerta de calidad completa sobre el árbol final de F7 (23 oct 2026, 11:47–11:57 UTC; el backend corre contra un PostgreSQL 16 real):

| Puerta | Resultado | Tras F6 |
|---|---|---|
| `ruff check .` | sin hallazgos | sin hallazgos |
| `mypy` (estricto; ahora incluye `src/fbi/knowledge`) | **421 archivos, sin errores** | 412 |
| `mypy .` (todo: también pruebas, scripts y migraciones) | **961 archivos, sin errores** | 937 |
| Batería del backend (`pytest`) | **4.277 pasan, 4 omitidas, 0 fallan** (8 min 48 s) | 3.974 pasan, 4 omitidas |
| Web: `bun run lint` | 0 errores (26 avisos que ya estaban; ninguno en un archivo de F7) | 0 errores |
| Web: `bun run typecheck` | sin errores | sin errores |
| Web: `bun test src` | **537 pasan, 0 fallan** (56 archivos) | 465 |
| Web: construcción de producción (`NITRO_PRESET=node-server VITE_DATA_MODE=live`) | correcta | correcta |

Son **303 pruebas más** en el backend y **72 más** en la web que tras F6. Las 4 omitidas son las mismas de entonces (pruebas de independencia
previa al partido que se omiten en los módulos sin código fuente que analizar).

**Lo que encontró la puerta.** La primera pasada completa halló **un fallo** que las pruebas dirigidas de cada parte no habían visto: una
guardia de arquitectura (`test_only_the_listed_modules_name_the_tables_that_hold_the_outcome_of_a_tie`) exige que todo módulo que nombre las
tablas del desenlace de una eliminatoria (`core.ties`, `core.competition_stages`) esté en una lista con su razón, para que ningún lector previo
al partido las lea por su cuenta. Dos módulos de Match Knowledge lo hacen (`fbi.knowledge.reader` lee la eliminatoria de un partido terminado
y cómo se decidió; `fbi.knowledge.layers` la nombra como fuente de la capa 1). Son de postpartido por naturaleza y la puerta de aislamiento
les impide llegar a cualquier lector previo, así que se añadieron a la lista con su razón (commit propio) y la batería se repitió entera
sobre el árbol final: verde. Ninguna otra prueba falló.

**Que las puertas de aislamiento muerden.** Se comprobaron con mutaciones (se rompe a propósito la regla y la prueba debe fallar): 12 de 12
detectadas en `test_knowledge_isolation.py`, y la regla de precios (un usuario no recibe nunca los precios del proveedor) también, porque
con la mutación (devolverlos) falla la prueba de la API.

## Resultado en producción

**Desplegado el 23 oct 2026 a las 14:13:15 UTC** (el despliegue empezó a las 14:00:25 y duró 12 min 50 s), con las migraciones 0089 y 0090
aplicadas a la primera. Backend `db476d5bd534`, web `b5136bc5f0c3`. Los usuarios no ven nada (`FBI_KNOWLEDGE_USERS` sin definir).

| Paso | Resultado |
|---|---|
| Copia verificada antes de migrar | `predigol-20261023T115938Z`: 1.160.610.202 bytes en 502 s (11:59–12:08 UTC). Sigue sin haber copia fuera del servidor (el aviso de siempre) |
| Prueba de restauración | **superada en 804 s** (12:08–12:21 UTC), con las mismas cuentas de filas que producción (246.017 partidos, 3.218.478 eventos, 158.633 picks, 8 cuentas…) |
| Comprobación de calma | ninguna transacción de escritura de más de 20 s sobre `core.fixtures` ni `raw.ingestion_payloads`; despliegue fuera de las horas de `fixtures_sync` |
| Vigilancia de bloqueos (`lockwatch`) | de las 14:00 a las 14:50 UTC (50 minutos: el despliegue, la carga de 11 minutos y las comprobaciones): terminó y su registro quedó vacío, **0 esperas** |
| Despliegue (`predigolctl deploy`) | copia propia del despliegue (1.172.092.404 bytes, 458 s), migración, permisos, reinicio y salud, sin incidencias; humo correcto |
| Verificación de solo lectura | revisión 0090; los tres objetos existen; la API solo lee y el worker lee y escribe; el disparador solo-anexar está activo; las tablas nacían vacías; ninguna versión nueva de modelo escribió pronósticos (todas `@mc9a7bec97ca`); los paquetes de IA no cambian (`packet-v8`, ≈ 6.400 tokens de media) ni el gasto del día |
| Una pasada de `pick_pipeline` | la que corría al reiniciar quedó «interrumpida» y la siguiente la rehízo (lo esperado en todo despliegue) |

**La carga de los últimos 400 días** (14:16:35–14:27:53 UTC; el constructor tardó 674 s, 11 min 14 s, y la estimación era de 15 a 25 minutos):

| Medida | Resultado |
|---|---|
| Partidos terminados y asentados en la ventana | **38.113** (ocho menos que en el ensayo en seco: la ventana de 400 días avanzó unas horas; hay 8 partidos en las tres horas que se salieron) |
| Con su Match Knowledge | **38.113 (100,00 %)**: el criterio del plan era 95 % y **se cumple**; 0 fallos, 0 que otro constructor dejara a medias |
| Completitud | completos **23.172 (60,8 %)**, parciales 11.553 (30,3 %), mínimos 3.388 (8,9 %): lo mismo que midió el ensayo en seco |
| Capas (partidos que la tienen) | resultado 38.110 · estadísticas 24.170 · eventos 34.727 (34.551 completos y 176 parciales) · jugadores 23.324 · táctica 37.422 (13.728 parciales) · mercado 2.024 · picks 1.732 · post-mortem 37 · contexto externo 0 (apagada) |
| Líneas de eventos clasificadas | **505.197** (el ensayo dijo 505.302: la diferencia, 105 líneas, son los ocho partidos que salieron de la ventana, a 13,3 líneas por partido) |
| Peso de una fila | 2,91 KB de media y 6,89 KB el máximo; las 38.113 filas pesan **110,9 MB de JSON** |
| Auditoría (`audit --sample 200 --seed 1`) | **ok**: 0 filas cuyo hash no es el de sus capas, 0 desactualizadas, 0 que reconstruidas hoy digan distinto, 0 líneas de eventos rancias, 0 partidos construidos más de una vez |
| Tamaño en la base (con índices) | `intel.match_knowledge` **108 MB** · `core.fixture_event_kinds` **92 MB** (59 MB de tabla y 34 MB de clave): **≈ 200 MB en total**, y la base completa 18 GB |
| Disco | 57 % (84 GB libres); el aviso del vigilante («90 % en ≈ 18 días, +3.535 MB/día») no se movió por F7 |

La carga solo escribió en las dos tablas nuevas: 0 peticiones al proveedor, y ningún pick, modelo, liquidación ni paquete de IA cambió.

**Lo que salió distinto de lo estimado.** (1) El tamaño de la carga: la estimación era «del orden de 150 MB» y son ≈ 200 MB. Las filas pesan lo
previsto (110,9 MB de JSON frente a los 113,5 MB estimados; 108 MB en la base, ya comprimidas y con sus índices), pero las 505.197 líneas de
eventos clasificadas cuestan 182 bytes cada una con su clave, más de lo que calculé. El crecimiento diario sí es el estimado: ≈ 91 partidos
al día son ≈ 0,26 MB de filas más ≈ 0,22 MB de líneas de eventos, **≈ 0,5 MB al día**, frente a +3.535 MB/día de la base entera; no cambia
nada de lo vigilado. (2) La carga fue **el doble de rápida** de lo previsto (11 min
frente a 15–25).

**Comprobaciones de la API en producción (solo lectura, 14:28–14:30 UTC).** Se montó la aplicación real en un contenedor de operaciones, con
una cuenta inventada y la base en solo lectura (nada se guarda; ninguna contraseña; ninguna petición de red), y se pidió el bloque a 404
partidos (400 elegidos por un hash fijo, más los cuatro de la guía; 403 con su Match Knowledge y uno sin construir todavía) y, por HTTP
completo, a 9 partidos de cada tipo:

| Qué se comprobó | Resultado |
|---|---|
| Con el interruptor apagado, un usuario no recibe nada del partido | sí: responde «no disponible» con la razón y 244 bytes |
| Con el interruptor encendido, un usuario recibe solo las seis capas de hechos | sí en las 403 páginas con conocimiento: resultado, estadísticas, eventos, jugadores, táctica y mercado; sin `stored` |
| Nada de lo que la construcción se guarda llega a un usuario (fuentes, entrenador, decisiones, picks, post-mortems, hashes, correcciones, cadena, precios del proveedor) | sí: ninguna clave ni palabra prohibida en las 403 páginas con conocimiento, y el `final` de cada bloque de mercado es nulo |
| La vista previa es solo del administrador | sí: 403 a un usuario; al administrador le llegan las nueve capas, los dos hashes y la cadena (en 24 de las páginas con precios finales del proveedor) |
| Un partido no terminado, sin asentar o inexistente lo dice | sí: «el partido no ha terminado», «espera la última lectura del proveedor» y 404 |
| Tiempo y peso | mediana 45 ms y máximo 385 ms (la primera petición en frío); los usuarios reciben de 1,3 a 7,1 KB y el administrador de 9 a 15 KB |

(Los dos scripts, `api_check.py` y `api_http_check.py`, y sus salidas se quedan en la carpeta de lanzamiento del servidor, `/root/releases/20261023T1200Z-f7/`.)

*Un falso positivo de la propia comprobación, por si lo ves en `api_check.out`:* la primera pasada marcó 5 páginas porque buscaba un campo
llamado `final` en cualquier sitio; el del resultado es el marcador tras la prórroga o los penales (un hecho del partido, presente en todo
partido que se alargó), no un precio. Se corrigió la comprobación para mirar solo los bloques de mercado y la segunda pasada dio 0 problemas.

**Para tus veinte partidos de prueba (si decides abrirlos con el «Modo de evaluación»):** 21369 y 32333 están completos y 603724 es mínimo.
El 20288 se jugó hoy y **no tendrá su Match Knowledge hasta mañana** (se arma 26 horas después del pitido inicial); mientras tanto la
pantalla dice que el partido espera la última lectura del proveedor. El trabajo del worker (`match_knowledge`, cada 30 minutos) aún no ha
dejado ninguna corrida en el libro porque aún no hay un partido que se haya asentado desde la carga; dejará la primera esta noche.

## Verificación de los criterios del plan

| Criterio de «hecho» | Resultado | Prueba |
|---|---|---|
| Autogol, penal, tanda y segunda amarilla bien clasificados en una muestra auditada | sí: auditado con 34.777 partidos reales (concordancia con el resultado: 99,70 % a los 90 minutos, 99,77 % al descanso, 98,59 % en el tiempo extra) y **ninguna línea sin clasificar** en las 505.302 construidas, salvo 75 decisiones del VAR de tipo desconocido | `test_an_own_goal_counts_for_the_side_the_provider_filed_it_under_and_belongs_to_the_other_mans_team`, `test_the_kicks_of_a_shoot_out_are_not_goals_of_the_match_and_have_their_own_period`, `test_a_yellow_and_a_red_of_the_same_man_at_the_same_minute_are_a_dismissal_for_two_yellows`, `test_a_goal_the_var_took_away_is_a_decision_with_no_goal_beside_it` |
| Reconstrucción idempotente | sí: mismo contenido, mismo hash (0 diferencias en 38.121); una relectura que encuentra lo mismo no añade fila; dos constructores a la vez no duplican | `test_the_provider_reading_the_match_again_and_finding_the_same_facts_adds_no_row`, `test_a_match_nobody_has_touched_costs_a_read_and_writes_nothing`, `test_two_builders_that_read_the_same_newest_build_cannot_both_add_the_next` |
| Un partido que cambia deja historia | sí: una cadena de filas, la más reciente es lo que el partido es hoy | `test_a_correction_of_the_result_adds_a_row_that_names_the_one_it_replaced_and_says_it_was_corrected`, `test_a_match_that_goes_back_to_what_it_was_has_three_rows_and_the_newest_is_what_it_is` |
| La tabla es solo de añadir | sí | `test_a_build_is_never_edited_or_deleted_afterwards`, `test_a_build_can_replace_only_a_build_of_the_same_match_and_version` |
| Al menos el 95 % de los partidos terminados de las competiciones seguidas tienen su Match Knowledge | **en producción, 38.113 de 38.113 (100,00 %)**, 0 fallos; `audit` termina bien (23 oct 2026, 14:28 UTC) | `test_coverage_says_how_many_have_a_build_and_exits_1_under_the_criterion`, `test_audit_passes_on_what_the_builder_wrote_and_names_what_is_wrong_otherwise` |
| Una fila es lo que dice ser, y una regla que cambia sin cambiar su versión se descubre | sí | `test_audit_fails_on_a_row_that_is_not_the_hash_of_its_layers_and_on_a_rule_that_changed_without_a_new_version` |
| Objeto nuevo; nada depende de él hasta F8 | sí: cuatro puertas, 12 de 12 mutaciones detectadas | `tests/unit/test_knowledge_isolation.py` (12 pruebas) |
| La migración se deshace sola y no toca nada más | sí | `test_0089_and_0090_add_three_objects_and_nothing_else_and_come_back_out` |
| Un usuario no ve nada hasta que se decide, y luego solo hechos y sin precios | sí | `test_a_user_gets_nothing_until_the_owner_decides_and_then_only_the_facts`, `test_a_user_is_told_the_facts_layer_by_layer`, `test_what_the_build_keeps_to_itself_never_reaches_a_user`, `KnowledgeBlock.test.tsx` |
| Un fallo del trabajo no frena nada y se apaga sin desplegar | sí | `test_a_match_that_fails_is_recorded_and_the_others_are_built`, `test_a_pass_and_the_daily_sweep_are_registered_only_while_the_switch_is_on` |

## Lo que se decidió distinto del plan (y los límites que conviene conocer)

* **El significado de cada línea de eventos va en una tabla derivada, no en columnas de `core.fixture_events`** (el plan hablaba de columnas).
  Motivos: (1) un disparador de auditoría (revisión 0061, `audit.keep_settled_detail`) copia, entera y en JSON, a
  `audit.settled_detail_changes` cada fila de un partido terminado que se actualiza: rellenar dos columnas de 3,2 millones de líneas las
  copiaría todas, y cambiar ese disparador no es un efecto secundario aceptable de una clasificación; (2) la ingesta reemplaza la lista entera
  de un partido cuando cambia, así que una columna rellenada al escribir guardaría las reglas del día en que se escribió; (3) las reglas van a
  mejorar, y una tabla derivada con versión se reconstruye, mientras que una tabla del proveedor no se reescribe.
* **Un trabajo propio del worker, no un paso dentro de `results_repair`** (el plan lo ponía después de la relectura final). Como los trabajos
  de árbitros y de jugadores de F3, tiene su interruptor, su plazo y su vigilante, y un defecto suyo no puede frenar la reparación de
  resultados. Espera las mismas 26 horas.
* **El VAR no se «enlaza» a un gol.** El plan decía «enlace VAR → gol anulado»; medido, el proveedor **quita** el gol anulado de la lista y
  deja la decisión sola (en 2.251 de 2.253 casos), así que no hay nada a lo que apuntar. La decisión queda como un hecho propio, con su minuto
  y su lado.
* **La capa 6 no calcula el CLV** (el plan lo nombraba). Hoy hay dos cierres (arriba) y elegir uno en silencio sería inventar. El CLV de cada
  decisión sigue en la capa 8, medido contra el cierre del consenso, y F8 lo unifica en una sola fuente.
* **La capa 7 (contexto externo con IA) existe y dice «apagada», pero no está construida.** El plan la dejaba opcional y apagada, con un costo
  estimado de US$ 3–8 al mes si se enciende; encenderla sería trabajo nuevo, no un interruptor.
* **La capa 4 guarda los tres mejor valorados de cada equipo** (con minutos, goles y asistencias), cuántos jugaron y cuántos goles no traen
  jugador; no guarda los tiros ni las tarjetas de cada jugador (las tarjetas están en la capa de eventos y las cifras de cada jugador siguen
  en `core.fixture_player_stats`).
* **Sin estadísticas por mitad:** el proveedor no las da (el plan ya lo anotó como riesgo). Lo único «por mitad» es el marcador del descanso y
  los goles por periodo que salen de la lista de eventos.
* **El criterio del 95 % es de partidos con su objeto, no de partidos completos.** Hoy solo el 60,8 % es completo porque hay datos que el
  proveedor no da (arriba); lo que se mide con el 95 % es que cada partido terminado de una competición seguida tenga su construcción.
* **Solo las competiciones que PrediGol sigue**, por defecto (`--all-competitions` quita el filtro). Hoy no cambia nada: los 38.121 partidos
  de los últimos 400 días lo son.
* **`known_at` dice cuándo PrediGol supo algo, no cuándo ocurrió.** Para un partido de hace un año cargado en octubre es octubre. Por eso el
  mercado, los picks y los post-mortems de los partidos antiguos están vacíos (no había nada guardado), y no es un fallo.
* **Nada depende de él hasta F8:** el post-mortem único y la memoria por entidad son de esa fase y entonces leerán el objeto con su propia
  regla «a fecha».
* **Un hueco conocido en los eventos:** `events-v1` no distingue una segunda amarilla escrita como roja con una amarilla anterior de una roja
  directa (1.529 casos en todo el historial); la lista no lo dice y no se adivina.

## Cómo estrenarlo en producción (y qué te aviso antes de cada paso)

1. Copia verificada y **prueba de restauración** antes de migrar. 0089 y 0090 son dos tablas, una vista y un disparador sobre una función que
   ya existe; no tocan nada existente y, al no tener claves foráneas, no necesitan bloquear `core.fixtures` (las migraciones 0085 y 0086 sí
   esperaron por la transacción de 27 minutos del trabajo de partidos). Aun así se hace fuera de las horas de ese trabajo (01:03, 07:03, 13:03
   y 19:03 UTC) y de la auditoría nocturna.
2. `predigolctl deploy`: respaldo propio del despliegue, migración, permisos, reinicio y salud. Con las tablas vacías todo se comporta como
   antes y el bloque no se ve para ningún usuario.
3. **Carga inicial** de los últimos 400 días: `python -m scripts.match_knowledge build --days 400 --apply` (38.121 partidos, un commit por cada
   200; 0 peticiones al proveedor; estimación de 15 a 25 minutos). Después `audit` y `coverage` (cobertura al menos del 95 %) y el tamaño
   real de las tablas.
4. Tú abres partidos con el «Modo de evaluación» encendido y ves el bloque. No hace falta nada más para que sea correcto.
5. Se vigila (abajo) y se anota aquí el «Resultado en producción».

## Cómo deshacerlo

* **Ocultarlo a los usuarios:** `FBI_KNOWLEDGE_USERS=0` (es el valor de fábrica) y reiniciar la API.
* **Dejar de escribir:** `FBI_MATCH_KNOWLEDGE=0` y reiniciar el worker; lo escrito se queda donde está.
* **Quitarlo todo:** `predigolctl rollback` a la versión anterior del código y `alembic downgrade 0088`, que borra la vista, las dos tablas y
  el disparador. Lo único que se pierde es lo derivado: las filas se pueden volver a construir con lo que haya guardado, pero no la historia
  de versiones de cada partido (cuándo cambió y qué decía antes), así que antes se hace la copia de despliegue habitual. Los paquetes de la IA
  y todo lo anterior no se tocan.

## Lo que decides tú

* **¿Los usuarios ven el postpartido?** (`FBI_KNOWLEDGE_USERS`.) No la tomé. Opciones: (a) **no, por ahora** (lo que queda al desplegar);
  (b) **sí, tal como está** (los hechos de los partidos terminados, sin precios, con «Parcial» o «Mínimo» y «Lo que no pudimos confirmar»
  donde corresponda); (c) **sí, pero solo los completos** (hoy el 60,8 %), que pide un cambio pequeño en la API y en la web antes de
  encender. Con lo medido, mi sugerencia es empezar por (a), abrir con el «Modo de evaluación» una veintena de partidos de tipos distintos
  (por ejemplo 21369, 20288, 603724 y alguno con eventos dudosos como 32333) y decidir con eso; pero es tu producto y tu riesgo.
* **¿Se vuelven a pedir al proveedor los partidos con hueco que dice cubrir?** (7.716 partidos, unas 386 peticiones, 0,6 % de un día del
  tope.) F7 promete 0 peticiones y no lo hice. Mi propuesta: **una sola petición de prueba** con 20 de esos partidos de más de 7 días (los que
  PrediGol ya no vuelve a leer); si el proveedor los entrega, decides el resto; si no, no hay nada que rellenar.
* **¿Se encenderá algún día la capa 7** (noticias de después del partido con IA, US$ 3–8 al mes según el plan)? No hace falta decidirlo ahora:
  hoy está apagada y habría que construirla.
* Nada más de F7 pide una decisión tuya. (Lo del CLV con dos cierres lo planteo cuando llegue F8.)

## Lo que queda vigilado tras desplegar

1. `python -m scripts.match_knowledge status` y `audit`: cobertura al menos del 95 % de los terminados de las competiciones seguidas; ninguna
   fila cuyo hash no concuerde; ninguna línea de eventos rancia; y los partidos construidos más de cinco veces (`flapping`) en cero o muy pocos.
2. Las corridas del trabajo `match_knowledge` en el libro: sin errores ni cortes, y una corrida solo cuando se construyó algo.
3. El tamaño real de las dos tablas tras la carga y tras una semana (la estimación de arriba, ≈ 0,5 MB al día, se confirma o se corrige).
4. El barrido de las 10:30 UTC: cuánto dura y qué carga pone, junto a los barridos de árbitros (09:50) y de jugadores (10:00).
5. La auditoría nocturna de fuga: sin cambios (`leak-audit-v6`, 0 violaciones) y el aviso de disco del servidor, que F7 no debe mover.
