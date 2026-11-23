# IA-157 · PM-12-03 · La cartera de modelos del LAB, con un protocolo preregistrado por línea

Plan Maestro PM, ola 6, tarea **PM-12-03** (OP-26, OP-27, OP-28, OP-29, OP-30). Ejecutado **fuera del servidor**, sobre la exportación
de solo lectura del LAB, con cuatro protocolos preregistrados (uno por línea), fusionados en `main` (#461, 05:00:55 UTC) **antes** de
tomar la exportación. **Nada sale del LAB**: un PASA deja como mucho un candidato para la puerta del modelo (`fbi.research.gate`) y
nunca llega a producción sin la firma del dueño. Ningún LLM toca probabilidades; el modelo en vigor no cambia.

| Línea | Protocolo | Huella |
| --- | --- | --- |
| OP-26 ventaja de local variable | `PM-12-03-OP26` (`proto-pm-12-03-op26-v1`) | `99998f67d326…8dca` |
| OP-27 rating de mercado | `PM-12-03-OP27` (`proto-pm-12-03-op27-v1`) | `c8525423220e…eda5` |
| OP-28 tiros y xG (E4), alineaciones (E6) | **no se toca**: sigue en el Plan Intelligence (INT-A09, INT-A08) | — |
| OP-29 abstención conforme (protocolo nuevo; no repite INT-A02) | `PM-12-03-OP29` (`proto-pm-12-03-op29-v1`) | `1b1ae6591a07…7a4c` |
| OP-30 retadores y contraste externo | `PM-12-03-OP30` (`proto-pm-12-03-op30-v1`) | `9192d1f5cab4…ccd1` |

## 1. Orden de los hechos (UTC, 21-nov-2026)

Protocolos empujados 03:24:45 (`fd0e5aa`) · código `scripts/lab_portfolio.py` 03:37:07 (`b7d68df`, probado con datos sintéticos) ·
fusión #461 05:00:55 (`194bf2f`) · exportación `lab-export-v2` 05:01:32–05:03:04 (carpeta `20261121T050132Z`, foto
`4765478:4765516:4765478`; tar SHA-256 `67204cc5…fc17`, `verify` correcto) · cálculo en el contenedor 05:04–05:20.

**Un cambio de implementación antes de ejecutar** (tras ver el formato, no los resultados): las cuotas de football-data traen dos
columnas que no son casas, `AVG` (media) y `MAX` (mejor precio, con margen negativo); el protocolo promedia «cada casa», así que se
excluyen. Está en este PR (`scripts/lab_portfolio.py`, `market_probs`).

## 2. La referencia B0 y la prueba

B0 es la aritmética del modelo en vigor: `fbi.competitions.scenario_store._fit` (Dixon-Coles con la especificación promovida
`spec-v1`, xi 0,002, penalización 1,0, 730 días de la misma competición, resultados conocidos 3 h después del saque; Poisson cuando la
corrección no es válida), ajustado cada lunes 00:00 UTC. Prueba: **92.760 partidos** de **71 ligas nacionales** del 1-jul-2022 al
20-nov-2026, 230 semanas ISO. Toda comparación es la diferencia pareada del log loss 1X2 por partido, con bootstrap de semanas
enteras (2.000 réplicas). Log loss medio: B0 1,0181; mercado de cierre (segmento M, 5.307 partidos de las cinco grandes) 0,9643.

## 3. Veredictos

### OP-26 · Ventaja de local re-estimada con los últimos 365 días: **NO PASA**

C26 − B0 = **+0,00021** (IC 0,00011 a 0,00032; n = 92.759; diferencia mínima detectable 0,00014): la ventaja de local
re-estimada empeora un poco, en lugar de mejorar. Por temporada no mejora en ninguna. La ventaja de local de B0 (fija en su ventana de
730 días con decaimiento) ya recoge lo que hay; la ventaja de local estimada por competición y año queda en el resultado completo.

### OP-27 · Fuerza de equipo derivada de cuotas («rating de mercado»): **NO PASA**

En 3.476 partidos del segmento M (ago-2023 a may-2025): C27 − B0 = +0,0046 (IC −0,0010 a +0,0102): **no mejora a B0**. El control de
circularidad funciona como se esperaba: el placebo (cuotas permutadas dentro de la semana) es mucho peor que B0 (+0,085) y C27 le gana
claramente (−0,080), así que la información que llevan las cuotas es real, pero ajustada a los partidos anteriores no pronostica mejor
que los resultados. Frente al mercado del propio partido, C27 pierde +0,030 (esperado; no es criterio).

