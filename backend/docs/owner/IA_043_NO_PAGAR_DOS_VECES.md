# IA-043 — No pagar dos veces

*Plan Maestro de Evolución de PrediGol Intelligence 2026, pieza INT-B07, ola 1. Medido el 11-nov-2026 en producción, solo lectura.*

## Qué se midió

Se usó la ventana [12-oct-2026 04:30, 11-nov-2026 04:30) UTC, la misma de `IA-040`. Se midieron cuatro cosas:

1. Cuántas lecturas son copia exacta o casi exacta de otra anterior: simhash de 64 bits sobre tejas de 3 palabras, distancia de Hamming ≤ 3 (Manku, Jain y Das Sarma, 2007). Se separó si la copia es del mismo partido o de otro, del mismo día o de otro, y cuántas URL se leyeron más de una vez. Se midió en tres planos:
   - las páginas que leyó el extractor;
   - los resultados que devolvió Exa;
   - los ítems de evidencia web.
2. Cuántas extracciones (`ai.usage`, `evidence_extraction`) y búsquedas de Exa (`web_search`) se habrían ahorrado con huella antes de extraer y con lectura incremental por entidad y tema, en llamadas y en US$, con los costes reales del registro de gasto.
3. El rendimiento por fuente: ítems → afirmaciones útiles → coste.
4. Un diseño con su ahorro esperado y su riesgo.

**Gasto de investigación en la ventana (`ai.usage`).**

| Concepto | Llamadas | US$ | Tokens de entrada / salida / en caché |
| --- | ---: | ---: | --- |
| Extracción v1 | 1.083 | 0,8127 | 4.564.195 / 808.942 / 597.135 |
| Extracción v2 (`claim_extractor`) | 269 | 0,2178 | 1.636.895 / 169.592 / 380.729 |
| Búsquedas de Exa (todas pagadas por v1) | 1.479 | 22,1850 | — |
| **Total** | | **23,2155** | Las búsquedas son el 95,6 % |

Research v2 no pagó ninguna búsqueda. Sus 366 necesidades las respondió la caché de búsquedas que había pagado v1, y además reutilizó 75 respuestas por entidad.

## Resultados (tablas con n)

**1. Copias.** Las páginas leídas se reconstruyeron con las marcas de URL leída (`ai.research_cache`, ámbito `url`), ligadas a su llamada por partido e instante. El texto es el título y el texto que devolvió Exa.

| Páginas leídas | v1 + v2 | Solo v1 |
| --- | ---: | ---: |
| Lecturas (n) | 7.351 (7.196 con texto) | 5.904 |
| Copia de una lectura anterior (exacta o ≤ 3 bits) | 1.432 (19,5 %) | 90 (1,5 %) |
| · exacta, mismo partido, mismo día | 1.338 | 7 |
| · exacta, otro partido, mismo día | 52 | 46 |
| · exacta, otro partido, otro día | 35 | 31 |
| · casi (1–3 bits), otro partido, otro día | 5 | 5 |
| · casi, mismo partido, mismo día | 2 | 1 |
| URL leídas más de una vez (lecturas sobrantes) | 1.392 (1.455) | 68 (113) |
| Páginas de v2 que v1 ya había leído en la misma pasada | 1.323 de 1.447 (91,4 %) | — |

De las 90 copias de v1:

- 82 son la misma URL;
- 4 son otra URL del mismo dominio;
- 4 son otro dominio.

Las producen sobre todo páginas de resumen de liga que se leen para varios partidos: aleagues.com.au (10), bundesliga.com (8), sportsgambler.com (6), exa.ai (6) y scorevoro.com (5).

En los resultados de Exa guardados en caché hay 10.536 resultados y 8.475 URL distintas. 1.540 URL salieron en más de una búsqueda, con 2.061 apariciones repetidas.

En los ítems de evidencia (título y afirmación, n = 6.074), 227 (3,7 %) copian un ítem anterior:

- 214 son exactos, del mismo partido y del mismo día;
- 11 son casi copias, del mismo partido y del mismo día;
- 2 son exactos, de otro partido y del mismo día;
- ninguno es de otro día.

215 de los 227 repiten el texto de un ítem anterior de la misma URL; no se comprobó si salieron de la misma llamada. Los dominios que más aportan son mediapronos.com (31), maxifoot.fr (15) y dongqiudi.com (14). 71 URL tienen ítems de más de una lectura (76 sobrantes).

**2. Ahorro simulado en extracción (US$ reales de `ai.usage`, 30 días).** El coste por llamada de v1, ajustado sobre 1.050 llamadas con 5,62 páginas de media, es US$ 0,000246 + US$ 0,000085 por página.

