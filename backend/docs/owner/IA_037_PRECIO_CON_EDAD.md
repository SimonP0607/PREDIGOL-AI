# IA-037 · Precio de decisión con su edad (INT-A06)

Pieza INT-A06 del Plan Maestro de Intelligence 2026 (sombra). Mide qué edad tiene el precio con el que se decide, qué tan fresco estaba el libro de cuotas en ese mismo momento y qué tan lejos del saque está el último precio que tenemos de cada partido (el del CLV). Añade a la repetición de `decision-v2` una segunda fuente de precio, **el libro**, que se elige con una opción y que **por defecto no se usa**. No toca `decision-v1` (`fbi/intel/decision.py`), ni el libro (código de Cuotas), ni nada que decida, publique o sirva a los lectores.

Todo lo medido es de solo lectura en producción, el 11-nov-2026 entre las 13:30 y las 14:40 UTC. Las consultas están en `docs/owner/lab/IA_037/` (de la `01` a la `06`); cada cifra dice de cuál sale.

## 1. Qué se midió

### 1.1 La edad del precio en las decisiones de `decision-v1` (consulta 01)

Filas de `intel.decisions` con `decision_version = decision-v1` y `known_at` entre el 12-oct y el 11-nov (30 días UTC): **68.014 filas de 3.115 partidos** (la primera del 13-oct 07:32, la última del 10-nov 20:19; ninguna copia de «pick del día» en la ventana). La edad es `known_at − price_at`: lo que tenía el precio cuando se decidió.

* **Sin edad de precio: 81 filas (0,12 %)**, y las 81 son filas **sin precio**: todas RECHAZADO con el motivo `no_price` (45 con él primero, 36 rechazadas antes por datos). **No hay ninguna fila con precio y sin edad.** Para `decision-v2` la repetición lo cuenta ahora en cada informe (`price.without_age`, apartado 3).
* Edad (67.933 filas con precio): mediana **99,7 min**, p75 713, p90 728, p95 730, máximo 2.160 (las 36 h que se mira hacia atrás). El 32,0 % pasa de 3 h (`price_stale` en 20.403 filas) y el 18,6 % tiene `price_not_fresh` (más de 30 min desde T-90m).

| Punto de control | Filas | Mediana (min) | p75 | p90 | p95 | Más de 3 h |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| T-36h | 17.733 | 724,8 | 729,3 | 747,3 | 1.030,5 | 17.109 |
| T-24h | 11.597 | 19,7 | 29,8 | 403,6 | 679,5 | 1.710 |
| T-12h | 12.940 | 19,7 | 35,3 | 208,5 | 319,4 | 1.962 |
| T-6h | 6.970 | 14,8 | 49,9 | 356,7 | 360,0 | 758 |
| T-3h | 5.985 | 9,9 | 19,9 | 84,9 | 179,8 | 109 |
| T-90m | 3.936 | 95,0 | 99,9 | 100,0 | 108,7 | 38 |
| T-60m | 4.079 | 125,1 | 130,0 | 140,0 | 174,4 | 76 |
| alineaciones | 4.693 | 169,7 | 174,6 | 175,0 | 175,0 | 4 |

Por horas al saque: en la última hora la mediana es **160 min** (8.767 filas) y el p95 175; de 1 a 3 h, 30 min; de 3 a 6 h, 15; de 6 a 12 h, 20; de 12 a 24 h, 20; de 24 a 36 h, 725.

### 1.2 La edad en cada pase de 15 minutos (consulta 06)

Las filas se escriben cuando algo cambia (sobre todo, justo después de cada captura), así que su edad sale baja. La edad que tendría una decisión **en cualquier pase** del trabajo de decisión (cada 15 min, de T-36 h a T-10 min) es otra: 3.097 partidos decididos, 407.162 pases con precio.

| Horas al saque | Pases | Mediana (min) | p90 | Más de 3 h | Más de 60 min |
| --- | ---: | ---: | ---: | ---: | ---: |
| 0-1 | 9.299 | 145,9 | 163,4 | 1,9 % | 99,3 % |
| 1-3 | 24.584 | 69,8 | 115,5 | 2,0 % | 51,0 % |
| 3-6 | 36.465 | 99,8 | 174,1 | 2,2 % | 67,3 % |
| 6-12 | 71.790 | 190,1 | 335,8 | 50,9 % | 83,6 % |
| 12-24 | 137.301 | 369,2 | 657,6 | 75,0 % | 91,6 % |
| 24-36 | 127.723 | 1.048,6 | 1.362,3 | 99,0 % | 99,7 % |

