# IA-105 · IA-106 · IA-107 · IA-108 · Evaluación por alineaciones: el ciclo E1–E4 (AD-D06, AD-D07, AD-D08, AD-D03)

Cuatro piezas del plan de la arquitectura definitiva 2026 (responsable: IA; AD-D03 con Modelos), en un solo ciclo, `eval-cycle-v1`:

| Código | Pieza | Qué es |
| --- | --- | --- |
| IA-105 | AD-D06 | El **programador** de las cuatro evaluaciones E1–E4 de cada partido |
| IA-106 | AD-D07 | **E3 por código**: la alineación oficial contra la selección (confirma, mantiene o retira) |
| IA-107 | AD-D08 | Las **alertas privadas** «antes → ahora» del dueño (contrato C-05) |
| IA-108 | AD-D03 | La **dependencia de alineación**: qué jugadores sostienen cada selección y su probabilidad si no juegan, calculada en E1 |

**Todo en sombra. Lo que ve el lector no cambia.** Los pases `first`, `pre` y `final` siguen exactamente igual hasta que el dueño firme su retirada. `decision-v1` no se toca (ni su código ni su tabla), `FBI_PICKS_SOURCE` sigue apagado, nada llega a picks, combinadas ni páginas de lectores. Ningún modelo de lenguaje calcula, sube ni baja nada: todo el ciclo es código. No se baja ningún umbral.

## 1. Por qué

Hoy el pase `final` espera la alineación solo hasta 50 minutos antes del saque: **0 de 1.078** pases finales de 14 días la tenían (medición del 16-nov). Medido ahora (§5), la alineación oficial se ve por primera vez **19 minutos antes del saque** (mediana). Hace falta una evaluación que llegue **después** de la alineación, y tiene que ser de código y rápida: no hay tiempo de deliberar en 19 minutos. Por eso la parte pesada (de qué jugadores depende cada selección) se calcula antes, en E1.

## 2. Las cuatro evaluaciones (IA-105)

| Evaluación | Cuándo | Qué hace |
| --- | --- | --- |
| **E1** | una vez, de 24 a 12 h antes del saque | `decision-v2` decide; se lee la titularidad estimada (IA-094) y se calcula la **dependencia** de cada selección (IA-108). Una selección que depende de la alineación queda **«Pendiente de alineaciones»**, nunca confirmada a ciegas |
| **E2** | por cada hecho nuevo del partido (`ai.evidence`), entre E1 y la apertura de E4 | si el hecho toca una variable del modelo (bajas, dudas, sanciones, alineación) o nombra a un jugador del que depende una selección, se **recalcula**; si no, solo se **anota**. Un mismo hecho nunca dispara dos E2 (una clave única en la base) |
| **E3** | al llegar la alineación oficial (llegadas de IA-069, o la hoja guardada), solo código, en menos de 2 min | §3 |
| **E4** | una vez, de **T-20 a T-10** | se **relee el partido** (hora, estado y sede, con la relectura de IA-061) y se juzga cada selección con la última decisión y la alineación que haya |

**Nota sobre E4 (decisión pendiente del dueño).** La ficha dice T-5. Por debajo de 10 minutos `decision-v1` rechaza todo por regla («menos de 10 min al saque», `MIN_MINUTES`), y `decision-v2` hereda esa regla. **No se baja.** Por eso E4 va de T-20 a T-10, igual que hizo IA-093. Una alineación que llegue después de E4 (en la medición, 49 de 873 partidos entre T-10 y el saque) **sí** tiene su E3: sin decisión nueva, con la última decisión y el **precio leído otra vez**.

**Entre evaluaciones**, cada pasada relee el partido: un saque adelantado o retrasado, un aplazamiento, una suspensión o un cambio de sede después de E1 es una alerta en minutos, no un hallazgo de auditoría días después (el incidente del 12-nov).

Cada evaluación guarda **su versión** de `decision-v2` (`intel.decisions_v2`, con su evaluación y número de versión) y su paso en el **ciclo de estados** con el escritor propio `eval-cycle-v1` (por la API del ciclo, IA-068).

## 3. E3 por código (IA-106)

Al llegar la alineación oficial, para cada selección:

1. **La alineación**: los titulares oficiales contra los jugadores de los que depende (tabla de E1). Se suma el efecto de cada uno: el que no es titular resta lo calculado «sin él»; el que es titular suma lo calculado «jugando de titular».
2. **La decisión**: si quedan 10 minutos o más, `decision-v2` decide otra vez (con el precio del libro en vigor y su edad); si no, vale la última decisión y solo se **relee el precio**.
3. **El valor a ese precio**: con la cifra ajustada por la alineación, el valor esperado y la ventaja se miden con los **mismos mínimos de `decision-v1`** (EV ≥ 2 %, ventaja ≥ 1 punto; importados, no se bajan).

Resultado, con **una** causa:

| Resultado | Cuándo |
| --- | --- |
| **Confirmada** | estaba pendiente de la alineación y todo se sostiene |
| **Sigue igual** / **Modificada** | estaba confirmada y se sostiene (modificada si la cifra se mueve medio punto o el precio una centésima) |
| **Retirada** | estaba pendiente o confirmada y: la nueva decisión está en contra, el precio está antiguo o no hay, la alineación está en contra (un jugador del que depende no es titular y se pierde el valor: `alineacion_en_contra`) o se pierde el valor al precio nuevo |
| **Pendiente** | todavía no se conoce la alineación del lado que importa: **un fallo o una ausencia de E3 nunca confirma** |

Una selección que no estaba confirmada solo puede confirmarse si la nueva decisión la aprueba y mantiene el valor con la alineación. Al saque, lo confirmado pasa a «En juego» y lo demás se cierra: lo que seguía esperando la alineación, como **«Descartada: sin alineación a tiempo»**.

## 4. La dependencia de alineación (IA-108)

Tres grupos de mercados:

| Grupo | Mercados | ¿Espera la alineación? |
| --- | --- | --- |
| `siempre` | los del propio jugador (remates, tiros a puerta, goles, asistencias, tarjeta, paradas) | siempre: sin alineación, «Descartada: sin alineación» |
| `si_dependencia` | 1X2, doble oportunidad, empate no válido, hándicaps, más/menos, ambos marcan, goles de un equipo; tarjetas | solo si un jugador del que depende está **en duda** |
| `no_espera` | córners | no |

**Los números** (ninguno de un modelo de lenguaje). Los mercados de goles salen de **una matriz de marcadores** reconstruida con las siete filas guardadas del modelo de goles (IA-074). Los goles esperados de cada equipo se reparten entre sus jugadores según su tasa de goles por 90 y sus minutos esperados (`player-engine-v1` con la titularidad estimada `lineup-estimate-v1`). Si un jugador **no juega**, sus minutos los cubre un sustituto con la tasa de su posición en su equipo; si **es titular seguro**, juega sus minutos de titular. Con esos goles esperados se rehace la matriz y se lee la selección. Se guarda el **cambio** que da la matriz, sumado a la cifra que juzgó la decisión.

Reglas fijadas **antes de medir** (17-nov-2026): un jugador entra en la lista si mueve la selección **2 puntos o más**; está **en duda** si su probabilidad de ser titular está entre 10 % y 90 %, o su disponibilidad dice «duda»; como mucho 6 jugadores por selección. **Tolerancia preregistrada** entre consultar la tabla y recalcular desde cero: **1 punto**.

**Límite de la v1, dicho claro.** Solo mide el **ataque**: la baja de un defensa o del portero no cambia los goles del rival (el motor de jugadores no tiene una tasa de «goles evitados»). Las tarjetas no tienen matriz: su fila dice `sin_matriz` y no esperan.

Ejemplo del Doc 1, comprobado en prueba: 1,0 tiro a puerta por 90 da **63,2 %** jugando entero y **53,7 %** con un 85 % de titularidad (el Doc 1 dice 53 %, redondeado hacia abajo).

## 5. Lo que se midió en producción (solo lectura, 17-nov-2026)

