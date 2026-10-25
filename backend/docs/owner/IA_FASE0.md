# Fase 0 del Plan Maestro IA · Eficiencia, coste y medición

Fecha: 25 oct 2026. Estado: **código terminado en la rama `ia/p0`, sin desplegar** (el primer despliegue lleva la migración 0110 y necesita su ventana). Fuente: Plan Maestro IA (aprobado), fase 0 y secciones 19, 24, 26, 28, 29, 32 y 34.

Este documento dice lo que hace el código y **lo vigila una prueba** (`tests/unit/test_ia_fase0_docs.py`): si una cifra de aquí y una constante del código dejan de coincidir, la prueba falla hasta que se corrija una de las dos. Lo que es tuyo (claves, topes de la Console) está en `IA_ACCIONES_MANUALES.md`; el punto de partida medido, en `IA_BASELINE_F0.md`.

## 1. Qué es la Fase 0 y qué no toca

La Fase 0 hace que la capa de IA gaste menos y que se pueda **comprobar** cuánto gasta, sin cambiar lo que responde. Lo que entra:

| Pieza | Qué hace | Dónde está |
| --- | --- | --- |
| Caché de prompts | no se paga de nuevo lo que el modelo ya leyó | `providers/anthropic.py`, `pricing.py` |
| Cambio material | un brief se paga de nuevo solo si el contexto del partido cambió de verdad | `material.py` |
| Batch | a mitad de precio lo que puede esperar | `batch.py`, trabajo `ai_batch_poll` del worker |
| Salidas estructuradas | el proveedor aplica el esquema, en vez de una llamada a herramienta forzada | `providers/anthropic.py` |
| Presupuesto v3 | tres sobres, proyección del mes, reserva y estados | `budget_v3.py`, `costs_v3.py` |
| Libro de cuentas | qué workspace pagó, escrituras de caché, lote, tipo de dinero | `usage.py`, migración 0110 |
| LAB | sondas y prueba de equivalencia con la clave del LAB | `lab.py`, `ia_probe`, `ia_equivalence` |
| Conciliación | el libro contra el CSV de la Console, por workspace y por día | `reconcile.py`, `ia_reconcile` |
| Gate A | el veredicto de fin de fase, leído del libro | `gate_a.py`, `ia_gate` |

**No toca**: probabilidades, calibradores, modelos estadísticos, umbrales, filtros, picks ni nada de lo que ve un usuario. `FBI_AI_MODE` sigue en `shadow`. Todo es aditivo, y si Claude, Batch o el LAB fallan, la capa de IA falla hacia el pipeline cuantitativo: el sistema decide con las reglas, como antes.

## 2. Los cinco interruptores

Cada optimización tiene una variable en el fichero de entorno del servidor (es tuyo). Los valores `0`, `off`, `false` y `no` la apagan, y eso es la **vuelta atrás**; `1`, `on`, `true` y `yes` la fuerzan; cualquier otro valor, o ninguno, es `auto`. Tras cambiarla se reinicia el worker (alrededor de un minuto).

| Interruptor | Variable | En `auto` | Evidencia que espera | Vuelta atrás |
| --- | --- | --- | --- | --- |
| `cache` | `FBI_AI_CACHE` | encendido | ninguna: solo cambia lo que se factura | `FBI_AI_CACHE=0` |
| `brief_material` | `FBI_AI_BRIEF_MATERIAL` | encendido | ninguna | `FBI_AI_BRIEF_MATERIAL=0` |
| `budget_v3` | `FBI_AI_BUDGET_V3` | encendido | ninguna | `FBI_AI_BUDGET_V3=0` |
| `batch` | `FBI_AI_BATCH` | apagado hasta que pase el gate `batch` | la sonda real de Batch en el LAB | `FBI_AI_BATCH=0` |
| `native_schema` | `FBI_AI_NATIVE_SCHEMA` | apagado hasta que pase el gate `native_schema` | la prueba de equivalencia | `FBI_AI_NATIVE_SCHEMA=0` |

El **bloque común del partido primero** (el único cambio de la fase que reordena lo que lee el modelo) necesita siempre su propio gate, `cache_layout`: ni `FBI_AI_CACHE=1` se lo salta, y con `FBI_AI_CACHE=0` no se aplica. Aparte, `FBI_AI_BATCH_MIN_LEAD_MINUTES` (por defecto 240) es el margen mínimo antes del partido para que una tarea vaya a Batch.

