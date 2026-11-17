# IA-109 · IA-110 · IA-111 · Seguimiento de selecciones, `parlay-v6` y cálculo de picks más ligero

Tres piezas del bloque E del plan de la arquitectura definitiva 2026 (responsable: IA):

| Código | Pieza | Qué es |
| --- | --- | --- |
| **IA-109** | AD-E05 | Seguimiento y liquidación de las selecciones sueltas de la sombra: **En juego → Liquidada → Evaluada**, con `settle-v4` |
| **IA-110** | AD-E06 | Constructor **`parlay-v6`**: tramos confirmados por sí mismos, **máximo 3**, probabilidad conjunta por simulación, margen acumulado a la vista, **ninguno si nada cumple** (decisión 6 del dueño) |
| **IA-111** | AD-E08 | El cálculo de picks en sombra deja de recorrer cada pasada todo el histórico de precios, **sin cambiar ninguna fila** |

**Todo en sombra. Lo que ve el lector no cambia.** `parlay-v5` sigue siendo lo publicado y su histórico no se toca; `picks.parlays` y su clave `(kind, day, source)` siguen igual; `settle-v4` sigue liquidando los picks como hoy; `decision-v1` no se toca; `FBI_PICKS_SOURCE` sigue apagado. Ningún modelo de lenguaje calcula nada de esto. Los tres interruptores nacen apagados.

## 1. IA-109 · Seguimiento de selecciones sueltas (AD-E05)

**El problema.** Una combinada de PrediGol se sigue hasta el final (en construcción → lista → en juego → ganada/perdida). Una selección suelta de la sombra no: `decision-v2` en sombra (IA-093) lleva su cadena del ciclo de estados (IA-068) hasta **«En juego»** en el saque, y ahí se quedaba, porque `decision-v2` no tiene liquidación propia.

**Qué hace.** Un trabajo del worker, `selection_settle_shadow` (cada 15 min, `FBI_SELECTION_SETTLE=shadow`; apagado por omisión), que para las cadenas de `decision-v2` (escritor `decision-v2-shadow-v1`) cuyo partido empezó en los últimos 10 días:

1. lee el partido tal como lo lee la liquidación (estado, resultado de los 90 minutos, prórroga, el saque para el que se tomó la selección);
2. aplica **la misma regla** que liquida los picks (`settle-v4`: resultado de 90 minutos; cancelado = nulo; sin resultado oficial 72 h después del saque = nulo);
3. guarda cada liquidación como **una fila nueva** en `intel.selection_settlements`:
   - **primera**: el resultado, su base y el marcador con el que se leyó;
   - **corrección**: si el proveedor corrige el marcador y cambia el resultado, una fila nueva que nombra la que sustituye (nada se reescribe). Lo que la reliquidación de los picks deja «para una persona», el seguimiento también lo deja: un nulo por regla se mantiene aunque luego llegue resultado; un resultado leído en un marcador no lo deshace un partido que ahora aparece cancelado o aplazado (probado caso por caso contra `resettlement.judge`);
   - **firme**: pasados 7 días (la ventana en la que la reliquidación sigue leyendo correcciones), el resultado queda firme con **el precio tomado, el último precio sin margen antes del saque y el valor frente a él** (CLV). Esa es la «evaluación» de la selección.
4. mueve la cadena del ciclo **por su API**: «En juego» → **«Liquidada»** (con el primer resultado) → **«Evaluada»** (con la fila firme). Una corrección no mueve la cadena (el ciclo no tiene paso de «Liquidada» a sí misma): su rastro es la fila de liquidación.

Las patas de `parlay-v6` se liquidan **siempre**, aunque su cadena se retirara antes del saque (la combinada se congela al construirse, como las de `parlay-v5`); en ese caso solo se guarda la liquidación, la cadena no se mueve.

**«Cómo se liquida» en palabras llanas** (para el contrato C-02): `how_it_settles` da una frase por selección, por ejemplo: *«Gana si hay más de 2,5 goles en total (sin devolución posible); en otro caso pierde. Se liquida con el resultado de los 90 minutos más el añadido; la prórroga y los penaltis no cuentan. Si el partido se cancela, o si 72 horas después del saque previsto no hay resultado oficial (aplazado, suspendido, interrumpido o abandonado), la selección se anula y se devuelve lo apostado.»* Las líneas partidas (.25/.75) y el hándicap asiático tienen su frase. Un mercado sin regla de `settle-v4` lo dice en vez de inventar.

**Qué no cambia.** `settle-v4`, `picks.pick_results`, la reliquidación y las cadenas de `decision-v1` (`lifecycle-shadow-v1`, que se liquidan con `intel.decision_outcomes` como hasta ahora) no se tocan.

## 2. IA-110 · `parlay-v6` (AD-E06)

