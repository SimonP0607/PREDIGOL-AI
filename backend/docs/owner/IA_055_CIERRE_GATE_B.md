# IA-055 · Cierre de Gate B como «NO EVALUADO» (AD-001)

Pieza AD-001 del plan de la arquitectura definitiva 2026 (decisión n.º 3 del 16-nov-2026). Gate B (`gate-b-v1`) medía 14 días completos y estables de la sombra. Tú interrumpiste esa ventana al aprobar la arquitectura nueva, así que Gate B **no aprobó ni suspendió: no se llegó a evaluar**. Este cambio permite dejarlo escrito así, con tu firma y con las cifras de ese momento, sin tocar ninguna medición.

Hasta ahora el código no podía hacerlo:

- `evaluate --record` solo escribe PASA o NO PASA, y nada si el veredicto está pendiente;
- el panel de gates leía cualquier fila de Gate B con `passed=false` como «NO PASA».

Un INSERT a mano habría quedado como suspenso.

## 1. Qué hace

Un subcomando nuevo, `close`, en `scripts/ia_gate_b.py`:

```
python -m scripts.ia_gate_b close --not-evaluated --reason "..."                   # vista previa: no escribe nada
python -m scripts.ia_gate_b close --not-evaluated --reason "..." --confirm-owner   # tu firma: escribe el cierre
```

Con `--confirm-owner` añade **una sola fila** a `ai.feature_gates`:

| Campo | Valor |
| --- | --- |
| `gate` | `gate_b` |
| `passed` | `false` (nada aprobó) |
| `decided_by` | `owner` |
| evidencia, `kind` | `gate-b-closure-v1` |
| evidencia, `verdict` | `NO EVALUADO` |
| evidencia, `verdict_es` | «NO EVALUADO — ventana interrumpida por decisión del dueño» |
| evidencia, `reason` | tu motivo, tal cual |
| evidencia, `informative_cut` | el informe completo de `evaluate` en ese mismo instante, calculado por el mismo evaluador (que solo lee), con su hash |
| evidencia, `measurements_untouched` | la nota de que el cierre no altera ninguna medición |
| evidencia, `rows_cited` | las filas de batería y de Research v2 que cita el corte (hoy, 18 y 17) |

Reglas del comando:

- **Sin `--confirm-owner` (o con `--dry-run`) es una vista previa.** Abre la conexión en solo lectura, enseña la fila que escribiría con el corte de ese instante, no escribe nada y sale con código 3.
- **Solo hay un cierre.** Si ya existe uno, el comando no escribe otro: dice qué fila encontró y sale con 0. Dos órdenes simultáneas se ordenan con un candado y la segunda encuentra la fila de la primera.
- **Falta algo, no escribe.** Sin `--not-evaluated` o sin `--reason`, no se conecta y sale con 2.

## 2. El comando exacto

Tras el despliegue, en el servidor. Primero la vista previa, que no escribe:

```
docker exec -w /app predigol-worker python -m scripts.ia_gate_b close --not-evaluated --reason "No evaluado: ventana interrumpida por decisión del dueño (Arquitectura definitiva 2026, 16-nov-2026); corte informativo adjunto"
```

Después tu firma, la misma orden con `--confirm-owner`:

```
docker exec -w /app predigol-worker python -m scripts.ia_gate_b close --not-evaluated --reason "No evaluado: ventana interrumpida por decisión del dueño (Arquitectura definitiva 2026, 16-nov-2026); corte informativo adjunto" --confirm-owner
```

La salida empieza por `GATE B · NO EVALUADO — ventana interrumpida por decisión del dueño` y da el número de la fila. Para comprobarlo:

```
docker exec -w /app predigol-worker python -m scripts.ia_gates_panel show
```

Gate B aparece como `[NO EVALUADO] Gate B … · NO EVALUADO — ventana interrumpida por decisión del dueño`, y en las filas de evidencia como `gate_b: No evaluado (cerrado por el dueño)`.

El paso siguiente (AD-002, volver `FBI_AI_MODE` a `shadow`) va **después** de esta fila y es un paso aparte. Este cambio no lo hace.

