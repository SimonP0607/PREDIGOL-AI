# Pre-partido v3: cara a cara ponderado, escenarios, táctica observable y registro de factores (Plan Maestro, fase F6)

**Qué es.** Antes de F6, lo que PrediGol sabía de «cómo llegan estos dos equipos a este partido» estaba repartido y a veces se contradecía: el
paquete de la IA leía el cara a cara por el marcador de los 90 minutos, la página del partido por el marcador final con la prórroga, y ninguno
decía qué había sido cada cruce (¿un amistoso de reservas de hace seis años pesaba lo mismo que la copa del mes pasado, jugada en el campo del
otro y con otro entrenador?). La IA hacía en prosa las cuentas de «qué le cambia este partido a la tabla» —donde un modelo de lenguaje es menos
fiable— y de la táctica no tenía casi nada. F6 pone todo eso en un solo sitio, con las cuentas hechas por el servidor, y lo dice siempre como
**descripción, no como señal**: nadie ha probado que ninguna de estas cosas prediga mejor que la forma y el mercado.

| | Antes de F6 | Con F6 |
|---|---|---|
| Cara a cara | Dos versiones: el paquete contaba los 90 minutos y la página el resultado final; un 2-2 decidido por penales era empate en una y victoria en la otra | **Una sola función** lee los cruces para el paquete y para la página. El récord cuenta los 90 minutos (como todos los mercados) y la página enseña cómo se decidió. Cada cruce lleva un **peso**: lo reciente, de la misma competición, en el mismo campo y con los mismos entrenadores pesa más |
| Qué le hace el partido a la tabla o a la eliminatoria | La IA lo calculaba en prosa | El servidor calcula, para cada resultado, los puntos y el puesto más alto y más bajo de los dos equipos; en una vuelta, con qué margen pasa o queda fuera cada uno |
| Táctica | Casi nada | Lo observable de los últimos 10 partidos de cada equipo: formaciones, rotación del once, entrenador, goles por tramo de 15 minutos, resultados según quién marca primero y cómo se llega al descanso, y el primer cambio según el marcador. Siempre con el tamaño de cada muestra |
| Estado de cada cosa | Todo lo que decía el paquete valía lo mismo | Cada factor de contexto **nace DESCRIPTIVO** y solo una persona, con el resultado de un experimento, puede dejarlo **VALIDADO** (registro `intel.context_factors`) |
| La IA | Escalaba y no podía decir qué le faltaba | No puede justificar una selección con un factor DESCRIPTIVO (el servidor rechaza esa razón) y puede **pedir investigación** de una lista cerrada (bajas, confirmación oficial, previa internacional) |
| Qué ve el usuario | La lista del cara a cara con el marcador final | La misma lista, con el récord contado a 90 minutos y «(prórroga)» o «(pen. 4–3)» donde corresponda. **Nada más** |
| Qué ven los modelos y los picks | Lo de siempre | **Exactamente lo mismo**: F6 no cambia ningún modelo, Elo, calibrador, regla de valor, pick ni liquidación |

**F6 no cambia ningún modelo ni ningún pick.** Los bloques nuevos viven en `fbi.intel` y `fbi.ai`, fuera de los paquetes de modelos, y una prueba
impide por construcción que algo que entrena, predice, pone precio, decide o liquida los lea (abajo). Por eso la «huella del código de modelos»
(`9a7bec97caec`) no cambia y los modelos no reescriben ningún pronóstico (la lección de F5).

## Qué escribe (y qué no)

Una migración, solo aditiva (**0088**): una tabla y una vista. Nada existente se altera y **la tabla queda vacía**.

| Objeto | Para qué |
|---|---|
| `intel.context_factors` | Una fila por **decisión** sobre un factor y una versión de su código (`DESCRIPTIVE` o `VALIDATED`). Solo-anexar: nada se edita ni se borra. Una validación necesita una persona (`decided_by = 'owner'` con su nombre), el nombre del experimento, el resultado del experimento y que ese resultado hable de **ese** factor y de **esa** versión: la base de datos rechaza la fila si falta algo, no es una convención. Las filas de un factor forman una sola línea (cada una cita la anterior y dos no pueden citar la misma), así que ninguna decisión se cuela por detrás de otra |
| `intel.context_factors_latest` | Vista: la decisión más reciente de cada (factor, versión) |

Sin fila, el factor es DESCRIPTIVO: así nacen los cuatro. **La migración no escribe ninguna fila**, no toca ninguna tabla existente (la nueva solo se
refiere a sí misma, sin claves foráneas hacia `core.fixtures` ni `raw.ingestion_payloads`) y fija un `lock_timeout` de 10 s. Los permisos
genéricos de `grants.sql` ya cubren el esquema `intel`: la API solo lee, y la propia tabla rechaza cualquier cambio o borrado de filas (disparador solo-anexar).

## Los cuatro factores del paquete (`packet-v8`)

Cada uno tiene un nombre en el registro, la versión del código que lo calcula y un lugar en el paquete. Una validación vale para **esa versión**: si se
cambia un peso o una regla, la versión sube y el factor vuelve a ser DESCRIPTIVO hasta que un experimento pruebe la nueva.

| Factor (registro) | Versión | Dónde está en el paquete | Qué tendría que mostrar un experimento |
|---|---|---|---|
| `h2h_weighted` — Cara a cara ponderado | `h2h-v2` | `h2h` | Que el historial entre los dos equipos, ponderado, predice el resultado mejor que la forma reciente de cada uno y que el mercado |
| `scenarios` — Escenarios de tabla y de eliminatoria | `scenarios-v1` | `scenarios` | Que lo que el partido le hace a su tabla o eliminatoria («le basta empatar», «necesita ganar por dos») cambia el resultado más allá de lo que ya dicen el modelo y el mercado |
| `tactics_profile` — Táctica observable | `tactics-v1` | `dossier.tactics` | Que formaciones, cambios y comportamiento con ventaja o desventaja de los últimos partidos predicen el próximo mejor que la forma |
| `rest_congestion` — Descanso y congestión | `team_calendar` (F4) | `schedule` | Que el descanso y la carga de partidos en todas las competiciones cambian el resultado más allá de lo que ya dicen el modelo y el mercado |

### 1. Cara a cara ponderado (`h2h-v2`)

