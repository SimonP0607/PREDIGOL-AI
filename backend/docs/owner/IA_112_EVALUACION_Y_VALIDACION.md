# IA-112 / IA-113 · Evaluación posterior única y tablero de validación (AD-K01, AD-K02)

Piezas AD-K01 y AD-K02 del plan de la arquitectura definitiva 2026. Todo en **sombra**: nada llega al lector, nada decide, nada se
promociona solo y ningún modelo de lenguaje da un veredicto.

## 1. Qué hace

**Una sola evaluación por selección (`eval-sel-v1`, AD-K01).** Hoy una selección se juzga después del partido en cinco sitios que no
comparten fila: el post-mortem por decisión (pm-v6, `intel.postmortems`), el de las familias (pm-fam-v1, `intel.family_postmortems`), la
revisión del partido (`intel.match_postmortems`), la revisión diaria (`ai.daily_reviews`) y la de la crónica (`ai.chronicle_reviews`). La
pieza nueva escribe, por código, **una fila por selección y versión** en `intel.selection_evaluations` (migración 0158, solo añadido) con
las preguntas del Doc 1:

| Pregunta | Cómo se responde |
| --- | --- |
| ¿Qué anticipamos y qué pasó? | La probabilidad que juzgó la decisión que quedó en pie (la última al menos 10 min antes del saque), con su sello (`calibrada` / `sin_calibrar`), la del mercado sin margen del mismo momento y el resultado de la liquidación de registro (`settle-v4` vía `intel.decision_outcomes`). Con resultado completo (ganada o perdida), log loss y Brier de las dos. Media ganada, media perdida, devuelta o nula: se cuentan, no se puntúan |
| ¿Fue buen precio? | El CLV de siempre (`clv-v1`), la calidad del precio (BUENO > +1 %, MALO < −1 %) y el veredicto calidad × resultado del post-mortem: MERECIDO, SUERTE, VARIANZA, ERROR, NULO, SIN_DATOS. **Un acierto no valida el mercado**: ganar con un precio malo es SUERTE |
| ¿Qué evidencia acertó o falló? | Cada hecho que citó la decisión queda **sostenido**, **contradicho** o **no evaluable** según lo que el proveedor dice que hizo el jugador: una baja se sostiene si no jugó; un titular, si fue titular; un convocado, si estuvo en la convocatoria. Una duda, una noticia o un dato del entrenador no tienen regla. Sin el identificador del jugador del proveedor, o sin la alineación oficial, no se juzga: **nunca se empareja por nombre** |
| ¿Cambió algo la alineación? | Si la decisión cambió al conocerse la alineación oficial (la última decisión antes de ella frente a la que quedó en pie, y cuántos puntos se movió su probabilidad) y cuántos titulares estimados (AD-D04) fueron titulares |
| ¿Se cumplió el escenario? | No se juzga en `eval-sel-v1`: el motor de escenarios (AD-B02) aún no guarda una lectura por selección |

Cada fila dice además si la capa **tomaría** la selección (`taken`: confirmada en sombra por el ciclo de estados, es decir aprobada, o
aparcada solo por la validación de su mercado) y su **paridad** con `intel.decision_outcomes`: el resultado se vuelve a calcular con
`settle-v4` desde el marcador y el CLV desde la probabilidad de cierre guardada; `igual`, `difiere` (con el motivo) o `sin_referencia` (la
capa no guarda liquidación: decision-v2).

**El tablero de validación (`board-v1`, AD-K02)** se calcula sobre esas evaluaciones, por capa, familia y mercado, y por familia completa,
con el **protocolo preregistrado `AD-K02`** (`proto-ad-k02-v1`, huella fijada por prueba en `tests/unit/test_research_protocols.py`):

- **Población:** solo las selecciones que la capa tomaría. Un mercado se valida por lo que publicaría, no por todo lo que miró; cada celda
  dice además cuántas candidatas tuvo.
