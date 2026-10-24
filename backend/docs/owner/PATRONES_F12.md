# La búsqueda de patrones en las decisiones (F12.6) · guía del propietario

*Medido el 24 de octubre de 2026 sobre las decisiones del sistema ya liquidadas. Todo sigue en SOMBRA: ninguna cifra de esta guía llega a un modelo, a un precio, a una decisión ni a un pick.*

## 1. En pocas palabras

* El plan (§14, paso 2) pide buscar cada semana **dónde el sistema se comporta distinto del resto por más de lo que el azar explica**: en una competición, un mercado, un modelo, un árbitro, un equipo. Esta herramienta lo hace con las decisiones ya liquidadas, cuando la pidas (`python -m scripts.patterns search`) o, si la enciendes, cada lunes (sección 9). **Viene apagada.**
* **De cada decisión mira tres cosas:** si ocurrió más o menos de lo que el sistema decía (calibración), si leyó el partido mejor o peor que las casas al cierre (frente al cierre) y si el precio que tomó era mejor o peor que el de cierre (valor de cierre, CLV).
* **Dice cuántas preguntas hizo.** Fueron 162 comparaciones: por azar solo 0,5 de ellas llegarían a 3 errores estándar, y para seguir siendo significativa después de hacerlas todas, una diferencia entre grupos grandes necesita llegar a 3,6.
* **Primera lectura: 49 grupos llegan a 3 errores estándar, y 39 de ellos solo describen cómo se construye el precio** (una cuota larga no vale lo mismo al cierre que una corta, haga lo que haga el sistema): esos no se proponen. De los otros 10, **5 se proponen** (los que se repiten en las dos mitades de la ventana y no dicen lo que ya dice otro mayor) y 3 de las 5 siguen siendo significativas corrigiendo por todas las comparaciones.
* **La más clara: las decisiones sin calibrar.** En 295 decisiones de 231 partidos, lo que ocurre queda en promedio 0,137 por debajo de lo que el sistema decía; en el resto queda 0,012 por encima. Sale en las dos mitades.
* **Es una lectura muy corta.** La ventana pide 90 días, pero el sistema decide desde el 13 de octubre: son unos 10 días de partidos, y «se repite en las dos mitades» quiere decir en dos mitades de unos 5.
* **No cambia nada.** Solo lee (conexión de solo lectura, 0 peticiones al proveedor, 0 IA). Lo que encuentra es, como mucho, una hipótesis que llega a Evolución, en «Mejoras propuestas», y que decides tú; nunca una regla, un modelo, un precio ni un pick. La lectura de esta guía no registró ninguna (sección 8).

## 2. Qué mira

**Las filas.** Cada decisión ya liquidada de la ventana es una fila: la última decisión de cada selección antes del inicio del partido (así lee la memoria), con el partido jugado y sin las anuladas. Cuenta aunque haya terminado rechazada o en investigación (`--selected-only` deja solo las que quedaron como pick o en vigilancia).

**Tres medidas**, un número por fila:

| Medida | Qué es, por fila | Positivo quiere decir |
|---|---|---|
| calibración | lo que pasó (1 si ganó, 0 si perdió) menos la probabilidad del sistema (la calibrada si hubo calibrador; si no, la del modelo) | que ocurre más de lo que el sistema dice |
| frente al cierre | la pérdida logarítmica (*log loss*) del consenso de las casas al cierre menos la del sistema | que el sistema leyó el partido mejor que las casas |
| valor de cierre (CLV) | `cuota × probabilidad justa de cierre − 1` (`clv-v1`) | que el precio tomado era mejor que el de cierre |

Las dos primeras solo se pueden leer en las decisiones que acaban en ganar o perder, sin apuesta devuelta, sin medias ganadas ni perdidas y sin líneas de cuarto: 4.288 de las 9.446. El valor de cierre se lee en todas.