Se leen los **últimos ocho cruces terminados** (`FT`, `AET` o `PEN`), jugados antes del partido y con el resultado ya registrado a la hora de la
pregunta (`settled_at ≤ hora`, como todo lector anterior al partido). El marcador que cuenta es el de **90 minutos**. A cada cruce se le da un peso que es el
**producto de cuatro factores**, todos números redondos:

| Factor | Valores |
|---|---|
| Antigüedad | Pierde la mitad de su peso cada **3 años** (0,5^(edad / 3 años)). La edad se cuenta desde el inicio del partido, no desde la hora de la pregunta, para que el bloque no cambie de un pase a otro si nada más cambió |
| Competición | La misma 1,0 · del mismo tipo (liga, copa, continental, selecciones) 0,85 · de otro tipo oficial 0,6 · un amistoso cuando el partido no lo es 0,25 |
| Campo | El local de hoy también fue local 1,0 · fue visitante 0,8 · campo neutral 0,9. Si el partido de hoy es en campo neutral, todos valen 1,0: no hay campo que reflejar |
| Entrenadores (por equipo) | El mismo que hoy 1,0 · no se sabe 0,9 · otro 0,75. Sale de la hoja de alineación más reciente que existía a esa hora (por id del proveedor o por el nombre sin acentos; nunca se adivina) |

**Los pesos no están ajustados a ningún dato.** Son redondos a propósito, para que se pueda explicar por qué un cruce cuenta lo que cuenta, y viajan
escritos en el bloque (`weights`, con `fitted: false`). El bloque lleva además el récord ponderado, el **tamaño de muestra efectivo** (el de Kish:
ocho cruces de los que tres llevan casi todo el peso son tres cruces) y una nota que dice que el historial directo pesa poco frente a la forma y el
mercado. Un cruce cuyo resultado se registró después de la hora de la pregunta no entra; aparece en el paquete **siguiente**, no en el anterior.

### 2. Escenarios (`scenarios-v1`)

Lo que **este partido solo** puede hacer, dicho como aritmética sobre la tabla y la eliminatoria que el paquete ya trae:

* **Tabla.** Para cada resultado (gana el local, empate, gana el visitante): los puntos de los dos equipos y el **puesto más alto y más bajo** que
  pueden ocupar, con la zona (título, continental, descenso) que describe el proveedor. **Los demás equipos conservan sus puntos actuales** (los otros
  partidos de la jornada no se simulan y el bloque lo dice), así que un puesto es un intervalo, no un número: el mejor puesto cuenta solo a los
  equipos con más puntos y el peor a los que tienen los mismos. Si la tabla del proveedor no está ordenada por puntos (un descuento que no está en los
  puntos, una clasificación por puntos por partido, dos tablas mezcladas) el bloque dice `rank_not_by_points` y **no** inventa un intervalo plausible.
* **Eliminatoria.** En la vuelta de una eliminatoria a dos partidos, con qué margen de goles (a 90 minutos) pasa cada equipo, queda igualado o queda
  fuera («puede perder por uno y seguir arriba»). Qué pasa con el global igualado lo decide el reglamento de la competición (prórroga, penales,
  goles de visitante) y el bloque dice `competition_rules`: no se supone. Una ida, un partido único, una repetición o una serie se pasan tal cual.

No son probabilidades: nadie le pregunta nada a un modelo y el bloque no dice cuál resultado es más probable.

### 3. Táctica observable (`tactics-v1`)

Solo lo que las listas del proveedor permiten **contar**, en los últimos 10 partidos de cada equipo (los mismos del dossier, hasta 400 días atrás):
las formaciones usadas, cuántas veces cambió de una a otra y la última; cuántos del once cambian de un partido al siguiente y cuántos jugadores los
jugaron todos; si la muestra es de un entrenador o de varios y desde cuándo está el último; los goles marcados y recibidos por tramo de 15 minutos (y
los tardíos, después del 75); los resultados cuando marcó primero o recibió primero, cuántas veces ganaba y no ganó o perdía y no perdió, y por el
resultado al descanso; y los cambios: cuántos, cuándo el primero y con qué marcador.

**Lo que no está.** Posiciones, presión, pases por zona, tiros por periodo: el proveedor no los da (las estadísticas son de todo el partido y los
eventos no traen coordenadas). La posesión y los tiros de **todo el partido** ya los traía el bloque de forma del dossier. No se deduce ningún
«estilo» (presión alta, bloque bajo) de lo que no se mide. Con diez partidos una tasa se mueve por un solo partido: cada bloque lleva su `n` y la
narrativa debe citarlo.

**Reglas para leer un partido** (cada una es una forma de **dejarlo fuera**, nunca de adivinar lo que habría dicho):

* Todo es a la hora de la pregunta: solo lo que existía entonces.
* Los eventos de un partido valen solo si sus goles de los 90 minutos **son** su marcador de los 90 minutos, lado por lado (la lista del proveedor
  puede ser una lectura en vivo que nunca se reemplazó, puede faltarle un gol o seguir listando uno que el VAR anuló). Los autogoles se cuentan para el
  equipo que recibe el gol (comprobado en producción: los 1.154 partidos cuyo único gol fue un autogol); un penal fallado y los de una tanda no son goles; lo
  que se marca después del minuto 90 es prórroga y se deja fuera.
* Una hoja de alineación que las estadísticas del mismo partido ponen en el lado contrario no se usa para la formación ni para el once. Pasa en
  **202 partidos** (casi todos de 2025, casi ninguno desde la primavera de 2026; F3.2). El entrenador escrito junto a esa hoja sí es el correcto (el
  proveedor cruza a los jugadores, no al entrenador) y se usa. Una hoja sin formación (**el 31,7 % de las hojas**) cuenta como un partido sin formación, nunca como
  una formación.

### 4. El registro de factores (`factors-v1`) y el calendario de F4

El paquete lleva ahora un bloque `factors` con el estado de cada factor **cuando se armó el paquete**: la versión del código en vigor, el estado y,
si hay una decisión, cuándo se tomó y con qué experimento. Un registro que no se pudo leer **no cuesta el resto del paquete**: se anota como
`factors` en `missing` y todo se dice DESCRIPTIVO (el lado seguro de cualquier duda). El descanso y la congestión que F4 ya traía (`schedule`) entran
al registro por el mismo camino y también nacen DESCRIPTIVOS.

