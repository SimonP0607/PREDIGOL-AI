# IA-143 · Firma de protocolos: registrar que usted aprobó un protocolo antes de mirar los datos

Fecha: 17 nov 2026. Pieza AD-K07 («cada promoción con firma») del plan de la arquitectura definitiva 2026. Añade **un registro de firmas de
protocolos** (migración 0166, una tabla de solo añadido) y un comando del dueño. **Una firma no activa nada.** Sin cambios en la web, sin
efecto en el lector. Ningún protocolo está firmado hoy: firmar es una acción suya.

## 1. Qué hace

* **Una tabla de solo añadido**, `ai.protocol_signatures`: cada fila es la firma de usted de **un** protocolo en **una** huella concreta
  (clave, versión, la huella sha256 que firma, su motivo con sus palabras de 10 a 600 caracteres, `decided_by = 'owner'` —la base no
  acepta otro valor—, la hora y la versión del código). No se puede cambiar ni borrar una fila (la base lo rechaza).
* **Solo vale la firma de la huella vigente.** La huella es el sha256 del texto canónico del protocolo. Si alguien cambia un protocolo,
  su huella cambia y su firma anterior deja de contar (se conserva, pero los lectores la cuentan como «de otra huella»): hace falta una
  firma nueva. El comando rechaza firmar una huella que no es la que el código tiene ahora.
* **Los lectores leen la firma.** Los que antes escribían `signed_by_owner: False` fijo ahora dicen si hay firma de la huella vigente
  (falso si no la hay, o si la base aún no tiene la tabla): el tablero `board-v1` (y con él C-03 y C-08), el informe de rendimiento
  `perf-v1`, la crónica (coletillas, comparación de retirada y revisión por muestreo) y la consola C-11, que añade un bloque
  `protocols` (C-11 pasa a 1.1.0) con cada protocolo, su huella y si está firmado.
* **Qué protocolos se pueden firmar** (17 desde IA-145; eran 16): los 13 de laboratorio de `fbi/research/protocol.py` —sus huellas no cambian— y los tres de la
  crónica de IA-117..IA-119, que eran registros propios de sus módulos y ahora tienen huella propia (`fbi/protosign/records.py`, con una
  prueba que obliga a que cada cifra sea la que la crónica aplica): **AD-F04** (umbrales de coletillas), **AD-F05** (comparación
  preregistrada para retirar textos duplicados) y **AD-F06** (revisión humana por muestreo). **IA-145** (20-nov-2026) añade del mismo modo
  **AD-D11** (`review-retire-v1`, la comparación preregistrada para retirar `review-v2`, IA-125): su registro es `PROTOCOL` de
  `fbi/ai/review_retirement.py` palabra por palabra más el control del paso `sample` (20 %, sal `review-v2-control-v1`), y una prueba
  obliga a que sean iguales. Su firma no mueve `FBI_REVIEW_V2`: cada paso de la retirada sigue siendo un cambio de interruptor aparte.

## 2. Qué NO hace

* **Ninguna firma enciende, promociona ni cambia un umbral.** Ningún veredicto cambia por estar firmado su protocolo (las pruebas lo
  comprueban: el tablero, el informe y la puntuación de la hoja dan lo mismo con y sin firma). Poner `FBI_CHRONICLE_REPEAT=on`, retirar
  un texto o promocionar una celda siguen siendo acciones suyas aparte (interruptor o propuesta firmada de IA-139).
* No sustituye a las firmas propias de **AD-A03** (battery-v4) y **AD-C09** (protocolo de extracción), que ya existen en `ai.feature_gates`
  y son las que su medición exige: `list` y `show` le dicen su comando (`ia_battery_v4 sign` / `ia_page_bank sign`) y dónde verlas.
* No toca `decision-v1`, `FBI_PICKS_SOURCE`, picks, prompts, modelos ni la web. Nada sale de la sombra.
* **Una firma tardía no preregistra.** Si un protocolo ya se usó para medir, su firma de hoy dice «este es el protocolo que apruebo» con la
  fecha de hoy; la fecha de registro la da `registered_on` y git. El listado muestra las dos.