**Qué es el valor de cierre.** Es lo que valía el precio tomado a la probabilidad justa con la que cerró el partido: el consenso de las casas sin su margen, en el último momento capturado antes del inicio (que no se ha demostrado que sea el cierre exacto). Cero es un precio justo. Un precio de una casa con un margen del 6 % da cerca de −6 % aunque nada se mueva (`fbi/market/closing_value.py`): por eso la media de todas las decisiones es −6,4 % y lo que importa aquí es la **diferencia entre grupos**, no el nivel.

**Doce dimensiones.** Un *grupo* es un valor de una dimensión:

| Dimensión | Un grupo es… |
|---|---|
| Mercado | `1X2`, `DC` (doble oposición), `AH` (hándicap asiático), `OU` (más o menos goles), `BTTS` (ambos marcan) |
| Mercado y línea | `OU 2.5`, `AH -1.25`, `1X2 0` |
| Selección | `1X2 Home`, `OU Under`, `BTTS Yes` |
| Modelo | el modelo que dio la probabilidad |
| Calibrador | `CHAMPION`, `CHALLENGER` o «ninguno (sin calibrar)» |
| Rango de cuota | menos de 1,40; 1,40 a 1,69; 1,70 a 1,99; 2,00 a 2,49; 2,50 a 3,49; 3,50 a 5,99; 6,00 o más |
| Contexto | cuánto había leído PrediGol Intelligence del partido: `FULL` (leído, con evidencia de la web o las alineaciones confirmadas), `PARTIAL` (leído, solo con lo que informa el proveedor), `LIMITED` (leído, sin nada fuera de los números), `PENDING` (aún no lo había leído) o `AI_OFF` (capa de IA apagada) |
| Tipo de partido | la clase de competición y su fase, como `continental:group` |
| Competición | UEFA Champions League, por ejemplo |
| Equipo | el equipo al que respalda la selección; si no respalda a ninguno (el empate) o habla del partido entero (goles, ambos marcan), los dos |
| Entrenador | el de ese equipo (la misma regla) |
| Árbitro | el del partido (el último que nombró el proveedor) |

**La pregunta.** Para cada grupo y cada medida: ¿la media del grupo es distinta de la media de todas las demás filas? La respuesta es la diferencia, su error estándar y el cociente de ambos, el **z**. Tres reglas la mantienen honrada:

* **El error estándar se agrupa por partido.** Las filas de un partido no son independientes (los dos lados de un mercado, los varios mercados de un partido): la influencia de cada fila en la diferencia se suma dentro de su partido antes de elevarse al cuadrado. Contar cada fila como un partido distinto haría los errores demasiado pequeños y los hallazgos demasiado fáciles.
* **Un grupo se prueba solo con 30 partidos** en el grupo y 30 en el resto (`--min-matches`). Con menos, el error estándar no es de fiar: el grupo se cuenta, pero no se prueba (columna «probados» de la sección 6).
* **Si dos grupos son exactamente las mismas filas** (una competición que es la única de su tipo, un mercado con una sola línea) se prueba **uno solo** y el informe dice qué otros son lo mismo («the same rows as…»). Y una dimensión con solo dos grupos se pregunta una vez: cada uno es el otro visto desde el otro lado.

## 3. Qué cuenta como un hallazgo, y qué se propone

Un grupo es un **hallazgo** cuando su diferencia llega a **3 errores estándar** (|z| ≥ 3, `--min-z`). Un hallazgo no es una propuesta: para proponerse tiene que cumplir además cuatro condiciones.

