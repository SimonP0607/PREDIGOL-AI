# IA-103 / IA-104 · Plan de contenido por código y crónica única (`content-plan-v1`, `chronicle-v4`)

Piezas **AD-F01** (plan de contenido, código IA-103) y **AD-F02** (crónica única, código IA-104) del plan de la arquitectura definitiva
2026 (ola 5, ruta crítica AD-B02 → AD-F01 → AD-F02 → C-01 entrega 2). Todo nace **apagado** (`FBI_CHRONICLE_V4=off`) y, encendido, va **en
sombra**: escribe en una tabla propia que ningún lector ve. **No cambia** `user-narrative-v3` (la crónica de hoy sigue igual), ni
probabilidades, ni picks, ni `decision-v1`, ni ningún umbral. `FBI_MATCH_INTELLIGENCE` sigue apagado; llevar la crónica al lector es la
entrega 2 de C-01, otra pieza.

## 1. Qué hace, en una frase por parte

| Parte | Dónde | Qué hace |
| --- | --- | --- |
| Tabla de clases | `fbi/chronicle/claims.py` (`claim-classes-v1`) | Dice qué hecho autoriza cada clase de afirmación («nada en juego», «clasificado», «racha», «duda», «rumor», «probabilidad»…). |
| Plan | `fbi/chronicle/plan.py` (`content-plan-v1`) | Elige por código, partido a partido, los hechos obligatorios, los opcionales y las abstenciones de cada sección. Puro. |
| Lectura | `fbi/chronicle/inputs.py` | Lee, solo lectura, lo que el plan necesita: la historia del paquete, las noticias por referencia, el motor de escenarios y la cifra única. |
| Redactor | `fbi/chronicle/writer.py` (`chronicle-v4`) | Pide al modelo pequeño la crónica en español e inglés, solo con los hechos del plan. |
| Verificador | `fbi/chronicle/verify.py` (`chronicle-verify-v1`) | Revisa frase por frase y **quita la frase** que el plan no apoya; el resto se queda. |
| Trabajo | `fbi/chronicle/v4_job.py` | Cada 30 min, en sombra: plan → redacción (por lotes si se puede) → verificación → fila en `ai.chronicles`. |
| Registro | tabla `ai.chronicles` (migración **0155**) | Cada plan y cada intento, de solo añadido. |

## 2. El plan de contenido (AD-F01)

**Sin plan no hay sección.** El código decide, no el modelo. Las secciones, en este orden: qué se juega, cómo llega cada equipo, qué
puede definir este partido, estadísticas, jugadores, novedades, riesgos (**puede quedar vacía**: un riesgo nunca se inventa) y qué falta
por saber. Cada sección tiene un tope de frases corto (2 a 4) y nunca más frases que hechos.

De dónde salen los hechos:

- **La historia del paquete** (la misma que usa la crónica de hoy): tabla, eliminatoria, forma, rachas, campo, goles esperados,
  máximo goleador, cara a cara, últimos resultados y bajas del proveedor.
- **El motor de escenarios** (`scenarios-v2`, IA-082): lo que cada equipo se juega, lo **demostrado** (conseguido o descartado) y lo que
  hace cada resultado de este partido. Nunca sus probabilidades simuladas.
- **Las noticias, solo por referencia** (`E:<id>`): estado, tipo, lado, medio y fecha. El texto de internet **no entra en el plan**.
  Solo el redactor recibe el texto propio de PrediGol de una noticia, y solo si su fuente está `verificada_autorizada` y firmada en el
  directorio v2.
- **La cifra única** (`forecast-v2`, IA-083): si se menciona una probabilidad, se copia con su cita (`57 % [cifra forecast-v2 <id>]`).
- **Lo que falta, dicho por código**: alineaciones aún no oficiales, reglamento no codificado, motor de escenarios sin lectura.

Lo que **nunca** entra (queda en `excluded` con su motivo): «nada en juego» sin el motor (`sin_certificacion_motor`), un objetivo no
demostrado como decidido (`no_demostrado`), un hecho conocido después del momento del plan (`posterior_al_plan`) o sin momento
(`sin_momento`), una noticia caducada (`caducada`) o de una fuente sin permiso (`fuente_sin_permiso`), el motivo médico del proveedor de
una baja (solo entra su tipo: lesión, sanción, enfermedad…), y un rumor como hecho (un rumor entra como rumor, con su nivel, en riesgos).