| Regla | v1: páginas | v1: llamadas enteras (parciales) | v1: US$ | v2: páginas | v2: llamadas enteras (parciales) | v2: US$ |
| --- | ---: | --- | ---: | ---: | --- | ---: |
| I · Lectura incremental por entidad: misma URL ya leída para los dos equipos en 7 días (la regla de v2) | 18 | 0 (10) | 0,0015 | 1.323 | 232 (15) | 0,1911 |
| H · Huella antes de extraer: casi copia (≤ 3 bits) ya leída para los dos equipos en 7 días | 26 | 0 (18) | 0,0022 | 1.323 | 232 (15) | 0,1911 |
| G · Cota superior: casi copia ya leída para cualquier partido (pierde matices) | 132 | 0 (111) | 0,0113 | 1.325 | 232 (17) | 0,1913 |
| Gasto real | — | 1.083 | 0,8127 | — | 269 | 0,2178 |

Todo el ahorro de v2 sale de las páginas que v1 ya había leído en la misma pasada. Ese es el coste de la comparación en sombra.

**3. Ahorro simulado en búsquedas (1.479 pagadas, US$ 0,015 cada una).**

Contexto:

- 829 partidos, con 1,78 búsquedas de media y 6 como máximo.
- 825 de los 829 partidos se buscaron un solo día.
- 162 consultas se pagaron dos veces al caducar la caché (US$ 2,43).

| Regla | Búsquedas evitadas | US$ |
| --- | ---: | ---: |
| E · Reutilizar la respuesta por entidad y tema, con la frescura de v2 (24 h; 4 h a menos de 12 h del saque) | 0 | 0 |
| C · Pedir solo lo publicado desde la última lectura de esa entidad y tema | 0 búsquedas; 1.457 de 11.408 páginas con texto (12,8 %) ya devueltas para la misma entidad y tema en 7 días | 1,46 a la tarifa de Exa (US$ 1 por 1.000 páginas). En `ai.usage` no se ve, porque registra US$ 0,015 fijos por búsqueda |
| S · Registro de `IA-040` y regla actual de parada en el primer nivel con una fuente de nivel conocido | 310 (178 de nivel 2 y 132 de nivel 3, en 191 pasadas) | 4,65 |

Con la regla S se habrían dejado de leer ítems que solo salieron de esas búsquedas. Es una cota superior, porque el lector habría leído otras páginas del nivel 1.

- 139 ítems en total, 113 de ellos con jugador.
- 18 con jugador en PROBABLE o CONFIRMED, 7 de ellos de fuente oficial.
- Por estado: 114 RUMOR, 15 PROBABLE, 6 CONFIRMED, 3 OUTDATED y 1 CONTRADICTORY.

**4. Rendimiento por fuente (30 días).** La categoría sale del registro actual y de la clasificación de `IA-040`. El coste de búsqueda de cada dominio viene de `ai.source_stats` (el reparto que hace el servidor). El de extracción reparte cada llamada a partes iguales entre sus páginas. «Útil» se cuenta de tres maneras:

- no RUMOR y con jugador (por id o por nombre);
- PROBABLE o CONFIRMED y con jugador;
- «exclusiva»: la fuente es la única de esa afirmación.

| Categoría | Dominios | Resultados Exa | Páginas leídas | Ítems | Con jugador | Útiles no RUMOR | Útiles P/C | Exclusivas | US$ | US$ por útil P/C |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Medio | 394 | 3.022 | 2.510 | 2.695 | 2.325 | 1.236 | 1.114 | 710 | 6,03 | 0,005 |
| Oficial | 116 | 631 | 499 | 407 | 311 | 162 | 152 | 94 | 1,25 | 0,008 |
| Otro | 136 | 518 | 368 | 566 | 510 | 79 | 51 | 0 | 1,03 | 0,020 |
| Agregador | 102 | 1.944 | 1.390 | 1.806 | 1.599 | 152 | 93 | 0 | 3,84 | 0,041 |
| Pronósticos o apuestas | 48 | 757 | 501 | 316 | 235 | 31 | 16 | 0 | 1,49 | 0,093 |
| Sin nivel | 1.605 | 4.960 | 2.083 | 284 | 158 | 28 | 16 | 0 | 9,54 | 0,596 |
| **Total** | 2.401 | 11.832 | 7.351 | 6.074 | 5.138 | 1.688 | 1.442 | 804 | 23,17 | 0,016 |

Fuentes que no aportan, con una medida que no depende del nivel (ningún ítem con jugador):

