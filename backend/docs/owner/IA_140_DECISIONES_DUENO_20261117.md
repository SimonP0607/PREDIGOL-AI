# IA-140 · IA-141 · IA-142 · Tres decisiones del dueño (17-nov-2026)

Fecha: 17 nov 2026. Dentro del «Plan maestro de implementación de la arquitectura definitiva 2026» (aprobado el 16-nov), el dueño tomó tres decisiones que estaban pendientes. Esta guía dice qué decidió, qué cambia en el código, qué **no** cambia y cómo se revierte cada una. Sin migración, sin cambios en la web y sin ningún efecto en el lector: todo sigue en sombra.

| Código | Pieza | Decisión |
| --- | --- | --- |
| IA-140 | AD-A03 (`battery-v4`) | Criterio estricto: **0 % de salidas inválidas** |
| IA-141 | AD-A06 (presupuesto) | Sobres **US$ 185 producción, US$ 55 LAB, US$ 35 Exa**; **sustituyen** al techo conjunto de US$ 190, que deja de aplicarse |
| IA-142 | AD-D06/D07 (ciclo de evaluaciones) | **E4 pasa a T-5**, con `decision-v1` intacto |

## 1. IA-140 · battery-v4: 0 % de salidas inválidas

**Qué estaba pendiente.** El protocolo AD-A03 deja firmar un umbral de salidas inválidas entre 0 % y 3 % (la prueba A2 del Doc 2 dice «hasta 3 %»; la propuesta del plan y la del 15-nov decían 0 %). El código no elegía: esperaba la firma.

**Qué cambia en el código** (`fbi.ai.battery.v4`, `fbi.ai.battery.v4_run`, `scripts/ia_battery_v4.py`):

* Constante nueva `OWNER_INVALID_MAX = 0.0`, con su procedencia fechada y versionada en `OWNER_INVALID_MAX_DECISION` (`IA-140`, `AD-A03`, `2026-11-17`, `invalid-max-v1`). El valor por defecto de los parámetros (`Params.invalid_max`) sale de ella.
* `sign` (la firma del dueño) **solo acepta `--invalid-max 0`**: cualquier otra cifra se rechaza sin escribir nada. La fila de la firma guarda además `owner_decision` con esa procedencia.
* Una firma con otra cifra **no cubre la batería** (`Signature.problems`): `submit` y `collect` se niegan. Hoy no hay ninguna firma de `battery-v4` en producción (consulta de solo lectura de `ai.feature_gates`, 17-nov-2026 14:27 UTC: 0 filas de `battery-v4`), así que no se invalida nada.

**Qué no cambia.** El protocolo AD-A03 (`proto-ad-a03-v1`) y su huella, el corpus y su `corpus_hash`, lo que se mide y el resto de umbrales: cero respuestas que obedecen, inventan o se niegan; 15 controles por base (12 como mínimo); 2 + 8 preguntas por caso de los jueces, 10 por extracción; Holm al 5 %. `battery-v3` y su fila 18 siguen como estaban. `fbi.ai.outputs` (IA-064) no cambia: valida cada respuesta, no fija ningún porcentaje.

**Lo que falta (no lo hace esta pieza).** La firma en la base la hace el agente principal con el comando documentado en `IA_065_BATTERY_V4.md`:

```
docker exec predigol-worker python -m scripts.ia_battery_v4 sign --invalid-max 0 --reason "..."                   # vista previa
docker exec predigol-worker python -m scripts.ia_battery_v4 sign --invalid-max 0 --reason "..." --confirm-owner   # la firma
```

**Cómo se revierte.** Volver a permitir otra cifra es una decisión nueva del dueño: una versión nueva de `OWNER_INVALID_MAX_DECISION` (`invalid-max-v2`) en un PR, nunca editar una firma ya guardada. Revertir el PR deja el código como antes (cualquier cifra de 0 a 3 % firmable).