| Medida | Resultado | Muestra y fuente |
| --- | --- | --- |
| Llegada de la alineación (primera vez que se vieron los dos onces) | mediana **19,4 min** antes del saque; p10 18,8; p25 19,1; p75 22,7; p90 29,1 | 873 partidos seguidos terminados de 14 días (3 a 17-nov) con los dos onces vistos antes de T+5, de 1.187; respuestas RAW de `/fixtures` (lecturas previas y seguimiento en vivo), leídas sin red en la imagen del worker |
| Por franjas | 20–30 min: 315; 10–20: 498; **0–10: 49**; después del saque: 11; antes de T-30: 0 | ídem |
| Ligas / copas | 634 de 640 / 228 de 233 antes del saque; mediana 19,4 / 19,5 min | ídem (los partidos sin los dos onces vistos: 111 de liga y 203 de copa) |
| Titular corregido después de la primera llegada y antes del saque | 16 partidos | ídem |
| Partidos con llegada en la misma franja de 2 minutos | mediana 1; p90 7; p99 18; **máximo 27** | 305 franjas con al menos una llegada |
| Selecciones a reevaluar por franja de 2 min (con los candidatos de `decision-v1` en su punto «alineaciones») | mediana 3; p90 12; máximo 28 | 384 partidos con ese punto en 14 días; 2 selecciones por partido de mediana, 7 como máximo |
| Tabla de llegadas `core.fixture_lineup_arrivals` (IA-069) y `first_seen_at` | **0 filas** y 0 de 558 alineaciones con `first_seen_at` (producción en la migración 0141 el 17-nov) | por eso E3 también sabe leer la hoja guardada |

**La resolución de la medida es de unos 10 minutos**: la lectura previa de hoy pregunta cada 10 minutos en los últimos 75 y se para al tener los dos onces. Con el sondeo de IA-069 encendido (cada 3 minutos) se medirá mejor.

**¿Cuántas E3 caben en menos de 2 minutos?** E3 corre cada 60 segundos. En la prueba de integración local, una E3 completa (leer la alineación, decidir, juzgar y escribir) tarda **16–18 ms** por partido con precio de consenso. En producción, con el precio del libro (lectura de cuerpos RAW), **no está medido**. Con la peor franja medida (27 partidos que llegan en los mismos 2 minutos), cumplir el criterio exige menos de unos **2,2 s por partido** de media (60 s de margen sobre la cadencia de 60 s, repartidos entre 27). Se verá en `eval_runs.latency_ms` desde el primer día en sombra.

## 6. Qué guarda (migración 0156, cinco tablas de solo añadido)

| Tabla | Qué guarda |
| --- | --- |
| `intel.eval_runs` | cada evaluación de un partido: cuál y su versión, por qué corrió (ventana, hecho nuevo, alineación oficial, corrección), la clave que impide repetirla, el momento leído, el saque de entonces, cuándo se conoció lo que la disparó y cuándo terminó (`latency_ms`), el momento de `decision-v2` en que decidió, la relectura del partido (E4) y la alineación vista (E3). Una evaluación que falla queda como `fallida` (solo la clase del error) y puede reintentarse (hasta 3 veces) |
| `intel.eval_facts` | cada hecho nuevo que miró E2, **una sola vez**: recalcula o anota, y por qué |
| `intel.lineup_dependencies` | la dependencia de cada selección (grupo, estado, si espera, jugadores con su cifra «sin él» y «de titular», la matriz usada) |
| `intel.eval_verdicts` | lo que cada evaluación hizo con cada selección (estado y motivo del ciclo, cifra y precio antes y ahora, efecto de la alineación, veredicto anterior) |
| `intel.private_alerts` | las alertas «antes → ahora», cada una una vez |

Además amplía el CHECK de `trigger` de las dos tablas de `decision-v2` (IA-093) a `E2` y `E3`. No cambia ninguna fila.

## 7. Las alertas privadas (IA-107)

Cuatro clases, siempre con el dato de **antes** y el de **ahora**:

- **Retirada**: una selección pendiente o confirmada se retira (estado, cifra y precio antes y ahora, jugadores que no son titulares, causa).
- **Sin alineación**: llegó E4 y no ha llegado la alineación que espera la selección (qué lados faltan, minutos al saque).
- **Cambio de horario**: el saque se adelantó o retrasó.
- **Cambio de condiciones**: aplazado, cancelado, suspendido, ya empezado o cambio de sede.

Las sirve **solo** el contrato **C-05** en `GET /api/v1/admin/intelligence/alerts` (con `require_admin`; `hours`, `fixture_id`, `kind`), con dos ejemplos en `tests/fixtures/contracts/intelligence/C-05/`. **Nunca hay aviso al lector**: `notifies_reader` es siempre falso y ninguna pieza de avisos, mensajes o lectores importa el ciclo (una prueba lo comprueba). Sin datos médicos: una baja es un estado, una fuente y una fecha. La consola (C-11) sigue diciendo «no entregado» en su cola de alertas: conectarla es de AD-J06/UX.