- 39 dominios con 10 páginas leídas o más: 862 páginas, 1.761 resultados, US$ 3,30 en búsqueda y US$ 0,10 en extracción. Los mayores son exa.ai (93 páginas, US$ 0,48), apwin.com (77; 0,46), xscores.com (64; 0,18), sokalive.com (46; 0,15), pitchsidelab.com, soccersite.com, betimate.com, previaxi.com, kickoffhour.com, mynet.com y footballpark.com.
- Con 5 páginas o más son 93 dominios y US$ 4,55.
- De los 39, 3 son oficiales: the-afc.com, por ejemplo, tiene 36 páginas de calendario y ninguna afirmación con jugador.
- En total, 1.586 dominios que en 30 días no dieron ningún ítem con jugador recibieron 5.516 de los 11.832 resultados (46,6 %), es decir, US$ 10,34 del gasto de búsqueda.

Los contadores propios de v2 en `ai.fixture_passes` (4–10 nov) son:

- 1.498 páginas leídas;
- 243 páginas no mostradas porque ya se habían leído para los mismos sujetos;
- 797 páginas no leídas por quedar más allá de las 6 más fiables;
- 37 respuestas inválidas.

## Conclusiones

1. **Pagar dos veces la extracción casi no ocurre en v1, y la extracción es barata.** Costó US$ 1,03 en 30 días, el 4,4 % del gasto de investigación. Solo el 1,5 % de las lecturas de v1 copia otra anterior, y el 91 % de esas copias es la misma URL. Una huella que tenga en cuenta los sujetos ahorraría 26 páginas (US$ 0,002). La doble lectura de verdad es la de la sombra: v1 ya había leído en la misma pasada el 91,4 % de las páginas de v2 (US$ 0,19 de US$ 0,22). Termina cuando se retire una de las dos generaciones.
2. **Las búsquedas no se repiten por entidad y tema.** Son el 95,6 % del gasto (US$ 22,19). Cada partido se busca un solo día (825 de 829) y los partidos de un mismo equipo están separados por días, así que reutilizar por entidad con la frescura de v2 no evita ninguna búsqueda en esta ventana. Leer por fecha de publicación quitaría el 12,8 % de las páginas con texto, US$ 1,46 a la tarifa de Exa, pero ninguna búsqueda. Además, el registro de gasto no lo vería, porque cobra un precio fijo por búsqueda.
3. **El dinero se va en lo que devuelven las búsquedas.**
   - El 46,6 % de los resultados de Exa (US$ 10,34) viene de dominios que en 30 días no dieron ninguna afirmación sobre un jugador.
   - Cada afirmación útil cuesta US$ 0,005 en medios, 0,008 en oficiales, 0,041 en agregadores, 0,093 en pronósticos y 0,60 en dominios sin nivel.
   - Solo medios (710) y oficiales (94) son alguna vez la única fuente de una afirmación útil. Agregadores, pronósticos y «otro» nunca lo son, en parte por las reglas (una fuente D sola no pasa de RUMOR): sus ítems útiles se apoyan siempre en otra fuente.
4. **El mayor ahorro viene de `IA-040` y cuesta información.** Con el registro propuesto, la regla actual de parada evitaría 310 búsquedas de nivel 2 y 3 (US$ 4,65, el 21 % del gasto de búsqueda). A cambio perdería, como máximo, 139 ítems; 18 de ellos útiles y 7 oficiales con jugador. El coste por afirmación útil bajaría de US$ 0,0161 a unos 0,0130, pero se recortaría el nivel que busca confirmación oficial. Es una decisión del dueño, y hay que medirla en sombra.
5. **Diseño propuesto, con ahorro modesto y sin riesgo serio de perder matices** (detalle abajo). Ahorro esperado en 30 días:
   - unos US$ 0,30 en extracción, de los que US$ 0,19 aparecen al retirar v1 o v2;
   - US$ 1,46 en la factura de Exa si se lee de forma incremental;
   - hasta US$ 4,65 en búsquedas si se acepta la parada temprana.

   El gate de partida («coste por afirmación útil igual o menor») queda en US$ 0,0138 por afirmación útil no RUMOR con jugador (23,22 / 1.688), o US$ 0,0161 si se cuenta solo PROBABLE o CONFIRMED (23,22 / 1.442), con las reglas de estado fijas.

**Diseño propuesto.**