**Puntuación de lo opcional:** 0,40 × pertinencia por mercado + 0,35 × rareza + 0,25 × novedad. La pertinencia dice cuánto habla un hecho
del resultado (1X2), de los goles (más/menos) y de que marquen ambos; la rareza, lo poco habitual (una racha larga, una baja clave); la
novedad, lo nuevo (una noticia del último día, un hecho que el plan anterior no tenía). Los **obligatorios** no se puntúan: un objetivo
demostrado, la situación de la eliminatoria, una baja clave, una noticia confirmada.

### La tabla «clase de afirmación → hecho que la autoriza» (`claim-classes-v1`)

| Clase | Riesgo | Solo la autoriza |
| --- | --- | --- |
| `SIN_OBJETIVO_DEMOSTRADO` («nada en juego») | alto | el hecho demostrado `SIN_OBJETIVO_DEMOSTRADO` del motor de escenarios |
| `OBJETIVO_CONSEGUIDO` («clasificado», «campeón», «ascendido», «salvado») | alto | un objetivo `conseguido` demostrado por el motor |
| `OBJETIVO_DESCARTADO` («eliminado», «descendido», «sin opciones») | alto | un objetivo `descartado` demostrado, lo que haría un resultado, o la eliminatoria |
| `OBJETIVO_EN_JUEGO` («se juega», «pelea por») | medio | un objetivo del motor, la tabla o la eliminatoria |
| `SUPERLATIVO` («nunca», «el mejor de la liga», «récord», «por primera vez») | alto | **nada** hoy: ningún código lo calcula; la frase se quita siempre |
| `RACHA` | medio | una racha, una forma o un resultado |
| `DISPONIBILIDAD` («baja», «duda», «sancionado») | medio | una baja o duda del proveedor, una noticia, o las alineaciones pendientes |
| `RUMOR` | alto | una noticia que **es** un rumor, solo en riesgos y llamada rumor |
| `CIFRA_PRONOSTICO` (un porcentaje) | alto | una cifra de `forecast-v2` repetida con su cita |
| `DETALLE_MEDICO` (diagnóstico, parte del cuerpo, tratamiento, tiempo de baja) | alto | **nada**: nunca en una crónica |

El plan solo deja entrar una clase si lleva un hecho que la autoriza; el verificador lee la clase de cada frase por sus palabras y quita
la frase que no cita ese hecho.

## 3. La crónica única (AD-F02)

El redactor (modelo pequeño, Haiku) recibe **solo el plan**: ningún artículo, ninguna página, ninguna búsqueda. Devuelve, en español e
inglés, las ocho secciones como listas de frases; cada frase cita los hechos en que se apoya. La voz es la de un analista: párrafos
cortos, hechos concretos con su fuente, sin adjetivos que sobren, sin pronósticos ni lenguaje de apuesta.

El verificador quita **la frase** (no la crónica) que: cita un hecho que no está en el plan; dice un número que no tiene ningún hecho
citado (los números calculados no tienen hecho); dice un porcentaje sin su cita o distinto de la cifra única; nombra a alguien que no está
en los hechos; hace una afirmación de una clase que su hecho no autoriza; cuenta un rumor fuera de riesgos o sin llamarlo rumor; cuenta
una noticia solo probable sin atribuirla; cuenta una duda como certeza; usa un hecho descriptivo como causa; da un detalle médico
(`health-filter-v1`); o dice certeza, apuesta o códigos del sistema. Después compara los dos idiomas frase a frase.

**Abstenciones con código** (`ai.chronicles.abstention`): `SIN_PLAN` (el partido no tiene historia: falta la forma reciente de un
equipo), `SIN_DATOS` (solo hay «lo que falta») y `VERIFICACION_VACIA` (el modelo escribió y no quedó ninguna frase en pie). Cada sección
vacía tiene la suya en el plan (`SIN_RIESGOS`, `SIN_NOVEDADES`, `SIN_ESCENARIO`…).

**Banco de partidos trampa** (`tests/unit/test_chronicle_verify.py`, corre en CI): 26 trampas que el verificador debe rechazar, entre
ellas rumor contado como noticia, cifra inventada o movida una décima, número calculado, «nada en juego» con solo la posición en la tabla,
«descendido» sin demostrar, superlativo, lesión con detalle médico, tiempo de baja, orden escondida en una noticia, nombre de otro equipo,
lenguaje de apuesta y riesgo inventado. Hoy las 26 se rechazan.