### OP-29 · Abstención conforme (90 %) sobre B0: **PASA**

87.119 partidos tras las 13 semanas de calibración: cobertura **0,901** (Wilson 0,899–0,903); en cada segmento con ≥ 500 partidos
entre 0,897 y 0,903 (prioritarias 0,899; resto 0,901; temporadas 2022–2026); tamaño medio del conjunto **2,44** (≤ 2,5). Conjuntos de
un resultado: 16,2 % (aciertan el 67,8 %); de dos: 23,3 %; de tres: 60,5 %. Secundario: la cobertura por resultado real no es
uniforme (local 0,965; empate 0,851; visitante 0,852): la garantía es marginal, no por clase.

Lectura: el conjunto conforme cumple lo que promete y deja una regla de abstención honesta («no hay un resultado claro») en el 60 % de
los partidos. No recalibra ni cambia ninguna cifra; pasa a ser candidato para que la sesión de Intelligence decida si lo usa (p. ej.
para no destacar un «favorito» cuando el conjunto tiene tres resultados).

### OP-30 · Retadores (Bonferroni, nivel 98,3 %): **PASA**, con C30b y C30c

| Retador | Retador − B0 (IC 98,3 %) | Brier |
| --- | --- | --- |
| C30a Poisson sin corrección DC | +0,00005 (−0,00025 a +0,00035) | 0,6099 |
| **C30b Elo dinámico + logit ordenado** | **−0,00174** (−0,00315 a −0,00028) | 0,6089 |
| **C30c pool 50/50 de B0 y C30b** | **−0,00447** (−0,00522 a −0,00372) | 0,6071 |
| B0 (referencia) | — | 0,6099 |

El pool mejora en todos los segmentos (prioritarias −0,0038; resto −0,0045; cada temporada de 2022 a 2026). **Contraste externo**
(segmento M, 5.307 partidos): el mercado de cierre gana a B0 por **0,0237** de log loss (IC 0,0190–0,0283) y al mejor retador (C30c) por
0,0199: la brecha con el mercado es unas cinco veces lo que gana el mejor retador. penaltyblog no se instaló (su Dixon-Coles con
decaimiento es la familia de B0) y no hay banco CC0 autorizado: no se usaron.

## 4. Lo que esto deja (sin cambiar nada)

* Dos candidatos para la puerta del modelo, **solo si la sesión de Intelligence y el dueño lo deciden**: el pool B0 + Elo (C30c) como
  retador del 1X2 y el conjunto conforme (OP-29) como regla de abstención. Ninguno se activa; cualquier paso es otra pieza con su
  propio protocolo de producción y firma.
* Cerradas con motivo: la ventaja de local re-estimada (OP-26) y el rating de mercado (OP-27). Repetirlas con otra semivida, ventana o
  forma sería un protocolo v2 registrado antes de mirar.
* OP-28 sigue en el Plan Intelligence (E4 hacia marzo de 2027, E6 con 1.500 partidos por segmento): no se tocó.

## 5. Criterios de aceptación y cierre

| Criterio | Estado |
| --- | --- |
| Un protocolo por línea, preregistrado; OP-28 no se toca; OP-29 con protocolo nuevo sin repetir INT-A02 | **Cumplido** |
| Fuera de muestra, con comparación emparejada frente al mercado | **Cumplido** (walk-forward semanal; contraste con el cierre en el segmento M) |
| Control de circularidad del rating de mercado preregistrado | **Cumplido** (placebo y exclusión de cuotas futuras) |
| Veredicto por línea | **Cumplido**: OP-26 NO PASA · OP-27 NO PASA · OP-29 PASA · OP-30 PASA (C30b, C30c) · OP-28 fuera |
| Un candidato solo llega a CANDIDATE por la puerta del modelo; nunca a producción sin firma | **Cumplido**: nada se promovió ni se activó |
| Decisión del dueño anotada | **Pendiente**: ¿se pasan C30c y el conjunto conforme a la sesión de Intelligence como candidatos? ¿Se archivan OP-26 y OP-27? |

## 6. Reproducir

```
python scripts/lab_export.py verify <carpeta 20261121T050132Z>
python -m scripts.lab_portfolio <carpeta> --out pm1203.json        # unos 16 minutos con 2 núcleos
```

Resultado completo: `fbi_scratch\lab\results_20261121\pm1203_portfolio.json` en el portátil, SHA-256 `58e1a48b…e7e9`.