1. **Se repite.** La ventana se parte por la mitad, en el punto medio entre el primer y el último partido leídos (en esta lectura, el 18 de octubre a las 08:52 UTC), y cada mitad se lee por separado: la diferencia debe tener el mismo signo y llegar a |z| ≥ 1 (`--half-min-z`) en las dos, con 10 partidos del grupo como mínimo en cada una (`--half-min-matches`). Con menos, la repetición queda «no comprobable» y no se propone. La barra de 1 es floja a propósito: una mitad tiene la mitad de los partidos.
2. **No describe solo cómo se construye el precio** (sección 4).
3. **No dice lo que ya dice otro mayor.** Los grupos de una dimensión son el «resto» unos de otros: si «sin calibrar» queda muy por debajo, `CHALLENGER` queda por encima sin haber hecho nada, porque su resto lleva dentro a los sin calibrar. Por eso, de cada medida y dimensión se propone solo el hallazgo de mayor |z|; y dos hallazgos de una misma medida que comparten la mitad o más de sus filas (las de ambos sobre las de cualquiera de los dos) dicen lo mismo dos veces: se propone el mayor.
4. **Hay sitio.** A lo sumo 5 por búsqueda (`--limit`), los de mayor |z|.

**La corrección por tantas preguntas.** Una búsqueda sobre miles de grupos encuentra z ≥ 3 por pura suerte, y el informe lo dice con tres números: las **comparaciones** que hizo (162), las que **por azar** llegarían a |z| ≥ 3 (0,5) y el |z| que hace falta para **seguir siendo significativo después de todas** (3,6 para un grupo con muchos partidos). Los dos últimos leen la cola de la t de Student con los partidos del lado más pequeño menos uno: con 30 partidos, un z de 3 lo alcanza el azar el doble de veces (p 0,0055) que lo que dice la curva normal (0,0027). Cada hallazgo lleva su **p** y se marca «sobrevive a la corrección» (`SURVIVES the correction`) cuando su p queda por debajo de 0,05 dividido por las comparaciones (corrección de Bonferroni): con 162, por debajo de 0,0003. Cuantas más comparaciones, más alta la barra: con 2.000 haría falta un z de 4,2.

## 4. El precio se compara con lo de su clase

El valor de cierre de un precio depende del tipo de apuesta antes que de nada: cuanto más larga es la cuota, más rara la línea y más pronto se tomó el precio (un día antes queda más lejos del cierre que en la última hora), más lejos queda del cierre, sea cual sea la decisión. Si no se tuviera en cuenta, la búsqueda presentaría como descubrimiento su propia fontanería. Por eso:

* **Mercado, Mercado y línea, Selección y Rango de cuota** son la estructura del precio. Sus grupos se leen tal como vienen y se marcan `[descriptive]`: dicen cómo se construye el precio, no qué hace el sistema, y **nunca se proponen**.
* **Las demás dimensiones** (modelo, calibrador, contexto, tipo de partido, competición, equipo, entrenador y árbitro) se comparan en el valor de cierre **dentro de cada clase de apuesta**: la misma línea de mercado, el mismo rango de cuota y la misma antelación de la decisión (menos de 1 h, de 1 a 3 h, de 3 a 6 h, de 6 a 12 h, de 12 a 24 h, 24 h o más; cada banda incluye su límite inferior). Se promedian las diferencias de cada clase donde hay filas del grupo y del resto, cada una con el peso de las filas del grupo por las del resto sobre el total de la clase (los pesos del estimador de Mantel-Haenszel); una clase donde solo hay una de las dos partes no cuenta. Se marcan `[adjusted]`. Por eso, en estos hallazgos, los partidos son los de las clases compartidas y el «resto» es el resto en esas mismas clases: la diferencia es exactamente la resta de las dos medias.
* **Calibración y frente al cierre** no necesitan nada de esto: «ninguna diferencia» es cero esté donde esté la apuesta.

**La antelación pesa más que casi cualquier hallazgo.** El valor de cierre medio según cuánto antes del inicio se tomó la decisión:

| Antelación de la decisión | Decisiones | Partidos | Valor de cierre medio |
|---|---|---|---|
| menos de 1 h | 1.229 | 478 | −3,0 % |
| de 1 a 3 h | 693 | 224 | −5,6 % |
| de 3 a 6 h | 524 | 228 | −6,3 % |
| de 6 a 12 h | 2.375 | 408 | −7,4 % |
| de 12 a 24 h | 1.777 | 343 | −7,7 % |
| 24 h o más | 2.848 | 688 | −6,4 % |

