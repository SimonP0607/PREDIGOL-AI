# IA-080 · Esquema `news`: el almacén de noticias

Pieza AD-G01 del plan maestro de la arquitectura definitiva 2026. Crea el sitio donde vivirán las noticias de PrediGol: los feeds de cada
fuente, los artículos, las historias que agrupan artículos del mismo hecho y los equipos y jugadores que nombra cada artículo. **Nada lo
llena todavía en producción** (lo hará AD-G02, en sombra) y **nada lo lee** hasta AD-G07, detrás de `FBI_NEWS_V2` (apagado). No cambia
probabilidades, umbrales, picks, `decision-v1`, prompts, motores, la sombra ni lo que ve el lector.

## 1. Qué hay ahora

**Una migración sola, `0146_news_schema.py`, solo de añadido.** Un esquema nuevo, `news`, con cinco tablas, y una columna nueva en
`ai.evidence`. Los nombres son los acordados con UX; la tabla de equivalencias con tu propuesta del Doc 2:

| Tu propuesta (Doc 2) | Lo que hay | Qué guarda |
| --- | --- | --- |
| `news.feeds` | `news.feeds` | Los RSS y sitemaps de cada fuente del directorio, con versión |
| `news.articles` | `news.items` | Un artículo tal como PrediGol lo vio, una fila por URL canónica y versión de su contenido |
| `news.stories` | `news.stories` | Una historia (los artículos que cuentan el mismo hecho), una fila por versión |
| `news.article_story` | `news.item_story` | En qué historia está cada artículo |
| `news.mentions` | `news.item_entities` | A quién nombra cada artículo: papel (protagonista o mencionado), método (plantilla, alias, proveedor, manual) y confianza |
| `news.claims` | columna `ai.evidence.item_id` | Las afirmaciones siguen en `ai.evidence`; cada una nueva dice de qué artículo salió |
| registro de fuentes propio | `ai.source_registry` (IA-062) | No se duplica: cada artículo apunta a la fuente del directorio v2 |

**Todo es de solo añadido.** Las cinco tablas rechazan modificar o borrar filas (el mismo disparador `ai.refuse_change()` de las tablas
de auditoría desde la migración 0072; la prueba estática de IA-059 lo exige para `news`). Un cambio es siempre una fila nueva:

- un artículo cuyo medio cambió el texto es la **versión 2** de esa URL; el mismo contenido otra vez no escribe nada;
- una historia clasificada (AD-G03), con su titular y resumen propios (AD-G04) o retirada a petición (AD-G05) es una **versión nueva**
  de la historia; volver a mostrarla es otra versión. Se ve la más reciente; las anteriores quedan como registro;
- mover un artículo a otra historia, o retirar un enlace a un jugador que resultó ser un homónimo, es una fila nueva que manda sobre la
  anterior.

**Duplicados.** La identidad de un artículo es la huella (sha256) de su **URL canónica**: https, sin `www.`, `m.` ni `amp.`, sin
parámetros de seguimiento (`utm_*`, `fbclid`, `gclid`…), sin versión AMP y con los demás parámetros ordenados (reglas `canon-v1`). La
base de datos comprueba que la huella corresponde a la URL. Además cada versión lleva la **huella del contenido** (`fp-v1`: el texto
leído en minúsculas, sin tildes ni signos): el mismo teletipo en cinco medios da la misma huella, lo que AD-G02 usará para agruparlos.
El texto se convierte en huella y se descarta: **no se guarda**.

**Los permisos de la fuente van copiados en cada artículo.** Al guardar un artículo se consulta la política de IA-063 y se copia su
respuesta: estado de la fuente en el directorio, qué se puede guardar (`facts` o `link`), qué se puede publicar (`summary`, `link` o
`none`), si la fuente tiene reserva de IA y la versión del registro. Tres reglas las hace cumplir la propia base de datos:

- una fuente que no permite guardar nada (no está en el directorio, está bloqueada, sin comprobar o en la lista de exclusión) **no se
  guarda**: el almacén la rechaza antes de escribir, y sin registro de fuentes no se guarda nada;
- solo una fuente autorizada y firmada por ti puede llegar a `facts` y a `summary`; una con reserva de IA queda siempre en enlace;
- al mostrar, manda **la más estricta** entre la copia y la política vigente: si retiras tu firma a una fuente, sus artículos pasan a
  enlace al momento, y una historia sin ninguna fuente que lo permita pierde su titular y resumen propios (solo quedan los enlaces).

**Cuatro fechas por artículo:** publicado (con dos marcas: si el medio solo dio el día, y si la fecha vino estructurada del feed o del
sitemap — solo esas entrarán en «Última hora»), visto por PrediGol, fecha del hecho y vigencia.

**Sin texto ni imágenes de terceros.** No hay ninguna columna para el cuerpo del artículo, extractos ni fotos. Del medio se guardan como
metadatos privados su nombre, el título y el autor; ninguno se muestra hasta que el abogado responda sobre el titular literal. El Doc 2
preveía guardar el cuerpo en privado para verificar citas: queda fuera hasta que el abogado fije el plazo de conservación (sería una
tabla nueva, versionada, en su propia migración).

