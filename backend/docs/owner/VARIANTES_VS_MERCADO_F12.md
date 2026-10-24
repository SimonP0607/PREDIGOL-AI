# Probar una idea sobre una familia contra el mercado (F12.5) · guía del propietario

*Medido el 24 de octubre de 2026 sobre los precios que el reloj de precios (F1) guarda desde el 25 de septiembre. Todo sigue en SOMBRA: ninguna cifra de esta guía llega a un modelo, a un precio, a una decisión ni a un pick.*

## 1. En pocas palabras

* La sección 7 de `FAMILIAS_VS_MERCADO_F11.md` probó una idea con un script que se tiró después: **corregir el nivel de córners del modelo con lo observado en las 4 semanas anteriores**. Esta herramienta es esa prueba convertida en comando, para cualquier familia que se ajuste con un conteo, y se puede repetir cuando haya más datos: `python -m scripts.families variant`.
* **Pone una variante de la familia junto a la familia tal cual, sobre los mismos partidos, los mismos precios de las casas y los mismos resultados**, y dice tres cosas: si la idea mejora a la familia tal cual, si alcanza al mercado y si llegaría al criterio del plan para decidir en sombra (`CRITERIO_FAMILIAS_F11.md`).
* **Córners:** la corrección de nivel de 28 días deja el total a la par del mercado (mercado − modelo pasa de −0,0038 ± 0,0032 a −0,0007 ± 0,0030 al cierre) y mejora a la familia tal cual (ahorra +0,0031 ± 0,0023 por fila). Por equipo no alcanza: el local sigue 3,2 errores estándar por debajo del mercado.
* **Tarjetas:** la corrección va en sentido contrario (el modelo se pasa de tarjetas, entre un 2 % y un 7 %) y también acerca el total al mercado, pero con 398 partidos el error es más del doble que el de córners. **Amarillas:** no hay con qué compararlas.
* **Ninguna variante cumple el criterio del plan.** Córners tiene más de 300 apuestas simuladas pero un valor de cierre negativo; tarjetas no llega a 300; amarillas no tiene ninguna.
* **No cambia nada:** ni la familia, ni un pronóstico, ni un precio, ni un pick, ni la versión de un modelo. Solo lee (conexión de solo lectura, 0 peticiones al proveedor, 0 IA).

## 2. Qué hace, semana a semana

1. **Rehace la familia semana a semana.** Cada 7 días (un «bloque») la reajusta solo con lo que se sabía al empezar el bloque, como el recorrido hacia delante de F10 y con lo mismo que usa el trabajo de producción (el decaimiento temporal, la penalización y, en tarjetas, el multiplicador del árbitro), y declara cada mercado que las casas también cotizan.
2. **Tal cual** son las medias de esa reconstrucción, sin tocar. **`recent-level:N`** (corrección de nivel de N días; N va de 7 a 365 días y, si no se pide otra, se lee `recent-level:28`) multiplica las medias de cada lado por lo observado entre pronosticado en los N días anteriores al bloque, solo con partidos que ya se conocían entonces (6 horas después de su inicio) y solo si hay al menos 200 partidos; con menos, ese bloque queda como la familia lo declara.
3. **La dispersión** (cuánto más se ensancha el reparto de córners o tarjetas que el de un Poisson) se mide en los 120 días anteriores a cada bloque con las medias de la variante, como hace producción; si no hay 300 partidos con los que medirla, no se declara nada.
4. **El mercado** es el de F11, sin una segunda definición: la probabilidad de las casas con su margen quitado, con 3 casas o más, al último precio antes del inicio y 24 horas antes.
5. **La línea principal** de cada partido es aquella cuyo «más de» el mercado deja más cerca de una de cada dos, entre el 8 % y el 92 % (en un empate, la línea más baja). La elige el mercado, no el modelo: es la misma para todas las variantes. Se lee también con todas las líneas, pero las líneas de un mismo partido se parecen mucho y cuentan como una sola observación.
6. **Las apuestas simuladas** son las del criterio del plan: una unidad al mejor precio de las casas, solo con pronósticos declarados 24 horas o más antes del inicio y cuando el modelo ve un valor de al menos 3 %. Como el pronóstico de un bloque se declara al empezar el bloque, un partido del último día de su bloque no tiene ninguno con esa antelación.

## 3. Sin ver el futuro

