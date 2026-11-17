# IA-118 · Evaluación factual de la crónica única (`chronicle-review-v2`, `chronicle-metrics-v1`, `chronicle-protocol-v1`)

Pieza **AD-F06**. Tres partes: un **banco fijo de partidos trampa** que corre en CI, la **revisión tras el partido** rediseñada sobre los
hechos que cita la crónica, y un **protocolo de revisión humana por muestreo**, preregistrado y **sin firmar**. Sin modelo, sin coste;
nada de esto decide, publica ni entrena nada.

## 1. El banco de partidos trampa (CI)

`tests/fixtures/chronicle_traps.json` y `tests/unit/test_chronicle_traps.py`. Cada trampa es un partido con frases que un modelo podría
escribir; las que los hechos autorizan deben quedar y las que no, caer. Si un cambio hace que la crónica afirme lo que el hecho no
autoriza, **el PR falla**. Hoy tiene tres:

- **Un equipo que aún puede salvarse por diferencia de goles**: ni «nada en juego», ni «ya no puede», ni «eliminado» (el motor no lo
  demostró); sí «aún pelea por la permanencia».
- **Un lesionado que acaba titular**: la crónica dijo la baja con su fuente; la actualización (IA-116) lo corrige a su hora, la
  explicación de la selección no repite la baja y la revisión posterior marca la frase como contradicha.
- **Un rumor de una sola fuente**: solo en riesgos y llamado rumor; nunca como novedad ni como confirmado.

Una trampa nueva es una entrada nueva; una entrada no se edita para que una prueba pase.

## 2. La revisión tras el partido (`chronicle-review-v2`)

`chronicle-review-v1` revisó 270 crónicas de lectores y encontró **0 afirmaciones evaluables en 3.761 frases** (14 días): casi todo lo que
citaba era historia. La v2 juzga la crónica única **sobre los hechos de su plan**, que se guarda con ella:

- **Apoyo**, frase por frase: cada hecho citado está en el plan, planificado y conocido antes de escribir. Si no: `sin_apoyo`.
- **Lo que el partido puede refutar**: una baja o una duda contra quién jugó (el mismo juicio de la v1); una noticia de un jugador igual;
  lo que el motor de escenarios **demostró** (conseguido, descartado, nada en juego, lo que hace este resultado) contra su primera lectura
  después del partido; la actualización tras la alineación contra la planilla y los minutos.
- Lo demás (forma, tabla, cara a cara, cifras) describe: `not_evaluable`, nunca un acierto.

Las **métricas por crónica** (`chronicle-metrics-v1`): apoyo del verificador, apoyo de esta auditoría, cobertura del plan (obligatorios
citados), coletillas y repeticiones (IA-117), lo que se sostuvo y lo contradicho. Va a `ai.chronicle_reviews` con `chronicle_id`, al lado
de las filas de la v1, que siguen igual.

**Migración 0159** (la única de estas piezas; la ficha decía «sin migración», pero la tabla no admitía otra versión de texto): añade
`chronicle_id`, permite `narrative_id` vacío, obliga a que cada fila nombre exactamente un texto y el que corresponde a su versión. No
reescribe ni borra nada; su vuelta atrás falla a propósito si ya hay revisiones v2 (nunca borra una revisión).

Interruptor `FBI_CHRONICLE_REVIEW_V2`: **`off` por defecto**; `shadow` la corre cada hora.

## 3. El protocolo de revisión humana (preregistrado, SIN FIRMAR)

`fbi/chronicle/protocol.py` y `scripts/ia_chronicle_eval.py`:

- **Muestra**: 50 crónicas revisadas por la v2, elegidas por un hash fijo (la misma muestra cada vez); 10 de ellas las lee una segunda
  persona sin ver la primera etiqueta.
- **Etiqueta** por frase: SUPPORTED / NOT_IN_SOURCES / CONTRADICTED_BY_SOURCES / UNCLEAR (las del banco etiquetado, IA-030). La hoja
  muestra los hechos citados, **nunca el veredicto del código**.
- **Criterio**: 0 frases sin apoyo en las 50. Con n = 50 y 0 fallos solo se puede afirmar una tasa real **por debajo del 5,8 %** (cota
  superior unilateral al 95 %), y el informe lo dice así. Acuerdo de la doble lectura ≥ 90 %; un desacuerdo se lista, no se resuelve.
- **Umbrales de IA-117**: 30 % de plantilla, 10 % de coletillas y 10 % de repeticiones por crónica.

Lo que hace falta del dueño: **firmar el protocolo** (o cambiarlo) antes de medir. Hasta la firma, todo umbral es una propuesta.
Las etiquetas humanas se guardan aparte y no entrenan ni ajustan nada (AD-K07).

```
python -m scripts.ia_chronicle_eval sample --out hoja.csv      # solo lectura: la hoja para etiquetar
python -m scripts.ia_chronicle_eval score hoja.csv             # sin base de datos: el resultado contra el criterio
```

## Estado al entregar (17-nov-2026)

En producción no hay aún crónicas únicas que revisar (la crónica única está en revisión y nace apagada): **las 50 crónicas revisadas no
existen todavía** y el protocolo no está firmado. El banco trampa pasa en verde.
