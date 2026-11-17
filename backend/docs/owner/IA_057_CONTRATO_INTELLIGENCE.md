# IA-057 · Convenciones del contrato único de Intelligence (AD-J01)

*Pieza AD-J01 del plan maestro de la arquitectura definitiva 2026, ola 0. 16-nov-2026. Para la sesión de UX y para el dueño.*

Fija **una sola vez** cómo es todo contrato de Intelligence (C-01 a C-12): dos proyecciones servidas por el servidor, un sello en cada cifra, una versión en cada contrato, un motivo en cada ausencia, listas cerradas, ejemplos y una prueba genérica de no fuga. **Solo son tipos y pruebas**: no hay endpoint nuevo, ni migración, ni interruptor, ni nada que lea un lector. No cambia ninguna cifra, decisión, pick, umbral, agente, prompt ni motor, y no toca `decision-v1` ni `web/`.

Desde que esto se fusiona, **manda el ejemplo de cada contrato** en `backend/tests/fixtures/contracts/intelligence/`: los nombres del documento de coordinación de las 18 pantallas eran propuestas.

## 1. Dónde está

| Qué | Fichero |
| --- | --- |
| Listas cerradas | `backend/src/fbi/api/contracts/intelligence/vocab.py` |
| Tipos base | `backend/src/fbi/api/contracts/intelligence/base.py` |
| Las dos proyecciones y la comprobación de fugas | `backend/src/fbi/api/contracts/intelligence/projection.py` |
| Aditivo o rompe, y qué versión pide | `backend/src/fbi/api/contracts/intelligence/versioning.py` |
| Registro de contratos y catálogo C-00…C-12 | `backend/src/fbi/api/contracts/intelligence/registry.py` |
| C-00, contrato de muestra (sin ruta) | `backend/src/fbi/api/contracts/intelligence/reference.py` |
| Ejemplos | `backend/tests/fixtures/contracts/intelligence/<contrato>/<caso>.<proyección>.json` |
| Forma y versión guardadas | `backend/tests/snapshots/intelligence_contracts.json` (`python -m scripts.intelligence_contracts`) |
| Pruebas | `backend/tests/unit/test_intelligence_contract_base.py`, `…_leaks.py`, `…_versions.py` |

## 2. Las reglas

1. **Cabecera.** Toda respuesta empieza por `contract` (`"C-01"`), `contract_version` (`"1.0.0"`), `projection` (`"public"` o `"private"`) y `freshness`. Viaja dentro del sobre de siempre (`{"status", "data", "reason", "meta"}`): el contrato es `data`. La clase del contrato fija su código y su versión una sola vez; un ejemplo con otra versión no valida.
2. **Dos proyecciones.** Pública en `/api/v1/…`, con las puertas de consentimiento y membresía de hoy. Privada en `/api/v1/admin/…`, con `require_admin` (solo SUPER_ADMIN; a un lector le responde 403 `forbidden` el servidor). La privada **hereda** de la pública y añade campos, cada uno marcado `private(...)` (en el esquema JSON llevan `"x-projection": "private"`); nunca al revés. El servidor construye la pública copiando **solo** los campos que declaran las clases públicas, a cualquier profundidad: lo privado no se oculta, no se copia. En la pública, un campo privado no viaja ni como ausente.
3. **Lo no publicado no sale.** Un elemento de una lista que no se puede enseñar (una selección que el dueño no autorizó) se queda fuera de la pública; si la lista se queda vacía por eso, dice `sin_publicados` (lo mismo que vería el lector si no hubiera nada).
4. **Cifra con sello.** Toda probabilidad es un objeto:

   ```json
   {"value": 0.59, "pct": 59, "interval_pct": {"low": 52, "high": 66}, "calibration": "calibrada",
    "as_of": "2026-11-21T16:42:00Z", "evaluation": "E2", "evaluation_version": 2, "origin": "forecast-v1"}
   ```

   `pct` es el número que se pinta: lo redondea el servidor (mitad hacia arriba, con 0 o 1 decimal) a partir de `value`, y el modelo rechaza un `pct` que no salga así. La web no recalcula, no redondea de otro modo, no combina y no elige. `as_of` es cuándo se calculó la cifra. Antes de que existan las evaluaciones (AD-D06), `evaluation` y `evaluation_version` llegan las dos como ausentes con motivo. `origin` es `forecast-v1` hoy y `market_view` desde AD-B05. El caso Arsenal W – London City queda así: 59 % `calibrada` en la pública; 78,5 % `sin_calibrar` solo en la privada (en C-00, `raw_probability`).
