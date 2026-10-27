# Fase 2 del Plan Maestro IA · El Servicio de investigación v2: una investigación por entidad y tema

Fecha: 26 oct 2026. Estado: **código terminado en la rama `ia/p2`; se despliega apagado y se enciende solo cuando pase el gate A** (la fase lleva las migraciones 0114 y 0115; por el orden del plan, sección 35, depende de la fase 1 y no del gate A, así que el código y las migraciones van ya, con `FBI_AI_RESEARCH_V2` sin definir). Fuente: Plan Maestro IA (aprobado), fase 2 y secciones 8, 24, 25, 30, 31 y 35.

Este documento dice lo que hace el código y **lo vigila una prueba** (`tests/unit/test_ia_fase2_docs.py`): si una cifra de aquí y una constante del código dejan de coincidir, la prueba falla hasta que se corrija una de las dos. Lo que es tuyo (claves, topes de la Console) está en `IA_ACCIONES_MANUALES.md`; la fase anterior, en `IA_FASE1.md`; el punto de partida medido, en `IA_BASELINE_F0.md`.

## 1. Qué es la Fase 2 y qué no toca

El objetivo del plan para esta fase es **una investigación por entidad y tema, compartida por partidos y agentes**. Hoy (v1) la IA investiga un *partido*: pregunta a la web por «A contra B», lee lo que vuelve para ese partido y escribe elementos atados a él; un equipo que juega dos veces en tres días se investiga dos veces, y una página que comparten dos partidos se lee dos veces. v2 guarda **una respuesta por equipo (o por partido) y tema** y deja que la lea cada partido y cada agente que la necesite mientras esté fresca. No es un agente que decide: el servidor escribe las consultas, un modelo pequeño solo extrae afirmaciones tipadas y el estado de cada evidencia lo decide el código.

| Pieza | Qué hace | Dónde está |
| --- | --- | --- |
| Caché por entidad y tema | una respuesta por (tipo de entidad, id, tema), la clave de una página sin el partido y la frescura de cada tema | `ai/cache.py` |
| Evidencias tipadas | cinco columnas nuevas en `ai.evidence`: qué afirma, sobre quién, de qué clase es la fuente y hasta cuándo se puede reutilizar | `ai/evidence.py`, migración `0114` |
| Extractor v2 | el prompt `extract-v2`, que contesta en `claim-v1` sobre sujetos que lista el servidor | `ai/extract_v2.py`, `ai/prompts.py`, `ai/agents/registry.py` |
| Investigación por entidad | el ciclo: una búsqueda por nivel para lo que no está fresco, una lectura de las páginas nuevas | `ai/entity_research.py`, `ai/collectors.py`, `ai/research.py`, `ai/cycle.py` |
| Interruptor y gate | `FBI_AI_RESEARCH_V2` y el gate `research_v2` | `ai/config.py`, `ai/gates.py`, `ai/gate_research.py`, migración `0115`, `ia_research_gate` |
| Lectores | los demás lectores de `ai.evidence` no ven lo tipado mientras v2 no esté encendido | `ai/packet.py`, `picks/daily.py`, `intel/decision.py` y otros siete (sección 5) |
| Consola | Operación → Trabajo de la IA → «Por entidad y tema» | `api/services/ai_research.py`, `web/src/live/TopicsLive.tsx` |
| Batería adversaria | el tercer objetivo, `claims`: 40 casos sobre `extract-v2` | `ai/battery/claims.py` |

**No toca**: probabilidades, calibradores, modelos estadísticos, umbrales, filtros, picks ni nada de lo que ve un usuario. Con `FBI_AI_RESEARCH_V2=off`, que es el valor de serie, el ciclo es exactamente el de antes. En `shadow` decide v1 y v2 solo cuenta. `FBI_AI_MODE` sigue en `shadow`. Todo es aditivo. La fase añade llamadas a un modelo (el extractor v2, de Haiku, que lee las mismas páginas que el de hoy) y por eso **no se enciende (`shadow`) hasta que pase el gate A**. Su código y sus migraciones se despliegan antes, **apagados**: con el valor de serie no hay ninguna llamada nueva a un modelo, ningún cambio de configuración que declarar ni nada que mueva el ancla del gate A; no confundir con el «research v2» de los pronósticos de la F10 del plan anterior, que es otra cosa y otros ficheros.

## 2. El interruptor y la vuelta atrás

`FBI_AI_RESEARCH_V2` tiene tres palabras (las mayúsculas y los espacios sobrantes no cuentan). **Cualquier otra, como `0`, `1`, `true` o un error de tecleo, es `off`**: solo `shadow` y `on` encienden algo. La palabra la lee el worker de su entorno, que en producción se fija al arrancar: un cambio en `app.env` rige cuando se reinicia.

| Palabra | Qué hace el ciclo | Qué lee el paquete |
| --- | --- | --- |
| `off` (de serie) | el ciclo de antes: v2 no existe | nada de v2 |
| `shadow` | v2 corre **después** de la investigación de v1, en la misma pasada (misma barrera, misma asignación de búsquedas); v1 decide y v2 solo cuenta; lo que escribe no lo lee nadie | nada de v2 |
| `on` | v1 deja de buscar en la web y v2 la sustituye; las afirmaciones de v2 entran en el paquete | las afirmaciones de v2 |

**`on` rige solo mientras la fila más nueva del gate `research_v2` diga que pasó** (`gates.research_mode`): sin esa fila, o después de una repetición que falla, `on` se comporta como `shadow` por sí solo. Un fallo de v2 no rompe nada: se deshace lo suyo, la pasada sigue con v1 (`v2_failed` en sus cuentas) y el ciclo queda `ok`; solo si v2 estaba sustituyendo a v1 el ciclo queda `partial` y la petición que no se pudo servir lo dice (`research_failed`).

| Qué quieres deshacer | Cómo | Qué se conserva |
| --- | --- | --- |
| Que v2 corra | `FBI_AI_RESEARCH_V2=off` (o `0`, o quitar la variable) y reiniciar el worker | todo lo que escribió: nadie lo lee |
| Que v2 sustituya a v1 | volver a `shadow` o a `off`; o una repetición del gate con `NO PASA`, que lo hace sola | lo mismo |
| La caché de v2 | no hace falta: sus claves (`rk-v2:`) no las lee v1 y las de v1 no las lee v2 | las filas, que caducan solas |
| Toda la fase | desplegar la versión anterior encima de la 0115 (sección 6) | tablas, columnas y filas: nada se borra |

## 3. Una investigación por entidad y tema

**La clave.** Una respuesta se guarda bajo `rk-v2:<tipo>:<id>:<tema>`, por ejemplo `rk-v2:team:42:availability` (el tipo, en minúsculas). Nunca lleva el partido: por eso la lee cualquier partido del equipo y cualquier agente. Los tipos de entidad que el código conoce son `TEAM`, `PLAYER`, `COACH`, `REFEREE`, `MATCH` y `COMPETITION`; hoy solo se guardan respuestas de equipos y de partidos (la tabla de abajo). Una página tiene su propia clave global, `rk-v2:url:<huella de su dirección>`, sin el partido: la dirección se normaliza antes (esquema y servidor en minúsculas, sin puerto por defecto, sin fragmento, sin parámetros de rastreo, sin barra final) para que dos formas de escribir la misma página sean una. Las claves de v1 son el resumen de una consulta o `<partido>:<url>`, así que las dos generaciones comparten tabla durante la semana de comparación sin leerse una a otra; lo único que comparten a propósito es la búsqueda de un partido entero, que es la misma consulta y por tanto la misma clave.

| Tema | Lo responde el nivel de la búsqueda escalonada | Sobre quién es | Qué busca |
| --- | --- | --- | --- |
| `availability` | 1 | cada equipo del partido | quién puede jugar: bajas, dudas, sanciones |
| `confirmation` | 2 | cada equipo del partido | confirmar con las palabras de los clubes y de la competición |
| `preview` | 3 | el partido | la previa de los medios internacionales |

