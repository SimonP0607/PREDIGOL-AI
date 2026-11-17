# IA-085 · Ingesta de señales: los RSS y sitemaps del directorio, en sombra

Pieza AD-C03 del plan maestro de la arquitectura definitiva 2026. Un trabajo del worker, `signals_ingest`, lee los RSS y sitemaps de las
fuentes del directorio v2 **que tienen permiso de lectura automatizada** y guarda en `news.items` (el almacén de IA-080, sin almacén
paralelo) el **título, la fecha, el autor y el enlace** de cada noticia. De las fuentes que aún no tienen permiso no lee nada: apunta lo que
**habría leído**. **Nace apagado** (`FBI_SIGNALS` sin valor = `off`). No llama a ningún modelo, no lanza búsquedas de Exa, no escribe en
`ai.evidence` y no cambia probabilidades, umbrales, picks, `decision-v1`, prompts, motores ni lo que ve el lector (nada lee `news` hasta
AD-G07, detrás de `FBI_NEWS_V2`, apagado).

## 1. Qué hace una pasada (cada 15 minutos, solo con `FBI_SIGNALS=shadow`)

1. **Los permisos deciden primero**, en el momento de leer (política de IA-063). Una fuente bloqueada, sin comprobar, excluida, fuera del
   directorio, con reserva de IA o con contradicción de derechos (El Colombiano) **ni se lee ni se planifica**. Una pendiente de derechos —o
   autorizada pero sin tu firma— **tampoco se lee**: cuando le toca, se apunta lo que habría leído (fila `would_read` en `news.feed_reads`,
   sin hacer ninguna petición) y una fila `would_block` en `ai.source_policy_log` (camino `ingest`, acción `fetch`).
2. **Solo una fuente autorizada y firmada se lee**, con petición propia: primero su `robots.txt` (una vez al día por sitio; si no se puede
   leer, cuenta como prohibido); luego el feed con `If-None-Match` / `If-Modified-Since`, un User-Agent honesto, diez segundos, sin
   reintentos y **sin otra vía jamás** (ni proxy, ni otro User-Agent, ni copias de terceros). Un 401, 403, 429 o un fallo es un fallo, y un
   feed que falla se consulta menos (el doble de espera por fallo seguido, como mucho una semana; se respeta `Retry-After`).
3. **Lectura incremental**: un 304 no escribe nada; un cuerpo con la misma huella (sha256) que el ya leído no se vuelve a analizar; de un
   feed nuevo solo entran las entradas del propio dominio de la fuente y no más antiguas que la más reciente ya vista. Cada noticia pasa
   por el almacén de IA-080: URL canónica (sin `utm_`, `fbclid`, `m.`, `www.`, AMP), sin duplicados, permisos copiados en la fila.
4. **Qué se guarda**: título (como texto no fiable: si parece una orden se marca y no cambia nada de lo que hace la pasada), fecha (con su
   marca de «estructurada» y de «solo día»), autor y enlace. **Nunca** el cuerpo, la descripción ni imágenes.
5. **Plan por tramos** según el partido más cercano de algún equipo o torneo que cubre la fuente (lo calcula el selector de IA-086):

| Tramo | Fuente oficial | Otra fuente |
| --- | --- | --- |
| ≤ 6 h | cada 30 min | cada hora |
| 6–36 h | cada 2 h | cada 3 h |
| 36 h–7 días | cada 6 h | cada 8 h |
| Sin partido | cada 24 h | cada 24 h |

**Exa, solo para huecos (planificado, nunca ejecutado en esta pieza).** Para los partidos de las próximas 36 horas y los hechos que mueven
un pick (lesiones, alineaciones, sanciones), se planifica una consulta solo si ninguna fuente legible hoy con autoridad `confirma` lo
cubre; siempre a través del selector (Exa limitado a dominios que se pueden leer, la consulta la escribe el servidor), **como mucho una por
partido** (hoy: 2,0) y nunca por encima del 95 % del sobre de 35. En sombra solo se cuenta: **esta pieza gasta 0**.

**Cuerpos.** Se cuenta qué titulares nombran un equipo con partido en 36 h (candidatos a pedir su cuerpo); leer cuerpos es de AD-C05 y
solo de fuentes con permiso de extracción.

## 2. Qué hay nuevo

