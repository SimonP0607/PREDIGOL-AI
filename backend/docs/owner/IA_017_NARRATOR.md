# IA-017 · El Narrator: el «por qué lo recomendamos» de un pick, escrito solo desde su traza

Fecha: 7 nov 2026. Estado: **en el código, sin desplegar y apagado**. Sin migración. Lo vigilan `tests/unit/test_narrator.py` y
`tests/integration/test_narrator.py`. Código: `src/fbi/narrator/` (`narrator-v1`), prompt `pick-why-v1`.

## 1. Qué es (y qué no)

Es la capa 12 de la arquitectura objetivo: convierte la **decisión ya tomada** sobre UN pick en una lectura de fútbol natural, en
español e inglés, con dos apartados: **por qué** (probabilidad de PrediGol frente a la cuota, el valor, los filtros que pasó, la
revisión y la evidencia que citó, el stake) y **riesgos**. Pocas cifras, bien elegidas; nada de volcados de estadísticas.

**No es la crónica del partido** (UX-025, `CRONICA_UX_025.md`): la crónica cuenta el partido y no sabe de picks; el Narrator cuenta
el pick y no cuenta el partido. Se escribe **después** de la decisión y **no puede añadir una razón que la decisión no usó**.

## 2. De dónde sale cada frase

De la traza `trace-v1` del pick (`fbi.observability.trace`) y de nada más. `facts.py` la convierte en una **lista cerrada de hechos**,
cada uno con su id (`F:odds`, `F:filter.ev`, `F:evidence.123`) y su papel (identidad, núcleo, razón o riesgo):

- de la **decisión del pick** (la más reciente que lo nombra): estado, checkpoint, probabilidad calibrada, probabilidad justa del
  mercado, cuota y número de casas, EV y edge calibrados, Pick Score, stake, sus filtros (pasado o no, con su efecto), los códigos de
  riesgo que registró y su estado de contexto;
- el **intervalo** de la predicción de la que salió el pick;
- la **revisión que la decisión cita** (veredicto y confianza: el Council), nunca una de sombra que no citó;
- la **evidencia que la decisión cita** (tipo, estado, el texto de la afirmación y el medio). Una `OUTDATED` no es hecho; un rumor o
  una contradicción solo es riesgo;
- y, aparte, la **identidad del partido** (los dos equipos y la competición, leídos del partido que nombra la traza): nombres, nunca
  razones.

Las versiones (decisión, modelo, calibrador, código) van con los hechos al informe y al hash, nunca al lector. Misma traza → mismos
hechos, mismo orden, mismo hash. **Decisión nueva → hash nuevo → se vuelve a escribir.**

## 3. Qué se comprueba (`verify.py`), frase a frase

Reutiliza, importándolos sin cambiarlos, los controles de la crónica (`fbi.narrative.job`: cifras también con letra, porcentajes,
tokens del sistema, rumores, atribución, «sin calibrar», el lado de la línea de goles). Una frase **se descarta** (no se arregla) si:

- no cita entre 1 y 4 hechos que existan, o solo cita la identidad del partido;
- en «por qué» cita un riesgo, o en «riesgos» no cita ninguno;
- dice un **número** que no está en los hechos que cita, o un **nombre** (palabra con mayúscula que no abre la frase) que no es del
  partido ni de un hecho citado;
- habla con certeza («seguro», «garantizado», «sin duda»...), usa códigos del sistema, no rotula una probabilidad sin calibrar, cuenta
  un rumor como hecho o una noticia probable sin atribuirla;
- su par en el otro idioma no existe, falla, o cita otros hechos u otras cifras.

Sin ninguna frase de «por qué» en pie, el pick **no tiene texto** (`rejected`). Con alguna descartada, `partial`.

## 4. Interruptor, dinero y modelo

| Variable | Valor por defecto | Qué hace |
| --- | --- | --- |
| `FBI_NARRATOR` | ausente = **apagado** | `shadow`: construye, llama, verifica e **informa**; `on` hoy se comporta como `shadow` (no hay dónde guardar). Apagado no lee nada, no llama y no gasta |
| `FBI_AI_USER_MONTHLY_BUDGET_USD` | 0 | el presupuesto **existente de lectores** (el de la crónica): con 0 no gasta. Se pregunta primero; luego `call_json` pregunta el de Intelligence |
| `FBI_NARRATOR_TIER` | `analysis` | Sonnet 5.5 en producción (lo que pide la arquitectura para picks publicados); `bulk` = Haiku, `final` = Opus |

Una llamada por pick, sin reintento; la misma entrada dos veces en una pasada se paga una. Cada llamada queda en el libro de lectores
(`ai.user_usage`, versión `pick-why-v1`, hash de los hechos).

## 5. Dónde se guarda: en ningún sitio (todavía)

`ai.user_narratives` es de la crónica, **una fila por partido**: su trabajo cuenta todas las filas del partido para su espera de 2 h
y sus 3 intentos al día, sea cual sea la versión, así que escribir ahí un texto de pick frenaría la crónica. El esquema no encaja y una
tabla propia es una migración. Por eso, en sombra, el resultado vive en el **informe** (`RunReport.as_json`) y en la línea de log
`narrator.pick`. Guardarlo y enseñarlo al lector es el paso siguiente, con tu OK (migración + API + web).

## 6. Cómo probarlo

```
python -m scripts.ia_narrator preview --pick 123          # hechos, hash y prompt: no llama, no gasta
python -m scripts.ia_narrator preview --pick 123 --json
python -m scripts.ia_narrator preview --pick 123 --call   # UNA llamada, solo con la clave del LAB y su sobre
```

Sin la clave del LAB para el nivel del Narrator, `--call` se niega sin llamar. El trabajo (`fbi.narrator.job.run`) no está conectado
al worker: se conectará cuando haya dónde guardar.

## 7. Aislamiento

- El Narrator **lee** la traza; nada que decide la importa (la prueba de la traza lo nombra como único lector, con su motivo).
- No escribe ninguna tabla salvo la fila de gasto de cada llamada; no cambia modelos, umbrales, decisiones, picks ni la crónica.
- No cambia `fbi.ai.agents`, `fbi.players` ni la decisión (`fbi.intel.decision`): lee lo que la decisión ya escribió.