## 4. Lo medido en producción (solo lectura, 17-nov-2026)

Repetición del plan sobre **los 1.078 partidos con análisis de los últimos 14 días** (cada uno en el momento de su última pasada; código
de esta rama ejecutado dentro del worker con conexión de solo lectura; 43 s; 0 errores; sin llamar a ningún modelo):

- **1.033 planes (95,8 %)** y **45 `SIN_PLAN`** (sin historia). Mediana de 20 hechos planificados por partido.
- **0 planes permiten «nada en juego»**: el motor de escenarios no está desplegado (la base de producción va por la migración 0141), así
  que nada lo certifica. **184 planes** tenían un «nada en juego» de `stakes-v5` (274 hechos `settled`) y el plan lo quitó.
- **0 planes con una clase de alto riesgo sin su hecho.**
- Noticias: los paquetes nombran 4.495; **4.155 quedan fuera por fuente sin permiso** (el directorio v2 no tiene firmadas las fuentes) y
  340 no están en `ai.evidence` para ese partido con la pregunta de lo tipado. Ninguna llega al redactor hoy: «novedades» queda vacía en
  todos. Es la regla funcionando, no un fallo.
- Riesgos: vacía en 1.044 de 1.078 (solo 60 dudas del proveedor); no se inventa ninguno.
- Para comparar: de las 442 crónicas `user-narrative-v3` aprobadas en esos 14 días, **87 (19,7 %) dicen «nada en juego»** o lo mismo en
  inglés; 66 de esos partidos tenían en su paquete la palabra `settled` de `stakes-v5`.
- **Coste estimado** (precio público de Haiku, entrada mediana ≈ 4.981 tokens, salida supuesta 1.800): **US$ 0,0014 por crónica en
  tiempo real, US$ 0,0007 por lotes**. Con 120 al día, unos US$ 0,17 diarios en tiempo real, por debajo del tope de US$ 1. La salida real
  y la tasa de frases en pie solo se sabrán al encender la sombra (no se ha llamado al modelo).

## 5. Dinero y límites

- **Tope de US$ 1 al día** (decisión previa del dueño): lo gastado hoy (Bogotá) con `chronicle-v4` más lo que reservan los lotes abiertos
  más la estimación de la llamada siguiente debe caber. `FBI_CHRONICLE_V4_DAY_USD` solo puede **bajarlo**.
- Encima, el presupuesto de Intelligence decide cada llamada como siempre. La capacidad `chronicle_v4` (US$ 14 al mes, sobre de
  producción) avisa en el panel de costes, no corta.
- Un intento por entrada (el mismo plan y las mismas noticias no se pagan dos veces), como mucho 3 por partido y día y 10 por pasada.
- Por lotes (mitad de precio) cuando la puerta `batch` cubre el modelo pequeño; si no, en tiempo real. El bloque de sistema va marcado
  para la caché de prompts.

## 6. Cómo se enciende, se apaga y se revierte

- **Encender la sombra**: tras desplegar (migración 0155), `FBI_CHRONICLE_V4=shadow` en el entorno del worker y reiniciarlo. Después,
  `python -m scripts.ia_capabilities sync --write` registra la capacidad `chronicle_v4` como `construida`.
- **Apagar**: `FBI_CHRONICLE_V4=off` (o quitar la línea) y reiniciar el worker. Nada más se lee ni se gasta.
- **Revertir**: apagar basta; las filas de `ai.chronicles` se conservan (solo añadido). La crónica de hoy (`user-narrative-v3`) no
  depende de nada de esto.
- **Qué mirar**: `SELECT status, abstention, count(*) FROM ai.chronicles GROUP BY 1, 2;` y, por fila, `metrics->>'support'` (frases en
  pie / propuestas) y `dropped` (cada frase quitada con su motivo).

## 7. Lo que queda para otras piezas

- C-01 entrega 2 (AD-J02) es la que llevará la crónica al lector, tras `FBI_MATCH_INTELLIGENCE`.
- AD-F06 rediseña la revisión posterior sobre los hechos citados y fija el muestreo humano (50 crónicas).
- Mientras el motor de escenarios no esté en sombra en producción, «qué se juega» solo dice posición y distancia en la tabla, y «qué puede
  definir» queda vacía salvo en eliminatorias.
