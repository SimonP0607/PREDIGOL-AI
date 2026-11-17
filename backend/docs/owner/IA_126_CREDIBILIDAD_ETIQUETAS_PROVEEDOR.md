# IA-126 · IA-127 · IA-128 · Credibilidad por tipo de hecho, banco de páginas etiquetadas y API-Football en el modelo de hechos

Piezas AD-C08, AD-C09 y AD-C10 del plan maestro de la arquitectura definitiva 2026. Todo nace **apagado o en sombra**: nada de esto llega al lector, a un paquete, a una decisión, a un pick ni a un umbral. Una migración: `0162` (una tabla nueva de solo añadido y un nombre de gate nuevo). Ninguna llamada nueva a API-Football y ningún modelo.

## 1. AD-C08 · Credibilidad de cada fuente por tipo de hecho (IA-126)

**Qué había.** El motor de evidencias aprende un solo número por fuente (`credibility-v1`): si un medio acierta siempre las alineaciones y falla las lesiones, sale la media de las dos cosas, sin muestra ni intervalo, y no se guarda en ningún sitio.

**Qué hace ahora (en sombra).** Una versión 2 que aprende **por tipo de hecho**: baja, sanción, titularidad y disponible. Una duda no se juzga (una duda no se puede refutar). Cada afirmación pasada se compara con lo que resolvió después el partido, en este orden: la alineación oficial del proveedor, su parte de bajas, y una fuente de nivel superior que dijo lo mismo o lo contrario. Lo que nada pudo comprobar no cuenta.

- **A fecha estricta:** nada que se supo después del momento de la lectura existe para ella, y una afirmación nunca avala a su fuente en su propio partido.
- **Con su intervalo y su muestra:** cada par fuente-tipo enseña aciertos/resueltas, el intervalo de Wilson del 95 % y un valor encogido hacia el previo de su nivel (la misma regla de v1, con 10 afirmaciones de peso). Por debajo de **30 resueltas** el tipo dice **«insuficiente»**: se enseña, no se interpreta. Ese mínimo está en el protocolo `AD-C08`, registrado el 17-nov antes de mirar ningún dato.
- **Informa, no decide:** el nivel A–D sigue fijando el peldaño máximo; la credibilidad solo puede afinar la confianza dentro del tope de su estado. Ningún estado cambia por ella (una prueba de propiedad con 400 casos lo comprueba) y ningún proceso sube el nivel de un dominio (el código no escribe `ai.sources` ni el registro). El motor sigue leyendo v1.
- **Repetición frente a v1** con las mismas entradas, con las diferencias listadas y su motivo: dudas que v1 juzgaba, tipos a más de 0,05 del número único de v1, y fuentes que v1 daba por aprendidas sin ningún tipo con la muestra mínima.

**Dónde se guarda.** `ai.source_credibility` (migración 0162): una fila por versión, momento, fuente y tipo; solo añadido; la misma foto dos veces se guarda una vez. La escribe la tarea del worker `source_credibility_shadow`, una vez al día, **solo con `FBI_SOURCE_CREDIBILITY=shadow`** (por defecto `off`; cada cuánto: `FBI_SOURCE_CREDIBILITY_HOURS`, 24 por defecto).

**Cómo se mira.** Dentro de la imagen del worker: `python -m scripts.ia_credibility snapshot` (foto de ahora y repetición frente a v1, solo lectura) y `python -m scripts.ia_credibility show` (la última foto guardada).

## 2. AD-C09 · Banco de páginas etiquetadas a mano y protocolo de la extracción (IA-127)

**Qué había.** El banco de IA-030 etiqueta evidencias ya escritas: mide si lo extraído es cierto, pero no lo que la página decía y nadie extrajo. Y el gate de research v2 (la **fila 17**, NO PASA, cobertura 23,07 % de v1, 12-nov) comparaba un extractor con otro extractor.

**Qué hace ahora.** La referencia pasa a ser **una persona que lee la página entera** y apunta todas sus afirmaciones verificables (sujeto, tipo y cita). Con eso se miden los cuatro brazos de AD-C05 (`extract-v3` con corte de 700, `extract-v3` completo, `extract-v4` y ventanas) sobre las mismas páginas.