El tema de una respuesta es el de la búsqueda que la encontró (un nivel al que se cae de reserva conserva el tema de su consulta). La previa es del partido y nadie la comparte.

**Cuánto vive una respuesta.** Lo dice su tema y el **próximo partido del equipo**, no el del partido que pregunta. Se juzga **al leer**, no al escribir:

| Cuándo | Se reutiliza durante |
| --- | --- |
| el próximo partido del equipo está a más de 12 horas | 24 horas |
| el próximo partido del equipo está dentro de las 12 horas | 4 horas |
| no se conoce ningún partido | las 24 horas |

Una respuesta encontrada un día antes del partido no es fresca para la pasada de las últimas doce horas: es el disparador que escribe el plan («pasada `pre` con la última búsqueda de más de 4 h»). **La frescura de v2 empieza igual que la de v1 para todos los temas.** Es una decisión mía y está declarada: la semana de comparación debe medir el cambio de clave y no un cambio de frescura. El plan dice que sus TTL son parámetros de partida y que cualquier ajuste se versiona; cuando esa semana dé evidencia, cada tema tendrá la suya.

**El ciclo**, para cada nivel de la búsqueda que pide la pasada (los mismos niveles que buscaría v1, `research.levels_for`):

1. Las entidades que el nivel cubre (los dos equipos, o el partido para la previa) se miran en la caché. Las que tienen respuesta fresca **no se buscan**.
2. Para las que faltan, **una sola búsqueda**: si faltan los dos equipos, la consulta del partido (la misma, y por tanto la misma clave de caché, que usa v1: si v1 la pagó hace un momento, v2 la lee y no la paga); si falta uno, la consulta de ese equipo solo; la previa, siempre sobre el partido.
3. El primer nivel cuya respuesta trae una fuente de peso conocido basta (la regla de v1: hasta un medio inclusive, los escalones 0 a 5 de `TIER_RANK`): no se baja al siguiente.
4. Las páginas encontradas, las más autoritativas primero y **nunca más de 6**, menos las que ya se leyeron para los mismos sujetos, van a **una sola llamada** del extractor; si alguna suena a una orden para un modelo, esa se lee **en una llamada aparte**, para que el modelo que lee las demás nunca la tenga delante (revisión independiente, H1). Una página leída se recuerda 7 días, con los sujetos para los que se leyó y sin el partido en su clave: otro partido que la encuentre no la vuelve a leer para ellos. Las que sobran del tope se cuentan aparte (`v2_pages_unread`).
5. Lo que queda en pie se guarda como evidencia tipada (sección 5) y la respuesta se recuerda por el tiempo que dice su tema.

**Lo que no cambia, y por eso puede correr al lado de v1.** Nunca busca más que los niveles que pide la pasada, una búsqueda por nivel como v1: el ahorro sale de las respuestas que guarda. Gasta como v1: las mismas guardas (una búsqueda y un modelo configurados, el presupuesto del día, el sobre propio de Exa), el mismo libro y las mismas cuentas (sus búsquedas pagadas van al libro bajo `rk-v2:<clave>` y sus lecturas bajo el agente `claim_extractor`). Falla abierto: una búsqueda que falla, un modelo caído o una respuesta que no es `claim-v1` se anotan y la pasada sigue. Un fallo del **transporte** (el modelo no contesta a tiempo, la red, un tope de gasto) deja las páginas sin leer, y se reintenta en la pasada siguiente sin coste de búsqueda. Un fallo de **contenido** (el modelo se niega, el proveedor no puede leer su respuesta, o la respuesta llega y no es `claim-v1`) no se reintenta, porque el plan lo prohíbe (solo se reintenta un fallo de transporte, nunca uno de contenido): sus páginas se dan por leídas, para que la pasada siguiente no pague otra vez la misma lectura (revisión independiente, M2). Se cuenta una sola vez, donde corresponde: una negativa o una respuesta ilegible ya están en el libro (`refused`, `invalid_output`); una respuesta que llegó y no es `claim-v1` está en el libro como `ok` (el proveedor contestó) y la cuenta la pasada (`v2_invalid`, que el gate suma a las respuestas inválidas del extractor). Una respuesta se recuerda solo después de leer sus páginas.

**Lo que cuenta cada pasada** (para la comparación): `v2_demand` (búsquedas que necesitó), `v2_paid` (las que pagó), `v2_shared` (las que respondió una búsqueda ya pagada por v1 o por una pasada anterior) y `v2_reused` (respuestas que seguían frescas: búsquedas que no hicieron falta), más las páginas, las afirmaciones y los fallos. Así el informe puede decir cuántas búsquedas habría pagado v2 **solo**.

## 4. El extractor v2 y `claim-v1`

**Qué lee el modelo.** Un solo JSON: el partido, la **lista de sujetos que escribe el servidor** (los dos equipos, el partido, la competición y los jugadores de los equipos que se investigan, hasta 30 por equipo: primero los que el proveedor da como ausentes, luego los de más minutos; el extractor nunca nombra a nadie, copia un id), y las páginas (`R1`…`R6`) con su título, su texto, su origen y sus marcas, **sin su dirección**. Todo lo que viene de fuera pasa antes por `ai/untrusted.py` (la sección 3 de `IA_FASE1.md`): se normaliza, se quitan el marcado y los enlaces y se corta, el texto de una página a 700 caracteres, su título a 160 y un nombre a 80, y un nombre que suena a una orden para un modelo se sustituye por `[name removed]`. Una respuesta no puede pasar de 4.000 tokens. El nombre del agente es `claim_extractor` (Haiku, escalón `bulk`) y su prompt `extract-v2`; en el registro nace CHALLENGER al lado del extractor de hoy (`replaces=extractor`) y solo lo sustituye una fila que firmas tú.

**Qué escribe.** Afirmaciones `claim-v1` (la sección 2 de `IA_FASE1.md`): la página, el sujeto (tipo e id de la lista), el tipo de afirmación, a qué partido se refiere (`THIS_MATCH`, `NEXT_MATCH`, `OTHER_MATCH` o `UNSPECIFIED`), una cita de la página de hasta 300 caracteres y, si la hay, la fecha. **Hasta 20 en toda la respuesta**, que cubre las páginas de una llamada (hasta 6): el tope es de la respuesta y no de cada página (hallazgo 10). Los tres límites que el esquema del contrato no puede llevar (la API no admite longitudes, cuentas ni formatos) cuestan **la afirmación que los rompe y no la respuesta**: una cita de más de 300 caracteres (`quote_too_long`), una fecha que no es un día real escrito año-mes-día (`invalid_date`) o una afirmación pasada la número 20 (`too_many`) se descartan y se cuentan, y las demás siguen en pie. Lo que sí rompe el esquema (un campo de más, un valor fuera de la lista cerrada, otro contrato) sigue descartando la respuesta entera.

**Qué se acepta.** `extract_v2.read` es una puerta de salida y no lanza nunca: la respuesta debe ser `claim-v1` (esquema cerrado), hablar de un sujeto que se listó, citar una página que se mostró y traer una **cita que está en esa página** (se ignoran los espacios y las mayúsculas). La cita tiene que ser una cita de verdad: de **10 caracteres y 2 palabras como mínimo** (una palabra suelta, «injured», está en toda página que hable de lesiones), **entera en una sola parte de la página** (el título o el texto, que el modelo lee por separado, nunca cosida entre las dos) y, si la afirmación es sobre un **jugador**, tiene que **nombrarlo**: alguna palabra de su nombre, sin acentos ni mayúsculas, y no solo su nombre. Una página que nunca lo nombra no puede ser la que dice algo de él, ni aunque otra página de la misma llamada ordene al modelo escribirlo (revisión independiente, H1). Una afirmación repetida cuenta una vez. Lo que no cumple se descarta y se cuenta con una palabra cerrada (`subject_not_listed`, `page_not_shown`, `quote_too_short`, `quote_not_in_page`, `quote_without_subject`, `duplicate`), nunca repitiendo su texto. Después, `to_evidence` decide si lo que queda es evidencia de este partido:

| Tipo de afirmación | Se acepta sobre | Se guarda como |
| --- | --- | --- |
| `OUT` | un jugador | lesión, «fuera» |
| `DOUBT` | un jugador | duda |
| `AVAILABLE` | un jugador | lesión, «disponible» (un jugador que vuelve) |
| `STARTER` | un jugador | alineación, «titular» |
| `SUSPENSION` | un jugador | sanción, «fuera» |
| `COACH` | un equipo | entrenador |
| `SCHEDULE` | un equipo, el partido o la competición | horario |
| `VENUE` | un equipo, el partido o la competición | sede |
| `OTHER` | cualquiera | noticia |

Quién puede jugar se dice de **un jugador**: «el equipo sin sus delanteros» no es un hecho sobre nadie a quien el servidor pueda nombrar, y una afirmación así se descarta y se cuenta (`type_not_for_subject`). Tampoco se guarda una afirmación sobre **otro partido** (el siguiente del equipo, o uno ya jugado: `other_match`), ni una cuya cita tenga menos de 5 caracteres (`quote_too_short`; la puerta de salida ya pide 10 caracteres y 2 palabras, y esta es la segunda guarda), ni la de un jugador cuyo equipo el servidor no conoce (`team_unknown`). Lo que se dice de un equipo o de un jugador sin partido (`UNSPECIFIED`) es lo que se sabe de él sea cual sea el partido que pregunte: se guarda sin partido y lo lee el próximo partido del equipo. La fecha es la que trae la búsqueda y, si falta, la que leyó el extractor: nunca la de hoy.

**Lo que una página todavía puede hacer**: decir algo falso en una cita que de verdad está en ella. Esa afirmación vale lo que vale su fuente, y una página que suena a una orden para un modelo vale como una fuente desconocida (sección 5) y se lee en una llamada aparte (sección 3).

## 5. Evidencias tipadas: estados, clases de fuente y quién las lee

Cada afirmación que queda en pie es una fila de `ai.evidence` con cinco campos nuevos: `claim_type` (los nueve tipos de arriba), `subject_type` y `subject_id` (sobre quién), `source_class` (la clase de la fuente) y `fresh_until` (hasta cuándo se puede reutilizar sin preguntar de nuevo). Un tipo se pone al escribir y **nunca después**: la base lo impone (sección 6). La misma afirmación leída dos veces se guarda una, y la frescura de una lectura no forma parte de lo que la afirmación dice.

**El estado lo decide el servidor, nunca un modelo**, con las reglas de siempre de `ai/evidence.py`:

| Estado | Cuándo |
| --- | --- |
| `CONFIRMED` | una fuente oficial (federación, competición o club) con fecha; la alineación confirmada del proveedor; o dos medios o periodistas independientes que dicen lo mismo |
| `PROBABLE` | un medio o un periodista solos, o una fuente oficial sin fecha; el informe de lesiones del proveedor |
| `RUMOR` | un agregador, una red social o un sitio que nadie clasificó, solos |
| `CONTRADICTORY` | dos informes opuestos sobre el mismo jugador, de fuentes de peso comparable, y nada más nuevo que los resuelva |
| `OUTDATED` | superada por algo más nuevo de igual o mayor peso; un informe de quién puede jugar de hace más de 10 días respecto al partido; o el jugador está en el once confirmado |

Un rumor nunca llega a `CONFIRMED`, por muchos agregadores o publicaciones que lo repitan; un informe más nuevo de peso igual o mayor deja al anterior en `OUTDATED`, y uno más débil por un solo escalón lo deja `CONTRADICTORY` si dice lo contrario; con dos escalones o más de distancia no se contradicen; un jugador en el once confirmado no está ausente. **Una página que suena a una orden para un modelo vale como fuente desconocida**: no cuenta como medio independiente, no sube a nadie, y, como vale lo que la última fuente de la escala, no puede dejar contradictorio ni viejo el informe honesto de un agregador o de algo mejor. Las afirmaciones tipadas se deciden sobre los últimos 21 días y **por persona** (equipo y jugador), no por partido: una afirmación sin partido («está lesionado») y otra de este partido («está disponible») sobre el mismo jugador son el mismo sujeto, así que se contradicen o se anulan como si fueran del mismo partido, y lo que el modelo diga que es su `applies_to` no decide si la regla se aplica. Se deciden **junto a** lo que dicen sobre quién juega el proveedor y v1 en ese partido, que se lee y nunca se escribe (un parte más nuevo del proveedor deja `OUTDATED` a una afirmación más vieja de la web, como entre los elementos de v1, y nada de lo que hace v2 mueve un estado de v1). Un once confirmado de su equipo, en cualquier partido, conocido después de leída la afirmación y con el jugador entre los titulares, deja `OUTDATED` para siempre a la afirmación sin partido que lo daba por ausente, sea cual sea el partido que se prepare. El estado de una historia sale de los informes que siguen vigentes (uno de hace más de 10 días no corrobora a uno de hoy) y los medios se cuentan por el dominio registrado que avala la dirección (`marca.com` y `amp.marca.com` son uno). Las que hablan de un equipo o de un jugador sin partido las lee también el siguiente partido del equipo.

**Clase de la fuente** (`source_class`, las palabras de `mcp-v1`). Es una etiqueta y no una regla: no cambia el estado de nada hasta que se mida el acierto de cada clase (plan, sección 8).

| Clase | Qué es | Lo máximo que alcanza sola |
| --- | --- | --- |
| `OFFICIAL` | federación, competición o club | `CONFIRMED`, con fecha |
| `PROVIDER` | el informe de lesiones del proveedor de datos | `PROBABLE` |
| `JOURNALIST` | un periodista | `PROBABLE` |
| `RELIABLE_MEDIA` | un medio de la lista de medios en los que confía el dueño | `PROBABLE` |
| `LOCAL_MEDIA` | un medio fuera de esa lista | `PROBABLE` |
| `AGGREGATOR` | estadísticas, apuestas, retransmisiones, páginas de aficionados | `RUMOR` |
| `SOCIAL` | una red social | `RUMOR` |
| `UNKNOWN` | un dominio que nadie clasificó | `RUMOR` |

La regla de los dos medios independientes (`CONFIRMED`) cuenta dominios del escalón de los medios y de los periodistas, sean `RELIABLE_MEDIA` o `LOCAL_MEDIA`: la clase es la etiqueta, el escalón es lo que la regla mira (hallazgo 11).

**Quién lee lo tipado.** En `off` y en `shadow`, **nadie**: ni el paquete, ni los picks del día, ni la decisión, ni la revisión del partido, ni el informe, ni el aprendizaje, ni los tres servicios de la Consola que enseñan evidencias, ni el script que repite paquetes (`ai_replay.py`). La tabla `ai.evidence` la leen trece módulos del código. Tres la leen a propósito, cada uno por su motivo: `ai/evidence.py` (decide los estados de lo de v1 y los de v2 por separado), `ai/gate_research.py` (la medida de la semana, que cuenta lo que encontró cada una) y `api/services/ai_research.py` (la pestaña de la Consola, que solo cuenta). Los otros diez filtran lo tipado con una sola pregunta (`subject_type IS NULL OR` lo que diga `gates.typed_visible`: v2 en `on` **y** la fila más nueva del gate en `PASA`), salvo en cuatro consultas por identificador que la prueba lista, cada una con su razón: tres leen algo que un paquete o una decisión ya citó (y mientras v2 no esté en `on` ningún paquete cita una afirmación suya) y la cuarta, la que evita guardar dos veces lo mismo, no encuentra nunca una afirmación de v2 para un elemento de v1. Una prueba estructural lee el código y falla si aparece un `FROM` o un `JOIN` nuevo de la tabla sin esa pregunta. Con `on`, el paquete enseña las afirmaciones tipadas, y no las que tienen más de 10 días.

