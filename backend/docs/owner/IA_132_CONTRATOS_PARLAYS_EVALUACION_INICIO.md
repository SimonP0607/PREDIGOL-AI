# IA-132 / IA-133 / IA-134 · Contratos C-04 «Parlays con estado», C-08 «Evaluación posterior» y C-12 «Inicio» (AD-J05, AD-J07, AD-J09)

Tres contratos de Intelligence con las convenciones de AD-J01 (IA-057): versión `1.0.0`, proyecciones servidas por el servidor, ausentes
con motivo, ejemplos y prueba de no fuga. Registrados en `fbi.api.contracts.intelligence.registry` con sus rutas. Sin migración y sin
interruptor nuevo.

## 1. C-04 «Parlays con estado» (pantalla de parlays, UX-168)

**Qué trae cada parlay:** el **estado del conjunto** (`armado`, `en_juego`, `liquidado` o **`ninguno`**), su resultado (`pendiente`,
`ganado`, `perdido`, `nulo`, `parcial_nulo`), **cómo se arma** (`rule`: versión de la regla, mínimo y máximo de tramos, tramos de un mismo
partido y cómo se calcula la conjunta), la ventana, los tramos con su resultado, la cuota combinada, la **probabilidad conjunta** con su
sello (`sin_calibrar`: no existe calibrador de una conjunta), la cuota justa, el **margen acumulado** y el valor esperado de la propia regla
(no es una promesa de ganancia).

«Ninguno si nada cumple» es un **estado explícito**: `status: "ninguno"` con `none_reason: "NINGUNO_CUMPLE"`, sin tramos. Nunca se rellena
un parlay para que haya uno.

- **Pública:** `GET /api/v1/parlays/{kind}` conserva su forma y suma el campo opcional `state`, que **solo viaja** con
  `FBI_MATCH_INTELLIGENCE` encendido y **solo** para lo que ve el lector: el parlay del producto (`parlay-v5`, hecho con los picks
  calificados). La vista previa del dueño (`preview=shadow`) no lo lleva y `parlay-v6` nunca sale aquí. Con 0 picks publicados, en la
  práctica dirá `ninguno`.
- **Privada:** `GET /api/v1/admin/intelligence/parlays?kind=&from=&to=` (`require_admin`; por defecto los siete últimos días de producto,
  31 como mucho). Trae los `parlay-v6` guardados en sombra (`intel.parlays_v6`, máximo 3 tramos — decisión 6 del dueño —, con la conjunta
  a los extremos pesimistas, su error de simulación, la conjunta del mercado, por qué un día no hubo y qué reglas dejaron fuera cuántas
  selecciones), el resultado leído de la liquidación de cada tramo, la **calibración** de la conjunta con su muestra (no se juzga con
  menos de 100 liquidados), los parlays del producto de ahora y el **histórico de `parlay-v5`** por estado (`picks.parlays`), que se sigue
  leyendo y no se reescribe.

## 2. C-08 «Evaluación posterior» (solo privada, UX-170)

`GET /api/v1/admin/intelligence/evaluations/{fixture_id}` (`require_admin`; 404 si el partido no existe). Por cada selección liquidada
del partido, la evaluación única `eval-sel-v1` (AD-K01) contesta las **seis preguntas**:

1. **Qué anticipamos:** la cifra juzgada con su sello, la del mercado en el mismo momento, la cuota, el estado de la decisión y si la capa
   la tomaría.
2. **Qué pasó:** el resultado de la liquidación de referencia y, si es completo (ganada o perdida), log loss y Brier de las dos cifras.
3. **Si fue buen precio:** el CLV frente al cierre, su calidad y el veredicto calidad × resultado (una ganada con precio malo es `SUERTE`).
4. **Qué evidencia acertó o falló:** cada hecho citado `sostenido`, `contradicho` o `no_evaluable`, solo con códigos (nunca el texto de
   un tercero).
5. **Si la alineación cambió algo:** la decisión antes de la alineación oficial frente a la que quedó y cómo fue la estimación de titulares.
6. **Si se cumplió el escenario:** `no_entregado` (`AD-B02`) hasta que el motor de escenarios guarde una lectura por selección.

Además, la **calibración acumulada** de cada celda del tablero de validación (AD-K02, últimos 30 días) con su muestra frente a la necesaria
(300), el veredicto del mercado de cada selección con su muestra y el aviso fijo **«Un acierto no valida el mercado.»**. Nada se presenta
como validado: por debajo de la muestra el veredicto es `INSUFICIENTE`. Si la base aún no tiene la tabla de evaluaciones, esos bloques
dicen `sin_datos`.

## 3. C-12 «Inicio» (solo pública, UX-166)

`GET /api/v1/home` conserva su forma y suma el campo opcional `featured_analyses`, que **solo viaja** con `FBI_MATCH_INTELLIGENCE`
encendido. Cada elemento es el **resumen del C-01 público** del partido (el mismo `match` y las mismas selecciones publicadas que sirve su
pestaña), así que nunca trae un análisis en sombra.

**La regla `featured-v1` (en código):** los partidos con al menos una selección **publicada** (el conjunto `qualified`) que empiezan en las
próximas 48 h; primero los de un **equipo favorito** del lector, luego los de una **competición que sigue**, luego el más próximo; cuatro
como mucho. Cada elemento dice por qué está (`reasons`). Los favoritos solo ordenan (`FBI_PERSONALIZATION`); no cambian ninguna selección,
cifra ni estado. Los candidatos se leen una vez para todos los lectores (la misma caché de 30 s que el resto de `/home`).

Con 0 publicados en la historia, la lista llega **vacía con su motivo**: `{"items": [], "missing_reason": "sin_publicados"}`. Si construirla
fallara, `/home` responde como siempre (sin el campo) y queda en el registro.

## 4. Ejemplos y pruebas

- Ejemplos en `tests/fixtures/contracts/intelligence/C-04/` (`ninguno`, `dos_tramos`, `tres_tramos`), `C-08/` (`ganada_sin_valor`,
  `perdida_con_valor`, `anulada`, `sin_evaluaciones`) y `C-12/` (`sin_publicados`, `destacados`). Equipos ficticios, sin datos de
  producción.
- Pruebas: las genéricas de contratos (no fuga, 403 al lector, forma y versión en `tests/snapshots/intelligence_contracts.json`),
  `tests/unit/test_parlay_states_contract.py`, `tests/unit/test_post_evaluation_contract.py`, `tests/unit/test_featured_analyses.py` y
  `tests/integration/test_parlays_evaluations_home_contracts.py` (las tres rutas contra una base real). La instantánea de `/home`
  (`tests/snapshots/client_api_shapes.json`) suma el campo opcional; ningún otro esquema cambia.

## 5. Qué no cambia y vuelta atrás

- No se toca `web/`, ni `parlay-v5`, ni `parlay-v6`, ni `decision-v1`, ni ningún pick. No cambia ninguna clave de las respuestas
  existentes; los campos nuevos no viajan con el interruptor apagado (ni como `null`).
- Sin migración y sin interruptor nuevo: la privada la protege `require_admin`; las públicas, `FBI_MATCH_INTELLIGENCE` (apagado).
- Vuelta atrás: dejar `FBI_MATCH_INTELLIGENCE` apagado, o revertir el PR. Aún no hay consumidor del lector.