Nada de lo que usa un bloque ocurrió después de su comienzo: ni el ajuste de la familia, ni la corrección, ni la dispersión. Una prueba lo comprueba (`test_no_number_of_a_week_changes_when_what_happens_from_that_week_on_does`): cambia los resultados de todos los partidos que aún no se conocían al empezar la segunda semana y exige que ni una cifra de esa semana ni de las anteriores se mueva, mientras que las semanas siguientes, que sí vieron esos partidos, tienen que cambiar. Otra prueba comprueba que dos lecturas de los mismos datos dan lo mismo, y así fue en el servidor: la lectura de córners repetida con los mismos datos dio el mismo fichero, byte a byte.

## 4. Cómo se lee

* **Mercado − modelo** es la diferencia de *log loss* (en nats por partido; menos es mejor) entre las casas y la variante, con su error estándar agrupado por partido. **Positivo: la variante fue mejor que el mercado. Negativo: ganó el mercado.** Una diferencia que no llega a dos errores estándar no se distingue de cero.
* **Señal extra** es lo mismo que en F11: el coeficiente que recibe «modelo − mercado» (en logit) en una regresión de lo ocurrido. 0 significa que el modelo no añade nada a lo que ya dice el mercado, 1 que habría que fiarse de él por completo. Con menos de 30 filas no se calcula.
* **Ahorra** es lo que la variante gana contra la familia tal cual **sobre las mismas filas**: el *log loss* que ahorra por fila (positivo: mejor que tal cual). Como el mercado y el resultado son los mismos para las dos, tiene menos ruido que comparar cada una con el mercado y es la medida de si la idea sirve como corrección.
* **Bloque desde** es el principio de cada semana de la reconstrucción; **×1,027** quiere decir que las medias de ese lado se multiplicaron por 1,027 porque el modelo se había quedado un 2,7 % corto en las semanas anteriores.
* **Veredicto** es el del criterio de `CRITERIO_FAMILIAS_F11.md`: `too few bets`, `closing-line value negative` o `meets the criterion`.

## 5. Primera lectura: córners

Ventana del 25-sep-2026 al 23-oct-2026 a las 12:00 UTC (la que tiene precios): 1.458 partidos con pronóstico, 1.258 de ellos con una línea principal del total al cierre y 772 a 24 horas. Variantes: tal cual, y la corrección de nivel de 28 y de 56 días.

**Mercado − modelo** (positivo: mejor que el mercado):

| Mercado | Momento | Partidos | Tal cual | Corrección de 28 días | Corrección de 56 días |
|---|---|---|---|---|---|
| total del partido | último precio | 1.258 | −0,0038 ± 0,0032 | −0,0007 ± 0,0030 | −0,0009 ± 0,0029 |
| total del partido | 24 h antes | 772 | −0,0061 ± 0,0041 | +0,0005 ± 0,0041 | −0,0008 ± 0,0038 |
| equipo local | último precio | 1.138 | −0,0139 ± 0,0045 | −0,0136 ± 0,0043 | −0,0135 ± 0,0043 |
| equipo local | 24 h antes | 392 | −0,0079 ± 0,0070 | −0,0076 ± 0,0066 | −0,0076 ± 0,0067 |
| equipo visitante | último precio | 1.127 | −0,0094 ± 0,0047 | −0,0049 ± 0,0043 | −0,0063 ± 0,0044 |
| equipo visitante | 24 h antes | 390 | −0,0144 ± 0,0069 | −0,0086 ± 0,0064 | −0,0105 ± 0,0064 |
| quién tiene más (1X2) | último precio | 1.033 | −0,0089 ± 0,0031 | −0,0081 ± 0,0031 | −0,0087 ± 0,0031 |
| quién tiene más (1X2) | 24 h antes | 420 | −0,0027 ± 0,0048 | −0,0020 ± 0,0049 | −0,0026 ± 0,0049 |

**Señal extra** (0: no añade nada al mercado; 1: peso completo):

