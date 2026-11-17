# IA-087 · Investigación unificada en sombra (con IA-088 e IA-089)

Piezas AD-C05 (extracción profunda unificada), AD-C06 (enlace de menciones) y AD-C07 (afirmaciones tipadas con autoridad, escalera por origen y cuatro fechas) del plan maestro de la arquitectura definitiva 2026. Un interruptor nuevo, `FBI_AI_RESEARCH_UNIFIED`, que **nace en `off`**: así, producción hace exactamente lo de hoy. Sin migración. Nada de esto llega al lector, a un paquete, a un gate ni a un pick.

## 1. Por qué

Hoy conviven dos investigaciones: Research v1 (`extract-v1`) y Research v2 (`extract-v3`). La v2 recuperó el 23,1 % de lo que encontró la v1 (gate `research_v2`, fila 17, 12-nov: **NO PASA**, y esa fila se conserva tal cual). De los 987 hechos que perdió, 747 se perdieron al **extraer** y solo 24 al buscar (diagnóstico RV2, 12-nov). Las causas medidas: la v2 solo ve los primeros 700 caracteres de cada página (y en el 92 % empiezan repitiendo el título), lee seis páginas por llamada, solo puede hablar de 30 jugadores por equipo, y su validador acepta cualquier palabra del nombre («Copa del **Rey**» cuenta como Oriol Rey). Y la escalera de confirmación cuenta **medios**, no **orígenes**: tres periódicos del mismo grupo que copian un teletipo «confirman» un rumor.

Esta pieza es el camino único que el plan pone en su lugar, medido al lado de los otros dos antes de que nada dependa de él.

## 2. Qué hace (en sombra)

Después de la investigación de cada pasada, sobre **las páginas que esa pasada ya tiene** (las que v1 y v2 guardaron en la caché de búsqueda; **no busca nada ni paga ninguna búsqueda**):

1. **Política de fuentes.** Una fuente con reserva de IA o de la lista de exclusión no se lee nunca. **Solo una fuente `verificada_autorizada` y firmada por ti pasa por un modelo**, diga lo que diga `FBI_SOURCE_POLICY`. Hoy (16-nov) son 3 de 2.001 y ninguna firmada: **en producción este camino no hace hoy ninguna llamada de modelo**; mide lo que el código haría.
2. **Texto limpio** (`deep_pages.clean`): sin el título repetido ni las líneas que el dominio imprime en todas sus páginas (menús, «Lee también»), hasta 12.000 caracteres.
3. **Huella de la página** (`fp-v1`, la misma del almacén de noticias): una página se extrae **una vez por huella**, la pida el partido que la pida y venga con la dirección que venga. Se guarda en `ai.research_cache` con la clave `rk-u1:page:<huella>` durante 30 días; «visto por primera vez» no se reescribe nunca.
4. **Ventanas elegidas por código** (`deep_pages.choose`): hasta 4 ventanas de 2.100 caracteres (el tamaño con el que se probó `extract-v4`), alrededor de los párrafos que **nombran a alguien del partido**. Un párrafo que no nombra a nadie no se envía; una página que no nombra a nadie no se pregunta (prefiltro).
5. **Enlace de menciones `name-match-v2`** (`mentions.py`, IA-088): contra la **plantilla completa** (listas de plantilla, temporada, alineaciones de los últimos 120 días —la última convocatoria de una selección—, fichajes y cesiones de 400 días, bajas del proveedor) y los alias de `core.entity_aliases` cuando existan. **Sin tope de 30.** Un nombre enlaza por el nombre completo, por un apellido distintivo, o —si el apellido no es distintivo («Rey», «Copa», «Real», «Santos», «Valencia», «León», un mes, una palabra del equipo o del torneo)— por dos palabras seguidas del nombre. Dos jugadores con el mismo apellido y nada más que los distinga en la cita: **no se enlaza a ninguno**. No translitera: una página en cirílico enlaza solo mediante un alias en cirílico.
6. **La puerta y las órdenes:** una página con algo de orden **en cualquier parte** (no solo en las ventanas) no se envía nunca.
7. **Una llamada por página** con `extract-v4` (contrato `claim-v2`, agente `quarantine_extractor`, en el **LAB**, como mucho `FBI_AI_RESEARCH_UNIFIED_MAX_PER_DAY` = 60 llamadas al día). Lo que vale se comprueba otra vez con `name-match-v2` y la cita tiene que estar dentro de **una** ventana. Alineaciones y listas de bajas se agrupan por código en una afirmación «lista» (tres jugadores o más, cita de hasta 600 caracteres); el contrato del modelo no cambia.
8. **Afirmaciones tipadas** (`assertions.py`, IA-089, `ladder-v2`): cada afirmación lleva su tipo y la **autoridad de su fuente para ese tipo** (de `autoridad_por_afirmacion`: un club confirma sus propias bajas y alineación; de otro equipo solo informa; la prensa nunca confirma sola; una frase escrita como rumor —«según», «podría»— es rumor). Escalera: Rumor < Reporte de un medio < Declaración atribuida < Confirmado por dos orígenes < Oficial. **Dos artículos cuentan como dos orígenes solo si** son de dominios distintos, no son del mismo grupo editorial ni de la misma red de sindicación, no son casi duplicados y no citan al mismo hablante. Una fuente de nivel D nunca sube nada. Más corroboración nunca baja un peldaño. **Cuatro fechas**: publicado (de la página, nunca la de hoy), visto (nunca se reescribe), del hecho y vigencia; lo visto después del momento de una decisión no existe para ella.
9. **Contradicciones = alertas, nunca correcciones:** bajas incompatibles entre orígenes (CC1), dos declaraciones incompatibles del mismo hablante (CS1), horario (CO1) o sede (CO2) oficial distinto del del proveedor.
10. **Comparación con v1 y v2 en la misma pasada:** de los jugadores sobre los que v1 (`xu_v1_*`) y v2 (`xu_v2_*`) escribieron un hecho de ese partido: cuántos enlaza la plantilla completa (`full`), cuántos los 30 de v2 (`capped`), cuántos están en las ventanas elegidas (`windows`) y sobre cuántos tiene este camino una afirmación (`found`).