## 8. Pruebas

- **Unitarias** (`tests/unit/test_eval_cycle.py`, `test_eval_cycle_isolation.py`): ventanas iguales a las de IA-093 e IA-094 y E4 parado en el umbral de 10 min; **reloj simulado** (saque adelantado, sin alineación, alineación a T-75 con corrección a T-30: cada evaluación una vez y E3 dentro de 2 min); un hecho no dispara dos E2; el ejemplo del Doc 1; los tres grupos; consulta frente a recálculo dentro de 1 punto; casos fijos de E3 (titular clave fuera, alineación como la estimada, precio antiguo, sin alineación); la cadena de estados legal y cerrada; aislamiento (E3 y la dependencia sin cliente de modelos; nada de avisos, mensajes, clientes, API pública, picks ni decisión importa el ciclo; solo escribe sus cinco tablas con INSERT; el worker solo lo programa en `shadow`).
- **Integración** en PostgreSQL 16 local (`test_eval_cycle_shadow.py`, `test_migration_0156_eval_cycle.py`): **un partido entero E1 → E2 → E3 → E4** con cambio de alineación que **retira** la selección y genera la **alerta privada**, latencia de E3 menor de 2 min, la cadena `eval-cycle-v1` legal y cerrada, `intel.decisions` sin mover; la alineación con el delantero **confirma**; sin alineación, alerta en E4 y cierre «sin alineación a tiempo»; saque adelantado, una alerta y nada después del saque; E3 leyendo la llegada del sondeo desde su respuesta RAW; la migración sube, rechaza lo que debe y baja limpia.

## 9. Cómo se activa en sombra (tras desplegar)

1. La migración 0156 la aplica el despliegue.
2. En el worker: `FBI_EVAL_CYCLE=shadow` (por defecto `off`; cualquier otra palabra es `off`). Cadencias: `FBI_EVAL_CYCLE_MINUTES` (5 por defecto, 1–10) y `FBI_EVAL_CYCLE_E3_SECONDS` (60 por defecto, 30–120). Reiniciar el worker.
3. Recomendado a la vez: `FBI_LINEUP_ESTIMATE=shadow` no hace falta (E1 lee la titularidad por su cuenta con la misma función), pero sí **`FBI_LINEUP_WATCH=shadow`** (IA-069) para ver la alineación cada 3 minutos en lugar de cada 10. Si `FBI_DECISION_V2=shadow` también está encendido, basta con `FBI_DECISION_V2_TRIGGERS=mirror`: E1 y E4 del ciclo adoptan el momento que ya guardó ese pase, así que nada se decide dos veces de ninguna manera.
4. Comprobar: `intel.eval_runs` (por evaluación, `status`, `latency_ms` de E3), `intel.private_alerts` (o la ruta C-05) y las cadenas `writer = 'eval-cycle-v1'` de `intel.selection_lifecycle`.

## 10. Cómo se apaga y se revierte

`FBI_EVAL_CYCLE=off` y reiniciar el worker: no se programa ningún trabajo del ciclo; las filas guardadas se conservan; los pases `first`/`pre`/`final`, `decision-v1` y todo lo del lector siguen como estaban. La migración 0156 tiene bajada (borra las cinco tablas y deja el CHECK de `decision-v2` como estaba, `NOT VALID`, sin tocar sus filas).

## 11. Lo pendiente

- **E4 a T-5** frente a la regla de 10 min de `decision-v1` (decisión del dueño).
- Medir en sombra el **p95 de latencia de E3** con el precio del libro y el **100 %** de partidos con E1 y E4 (criterio de AD-D06).
- La dependencia v1 no mide defensas ni porteros, ni tarjetas; los mercados de jugador (`siempre`) aún no son candidatos de `decision-v2` (llegarán con AD-E04).
- La retirada de los pases `first`/`pre`/`final` la firma el dueño; esta pieza no la hace.
- Conectar la cola de alertas de la consola (C-11) y la vista privada (AD-J06, sesión UX).
