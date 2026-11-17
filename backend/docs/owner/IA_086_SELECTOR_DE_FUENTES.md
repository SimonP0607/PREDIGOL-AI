# IA-086 · El selector de fuentes: quién tiene autoridad para cada afirmación

Pieza AD-C04 del plan maestro de la arquitectura definitiva 2026. Dado un partido y un tipo de hecho (alineación, lesiones, sanciones,
calendario, reglamento, rumores…), devuelve **las fuentes del directorio v2 que tienen autoridad para ESA afirmación**, ordenadas, con lo
que se puede hacer hoy con cada una y lo que se podría hacer si tú la firmaras. **Solo propone**: no lee ninguna web, no llama a ningún
modelo, no gasta, no guarda nada y no cambia probabilidades, umbrales, picks, `decision-v1`, prompts ni lo que ve el lector. Lo usará
AD-C05 (extracción unificada) en sombra; hoy lo usa la ingesta de señales (IA-085) para planificar.

## 1. Qué hace

`backend/src/fbi/ai/source_select.py` (`source-select-v1`):

| Función | Qué devuelve |
| --- | --- |
| `select(partido, tipo_de_hecho, …)` | Las fuentes en orden de prioridad, cada una con su papel, su autoridad, su estado, su vía de hoy y la que tendría si la firmaras, y las consultas de Exa que haría falta lanzar (si alguna) |
| `select_sources(conexión, fixture_id, tipo_de_hecho)` | Lo mismo leyendo el partido de la base (solo lectura) |
| `explain(selección)` | Una línea en español por fuente: por qué está, su autoridad, qué se hace hoy con ella y qué «habría leído» |
| `summarize(partidos)` | Para un día: cuántas fuentes elige por partido y cuántas se pueden leer hoy (la medición de abajo) |

**Qué fuentes entran en juego** (todo sale de los campos del directorio, nunca de un texto leído):

- **Web oficial de cada club**: cuando uno de sus `clubes_cubiertos` es el equipo **y** es del mismo país. «Atlético Bucaramanga» es
  «Bucaramanga»; «América de Cali» no es «Deportivo Cali»; el «CD Nacional» de Madeira no es «Atlético Nacional»; «Real Madrid» no es
  «Atlético de Madrid». Si el equipo no tiene país conocido, no se elige ninguna: **abstenerse vale más que adivinar**.
- **Liga** del torneo (la que lo nombra, si alguna: Serie A y no Serie B), sin las divisiones aficionadas, juveniles, femeninas ni de
  fútbol sala; la **federación** si el país no tiene liga en el directorio, y siempre para las selecciones.
- **Confederación** (UEFA, Concacaf, Conmebol, AFC, CAF, OFC o FIFA) de un torneo internacional, por las palabras de su nombre.
- **Prensa regional**: la del país del equipo que lo cubre o que es de su ciudad (no para selecciones).
- **Prensa nacional** de cada país, sin medios dedicados al fútbol femenino en un partido masculino; **fuentes de datos** solo para
  estadísticas, resultados y análisis.

**La autoridad** es la del directorio (`autoridad_por_afirmacion`): `confirma`, `informa`, `solo_rumor`, `sin_autoridad`. Para un hecho
solo salen fuentes que `confirma` o `informa`: **un rumor nunca sale como hecho de una fuente sin autoridad**. Pidiendo `rumores` salen todas
las del partido y ninguna cuenta como hecho. Un club «confirma (solo del propio club)»: preguntado por el otro equipo, no tiene autoridad.

**La vía** la decide la política de fuentes de IA-063 en el momento de preguntar:

| Vía | Cuándo |
| --- | --- |
| `rss`, `sitemap`, `official` | Fuente autorizada **y firmada por ti**: se lee con petición propia (su feed, su sitemap o su web oficial) |
| `exa` | Lo mismo, sin feed: Exa limitado a su dominio, y solo si el sobre de Exa no ha gastado el 95 % |
| `link` | Pendiente de derechos, sin firmar, con reserva de IA (nunca un modelo) o sin presupuesto: solo su enlace |
| `none` | Bloqueada, sin comprobar, excluida o desconocida: nada |

**Contradicción entre fuentes (El Colombiano).** El directorio v2 la marca «sin reserva conocida»; el Doc 2 recoge que sus términos no
autorizan el uso por IA sin permiso previo. Hasta resolverlo cuenta **la lectura más estricta**: solo enlace, aunque la firmaras
(`STRICTER_READINGS`; quitarla es un cambio de código que decides tú).

**El orden.** Prioridad = cercanía del partido (≤ 6 h: 1; 6–36 h: 0,7; 36 h–7 días: 0,4; más: 0,1) × prioridad de la entidad × papel ×
autoridad × fiabilidad × lo que se puede hacer hoy × relevancia para el mercado (si se da uno).

**Las consultas las escribe el servidor**: el nombre del equipo que hay en la base más unas palabras fijas por tipo de hecho e idioma
(«Bucaramanga lesionados bajas»), con `includeDomains` de las fuentes que se pueden leer. Ningún modelo escribe una consulta, una URL o un
nombre, y ningún texto leído las cambia. Como mucho **una por selección** (hoy Exa hace 2,0 búsquedas por partido).

