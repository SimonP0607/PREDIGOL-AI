# PM-11-05 · Salidas inválidas de Claude, por causa y agente

Plan Maestro PM, ola 1. Medición de solo lectura del **20-nov-2026, 01:36 UTC** sobre `ai.usage` (append-only: una fila por
llamada), 0 peticiones, 0 USD. Código del PR que deja esta guía: OPS-010. **No se cambia nada** (`fbi/ai/outputs.py` queda igual).

## Qué se cuenta

* `ai.usage.status = 'invalid_output'`: la llamada no dio una respuesta usable. Dos orígenes: el validador común
  (`output-guard-v1`, error `output_guard: <motivo>@<ruta>; …`, modo **enforce**: la respuesta se tira) y el proveedor o el
  lector (`invalid_output: the model did not submit the answer`, `… does not parse`).
* `ai.usage.error LIKE 'output_guard(shadow): %'` con `status = 'ok'`: el validador la habría rechazado, pero esa superficie
  está en **sombra** y la respuesta siguió su camino (lo que hace cada lector con ella es cosa suya).
* El validador nunca guarda el valor ni una clave inventada por el modelo (una respuesta puede venir de un atacante): solo el
  motivo y la ruta del esquema. Ningún error llega a los 300 caracteres del campo (0 truncados).

## Resultado

`ai.usage`: 28.320 llamadas del 8-oct al 20-nov-2026. El validador empezó a anotar el 17-nov-2026 a las 08:10 UTC.

| Origen | Llamadas | Coste | Desde |
|---|---:|---:|---|
| Validador, enforce (`invalid_output`) | 61 | 0,07 USD | 17-nov |
| Validador, sombra (`ok` con aviso) | 72 | 0,19 USD | 17-nov |
| Proveedor o lector (`invalid_output`) | 26 | 0,04 USD | 15-nov |

Por motivo (llamadas distintas; una llamada puede tener varios):

| Motivo | Enforce | Sombra | Dónde |
|---|---:|---:|---|
| `missing_field` | 57 | 11 | 56 en `match_brief` · `chronicle-v4` (enforce); 10 en `brief-v8`; 1 `extract-v3`; 1 `extract-v1` |
| `extra_field` | 4 | 43 | 43 en `brief-v8` (sombra); 4 en `claim_extractor` · `extract-v3` |
| `not_in_enum` | 1 | 23 | 21 en `evidence_extraction` · `extract-v1` (`items[].kind`); 2 en `brief-v8` (`data_quality`, `research[].topic`, `uncertainty`); 1 en `council-v1` (`verdicts[].risks[]`, enforce) |
| `wrong_type` | 0 | 9 | `brief-v8` |
| `text_control` | 0 | 1 | `extract-v1` |
| «the model did not submit the answer» | 23 | — | 22 `match_brief`, 1 otra |
| «JSON does not parse» | 3 | — | 2 otras, 1 `stats` |

Proporción desde el 17-nov (marcadas o inválidas sobre llamadas): `match_brief` 106 de 319 (40 %, sobre todo
`chronicle-v4` en enforce); `evidence_extraction` 22 de 86 (26 %); `claim_extractor` 4 de 84 (5 %); `council` 1 de 24.
Fuera de `ai.usage`: `ai.agent_runs` 102 filas `invalid`, `ai.user_narratives` 60 `invalid_output`, `ai.batch_items`
81 `invalid` y 210 `errored` con `invalid_request_error` (petición rechazada, no salida inválida).

## La hipótesis de las mayúsculas (`not_in_enum`)

`fbi/ai/outputs.py` compara el valor de un enumerado por igualdad exacta (`value == e` y mismo tipo), así que `"Injury"` no es
`"injury"`. **No se puede confirmar ni descartar con los registros**: el validador no guarda el valor por diseño, y el lector de
`extract-v1` (`fbi/ai/collectors.py`) descarta en silencio el elemento cuyo `kind` no está en su lista, sin guardarlo. Lo que sí
se sabe: son **25 llamadas** con `not_in_enum` en tres días, **24 en sombra** (el validador no tiró nada) y 1 en enforce
(`council-v1`). En `extract-v1` se pierden elementos sueltos, no la respuesta entera.

**Decisión (ficha PM-11-05):** el recuento no justifica cambiar `outputs.py`. La causa que más respuestas tira es
`missing_field` de `chronicle-v4` (56 en enforce), no el enumerado. Si se quiere probar la hipótesis, la forma limpia es una
sonda fijada (`pinned`) que guarde el valor crudo de `items[].kind` en el laboratorio, no tocar el validador de producción.

## Consulta reproducible

```
SELECT m[1] AS motivo, CASE WHEN u.error LIKE 'output_guard(shadow)%' THEN 'sombra' ELSE 'enforce' END AS modo,
       coalesce(u.agent, u.purpose) AS quien, u.prompt_version, count(DISTINCT u.id)
  FROM ai.usage u
 CROSS JOIN LATERAL regexp_matches(u.error, '(not_an_object|missing_field|extra_field|wrong_type|not_in_enum|too_few_items|'
                                            'too_deep|text_link|text_markup|text_order|text_control|repeat_after_invalid)@', 'g') m
 WHERE u.error LIKE 'output_guard%'
 GROUP BY 1, 2, 3, 4 ORDER BY 5 DESC;
```

y las rutas de `not_in_enum` con `regexp_matches(u.error, 'not_in_enum@([^;]+)', 'g')`. Siempre con
`SET default_transaction_read_only=on; SET statement_timeout='90s'`. Guion completo: `fbi_scratch\pm\b_q1105.sh`.

## Vuelta atrás

No hay nada que revertir: la medición solo lee.