De la mejor banda (menos de 1 h, −3,0 %) a la peor (de 12 a 24 h, −7,7 %) hay 4,7 puntos, más que cualquiera de las diferencias entre grupos de dimensiones situacionales de la sección 6 (la mayor es de 3,4).

## 5. Cómo se lee

La orden `search` imprime una línea por grupo. Esta es la de las decisiones sin calibrar:

```
  calibration Calibrador       ninguno (sin calibrar)             matches  231 rows   295  group -0.137 rest +0.012  diff -0.149  z -4.9  p 0.0000  halves -4.0/-3.2 repeats  SURVIVES the correction
```

* **`calibration`** es la medida (`calibration`, `vs_close` o `clv`) y **`Calibrador ninguno (sin calibrar)`**, el grupo: la dimensión y su valor.
* **`matches 231 rows 295`** son los partidos y las decisiones del grupo (las decisiones superan a los partidos cuando un partido tiene varias del grupo).
* **`group -0.137 rest +0.012`** son la media del grupo y la del resto (el valor de cierre se imprime en porcentaje y las otras dos medidas como vienen); **`diff`** es grupo − resto.
* **`z -4.9`** es la diferencia entre su error estándar y **`p`**, la probabilidad de ver una diferencia así de lejos de cero si no hubiera ninguna (en la t de Student, sección 3).
* **`halves -4.0/-3.2`** es el z de cada mitad de la ventana y **`repeats`** dice si se repite (`repeats`, `does not repeat` o `not assessable`; solo se calcula para los que llegan a la barra y los demás llevan «-»). **`n/a`** es una mitad con menos de 10 partidos del grupo.
* **`SURVIVES the correction`**, **`[descriptive]`**, **`[adjusted]`** y **`(the same rows as …)`** son lo que se dijo en las secciones 3 y 4.
* Debajo de los hallazgos, **`NEAREST`** lista los diez grupos que se quedaron más cerca de la barra.

Las tablas de esta guía dicen lo mismo con palabras: «Partidos (grupo / resto)», «En el grupo», «En el resto», «Diferencia» (en puntos de porcentaje para el valor de cierre), «z», «z de cada mitad» (`n/d`: la mitad no tiene 10 partidos del grupo) y «Qué se hace con él».

## 6. Primera lectura

Ventana de 90 días: los partidos que empezaron entre el 26-jul-2026 y el 24-oct-2026 a las 00:00 UTC. El sistema decide desde el 13 de octubre de 2026, de modo que de esos 90 días solo hay decisiones en unos 10.

**Qué se leyó:**

| Medida | Filas | Partidos | Media |
|---|---|---|---|
| calibración | 4.288 | 910 | +0,002 |
| frente al cierre | 4.288 | 910 | −0,008 |
| valor de cierre (CLV) | 9.446 | 912 | −6,4 % |

**Cuántos grupos había y cuántos se pudieron probar,** por dimensión (grupos · probados · con las mismas filas que otro, probados una sola vez):

| Dimensión | Calibración y frente al cierre (grupos · probados · con las mismas filas que otro) | Valor de cierre (grupos · probados · con las mismas filas que otro) |
|---|---|---|
| Mercado | 5 · 5 · 0 | 5 · 5 · 0 |
| Mercado y línea | 16 · 8 · 3 | 54 · 32 · 3 |
| Selección | 11 · 11 · 0 | 11 · 11 · 0 |
| Modelo | 3 · 3 · 0 | 3 · 3 · 0 |
| Calibrador | 3 · 3 · 0 | 3 · 3 · 0 |
| Rango de cuota | 7 · 5 · 0 | 7 · 5 · 0 |
| Contexto | 4 · 4 · 0 | 4 · 4 · 0 |
| Tipo de partido | 8 · 3 · 3 | 8 · 3 · 3 |
| Competición | 85 · 3 · 0 | 85 · 3 · 0 |
| Equipo | 1.282 · 0 · 65 | 1.285 · 0 · 62 |
| Entrenador | 948 · 1 · 837 | 950 · 1 · 837 |
| Árbitro | 601 · 0 · 262 | 603 · 0 · 261 |