**El problema** (medición del 16-nov-2026): `parlay-v5` perdió 66 de 67 combinadas liquidadas, con cuota combinada media de 26,9 (diarias) y 45,1 (varios días); sus tramos acertaban el 38,9 % cuando el modelo les daba el 58 % (n = 257 tramos).

**La regla `parlay-v6`:**

- **Un tramo** es una selección **confirmada en sombra por sí misma** (la última fila de su cadena es «confirmada en sombra»). Además: que no empiece en menos de 10 minutos; una línea **sin devolución posible** (1X2, doble oportunidad, ambos marcan, líneas .5 de goles y de hándicap: un nulo dentro de una combinada no tiene un sentido limpio); precio de **al menos 3 casas** («una sola casa» nunca confirma); probabilidad con su extremo pesimista; y valor a su propio precio. Nunca se añade un tramo para completar.
- **Una combinada** tiene **2 o 3 tramos** (3 por defecto, que es el máximo; la base de datos rechaza más), como mucho 2 del mismo partido y nunca el mismo equipo en dos partidos. La de varios días abarca dos días.
- **La probabilidad conjunta, por simulación** (100.000 escenarios, semilla fija por tramos: los mismos tramos dan siempre la misma cifra): cada tramo con su propia probabilidad, y entre dos tramos la dependencia de la **correlación única `corr-v2`** (IA-098): del **mismo partido**, la de su **matriz de marcadores** (IA-074) —p. ej. «más de 2,5» y «ambos marcan» juntos salen ~1,5 veces el producto—; **entre partidos**, la medida sobre resultados solo cuando puede bajar la conjunta: una dependencia positiva o sin medir **nunca la sube**. Un par que `corr-v2` no puede combinar (mismo partido sin matriz, mismo equipo) no forma combinada.
- **La elección**, como `parlay-v5`: por el crecimiento esperado de una apuesta del 1 % con la conjunta **pesimista**; un tramo entra solo si hace crecer la combinada.
- **Lo que muestra**: cuota combinada, conjunta y su error de simulación, conjunta pesimista, producto de tramos, conjunta del mercado, **cuota justa** (1/conjunta), **margen acumulado** (1 − cuota × conjunta del mercado: lo que se quedan las casas de media, que crece con cada tramo) y valor esperado.
- **Ninguna** si nada cumple, con su motivo: `sin_candidatos`, `un_solo_candidato` o `ninguna_combinacion_cumple`. Los días sin combinada quedan registrados como tales.

**Dónde se guarda** (migración **0157**, tablas nuevas de solo añadido): `intel.parlays_v6` (una fila por escritor, regla, tipo y día: la combinada o «ninguna») y `intel.parlay_v6_legs` (los tramos, cada uno con la fila del ciclo que lo confirmó). La clave única `(kind, day, source)` de `picks.parlays` impedía guardar `parlay-v6` el mismo día que `parlay-v5`: por eso es una tabla propia y **ni la clave ni las filas de `picks.parlays` se tocan**. El resultado de una combinada se lee de las liquidaciones de sus tramos (IA-109): ganada, perdida, nula parcial o nula; nunca se escribe dos veces.

**Trabajo del worker**: `parlay_v6_shadow`, cada 15 min, `FBI_PARLAY_V6=shadow` (apagado por omisión).

PrediGol no es una casa de apuestas: nada de esto acepta depósitos, paga por adelantado ni ofrece bonos. La incertidumbre se acumula con cada tramo (referencia del plan: retención del 18,7 % en combinadas en Nueva Jersey, 2025, cifra de regulador sin auditar).

### Medición: 14 días de `parlay-v6` frente a `parlay-v5` (producción, solo lectura, 17-nov-2026)

Días de producto (Bogotá) del 3 al 16 de noviembre. En producción **no** están todavía ni el ciclo de estados (0142) ni `decision-v2` en sombra (0150): la producción está en la migración 0141. Por eso «confirmada en sombra» se reconstruyó con el mapa del ciclo (`lifecycle-map-v1`) sobre las decisiones de `decision-v1` (aprobadas, o en investigación solo por `edge_not_validated`): **109 selecciones** lo estuvieron en algún momento. Se repitió el constructor en cada momento de decisión y cada 15 minutos (1.705 momentos), sin matrices de marcadores (en la repetición, dos tramos del mismo partido no se combinan).

| | `parlay-v5` (lo publicado) | `parlay-v6` (repetición) |
| --- | --- | --- |
| Diarias construidas | 13 (12 perdidas, 1 ganada) + 1 día sin combinada | **5** (5 perdidas) + **9 días sin combinada** (5 «ninguna combinación cumple», 2 «un solo candidato», 2 «sin candidatos») |
| Varios días construidas | 13 (13 perdidas) + 1 sin combinada | **1** (perdida) + **13 sin combinada** (11 / 2 / 0) |
| Tramos por combinada | 86 tramos en 26 (3,3 de media) | **2** en las 6 |
| Cuota combinada media | 16,9 (diarias) y 27,0 (varios días) | **4,9** |
| Conjunta frente a resultado | — | 6 liquidadas, suma de conjuntas 1,38, **0 ganadas**; 5 de sus 12 tramos ganaron |

