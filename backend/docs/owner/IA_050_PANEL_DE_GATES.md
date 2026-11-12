# IA-050 · Panel de gates y valor por dólar (solo lectura)

*Pieza INT-T03 del Plan Maestro de Evolución de PrediGol Intelligence 2026, ola 1. 11-nov-2026.*

Un solo sitio, de solo lectura, con cada gate del plan —sus casos, su intervalo, su umbral, su veredicto, el día en que se puede evaluar y de dónde sale cada cifra— y lo que cuesta cada componente de la IA, con un valor por dólar **solo donde hay un beneficio medido**. Informa y no decide: no registra ningún gate, no cambia umbrales, interruptores, agentes, prompts, motores, la muestra de sombra ni picks, y no añade endpoint ni contrato de la API.

## 1. Qué es y cómo se mira

- `fbi.ai.gates_panel` (`gates-panel-v1`): el panel. Puro: no lee la base de datos ni el reloj (`"decides": false`).
- `fbi.ai.gates_panel_readers`: las lecturas —la fila más nueva de cada gate en `ai.feature_gates`, el informe más reciente de cada motor en `ai.shadow_reports` y los conteos de P1— y los evaluadores de Gate B y de Research v2 tal como los corren sus scripts **sin `--record`**. Los dos evaluadores y el conteo de P1 van cada uno en su propio punto de guardado: si uno falla, su gate sale PENDIENTE POR ACCIONES MANUALES con el error (o, si tiene fila, manda la fila) y el resto de la foto se lee.
- `scripts/ia_gates_panel.py`: lo que se ejecuta, en el contenedor del worker como los demás scripts de la IA. El coste lo lee el script con `fbi.ai.cost_paths_readers`.
- El panel **no lee `ai.evidence`**: la tabla tiene su lista cerrada de lectores (`tests/unit/test_typed_evidence_guard.py`, sección 5 de `IA_FASE2.md`). Las cifras de G-FUENTES 1 son la medida de IA-040, congeladas con su fuente.

```
python -m scripts.ia_gates_panel show                  # el panel, en español
python -m scripts.ia_gates_panel show --json           # el panel entero en JSON (lo que leerá la vista de admin)
python -m scripts.ia_gates_panel show --cost-days 7    # coste de los 7 últimos días UTC completos (14 por defecto)
python -m scripts.ia_gates_panel show --cost-since 2026-10-28 --cost-until 2026-11-11
```

La conexión se abre de solo lectura (`default_transaction_read_only=on`, `statement_timeout` de 95 s) y todo se lee en **una sola foto** (`REPEATABLE READ`): una escritura la rechazaría la propia base de datos. Sale con 0 si el panel se hizo y la regla se cumple, con 1 si la regla falla (un defecto: no debe pasar nunca) y con 2 si no pudo correr por un error de uso (por ejemplo, una ventana de coste vacía o que acaba después de ahora).

El texto muestra hasta 6 cifras por bloque (y dice cuántas más hay en `--json`) y corta a 240 caracteres los motivos de una comprobación; el JSON lo lleva todo. Los motivos de los evaluadores salen como ellos los escriben (algunos en inglés): el panel no los reescribe.

## 2. La regla: ningún gate pendiente aparece como aprobado

PASA solo sale donde hay un **pase registrado** (`on_file_pass`):

| Tipo de gate | PASA solo si |
| --- | --- |
| vivo (Gate B, Research v2) | la fila más nueva de ese gate en `ai.feature_gates` dice que pasó (la fila más nueva decide: `ORDER BY at DESC, id DESC`) |
| registrado (Gate A, puerta de la capa IA) | la fila `gate_a` de `ai.feature_gates`, o el informe más reciente de `combined` en `ai.shadow_reports` (`ai-gate-v2`), dice que pasó |
| LAB (G-EVENTOS, G-E4) | su veredicto congelado es PASA, con la huella de su protocolo |
| muestra (P1) y dependencias | nunca |

