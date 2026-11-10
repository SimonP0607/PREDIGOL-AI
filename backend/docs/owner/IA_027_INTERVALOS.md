# IA-027 · Cada tasa de los informes lleva sus casos y su intervalo

Fecha: 10 nov 2026. Estado: **en el código**. Sin migración ni interruptor. Es la R3 de la auditoría del 10-nov (`AUDITORIA_IA_Y_MATERIAL_UNIVERSITARIO_20261110`), aprobada por el dueño el mismo día. Lo vigila `tests/unit/test_intervals.py`.

## 1. Por qué

Un gate lee una tasa y la compara con su umbral. La tasa sola no dice en cuántos casos descansa: 0 inválidas de 35 y 0 de 3.500 se imprimen igual («0 %»), y 4 inválidas de 44 (9,1 %) son compatibles con cualquier tasa real entre el 3,6 % y el 21,2 %. Con las cifras medidas en producción (solo lectura) en la vista previa del Gate B del 10-nov:

| Tasa | Casos | % | IC95 (Wilson) | Umbral | El intervalo queda |
| --- | --- | --- | --- | --- | --- |
| Inválidas `match-v4` | 9 / 116 | 7,8 % | 4,1 – 14,1 % | ≤ 3 % | por encima |
| Inválidas `council-v1` | 9 / 443 | 2,0 % | 1,1 – 3,8 % | ≤ 3 % | a ambos lados |
| Atribución | 87 / 127 | 68,5 % | 60,0 – 75,9 % | ≥ 95 % | por debajo |

El Council pasa hoy el 3 % por su tasa, pero sus casos todavía no lo aseguran; el Match no lo pasa ni en el mejor extremo de su intervalo.

## 2. Qué cambia

* **`fbi.ai.intervals`** (aritmética pura, sin numpy ni scipy): el intervalo de **Wilson** (el que se muestra primero: honesto en 0 y en n, nunca fuera de [0, 1]) y el **exacto de Clopper-Pearson** (de la binomial misma, más ancho, nunca cubre menos del 95 %). `Proportion(k, n, umbral, kind)` da los casos, cuántos de cada tipo, la tasa, los dos intervalos y dónde queda el de Wilson frente al umbral: `below`, `above`, `straddles`, `no_threshold` o `no_cases`.
* **Gate B** (`gate-b-v1`): cada agente y versión de `invalid_outputs` y la `attribution` llevan `interval` en su detalle, y el informe escrito pone una línea por tasa bajo su check: «stats stats-v3: 4/44 · 9.1 % · IC95 3.6-21.2 % · umbral ≤ 3.0 % · resultado del check: NO PASA».
* **Gate de Research v2**: la cobertura de hechos y la de jugadores llevan su intervalo, en el JSON y en el informe.
* **Banco de evaluación** (`eval-bench-v1`): las válidas al primer intento de cada celda, las señales, el veredicto y la cobertura llevan su intervalo; el informe escrito pone la línea de las válidas al primer intento.

## 3. Lo que NO hace

* **No decide nada.** Ningún gate lee el intervalo para pasar o fallar: el veredicto es el de antes, la tasa contra su umbral (la prueba lo comprueba con una tasa que falla y un intervalo que lo confirma, y con el JSON marcado `"decides": false`). Usar el extremo del intervalo para decidir sería una versión nueva de un gate y la firma el dueño; no se toca aquí («primero mejora la evidencia utilizada para decidir»).
* No cambia ningún umbral, ningún método ni ninguna versión de agente, prompt o contrato: **no mueve el ancla del Gate B**.
* No graba nada nuevo: los informes que ya se graban llevan unas claves más en su detalle.
