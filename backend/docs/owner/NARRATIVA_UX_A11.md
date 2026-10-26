# A11 · Narrativa ES/EN con IA, validada y con presupuesto propio

Plan Maestro UX, fase A11. **Nace apagada y sin gastar nada.** El código, la migración y las pruebas están listos; la narrativa solo
escribe cuando tú apruebas su presupuesto (**P8**: 30 US$ al mes) y alguien pone dos líneas en el servidor, y los lectores solo la
ven cuando la enciendes después de revisar una muestra. Sin eso, todo sigue como en A9: la lectura estructurada, sin IA.

La capa de usuario consume la inteligencia y no la altera: la narrativa se escribe **a partir de la lectura estructurada que ya ve el
lector** y de las noticias verificadas del partido; no cambia prompts, umbrales, decisiones, picks, liquidación ni el paquete de
PrediGol Intelligence, y nada de Intelligence lee lo que escribe (lo vigilan pruebas estáticas y de base de datos).

## 1. Qué ve el cliente

**Centro de partido, sección Análisis**, cuando hay una narrativa validada para la lectura de ese momento:

- Los seis apartados del plan (Resumen, Contexto, Datos, Mercado, Riesgos, Conclusión de PrediGol) escritos como texto, en el idioma
  de la página (español o inglés: los dos se escriben en la misma pasada y dicen lo mismo).
- Rótulos: «Redactado con IA y validado contra los datos de PrediGol» y «Escrito con datos de las 12:30» (la hora del paquete del que
  sale). En inglés: «Written with AI and checked against PrediGol's data» y «Written with data as of 12:30».
- **La conclusión arriba**, nunca plegada, con su advertencia de siempre («Es una probabilidad, no una recomendación…»). Los demás
  apartados se pliegan bajo su título (filas de 44 px): en el teléfono solo el Resumen queda abierto; en una pantalla de tableta o
  mayor, todos abiertos.
- **Sin narrativa** (apagada, rechazada por los controles, o escrita para otra lectura): la lectura estructurada de A9, igual que hoy,
  con «Lectura automática con los datos de PrediGol». Nunca un texto que el servidor no validó.

**Noticias** (A10), cuando la narrativa está encendida: cada tarjeta puede llevar su **titular propio** (hasta 80 caracteres, en
español y en inglés; nunca en una contradicción, que tomaría partido) y, en inglés, el **resumen traducido**, sin el rótulo «(in
Spanish)». Lo que no se tradujo sigue en español con su rótulo. El Resumen del partido (arriba) sigue mostrando los hechos de A9.

## 2. Cómo se escribe

- **Trabajo `user_narrative` del worker**, cada 10 minutos (`FBI_USER_NARRATIVE_MINUTES`), solo si el interruptor no está apagado.
- **Qué partidos:** los que PrediGol Intelligence dio por terminados en su **pasada final** (100 a 10 minutos antes del saque) y que
  tienen mercado; mientras no hayan pasado dos horas del saque. Analizar una vez y leer muchas: **ninguna visita llama a la IA**.
- **Qué recibe la IA:** los hechos de la lectura estructurada **tal como los ve el lector** (calculados con el mismo código de la API:
  mismo paquete, el pronóstico que un lector puede ver; nunca las probabilidades propias de los modelos, el Elo, las cuotas, las casas
  ni un pick) y las noticias de la web del paquete (su resumen, su estado y el nivel de la fuente). Nunca nada de un cliente.
- **Una llamada JSON** con el prompt `user-narrative-v1` al modelo económico (Haiku 5.5), español e inglés juntos, una referencia en
  cada frase (`P:<bloque>` para un hecho de la lectura, `E:<id>` para una noticia) y la traducción de las noticias en la misma pasada.
- Una lectura que ya tuvo respuesta (validada o rechazada) **no se paga dos veces**. Si después de la pasada final llega un paquete
  nuevo que cambia la lectura, se escribe otra (como mucho 3 intentos por partido y día).

## 3. Qué se comprueba antes de enseñar una frase