## Qué ve cada quien

**Los usuarios.** Solo cambia el panel del **cara a cara** de la ficha del partido: el récord (victorias de cada uno y empates) cuenta los 90 minutos y la
lista muestra «(prórroga)» o «(pen. 4–3)» junto al marcador final. Los pesos, los escenarios, la táctica y el registro **no se muestran**. (La API
envía a todos los campos nuevos de cada cruce —goles de 90 minutos, prórroga, penales, tipo de cruce, campo y peso—; la web solo enseña los pesos a los
administradores, y son una descripción, no una predicción.)

**Los administradores (Consola, «PrediGol Intelligence» → «Dossier del partido»).**

* Un **selector de partido**: los partidos del día (de Bogotá) que la IA estudió primero, o una búsqueda por equipo o competición dentro de ±45 días
  del día, o el número del partido (ya no hay que escribir el identificador a mano). Cada resultado dice si la IA tiene paquete y cuánta investigación pidió su último
  informe.
* El dossier del partido ahora incluye: el cara a cara ponderado (cada cruce con su peso y por qué: tipo de cruce y campo; el tamaño de muestra efectivo),
  los escenarios, la táctica de cada lado con el tamaño de cada muestra, **«Factores de contexto»** (el estado de cada uno cuando la IA leyó el paquete y el
  que tiene hoy en el registro, con las decisiones), el **último informe de la IA**, la **investigación que pidió** (qué, para qué lado, qué hizo el
  servidor en cada pasada y por qué no se atendió) y **las afirmaciones que el servidor rechazó** con el motivo.
* En la ficha del partido con el modo de evaluación, cada cruce del cara a cara muestra su peso.

**La IA.** Dos lectores, con paquetes distintos a propósito (ver «Lo que cuesta la IA»):

* **El informe del partido (`brief-v8`, modelo económico).** Lee el paquete **completo**. Lo describe. El servidor **rechaza** como razón de una selección
  cualquier afirmación apoyada en un factor DESCRIPTIVO (queda en la lista de rechazadas con el motivo «rests on h2h_weighted, a DESCRIPTIVE factor:
  it describes the match, it does not justify a selection»). Solo los factores VALIDADOS pueden citarse para eso. El informe puede **pedir investigación** (abajo).
* **El revisor de picks (Sonnet; Opus en la última mirada).** Lee el paquete **como era antes de F6** mientras ningún factor esté validado
  (`fbi.ai.views`): sin los bloques descriptivos nuevos. Un factor validado le llega entero, con su entrada del registro, desde el paquete siguiente.
  Con esa misma vista se comprueban sus afirmaciones y se recuerda su respuesta: un número que solo está en un bloque que no recibió no respalda una
  afirmación suya, y un cambio que solo está en un bloque que no recibió no compra una segunda revisión.
* **Pedir investigación (`research-v1`).** El informe puede decir **qué** le falta, de una lista que escribe el servidor (`availability`: quién puede
  jugar; `confirmation`: confirmar un rumor con fuentes oficiales; `preview`: previa de medios internacionales), de qué lado y por qué (la razón es una
  afirmación como cualquier otra: tipada, citada y con sus números comprobados). Hasta 3 por informe. **La IA nunca escribe una consulta, una dirección ni
  un número de búsquedas**: el servidor las escribe (en el idioma de la competición), decide si busca y cuándo, y solo dentro de lo que ya se permitía
  (las búsquedas del día `FBI_AI_MAX_WEB_FIRST` / `FBI_AI_MAX_WEB_PRE` y el presupuesto: un partido sin candidatos pierde primero su profundidad de pago).
  Un pedido no es motivo para escalar ni cambia nada de lo que un modelo, una regla o un pick deciden. Un pase final no lee la web: lo pedido espera
  al «Ejecutar ahora» del administrador. Cada pedido queda contado (`research_asked`, y `research_searched` o `research_unserved` con el motivo).

**Los modelos y los picks.** Nada. Ningún modelo, Elo, calibrador, regla de valor, pick, liquidación ni backtest lee estos bloques ni el registro.

**La auditoría nocturna de fuga (`leak-audit-v6`).** Cuatro reglas nuevas comprueban que el paquete **no leyó el futuro**:

| Regla | Qué comprueba (por paquete del día que lleva el bloque) |
|---|---|
| `h2h_known` | Cada cruce citado existe, es entre los dos equipos, terminó, fue antes del partido, tenía el resultado registrado a la hora del paquete y tiene la edad que dice; cuando el bloque dice si cambió el entrenador, había una hoja traída a esa hora; y no se dejó fuera un cruce ya conocido por uno más viejo |
| `scenarios_known` | La tabla sobre la que se calcula existe como foto, se tomó antes del paquete y no después del inicio, y trae a cada equipo con los puntos y partidos que cita; la lectura de una vuelta usa el global del propio paquete y su aritmética es la de ese global |
| `tactics_known` | Cada partido de la muestra existe, es del equipo, fue antes y dentro de la ventana, con resultado registrado a esa hora; los eventos y hojas que dice haber leído existían; la muestra son los últimos `N` sin dejar fuera uno conocido; y los goles que cuenta son los de 90 minutos de los partidos cuyos eventos leyó |
| `factors_known` | Para cada factor del paquete, el estado, la decisión y el experimento que cita son exactamente los de la decisión más reciente tomada **hasta la hora del paquete** (una validación decidida después no está; una retirada no sigue ahí; una que existe no falta); y el estado de cada bloque que dice el suyo coincide con el del registro y con su versión |

Las reglas que ya existían (`calendar_known` y las demás) siguen igual.

## Lo que cuesta la IA (el hallazgo de esta fase)

El plan decía «coste similar al actual (el paquete crece; se compensa con el caché por hash)». **Medido, el paquete crece mucho y el caché por hash no
lo compensa**: cada paquete nuevo es un paquete nuevo. Sobre 200 partidos reales que aún no empezaron (el `packet-v7` guardado frente al constructor de
F6, lectura en producción, 23 oct 2026):