- **Huella antes de extraer.** Primero la URL canónica y después simhash de 64 bits sobre título y texto, con tejas de 3 palabras (un carácter por palabra en chino, japonés y tailandés) y un índice de 4 bloques de 16 bits. Una página se salta si ya se leyó una copia a ≤ 3 bits para los mismos sujetos en los últimos 7 días (el `EXTRACT_TTL` actual). El ahorro medido es mínimo. Su valor está en `INT-B10`: reconocer la misma nota en varios medios o subdominios espejo para no contarla como corroboración. El riesgo es casi nulo, porque solo descarta textos casi idénticos y vuelve a leer la página para sujetos nuevos. Va detrás de un interruptor.
- **Lectura incremental por entidad y tema.** Se mantiene la clave de URL sin partido de v2, que ya evita 243 relecturas. Se añade `startPublishedDate` igual a la última lectura de esa entidad y tema, con una búsqueda completa de 7 días en la primera pasada del día. Ahorra páginas de texto, no búsquedas. El riesgo es perder un artículo actualizado que conserva su fecha original; la búsqueda diaria completa lo cubre. Conviene registrar el precio por página en `ai.usage` para ver el efecto.
- **Fuentes que no aportan.** Lista mensual por rendimiento medido: 10 páginas o más y ninguna afirmación con jugador en 30 días. Se sumaría a las exclusiones de `IA-040`. Esos dominios no se extraen y se pasan a Exa como `excludeDomains`. No reduce búsquedas, porque Exa cobra por búsqueda, pero libera huecos de resultado. Que eso suba las afirmaciones útiles por búsqueda es una hipótesis, que se prueba con `INT-B02`. Los dominios oficiales nunca van a la lista.
- **Parada temprana.** Hay que decidir si la regla de parada pide «medio o mejor» (hoy) o «nacional u oficial» (B o mejor) cuando entre el registro de `IA-040`. Se mide en sombra contra el gate.

## Limitaciones

- **Lecturas reconstruidas.** Salen de marcas de caché, no de un registro de lecturas. v2 solo conserva la última lectura de cada URL (1.447 frente a 1.498 en sus contadores), 28 marcas de v2 no se pudieron ligar a una URL y 33 llamadas de v1 quedaron sin páginas.
- **Texto de las páginas.** Es el título y el texto de la caché de búsquedas. Si una consulta se volvió a pagar (162 claves), queda su versión posterior. 155 lecturas no tienen texto y solo cuentan por URL.
- **«Útil» depende del estado guardado.** En v1, todos los ítems de una historia comparten su estado, y los dominios sin nivel son RUMOR por construcción. Por eso se añadieron las útiles exclusivas y los ítems con jugador por página, que no dependen del nivel.
- **Simulaciones contrafactuales.**
  - El coste parcial de una llamada usa un ajuste lineal.
  - La pérdida de la regla S es una cota superior.
  - El precio por página de Exa es la tarifa del proveedor, no un dato del registro.
  - La regla H exige que la copia anterior se leyera para los dos equipos. Una regla por equipo ahorraría algo más, pero necesitaría saber de qué equipo habla la página.
- **Muestra de v2.** Research v2 solo tiene 7 días de datos.
- **Huella.** Los textos de menos de 3 palabras no tienen huella y solo cuentan como copia exacta.

## Cómo se midió

- **Lectura.** Solo lectura, misma ventana fija y mismas reglas que `IA-040`.
- **`consultas/q8.sh`.** Resúmenes en SQL de `ai.usage`, `ai.research_cache` y `ai.fixture_passes`. Exporta a `/tmp/lab_B07`:
  - `ai.usage` de extracción y búsqueda (2.831 filas);
  - los resultados de las búsquedas en caché (10.536, texto hasta 2.000 caracteres);
  - las marcas de URL leída (8.019);
  - los partidos (829);
  - `ai.source_stats`;
  - los ítems de `IA-040`.
- **`q9.sh` (`b1.py`).** Copias, simulaciones I, H, G, E, S y C, y rendimiento por categoría.
- **`q10.sh` (`b2.py`).** Útiles exclusivas, fuentes sin aporte y qué traían las búsquedas evitables.
- **`q11.sh` (`b3.py`).** Tipo de copia (misma URL, mismo dominio u otro dominio).
- **Cálculo.** Todo se calculó con Python y numpy en la imagen `predigol-backend:5ae050a9c56a`, sin red. `canonical_url` y `url_key` se importan de `fbi.ai.cache` para ligar las marcas de v2. Cada teja se resume con blake2b de 8 bytes y el umbral es k = 3.
- **Prueba previa.** Los scripts se probaron antes con datos sintéticos.
- **Limpieza.** La carpeta temporal del servidor se borró al terminar. No se escribió nada en producción.
