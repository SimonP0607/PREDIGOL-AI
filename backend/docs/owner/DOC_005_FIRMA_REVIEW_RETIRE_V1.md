# DOC-005 · Paquete de firma de `review-retire-v1` y calendario de retiradas (PM-13-01, DM-10)

Fecha: 19 nov 2026. Tarea PM-13-01 del Plan Maestro PM. **Solo documentación: no cambia código, interruptores ni datos, y no retira
nada.** Cada retirada se hace cuando su comparación preregistrada se cumple, nunca antes.

Marcas: [M] medido en producción el 19-nov-2026 (solo lectura); [C] leído en el código de `main` (`b8f0aca`).

## 1. La decisión del dueño

El 19-nov-2026 el dueño escribió: «Apruebo las recomendaciones documentadas para cada decisión». Eso incluye **DM-10** del registro de
decisiones del plan, cuya recomendación es:

| Asunto | Recomendación aprobada |
| --- | --- |
| `review-retire-v1` | **Firmar** |
| Brazo Haiku del Council | Retirar, porque el banco C02 no pasa |
| `/odds/best` y la página antigua de cuotas | Retirar cuando el recuento de uso dé cero |

Esta guía deja esa aprobación **fechada y por escrito**. Lo que todavía no está es su fila en la base (apartado 3).

## 2. Qué se firma

`review-retire-v1` es la comparación preregistrada que decide si `review-v2` (la revisión con Sonnet y Opus) se puede retirar
(pieza AD-D11, IA-125; guía `IA_123_LECTORES_Y_COUNCIL_REDUCIDO.md`, apartado 3). Vive en `backend/src/fbi/ai/review_retirement.py`
(`PROTOCOL`) [C]. Sus cifras:

| Campo | Valor |
| --- | --- |
| Población | Selecciones que `review-v2` revisó con modelo y que `decision-v2` decidió en sombra antes del saque, con evaluación `eval-sel-v1` y precio de cierre (`clv-v1`) |
| Referencia | `review-v2`: la selección se queda si la revisión combinada más reciente antes del saque es APPROVE |
| Camino nuevo | `decision-v2` + reglas + Council reducido: se queda si `decision-v2` la toma |
| Métrica | Diferencia pareada por selección examinada: CLV × (se queda en el nuevo − se queda en `review-v2`) |
| Intervalo | IC95 bilateral por remuestreo de días enteros de Bogotá, 2.000 réplicas, semilla 20261117 |
| Regla | NO_INFERIOR si el extremo inferior del IC95 ≥ −0,005; INFERIOR si no; INSUFICIENTE bajo la muestra |
| Muestra mínima | 300 selecciones y 14 días |
| Ventana | Las 4 semanas siguientes a la firma; nada anterior cuenta |
| Grupo de control del paso `sample` | 20 % fijo de las selecciones (sal `review-v2-control-v1`) |

**Huella del texto aprobado.** SHA-256 de `PROTOCOL` en su forma canónica (claves ordenadas, sin espacios, UTF-8; la misma de
`fbi/research/protocol.py`) en `main` `b8f0aca`:

`0e8938f4dfbf354308ef26c718e32ffd66ccc69d7745abbcae12a6b7d58c1df8`

Se recalcula en el worker con:

```
docker exec -w /app predigol-worker python -c "import json,hashlib; from fbi.ai import review_retirement as r; print(hashlib.sha256(json.dumps(dict(r.PROTOCOL), sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()).hexdigest())"
```

Si da otra huella, el protocolo cambió después de esta guía y lo aprobado ya no es ese texto: no se firma sin volver a preguntar.

## 3. Cómo se firma de verdad, y por qué hoy no queda la fila

**El procedimiento** es el de `IA_143_FIRMA_DE_PROTOCOLOS.md`: el comando `scripts.ia_protocols sign --key … --fingerprint … --reason …
--confirm-owner` escribe una fila en `ai.protocol_signatures` (solo añadir; `decided_by = 'owner'`; la huella debe ser la vigente; el
motivo, de 10 a 600 caracteres). **Admite registrar una aprobación escrita del dueño:** así se registraron el 18-nov-2026 a las 00:08 UTC
las 11 firmas que hay hoy (AD-A03, AD-B03, AD-B07, AD-C08, AD-C09, AD-F04, AD-F05, AD-F06, AD-K02, AD-K03, AD-K04), con el motivo
«Aprobado y firmado por el dueño en el chat del 17-nov-2026 …» [M].