| Tokens aproximados por paquete (caracteres / 4) | Media | Mediana | p95 | Máximo |
|---|---|---|---|---|
| `packet-v7` guardado (hoy) | 4.184 | 4.222 | 4.914 | 6.206 |
| `packet-v8` (entero) | **6.222** (×1,49) | 6.338 | 6.998 | 8.380 |
| Vista del revisor de picks | **4.175** (×0,998 del v7) | 4.244 | 4.828 | 6.211 |

Por bloque (bytes medios): dossier 5.849 → 9.487 (la táctica son 3.602 de esos 3.638 de más), cara a cara 79 → 2.430, escenarios 0 → 1.393, registro de
factores 0 → 840. Armar un paquete tarda 383 ms de media por partido (p95 556 ms, máximo 883 ms; 0 errores en 200).

Con los precios de `fbi.ai.pricing` y los 7 días anteriores (16–22 oct, gasto de IA real: **5,58 US$/día de media, ≈ 167 US$ por mes de 30 días, con el tope
mensual en 180**), cada token aproximado son ≈ 2,34 tokens reales: F6 añade ≈ 4.800 tokens reales de entrada por llamada.

| | Hoy | F6 sin vista (lo que habría pasado) | **F6 con la vista (lo que se despliega)** |
|---|---|---|---|
| Revisor de picks (75 con Sonnet + 15 con Opus al día, los topes que se agotan cada día) | ≈ 3,8–4,1 US$/día | **+1,00 US$/día** | **+0,00** |
| Informes (modelo económico, ≈ 335 al día de media) | 0,37–2,27 US$/día | +0,16 US$/día | +0,16 US$/día |
| Total al día | 5,58 | ≈ 6,74 | **≈ 5,74** |
| Total al mes (30 días) | ≈ 167 US$ | **≈ 202 US$ (por encima del tope de 180)** | **≈ 172 US$** (+ ≈ 1,8 US$ una sola vez) |

La mitigación es la **vista del revisor de picks** (`fbi.ai.views`, descrita arriba): lo que pesa sobre si un pick se muestra (la llamada más cara de
PrediGol) sigue leyendo el paquete de antes de F6 hasta que una persona valide un factor, y solo el informe (una fracción de centavo por llamada) lee el
paquete entero. Es además lo correcto por diseño: un bloque que no debe pesar en un pick es un bloque que el revisor no recibe.

**Una sola vez tras desplegar**, `BRIEF_VERSION` forma parte de la huella de entrada de cada informe y todos se releen una vez: el 17 de octubre, tras
un cambio de versión, fueron 877 informes y 2,27 US$ frente a ≈ 0,45 normales, o sea ≈ +1,8 US$ por única vez.

**El margen queda estrecho**: ≈ 172–174 US$ de 180 (3–4 %), y el gasto de hoy ya era el 93 % del tope. Si se llegara al tope, la IA deja de llamar y el
informe lo escribe la regla con el mismo paquete («el día sigue con menos prosa, nunca con menos verdad»); la decisión de si se sube el tope o se bajan los
topes de revisiones es tuya (abajo).

## Cómo se valida un factor (o se retira)

Un factor VALIDADO es una decisión **tuya**, con un experimento detrás, sobre **una versión** del código del factor. Qué cambia: el informe puede citarlo
para justificar una selección y el revisor de picks lo lee entero. **No alimenta ningún modelo**: meter un factor en un modelo es trabajo de F10–F12 y
exigirá cambiar `test_context_isolation.py` con su motivo, no ocurrirá como efecto lateral de este registro. Hoy no hay ninguna decisión: los cuatro
siguen DESCRIPTIVOS (el único experimento que ya existe es el de descanso real de F4, que además no promueve nada por sí solo).

```bash
python -m scripts.context_factors list                                   # cada factor, su versión en vigor, su estado y la decisión que lo respalda
python -m scripts.context_factors history [FACTOR]                       # todas las decisiones, de la más antigua a la más reciente
python -m scripts.context_factors promote FACTOR --experiment NOMBRE --result RESULTADO.json --reason "por qué"                         # ensayo: qué cambiaría
python -m scripts.context_factors promote FACTOR --experiment NOMBRE --result RESULTADO.json --reason "por qué" --by TU_NOMBRE --confirm # TU decisión: validar
python -m scripts.context_factors retire FACTOR --reason "por qué" [--by TU_NOMBRE --confirm]                                          # quitar la validación (ensayo si no hay --confirm)
```

Todo lo que escribe es un ensayo hasta `--by NOMBRE --confirm`; una validación que la base rechazaría se rechaza antes de preguntar; el resultado del
experimento es un archivo JSON (el registro guarda hasta 64 kB del resultado; uno mayor se queda en su archivo y la fila lo nombra). Retirar una validación es una fila
nueva DESCRIPTIVA: el pasado no se toca, y «¿qué era este factor el día 3?» tiene una sola respuesta.

## Reglas que se respetan

* **Ningún modelo, Elo, calibrador, regla de valor, pick, liquidación ni backtest lee estos bloques ni el registro.** Lo prueba
  `test_context_isolation.py` con tres comprobaciones: los módulos viven fuera de los paquetes de modelos; solo los archivos de una lista escrita importan
  cada módulo (añadir un lector nuevo rompe la prueba hasta que alguien decida, por escrito, que puede leer; así se añadió `ai/views.py`); y nada que
  entrena, predice, pone precio, decide o liquida los importa.
* **Lo que se sabía en ese momento.** Cada bloque se lee «a la hora T», como el resto del paquete; la auditoría de fuga lo comprueba cada noche.
* **Se deja fuera, no se adivina.** Un cruce, un partido, una hoja o una lista que no cumple se descarta y el bloque lo cuenta (`data`); nunca se rellena.
* **Cada bloque lleva el tamaño de su muestra** y la narrativa por reglas (`narrative-v4`) lo cita: un cara a cara corto se dice como «El historial
  directo dice poco (3 cruces, 1.8 efectivos)» y la táctica se cuenta siempre con su `n`.
* **Sin narrativa «emocional» con aspecto de evidencia** (el riesgo que nombra el plan): lo descriptivo se dice como descripción, y el servidor rechaza
  usarlo como razón.

## Cómo corre

* **Worker:** ningún job nuevo. Los bloques se arman dentro de los pases de la IA que ya existen, al construir el paquete. Ninguna petición nueva al
  proveedor, ninguna dependencia nueva, **ningún interruptor nuevo** (`FBI_FORECAST_USERS` y `FBI_CALENDAR_USERS` siguen siendo tuyos y siguen apagados).
