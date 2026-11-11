# IA-045 — Estudio de eventos: noticia → precio (LAB)

*Plan Maestro de Evolución de PrediGol Intelligence 2026, pieza INT-B09, ola 1. Protocolo proto-int-b09-v1, huella 2b8e49fb…; ejecutado el 11-nov-2026.*

> **Resultado.** El informe es válido según el protocolo y el veredicto es **rechazo**. En ningún segmento preregistrado el precio se mueve, después de que PrediGol conoce el hecho, más de lo que se mueve a horas barajadas. Global: D = 0,000 pp [−0,035; 0,036], con 3.095 eventos en 371 partidos y una diferencia mínima detectable de 0,05 pp. Para el proveedor la conclusión es firme. Para la web (Research v2: una semana y 216 eventos) solo se descartan efectos mayores de ≈0,5–1,5 pp. No se propone ninguna fuente nueva.

## Protocolo (sello)

- **Sello que imprime el script en su salida:** `SELLO INT-B09 proto-int-b09-v1 huella=2b8e49fb115f5cecbcb5e61f52d9ac11d8c8464ce7b3da97af62b3f9382e9232 marco=lab-protocol-v1 script=ia-lab-b09-eventos-v1`.
- **Comprobaciones de la huella:**
  - La huella calculada sobre `fbi/research/protocol.py` (objeto `B09`) es la registrada, y `tests/unit/test_research_protocols.py` la fija.
  - El script lleva el protocolo copiado y no se ejecuta si su SHA-256 cambia.
  - El registro en GitHub (commit 1d8c98d, PR #236) es el que indica el encargo; no lo revisé en GitHub.
  - En la imagen de producción no pude cruzar la huella con el código desplegado: en el contenedor lanzado con `--entrypoint python` no se pudo importar `fbi.research.protocol` (ModuleNotFoundError), y la salida dice «no disponible».
- **Una sola evaluación.** Primero corrí un inventario que solo cuenta eventos y exclusiones, sin calcular ningún movimiento de precio. Después corrí la evaluación una sola vez, el 11-nov-2026 de 05:19:31 a 05:19:59 UTC, con el script de sha256 `c1cd7a0c…`, idéntico en local y en el servidor.
- **Concreción operativa**, fijada antes de evaluar y escrita en la cabecera del script (no cambia el protocolo):
  - **Evento:** la primera afirmación por partido, jugador y tema, entre las del proveedor y las de Research v2. Los temas son:
    - baja: «Missing Fixture» que no es sanción;
    - duda: «Questionable»;
    - sanción: motivo con «suspen», «red card», «yellow card», «sancion» o «expuls», la misma regla que `fbi.ai.collectors`;
    - titularidad: afirmaciones STARTER de Research v2.
  - **known_at:**
    - Proveedor: la primera lectura registrada en `core.player_availability_obs` (origin `answer`, la hora en que preguntamos). Si el primer registro es la copia inicial de la migración 0078 (`snapshot`) o una copia del colector anterior al inicio del historial, la hora de primera lectura no se conoce y el evento cuenta como «sin hora conocida».
    - Research v2: `retrieved_at`. Una afirmación sobre un equipo que no trae partido se asigna al siguiente partido del equipo en los 10 días siguientes (la ventana `STALE_AFTER` del paquete).
  - **Precio:** probabilidad Shin 1X2 del equipo del jugador en `market.market_consensus`. «Antes» es la última cotización con `as_of` anterior a known_at. «Después» es la última anterior al saque, siempre que sea posterior a known_at.
  - **Controles y métrica:**
    - Se hacen 200 permutaciones (semilla 20261111) de la antelación al saque entre los eventos; un evento nunca toma la antelación de otro de su mismo partido.
    - El control de cada evento es la media de sus extracciones válidas.
    - D = media(evento) − media(control).
    - El IC del 95 % sale de un bootstrap de partidos (B = 10.000, percentiles, semilla 20261111).
  - **Tipo de fuente:**
    - proveedor;
    - oficial: federación, liga o club;
    - medio: medio o periodista;
    - rumor: agregador, red social, dominio sin clasificar o página marcada como instrucción.
  - **Ligas prioritarias:** el grupo 1 de `comp-priority-v1`, es decir, la Champions y las ligas top de Inglaterra, España, Alemania, Francia, Portugal e Italia.
- **Añadidos no preregistrados**, que no cuentan para el veredicto: el diagnóstico de los controles (horas antes y después del evento), los componentes de la anticipación en pp y la importancia del jugador.

## Datos

La extracción fue de solo lectura, el 11-nov-2026 a las 05:04:29 UTC: cuatro sentencias COPY, una tras otra. Las tres pesadas tardaron 16 s, 34 s y 30 s.

| Fuente | Tabla | Ventana con hora real |
|---|---|---|
| Bajas de API-Football | `core.player_availability_obs` (origin `answer`) | 22-oct-2026 14:08 → 11-nov 00:57 UTC |
| Research v2 con jugador | `ai.evidence` (web, `subject_type = PLAYER`) | 4-nov 05:05 → 10-nov 13:02 UTC (OUT 225, DOUBT 69, SUSPENSION 17, STARTER 107) |
| Precio | `market.market_consensus` (1X2, Shin) | 2.756 cotizaciones para los 469 partidos con alguna afirmación; mediana de 6 por partido con evento (ventanas T−72/48/24/12/6/3 h) |

Embudo de afirmaciones, en el orden del protocolo:

| Paso | Afirmaciones |
|---|---|
| Candidatas (proveedor 4.678; Research v2 418) | 5.096 |
| Repeticiones de un mismo hecho (fuera) | −130 |
| Primeras por partido, jugador y tema | 4.966 |
| Sin hora conocida (copia de 0078 o anterior al historial) | −783 |
| A menos de 30 min del saque, o después | −617 |
| Sin consenso antes | −286 |
| Sin consenso después | −82 (80 direccionales y 2 de titularidad) |
| **Eventos válidos** | **3.198: 3.095 direccionales (371 partidos, 36 ligas) y 103 de titularidad (34 partidos)** |

**Los 3.095 eventos direccionales:**

- Por fuente: proveedor 2.879, medio 71, oficial 12 y rumor 133.
- Por hecho: baja 2.127, duda 836 y sanción 132.
- Por liga: prioritarias 1.316 (145 partidos) y resto 1.779 (226).

**Antelación al saque:**

- Mediana de 55,3 h, con rango intercuartílico de 38,4 a 60,8 h.
- Por fuente: proveedor 56,4 h, oficial 8,9 h, medio 9,9 h y rumor 10,4 h.
- La cotización «antes» queda a una mediana de 11,0 h del evento. La última antes del saque queda a 2,9 h del saque.

**Contenido nuevo de Research v2** (311 afirmaciones de baja, duda o sanción):

- 217 fueron la primera afirmación de su partido, jugador y tema: oficial 12 de 14, medio 71 de 96 y rumor 134 de 201.
- 58 ya las tenía el proveedor y 36 ya las tenía otra afirmación de v2.
- En 34 casos la lista del proveedor nombró al jugador para ese partido y tema después que Research v2.
- 52 de las 311 no traían partido y se asignaron al siguiente partido del equipo.

## Resultados

Las cifras están en puntos porcentuales (pp) de la probabilidad sin margen del equipo del jugador. Un valor positivo significa que la probabilidad bajó, que es la dirección esperada. Los intervalos son del 95 %, con bootstrap de partidos.

### Métrica principal y segmentos preregistrados

| Segmento | Eventos | Partidos | Cambio tras el evento | Controles (horas barajadas) | **D** | MDE |
|---|---|---|---|---|---|---|
| **Global** | 3.095 | 371 | 0,096 [−0,018; 0,211] | 0,096 [−0,011; 0,203] | **0,000 [−0,035; 0,036]** | 0,050 |
| Fuente: proveedor | 2.879 | 314 | 0,103 [−0,019; 0,222] | 0,109 [−0,001; 0,220] | −0,007 [−0,040; 0,027] | ≈0,05 |
| Fuente: oficial | 12 | 5 | 0,572 [−0,351; 1,557] | 0,917 [0,017; 1,884] | −0,345 [−1,749; 0,405] | ≈1,5 |
| Fuente: medio | 71 | 30 | −0,007 [−0,402; 0,386] | −0,210 [−0,827; 0,414] | 0,203 [−0,306; 0,664] | ≈0,7 |
| Fuente: rumor | 133 | 48 | −0,032 [−0,371; 0,256] | −0,105 [−0,595; 0,322] | 0,073 [−0,251; 0,417] | ≈0,5 |
| Hecho: baja | 2.127 | 355 | 0,097 [−0,033; 0,235] | 0,108 [−0,009; 0,231] | −0,011 [−0,050; 0,027] | ≈0,06 |
| Hecho: duda | 836 | 284 | 0,080 [−0,085; 0,243] | 0,039 [−0,121; 0,195] | 0,041 [−0,044; 0,131] | ≈0,13 |
| Hecho: sanción | 132 | 100 | 0,184 [−0,182; 0,553] | 0,252 [−0,072; 0,581] | −0,068 [−0,205; 0,065] | ≈0,19 |
| Ligas prioritarias | 1.316 | 145 | 0,271 [0,082; 0,466] | 0,255 [0,083; 0,433] | 0,016 [−0,034; 0,066] | ≈0,07 |
| Resto de ligas | 1.779 | 226 | −0,033 [−0,172; 0,099] | −0,022 [−0,153; 0,105] | −0,011 [−0,060; 0,038] | ≈0,07 |

MDE es la diferencia mínima detectable: 2,80 × el error típico. La global sale del bootstrap: 0,050 pp, o 0,043 pp sin agrupar, con una desviación de la diferencia de ≈0,85 pp por evento. La de los segmentos es aproximada y sale del ancho del intervalo.

### Controles

- Los 3.095 eventos tienen control válido, con una mediana de 198 extracciones válidas de 200.
- Diagnóstico no preregistrado: con la hora barajada anterior a la del evento, el control da 0,106 [−0,021; 0,233] (3.032 eventos); con la hora barajada posterior, 0,078 [−0,005; 0,162] (3.087). El precio deriva contra el equipo afectado a lo largo de toda la ventana, no a partir del momento en que PrediGol se entera.

### Secundarios

- **Anticipación** (1.205 eventos con una cotización al menos 24 h anterior al evento):
  - Movimiento en las 24 h previas: 0,026 pp [−0,049; 0,101]. Después del evento: 0,122 [0,001; 0,245]. Total: 0,148 [−0,011; 0,305].
  - Como el total no se distingue de 0, la fracción posterior (0,83 [−0,01; 2,09]) no es interpretable.
  - Por fuente tampoco: el proveedor (992 eventos) da 0,75 [0,20; 1,26] sobre un total de solo 0,20 pp, y en las fuentes web el total es ≤ 0 o hay solo 12 eventos.
  - Ese movimiento posterior es el mismo que el de los controles, así que no es anticipación de PrediGol.
- **Titularidad** (sin dirección; 103 eventos en 34 partidos): el cambio en valor absoluto tras el evento es de 0,805 pp [0,455; 1,279], frente a 0,736 [0,445; 1,131] en los controles. D = 0,069 [−0,062; 0,239].
- **Por liga** (ligas con al menos 30 eventos, umbral fijado antes de evaluar; suman 3.012 eventos): ninguna tiene D por encima de 0.

| Liga | Eventos | Partidos | D |
|---|---|---|---|
| Championship (Inglaterra) | 319 | 31 | 0,039 [−0,149; 0,236] |
| Serie A (Italia) | 310 | 35 | −0,007 [−0,124; 0,085] |
| MLS | 307 | 31 | −0,071 [−0,161; 0,006] |
| Serie A (Brasil) | 237 | 23 | 0,007 [−0,074; 0,096] |
| Europa League | 237 | 18 | −0,059 [−0,177; 0,052] |
| Champions League | 224 | 17 | 0,086 [−0,073; 0,248] |
| Premier League | 218 | 22 | 0,075 [−0,032; 0,219] |
| LaLiga | 185 | 24 | −0,057 [−0,160; 0,035] |
| Bundesliga | 185 | 19 | 0,001 [−0,063; 0,091] |
| Ligue 1 | 183 | 25 | −0,033 [−0,156; 0,077] |
| Eliteserien | 120 | 15 | 0,012 [−0,037; 0,075] |
| Allsvenskan | 116 | 21 | 0,050 [−0,041; 0,127] |
| Eredivisie | 101 | 13 | −0,064 [−0,150; −0,001] |
| Süper Lig | 92 | 15 | 0,051 [−0,072; 0,264] |
| Superliga (Dinamarca) | 78 | 11 | −0,168 [−0,497; 0,006] |
| A-League | 54 | 9 | −0,175 [−0,489; 0,015] |
| Premier League (Rusia) | 46 | 11 | −0,000 [−0,118; 0,093] |

- **Importancia del jugador** (anotación exploratoria, que no cambia la métrica principal): se mide por las titularidades en los 5 partidos previos de su equipo con alineación, como máximo 120 días antes.

| Clase | Eventos | Partidos | Cambio tras el evento | Controles | D |
|---|---|---|---|---|---|
| Titular habitual (≥ 60 %) | 593 | 264 | 0,530 [0,264; 0,809] | 0,584 [0,303; 0,878] | −0,054 [−0,133; 0,025] |
| Ocasional (> 0 y < 60 %) | 774 | 280 | 0,261 [0,047; 0,476] | 0,213 [0,017; 0,405] | 0,048 [−0,011; 0,111] |
| No titular (0 titularidades) | 1.725 | 332 | −0,123 [−0,284; 0,027] | −0,121 [−0,267; 0,018] | −0,002 [−0,040; 0,035] |
| Sin datos (< 3 partidos con alineación) | 3 | 1 | — | — | — |

## Veredicto según el protocolo

1. **Validez (pass_rule): el informe es válido.** Hay 3.095 eventos con precio antes y después, por encima del mínimo de 200. El intervalo está agrupado por partido (371). Los controles dan 0,096 [−0,011; 0,203], un intervalo que incluye 0.
2. **Regla de rechazo: se cumple.** Ni el global ni ninguno de los nueve segmentos preregistrados tiene el intervalo de D por encima de 0. Según el protocolo, **el mercado ya tenía los hechos y no se propone ninguna fuente nueva.**
3. **Potencia.** La MDE global alcanzada, 0,050 pp, es diez veces menor que la de la nota de potencia (0,5 pp): el rechazo global no se debe a falta de muestra. En los segmentos web (oficial, medio y rumor) la MDE es de ≈0,5 a 1,5 pp.

Para G-EVENTOS el resultado es un **rechazo documentado**, no un pendiente.

## Qué significa para las fuentes (G-EVENTOS)

1. **Proveedor.** Las bajas de API-Football, tal como PrediGol las lee, no van por delante del precio: D = −0,007 pp [−0,040; 0,027]. Son el 93 % de los eventos y se leen ≈56 h antes del saque. Siguen siendo útiles como contexto del análisis, pero no dan ventaja de información frente al precio.
2. **Jugadores importantes.** Cuando falta un titular habitual, el precio sí se mueve contra su equipo: ≈0,5 pp entre el evento y el saque. Pero se mueve lo mismo desde horas al azar. El mercado incorpora el hecho a su ritmo, no después de nosotros. Este punto es exploratorio.
3. **Web (Research v2).** Aporta contenido nuevo en volumen: 217 de las 311 afirmaciones de baja, duda o sanción fueron las primeras de su partido, jugador y tema. Pero llega tarde, ≈10 h antes del saque, y el precio no se mueve después en la dirección del hecho. Con una semana de datos solo descarta efectos mayores de ≈0,5 pp en rumor, ≈0,7 pp en medio y ≈1,5 pp en oficial. Es ausencia de evidencia, no evidencia de ausencia.
4. **Consecuencias en el plan.**
   - No se propone ninguna fuente nueva.
   - `INT-B11` (G-REDES) pedía «G-EVENTOS con alguna ventana positiva», y eso no se cumple.
   - Este estudio no justifica X ni ninguna fuente de pago.
   - El modelo de lenguaje combinado con el mercado (I-op. 7) queda sin activar.
5. **Qué podría cambiar el veredicto**, solo con un protocolo v2 registrado antes de mirar:
   - Más semanas de Research v2. Como orientación, al ritmo medido de ≈71 eventos de medios por semana harían falta ≈140 para ver 0,5 pp y ≈850 para ver 0,2 pp.
   - Precios más cerca del evento que las ventanas de 3 a 24 h actuales.
   - Separar los hechos frescos (la primera vez que un jugador aparece en cualquier lista) de las bajas largas.

## Limitaciones

1. **Resolución del precio.**
   - El consenso guardado solo existe en las ventanas T−72/48/24/12/6/3 h, con una mediana de 6 cotizaciones por partido.
   - La cotización «antes» está a una mediana de 11 h del evento, y la última a 2,9 h del saque. Lo que pasa en las últimas 3 h (las alineaciones) no se ve.
   - Por eso el «retraso mediano» noticia → precio no se puede medir. Además, el evento y su control comparten a menudo la misma cotización, lo que atenúa D.
2. **Poca historia.** El proveedor solo tiene hora real de primera lectura desde el 22-oct-2026 (19 días), y Research v2 solo del 4 al 10-nov. 783 primeras afirmaciones quedaron sin hora conocida.
3. **known_at es cuándo PrediGol preguntó, no cuándo se supo el hecho.**
   - La lista del proveedor se lee por temporada. La primera lectura para un partido, ≈56 h antes, refleja el horizonte de lectura, y muchas bajas son largas: el 56 % de los eventos son de jugadores sin ninguna titularidad en sus últimos partidos con alineación (entre 3 y 5).
   - Research v1 queda fuera por protocolo: en total, 3.885 afirmaciones de baja, duda o sanción y 1.353 de alineación, ninguna con id de jugador. Si alguna llegó antes que un evento, nuestra hora es tardía, y eso sesga hacia «el mercado ya lo sabía».
4. **Diseño de los controles.**
   - El control global roza el límite: 0,096 [−0,011; 0,203]. En las ligas prioritarias y con titulares habituales es mayor que 0, porque el precio deriva contra el equipo con bajas durante toda la ventana.
   - Un control del mismo partido que empieza antes del evento también recoge el efecto real. En la prueba con datos sintéticos, un efecto verdadero de 1–2 pp dio «informe no válido» en vez de positivo. En los datos reales no aparece esa firma: los controles anteriores y posteriores al evento dan casi lo mismo.
   - Un protocolo v2 debería corregir esto.
5. **Segmentos pequeños y comparaciones múltiples.** El segmento oficial tiene 12 eventos en 5 partidos, así que su intervalo es poco fiable. Hay 9 segmentos y 17 ligas sin corrección por multiplicidad; el único intervalo por debajo de 0 (Eredivisie) es compatible con el azar.
6. **Sin comprobar:** si el hecho resultó cierto (el protocolo no lo pide), y la huella contra el código de la imagen desplegada.

## Reproducción

Dónde está cada fichero en el repositorio: el script de análisis tal como se ejecutó, `backend/docs/owner/lab/IA_045/ia_lab_b09_eventos.py.txt` (copia exacta, sha256 `c1cd7a0c…`; la extensión `.txt` lo deja fuera del linter porque es un registro del experimento, no código del producto: quítasela para ejecutarlo); la extracción, `lab/IA_045/extract.sql`; y los pasos de la ejecución, `lab/IA_045/ejecucion/`.

- **Ficheros:**
  - `extract.sql`, con los bloques `@meta`, `@events`, `@prices` e `@importance` (sha256 `ca36947d…`);
  - `ia_lab_b09_eventos.py` (sha256 `c1cd7a0c…`);
  - en `ejecucion/`: `q2.sh` (extracción), `q3.sh` (reconstruye el script, que se subió en trozos base64 por el límite de longitud de línea de Windows, y corre el inventario), `q4.sh` (evaluación) y `q1.sh` (inventario del esquema).
- **Pasos:**
  1. Lanza cada bloque de `extract.sql` con psql de solo lectura, con salida a `/tmp/lab_b09/<bloque>.csv`. `q2.sh` rellena `{{IDS}}` y `{{TRIPLES}}` a partir de `events.csv`. Para repetir exactamente esta corrida, cambia `now()` por `timestamptz '2026-11-11 05:04:29+00'`.
  2. Ejecuta `docker run --rm --network none -v /tmp/lab_b09:/lab --entrypoint python <imagen de predigol-worker> /lab/ia_lab_b09_eventos.py /lab --out /lab/results.json`. En esta corrida la imagen fue `predigol-backend:5ae050a9c56a`, con Python 3.12.16 y numpy 2.5.4, y tardó unos 30 s. Con `--inventory` el script da los conteos sin calcular movimientos de precio.
  3. Parámetros: semilla 20261111, R = 200 permutaciones y B = 10.000 remuestreos.
- Al terminar borré `/tmp/lab_b09` del servidor, como pide el brief. Las cifras de este informe están copiadas de la salida del programa.
