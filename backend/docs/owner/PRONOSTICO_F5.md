# Pronóstico PrediGol: lo que se espera de un partido, aparte de lo que vale y de lo que se recomienda (Plan Maestro, fase F5)

**Qué es.** Hasta hoy un modelo solo podía hablarle a un usuario a través de un *candidato*: un pick nace de una selección que ya
pasó la regla de valor (un precio, una ventaja sobre el mercado y diez filtros). Un partido en el que los modelos estaban muy
seguros pero el precio era corto (un favorito a 1,30) no dejaba ninguna fila: el sistema no tenía dónde decir «esto es lo más
probable» sin que pareciera, o fuera, una recomendación. F5 separa tres cosas que estaban pegadas:

| | **Pronóstico** | **Valor** | **Pick** |
|---|---|---|---|
| Qué responde | ¿qué espera PrediGol que pase? | ¿está bien pagado? | ¿qué recomienda PrediGol? |
| Qué necesita | un modelo (y, solo para calibrar, un precio reciente del mercado) | el precio de una casa | pasar los diez filtros de la capa de decisión |
| Cómo se ve | «Local 61 % (entre 56 y 66)» | «a 2,10: ventaja +4 %» | congelado, inmutable, liquidado |
| Dónde vive | `models.match_forecasts` (nuevo) | `intel.decisions` | `picks.*` |
| Quién lo ve | **tú, y los usuarios solo si lo decides** (`FBI_FORECAST_USERS`) | solo la consola de administración | los usuarios |

Un ejemplo: un favorito a 1,30 al que el modelo da 74 %. Pronóstico: «Local 74 %». Valor: 0,74 × 1,30 − 1 = −3,8 %, así que no hay
ventaja, no hay candidato y no hay pick. Antes de F5 ese partido no dejaba rastro de la confianza del modelo; ahora el pronóstico
existe y, por construcción, no puede convertirse en pick. **F5 no cambia ningún modelo, calibrador, regla de valor, pick ni
liquidación, ni el modo SHADOW, y no muestra nada a ningún usuario hasta que tú lo decidas.**

## Qué escribe (y qué no)

Una migración, solo aditiva:

| Migración | Objeto | Para qué |
|---|---|---|
| **0086** | `models.match_forecasts` | Una fila por (partido, mercado, desenlace, línea) **en el instante en que PrediGol lo dijo** (`known_at`). Solo se añade: un disparador (`match_forecasts_append_only`) rechaza cambiar o borrar una fila, salvo una sesión de mantenimiento que lo declare (`fbi.models_maintenance = on`). |
| | `models.refuse_forecast_change()` | La función de ese disparador. |

Cada fila guarda: `p` (lo que PrediGol declara), `p_model` (la cifra cruda del modelo), `p_lo` y `p_hi` (el intervalo que el modelo
midió), `calibration` (`CALIBRATED` o `UNCALIBRATED`) y `basis` (por qué: `champion`, `no_champion`, `needs_price` o
`not_applicable`), `calibrator_id`, `p_market_used` y `market_as_of` (el consenso del mercado que usó un calibrador, si lo usó),
`model_name`, `model_version_id` y `data_cutoff_ts` (qué modelo y con qué datos) y `input_hash` con `code_version`. **Nunca lleva un
precio, una ventaja, una apuesta ni un estado:** eso es de la capa de decisión. Es una tabla *derivada* (sale de
`models.predictions` y de los calibradores): perderla pierde solo lo que se dijo y cuándo, no un dato del proveedor.

Reglas de escritura (`forecast-v1`, `fbi.forecasting.match_forecast`):

1. **Qué partidos:** los de los próximos 4 días con un modelo. Quedan fuera las competiciones cuyos datos no sirven para un modelo
   (`PRODUCT_ONLY`, `INSUFFICIENT`: la misma puerta que ya usa la capa de decisión) y los partidos en cuarentena; la API dice el motivo
   en vez de dejar un hueco.