Un equipo juega, como mucho, un partido cada tres o cuatro días, así que en 90 días casi ninguno llega a los 30 partidos que pide la barra: **ningún equipo, ningún árbitro y un solo entrenador** pudieron probarse (0, 0 y 1). Con esta ventana, esas tres dimensiones no se leerán; para verlas hace falta una más larga (`--days 365`, cuando haya un año de decisiones) o bajar `--min-matches`, sabiendo que con menos partidos el error estándar es menos fiable.

**Los hallazgos que solo describen el precio** (39 de los 49; por dimensión y el mayor de cada una):

| Dimensión | Hallazgos | El mayor |
|---|---|---|
| Mercado | 3 | 1X2: −4,3 % frente a −6,7 % en el resto (z +11,6) |
| Mercado y línea | 24 | OU 1.25: −20,0 % frente a −6,2 % en el resto (z −17,0) |
| Selección | 7 | 1X2 Away: −3,4 % frente a −6,5 % en el resto (z +8,3) |
| Rango de cuota | 5 | 3,50 a 5,99: −11,4 % frente a −4,8 % en el resto (z −34,7) |

Se repiten los 39 y 36 sobreviven a la corrección, pero no son del sistema: las cuotas largas (3,50 a 5,99) valen 6,6 puntos menos al cierre que el resto y las cortas (de 1,40 a 2,49) entre 2,4 y 3,8 puntos más; las líneas raras, como `OU 1.25`, hasta 13,7 menos.

**Los otros 10 hallazgos** (los de dimensiones situacionales, por |z|):

| Medida | Grupo | Partidos (grupo / resto) | En el grupo | En el resto | Diferencia | z | z de cada mitad | Qué se hace con él |
|---|---|---|---|---|---|---|---|---|
| calibración | Calibrador: ninguno (sin calibrar) | 231 / 896 | −0,137 | +0,012 | −0,149 | −4,9 | −4,0 / −3,2 | **Se propone** |
| valor de cierre (CLV) | Contexto: PENDING | 738 / 537 | −7,4 % | −5,6 % | −1,8 puntos | −4,6 | −4,4 / −1,4 | **Se propone** |
| calibración | Calibrador: CHALLENGER | 890 / 528 | +0,020 | −0,057 | +0,077 | +4,1 | +2,8 / +2,9 | Fuera: otro mayor de la misma dimensión ya lo dice |
| calibración | Contexto: PENDING | 752 / 747 | +0,031 | −0,033 | +0,064 | +3,9 | +3,2 / +2,2 | **Se propone** |
| valor de cierre (CLV) | Contexto: FULL | 142 / 618 | −3,9 % | −4,8 % | +0,8 puntos | +3,8 | +2,7 / +3,3 | Fuera: otro mayor de la misma dimensión ya lo dice |
| valor de cierre (CLV) | Competición: UEFA Champions League | 36 / 826 | −3,2 % | −6,6 % | +3,4 puntos | +3,7 | +2,2 / +3,5 | **Se propone** |
| calibración | Mercado: DC | 282 / 910 | −0,086 | +0,008 | −0,094 | −3,6 | −2,8 / −2,2 | Fuera: comparte la mitad o más de sus filas con otro mayor |
| frente al cierre | Mercado y línea: OU 1.5 | 274 / 910 | +0,003 | −0,009 | +0,013 | +3,4 | +2,5 / +2,4 | **Se propone** |
| calibración | Contexto: FULL | 136 / 899 | −0,113 | +0,010 | −0,123 | −3,3 | −1,9 / −2,7 | Fuera: otro mayor de la misma dimensión ya lo dice |
| valor de cierre (CLV) | Contexto: LIMITED | 607 / 802 | −5,6 % | −6,6 % | +1,0 puntos | +3,0 | +3,5 / +0,1 | Fuera: no se repite en las dos mitades |