Frase por frase y en los dos idiomas (`fbi.narrative.job.validate`, pruebas en `tests/unit/test_user_narrative.py`):

| Control | Qué refuerza |
| --- | --- |
| Referencias | Cada frase cita al menos un hecho o una noticia que se le dio; nunca una referencia inventada |
| Cifras | Cada número está en los hechos o las noticias **que esa frase cita** (una probabilidad puede escribirse como porcentaje, redondeada como se muestre); también los números pequeños y los escritos con letra («cuatro»), y un valor por debajo de 1 nunca se escribe como «1» |
| Frases prohibidas | Sin certezas ni garantías («seguro», «fijo», «garantizado», «sin duda», «asegurar», «ganará»; «sure», «guaranteed», «will win»…), sin palabras de apuesta ni consejo («apuesta», «valor», «pick», «stake», «bet», «value»…) y sin códigos del sistema (`1X2`, `CONFIRMED`, `home_win`, `P:`), enlaces ni marcas |
| Un factor descriptivo no es una causa | El cara a cara, los escenarios de tabla, la táctica, el descanso y el calendario describen el partido: la conclusión nunca los cita y una frase que los cita nunca dice «porque», «por eso», «debido a», «gracias a», «favorece», «because», «due to»… (la regla del brief de Intelligence, leída, no cambiada) |
| Noticias | Una confirmada se cuenta como hecho; una probable se atribuye («según…»); un rumor o una contradicción solo en Riesgos y llamada por su nombre |
| Pronóstico sin calibrar | Una probabilidad propia del modelo va con su rótulo («sin calibrar» / «uncalibrated») |
| La conclusión | Se apoya en el pronóstico de PrediGol y nunca nombra el lado contrario al que el pronóstico da como más probable (ni el otro lado de la línea de goles) |
| ES = EN | Mismo número de frases por apartado y, frase a frase, las mismas referencias y las mismas cifras |
| Apartados | Los de la lectura y solo esos; Riesgos nunca vacío; como mucho 3 o 4 frases por apartado |

**Una frase mal y la narrativa no se enseña:** se pide una vez más, diciendo qué falló; si vuelve a fallar, el lector ve la lectura
estructurada y el rechazo queda registrado con sus motivos (`ai.user_narratives.status = rejected`). Cada traducción se comprueba sola
(sus cifras deben estar en el resumen original, nunca repite el titular de la fuente, la inglesa no puede ser el español) y se guarda o
se descarta sola.

**Atada a su lectura:** la API enseña una narrativa solo si se escribió con el **mismo paquete** y los **mismos hechos** que la lectura
de ese momento (`reading_hash`). Si la lectura cambia (llega otro paquete, cambia el pronóstico), el lector ve los hechos hasta que se
escriba la nueva: la narrativa nunca contradice lo que el lector tiene al lado.

## 4. Presupuesto aparte del de Intelligence

- `FBI_AI_USER_MONTHLY_BUDGET_USD`: el tope del mes de la IA de lectores. **Ausente o 0 = no gasta nada** (así nace). P8 lo pone en 30.
- Cada llamada se registra en `ai.user_usage` con `UserUsageLedger`, una subclase de `UsageLedger` (`fbi/ai/user_budget.py`); `ai/usage.py`
  **no se tocó**. Como `SPENT_SQL` de Intelligence solo suma `ai.usage` y `analytics.ai_runs`, este gasto **nunca reduce el de
  Intelligence**: lo prueba una prueba de integración (el estado del presupuesto de Intelligence es idéntico con y sin 25 US$ de gasto de
  lectores) y otra comprueba que una pasada del trabajo no escribe ni una fila en `ai.usage`.
- La narrativa solo llama si **los dos** presupuestos lo permiten: el de lectores (estado con `state_of`, el mismo cálculo de Intelligence:
  el ritmo del mes por día y un tope diario de 1,5 veces, día y mes de Bogotá) y el de Intelligence (que `call_json` sigue consultando).
