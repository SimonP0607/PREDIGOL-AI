# IA-040 — Registro de fuentes depurado

*Plan Maestro de Evolución de PrediGol Intelligence 2026, pieza INT-B01, ola 1. Medido el 11-nov-2026 en producción, solo lectura.*

## Qué se midió

- **Universo.** La evidencia web (`ai.evidence`, `origin = 'web'`) leída entre el 12-oct-2026 04:30 y el 11-nov-2026 04:30 UTC: 6.074 ítems de 1.047 hosts (5.175 de v1 y 899 de Research v2, que empezó el 4-nov).
- **Nivel de cada ítem, leído de tres maneras.** (a) El que guardó el registro al escribir (`source_tier`). (b) El que dan hoy las listas del código y el registro actual. (c) El de `evidence-engine-v1` (`tiers-v1`), calculado con el código desplegado.
- **Dónde están las listas.** En `fbi/ai/evidence.py`: 18 federaciones, 15 ligas, 94 medios, 12 agregadores, 9 redes, 1 periodista, `SOURCES_V2` (134 dominios, 13-oct) y `SOURCES_V3` (97, 7-nov; solo sirve de semilla del registro). En `fbi/analyst/provenance.py`: 51 oficiales y 47 reputados. En `fbi/evidence/rules.py`, `DOMAIN_TIERS` reúne 304 dominios (A 84, B 48, C 116, D 56). Su `DOMAINS_DIGEST` es `7ed11932d969`, el mismo en la imagen desplegada `predigol-backend:5ae050a9c56a`.
- **El registro.** `ai.sources` tiene 402 filas y todas son semilla; ninguna la añadió el dueño. Reparto: media 187, club 90, aggregator 47, competition 42, official 25, social 9, journalist 1 y provider 1.
- **Lo que se hizo.** Se clasificaron los dominios sin nivel que suman más del 90 % de esos ítems. Después se repitieron los niveles y el estado de las afirmaciones con esa clasificación y con la exclusión de pronósticos y agregadores.

## Resultados (tablas con n)

**1. Evidencia web de 30 días por nivel guardado al escribir (n = 6.074).** Las cifras coinciden con las de la medición del 10-nov.

| Nivel guardado | Ítems | % | Dominios | RUMOR | PROBABLE | CONFIRMED | OUTDATED | CONTRADICTORY |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| unknown | 3.560 | 58,6 | 923 | 3.210 | 153 | 59 | 132 | 6 |
| media | 1.247 | 20,5 | 80 | 0 | 933 | 246 | 62 | 6 |
| aggregator | 1.074 | 17,7 | 26 | 967 | 46 | 24 | 30 | 7 |
| club | 118 | 1,9 | 23 | 0 | 0 | 115 | 3 | 0 |
| competition | 71 | 1,2 | 9 | 0 | 0 | 71 | 0 | 0 |
| official | 4 | 0,1 | 2 | 0 | 0 | 4 | 0 | 0 |

En total hay 4.177 RUMOR (68,8 %) y 193 ítems de fuente oficial (3,2 %). Los dominios con más ítems son:

- m.dongqiudi.com: 330 (300 RUMOR).
- mediapronos.com: 242 (238 RUMOR).
- qiumiwu.com: 189, repartidos en 3 subdominios (188 RUMOR).
- as.com: 131.
- bbc.com y bbc.co.uk: 68 y 60.
- sport.sky.it: 77.
- whoscored.com: 76.
- sportsmole.co.uk: 72.
- tuttomercatoweb.com: 63.
- sport.fr: 58.
- bollsvenskan.se: 58.
- injuriesandsuspensions.com: 54.

**2. Ítems sin nivel y reparto por nivel A–D (n = 6.074).**

| Lectura | Sin nivel | % | A | B | C | D |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Guardado al escribir; motor con ese nivel (3.483 «unknown source») | 3.560 | 58,6 | 193 | 637 | 620 | 4.624 |
| Hoy: listas y registro actual | 3.398 | 55,9 | 255 | 637 | 643 | 4.539 |
| Propuesta, solo filas del registro (datos) | 284 | 4,7 | 407 | 637 | 2.058 | 2.972 |
| Propuesta y 24 medios añadidos a `REPUTABLE_DOMAINS` (código, tras Gate B) | 284 | 4,7 | 407 | 746 | 1.949 | 2.972 |