En un gate vivo manda la fila; si su evaluador dice hoy otra cosa, se escribe al lado. Sin fila, un PASA del evaluador sale **PENDIENTE POR ACCIONES MANUALES** —sin la fila el sistema no lo da por aprobado— y cualquier otro veredicto sale tal cual, marcado «sin registrar». `violations` comprueba la regla sobre el panel entero (estado desconocido, `approved` distinto de `status == "PASA"`, PASA sin pase registrado, PASA en P1 o en un gate de dependencias) y el script sale con 1 si alguna vez falla.

Las palabras son las de los gates: PASA, NO PASA, PENDIENTE POR TIEMPO REAL y PENDIENTE POR ACCIONES MANUALES (`fbi.ai.gate_b`); las del LAB, RECHAZA y PENDIENTE POR MUESTRA (`fbi.research.protocol`); y PENDIENTE POR DEPENDENCIAS para un gate cuyas piezas aún no existen.

Lo vigila `tests/unit/test_gates_panel.py`: en 324 combinaciones de filas y veredictos (Gate B, Research v2 y `ai-gate-v2`) ningún pendiente sale aprobado; el comprobador caza los paneles rotos; los veredictos del panel son los de los evaluadores sobre datos falsos hechos con las piezas de los propios evaluadores; las cifras del LAB son las de sus ficheros de resultado y las de G-FUENTES 1, las de la tabla de IA-040; y ni el panel ni sus lecturas escriben.

## 3. Los gates y de dónde sale cada cifra

| Gate | Pieza | Tipo | Estado y cifras: de dónde salen | Cuándo se puede evaluar |
| --- | --- | --- | --- | --- |
| Gate B | sección 24 (`gate-b-v1`) | vivo | `fbi.ai.gate_b` (vista previa, sin registrar) y la fila `gate_b`. Cada comprobación con sus tablas: plazo (`ai.match_runs`, `ai.agent_runs`, `ai.agent_tasks`), inválidas y pagos duplicados (`ai.agent_runs`), sobre del LAB (`ai.usage` del LAB, `ai.cycles` y la fila `lab_plan`), atribución (`intel.agent_attributions`, `core.fixtures`), fugas (`intel.audit_checks`), batería y Research v2 (`ai.feature_gates`) | 14 días completos de Bogotá desde el ancla de la configuración |
| Research v2 | fase 2 | vivo | `fbi.ai.gate_research` y la fila `research_v2`; `ai.evidence` y `ai.fixture_passes` | 7 días completos con v2 en sombra |
| Gate A | sección 24 (fin de la fase 0) | registrado | la fila `gate_a` (la escribe `scripts/ia_gate.py`); el panel no lo vuelve a evaluar | ya evaluado |
| Puerta de la capa IA | `fbi.ai.shadow`, `fbi.ai.gating` | registrado | `ai.shadow_reports` (`ai-gate-v2`), informe más reciente por motor; manda `combined` | cada día, sobre los 60 días anteriores |
| G-COH | INT-A04 | dependencias | espera INT-A03 e INT-A04; lleva al lado el veredicto congelado de INT-A02 (IA-036) | 72 h de producción tras INT-A04 |
| G-PRECIO | INT-A06 | dependencias | espera INT-A06 (IA-037) | — |
| G-FUENTES 1 | INT-B01 | dependencias | espera el registro depurado en la sombra; lleva al lado la medida de IA-040 (su tabla 2), congelada con su fuente y sin veredicto | tras el Gate B |
| G-FUENTES 2 | INT-B02 | dependencias | espera INT-B01, INT-B03 e INT-B02 | — |
| G-FUENTES 3 | INT-B04 | dependencias | espera INT-B04 y el gate de Research v2 | — |
| G-EVENTOS | INT-B09 | LAB | veredicto congelado de IA-045 | evaluado una sola vez |
| G-E4 | INT-A09 | LAB | veredicto congelado de IA-039 | evaluado una sola vez |
| G-E6 | INT-A08 | dependencias | `fbi.research.protocol`: INT-A08 aún no tiene protocolo registrado | después de INT-A08 en el LAB |
| G-DELIB | INT-C08 | dependencias | espera INT-C03 a INT-C07 y la ventana de P1 | — |
| G-CRON | INT-D04 | dependencias | espera INT-D02 | — |
| P1 | ventana de la sombra | muestra | `ai.pick_reviews`: selecciones distintas de `ma-v1`, `ma-v1-h` y `cs-v1` (modo sombra, estado `ok` o `fallback`, revisadas antes del saque) desde el ancla del Gate B, por familia de mercado | 30 días y 300 selecciones por familia |
| F-Player | fuera de este plan | dependencias | — | — |

