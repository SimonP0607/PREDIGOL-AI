# IA-056 · Registro de capacidades (AD-003) · con IA-059 · Auditoría e históricos (AD-A07)

Piezas AD-003 y AD-A07 del plan de la arquitectura definitiva 2026 (aprobado el 16-nov-2026). Añaden un **registro** que dice en qué
estado está cada capacidad del plan y por qué, y hacen que **las copias de seguridad demuestren** que vuelven todos los esquemas y todas
las tablas de solo añadido. No encienden, apagan ni cambian nada de lo que hacen los agentes, los motores, los picks o el lector.

## 1. Qué hace el registro

Cada capacidad pasa por cuatro estados, siempre en este orden:

| Estado | Qué significa |
| --- | --- |
| `construida` | El código está desplegado, apagado o aún sin sombra. |
| `en_sombra` | Funciona en sombra: nada llega a un lector. |
| `lista_para_revision` | Su seguridad dio **PASA** y su validación tiene un veredicto medido con su muestra: el dueño puede revisarla. |
| `autorizada` | **El dueño la firmó.** Solo el dueño puede escribir este estado. |

Cada paso es una fila nueva de `intel.capability_transitions` (tabla de solo añadido) con dos veredictos:

- **Seguridad**: `PASA`, `NO PASA`, `PENDIENTE POR ACCIONES MANUALES`, `PENDIENTE POR DEPENDENCIAS` (las palabras de los gates).
- **Validación**: `VALIDADO`, `NO VALIDADO`, `INSUFICIENTE` (siempre con su tamaño de muestra), o pendiente.

Las reglas, que comprueban a la vez el código y la propia base de datos:

1. **No se salta ningún estado** hacia delante. Hacia atrás (retirar) se puede siempre, con su motivo.
2. **«autorizada» exige la firma del dueño** (`--confirm-owner` y una frase suya) y una seguridad `PASA`. El sistema nunca puede escribirla.
3. **Solo la seguridad frena**: con `NO PASA` la capacidad se queda en `construida`. Una validación desfavorable (`NO VALIDADO`,
   `INSUFICIENTE`) se anota tal cual y no bloquea; la consola la muestra como «no validada», nunca como validada.
4. **Nada avanza mientras un gate del que depende dice NO PASA** (la última fila de `ai.feature_gates`, por ejemplo `battery`).
5. **Nada se promociona solo**: cada fila la escribe un comando que ejecuta una persona. Y «autorizada» es una firma, no un interruptor:
   encender algo para lectores sigue siendo tu cambio de interruptor, aparte.

## 2. Qué hay hoy (siembra de la migración 0138)

Siete capacidades del plan que **ya corren en sombra**, comprobado en producción en solo lectura el 16-nov-2026 a las 20:45 UTC, con
filas de los últimos 7 días:

| Capacidad | Pieza | Interruptor | Lo que se vio (7 días) |
| --- | --- | --- | --- |
| `research_v2` | AD-C05 | `FBI_AI_RESEARCH_V2` (`shadow`) | 854 evidencias tipadas en 182 partidos (`ai.evidence`) |
| `readers` | AD-D09 | `FBI_AI_AGENTS` (`match,council,stats`) | 152 ejecuciones de Partido y 29 de Estadísticas (`ai.agent_runs`) |
| `council` | AD-D10 | `FBI_AI_AGENTS` | 178 ejecuciones de `council-v1`; 375 revisiones `ma-v1` en sombra |
| `haiku_arm` | AD-D10 | `FBI_AI_ENGINES` | 375 revisiones `ma-v1-h` en sombra (`ai.pick_reviews`) |
| `family_decisions` | AD-B07 | `FBI_FAMILY_DECISIONS` (`shadow`) | 11.125 decisiones `decision-fam-v1` (`intel.decisions`) |
| `attribution` | AD-K03 | `FBI_AI_PM_REVIEWER` (encendido) | 1.423 atribuciones `attr-v1` |
| `chronicle_review` | AD-F06 | sin interruptor (trabajo del worker) | 290 revisiones en total; la última, 16-nov 20:03 UTC |

Las palabras de los interruptores salen del libro de palabras del dueño (`ai.feature_gates`, fila 13, gate `switches`), no de `app.env`.

**No se inventa ningún veredicto**: las siete entran con seguridad `PENDIENTE POR ACCIONES MANUALES` (el registro aún no la ha juzgado)
y validación `PENDIENTE POR DEPENDENCIAS` (el tablero de validación por mercado, AD-K02, no existe aún). Al lado, la consola muestra la
última fila de cada gate del que dependen: hoy `battery` (fila 18, 15-nov) y `research_v2` (fila 17, 12-nov) dicen **NO PASA**, así que
`research_v2`, `readers`, `council` y `haiku_arm` aparecen con el aviso «no puede avanzar».