**Qué escribe y dónde:** los contadores `xu_*` en `ai.fixture_passes.counts`; las páginas extraídas en `ai.research_cache` (`rk-u1:page:`, ninguna pantalla, paquete ni gate lee ese prefijo); una fila de `ai.usage` por llamada (espacio del LAB, `input_hash` que empieza por `rk-u1:`). **Nunca `ai.evidence`**: las filas de v1 (`subject_type IS NULL`) y las de v2 quedan intactas.

## 3. Qué no cambia

`decision-v1`, los picks, `FBI_PICKS_SOURCE`, probabilidades, umbrales, la sombra de los agentes, Research v1 y v2 (sus filas, sus llamadas, sus contadores y su gate, la fila 17 incluida), `extract-v4` y su contrato, la política de fuentes, y nada de lo que ve el lector. La lectura de la caché de búsqueda se hace sin contar reutilizaciones (`cache.peek`), para no mover las cifras con que se comparan v1 y v2.

## 4. Cómo se activa en sombra (tras desplegar)

1. Pon `FBI_AI_RESEARCH_UNIFIED=shadow` en el entorno del worker y reinícialo (un minuto). El libro de interruptores lo anota (`research_unified`) solo cuando deja de ser `off`.
2. Al día siguiente, mira las cifras (solo lectura, dentro de la imagen del worker):
   - `python -m scripts.ia_research_unified report --days 1` — contadores `xu_*`, páginas recordadas, llamadas y coste.
   - `python -m scripts.ia_research_unified linking --days 7` — AD-C06: jugadores no identificables con plantilla completa frente a los 30 de v2, por ámbito; citas de v2 que `name-match-v2` rechazaría.
   - `python -m scripts.ia_research_unified windows --days 7` — AD-C05: ¿el jugador de cada hecho de v1 está en el texto, en los primeros 700 caracteres y en las ventanas?
   - `python -m scripts.ia_research_unified replay --days 30` — AD-C07: `ladder-v1` frente a `ladder-v2` hecho por hecho, y los hechos que `ladder-v1` confirma solo con copias de un mismo origen.
3. Para que este camino llame a un modelo hace falta que **firmes** alguna fuente autorizada (`ia_sources_load sign`, IA-062) y que el LAB tenga sobre (`FBI_AI_LAB_MONTHLY_BUDGET_USD` > 0).

## 5. Cómo se apaga y se revierte

`FBI_AI_RESEARCH_UNIFIED=off` (o quitar la variable) y reiniciar el worker. No queda nada que limpiar: las páginas `rk-u1:page:` caducan solas (30 días) y la purga de la caché las borra 14 días después; los contadores `xu_*` son históricos de la pasada.