- **Gate A** entra porque existe como gate con fila: es el cierre de la fase 0 y cuenta su veredicto registrado.
- **La puerta de la capa IA** (`ai-gate-v2`) entra porque es la que lee `fbi.ai.gating` —sin PASA en `combined`, la IA no cambia lo que ven los usuarios— y porque es el beneficio medido del valor por dólar (sección 4).
- `switches` y `lab_plan` son registros, no gates: salen en «Filas más nuevas» y nunca se juzgan.
- **P1** no guarda evidencia propia. Con los 30 días y una familia en 300 selecciones sale PENDIENTE POR ACCIONES MANUALES (la evalúa el informe de G-DELIB), nunca PASA.

**Registro congelado del LAB** (en el código, con pruebas que lo comparan con sus ficheros). Cada registro dice si su huella es la registrada hoy en `fbi.research.protocol` (`registered`); si no lo fuera, el panel lo escribe. Un resultado nuevo es un registro nuevo con su PR, nunca una edición de estos.

| Pieza | Protocolo | Huella (SHA-256) | Veredicto | Resultado |
| --- | --- | --- | --- | --- |
| INT-A02 (IA-036) | `proto-int-a02-v1` | `2a1cdb3ec31a6b5075010a989e6205bf60bc699c54891a62ac861ad0fd69ae6d` | RECHAZA | `docs/owner/lab/IA_036/resultado.json` |
| INT-A09 (IA-039) | `proto-int-a09-v1` | `400778f85de7acdfc59b1d9e265d7f4c4d5fe42abc4abf71cb5785b33604bd36` | RECHAZA | `docs/owner/lab/IA_039/resultado_e4.json` |
| INT-B09 (IA-045) | `proto-int-b09-v1` | `2b8e49fb115f5cecbcb5e61f52d9ac11d8c8464ce7b3da97af62b3f9382e9232` | RECHAZA | tabla «Métrica principal y segmentos preregistrados» de `IA_045_ESTUDIO_EVENTOS.md` |

## 4. Valor por dólar

**Coste.** `fbi.ai.cost_paths` (`cost-paths-v1`) sobre días UTC completos (14 por defecto), al céntimo del libro `ai.usage`; la crónica de lectores lleva además su propio libro (`ai.user_usage`), que va al lado del total y nunca dentro. Por componente: US$, parte del gasto, llamadas, partidos, candidatos y US$ por candidato cuando los hay, los tres modelos que más gastan y el ritmo a 30 días. `fbi/ai/costs_v3.py` no se toca.

**Beneficio**, solo de un informe que lo mide con una regla:

- la prueba prospectiva de la propia IA, `ai-gate-v2` (`fbi.ai.shadow`, tabla `ai.shadow_reports`), por motor: ROI(guardadas) − ROI(rechazadas) a stake plano de 1 sobre las selecciones liquidadas que el motor revisó antes del saque, con el error típico del bootstrap por partido. Pasa con z ≥ 2, el CLV de las guardadas no por debajo del de las rechazadas y su Brier no peor que el de todas en más de 0,002, con al menos 300 selecciones, 30 días y 50 rechazadas;
- G-EVENTOS (IA-045): si el precio se movió después de que PrediGol supo una afirmación web, más que en los controles.

**Por qué no R4 (IA-029).** R4 (`fbi.ai.r4_compare`) dice cuánto coinciden la revisión de producción y el Council y qué hicieron las selecciones guardadas y rechazadas, pero no tiene umbral ni prueba y no decide: no dice si hay beneficio. `ai-gate-v2` sí lo dice, con su regla, y es la puerta que lee `fbi.ai.gating`.

