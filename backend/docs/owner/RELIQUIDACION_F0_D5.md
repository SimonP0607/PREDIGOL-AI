# Re-liquidación de resultados corregidos (Plan Maestro, fase F0, defecto 5)

**Qué es.** Cuando el proveedor corrige el marcador de un partido *después* de que sus apuestas ya estaban liquidadas, esas
apuestas se liquidan de nuevo con el resultado nuevo, **dejando rastro** de lo que eran antes. Versiones: `settle-v4` (picks,
picks del día, selecciones) y `parlay-settle-v2` (combinadas). **No toca lo que se decidió antes del partido** (precio,
probabilidad, EV, stake, congelado del pick del día): solo el resultado.

## El problema que corrige

El resultado de un partido se sobrescribe cada vez que se lee un payload más nuevo, y la liquidación corre **una sola vez**: con la
*primera* lectura que dice «final», antes de las relecturas (inicio + 150 min y + 26 h) que existen justamente para pillar
correcciones. Un gol que el proveedor da o quita una hora después del pitido dejaba picks, picks del día, combinadas y apuestas de
usuarios liquidados con el resultado equivocado **para siempre**, y nada en la base de datos lo decía.

## Qué escribe (y qué no)

Migración **0080** (con respaldo y prueba de restauración antes, como todas):

| Objeto | Para qué |
|---|---|
| `core.fixture_result_revisions` | Cada corrección de un resultado: el marcador antes y después (tipo `score`) o el cambio de estado de un partido que ya había terminado (tipo `status`), con los payloads de cada lado. La escribe un **trigger** de la base de datos: ningún escritor puede saltárselo. La primera lectura de un resultado no es una revisión. |
| `picks.resettlements` | El rastro: una fila cada vez que un registro cambia de resultado (qué era, qué es, versión de liquidación, razón, revisión a la que responde). |
| `picks.pick_events.event_kind` | `status` (como siempre) o `resettlement`: el pick sigue liquidado pero su resultado cambió. La línea de tiempo del pick lo distingue. |
| `picks.v_pick_record` | La vista del registro completo del pick, con una columna más: cuántas veces se liquidó de nuevo. |

Nada existente se reescribe. Las dos tablas nuevas son de solo-añadir: un `UPDATE` sobre ellas lo rechaza la base de datos (salvo el
interruptor de mantenimiento `fbi.history_maintenance`), y la revisión a la que responde una fila del rastro no se puede borrar
suelta (las dos se van con su partido). **El historial anterior a 0080 no existe**: una corrección de entonces sobrescribió el
marcador anterior y no quedó nada; la auditoría (más abajo) lo detecta igualmente comparando contra el marcador actual.

## Qué cambia y qué se niega a adivinar

Solo actúa donde **un marcador decidió el registro** y el marcador actual lo decide distinto. Todo lo demás se **retiene y se
informa**, nunca se aplica:

| Código | Qué pasó | Qué hace falta |
|---|---|---|
| `void_by_rule_stands` | Se anuló por regla (partido cancelado, o sin resultado a las 72 h) y ahora el partido tiene resultado. | Una persona decide si la casa lo anularía después de hecho. |
| `settles_by_rule_now` | Estaba liquidado por marcador y ahora el partido se liquida por regla (p. ej. dice cancelado). | Una persona decide si se anula. |
| `no_longer_settles` | Estaba liquidado por marcador y ahora el partido ya no se liquida (aplazado, o sin marcador de 90 min). | Esperar: un estado que va y vuelve no debe reescribir dinero dos veces. |
| `profit_unknown` | Todas las selecciones están liquidadas pero el beneficio no se puede conocer (medio perdido y una selección sin cuota). | Nunca se inventa. |

Una combinada **sigue a sus selecciones**: se decide de nuevo con las selecciones como están ahora, y si ninguna selección corregida
la decide ya, **vuelve a `ACTIVE`** (sin resultado, sin beneficio, sin fecha de liquidación) hasta que se jueguen las demás.
`settled_at` se conserva (el momento de la primera liquidación); el momento de cada corrección está en el rastro.

* **Idempotente.** Compara cada registro con lo que da el marcador actual: una segunda pasada no encuentra nada, y una corrección de
  la corrección lo devuelve y deja una segunda fila de rastro.
* **Guardado.** Cada `UPDATE` exige que el registro siga como se leyó (estado **y** beneficio): si otra pasada lo cambió en medio,
  es un *conflicto* (se cuenta) y no una sobrescritura.
* **Freno de masa.** Más de **25 partidos** con registros cambiados en una pasada no es una corrección, es algo que va mal aguas
  arriba (un reproceso, un defecto): **no se escribe nada**, se informa la lista y una persona sube el límite cuando la ha mirado.
* **Un solo pase a la vez** (candado de aplicación).
* **Lo que se construyó sobre el resultado viejo no se reescribe aquí**: `intel.decision_outcomes`, `intel.postmortems`,
  `intel.match_postmortems`, `ai.pick_postmortems` y `ai.postmortems` son de solo-añadir; se **cuentan** en el informe (`built on the
  old results`). Reconstruirlos era la fase **F8** (hasta entonces conservan el resultado de entonces). *Lo que se decidió en F8
  (23 oct 2026):* el post-mortem único (`pm-v6`) tampoco se reescribe, así que si un resultado se corrige, rehacerlo exige una versión
  nueva del post-mortem; la tabla `core.fixture_result_revisions` no tiene hoy ninguna corrección registrada, así que no hay nada que
  reconstruir. Ver `docs/owner/POSTMORTEM_MEMORIA_F8.md`.

