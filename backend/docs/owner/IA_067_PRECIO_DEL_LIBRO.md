# IA-067 · El precio del libro como precio de decisión, con su edad por horizonte (AD-B06)

Pieza AD-B06 del plan de la arquitectura definitiva 2026, **decisión n.º 11** del dueño (aprobada el 16-nov-2026). Es una **versión nueva
de las reglas de `decision-v2`**, en sombra: `decision-v2.1`. Decide con el precio que el libro de cuotas tiene en vigor en cada momento y
comprueba su edad con un límite por horizonte (195, 75 y 45 min, con los bordes adelantados 15 min). No toca `decision-v1`
(`fbi/intel/decision.py`), ni el libro ni su ingesta (`fbi/odds`, `fbi/market`, de la sesión de Cuotas), ni nada que decida, publique o
sirva a los lectores. No hay interruptor: es una versión de la repetición en sombra, y por defecto todo sigue como estaba.

La medición es de solo lectura en producción, del 16-nov-2026 (entre las 23:30 y las 00:45 UTC): la repetición de 7 días, del 9 al
15-nov (días de Bogotá). Las órdenes están en `docs/owner/lab/IA_067/`.

## 1. Qué cambia

### 1.1 Dos versiones de las reglas, con nombre

| Reglas | Precio del núcleo por defecto | Regla de edad del precio | Para qué |
| --- | --- | --- | --- |
| `decision-v2.0` (por defecto) | consenso de la última captura (el de `decision-v1`) | `price-age-v1`: la de `decision-v1`, importada (3 h; 30 min en los puntos finales) | La evidencia de P1, como siempre |
| `decision-v2.1` (nueva, en sombra) | el libro: la respuesta en vigor, de una captura o de un refresco | `price-age-v2`: por horizonte, 195 / 75 / 45 min | La decisión n.º 11 |

Cada decisión dice con qué reglas se tomó (`rules`) y con qué regla de edad se juzgó su precio (`price.age_rule`). La capa sigue
llamándose `decision-v2`, igual que `decision-v1.1` sigue siendo la capa `decision-v1`.

### 1.2 La regla de edad por horizonte (`price-age-v2`)

El límite es **la cadencia de los refrescos del libro más el retraso normal de una consulta** (p99 de unos 15 min): 30 + 15, 60 + 15 y
180 + 15. Cada franja empieza **15 min antes** que la consulta que la abre, para que una decisión tomada justo antes de un refresco
programado siga leyendo el refresco anterior:

| Tiempo que falta para el saque | Edad máxima del precio |
| --- | ---: |
| 345 min o más | 195 min |
| De 345 a 45 min | 75 min |
| Menos de 45 min | 45 min |

Bordes exactos: a 345 min justos rige 195; a 45 min justos rige 75. Un precio con exactamente su edad máxima está vigente; un segundo
más, no. La edad se cuenta desde la consulta que confirmó el precio (como la cuentan el libro y el explorador).

Dónde actúa:

* **Etapa 3 (mercado):** un precio más viejo que su límite es `price_stale` (estado WATCH), como en `decision-v1`.
* **Etapa 9 (precio final):** en los puntos finales (T-90m, alineaciones, T-60m, T-15m) rige el mismo límite de la franja
  (`price_not_fresh`, CAUTION). Así la etapa 9 nunca rechaza sola lo que la etapa 3 acepta.
* **Un precio sin edad** no se puede comprobar: es antiguo (`no_age`).
* **Solo para los precios del libro.** La regla sale de la cadencia del libro, así que solo juzga precios del libro. Un precio que no sale
  del libro (las familias de mercados con sus propias cuotas, o el núcleo si se pide `--price consensus`) sigue con la regla de `decision-v1`.

Comparada con `decision-v1`, es más exigente entre T-5 h 45 y T-45 min (75 min en lugar de 3 h). Es más permisiva lejos del saque
(195 min en lugar de 180) y en los puntos finales (45 a 75 min en lugar de 30). Es lo aprobado en la decisión n.º 11, y solo en sombra.

### 1.3 El estado del precio, para la interfaz (contratos C-01 y C-02)

Cada decisión lleva el estado de su precio (`price.state`) con su motivo (`price.state_reason`), el límite que se le aplicó
(`price.max_age_minutes`) y la franja (`price.band`):

* **`vigente`**: hay precio y está dentro de su límite.
* **`antiguo`**: hay precio, pero es más viejo que su límite (`over_limit`; `over_final` en un punto final con la regla de `decision-v1`) o
  no tiene edad (`no_age`).
* **`sin_precio`**: no hay precio. El motivo es el del libro (`never_asked`, `not_quoted`, `withdrawn`, `unreadable`) o `no_price`.