## 6. Las migraciones 0114 y 0115

| Migración | Qué añade |
| --- | --- |
| `0114` | en `ai.evidence`, cinco columnas que admiten nulo (`claim_type`, `subject_type`, `subject_id`, `source_class`, `fresh_until`); tres llevan una restricción por vocabulario que nombra las palabras del código (nueve tipos de afirmación, seis tipos de sujeto, ocho clases de fuente) y el id del sujeto debe ser positivo; otra restricción obliga a que el tipo y el id del sujeto vayan juntos o no vayan, y un índice por sujeto sirve solo a las filas tipadas; el ámbito `entity` en `ai.research_cache`; y la guarda de inmutabilidad de la evidencia (`ai.evidence_guard`) aprende las cinco columnas: son contenido, y el contenido de una evidencia no cambia |
| `0115` | `research_v2` en la lista de gates de `ai.feature_gates` |

Las dos son **aditivas**: las columnas valen nulo para toda fila escrita antes y para lo que escribe el código anterior (que no las conoce), nada se copia, mueve ni reescribe, y las dos esperan como máximo 10 segundos un bloqueo. **Por qué se puede desplegar la versión anterior encima:** el código de antes escribe nulos en las columnas, la guarda solo añade reglas sobre ellas y el código de antes lee los gates que conoce. Bajar la 0115 con `alembic downgrade` devuelve la lista de gates a su valor anterior; bajar la 0114 hace lo mismo con la de ámbitos y **deja las columnas y la guarda como están** (quitarlas borraría el tipado de lo leído). Las dos listas vuelven sin validar lo ya escrito y ninguna fila se borra. Existen para el desarrollo; no son la vuelta atrás de producción, que es la sección 2.

**Cuánto bloquean.** Cada una corre en una sola transacción y, hasta que confirma, tiene un bloqueo exclusivo sobre las tablas que toca: `lock_timeout` acota la espera para conseguirlo, no el tiempo que se lo tiene. Por eso se midió antes de migrar (hallazgo M4 de la revisión, sección 11). El tamaño real, leído en solo lectura en producción el 27 oct 2026: `ai.evidence`, 10.456 filas y 14 MB; `ai.research_cache`, 4.375 filas y 5,2 MB. En una base de pruebas con filas generadas de ese número y de un ancho parecido (12 MB y 4,7 MB), tres veces seguidas, la 0114 tardó de 46 a 48 ms de principio a fin (con el arranque de `alembic` y la conexión) y el peor tirón que notó un lector concurrente de cualquiera de las dos tablas fue de 19 ms; la 0115, de 26 a 30 ms, con 5 ms de peor tirón. Con ese tamaño, partir la transacción (restricciones `NOT VALID` que se validan después, un índice `CONCURRENTLY` fuera de ella) añadiría riesgo y no quitaría nada; si las tablas crecieran órdenes de magnitud, se volvería a medir antes de otra migración sobre ellas.

## 7. La semana de comparación y el gate `research_v2`

El plan pide que v1 y v2 corran en paralelo **una semana** y que el gate (parte del B, plan, sección 24) exija «≥ 95 % de las evidencias de v1 con menos búsquedas». `ia_research_gate` lo mide con lo que hay en la base de datos y **no se aprueba por ninguna frase**.

**La ventana.** Los 7 días completos de Bogotá que terminaron ayer, y que sean días en los que **todas** las pasadas del ciclo corrieron en `shadow`: cada pasada apunta bajo qué investigación corrió (`research_v2_shadow` o `research_v2_on` en sus cuentas), así que un día sin pasadas, un día en que la palabra cambió, un despliegue reinició el worker con otra o v2 sustituyó a v1 no es un día de la medida. Con menos días completos el veredicto es **`PENDIENTE POR TIEMPO REAL`**: no se registra, no es evidencia, no se simula ni se estima. Un despliegue que alteró lo que hace v2 sin dejar una fila propia se declara con `--changed-on` y solo puede retrasar el gate.

| Comprobación | Qué exige | De quién es |
| --- | --- | --- |
| `window` | los 7 días completos con v2 en sombra en todas las pasadas | plan («una semana»), y mi lectura de «en paralelo» |
| `fewer_searches` | las búsquedas que v2 habría pagado **solo** (las que pagó más las que le respondió una caché, de v1 o de una pasada anterior) son estrictamente menos que las que pagó v1, en las pasadas en que las dos terminaron | plan; el modo de contar es mío y solo puede endurecerlo |
| `coverage` | v2 encontró al menos el 95 % de los hechos de v1 de los partidos de la ventana (un hecho es partido, lado, jugador y clase: quién falta, quién duda, quién juega, el entrenador, la alineación, el horario y la noticia) | plan («≥ 95 % de las evidencias de v1»); el hecho como unidad es mío |
| `coverage_players` | lo mismo, pedido solo a los hechos sobre quién puede jugar | mío: las bajas son lo que mueve una decisión, y un delantero ausente pesa lo mismo que una previa en el recuento general |
| `shadow_invisible` | ninguna revisión ni decisión de la ventana cita una afirmación de v2 (en sombra decide v1) | mío |
| `evidence_known` | la auditoría nocturna de fugas de datos halló 0 violaciones de la regla `evidence_known` en los días de la ventana (basta con que se hayan auditado 6 de los 7: la de la última noche puede no haber corrido todavía) | plan (la prueba `evidence_known` sin violaciones) |
| `sample` | se compararon al menos 30 partidos y 50 hechos de v1: un porcentaje sobre un puñado de hechos no dice nada | mío; solo puede retrasar el gate |

Una comprobación que no se puede juzgar (no hay datos) no es un pase: vale `None` y, mientras haya una, el veredicto queda pendiente aunque otra ya falle (el informe dice cuáles fallan ahora y que eso no es un veredicto). Con las siete juzgadas, si todas pasan es **`PASA`**; si falla alguna, **`NO PASA`** y el informe dice qué se hace (nada se cambia a mano: `on` se comporta como `shadow` mientras la fila más nueva no pase, y el plan manda corregir y comparar otra vez; si lo que falló es `shadow_invisible`, se pone `off` hasta corregir el lector que cita la afirmación y la semana vuelve a empezar). Solo `PASA` y `NO PASA` se escriben, y se escriben en `ai.feature_gates` (gate `research_v2`, solo se añade, con el resumen de la evidencia para poder reproducir el informe). **La fila más nueva manda.**

**Una vez en `on`, el gate ya no se vuelve a medir (hallazgo M3 de la revisión).** Bajo `on` cada pasada anota `research_v2_on` en sus cuentas y no `research_v2_shadow`, así que la ventana (todas las pasadas de los 7 días en sombra) no se completa mientras `on` rija: `evaluate` da `PENDIENTE POR TIEMPO REAL`, `--record` no escribe nada y un `PASA` ya registrado rige mientras sea la fila más nueva. Es consecuencia de medir a v2 contra lo que decide v1 (con `on` v1 ya no investiga) y se deja así, declarado. Para revalidar un `PASA` viejo (porque cambió el extractor, las fuentes o la temporada) se pone `shadow` otra vez (copia fechada de `app.env` y reinicio del worker, como para encenderlo) y se reúnen 7 días nuevos, en los que decide v1 como en la primera semana; solo un `NO PASA` registrado devuelve `on` a `shadow` por sí solo. Por la misma razón, `evidence_known` y `shadow_invisible` no pueden ver en sombra cómo se comporta lo tipado cuando se lee de verdad: esa parte solo se ve bajo `on`, y por eso el hallazgo H4 (sección 11) es condición para encenderlo.