**La columna `ai.evidence.item_id`.** Nula y sin valor por defecto (instantáneo: ninguna fila se reescribe). Es contenido: el
disparador de `ai.evidence` aprende la columna, así que se escribe al insertar la afirmación y nunca después. Las 20.756 evidencias que
hay (producción, 16-nov-2026) **se quedan sin artículo para siempre**; no se rellenan. `ai.evidence` sigue sin admitir borrado.

## 2. El código

`backend/src/fbi/news/`:

| Fichero | Qué hace |
| --- | --- |
| `canonical.py` | URL canónica (`canon-v1`) y huella del contenido (`fp-v1`) |
| `store.py` | Las escrituras: idempotentes (escribir dos veces lo mismo no hace nada), sin duplicados y con la política de fuentes aplicada. Dos procesos que guardan el mismo artículo a la vez dejan una sola fila |
| `readers.py` | Las lecturas de las que saldrá C-06: historia con sus artículos y entidades, artículos de un equipo o jugador, historias recientes. La lectura pública no muestra una historia en moderación o retirada, ni artículos de fuentes sin permiso de publicación |
| `vocab.py` | Las palabras (categorías, niveles, papeles…), las mismas que la migración; una prueba las mantiene iguales |

Nada del módulo lee una clave, llama a un modelo o a internet, ni escribe en `ai.evidence`. Ningún trabajo del worker lo usa todavía.

## 3. Qué se midió (producción, solo lectura, 16-nov-2026)

| Dato | Valor | Consulta |
| --- | --- | --- |
| Esquema `news` | No existe | `pg_namespace` |
| `ai.evidence` | 20.756 filas, 29 MB | `pg_class.reltuples`, `pg_total_relation_size` |
| Evidencias web, últimos 14 días | 427,2 al día; 142,4 URL distintas al día | `ai.evidence`, `origin = 'web'` |
| Evidencias web, últimos 30 días | 8.384 con 3.050 URL distintas | ídem |
| Tamaño de la base | 31 GB | `pg_database_size` |
| Migración en producción | `0137` | `public.alembic_version` |

Con el ritmo de hoy (unas 142 URL nuevas al día) `news.items` crecería unas 52.000 filas al año; el diseño técnico estima 1,1 millones
al año si se llega a 3.000 artículos al día. Cabe sin problema.

## 4. Pruebas

- **Migración de ida y vuelta** en una base de prueba desde `0139`: las cinco tablas con su disparador; una sola columna nueva en el
  resto del esquema (`ai.evidence.item_id`, nula); una evidencia anterior sigue nula y no se le puede poner artículo; `ai.evidence` sigue
  sin admitir borrado y su estado sigue cambiando; una evidencia nueva lleva su artículo y no se le puede quitar; la base rechaza una
  huella que no corresponde a la URL y un `summary` de una fuente que solo admite enlace; al bajar, el esquema queda exactamente como
  estaba.
- **Almacén** contra PostgreSQL: idempotencia, versión nueva por contenido nuevo, permisos copiados por estado de fuente, fuentes
  rechazadas, feeds versionados, historias versionadas, moderación y retirada, homónimo retirado, movimiento entre historias,
  concurrencia (cuatro procesos, una fila).
- **Prueba de contrato:** el ejemplo de C-06 «noticia individual» (`backend/tests/fixtures/contracts/news/C-06/noticia.public.json`,
  ficticio) se construye solo con lo que devuelven las lecturas de `news.items` + `news.item_entities`.

## 5. Despliegue, apagado y vuelta atrás

- **Despliegue:** la migración sola. No hay interruptor: nada lee ni escribe las tablas hasta AD-G02 y AD-G07. Tras desplegar, el
  script de permisos de siempre (`deploy/vps/db/grants.sql`) da lectura a la API y escritura al worker en el esquema nuevo, como en
  todos. Conviene la copia y la prueba de restauración con el esquema nuevo (AD-A07): la copia ya nombra todos los esquemas y los
  disparadores `*_append_only`.
- **Qué no cambia:** nada de lo que hoy se ve en Noticias (sigue saliendo de `ai.evidence`), ni ningún motor, prompt o pick.
- **Vuelta atrás:** las tablas pueden quedarse sin uso y la columna nula no afecta a nada de lo que ya lee `ai.evidence`. Si hiciera
  falta quitarlas, `alembic downgrade 0139` devuelve el disparador anterior, quita la columna y borra el esquema `news` con lo que
  tuviera (hoy, nada).

## 6. Pendiente

- **AD-G02** llena el almacén en sombra (ingesta, casi duplicados con `simhash`, historias) y escribe `item_id` en las afirmaciones nuevas.
- **AD-C03** necesitará guardar el estado de lectura de cada feed (`ETag`, `Last-Modified`, fallos); no cabe en `news.feeds` sin
  reescribirla, así que irá en un registro propio de solo añadido.
- **AD-G05:** la cola de moderación y las retiradas desde la consola necesitan que la API pueda insertar versiones de historias (hoy
  la API solo lee `news`).
- **Jugadores:** `news.item_entities.entity_id` usa el id propio (`core.players.id`), no el del proveedor que usa `ai.evidence`; la
  regla única de claves es de AD-H02.
- **Abogado:** titular literal del medio, autor, y plazo de conservación del cuerpo de los artículos.