## 2. IA-141 · Los sobres sustituyen al techo conjunto de 190

**Qué estaba pendiente.** Los sobres de la decisión 12 (185 / 55 / 35) ya se mostraban, pero el LAB seguía cediendo ante el techo conjunto: recibía como mucho `190 − proyección de producción` (el 16-nov eso le dejaba 50,84 en vez de 55). El interruptor `FBI_AI_ENVELOPES_INDEPENDENT` estaba preparado y apagado.

**Qué cambia en el código:**

* **Registro versionado de los sobres** (`fbi.ai.capability_budget.ENVELOPE_DECISIONS`): `envelopes-v1` (decisión 12, 16-nov: 185 / 35 / 55, techo conjunto vigente) se conserva tal cual, y se añade `envelopes-v2` (17-nov, IA-141: las mismas cifras, techo conjunto **no** aplica). `DECISION_12` no cambia. El registro de capacidades sigue siendo `capability-budget-v1` (sus topes no cambian).
* **Ningún sobre sube por encima de lo decidido** (`envelope_cap`): el presupuesto v3 aplica la cifra del entorno, pero nunca más de 185 (producción), 55 (LAB) o 35 (Exa). Una cifra menor en el entorno sigue mandando (por ejemplo 0 para parar el LAB).
* **El LAB se rige por su sobre de 55** (`fbi.ai.budget_v3.lab_day`): ya no cede ante la proyección de producción. `FBI_AI_ENVELOPES_INDEPENDENT` pasa a estar **encendido por defecto**; solo `off`, `0`, `false` o `no` lo apagan (la vuelta atrás). `JOINT_CEILING_PENDING` pasa a `False`.
* **El panel de costes** (`fbi.ai.costs_v3`) dice «techo conjunto 190 sustituido por los sobres 185 / 55 / 35 (decisión del dueño del 17-nov-2026, IA-141)», con `replaced_by: envelopes-v2`, lo que recibe el LAB y lo que recibiría si se volviera atrás. La consola (C-11) enseña `applies: false`, `pending_owner: false` y el interruptor con su nuevo valor por defecto (`on`). El contrato C-11 no cambia.
* **Las alertas de coste** pasan a `cost-alerts-v2`: la proyección «producción + LAB contra el techo conjunto» solo se vigila mientras el techo aplique (interruptor en `off`). Lo demás de v1 sigue igual.

**Qué no cambia.** Los cortes que fallan cerrado: el sobre de cada uno (mes gastado, tope del día, límite del proveedor), el LAB que solo empieza un día que puede terminar, el corte por pieza al 95 % de IA-137 (`piece_allows`), la reserva de 10 de producción y los avisos del 50 / 70 / 85 / 95 / 100 % y del 80 / 95 %. La cifra `FBI_AI_JOINT_CEILING_USD` (190) se conserva para la vuelta atrás. **La puerta A** (`fbi.ai.gate_a`, comprobación `cost_joint` ≤ 190) no se toca: es una puerta con su criterio registrado; cambiarlo a posteriori sería cambiar la regla de una puerta. Los límites de la Console de Anthropic (190 en producción, el del LAB) son acciones del dueño fuera del código y siguen como estén. El camino anterior (`FBI_AI_BUDGET_V3=0`) sigue igual.

**En el servidor.** El 16-nov el servidor tenía configurados 185 / 55 / 35 (`IA_058`): no hace falta cambiar ninguna variable. Tras desplegar, el panel de costes debe decir `joint_ceiling.applies = false` y `lab_allocation_usd = 55`. Si dijera `applies = true`, es que en `app.env` hay un `FBI_AI_ENVELOPES_INDEPENDENT=off` explícito (IA-058 no lo añadió).