Hay 162 ítems guardados como «unknown» cuyo dominio ya tiene nivel hoy:

- 67 de agregadores y 10 de medios de `SOURCES_V2`, sembrados el 13-oct.
- 62 de clubes y 23 de medios de `SOURCES_V3`, sembrados el 7-nov.

Con la propuesta, la parte oficial pasa del 3,2 % al 6,7 %.

Reparto por categoría del registro con la propuesta (n = 6.074):

| Categoría | media | aggregator | aggregator, excluido | club | competition | official | sin nivel |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Ítems | 2.695 | 1.701 | 987 | 320 | 79 | 8 | 284 |

Los 1.701 ítems de `aggregator` son los 1.141 de agregadores ya registrados y los 560 de «otro».

**3. Concentración de los ítems sin nivel de hoy (3.398 ítems, 885 hosts, 872 dominios registrables).**

| Cobertura de los ítems | 50 % | 80 % | 90 % | 95 % | 100 % |
| --- | ---: | ---: | ---: | ---: | ---: |
| Dominios necesarios | 124 | 391 | 561 | 703 | 872 |

284 dominios tienen 1 ítem y 209 tienen 2. Se clasificaron los 588 que tienen 2 ítems o más: suman 3.114 ítems, el 91,6 % de los que hoy no tienen nivel.

**4. Clasificación propuesta (588 dominios, `lab/IA_040/dominios_propuestos.csv`).**

| Categoría | Nivel | Tier del registro | Excluir | Dominios | Ítems 30 d |
| --- | --- | --- | --- | ---: | ---: |
| Medio general (prensa local y regional, webs con redacción) | C | media | no | 269 | 1.306 |
| Agregador (copia, granjas de contenido, resultados en directo, espejos) | D | aggregator | sí | 63 | 665 |
| Otro (blogs de aficionados, fútbol fantasía, identidad no clara) | D | aggregator | no | 134 | 560 |
| Página de pronósticos o apuestas | D | aggregator | sí | 48 | 316 |
| Oficial (44 clubes, 2 ligas, 2 federaciones) | A | club, competition, official | no | 48 | 152 |
| Medio reputado (prensa nacional de referencia, radiotelevisión pública, agencias) | B (C mientras no esté en `REPUTABLE_DOMAINS`) | media | no | 24 | 109 |
| Otro no informativo (reventa de entradas) | D | aggregator | sí | 2 | 6 |
| Red social | — | — | — | 0 | 0 |

Los mayores son:

- qiumiwu.com (189): agregador; publica listas de bajas en plantilla en 3 subdominios espejo.
- maxifoot.fr (46): medio general.
- btfnews.com (40): agregador.
- sina.cn (38): agregador.
- alphanews.live (32): medio general.
- thestatszone.com (32) y whichbookie.co.uk (31): pronósticos.
- onefootball.com (29): agregador.
- ysscores.com (26): agregador.
- spelkanalen.se (25): pronósticos.

60 dominios (247 ítems) llevan en el CSV la marca «identidad no verificada»: 55 «otro», 4 agregadores y 1 club.

**5. Exclusión: no leer ni extraer pronósticos, apuestas ni agregadores.** Afirmación = `story_key`, la unidad sobre la que el servidor decide el estado: 4.976 en 30 días. «Útil» = no RUMOR y con jugador (por id o por nombre).

| Conjunto | Ítems | % de 6.074 | v1 / v2 | Con jugador | Útiles | Afirmaciones que alimentan | Solo con estos ítems (desaparecerían) | Mixtas |
| --- | ---: | ---: | --- | ---: | ---: | ---: | --- | ---: |
| Nuevos: agregador, pronósticos y no informativos (113 dominios) | 987 | 16,2 | 836 / 151 | 800 | 81 | 889 | 734 (RUMOR 704, OUTDATED 29, CONTRADICTORY 1) | 155 |
| Agregadores ya registrados (29 dominios con ítems) | 1.141 | 18,8 | 1.000 / 141 | 1.040 | 102 | 1.112 | 947 (RUMOR 912, OUTDATED 29, CONTRADICTORY 6) | 165 |
| Ambos | 2.128 | 35,0 | 1.836 / 292 | 1.840 | 183 | 1.951 | 1.716 (RUMOR 1.651, OUTDATED 58, CONTRADICTORY 7) | 235 |