- **Muestra necesaria:** 300 selecciones con resultado completo, probabilidad del mercado y cierre (el mínimo de la vara INT-A10).
- **Tres reglas, las tres a la vez:** (1) log loss medio menor que el del mercado (extremo superior del intervalo < 0); (2) ECE ≤ 0,03 en
  10 tramos; (3) CLV medio por encima de la vara de la regla de precio: el extremo inferior de su intervalo debe superar **+6,24 %** (la
  regla de precio dio +5,77 % [5,28; 6,24] en 2.705 selecciones, IA-054).
- **Intervalos:** bootstrap de días de Bogotá enteros, 2.000 réplicas, semilla del protocolo, al nivel corregido de **Bonferroni**
  (1 − 0,05/m, con m las celdas y familias que alcanzan la muestra).
- **Veredicto:** INSUFICIENTE por debajo de 300; con la muestra, VALIDADO solo si se cumplen las tres; NO VALIDADO en otro caso, diciendo
  cuál falló. Una regla que no se pudo medir cuenta como fallo, nunca como acierto.

## 2. Qué se midió en producción (solo lectura)

17-nov-2026, 07:51 y 07:57 UTC, dentro de `predigol-worker`, en una sesión de solo lectura (`default_transaction_read_only = on`, 95 s
por sentencia), con el código de esta rama cargado en memoria (la tabla nueva no existe aún en producción: se calculó **en seco**, sin
escribir). Ventana: partidos con saque del 18-oct al 15-nov de 2026 (días de Bogotá). La carpeta temporal del servidor se borró.

| Medida | Cifra |
| --- | --- |
| Partidos con decisión | 2.804 |
| Selecciones liquidadas evaluadas | **37.739** (decision-v1 31.593; decision-fam-v1 6.146); 0 fallos; 48–56 s |
| No evaluadas aún | 379 sin liquidar, 85 sin cuota, 1 sin decisión antes del saque |
| Resultados | 12.867 ganadas, 20.612 perdidas, 1.281 medias ganadas, 1.425 medias perdidas, 1.314 devueltas, 240 nulas |
| Veredicto calidad × resultado | ERROR 17.979 · SUERTE 11.456 · VARIANZA 4.058 · MERECIDO 2.692 · NULO 1.554 (todas con cierre) |
| Sello de la probabilidad juzgada | 31.529 `calibrada`, 6.210 `sin_calibrar` (las familias) |
| Paridad con `intel.decision_outcomes` | **37.583 iguales, 156 distintas**, todas en el resultado de decision-v1 |
| Hechos citados | 35.070: 1.999 sostenidos, 63 contradichos (una baja que jugó), 33.008 no evaluables (22.159 sin identificador del jugador; 7.461 sin regla; 3.371 dudas; 17 sin minutos) |
| Efecto de la alineación | **No medible hoy**: `core.fixture_lineup_arrivals` tiene 0 filas y `first_seen_at` está vacío (0 de 192 alineaciones del 14-nov); `fetched_at` es la última lectura, posterior al partido, y no se usa como primera vista |
| Selecciones que la capa tomaría | **0 de 37.739**: decision-v1 no aprobó ninguna (24.301 de sus decisiones en pie se quedaron en «valor insuficiente») y las familias quedaron «sin calibrar» |

**Las 156 diferencias, explicadas en una muestra de 40 (9 partidos):** 32 son partidos **aplazados** que la liquidación dejó nulos a las
72 h del saque original (`settle-v3`) y que luego se jugaron (7 partidos; en toda la ventana hay 17 partidos con 341 liquidaciones
anteriores al saque real); 8 son **correcciones del marcador** del proveedor en 2 partidos (21389 y 21497, re-liquidados el 9-nov en
`picks.resettlements`): `intel.decision_outcomes` no se reescribe por diseño, y la evaluación guarda la liquidación de registro y dice
cuál daría hoy.

**El tablero:** 24 celdas (capa × familia × mercado y cada familia completa), **24 INSUFICIENTE, con muestra 0 de 300**, 0 VALIDADO,
Bonferroni m = 0. Ningún mercado tiene hoy selecciones que la capa tomaría.