## 2. El ejemplo del plan: Bucaramanga – Nacional (prueba de contrato)

| Tipo de hecho | Fuentes | Autoridad | Hoy | Si lo firmas |
| --- | --- | --- | --- | --- |
| Alineación, convocatoria, lesiones, declaraciones | `atleticobucaramanga.com.co`, `atlnacional.com.co` | Confirma (lo propio) | Enlace | Su web oficial |
| Sanciones, calendario, arbitraje, reglamento | `dimayor.com.co` | Confirma | Enlace | Su RSS verificado |
| Prensa de Santander | Vanguardia, El Frente, Canal TRO | Informa | Enlace | Exa limitado a su dominio |
| Prensa de Antioquia | Telemedellín (enlace); El Colombiano (enlace siempre: lectura más estricta); Minuto30 (solo referencia); Teleantioquia (bloqueada: nada) | Informa | — | — |
| Prensa nacional | Futbolred, El Espectador (sitemap), Semana, Blu Radio, Deportes RCN (sitemap), Win Sports… | Informa | Enlace | Exa o sitemap |
| Prensa con reserva de IA | El Tiempo, Gol Caracol (noticiascaracol.com), ESPN Colombia | Informa | Enlace, para siempre | Enlace |
| Rumores | Cualquiera de las anteriores | Sin autoridad / solo rumor | Como rumor; nunca sube solo | — |

Hoy ninguna de esas fuentes se puede leer ni pasar por un modelo: los hechos de ese partido siguen llegando por API-Football.

## 3. Qué se midió (producción, solo lectura, 17-nov-2026 04:45 UTC)

Partidos seguidos (`core.competitions.is_tracked`) exportados de producción: 601 del 17 al 23-nov; el selector corrió en local con el
directorio fijado de la imagen (producción está en la migración 0138: no tiene `ai.source_registry` ni firmas, así que nadie ha firmado).

| Dato | Valor |
| --- | --- |
| Partidos de mañana (17-nov, hora de Bogotá) | 44 (42 de selecciones: fecha FIFA; 1 EFL Trophy) |
| Fuentes que elegiría el selector por partido (13 tipos de hecho) | media 25,6; mínimo 8; máximo 56; 0 partidos sin fuente |
| Fuentes distintas para los 44 | 640 |
| **Que se pueden leer hoy con los permisos vigentes** | **0** (0 por partido) |
| Que se podrían leer si firmaras las que el directorio tiene como pendientes | 395 distintas; 14,8 por partido de media (mínimo 4) |
| Si firmaras solo las 3 autorizadas del directorio | 0 para mañana: ninguna cubre esos partidos (Tolima, Agência Brasil, Apunt) |
| Próximos 7 días (601 partidos) | 26,6 fuentes por partido; 1.430 distintas; 0 legibles hoy; 868 si se firmaran |
| Webs oficiales de club encontradas (558 partidos de clubes, 7 días) | las dos: 88; una: 141; ninguna: 329 (nombres cortos del proveedor sin alias en producción: «Luton», «Kashima») |

## 4. Pruebas

- **Contrato**: el ejemplo de Bucaramanga–Nacional, tipo por tipo (`tests/unit/test_source_select.py`).
- **20 partidos de otras ligas** (Premier, LaLiga, Serie A, Bundesliga, Ligue 1, Liga MX, Brasil, Argentina, J1, K League, MLS, Eredivisie,
  Portugal, Turquía, Bélgica, Chile, Ecuador, Colombia, Escocia, Dinamarca) con sus webs de club y su liga esperadas, y tres de selecciones.
- **Propiedades**: aunque firmaras todo el directorio, una fuente con reserva de IA nunca sale con vía de lectura ni de extracción; ningún
  hecho sale de una fuente sin autoridad; una pendiente siempre es enlace; sin registro, nada se puede leer.
- **Presupuesto**: al 95 % del sobre de Exa (US$ 33,25 de 35) deja de proponer Exa; como mucho una consulta por selección.
- **Nombres**: homónimos de otro país y de la misma ciudad no son el equipo.

## 5. Despliegue, apagado y vuelta atrás

- **Sin migración, sin interruptor propio**: es un módulo puro. Nada del lector lo llama. Lo usa la ingesta de IA-085 (apagada por defecto).
- **A mano**: `python -m scripts.ia_signals select <fixture_id> <tipo>` (o `--json`) y `python -m scripts.ia_signals day 2026-11-17`,
  ambos de solo lectura.
- **Vuelta atrás**: no guarda estado; AD-C05 seguiría con los niveles de búsqueda de `research-v1`.

## 6. Pendiente

- Los **alias de AD-H02** (`core.entity_aliases_live`) mejorarán el encuentro de webs de club (329 de 558 partidos sin ninguna). El selector
  ya los lee cuando existen; si no, usa `core.team_aliases`.
- **Tus firmas**: Dimayor (RSS abierto) y la FCF (RSS abierto) son las candidatas que más hechos `confirma` darían en Colombia.
- **El Colombiano**: resolver la contradicción de derechos.