```bash
python -m scripts.ia_research_gate evaluate                      # el veredicto de la ventana que terminó ayer (no escribe nada)
python -m scripts.ia_research_gate evaluate --record             # lo mismo, y un PASA o un NO PASA se añade a ai.feature_gates
python -m scripts.ia_research_gate evaluate --json               # el informe entero (cada comprobación con sus cifras) como JSON
python -m scripts.ia_research_gate evaluate --through 2026-11-10 # mirar atrás una ventana que terminó ese día (nunca se registra)
python -m scripts.ia_research_gate evaluate --changed-on 2026-11-02   # declarar un despliegue que cambió lo que hace v2 ese día (repetible)
```

Se ejecuta donde corre el worker; `--dsn` cambia la base. Registrar un `PASA` **no enciende nada**: `FBI_AI_RESEARCH_V2=on` es una palabra tuya y solo rige mientras la fila más nueva diga `PASA`.

| Código de salida | Qué significa |
| --- | --- |
| 0 | `PASA` |
| 1 | `NO PASA` |
| 2 | no pudo correr: mal uso de las opciones, un día que no está completo, o `--record` con `--through` |
| 3 | `PENDIENTE POR TIEMPO REAL` |

## 8. La Consola: Operación → Trabajo de la IA → «Por entidad y tema»

Es la pestaña donde se ve lo que hace v2, en español y en inglés, y **solo lee**: no busca, no llama a ningún modelo, no registra ningún veredicto y no cambia ningún interruptor. La alimenta `GET /api/v1/admin/ai/research/entities?days=N`, con `days` de 1 a 30 (7 por defecto). De arriba abajo, nueve secciones:

| Sección | Qué enseña |
| --- | --- |
| Qué mirar | ocho avisos, el más grave primero: una parte de la página que no se pudo calcular, pasadas en las que v2 falló, pasadas en las que se cortó (presupuesto o caída de la búsqueda), un interruptor encendido que ninguna pasada de la ventana ejecutó, un `on` retenido como `shadow` porque la puerta no ha pasado, afirmaciones leídas de páginas marcadas, páginas marcadas y filas de la caché de entidades que este código no sabe leer; si no hay ninguno, lo dice |
| Interruptor de la investigación v2 | lo que pediste (`off`, `shadow` o `on`), lo que hace el ciclo y por qué, si el sistema lee las afirmaciones de v2 o solo las mide, y los cinco últimos veredictos registrados de la puerta (decide el más reciente) |
| Puerta de la investigación v2 | la ventana (los días completos con v2 en `shadow`, desde cuándo y el primer día evaluable), cada una de las siete comprobaciones con su resultado, sus cifras y qué se revierte si falla (`FBI_AI_RESEARCH_V2`), y la consecuencia; mientras los 7 días no estén completos, la línea de «lo que falta» y una vista previa marcada como **no evidencia** |
| Investigación v1 frente a v2 | sobre la ventana de la página y las pasadas en que las dos terminaron: las búsquedas de v1 y las que v2 habría pagado sola, la reutilización, la cobertura de los hechos de v1 (en general y en los de quién puede jugar), los hechos por partido, el gasto de Exa de cada una y lo que contestó el extractor, con ejemplos de los hechos de v1 que v2 no encontró |
| Frescura por tema | cada tema con la regla de su frescura (lejos y cerca del saque, sección 3) y lo que la caché guarda de él: cuántas respuestas, cuántas siguen frescas, cuántas caducaron y cuántas veces se reutilizaron; las filas con una clave que este código no lee se cuentan aparte |
| Respuestas guardadas | las 60 más recientes de la ventana, por entidad y tema: el nivel de la búsqueda, los resultados por escalón de fuente y si alguno es de peso conocido, cuándo se buscó, si sigue fresca o caducó (juzgado ahora), cuántas veces se reutilizó y cuántas afirmaciones dejó |
| Afirmaciones por clase de fuente y estado | lo que v2 escribió en la ventana: cuántas, cuántas siguen vigentes, cuántas son de una entidad (las que lee también el próximo partido del equipo) y cuántas de un partido, y cuántas vienen de páginas marcadas; por estado, por clase de fuente y por tipo, con las clases que no produjeron ninguna |
| Día a día del ciclo | por día de Bogotá: las pasadas, las que corrieron v2, las que fallaron y las que se cortaron; las búsquedas de v1 y las que v2 necesitó, pagó, vio ya pagadas o se ahorró con una respuesta fresca; las páginas y las afirmaciones; el gasto de Exa de v1 y de v2 |
| Páginas leídas | las páginas que v2 recuerda (cuántas siguen vigentes y cuántas veces se reutilizaron) y, en la ventana, las que leyó el extractor, las ya conocidas, las que sobraron del tope de una lectura y las marcadas |

Las dos secciones que hacen más cuentas, la comparación y la puerta, se calculan cada una en su propio punto de guardado: si una falla, la página lo dice (`comparison_failed` o `gate_failed`, con la clase del error y nada más, porque un mensaje puede llevar un servidor o un usuario) y el resto se enseña; si ninguna pasada de la ventana corrió v2, la comparación dice que no hay nada que comparar (`no_v2_passes`). Las demás secciones leen cada una sus tablas. El dinero se suma en millonésimas de dólar, para que un total no se desvíe.

## 9. La batería adversaria sobre `extract-v2`

La regla de la batería (sección 12 de `IA_FASE1.md`) pide al menos 40 casos por cada prompt que lee texto ajeno. `extract-v2` es el tercero: lee las mismas tres páginas que el extractor de hoy, con los mismos hechos, pero **después de la puerta** de `ai/untrusted.py`, así que mide dos cosas a la vez: qué deja la puerta de un ataque (lo ve la capa determinista, sin modelo y sin coste) y si el modelo sigue lo que queda. Son 40 casos, 55 peticiones en la primera ronda (≈ US$ 0,01 de los 0,53 de la ronda entera), sobre tres bases (`c_injury`, `c_doubt` y `c_quiet`); un caso cambia una sola cosa: el texto de la tercera página, su título, el dominio de su dirección o el nombre de uno de los sujetos. Lo que se compara de una respuesta es lo que el servidor guardaría como evidencia de ese partido. **La batería real todavía no se ha lanzado**: necesita la clave y el sobre del LAB (tus acciones 5 y 7). La versión de la batería es `battery-v2`, y una medición hecha con `battery-v1` no habla de ella.

## 10. Lo que cuesta

El plan dice «Exa −10–20 % (estimado); Claude, igual». Dicho con cuidado, **la semana de comparación cuesta más que eso, no menos**, porque corren las dos investigaciones: v2 lee con su extractor las mismas páginas que ya leyó el de hoy y, cuando solo falta un equipo, paga la búsqueda de ese equipo solo, que v1 no hacía. Lo primero lo estima el plan en 30 llamadas de Haiku al día (≈ 0,02 USD al día); la línea base de la fase 0 midió el extractor de hoy en 569 llamadas y 0,39 USD en 16,2 días, lo mismo de orden. Lo segundo está acotado por las guardas de v1 (el presupuesto del día y el sobre de Exa de la acción 7). **Las cifras reales no son mías: las miden el libro (`ai.usage`, bajo `rk-v2:` y `claim_extractor`) y la pestaña de la sección 8**, que enseña las búsquedas que pagó cada una de las dos investigaciones, las que v2 habría pagado solo y el gasto de Exa de cada una. El ahorro de Exa solo existe si el gate lo mide (`fewer_searches`) y sin él `on` no rige.

