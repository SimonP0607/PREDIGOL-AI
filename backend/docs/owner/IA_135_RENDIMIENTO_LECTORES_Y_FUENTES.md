# IA-135 e IA-136 · Rendimiento de lectores y fuentes, y el banco de repetición como prueba de regresión

Fecha: 17 nov 2026. Piezas AD-K03 (IA-135) y AD-K04 (IA-136) del plan de la arquitectura definitiva 2026. **Sin migración, sin cambios en la
web, sin efecto en el lector.** Nada se entrena ni se promociona; ningún veredicto activa nada; ningún modelo cambia probabilidades. Las dos
piezas solo leen y le dan cifras a usted.

## 1. Rendimiento de lectores y fuentes (AD-K03, `perf-v1`)

**La pregunta.** ¿Qué aporta cada lector de la sombra frente a las reglas, sobre las **mismas** selecciones? Y ¿qué parte de lo que dijo cada
fuente resultó cierto?

**Lectores.** Para cada selección liquidada que juzgaron a la vez las reglas (`rules-review-v1`, su última palabra antes del saque) y un lector
(Partido y Estadísticas por versión; cada brazo del Council, `ma-v1`, `ma-v1-h`, `cs-v1`, por separado), con la postura que guardó la atribución
`attr-v1`:

- *se queda con las reglas* si la palabra de las reglas no es DOWNGRADE ni REJECT (lo que deja pasar el filtro 6 de `decision-v1`);
- *el lector la veta* si su postura es en contra (CONCERN, REJECT_SIGNAL, DOWNGRADE, REJECT);
- **la cifra**: cuánto cambia el valor frente al cierre (CLV) de lo que pasa si a las reglas se les suma el veto del lector, por selección
  examinada. Es la misma medida que la retirada condicionada de `review-v2` (IA-125), para que se puedan comparar.

Veredicto con intervalo por días de Bogotá y corrección de Bonferroni (tantos lectores como lleguen a la muestra): **APORTA** (todo el intervalo
por encima de 0), **RESTA** (todo por debajo), **SIN_DIFERENCIA** (cubre el 0) o **INSUFICIENTE**. Al lado, la atribución con intervalos de
Wilson: aciertos sobre las posturas con lado, posturas hacia el cierre y la parte sin lado (ABSTAIN, NEUTRAL).

**La muestra, calculada antes de mirar.** Para ver un punto de CLV por selección examinada con potencia del 80 % (alfa 5 %, bilateral) y la
dispersión del CLV que midió IA-054 (0,13): **1.327 selecciones examinadas por lector**, en al menos **14 días**, y al menos **30 selecciones
en que el veto cambia algo**. Con menos, INSUFICIENTE y se dice cuánto falta. El lector Jugador no tiene atribución (`attr-v1` no lo lee): sale
INSUFICIENTE con ese motivo.

**Fuentes.** Cada hecho que citó una decisión y que la evaluación posterior `eval-sel-v1` juzgó (sostenido, contradicho o no evaluable), contado
**una vez por hecho**, por fuente (el dominio de su dirección) y tipo (`out`, `starts`, `available`): la parte sostenida con su intervalo de
Wilson, medida desde **30 hechos resueltos** (el mínimo de AD-C08), y si queda por encima o por debajo del resto de fuentes de ese tipo. El CLV
medio de las selecciones que la citan se enseña como descripción, **no como efecto**.

**Cómo se usa.**

```
python -m scripts.ia_reader_performance report --since 2026-10-18 --until 2026-11-17            # lee intel.selection_evaluations
python -m scripts.ia_reader_performance report --since 2026-10-18 --until 2026-11-17 --dry-run  # calcula las evaluaciones sin guardarlas
```

Sesión de solo lectura, 95 s por consulta. El protocolo es `AD-K03` (`proto-ad-k03-v1`), registrado con su huella fijada por una prueba y **sin
firmar**: un veredicto solo cuenta para el aprendizaje controlado (AD-K07) o para la retirada de `review-v2` (AD-D11) cuando usted lo firme y
sobre una ventana fijada antes de mirarla.

## 2. El banco de repetición como prueba de regresión (AD-K04, `replay-regression-v1`)

