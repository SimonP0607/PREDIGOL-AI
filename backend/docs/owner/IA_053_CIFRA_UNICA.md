# IA-053 · Cifra única de referencia, en sombra (INT-A03)

Pieza INT-A03 del Plan Maestro de Intelligence 2026, solo la parte de la sombra. Hace que la repetición de `decision-v2` pueda juzgar cada selección con **la misma cifra que enseña el Match Center** (la vista común de probabilidad, `forecast-v1`), con su versión y su sello «Sin calibrar» cuando no hay precio fresco, y lo compara con la decisión de siempre. **Por defecto no cambia nada**: la evidencia de P1 sigue siendo la de hoy hasta que alguien decida otra cosa. No toca `decision-v1` (`fbi/intel/decision.py`), ni `fbi/forecasting/market_view.py` (no cambia ningún número), ni los paquetes de modelos, ni `web/`, ni la API, ni nada que decida, publique o sirva a los lectores.

Se construye encima de IA-037 (INT-A06, precio del libro con su edad), todavía sin fusionar.

## 1. El problema, en una frase

Hoy una misma selección puede llevar tres números distintos: el del Match Center (`models.match_forecasts`, la vista común), el de la decisión (`decision-v1`, su probabilidad calibrada `p_cal`) y el del pick (`picks.picks.p_calibrated`, que en realidad guarda la del modelo sin calibrar). La Parte I midió una mediana de 1,82 puntos entre el Match Center y la decisión. La ficha pide **un número por selección**, el mismo para la decisión, el Match Center y Picks; A02 (IA-036) rechazó la calibración coherente, así que ese número es **la vista común reescalada** que ya existe.

## 2. Qué cambia (código, todo en `fbi/decision` y su comando)

* **`--probability common`** en `python -m scripts.ia_decision_v2 replay` (por defecto `own`, la de hoy). Con la opción, las etapas del núcleo juzgan **la cifra de la vista común** en lugar de la del pick:
  * **modelo** (etapa 2): el modelo, la probabilidad y el intervalo de la vista (la vista elige un modelo por mercado y sus resultados suman 1);
  * **datos** (etapa 1): la antigüedad del pronóstico es la de la vista;
  * **calibración** (etapa 4): el sello de la vista. Si está calibrada (un calibrador campeón con precio fresco), pasa; si dice «Sin calibrar» (`no_champion`, `needs_price`: sin precio de menos de 6 h, o `not_applicable`), no aprueba y lo dice con su motivo;
  * **valor** (etapa 5): el valor esperado con la cifra de la vista **solo si está calibrada**. Sin calibrar no hay cifra calibrada con la que juzgar el valor: queda `ev_unknown` (no se disfraza la cifra del modelo de calibrada);
  * **riesgo, correlación, etiquetas y la puerta de la ventaja** (etapas 7, 8 y 10) usan esa misma cifra, su intervalo y la ventaja validada **del modelo de la vista**.
* **Lo que la vista no cubre conserva su probabilidad** y dice por qué: `not_in_view` (hándicap asiático, doble oportunidad, otras líneas de goles, las familias) o `no_reading` (la vista cubre el mercado, pero en ese momento ningún modelo había puesto precio a todos sus resultados).
* **Cada decisión dice qué cifra juzgó**: `prediction.source` (`own` o `common`), `calibration` (`CALIBRATED` / `UNCALIBRATED`), `basis`, `version` (`forecast-v1`) y, si se quedó con la suya, `missing`.
* **El informe** añade una sección `probability`: cuántas decisiones juzgó la vista y con qué sello, cuántas conservaron la suya y por qué, y —contra las **mismas candidatas juzgadas con su propia probabilidad**— cuántos estados cambian, de cuál a cuál, en qué etapa, la distancia entre las dos probabilidades calibradas y hasta 20 ejemplos.

Ficheros: `src/fbi/decision/engine.py` (`PROBABILITY_SOURCES`, `Prediction`, etapas 1, 2 y 4), `src/fbi/decision/view.py` (`judged`, `fields`, `covered`), `src/fbi/decision/replay.py` (`replay_day(probability=)`, `probability_summary`), `scripts/ia_decision_v2.py` (`--probability`, `render_probability`).

```
docker exec -w /app predigol-worker python -m scripts.ia_decision_v2 replay --day 2026-11-10                         # como siempre
docker exec -w /app predigol-worker python -m scripts.ia_decision_v2 replay --day 2026-11-10 --probability common    # con la cifra única
```