- **Avisos `ai_user_budget`** al cruzar el 50, 70, 85, 95 y 100 % del mes, una vez cada uno, por tu canal de avisos: importes y el enlace a
  la consola, nada de un lector.
- **La consola de IA** (Costes) muestra una tarjeta «IA de lectores (narrativa)»: el interruptor, su presupuesto (tope, gastado hoy y en
  el mes, estado) y lo de hoy (narrativas validadas, no mostradas, noticias traducidas). P8 se verifica ahí.

**Coste estimado:** en la línea base de Intelligence (9–24 oct) hubo unas 112 pasadas finales al día con mercado. Con los precios de
Haiku 5.5 (0,10 / 0,50 US$ por millón de tokens de entrada / salida) y unos 5.000 tokens de entrada y 3.000 de salida por llamada, cada
narrativa cuesta ≈ 0,003 US$; con reintentos y relecturas, **≈ 11–17 US$ al mes** (estimación mía), por debajo del tope de 30. El plan
estimaba 18–30 con los precios de la auditoría. Si el tope se alcanza, la narrativa se detiene sola y los lectores ven la lectura
estructurada, que cuesta 0.

## 5. Interruptor

`FBI_USER_NARRATIVE` (lo leen el worker y la API al arrancar):

| Valor | Trabajo | Lectores | Consola (vista previa) |
| --- | --- | --- | --- |
| ausente, `0`, `off` o algo que no se entiende | no corre, no gasta | lectura estructurada | ve una narrativa si existe |
| `shadow` | escribe (si hay presupuesto) | lectura estructurada | ve la narrativa |
| `on` (o `1`) | escribe | **narrativa validada** y titulares/traducciones de noticias | ve la narrativa |

Cómo encenderla, cuando tú lo decidas: P8 → en `/etc/predigol/app.env` (fichero del plan de seguridad: copia fechada, candado de
despliegue, ventana propia) `FBI_AI_USER_MONTHLY_BUDGET_USD=30` y `FBI_USER_NARRATIVE=shadow` → recrear worker y API → revisar **50
narrativas** en la vista previa de la consola (el plan pide 0 cifras sin referencia) → `FBI_USER_NARRATIVE=on`. Para apagarla, `=0` (sin
desplegar) y la web vuelve a la lectura estructurada.

## 6. Aislamiento y privacidad

- **Nada de Intelligence lee lo de lectores:** una prueba estática impide que cualquier módulo de modelos, decisiones, picks, liquidación
  o del paquete de la IA nombre `ai.user_narratives`, `ai.evidence_translations` o `ai.user_usage`, o importe los módulos que las escriben
  (`tests/unit/test_user_layer_isolation.py`).
- **La narrativa no puede llegar a datos de clientes:** nada de lo que carga el trabajo nombra una tabla de `auth`, `customer` o los picks
  de un cliente, ni carga sus paquetes (otra prueba estática). Para lograrlo, `ApiError` (el rechazo de la API) vive ahora en
  `fbi/api/problem.py`, sin el código de cuentas; `fbi.api.errors` lo reexporta y todo lo anterior sigue igual.
- **La API no tiene claves de IA:** el trabajo corre en el worker; la API solo lee las narrativas guardadas.
- **Roles de base de datos:** el worker escribe las tres tablas (solo anexar por disparador) y la API solo las lee (`test_db_roles.py`).

## 7. Migración 0100

Tres tablas nuevas en `ai`, solo anexar con `ai.refuse_change()`: `ai.user_narratives` (el texto validado o por qué no), `ai.evidence_translations`
(titular y resumen traducido, atados al contenido inmutable de cada noticia) y `ai.user_usage` (el gasto de lectores). No toca ninguna
tabla existente y **no tiene claves foráneas hacia tablas que el worker escribe todo el rato** (`core.fixtures`, `ai.match_packets`,
`ai.evidence`): crear una bloquearía esa tabla en una base viva (la lección de la 0076 y de la 0110 de la IA). Espera máxima de 10 s por
bloqueos. **Bajada:** borra las tres tablas mientras no haya gasto real registrado (las narrativas se vuelven a escribir); con gasto, se
niega, porque olvidar el gasto del mes permitiría gastarlo otra vez: la vuelta atrás es el interruptor.