2. **Qué mercados:** resultado (1X2), total de goles en 2,5 y ambos marcan: los que los modelos de goles valoran desde una sola
   matriz de marcadores y el modelo Elo para el resultado. Las demás familias (goles por mitad, córners, tarjetas) entran en F10
   añadiendo filas; la tabla ya guarda la familia.
3. **Qué modelo:** por mercado, el que usaría la capa de decisión: el campeón con menor pérdida logarítmica fuera de muestra
   entre los que valoran el mercado; si no hay campeón, el de mejor ajuste; si no, el primero por nombre. **Todos los desenlaces de
   un mercado salen de un mismo modelo y un mismo corte de datos**, así que suman 1.
4. **Cuándo se escribe una fila:** cuando el mercado es nuevo, cuando cambió el modelo, su versión o el calibrador, o cuando algún
   desenlace se movió al menos medio punto (0,005). Se escriben todos los desenlaces de un mercado juntos. La tabla es un registro de
   lo que PrediGol dijo y cuándo, no un latido. «Lo que PrediGol había dicho a la hora T» es la fila más reciente con `known_at ≤ T`
   de cada mercado.
5. **Un fallo en este paso no frena nada.** Corre dentro del pase de picks, en su propio punto de guardado; si falla, el pase sigue
   y el error queda anotado en la corrida (`match forecasts: <nombre del error>`).

## «Calibrada» y «Sin calibrar»: lo que hoy es cierto en producción

La calibración de PrediGol (`cal-logit2-v1`) encontró que los modelos están entre 10 y 15 puntos demasiado seguros en las selecciones
que marcan. Por eso un pronóstico se declara **Calibrado solo donde existe un calibrador CAMPEÓN** para ese mercado y modelo; en
todos los demás casos se declara la cifra del propio modelo, marcada «Sin calibrar», con la razón. Lo medido en producción (solo
lectura, 22 oct 2026):

| Mercado | Modelos | Calibrador | Qué dice el pronóstico |
|---|---|---|---|
| Más/Menos 2,5 | Dixon-Coles, Poisson | **Campeón** (`logit2`, desde el 19 y el 20 oct; 5.187 y 5.418 muestras; pérdida 0,623 y 0,621 contra 0,673 y 0,671 sin calibrar y 0,621 y 0,619 del mercado) | **Calibrada** si hay un consenso del mercado, sin margen, de hace 6 horas o menos; si no, «Sin calibrar» (`needs_price`) |
| Resultado (1X2) | Dixon-Coles, Poisson, Elo | Desafiante | «Sin calibrar» (`no_champion`) |
| Ambos marcan | Dixon-Coles, Poisson | Desafiante | «Sin calibrar» (`no_champion`) |
| Hándicap asiático y doble oportunidad | Dixon-Coles, Poisson | Desafiante | No se pronostican en F5 |

En lenguaje llano: de los tres mercados que F5 pronostica, **solo el total de goles puede salir calibrado**, y solo mientras haya un
precio fresco; el resultado y ambos marcan salen con la cifra del modelo y la etiqueta «Sin calibrar». Ningún modelo ha demostrado
todavía ventaja sobre el mercado (la validación de ventaja figura `NOT_VALIDATED` en todos), y la pérdida del total de goles calibrado
(0,623) está pegada a la del mercado (0,621), no por debajo: **un pronóstico dice qué cree PrediGol, no dónde apostar.**

La calibración de un pronóstico es una aproximación honesta, no una prueba: el calibrador se ajustó con las selecciones que los modelos
marcaron, no con todos los desenlaces, y aquí se aplica a cada desenlace y se reescala para que el mercado sume 1; el intervalo es el del
modelo pasado por la misma función. Por eso la tabla guarda la cifra cruda (`p_model`) y el consenso usado (`p_market_used`): cuando
haya resultados se puede medir cuánto acierta y si el ajuste se sostiene (F10 y la puerta final F14).

## Qué ve cada quien

