# IA-048 · Falsos rechazos del verificador de la crónica (sigue IA-024 e IA-032)

Pieza INT-D01 del Plan Maestro de Intelligence 2026. Cambia solo reglas del verificador de la crónica de los lectores (`fbi.narrative.job`). No toca el prompt (`user-narrative-v3`), ni el `input_hash`, ni presupuestos, interruptores, umbrales, modelos ni nada de Intelligence.

## 1. Qué se midió (solo lectura, 11-nov-2026)

Tabla `ai.user_narratives`, versión `user-narrative-v3`. Desde el despliegue de IA-032 (10-nov 09:46 UTC) hasta la última tanda escrita (11-nov 05:39 UTC): **19 crónicas rechazadas** (ids 738–757), 2 con salida inválida (746 y 758) y 1 aprobada (759). Las 19 rechazadas suman **139 frases rechazadas** (más 5 traducciones de noticias rechazadas, que no cuentan para aprobar o rechazar). Cada rechazo se clasificó leyendo el texto guardado:

| Clase | Frases | Causas |
| --- | ---: | --- |
| Verdadero | 101 | 41 rumor fuera de «riesgos» · 22 más de 4 referencias en una frase · 10 sección vacía o distinto número de frases en español e inglés · 8 más frases de las que permite la sección · 5 noticia probable contada sin atribuir · 4 rumor contado como hecho · 4 referencias que no se le dieron · 3 palabras prohibidas («apuestas», «betting», «stake») · 2 cifras sin referencia («nueve»/«nine») · 1 factor descriptivo convertido en causa · 1 referencias distintas en los dos idiomas |
| Falso | 19 | 13 rumor que la frase sí llama no confirmado, con otras palabras («no está confirmada», «no están verificadas», «sin confirmación», «unverified», «no other source confirms it»…) · 5 «starting eleven» leído como 11 · 1 «del once» frente a «XI» |
| Falso probable | 8 | comparación español/inglés de la que solo se guarda el inglés, que cambia con la regla nueva («League Two», «starting eleven») |
| Indeterminado | 11 | 8 comparaciones español/inglés sin el texto español («both», «matchday four»…) · 3 textos cortados a 200 caracteres |

**Ninguna de las 19 habría pasado arreglando solo los falsos**: 18 tienen al menos un rechazo verdadero; la 752 solo tiene dos comparaciones «both» indeterminadas, que la regla nueva no toca. Lo que hoy rechaza la crónica es, sobre todo, el prompt (rumores fuera de «riesgos», frases con demasiadas referencias, secciones vacías): eso es de la crónica v4 (INT-D02), no del verificador.

## 2. Qué cambia

Tres reglas acotadas, cada una con sus pruebas de lo que debe pasar y de lo que se debe seguir rechazando (`tests/unit/test_user_narrative.py`, las que terminan en `_ia048`):

1. **Un rumor o una contradicción llamados por su nombre** (`RUMOUR_WORDS`). La negación tiene que ir pegada a la confirmación, como ya lo estaba «no confirmada»: «no está confirmada», «no han sido verificadas», «de calidad no verificada», «sin confirmación», «sigue sin confirmarse», «no pudo verificarse», «el club no lo ha confirmado», «es una previsión, no una baja confirmada», «no se ha publicado una alineación confirmada», «son previsiones, no alineaciones oficiales», «ninguna otra fuente la confirma»; en inglés «unverified», «has not been confirmed», «could not be verified», «the reports do not confirm», «no confirmed line-up», «not a confirmed absence», «not official line-ups», «no confirmation», «no other source confirms it». Y la contradicción **nombrada junto con las informaciones** a las que se refiere: «las informaciones no coinciden», «las fuentes difieren», «contrasta con las informaciones», «reports conflict», «reports on X conflict», «which conflicts with reports», «sources differ», «details that do not match» (aunque entre las informaciones y el verbo haya un nombre que la comprobación quita antes de leer).
2. **El once titular en inglés no es un número** (`LINEUP`): «starting/first/same/usual/changed… eleven», «the eleven may differ»; y en español, además de lo de IA-032, «del once» y «al once». Se quita antes de leer las cifras de la frase y antes de comparar los idiomas. «eleven matches», «the first eleven minutes» y «the same eleven players» siguen siendo once de algo y se comprueban.
3. **Un número dentro de un nombre no es una cantidad al comparar idiomas** (`_numbers_key`): «League Two», «Once Caldas», «AFC Champions League Two», «Dos Santos». La comprobación de cada idioma ya los leía así; la comparación entre idiomas no. Las cifras se siguen leyendo tal como están escritas («FC Schalke 04» en un idioma y «Schalke 04» en el otro no dejan un 04 suelto). El falso rechazo de «League Two» lo introdujo IA-024 al contar «two».

