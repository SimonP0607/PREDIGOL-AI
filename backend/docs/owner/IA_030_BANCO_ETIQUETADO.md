# IA-030 · Un banco etiquetado a mano del extractor y de las frases de la crónica

Fecha: 10 nov 2026. Estado: **en el código**. Sin migración ni interruptor. Es la R2 de la auditoría del 10-nov (`AUDITORIA_IA_Y_MATERIAL_UNIVERSITARIO_20261110`), aprobada por el dueño esa noche. Lo vigilan `tests/unit/test_label_bank.py` y `tests/integration/test_label_bank_readers.py`.

## 1. Para qué

Hoy nadie mide si lo que escriben los modelos es verdad frente a la fuente que citan: la batería mide ataques, el Gate B mide salidas inválidas, y la revisión posterior de la crónica tiene 0 afirmaciones firmes en sus primeras 193. Este banco es la medición que falta, hecha por personas: una muestra de lo que el sistema escribió, juzgada contra lo que cita.

## 2. Qué se muestrea (`label-bank-v1`)

* **`claims`**: la evidencia que los extractores escribieron de páginas web (`ai.evidence`, `origin = 'web'`, `extract-v1`, `extract-v2` y `extract-v3`; la del proveedor no es de un modelo y no entra). Estratos: versión del extractor × tipo de `claim-v1` que dice (`OUT`, `DOUBT`, `SUSPENSION`, `AVAILABLE`, `STARTER`, `COACH`, `SCHEDULE`, `VENUE`, `OTHER`; para `extract-v1`, que no escribía tipo, el que dan su clase y su afirmación). Cuota: 150.
* **`sentences`**: las frases de la crónica con el veredicto de su revisión posterior (`ai.chronicle_reviews`, la revisión más nueva de cada crónica). Estratos: el veredicto de la revisión (`contradicted`, `held`, `played`, `did_not_play`, `pending`, `not_checkable`, `not_evaluable`). Cuota: 60. Cada frase lleva los hechos que cita tal como los leía la crónica (`P:` desde el paquete con la función de la crónica, `E:` desde la evidencia).

La muestra es **determinista**: dentro de cada estrato las filas se ordenan por un hash de la semilla y del id; la cuota se reparte por igual entre estratos (lo que un estrato pequeño no usa pasa a los demás). En cada estrato, al menos una cuarta parte (redondeando hacia arriba) va marcada `double` para un segundo etiquetador **a ciegas**.

## 3. Las etiquetas

**Evidencia (`label_a`, `label_b`)**, contra la página citada y nada más:

| Etiqueta | Cuándo |
| --- | --- |
| `CORRECT` | la página dice esto, de este sujeto y para este partido |
| `WRONG_FACT` | habla del sujeto pero dice otra cosa (una duda guardada como baja…): se anota en `type_a` / `type_b` el tipo que sí dice |
| `WRONG_SUBJECT` | lo dicho es de otro jugador, equipo o entrenador |
| `WRONG_MATCH` | es de otro partido o es viejo (lesión curada, sanción cumplida) |
| `NOT_IN_SOURCE` | la página no dice nada parecido |
| `SOURCE_UNAVAILABLE` | la página ya no abre o no muestra el texto |
| `UNCLEAR` | no se puede decidir |

**Frases (`label_a`, `label_b`)**, el veredicto que la revisión debió dar, con la frase, sus hechos citados y el partido:

| Etiqueta | Cuándo |
| --- | --- |
| `HELD` | anticipaba algo refutable (quién juega) y el partido lo confirmó |
| `CONTRADICTED` | anticipaba algo y el partido mostró lo contrario |
| `NOT_EVALUABLE` | no anticipa nada que un resultado refute (historia, contexto, forma, o una duda: se cuenta, no se juzga) |
| `NOT_CHECKABLE` | anticipa algo, pero los datos del partido no lo pueden decir |
| `UNCLEAR` | no se puede decidir |

**Frases (`support_a`, `support_b`)**, aparte: si la frase, escrita antes del partido, dice solo lo que citan sus hechos: `SUPPORTED`, `NOT_IN_SOURCES` (dice algo que sus hechos no dicen), `CONTRADICTED_BY_SOURCES`, `UNCLEAR`.

`UNCLEAR` y `SOURCE_UNAVAILABLE` se cuentan pero no entran en el denominador de ninguna tasa.

## 4. El procedimiento

1. `python -m scripts.ia_label_bank sample --bank claims --since AAAA-MM-DD --out CARPETA` (y `--bank sentences`): lee en una transacción de solo lectura y escribe `claims.json` y `claims.csv` (las filas, las etiquetas y lo que significa cada una). Los archivos llevan el texto de la evidencia y de la crónica, las páginas y los nombres de jugadores; ninguna clave ni dato de usuarios.
2. El etiquetador A rellena `label_a` (y `type_a` / `support_a`) en todas las filas, **solo contra la fuente citada**, sin mirar la etiqueta del sistema más que para entender qué se afirma.
3. El etiquetador B rellena `label_b` solo en las filas `double`, sin ver las de A.
4. Los desacuerdos se hablan y se anotan en `notes`; **no se sobrescriben**. El puntuador los lista y los deja fuera de la comparación con el sistema.
5. `python -m scripts.ia_label_bank score --sheet CARPETA/claims.csv`: sin base de datos.

## 5. Qué mide la puntuación

* Acuerdo entre etiquetadores en las filas con dos etiquetas: casos, %, IC95 y **kappa de Cohen**; la lista de desacuerdos.
* Evidencia: la parte `CORRECT`, en total y por estrato; la matriz tipo del sistema × tipo humano (`NONE` cuando la página no sostiene ninguna afirmación de ese sujeto y partido), con **precisión** por tipo del sistema y **exhaustividad** por tipo humano. La exhaustividad es dentro del banco: una afirmación que el extractor nunca escribió no está en él.
* Frases: la matriz veredicto de la revisión × veredicto humano, con precisión y exhaustividad; y la parte de frases `SUPPORTED` y `NOT_IN_SOURCES`.
* Cada tasa lleva sus casos y su intervalo de Wilson al 95 % (IA-027).

## 6. Lo que NO hace

* **Ninguna etiqueta automática cuenta como verdad**: la referencia es la etiqueta humana; una fila sin etiqueta queda fuera, nunca se adivina; un desacuerdo nunca se resuelve por código.
* No cambia un gate, un umbral, un agente, un prompt ni la revisión de la crónica; no llama a ningún modelo; no escribe en la base de datos. Informa (`"decides": false`).

## 7. Resultados

Pendientes: la muestra se saca en producción en solo lectura y se etiqueta a mano; aquí se anotan la fecha, la ventana, la semilla y la puntuación.