**Valor por dólar**, solo con el `ai-gate-v2` del motor en PASA:

> valor por dólar = (1 − r) · r · (ROI guardadas − ROI rechazadas) / coste por candidato

con r la proporción rechazada. El numerador es lo que la revisión añade por candidato juzgado, a stake plano de 1 por selección guardada, frente a un veto al azar que rechazara la misma proporción; el denominador, lo que cuesta juzgar un candidato (`cost_paths`). Unidad: unidades de beneficio a stake plano de 1 por cada US$ de coste. Su IC95 es el de la diferencia (± 1,96 errores típicos), con r y el coste tomados como fijos.

Si no hay PASA, el panel dice por qué: «no demostrado» (su `ai-gate-v2` da NO PASA), «pendiente por muestra» (aún sin 300 selecciones, 30 días y 50 rechazadas) o «sin medir» (ningún informe lo mide, o el motor no corre). G-EVENTOS no está en dólares y nunca da valor por dólar.

| Componente | Camino de coste | Beneficio que se mira |
| --- | --- | --- |
| Revisión de producción (`review-v2`) | producción · review | `ai-gate-v2` de `llm` |
| Lectura del partido (`brief-v8`) | producción · brief | ninguno: es insumo de `review-v2` |
| Deliberación en sombra (agentes, Council y escaladas) | deliberación entera (los brazos comparten las llamadas de los agentes) | `ai-gate-v2` de `ma-v1`, `ma-v1-h` y `cs-v1` |
| Research: búsquedas de Exa · extracción | research · search, extraction | G-EVENTOS (segmentos oficial, medio y rumor) |
| Crónica de lectores | chronicles + su libro `ai.user_usage` | ninguno |
| Aprendizaje · Post-mortems · LAB · Otros | resto | ninguno |

## 5. Forma del JSON (para la futura vista de admin)

`show --json` da un objeto con estas claves, siempre las mismas (un valor que falta va como `null`):

