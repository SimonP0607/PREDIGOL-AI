# IA-079 · La consola de Intelligence (contrato C-11)

Fecha: 16 nov 2026. Pieza AD-J08 del plan de la arquitectura definitiva 2026, ola 1. Añade **una vista privada de solo lectura**: `GET /api/v1/admin/intelligence/console`. Sin migración, sin interruptor, sin cambios en la web y sin ningún efecto en el lector. No cambia ninguna cifra, decisión, pick, umbral, agente, prompt ni motor, y no toca `decision-v1`.

## 1. Qué hace

Una sola respuesta con lo que conviene mirar antes que nada. Es el contrato **C-11** (versión 1.0.0, solo privada: `require_admin`, a una cuenta de lector el servidor le responde 403). Sigue las reglas de IA-057: cabecera con contrato, versión y proyección, frescura, ausentes con motivo y listas cerradas. Tiene seis bloques:

| Bloque | Qué enseña | De dónde sale |
| --- | --- | --- |
| `shadow` · «nada sale de la sombra» | Estado real de `FBI_PICKS_SOURCE` y `FBI_AI_MODE`, si el veto de la IA está en vigor, cuántas selecciones ve un lector como pick y los interruptores de las capacidades (`FBI_AI_RESEARCH_V2`, `FBI_AI_AGENTS`, `FBI_AI_ENGINES`, `FBI_FAMILY_DECISIONS`, `FBI_AI_PM_REVIEWER`, `FBI_AI_LEARNING_ANALYST`, `FBI_AI_ENVELOPES_INDEPENDENT`) y de las pantallas de lector de Intelligence (`FBI_MATCH_INTELLIGENCE`, `FBI_NEWS_V2`, `FBI_SEARCH`, `FBI_PROFILES`) | El analizador de cada interruptor en el código; el último registro del trabajador (`ai.feature_gates`, gate `switches`); `fbi.ai.gating.enforcement`; `picks.picks` |
| `capabilities` | Cada capacidad del registro con uno de sus cuatro estados (`construida`, `en_sombra`, `lista_revision`, `autorizada`), su veredicto de seguridad y de validación (con su muestra), las últimas filas de los gates de los que depende y los avisos | Registro de capacidades (IA-056, AD-003) |
| `costs` | Cada sobre de la decisión 12 (producción con la crónica de lectores dentro, Exa, LAB) y el tope de cada capacidad nueva frente a lo gastado en el mes, con su aviso al 80 / 95 %; el techo conjunto de 190, si se aplica y que está pendiente de tu confirmación | Presupuesto por capacidad (IA-058, AD-A06), `fbi.ai.costs_v3.month_of` |
| `security` | La última fila de la batería adversaria, la última noche de la auditoría de fugas (las reglas que encontraron algo), el panel de los 16 gates con su veredicto real y si el esquema de la base es el del código | `ai.feature_gates`, `intel.audit_checks`, panel de gates (IA-050), `alembic_version` |
| `news_engine` | Ausente: `no_entregado`, pieza AD-G01 | — |
| `alert_queue` | Ausente: `no_entregado`, pieza AD-D08 | — |

**«Nada sale de la sombra»** dice `se_cumple`, `no_se_cumple` o `sin_comprobar`. Se rompe exactamente por tres cosas: la página de Picks leyendo Intelligence (`FBI_PICKS_SOURCE=intelligence`), el veto de la IA en vigor sobre lo que ven los lectores, o una selección publicada (`picks.picks` en `qualified` o `published`). `FBI_AI_MODE=enforce` **no basta** para que el veto esté en vigor: además, el último informe de `combined` tiene que decir `pass`. La consola enseña las dos cosas por separado. Si una lectura que necesita falla, dice `sin_comprobar` y nunca `se_cumple`.

**Gate B** sale como «NO EVALUADO» solo cuando tu cierre está registrado (fila `gate-b-closure-v1` de `gate_b` con `decided_by = 'owner'`, IA-055). Mientras no exista esa fila, el panel dice lo que dice su evaluador. La consola no inventa ese veredicto.

## 2. Lo que se midió en producción (solo lectura, 16-nov-2026, 19:20–19:35 hora de Bogotá)

* **Las 38 rutas de consulta de la consola de IA responden 200** con los datos de producción (migración 0137): las 25 de `/admin/ai/…` y las 13 de `/admin/intelligence/…` que no llevan parámetros en la ruta, llamadas una a una como SUPER_ADMIN dentro del contenedor de la API con su conexión de solo lectura. La más lenta es `families` (9,2 s), seguida de `price-clock` (4,5 s) y `ai/costs` (4,1 s).
* **Lo que la consola habría enseñado ese día:** `FBI_PICKS_SOURCE` sin línea (`legacy`). `FBI_AI_MODE=enforce` en la API, pero el veto no está en vigor porque el gate de la IA (`ai_gate_v2`, informe de `combined`) dice NO PASA. 0 selecciones en `qualified` o `published`. Batería: NO PASA (fila 18, 15-nov 17:12 UTC; las cuatro últimas filas, NO PASA). Auditoría de fugas del 15-nov (`leak-audit-v9`): 22 reglas, 134 violaciones en tres (`forecast_known` 109 de 5.299, `h2h_known` 13 de 8.284, `national_known` 12 de 65.325). Gates: 1 PASA (Gate A), 2 NO PASA (research v2, gate de la IA), 2 RECHAZA, 2 PENDIENTE POR TIEMPO REAL (Gate B, sin fila de cierre todavía, y P1), 9 PENDIENTE POR DEPENDENCIAS. La regla «ningún pendiente aparece como aprobado» se cumple.
* **El panel de gates tarda 5,2 s** en leerse con datos de producción (evalúa Gate B y research v2 en vista previa, sin registrar). Por eso la consola lo guarda **cinco minutos** por proceso; `security.gates.as_of` dice cuándo se leyó.