Es la lista que proponía UX en P-06 (`vigente`, `antiguo`, `sin_precio`). Los umbrales viajan **como datos versionados**: la regla entera,
con su versión, sus franjas, el adelanto de los bordes y los estados posibles, sale en `rules.age` de cada informe
(`PriceAgeRule.as_json()`). La interfaz recibe los umbrales y el estado ya calculados; no los fija.

## 2. Qué se midió (repetición de 7 días, solo lectura)

Se repitieron todas las decisiones de `decision-v1` y `decision-fam-v1` de cada día con tres juegos de reglas, sobre los mismos candidatos
y en los mismos momentos:

* **A:** `decision-v2.1`, es decir, el libro con la edad por horizonte.
* **B:** `decision-v2.0`, es decir, el consenso con la regla de `decision-v1` (lo de hoy).
* **C:** `decision-v2.0:book`, es decir, el libro con la regla de `decision-v1`. C aísla el efecto de la regla de edad sola.

En total, **14.227 filas** en 544 momentos. Se reconstruyeron 13.797 decisiones, y **3.324** de ellas son del núcleo, que es lo que el libro
pone precio.

| Día | Filas | Núcleo con precio del libro | Antiguo con la regla nueva | Antiguo con la regla de v1 (mismo precio) | Cambios de estado, A frente a B | Cambios, A frente a C |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| 9-nov | 1.015 | 258 | 119 (46,1 %) | 124 (48,1 %) | 32 | 30 |
| 10-nov | 760 | 42 | 0 | 2 (4,8 %) | 5 | 1 |
| 11-nov | 812 | 257 | 0 | 36 (14,0 %) | 33 | 8 |
| 12-nov | 1.835 | 376 | 11 (2,9 %) | 75 (19,9 %) | 47 | 12 |
| 13-nov | 3.286 | 1.009 | 9 (0,9 %) | 30 (3,0 %) | 117 | 16 |
| 14-nov | 4.721 | 865 | 5 (0,6 %) | 109 (12,6 %) | 146 | 47 |
| 15-nov | 1.798 | 511 | 0 | 18 (3,5 %) | 86 | 2 |
| **Total** | **14.227** | **3.318** | **144 (4,3 %)** | **394 (11,9 %)** | **466 de 13.797** | **116 de 13.797** |

### 2.1 Edad del precio: el criterio de cierre

* **Precio sin edad: 0** en los 7 días (`price.without_age`). Es la condición 1 de G-PRECIO.
* **En la era de los refrescos, del 10 al 15-nov: 25 de 3.060 decisiones con precio del libro quedan fuera de su límite (0,82 %).** El
  criterio de la ficha pide como mucho el 1,0 %. Con la regla de `decision-v1` y el mismo precio serían 270 (8,8 %).
* **Reproduce la medición anterior.** Del 11 al 14-nov salen 25 de 2.507, frente a los 25 de 2.512 de la medición del 11 al 15-nov que
  sirvió para la decisión. Por franja, 22 lejos del saque, 3 entre 345 y 45 min y 0 en los últimos 45 min (antes: 22, 3 y 0).
* **El 9-nov no cuenta para el criterio.** Los refrescos del libro empezaron ese día a las 23:08 UTC, así que casi todo el día se decidió con
  el libro de las capturas, que es tan viejo como la captura. Ese día salen 119 de 258 antiguos. Por eso el total de los 7 días es del 4,3 %.
* **De dónde salen los 25 que quedan.** Los 11 del 12-nov son partidos de T-36h sin ningún refresco todavía. Los del 13 y el 14-nov caen en
  las paradas del worker, cuando el libro dejó de refrescarse (lo vio la medición anterior). Es justo lo que tiene que pasar: si el refresco
  se para, la regla rechaza más y lo dice, sin relajarse sola.
* **Sin precio: 6 selecciones** (el proveedor retiró los precios, `withdrawn`).

### 2.2 Cuántas decisiones cambian de estado

**A frente a B** (la regla nueva entera frente a la de hoy): **466 de 13.797 decisiones (3,4 %)**, todas del núcleo. 247 suben, 219 bajan y
**ninguna llega a RECOMMENDED**. Por la primera etapa que difiere:

* **Mercado, 374 (247 suben, 127 bajan).** Sobre todo WATCH → CAUTION (234): un precio más fresco ya no es `price_stale`.
* **Precio final, 52 (bajan).** Son CAUTION → ABSTAIN: el precio del punto final ya no es viejo, y entonces lo que frena la selección es lo
  de verdad, su ventaja sin validar (`edge_not_validated`).