```
{
  "version": "gates-panel-v1", "decides": false,
  "at": "<instante UTC de la foto>", "day": "<día de Bogotá>",
  "rule": "<la regla, en una frase>",
  "summary": {"PASA": n, "NO PASA": n, "RECHAZA": n, "PENDIENTE POR ACCIONES MANUALES": n,
              "PENDIENTE POR TIEMPO REAL": n, "PENDIENTE POR MUESTRA": n, "PENDIENTE POR DEPENDENCIAS": n},
  "gates": [<gate>, …],            // 16, en el orden del plan
  "evidence_rows": [<fila>, …],    // la fila más nueva de cada gate de ai.feature_gates
  "value": <valor>,
  "violations": [],                // vacío si la regla se cumple
  "rule_holds": true
}

<gate> = {
  "id", "name", "piece", "code",
  "kind": "vivo" | "registrado" | "lab" | "muestra" | "dependencias",
  "status": una de las siete palabras, "approved": status == "PASA",
  "why": [frases], "threshold", "rejects_if",
  "evaluable_on": "AAAA-MM-DD" | null, "evaluated_on": "AAAA-MM-DD" | null, "when": "<frase>",
  "figures": [<cifra>], "checks": [<comprobación>], "failing_now": [ids de comprobación],
  "evaluator": {"module", "method", "verdict", "at", "preview", "window", "recorded_only_if"} | null,
  "recorded": <registro> | null, "lab": <lab> | null,
  "depends_on": [piezas], "note", "sources": [{"what", "where"}]
}

<cifra> = {"label", "value", "cases", "counted", "ci95": [inferior, superior] | null, "ci_method",
           "threshold", "interval_vs_threshold", "verdict", "source", "note"}
           // verdict null: la cifra no tiene veredicto propio (p. ej. las filas por versión de un
           // check de Gate B, o las cifras de IA-040 en G-FUENTES 1)

<comprobación> = {"id", "title", "verdict", "reasons": [frases], "numbers": {cifras planas}, "figures": [<cifra>]}

<registro> = {"table": "ai.feature_gates", "gate", "id", "at", "passed", "decided_by", "evidence_hash",
              "verdict", "window", "models"}
           | {"table": "ai.shadow_reports", "engine": "combined", "id", "at", "passed", "verdict", "window"}

<lab> = {"key", "code", "title", "protocol": {"version", "fingerprint", "framework", "registered"},
         "evaluated", "evaluated_on", "verdict", "metric", "estimate_unit", "rule", "result", "doc", "notes",
         "rows": [{"segment", "n", "n_unit", "blocks", "blocks_unit", "estimate", "ci95", "mde", "verdict",
                   "why", "weight": {"w", "ci95"} | null, "facts"}]}

<fila> = {"gate", "is_gate", "reads_as", "row": <registro de ai.feature_gates> | null}

<valor> = {"decides": false, "benefit_sources", "value_unit", "rule",
           "cost_window": {"version", "since", "until", "days", "calls", "usd", "usd_exact",
                           "ledger_usd_exact", "difference_usd", "reconciles", "opus_all_registered"} | null,
           "components": [<componente>]}

<componente> = {"id", "name", "path", "path_label", "parts", "note",
                "cost": {"usd", "usd_exact", "share_pct", "calls", "fixtures", "usd_per_fixture", "candidates",
                         "usd_per_candidate", "models": [{"model", "calls", "usd"}], "pace_30_days_usd",
                         // solo la crónica: "own_ledger": {"ledger", "calls", "usd"}, "pace_30_days_usd_own_ledger"
                         // solo la deliberación: "parts": {<parte>: {"usd", "calls"}}
                        } | null,
                "benefit": <beneficio>}

<beneficio> = {"status": "demostrado" | "no demostrado" | "pendiente por muestra" | "sin medir", "source", "measure",
               // con motores (ai-gate-v2):
               "engines": [{"engine", "report_id", "created_at", "window", "version", "verdict", "status",
                            "selections", "days", "rejected", "roi_kept", "roi_rejected", "diff", "se", "z",
                            "ci95_normal", "clv_kept", "clv_rejected",
                            "value_per_usd": {"value", "ci95", "unit", "why", "inputs" (solo con valor)}}],
                           // un motor sin informe: {"engine", "status": "sin medir", "why", "value_per_usd"}
               // con G-EVENTOS: "segments": [{"segment", "events", "matches", "d_pp", "ci95"}], "reading", "value_per_usd"
               // sin medida: "reading", "value_per_usd"
              }
```

Para la vista: el estado se muestra como viene y «aprobado» es solo `approved`; `value_per_usd.value` en `null` siempre trae su `why`; si `rule_holds` fuera `false` es un defecto del panel y la vista debe decirlo, no mostrar el panel como bueno. El endpoint y su contrato son otra pieza: este PR no los añade.

## 6. Foto del 11-nov-2026 (solo lectura)

En el contenedor del worker (imagen `5ae050a9c56a`), sin copiar ficheros al contenedor: el código de esta rama entró por la entrada estándar de `docker exec -i`, con `PGOPTIONS` de solo lectura y `statement_timeout` de 95 s; la sesión confirmó `transaction_read_only = on`, `repeatable read` y `95s`. Los módulos de la imagen que dan los veredictos (`gate_b`, `gate_research`, `gates`, `intervals`, `calendar`, `contracts.mcp`, `shadow`, `gating`) son idénticos byte a byte a los de main. Foto a las 15:06:20 UTC con el código de este PR; coste del 28-oct al 11-nov (14 días UTC). **La regla se cumple: 0 violaciones.** Resumen: PASA 1, NO PASA 2, RECHAZA 2, PENDIENTE POR TIEMPO REAL 2, PENDIENTE POR DEPENDENCIAS 9.

