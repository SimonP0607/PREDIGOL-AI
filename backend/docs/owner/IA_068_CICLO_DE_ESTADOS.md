# IA-068 · Ciclo único de estados de una selección (AD-D02)

Pieza AD-D02 del plan de la arquitectura definitiva 2026. Da a cada selección **un solo ciclo de diez estados**, guardado como una
cadena de filas que nunca se reescribe. Lo escribe un proceso **en sombra**, apagado por defecto, que lee las capas actuales y no
cambia ninguna de ellas. Nadie lo lee salvo las vistas privadas del dueño.

## 1. Los diez estados

| Código | Qué significa | Quién lo pone hoy |
| --- | --- | --- |
| `detectado` | El sistema ve la selección por primera vez | El primer pick en sombra (`picks.picks`) o la primera decisión |
| `en_investigacion` | Se buscan hechos que la sostengan o la tumben | Una decisión con el contexto aún sin leer (`PENDING`) |
| `en_evaluacion` | Decisión en curso; algo de la propia selección no cumple todavía | Cualquier otra decisión que no la confirme, con su motivo |
| `pendiente_alineaciones` | Espera a la alineación oficial | Una baja clave anunciada y nada más, antes del punto `lineups` |
| `confirmada_sombra` | Cumple todo; no se publica | Una decisión aprobada, o aparcada **solo** porque su mercado no está validado |
| `retirada` | Estaba esperando o confirmada y perdió el fundamento | La siguiente decisión ya no la sostiene, o la revisión la rechaza |
| `descartada` | No llegó a cumplir | Al saque, con el último motivo que la frenó; o el partido no se juega |
| `en_juego` | El partido empezó | Al saque, si estaba confirmada |
| `liquidada` | Tiene resultado (`settle-v4`) | `intel.decision_outcomes` |
| `evaluada` | Tiene evaluación posterior | El post-mortem (`intel.postmortems`, `intel.family_postmortems`) |

Cada fila lleva un **motivo de una lista cerrada** propia de su estado (por ejemplo `valor_insuficiente`, `sin_calibrar`,
`precio_antiguo`, `revision_en_contra`, `cumple_salvo_validacion`, `retirada_al_saque`, `partido_no_jugado`). Un motivo que el mapa no
conoce queda como `sin_motivo_conocido`, contado, nunca adivinado.

## 2. Las reglas, en la base de datos y en el código

La tabla `intel.selection_lifecycle` (migración `0142`) y el módulo `fbi.lifecycle.machine` tienen las mismas reglas, y una prueba
comprueba que coinciden:

- Una cadena empieza siempre en `detectado` y cada fila nombra la anterior. Una fila tiene un solo sucesor: no hay ramas.
- Solo valen los movimientos del ciclo. `descartada` y `evaluada` no tienen salida; `en_juego` solo pasa a `liquidada`, y esta a
  `evaluada`. Solo una selección confirmada entra en juego.
- **Un modelo solo baja**: una fila escrita por un modelo (la revisión, el Council) solo puede llevar a `retirada` o `descartada`.
- **Nada es público sin el dueño**: el único movimiento del dueño es autorizar una selección confirmada, con su firma. El estado público
  (`publicada`, `en_juego`, `liquidada`) solo existe con esa autorización, y se pierde si la selección se retira. El proceso en sombra
  nunca escribe una autorización: todo lo que escribe es privado.
- Ninguna fila puede ser anterior a la que sigue. No se puede modificar ni borrar ninguna fila.

## 3. Cómo se lee de las capas actuales (`lifecycle-map-v1`)

- **Selección** = partido, mercado, selección y línea (la misma clave de `decision-v1`). La guía la marca la capa que decide:
  `decision-v1` para los mercados del núcleo y `decision-fam-v1` para córners, tarjetas y mitades. Son los mismos candidatos que
  `decision-v2` vuelve a decidir en la repetición; cuando `decision-v2` guarde sus decisiones (AD-D01), su tabla se añade como otra capa.
- **Un rechazo antes del saque no es definitivo.** En 14 días, 709 de las 10.181 selecciones que `decision-v1` rechazó en algún punto
  de control dejaron de estar rechazadas en uno posterior. Por eso siguen «en evaluación» con su motivo y se descartan al saque.
- **Los últimos 10 minutos no cuentan.** `decision-v1` rechaza todo a menos de 10 minutos del saque («menos de 10 min al saque»); eso
  dice que el partido va a empezar, no que la selección perdió el fundamento. En 14 días hubo 596 filas así (568 en el punto `lineups`).
- **La revisión solo baja.** Un `REJECT` o `DOWNGRADE` de la revisión combinada sobre una selección que esperaba o estaba confirmada la
  retira, con actor «modelo». Un `APPROVE` no sube nada.
- **Un partido aplazado espera 3 días** antes de cerrar sus selecciones (puede jugarse otro día). Uno cancelado, abandonado o adjudicado
  las cierra a la hora prevista del saque. Sin un estado que diga que empezó, no se cierra nada solo por la hora.

## 4. Qué se midió en producción (solo lectura, 17-nov-2026 00:39 UTC)

Las capas actuales de los partidos con saque del 2 al 15 de noviembre (14 días de Bogotá), derivadas con este mismo código cargado en
memoria en el contenedor del worker, con conexión de solo lectura:

| Dato | Valor |
| --- | --- |
| Selecciones (n = 17.332) | **1.238 al día de media**, mediana 607, mínimo 123, máximo 4.827 (sábado 7-nov) |
| Por capa | `decision-v1` 10.818 · `decision-fam-v1` 6.514 (las familias desde el 5-nov) |
| Filas del ciclo | 60.805: **4.343 al día de media** (máximo 17.003), 3,5 por selección |
| Con estado y motivo | 100 %: 17.271 descartadas y 61 abiertas (9 partidos aplazados dentro de los 3 días y 3 sin estado actualizado) |
| Transiciones ilegales | **0** |
| Motivos desconocidos | **0** |
| Cadenas que no son prefijo de la cadena final | **0** de 85.730 comprobaciones (5 momentos por selección, de T-24 h a T+50 h) |
| Confirmadas en sombra alguna vez | 110 selecciones; **todas se retiraron antes del saque** y ninguna llegó a `en_juego` |
| Motivo de las 128 retiradas | precio antiguo 90 · revisión en contra 19 (escritas por un modelo) · valor insuficiente 11 · datos 5 · riesgo 3 |
| Motivo final de las descartadas | valor insuficiente 8.444 · sin calibrar 5.898 · mercado estrecho 934 · contexto pendiente 637 · precio antiguo 622 · datos 389 · revisión en contra 120 · retirada al saque 109 · partido no jugado 88 · precio atípico 29 · baja clave confirmada 1 |

Dos conclusiones para el dueño:

1. **Hoy ninguna selección llegaría a «en juego», «liquidada» ni «evaluada».** Las pocas que `decision-v1` deja aparcadas solo por la
   validación del mercado se pierden antes del saque, sobre todo por el precio (90 de 128 retiradas): en los puntos finales
   `decision-v1` pide un precio de menos de 30 minutos y el de la captura tiene una edad mediana de 99,7 minutos (medición A06 del plan). El precio del libro con 45/75/195 min (`decision-v2.1`, IA-067) es lo que puede cambiar esto cuando
   `decision-v2` decida en sombra (AD-D01).
2. **Las familias nunca se confirman con este mapa**: todas llevan «sin calibrar» (no tienen calibrador campeón). Es una decisión del
   mapa, no del código: si el dueño quiere seguir sus selecciones hasta el resultado aunque su número no esté calibrado, hace falta un
   `lifecycle-map-v2` con un motivo propio (por ejemplo `cumple_sin_calibrar`), siempre con el sello «sin calibrar».

El tamaño esperado de la tabla es de unas 4.300 filas al día (unos 1,6 millones al año). Se vigila con AD-A07.

## 5. Qué no cambia

`decision-v1`, `decision-fam-v1`, `state-v2`, `user-status-v2`, la revisión, los picks, el set del día, la liquidación y los post-mortems
siguen igual: el proceso solo los lee y una prueba comprueba que solo escribe en su propia tabla. `FBI_PICKS_SOURCE` sigue apagado.
No hay ningún modelo, búsqueda ni petición a API-Football. Ningún lector ve nada.

## 6. Cómo se enciende, se apaga y se revierte

- **Encender en sombra:** `FBI_SELECTION_LIFECYCLE=shadow` en el entorno del worker y reiniciarlo. El trabajo `lifecycle_shadow` corre cada 30
  minutos (`FBI_SELECTION_LIFECYCLE_MINUTES`), sigue los partidos de los últimos 7 días y las próximas 48 horas, y tiene un plazo de 15 minutos.
  La primera pasada rellena esos 9 días (unas 40.000 filas).
- **Ver qué haría sin escribir:** `python -m scripts.ia_lifecycle run --dry-run`. **Medir:** `python -m scripts.ia_lifecycle measure
  --from 2026-11-02 --to 2026-11-15`. **Leer** (lo que usará C-03): `python -m scripts.ia_lifecycle tracking --from … --to …
  [--state …] [--family corners]`.
- **Apagar:** `FBI_SELECTION_LIFECYCLE=off` (o quitar la variable). Las filas se conservan.
- **Revertir del todo:** la migración `0142` tiene `downgrade`, que borra la tabla con sus filas. Las capas actuales siguen funcionando
  igual con o sin ella.

## 7. Lo que queda para otras piezas

- AD-D01: que `decision-v2` guarde sus decisiones y pase a guiar el ciclo (con el precio del libro).
- AD-D06: las evaluaciones E1–E4 escribirán sus propias cadenas (`eval-cycle-v1`), con la evaluación y su versión en cada fila.
- AD-D03: la dependencia de la alineación por selección (hoy `pendiente_alineaciones` solo sale de una baja clave anunciada).
- AD-J03 y AD-J04: los contratos C-02 y C-03 con su ejemplo y sus rutas privadas; `fbi.lifecycle.reader.tracking` ya da los
  contadores por estado y las selecciones con su estado para C-03.


## Cambio de nombre del interruptor (IA-144, 17-nov-2026)

El interruptor del ciclo de una selección se llama ahora `FBI_SELECTION_LIFECYCLE` (y su cadencia `FBI_SELECTION_LIFECYCLE_MINUTES`). Antes compartía `FBI_LIFECYCLE` con el ciclo de los clientes de la capa de lectores (plan UX, B11, encendido por omisión): apagar uno apagaba el otro, y encender la sombra con `shadow` habría dejado encendido el de clientes aunque estuviera en `0`. El ciclo de una selección ya no lee `FBI_LIFECYCLE`; el de clientes no cambia.
