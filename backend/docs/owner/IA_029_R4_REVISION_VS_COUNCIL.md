# IA-029 · La revisión de producción frente al Council de la sombra, medida igual cada vez

Fecha: 10 nov 2026. Estado: **en el código**. Sin migración ni interruptor; lee y no escribe. Es la R4 de la auditoría del 10-nov (`AUDITORIA_IA_Y_MATERIAL_UNIVERSITARIO_20261110`), la prioridad del dueño. Lo vigilan `tests/unit/test_r4_compare.py` y `tests/integration/test_r4_readers.py`.

## 1. Qué compara

La misma pregunta se paga dos veces: `llm` revisa las selecciones de producción con `review-v2` (y `brief-v8` escribe su lectura), y la sombra las juzga con el Council: `ma-v1` (Match Agent y Sonnet), `ma-v1-h` (Match Agent y Haiku) y `cs-v1` (solo el Council). `fbi.ai.r4_compare` (`r4-compare-v1`) toma, de cada motor, la revisión más reciente de cada selección hecha **antes del saque** y que juzgó algo (`ok` o `fallback`), y dice:

* **Por motor**: cuántas selecciones, sus decisiones, cuántas rechaza (con su intervalo), los modelos, el coste de esas revisiones y qué hicieron después del partido las que guardó y las que rechazó (liquidadas, ganadas de las decididas con su intervalo, ROI a stake plano de 1, CLV medio y cuántas con CLV positivo, con su intervalo).
* **Por pareja** (`llm` frente a `ma-v1`, `ma-v1-h` y `cs-v1`; `ma-v1` frente a `ma-v1-h`; `rules` frente a `llm`): la matriz de decisiones, el acuerdo exacto y el acuerdo en rechazar o no (con su intervalo), y las selecciones en que uno rechaza y el otro no, leídas al precio del que la **guardó** (lo que habría hecho seguirle).
* **El gasto de la ventana** en `ai.usage` por propósito, prompt y modelo, con su parte del total.

El CLV es `cuota × p_cierre − 1`, con la probabilidad justa de cierre del consenso Shin antes del saque. Los lectores (`fbi.ai.r4_readers`) leen producción y sombra en dos consultas que nombran sus motores (la regla de `test_engine_filter_guard.py`).

## 2. Cómo se corre

```
python -m scripts.ia_r4_compare                       # del 26-oct (primer día del Council en la sombra) hasta ahora
python -m scripts.ia_r4_compare --since 2026-11-03 --until 2026-11-10
python -m scripts.ia_r4_compare --json                # solo el JSON
```

La conexión se abre de solo lectura (`default_transaction_read_only=on`); imprime el JSON y unas líneas en español.

## 3. Lo que NO hace

* **No decide**: cada tasa lleva sus casos y su intervalo (`"decides": false`), sin umbral. Una muestra pequeña dice lo que dice con su intervalo, nunca más.
* **No retira** `review-v2` ni `brief-v8` antes de que se cumplan las condiciones de sustitución de P2, ni cambia el enrutado: a qué modelo escala el Council (Opus por las reglas E1–E7) lo decide el dueño.
* No toca agentes, prompts, gates ni umbrales; no promueve nada.

## 4. Resultados

Pendientes: las cifras salen de correr el script en producción, en solo lectura, y se anotan aquí con su fecha y su ventana.