## 11. Las pruebas y lo que se halló

**Qué prueba cada cosa.** El plan pide cinco pruebas para esta fase; cada una tiene su fichero, y una prueba de este documento (`tests/unit/test_ia_fase2_docs.py`) falla si alguno desaparece:

| Prueba que pide el plan | Dónde está |
| --- | --- |
| un equipo con dos partidos en 3 días busca una vez | `tests/integration/test_cache_v2.py` (`test_a_team_with_two_matches_in_three_days_is_searched_once`) y, sobre un mundo construido con el ciclo entero, `tests/integration/test_ai_research_entities.py` |
| dos fuentes enfrentadas quedan `CONTRADICTORY` | `tests/integration/test_evidence_entity.py` (`test_two_sources_of_comparable_standing_that_disagree_are_contradictory`) |
| un rumor nunca llega a `CONFIRMED` | `tests/integration/test_evidence_entity.py` (`test_a_rumour_never_reaches_confirmed_however_many_aggregators_and_posts_repeat_it`) |
| `evidence_known` sin violaciones | `tests/integration/test_ai_research_entities.py` (`test_what_the_pass_stored_was_known_when_it_was_retrieved`) y la comprobación `evidence_known` del gate (`tests/integration/test_gate_research.py`) |
| una inyección en la página no cambia la extracción | `tests/integration/test_ai_research_entities.py` (`test_an_injection_in_a_page_changes_nothing_of_what_stands`) y, con un modelo real, el objetivo `claims` de la batería (sección 9) |

Y el resto de lo que la fase construyó, fichero a fichero:

| Qué | Dónde está |
| --- | --- |
| la clave, la frescura y la dirección de una página | `tests/unit/test_cache_keys_v2.py`, `tests/integration/test_cache_v2.py` |
| las migraciones | `tests/integration/test_migration_0114.py`, `tests/integration/test_migration_0115.py` |
| las evidencias tipadas y sus estados | `tests/integration/test_evidence_typed.py`, `tests/integration/test_evidence_entity.py` |
| el extractor: lo que lee y lo que se acepta | `tests/unit/test_extract_v2.py`, `tests/unit/test_research_v2_queries.py` |
| la investigación por entidad | `tests/integration/test_ai_research_entities.py` |
| el interruptor y el ciclo | `tests/unit/test_ai_research_switch.py`, `tests/integration/test_research_mode.py`, `tests/integration/test_research_v2_cycle.py` |
| ninguna otra lectura ve lo tipado | `tests/unit/test_typed_evidence_guard.py`, `tests/integration/test_typed_evidence_readers.py` |
| el gate y su orden de línea de comandos | `tests/unit/test_gate_research_pure.py`, `tests/integration/test_gate_research.py`, `tests/integration/test_ia_research_gate_script.py` |
| la vista de la Consola, de la base al web | `tests/unit/test_ai_research_view.py`, `tests/integration/test_ai_research_service.py`, `tests/integration/test_ai_research_api.py`, `web/src/live/TopicsLive.test.tsx`, `web/src/live/topicsModel.test.ts` |
| la batería sobre `extract-v2` | `tests/unit/test_battery_claims.py` y las pruebas de la batería de la fase 1, ampliadas a tres objetivos |

**Calidad de las pruebas.** Que una prueba pase no basta (sección 15 de `IA_FASE1.md`): cada pieza con lógica propia se midió además estropeando el código a propósito, una condición, una constante o una comparación cada vez, y exigiendo que alguna prueba falle (mutaciones). Lo que sobrevivió o bien obligó a escribir una prueba nueva, o bien era un cambio que no altera lo que hace el código y así se anotó. El resultado, pieza a pieza, tal como lo dejó cada commit: la caché por entidad y la migración 0114 (64 pruebas: 50 + 7 + 7) aguantaron 41 alteraciones sin que sobreviviera ninguna; las evidencias tipadas (11 pruebas), 13 sin supervivientes; la investigación por entidad (19 pruebas de integración sobre un mundo construido, sin red ni clave), 17, todas cazadas; el gate (95 pruebas), 102, y las 28 que sobrevivieron a la primera ronda tienen ya su prueba; la vista de la Consola (93 pruebas: 54 unitarias, 33 de integración y 6 por HTTP), 84, todas cazadas. La pestaña web tiene 111 pruebas nuevas (48 sobre el modelo y 63 sobre la página, en los dos idiomas). La batería sobre `extract-v2` pasó por lo mismo: `ai/battery/claims.py` se estropeó de 148 maneras (125 las cazaron las primeras pruebas; de las 23 vivas, 22 se cerraron con 9 pruebas nuevas y una se anotó como cambio que no altera nada: el origen que se pasa a `sanitize` solo etiqueta lo que devuelve), la liquidación de su respuesta de 46, el gancho de su puerta en `offline` de 11, su sitio en `corpus` de 13 y `VERSION` y `TARGETS` de 3: 221 en total, 220 cazadas y 1 equivalente.

**Lo que no se midió así, o no dejó cifra:** las afirmaciones tipadas (66 pruebas unitarias de la conversión y 18 de integración sobre la base) y los lectores de `ai.evidence` (un barrido de comportamiento de 12 lectores, la guarda estructural y sus predicados) se midieron con mutaciones, pero el commit no guardó cuántas. De la frescura al leer, el registro del extractor, el mensaje que lee y la puerta de su respuesta, las consultas, el interruptor y el ciclo (18 pruebas de integración sobre todo el camino) hay pruebas, y ninguna cifra de alteraciones anotada. Y esta guía se midió igual: se alteraron 681 cosas suyas (una cifra, un nombre entre comillas invertidas, una palabra que da la vuelta a una frase o una fila de una tabla, una cada vez) y 530 las cazó una prueba a la primera; de las 151 que no, 128 se cerraron con comprobaciones nuevas (98 en una segunda vuelta y 30 en una tercera) y 23 siguen sin cazarse: 2 fechas (las de la cabecera), 13 cifras de lo que contó cada commit de su propio trabajo (cuántas pruebas y cuántas alteraciones) y 8 palabras de la prosa («cada», cinco veces; «todas cazadas», «no altera nada» y «hoy»). Es historia y texto, no afirmaciones sobre el código, y por eso no se fijaron. Una salvedad sobre la medida misma: el alterador solo toca cifras, nombres entre comillas invertidas, unas cuarenta palabras que dan la vuelta a una frase y filas de tablas; el resto de la prosa no se midió de esta manera.

**Resultado de la última pasada por las puertas** (26 oct 2026, sobre el código de esta rama): backend, 4.859 pruebas unitarias en verde y 6 que se saltan solas (4 de antes de esta fase, dos módulos sin código fuente que la guarda del pre-partido no puede leer, y 2 que necesitan el binario `caddy`, que el sandbox no trae: con el oficial, v2.10.0 y de huella comprobada, pasan, igual que las otras 9 de su archivo) y 2.968 de integración en verde; `ruff check .` sin avisos y `mypy` estricto sobre los paquetes del proyecto (496 archivos) y sobre el árbol entero (1.207 archivos, con las pruebas) sin errores. Web: `bun run lint` (0 errores y 26 avisos que ya estaban), `bun run typecheck` y `bun run test` en verde, 911 pruebas. Ninguna se ha saltado ni se ha relajado para que pase. Esa pasada halló además dos cosas, que se dicen como ocurrieron. Una: 18 avisos de tipos del árbol entero en pruebas de esta fase (comentarios `type: ignore` que no hacían falta, una llamada que repartía un diccionario de enteros sobre parámetros de otros tipos y la comparación de un entero con un decimal), corregidos en un commit aparte (7a32cce1) sin cambiar el sentido de ninguna comprobación. Otra: la primera pasada de integración dio 5 resultados malos en 4 pruebas (de test_db_roles, test_promotions_policy_0111 y test_referee_admin_api) que no eran de esta fase: esas pruebas borran y recrean los roles del clúster, y una base de ensayo de migraciones de un ensayo anterior, en el mismo clúster, tenía 363 objetos que dependían de un rol. Se guardó una copia de esa base, se sacó del clúster, esos tres archivos dieron 198 pruebas en verde y la suite entera, con el clúster limpio, las 2.968.

