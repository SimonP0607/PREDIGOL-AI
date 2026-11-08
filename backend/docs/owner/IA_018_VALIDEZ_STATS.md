# IA-018 · Validez del Agente de Estadísticas (v3) y del modo contexto del Match Agent (v4)

Fecha: 7 nov 2026. Estado: **en el código, sin desplegar**. Sin migración ni interruptor. Lo vigila `tests/unit/test_ia018_stats_validity.py`. Sigue el camino de IA-014 (`IA_014_SALIDAS_INVALIDAS_MATCH.md`).

## 1. Lo medido

* `battery-v3` con modelos reales (7 nov): objetivo `stats` **INSUFICIENTE** porque sus bases limpias no eran estables, y no porque el modelo obedeciera ataques: las respuestas limpias eran **inválidas** (`s_high` 1 de 5 válidas, `s_low` 2 de 5, `s_mixed` 1 de 5). En `match`, la base `m_context` quedó inestable (1 de 5 respuestas limpias no válida); las dos de evaluación, estables.
* Producción: una respuesta de `stats-v2` rechazada con `schema:candidates.0.risks.0:literal_error` (un riesgo fuera de su lista).

Son 15 + 5 respuestas de la batería y una de producción: la muestra no da una tasa; el diagnóstico sale del código.

## 2. Diagnóstico (desde el código)

**Estadísticas (`stats-v2`).**

1. **Una pareja (código, dirección) escrita dos veces.** Córners y tarjetas comparten códigos: en `s_high` las dos tasas superan su línea y en `s_low` las dos quedan por debajo, así que lo natural es `RATE OVER` (o `UNDER`) una vez por familia, y lo mismo con `MODEL_MARKET_GAP` (el modelo da 0,62 y 0,60 contra 0,50 del mercado). `aa-v1` rechaza entera la respuesta con la pareja repetida. El prompt pedía además una señal `RATE NEUTRAL` por relación descriptiva, y hay dos.
2. **Una referencia que el corte no tiene.** El prompt decía que `MODEL_MARKET_GAP` viene «de los candidatos», que están en el segundo objeto y no son referencia; el corte `stats` no tiene bloque `market`. No había lista de referencias citables (su ejemplo `P:shared.teams.home.all` está a cuatro claves).
3. **Un riesgo fuera de la lista** (lo de producción). Las razones de `REJECT_SIGNAL` («una tasa sobre pocos partidos», «un árbitro que no es el designado») no tenían código de riesgo, y la lista de salida no decía que un código de señal (`MODEL_MARKET_GAP`, `REFEREE`...) nunca es un riesgo.

**Match Agent, modo contexto (`match-context-v3`).** Es el único modo cuyo veredicto en la batería es la petición de investigación, y `aa-v1` escribe en una misma respuesta la dirección `HOME` y el lado `home`; la lista de v3 usaba además «topic» para dos cosas (el tema de una señal y el campo `topic` de la petición). Una petición con `side: "HOME"` o `topic: "ABSENCES"` invalida la respuesta entera. Es la causa concreta que el código muestra; la otra posible, más de 12 señales en un modo que invita a enumerar, quedaría como `schema:signals:too_long` y no se toca sin medirla.

## 3. Qué cambia

* **`stats-assess-v3` / agente `stats-v3`**, nacido **RETADOR** (fase `IA-018`):
  * el mensaje trae `citable` (`common.citable_refs` de lo que el modelo lee, escrito por código);
  * lista de salida cerrada (`output_checklist`): los 11 códigos de señal y los 11 de riesgo de este agente exactos (`LOW_STAKES` deja de ofrecerse: es del Match Agent; el contrato lo sigue aceptando), qué código toma cada tema y cada razón de cautela, «un código de señal nunca es riesgo», una señal por (código, dirección) **para las dos familias juntas**, las claves del segundo objeto que nunca se copian (`settlement`, `descriptive_relations`...);
  * reglas corregidas: `MODEL_MARKET_GAP` cita `P:families.markets`; las relaciones descriptivas son UNA señal; `REJECT_SIGNAL` nombra sus riesgos;
  * el lector añade los códigos `why:` de IA-014 (palabras fijas del servidor) y la lista de claves nombradas crece con `NAMED_EXTRA_KEYS_IA018`.
* **`match-context-v4` / agente `match-v4`**, RETADOR: solo cambia la lista de salida del contexto (las palabras de la petición van en minúsculas y no son direcciones ni códigos; «subject» en vez de «topic»). `match-assess-v3` no cambia byte a byte.
* `engine_version`: `ma-v1+match-v4+stats-v3+council-v1+contra-v1+router-v1`.

**No cambia:** el contrato `aa-v1` (mismo hash de esquema), el lector (no es tolerante: las respuestas de estilo v2 siguen rechazadas enteras), las salidas estructuradas nativas (apagadas), modelos, esfuerzos ni el Council. Los objetivos de la batería leen las constantes del prompt: `requests_hash` de `stats` y `match` cambia y la medición anterior queda vieja, como manda `battery-v3`.

## 4. Cómo medir

1. Una ronda de `battery-v3` en el LAB con `stats` y `match`: las bases `s_*` y `m_context` deben salir **estables** (≥ 4 de 5 respuestas limpias válidas y con el mismo veredicto).
2. En producción, por `agent_version` desde el despliegue: inválidas de `stats-v3` y `match-v4` con sus códigos (`schema:`, `why:`). Objetivo ≤ 3 %; no se juzga antes de 100 ejecuciones respondidas.
3. Si sigue fallando: los `why:` dicen qué; el siguiente paso es el turno de reparación (IA-014, sección 3), nunca aflojar el lector.

Vuelta atrás: desplegar el código anterior; las filas se distinguen por `agent_version`.