* **Un usuario: nada, hasta que tú enciendas `FBI_FORECAST_USERS=1`.** La API contesta «no disponible» y la web no pinta ni un hueco.
* **Tú (SUPER_ADMIN) con el interruptor «Modo de evaluación (solo admin)» encendido:** en el Resumen de un partido, antes de que
  empiece, es el primer bloque, «Pronóstico PrediGol», con la insignia MODO EVALUACIÓN:
  * por mercado, la probabilidad de cada desenlace con su rango («entre 56 % y 66 %», o «sin rango medido» si el modelo no midió
    ninguno) y una barra, con **lo más probable** marcado;
  * «Calibrada» o «Sin calibrar» y, en una frase, por qué («Es la probabilidad del modelo tal cual: en este mercado todavía no hay
    una corrección comprobada»), el modelo (Poisson, Dixon-Coles, Elo) y cuándo se dijo;
  * junto a cada cifra, la **cuota justa** (1 ÷ probabilidad) y, si estaba calibrada, la cifra cruda del modelo;
  * plegado: «Valor y picks de este partido (solo administrador)» con lo que dijo la capa de decisión sobre el mismo partido (cuota,
    ventaja, valor esperado, estado) y los picks congelados. Si no hay precio evaluado o pick, lo dice con palabras
    («sin precio no hay valor», «un pronóstico, por seguro que sea, no lo es»).
  * No aparece con «Ver como USUARIO»: ahí ves lo que vería un usuario.
* **Un partido sin pronóstico** dice por qué en una frase (competición sin datos aptos, datos en revisión, o «todavía no hay»).
* **Si enciendes el interruptor para los usuarios**, ven el pronóstico **sin cuotas, sin ventaja, sin valor y sin picks**: las
  probabilidades, su rango, la etiqueta de calibración y el aviso fijo «Es una probabilidad, no una recomendación ni una cuota para
  apostar» con el pie «Un pronóstico dice qué es probable, no si está bien pagado… lo que PrediGol recomienda está en la pestaña Picks».
* **API:** `GET /api/v1/matches/{id}/forecast`; con `?preview=shadow` (solo SUPER_ADMIN; cualquier otro recibe 403) añade la cuota justa
  y, al lado, el valor y los picks del partido. Desde F10 añade un cuarto bloque, `families`, con lo que pronostican las familias (goles por
  mitad, córners, tarjetas y amarillas, versión `family-v1`): sin calibrar, sin intervalo y aparte del pronóstico de arriba, que sigue
  leyendo solo `forecast-v1`; para cualquier otra respuesta es `null`. Ninguna ruta de F5 calcula una probabilidad, llama a un modelo ni puede
  cambiar un pick.

## La IA y el pronóstico

Versiones nuevas (corren desde el despliegue de F5): **`packet-v6`**, **`brief-v7`**, **`narrative-v3`**, **`leak-audit-v4`**.

* `packet-v6`: el paquete de un partido lleva un bloque `forecast` (por mercado: modelo, calibración y motivo, cuándo se dijo, corte de
  datos y, por desenlace, `p`, `p_lo`, `p_hi` y cuál es el más probable) leído **a la hora del paquete** (la fila más reciente conocida
  para entonces). Es una probabilidad: el bloque no lleva cuotas ni nada que se lea como precio. Si la lectura falla, el paquete se
  construye igual y `forecast` figura entre los datos que faltan (la web lo dice: «Datos que aún no tenemos: pronóstico»).
* `brief-v7`: la IA puede citar el bloque (`P:forecast`, con las cifras verificadas contra el paquete) y lo primero que dice de
  «mercados interesantes» es qué espera PrediGol, en una frase, con los porcentajes copiados y «sin calibrar» donde corresponda.
  **Se le prohíbe presentar el pronóstico como un pick, como valor o como razón para apostar** y decir que un precio es bueno porque
  el desenlace es probable: lo más probable no es lo mejor pagado, y una tarjeta puede estar en un desenlace que no es el probable.
* `narrative-v3` (la narrativa por reglas, sin IA): antepone «PrediGol espera: Local (61 %); … Es una probabilidad, no un precio.» a las
  tarjetas de valor, y si no hay ninguna dice «Ningún mercado destaca frente al precio».
* La **revisión de picks** (el revisor LLM) también recibe el bloque como contexto: puede confirmar, bajar o rechazar un pick, **nunca
  subir una probabilidad ni crear uno**.