## 3. Los gates de evidencia

Un gate es una fila de `ai.feature_gates` que dice si una optimización ha demostrado lo que debía. Hay cuatro:

| Gate | Lo escribe | Qué decide |
| --- | --- | --- |
| `batch` | `ia_probe batch-collect` | `FBI_AI_BATCH` en `auto` |
| `native_schema` | `ia_equivalence collect` | `FBI_AI_NATIVE_SCHEMA` en `auto` |
| `cache_layout` | `ia_equivalence collect` | el bloque común del partido primero |
| `gate_a` | `ia_gate evaluate --record` | el fin de la fase 0 |

La tabla es de solo añadir: nadie edita una fila. **La fila más nueva manda**, así que una repetición que falla vuelve a apagar la optimización que otra había encendido. La evidencia puede nombrar los modelos con los que se midió, y otro modelo no queda cubierto. Cada fila guarda el hash de su evidencia, para poder reproducir la decisión; solo las escriben los scripts, desde mediciones, nunca a mano.

## 4. El presupuesto v3: tres sobres

El dinero de la IA nunca es un solo número. Cada sobre se mide contra su propio tope:

| Sobre | Qué cuenta | Variable | Valor en las fases 0 a 2 |
| --- | --- | --- | --- |
| Producción | Claude del workspace PREDIGOL y las ejecuciones del analista | `FBI_AI_MONTHLY_BUDGET_USD` | 185 |
| LAB | Claude del workspace PREDIGOL-LAB | `FBI_AI_LAB_MONTHLY_BUDGET_USD` | 15 |
| Exa | las búsquedas web, a US$ 0,015 cada una | `FBI_AI_EXA_MONTHLY_BUDGET_USD` | 35 |

* **Techo conjunto de Claude** (producción más LAB): 190 (`FBI_AI_JOINT_CEILING_USD`). El LAB cede primero, por días enteros y sin cambiar de modelo: un brazo que cambia de juez es otro experimento. Su sobre es 15 en las fases 0 a 2, 55 en las 3 a 8 y 15 desde la 9 (acciones 15 y 16).
* **Reserva**: 10 (`FBI_AI_RESERVE_USD`), solo para producción; se libera en los últimos 5 días del mes.
* Los topes de la Console (acciones 8 a 10) quedan un poco por encima de los internos: son la red de seguridad, no el control.
* Sin `FBI_AI_LAB_MONTHLY_BUDGET_USD` el LAB vale 0 y no hace ninguna llamada.

**La proyección del mes** se calcula, no se espera: lo gastado hasta hoy, más lo que le queda a hoy, más los días siguientes. El coste de un día es su número de partidos con mercado por el coste unitario, que es lo que costó un partido con mercado en los últimos 7 días (o en los últimos 14 si en menos de 3 de ellos hubo partidos). Los partidos de los próximos 7 días salen del calendario; más allá, de la mediana del mismo día de la semana en las últimas 4 semanas.

**La asignación del día** es lo que queda, menos la reserva, repartido en proporción a la carga esperada de cada día: entre 0,5 y `FBI_AI_DAILY_MAX_FACTOR` (2) veces la media. Su tope duro es 1,5 veces la asignación, y nunca más de lo que queda.

**Los estados** de producción (se aplica el primero que se cumple, del peor al mejor):

| Estado | Cuándo | Qué cambia |
| --- | --- | --- |
| `EXHAUSTED` | el mes está gastado, el día llegó a su tope duro o el proveedor dijo que el límite está gastado | decide el revisor de reglas, sin llamadas |
| `CHEAP_ONLY` | el gasto del día llega al 125 % de su asignación | solo el nivel barato y sin búsqueda web (hasta que se retire la ruta antigua) |
| `REDUCED` | la proyección pasa del 100 % del sobre, o el gasto del día llega al 100 % de su asignación | sin profundidad de pago para partidos sin candidatos y sin nivel final |
| `AJUSTE` | la proyección pasa del 95 % y no del 100 % | se quita el trabajo duplicado, se reutiliza lo guardado, la caché y Batch cargan con lo que puede esperar, paran las llamadas redundantes y los experimentos secundarios y el LAB se encoge; **la calidad del camino principal no cambia** |
| `NORMAL` | la proyección llega como mucho al 95 % | nada |

**Las alertas** avisan y no degradan nada: el mes de cada sobre al 50, 70, 85, 95 y 100 %, y la proyección de producción al 95 y 100 %.