**Contexto, no veredicto** (la misma medida sobre **todas** las candidatas, primer cálculo de la misma sesión): en el núcleo de
decision-v1 (27.333 selecciones completas) la probabilidad está bien calibrada (ECE 0,0097) pero no pronostica mejor que el mercado
(log loss +0,0011 por selección frente al mercado, intervalo que incluye el 0) y la candidata media a su mejor cuota pierde frente al
cierre: CLV −6,0 % (1X2 −3,8 %, hándicap −5,7 %, ambos marcan −4,8 %, doble oportunidad −5,4 %, más/menos −7,2 %). Las familias están peor
calibradas (ECE de 0,05 a 0,13 por mercado) y también por debajo del mercado. Es lo esperable con 0 aprobaciones: cuando decision-v1 o
decision-v2 aprueben, el tablero juzgará exactamente esas selecciones.

## 3. Qué cambia (código)

- `src/fbi/evaluation/` (nuevo): `selection.py` (la evaluación, pura), `reads.py` (lo que lee, solo lectura), `store.py` (la pasada en
  sombra y la ejecución en seco), `board.py` (el tablero, puro), `views.py` (lecturas del dueño).
- `migrations/versions/0158_selection_evaluations.py`: la tabla, solo añadido, con sus comprobaciones (decidida antes del saque, un acierto
  solo sobre un resultado completo, veredicto coherente con el resultado, una evaluación por selección y versión).
- `src/fbi/research/protocol.py`: el protocolo `AD-K02`.
- `src/fbi/shadowjobs/selection_eval.py` y `apps/worker/scheduler.py`: la tarea `selection_eval_shadow`, cada 60 min, solo con
  `FBI_SELECTION_EVAL=shadow`.
- `scripts/ia_selection_eval.py`: `dry-run` y `board` para el dueño, en solo lectura.
- Dos lectores nuevos de `ai.evidence`: el pase (`evalpass/reads.py`) y lo que lee C-02 (`evaluation/sources.py`, que recibe la respuesta de `gates.typed_visible` de quien lo llama), con la pregunta de siempre; `IA_FASE2.md` los cuenta. El pase va en su propio paquete (`fbi.evalpass`) para que la API, que lee `fbi.evaluation`, no entre en el ciclo de importaciones.

## 4. Qué no cambia

- Los cinco escritores del «después» siguen escribiendo igual (se retirarán uno a uno en AD-K06). `intel.decision_outcomes`,
  `decision-v1`, `FBI_PICKS_SOURCE`, los umbrales, los picks, los agentes y los interruptores del lector, intactos.
- Un veredicto del tablero **no activa nada**: ningún interruptor, umbral, modelo ni pick lo lee. Solo lo leen las vistas privadas (C-02,
  C-03) y el comando del dueño. El protocolo está registrado, **sin la firma del dueño** (`signed_by_owner: false`).

## 5. Cómo se enciende y cómo se apaga

- Tras desplegar (con la migración 0158), en el entorno del worker: `FBI_SELECTION_EVAL=shadow` (por defecto `off`: ni se programa). La
  primera pasada evalúa los siete últimos días.
- Medir sin escribir: `docker exec -w /app predigol-worker python -m scripts.ia_selection_eval dry-run --since 2026-10-18 --until 2026-11-16`.
- Tablero sobre lo guardado: `... ia_selection_eval board --since ... --until ...`.
- Apagar: quitar la línea o `FBI_SELECTION_EVAL=off`. Las filas se quedan (solo añadido); revertir el PR y bajar la migración borra la
  tabla y nada más.

## 6. Pendiente

- Firma del dueño del protocolo `AD-K02` (AD-K07); hasta entonces ningún veredicto cuenta para el aprendizaje.
- Efecto de la alineación: necesita el registro de llegadas (IA-069, `FBI_LINEUP_WATCH`) encendido.
- Hechos de la web sin identificador del jugador (22.159): necesitan la clave única del jugador (IA-071) en esas filas.
- decision-v2 (IA-093) entra solo, con su liquidación por `settle-v4`, el día que su sombra guarde decisiones.