5. **Fechas.** UTC, ISO 8601 con zona (`2026-11-21T23:00:00Z`); una hora sin zona se rechaza y otra zona se pasa a UTC. Un hecho lleva sus cuatro fechas: `published_at` (la fuente), `known_at` (PrediGol lo incorporó; obligatoria), `fact_at` (cuándo ocurre) y `valid_until` (vigencia). Si la fuente solo dio el día, `*_day_only: true` y la hora es 00:00 UTC: se muestra el día, nunca una hora.
6. **Ausente con motivo.** Un campo sin valor llega como `{"missing_reason": "<código>", …}` y una lista vacía como `{"items": [], "missing_reason": "<código>"}`. Nunca un `null` mudo. Los campos que acompañan a un motivo que no los usa no aparecen.
7. **Frescura.** `freshness: {generated_at, stale, stale_reason}`: el servidor dice si el dato está antiguo (`stale_reason` va exactamente cuando `stale` es `true`); la web solo enseña su aviso.
8. **Versión.** Un cambio que solo añade (un campo, un valor de una lista cerrada) sube el número menor. Uno que quita un campo, cambia su tipo, lo hace opcional, quita un valor o abre una unión (un campo que ahora puede llegar ausente) sube el mayor y va con la web en el mismo PR. La prueba de forma falla si la forma cambia sin la versión que pide y dice cuál es.
9. **Ejemplos.** Uno por caso y proyección: `<caso>.private.json` y, si el contrato tiene pública, `<caso>.public.json`, que es **exactamente** lo que el servidor sirve a partir del privado. Equipos y personas ficticios, enlaces en `.invalid`; nunca datos de producción. La web los usa en pruebas de componente y de regresión visual; nunca como datos.
10. **Errores.** El sobre de hoy: `{"status": "error", "error": {"code", "message"}, "request_id"}`.

## 3. Motivos de ausencia (`missing_reason`)

| Código | Significa | Acompaña (obligatorio) |
| --- | --- | --- |
| `no_entregado` | La pieza que lo calcula aún no está | `expected_piece` (p. ej. `AD-B02`); `expected_at` opcional |
| `aun_no_disponible` | Se sabrá más tarde (p. ej. la alineación oficial) | `expected_at` |
| `sin_datos` | Ni el proveedor ni las fuentes lo tienen | — |
| `sin_cobertura` | Competición o selección fuera de cobertura | — |
| `reglamento_no_codificado` | Sin reglamento no hay escenarios (AD-B01) | — |
| `muestra_insuficiente` | Por debajo de la muestra mínima del contrato | `sample` y `min_sample` (`sample` < `min_sample`) |
| `pendiente_derechos` | Falta el permiso de publicación o la respuesta del abogado | — |
| `retirado_por_derechos` | Retirado a petición; la auditoría se conserva | — |
| `sin_publicados` · `sin_resultados` · `sin_favoritos` | Solo para listas vacías del lector | — |

## 4. Listas cerradas

La web traduce el texto (ES/EN) y nunca deduce un valor a partir de otros.

- **Ciclo de una selección (AD-D02), solo en la privada:** `detectado`, `en_investigacion`, `en_evaluacion`, `pendiente_alineaciones`, `confirmada_sombra`, `retirada`, `descartada`, `en_juego`, `liquidada`, `evaluada`.
- **Estado público, lo único que ve un lector:** `publicada`, `en_juego`, `liquidada`. Lo calcula el servidor (`public_state_of`): sin la autorización del dueño, nada; con ella, `confirmada_sombra` → `publicada`, `en_juego` → `en_juego`, `liquidada` y `evaluada` → `liquidada`; los demás estados siguen privados.
- **Sello:** `calibrada`, `sin_calibrar`.
- **Evaluaciones (AD-D06):** `E1` primera lectura, `E2` por hecho nuevo, `E3` alineación oficial, `E4` cierre.
- **Liquidación (`settle-v4`):** `pending`, `win`, `loss`, `push`, `void`, `half_win`, `half_loss` (la prueba comprueba que son los de `fbi/picks/settlement.py`).
- **Confirmación (AD-C07, AD-G03):** `oficial`, `dos_origenes`, `declaracion`, `un_medio`, `rumor`. Avisos que no son nivel: `contradiccion`, `desactualizada`.
- **Veredicto de validación (AD-K02):** `VALIDADO`, `NO_VALIDADO`, `INSUFICIENTE`, siempre con `sample` y `needed`. `INSUFICIENTE` exactamente cuando la muestra no llega; con muestra completa, `VALIDADO` o `NO_VALIDADO`.
- **Estado de mercado (AD-E01):** `evaluable`, `en_calibracion`, `necesita_datos`, `no_ofrecer`.
- **Estado de capacidad (AD-003):** `construida`, `en_sombra`, `lista_revision`, `autorizada`.
- **Abstención (en mayúsculas):** `SIN_PRECIO_VIGENTE`, `UNA_SOLA_CASA`, `VALOR_INSUFICIENTE`, `MERCADO_NO_EVALUABLE`, `SIN_ALINEACION_A_TIEMPO`, `NINGUNO_CUMPLE`, `SIN_HECHO_QUE_LO_AUTORICE`, `CONTRADICCION_MATERIAL`. `SIN_OBJETIVO_DEMOSTRADO` no es una abstención (lo afirma solo el motor de escenarios).
- **Relación de un hecho con el análisis (AD-G08):** `a_favor`, `en_contra`, `contexto`, `no_usada`.
- **Disponibilidad (AD-H05), sin nada médico:** `disponible`, `duda`, `baja`, `sancionado`.
- **Dependencia de alineación (AD-D03):** `baja`, `media`, `alta`.
- **Proyección:** `public`, `private`.