**El límite gastado del proveedor** (HTTP 400 por el tope del workspace, HTTP 429 `enforced_spend_limit_reached`) deja al workspace en `EXHAUSTED` durante una espera de 30 minutos que se duplica con cada golpe de las últimas 12 horas (30 min, 1 h, 2 h, 4 h, 6 h como máximo). Pasada la espera se hace **una** llamada para probar; si la rechazan es otro golpe y una espera más larga. Nunca un bucle.

## 5. Caché de prompts

Con `FBI_AI_CACHE` en `auto` o `on`, cada llamada marca para la caché del proveedor el **bloque del sistema** (las reglas, el esquema y las consignas, iguales para todas las llamadas) durante **1 hora**; y, solo cuando el gate `cache_layout` ha pasado, también el **bloque común del partido** (lo que comparten todas las revisiones del mismo partido, que va primero, con lo que varía después) durante **5 minutos**. Lo que varía nunca se cachea. Un modelo que rechaza `cache_control`, o su `ttl` de 1 hora, se vuelve a preguntar sin ello y se recuerda.

Precios en US$ por millón de tokens (tabla de `pricing.py`). Escribir en la caché cuesta más que la entrada normal; leerla, mucho menos:

| Modelo | Entrada | Salida | Lectura de caché | Escritura de 5 min | Escritura de 1 h |
| --- | --- | --- | --- | --- | --- |
| Haiku 5.5 | 0,10 | 0,50 | 0,01 | 0,125 | 0,20 |
| Sonnet 5.5 | 2 | 10 | 0,10 | 2,50 | 4 |
| Opus 5.5 | 4 | 20 | 0,20 | 5 | 8 |

La escritura de 5 minutos vale 1,25 veces la entrada y la de 1 hora, 2 veces; la lectura vale 0,1 veces la entrada en Haiku y 0,05 en Sonnet y Opus. El mínimo cacheable de la plataforma es de unos 512 tokens por bloque (verificado el 24 oct 2026): las sondas del LAB usan bloques de unos 1.600, para que si no hay caché eso sea un hallazgo.

**El ahorro se mide, no se supone.** El panel de costes (`costs_v3.py`) valora cada grupo del libro (día de Bogotá, modelo, tiempo real o Batch) dos veces con la misma tabla verificada: como se facturó y como si toda la entrada hubiera sido fresca. La diferencia es el ahorro de la caché. **Puede salir negativa** mientras una escritura aún no se ha leído, y entonces lo dice.

## 6. Batch: a mitad de precio lo que puede esperar

La API de lotes de mensajes (Message Batches) responde la misma petición más tarde, con la mitad de precio en cada token (entrada, salida y caché). Solo va a Batch lo que puede esperar:

| Tarea | ¿Va a Batch? |
| --- | --- |
| Pasada `first` (revisión de candidatos) | sí |
| Pasada `pre` | sí, si el partido empieza dentro de 240 minutos o más |
| Pasada `final`, después de las alineaciones | nunca |
| Vigilancia y arbitraje de una contradicción | nunca: responden algo que acaba de pasar |

Cualquier negativa (un interruptor, un gate, un presupuesto, un lote fallido) devuelve la tarea a la ruta de tiempo real, exactamente como antes.

**La ruta de una tarea.** (1) El ciclo la anota como un elemento del lote del día (`submitting`) **antes** de que salga nada de la máquina. (2) Al final del ciclo se crea un lote por workspace en el proveedor y los elementos pasan a `submitted`. (3) El trabajo `ai_batch_poll` del worker, cada 5 minutos, pregunta por los lotes que terminaron y toma sus resultados: cada uno se decodifica, se valora **a la mitad**, se registra en el libro y pasa al manejador de su propósito, que lo valida y lo guarda igual que lo haría la ruta de tiempo real. Un lote termina casi siempre en menos de una hora y como mucho en 24. `errored`, `canceled` y `expired` no cuestan nada y quedan anotados como tales; la pasada siguiente vuelve a preguntar en tiempo real si el reloj lo permite.

**Nunca se paga dos veces.** El `custom_id` es el hash (SHA-256, 48 caracteres) de propósito, versión del prompt, modelo, hash de la entrada, nivel, workspace (producción o LAB) y agente. La base de datos admite **un** elemento abierto por `custom_id` y **una** fila del libro por (lote, `custom_id`): no lo duplican dos ciclos, ni el reintento de un resultado a medio procesar, ni un lote seguido de una llamada en tiempo real.