**Repetida el 27 oct 2026** sobre el código de la rama tras la decisión A del gate A y el arreglo de las salidas estructuradas: 4.877 pruebas unitarias en verde y las mismas 6 que se saltan solas, y 2.971 de integración en verde; `ruff check .` sin avisos y `mypy` estricto sobre los paquetes del proyecto (497 archivos) sin errores. En esa pasada, 18 pruebas de integración fallaron la primera vez y no eran del código: el clúster de pruebas de esa máquina tiene su zona horaria en America/Bogota y esas pruebas comparan fechas escritas en UTC; con la zona horaria de la sesión de la base puesta en UTC (la variable PGTZ), que es lo que esperan, las 2.971 pasan (los cuatro archivos que fallaban dieron 91 en verde).

**Lo que se halló y lo que se decidió.** Aquí queda cada sitio donde lo hecho se separa del texto del plan, o donde el trabajo encontró algo que el plan no sabía:

| # | Qué | Qué se hizo |
| --- | --- | --- |
| 1 | **Temas.** El plan lista seis temas con frescura propia (lesiones y dudas, sanciones, alineación probable, entrenador, horario o sede, contexto competitivo); v1 busca hoy tres cosas: las noticias del equipo, las palabras oficiales y la previa internacional | v2 empieza con esos tres temas y con la frescura de v1 para todos (sección 3). Los tipos de afirmación de los otros temas ya los entiende el extractor (sanción, titular, entrenador, horario, sede), pero no tienen una búsqueda propia hasta que la semana de comparación diga que merece la pena |
| 2 | **«Dos partidos en 3 días».** Con la frescura que el propio plan fija (24 horas, 4 en las últimas 12) dos partidos del mismo equipo solo comparten una búsqueda si sus pasadas caen dentro de esa frescura | no se alarga la frescura para que la prueba salga: eso cambiaría lo que se sabe de un jugador lesionado. La prueba del plan pasa sobre la caché real y la del ciclo enseña las dos mitades (una búsqueda mientras está fresca, otra cuando caduca) |
| 3 | **v1 daba al partido de la pasada lo que la página decía del siguiente partido del equipo** | v2 lo descarta (`other_match`). Puede aparecer como «hecho de v1 que v2 no encontró» en la comparación: es lo esperado, y la pestaña lo enseña con ejemplos |
| 4 | **La frescura se juzga al leer.** Una respuesta encontrada un día antes del partido no es fresca para la pasada de las últimas doce horas | la caché la juzga cuando se hace la pregunta y con el próximo partido de cada equipo (sección 3) |
| 5 | **Lo tipado tenía más lectores de los que parecía.** La tabla `ai.evidence` la leen trece módulos, diez de ellos ajenos a v2: el paquete, los picks del día, la decisión, la revisión del partido, el informe, el aprendizaje, la auditoría de fugas y tres servicios de la Consola | todos pasan por una sola pregunta (`gates.typed_visible`), y una prueba estructural falla si aparece un lector nuevo sin ella (sección 5) |
| 6 | **Quién paga una búsqueda que comparten las dos investigaciones.** La consulta del partido es la misma en v1 y en v2 | v1 paga y v2 lee, y se cuenta aparte (`v2_shared`): así la comparación puede decir cuántas habría pagado v2 solo, que es lo que mide el gate (sección 7) |
| 7 | **El gate es más duro que el plan en cinco sitios, todos míos:** cuenta como pagada la búsqueda que respondió una caché, mira aparte los hechos sobre quién puede jugar, exige que todas las pasadas del día corrieran en sombra, exige que nadie cite lo de v2 y pide un mínimo de muestra | sección 7; todos pueden retrasar o endurecer el gate y ninguno lo relaja |
| 8 | **`on` sustituye al extractor de hoy.** El registro dice que `claim_extractor` solo lo sustituye una fila que firmas tú, y el código no comprueba esa firma: `on` es una palabra tuya y solo la limita el gate | el orden es mío: no se pone `on` sin el gate en `PASA` y sin esa firma (sección 12) |
| 9 | **Coste.** El plan dice «Claude, igual» | la semana de comparación suma las lecturas del extractor v2 a las del de hoy; declarado y medido en el libro (sección 10) |
| 10 | **El tope de 20 afirmaciones es de la respuesta, no de la página.** El contrato lo describía «por página»; una llamada lee hasta 6 páginas y su respuesta entera no puede pasar de 20 | una respuesta con más de 20 afirmaciones ya no se pierde entera (al principio el contrato la rechazaba y cada pasada pagaba otra vez la misma lectura): se leen las 20 primeras y el resto se descarta y se cuenta (`too_many`). El prompt ya pide «como mucho 20». La comparación lo enseña (las pasadas cortadas) y, si pasa a menudo, el arreglo es partir las páginas en varias llamadas o un contrato nuevo con otro tope, nunca subirlo sin versión. Se corrigieron el comentario del contrato y la fila de `IA_FASE1.md` |
| 11 | **Dos medios independientes.** El plan escribe la regla junto a «medio fiable»; la regla de hoy cuenta dominios de periodistas y de medios, fiables o no | no se cambia: la clase de la fuente es una etiqueta hasta que se mida su acierto (sección 5) |
| 12 | **Salidas estructuradas y Batch.** El plan dice «Haiku 5.5 con structured outputs; Batch para lo que no corre prisa» | el extractor v2 llama por la misma función que el de hoy (`call_json`, nivel `bulk`, el de Haiku), así que hereda lo que la fase 0 decide para cualquier prompt: la caché de prompts, encendida de serie, y las salidas estructuradas, apagadas hasta que el gate `native_schema` del LAB las abra para el modelo. **No usa Batch**: la pasada necesita la respuesta del extractor para guardar la evidencia y armar el paquete antes de terminar, y un lote puede tardar horas. Nada del plan lo exige para esta fase; si la fase 3 necesitara que la investigación de los partidos lejanos espere, se decide entonces, con su propio gate |

**La revisión independiente (27 oct 2026).** Antes de desplegar, un revisor que no había escrito el código leyó la rama y corrió fragmentos contra las funciones reales: halló 4 hallazgos altos, 5 medios y 4 bajos. Ninguno impedía desplegar con el interruptor en `off` o en `shadow`, y los cuatro altos solo rigen con `on` (en sombra nadie lee lo tipado). Cada uno terminó así:

| Hallazgo | Qué era | Qué se hizo |
| --- | --- | --- |
| H1 (alto) | Una página que da órdenes podía hacer que el extractor escribiera dos afirmaciones sobre un jugador citando dos páginas que no lo nombran, y dos medios las confirmaban: la cita era una subcadena de cinco caracteres que podía cruzar título y texto | **Corregido en ia-p02.** La cita tiene un mínimo (10 caracteres y 2 palabras) y está en una sola parte de la página; la de un jugador debe nombrarlo y decir algo más que su nombre; las páginas que suenan a una orden se leen en una llamada aparte (secciones 3 y 4) |
| H2 (alto) | La regla de que lo opuesto es `CONTRADICTORY` no se aplicaba entre ámbitos (una afirmación sin partido y otra de este partido sobre el mismo jugador eran dos sujetos) ni frente al parte del proveedor | **Corregido en ia-p02.** Una afirmación tipada se agrupa por persona (equipo y jugador) y se decide junto a los partes del proveedor y de v1 del partido (sección 5) |
| H3 (alto) | Una afirmación sin partido que la alineación confirmada de un partido desmintió volvía a `PROBABLE` para el siguiente, y con los dos partidos dentro del horizonte cambiaba de estado dos veces por ciclo | **Corregido en ia-p02.** Una alineación confirmada del mismo equipo, conocida después de leída la afirmación y con el jugador en el once, la mantiene `OUTDATED` para toda pasada posterior (sección 5) |
| H4 (alto) | Con `on`, las lecturas de la decisión (`intel/decision.py`, los picks del día, `intel/match_review.py` e `intel/report.py`) eligen la evidencia por partido y no ven las afirmaciones sin partido, que son las que el extractor escribe para un parte de lesiones sin partido: el contexto bajaría de completo a parcial, y con él la puntuación del pick | **Abierto, y es condición para `on`.** No cambia nada con `off` ni con `shadow`. Antes de encender `on`, esos lectores usarán el predicado del paquete (el del partido, o el del equipo sin partido dentro de la ventana de frescura) cuando lo tipado sea visible, con una prueba que ponga una afirmación de equipo y compare el contexto y la puntuación; `on` no se pone sin ello (sección 12) |
| M1 (medio) | El estado de una historia tipada contaba los partes que la misma pasada daba por caducados, y comparaba los medios por la dirección exacta: `marca.com` y `amp.marca.com` eran dos | **Corregido en ia-p02.** El estado sale de los partes que siguen vigentes y el medio es el dominio registrado que avala la dirección (el sufijo más específico de `ai.sources`) o, si ninguno, la propia dirección |
| M2 (medio) | Una cita de 301 caracteres, o 21 afirmaciones, invalidaba la respuesta entera y cada pasada volvía a pagar la misma lectura; el libro apuntaba la llamada como buena antes de que se rechazara | **Corregido en ia-p02.** Los límites que el esquema del hilo no puede llevar (300 caracteres de cita, 20 afirmaciones, una fecha que sea fecha) se miden afirmación por afirmación: una fuera de límite cuesta esa afirmación y no la respuesta; lo que no es `claim-v1` se descarta entero y se cuenta una sola vez; las páginas se marcan leídas al acabar su llamada (secciones 3 y 4) |
| M3 (medio) | Una vez en `on`, el gate no puede volver a medirse: sus pasadas se anotan `research_v2_on`, la ventana en sombra no se completa y un `PASA` rige para siempre | **Declarado, no corregido** (sección 7). Es la consecuencia de medir a v2 mientras v1 decide; revalidar es volver a `shadow` y reunir 7 días nuevos |
| M4 (medio) | La migración 0114 pide bloqueos exclusivos en una sola transacción: sobre una tabla grande bloquearía las lecturas | **Medido, sin cambio** (sección 6). Con el volumen real de producción tarda 46 a 48 ms y el peor tirón de un lector fue de 19 ms |
| M5 (medio) | Lo «en vigor» del gate A (decisión A) se leía del entorno del proceso que evalúa y no del de la ventana: una optimización encendida con evidencia mala y apagada antes de registrar no se juzgaba | **Corregido en ia-p03.** El worker anota en `ai.feature_gates` (gate `switches`) las palabras con que corre cada vez que cambian; el gate A lee de ese libro qué estaba en vigor y un cambio de palabras dentro de la ventana la deja incompleta (`IA_FASE0.md`, secciones 3 y 10) |
| L1 (bajo) | Con el interruptor en `off`, el set diario nombraba las columnas de la 0114: si el código arrancaba antes de aplicarse la migración, el set diario fallaba | **Corregido en ia-p03.** Una columna que no existe se trata como una tabla que no existe: el set diario se arma como antes |
| L2 (bajo) | Cuatro desviaciones del texto del plan que quedan: la tabla de frescuras y los disparadores del plan no se aplican (todos los temas, 24 horas y 4 en las últimas 12; solo existe el disparador de la pasada previa); las páginas ya leídas se vuelven a pagar para cada partido nuevo; las suspensiones del siguiente partido se descartan; y «dos partidos en 3 días» pasa sobre la caché pero la producción solo investiga los partidos de hoy | **Declaradas** (filas 1 a 4 de la tabla de arriba; las páginas, en la sección 3). El ahorro no se promete: lo mide el gate (`fewer_searches`) y puede no cumplirse, y entonces el gate dice `NO PASA` |
| L3 (bajo) | `scripts/ia_baseline.sql` leía `ai.evidence` sin filtrar: repetir la línea base en sombra habría contado las afirmaciones tipadas | **Corregido en ia-p03.** Las dos consultas que cuentan evidencias (por día y por partido) cuentan solo las filas de v1 (`subject_type IS NULL`) |
| L4 (bajo) | `scripts/ai_replay.py` repite pasadas viejas con el modo de hoy y los estados de hoy de cada afirmación; con H3, una alineación posterior se cuela en la repetición | **Declarado.** El mecanismo es anterior a la fase y no decide nada (el informe va a la salida): una repetición no prueba lo que la pasada vio entonces; para eso están el paquete que se guardó con la pasada y el libro |

## 12. Lo que falta

La fase está **terminada en el código para `off` y para `shadow`, y se despliega apagada**; para `on` falta cerrar el hallazgo H4 de la revisión. Lo que queda es el orden del plan, el tiempo, una medición y esa lectura:

| Falta | Quién | Cuándo | Qué lo cierra |
| --- | --- | --- | --- |
| Que pase el gate A | el tiempo | 7 días completos de medición de la fase 0 | `ia_gate evaluate --record` con `PASA` |
| Desplegar la fase (0114 y 0115), apagada | yo | ya: no depende del gate A (plan, sección 35) | una copia de seguridad con su prueba de restauración justo antes de migrar, las dos migraciones, la comprobación de salud y el escaneo de seguridad del rango desplegado en 0 |
| Poner `FBI_AI_RESEARCH_V2=shadow` | yo | cuando el gate A haya dado `PASA`, con una copia fechada de `app.env` y reinicio del worker | la primera pasada con `research_v2_shadow` en sus cuentas |
| 7 días completos con todas las pasadas en sombra | el tiempo | desde que se encienda | `python -m scripts.ia_research_gate evaluate --record` con `PASA` |
| La batería sobre `extract-v2` | tú y yo | cuando estén las acciones 5 y 7 | `ia_battery submit` y `collect` con `PASA` |
| Que las lecturas de la decisión vean las afirmaciones de equipo sin partido (hallazgo H4, sección 11) | yo | antes de `on`; con `off` y con `shadow` no cambia nada | los cuatro lectores usan el predicado del paquete cuando lo tipado es visible, con una prueba que ponga una afirmación de equipo y compare el contexto y la puntuación |
| Pasar a `on` | tú | solo con el gate en `PASA` y con el hallazgo H4 cerrado | tu firma de `claim_extractor` en `intel.promotions` y, entonces, tu palabra en `FBI_AI_RESEARCH_V2` |

**El gate.** La fase 2 no tiene gate propio: su comprobación es la parte de investigación del **gate B** (la sombra funcional tras 14 días), que además pide la batería en verde. Ninguna de las dos cosas se declara sin evidencia real.

**Qué no puede hacerse antes.** Los 7 días de la fase 0 y los 7 de esta son tiempo real; no se simulan ni se estiman. Encender esta fase y empezar la 3 esperan al gate A. La fase 3 usa lo que escribe v2, pero lo lee con las mismas reglas.

**Acciones tuyas de esta fase: ninguna nueva.** El plan lo dice (propietario: ninguno). La batería sobre `extract-v2` usa la clave y el sobre del LAB de las acciones 5 y 7, que ya estaban en la lista (`IA_ACCIONES_MANUALES.md`); la firma de `claim_extractor` es de más adelante, cuando el gate haya pasado.