## Cómo corre

* **Rutina:** dentro del pipeline de picks (cada 30 min), tras la liquidación normal y antes de los registros del producto, en su
  propia subtransacción: un fallo ahí queda anotado en la corrida (`errors`) y **no cuesta** los pronósticos, candidatos ni la
  liquidación. Mira los partidos corregidos en los **últimos 7 días**.
  *Diferencia con el plan:* el plan decía «`results_repair` detecta la corrección y re-liquida». Se hizo distinto a propósito: la
  **detección** es un trigger de la base de datos (la ve cualquier escritor: seguimiento en vivo, reparación, relectura posterior,
  sincronización de resultados) y la **re-liquidación** va en el pipeline, que ya liquida los picks y los registros del producto
  en el orden que hace falta (las selecciones antes que la combinada que las usa) y corre cada 30 min.
* **Interruptor:** `FBI_RESETTLE=0` (y reiniciar el worker) la apaga sin desplegar. La corrida lo dice en sus notas
  (`re-settlement OFF`) y en el registro de avisos. Las correcciones se siguen **registrando** (lo hace la base de datos); se
  liquidan al volver a encenderlo o a mano.
* **A mano** (desde `backend/`), para lo que la rutina no alcanza:

```bash
python -m scripts.resettle                              # ensayo: los partidos corregidos en los últimos 7 días
python -m scripts.resettle --days 30                    # ... en los últimos 30 días
python -m scripts.resettle --fixture 123 --fixture 456  # ... estos partidos, corregidos o no
python -m scripts.resettle --all                        # ensayo: AUDITORÍA de todo registro liquidado
python -m scripts.resettle --all --apply --by NOMBRE    # escribir lo que encontró la auditoría (decisión de una persona)
```

  El ensayo escribe dentro de una transacción que se deshace: **lo que imprime es exactamente lo que haría `--apply`**. `--apply`
  exige `--by NOMBRE` (el nombre queda en la razón de cada fila del rastro). Código de salida: 0 hecho (o ensayo), 2 argumentos
  mal, 3 frenado por la guarda u otra pasada en curso.

## Primer despliegue

1. Respaldo verificado y prueba de restauración (regla del proyecto), worker parado, migración 0080 con `lock_timeout`, permisos
   (`grants.sql`: el API ya lee las tablas nuevas por los privilegios por defecto), reinicio, salud.
2. **Antes de dejar la rutina sola:** `python -m scripts.resettle --all` (ensayo). Lista las combinadas liquidadas con la fórmula
   antigua de medias líneas (defecto 4) y los registros cuyo marcador guardado no coincide con el actual. Se revisa la lista; si es
   lo esperado, `--all --apply --by NOMBRE` (subiendo `--max-fixtures` solo si cada partido de la lista es esperado).
3. Después, la rutina se ocupa de las correcciones nuevas. Todo sigue en **SHADOW**.

## Qué ve cada quien

* **Quien usa el producto** (pick del día, combinadas, «Mis picks», «Mis combinadas»): la tarjeta muestra el resultado de ahora y
  una nota «Resultado corregido» con *qué era → qué es* (y a qué selección se refiere en una combinada). La causa va como **código**
  que la web traduce a ES/EN (`result_corrected`, `status_changed`, `audit`): **nunca** el texto interno del rastro (que nombra
  revisiones y a quien lanzó una pasada manual). Cada persona ve solo lo suyo.
* **El administrador:** en la línea de tiempo del pick, el evento «resultado corregido» aparte de los cambios de estado; y en la
  **Auditoría del partido**, las correcciones del resultado (paso «Normalised rows», con los payloads de cada lado, que ahora
  también cuentan en «Raw payloads») y los registros liquidados de nuevo (paso «Settlement»). Los registros de **usuarios** solo se
  cuentan, no se nombran.

## Límites conocidos

* Sin historial de correcciones anterior a 0080 (la auditoría lo suple, con causa `audit`).
* Lo derivado del resultado viejo se cuenta, no se reescribe (F8).
* Las revisiones de *estado* solo se registran desde un partido que ya terminó (FT/AET/PEN) hacia otro estado.
* Una re-liquidación no envía correos ni notificaciones: solo se ve la nota en la tarjeta. La notificación de un pick liquidado
  (`pick_settled`) es una por pick (su clave de deduplicación es `pick:ID:settled`): la que ya se envió o está en cola conserva el
  resultado de entonces.

## Cómo deshacerlo

* Parar solo la rutina: `FBI_RESETTLE=0` y reiniciar el worker. El rastro y las revisiones quedan.
* Deshacer lo que escribió una pasada: no hay botón, a propósito. El rastro (`picks.resettlements`) tiene el estado y beneficio
  anteriores de cada registro; revertir es una decisión de una persona, con su propio respaldo.
* Quitar el mecanismo: `alembic downgrade 0079` (borra las dos tablas nuevas, los triggers, la columna `event_kind` y devuelve la
  vista a como era). **No** devuelve los registros ya corregidos a su resultado anterior. Hacer antes el respaldo habitual.