Ninguna afirmación que desaparecería estaba en PROBABLE ni en CONFIRMED. Las 235 mixtas conservan el estado que les daba otra fuente: 81 PROBABLE, 41 CONFIRMED, 106 RUMOR, 6 OUTDATED y 1 CONTRADICTORY.

Los agregadores ya registrados con más ítems son:

- m.dongqiudi.com: 330.
- mediapronos.com: 242.
- whoscored.com: 76.
- tuttomercatoweb.com: 63.
- bollsvenskan.se: 58.
- injuriesandsuspensions.com: 54.
- lineupstoday.com: 46.
- squawka.com: 40.
- jarayid.com: 36.
- 163.com: 29.
- rotowire.com: 27.

Algunos de ellos son de datos, no de copia (whoscored, fotmob, rotowire).

**6. Efecto en el estado de las afirmaciones (n = 4.976).** Reglas base de v1 (`_base_status`), antes y después de la clasificación:

| Estado guardado → con la propuesta | Afirmaciones |
| --- | ---: |
| RUMOR → RUMOR | 2.369 |
| RUMOR → PROBABLE | 1.038 |
| RUMOR → CONFIRMED (dos medios independientes) | 283 |
| PROBABLE → PROBABLE | 960 |
| PROBABLE → CONFIRMED | 60 |
| CONFIRMED → CONFIRMED | 266 |

En la escalera `ladder-v1` del motor, contando cada dominio registrable como un medio:

| Escalera del motor | RUMOR | REPORTADO | CONFIRMADO | OFICIAL |
| --- | ---: | ---: | ---: | ---: |
| Antes | 3.686 | 1.038 | 63 | 189 |
| Con la propuesta | 2.369 | 2.104 | 105 | 398 |

Si además se aplica la exclusión, desaparecen 1.716 afirmaciones, todas en RUMOR.

## Conclusiones

1. **El hueco está concentrado y se cierra con datos.** Hoy 3.398 ítems (55,9 %) siguen sin nivel. Con las 588 filas propuestas quedan 284 (4,7 %), todos de dominios con un solo ítem, y en la repetición G-FUENTES 1 (< 20 %) se cumple con margen. Casi todo el volumen sin nivel es prensa local (269 dominios, 1.306 ítems) o agregadores y pronósticos (111 dominios, 981 ítems). Los oficiales nuevos son pocos (48 dominios, 152 ítems), pero llevan la parte oficial del 3,2 % al 6,7 %.
2. **Las filas nuevas del registro no cambian lo ya guardado.** El motor toma como respaldo el nivel que se guardó al escribir, no el registro vigente. Por eso 162 ítems siguen como «unknown» aunque sus dominios se registraron el 13-oct y el 7-nov. Para que el registro depurado cuente en la sombra y en el gate, el motor tiene que consultar el registro vigente (cambio de código, tras Gate B). La otra opción es medir el gate solo sobre ítems escritos después de cargar las filas.
3. **Excluir pronósticos y agregadores no quita ninguna afirmación por encima de RUMOR.** Los 987 ítems nuevos excluidos (16,2 %) alimentan 889 afirmaciones. Las 734 que desaparecerían eran RUMOR, OUTDATED o CONTRADICTORY, y las 155 mixtas conservan el estado que les daba otra fuente. Con los agregadores ya registrados (2.128 ítems, 35,0 %) el resultado es el mismo. Solo se pierde la noticia temprana que únicamente recogió un agregador, que ya era RUMOR.
4. **La reclasificación cambia etiquetas, no información.** Con las reglas de v1, 1.321 de 4.976 afirmaciones (26,5 %) dejarían de ser RUMOR: 1.038 pasarían a PROBABLE y 283 a CONFIRMED por «dos medios independientes», aunque esos medios sean prensa local. En el motor, REPORTADO se duplica (de 1.038 a 2.104). La bajada del 68,8 % de RUMOR sería, en buena parte, efecto de la etiqueta. Por eso conviene tres cosas:
   - activar en sombra después del Gate B, junto con la credibilidad aprendida (`INT-B10`);
   - revisar la regla «dos medios = CONFIRMED» cuando los dos son de nivel C;
   - tener en cuenta que la parada de la búsqueda por niveles (`KNOWN_STANDING` = medio) llegaría antes: en 30 días se habrían hecho 310 búsquedas menos, US$ 4,65, según la medición de `IA-043`.
