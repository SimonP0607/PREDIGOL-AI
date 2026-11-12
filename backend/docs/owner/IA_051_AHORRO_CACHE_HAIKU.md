# IA-051 · El panel de costes exageraba el ahorro de la caché de Haiku

Fecha: 11 nov 2026. Hallazgo de IA-034 (INT-T01). Cambia **solo el informe**: el cálculo del ahorro del panel de costes (`fbi.ai.costs_v3.savings`). No toca presupuestos, sobres, proyección, interruptores, agentes, enrutado, prompts ni lo que el libro (`ai.usage`) guarda o cobra. Sin migración y sin cambios en la web: los campos del panel son los mismos y lo que cambia son sus valores.

## 1. Qué estaba mal

El panel sumaba los tokens de **todas las llamadas de un día** (día de Bogotá, modelo, tiempo real o Batch) y valoraba esa suma **como si fuera una sola llamada**. Haiku 5.5 cobra cinco veces más (0,50 / 2,50 / 0,05 US$ por millón en vez de 0,10 / 0,50 / 0,01) cuando **un solo prompt** pasa de 100.000 tokens de entrada. Ninguna llamada de Haiku llega a eso (la mayor de la ventana medida: 32.166 tokens), pero la suma de un día siempre lo pasa (la menor de los 21 grupos diarios: 127.517 tokens). El panel valoraba lo «fresco» al precio largo, cuando lo facturado se había cobrado al normal, y esa diferencia salía como ahorro.

La cuenta se reproduce a mano. Como el precio largo es exactamente cinco veces el normal en las tres tarifas, el panel decía **5 × (lo facturado + el ahorro real) − lo facturado = 4 × facturado + 5 × ahorro real**. Para `brief-v8` en la ventana de la primera corrida de IA-034 (28-oct 05:07 a 11-nov 05:07 UTC): 4 × 11,0067 + 5 × 1,5407 = **51,73**, que es la cifra que dio. Al ahorro del Batch de Haiku le pasaba lo mismo (salía multiplicado por cinco).

Sonnet 5.5 y Opus 5.5 no tienen precio largo, así que sumar sus llamadas no cambiaba nada: sus cifras son iguales antes y después.

Se descartaron las otras causas posibles. No había precios de otro modelo (cada grupo se valoraba con el suyo). Las escrituras de caché no se contaban como ahorro (restaban, como deben). La lectura de caché no iba a un precio equivocado. El Batch no se contaba dos veces. Tampoco había deriva de la tabla: de 7.654 llamadas, ninguna tiene en el libro un coste distinto del que da la tabla de precios.

## 2. Cuánto (producción, solo lectura, 11 nov 2026 14:06 UTC)

Ventana **28-oct 00:00 a 11-nov 00:00 UTC**, 7.654 llamadas de Claude con tokens (producción y LAB; Exa no entra). En US$:

| Modelo | Llamadas (Batch) | Caché antes | Caché ahora | Batch antes | Batch ahora |
| --- | ---: | ---: | ---: | ---: | ---: |
| Haiku 5.5 | 6.166 (1.141) | 64,29 | **1,96** | 5,47 | **1,09** |
| Sonnet 5.5 | 1.255 (809) | 2,91 | 2,91 | 12,30 | 12,30 |
| Opus 5.5 | 233 (36) | 0,98 | 0,98 | 0,70 | 0,70 |
| **Total** | **7.654 (1.986)** | **68,18** | **5,85** | **18,47** | **14,09** |

* Ahorro total de los 14 días: decía **US$ 86,65** y es **US$ 19,95**. Casi todo lo ahorra el Batch de Sonnet (de sus 12,30, 9,55 son las revisiones de producción, según IA-034); la caché ahorra unos US$ 0,42 al día.
* `brief-v8` solo: en la ventana de IA-034 (00:00 UTC), 3.686 llamadas, decía 53,21 y es **1,59**, la misma cifra que IA-034 contó llamada a llamada. En la ventana de su primera corrida (05:07 UTC) decía 51,73 y es 1,54.
* **Lo que enseña hoy el panel** (noviembre de Bogotá hasta el 11-nov 14:06 UTC, 6.093 llamadas): decía US$ 66,01 de ahorro (caché 50,72 + Batch 15,29); con la corrección son **US$ 15,60** (caché 4,74 + Batch 10,86).
* Comprobación independiente: una consulta SQL, con los precios escritos a mano y sin el código de precios, valora cada llamada y da 5,854962 de caché y 14,092321 de Batch. El código nuevo da 5,854976 y 14,0923. La diferencia (0,000014) es el redondeo a la millonésima de cada llamada.
* El script (código nuevo y desplegado sobre la misma instantánea, en solo lectura) y su salida están en `docs/owner/lab/IA_051/`.

## 3. Qué cambia

* `costs_v3.savings` valora **cada llamada sola** (`Call`), con la misma función que la facturó (`fbi.ai.pricing.token_cost`) y en su fecha UTC: lectura de caché frente a entrada normal, la escritura cuesta más (nunca ahorra) y el Batch va a mitad de precio. La consulta lee una fila por llamada (`CALLS_SQL`) en lugar de sumas por día. Leer y valorar el mes en producción (6.093 llamadas) tarda 0,18 s.
* De paso, el precio de una promoción (Gemini 3.8 Flash, hasta el 31-dic) se lee en la fecha UTC de cada llamada, como lo factura el libro, y no en el día de Bogotá del grupo. Hoy no se usa Gemini.
* Pruebas: `tests/unit/test_costs_v3_pure.py` fija el caso de Haiku (30 llamadas de 20.000 tokens dan 0,0135; la suma valorada como una llamada daría 0,3135), una llamada de Haiku de más de 100.000 tokens (paga el precio largo, y su ahorro también), el Batch de Haiku y **los 22 modelos de la tabla** contra un oráculo que calcula el ahorro con la fórmula directa. `tests/integration/test_costs_v3.py` fija el panel entero con 12 llamadas de Haiku en el libro: 0,0054 (antes, 0,1254). Con el cálculo antiguo fallan 9 de las 32 pruebas unitarias, justo las de los modelos con precio largo y la de la fecha.

## 4. Lo que no se puede medir y un límite

* El panel mide el ahorro con la tabla de precios actual. Si un precio cambia a mitad de mes, la tabla debe guardar el precio anterior con su fecha (como ya hace con la promoción de Gemini); si no, el ahorro de las llamadas anteriores mezclaría los dos precios. Hoy el libro y la tabla coinciden en las 7.654 llamadas.
* El ahorro de la caché se mide contra «toda la entrada fresca», no contra lo que habría costado con otro diseño del prompt.

## 5. Vuelta atrás

Revertir el PR de IA-051: el código es un solo módulo (`fbi/ai/costs_v3.py`), sin migración ni datos. El panel volvería a enseñar la cifra inflada. No hay interruptor porque no cambia nada de lo que decide o cobra.
