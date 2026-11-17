# IA-083 · Cifra única para toda salida (AD-B05) · IA-084 · Pruebas de coherencia G-COH (AD-B09)

Piezas AD-B05 y AD-B09 del plan de la arquitectura definitiva 2026 (responsable: Modelos). Hasta hoy cada salida calculaba su propia probabilidad: la página del partido escribe `forecast-v1` (tres mercados, cada uno calibrado por su lado), la capa de decisión calibra selección por selección (`decision-v1`), Picks muestra la cifra cruda del modelo y un texto repite la que le den. Esta pieza crea **una sola función** que da la probabilidad de cualquier mercado de goles de un partido, con su sello, su modelo, su versión, la hora de su precio y un identificador que un texto puede citar. También añade **pruebas automáticas** que fallan si dos salidas dan cifras distintas para la misma selección y versión, y un **informe de solo lectura** con las incoherencias actuales en producción.

**Todo en sombra. Lo que ve el lector no cambia**: la página, el paquete de la IA y la proyección pública del contrato del partido siguen con `forecast-v1`. **Ningún modelo de lenguaje toca un número**. No se ajusta, promociona ni retira ningún calibrador. No toca `decision-v1`, ni los paquetes de modelos (su huella no cambia), ni `web/`, ni los picks publicados. `FBI_PICKS_SOURCE` sigue apagado. Sin migración y sin interruptor nuevo.

## 1. La cifra única (`forecast-v2`, `fbi/forecasting/single_figure.py`)

Para un partido y un momento, con los números más recientes de cada modelo, el consenso del mercado sin margen y los calibradores vigentes:

| Mercado | De dónde sale la cifra | Sello |
| --- | --- | --- |
| 1X2, más/menos 2,5, ambos marcan | Exactamente la función de `forecast-v1` (`market_view.forecast_market`): mismo modelo, misma calibración, mismos números con el mismo precio | El del campeón con el precio de los últimos **4 días** (la regla del sello estable `seal-v1`, IA-073) |
| Doble oportunidad, empate no acción, hándicap asiático −0,5 / −0,25 / 0 / +0,25 / +0,5 | **El 1X2 sumado**: «Local −0,5» es «Local»; «1X» es Local + Empate | El del 1X2 (un mismo suceso, una sola cifra) |
| Resto de líneas de más/menos y de hándicap asiático | La fila guardada del modelo especializado del mercado o, si el modelo no guardó esa línea, su **matriz de marcadores** (IA-074) | El campeón del mercado aplicado a cada lado con su precio, y el par reescalado para que sume 1 con la devolución; sin campeón o sin precio, «sin calibrar» con su motivo |
| Goles de cada equipo, hándicap europeo | La matriz de marcadores | «sin calibrar» (`no_champion`): no existe calibrador para ellos |
| Córners, tarjetas, mitades, jugadores | **Sin cifra**, con el motivo `not_in_view` (llegarán con AD-B07) | — |

La matriz se reconstruye de las siete filas guardadas del propio modelo (`score_matrix.invert`, la misma solución que el simulador; una prueba lo comprueba). **No hizo falta migración**: los parámetros se recuperan de filas de solo añadido de forma determinista, así que una matriz recalculada después es la misma.

Cada cifra lleva un **identificador de lectura** de 12 caracteres (versión, partido, selección y entradas de su conjunto). Si cambia la versión o cualquier entrada, cambia el identificador.

## 2. Quién la usa (en sombra)

- **decision-v2**: `python -m scripts.ia_decision_v2 replay --day AAAA-MM-DD --probability common --view-version forecast-v2`. Las etapas juzgan la cifra única: su modelo, su intervalo y su sello. Sin sello calibrado no hay valor calibrado. Por omisión nada cambia (`own` y `forecast-v1`).
- **Contrato del partido (C-01), solo la proyección privada** (`/api/v1/admin/intelligence/matches/{id}/intelligence`, `require_admin`): bloque nuevo `single_figure` con todas las cifras de goles del partido. El contrato pasa a **1.1.0** (cambio aditivo). La proyección pública no lo trae, ni siquiera lo calcula, y sus cifras siguen siendo `forecast-v1`.
- **Textos nuevos** (`fbi/forecasting/figure_text.py`, regla `figure-text-v1`): un texto solo puede escribir un porcentaje repitiendo una cifra con su cita, así: `57 % [cifra forecast-v2 3f9a1c2b7d4e]`. El verificador **rechaza el texto entero** si un porcentaje no lleva cita, si cita otra versión, si cita una lectura que no existe, si el número no es la cifra citada redondeada como la redondea el contrato, o si una cita no acompaña a ningún porcentaje. La crónica única (AD-F02) será su primer usuario; hoy ningún texto cita lecturas.

## 3. Pruebas de coherencia G-COH (IA-084)

- **Sin base de datos** (`tests/unit/test_gcoh_parity.py`): de un mismo conjunto de cifras, la función, el bloque del contrato, el número que juzga decision-v2 y un texto que cita las cifras dan la misma cifra a seis decimales, con el mismo sello, modelo y versión. La prueba **muerde**: si en cualquiera de las tres salidas se mueve una cifra 0,1 puntos, se cambia un sello, se cambia la versión o falta una cifra, falla y nombra la selección.
- **Los tres casos adversarios de la ficha**: un texto con una cifra desplazada 0,1 pp, uno sin cita y uno con una cita de otra versión. **Los tres se rechazan** (3 de 3), y también la cita a una lectura inexistente y la cita suelta.
- **Con PostgreSQL** (`tests/integration/test_single_figure_parity.py`, 4 pruebas): el lector, el contrato privado servido desde la base y decision-v2 dicen lo mismo; las tres cifras de la página son `forecast-v1` con su ventana de 6 h y el sello estable con la suya; la repetición de decision-v2 con la cifra única no escribe nada y es determinista; y el informe de producción no encuentra ninguna diferencia donde la cifra única debe reproducir la página.
- **Regresión**: con la ventana de 6 h, las tres cifras de la página salen idénticas a `forecast-v1` (prueba unitaria y de integración).