- **El banco** (`python -m scripts.ia_page_bank sample --days 14 --out banco.json --labels etiquetas.csv`, solo lectura): las páginas con texto que la investigación ya guardó para los partidos de la ventana, leídas antes de su purga y **sin contar reutilizaciones**. Se guarda el texto solo cuando la política de fuentes deja guardarlo (una fuente reservada o excluida queda con su enlace). Muestra estratificada (clubes/selecciones, idioma, tipo de búsqueda) y determinista con la semilla del protocolo; un cuarto de cada estrato lleva segundo etiquetador ciego. El fichero es texto de terceros: **datos no confiables, nunca se publican y no pasan por ningún modelo desde aquí**.
- **Las etiquetas** (una línea por afirmación, o `NONE` si la página no afirma nada verificable): una página sin etiqueta queda fuera, nunca se adivina. En las páginas dobles cuenta lo que marcaron los dos; lo que marcó uno solo queda **en disputa**, aparte, y no cuenta ni a favor ni en contra. **Las etiquetas no entrenan nada.**
- **El protocolo `AD-C09` (`extract-protocol-v1`)**, registrado el 17-nov **sin firmar**: PASA un brazo si al menos **47 de sus 50 primeras afirmaciones** son ciertas y el extremo inferior de su recuperación, con la corrección de Bonferroni para los cuatro brazos, es **≥ 0,60**, con un acuerdo entre etiquetadores ≥ 0,80. Con menos de 150 páginas, menos de un cuarto dobles o menos de 50 afirmaciones: INSUFICIENTE. Con acuerdo bajo: NO EVALUABLE.
- **El gate propio `extract_protocol`** en `ai.feature_gates`: primero **tu firma** (`python -m scripts.ia_page_bank sign --reason "..." --confirm-owner`; sin `--confirm-owner` es una vista previa y no escribe nada), y solo después una fila por medición (`score` + `record`), que se niega sin tu firma del protocolo tal como está. La fila dice «pasa» solo si pasa el brazo «ventanas» (el camino unificado, el que sustituiría a v1). **Un PASA no activa nada.**
- **La fila 17 se conserva:** nada de esto lee ni escribe el gate `research_v2`; sigue siendo la fila que lee el interruptor de research v2.

## 3. AD-C10 · API-Football en el mismo modelo de hechos (IA-128)

**Qué había.** El proveedor ya entraba en las evidencias (alineación como A, parte de bajas como B), pero no como afirmaciones del modelo que habla la investigación unificada: sin tipo, sin autoridad por tipo, sin cuatro fechas, y una competición en la que el proveedor no da bajas se veía igual que una sin lesionados.

**Qué hace ahora (solo lectura, con lo ya ingerido).**

- **API-Football como fuente** con su autoridad por tipo: la alineación registrada **confirma**; bajas y sanciones **informan**; los eventos confirman.
- **Cada dato, una afirmación:** titular, suplente (disponible), baja, sanción (por tarjeta o suspensión, con las mismas palabras que hoy), duda, y gol, tarjeta, cambio o VAR de un jugador. Lo que el código no sabe tipar no se adivina: se cuenta aparte con su motivo.
- **Cuatro fechas y hora de conocimiento:** sin fecha de publicación (el proveedor no da; nunca la de hoy); «visto» = la primera llegada de la alineación (AD-D05) o la observación del parte; vigencia hasta el siguiente cambio del parte. Lo visto después del momento de una decisión no existe para ella.
- **Sin detalle médico:** el motivo de una baja solo se lee para distinguir sanción de lesión y no se guarda en ninguna afirmación (una prueba lo comprueba).
- **La cobertura como hecho:** si `raw.league_coverage` dice que el proveedor no da bajas en una competición, el resultado es **«sin dato» — «el proveedor no da bajas en esta competición»**, nunca «sin bajas». Tampoco es «sin bajas» una competición cubierta cuyo parte no se pidió.

**Cómo se mira.** `python -m scripts.ia_provider_facts match --fixture N [--at ...]`, `coverage --days 7` y `replay --days 14` (estados de hoy de las evidencias del proveedor frente a los peldaños de sus afirmaciones, en el momento en que se decidió cada estado, con cada diferencia y su motivo).

## 4. Qué no cambia

`decision-v1`, `FBI_PICKS_SOURCE`, probabilidades, umbrales, picks, la sombra de los agentes, los estados de `ai.evidence`, el motor de evidencias (sigue con `credibility-v1` y `tiers-v1`), la fila 17 y todos los demás gates, la política de fuentes, el directorio v2 (API-Football no se añade a ese fichero fijado: se escribe en el código), las llamadas a API-Football (ninguna nueva) y nada de lo que ve el lector.

## 5. Cómo se activa y cómo se apaga

- Tras desplegar (la migración 0162 corre con el despliegue): `FBI_SOURCE_CREDIBILITY=shadow` en el worker y reinicio para guardar la foto diaria. Para apagar: `off` (o quitar la variable) y reinicio; las filas guardadas se conservan.
- El banco y el gate no tienen interruptor: no hacen nada hasta que tú firmes el protocolo y alguien etiquete al menos 150 páginas.
- Los facts del proveedor no tienen interruptor: son lecturas para la consola del dueño y para las piezas que los usarán (AD-D04, AD-H05).
- Vuelta atrás del código: revertir el cambio; la bajada de la migración borra `ai.source_credibility` y se niega mientras haya filas del gate `extract_protocol` (se perderían).

## 6. Mediciones

Ver la entrega de la pieza: las cifras de producción se miden con los tres scripts tras desplegar (solo lectura). Hoy hay **0 fuentes firmadas**: nada de texto de terceros llega a un modelo, y los brazos de AD-C05 no se pueden ejecutar sobre el banco hasta que lo decidas.