**El dinero se reserva.** Un elemento abierto reserva su coste estimado en el presupuesto hasta que llega su resultado (los tokens de entrada de la petición más la salida típica del propósito, a mitad de precio), de modo que los lotes de un día no pueden pasar de su asignación.

**Si falla.** Un lote que no se puede crear (caída, petición rechazada, límite gastado) abandona sus elementos; el ciclo siguiente lo intenta otra vez, y tras 2 fallos de la misma tarea en 24 horas se pide en tiempo real. Una respuesta que llega con menos de 60 minutos de margen antes del partido se guarda (ya se pagó) pero queda marcada `late`. El pipeline cuantitativo nunca espera un lote: la revisión combinada es la de las reglas hasta que llega la del modelo, y entonces el ciclo siguiente combina las dos.

`FBI_AI_BATCH=0` detiene los lotes **nuevos**, nunca el cobro de los que ya se pagaron: `ai_batch_poll` recoge lo que haya abierto sea cual sea el interruptor. Se ejecuta cada `FBI_AI_BATCH_POLL_MINUTES` (por defecto 5).

## 7. El cambio material: cuándo se paga de nuevo un brief

Hasta la Fase 0 un brief solo se reutilizaba si su entrada era **idéntica byte a byte**: un precio que se movía un céntimo o una cifra del modelo que se refrescaba generaba un brief nuevo y de pago (el 24 oct 2026, 232 de 299 partidos tenían de dos a cuatro). Un brief es una lectura del **contexto** de un partido (quién juega, quién falta, qué dicen las noticias y el mercado), y el contexto cambia menos que el paquete. Con `FBI_AI_BRIEF_MATERIAL` en `auto`, un brief se paga de nuevo solo por lo que el plan llama material (`material-v1`):

* la alineación, una lesión o convocatoria, el entrenador;
* un precio que se mueve **más del 3 %** (también la probabilidad del modelo de un candidato), contado frente a lo que leyó el brief y no frente al último precio: una deriva de 1 % por hora reconstruye el brief cuando la suma pasa del 3 %;
* evidencia nueva, una contradicción entre fuentes, una noticia relevante;
* un cambio de hora del partido o una suspensión;
* un cambio del escenario competitivo;
* las selecciones sobre las que se pregunta (los candidatos), porque el brief escribe una nota por cada una.

Un movimiento del 2 % reutiliza el brief; uno del 4 % escribe uno nuevo. Un brief de más de 36 horas no se reutiliza por motivo material: el día para el que se escribió ya terminó. Con `FBI_AI_BRIEF_MATERIAL=0` se vuelve a reutilizar solo por hash idéntico, como antes. Nada de esto lee reloj, clave ni modelo, y no cambia ninguna probabilidad, umbral ni pick.

## 8. El libro de cuentas

La migración 0110 enseña a `ai.usage` qué es una escritura de caché, una llamada de Batch y un workspace. Las filas anteriores conservan NULL en lo nuevo:

| Columna | Qué guarda |
| --- | --- |
| `cache_write_tokens` | entrada escrita en la caché (se factura a 1,25 o 2 veces la entrada) |
| `cache_write_1h_tokens` | la parte escrita por 1 hora (el resto es la entrada de 5 minutos) |
| `cache_ttl` | `5m`, `1h` o `mixed` |
| `thinking_tokens` | tokens de razonamiento (se facturan como salida) |
| `batch_id`, `custom_id` | el lote (`ai.batches.id`) y la clave de idempotencia de la tarea; único por (lote, `custom_id`) |
| `workspace`, `key_label` | el **nombre** del workspace que pagó (`PREDIGOL`, `PREDIGOL-LAB`) y de la clave en la Console (`worker-prod`, `worker-lab`): nunca una clave |
| `run_id`, `agent` | reservados para la fase 1 (`ai.agent_runs`) |

`input_tokens` sigue siendo **toda** la entrada: los tokens frescos, los leídos de la caché y los escritos en ella. La vista `ai.usage_scoped` añade el tipo de dinero (`scope`): `exa` para toda búsqueda, `lab` para una llamada hecha con un workspace cuyo nombre acaba en `LAB`, y `production` para el resto, incluidas todas las filas anteriores a la 0110. Así el dinero de Claude y el de Exa nunca son un solo número.

## 9. El LAB: sondas y prueba de equivalencia

