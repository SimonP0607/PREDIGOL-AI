# IA-058 · Presupuesto por capacidad y sobres de la decisión 12

Fecha: 16 nov 2026. Pieza AD-A06 del plan de la arquitectura definitiva 2026. Cambia **el panel de costes y los avisos internos**; deja el control del gasto como estaba. Sin migración, sin cambios en la web y sin ningún efecto en el lector.

## 1. Qué hace

* **Tres sobres a la vista y por separado** (decisión 12): Claude en producción **US$ 185**, Exa **US$ 35** y LAB **US$ 55**. El panel (`fbi.ai.costs_v3`, vista privada de administración) enseña cada sobre con lo gastado en el mes, su porcentaje y su aviso. También muestra la cifra que tiene configurada el servidor y si coincide con la decisión 12.
* **La crónica de lectores entra en producción.** El sobre de producción suma dos libros: lo de Intelligence (`ai.usage`, más `analytics.ai_runs`) y la crónica de lectores (`ai.user_usage`). El panel enseña los dos por separado y el total, por día y en el mes. Hasta hoy el panel solo contaba `ai.usage`.
* **Avisos al 80 % y al 95 %** de cada sobre y del tope de cada capacidad nueva. El panel los muestra siempre (bloque `alerts`). Cada vez que se abre, la API los deja también en su registro (`fbi.ai.envelopes`, nivel WARNING), una vez por proceso y por mes; tras un reinicio, un aviso puede salir una segunda vez. **No avisan a ningún lector, no mandan correos ni cortan nada.** Los avisos que ya escribe el ciclo del trabajador (50, 70, 85, 95 y 100 % en `ai.budget_alerts` y `ai.envelope_alerts`, sobre `ai.usage`) siguen igual.
* **Por qué el ciclo no calcula estos avisos.** Una regla del plan UX (A11) prohíbe que el ciclo, el presupuesto o las decisiones de Intelligence lean el libro de los lectores. Por eso ese libro se lee en un módulo aparte, `fbi.ai.envelopes_readers`, que solo importa el panel. Una prueba (`tests/unit/test_user_layer_isolation.py`) comprueba que el ciclo nunca lo carga.
* **Presupuesto por pieza nueva** (`fbi.ai.capability_budget`, `capability-budget-v1`). Es un registro en el código: cada capacidad tiene su clave, la pieza del plan, el sobre que la paga, su tope mensual y de dónde sale la cifra. `get("chronicle_v4")` devuelve el tope de una capacidad, y el panel enseña cada capacidad frente a su tope. Cuando AD-003 tenga su registro, leerá estos topes de aquí.

| Clave | Pieza | Sobre | Tope (US$/mes) | Origen de la cifra | Se encuentra en el libro por |
| --- | --- | --- | ---: | --- | --- |
| `chronicle_v4` | AD-F02 | producción | 14,00 | ficha: 0,004 × 120 crónicas al día | prompt `chronicle-v4` |
| `news_summaries` | AD-G04 | producción | 13,50 | ficha: entre 4 y 13,5; se toma el alto | aún sin construir |
| `deep_extraction` | AD-C05 | producción | 4,40 | ficha: 210 páginas al día | aún sin construir |
| `specialist_readers` | AD-D09 | producción | 15,00 | costes del plan: unos 15 que pasan del LAB | aún sin construir |
| `page_bodies` | AD-C05 | Exa | 9,00 | entre 6 y 9; se toma el alto | aún sin construir |
| `battery_v4` | AD-A03 | LAB | 3,00 | ficha: menos de 3 por ejecución, una al mes | prompt `battery-v4` |
| `quarantine_tests` | AD-A01 | LAB | 3,00 | ficha: pruebas A1–A6 por debajo de 3 | aún sin construir |
| `label_bank_arms` | AD-C09 | LAB | 2,00 | ficha: menos de 2 | aún sin construir |
| `replay_regression` | AD-K04 | LAB | 2,93 | ficha: 2,93 por pasada, una al mes | prompt `replay-bank-` |
| `news_text_shadow` | AD-G04 | LAB | 2,00 | encargo IA-101: tope de las pruebas en sombra del texto propio de noticias | prompt `news-text-v1` |

Los topes de producción suman 46,90 de 185; los del LAB, 12,93 de 55 (con `news_text_shadow`, IA-101); los de Exa, 9 de 35. Una prueba comprueba que siempre caben en su sobre. Una llamada solo cuenta para una capacidad de su propio sobre: una `battery-v4` pagada con la clave de producción no carga la batería del LAB.

## 2. Qué no cambia