## 3. Paridad en el CI: un solo número

Dos pruebas nuevas, que corren en el CI:

* **Sin base de datos** (`tests/unit/test_decision_v2_common_probability.py`): para la misma entrada, lo que el escritor del Match Center insertaría (`match_forecast.store`), lo que `decision-v2` lee (`view.readings`) y lo que sus etapas juzgan son el mismo número, con el mismo modelo, versión de modelo, sello, motivo y calibrador; el mercado suma 1 (y lo guardado, a sus seis decimales); con precio fresco y sin él.
* **Con PostgreSQL** (`tests/integration/test_common_probability_parity.py`): el escritor real (`write_match_forecasts`), **la página del partido** que sirve el Match Center (`fbi.api.services.forecast.match_forecast`), la vista que lee `decision-v2` (`fbi.decision.view.read`) y la cifra que juzgan sus etapas coinciden **a los seis decimales** en los 7 resultados de 1X2, goles a 2,5 y ambos marcan; cada mercado suma 1; con un precio de hace 7 h los cuatro dicen «Sin calibrar» (`needs_price`) con el mismo motivo y la decisión no tiene cifra calibrada; y la repetición con `--probability common` no escribe nada, es determinista y deja la repetición por defecto como estaba (acuerdo 100 %).

## 4. Medición en producción (solo lectura)

12-nov-2026, 13:50 UTC. El código de esta rama se ejecutó dentro del worker, por la entrada estándar, sin copiar nada al contenedor ni escribir nada (`default_transaction_read_only`). La imagen desplegada era `3da952b7a4c6`. Se repitió el día 10-nov (hora de Bogotá).

**Un día de repetición, con y sin la opción.**

| | Sin opción (`own`, la de hoy) | `--probability common` |
| --- | ---: | ---: |
| Acuerdo con `decision-v1` | 712 de 760 (93,7 %) | 698 de 760 (91,8 %) |
| Núcleo, 1X2 | 17 de 18 | 7 de 18 |
| Núcleo, ambos marcan | 5 de 8 | 3 de 8 |
| Núcleo, más/menos | 11 de 12 | 9 de 12 |
| Núcleo, hándicap y doble oportunidad | 9 de 9 | 9 de 9 |
| Desacuerdos por etapa | mercado 2 | calibración 12, mercado 2, datos 1, valor 1 |

- **Sin la opción**, la repetición da lo mismo que antes. Es la evidencia de P1, y no cambia.
- **Qué cifra lee la opción.** La vista común juzgó las 34 selecciones del núcleo:
  - 14 con el sello «Calibrado» y 20 «Sin calibrar», sin precio fresco;
  - frente a la probabilidad que hoy juzga la decisión, la diferencia es de 5,2 pp de mediana (p90 20,7 pp, máximo 24,0 pp), y solo 7 de las 34 quedan dentro de 0,5 pp.
- **Las causas de esa diferencia:**
  - «Sin calibrar» de la vista: 18 selecciones, mediana 11,1 pp;
  - otra calibración: 13, mediana 0,2 pp, 6 por encima de 0,5 pp;
  - otro modelo: 3, mediana 6,1 pp.
- **Los estados que cambian** (de `decision-v1` a `decision-v2` con la opción):
  - 9 de RECHAZADO a ABSTENCIÓN y 4 de VIGILANCIA a ABSTENCIÓN: sin cifra calibrada no hay valor que juzgar;
  - 1 de RECHAZADO a CAUTELA.
  - Ninguna selección llega a RECOMENDADO.
- **Lectura:** juzgar con la cifra que ve el usuario hace hoy la decisión más prudente, porque muchas cifras del núcleo están «Sin calibrar».
  - El caso de RECHAZADO a CAUTELA es menos severo y hay que mirarlo antes de pensar en usar la opción.
  - Activarla es la pieza `INT-A05`, con G-COH, P1 y tu decisión.

**La paridad en producción** entre lo que guardó el Match Center (`forecast-v1`) y la vista que lee `decision-v2` en los mismos momentos:

| Ventana | Momentos leídos | Filas comparadas | Iguales | Mercados que suman 1 |
| --- | ---: | ---: | ---: | ---: |
| 24 h | 59 de 59 | 2.528 | 2.528 | 1.065 de 1.065 |
| 72 h | 65 de 129 (tope de 120 momentos por lectura, a partes) | 2.955 | 2.955 | 1.254 de 1.254 |

