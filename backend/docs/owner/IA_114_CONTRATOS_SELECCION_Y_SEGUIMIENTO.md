# IA-114 / IA-115 · Contratos C-02 «Selección» y C-03 «Seguimiento privado» (AD-J03, AD-J04)

Dos contratos de Intelligence con las convenciones de AD-J01 (IA-057): versión, dos proyecciones servidas por el servidor, ausentes con
motivo, ejemplos y prueba de no fuga. Registrados en `fbi.api.contracts.intelligence.registry` con sus rutas.

## 1. C-02 «Selección» (`1.0.0`) — pantalla 04

**Qué trae:** la selección (mercado, lado, línea, familia y cómo se lee en español), su cifra con sello, la cuota justa, el valor
esperado de la decisión, el **precio y su antigüedad** juzgada por la regla de su capa (`price-age-v1` para decision-v1: 3 h, y 30 min en
los cortes finales; los umbrales viajan en el contrato: `thresholds_min`), **Por qué** y **En contra** (plantillas del código sobre los
números y los códigos guardados), **De qué depende** (alineación oficial, contexto pendiente, precio vigente, validación del mercado),
**Cómo se liquida** (`settle-v4` o la regla de conteo del catálogo), las **versiones** (cada decisión de su capa, de la más antigua a la
más nueva) y las **fuentes usadas** (tipo, nombre, enlace y hora en que PrediGol lo supo; nunca el texto de un tercero).

**Solo en la privada:** el id de la decisión y su capa, la palabra de la capa, el **estado del ciclo** y su motivo (AD-D02), la cifra del
modelo `sin_calibrar`, la **validación del mercado** del tablero (AD-K02: veredicto, muestra y necesaria; hoy INSUFICIENTE, 0 de 300) con
su celda, y la **evaluación posterior** (AD-K01). La dependencia de la alineación con jugadores y puntos va como `no_entregado` (AD-D03).

**Dónde:**

- **Privada:** `GET /api/v1/admin/intelligence/decisions/{decision_id}` (`require_admin`). La página de siempre conserva todas sus
  claves y suma una: `intelligence`, con este contrato. Si construirlo fallara, esa clave dice `{"read_failed": true, "error": "<clase>"}`
  y el resto de la página sigue igual.
- **Pública:** `GET /api/v1/picks/{pick_id}/explanation` («Explícame») conserva su forma y suma el campo opcional `intelligence`, que
  **solo viaja** con `FBI_MATCH_INTELLIGENCE` encendido **y** para una selección que el dueño autorizó (publicada, en juego o
  liquidada). Una selección en evaluación, retirada o descartada **nunca** sale en la pública, y con el interruptor apagado el campo no
  existe en la respuesta (no viaja ni como `null`). Hoy hay 0 picks publicados en la historia: en la práctica, la pública no lo trae.

## 2. C-03 «Seguimiento privado» (`1.0.0`, solo privada) — pantalla 05

`GET /api/v1/admin/intelligence/tracking?state=&family=&competition=&from=&to=&cursor=&limit=` (`require_admin`; por defecto, los seis
últimos días y mañana; 31 días como mucho; 50 por página, 200 como mucho).

- `counts_by_state`: los diez estados del ciclo, con sus ceros, contados por el lector del propio ciclo (`fbi.lifecycle.reader`).
- `families`: por capa y familia, las candidatas evaluadas, la **muestra** que cuenta el tablero frente a la **necesaria** (300), el
  veredicto y el CLV medio de lo que la capa tomaría.
- `items`: cada selección con su estado y motivo, la cifra y la cuota de su decisión más reciente hasta ese momento, el paso de
  evaluación, el resultado y el CLV de su evaluación posterior; paginadas por el servidor (`next_cursor`).
- `board`: qué tablero contó (`board-v1`), su protocolo y su huella, y que el dueño **no lo ha firmado**.

Si la base aún no tiene la tabla del ciclo o la de evaluaciones (una base detrás del código), ese bloque dice `sin_datos` y el resto
responde. Hoy en producción ninguna de las dos existe todavía (la base va por la 0141): tras desplegar, C-03 mostrará los ceros hasta que
`FBI_LIFECYCLE=shadow` y `FBI_SELECTION_EVAL=shadow` escriban.

## 3. Ejemplos y pruebas

- Ejemplos en `tests/fixtures/contracts/intelligence/C-02/` (`publicada`, `liquidada`, en las dos proyecciones; y en `privada/`
  `en_evaluacion` y `retirada`, que no tienen proyección pública) y `C-03/` (`en_sombra`, `sin_tablas`). Equipos y personas ficticios,
  enlaces en `.invalid`.
- Pruebas: las genéricas de contratos (no fuga, 403 al lector, forma y versión en `tests/snapshots/intelligence_contracts.json`),
  `tests/unit/test_selection_contract.py` (una selección en evaluación nunca se proyecta; sin interruptor no se construye nada; las reglas
  de precio son las del código; las plantillas) y `tests/integration/test_selection_evaluation.py` (las dos rutas contra una base real).

## 4. Qué no cambia y vuelta atrás

- No se toca `web/` (UX consume C-02 y C-03 en UX-164 y UX-167). No cambia ninguna clave de las respuestas existentes; las seis rutas de
  la instantánea del cliente no cambian.
- Sin migración propia y sin interruptor nuevo: la privada la protege `require_admin`; la pública, `FBI_MATCH_INTELLIGENCE` (apagado).
- Vuelta atrás: revertir el PR. Los campos nuevos son opcionales y no tienen consumidor del lector.