* **`leak-audit-v4`**, una regla nueva en la auditoría nocturna de fuga (probada con paquetes escritos a mano):
  * `forecast_known`: todo mercado del pronóstico que un paquete cita existe en `models.match_forecasts` (partido, versión, mercado,
    línea, momento y modelo), no es posterior al momento del paquete y era **el más reciente** entonces: un paquete que citara un
    pronóstico del futuro, uno que nunca existió, el de otro modelo o uno ya reemplazado queda marcado. Un paquete construido *antes* de
    que llegara una serie nueva no es obsoleto por eso.
* **Coste:** cambiar la versión del paquete hace que los partidos próximos se vuelvan a empaquetar y que la IA vuelva a resumir y a
  revisar lo que cambió, una vez. Eso queda dentro de los topes diarios de siempre (US$ 6 al día y 90 revisiones LLM al día; PrediGol
  Intelligence sigue en 180 US$ al mes y en modo SHADOW). Una nota de contexto: al desplegar F3 pasó lo mismo con `packet-v5`.

## Reglas que se respetan

1. **Un pronóstico no es un valor ni un pick.** Nada de la capa de decisión (`intel/`, salvo la auditoría de fuga), del motor de picks
   ni del dominio lee la tabla ni importa el módulo que la escribe. Una prueba de aislamiento
   (`tests/unit/test_forecast_isolation.py`) lleva la lista cerrada de archivos que la nombran (el escritor, la ficha del partido, el
   paquete de la IA, la auditoría de fuga, la herramienta de línea de órdenes) y del único archivo que importa el escritor (el pase de
   picks); un lector nuevo hace fallar la prueba hasta que alguien decida que puede leer. Se comprobó con una mutación: añadir la
   lectura en la capa de decisión la rompe.
2. **Un pronóstico caro de sostener se dice, no se maquilla:** sin campeón → «Sin calibrar»; campeón que necesita el mercado y el
   consenso tiene más de 6 horas (o no existe) → «Sin calibrar» con motivo `needs_price`; nunca se calibra contra un precio viejo.
3. **A fecha.** El pronóstico que se lee para un momento es el último con `known_at ≤ ese momento`; un *backtest* no es un pronóstico
   (las predicciones de una sesión de *backtest* no se leen).
4. **Sin modelo no hay pronóstico:** ni se inventa ni se rellena con otro mercado; la API lo dice con un código estable
   (`data_not_fit`, `quarantined`, `no_forecast_yet`).
5. **Solo se añade.** Lo dicho no se reescribe; lo nuevo es una fila nueva con su hora.

## Cómo corre

* **Worker:** un paso del pase de picks (`pick_pipeline`), después de los pronósticos de los modelos y antes de la capa de decisión;
  tiene la cadencia del propio pase y escribe solo la diferencia. Se apaga **sin desplegar** con `FBI_MATCH_FORECAST=0` en
  `/etc/predigol/app.env` y reiniciando el worker (la API, `FBI_FORECAST_USERS`, necesita su propio reinicio).
* **A mano, desde `backend/` (0 peticiones al proveedor; `write` es un ensayo en seco hasta `--apply`):**

```bash
python -m scripts.match_forecast status                       # filas, partidos con pronóstico, por día y por mercado/calibración/motivo, y los partidos próximos sin él
python -m scripts.match_forecast status --days 14 --list 25   # más días atrás; nombra hasta 25 partidos próximos sin pronóstico
python -m scripts.match_forecast show 45140                   # lo que PrediGol dijo de un partido, conjunto por conjunto, y cuándo
python -m scripts.match_forecast show 45140 --at 2026-10-23T09:00:00+00:00   # ... y lo que había dicho hasta esa hora
python -m scripts.match_forecast write                        # ensayo en seco: lo que escribiría un pase sobre los partidos próximos
python -m scripts.match_forecast write --apply                # el mismo paso del pase de picks, a mano (repetible --fixture N)
```

## Lo que se midió antes de estrenar (producción, solo lectura, 22 oct 2026)

