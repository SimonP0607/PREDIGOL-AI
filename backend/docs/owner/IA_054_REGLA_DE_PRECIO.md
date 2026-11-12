# IA-054 · Regla de precio como vara de comparación, en sombra (INT-A10)

Pieza INT-A10 del Plan Maestro de Intelligence 2026 (sombra). Mide qué daría **el precio solo**: tomar una selección cuando la mejor cuota del mercado paga más que el consenso sin margen, sin modelo, sin calibración y sin contexto. Es **una vara de comparación** para medir contra ella lo que aporta el análisis (E6, E4, la deliberación). **Nunca es fuente de picks**, por tu criterio de que el valor salga del análisis y no de que una casa pague más: no tiene ningún camino a la publicación, ni a `picks`, ni a `intel.decisions`, ni a la decisión.

Se construye encima de IA-037 (INT-A06: el precio del libro con su edad y su cierre), todavía sin fusionar, y reutiliza su lectura del libro sin cambiarla.

## 1. La regla (`price-rule-v1`)

* **Qué se toma.** Una selección de los mercados del núcleo de `decision-v1` (1X2, goles, ambos marcan, hándicap asiático, doble oportunidad), **la primera vez** que, dentro de la ventana en la que decide `decision-v1` (de 36 h a 10 min antes del saque), su **mejor cuota supera al consenso sin margen (Shin) en al menos un 2 %**: `mejor cuota × probabilidad del consenso − 1 ≥ 0,02`.
* **Con las mismas puertas de precio que `decision-v1`.** Al menos 3 casas, no atípica (como mucho un 25 % por encima del consenso) y no más vieja de 3 h. Todos los umbrales se **importan** de `decision-v1`, no se copian: si un día cambian allí, cambian aquí.
* **Qué se mide.** El CLV de siempre (`clv-v1`: `cuota tomada × probabilidad sin margen al cierre − 1`) frente al **último precio observado antes del saque**, con dos lecturas del mercado:
  * **capturas** (`consensus`, la historia larga): los momentos son las capturas del consenso (de T-72 h a T-3 h) y el cierre es la referencia del sistema, el último consenso antes del saque (`closing_reference`, unas 3 h antes);
  * **libro** (`book`, desde los refrescos del 9-nov): los momentos son las consultas de captura y de refresco, y el cierre es la última respuesta antes del saque (la medida `Close` de IA-037, unos 10 min antes).
* **Una selección cuyo cierre no es posterior a la toma no se mide**: sería medir una foto contra sí misma (pasa con lo que se toma en la última captura, T-3 h, cuando no hay refrescos). Se cuenta aparte (`not_later`), igual que la que no tiene cierre (`no_close`, o el estado de la última respuesta del libro: `withdrawn`, `not_quoted`…).
* **Intervalo.** La media del CLV con su intervalo del 95 % remuestreando **partidos enteros** y, aparte, **días enteros** (Bogotá), 2.000 réplicas, semilla fija `20261111`: la misma entrada da el mismo informe.
* **Gate de la ficha.** Un informe necesita **al menos 300 selecciones medidas**; con menos dice `pending_sample` («pendiente por muestra»).

## 2. Qué se midió (solo lectura, producción)

12-nov-2026, entre las 13:41 y las 13:53 UTC. El código de esta rama corrió dentro del worker, por la entrada estándar, en una sesión de solo lectura (`default_transaction_read_only`); la imagen desplegada era `3da952b7a4c6`. Al terminar, la carpeta temporal del servidor se borró.

| Informe | Selecciones medidas (partidos, días) | CLV medio, IC95 por partido | IC95 por día | Positivas | Valor de la cuota al tomarla | Deriva del consenso hasta el cierre | Cierre | Gate |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| Capturas, 12-oct a 10-nov | 2.705 (1.045, 30) | +5,77 % [5,28; 6,24] | [5,32; 6,27] | 85,6 % | +5,65 % | +0,12 pp (mediana 0) | unos 176 min antes del saque | **informe** (≥ 300) |
| Capturas, 10 y 11-nov | 151 (29, 2) | +7,25 % [4,07; 9,99] | [6,31; 10,07] | 82,8 % | +6,30 % | +0,31 pp | 175 min | pendiente por muestra |
| Libro, 10 y 11-nov | 357 (34, 2) | +6,99 % [4,66; 9,19] | [5,80; 7,33] | 86,0 % | +6,29 % | +0,29 pp (mediana 0) | 8,8 min | informe |