* **API:** el dossier se amplía y hay dos rutas de administrador: `GET /admin/intelligence/matches` (el selector) y `GET /admin/intelligence/factors`
  (el registro). La ficha del partido para los usuarios cambia solo en el cara a cara.
* **A mano:** `python -m scripts.context_factors …` (arriba).

## Lo que se midió antes de estrenar

Producción, solo lectura, 23 oct 2026 (las cifras de paquete son las de la tabla de arriba).

| Medida | Cifra |
|---|---|
| Partidos que aún no empiezan en la muestra | 200 |
| Cruces por partido (hasta 8) | media 5,6; **8 en 102 partidos**, ninguno en 14 (distribución: 0→14, 1→14, 2→15, 3→13, 4→15, 5→9, 6→11, 7→7, 8→102) |
| Partidos con escenarios | 199 de 200 (tabla en 190, eliminatoria en 9) |
| Equipos locales con una muestra de 10 partidos de táctica | 194 de 200 |
| Registro de factores | `factors` en `missing` en los 200 (la tabla aún no existe: todo DESCRIPTIVO) |
| Partidos terminados de los últimos 400 días con resultado | 38.198 |
| …con una lista de eventos que da el marcador de 90 minutos | **90,7 %** (34.652) |
| …sin ninguna lista de eventos | 8,9 % (3.388) |
| …con una lista que no cuadra con el marcador | 0,4 % (158) |
| Hojas de alineación (partido, lado) sin formación | **31,7 %** (22.591 de 71.207) |
| Partidos con las hojas de alineación cruzadas por el proveedor | 202 de 137.400 que tienen hoja y estadísticas (casi todos de 2025) |
| Autogoles archivados bajo el equipo que recibe el gol | los 1.154 partidos cuyo único gol fue un autogol |
| Gasto de IA (7 días, 16–22 oct) | 5,08 · 6,85 · 6,37 · 5,43 · 5,12 · 4,99 · 5,23 US$ → 5,58 de media; octubre hasta hoy (8 oct – 23 oct 06:59 UTC): 77,89 US$ |

## Resultado de la prueba general

Pasada el 23 oct 2026 sobre la rama `plan/f6` (encima de F4), antes de preparar el paquete. Nada de esto toca producción.

| Comprobación | Resultado |
|---|---|
| `ruff check` | sin errores |
| `mypy` estricto sobre `src/fbi` (412 archivos) y sobre todo el árbol, pruebas y scripts incluidos (937) | sin errores |
| `pytest` del backend completo, con PostgreSQL | **3.974 pasan**, 4 se saltan (necesitan datos fuente que no existen en el entorno local y ya se saltaban antes), 0 fallan; 314 pruebas más que al cerrar F4 (3.660). Tarda 7 min 34 s |
| Web: `lint`, `typecheck`, `bun test src` | 0 errores (26 avisos que ya existían), tipos sin errores, **465 pruebas pasan** (44 más que al cerrar F4: 421) |
| Web: compilación de producción (`NITRO_PRESET=node-server VITE_DATA_MODE=live`) | correcta |
| Migración 0088 | sube y baja sola dejando la base como estaba (`test_0088_adds_one_table_and_one_view_and_nothing_else_and_comes_back_out`, la prueba de que todas las migraciones son reversibles y el ensayo de cadena completa) |
| Aislamiento de los bloques de contexto | las tres comprobaciones de `test_context_isolation.py` (y `test_calendar_isolation.py` sigue en pie): ningún modelo, Elo, calibrador, regla de valor, pick, liquidación ni backtest los lee |
| Auditoría de fuga `leak-audit-v6` (reglas `h2h_known`, `scenarios_known`, `tactics_known`, `factors_known`) | todas las pruebas de las cuatro reglas, incluidas las que escriben a mano paquetes que leen el futuro y deben ser violaciones |
| Vista del revisor de picks | las 24 pruebas de `test_review_view.py` y la prueba de extremo a extremo de `test_ai_decision_layer.py` (su prompt, sus afirmaciones comprobadas y su respuesta recordada son los de la vista) |

Lo único que esta prueba no puede decir es cómo se comporta todo con los datos reales de un día entero (la lectura de solo lectura de arriba es una muestra de 200 partidos
que aún no empiezan) ni cuánto gasta realmente la IA con los informes nuevos: eso se mide tras desplegar (punto 4 de «Cómo estrenarlo»).

## Resultado en producción (23 oct 2026)

**El despliegue.** Backend `51430f6b326a`, web `29ba732b2358`, migración 0088. Copia verificada y prueba de restauración antes de tocar nada
(`predigol-20261023T072807Z`: 1.151.252.363 bytes en 407 s, revisión 0087; restauración **superada en 653 s**, hasta las 07:46 UTC), vigilancia de
bloqueos sobre `core.fixtures` y `raw.ingestion_payloads` (una muestra cada 3 segundos desde las 07:28 UTC), comprobación de calma justo antes de
empezar (08:00 UTC: ninguna transacción de escritura de más de 20 s sobre esas dos tablas), la copia propia del despliegue
(`predigol-20261023T080047Z-pre-deploy-51430f6b326a`: 1.152.240.254 bytes en 387 s) y `predigolctl deploy`. **La migración se aplicó a la primera** y el
despliegue terminó a las 08:09:15 UTC (9 min 7 s desde el arranque a las 08:00:08, de los que 6,5 son la copia). La ventana quedó fuera de la de
`fixtures_sync` (su pasada de las 07:03 UTC mantiene transacciones de escritura abiertas entre unos 24 y 51 minutos después, es decir, hasta las 07:54).
La vigilancia de bloqueos (de las 07:28 a las 08:38 UTC) terminó sin registrar ninguna espera.

**Lo que se comprobó al terminar (solo lectura, 08:09–08:10 UTC).**

