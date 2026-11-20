# DOC-008 · Cotejo humano del reglamento de la Liga BetPlay 2026 (arts. 27 a 34) antes de publicar una tabla

Plan Maestro PM, tarea **PM-09-02** (OP-20). **Estado: pendiente del dueño.** Este documento es el paquete para que una persona
(el dueño o quien designe; unas dos horas) compare con el PDF oficial en pantalla lo que PrediGol tiene codificado para la
reclasificación, los cupos internacionales y el descenso por promedio. **Nada de esto lo hace ni lo da por hecho una máquina**: el
texto de abajo salió de dos lecturas automáticas (OCR) y el cotejo existe precisamente porque un OCR puede equivocarse. Hasta que el
acta del §5 esté firmada no se publica ninguna tabla de reclasificación, de cupos ni de descenso (DM-14: primero lo demostrado).

No cambia código, reglas ni datos. El fichero de reglas `config/rules/239_primera_a_colombia/v1.yaml` es zona de la sesión de
Intelligence y no se toca a mano (IA-072, §5): si el cotejo encuentra diferencias, se corrigen con una versión nueva (`v2.yaml`).

## 1. El documento que se coteja

| | |
| --- | --- |
| Reglamento | Liga BetPlay DIMAYOR 2026, edición **V0** («V0 - 14/01/26» en el propio PDF) |
| Enlace oficial | <https://dimayor.com.co/wp-content/uploads/2026/04/REGLAMENTO-LIGA-2026-V0.pdf> (lo enlaza el [artículo de la DIMAYOR del 13-abr-2026](https://dimayor.com.co/2026/04/13/reglamento-copa-betplay-dimayor-2026/)) |
| **Huella SHA-256** | **`8b377600d9937c08a2dd9fb6438c769770aa7e54e824d7273f53312dd0b5b0c2`** |
| Tamaño | 11.878.960 bytes, 57 páginas |
| Metadatos del PDF | título «REGLAMENTO-LIGA 2026 -V0»; creado y modificado el 16-abr-2026 22:54 UTC (de ahí el «2026-04-16» de `published` en `v1.yaml`) |
| Servidor | `Last-Modified: Fri, 17 Apr 2026 13:42:57 GMT` |
| Descargado y medido | 20-nov-2026, 06:52 UTC |

Edición anterior en el mismo servidor, solo como referencia (no es la que se coteja): «V12 - 2026/01/09»,
<https://dimayor.com.co/wp-content/uploads/2026/01/REGLAMENTO-LIGA-2026-V12.pdf>, SHA-256
`5c9046b88f633b66538d10cb0bcb826c8c5439b47695566246b71453cc7bdad1` (5.841.829 bytes). La dirección con `-1` que cita `v1.yaml`
(`REGLAMENTO-LIGA-2026-V12-1.pdf`) devuelve **el mismo archivo** (misma huella).

**Antes de empezar, comprueba que tienes el mismo archivo** (si la huella no coincide, la DIMAYOR lo cambió: para y avisa, el cotejo
se hace sobre la versión nueva y este paquete hay que rehacerlo):

```
# Windows (PowerShell), en la carpeta de descargas
Get-FileHash .\REGLAMENTO-LIGA-2026-V0.pdf -Algorithm SHA256
# Linux o macOS
sha256sum REGLAMENTO-LIGA-2026-V0.pdf
```

**Dónde mirar** (número de página del visor de PDF; la capa de texto del archivo arrastra texto de 2025 superpuesto, así que lo
fiable es la imagen de la página):

| Página del PDF | Artículos |
| ---: | --- |
| 17 | 25, 26, **27** (reclasificación) y **28** (empates en la reclasificación) |
| 18 | **29** (goleador y valla menos vencida) y **30** (Libertadores 2027, hasta el parágrafo 1) |
| 19 | **30** (parágrafos 2 a 5) y **31** (Sudamericana 2027) |
| 20 | **32** (tabla de descenso), **33** (desempates del promedio) y **34** (descenso) |

## 2. De dónde sale el texto de este paquete

