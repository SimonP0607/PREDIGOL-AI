# IA-061 · Prevención de fugas temporales (pieza AD-A04)

Pieza AD-A04 del plan de la arquitectura definitiva 2026. Tres cosas, todas **en la sombra**: la sombra relee el partido justo antes del último pase; ningún hecho llega a un agente sin su hora de conocimiento comprobada; y la auditoría nocturna tiene una versión nueva, `leak-audit-v10`, que corre **junto a** `leak-audit-v9`. Sin migración. Sin cambios en `decision-v1`, en los pases de producción, en los paquetes ni en lo que ve el lector.

## 1. El caso de origen (12-nov-2026, partido 180277)

El estado del pase `final` (fila 6912 de `ai.match_runs`) se escribió a las 19:26:51 con un paquete de las 19:20:51 que decía «saque 20:00, `NS`». El saque real fue a las 19:00. El proveedor corrigió la hora al día siguiente (13-nov 10:57:29). Ningún agente leyó ese paquete.

Lo que se comprobó el 16-nov, en solo lectura:

- **El proveedor también estaba mal en el momento.** Sus propias respuestas de `/fixtures` para ese partido decían `NS` y 20:00 a las 19:18, las 19:29 y las 19:40 (3 respuestas guardadas). El primer estado «en juego» llegó a las 19:51 («1H, minuto 21»). Releer el partido, en la base o al proveedor, a las 19:26 **no lo habría visto**. Lo que sí lo cuenta es la auditoría del día siguiente.
- **Es un caso raro.** Del 25-oct al 16-nov hubo 2.074 pases `final` de la capa de IA. Solo 1 tiene el paquete en o después del saque de hoy (el 180277). Solo 2 tuvieron un cambio de saque visto después del paquete y antes de 3 h tras el pase, y en los dos el cambio se vio después de terminado el pase (06:04 y 13:19), así que una relectura en el momento tampoco lo habría visto.

## 2. Qué cambia

### 2.1 Relectura antes del último pase (`fbi/ai/final_reread.py`, `reread-v1`)

Justo antes de dar un pase `final` a un agente de la sombra (`fbi/ai/orchestrator.py`), el código vuelve a leer el partido: la hora y el estado que hay ahora en `core.fixtures` (los mantienen al día el seguimiento en vivo y la actualización de alineaciones con lo que dice el proveedor), y si el mercado en vivo lo está viendo jugar (`market.live_fixture_current`, captura de menos de 5 min y no terminada). El pase solo sigue si el partido está por jugarse, a la misma hora que tenía el paquete y con esa hora todavía por delante. Si no, se para con **un motivo cerrado**:

| Motivo | Cuándo |
| --- | --- |
| `kickoff_moved` | la hora de ahora no es la del paquete (adelantada o atrasada) |
| `kickoff_passed` | la hora de ahora ya pasó |
| `started` | el estado es de partido en juego, o el mercado en vivo lo ve jugando |
| `suspended` | `SUSP` o `INT` |
| `postponed` | `PST` |
| `cancelled` | `CANC`, `ABD`, `AWD`, `WO` |
| `finished` | `FT`, `AET`, `PEN` |
| `kickoff_unknown` | sin hora, o `TBD` |
| `status_unknown` | un código que la tabla no conoce |
| `fixture_missing`, `packet_without_kickoff`, `reread_failed` | no hay con qué comparar, o la lectura falló |

Un pase parado **no escribe nada**: ni tarea, ni ejecución, ni estado, ni revisión. Así no queda un estado escrito con el partido ya empezado (que la auditoría v9 y la Gate B contarían como tarde). El informe de cada ciclo `orchestrate` (`ai.cycles.counts`) lo cuenta en `reread_aborted`, con el motivo en `reread`. El proceso no vuelve a leer ese pase.

Un pase que sigue guarda su lectura en `ai.match_runs.data_status.reread`: la hora y el estado leídos, la hora del paquete y el momento de la lectura.

La relectura es gratis: lee dos filas por índice, no llama al proveedor ni a ningún modelo. Llamar al proveedor no se hizo, por lo que dice el punto 1. Si el dueño lo quiere, costaría una petición por pase `final` de la sombra (entre 1 y 17 al día del 9 al 16-nov, frente a un cupo de 60.000).

### 2.2 Hora de conocimiento comprobada en cada hecho (`fbi/ai/known_at.py`, `known-at-v1`)

El paquete ya rechazaba cualquier bloque con una marca de tiempo posterior a su momento, y dejaba fuera la evidencia sin hora o posterior. Pero se fiaba de la **copia** de las horas que guarda el paquete. Ahora, antes de dar **cualquier** pase a un agente, cada hecho del índice de evidencia (noticias, bajas, alineaciones, entrenador…, de `ai.evidence`, cuya hora de conocimiento es `retrieved_at`) se vuelve a leer de su fila por id. Si algo falla, el pase queda como NO EJECUTADO con el motivo `known_at:<códigos>`:

- `fact_missing`: la fila no existe;
- `fact_after_cutoff`: recuperado o publicado después del momento del paquete;
- `fact_stamp_differs`: la copia del paquete no tiene las mismas horas que la fila;
- `fact_other_match`: es de otro partido.