| Medida | Resultado |
|---|---|
| Partidos próximos (4 días) | 647 |
| Partidos con cifras de los modelos de goles (Dixon-Coles y Poisson: 1X2, ambos marcan, total) | 647 de 647 |
| Partidos con cifras del modelo Elo (1X2) | 614 de 647 |
| Filas de predicción con intervalo | todas (7.137 de 7.137 en el 1X2) |
| Partidos próximos en competiciones sin datos aptos | unos 17 (sin pronóstico, con su motivo) |
| Calibradores campeones | 2 (total de goles, Dixon-Coles y Poisson); ningún otro mercado |
| Primera pasada (estimación) | unos 630 partidos × 7 desenlaces ≈ **4.400 filas**; después, solo lo que se mueva medio punto |
| Espacio (estimación) | ≈ 250 bytes por fila: la primera pasada ocupa ~1 MB; el crecimiento diario se mide la primera semana (`status`) |

## Resultado de la prueba general (23 oct 2026)

**La puerta de calidad.**

| Parte | Resultado |
|---|---|
| Backend | la batería completa pasa de 3.468 a **3.538 pruebas** (4 omitidas, como antes; 3 min 40 s); 68 son nuevas y están en seis archivos (el escritor, la API, el paquete de la IA y la auditoría de fuga, la herramienta de línea de órdenes y el aislamiento) |
| Tipos y estilo | `ruff` limpio; `mypy` estricto sobre 398 archivos limpio, y `mypy .` (887 archivos, pruebas y herramientas incluidas) limpio |
| Web | de 355 a **393 pruebas**; `eslint` sin errores; `tsc` limpio; la construcción de producción (`NITRO_PRESET=node-server VITE_DATA_MODE=live`) pasa |
| Migración | 0086 sube, baja y vuelve a subir sin dejar nada (`test_0086_adds_one_table_one_function_one_trigger_and_nothing_else_and_comes_back_out`); la batería de migraciones (reversibilidad de todas, ensayo en seco, roles de la base, guardas estructurales) pasa completa |
| Aislamiento | la capa de decisión, el motor de picks y el dominio no leen la tabla; verificado con una mutación (añadirle una lectura a la capa de decisión rompe la prueba) |

**Qué no se pudo ensayar con datos reales.** No hay una copia de la base de producción con los modelos en la nube y no se toca
producción para ensayar, así que el paso de escritura se probó en un mundo de pruebas sobre PostgreSQL 16 real, con las mismas
restricciones y disparadores, y se midieron en producción, solo leyendo, las cifras de arriba. **La primera pasada en producción es la
primera con datos reales:** por eso se mide enseguida con `scripts.match_forecast status` y `show`, no puede frenar el pase de picks y
se puede apagar sin desplegar.

## Resultado en producción (23 oct 2026)

**El despliegue.** Backend `bbfec85e70d4`, web `2f134b12be2a`, migración 0086, junto con F3.2. Copia de seguridad verificada y prueba de
restauración antes de tocar nada (01:23–01:42 UTC, pasó), más la copia propia del despliegue (`pre-deploy-bbfec85e70d4`, 02:35 UTC).
**El primer intento (01:42 UTC) se detuvo solo, sin daño:** la migración necesita un bloqueo breve sobre `core.fixtures` y otras tablas para
las claves foráneas de la tabla nueva, y el job de partidos (`fixtures_sync`, cada 6 h) mantenía abierta una transacción de unos 27 minutos
sobre ellas (la temporada «Friendlies Clubs», 8.359 partidos). Tras cinco intentos de 10 s la migración se rindió, la base quedó en 0085 y los
servicios en la imagen anterior. Se midió la causa (muestreo de bloqueos cada 3 s) y el segundo intento (02:35 UTC) comprobó antes de empezar
que ninguna transacción de escritura de más de 20 s estuviera sobre esas tablas: la migración se aplicó a las 02:43 UTC a la primera.

**Lo que se comprobó al terminar (solo lectura).**