| Gate | Estado | Cifras (casos, IC95) |
| --- | --- | --- |
| Gate B | PENDIENTE POR TIEMPO REAL | 0 de 14 días desde el ancla del 11-nov (`match-v5` corrió por primera vez el 10-nov): evaluable el **25-nov** si nada cambia. Sin fila `gate_b`. La vista previa del 28-oct al 10-nov (no es evidencia) ya falla en inválidas, fugas y batería; ver sección 7 |
| Research v2 | **NO PASA** (sin registrar) | ventana completa del 4 al 10-nov: v2 encontró 333 de 1.308 hechos de v1 = 25,5 % [23,2; 27,9] (umbral ≥ 95 %) y 303 de 1.059 de quién juega = 28,6 % [26,0; 31,4]; búsquedas 366 frente a 384 (pasa); ninguna revisión ni decisión cita a v2; `evidence_known` 0 violaciones en 61.571 comprobaciones; 182 partidos y 1.308 hechos comparados |
| Gate A | PASA | fila 6, 3-nov 14:06 UTC; ventana del 27-oct al 2-nov, 7 días |
| Puerta de la capa IA | NO PASA | `combined` (fila 121, 11-nov 12:35 UTC, 60 días): Δ −0,0055 [−0,1435; 0,1325], z −0,079, 6.336 selecciones en 34 días, 1.293 rechazadas. `llm`: Δ −0,0748 [−0,2590; 0,1094], z −0,796 (2.223; 814 rechazadas). `rules`: Δ +0,1526 [−0,0089; 0,3141], z 1,853 (6.336; 725). `ma-v1` y `ma-v1-h`: insuficientes (273 y 272 selecciones en 7 días; 28 y 9 rechazadas). `cs-v1`: sin informe |
| G-COH | PENDIENTE POR DEPENDENCIAS | INT-A02 RECHAZA: 1X2 +0,0025 nats [−0,0001; +0,0053] (5.796), OU +0,0045 [+0,0002; +0,0107] (2.602), BTTS +0,0044 [−0,0027; +0,0146] (2.602) |
| G-PRECIO | PENDIENTE POR DEPENDENCIAS | espera INT-A06 |
| G-FUENTES 1 | PENDIENTE POR DEPENDENCIAS | medida de IA-040 (no es su veredicto), ítems web de 30 días sin nivel frente a ≤ 20 %: 3.560 de 6.074 = 58,6 % [57,4; 59,8] con el nivel guardado al escribir; 3.398 = 55,9 % [54,7; 57,2] con el registro de hoy; 284 = 4,7 % [4,2; 5,2] con las filas propuestas, en repetición |
| G-FUENTES 2 y 3 | PENDIENTE POR DEPENDENCIAS | — |
| G-EVENTOS | RECHAZA | D global 0,000 pp [−0,035; 0,036] (3.095 eventos, 371 partidos); ningún segmento con el intervalo por encima de 0 |
| G-E4 | RECHAZA | resto 1X2 +0,0061 nats [−0,0007; +0,0127] con peso −0,378 [−0,632; −0,164]; resto OU −0,0094 [−0,0140; −0,0053] con peso +0,068 [−0,193; +0,329]; prioritarias pendientes por muestra (281 partidos < 1.500) |
| G-E6 | PENDIENTE POR DEPENDENCIAS | INT-A08 sin protocolo registrado |
| G-DELIB, G-CRON, F-Player | PENDIENTE POR DEPENDENCIAS | — |
| P1 | PENDIENTE POR TIEMPO REAL | 0 de 30 días desde el 11-nov: no antes del **11-dic**. `ma-v1` y `ma-v1-h`: 2 (1X2), 3 (CORNERS) y 1 (OU) selecciones, ninguna con el partido terminado; `cs-v1`: ninguna |

**Coste del 28-oct al 11-nov** (14 días UTC): US$ 65,76 en 8.390 llamadas; cuadra con `ai.usage` al céntimo (diferencia 0,000000) y todo Opus está registrado.

