# Cuándo puede una familia pasar a decidir en sombra (F11.5) · guía del propietario

*Escrita el 24 de octubre de 2026. Es una medición: solo lee la base de datos, no hace peticiones al proveedor, no usa IA y no cambia ningún modelo, precio, decisión ni pick. **Lo que imprime no promueve nada**: aunque una familia cumpla el criterio, que pase a decidir en sombra es decisión tuya.*

## 1. En pocas palabras

* El plan pone una puerta a cada familia nueva (goles por mitad, córners, tarjetas): para pasar de **investigación** a **decidir en sombra** necesita **al menos 300 apuestas simuladas** y que **el valor de cierre de esas apuestas no sea negativo**.
* Hasta ahora eso se había medido a mano (`FAMILIAS_VS_MERCADO_F11.md`, con una aproximación del modelo). Desde F11.5 lo mide el marcador solo, con los **pronósticos que el servidor guarda de verdad** antes de cada partido y los precios del reloj de precios (F1).
* **Hoy no hay ninguna cifra.** Los pronósticos de las familias se guardan desde el 24-oct a las 04:13 UTC, hace falta uno guardado al menos 24 horas antes del inicio, y el marcador espera 30 horas tras el partido a que se asienten las estadísticas. Las primeras apuestas medibles saldrán hacia el 26 o el 27 de octubre.
* La primera lectura con sentido (300 apuestas de córners) llegaría hacia principios de noviembre y las tarjetas tardarían meses; son estimaciones (sección 5).

## 2. Qué es una apuesta simulada

Es lo que haría el sistema con un pronóstico guardado, sin usar nada que no pudiera saber en ese momento:

* **El pronóstico** es el último guardado **24 horas o más antes del inicio**, no el último antes del partido (ese sabe más).
* **El precio** es el mejor que ofrecía **cualquier casa completa** ese mismo momento (una casa que cotiza todas las opciones de esa línea y con un margen creíble: por encima de 1 y como mucho 1,25), en una línea donde no puede haber devolución (sin línea o con «medio») y con **3 casas o más** detrás, para que haya un mercado con el que medirse.
* **Se apuesta** cuando el valor que el modelo ve en ese precio (probabilidad del modelo × cuota − 1) es de **al menos 3 %**, y solo la mejor línea de cada mercado de cada partido: una unidad, una apuesta por modelo, partido y mercado (las líneas de un mercado son la misma pregunta vista varias veces).
* **Se liquida** con la misma aritmética del marcador: acierto devuelve cuota − 1, fallo devuelve −1.

## 3. Las cuatro cifras de cada familia

Todas se calculan sobre las mismas apuestas: las que además tienen consenso de casas en el último precio antes del inicio (las que no, se cuentan aparte: «N más sin consenso de cierre»).

| Cifra | Qué dice | Cómo leerla |
|---|---|---|
| *the model believed* (lo que creía el modelo) | el valor medio que veía en el precio | por construcción ≥ 3 %; casi siempre es sesgo propio, no ventaja |
| *the books' probability that day* (la probabilidad de las casas ese día) | lo que valía ese mismo precio según el consenso de las casas sin margen | mide lo que da buscar el mejor precio, menos el margen: suele ser negativo |
| *closing line* (**valor de cierre**, `clv-v1`) | lo que valía ese precio según el consenso del último precio antes del inicio | **es la cifra que pide el plan**: positivo = el mercado acabó dándole la razón al precio |
| *return* (rendimiento) | lo que devolvieron las apuestas por unidad apostada | con 300 apuestas tiene ±4 a ±6 puntos de error: es suerte, no se decide con él |

El valor de cierre es la **única definición** del sistema (`fbi.market.closing_value`): el mismo número que usan el post-mortem, la memoria y la puntuación. Los errores estándar agrupan por partido: las apuestas de un mismo partido son una sola observación de cómo se movieron sus precios.

## 4. El veredicto

Cada familia sale con una de tres frases:

* `too few bets` — menos de 300 apuestas (el texto dice cuántas faltan). El valor de cierre se imprime, pero todavía no es prueba de nada.
* `closing-line value negative` — 300 o más y el valor de cierre es menor que cero: **la familia no pasa**; los precios que encuentra no son los que el mercado acaba aceptando.
* `meets the criterion` — 300 o más y el valor de cierre no es negativo (el cero pasa). Si está a menos de 2 errores estándar de cero lo dice: *«but the closing-line value is within 2 standard errors of zero»*. Eso es lo que pide el plan, no más: indica que **puedes pedir** decisiones en sombra de esa familia, no que haya ventaja demostrada.

## 5. Cuándo habrá cifras (estimaciones mías, no medidas)

En la medición a mano de F11.4 (cuatro semanas, apostando 24 horas antes) salieron 365 + 210 + 232 apuestas de córners (total, local y visitante: unas 29 al día) y 78 de tarjetas (unas 3 al día). Con ese ritmo los córners juntarían 300 apuestas en unos 10 o 11 días de pronósticos guardados, y las tarjetas en más de tres meses. Los goles por mitad no se han medido todavía. Las **amarillas** no tendrán ninguna apuesta mientras el reloj de precios guarde una sola casa para ellas (con menos de 3 no hay consenso). Esto es una orientación: el criterio de ahora es más estricto que la medición a mano.

## 6. Cómo se repite

```
python -m scripts.families score --days 60                 # el marcador, el cruce con las casas y, al final, el criterio del plan
python -m scripts.families score --days 60 --min-ev 0.05   # exigir al modelo un valor de 5 % en lugar de 3 %
python -m scripts.families score --days 60 --json          # lo mismo, para leerlo con otra herramienta
```

Solo lee (conexión de solo lectura). Los precios se leen por tandas de 250 partidos para que una ventana de semanas no llene la memoria; con muchas semanas puede tardar unos minutos. No hay trabajo programado: la medición se repite cuando quieras y da lo mismo cada vez con los mismos datos. Se propone mirarla una vez por semana.

## 7. Límites

* **El momento de la apuesta es 24 horas antes** del inicio, que es cuando el sistema toma un pick; no es el momento real de ningún pick (las familias no tienen picks).
* **El mejor precio de todas las casas** supone una cuenta en cada una. Un pick de verdad iría a una casa concreta y su valor de cierre no podría ser mejor.
* **El «cierre» es el último consenso capturado antes del inicio**; no está demostrado que sea el cierre real (la nota de `clv-v1` lo dice), y el consenso es proporcional, no el estimador de Shin del resto del sistema.
* **Elegir la mejor línea de cada mercado escoge los mayores desacuerdos del modelo con el mercado**: es lo que haría un selector real, y por eso lo que el modelo cree (+10 %) está tan lejos de lo que las casas dan.
* **Solo mercados de dos o tres opciones** (más/menos, ambos marcan, par/impar, empate no apuesta y 1X2) y líneas sin devolución, igual que en F11.3.
* Las familias siguen **sin calibrar**: la medición no corrige el sesgo del nivel de córners que se vio en F11.4 (sección 7 de esa guía). Esa corrección es un experimento de F12, con su fila de promoción, no algo que esta medición haga por sí sola.
* **Cada apuesta es de una sola familia y de un solo partido.** Qué pasaría al juntar en una combinada selecciones de familias distintas del mismo partido lo mide aparte `DEPENDENCIA_FAMILIAS_F11.md` (F11.6): hoy no se propone relajar la regla de «una selección por partido».