**Lectura honesta.** `parlay-v6` construye mucho menos (6 frente a 26) y con cuotas cinco veces más bajas, que es lo que pide la decisión 6. **Seis combinadas no dicen nada sobre su calibración** (esperaba 1,4 aciertos; tuvo 0: con n = 6 eso es compatible con estar bien calibrada). La calibración se juzgará con al menos 100 combinadas liquidadas (`calibration` lo avisa). Hallazgo: en 51 momentos un candidato se rechazó por línea con devolución.

## 3. IA-111 · Cálculo de picks en sombra más ligero (AD-E08)

**Qué se midió** (producción, solo lectura, 17-nov-2026):

- `pick_pipeline`: **1.324 pasadas** en 14 días (3–17 nov), mediana **667 s**, p90 931 s; medianas diarias del 12 al 16 de noviembre entre 517 y 608 s.
- Cada pasada recorre **todos los instantes de precio de la historia** (`evaluate_captures` sin `since`): **23.905** instantes el 17-nov; el **94 %** son de partidos que empezaron hace más de 3 días. Solo **176** (0,7 %) caen en la ventana de 24 h antes de la última pasada.
- En 14 días, de **500.119 candidatos** escritos, **0** se escribieron más de 2 horas después de su instante de precio (p99: 24 minutos); 3 después del saque y ninguno más de 6 h después. Es decir: el recorrido de los instantes viejos no produce nada.
- Coste de leer los instantes (las mismas cuatro consultas por instante que hace la pasada, cronometradas en una sesión de solo lectura): **65,6 ms por instante** en una muestra de 400 instantes de toda la historia, frente a **3,5 s en total** para los 176 de la ventana; la consulta que lista los instantes, **18,7 s** (todos) frente a **2,8 s** (ventana).
- No se puede atribuir con exactitud qué parte de los ~600 s es este recorrido: el texto de las consultas del worker no es visible para el rol de lectura. Por el número de llamadas registradas (unos 10,5 millones por consulta desde el 9-nov, compatible con una por instante y pasada en 711 pasadas) y su tiempo medio, el recorrido se estima en **~300 s por pasada** (hipótesis, no medición). Con la ventana bajaría a segundos, y la pasada a ~300–350 s. **El tiempo real se medirá con el modo `window` encendido** (duración de cada pasada en `raw.ingestion_runs`).

**Por qué no «evaluar solo lo que `decision-v2` considera»** (lo que decía la ficha): `decision-v1`, que está protegido, lee **`picks.picks`** como su lista de candidatos y **`picks.pick_line_value`** para su CLV por tipo de pick. Crear menos picks cambiaría las entradas de `decision-v1`. Por eso esta pieza no quita ningún pick: quita el trabajo que **no puede producir ninguno**. Los 75.809 picks en 14 días que no pueden calificar (sin backtest guardado) se siguen creando, porque `decision-v1` los lee; dejar de crearlos es una decisión que solo puede tomarse cuando `decision-v1` deje de leerlos.

**Qué hace.** Un interruptor, `FBI_PICKS_SCAN`:

| Valor | Qué hace |
| --- | --- |
| `off` (por omisión) | exactamente como hoy: todos los instantes de la historia |
| `shadow` | el mismo recorrido completo y, además, **cuenta** cuántos candidatos salieron de un instante anterior a la ventana (en la nota de cada pasada: `scan shadow: N instants, from old instants M`). Es la prueba, pasada a pasada, de que la ventana no pierde nada |
| `window` | solo los instantes desde **24 h antes del inicio de la última pasada que se completó** (nunca menos de 24 h antes de la actual: si el worker estuvo parado días, lee todo lo que no leyó), y la evidencia de backtest leída **una vez por pasada** por (versión de modelo, mercado, línea) en vez de una vez por pick |

Las filas de candidatos, picks, su valor de línea y todo lo que lee `decision-v1` son **las mismas** en los tres modos (prueba de integración: una pasada en ventana escribe lo mismo que la completa, y una completa después no encuentra nada).

## 4. Pruebas