## 8. Decisiones que tomé (desviaciones deliberadas, escritas)

- **Numeración:** el plan dice 0099; en el repositorio la 0099 es la de A8 (la 0094 la tomó A1), así que A11 es la **0100**.
- **Dónde vive:** el trabajo está en `fbi/narrative/job.py`, no en `fbi/ai/user_narrative.py`: la regla de arquitectura impide que el paquete
  de Intelligence (`fbi.ai`) importe la capa de la API, y la narrativa **debe** leer la lectura con el código de la API para no decir más
  de lo que ve el lector. El presupuesto y su registrador sí viven junto a los de Intelligence (`fbi/ai/user_budget.py`).
- **La entrada es la lectura, no el paquete entero:** más estricto que «cada número está en el paquete»: el paquete tiene probabilidades
  de los modelos, el Elo y cuotas que un lector no debe ver. Las referencias `P:` son las de los hechos de la lectura
  (`P:forecast.1X2` para el pronóstico).
- **Interruptor de tres posiciones** (`off`, `shadow`, `on`): el plan pide revisar 50 narrativas **antes** de encender, y para eso tienen
  que escribirse sin que los lectores las vean.
- **La narrativa se ata a su lectura** (paquete y hash de los hechos) y cae a la estructurada si la lectura cambia.
- **Los avisos se deduplican en `audit.notifications`** (clave por mes y umbral): sin una cuarta tabla.
- **Titulares y traducciones solo con la narrativa encendida**, y nunca titular propio en una contradicción.
- **Una sola fila por intento, con su estado**: `ok`, `rejected` (respondió pero no pasó los controles), `invalid_output` (no siguió el
  esquema) o `failed` (el proveedor falló; se reintenta en la siguiente pasada). Sin presupuesto o sin modelo configurado no se escribe
  fila: se reintenta solo.

## 9. Calidad

- Antes de encender: **una muestra de 50 narrativas** revisada en la vista previa (0 cifras sin referencia).
- El primer mes: una muestra semanal; desde B6, los votos de «¿Te sirvió?»; desde B9, «Explícame» sobre el mismo texto.
- Criterio de terminado del plan: el 95 % de los partidos con mercado en la pasada final con narrativa validada en ES y EN **o caída
  limpia** a la estructurada; 0 cifras sin referencia en la muestra; gasto dentro del tope. Se mide con `ai.user_narratives` (estados por
  día) en cuanto esté en `shadow`.

## 10. Pruebas

| Prueba | Qué demuestra |
| --- | --- |
| `tests/unit/test_user_narrative.py` (56) | El validador: una narrativa buena pasa entera; cada control falla solo (referencias, cifras, números pequeños y con letra, certezas y apuestas en ES y EN, códigos, factor descriptivo, rumores, probables, sin calibrar, lado contrario, ES ≠ EN, apartados); las traducciones una a una; la entrada (sin la lista de traducción en su hash); el glosario cubre cada código de la lectura; el esquema sin límites numéricos; el interruptor; el presupuesto en 0 por defecto; los avisos una vez por umbral; el registro en el worker y el vigilante |
| `tests/integration/test_user_narrative.py` (7) | Narrativa validada guardada con sus traducciones y su coste en `ai.user_usage` (ni una fila en `ai.usage`), enseñada solo para su lectura (encendida, sombra, apagada, paquete nuevo); rechazada con sus motivos y nunca pagada otra vez; fallo del proveedor reintentado; nada sin presupuesto y los avisos una vez; el presupuesto de Intelligence idéntico; una pasada solo escribe las tablas de lectores; el registro del trabajo |
| `tests/integration/test_migration_0100_user_narratives.py` | Las tres tablas, lo que rechazan, solo anexar, la bajada sin gasto y su negativa con gasto |
| `test_user_layer_isolation.py`, `test_architecture.py`, `test_context_isolation.py`, `test_db_roles.py` | El aislamiento descrito arriba |
| Web: `ReadingBlock.test.tsx`, `news.test.tsx`, `AiCosts.test.tsx` | La narrativa en lugar de los hechos, sus rótulos, la conclusión primero, los plegables, el idioma; los titulares y traducciones de las noticias; la tarjeta de la IA de lectores en Costes («Sin presupuesto: no gasta» con 0, la barra del mes solo con presupuesto, ninguna tabla interna en su texto) |
| e2e `user.spec.ts` y `responsive.spec.ts` | Un partido con narrativa (ES y EN) y otro sin ella con sus hechos; las noticias traducidas; la narrativa a 320–430 px con filas de 44 px |