En las próximas 24 h la mediana es **190 min (3,2 h)**: coincide con los 3,4 h de la Parte I del plan, que eran una foto de un momento.

### 1.3 De dónde sale ese precio (consulta 02)

De 68.160 filas con precio (la ventana alargada hasta el 11-nov 14:00), **68.154 (99,99 %) tienen el precio de la última captura** del partido (una de las seis ventanas, T-72 h … T-3 h), con ±2 min; 6 tienen la anterior, 24 h más vieja (no se comprobó por qué), y **26 usaron un precio aunque la última consulta había vuelto vacía** (el proveedor había retirado los precios). Es decir: el precio de la decisión envejece entre captura y captura, y después de T-3 h no hay ninguna más.

### 1.4 El libro con refrescos, en esos mismos momentos (consultas 02, 05 y 06)

Los refrescos del libro (BE-011) existen **desde el 9-nov 23:08 UTC**: 774 consultas de 93 partidos hasta el 11-nov 13:05 (una vacía). Antes, el libro eran las mismas seis capturas y su edad era la de la decisión, franja por franja (consulta 02).

* **Filas de la era de refrescos** (desde el 9-nov 23:08; 285 filas de 41 partidos): en **163 (57 %)** había en vigor un refresco más nuevo que la captura. Edad de la decisión: mediana 717 min; la del libro: **120 min**.
* **Coherencia entre libro y decisión** en esas 163 filas: la mejor cuota del libro difiere de la de la decisión en una mediana de 0,0 %, p90 **5,6 %**, máximo 14,8 %; la probabilidad sin margen, mediana 0,0, p90 **0,88 pp**, máximo 7,5 pp. **28 filas (17 %) se movieron más de un 3 %** (el umbral de movimiento de `decision-v1`).
* **Pases de 15 min** desde el inicio de los refrescos, partidos decididos (25 a 29 partidos por franja; 2.935 pases):

| Horas al saque | Pases | Edad de la captura (mediana / p90) | Edad del libro (mediana / p90) | Selecciones cuya mejor cuota difiere más de un 3 % (pases con refresco en vigor) | Sello del proveedor del libro (mediana) |
| --- | ---: | ---: | ---: | ---: | ---: |
| 0-1 | 74 | 144 / 160 | **14 / 29** | 22,9 % de 6.729 | 208 min |
| 1-3 | 187 | 59 / 114 | **29 / 59** | 3,7 % de 8.576 | 285 min |
| 3-6 | 299 | 86 / 160 | **29 / 59** | 5,2 % de 17.850 | 180 min |
| 6-12 | 684 | 176 / 326 | **88 / 163** | 11,7 % de 30.704 | 230 min |
| 12-24 | 997 | 465 / 675 | **103 / 270** | 21,2 % de 73.250 | 293 min |
| 24-36 | 694 | 943 / 1.255 | **85 / 160** | 27,9 % de 55.802 | 369 min |

  La frescura del libro importa sobre todo lejos del saque (entre capturas pasan 12-24 h) y en la última hora (después de la captura de T-3 h el proveedor todavía actualiza). Entre T-6 h y T-1 h el refresco suele traer el mismo cuerpo que la captura (73-83 % de los pases con refresco en vigor).
* **Cobertura**: los 42 partidos con saque el 10 y el 11-nov que tenían capturas tenían también refrescos; los 31 decididos, todos. Las 163 selecciones de las filas estaban en el cuerpo del refresco; ninguna respuesta vacía.
* **Paridad**: el consenso reconstruido desde el crudo (RAW) para 286 cuerpos de captura (5-11 nov) es **idéntico** al guardado en `market.market_consensus`: 24.115 selecciones, diferencia 0. El precio del libro se calcula igual que el de la decisión; solo cambia **cuándo** se confirmó.

**Dos edades distintas.** La edad del libro es el tiempo desde la última consulta que confirmó el precio (la regla del libro y del explorador, `fbi/odds/freshness.py`). El **sello del proveedor** (`update`) dice cuándo movió él sus precios por última vez, y es mucho más viejo: 3-6 h de mediana incluso en la última hora. Es una propiedad de API-Football, no de nuestras consultas: se guarda como información, no como filtro.

### 1.5 El último precio antes del saque, para el CLV (consultas 03 y 06)