| Comprobación | Resultado |
|---|---|
| Revisión de la base | 0086 |
| Tabla, función y disparador de solo-anexar | `t \| 1 \| t` (existen; un disparador) |
| Permisos | la API solo lee; el worker lee e inserta |
| Servicios | API, web y worker en la versión nueva, los tres «healthy»; caddy y postgres sin reiniciar |
| Prueba de humo | `/health` ok, `/login` 200, HSTS presente, `/auth/me` 401, `/docs` 404 |
| Salud del servidor | «warning» solo por el aviso de disco que ya existía (90 % en unos 25 días, +2.773 MB/día); ningún problema |
| Registros del worker y de la API (3 h) | 0 errores |
| Interruptores en los archivos de entorno | `FBI_FORECAST_USERS` y `FBI_MATCH_FORECAST` sin definir: el pronóstico se escribe y **los usuarios no lo ven** |
| Gasto de IA | 5,23 US$ y 331 llamadas el 22 oct, sin subida |

**La primera pasada con datos reales** (02:45–02:53 UTC, 8 min) escribió **4.417 filas en 1.893 conjuntos de mercado para 631 de los 648
partidos de los próximos 4 días**; los otros 17 son de competiciones sin datos aptos para modelos (no se pronostican, y la página lo dice). Es
lo que se midió antes de estrenar:

| Mercado | Modelo | Estado | Conjuntos |
|---|---|---|---|
| 1X2 | Elo (`elo_ologit`) 600, Poisson 31 | sin calibrar (no hay campeón) | 631 |
| Ambos marcan | Poisson | sin calibrar (no hay campeón) | 631 |
| Total de goles, línea 2,5 | Poisson | **calibrado** (hay campeón y un precio fresco) | 76 |
| Total de goles, línea 2,5 | Poisson | sin calibrar (falta un precio fresco del mercado) | 555 |

Un partido real (173728) lo ilustra: 1X2 local 74,5 % / empate 16,1 % / visitante 9,4 %; ambos marcan sí 56,4 %; más de 2,5 goles 69,7 %
calibrado (el modelo decía 72,6 %, el calibrador lo bajó); las probabilidades de cada mercado suman 100 %.

**Lo que se aprendió: el archivo del pronóstico estaba en un paquete de modelos.** La regla del 5 de octubre dice que cualquier cambio en
`models`, `features`, `predictions`, `backtesting` o `domain` es un modelo nuevo: se renueva la versión de todos. F5 había puesto su escritor
en `predictions/`, así que la huella del código de modelos pasó de `mc9a7bec97ca` a `mce0abbbb30d` y **la primera pasada volvió a escribir
una vez 92.937 pronósticos de los modelos bajo versiones nuevas** (8 min en vez de 6; ningún error, y el pronóstico de PrediGol salió como
diseñado). No cambió ningún número que ve un usuario ni ningún pick, pero no era lo que F5 prometía («no cambia ningún modelo»). Corregido con
la versión de F4: el escritor vive ahora en `fbi.forecasting`, fuera de los paquetes de modelos; la huella vuelve a `mc9a7bec97ca` (una
prueba la fija: un cambio en el código de modelos exige actualizar la huella en el mismo commit) y vuelven las versiones de antes sin otra
reescritura masiva. Lo escrito entre medias (92.937 pronósticos y las filas de `match_forecasts` de esas versiones) se queda: son registros
solo-anexar y siguen siendo ciertos. La migración 0086, ya aplicada, sigue nombrando en un comentario la ruta antigua (no se editan las
migraciones aplicadas).

## Verificación de los criterios del plan