- **Entre el Match Center y la decisión:** ninguna diferencia, y cada mercado suma 1. La condición de G-COH se cumple para estos dos lectores.
- **Picks:** sigue leyendo la probabilidad del pick (`p_calibrated`), que difiere de la vista una mediana de 5,2 pp. Por eso la paridad con Picks queda para el apartado 5.

## 5. Lo que falta para Picks y el Match Center (diseño para la sesión de UX)

Nada de esto se ha tocado: **ni `web/` ni la API**. Es la lista de lo que haría falta para que la app enseñe la cifra única, para que la sesión de UX lo encaje con su mapa (`IA_049_MAPA_UX_INTELLIGENCE.md`, campos «Pronóstico: cifra única», «rango» y «calibración», y la regla 5 «Una sola cifra»).

**Lo que ya está.** La cifra única **es** la vista común, y ya se guarda versionada y de solo anexar: `models.match_forecasts` con `version = forecast-v1`, escrita por un solo módulo (`fbi/forecasting/match_forecast.py`), con su sello (`calibration`), su motivo (`basis`), su intervalo y su hora (`known_at`). **No hace falta una tabla nueva.** El Match Center ya la enseña (P03 «Pronóstico PrediGol», con el sello «Calibrado» o «Sin calibrar»): para el Match Center no falta ninguna cifra.

**Lo que falta, por orden:**

1. **Picks lee la misma cifra (K02 «Por qué tiene valor», K03 «Cómo lo decidimos», P06 «PrediGol estima»).** Hoy Picks enseña la probabilidad de la decisión (`intel.decisions.p_cal`, con `FBI_PICKS_SOURCE` apagado la del pick). Debe enseñar la de `forecast-v1` de esa selección. Regla propuesta: en una tarjeta de pick, la cifra **del momento de la decisión** (la fila de `match_forecasts` más nueva con `known_at` anterior o igual a la decisión), con su hora; en el Match Center, la más nueva. Si las dos están en la misma pantalla, se enseña una sola, con su hora (regla del mapa: «no deben mostrarse las dos cifras»).
2. **El registro de la decisión lleva la cifra que juzgó (`INT-C06`, contrato `INT-E01`).** Campos propuestos por selección: `probability` (la cifra), `low`/`high`, `calibration` (`CALIBRATED`/`UNCALIBRATED`), `basis`, `version` (`forecast-v1`), `known_at`, y `probability_source` (`own` o `common`). Así la «Lista de condiciones» (fila Estadística) y la tarjeta de pick leen el mismo número que la decisión, sin recalcularlo en la API.
3. **El sello, una sola vez.** Con `UNCALIBRATED`, el gris «Sin calibrar» que ya existe (`forecast.uncalibrated`), y su motivo en palabras: «sin precio reciente» (`needs_price`), «sin calibrador validado» (`no_champion`). Con `CALIBRATED`, el sello «Calibrado» de P03.
4. **Mercados sin cifra única.** La vista cubre hoy 1X2, goles a 2,5 y ambos marcan. Un pick de hándicap asiático, doble oportunidad u otra línea de goles **no tiene** cifra de la vista: lleva la de la decisión, con su sello, y el Match Center no la enseña (no hay conflicto, porque allí no aparece). Ampliar la vista a esos mercados es de `INT-A01`/`INT-A02`, no de UX.
5. **El orden de los interruptores (`INT-A05`).** Primero, que Picks enseñe la cifra única (cambia lo que se ve, no lo que se decide). Después, y solo tras G-COH, P1 y tu aprobación, que el motor la use para el valor esperado: eso cambia qué selecciones pasan las puertas, y esta sombra es la que dice cuántas y por qué antes de decidirlo.

## 6. Qué no cambia

* La evidencia de P1: sin `--probability common` la repetición da lo mismo que antes (las 2.000 selecciones de la prueba de equivalencia con `decision-v1` siguen coincidiendo; en la base de datos de pruebas, acuerdo 100 %). Solo se añaden campos de medida a `prediction` y `inputs.probability = "own"`.
* `decision-v1`, sus umbrales, sus filas, los picks, la muestra de la sombra, los agentes, los motores, los interruptores, `market_view.py` (ningún número cambia: la vista es la misma función), el escritor del Match Center y la API.
* Ningún interruptor nuevo, ninguna migración, ninguna escritura: la opción solo existe en el comando de repetición, y nada que decida, publique o sirva a los lectores importa `fbi.decision` (prueba de aislamiento).

## 7. Vuelta atrás

Revertir el PR. No hay migración, ni interruptor, ni datos escritos.
