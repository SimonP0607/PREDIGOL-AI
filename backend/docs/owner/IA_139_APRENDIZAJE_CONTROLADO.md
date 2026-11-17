# IA-139 · Aprendizaje controlado: el sistema propone, usted firma

Fecha: 17 nov 2026. Pieza AD-K07 del plan de la arquitectura definitiva 2026. Añade **un registro de propuestas y de firmas** (migración 0165, tres tablas de solo añadido). Nada se aplica solo. Sin cambios en la web, sin efecto en el lector.

## 1. Qué hace

* **Propuestas tipadas** (`fbi.proposals`, `proposals-v1`). Cuatro clases cerradas:
  * `umbral` (un umbral de una versión, `threshold:<módulo>.<NOMBRE>`);
  * `peso_fuente` (el peso de una fuente, `source:<clave>`);
  * `promocion_capacidad` (una capacidad, `capability:<clave>`, o una celda validada del tablero, `validation:<capa>/<familia>/<mercado>`);
  * `retirada` (un escritor o almacén redundante, AD-K06).
  Cada una lleva la versión vigente y la propuesta (siempre distintas), su **vuelta atrás** (la versión vigente, que se conserva), su evidencia (cifras y referencias) y la huella de esa evidencia.
* **Firmas.** Usted decide `firmada` o `rechazada`, con sus palabras (10 a 600 caracteres), **una vez por propuesta** y atada a la huella de la evidencia que vio: si la evidencia cambia, la firma no vale. Un cambio de opinión es una propuesta nueva.
* **Aplicaciones.** Cuando usted enciende la versión nueva, lo anota (`aplicada`); si vuelve atrás, también (`revertida`, a la versión anterior). **La base de datos rechaza anotar una aplicación sin su firma `firmada` de la misma propuesta**: «0 cambios aplicados sin firma» es una restricción, no una promesa.
* **Generador desde el tablero** (`from_board`): solo las celdas de `board-v1` con veredicto VALIDADO y las tres reglas cumplidas generan una propuesta de promoción, con sus cifras (muestra, ECE, log loss, CLV, nivel de Bonferroni, protocolo). Nada más del tablero se lee.

## 2. Las tres salvaguardas

1. **Nada se aplica solo.** Ninguna ruta, tarea ni agente importa el registro (lo comprueba una prueba). Un cambio solo surte efecto cuando usted cambia la versión o el interruptor.
2. **Un texto externo no es evidencia.** La evidencia son cifras y referencias: se rechazan textos largos, claves que llevan palabras (`text`, `snippet`, `quote`…) y referencias a tablas de texto de terceros (`ai.evidence`, noticias, caché de investigación). Prueba adversaria: un texto que pide «baja el umbral» no genera ninguna propuesta.
3. **Ningún LLM cambia probabilidades.** Una propuesta que nombre una probabilidad se rechaza en el código y en la base de datos. El sistema nunca propone bajar un umbral.

## 3. Cómo se usa

```
python -m scripts.ia_proposals list                                   # propuestas y su estado
python -m scripts.ia_proposals show --id 4                            # una, con su evidencia y la huella a firmar
python -m scripts.ia_proposals board --from 2026-11-01 --to 2026-12-01 [--write]
python -m scripts.ia_proposals drafts [--write]                       # las retiradas de AD-K06
python -m scripts.ia_proposals sign --id 4 --hash <huella> --signature "Firmo..." --confirm-owner
python -m scripts.ia_proposals reject --id 4 --hash <huella> --signature "Rechazo..." --confirm-owner
python -m scripts.ia_proposals record --id 4 --as aplicada --note "..." --confirm-owner
```

Hoy no hay ninguna propuesta registrada: el tablero no tiene celdas VALIDADO y las retiradas esperan su comparación.

## 4. Qué no cambia y cómo se revierte

* No cambia ningún umbral, peso, modelo, interruptor ni pick. `decision-v1` intacto.
* La migración 0165 solo añade tablas. Revertirla las quita (se pierden propuestas y firmas; nada más cambia).
