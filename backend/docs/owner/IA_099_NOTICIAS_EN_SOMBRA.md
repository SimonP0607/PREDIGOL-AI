# IA-099 a IA-102 · Noticias en sombra: historias, clasificación, texto propio y moderación

Piezas AD-G02 (IA-099), AD-G03 (IA-100), AD-G04 (IA-101) y AD-G05 (IA-102) del plan maestro de la arquitectura definitiva 2026. Un trabajo
del worker, `news_stories`, toma las noticias que ya guarda `news.items` (IA-080/IA-085: título, fecha, autor y enlace; **nunca el texto
del artículo**) y las agrupa en **historias**, les pone **categoría, idioma, país y nivel de confirmación**, aplica las **reglas de
derechos y lesiones** y, solo con un segundo interruptor, escribe el **titular y el resumen propios** de las historias cuyas fuentes lo
permiten. **Todo nace apagado y queda en privado.** Las respuestas del abogado siguen pendientes: `FBI_NEWS_V2` sigue apagado y la portada
actual (`FBI_NEWS_FEED`, encendida, que lee `ai.evidence`) **no cambia**.

## 1. Qué hace una pasada (cada 30 minutos, solo con `FBI_NEWS_STORIES=shadow`)

1. **Quién nombra cada noticia nueva** (`news-linker-v1`): los equipos de los partidos seguidos de tres días atrás a siete adelante, con
   todos sus nombres y alias. Un equipo cuenta si **todas** las palabras distintivas de uno de sus nombres están en el título; dos equipos
   que el título nombra con las mismas palabras (homónimos) se descartan los dos. Jugadores: no desde el título (llegarán con las
   afirmaciones de AD-C06). Se escribe en `news.item_entities`.
2. **Duplicados e historias** (`stories-v1`), de lo más seguro a lo menos:
   | Método | Regla |
   | --- | --- |
   | `url` | la misma URL canónica (sin `utm_`, `fbclid`, `m.`, `www.`, AMP, barra final) = el mismo artículo |
   | `huella` | la misma huella del texto (`fp-v1`): el mismo teletipo en otro medio |
   | `similitud` | títulos casi iguales (Jaccard ≥ 0,6 de sus palabras distintivas); del **mismo medio**, ≥ 0,85 |
   | `entidades` | el mismo tipo de hecho concreto (lesión, fichaje, sanción…) en 72 h y el mismo jugador, o el mismo equipo y títulos que comparten ≥ 0,5 de sus palabras |
   | `idiomas` | otro idioma, el mismo tipo de hecho, el mismo jugador o la misma pareja de equipos, en 36 h |
   **Nunca en la misma historia:** dos noticias que nombran equipos sin ninguno en común; una que dice «femenino», «sub-20», «reservas» y
   otra que no; dos títulos «A vs B» con parejas distintas (las plantillas de las webs de pronósticos). Una historia sigue abierta 72 h
   desde su última noticia. **Incremental:** solo se agrupa lo nuevo y nada ya agrupado se mueve (moverlo es decisión tuya, `manual`).
3. **Clasificación** (`classify-v1`, por reglas, **sin modelo**: no hace falta):
   - **Categoría**: primero el tema (Fichajes; Bajas y sanciones; Declaraciones), luego Selecciones si hay una selección, luego
     Competiciones (resultados, calendario, alineaciones, convocatorias, reglamento, arbitraje, estadísticas), si no Colombia o
     Internacional por el país. «Resultados y próximos partidos» **nunca** sale de la prensa: es de los datos de API-Football.
   - **Idioma**: el de sus noticias; si no lo traen, el de las palabras comunes de sus títulos; si no, el de sus fuentes.
   - **País**: el que comparten sus equipos (como lo escribe el proveedor); equipos de varios países = «Internacional».
   - **Nivel** (la escalera de AD-C07, por **origen**): Oficial (una fuente con autoridad `confirma` para ese tipo de hecho; un club solo
     sobre sí mismo) · Dos orígenes (dos independientes que informan) · Declaración (las palabras de una persona: los medios que la citan
     son un solo origen) · Un solo medio · Rumor. **Un teletipo en cinco medios es un origen**: mismo dominio, mismo grupo editorial, misma
     red de sindicación o títulos casi iguales. Un título escrito como rumor es rumor, sea cual sea la fuente.
4. **Reglas de moderación** (`moderation-v1`): una historia va a la **cola privada** (`en_moderacion`, oculta en toda proyección pública)
   cuando tiene texto propio y es de una lesión (`texto_lesion`), cuando un texto se rechazó por un detalle médico (`salud_rechazado`) o
   cuando tiene texto propio y ninguna de sus fuentes permite ya un resumen (`derechos_retirados`).