**Cómo se revierte.** Sin PR: `FBI_AI_ENVELOPES_INDEPENDENT=off` y reiniciar el trabajador. El LAB vuelve a ceder ante 190 menos la proyección de producción, y la alerta conjunta vuelve. El tope de 55 del LAB sigue (el techo conjunto solo puede bajarlo). Con PR: revertirlo deja el código como en IA-058.

## 3. IA-142 · E4 a T-5

**Qué estaba pendiente.** La ficha dice E4 a T-5. El ciclo lo tenía de T-20 a T-10 porque, por debajo de 10 minutos, `decision-v1` rechaza todo («menos de 10 min al saque», `fbi.intel.decision.MIN_MINUTES`) y `decision-v2` hereda esa regla. **`decision-v1` está protegido: no se toca ni se baja su mínimo.**

**Qué cambia en el código** (`fbi.evalcycle.clock`, `fbi.evalcycle.run`, `fbi.shadowjobs.eval_cycle`):

* El reloj pasa a `eval-clock-v2`. **E4 va de T-5 al saque.** E2 cubre los hechos hasta que abre E4 (T-5).
* **La última decisión, de T-20 a T-10** (`clock.last_decision`): `decision-v2` decide por última vez antes de su umbral, o se adopta el momento que ya guardó su propio pase (disparador E4 de IA-093). Se guarda solo en las tablas de `decision-v2`; no escribe ninguna evaluación del ciclo. Es lo que antes hacía E4.
* **E4 a T-5 no decide.** Relee el partido (hora, estado, sede) y juzga cada selección con la **última decisión guardada de `decision-v2` antes de su umbral** (en sombra) y el **precio leído otra vez a T-5**, con la alineación que haya. Su fila dice `decided = false`, el momento adoptado (`decision_moment_id` y `summary.decision`), `summary.clock = eval-clock-v2` y `summary.price = releido`.
* La cadencia del pase principal (`FBI_EVAL_CYCLE_MINUTES`) pasa a 1–5 minutos (5 por defecto): la ventana de E4 mide 5 minutos y una cadencia mayor podría saltársela. Una cifra fuera de rango vale 5.
* En la vista privada del partido (C-01 v2), la evaluación E4 pendiente se espera a T-5.

**El espejo de `decision-v1` en esa ventana.** El espejo (IA-093) copia cada momento en que `decision-v1` decidió. A T-5 `decision-v1` no decide: su último punto es T-15m, y un pase suyo por debajo de 10 min solo rechaza (97 filas de `decision-v1` en 59 partidos en los últimos 7 días, consulta de solo lectura del 17-nov-2026); el espejo copia esos rechazos tal cual, como debe. **E4 nunca adopta un momento guardado por debajo del umbral**, así que esa copia nunca pasa a ser la decisión de E4. La comparación con `decision-v1` termina en su último momento.

**Lo que se miró y no cambia.** `decision-v2` guardada (IA-093) sigue con su E4 de T-20 a T-10: es su última decisión posible. La titularidad estimada (IA-094) sigue en sus ventanas (E1 y T-20 a T-10): el E4 del ciclo no la lee. Los lectores especialistas (`fbi.ai.readers`, IA-123) siguen callando desde T-20, la apertura de la última decisión. En producción, a 17-nov-2026 14:27 UTC, ni el ciclo (`intel.eval_runs`) ni `decision-v2` guardada (`intel.decision_v2_moments`) están desplegados todavía: no hay filas antiguas que reinterpretar.

**Cómo se revierte.** Revertir el PR (vuelve `eval-clock-v1`: E4 de T-20 a T-10 decidiendo, cadencia 1–10). Apagar el ciclo: `FBI_EVAL_CYCLE=off` y reiniciar el trabajador; las filas guardadas se conservan.

## 4. Qué no cambia en ninguna de las tres

`decision-v1`, `FBI_PICKS_SOURCE`, los picks, las probabilidades, los prompts, los modelos, la web y todo lo que ve un lector. Nada sale de la sombra. Ninguna tabla nueva, ningún dato borrado.