**Qué cambia respecto del banco (IA-047).** El banco decía PASA si «la repetición cambia lo guardado no más que repetir la misma llamada»: una
regla puntual que una reproducción perfecta pasa poco más de la mitad de las veces. La prueba de regresión usa una **tolerancia fijada antes de
mirar**: un ámbito PASA si el **extremo superior del intervalo del 95 % de la diferencia es ≤ 5 puntos**, con la misma regla de inválidas
(≤ 3 % y ≤ 1 punto sobre las guardadas) y la misma muestra (200 unidades de 30 partidos). La tolerancia es una **propuesta: la firma usted**.

**Con la ejecución del 15-nov** (1.022 preguntas, US$ 2,93; cifras de ese informe, no medidas de nuevo): Council `ma-v1` +2,96 puntos [0,2; 5,7] →
**NO PASA** también con la tolerancia (5,7 > 5); `ma-v1-h` +16,4 [9,6; 23,5] → NO PASA; Partido y Estadísticas → INSUFICIENTE (81 y 39
unidades). Una prueba fija esas cuatro conclusiones.

**Cada NO PASA lleva su causa escrita** (`diag-v1`), de una lista cerrada, partiendo las unidades del ámbito de dos maneras y midiendo cada parte
con la misma regla:

| Causa | Cuándo |
| --- | --- |
| `via_tiempo_real` | las guardadas en tiempo real no pasan y las guardadas por Batch sí (las repeticiones van siempre por Batch) |
| `modelo_distinto` | las repeticiones que respondió un modelo distinto del guardado no pasan y las del mismo sí |
| `validez` | las palabras se reproducen pero las inválidas superan su límite |
| `no_explicada` | ninguna partición lo explica |
| `muestra_insuficiente_para_explicar` | las particiones no llegan a 200 unidades de 30 partidos |

**La regla del protocolo, en el código.** No se repite para cambiar un veredicto: una medida de regresión sobre ejecuciones guardadas que ya usó
otra medida del mismo ámbito no se registra (se dice cuáles se repetían). Una medida nueva usa ejecuciones guardadas nuevas.

**Cuándo se corre.** Ante cada cambio de versión de un lector o del juez del Council (AD-D10): el informe dice qué ámbitos tocan (versión en vigor
frente a la medida). Hoy, por ejemplo, Partido pasó a `match-v6` y Estadísticas a `stats-v5` (IA-123) después del 15-nov: su medida es de las
versiones anteriores.

**Cómo se usa** (no pregunta a ningún modelo ni gasta: juzga lo que el banco ya recogió):

```
python -m scripts.ia_replay_regression check                    # veredicto con la tolerancia, su causa y qué ámbitos tocan
python -m scripts.ia_replay_regression propose                  # la tolerancia como propuesta («umbral», IA-139), sin escribir
python -m scripts.ia_replay_regression propose --write          # la registra, pendiente de su firma
python -m scripts.ia_proposals sign --id N --hash ... --signature "..." --confirm-owner   # SU firma
python -m scripts.ia_replay_regression record --confirm-owner   # anota los veredictos (se niega sin la firma)
```

Los veredictos van a `ai.replay_assessments` (la tabla del banco, solo añadido) con el método `replay-regression-v1` y el protocolo `AD-K04`
(`proto-ad-k04-v1`, huella fijada, sin firmar). Nada los lee para encender o apagar nada.

## 3. Qué no cambia y cómo se revierte

- No cambia ningún agente, prompt, modelo, umbral, peso, interruptor, pick ni la muestra de la sombra. `decision-v1` intacto.
- No hay tarea del worker nueva: son dos órdenes suyas de solo lectura (y la de anotar, que exige su firma).
- Revertir es quitar el código; las filas que se hubieran anotado en `ai.replay_assessments` se conservan.

## 4. Lo pendiente

- Medir en producción (las consultas de solo lectura están preparadas): no se pudo el 17-nov porque el puente al servidor no respondía.
- Firmar los protocolos `AD-K03` y `AD-K04` y la tolerancia de 5 puntos.
- El lector Jugador necesita atribución propia para poder medirse.