1. **OCR 1**, 19-nov-2026 (Firecrawl, investigación del Plan Maestro PM): artículos 21 a 34 salvo 28 y 29; resumen en las notas de
   la investigación (sección 6, «Reglamento Dimayor 2026»).
2. **OCR 2**, 20-nov-2026 (Tesseract 5 sobre las páginas 17 a 20 a 200 ppp, hecho para este paquete): artículos 27 a 34 completos,
   también 28 y 29.

Los dos coinciden en todo lo que leen los dos. Abajo se cita lo justo para localizar cada regla; el texto que manda es el del PDF.

## 3. Tabla de cotejo

Para cada fila: lee el artículo en el PDF, compáralo con la columna «Lo codificado» y marca **Coincide** o **No coincide** (con una
nota de qué dice el PDF). «Lo codificado» es `config/rules/239_primera_a_colombia/v1.yaml` en `main` del 20-nov-2026.

| # | Art. (pág.) | Qué dice (OCR 1 y 2) | Lo codificado en `v1.yaml` | Pregunta para el cotejo | Resultado |
| --- | --- | --- | --- | --- | --- |
| 1 | 27 (17) | La reclasificación «resultará de la sumatoria de los puntos obtenidos por los clubes en todos los partidos» de las 4 fases de la Liga I (todos contra todos, cuartos, semifinales, final) y de las 3 fases de la Liga II (todos contra todos, cuadrangulares, final). | `tables.reclasificacion`: `kind: aggregate`, `counts: ["liga_i.*", "liga_ii.*"]` (todas las fases de los dos torneos). | ¿Cuentan **todas** las fases, finales incluidas, y nada más (ni Copa ni Superliga)? | [ ] Coincide [ ] No coincide |
| 2 | 28 (17) | Empate en puntos en la reclasificación, en este orden: 1) mayor diferencia de gol; 2) más goles a favor; 3) más goles a favor como visitante; 4) menos goles en contra; 5) menos goles en contra como visitante — todo «durante todas las Fases» de la Liga I y II 2026 —; 6) sorteo de la DIMAYOR. *(Solo OCR 2: el OCR 1 no lo leyó.)* | `reclasificacion.ranking.tiebreakers: [goal_difference, goals_for, away_goals_for, goals_against_fewer, away_goals_against_fewer, lots]`; nota «art. 27-28». | ¿Mismo orden, sobre todas las fases, y el último criterio es sorteo (no partido extra)? | [ ] Coincide [ ] No coincide |
| 3 | 29 (18) | Goleador y valla menos vencida de la Liga I y II. *(Solo OCR 2.)* | Nada (no afecta a ninguna tabla). | ¿Confirmas que el art. 29 no cambia ninguna tabla ni cupo? | [ ] Confirmado |
| 4 | 30 (18) | Libertadores 2027: «COLOMBIA tiene derecho a 4 cupos»; 2 a fase de grupos (Colombia 1: campeón de la Liga I; Colombia 2: campeón de la Liga II) y 2 a la Fase 2 previa (Colombia 3 y 4: los mejor situados en la reclasificación «sin ser campeones»). | Zona `continental`, `from: 1, to: 4, conditional: true`, destino «Libertadores 2027 (Colombia 3 and 4)», nota «art. 30: the two champions are Colombia 1 and 2; the best placed non-champions take 3 and 4». | ¿El reparto 2 + 2 y el orden (campeones, luego reclasificación sin campeones) son exactamente esos? | [ ] Coincide [ ] No coincide |
| 5 | 30, par. 1 (18) | Si el campeón de la Liga I es también el de la Liga II, los cupos 2, 3 y 4 van a los mejor situados de la reclasificación. | Solo en la idea de la nota («best placed non-champions»); no hay regla propia. | ¿Basta la nota o hace falta codificar el caso «mismo campeón»? La tabla no debe dar cupos como definitivos mientras haya campeones por decidir. | [ ] Coincide [ ] No coincide |
| 6 | 30, par. 2 y 3 (19) | Si un campeón de la Liga 2026 gana además la Libertadores o la Sudamericana 2026 y entra por ahí en la Libertadores 2027, los cupos se reordenan por la reclasificación (par. 2: campeón de los dos torneos; par. 3: campeón de uno, y Colombia 1 pasa al otro campeón). *(Solo OCR 2.)* | No codificado. | ¿Se acepta mostrar la zona como «condicional» sin estos casos, o hay que codificarlos antes de publicar? | [ ] Aceptado como condicional [ ] Codificar |
| 7 | 30, par. 4 y 5 (19) | Par. 4: si un club que desciende gana cupo a Libertadores o Sudamericana 2027 por la Liga, el cupo pasa al mejor situado de la reclasificación. Par. 5: lo no previsto lo asigna la DIMAYOR por la reclasificación. | No codificado (la zona es `conditional: true`). | ¿Igual que la fila 6? | [ ] Aceptado como condicional [ ] Codificar |
| 8 | 31 (19) | Sudamericana 2027: «4 CUPOS PARA FASE PRELIMINAR»; Colombia 1: campeón de la Copa BetPlay 2026; Colombia 2, 3 y 4: los mejor situados de la reclasificación «que NO hayan obtenido cupo a la CONMEBOL LIBERTADORES 2027». | Zona `continental`, `from: 1, to: 8, conditional: true`, destino «Sudamericana 2027 (Colombia 2-4)». | El reglamento no habla de «puestos 1 a 8»: el `to: 8` parece una cota de pantalla (4 de Libertadores + 4 de Sudamericana; el fichero no lo explica). ¿Se acepta como cota o debe calcularse el puesto real? | [ ] Aceptado [ ] Cambiar |
| 9 | 31, par. 1 y 2 (19) | Par. 1: si un club que desciende gana un cupo a la Sudamericana (por la Liga o por la Copa), pasa al mejor situado de la reclasificación sin cupo internacional. Par. 2: lo no previsto, la DIMAYOR por la reclasificación. *(El art. 18 del reglamento de la Copa V1 añade que el campeón de Copa solo es Colombia 1 si juega en la División Principal.)* | No codificado (zona condicional). | ¿Igual que las filas 6 y 7? | [ ] Aceptado como condicional [ ] Codificar |
| 10 | 32 (20) | Tabla de descenso por **promedio**: «se calculará dividiendo el total de puntos obtenidos entre el total de partidos disputados», **solo Fase I** («Todos contra todos») de cada torneo. | `tables.descenso`: `kind: average`, `metric: points_per_match`, `counts: ["liga_i.fase_1", "liga_ii.fase_1"]`, `seasons: 3`; nota «Fase I of the six tournaments 2024-I to 2026-II». | ¿Solo la Fase I, de 2024-I a 2026-II (seis torneos), puntos entre partidos? | [ ] Coincide [ ] No coincide |
| 11 | 32 (20) | Excepciones: **Jaguares FC y Cúcuta Deportivo** (llegan del Torneo 2025): solo Fase I de la Liga I y II 2026. **Llaneros FC**: Fase I de la Liga I y II 2025 y 2026. | `exceptions`: los mismos tres clubes con las mismas ventanas. | ¿Los nombres y las ventanas son exactamente esos? | [ ] Coincide [ ] No coincide |
| 12 | 32 (20) | «El cálculo del promedio se hará en la aplicación de software Excel». | Nada sobre redondeo: el código compararía el cociente sin redondear. | **Pregunta abierta:** ¿la DIMAYOR redondea el promedio (¿a cuántos decimales?) antes de ordenar? Con el desempate del art. 33 el orden no cambia si se compara sin redondear, pero la cifra mostrada sí. Propuesta: mostrar 3 decimales y ordenar por el cociente exacto y el art. 33. | [ ] Aceptar la propuesta [ ] Otra: |
| 13 | 33 (20) | Empate en el promedio: **solo con la Fase I de la Liga I y II 2026**, en este orden: 1) más puntos; 2) diferencia de gol; 3) goles a favor; 4) goles a favor como visitante; 5) menos goles en contra; 6) menos goles en contra como visitante; 7) más partidos ganados. Parágrafo: si sigue el empate, «partido o partidos necesarios» que fije la DIMAYOR. | `descenso.ranking.tiebreakers: [points, goal_difference, goals_for, away_goals_for, goals_against_fewer, away_goals_against_fewer, wins, playoff]`; nota «art. 33: ties … on the sum of Fase I of tournaments I and II 2026 only». | ¿Siete criterios en este orden, sobre 2026 solo, y después partido (no sorteo)? | [ ] Coincide [ ] No coincide |
| 14 | 34 (20) | «Los clubes que ocupen las dos últimas posiciones en la Tabla de Descenso […] descenderán a la Categoría "B" en el año 2027», y los sustituyen los dos que asciendan por el reglamento del Torneo 2026. | Zona `relegation`, `last: 2`, destino «Primera B 2027», **nota «art. 32»**. | ¿Dos descensos? La nota debería citar el **art. 34** (el 32 es la fórmula): ver §4, b. | [ ] Coincide [ ] No coincide |