## 3. Los 500 de QA en las cinco pruebas de la consola (`web/e2e/admin.spec.ts` 252, 355, 465, 687, 706)

**Causa: la base de QA no tiene las tablas de las migraciones 0118, 0119 y 0120. No es un fallo del código de la IA.** Cómo se comprobó:

1. Las cinco pruebas dependen de dos rutas. Las páginas Operación y Aprendizaje (y cualquier dirección vieja que lleve a ellas) montan la línea de sombra, que sale de `GET /admin/ai/overview`. Si esa ruta falla, no hay línea («no aparece la línea de sombra»), y además el vigilante de las pruebas apunta el 500. La prueba 465 llama directamente a `GET /admin/intelligence/families` y espera un 200.
2. Con el código de `main` y una base vacía migrada **hasta la cabeza**, las 38 rutas responden 200. En producción, también 200 (punto 2).
3. Con el mismo código y la base parada en revisiones anteriores (probado en 0117, 0118, 0119 y 0120):
   * en **0117**, responden 500 (`UndefinedTable`) exactamente `ai/overview`, `intelligence/families`, `ai/shadow/arms` y `ai/attribution`, y ninguna otra ruta de IA;
   * en **0118** (`intel.family_postmortems`, `intel.family_memory`), `families` pasa a 200;
   * en **0119** (`ai.shadow_assignments`), `shadow/arms` pasa a 200;
   * en **0120** (`intel.agent_attributions` y dos columnas), `overview` y `attribution` pasan a 200.

   Es el mismo conjunto de síntomas que ve QA.
4. Una pista de cómo pudo pasar: esas revisiones entraron con la unificación de las cuatro líneas del 2-nov. La migración de las familias se llamaba **0094** en la línea del plan y se renumeró a **0118**. Una base de QA que venía de aquella línea puede tener en `alembic_version` un número que no corresponde a las tablas que de verdad tiene. **No lo he podido ver en la base de QA**: no tengo acceso a ella.

**Qué hacer (sesión de UX o dueño, en la base de QA, no en producción):**

```sql
SELECT version_num FROM alembic_version;
SELECT r, to_regclass(r) IS NOT NULL AS existe
  FROM unnest(ARRAY['intel.family_postmortems','intel.family_memory','ai.shadow_assignments','intel.agent_attributions']) AS r;
```

Si falta alguna, hay que hacer copia y migrar (`scripts/dev-up --migrate`). Si `alembic_version` ya dice la cabeza pero faltan tablas, hay que rehacer la base de QA desde una copia buena. Con las tablas en su sitio, las cinco pruebas deberían dejar de recibir 500. Está pendiente de confirmar con dos pasadas seguidas en QA, que es el criterio de cierre.

**Lo que cambia en el código:** no se cambia ningún permiso ni ninguna ruta existente, y tampoco se ocultan los errores de esas rutas, porque una base atrasada debe notarse. La consola nueva, en cambio, **no se cae entera**. Cada bloque se lee en su propio punto de guardado: si a un bloque le falta una tabla, llega como `{"read_failed": true, "error": "UndefinedTable"}` (solo la clase del error, nunca el mensaje) y el resto se sirve igual. `security.schema_check` dice la revisión de la base, la cabeza del código y qué tablas de la consola faltan.

## 4. Qué no cambia

* **Solo lectura.** La consola no escribe ninguna fila, no cambia ningún interruptor, no registra ningún gate y no promociona nada. Cada interruptor lleva `changeable_here: false`. Una prueba comprueba que su ruta es solo GET y que las únicas escrituras de las páginas de IA son las tres que ya existían (`/admin/ai/run-requests`, `/admin/ai/review/run`, `/admin/ai/report/run`): lanzan o encolan un trabajo, ninguna cambia un interruptor.
* **Sin secretos.** Cada interruptor se enseña con la palabra que el código lee de él (`legacy`, `shadow`, `match,council`…), nunca con su valor tal cual. Un valor raro se lee como su valor por defecto, y en el registro del trabajador solo se aceptan sus palabras conocidas. Una prueba pone una clave falsa en tres interruptores y comprueba que no aparece.
* `FBI_PICKS_SOURCE` sigue apagado. La crónica de lectores sigue sin leerse desde Intelligence: los costes llegan por `fbi.ai.costs_v3`, el único módulo que puede leer ese libro. La consola solo pregunta si su tabla existe.
* El nombre del estado: el registro escribe `lista_para_revision` y el contrato (lista cerrada acordada con UX) dice `lista_revision`. La consola los traduce con una tabla fija, y un estado desconocido es un error, nunca una suposición.

## 5. Despliegue y vuelta atrás

* Se despliega con el flujo normal; no hace falta ningún paso en el servidor. Necesita las ramas IA-056 (registro y migración 0138), IA-057 (convenciones) e IA-058 (presupuesto), que van con ella. Si la 0138 aún no estuviera aplicada, el bloque `capabilities` saldría como `read_failed` y el resto funcionaría.
* El ejemplo para UX está en `backend/tests/fixtures/contracts/intelligence/C-11/` (`en_sombra`, `esquema_atrasado`). Cuando existan el motor de noticias (AD-G01) y la cola de alertas (AD-D08), sus campos dejarán de ser solo «ausente» y el contrato pasará a 2.0.0, junto con la web.
* Vuelta atrás: revertir el PR. La consola actual sigue funcionando igual; nada la consume todavía.