## 3. Cómo se firma (tres pasos, con la huella que da `show`)

1. **Ver el protocolo entero y su huella vigente** (no escribe nada):
   `docker exec -w /app predigol-worker python -m scripts.ia_protocols show --key AD-K02`
   Lea `protocol` (el texto completo). `fingerprint` es la huella a firmar; `sign` trae el comando exacto ya rellenado.
2. **Vista previa** (sin `--confirm-owner`; no escribe nada; sale con 3):
   `docker exec -w /app predigol-worker python -m scripts.ia_protocols sign --key AD-K02 --fingerprint <huella> --reason "Su motivo"`
3. **Firma** (la misma línea con `--confirm-owner`; sale con 0). Repetirla no escribe dos veces: dice qué fila ya la firma.

Para ver todo de un vistazo: `docker exec -w /app predigol-worker python -m scripts.ia_protocols list` (cada protocolo, su huella, si está
firmado y, si no, su comando de firma). Códigos de salida: 0 hecho, 1 rechazado por las reglas (no se escribió nada), 2 error de uso,
3 vista previa.

## 4. Los protocolos pendientes y su comando exacto

| Clave | Versión | Qué es | Registrado | Huella vigente | Quién lee la firma |
| --- | --- | --- | --- | --- | --- |
| `INT-A02` | `proto-int-a02-v1` | Calibración coherente multiclase | 2026-11-11 | `2a1cdb3ec31a…` | solo la consola C-11 y este comando |
| `INT-A09` | `proto-int-a09-v1` | E4: tiros y xG en los ratings | 2026-11-11 | `400778f85de7…` | solo la consola C-11 y este comando |
| `INT-B09` | `proto-int-b09-v1` | Estudio de eventos: noticia → precio | 2026-11-11 | `2b8e49fb115f…` | solo la consola C-11 y este comando |
| `INT-A08` | `proto-int-a08-v1` | E6: quién juega, en el modelo | 2026-11-11 | `a37fdb4265f4…` | solo la consola C-11 y este comando |
| `INT-C02` | `proto-int-c02-v1` | Banco de repetición: la variante actual reproduce la sombra | 2026-11-11 | `f954582c9594…` | solo la consola C-11 y este comando |
| `AD-A03` | `proto-ad-a03-v1` | battery-v4: batería adversaria que separa ataque de variabilidad | 2026-11-16 | `205e671347e7…` | solo la consola C-11 y este comando |
| `AD-B03` | `proto-ad-b03-v1` | Sello estable: el calibrador campeón con un precio de más de 6 horas | 2026-11-16 | `989b82a53fe3…` | solo la consola C-11 y este comando |
| `AD-B07` | `proto-ad-b07-v1` | Córners y tarjetas: calibrador de conteos por familia (count-cal-v1) | 2026-11-17 | `aac10f7f5cc4…` | solo la consola C-11 y este comando |
| `AD-K02` | `proto-ad-k02-v1` | Tablero de validación por mercado y familia (board-v1) | 2026-11-17 | `6eff7d3066cb…` | el tablero `board-v1`: C-03 (seguimiento), C-08 (evaluación posterior), la vista de una selección y `ia_selection_eval` |
| `AD-C08` | `proto-ad-c08-v1` | Credibilidad de fuentes por tipo de hecho (credibility-v2) | 2026-11-17 | `7ae65569c4f3…` | solo la consola C-11 y este comando |
| `AD-C09` | `proto-ad-c09-v1` | Medición de la extracción frente a etiquetas humanas de páginas enteras (extract-protocol-v1) | 2026-11-17 | `f0bd0d90c774…` | solo la consola C-11 y este comando |
| `AD-K03` | `proto-ad-k03-v1` | Rendimiento de lectores y fuentes frente a las reglas (perf-v1) | 2026-11-17 | `c5638110bd73…` | el informe `perf-v1` (`ia_reader_performance report`) |
| `AD-K04` | `proto-ad-k04-v1` | Banco de repetición como prueba de regresión con tolerancia (replay-regression-v1) | 2026-11-17 | `9d37ca84b4db…` | solo la consola C-11 y este comando |
| `AD-F04` | `repeat-check-v1` | Coletillas y repeticiones de la crónica única: umbrales | 2026-11-17 | `17c942303fbc…` | `metrics.repetition.thresholds.signed` de cada crónica nueva (`repeat-check-v1`) |
| `AD-F05` | `retire-compare-v1` | Retirada de los textos duplicados: la comparación preregistrada | 2026-11-17 | `1fbeadbddd16…` | `ia_chronicle_eval compare` (`rule.signed`) |
| `AD-F06` | `chronicle-protocol-v1` | Evaluación factual de la crónica única: revisión humana por muestreo | 2026-11-17 | `33b296c7c385…` | `ia_chronicle_eval protocol`, `sample` y `score` |
| `AD-D11` | `review-retire-v1` | Retirada de review-v2: comparación preregistrada de no inferioridad frente al cierre (IA-145) | 2026-11-17 | `0fdd2a7145b5…` | solo la consola C-11 y este comando |