El LAB es el workspace `PREDIGOL-LAB` con su propia clave (`FBI_AI_KEY_ANTHROPIC_LAB`, que no es la de producción ni se lee desde producción) y su propio sobre. Cada llamada suya se anota con su workspace y el nombre de su clave. Lo que no se puede pagar lo dice y se detiene: nada corre a medias. Lo que puede esperar va por la ruta de Batch (a mitad de precio) y lo recoge el mismo `ai_batch_poll`; las sondas de caché y de esquema son de tiempo real.

**Sondas** (`python -m scripts.ia_probe`), que cuestan céntimos:

| Orden | Qué hace |
| --- | --- |
| `status` | qué falta (por nombre de variable) y en qué estado está cada gate; no llama a nadie |
| `cache` | dos llamadas idénticas por nivel: ¿la primera escribe y la segunda lee lo escrito? (tiempo real) |
| `schema` | la misma pregunta por llamada a herramienta y por salidas estructuradas (tiempo real) |
| `batch-submit` | el lote de sondas del día |
| `batch-collect` | toma los resultados y registra el gate `batch`, pase o no, con su evidencia (`--no-record` solo lo muestra) |

**Prueba de equivalencia** (`python -m scripts.ia_equivalence`): ¿pedir una revisión con salidas estructuradas, o con el bloque común del partido primero, cambia el veredicto más que pedir lo mismo dos veces? Se repiten revisiones que la capa ya hizo (el paquete y el candidato tal como eran) y cada una se pide **cuatro veces** en el LAB: dos como hoy (`A1`, `A2`), una con salidas estructuradas (`B`) y una con el bloque común primero (`C`). Nada de eso es una revisión, un pick ni un estado de producción. El experimento entero cuesta unos US$ 14 del sobre de 15 del LAB y se paga (o se rechaza) antes de la primera petición.

| Orden | Qué hace |
| --- | --- |
| `plan` | cuántas entradas, cuánto costaría y si el LAB puede pagarlo; no llama a nadie |
| `submit` | envía el experimento como **un** lote, todo o nada (el mismo día encuentra lo ya enviado) |
| `collect` | toma los resultados y, con todo cerrado, decide y registra los dos gates |
| `status` | el experimento más nuevo: peticiones abiertas y lo que dicen los gates |

La regla de cada gate está escrita antes de los datos (`lab.assess`, versión `equiv-v1`):

* **Cambio de veredicto**: sobre las entradas con sus tres veredictos válidos, las veces que la variante difiere de la primera llamada no pueden ser más que las veces que difiere la segunda llamada idéntica. El ruido de la propia repetición es la vara de medir.
* **Validez**: las respuestas inválidas de la variante, como mucho el 3 % y como mucho 1 punto por encima de las de las llamadas idénticas.
* **Tamaño**: al menos 200 entradas así. Con menos, el veredicto es `INSUFICIENTE`, nunca un pase.

El veredicto de cada variante es `PASA`, `NO PASA` o `INSUFICIENTE`. La evidencia guarda **las letras de cada entrada** (`A` aprobar, `D` degradar, `R` rechazar, `S` abstenerse, `-` inválida), de modo que cualquiera puede recalcular la decisión, y el Gate A lo hace. Una repetición que falla cierra un gate que una que pasó había abierto; cada intento es una fila de `ai.feature_gates`. Opciones de `ia_equivalence`: `--tier` (por defecto `analysis`: el gate nombra el modelo y otro no queda cubierto), `--inputs` (por defecto 210), `--since-days` (21), `--experiment`, `--no-record` y `--dsn`.

## 10. El Gate A: cuándo termina la Fase 0

«Un gate no se aprueba por esta frase»: el Gate A pasa solo con lo que el libro muestra sobre **7 días completos** del sistema real, con **una** sola configuración. Nada se simula y nada se da por pasado.

**La ventana.** Son los 7 días de Bogotá que terminaron ayer, todos posteriores al **ancla**: el día siguiente al más reciente de (a) el primer día en que el código de la fase 0 escribió el libro con un workspace, (b) el último cambio de un gate de optimización (`batch`, `native_schema`, `cache_layout`: una fila nueva que lo enciende o lo apaga) y (c) un cambio de configuración que quien despliega declara con `--changed-on` (un despliegue que cambia lo que hace la capa no deja fila propia; declararlo solo puede retrasar el gate). Un día en que cambió la configuración no cuenta como medida. Una optimización apagada a mano tampoco deja huella, y por eso los días tienen que *mostrar* las optimizaciones en el libro (comprobación de la caché).