**Las cinco hipótesis que deja la búsqueda,** como las vería Evolución:

| Hipótesis que deja | Qué cambiaría | z | ¿Sobrevive a la corrección? |
|---|---|---|---|
| Calibrador ninguno (sin calibrar): ocurre menos de lo que el sistema dice | Modelos | −4,9 | sí |
| Contexto PENDING: el precio tomado pierde contra el cierre más que en el resto | Motor de picks | −4,6 | sí |
| Contexto PENDING: ocurre más de lo que el sistema dice | Modelos | +3,9 | sí |
| Competición UEFA Champions League: el precio tomado bate el cierre más que en el resto | Motor de picks | +3,7 | no |
| Mercado y línea OU 1.5: el sistema lee mejor que el cierre | Modelos | +3,4 | no |

Lectura:

* **La más clara es la de las decisiones sin calibrar.** Lo que ocurre queda 0,137 por debajo de lo que el sistema decía (frente a +0,012 en el resto: −0,149, z −4,9), con el mismo signo en las dos mitades (−4,0 y −3,2) y sin perderse en la corrección. «Mercado: DC» (doble oposición) comparte la mitad o más de sus filas con este hallazgo y por eso no se propone aparte, y el de `CHALLENGER` (+0,077) es el mismo hecho visto desde el otro lado: su resto (−0,057) lleva dentro a los sin calibrar.
* **«Contexto: PENDING» sale en dos medidas.** El precio tomado pierde 1,8 puntos más contra el cierre que el resto, en las mismas clases de apuesta (−7,4 % frente a −5,6 %, z −4,6), y lo que ocurre queda 0,064 por encima de lo que el sistema decía (+0,031 frente a −0,033, z +3,9). Las dos se repiten y sobreviven a la corrección, pero son en buena parte **las mismas decisiones**: no suman como dos pruebas, y la del precio es mucho más débil en la segunda mitad (−4,4 y −1,4). No dice por qué: «PENDING» puede hacer tomar peor precio, o marcar otra cosa (decisiones más tempranas dentro de cada banda de antelación, por ejemplo).
* **La Champions League es la más frágil de las cinco.** Son 36 partidos (372 decisiones) con el precio tomado 3,4 puntos mejor contra el cierre que el resto (−3,2 % frente a −6,6 %, z +3,7, mitades +2,2 y +3,5). Se repite, pero no sobrevive a la corrección: su p (0,0007) queda por encima de 0,0003.
* **«OU 1.5» frente al cierre.** En 274 partidos el sistema queda ligeramente por encima de las casas (+0,003 por fila) mientras que en el resto las casas van por delante (−0,009): diferencia de +0,013, z +3,4. Tampoco sobrevive (p 0,0008).
* **Cinco hallazgos se quedaron fuera.** Tres porque otro mayor de su misma dimensión ya lo dice (`CHALLENGER`, y «Contexto: FULL» en calibración y en valor de cierre), uno porque comparte la mitad o más de sus filas con otro mayor («Mercado: DC») y uno porque no se repite: «Contexto: LIMITED» en valor de cierre (+1,0 puntos, z +3,0) tiene +3,5 en la primera mitad y +0,1 en la segunda.
* **Los diez que se quedaron más cerca** (de z 2,8 a 2,3) están en el informe de `search` y en el fichero; ninguno llega a la barra.

## 7. Qué se puede decir y qué no