## 3. Qué se ve en el panel

`scripts/ia_gates_panel.py` (`fbi.ai.gates_panel`) tiene una palabra nueva, **NO EVALUADO**. La usa solo cuando la fila más reciente de Gate B es tu cierre: `gate-b-closure-v1` con `decided_by='owner'`.

- **Nunca sale como NO PASA ni como PASA**, y nunca como aprobado.
- **El primer motivo** dice «No evaluado (cerrado por el dueño): NO EVALUADO — ventana interrumpida por decisión del dueño», con la fecha y la fila. El segundo es tu motivo.
- **Sin fecha evaluable ni «falla ya».** Las comprobaciones del día siguen a la vista, cada una con su palabra, marcadas como **corte informativo**: informan, pero no reabren el gate.
- **Una fila normal de `gate-b-v1` se lee igual que antes.** PASA o NO PASA. Una fila con forma de cierre que no hayas escrito tú no cuenta como cierre.
- **El comprobador del panel** da una violación si apareciera un NO EVALUADO sin tu fila de cierre.

## 4. Qué no cambia

- **Ninguna medición.** El cierre es una fila añadida y `ai.feature_gates` e `intel.audit_checks` son de solo añadido. Las filas 17 (`research_v2`, NO PASA, 12-nov) y 18 (`battery`, NO PASA, 15-nov) de `ai.feature_gates` y la 507 de `intel.audit_checks` (`slice_known` del 12-nov: 1 violación en 103) siguen como están, y el corte guarda todas las cifras tal y como las leyó el evaluador.
- **`evaluate` sigue sin escribir nada.** Después del cierre, `evaluate --record` ya no registra nada de `gate-b-v1` (dice que está cerrado). Una regla nueva sería otra versión, no esta.
- **El ancla de la ventana, `FBI_AI_MODE`, los interruptores, los motores, la muestra de sombra, los umbrales y los picks.** Nada de esto cambia: la fila es de `gate_b`, y lo que reancla ventanas lee otras filas (`switches` y los gates de optimización). El lector no ve nada nuevo y `decision-v1` no se toca.
- **Sin migración.** El CHECK de la `0127` ya admite `gate_b` y `decided_by='owner'`. Sin interruptor y sin coste de API.

## 5. `set-lab-plan` ya no hace falta

`set-lab-plan` servía para que escribieras los días del LAB previstos al arrancar la sombra, que Gate B necesitaba para su comprobación `lab_envelope`. Con Gate B cerrado como no evaluado, esa cifra ya no se va a juzgar: **no hace falta ejecutarlo**. El subcomando se conserva, sin cambios, por si un gate posterior lo necesita y para que el registro no pierda nada.

## 6. Cómo se revierte

- **El código** se revierte con el PR. Sin `close`, el panel volvería a leer la fila de cierre como «NO PASA», así que no conviene revertir después de firmar.
- **La fila se queda**, porque `ai.feature_gates` es de solo añadido. Una corrección se hace con una fila nueva tuya, nunca borrando ni editando.
- **La `0127` ya no se puede bajar.** Con una fila de `gate_b` escrita, el `downgrade` de esa migración se niega, como ya decía la migración.

## 7. Comprobado en producción (solo lectura)

El 16-nov-2026 a las 20:51 UTC, con una conexión de solo lectura: `ai.feature_gates` tiene 18 filas y ninguna es de `gate_b` ni de `lab_plan`. Los hashes empiezan por `70d7e14bc650` en la fila 17 y por `253ce60d923d` en la 18; la fila 507 de `intel.audit_checks` es `slice_known`, `leak-audit-v9`, 103 comprobadas y 1 violación.

El corte informativo de referencia es el de las 17:45:35 UTC de ese día:

| Comprobación | Resultado |
| --- | --- |
| Ventana | `PENDIENTE POR TIEMPO REAL`, 5 de 14 días, evaluable el 25-nov |
| `invalid_outputs` | NO PASA |
| `leak_audit` | NO PASA |
| `battery` | NO PASA |
| `research_v2` | NO PASA |

El corte que se adjunte se calcula en el momento de tu firma y puede diferir en los días transcurridos.