| Comprobación | Resultado |
|---|---|
| Revisión de la base | 0088 |
| Objetos | la tabla `intel.context_factors` y la vista `intel.context_factors_latest` existen |
| Permisos | la API solo lee (SELECT sí, INSERT no); el worker lee e inserta |
| El registro | **0 filas** (todo factor nace DESCRIPTIVO), con el disparador de «solo se añade» (`context_factors_append_only`) puesto. `python -m scripts.context_factors list` corre en producción y lista los cuatro factores (`h2h_weighted`, `scenarios`, `tactics_profile`, `rest_congestion`), los cuatro DESCRIPTIVOS |
| Servicios | API, web y worker en la versión nueva, los tres «healthy»; caddy y postgres sin reiniciar |
| Prueba de humo | `/health` ok y `/login` 200 |
| Salud del servidor | «warning» solo por el aviso de disco que ya existía (90 % en unos 21 días, +3.133 MB/día; disco al 56 %); ningún problema; copia de hace 0 h con la prueba de restauración superada; 0 errores del servidor en 5 minutos; certificado 76 días |
| Registros del worker y de la API (3 horas) | 0 líneas con error en ambos |
| Interruptores en los archivos de entorno | `FBI_FORECAST_USERS`, `FBI_CALENDAR_USERS` y `FBI_TEAM_CALENDAR` siguen sin definir (F6 no añade ninguno): los usuarios no ven pronóstico ni calendario y el feed del calendario sigue leyendo como desde F4 |
| Gasto de IA | hasta las 08:09 UTC de hoy, 5,03 US$ (`pick_review` 4,05 · `web_search` 0,66 · `match_brief` 0,30 · `evidence_extraction` 0,02); el 22 oct fueron 5,23 US$ en el día entero. Sin cambio: aún no hay informes ni paquetes nuevos |
| Peticiones a API-Football | 3.578 de 60.000 a las 08:09 UTC (el 21 y el 22 de octubre fueron 11.825 y 10.665) |

**Una corrida interrumpida, como se esperaba.** La pasada de `pick_pipeline` 74330 (empezó a las 08:03:31) quedó marcada como interrumpida porque el propio
despliegue reinició el worker: el vigilante de corridas cierra la que perdió su proceso y la pasada siguiente la rehace. Las dos anteriores (74323 y
74326) terminaron bien y no encontraron nada que reescribir en los modelos (1.911 pronósticos sin cambios para 648 partidos).

**Lo que se midió a las 08:49 UTC, 40 minutos después (solo lectura).** El worker ya había armado paquetes nuevos de la versión `packet-v8`.

| Medición | Resultado |
|---|---|
| Servicios y registros | API, web y worker «healthy» desde hace 40 minutos; 0 líneas con error en el worker y en la API (3 horas); las pasadas de `pick_pipeline` 74345 y 74346 terminaron bien (la 74350 seguía en marcha) |
| Paquetes de las últimas 6 horas | `packet-v8`: 283 (6.312 tokens aproximados de media, 27.982 caracteres) · `packet-v7`: 1.230 (4.281) · `packet-v6`: 217 (3.686) |
| Tamaño del paquete nuevo frente al viejo, sobre los 194 partidos que tienen los dos | `packet-v8` 6.223 tokens de media (mediana 6.363, p95 7.124, máximo 7.982) contra 4.174 del `packet-v7` del mismo partido: **×1,49**, como se había calculado antes de estrenar |
| **Lo que lee el revisor de picks (la vista)** | **4.183 tokens de media** (p95 4.952, máximo 6.228; ×0,672 del paquete guardado): **+0,2 % frente al `packet-v7`**, es decir, el revisor de picks cuesta lo mismo que antes de F6 |
| Cuánto pesa cada bloque nuevo (bytes de media) | cara a cara 2.440 (en 194 de 194) · escenarios 1.385 (193 de 194) · factores 815 (194 de 194) · agenda de partidos 2.613 · dossier completo 9.506 |
| Estado de los cuatro factores en los 283 paquetes | `h2h_weighted`, `scenarios`, `tactics_profile` y `rest_congestion`: **DESCRIPTIVO en los 283**; ningún paquete trae `factors` entre lo que falta |
| Lo que más falta en los paquetes (de 194) | alineaciones 193 (aún no salen a esa hora), mercado 18, clasificación 13, cara a cara 11 |
| Informes | `brief-v8`: 2 (0,0075 US$ en total; uno pidió investigación) · `brief-v7`: 97 (0,2991 US$). Ninguna afirmación fue rechazada por apoyarse en un factor descriptivo. Con 2 informes no se puede extrapolar el coste por informe |
| Versiones de modelo | ningún pronóstico de modelo nuevo se escribió en las 3 horas (1.911 sin cambios para 648 partidos): no apareció ninguna versión nueva; la huella del código sigue siendo `9a7bec97caec` |
| Gasto de IA de hoy hasta las 08:49 UTC | 5,03 US$ (`pick_review` 4,05 en 85 llamadas · `web_search` 0,66 · `match_brief` 0,31 · `evidence_extraction` 0,02): igual que a las 08:09 UTC, porque la revisión de picks no volvió a correr en esos 40 minutos. El efecto en el gasto se verá en el primer día completo (24 oct) |
| Peticiones a API-Football | 3.749 de 60.000 (el 22 oct fueron 10.665) |
| Disco | 56 %; el mismo aviso de antes (90 % en unos 21 días) |

Lo que esto dice del coste: el revisor de picks, que es lo que más gasta (≈ 4 US$ de los ≈ 5 diarios), no cambia, y por eso el gasto de F6 se queda en los
informes (`match_brief`, ≈ 0,3–0,5 US$ al día), que sí leen el paquete entero: si su coste subiera en la proporción del paquete serían ≈ 0,15 US$ más al día
(≈ 4,5 US$ al mes), dentro del margen que deja el tope de 180 US$. Es una cota, no una medición: se confirma con el primer día completo.

**Todavía por medir.** El gasto de IA de un día completo con la versión nueva (24 oct), y la auditoría nocturna, que se explica en «Lo que queda vigilado»,
punto 3.

## Verificación de los criterios del plan