* **El de hoy** (la referencia del CLV del sistema: el último consenso antes del saque), 3.097 partidos decididos: **175,9 min antes del saque** de mediana (p10 174,9, p90 179,4): la captura de T-3 h. El sello del proveedor de ese cuerpo: 368 min antes del saque.
* **El del libro** (36 partidos ya jugados con refrescos): la última respuesta llega **8,8 min antes del saque** (p90 9,2: el refresco de T-10). Su sello del proveedor: mediana 120 min antes (p10 60, p90 327). En **12 de 34 (35 %)** el proveedor actualizó después de ese sello (lo dice la lectura final tras el partido); en 22 era el mismo.
* **«El proveedor deja de actualizar unos 103 min antes del saque»**: la última actualización prepartido según la lectura final (`market.final_prematch_checks`), todos los partidos con saque del 12-oct al 11-nov: **3.218 partidos, mediana 88,8 min** (p10 24,6, p25 51,6, p75 150,8, p90 228,7). En los 14 días del 26-oct al 9-nov: 1.600 partidos, **mediana 102,8 min**: se reproduce el dato de BE-011 (1.578 partidos, 103 min) para su periodo. Por semanas va de 69 a 101 min. En el 81,5 % de los partidos decididos (2.510 de 3.078) esa última actualización llegó después de nuestra última captura (BE-011 decía 84 %).

### 1.6 ¿Se puede reconstruir el libro de un momento pasado? (consulta 04)

Sí, con un matiz.

* `market.book_current` **no tiene historia**: una fila por partido y tipo, que se reescribe y se borra 6 h después del saque.
* Pero cada consulta queda apuntada con el hash del cuerpo que la contestó: las de captura en `market.odds_asks` (desde el 5-oct: 23.895 consultas de 4.182 partidos, 2.127 vacías) y las de refresco en `market.book_asks` (desde el 9-nov 23:08). Y cada cuerpo está en el crudo (inmutable) con su índice (`raw.ingestion_payloads`). Con eso se sabe qué respuesta estaba en vigor en cualquier momento (la regla del libro: manda la consulta más nueva, A → B → A lee A, una respuesta vacía retira los precios) y sus precios salen del cuerpo, exactos (paridad 286/286).
* El matiz: los cuerpos de captura están también en `market.odds_quotes`, pero **los de refresco no** (el extractor se los salta a propósito): solo están en el crudo. Por eso la lectura nueva lee los cuerpos del crudo, los dos tipos igual.
* Coste: las consultas van por clave. `EXPLAIN` en producción: `odds_asks` y `book_asks` por su clave primaria (partido, hora); el índice del crudo por hash; `odds_quotes` por partido, definición y hora con 7 de sus 8 particiones descartadas (la de octubre tiene 19,1 millones de filas, 3,9 GB).

## 2. Propuesta de umbral de edad (G-PRECIO, condición 2) — la fijas tú

**No se aplica**: es una propuesta medida. El umbral es la cadencia de las consultas del libro más 15 minutos de margen para el trabajo de refresco (corre cada 5 min):

| Distancia al saque | Edad máxima del precio | Por qué |
| --- | ---: | --- |
| Última hora (de T-60 min al saque) | **45 min** | refrescos a T-30 y T-10 |
| De T-6 h a T-1 h | **75 min** | un refresco cada hora |
| Más de 6 h | **195 min (3 h 15)** | un refresco cada 3 h |

Con lo medido (pases de 15 min de los partidos decididos, consulta 06):

| Horas al saque | Pases | Libro dentro del umbral | Captura de hoy dentro del umbral |
| --- | ---: | ---: | ---: |
| 0-1 | 74 | 100 % | 0 % |
| 1-3 | 187 | 100 % | 62,6 % |
| 3-6 | 299 | 100 % | 43,1 % |
| 6-12 | 684 | 100 % | 55,1 % |
| 12-24 | 997 | 88,9 % | 7,8 % |
| 24-36 | 694 | 100 % | 4,9 % |
| **Total** | **2.935** | **96,2 %** | **25,0 %** |

En los 30 días de capturas (3.097 partidos, 407.162 pases) el precio de hoy estaría dentro del umbral en el **26,2 %** de los pases (0,5 % en la última hora). Con el libro, el único hueco es 12-24 h: hubo pases con más de 3 h 15 sin consulta (p90 de 270 min). **Hipótesis, no comprobada**: refrescos perdidos o tardíos por los reinicios del worker en los despliegues del 10 y el 11-nov; queda para Cuotas.

Qué haría una decisión con el precio por encima del umbral (la regla del plan: «el precio está caducado»): no pasa la condición de precio; en sombra, «esperar a un precio vigente». Esa parte se decide con G-PRECIO; nada de esto toca `decision-v1`, que sigue con sus 3 h y sus 30 min.