| Criterio de «hecho» | Resultado | Prueba |
|---|---|---|
| Pronóstico, valor y pick son tres cosas distintas | sí: un pronóstico seguro a precio corto no crea decisión, candidato ni pick | `test_a_sure_forecast_at_a_short_price_creates_no_decision_candidate_or_pick`, `test_forecast_isolation` (3) |
| «Calibrada» solo con un calibrador campeón | sí; con campeón que necesita el mercado y sin precio fresco queda «Sin calibrar» | `test_a_champion_that_uses_the_market_makes_the_total_calibrated_and_the_rest_stays_as_it_is`, `test_a_champion_that_needs_a_price_does_not_calibrate_against_a_stale_one_or_none`, `test_a_calibrator_that_cannot_be_applied_is_not_dressed_up` |
| Un partido sin datos aptos no tiene pronóstico y dice por qué | sí | `test_a_competition_the_decision_layer_does_not_trust_gets_no_forecast`, `test_a_quarantined_match_gets_none_and_its_neighbour_does`, `test_a_match_without_a_forecast_says_why` |
| Lo dicho es lo que se sabía en ese momento | sí: nada posterior, y un *backtest* no es un pronóstico | `test_the_forecast_reads_what_was_known_at_the_moment_and_nothing_later`, `test_a_backtest_is_not_a_forecast`, `test_the_forecast_shown_is_the_newest_known_at_the_moment_asked` |
| La tabla es solo de añadir | sí | `test_a_forecast_is_never_rewritten_unless_a_maintenance_session_says_so`, `test_the_table_refuses_what_a_reader_could_not_mean` |
| La migración se deshace sola y no toca nada más | sí | `test_0086_adds_one_table_one_function_one_trigger_and_nothing_else_and_comes_back_out` |
| Un usuario no ve nada hasta que se decide, y luego sin precios | sí | `test_a_user_gets_nothing_until_the_owner_decides_and_then_only_the_forecast`, `ForecastBlock.test.tsx` |
| La IA lo cita sin convertirlo en pick; las cifras son las del paquete | sí | `test_a_claim_may_cite_the_forecast_and_its_numbers_are_the_packets`, `test_the_brief_is_told_the_likely_outcome_is_not_the_best_paid_one` |
| El paquete no leyó el futuro | sí: la auditoría nocturna lo comprueba | las pruebas de `forecast_known` en `test_forecast_in_the_packet.py` |
| Un fallo del paso no frena el pase de picks y se puede apagar sin desplegar | sí | `test_the_pipeline_writes_the_forecasts_in_a_step_of_its_own_and_a_defect_there_costs_nothing_else`, `test_the_pass_can_stop_writing_the_forecast_without_a_deploy` |

## Lo que se decidió distinto del plan (y los límites que conviene conocer)

* **Tres mercados en esta versión** (resultado, total de goles en 2,5 y ambos marcan). El plan fija que F5 no trae ningún modelo
  nuevo y que usa la probabilidad calibrada donde hay campeón y «sin calibrar» en el resto; por eso pronostica lo que los modelos de
  hoy ya valoran. Las familias nuevas (goles por mitad, córners, tarjetas) llegan con sus modelos en **F10**, que añade filas en este
  mismo bloque. El hándicap asiático y la doble oportunidad no entran: se pueden sumar más adelante como filas (el hándicap pide además
  enseñar la probabilidad de devolución).
* **No hay pronósticos retroactivos.** La tabla empieza el día del despliegue; lo que PrediGol «habría dicho» de partidos ya jugados es
  una pregunta de *backtest* (F10/F14), no un dato que se invente aquí.
* **La calibración de un pronóstico es una aproximación** (arriba): se rotula, se guarda la cifra cruda y se mide en cuanto haya
  resultados.
* **La revisión de picks sí ve el bloque** (lo aceptado): confirma, baja o rechaza, nunca sube una probabilidad.
* **El bloque se enseña solo antes del partido**: en vivo y después del partido lo que se compara con el resultado es de F7.
* **Si el modelo Elo firma el resultado, la web lo nombra «Elo (logit ordenado)»** (Poisson «Poisson (Maher)», Dixon-Coles
  «Dixon-Coles»); un modelo que se incorpore después se muestra con su nombre técnico hasta que se le ponga uno.
* **La web de la ficha ya nombra todo lo que puede faltar en el paquete** (pronóstico, contexto del partido, fase): antes «contexto» y
  «fase» saldrían como la clave cruda.

## Cómo estrenarlo en producción (y qué te aviso antes de cada paso)

1. Copia verificada y **prueba de restauración** antes de migrar (0086 es una tabla nueva, una función y un disparador; no toca nada
   existente).