## 4. Diferencias ya vistas entre `v1.yaml` y el PDF (las confirma el cotejo; las corrige Intelligence con `v2.yaml`)

a. `sources[0].published: 2026-04-16` es la fecha de creación del PDF; la edición es la **V0 del 14-ene-2026** (ya anotado en
   `IA_072_REGLAMENTOS.md`, nota del 20-nov-2026, PM-00-03).
b. La zona de descenso cita el **art. 32**; el descenso de los dos últimos es el **art. 34** (el 32 es la fórmula del promedio).
c. `sources[0].articles: arts. 4-33` no incluye el **art. 34**.
d. `sources[1]` (V12) apunta a `REGLAMENTO-LIGA-2026-V12-1.pdf` con fecha 2026-01-15; el rótulo de esa edición es «V12 -
   2026/01/09» y la dirección sin `-1` es el mismo archivo.
e. Los parágrafos de los arts. 30 y 31 (filas 5 a 9) no están codificados: la zona es `conditional`, que es lo correcto mientras se
   muestre como tal; publicar cupos como definitivos exigiría codificarlos.
f. Redondeo del promedio (fila 12): sin regla.

Ninguna cambia hoy lo que ve un lector: las tablas de reclasificación, cupos y descenso no se publican (OP-20 en sombra).