5. **Texto propio** — solo con `FBI_NEWS_TEXT=shadow` (apagado por defecto). Ver la sección 2.

## 2. El titular y el resumen propios (IA-101), solo con `FBI_NEWS_TEXT=shadow`

- **Quién llega al modelo**: solo los hechos tipados (`ai.evidence` con `item_id`) de artículos de fuentes **autorizadas por el directorio,
  firmadas por ti, sin reserva de IA**, guardadas como `facts` y con publicación `summary` (la copia de cuando se vio **y** la política
  vigente). Una fuente con reserva, pendiente o «solo referencia» **nunca** llega al modelo: aparece solo como enlace (medio, fecha y URL).
  El título del medio no se envía nunca.
- **Qué devuelve**: titular (5–120 caracteres) y 2 o 3 frases, en español e inglés, cada una con los hechos que la sostienen.
- **Verificador de apoyo** (`news-verify-v1`): cada frase cita 1–4 hechos que existen; cada número y cada nombre están en un hecho citado;
  un rumor se dice como rumor; un solo medio se atribuye; el inglés dice los mismos hechos y números que el español; sin enlaces ni marcas.
- **Verificador anti-copia** (`anticopy-v1`), **umbrales preregistrados el 17-nov-2026 antes de generar ningún texto**: ninguna racha de
  **más de 15 palabras** seguidas de una fuente; como mucho el **25 %** de los 4-gramas del texto en las fuentes (los que son solo
  nombres no cuentan); el titular comparte como mucho la **mitad** de sus 3-gramas con el de un medio y nunca es el del medio.
- **Lesiones** (`health-filter-v1`, IA-102): solo el estado (baja, duda, sancionado, disponible), la fuente y la fecha. Diagnóstico,
  parte del cuerpo, tratamiento, prueba o plazo **solo** si lo comunicó el club o el jugador y la frase lo atribuye («según informó el
  club»); un plazo nunca se estima ni se infiere. La duración de una sanción («tres fechas») no es un dato de salud.
- **Todo o nada**: un texto que falla en cualquier cosa no se escribe (no se arregla) y **no se guarda** (podría ser copia de un tercero);
  sí se guarda el intento en `news.story_texts` con sus motivos y medidas. Un texto aceptado es una versión nueva de la historia.
- **Dinero**: modelo pequeño (tier `bulk`), clave y sobre del **LAB**, como mucho **10 por pasada** y **US$ 2 al mes** (capacidad
  `news_text_shadow`, IA-058), y solo si el mes del LAB lo permite. Hoy, sin fuentes firmadas, **0 llamadas**. El paso a la API de
  lotes (mitad de precio) se hará cuando haya volumen: con 0 historias elegibles al día no hay nada que agrupar en lotes.

## 3. Derechos, cola privada y retirada (IA-102)

- **Permiso por fuente**: lo que se puede mostrar de un artículo es el `publish_level` más estricto entre la copia y la política vigente:
  `summary`, `link` o `none` (`none` no sale en ninguna proyección pública). Si retiras una firma, el texto propio deja de mostrarse al
  momento y la historia pasa a la cola. **Ninguna imagen de terceros**, nunca.
- **La consola** (solo SUPER_ADMIN, `require_admin`), bajo `/api/v1/admin/news/`:
  `GET moderation` (la cola, o `?status=retirada`), `GET stories/{clave}` (artículos con lo que su fuente permite hoy —sin el título del
  medio—, intentos de texto y el registro), y `POST stories/{clave}/request | withdraw | restore | approve | dismiss` con un motivo.
- **Retirada a petición con registro**: anotas quién la pidió (el titular de los derechos, una persona mencionada, un club, un medio, tú,
  otro) y una referencia (un número de caso: **nunca** el correo o el teléfono de la persona). La historia se oculta con una versión nueva
  `retirada`; devolverla es otra versión. **Nada se borra**: `news.moderation_log` y `news.stories` son de solo añadido.

## 4. Qué se midió (producción, solo lectura, 17-nov-2026)

Producción está en la migración **0138**: no existe aún el esquema `news`, así que la repetición se hizo sobre la **evidencia web de 14
días** de `ai.evidence` (cada dirección = un artículo, con el título que dio la búsqueda, sus equipos, jugadores y tipo), en un contenedor
sin red con el código de esta pieza. Muestra: **6.351 afirmaciones, 2.095 direcciones, 1.023 dominios**.