## 11. Despliegue y vuelta atrás

- Migración 0100: **copia de seguridad y prueba de restauración antes**, como en cada fase con migración.
- Se despliega **apagada y con presupuesto 0**: no gasta y nadie ve nada nuevo hasta P8, la muestra y tu decisión.
- Vuelta atrás sin desplegar: `FBI_USER_NARRATIVE=0`. Completa: la imagen anterior (el código anterior ignora las tablas nuevas).

## 12. Acción manual

**P8**: aprobar el presupuesto de la IA de lectores, **30 US$ al mes**, aparte del de Intelligence. Por la regla 13 de la coordinación no
te lo pido mientras otra tarea tuya del plan esté abierta (hoy P4). Después, las dos líneas del apartado 5 en el servidor (fichero del plan
de seguridad) y tu decisión de encender tras la muestra.

## 13. Puertas

| Puerta | Árbol | Resultado |
| --- | --- | --- |
| Backend: ruff, mypy estricto y del árbol entero, pytest | backend `acc53011` | Limpio; mypy 490 y 1.166 ficheros; **5.785 pruebas** (4 omitidas), 10 min |
| Web: lint, tipos (también los del e2e), pruebas, build de producción | web `29d418ce` | Lint 0 errores (los 26 avisos de antes); **831 pruebas**; build correcto |
| e2e completo con la narrativa encendida en QA (`fbi_qa_a11`, la `0100`; `seed_a11.py`: una narrativa validada, una rechazada y sus traducciones) | web `f157defa`, backend `acc53011` | **136 / 3 / 12** (26,7 min). Los tres fallos tenían una sola causa, real: la nota de la tarjeta de la IA de lectores en Costes nombraba la tabla `ai.user_usage` y la comprobación de página limpia la tomó por una clave sin traducir. Corregido en `e9bd3a64` (la tarjeta dice «Sin presupuesto: no gasta» con el presupuesto en 0, dibuja la barra del mes solo con presupuesto y tiene sus propios estados) con su prueba unitaria |
| e2e sobre el árbol final | web `29d418ce` | Los tres fallos repetidos: **3 / 3**. La consola y el móvil enteros: 56 / 5 / 2; los cinco fallos no eran del código: el servidor de desarrollo de la web de QA creció hasta el límite de memoria de la máquina de pruebas y el sistema cerró procesos (tres esperas del esqueleto de más de 20 s y dos «page crashed»; registrado en el núcleo como *out of memory*). Repetidos: **5 / 5** (el último con el servidor de desarrollo reiniciado) |
| e2e completo «como arranca producción» (el interruptor ausente: apagado; servidor de desarrollo reiniciado) | web `29d418ce`, backend `acc53011` | **137 / 2 / 12** (24,6 min): los lectores ven la lectura estructurada y las noticias sin traducir, y la tarjeta de Costes dice «Apagada». Los dos fallos, otra vez del límite de memoria (el sistema cerró dos procesos del navegador mientras corrían otras pruebas en la misma máquina), repetidos: **2 / 2** |
| Accesibilidad (axe) | | La narrativa a 1440 y 390 px: 0 reglas incumplidas |
| Gitleaks del rango de la rama (`ux/a10..ux/a11`) | | 0 hallazgos en sus 7 commits de código |