1. **Hoy hay cinco hipótesis, ninguna prueba.** Salen de unos 10 días de partidos y cada mitad es de unos 5. Tres sobreviven a la corrección por las 162 comparaciones, y dos no.
2. **El precio no es el sistema.** 39 de los 49 hallazgos solo dicen cómo se construye el precio. Ni el nivel de cada banda de cuota ni el de cada línea es una conclusión sobre PrediGol.
3. **Las dimensiones miran las mismas decisiones.** «Contexto: PENDING» sale dos veces porque son las mismas decisiones con dos reglas; un árbitro que solo pita una competición saldría dos veces. Las 162 comparaciones no son 162 pruebas independientes: la corrección por tantas preguntas es prudente en eso, pero no permite leer cada z por separado.
4. **El valor de cierre medio no es una pérdida.** El −6,4 % de la media es sobre todo el margen de las casas; solo la diferencia entre grupos, y dentro de su clase, dice algo.
5. **Equipos, árbitros y entrenadores no se leen todavía** (sección 6): ningún equipo ni árbitro y un solo entrenador llegaron a los 30 partidos. Que no salga nada de ellos no quiere decir que no haya nada.
6. **Lo que dice esta lectura no es la prueba.** Si se aprueba un experimento, la prueba es la lectura hacia delante, sobre partidos posteriores a la aprobación (sección 8).

## 8. Qué se propone y qué hacer con ello

Una hipótesis que sale de aquí es una **pregunta para un experimento**, nunca una regla. Las cinco de la sección 6 no están registradas: la lectura de esta guía no escribió nada. `python -m scripts.patterns propose` las muestra (y marca las que la base ya tenga) sin escribir; con `--confirm` las registra; y las registra solas cada lunes si enciendes `propose` (sección 9).

Registradas, aparecen en Evolución, en **«Mejoras propuestas»**, con el estado **«Propuesta»**, puestas por el sistema, con su hipótesis, su motivo (donde se lee cuántas comparaciones se hicieron, cuántas se esperaban por azar y si sigue siendo significativa corrigiendo por todas), su evidencia (número de partidos, impacto potencial y costo de investigarlo: «US$0 en IA: la comparación se repite en local y luego unos 30 días de shadow») y lo que cambiarían. Tú decides: **«Rechazar»**, **«Investigar»** o **«Aprobar experimento»**. Ninguna de las tres cambia un modelo, un precio ni un pick (`FAMILIAS_VS_MERCADO_F11.md`, sección 8).

* **Una vez y para siempre.** La clave de una hipótesis es `pattern2:{medida}:{dimensión}:{grupo}:{up|down}` (por ejemplo, `pattern2:calibration:calibration_role:none:down`): la búsqueda no la repite aunque la vea cada semana, y **si la rechazas, no vuelve**. Si el mismo grupo cambiara de sentido, sería otra hipótesis.
* **Lo que cambiaría.** Las de calibración y las de frente al cierre apuntan a «Modelos»; las del valor de cierre, al «Motor de picks».
* **Si apruebas un experimento,** la prueba es este mismo comando mirando hacia delante, sobre partidos posteriores a la aprobación: `python -m scripts.patterns search --days N`, con N los días que pasaron desde entonces. Nada de lo que se midió para proponerla cuenta como prueba. Y si una idea llegara a ganar de verdad, cambiar un modelo es una decisión tuya con su propia puerta (`PROMOCIONES_F12.md`); esta herramienta no la abre.

## 9. Cada lunes, si lo enciendes

El trabajo semanal de PrediGol Intelligence (`intel_weekly`, los lunes a las 04:40 hora de Bogotá) tiene este paso al final. **Viene apagado.** Lo decide una variable del servidor, `FBI_PATTERN_SEARCH`:

| Valor | Qué hace el lunes |
|---|---|
| `off` (por omisión, y cualquier valor desconocido) | nada: la búsqueda no corre |
| `report` | corre la búsqueda de 90 días y guarda un resumen en el registro de la corrida (`intel.runs`, campo `counts.patterns`): decisiones y partidos leídos, comparaciones, esperadas por azar, hallazgos, cuántos solo describen el precio, cuántos se repiten, cuántos sobreviven a la corrección y los cinco mayores. No escribe nada más |
| `propose` | lo mismo, y además propone en Evolución, una sola vez cada una, hasta cinco hipótesis (las que se repiten en las dos mitades) |

El trabajador la lee al arrancar: cambiarla en `/etc/predigol/app.env` pide reiniciarlo, como las demás variables de `deploy/vps/app.env.example`. Un fallo de este paso deja la corrida como «parcial» sin parar los demás pasos de la semana. 0 peticiones al proveedor y 0 IA.