| Señal extra de | Momento | Partidos | Tal cual | Corrección de 28 días | Corrección de 56 días |
|---|---|---|---|---|---|
| total del partido | último precio | 1.258 | +0,53 ± 0,28 | +0,35 ± 0,27 | +0,42 ± 0,27 |
| total del partido | 24 h antes | 772 | +0,41 ± 0,35 | +0,26 ± 0,34 | +0,32 ± 0,35 |
| equipo local | último precio | 1.138 | −0,16 ± 0,21 | −0,17 ± 0,21 | −0,17 ± 0,21 |
| equipo local | 24 h antes | 392 | +0,06 ± 0,39 | +0,05 ± 0,39 | +0,05 ± 0,39 |
| equipo visitante | último precio | 1.127 | +0,33 ± 0,21 | +0,28 ± 0,21 | +0,31 ± 0,21 |
| equipo visitante | 24 h antes | 390 | +0,06 ± 0,39 | −0,02 ± 0,39 | +0,03 ± 0,39 |
| quién tiene más (1X2) | último precio | 1.033 | +0,07 ± 0,18 | +0,12 ± 0,18 | +0,08 ± 0,18 |
| quién tiene más (1X2) | 24 h antes | 420 | +0,42 ± 0,29 | +0,45 ± 0,29 | +0,41 ± 0,29 |

**Lo que ahorra la corrección** contra la familia tal cual, sobre las mismas filas (positivo: mejor que tal cual):

| Ahorra en | Momento | Partidos | Corrección de 28 días | Corrección de 56 días |
|---|---|---|---|---|
| total del partido | último precio | 1.258 | +0,0031 ± 0,0023 | +0,0029 ± 0,0015 |
| total del partido | 24 h antes | 772 | +0,0066 ± 0,0031 | +0,0053 ± 0,0020 |
| equipo local | último precio | 1.138 | +0,0004 ± 0,0012 | +0,0004 ± 0,0010 |
| equipo local | 24 h antes | 392 | +0,0003 ± 0,0020 | +0,0003 ± 0,0017 |
| equipo visitante | último precio | 1.127 | +0,0045 ± 0,0019 | +0,0031 ± 0,0010 |
| equipo visitante | 24 h antes | 390 | +0,0058 ± 0,0034 | +0,0039 ± 0,0018 |
| quién tiene más (1X2) | último precio | 1.033 | +0,0007 ± 0,0004 | +0,0002 ± 0,0001 |
| quién tiene más (1X2) | 24 h antes | 420 | +0,0007 ± 0,0006 | +0,0001 ± 0,0002 |

**Qué multiplicó la corrección** en cada bloque (observado entre pronosticado de las semanas anteriores):

| Bloque desde | Local (28 días) | Visitante (28 días) | Local (56 días) | Visitante (56 días) |
|---|---|---|---|---|
| 25-sep-2026 | ×1,027 | ×1,019 | ×1,020 | ×1,005 |
| 2-oct-2026 | ×1,025 | ×1,018 | ×1,018 | ×1,010 |
| 9-oct-2026 | ×1,026 | ×1,038 | ×1,022 | ×1,023 |
| 16-oct-2026 | ×1,029 | ×1,061 | ×1,025 | ×1,030 |
| 23-oct-2026 | ×1,024 | ×1,070 | ×1,025 | ×1,040 |

**Apuestas simuladas** con el criterio del plan (valor medio en puntos porcentuales; «Las casas ese día» es lo que valía ese precio según el consenso de las casas):

| Variante | Apuestas | Partidos | Faltan | Creía el modelo | Las casas ese día | Valor de cierre | Rendimiento | Veredicto |
|---|---|---|---|---|---|---|---|---|
| tal cual | 1.053 | 529 | 0 | +16,0 % | −2,4 % | −1,0 % ± 0,3 % | +4,2 % ± 4,7 % | `closing-line value negative` |
| corrección de 28 días | 1.045 | 558 | 0 | +16,4 % | −2,2 % | −0,5 % ± 0,3 % | +7,6 % ± 4,9 % | `closing-line value negative` |
| corrección de 56 días | 1.005 | 523 | 0 | +16,1 % | −2,1 % | −0,5 % ± 0,3 % | +7,5 % ± 5,0 % | `closing-line value negative` |

Lectura:

* **El total queda a la par del mercado.** Tal cual, mercado − modelo es −0,0038 ± 0,0032 al cierre (1,2 errores estándar: el mercado va por delante, sin que se distinga de cero); con la corrección de 28 días queda en −0,0007 ± 0,0030 y con la de 56 en −0,0009 ± 0,0029, y a 24 horas en +0,0005 ± 0,0041 y −0,0008 ± 0,0038. Es lo que midió F11 a mano (de −0,0040 ± 0,0032 a −0,0006 ± 0,0030 con 1.268 partidos): la herramienta permanente lo reproduce con unas milésimas de diferencia, porque la ventana no coincide al partido (aquí 1.258).
* **La corrección sí mejora a la familia tal cual, pero solo la lleva hasta el mercado.** En el total ahorra +0,0031 ± 0,0023 por fila al cierre con 28 días (+0,0029 ± 0,0015 con 56) y en el visitante +0,0045 ± 0,0019 (+0,0031 ± 0,0010); en el local no ahorra nada (+0,0004 ± 0,0012).
* **Por equipo no se cierra.** El local sigue en −0,0136 ± 0,0043 al cierre con 28 días (3,2 errores estándar por debajo del mercado) y «quién tiene más córners» en −0,0081 ± 0,0031 (2,6): el mercado ve alineaciones, bajas y planteamientos que el modelo no ve, y un cambio de nivel no arregla eso.
* **El modelo se quedó corto, y desde el bloque del 9-oct cada vez más con el visitante.** Con 28 días la corrección multiplicó las medias del local por entre 1,024 y 1,029 y las del visitante por entre 1,018 y 1,070, hasta 1,070 en el último bloque (F11 midió un 4,5 % corto entre el 18 de septiembre y el 16 de octubre).
* **Dar 28 o 56 días da lo mismo.** Ninguna sale claramente mejor (total al cierre −0,0007 ± 0,0030 frente a −0,0009 ± 0,0029).
* **Las apuestas pasan de 300 pero no el valor de cierre.** Son 1.053, 1.045 y 1.005 apuestas y el valor de cierre es −1,0 % ± 0,3 % tal cual, −0,5 % ± 0,3 % con 28 días y −0,5 % ± 0,3 % con 56: la corrección reduce a la mitad lo que le falta y no lo lleva a cero, así que el veredicto es `closing-line value negative` en las tres. Los rendimientos (+4,2 %, +7,6 % y +7,5 %, con errores de ±4,7 a ±5,0 puntos) no se distinguen de cero.
* **Una cosa que mirar, no un hallazgo:** «quién tiene más córners» (`CORNERS_1X2`) es el único tipo de apuesta con valor de cierre positivo en las tres lecturas (+2,3 %, +2,5 % y +2,3 %, con errores de ±0,7 a ±0,8 puntos, con 253 a 259 apuestas), igual con la corrección que sin ella, así que no es efecto de la idea. Es el mejor precio de cualquier casa contra el consenso de cierre (`CRITERIO_FAMILIAS_F11.md`, límites), en cuatro semanas y entre decenas de comparaciones.

## 6. Primera lectura: tarjetas

`cards_lines_ft` lleva el multiplicador del árbitro (un prior de 150 tarjetas), aplicado a 915 de los 1.432 partidos de la ventana. De todo lo que la familia declara, solo el total del partido tiene en estas semanas un consenso de 3 casas o más: 398 partidos al cierre y 123 a 24 horas.

**Mercado − modelo** (positivo: mejor que el mercado):

| Mercado | Momento | Partidos | Tal cual | Corrección de 28 días | Corrección de 56 días |
|---|---|---|---|---|---|
| total del partido | último precio | 398 | −0,0045 ± 0,0072 | +0,0009 ± 0,0071 | +0,0028 ± 0,0076 |
| total del partido | 24 h antes | 123 | +0,0100 ± 0,0126 | +0,0137 ± 0,0128 | +0,0146 ± 0,0139 |

**Señal extra:**

| Señal extra de | Momento | Partidos | Tal cual | Corrección de 28 días | Corrección de 56 días |
|---|---|---|---|---|---|
| total del partido | último precio | 398 | +0,44 ± 0,36 | +0,42 ± 0,35 | +0,40 ± 0,35 |
| total del partido | 24 h antes | 123 | +1,06 ± 0,71 | +1,06 ± 0,70 | +1,06 ± 0,70 |

**Lo que ahorra la corrección** contra la familia tal cual, sobre las mismas filas:

| Ahorra en | Momento | Partidos | Corrección de 28 días | Corrección de 56 días |
|---|---|---|---|---|
| total del partido | último precio | 398 | +0,0054 ± 0,0027 | +0,0073 ± 0,0046 |
| total del partido | 24 h antes | 123 | +0,0037 ± 0,0047 | +0,0046 ± 0,0081 |

**Qué multiplicó la corrección** en cada bloque:

| Bloque desde | Local (28 días) | Visitante (28 días) | Local (56 días) | Visitante (56 días) |
|---|---|---|---|---|
| 25-sep-2026 | ×0,958 | ×0,941 | ×0,934 | ×0,935 |
| 2-oct-2026 | ×0,976 | ×0,955 | ×0,938 | ×0,938 |
| 9-oct-2026 | ×0,971 | ×0,961 | ×0,944 | ×0,943 |
| 16-oct-2026 | ×0,982 | ×0,960 | ×0,956 | ×0,945 |
| 23-oct-2026 | ×0,957 | ×0,933 | ×0,958 | ×0,937 |

**Apuestas simuladas** con el criterio del plan:

| Variante | Apuestas | Partidos | Faltan | Creía el modelo | Las casas ese día | Valor de cierre | Rendimiento | Veredicto |
|---|---|---|---|---|---|---|---|---|
| tal cual | 76 | 76 | 224 | +11,3 % | −2,6 % | −1,0 % ± 0,8 % | +19,0 % ± 11,0 % | `too few bets` |
| corrección de 28 días | 63 | 63 | 237 | +13,0 % | −3,0 % | −0,8 % ± 0,8 % | +18,8 % ± 11,5 % | `too few bets` |
| corrección de 56 días | 69 | 69 | 231 | +13,2 % | −3,2 % | −0,8 % ± 0,8 % | +17,7 % ± 11,2 % | `too few bets` |

Lectura:

* **La corrección va en sentido contrario al de córners:** el modelo se pasa de tarjetas, y la corrección bajó sus medias entre un 2 % y un 7 % (28 días).
* **Acerca el total al mercado:** de −0,0045 ± 0,0072 a +0,0009 ± 0,0071 al cierre con 28 días (+0,0028 ± 0,0076 con 56), y ahorra +0,0054 ± 0,0027 por fila (28 días) y +0,0073 ± 0,0046 (56). Con 398 partidos el error es mucho mayor que en córners, y a 24 horas (123 partidos) más aún: no se distingue de cero.
* **Faltan apuestas:** son 76, 63 y 69; con la corrección de 28 días faltan 237 para las 300 (`too few bets`). El valor de cierre (−0,8 % ± 0,8 %) no es prueba de nada todavía.

## 7. Primera lectura: amarillas

**No hay con qué compararlas.** El reloj de precios guarda para las amarillas una sola casa, y con menos de 3 no hay consenso (lo dijo F11). El comando no inventa una comparación: no imprime ninguna fila de mercado ni de apuestas (`no bet -> too few bets`) y lo único que sale es el nivel que la corrección habría aplicado:

| Bloque desde | Local (28 días) | Visitante (28 días) | Local (56 días) | Visitante (56 días) |
|---|---|---|---|---|
| 25-sep-2026 | ×0,959 | ×0,947 | ×0,936 | ×0,938 |
| 2-oct-2026 | ×0,974 | ×0,959 | ×0,939 | ×0,941 |
| 9-oct-2026 | ×0,969 | ×0,963 | ×0,947 | ×0,946 |
| 16-oct-2026 | ×0,973 | ×0,955 | ×0,956 | ×0,946 |
| 23-oct-2026 | ×0,954 | ×0,926 | ×0,958 | ×0,938 |

Con 28 días las medias se habrían multiplicado por entre 0,926 y 0,974: el modelo de amarillas también se pasa, como el de tarjetas. Hasta que el reloj de precios guarde 3 casas o más para ellas, nada se puede decir de si eso es un acierto.

## 8. Qué se puede decir y qué no

1. **Ninguna variante tiene valor demostrado.** Córners tiene apuestas de sobra pero un valor de cierre negativo, tarjetas no llega a 300 apuestas y amarillas no se pueden comparar. Todo sigue en INVESTIGACIÓN.
2. **La corrección de nivel es un arreglo, no una ventaja.** Mejora a la familia tal cual y la deja a la par del mercado en los totales, que es lo que F11 proponía comprobar. Estar a la par no es ganarle: el margen de las casas (≈ −3 %) sigue ahí.
3. **Son muchas comparaciones y pocas semanas.** Cada tabla tiene decenas de cifras y las de una misma tabla se parecen entre sí (mismas filas): que una salga a dos errores estándar no es un hallazgo. Lo que merece confianza es lo que se repite en las dos variantes, en los dos momentos y en las dos líneas, como el total de córners, y aun así son 4 semanas.
4. **Lo que dijo esta lectura no es la prueba.** Si una idea se aprueba como experimento, la prueba es la lectura hacia delante, sobre partidos posteriores a su aprobación.