| Componente | US$ | Parte | Llamadas | US$ por candidato | Ritmo a 30 días | Beneficio | Valor por dólar |
| --- | ---: | ---: | ---: | ---: | ---: | --- | --- |
| Revisión de producción (`review-v2`) | 34,38 | 52,3 % | 944 | 0,0413 (833) | 73,67 | no demostrado (`llm` NO PASA) | — |
| Lectura del partido (`brief-v8`) | 11,32 | 17,2 % | 3.686 | — | 24,25 | sin medir | — |
| Research: búsquedas de Exa | 11,04 | 16,8 % | 736 | — | 23,66 | no demostrado (G-EVENTOS) | — |
| Deliberación en sombra | 5,40 | 8,2 % | 1.178 | 0,0124 (435) | 11,57 | pendiente por muestra | — |
| LAB | 1,67 | 2,5 % | 842 | — | 3,57 | sin medir | — |
| Research: extracción | 0,65 | 1,0 % | 799 | — | 1,40 | no demostrado (G-EVENTOS) | — |
| Aprendizaje y patrones | 0,95 | 1,4 % | 28 | — | 2,04 | sin medir | — |
| Post-mortems | 0,36 | 0,5 % | 177 | — | 0,77 | sin medir | — |
| Crónica de lectores | 0,00 + 2,23 en su libro | — | 0 + 1.306 | — | 4,78 (su libro) | sin medir | — |
| Otros | 0,00 | 0,0 % | 0 | — | 0,00 | sin medir | — |

**Ningún componente tiene hoy valor por dólar**: ningún `ai-gate-v2` está en PASA y G-EVENTOS no encontró ventaja de la web frente al precio.

## 7. Lo que la foto deja a la vista

- **Research v2 no pasa su gate y el Gate B lo necesita.** Su evaluador da NO PASA sobre una ventana completa (v2 encuentra el 25,5 % de lo que encuentra v1), pero no hay fila registrada: el Gate B lo lee como «nunca evaluado». El Gate B pide el gate de Research v2 en PASA, así que **no puede pasar el 25-nov mientras Research v2 no tenga una fila en PASA**, aunque todo lo demás pase. Registrarlo es `python -m scripts.ia_research_gate evaluate --record` (solo vale para la ventana que acabó ayer), nunca el panel. La consecuencia que escribe el evaluador: v2 sigue en sombra, se corrige con versión nueva y la semana de comparación vuelve a empezar.
- **Vista previa del Gate B** (28-oct a 10-nov, antes del ancla; no es evidencia): fallan las inválidas por versiones viejas (`match-v1` 33 de 88, `stats-v2` 8 de 35…; `match-v5` solo tiene 8 respuestas), la auditoría de fugas (`slice_known` el 31-oct, 4-nov y 7-nov; `shadow_review_known` sin fila el 3-nov; 12 reglas-noche sin auditar) y la batería (la fila 16, del 10-nov, dice NO PASA). Falta además una acción tuya: escribir los días excluidos previstos del LAB (`python -m scripts.ia_gate_b set-lab-plan --days N --reason "..." --confirm-owner`); van 3.
- **La revisión de producción es la mitad del gasto sin beneficio demostrado**: `review-v2` cuesta US$ 34,38 en 14 días (52,3 %) y lo que rechaza no rinde peor que lo que guarda (z −0,796). El panel no propone nada: qué hacer con ello es tuyo (condiciones de P2).
- **G-FUENTES 1** sigue lejos del 20 % mientras el registro depurado no esté en la sombra: el 58,6 % de los ítems web de IA-040 viene de dominios sin nivel, y con sus filas propuestas quedaría el 4,7 % (repetición, no medida en la sombra). Una cuenta de solo lectura del 11-nov a las 14:31 UTC con la consulta de IA-040 sobre los 30 días anteriores (v1 y Research v2 juntos) dio 3.573 de 6.125, 58,3 % [57,1; 59,6]: no se ha movido.

## 8. Qué no cambia y vuelta atrás

- No registra ningún gate (nunca `--record`) ni cambia umbrales, interruptores, agentes, prompts, motores, la muestra de sombra, picks ni `decision-v1`. No toca `fbi/ai/costs_v3.py` ni la lógica de ningún gate.
- Sin endpoint, sin contrato de la API, sin migración y sin cambios en `web/`.
- Vuelta atrás: revertir el PR. No hay migración, interruptor ni endpoint que deshacer.