## 5. Dos nombres que cambian respecto a la propuesta

En la cifra, el documento de coordinación proponía `seal` y `known_at`. Se fijan **`calibration`** y **`as_of`**: `calibration` dice qué es el sello, y `known_at` queda reservado a los hechos (cuándo PrediGol los incorporó), que es otra cosa que la hora en que se calculó una cifra. El resto de nombres de la propuesta se mantiene.

## 6. Las pruebas (corren en el CI para cada contrato registrado)

Un contrato entra en `CONTRACTS` (`registry.py`) en el PR que fusiona sus modelos, y desde entonces, sin escribir pruebas propias para esto:

- **Convenciones:** la privada hereda de la pública, todo lo que añade está marcado, ningún campo sin tipo (`dict`, `Any`), su código está en el catálogo, sus rutas privadas están bajo `/api/v1/admin/`; y toda clase de contrato de `fbi` está registrada.
- **Ejemplos:** cada uno valida contra su modelo y vuelve idéntico; el público es exactamente la proyección del privado.
- **No fuga:** el JSON público no tiene ningún campo que solo tenga el esquema privado ni ninguno que no tenga el público, ningún estado del ciclo distinto de `publicada`, `en_juego` o `liquidada`, y dice `projection: "public"`. Una prueba aparte comprueba que la comprobación caza una fuga de verdad (una clase pública con un campo privado, un añadido sin marcar, una clave privada en el JSON).
- **403:** cada ruta privada registrada responde 403 `forbidden` a una cuenta de lector con la aplicación real. Hoy se comprueba con la ruta del dossier, que ya existe.
- **Versión:** la forma y la versión de cada contrato están en `tests/snapshots/intelligence_contracts.json`; si la forma cambia sin la versión que pide, la prueba falla y lo dice. Un cambio a propósito se apunta con `python -m scripts.intelligence_contracts write --reason "IA-0NN: …"` (se niega sin motivo, sin cambio o con la versión equivocada).
- **Datos:** ningún ejemplo lleva teléfonos, ni correos ni enlaces fuera de `.invalid`.

## 7. C-00, el contrato de muestra

No tiene ruta ni consumidor. Usa todos los tipos base en una respuesta pequeña de un partido ficticio (Atlético Ficticio – Deportivo Ejemplo): tres cifras con sello, una selección publicada y otra en evaluación, un hecho con sus cuatro fechas, una lista vacía por cobertura, una crónica `no_entregado`, una alineación `aun_no_disponible`, una tasa con `muestra_insuficiente` y una validación `INSUFICIENTE`. Dos casos: `publicada` (la pública trae una selección) y `sin_publicar` (la pública trae `{"items": [], "missing_reason": "sin_publicados"}`). Sirve para que UX pruebe `ProbabilityLine`, `LifecycleChip` y los vacíos con motivo antes de C-01.

## 8. Qué no cambia, despliegue y vuelta atrás

- No hay endpoint visible, migración ni interruptor; ningún lector recibe nada nuevo. `FBI_PICKS_SOURCE` sigue apagado.
- Se despliega con el flujo normal; no hace falta ningún paso en el servidor.
- Vuelta atrás: revertir el PR. Aún no hay consumidor.