## 4. Medición en producción (solo lectura, 17-nov-2026 04:49 UTC)

Comando nuevo `python -m scripts.ia_single_figure check --hours 24|72 --json`, con conexión de solo lectura. Muestra: partidos que empiezan en las próximas 24 h (**38**) y 72 h (**68**) con pronóstico en la página. Diferencias en puntos porcentuales; la tolerancia de AD-B05 es **0,05 pp**.

| Superficie, frente a la cifra única | 24 h | 72 h | Lectura |
| --- | --- | --- | --- |
| **Repetición**: cada conjunto guardado de `forecast-v1`, recalculado en su propio momento con su ventana de 6 h | 186 de 186 iguales (máx. 0,0 pp) | **388 de 388 iguales** (máx. 0,0 pp) | La cifra única reproduce la página en producción, sin una sola diferencia |
| Matrices reconstruidas | 36, ninguna rechazada | 91, ninguna rechazada, residuo máx. 5,4·10⁻⁷ | Los parámetros salen de las filas del propio modelo |
| **Match Center ahora** (`forecast-v1`) | 118 de 186 > 0,05 pp; mediana 1,4 pp | 250 de 388; mediana 1,6 pp, máx. 35,1 pp | 238 de las 250 por **sello distinto**: la página dice «sin calibrar» porque el precio tiene más de 6 h, y la cifra única lo calibra con el precio de los últimos 4 días (la alternancia que corrige IA-073). Las otras 12 son el mismo sello con otro momento |
| **decision-v1** (`p_cal`), en el momento de cada decisión | 198 de 208 > 0,05 pp; mediana 2,6 pp | 246 de 256; mediana 2,6 pp, máx. 15,6 pp | 59 por **otro modelo**; 186 por la calibración selección a selección. Cobertura: **256 de 256** selecciones del núcleo tienen cifra única |
| **Picks**, cifra cruda (`picks.picks`) | 208 de 208; mediana 15,2 pp | **368 de 368**; mediana 12,6 pp, máx. 59,8 pp | Picks muestra el número del modelo sin calibrar |
| Picks con `FBI_PICKS_SOURCE` (apagado) | 204 de 208; mediana 2,7 pp | 364 de 368; mediana 4,2 pp | Lo que vería un lector si se encendiera hoy: la cifra de decision-v1, no la única |
| Textos | — | — | **No medible todavía**: ningún texto cita una lectura |

**Coherencia de la propia cifra única entre mercados** (72 h): **46 de 68 partidos** rompen alguna regla. Son 488 escaleras no monótonas y 46 casos de «europeo +1 local ≠ asiático +0,5 local». Hay además 2 sumas fuera por 10⁻⁹, del redondeo a seis decimales de las filas guardadas: el informe ya usa la tolerancia del redondeo, 2·10⁻⁶, pero no lo he vuelto a ejecutar. Las escaleras y el europeo son reales, y nacen de que los calibradores se ajustaron mercado a mercado y línea a línea. Por ejemplo, «más de 1» (gana o devuelve) sale calibrado más alto que «más de 0,5», cuando es el mismo suceso. La calibración coherente se rechazó en IA-036. **Esta pieza no lo corrige**: lo mide y lo deja a la vista. Hay tres caminos posibles, y los tres necesitan protocolo y tu firma:
1. calibrar solo la línea principal y derivar las demás de la matriz;
2. una calibración coherente de la matriz;
3. dejar sin calibrar las líneas sin campeón propio.

## 5. Qué no cambia

La página del partido, la proyección pública del contrato, el paquete de la IA, decision-v1, los picks publicados y su liquidación, los calibradores, los modelos y su huella, `web/`, `FBI_PICKS_SOURCE`.

## 6. Cómo se activa, cómo se repite y cómo se revierte

- **Activación**: ninguna. Tras desplegar, el bloque privado de C-01 se calcula al pedirlo y la repetición de decision-v2 acepta `--view-version forecast-v2`.
- **Repetir la medición**: `docker exec -w /app predigol-worker python -m scripts.ia_single_figure check --hours 72 --json`.
- **Revertir**: revertir el PR. No escribe datos, no hay migración ni interruptor. Para que un lector vea la cifra única hace falta otra pieza y tu firma; el orden lo marca el plan (AD-D01, y `FBI_MATCH_INTELLIGENCE` para el contrato público).

## 7. Pendiente

- **Cierre de AD-B05**: pide 0 diferencias > 0,05 pp entre salidas. Hoy solo se cumple entre las salidas que ya leen la cifra única: la función, C-01 privado, decision-v2 y los textos. Picks, la página y decision-v1 seguirán distintos hasta que firmes el cambio de cada lector.
- **Cierre de AD-B09 en sombra**: hace falta un texto real que cite lecturas (AD-F02) para medir los textos de producción.
- **Escribir `forecast-v2` en `models.match_forecasts`** (con su volumen medido) en lugar de calcularla al vuelo: lo dejo para AD-D01, que persiste decision-v2.