## 6. Qué se midió (producción, solo lectura, 16/17-nov-2026)

| Qué | Dato | Fuente |
| --- | --- | --- |
| Resultados de búsqueda guardados, 8 días | 3.560 resultados; 2.599 direcciones distintas (961 resultados repetidos, un 27 %, que hoy se leen otra vez); 2.732 textos distintos | `ai.research_cache`, ámbito `search` |
| Longitud del texto | mediana y p90 = 2.000 caracteres: **todos llegan cortados por la búsqueda** (`TEXT_CHARS`); hoy no hay texto de 12.000 | la misma muestra |
| Título repetido al empezar el texto | 3.391 de 3.560 (95,3 %) | la misma muestra |
| Mismo texto bajo varias direcciones | 3 grupos, 6 direcciones (poco: casi toda la repetición es la misma dirección pedida por varias búsquedas) | la misma muestra |
| Jugadores por equipo (plantilla + alineaciones de 120 días), 319 equipos de los partidos con hechos web de 7 días | mediana 34, p90 46; **228 de 319 (71,5 %) tienen más de 30**: v2 no puede nombrar a parte de su plantilla | `core.squad_members`, `core.fixture_lineup_players` |
| Citas de v2 sobre un jugador, 14 días | 878; **44 (5,0 %) no contienen el apellido** (las aceptó otra palabra del nombre): cota superior de lo que `name-match-v2` rechazaría; ninguna con «Copa del Rey» en esta ventana | `ai.evidence` con `subject_type = 'PLAYER'` |
| Hechos web de v1 con jugador, 7 días | 2.430 (1.424 de selecciones, 1.006 de clubes); **ninguno trae id del proveedor**: se enlazan por nombre | `ai.evidence` |
| Historias web, 30 días | 6.766; 990 con 2 medios o más, 178 con 3 o más | `ai.evidence.story_key` |
| Estados de `ladder-v1`, 30 días, web (n = 8.384) | Rumor 5.711, Probable 1.579, Confirmado 718, Caducado 357, Contradictorio 19 | `ai.evidence.status` |
| Gasto del LAB en noviembre | US$ 12,98 | `ai.usage` |

**No medido todavía, y por qué:** la recuperación de ventanas y enlaces sobre los hechos de v1, el porcentaje de no identificables con plantilla completa y la repetición `ladder-v1`/`ladder-v2` necesitan el código de esta pieza dentro de la imagen del servidor; se miden con el script del punto 4 en cuanto esté desplegado (las páginas guardadas se purgan 14 días después de caducar: conviene correr `windows` en la primera semana). **No se llamó a ningún modelo** (US$ 0): ninguna fuente está firmada y la medición en el LAB habría escrito en `ai.usage` de producción.

## 7. Pruebas

- **Unitarias** (sin base ni modelo): los cuatro casos fijos de AD-C06 («Copa del Rey» no es Oriol Rey; «Jesús de Miguel» no es Rodrigo Miguel Ferreira Rêgo; «Cásseres Jr.» sí es su jugador; cirílico solo por alias), una propiedad de homónimos (300 casos: sin segunda señal nunca se enlaza), plantilla de 60 sin tope; ventanas (el dato después del carácter 700 entra, como mucho 4, ninguna sin nombre), huella y casi duplicados; autoridad por tipo, escalera, **sindicación** (tres copias de un teletipo = un origen; mismo grupo o red = un origen; mismo hablante = un origen), propiedad de monotonía (400 casos), fuentes D, cuatro fechas, fugas, contradicciones.
- **Adversarias:** las 64 páginas de ataque profundo de `attacks_deep` (8 idiomas × 8 familias, la orden después del carácter 700) **nunca se envían**; las 8 honradas con imperativos normales se envían y sus dos datos valen; un modelo que escribe «Copa del Rey» sobre Oriol Rey, una cita que cruza dos ventanas o una palabra clave equivocada: no se guarda nada.
- **Integración** (PostgreSQL local): solo la fuente autorizada llega al modelo y paga el LAB; la misma página bajo otra dirección o para otro partido no se paga otra vez; la caché de v1 se lee sin contar reutilizaciones; `ai.evidence` no cambia; en el ciclo completo, con el interruptor en `shadow`, lo que escribieron, pidieron y respondieron v1 y v2 es idéntico a sin él.