**Antes de fijarlo, más muestra.** La era de refrescos tiene día y medio, 25-29 partidos decididos por franja y cae en una semana de selecciones con pocos partidos. Propuesta: volver a medirlo con 14 días de refrescos (el 25-nov, junto al Gate B) con `ia_decision_v2 replay --price book` de cada día, que da estas cifras.

**Alternativa**: usar la misma regla del explorador (`fbi/odds/freshness.py`, tolerancia de 45 min). Es más permisiva en la última hora (deja precios de hasta 105 min a T-15 min).

## 3. Qué cambia (código, todo en `fbi/decision` y su comando)

* **`fbi/decision/book_price.py` (nuevo).** Lee el libro «como estaba» en un momento: las consultas de captura y de refresco de los partidos (por clave), el índice del crudo, los ids de las casas, y los cuerpos del crudo (comprobando su hash). La respuesta en vigor la elige la regla del propio libro (`quote_current.choose_in_force`, sin copiarla) y se pone precio con lo mismo que el consenso de una captura (`iter_odds` y `consensus`, Shin), con el mismo redondeo. Da también **el cierre**: la última respuesta antes del saque, con su distancia al saque y el sello del proveedor. Nunca lee una consulta posterior al momento.
* **`engine.py`.** El precio de cada decisión dice su fuente (`consensus` o `book`), qué consulta lo confirmó (`capture` o `refresh`), el sello del proveedor y, si no hay precio, por qué (`withdrawn`, `never_asked`, `not_quoted`, `unreadable`). Cada decisión puede llevar su **cierre** como medida (nada lo lee). Las etapas, los umbrales y los estados no cambian.
* **`replay.py` y `scripts/ia_decision_v2.py`.** Opción `--price book` (por defecto `consensus`, la de siempre). El informe añade una sección `price` con cuántas decisiones tienen precio y **cuántas no tienen edad** (la condición 1 de G-PRECIO; debe ser 0) y la edad por punto de control. Con `--price book`, además: qué consulta confirmó cada precio, por qué faltaba, la diferencia con el precio de `decision-v1` en la misma fila y el cierre. Con el libro, cada sentencia tiene un límite de 95 s.

```
docker exec -w /app predigol-worker python -m scripts.ia_decision_v2 replay --day 2026-11-10                # como siempre
docker exec -w /app predigol-worker python -m scripts.ia_decision_v2 replay --day 2026-11-10 --price book   # con el precio del libro
```

## 4. Qué no cambia

* La evidencia de P1: sin `--price book` la repetición da lo mismo que antes (acuerdos, tabla de confusión, desacuerdos); solo añade la sección de medida `price` y `inputs.price = "consensus"`.
* `decision-v1`, sus umbrales (`MAX_PRICE_AGE` 3 h, `FINAL_FRESH` 30 min), sus filas, los picks, la muestra de la sombra, los agentes, los motores y los interruptores.
* El libro, su código y sus tablas (de Cuotas): solo se leen. Ningún interruptor nuevo, ninguna migración, ninguna petición al proveedor.
* Nada que decide, publica o sirve a los lectores importa `fbi.decision` (prueba de aislamiento), y el paquete llega al libro por un solo módulo, sin tocar sus escritores.

## 5. Lo que no se pudo medir

* La era de refrescos es corta (desde el 9-nov 23:08) y con pocos partidos (parón de selecciones): las cifras del libro valen como primera medida, no como definitiva.
* Cuánto se ha movido de verdad el mercado en las casas entre dos actualizaciones del proveedor: solo vemos lo que API-Football sirve, y su sello es su propia hora.
* La repetición completa con `--price book` (cuántos estados de `decision-v2` cambiarían) necesita el código desplegado: es el primer paso después del despliegue (solo lectura).
* Límites de la lectura, los mismos del libro: de una respuesta se usa la primera página (en la práctica es una) y no se modelan los minutos que el extractor va detrás de la captura.

## 6. Cómo se comprueba

* `pytest -q -m "not integration" tests/unit/test_decision_v2_book_price.py tests/unit/test_decision_v2_*.py` y, con PostgreSQL, `tests/integration/test_decision_v2_book_price.py` (precio de un cuerpo de captura = su consenso guardado, refresco en vigor, cierre, repetición sin escribir nada y determinista).
* En producción, tras desplegar: la repetición de un día con y sin `--price book`; `price.without_age` debe ser 0 en las dos.

## 7. Vuelta atrás

Revertir el PR. No hay migración, ni interruptor, ni datos escritos: la opción `--price book` solo existe en el comando de repetición.