**Lo que no se sembró, y por qué**: el pronóstico (`forecast-v1`) y el conocimiento del partido terminado (`mk-v1`) ya los ven los
lectores desde el plan UX A9 por decisión tuya; su estado sería «autorizada» y eso necesita tu firma, que nadie ha anotado aquí.
`review-v2` (con `FBI_AI_MODE`) espera a la transición a `shadow` de AD-002. `player`, `cs-v1` y el analista de aprendizaje no están
encendidos. Cada pieza nueva del plan añade su capacidad al catálogo y entra como `construida` al desplegarse.

## 3. Cómo se usa

En el servidor, dentro del worker (todo lo que no lleva `--write` es de solo lectura):

```
docker exec -w /app predigol-worker python -m scripts.ia_capabilities list
docker exec -w /app predigol-worker python -m scripts.ia_capabilities history --key council
docker exec -w /app predigol-worker python -m scripts.ia_capabilities sync            # qué faltaría registrar
docker exec -w /app predigol-worker python -m scripts.ia_capabilities sync --write    # registra las nuevas como «construida»
```

Proponer un paso: primero sin `--write` (se comprueba y se enseña, no se escribe); después con `--write`. Para **autorizar**, solo tú:

```
python -m scripts.ia_capabilities propose --key council --to autorizada --safety PASA --safety-evidence '{"gate":"battery","fila":NN}' \
  --validation VALIDADO --sample 412 --validation-evidence '{"protocolo":"..."}' --reason "..." \
  --signature "Autorizo el Council, el dueño, AAAA-MM-DD" --confirm-owner --write
```

En la consola: `GET /api/v1/admin/intelligence/capabilities` (solo administradores, `require_admin`). Ejemplo de la respuesta en
`backend/tests/fixtures/contracts/intelligence/admin_capabilities.json`. Nada del registro está en ninguna respuesta para lectores.

## 4. IA-059 · Auditoría e históricos (AD-A07)

- **Tablas nuevas de solo añadido.** Las dos del registro llevan el disparador `*_append_only` (`intel.refuse_change()`): un UPDATE o un
  DELETE falla. Una corrección es siempre una fila nueva. Una prueba (`tests/unit/test_append_only_new_tables.py`) **falla si una
  migración del plan (0138 en adelante) crea una tabla en `ai`, `intel` o `news` sin ese disparador**, salvo que se apunte en esa prueba,
  a la vista, con el motivo.
- **Versiones encadenadas.** Una versión nueva de una entrada del catálogo nombra la que sustituye (`supersedes`) y cada fila del registro
  nombra la anterior (`previous_id`); la base solo admite un sucesor por fila, así que la cadena no se bifurca ni se reescribe.
- **Copias y prueba de restauración.** `pg_dump` copia la base entera, sin lista de esquemas: un esquema nuevo (por ejemplo `news`) ya
  entra solo. Ahora la copia diaria y la de cada despliegue **anotan en su manifiesto todos los esquemas y todos los disparadores de solo
  añadido**, y la prueba de restauración **falla si alguno no vuelve**. La última prueba antes de este cambio (16-nov 20:32 UTC, copia
  `predigol-20261116T195712Z-auto-e821168`, revisión 0137) pasó en 1.283 s, sin esta comprobación. Una copia anterior a este cambio se
  sigue probando como antes (su manifiesto no trae la lista). Lo mismo en las copias del equipo de desarrollo (`fbi.ops.backup`).

## 5. Qué no cambia

Ningún interruptor, gate, umbral, agente, prompt, motor, muestra de la sombra, pick ni pantalla de lector. `decision-v1` no se toca.
No hay coste de API. La migración solo añade dos tablas vacías más la siembra (siete entradas y siete filas).

## 6. Cómo se apaga o se revierte

- El endpoint y el comando se retiran revirtiendo el PR. Las tablas se quedan con sus filas (son de solo añadido); si hiciera falta
  quitarlas, la vuelta atrás de la migración 0138 las borra (exporta antes las filas que tengan tu firma).
- La comprobación de las copias se revierte con el PR; si diera un falso fallo, la cadena de despliegue se pararía en la prueba de
  restauración: el arreglo es revertir los dos guiones (`backup.sh`, `restore-test.sh`), sin tocar la base.