- **De dónde sale la muestra:** 3.367 partidos y 278.480 selecciones con precio en los 30 días. Quedaron sin medir 885, porque no había un cierre posterior a la toma.
- **Por mercado (30 días):** 1X2 +5,7 %, hándicap +5,9 %, más/menos +5,0 %, ambos marcan +5,4 % y doble oportunidad +10,2 %.

**Cómo leerlo.** Esto **no es valor**. La probabilidad del consenso apenas se mueve hasta el cierre: su deriva media es de 0,12 pp, y la mediana, cero. El CLV sale casi entero de la distancia entre la mejor cuota y el consenso sin margen en el momento de tomarla: +5,65 % frente a +5,77 %. Con el libro, que cierra a 9 minutos del saque en vez de a 3 horas, la cifra apenas cambia.

Eso es justo lo que pedía la ficha, una **vara**: «el precio solo» ya da un CLV de unos +5,8 % frente al consenso de cierre. Por tanto:

- un CLV positivo frente al consenso, por sí solo, no demuestra que un modelo, E6 o la deliberación aporten nada;
- tienen que mejorar este CLV sobre las mismas selecciones;
- cuentan además que la mejor cuota sea de verdad accesible (casas atípicas, límites), y la regla ya excluye las de más del 25 % sobre el consenso.

La regla **no tiene ningún camino a la publicación** (apartado 4).

## 3. Qué cambia (código)

* **`fbi/decision/price_rule.py` (nuevo).** La regla y su medida, puras y probadas (`verdict`, `first_taken`, `measure`, `summarise`), y sus lecturas de solo lectura: las capturas por partido (un tramo del índice `(fixture_id, as_of)` por partido, con un prefiltro en SQL un pelo más ancho que la regla, que la aplica exacta en Python), el cierre con `closing_reference.closing_probabilities` (la referencia del sistema) y el libro con `book_price` (IA-037) tal cual. **No edita `book_price`, `engine.py`, `replay.py` ni `scripts/ia_decision_v2.py`.**
* **`scripts/ia_price_rule.py` (nuevo).** `report --since AAAA-MM-DD --until AAAA-MM-DD [--price consensus|book] [--raw DIR] [--json]`. Los días son de Bogotá (`--until` no incluido y nunca después de ahora). Conexión de solo lectura y 95 s por sentencia.

```
docker exec -w /app predigol-worker python -m scripts.ia_price_rule report --since 2026-10-12 --until 2026-11-11              # capturas, 30 días
docker exec -w /app predigol-worker python -m scripts.ia_price_rule report --since 2026-11-10 --until 2026-11-12 --price book # libro
```

* **Pruebas.** `tests/unit/test_price_rule.py` (19: la regla con los umbrales de `decision-v1`, la primera toma dentro de la ventana y nunca leyendo después, el CLV contra un cierre posterior, el intervalo determinista, el gate de 300, el libro consulta a consulta con sus refrescos, el comando, y que no escribe ni lee `picks`/`intel` ni llama a ninguna etapa de la decisión); `tests/integration/test_price_rule.py` (2, PostgreSQL: las capturas leídas por partido, solo Shin, nunca un partido aplazado ni el consenso de después del saque; y una captura tomada **igual, al decimal**, desde el consenso y desde el cuerpo del libro, con el refresco dándole al libro un cierre posterior que las capturas no tienen); `tests/unit/test_decision_v2_isolation.py` (el comando nuevo es el único que importa la regla, y la regla solo nombra el almacén RAW que le pasa al libro).

## 4. Qué no cambia

* No es un pick ni lo puede ser: nada de lo que decide, publica o sirve a los lectores importa `fbi.decision`, y dentro de él nada importa la regla salvo su propio comando (prueba de aislamiento). No escribe nada.
* `decision-v1`, `decision-v2` (motor, repetición y su comando), el libro y su código (de Cuotas), los umbrales, los picks, la muestra de la sombra, los agentes, los motores y los interruptores. Ninguna migración, ningún interruptor, ninguna petición al proveedor.

## 5. Cómo leerla

* **Es la vara, no un resultado del análisis.** Una media de CLV positiva aquí mide sobre todo la distancia entre la casa que más paga y el consenso (lo que se gana comparando casas), no que se sepa algo del partido. Un análisis que no supere esta vara no está aportando valor propio.
* **El CLV frente a las capturas mide el movimiento hasta unas 3 h antes del saque**, no hasta el saque; el del libro llega a unos 10 min, pero solo existe desde el 9-nov.

## 6. Vuelta atrás

Revertir el PR. No hay migración, ni interruptor, ni datos escritos.