**Las comprobaciones.** El informe trae once líneas: la ventana y diez comprobaciones, cada una con sus cifras. Una que no se puede juzgar queda en `PENDIENTE` y deja el veredicto pendiente, nunca aprobado.

| Comprobación | Umbral | De quién es |
| --- | --- | --- |
| `plans` | los 7 días de la ventana tienen su plan abierto (el de las 00:05) | plan |
| `cost_production` | la proyección mensual de producción es de 185 USD como máximo | plan |
| `cost_joint` | con la sombra al 30 % de un mes normal (US$ 51), 190 USD como máximo | plan (modelo de coste) |
| `cost_heavy` | en un mes pesado (+25 %), producción sola de 185 USD como máximo; el LAB cede lo que pase de 190 | plan |
| `coverage` | partidos informados, pasadas `first`, `pre` y `final` hechas y candidatos con revisión de modelo: cada uno como mucho 2 puntos por debajo de la línea base | plan («misma cobertura»); **los 2 puntos son míos** |
| `final_t15` | el veredicto final antes de T-15 en el 99 % de las pasadas `final` o más | plan (sección 32) |
| `verdict_equivalence` | cada optimización con su evidencia: `batch` su sonda; `native_schema` y `cache_layout` cambian como mucho tantos veredictos como repetir la llamada, con 200 paquetes o más, **recalculado** desde las letras guardadas | plan |
| `cache_visible` | lecturas de caché en 6 de los 7 días y, en tiempo real, el 40 % o más de lo cacheable leído | el 40 %: plan (alarma de la sección 28); **los 6 de 7 días: míos** |
| `batch_lost` | 0 resultados de lote perdidos y como mucho el 1 % de peticiones caducadas | plan |
| `manual_actions` | acciones 3, 5 y 7 hechas, comprobadas con datos | plan |

* **Coste.** El coste unitario de la ventana (US$ por partido con mercado, con las ejecuciones del analista incluidas) por los partidos con mercado del mes: los reales de los días pasados y los del calendario para los que faltan. La referencia es la línea base de los 7 días del 18 al 24 oct 2026 (5,17 USD al día de Claude). Si solo falla `cost_joint`, la sombra se planifica con menos muestra, nunca por debajo de la que da 300 selecciones en 30 días.
* **Cobertura.** Las dos partes se calculan con las mismas definiciones, la línea base sobre los 16 días del 9 al 24 oct 2026: de los partidos con mercado del plan **abierto** de cada día (las altas tardías no lo mueven), la parte informada (una pasada que terminó `ok` o `partial` con brief) y las partes con su pasada `first`, `pre` y `final` en `ok`; y, de los candidatos (las selecciones que recibieron una revisión), la parte con revisión de modelo.
* **Equivalencia.** Un `batch` con la sonda fallida deja Batch apagado y el coste juzga lo que queda. Una variante cuya evidencia más nueva dice `NO PASA` hace fallar la comprobación (su interruptor ya está apagado: se corrige y se mide otra vez). Con menos de 200 entradas, o sin evidencia, la comprobación queda pendiente.
* **Batch.** Con Batch encendido y ni una petición en la ventana, falla; con Batch apagado y ninguna, pasa.
* **Acciones manuales.** Se comprueban por **datos**: que el workspace del LAB respondió con su propia clave y que el servidor tiene la clave del LAB y los tres presupuestos (185, 15 y 35). Si no están hechas es `PENDIENTE` (es tuyo hacerlas), nunca un fallo del sistema.

**Los veredictos.**

| Veredicto | Cuándo | ¿Se registra? |
| --- | --- | --- |
| `PASA` | todas las comprobaciones salen sí | sí, en `ai.feature_gates` (gate `gate_a`, `decided_by` = `script`) |
| `NO PASA` | alguna sale no | sí |
| `PENDIENTE POR TIEMPO REAL` | menos de 7 días completos con la configuración estable | no |
| `PENDIENTE POR ACCIONES MANUALES` | falta evidencia o una acción tuya | no |

Un veredicto pendiente no es evidencia y no se registra. **Si no pasa**, el plan dice qué hacer: se revierte el interruptor que falle, se corrige y se repite la medición.