| Dato | Valor |
| --- | --- |
| Direcciones que la URL canónica juntó | 0 de 2.095 (Exa ya las devuelve limpias) |
| Duplicados exactos (misma huella en otra dirección) | 9 (0,43 %) |
| Casi duplicados (`similitud`) | 28 |
| Mismo hecho por entidades (`entidades`) / entre idiomas (`idiomas`) | 66 / 0 |
| Historias | 1.992 (**tasa de agrupación 4,9 %**); 82 con ≥ 2 artículos, 78 con ≥ 2 dominios; la mayor, 4 |
| Revisión a mano de 20 historias de ≥ 2 artículos (versión final) | 19 bien agrupadas, 1 dudosa (una lista genérica de bajas del día unida a un partido) |
| Categoría | 100 %: Bajas y sanciones 1.050 · Competiciones 468 · Selecciones 257 · Internacional 211 · Colombia 6 |
| Afirmaciones web de lesión con detalle médico | 482 de 2.999 (16,1 %); de duda, 57 de 343; con plazo, 118 de 2.999 |
| Fuentes cuyos hechos podrían llegar al modelo | **0** (nadie ha firmado; directorio v2: 3 autorizadas de 2.001) |
| Llamadas de modelo y gasto de esta pieza | **0 / US$ 0** (gasto del LAB en noviembre: US$ 13,01 de 55) |

**Calibración honesta**: los umbrales de agrupación se escribieron antes de medir. La primera repetición, revisada a mano (15 historias),
tenía **4 uniones falsas** (plantillas de webs de pronósticos y títulos en chino, que `fp-v1` reduce a sus cifras); la segunda (20),
plantillas del mismo medio con otros equipos; la tercera (20), subdominios del mismo medio, un partido femenino y títulos «AvsB» sin
espacios. Cada hallazgo es una regla de la sección 1 (todo dentro de `stories-v1`, antes de desplegar). El nivel de confirmación no se pudo
medir en producción: necesita el registro de fuentes (migración 0139), aún sin desplegar. Los umbrales anti-copia **no** se tocaron.

**Hallazgo para ti (no cambiado, fuera de esta pieza):** la portada actual muestra como «resumen» el texto de la afirmación de `ai.evidence`;
el 16 % de las de lesión llevan detalle médico (rodilla 81, tobillo 54, ligamento 32 veces en 14 días). El filtro de lesiones de esta pieza
solo actúa sobre los textos nuevos, en sombra.

## 5. Qué NO cambia

`FBI_NEWS_FEED` y su portada, `/news`, `/today/news`, `/matches/{id}/news`; `decision-v1`, probabilidades, umbrales, picks, prompts y motores
existentes; ninguna fuente se lee por esta pieza (lee lo que ya guardó IA-085); no se usa ningún proveedor ni API nuevos; no se toca
`web/`. `ai.evidence` solo se lee (con el filtro de research v2).

## 6. Cómo se enciende en sombra (tras desplegar) y cómo se apaga

1. La migración `0154` la aplica el despliegue; `deploy/vps/db/grants.sql` (lo corre `predigolctl` tras cada migración) da a la API
   `INSERT` en `news.stories` y `news.moderation_log` (la consola).
2. `FBI_NEWS_STORIES=shadow` en el worker + reinicio. Sin noticias en `news.items` (hoy, sin firmas, IA-085 no guarda ninguna) la pasada
   dice `nothing_new` y no escribe nada.
3. Solo cuando haya fuentes firmadas y quieras probar el texto: `FBI_NEWS_TEXT=shadow` (tope US$ 2/mes del LAB).
4. A mano: `python -m scripts.ia_news_stories report` (qué hay), `replay --days 14` (la medición de arriba sobre la base), `run` (una pasada).

**Vuelta atrás**: quitar los interruptores (o `off`) y reiniciar; las filas guardadas se conservan y nadie las lee. La migración se puede
bajar (`0154 → 0149`) y borra solo las dos tablas nuevas.

## 7. Pendiente

- Respuestas del abogado (titular literal, extensión de un extracto, resumen de un modelo que leyó un medio con reserva, exclusión
  periodística para lesiones, cláusula 4.2 a) de Exa, plazo de conservación). Hasta entonces, todo en privado.
- Tus firmas de fuentes: sin ellas no hay ningún texto propio que generar (y la ingesta no guarda artículos).
- Que los extractores escriban `ai.evidence.item_id` (AD-C05 en modo `on`): sin eso, ninguna historia tiene hechos que resumir.
- Muestra revisada a mano de textos propios (0 % de copia y de frases sin apoyo) y de niveles (0 rumores subidos): cuando haya textos.