| Criterio de «hecho» | Resultado | Prueba |
|---|---|---|
| El cara a cara es el mismo en el paquete y en la API | sí, es una sola función; mismos cruces, mismo orden | `test_the_packet_and_the_page_list_the_same_meetings`, `test_the_match_page_reads_the_same_head_to_head_as_the_packet`, `test_the_packet_and_the_page_list_the_same_meetings_in_the_same_order` |
| Un 2-2 decidido por penales es empate a 90 minutos y la página dice cómo se decidió | sí | `test_a_penalty_shootout_is_a_draw_in_regulation_time_and_says_so`, `test_the_page_rows_carry_the_final_score_the_regulation_score_and_how_it_was_decided` |
| Prueba de fuga de datos sobre cada bloque nuevo | sí: cuatro reglas de la auditoría, cada una con paquetes escritos a mano que leen el futuro y deben ser violaciones | `test_the_rule_catches_each_way_a_packet_could_have_known_more_or_less_than_it_should` (cara a cara), `test_the_rule_catches_a_table_the_packet_could_not_have_read` y `test_the_rule_catches_a_reading_of_the_tie_that_is_not_the_arithmetic_of_what_the_packet_knew` (escenarios), `test_the_rule_catches_a_profile_the_packet_could_not_have_read` (táctica), y once casos de `test_context_factors_in_the_packet.py` (registro) |
| Un resultado o una lista que llega después no está en el paquete anterior y sí en el siguiente | sí | `test_a_result_recorded_after_the_moment_is_not_in_the_packet_and_is_in_the_next_one`, `test_a_result_or_a_list_that_arrived_after_the_moment_is_not_there_and_is_there_once_it_has`, `test_a_decision_taken_after_the_packets_moment_is_not_in_it_and_is_in_the_packet_built_afterwards` |
| Todo factor nace DESCRIPTIVO y ningún modelo lo lee | sí | `test_while_nobody_has_validated_anything_every_factor_and_every_block_is_descriptive`, `test_nothing_that_trains_predicts_prices_decides_or_settles_imports_them` |
| Validar exige una persona, un experimento y su resultado, y la base lo impone | sí | `test_the_database_refuses_a_decision_that_breaks_a_rule`, `test_confirming_needs_a_person`, `test_a_decision_is_never_edited_or_deleted_afterwards` |
| Una validación vale solo para la versión del código que se midió | sí | `test_a_validation_is_about_one_version_of_the_code`, `test_a_validation_of_another_version_of_the_code_is_not_in_the_packet`, `test_a_validation_of_another_version_used_for_this_one_is_caught` |
| La IA no justifica una selección con un factor descriptivo | sí, lo impone el servidor | `test_a_reason_for_a_selection_cannot_rest_on_a_descriptive_factor`, `test_a_validated_factor_may_be_cited_and_only_that_one` |
| La IA no escribe consultas y el servidor decide dentro de lo permitido | sí | `test_the_ai_never_writes_a_query`, `test_with_one_search_left_the_match_with_a_candidate_gets_it_and_the_request_is_counted_as_unserved`, `test_near_the_days_budget_a_match_without_a_candidate_loses_its_research_with_the_rest_of_its_paid_depth`, `test_a_final_pass_does_not_read_the_web_and_the_owners_run_now_serves_what_was_asked` |
| El coste de la IA es «similar al actual» | sí, **gracias a la vista** (sin ella, +35 US$/mes); medido en producción: el revisor lee 4.183 tokens contra 4.174 del paquete anterior (+0,2 %) | `test_while_every_factor_is_descriptive_the_reviewer_reads_the_packet_of_before_plan_f6`, `test_the_view_is_about_the_size_the_packet_had_before_plan_f6_and_far_below_the_packet_of_v8`, `test_a_change_only_in_what_the_reviewer_is_not_given_buys_no_second_review` |
| El selector de partido del dossier | sí | `test_the_day_lists_the_matches_of_the_bogota_day_and_the_ones_the_ai_studied_first`, `test_a_text_finds_the_matches_of_a_team_within_45_days_nearest_first_and_ignores_case`, `test_a_number_is_also_a_match_id_and_that_match_comes_first_wherever_it_is` |
| La migración se deshace sola y no toca nada más | sí | `test_0088_adds_one_table_and_one_view_and_nothing_else_and_comes_back_out` |
| «Terminado cuando»: el paquete en *shadow* dos semanas sin errores de fuga y con el coste por partido dentro del presupuesto | **en curso** desde el despliegue: la auditoría nocturna con las cuatro reglas y el gasto de IA se miran cada día (abajo); F6 no cambia ninguna decisión, así que no frena a la fase siguiente | `leak-audit-v6`, `ai.usage` |
| Los modelos no cambian de versión (la huella del código no se mueve) | sí | `tests/unit/test_model_code_version.py` (huella fija `9a7bec97caec`) |

## Lo que se decidió distinto del plan (y los límites que conviene conocer)

* **Los nombres de las rutas y de las versiones.** El plan decía `/admin/intel/dossier?fixture=` con búsqueda, `dossier-v2` y `packet-v3`. Las rutas
  que ya existían se llaman `/admin/intelligence/...` (el selector es `/matches`, el dossier `/matches/{id}/dossier` y el registro `/factors`), y las
  versiones ya iban en `dossier-v4` y `packet-v8` (el resto de fases las subió). Mismo resultado, otro nombre.
* **El revisor de picks no lee los bloques nuevos (la vista).** El plan no lo preveía; lo impuso la medición del coste (arriba). Mientras ningún
  factor esté validado, la IA que pesa sobre un pick lee lo de antes de F6; el informe, que no decide nada, lee todo.
* **La táctica se queda en lo observable.** El plan listaba posesión y tiros; los de todo el partido ya estaban en el dossier y por periodo el proveedor
  no los da. No se infiere ningún estilo de lo que no se mide.
* **«Bajas a fecha» y «calendario» ya existían** (F3 y F4): F6 no los rehace, los registra como factor (el calendario) y los deja donde estaban.
  Una consecuencia que conviene saber: el **descanso y la congestión** de F4 también quedan DESCRIPTIVOS, así que el informe puede describirlos pero el
  servidor ya no le deja usarlos como razón de una selección (el revisor de picks los sigue leyendo como hasta hoy: su bloque es anterior al registro).
* **Los pesos del cara a cara son redondos y no están ajustados.** Ajustarlos a los resultados sería convertirlos en un modelo; eso es un experimento
  (F10–F12), no una descripción. Por eso el factor nace DESCRIPTIVO y el bloque dice `fitted: false`.
* **Un escenario de tabla es un intervalo, no un puesto.** Los otros partidos de la jornada no se simulan. Quien quiera un puesto esperado necesita un
  modelo de toda la jornada: es otro trabajo.