**Qué te recomiendo:** `report` primero, para ver durante unas semanas qué resumen deja cada lunes; `propose` cuando quieras que lo que cumpla el criterio llegue solo a Evolución. Es decisión tuya, y mientras no digas nada queda apagado.

## 10. Cómo se repite

```
python -m scripts.patterns search                                   # los últimos 90 días, todas las dimensiones y medidas, en texto
python -m scripts.patterns search --days 60 --selected-only --metric clv --dimension competition --dimension market
python -m scripts.patterns search --json --out patrones.json        # la lectura entera, en JSON y también en un fichero
python -m scripts.patterns propose                                  # ensayo: las hipótesis que deja la búsqueda y cuáles ya tiene la base
python -m scripts.patterns propose --confirm                        # las escribe (estado «Propuesta», puestas por el sistema)
```

Las opciones (iguales en `search` y en `propose`, salvo las dos últimas de cada una):

| Opción | Por omisión | Qué hace |
|---|---|---|
| `--days` | 90 | cuenta hacia atrás desde `--until` los partidos que lee |
| `--until` | ahora | solo los partidos anteriores a este día o instante, en UTC (`2026-10-24`, `2026-10-24T09:00`) |
| `--selected-only` | no | solo las decisiones que quedaron como pick o en vigilancia |
| `--metric` | las tres | una medida; se repite para varias (`calibration`, `vs_close`, `clv`) |
| `--dimension` | las doce | una dimensión; se repite para varias |
| `--min-matches` | 30 | partidos que necesita un grupo, y el resto |
| `--min-z` | 3 | el z, sin signo, que debe alcanzar la diferencia |
| `--half-min-matches` | 10 | partidos del grupo que necesita cada mitad para leerse |
| `--half-min-z` | 1 | el z, sin signo, de cada mitad (con el signo del total) |
| `--alpha` | 0,05 | la probabilidad de un falso hallazgo entre todas las comparaciones |
| `--json`, `--out` (`search`) | no | imprime la lectura como JSON; la guarda además en un fichero |
| `--limit`, `--confirm` (`propose`) | 5, no | las hipótesis como máximo; escribirlas (sin ello, un ensayo) |

Solo lee: abre la conexión de solo lectura y la deshace; con `propose --confirm` es la única orden que escribe, y escribe hipótesis nuevas en estado «Propuesta». Una hipótesis que la base ya tiene, la decidiera como la decidiera el dueño, se deja como está. Tarda unos 30 segundos y usa un núcleo; en el servidor se ejecuta aparte, con prioridad baja, para no competir con el trabajo de producción.

## 11. Dónde está

* El código: `fbi/research/pattern_search.py` (las funciones que deciden son puras y van primero; la lectura de la base y las propuestas, al final) y el comando `scripts/patterns.py`.
* Las pruebas: `tests/unit/test_pattern_search.py` y `tests/integration/test_pattern_search.py` (contra PostgreSQL real). Entre ellas, `test_inside_the_strata_the_difference_is_the_average_of_the_differences_weighted_by_the_rows_of_both` comprueba la aritmética de la sección 4 y `test_a_planted_difference_is_found_with_its_numbers_and_nothing_else_is` que una diferencia plantada se encuentra y nada más.
* Esta lectura: `PATRONES_F12_resultado.json` es lo que escribió `--out`. Lleva la versión de la herramienta (`search-v1`): si cambia la forma de leer, cambia la versión, y una lectura guardada con otra deja de valer. Una prueba ata cada cifra de esta guía a ese fichero y el fichero a la aritmética del código.
* Las guías de las que cuelga: `FAMILIAS_VS_MERCADO_F11.md` (qué es una hipótesis y cómo se decide), `PROMOCIONES_F12.md` (la puerta de un cambio de modelo) y `VARIANTES_VS_MERCADO_F12.md` (la otra herramienta de F12 que propone hipótesis).