| Fichero | Qué es |
| --- | --- |
| `backend/src/fbi/news/feeds.py` | Lector de RSS 2.0, Atom, sitemap, news-sitemap e índice de sitemaps (`feeds-v1`); rechaza documentos con `DOCTYPE`/`ENTITY` y de más de 5 MB |
| `backend/src/fbi/news/signals.py` | La pasada, el plan, robots, el plan de Exa (`signals-v1`) |
| `backend/migrations/versions/0149_news_feed_reads.py` | `news.feed_reads`: el estado de lectura de cada feed (ETag, Last-Modified, huella del cuerpo, fallos seguidos, próxima lectura), una fila por pasada, solo añadido |
| `backend/apps/worker/scheduler.py` | El trabajo `signals_ingest`, registrado **solo** con `FBI_SIGNALS=shadow`, plazo de 20 min; nunca tumba el worker |
| `backend/scripts/ia_signals.py` | A mano: `plan` (qué haría ahora, sin peticiones), `day`, `select`, `run` (una pasada) |

## 3. Qué se midió (producción, solo lectura, 17-nov-2026)

| Dato | Valor | Fuente |
| --- | --- | --- |
| Feeds que da el directorio v2 | 129 (112 RSS, 11 sitemaps, 6 news-sitemaps) | directorio fijado de la imagen |
| Nunca se leen ni se planifican | 23 (17 con reserva de IA, 6 bloqueados o sin comprobar) | política IA-063 |
| **Se pueden leer hoy** | **0**: nadie ha firmado (producción está en la migración 0138; no hay firmas) | — |
| Se apuntarían como «habría leído» | 106 (103 pendientes de derechos y 3 autorizadas sin firmar) | — |
| Si firmaras las 3 autorizadas | 3 feeds: Agência Brasil, El Nuevo Día (Tolima), Apunt (Valencia) | — |
| Tramos de los 106 planificables ahora | ≤ 6 h: 1; 6–36 h: 62; 36 h–7 d: 26; sin partido: 17 | 601 partidos seguidos del 17 al 23-nov |
| Exa hoy | 890 búsquedas en 446 partidos del 2 al 16-nov = **2,0 por partido**, US$ 13,35; mes a 16-nov: US$ 14,10 de 35 | `ai.usage`, `provider = 'exa'` |
| Exa que planificaría esta pieza para las próximas 36 h (45 partidos) | **0 consultas** (ninguna fuente firmada); si se firmaran todas las pendientes habría 666 fuentes candidatas a Exa, y el tope sigue siendo 1 por partido | — |
| Coste de CPU de una pasada | unos 4 s para planificar 601 partidos (local) | — |

Feeds de prueba: Dimayor y la FCF están pendientes de derechos, así que **no se grabaron de la red**; las pruebas usan feeds sintéticos con
su forma (`backend/tests/fixtures/signals/`).

## 4. Pruebas

Unitarias (`tests/unit/test_signals.py`): lector de feeds (RSS, Atom, news-sitemap, índice; fechas; rechazo de entidades y de lo que no es
un feed), URL canónica (`utm_`, `amp`, `m.`), `robots.txt` (grupo propio o `*`, la regla más larga gana, el empate prohíbe; uno al día;
ilegible = prohibido), tramos y castigo por fallos, que hoy no se lee nada, candidatos a cuerpo, el titular adversario (se marca y no cambia
el plan), Exa (solo ≤ 36 h, uno por partido, nunca ejecutado, corte al 95 %), el interruptor y el registro en el worker. De integración
(`tests/integration/test_signals_db.py`, PostgreSQL 16): primera pasada, petición condicional y 304, mismo cuerpo, solo lo nuevo, feed que
falla, robots que prohíbe, titular adversario, sin registro no se lee nada, `news.feed_reads` de solo añadido; y la migración de ida y vuelta.

## 5. Cómo se activa, se apaga y se revierte

- **Activar en sombra** (tras desplegar, si lo decides): `FBI_SIGNALS=shadow` en el entorno del worker y reiniciarlo. Antes, en el
  servidor: `alembic upgrade head` (lo hace el despliegue), `python -m scripts.ia_sources_load load` (el registro de IA-062) y el script de
  permisos de siempre (`deploy/vps/db/grants.sql`) para que el worker escriba en `news.feed_reads`. **Mientras no firmes ninguna fuente, la
  sombra solo apunta lo que habría leído: 0 peticiones a sitios de terceros.**
- **Apagar**: quitar `FBI_SIGNALS` (o cualquier valor distinto de `shadow`). Lo guardado se conserva.
- **Revertir**: `alembic downgrade 0147` quita `news.feed_reads` (el estado de lectura se rehace en la siguiente pasada completa); `news.feeds`
  y `news.items` no se tocan.

## 6. Pendiente

- **Tus firmas** (`ia_sources_load sign … --confirm-owner`): sin ellas no se lee ningún feed. Dimayor y la FCF tienen RSS abierto verificado.
- **AD-G02** agrupará las noticias en historias y enlazará equipos y jugadores; **AD-C05** pedirá cuerpos de las fuentes con permiso de
  extracción.
- Si un día se ejecuta Exa desde aquí, será otra versión, con su propia medición frente a los 2,0 por partido de hoy.