2. `predigolctl deploy`: respaldo propio del despliegue, migración, permisos, reinicio y salud. Con la tabla vacía todo se comporta
   como antes; el bloque no se ve para ningún usuario.
3. La primera pasada del pase de picks escribe los pronósticos de los ~630 partidos; se comprueba con `scripts.match_forecast status`
   (filas, mercados, cuántos salen «Calibrada» y por qué los demás no) y `show` de un partido conocido.
4. Tú abres un partido con el «Modo de evaluación» encendido y ves el bloque. No hace falta nada más para que sea correcto.
5. Se vigila (abajo) y se anota aquí el «Resultado en producción».

## Cómo deshacerlo

* **Ocultarlo a los usuarios:** `FBI_FORECAST_USERS=0` (es el valor de fábrica) y reiniciar la API.
* **Dejar de escribir:** `FBI_MATCH_FORECAST=0` y reiniciar el worker; lo escrito se queda donde está.
* **Quitarlo todo:** `predigolctl rollback` a la versión anterior del código y `alembic downgrade 0085`, que borra la tabla, la función y
  el disparador. Lo único que se pierde es el registro de lo que PrediGol dijo y cuándo (se puede rehacer hacia delante, no hacia
  atrás), así que antes se hace la copia de despliegue habitual. `packet-v6`, `brief-v7`, `narrative-v3` y `leak-audit-v4` vuelven con
  el código; los paquetes ya escritos (`ai.match_packets`) solo se añaden y no se tocan.

## Lo que decides tú

* **¿Los usuarios ven el pronóstico?** Es la decisión central de F5 y no la tomé. Opciones: (a) **no, por ahora** (lo que queda al
  desplegar); (b) **sí, tal como está** (todos los mercados, con «Sin calibrar» donde corresponda); (c) **sí, pero solo lo calibrado**
  (hoy, el total de goles con un precio fresco), que pide un cambio pequeño antes de encender. Con lo medido (arriba) mi sugerencia es
  empezar por (a) y mirar una o dos semanas de `status` antes de decidir, pero es tu producto y tu riesgo.
* **¿Se muestra también en vivo y después del partido?** Hoy solo antes del partido.
* **¿Ocultar a los usuarios las competiciones sin modelo en vez de decir que no se pronostican?** Con el interruptor encendido, un
  usuario que abre un partido de una competición sin datos aptos vería «PrediGol no pronostica esta competición…».
* Nada más de F5 pide una decisión tuya.

## Lo que queda vigilado tras desplegar

1. `scripts.match_forecast status`: filas por día, partidos con pronóstico frente a los próximos, el reparto
   Calibrada/Sin calibrar y por qué (un total de goles que casi nunca sale calibrado delataría que el consenso del mercado llega tarde).
2. Que el paso no falle: las corridas del pase de picks no deben traer `match forecasts: …` en las notas.
3. La auditoría nocturna de fuga con `forecast_known`: `checked` sube con los paquetes que citan el bloque y `violations` queda en 0.
   *Primera lectura (23 oct, auditoría de las 12:50 UTC sobre el día 22):* revisó 1.281 conjuntos citados y marcó **4, todos O/U 2,5 `poisson`**.
   No es futuro filtrado: la regla marca también el paquete que leyó un pronóstico **más antiguo** que otro que ya existía a su hora, y aquí
   `pick_pipeline` sella el `known_at` del conjunto al empezar su pasada y lo confirma unos minutos después, justo cuando los paquetes se
   construyen (a los :06 y :36 de cada hora): el paquete leyó el conjunto anterior, que era el confirmado, y la regla vio después el nuevo con
   un sello anterior al momento del paquete. Dos arreglos posibles, sin urgencia: sellar `known_at` al confirmar la transacción, o que la
   regla (y el paquete) cuenten solo lo confirmado. Hasta entonces, cuatro marcas de este tipo al día no son una violación real; otra causa sí.
4. El gasto de IA de los primeros días con `packet-v6` y `brief-v7` frente al de antes (US$ 6 al día es el tope).
5. El tamaño de `models.match_forecasts` la primera semana (la estimación de arriba se confirma o se corrige).