- **Unitarias** (sin base): propiedades del constructor sobre 40 grupos aleatorios de candidatos (nunca más de 3 tramos, nunca menos de 2, nunca un tramo no confirmado, conjunta ≤ la menor de las marginales y ≥ el límite inferior, crecimiento > 0); un solo candidato válido → ninguna; 4 buenos → 3; tope de 4 rechazado; un tramo de cuota alta que no hace crecer la combinada no entra; reglas de cada tramo (una sola casa, línea con devolución, sin precio, sin valor, empieza ya); conjunta con dependencia positiva ≥ producto y negativa ≤ producto (con su error), y determinista; mismo partido = la matriz; entre partidos, dependencia positiva o sin medir nunca sube la conjunta; mismo equipo nunca; margen acumulado; varios días = dos días; resultado de una combinada. Seguimiento: primera, aplazado/suspendido/abandonado nulo a las 72 h, cancelado, corrección como fila nueva y vuelta atrás, nulo por regla que se mantiene, firme una sola vez y a los 7 días, lo retenido idéntico a la reliquidación caso por caso, movimientos del ciclo, frases de «cómo se liquida», qué tablas escribe cada módulo y quién los importa. Interruptor del recorrido y lo que cada modo pasa al motor.
- **Integración** (PostgreSQL local): migración 0157 (sube, reglas en la base —más de 3 tramos, primera que sustituye, campos de firme en una primera, clave mal formada, UPDATE/DELETE rechazados—, baja limpia); escena completa: cuatro selecciones confirmadas → una diaria de 3 tramos (la línea con devolución nunca entra), ninguna de varios días, días anteriores registrados sin combinada, segunda pasada no duplica; resultados → 5 liquidadas, «En juego → Liquidada», segunda pasada sin escribir nada, la derivación de `decision-v2` coincide con lo añadido (0 divergentes); corrección del proveedor → fila nueva sin mover la cadena; a los 7 días → firme con precio tomado y «Evaluada»; lectura de la combinada con su resultado; nada de lo que se lee cambia (`decision-v1`, `picks.parlays`, picks). Recorrido en ventana = recorrido completo. Suites afectadas: ciclo de estados, `decision-v2` en sombra, pipeline de picks, reliquidación.

### Repetición de la liquidación (producción, solo lectura, 17-nov-2026)

- **Las 76.493 selecciones de picks en sombra** de los partidos del 3 al 17 de noviembre, liquidadas otra vez con la regla y las entradas del seguimiento: **75.657 idénticas** al resultado guardado por `settle-v4` (incluidos 87 pendientes en ambos). Las **836** restantes son todas nulos «sin resultado a las 72 h» (`no_result_72h`) de partidos que se jugaron después (832 con FT, 4 con AET): `settle-v4` y la reliquidación los mantienen nulos, y el seguimiento también (misma regla: «el nulo por regla se mantiene»). **0 discrepancias** con la regla.
- **Hallazgo:** de las **109** selecciones confirmadas en sombra por `decision-v1` en esos 14 días, **ninguna** seguía confirmada en el saque: todas se retiraron antes (73 por precio antiguo, 17 por la revisión, 10 por valor insuficiente, 5 por datos, 3 por riesgo) y se descartaron al saque (1 partido no jugado). Con `decision-v1`, «En juego → Liquidada» habría tenido 0 selecciones; el seguimiento trabajará sobre las cadenas de `decision-v2` cuando esté desplegado.

## 5. Cómo se activa en sombra (tras desplegar)

1. El despliegue aplica la migración **0157** (y deben estar 0142 —ciclo— y 0150 —`decision-v2`—).
2. `FBI_DECISION_V2=shadow` (IA-093) para que haya cadenas que seguir.
3. En el worker: `FBI_SELECTION_SETTLE=shadow` y `FBI_PARLAY_V6=shadow`; reiniciar.
4. `FBI_PICKS_SCAN=shadow` y, cuando varias pasadas digan `from old instants 0`, `FBI_PICKS_SCAN=window` (decisión del dueño); reiniciar el worker.
5. Comprobar (solo lectura, en la imagen del worker): `python -m scripts.ia_parlays_v6 preview --kind daily`, `... read --from AAAA-MM-DD --to AAAA-MM-DD` (combinadas, resultados y calibración), `... parity --days 14` (seguimiento frente a `settle-v4`: criterio 0 diferencias), `... selection --fixture N --market OU --selection Over --line 2.5` (una selección con su rastro y su frase), y `... settle --dry-run` / `... build --dry-run`.

## 6. Cómo se apaga y se revierte

- `FBI_SELECTION_SETTLE=off`, `FBI_PARLAY_V6=off` y/o `FBI_PICKS_SCAN=off` (o quitar las variables) y reiniciar el worker: los trabajos ni se programan y el recorrido vuelve a ser completo. Las filas se conservan.
- `parlay-v5`, `settle-v4` y `decision-v1` siguen exactamente igual en cualquier caso.
- Bajar la migración 0157 borra las tres tablas nuevas; las cadenas del ciclo conservan los pasos que se les añadieron.
- El código nuevo vive en un paquete hoja, `fbi/tracking/` (nada de `fbi` lo importa salvo la puerta del worker), para no agrandar el ciclo de importaciones entre paquetes (`test_architecture`).