## 5. Acta de cotejo (la rellena y la firma la persona que coteja)

```
Acta de cotejo · Reglamento Liga BetPlay DIMAYOR 2026 V0, artículos 27 a 34 (PM-09-02, DOC-008)

Fecha y hora (Bogotá):
Persona que coteja:
Huella SHA-256 del PDF comprobada:   8b377600d9937c08a2dd9fb6438c769770aa7e54e824d7273f53312dd0b5b0c2   [ ] coincide
Filas 1-14 de la tabla del §3:       coinciden: ____   no coinciden: ____ (detalle: ________________________)
Doble lectura de los arts. 32 a 34 (filas 10-14), segunda persona o segunda lectura en otro momento:   [ ] hecha
Pregunta del redondeo (fila 12):
Decisión:   [ ] Se puede publicar la tabla calculada cuando lo firme DM-14   [ ] Corregir antes (v2.yaml)   [ ] No publicar
Firma:
```

Basta con que el dueño devuelva el acta (en el chat o en un comentario del PR) con su fecha: el coordinador la anota en el registro
de decisiones (anexo I) y en el estado de ejecución. Si hay diferencias, la sesión de Intelligence escribe `v2.yaml` (IA-072, §5)
citando el acta, y la publicación espera a DM-14.

## 6. Qué no hace este paquete

* No publica ni enciende nada; no toca `config/rules/`, la base de datos ni el servidor.
* No sustituye la lectura humana: la huella y las páginas sirven para que la persona mire exactamente el mismo documento.
* No copia el reglamento: cita frases cortas para localizar cada regla y enlaza el PDF oficial.