5. **El registro solo distingue A, C y D, y las filas oficiales deben revisarse antes de activarlas.**
   - Una fila «media» da C salvo que el dominio esté en `REPUTABLE_DOMAINS`, en el código. Los 24 medios propuestos como B (109 ítems; por ejemplo gsp.ro, dhnet.be, nrk.no o aa.com.tr) necesitan ese cambio de lista.
   - El registro no tiene una categoría D neutra. Por eso los «otro» van como `aggregator`, con la exclusión en una columna aparte.
   - Las 48 filas oficiales dan nivel A, que basta para OFICIAL. Hay que revisarlas a mano antes de activarlas, empezando por fckudrivka.com (sin verificar).

## Limitaciones

- **Clasificación a mano.** Se hizo con el nombre del dominio, los títulos, las URL y las afirmaciones guardadas, más conocimiento previo. Hubo 8 búsquedas web rápidas, sin scraping, solo para identidades dudosas. 60 dominios (247 ítems) quedan con identidad no verificada. Separar «medio general» (C) de «otro» (D), sobre todo en las webs de aficionados, es cuestión de criterio.
- **Dominio registrable aproximado.** Se calculó con una regla simple (las dos últimas etiquetas, o tres si la penúltima es un segundo nivel genérico de país), sin la lista pública de sufijos.
- **La repetición no es una ejecución completa de `evidence_for`.** Recalcula el nivel con `fbi.evidence.rules.tier_of` y el estado con versiones simplificadas: las reglas base de v1 por `story_key`, sin las de OUTDATED y CONTRADICTORY por sujeto, y la escalera del motor por `story_key`, con medio = dominio registrable y sin credibilidad aprendida.
- **Ventana y estados.** 30 días. Research v2 solo cubre desde el 4-nov (899 ítems). Los estados son los guardados el 11-nov.
- **Estado compartido en v1.** Todos los ítems de una historia comparten su estado, así que los «útiles» de los dominios excluidos lo son gracias a otra fuente.
- **Detalle de ejecución.** zougla.gr (2 ítems) se añadió después de la primera repetición. Las cifras de las tablas 2 y 4 lo incluyen; las de las tablas 5 y 6 no, con una diferencia de 2 ítems o menos.

## Cómo se midió

- **Ventana y consultas.** Ventana fija [2026-10-12 04:30, 2026-11-11 04:30) UTC. Consultas de solo lectura (`default_transaction_read_only`, `statement_timeout` 95 s) en `predigol-postgres`, de una en una. `ai.evidence` tiene unas 17.800 filas (24 MB) y `ai.sources` 402.
- **`consultas/q1.sh`.** Recuentos por nivel guardado, estado, generación y día.
- **`q2.sh`.** Exporta los 6.074 ítems y el registro a `/tmp/lab_B01` y calcula los tres niveles en la imagen del backend sin red (`docker run --network none`), con `fbi.evidence.rules` del código desplegado.
- **`q3.sh` a `q5.sh`.** Tabla de dominios sin nivel con títulos y una URL de muestra.
- **`q6.sh` y `q7.sh`.** Repetición con la clasificación (subida como lista dominio → código), exclusión, efecto en los estados y recuento por dominio para el CSV.
- **Tabla de trabajo.** `consultas/clasif.tsv`.
- **Limpieza.** La carpeta temporal del servidor se borró al terminar. No se escribió nada en la base de datos ni en el código.