**Qué es del plan y qué es mío.** El plan fija los 7 días, los umbrales de coste, los 200 paquetes, el 99 %, el 40 %, el 1 % y los 0 perdidos. La ventana con ancla, la tolerancia de 2 puntos para «misma cobertura» y los 6 de 7 días de lectura son lecturas de ingeniería mías; el informe las marca como tales. Cambiar una es cambiar una constante de `gate_a.py`, y la prueba que ata este documento falla hasta que se corrige aquí.

**Comandos** (se ejecutan donde corre el worker, que tiene las variables que lee la comprobación de acciones manuales: solo nombres y números, nunca una clave):

```bash
python -m scripts.ia_gate evaluate                          # el veredicto de los 7 días que terminaron ayer; no escribe nada
python -m scripts.ia_gate evaluate --record                 # y añade un PASA o NO PASA a ai.feature_gates
python -m scripts.ia_gate evaluate --json                   # el informe entero, con las cifras de cada comprobación
python -m scripts.ia_gate evaluate --through 2026-11-03     # una ventana que terminó ese día, para mirar atrás; nunca se registra
python -m scripts.ia_gate evaluate --changed-on 2026-11-02  # un despliegue que cambió lo que hace la capa ese día (repetible)
python -m scripts.ia_gate revert batch --reason "caducan el 3 %"   # batch | native_schema | cache_layout
```

## 11. Conciliación mensual con la Console

Una vez al mes (acción 12) se exporta el CSV de la página Cost de la Console y se ejecuta en el servidor, donde está la base de datos:

```bash
python -m scripts.ia_reconcile --csv cost-oct.csv                           # un export con columna de workspace
python -m scripts.ia_reconcile --csv prod.csv=production --csv lab.csv=lab  # un export por workspace
python -m scripts.ia_reconcile --csv cost-oct.csv --month 2026-10           # el fichero trae varios meses
```

Compara el gasto de Claude en `ai.usage` (más las ejecuciones del analista, que paga el workspace de producción) con el CSV, **workspace por workspace y día por día** (días UTC, como la Console). Más de un 5 % de diferencia se investiga; una diferencia menor de US$ 0,50 es redondeo. Que el total coincida no basta: cada workspace se juzga por separado, para que el LAB no se esconda dentro de producción. Exa no tiene Console: se concilia con su factura. No escribe nada: el informe es JSON por la salida estándar, con el SHA-256 del CSV para rastrear la evidencia hasta el fichero.

`--cost-column`, `--date-column` y `--workspace-column` nombran una columna cuando la exportación usa un nombre que el script no conoce; `--cost-divisor 100` lee una cifra en céntimos; `--date-format` da un formato `strptime` para una fecha rara.

## 12. La vuelta atrás es real

Una vuelta atrás que exige borrar datos, o que choca con un esquema nuevo, no es una vuelta atrás. Aquí todo es aditivo: **el código de la versión anterior funciona sobre el esquema de la 0110**, y nada se borra.

| Qué quieres deshacer | Cómo | Qué se conserva |
| --- | --- | --- |
| La caché | `FBI_AI_CACHE=0` y reiniciar el worker | todo el libro; la caché solo cambia lo que se factura |
| El cambio material | `FBI_AI_BRIEF_MATERIAL=0` | los briefs escritos y su campo `material` |
| El presupuesto v3 | `FBI_AI_BUDGET_V3=0` (vuelve el presupuesto V2, intacto) | el libro con workspace y las alertas por sobre |
| Batch | `FBI_AI_BATCH=0`, o `ia_gate revert batch --reason ...` | los lotes ya pagados se siguen recogiendo |
| Salidas estructuradas | `FBI_AI_NATIVE_SCHEMA=0`, o `ia_gate revert native_schema --reason ...` | la evidencia de su gate |
| El bloque común del partido | `ia_gate revert cache_layout --reason ...`, o `FBI_AI_CACHE=0` | la evidencia de su gate |
| Toda la fase | desplegar la versión anterior | todas las tablas y columnas nuevas, sin borrar nada |

**Cómo se consiguió.** `ai.budget_alerts`, la tabla de alertas de presupuesto que ya existía, **no se toca**: ni sus columnas ni su restricción de unicidad por (mes, umbral). La alerta del mes de producción la escriben las dos generaciones de código con la misma sentencia, una sola vez. Las del LAB, las de Exa y las de la proyección de producción van a la tabla nueva `ai.envelope_alerts`, y la vista `ai.budget_alerts_all` lee las dos.