El resultado queda en `data_status.known_at`. No se cambió ninguna tabla. Según el ajuste del plan, en `ai.evidence` la hora de conocimiento es `retrieved_at`, que es obligatoria desde la migración 0072. Las tablas nuevas la llevarán desde su creación.

### 2.3 `leak-audit-v10` (`fbi/intel/leakage_v10.py`)

Es un paso nuevo de la noche (`leakage_audit_v10`). Corre **después** de v9 y escribe sus filas en `intel.audit_checks` con `version = 'leak-audit-v10'`. v9 no se toca: sus reglas siguen escribiéndose como `leak-audit-v9` (la Gate B lee esas), y sus filas antiguas no se recalculan. v10 son las reglas de v9 más estas cuatro:

| Regla | Qué comprueba |
| --- | --- |
| `final_reread_known` | cada estado `final` de la sombra escrito después del primero que llevó relectura trae la suya: versión conocida, lectura que dejó seguir, hecha entre el momento del paquete y la escritura, con la hora del paquete por delante y el partido por jugarse |
| `final_started_known` | cada estado `final` (en vivo y sombra) tiene su momento antes del saque de hoy, **o** está explicado por el proveedor: el saque cambió después de escribirse el estado y, cuando se escribió, el proveedor decía una hora posterior a ese momento. Lo no explicado es violación |
| `final_started_explained` | la compañera de la anterior: `n_checked` es el número de casos explicados y `examples` sus ids. Nunca cuenta como violación, pero hace visible el caso, para que una noche no quede limpia en silencio |
| `news_known` | las noticias y demás hechos que llevan los paquetes del día (sombra y en vivo): cada hecho existe, es de ese partido o de un equipo, se recuperó y se publicó antes del momento del paquete, y la copia tiene las horas de la fila. Un paquete que no se puede volver a derivar cuenta como violación |

## 3. Medición en producción (solo lectura, 16-nov-2026)

Las reglas v10 se pasaron, con este mismo código, sobre los días del 9 al 15-nov (hora de Bogotá), con una conexión de solo lectura dentro del worker. No se escribió nada.

| Día | `final_started_known` (estados / violaciones) | explicados | `news_known` (hechos / violaciones) | `final_reread_known` |
| --- | ---: | ---: | ---: | ---: |
| 09-nov | 20 / 0 | 0 | 517 / 0 | 0 |
| 10-nov | 36 / 0 | 0 | 967 / 0 | 0 |
| 11-nov | 10 / 0 | 0 | 516 / 0 | 0 |
| 12-nov | 34 / 0 | **1 (fila 6912)** | 1.480 / 0 | 0 |
| 13-nov | 59 / 0 | 0 | 1.519 / 0 | 0 |
| 14-nov | 135 / 0 | 0 | 1.322 / 0 | 0 |
| 15-nov | 61 / 0 | 0 | 1.057 / 0 | 0 |

En total: 355 estados `final` y 7.378 hechos leídos, 0 violaciones sin explicar. El 12-nov queda **explicado**, no limpio. `final_reread_known` lee 0 porque en producción todavía no hay estados con relectura. Cada día tardó entre 1,5 y 16 s.

## 4. Qué no cambia

- `decision-v1`, los pases de la capa de IA (`fbi/ai/cycle.py`), los paquetes (`package-v3`, mismos hashes), los prompts, los umbrales, los interruptores y lo que lee el lector.
- `leak-audit-v9`: el mismo código, las mismas filas. El 12-nov sigue con su violación de `slice_known` (la v10 no la relaja: la explica aparte). Aceptarla en la Gate B sigue siendo decisión del dueño.
- Los pases `first`, `pre` y `request` no se releen (solo se comprueban sus hechos).

## 5. Cómo se apaga o se revierte

- No hay interruptor nuevo: la relectura y la comprobación de hechos son parte del pase de la sombra. Se apagan apagando la sombra (`FBI_AI_ENGINES`, `FBI_AI_SHADOW_SAMPLE` o `FBI_AI_AGENTS`), como siempre, o revirtiendo el PR. Al revertir, el pase vuelve a la versión anterior y v9 sigue corriendo.
- La v10 es un paso aparte: si falla, no toca las filas de v9 de esa noche. Revertir el PR la quita, y sus filas quedan en `intel.audit_checks` (no se borra nada).

## 6. Criterio de cierre de la ficha

- 0 hechos nuevos sin hora de conocimiento: `news_known` a 0 violaciones en 7.378 hechos (9 al 15-nov) y, desde el despliegue, la puerta `known_at` en cada pase.
- El caso del 12-nov reproducido y resuelto en prueba: `tests/integration/test_final_reread_shadow.py` cubre el saque adelantado tras el paquete (el pase se para y no escribe nada) y un estado como el 6912 (explicado en v10 y todavía violación en v9).
- Una semana de días auditados sin violaciones sin explicar: medida hacia atrás (9 al 15-nov, arriba). Falta la semana de noches reales con la relectura desplegada, que la mostrará `final_reread_known` con `n_checked > 0`.