* **Valor, 40 (bajan).** Con la cuota del libro el EV calibrado queda por debajo del mínimo.

Transiciones: WATCH → CAUTION 234, CAUTION → ABSTAIN 52, WATCH → REJECTED 52, WATCH → ABSTAIN 48, CAUTION → REJECTED 37, CAUTION → WATCH 24,
REJECTED → CAUTION 9, ABSTAIN → REJECTED 6, REJECTED → ABSTAIN 4. La medición anterior, del libro frente al consenso los dos con la regla
de v1 (11 al 14-nov), dio 263 de 10.654, también ninguno a RECOMMENDED.

**A frente a C** (solo la regla de edad, con el mismo precio del libro): **116 de 13.797 (0,84 %)**, 55 suben, 61 bajan y ninguna llega a
RECOMMENDED.

* **WATCH → CAUTION, 55, en la etapa de mercado.** Precios de entre 180 y 195 min lejos del saque, como el refresco de cada 3 h llegado con
  unos minutos de retraso (180,0 a 188,7 min en los ejemplos).
* **CAUTION → ABSTAIN, 26, en el precio final.** Precios de 34 a 45 min en T-90m o T-60m: los 30 min de v1 los rechazaban y los 75 min nuevos
  no.
* **CAUTION → WATCH, 24, en el mercado.** Puntos finales con un precio de más de 75 min, por ejemplo uno de 100 min a 78 min del saque. Antes
  quedaban en CAUTION por `price_not_fresh`; ahora son `price_stale`.
* **WATCH → ABSTAIN, 11, en el mercado.**

Las familias de mercados (córners, tarjetas, etc.) no cambian. No tienen precio del libro y conservan su propia regla.

### 2.3 Límites de esta medida

* Hay **6 días de refrescos** (del 10 al 15-nov), en semana de parón de selecciones, y el 10-nov tuvo solo 42 decisiones del núcleo. La ficha
  pide confirmarlo con 14 días de refrescos (a partir del 24-nov), con la orden `01` de `docs/owner/lab/IA_067/`.
* El código no estaba desplegado. La repetición cargó los tres módulos nuevos **en memoria**, dentro de una ejecución de python leída por
  stdin en el worker (orden `02`). No escribió nada en el contenedor ni en la base. Antes se comprobó que el resto del código desplegado es
  idéntico al de la rama: mismos sha256 de `fbi/decision/*`, `fbi/odds/quote_current.py` y `fbi/intel/decision.py`.
* Una primera pasada aplicó la regla nueva también a los precios propios de las familias. Se corrigió (la regla es la del libro) y se
  repitieron los 7 días. En los dos días que se compararon (14 y 15-nov), los cambios de estado son idénticos en las dos pasadas, porque las
  familias no cambiaban de estado. Las cifras de arriba son de la segunda pasada.

## 3. Cómo se usa

En sombra, desde el servidor (solo lectura):

```
python -m scripts.ia_decision_v2 replay --day 2026-11-14 --rules decision-v2.1                      # el libro con la edad por horizonte
python -m scripts.ia_decision_v2 replay --day 2026-11-14 --rules decision-v2.1 \
    --against decision-v2.0 --against decision-v2.0:book                                           # y qué cambia frente a hoy
```

`--rules` elige las reglas y trae su precio por defecto (`--price` sigue mandando si se da). `--against` decide los mismos candidatos con
otras reglas (`etiqueta` o `etiqueta:precio`) y el informe dice, en `versus`, cuántos estados cambian, de cuál a cuál, en qué etapa y
cuántos llegan a RECOMMENDED. La sección `price.states` cuenta los estados del precio por franja y por fuente.

## 4. Qué NO cambia

* `decision-v1`, sus umbrales y sus filas: nada.
* `decision-v2` sin opciones: es `decision-v2.0`, con el consenso y la regla de `decision-v1`, decisión a decisión igual que antes (la
  evidencia de P1; lo prueban las pruebas de equivalencia de siempre).
* El libro y su ingesta (`fbi/odds`, `fbi/market`): solo se leen, por el mismo lector de IA-037.
* Nada que publique, decida picks o sirva a los lectores importa `fbi.decision` (prueba de aislamiento). No hay migración, no hay
  interruptor y no se escribe nada. Persistir las decisiones de `decision-v2.1` es la pieza AD-D01.

## 5. Vuelta atrás

No hace falta apagar nada: `decision-v2.1` solo existe cuando se pide con `--rules decision-v2.1`. Para volver a lo de antes basta con no
pedirlo, o con pedir `--rules decision-v2.0` o `--price consensus`. Revertir el commit quita la versión nueva sin tocar datos: nada se
guardó con ella.