**Desviación respecto al texto del plan.** La sección 34 del plan decía que `ai.budget_alerts` «gana scope y kind». Ampliar esa tabla cambiaba su restricción de unicidad, y la versión anterior escribe sus alertas con `ON CONFLICT (month, threshold)`, una sentencia que falla si ya no existe una restricción exactamente sobre esas dos columnas: el primer aviso de umbral después de volver atrás habría dado error. Por eso la ampliación vive en una tabla nueva. Lo que el plan quería (alertas por sobre y por tipo, con una vista única) está entero; solo cambia dónde viven las filas.

**La prueba.** La versión de la que parte esta rama (`c6ed649`) pasó sus 3.157 pruebas unitarias y sus 1.954 de integración contra el esquema 0110 (25 oct 2026), y `tests/integration/test_rollback_compat.py` congela las sentencias de esa versión para que una migración futura no la rompa sin que una prueba lo diga.

## 13. Comandos y códigos de salida

Todos se ejecutan en el servidor, donde está la base de datos y el worker, con `python -m scripts.<nombre>`. Ninguno imprime una clave y los que llaman a Claude usan solo la del LAB.

| Comando | Para qué | 0 | 1 | 2 | 3 |
| --- | --- | --- | --- | --- | --- |
| `ia_probe` | sondas del LAB | hecho y bien | hecho y la sonda dice que no | no pudo correr (dice qué falta) o mal uso | resultados en camino: repetir `batch-collect` |
| `ia_equivalence` | prueba de equivalencia | hecho y los veredictos pasan | hecho y alguno no pasa | no pudo correr o mal uso | resultados en camino: repetir `collect` |
| `ia_gate` | el Gate A | `PASA` | `NO PASA` | no pudo correr: mal uso, o un día que no ha terminado | pendiente por tiempo real o por acciones manuales |
| `ia_reconcile` | conciliación mensual | el mes cuadra | difiere más de la tolerancia | CSV ilegible o base de datos inalcanzable | no hubo gasto en ninguno de los dos lados |

## 14. La migración 0110

Es aditiva y entra en una base viva (el worker sigue escribiendo el libro): las tablas ocupadas se bloquean **primero y juntas**, y una espera de más de 10 s hace fallar la migración entera (la lección de la 0076, 13 oct 2026), de modo que no queda nada a medias ni nada esperando detrás. Las tablas nuevas no llevan clave foránea hacia una tabla ocupada, por la misma razón.

* `ai.usage` gana las diez columnas de la sección 8, una restricción (`usage_cache_write_check`: lo escrito por 1 hora no puede pasar de lo escrito) y dos índices (`ai_usage_batch_once`, único por (lote, `custom_id`), y `ai_usage_custom`).
* La función `ai.scope_of` y la vista `ai.usage_scoped`.
* Las tablas `ai.batches` y `ai.batch_items` (la API de lotes, con **un** elemento abierto por `custom_id`), `ai.envelope_alerts`, `ai.feature_gates` y `ai.limit_hits`. Las tres últimas son de solo añadir: un disparador rechaza `UPDATE` y `DELETE`.
* La vista `ai.budget_alerts_all`.
* `ai.match_briefs` gana `material_hash` y `material` (y su índice `ai_match_briefs_material`).

## 15. Lo que falta para cerrar la Fase 0

1. **Desplegar** el paquete de la fase 0 (migración 0110, código y web) en la ventana de despliegue, con copia de seguridad y prueba de restauración justo antes de migrar. Lo hago yo cuando le toque a la IA en la cola de despliegues de los tres planes.
2. **Acciones 3, 5 y 7** (el workspace `PREDIGOL-LAB`, la clave `worker-lab`, la clave y los tres presupuestos en el servidor). Son tuyas; el detalle está en `IA_ACCIONES_MANUALES.md`.
3. **Las sondas y la prueba de equivalencia** (`ia_probe cache`, `schema`, `batch-submit`, `batch-collect`; `ia_equivalence submit`, `collect`). Las hago yo cuando existan las acciones 3, 5 y 7. Abren (o no) los gates `batch`, `native_schema` y `cache_layout`.
4. **Siete días completos** con la configuración estable. Es el reloj: no se acorta ni se simula.
5. **`ia_gate evaluate --record`**. `PASA` cierra la Fase 0 y habilita las fases 1 y 2 en producción (la 1 avanza antes, en paralelo con la medición, porque no toca el comportamiento). `NO PASA` aplica lo que dice la sección 10.