## 9. Qué hacer con un resultado

Una variante que mejora a la familia y se acerca al mercado es una **hipótesis con una medición detrás**, no una promoción. Las dos que ya están escritas en el código (`fbi/research/hypotheses.py`: la corrección de nivel reciente de córners y la mezcla anclada al mercado) salen de la sección 7 de `FAMILIAS_VS_MERCADO_F11.md`; esta herramienta es con la que se repiten. Se registran con `python -m scripts.hypotheses register --confirm` y las decides tú en Evolución (ver `FAMILIAS_VS_MERCADO_F11.md`, sección 8).

Si apruebas el experimento de una, la prueba hacia delante es este mismo comando con una ventana que empiece el día de la aprobación (`--since`): nada de lo que se midió para proponerla cuenta como prueba. Y si una variante llegara a ganar de verdad, promover el código del modelo es una decisión tuya con su propia puerta (`PROMOCIONES_F12.md`); esta herramienta no la abre.

## 10. Cómo se repite

```
python -m scripts.families variant --family corners_ft                  # las últimas 4 semanas, con la corrección de 28 días
python -m scripts.families variant --family corners_ft --variant recent-level:28 --variant recent-level:56
python -m scripts.families variant --family cards_lines_ft --since 2026-09-25 --until 2026-10-23T12:00 --out lectura.json
python -m scripts.families variant --family corners_ft --json           # lo mismo, para leerlo con otra herramienta
```

Las opciones:

* `--family` (obligatoria): `corners_ft`, `cards_lines_ft` o `yellow_ft`, las familias que se ajustan con un solo conteo que las casas también cotizan.
* `--variant`: `recent-level:DÍAS`, repetible; la familia tal cual siempre se lee. Si no se pide ninguna, `recent-level:28`.
* `--days` (por omisión 28) cuenta hacia atrás desde `--until`; `--since` y `--until` fijan la ventana exacta (un día, o un instante en UTC) para repetir una lectura. `--until`, por omisión, es ahora menos `--wait-hours` (por omisión 30: las estadísticas de tarjetas tardan en asentarse).
* `--step-days` (por omisión 7) y `--dispersion-days` (por omisión 120) son el largo del bloque y los días con los que se mide la dispersión; `--min-books` (por omisión 3) y `--min-ev` (por omisión 0,03) son los del marcador.
* `--out` guarda además la lectura en un fichero y `--json` la imprime así; el fichero de esta guía, `VARIANTES_VS_MERCADO_F12_resultado.json`, es lo que esos comandos escriben, una lectura por familia. Cada lectura lleva la versión de la herramienta (`variants-v1`): si cambia la forma de leer, cambia la versión, y una lectura guardada con otra deja de valer.

Solo lee: abre la conexión de solo lectura y la deshace. Tarda unos 2 a 3 minutos por familia y usa un núcleo; en el servidor se ejecuta aparte, con prioridad baja, para no competir con el trabajo de producción. Una prueba ata cada cifra de esta guía a ese fichero y el fichero a la aritmética del código.

## 11. Límites de esta medición

* **Cuatro semanas de precios** (del 25-sep-2026 al 23-oct-2026 a las 12:00 UTC). Con tan pocos partidos, una diferencia pequeña no se distingue del azar.
* **El modelo es la reconstrucción semanal de F10, no los pronósticos guardados**, que se reajustan cada 3 horas. Cuando haya semanas de pronósticos guardados, `score` los mide sin esta aproximación; esta herramienta es para probar ideas antes de que existan pronósticos guardados con ellas.
* **El pronóstico se declara al empezar el bloque**, hasta casi 7 días antes del partido: es más viejo que el real y perjudica a las dos lecturas por igual.
* **El consenso es proporcional**, no el estimador de Shin del resto del sistema; con dos opciones casi equilibradas la diferencia es pequeña.
* **El último precio ya conoce las alineaciones; el modelo no.** A 24 horas la comparación es más justa y también menos precisa.
* **Solo hay un tipo de variante** (`recent-level`) y solo se leen las familias de un conteo. Los goles por mitad se ajustan con dos y no se leen aquí; la mezcla anclada al mercado de F12.4 se mide con la señal extra, pero todavía no como variante.
* **Las apuestas son el mejor precio de cualquier casa**, que supone una cuenta en cada una; un pick de verdad iría a una casa concreta y su valor de cierre no podría ser mejor (`CRITERIO_FAMILIAS_F11.md`).