**Por qué no se puede escribir hoy.** `review-retire-v1` **no está en el catálogo de protocolos firmables** (`fbi.protosign.catalog()`:
16 claves, los 13 de laboratorio y AD-F04/F05/F06) [C], y el comando rechaza una clave que no está en él. En producción, el 19-nov a las
22:20 UTC, `ai.protocol_signatures` tiene esas 11 filas y ninguna de AD-D11 [M]. Para firmarlo hace falta **registrarlo** como protocolo
firmable (clave AD-D11): un registro propio en `fbi/protosign/records.py` cuyas cifras sean las de `review_retirement.PROTOCOL`, con su
huella fijada por `tests/unit/test_protocol_signatures.py`. Eso es código de la zona de la sesión de Intelligence (`fbi/protosign`), y esta
tarea no lleva código.

**Estado:** aprobación del dueño registrada aquí (19-nov-2026); firma en la base **pendiente del registro de AD-D11 por la sesión de
Intelligence**. No hace falta que el dueño vuelva a decidir.

**El paso único, cuando AD-D11 esté registrado y desplegado** (lo ejecuta la sesión o el dueño; primero sin `--confirm-owner` para la vista
previa):

```
docker exec -w /app predigol-worker python -m scripts.ia_protocols show --key AD-D11
docker exec -w /app predigol-worker python -m scripts.ia_protocols sign --key AD-D11 --fingerprint <huella de show> --reason "Aprobado por el dueño por escrito el 19-nov-2026 (Plan Maestro PM, DM-10: «Apruebo las recomendaciones documentadas para cada decisión»): protocolo preregistrado antes de mirar los datos" --confirm-owner
```

Antes de firmar, comprobar que el texto de `show` dice las cifras del apartado 2. **La ventana de 4 semanas empieza con la fila de la
firma** (`signed_at`), no con esta guía: así ninguna selección anterior a la firma cuenta.

## 4. Calendario de retiradas

Retirar es apagar con su interruptor, por pasos; no se borra ninguna fila ni tabla.

| Candidato | Estado [M]/[C] | Comparación | Condición para retirar | Fecha más temprana | Quién |
| --- | --- | --- | --- | --- | --- |
| `review-v2` y Opus en la revisión | Activo: `FBI_REVIEW_V2` en `on` (por defecto) | `review-retire-v1` (apartado 2) | Firma en la base; después NO_INFERIOR con ≥ 300 selecciones y ≥ 14 días dentro de las 4 semanas siguientes. Pasos `no_opus` → `sample` → `off`, cada uno con `effect_of_removal` medido antes | Firma + 14 días; la ventana cierra a firma + 28 días | Intelligence (registro y firma); el paso del interruptor, con kit auditado |
| `/odds/best` y la página antigua de Cuotas | En `main`. `audit.deprecated_api_use`: **ninguna fila `browser`**; una sola fila `testclient` del 10-nov | Siete días sin uso de navegador y visto bueno | Siete días seguidos sin filas `browser` desde el 17-nov (se cumplen al terminar el 23-nov) y volver a leer el recuento ese día. Visto bueno: dado el 19-nov | **24-nov-2026**, tras releer el recuento | Sesión de Cuotas/UX (`routers/odds_explorer.py`, `web/src/product/odds/*`) |
| Brazo Haiku del Council (`ma-v1-h`) | En sombra: `FBI_AI_ENGINES` lo incluye | Banco de repetición C02 (INT-C02) | El veredicto del banco C02 dice que no pasa | Con el veredicto del banco, hacia el 20-dic-2026 | Intelligence: quitar `ma-v1-h` de `FBI_AI_ENGINES` (kit `ia-switch-*`) |
| Crónica `user-narrative-v3` | Activa | `retire-compare-v1` (AD-F05), firmado el 18-nov | 100 partidos de `chronicle-v4` con resultado no peor | Cuando haya la muestra | Intelligence |
| `brief-v8` y `match-analysis-v1` | Activos, sin interruptor propio | La misma (AD-F05) | La misma, y una pieza que les dé interruptor | Tras esa pieza | Intelligence con la sesión UX |
| Council completo | Activo | AD-D10 y AD-K03, firmados | Muestra suficiente | Cuando haya la muestra | Intelligence |
| Extractores v1 a v3 | v1 en producción | AD-A01 y AD-C09 | Etiquetas humanas del banco de páginas | Tras las etiquetas del dueño | Intelligence |

Ahorro estimado por el Plan AD si se cumplen: unos 85 USD al mes (estimación, no medición). `review-v2` es del 52 al 76 % del gasto de
Claude.

## 5. Vuelta atrás

Esta guía no cambia nada. Una firma no enciende nada (IA-143) y no se borra: si el dueño cambia de opinión, se deja escrito con una decisión
nueva y no se ejecuta ningún paso. Cada paso de retirada vuelve atrás con su interruptor (`FBI_REVIEW_V2=on`, `FBI_AI_ENGINES` con
`ma-v1-h`, un `revert` del PR que retire `/odds/best`).