**Se sigue rechazando**, y hay pruebas de ello: un rumor fuera de «riesgos» aunque se llame no confirmado; una frase que solo dice que algo es incierto, desconocido, «queda por confirmar» o «está en evaluación» (cuenta el contenido del rumor como hecho); una frase que solo atribuye («según un agregador», «Sky Sport lo da como duda»); una frase que describe el choque sin nombrarlo («un reporte la da como duda, mientras otras fuentes la dan de baja»); un «conflict» o un «no coinciden» que no habla de las informaciones («which conflicts with the coach's plans»); y una cantidad o un marcador distinto entre idiomas.

## 3. Repetición sobre todas las crónicas guardadas

Solo lectura, en el contenedor del worker, con el verificador desplegado (IA-032) y el nuevo sobre las mismas entradas: la entrada de cada crónica se reconstruye en su momento (`reading_basis` + relato + noticias) y se compara su hash con el guardado. 720 crónicas `v3` (300 aprobadas, 420 rechazadas; las 24 con salida inválida no tienen texto que verificar), 11-nov 06:22 UTC, código nuevo con `sha256` 650036ce6d3f1400…

**Aprobadas (300; las 300 entradas reproducidas con el mismo hash).**

| Verificador desplegado → nuevo | Crónicas |
| --- | ---: |
| aprueba → aprueba | 257 |
| rechaza → aprueba | 20 |
| rechaza → rechaza | 23 |
| **aprueba → rechaza** | **0** |

Las 43 que el verificador desplegado ya rechazaría se aprobaron entre el 7-nov 05:26 y el 9-nov 00:55 UTC, antes de que IA-024 (9-nov 20:16 UTC) cambiara la comparación entre idiomas; las 43 por «el inglés dice otras cifras que el español». De los 4.138 pares de frases español/inglés de las aprobadas: 4.076 coinciden con las dos reglas, **37 dejan de discrepar** (nombres como «League Two», «Once Caldas», «Dos Santos»; el once), 25 siguen discrepando y **ninguno pasa a discrepar**. Los 25: 18 son la asimetría «los dos»/«ambos» frente a «both»/«the two» que IA-032 dejó a propósito; 1 dice «dos derrotas en las dos últimas» frente a «lost its last two»; 5 dicen de verdad cosas distintas (36: «sin margen» frente a «two points above»; 156: «un punto» frente a «two points»; 273, 503 y 523: rachas distintas) y 1 está cortado (413). Esas 5 se publicaron con el español y el inglés diciendo cifras distintas; el verificador actual ya las rechazaría.

**Rechazadas (420; 413 entradas reproducidas, 7 no).** De una rechazada solo se guardan las frases rechazadas (texto hasta 200 caracteres y motivo), así que cada rechazo se juzga por separado y una crónica «pasaría» solo si se levantan todos sus rechazos con seguridad (suponiendo que lo que el verificador desplegado dejó pasar lo sigue dejando pasar el nuevo, como ocurre en las 300 aprobadas).

| Rechazo guardado | Se levanta | Se mantiene | Indeterminado |
| --- | ---: | ---: | ---: |
| Rumor o contradicción no llamados por su nombre (107) | 64 | 41 | 2 (texto cortado) |
| Rumor o contradicción fuera de «riesgos» (254) | 0 | 254 | 0 |
| El inglés dice otras cifras que el español (236) | 2 | 4 | 230 (falta el texto español) |
| Cifras que no están en lo que cita (130) | 0 | 123 | 7 (se va el «eleven», pero lo que viene detrás necesita las referencias, que no se guardan) |
| Todos los demás motivos | 0 | todos | 0 |

**5 crónicas rechazadas habrían pasado** (22, 138, 298, 544 y 703): cada una se rechazó solo por frases de «riesgos» que llamaban al rumor no confirmado con las palabras nuevas («no está confirmada», «no official confirmation», «could not be verified» / «no pudo verificarse»). 336 siguen rechazadas por al menos un rechazo que no cambia y 79 quedan indeterminadas. De las 19 rechazadas desde IA-032, **ninguna** pasaría (18 siguen rechazadas, la 752 indeterminada). No se reescribe ninguna: la regla vale para las crónicas que se escriban a partir de ahora.

Los 41 rechazos de «rumor no llamado rumor» que se mantienen: 13 solo dicen que algo es incierto, desconocido o está en evaluación y cuentan el contenido como hecho («La lesión de rodilla de Helik sigue en evaluación…»); 16 solo atribuyen («Infobetting lists… as out»); 3 describen el choque sin nombrarlo; 8 citan el rumor solo para decir que no trae datos, y 1 solo dice que las alineaciones probables «son estimaciones» (apartado 5).

**El rumor como hecho no pasa.** La regla «rumor fuera de riesgos» no cambia (254 rechazos, los 254 se mantienen). Los 64 rechazos de «rumor no llamado rumor» que la regla nueva levanta se leyeron uno a uno: todos dicen, con esas palabras, que la noticia no está confirmada o que las informaciones chocan; ninguno cuenta el rumor como hecho. El que más se acerca es «According to an unverified outlet, George Evans reportedly returned…» (742), atribuido y con la fuente marcada como no verificada.

## 4. Lo que no se puede medir

* De una crónica rechazada no se guarda el contenido, solo las frases rechazadas, cortadas a 200 caracteres, y sin sus referencias. Las comprobaciones que van detrás de la del rumor solo miran frases que citan la previsión de PrediGol; no se puede comprobar que estas no lo hagan.
* En una discrepancia español/inglés se guarda solo la frase inglesa: si la española no se rechazó por otra cosa, no está, y la comparación queda indeterminada.
* 7 crónicas rechazadas no se pueden reconstruir con el mismo hash (su historia cambió después).
* Lo que pasaría con las crónicas nuevas no se puede medir hasta que se escriban: las rechazadas **no se vuelven a pedir** (el `input_hash` no depende del verificador).

## 5. Decisiones que quedan para el dueño

* **«los dos»/«ambos» frente a «both»/«the two»**: se deja como decidió IA-032 (contarlos rechazaba crónicas aprobadas que dicen lo mismo). Son 18 de los 25 pares que siguen discrepando.
* **Frases que citan un rumor solo para decir que no trae datos** («the visible text reports no line-ups», «no starting line-up is detailed»; 8 frases de las crónicas 66, 89, 707 y 717) o que la alineación probable «son estimaciones, por lo que pueden cambiar» (622): la regla las rechaza porque citan el rumor sin llamarlo rumor. No cuentan un rumor como hecho, pero una regla de vocabulario para ellas dejaría pasar frases que sí lo hacen. Propuesta: que el prompt v4 no cite un rumor para decir que no dice nada.
* **Frases que describen el choque sin nombrarlo** (3 frases de las crónicas 691 y 739): siguen rechazadas; la regla quiere la contradicción nombrada.
* **Atribuir una noticia probable por el nombre del medio** («diadejogo.pt informa…»): desde IA-032 solo hay un caso (755). No se implementa: nombrar un medio que no es la fuente de la noticia no es atribuirla.

## 6. Qué no cambia y vuelta atrás

* Prompt, referencias, `input_hash`, presupuesto, modos (`FBI_USER_NARRATIVE`), tablas: nada. Intelligence no lee nada de esto.
* El verificador del Narrador (`fbi.narrator.verify`, nacido apagado y sin almacenamiento) reutiliza `RUMOUR_WORDS` y `figures` tal cual, por diseño: hereda las mismas reglas. Sus pruebas pasan.
* Cómo se mide el efecto: proporción de frases rechazadas por «a rumour or a contradiction not called one», «numbers not in what it cites: eleven» y «the English says other numbers than the Spanish», por día (consulta de solo lectura sobre `ai.user_narratives.rejected`).
* Vuelta atrás: revertir el PR; no hay migración ni interruptor.