* **El techo conjunto de US$ 190 sigue vigente.** El LAB sigue cediendo lo que pase de 190 menos la proyección de producción, como antes. El panel lo dice con todas las letras: «techo conjunto 190 vigente; pendiente de confirmación del dueño», con lo que recibe hoy el LAB y lo que recibiría con sobres independientes.
* **El control del gasto se queda como estaba.** El estado del presupuesto (NORMAL, AJUSTE…), la proyección, el reparto por día y los cortes siguen contando solo `ai.usage`, como hasta ahora. La crónica de lectores tiene su propio tope (`FBI_AI_USER_MONTHLY_BUDGET_USD`) y lo conserva. El panel lo indica con `control_counts: intelligence`.
* **El precio de Exa no cambia.** El código cobra US$ 0,015 por búsqueda (`fbi.ai.pricing`: 7 por la búsqueda más 1 por cada 1.000 páginas, contando el texto de 8 resultados). La página de Exa (exa.ai/docs/changelog, consultada el 16-nov-2026) dice US$ 7 por 1.000 búsquedas, con el texto de 10 resultados incluido, es decir, 0,007. El panel enseña las dos cifras, el mes a cada precio y la diferencia, marcada **«sin verificar hasta la factura»**. Solo una factura de Exa decide cuál vale; el código no lee facturas.
* Agentes, prompts, motores, modelos, umbrales, picks, `decision-v1` y la web quedan igual. No hay tablas nuevas ni se escribe nada nuevo en la base de datos.

## 3. Lo medido en producción (solo lectura, 16-nov-2026 20:53 UTC, mes de Bogotá del 1 al 16-nov)

| Sobre | Gastado (US$) | Sobre (US$) | % | Aviso |
| --- | ---: | ---: | ---: | --- |
| Producción: Intelligence 55,64 + lectores 3,91 | 59,55 | 185 | 32,2 % | ninguno |
| Exa (940 búsquedas a 0,015) | 14,10 | 35 | 40,3 % | ninguno |
| LAB | 12,98 | 55 | 23,6 % | ninguno |

* El servidor tiene configurados 185 / 55 / 35, un techo de 190 y una reserva de 10, que coinciden con la decisión 12. La proyección de producción del panel actual es de US$ 141,15 (76,3 %). Con ella, el techo conjunto deja al LAB **US$ 50,84 en vez de 55**: el techo ya recorta unos 4 dólares este mes.
* Exa a 0,007 habría costado 6,58 en el mes, 7,52 menos que lo anotado. Esto sigue sin verificar.
* De las capacidades nuevas, solo `replay_regression` tiene gasto: 2,93 de 2,93 (la pasada del banco del 15-nov). En cuanto se despliegue saldrán sus avisos del 80 % y del 95 %. Es lo esperado: la pasada del mes ya está hecha.

## 4. Cómo se pasa a sobres independientes (cuando el dueño lo confirme)

1. En `/etc/predigol/app.env`, `FBI_AI_ENVELOPES_INDEPENDENT=on`, y reiniciar el trabajador. Con eso, el LAB recibe su sobre entero sin depender de lo que proyecte producción.
2. Cambiar `JOINT_CEILING_PENDING` a `False` en `fbi.ai.budget_v3` (un PR) para que el panel deje de decir «pendiente».
3. Pendiente en ese mismo paso: `fbi.observability.cost_alerts` y la puerta A (`fbi.ai.gate_a`) siguen comparando con 190. Habría que cambiarlos a la vez.

## 5. Cómo se apaga o se revierte

* Para volver al techo conjunto después de haberlo cambiado: borrar `FBI_AI_ENVELOPES_INDEPENDENT` (o ponerlo a `off`) y reiniciar el trabajador.
* El presupuesto v3 completo sigue apagándose con `FBI_AI_BUDGET_V3=0`. Con él apagado, el trabajador vuelve al cálculo anterior y no escribe estos avisos.
* El panel nuevo y sus avisos se retiran revirtiendo el PR. Como no hay tablas ni datos nuevos, no queda nada que limpiar.

## 6. Lo que queda pendiente

* **Factura de Exa** (dueño): con ella, confirmar 0,015 o 0,007 y, si toca, cambiar `SEARCH_PRICES['exa']` y `EXA_PRICE_VERIFIED_BY_INVOICE` en un PR.
* **Confirmar si los sobres sustituyen al techo de 190** (dueño).
* **Avisos del 80 % fuera del panel** (opcional). Hoy solo aparecen al abrir el panel, porque las tablas de avisos solo admiten 50, 70, 85, 95 y 100 y el ciclo no puede leer el libro de los lectores. Avisar sin abrir el panel pediría dos cosas:
  - una migración que amplíe esa lista en `ai.envelope_alerts` y añada el tipo `capability` (no está hecha);
  - una tarea fuera del ciclo de Intelligence que la escriba, o una excepción explícita a la regla A11.
* Las piezas sin construir declaran su prefijo de prompt en este registro cuando se construyan. Hasta entonces, su gasto aparece como 0.
