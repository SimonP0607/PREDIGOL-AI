# IA-120 / IA-121 / IA-122 — Portada de Noticias, contrato C-06 y fuentes del análisis (C-07)

Piezas AD-G06, AD-G07 y AD-G08 del plan de la arquitectura definitiva 2026. Todo nace **apagado o en sombra**: ningún lector ve nada
nuevo hasta que usted encienda `FBI_NEWS_V2` (Noticias) o `FBI_MATCH_INTELLIGENCE` (fuentes del análisis), y ninguna probabilidad,
pick ni umbral cambia.

## Qué hace

**C-06, la noticia (AD-G07).** Las noticias se sirven ahora también desde el almacén propio (`news.stories`, `news.items`,
`news.item_entities`) con un contrato versionado (`C-06 1.0.0`) en cuatro vistas:

| Vista | Ruta pública (con `FBI_NEWS_FEED` **y** `FBI_NEWS_V2`) | Ruta privada (solo usted, sin interruptor) |
| --- | --- | --- |
| Portada | `GET /api/v1/news/v2` | `GET /api/v1/admin/intelligence/news` |
| Búsqueda y filtros | `GET /api/v1/news/v2?q=…&country=&competition=&team=&player=&from=&to=&category=&level=&mine=&sort=` | la misma, privada |
| Noticia individual | `GET /api/v1/news/{clave de la historia}` | `GET /api/v1/admin/intelligence/news/{clave}` |
| Noticias del partido | `GET /api/v1/matches/{id}/news/v2` | `GET /api/v1/admin/intelligence/matches/{id}/news` |

La búsqueda es de texto completo de PostgreSQL, sin tildes ni mayúsculas, sobre el titular y el resumen **propios** de PrediGol y los
nombres de lo que la historia nombra. Nunca sobre el texto de un artículo: no se guarda.

**La portada (AD-G06, `front-v1`).** Orden por código, siempre el mismo para los mismos datos:

1. *Destacadas*: por nivel (oficial, dos orígenes, declaración, un medio, rumor), luego por la cercanía del próximo partido de lo
   que nombra (72 h), luego la más nueva.
2. *Principal*: la primera destacada con nivel oficial, dos orígenes o declaración. Un solo medio o un rumor nunca encabezan.
3. *Última hora*: solo historias con fecha de publicación **estructurada** (feed, sitemap, metadatos) de las últimas 24 h.
4. *Tus equipos*: las que nombran equipos o jugadores que el lector sigue (`/me/favorites`, solo lectura). Sin favoritos, el bloque
   dice `sin_favoritos`: las sugerencias no lo rellenan.

Un bloque vacío dice por qué; nunca se rellena.

**C-07, las fuentes del análisis (AD-G08, `link-v1`).** Cada evaluación E1–E4 del ciclo en sombra escribe, **en su misma
transacción**, la lista de hechos que miró (tablas `intel.eval_source_lists` e `intel.eval_sources`, migración 0160). El validador
solo enlaza un hecho si cumple tres cosas: la entidad por su identificador (un equipo del partido o un jugador de sus plantillas),
una cita literal que la nombra (nombre completo o inicial y apellido; un apellido solo no basta y un homónimo sin señal se descarta)
y un hecho fechado dentro de la ventana del partido (después del partido anterior del equipo: la noticia de un club no se cuelga de
todos sus partidos). La relación con el análisis la pone el código: `no_usada` para un rumor; `a_favor` o `en_contra` si el hecho
mueve dos puntos o más la probabilidad de una selección que depende de ese jugador; `contexto` en lo demás.

| Ruta | Quién |
| --- | --- |
| `GET /api/v1/matches/{id}/sources` | lector, solo con `FBI_MATCH_INTELLIGENCE` y solo si el análisis del partido está publicado (404 en otro caso) |
| `GET /api/v1/admin/intelligence/matches/{id}/sources` | usted: además, el efecto en cada selección, lo rechazado y por qué, y todas las evaluaciones |

## Qué no cambia

- `GET /news`, `GET /today/news` y `GET /matches/{id}/news` (BE-040) responden igual y siguen leyendo `ai.evidence`; con
  `FBI_NEWS_FEED=1` y `FBI_NEWS_V2` apagado, producción no ve ninguna diferencia.
- Nada busca en internet, llama a un modelo ni cambia una noticia o una probabilidad. `decision-v1` no se toca.
- En lo público nunca viaja: el texto, título, autor o foto de un artículo (el autor llega `pendiente_derechos`; la imagen es un
  monograma), una fuente sin permiso de publicación, el texto propio de una historia sin ninguna fuente que permita resumen
  (`pendiente_derechos`), una historia en moderación o retirada (`retirado_por_derechos`), ni ningún enlace a una selección. De una
  baja solo se dice el estado («baja», «en duda», «sancionado»), nunca un detalle médico.

## Lo que hay hoy

Hay **0 fuentes firmadas**: con la política vigente, ninguna fuente puede publicar resumen, así que C-06 mostraría solo enlaces o nada,
y el almacén `news` aún no lo llena ninguna ingesta en producción. Los hechos que hoy llegan de la web son resúmenes de un modelo
(no citas literales) salvo los de la investigación v2 y las citas comprobadas del extractor en cuarentena: el validador los rechaza
con `sin_cita_literal`, así que la mayoría de las listas de C-07 tendrán 0 hechos enlazados hasta que llegue texto literal de fuentes
con permiso. Todo se probó con datos ficticios (`tests/fixtures/contracts/intelligence/C-06` y `C-07`).

## Cómo se apaga o se revierte

- Noticias v2: dejar `FBI_NEWS_V2` apagado (como está). Las rutas nuevas responden 404 al lector.
- Fuentes del análisis: dejar `FBI_MATCH_INTELLIGENCE` apagado (como está).
- El registro de hechos se escribe solo con el ciclo en sombra (`FBI_EVAL_CYCLE=shadow`). Apagando el ciclo deja de escribirse; lo
  escrito se conserva (solo de añadido). La migración 0160 se revierte borrando sus dos tablas, sin tocar nada más.
