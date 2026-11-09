# IA-022 · La revisión posterior de la crónica

**Qué es.** La etapa A y B del flujo único (`claude/PLAN_FLUJO_UNICO_ANALISIS.md`): después del partido, comparar lo que la crónica dijo con lo que el partido mostró. Hasta ahora ningún post-mortem leía el texto que vio el lector.

**Qué hace.** `fbi.chronicle.review` (`chronicle-review-v1`) toma, de cada partido terminado hace 26 horas o más, la crónica más reciente que un lector pudo ver antes del inicio (`ai.user_narratives`, estado `ok`), y juzga cada referencia de cada frase:

- una **baja o una duda** (`P:absences.<lado>.<n>`) contra quién jugó (minutos del partido; si no hay minutos, quién fue titular): quien la crónica dio por baja y jugó **la contradice**; quien no jugó, **la sostiene**; la duda se cuenta como «jugó» o «no jugó»;
- una **noticia** (`E:<id>`) sobre un jugador (lesión, sanción, duda) se juzga igual, por el id del jugador en el proveedor;
- todo lo demás (forma, últimos resultados, cara a cara, lo que se juega cada equipo) es historia o contexto: describe el partido, no anticipa nada que un resultado pueda refutar. Queda como **no evaluable**, nunca como acierto.

Un nombre que las alineaciones no colocan, pero que se parece al de alguien de la plantilla, queda **no comprobable**: no se usa para dar un acierto. Sin alineaciones ni minutos el partido **espera** y no se escribe nada hasta que haya datos. Junto a la revisión se listan las selecciones del partido tal como las juzgan los post-mortems (`intel.postmortems`), sin enlazar ninguna con la crónica.

**Qué no hace.** No llama a ningún modelo, no gasta dinero, no afirma causas («la crónica acertó» no significa que la crónica provocara nada), no modifica modelos, umbrales ni picks, y ninguna pieza de Intelligence la lee (`tests/unit/test_user_layer_isolation.py` lo comprueba: el módulo está en la lista de los que pueden nombrar la tabla de las crónicas, con su razón).

**Dónde queda.** `ai.chronicle_reviews` (migración 0132, solo anexar, sin claves foráneas a tablas vivas): una fila por crónica y versión, con `items` (cada frase con su veredicto y el de cada referencia), `summary` (conteos), `outcome` (marcador y qué datos había), `picks` y el `trace_id` del partido. Solo lectura del dueño.

**Cómo se usa.**

    python -m scripts.ia_chronicle_review preview                 # lo que toca, sin escribir
    python -m scripts.ia_chronicle_review preview --fixture 123   # un partido
    python -m scripts.ia_chronicle_review run --confirm-owner     # escribe las filas pendientes

El trabajo programado del worker (`chronicle_review`, IA-023) la ejecuta cada hora sobre lo que toca: está encendido por defecto, no gasta nada y se apaga con `FBI_CHRONICLE_REVIEW=0` sin desplegar (`FBI_CHRONICLE_REVIEW_MINUTES` cambia el intervalo). Una pasada sin nada que escribir no deja fila en el libro de trabajos; una que escribe deja una con sus conteos. Un partido sin alineaciones ni minutos espera a la pasada siguiente.

**Cobertura hoy.** 246 partidos terminados tienen crónica `ok`; 206 tienen minutos del partido. Como la mayor parte de una crónica es historia, el número de afirmaciones firmes por partido es pequeño (las bajas y las noticias de jugadores); la revisión lo dice tal cual en `summary`, no lo maquilla.

**Vuelta atrás.** Revertir el cambio; la migración se baja con `DROP TABLE` (las revisiones se escriben de nuevo desde las crónicas, que nunca se borran).