Comandos de firma (cambie `"..."` por su motivo, de 10 a 600 caracteres; quite `--confirm-owner` para la vista previa):

```
# INT-A02 · Calibración coherente multiclase
docker exec -w /app predigol-worker python -m scripts.ia_protocols sign --key INT-A02 --fingerprint 2a1cdb3ec31a6b5075010a989e6205bf60bc699c54891a62ac861ad0fd69ae6d --reason "..." --confirm-owner

# INT-A09 · E4: tiros y xG en los ratings
docker exec -w /app predigol-worker python -m scripts.ia_protocols sign --key INT-A09 --fingerprint 400778f85de7acdfc59b1d9e265d7f4c4d5fe42abc4abf71cb5785b33604bd36 --reason "..." --confirm-owner

# INT-B09 · Estudio de eventos: noticia → precio
docker exec -w /app predigol-worker python -m scripts.ia_protocols sign --key INT-B09 --fingerprint 2b8e49fb115f5cecbcb5e61f52d9ac11d8c8464ce7b3da97af62b3f9382e9232 --reason "..." --confirm-owner

# INT-A08 · E6: quién juega, en el modelo
docker exec -w /app predigol-worker python -m scripts.ia_protocols sign --key INT-A08 --fingerprint a37fdb4265f407c892e11f793ce86a083667ec491f0251fdd4d1f1d3603a1c43 --reason "..." --confirm-owner

# INT-C02 · Banco de repetición: la variante actual reproduce la sombra
docker exec -w /app predigol-worker python -m scripts.ia_protocols sign --key INT-C02 --fingerprint f954582c9594c509dfc93f4abd9a847292a023d74dc5495daf0eead00bd0cc63 --reason "..." --confirm-owner

# AD-A03 · battery-v4: batería adversaria que separa ataque de variabilidad
docker exec -w /app predigol-worker python -m scripts.ia_protocols sign --key AD-A03 --fingerprint 205e671347e7c9ab21a4fb0ab03d1b6c66a2c4d9e44494f937e3e23707653bae --reason "..." --confirm-owner

# AD-B03 · Sello estable: el calibrador campeón con un precio de más de 6 horas
docker exec -w /app predigol-worker python -m scripts.ia_protocols sign --key AD-B03 --fingerprint 989b82a53fe35ae6712f39ce71d75588a1f868e38b9a2832ba2e393162364bd5 --reason "..." --confirm-owner

# AD-B07 · Córners y tarjetas: calibrador de conteos por familia (count-cal-v1)
docker exec -w /app predigol-worker python -m scripts.ia_protocols sign --key AD-B07 --fingerprint aac10f7f5cc48dfbf136283f0c76d1c6043556536b137e7df2bd4cbe05299128 --reason "..." --confirm-owner

# AD-K02 · Tablero de validación por mercado y familia (board-v1)
docker exec -w /app predigol-worker python -m scripts.ia_protocols sign --key AD-K02 --fingerprint 6eff7d3066cbeed274d457c2694f478e339fc8232610be74f4c56f54e570def1 --reason "..." --confirm-owner

# AD-C08 · Credibilidad de fuentes por tipo de hecho (credibility-v2)
docker exec -w /app predigol-worker python -m scripts.ia_protocols sign --key AD-C08 --fingerprint 7ae65569c4f330956c9437c99a1224f36448d94fdba90d371d7ec6eb144943a4 --reason "..." --confirm-owner

# AD-C09 · Medición de la extracción frente a etiquetas humanas de páginas enteras (extract-protocol-v1)
docker exec -w /app predigol-worker python -m scripts.ia_protocols sign --key AD-C09 --fingerprint f0bd0d90c7747bcab6e48dde47676c64b784d2d18fe9e78635c21efbc2106ed8 --reason "..." --confirm-owner

# AD-K03 · Rendimiento de lectores y fuentes frente a las reglas (perf-v1)
docker exec -w /app predigol-worker python -m scripts.ia_protocols sign --key AD-K03 --fingerprint c5638110bd730e99a7d841caace34731bafb73cfac2c93d3c9bef89e49c719d3 --reason "..." --confirm-owner

# AD-K04 · Banco de repetición como prueba de regresión con tolerancia (replay-regression-v1)
docker exec -w /app predigol-worker python -m scripts.ia_protocols sign --key AD-K04 --fingerprint 9d37ca84b4dba0aa37e0b40cd9add0be4ea96951bac59e6c53802763482a9d14 --reason "..." --confirm-owner

# AD-F04 · Coletillas y repeticiones de la crónica única: umbrales
docker exec -w /app predigol-worker python -m scripts.ia_protocols sign --key AD-F04 --fingerprint 17c942303fbc2cd0f39f90a1184f8cf0a699e1c3bffa5c783967952fb32d3608 --reason "..." --confirm-owner

# AD-F05 · Retirada de los textos duplicados: la comparación preregistrada
docker exec -w /app predigol-worker python -m scripts.ia_protocols sign --key AD-F05 --fingerprint 1fbeadbddd163eb4eae3b15e952e340c11226544aa304a5551988060f07a7b6a --reason "..." --confirm-owner

# AD-F06 · Evaluación factual de la crónica única: revisión humana por muestreo
docker exec -w /app predigol-worker python -m scripts.ia_protocols sign --key AD-F06 --fingerprint 33b296c7c3852187e5cb59b223bc752b9f36f997fdf9320b5f8beb4fbee8b47b --reason "..." --confirm-owner

# AD-D11 · Retirada de review-v2: comparación preregistrada de no inferioridad frente al cierre (review-retire-v1, IA-145)
docker exec -w /app predigol-worker python -m scripts.ia_protocols sign --key AD-D11 --fingerprint 0fdd2a7145b57fe9ed0d727cf171de14c496b3b21dc93c588f549daa6251b5c6 --reason "..." --confirm-owner
```

Para AD-A03 y AD-C09, además, la firma propia que exige su medición:
`docker exec -w /app predigol-worker python -m scripts.ia_battery_v4 sign --invalid-max 0 --reason "..." --confirm-owner` y
`docker exec -w /app predigol-worker python -m scripts.ia_page_bank sign --reason "..." --confirm-owner`.

Si `show` da otra huella que la de esta tabla, **firme la de `show`**: es la vigente (el protocolo cambió después de escribir esta guía) y
el comando rechazará cualquier otra.

## 5. Vuelta atrás

* Una firma no se borra: si se equivocó, no hace falta deshacer nada operativo (la firma no activó nada). Deje constancia con el motivo de
  una firma nueva cuando el protocolo cambie (versión nueva, huella nueva).
* Revertir la migración 0166 quita la tabla (se pierden las firmas); los lectores vuelven a decir «sin firmar» sin errores.
* C-11 1.1.0 es un cambio aditivo de un contrato privado; ningún consumidor de la web lo lee hoy.