* **La muestra de táctica es de 10 partidos.** Con tan poco, una diferencia pequeña es ruido; por eso el bloque dice `n` y la narrativa lo repite.
* **El cara a cara de la página cambia para los usuarios**: el récord cuenta los 90 minutos. Es lo coherente con los mercados y con el paquete, y es lo
  único que verán de F6; si prefieres el recuento anterior (resultado final), es un cambio de código, no un interruptor.

## Cómo estrenarlo en producción (y qué te aviso antes de cada paso)

1. Copia verificada y **prueba de restauración** antes de migrar (la 0088 es una tabla nueva y una vista, sin claves hacia las tablas grandes y sin
   pedir bloqueo sobre ellas, pero el procedimiento no cambia). **Se despliega en un momento tranquilo**: el job `fixtures_sync` (01:03, 07:03, 13:03
   y 19:03 UTC) mantiene hasta ~27 minutos una transacción de escritura abierta sobre varias tablas, entre unos 24 y 51 minutos después de cada una
   de esas horas; el paso de despliegue comprueba antes de empezar que ninguna transacción de escritura de más de 20 s esté sobre `core.fixtures` o
   `raw.ingestion_payloads` y no arranca dentro de esa ventana.
2. `predigolctl deploy`: copia propia del despliegue, migración, permisos, reinicio y salud. Con la tabla vacía todo se comporta como antes.
3. Prueba de humo (`/health`, `/login`, cabeceras) y verificación de solo lectura: revisión de la base `0088`, la tabla y la vista, los permisos
   (la API solo lee), los tres servicios en la versión nueva, 0 errores en los registros, versiones de modelo que se escriben (deben acabar solo en
   `@mc9a7bec97ca`), paquetes `packet-v8` nuevos y el gasto de IA.
4. Se mide el paquete y el gasto **reales** frente a esta guía (tamaño del `packet-v8`, tamaño de la vista del revisor, coste de la relectura única
   de los informes) y se anota aquí el «Resultado en producción».
5. Se vigila (abajo).

## Cómo deshacerlo

* **No hay interruptores de F6 que apagar**: lo que hace es describir y la IA no puede usarlo para justificar una selección mientras sea descriptivo.
* **Quitarlo todo:** `predigolctl rollback` a la versión anterior del código y `alembic downgrade 0087`, que borra la vista y la tabla. Si se hubiera
  tomado alguna decisión en el registro, **se exporta antes** (`python -m scripts.context_factors history > decisiones.txt` y los archivos de resultado
  de los experimentos) porque la tabla es un registro de decisiones. `packet-v7`, `brief-v7` y `leak-audit-v5` vuelven con el código; los paquetes ya
  escritos solo se añaden y no se tocan. Como F6 no toca los paquetes de modelos, la huella del código de modelos no se mueve y **no se reescribe
  ningún pronóstico** al volver atrás.

## Lo que decides tú

* **El presupuesto de la IA.** Con F6 y la vista, el gasto esperado sube de ≈ 167 a ≈ 172–174 US$ al mes frente a un tope de 180: queda un margen de 6–8
  US$. Si se alcanza el tope, la IA se detiene y los informes los escribe la regla. Opciones: (a) **dejarlo así y mirar la primera semana** (mi
  sugerencia), (b) subir `FBI_AI_MONTHLY_BUDGET_USD`, (c) bajar los topes diarios de revisiones. No hay una decisión urgente.
* **El cara a cara visible para los usuarios.** Cuenta los 90 minutos y enseña la prórroga y los penales. Si no te gusta, dímelo.
* **¿Los usuarios ven el «Pronóstico PrediGol» (`FBI_FORECAST_USERS`) y el calendario (`FBI_CALENDAR_USERS`)?** Siguen apagados y son tuyos; F6 no cambia
  nada de eso.
* **Validar un factor.** Solo cuando exista un experimento (F10–F12) que lo respalde; hoy no hay ninguno que lo pida.
* Nada más de F6 pide una decisión tuya.

## Lo que queda vigilado tras desplegar

1. El gasto de IA por día y por propósito (`ai.usage`: `pick_review` debe seguir en ≈ 4 US$/día y `match_brief` subir ≈ 0,16 US$/día, más el pico único de
   la relectura de los informes el primer día).
2. El tamaño real de los paquetes (`packet-v8` ≈ 6.200 tokens aproximados; la vista del revisor ≈ 4.200) y el tiempo de armado.
3. Las auditorías nocturnas con el código nuevo. La de hoy (≈ 12:50 UTC, que audita el día 22) es **la primera que corre desde F2**: hasta ahora la
   base solo tiene filas `leak-audit-v1` (siete reglas, 0 violaciones en las diez noches que hay), porque todo F2–F6 se desplegó después de la
   auditoría de ayer. Estrena las reglas de F2 a F6, pero las cuatro de F6 aún no tendrán paquetes que revisar (`checked` = 0: el primer paquete con
   sus bloques es de hoy a partir de las 08:10 UTC). **La que cuenta para F6 es la de mañana (24 oct, que audita el 23)**: ahí `checked` sube con los
   paquetes que llevan los bloques y `violations` debe quedar en 0.
   *Primera lectura (23 oct, 12:50 UTC):* la auditoría corrió con `leak-audit-v6` (17 reglas) y las cuatro de F6 (`h2h_known`, `scenarios_known`,
   `tactics_known`, `factors_known`) dieron `checked` = 0, como se esperaba; las demás dejaron dos hallazgos que no son de F6 (`absences_known` en
   paquetes anteriores a F3 y `forecast_known`, ver las guías de F3 y F5) y 0 violaciones en las otras 13 reglas.
4. Que el informe no rechace en masa por «factor descriptivo» (`refused` en el panel «Afirmaciones que el servidor rechazó» del dossier): unas pocas es
   lo esperado; muchas dirían que el prompt está empujando a la IA a usar lo descriptivo como razón.
5. Las peticiones de investigación y qué se hizo con ellas (`research_asked`, `research_searched`, `research_unserved` por motivo) y que no
   superen las búsquedas del día.
6. Que ningún pronóstico se reescriba (versiones de modelo que se escriben terminan solo en `@mc9a7bec97ca`).
