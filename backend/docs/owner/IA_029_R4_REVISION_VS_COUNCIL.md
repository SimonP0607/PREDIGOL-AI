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

Corrida en producción, en solo lectura, el **10 nov 2026 a las 05:40 UTC**, ventana del 26-oct 00:00 UTC hasta ese momento (`r4-compare-v1`). Las selecciones son las últimas revisiones de cada motor antes del saque con estado `ok` o `fallback`; la ganancia es a una unidad fija, al precio de quien guardó la selección, y el CLV es `cuota × p_cierre − 1` (consenso Shin antes del saque).

**Cada motor**

| Motor | Selecciones (partidos) | Rechaza | Guardadas: ROI · CLV medio | Rechazadas: ROI · CLV medio |
| --- | --- | --- | --- | --- |
| `llm` (`review-v2`) | 960 (556) | 387 · 40,3 % (IC95 37,3-43,4 %) | +4,0 % en 566 · −2,86 % | +1,9 % en 382 · −4,37 % |
| `rules` | 2.774 (1.270) | 313 · 11,3 % (10,2-12,5 %) | −0,4 % en 2.404 · −3,16 % | −15,1 % en 310 · −1,93 % |
| `ma-v1` (Council con Sonnet) | 428 (139) | 40 · 9,3 % (6,9-12,5 %) | −9,1 % en 239 · −3,20 % | −26,8 % en 23 · −6,38 % |
| `ma-v1-h` (Council con Haiku) | 427 (138) | 10 · 2,3 % (1,3-4,3 %) | −8,8 % en 255 · −3,42 % | 6 liquidadas |
| `cs-v1` (Council solo) | 0 | — | — | — |

`cs-v1` no corre: la activación del plan solo nombra `ma-v1` y `ma-v1-h` en `FBI_AI_ENGINES` (`fbi.ai.arms`), así que no hay comparación con él. `ma-v1-h` se abstiene en 367 de sus 427 selecciones (86 %).

**`review-v2` frente al Council (`ma-v1`)**: 102 selecciones en común (la sombra cubre una parte de los partidos: 858 solo las revisó `llm`). Acuerdo exacto 70/102 (68,6 %, IC95 59,1-76,8 %); acuerdo en rechazar o no 74/102 (72,5 %, IC95 63,2-80,3 %). La matriz: `DOWNGRADE|DOWNGRADE` 61, `REJECT|DOWNGRADE` 23, `REJECT|REJECT` 9, `DOWNGRADE|APPROVE` 3, `DOWNGRADE|REJECT` 3, `REJECT|ABSTAIN` 2, `APPROVE|DOWNGRADE` 1.

* Donde `review-v2` rechaza y el Council guarda: 25 selecciones, todas liquidadas; ganadas 8/25 (32,0 %, IC95 17,2-51,6 %), ROI +5,6 % si se hubiera seguido al Council, CLV medio −2,75 %.
* Donde el Council rechaza y `review-v2` guarda: 3 selecciones (0 de 2 decididas ganadas).

Con 25 casos el ROI no distingue nada (su intervalo cabe en cualquier lado del cero); el CLV negativo de esas 25 es coherente con que `review-v2` las rechazó por precio. **No hay evidencia** de que uno de los dos sea mejor: ni para retirar `review-v2`, ni para darle peso al Council.

**El gasto de la ventana**: US$ 84,71 en 9.910 llamadas. `review-v2` US$ 41,31 (48,8 %: Sonnet 906 llamadas US$ 22,51; Opus 205 llamadas US$ 18,80, unas 15 al día, la etapa final del revisor de producción); `brief-v8` 3.963 llamadas US$ 12,20 (14,4 %); Exa US$ 12,12 (14,3 %); el experimento de equivalencia `equiv-v1` US$ 9,56 (11,3 %, del LAB, ya terminado); el Council de la sombra ≈ US$ 4,1 (Sonnet US$ 3,22, Opus por regla 12 llamadas US$ 0,79, Haiku US$ 0,12). En las últimas 48 h no corre ninguna versión vieja de un agente (`match-context-v3` y `stats-assess-v2` se pararon el 8-nov).

**Lo que es del dueño**: la etapa final de `review-v2` con Opus (≈ US$ 1,5 al día) y el brazo `ma-v1-h` (barato, pero se abstiene casi siempre) son decisiones de enrutamiento y de diseño de la sombra; este informe no cambia ninguna. `review-v2` y `brief-v8` siguen hasta las condiciones de P2.
