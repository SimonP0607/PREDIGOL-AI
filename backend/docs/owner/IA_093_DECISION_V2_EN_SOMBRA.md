# IA-093 · `decision-v2` en sombra continua y guardada (AD-D01)

Pieza AD-D01 del plan de la arquitectura definitiva 2026 (responsable: IA). Hasta hoy `decision-v2` —el motor único de decisión de todos los mercados— solo decidía cuando alguien lanzaba su **repetición** a mano, y no guardaba nada: en `intel.decisions` hay **0 filas** de `decision-v2` (producción, 16-nov-2026, n = 107.109 filas). Sin filas no se puede seguir una decisión hasta el saque, medirla contra el cierre ni dársela al ciclo de estados. Esta pieza hace que decida **sola**, en momentos fijos, y que **guarde cada decisión** con todo lo que usó.

**Todo en sombra. Lo que ve el lector no cambia.** `decision-v1` no se toca (ni su código ni su tabla `intel.decisions`), `FBI_PICKS_SOURCE` sigue apagado, nada de esto llega a picks, combinadas ni a ninguna página. Ningún modelo de lenguaje toca una probabilidad. No se baja ningún umbral.

## 1. Qué hace

Un trabajo del worker, `decision_v2_shadow`, que **nace apagado** (`FBI_DECISION_V2=off`). Encendido en `shadow`, cada 5 minutos decide los momentos que tocan para los partidos seguidos (`core.competitions.is_tracked`):

| Momento | Cuándo | Para qué |
| --- | --- | --- |
| **E1** | una vez por partido, entre 24 y 12 horas antes del saque | la primera evaluación del ciclo E1–E4 (AD-D06) |
| **E4** | una vez por partido, entre 20 y 10 minutos antes del saque | la última decisión antes del saque (ver nota) |
| **espejo** | en cada momento en que decidió `decision-v1` (sus puntos T-36h … T-15m y «alineaciones») | demostrar que la sombra cubre a todos los candidatos de `decision-v1` y que es exactamente la repetición |

**Nota sobre E4.** La ficha dice T-5. Pero por debajo de 10 minutos la etapa de datos rechaza todo («menos de 10 min al saque»): es el umbral de `decision-v1` (`MIN_MINUTES`), que el motor importa y **no se baja**. Una fila a T-5 solo diría eso. Por eso E4 se guarda en el último momento en que el motor todavía juzga: de T-20 a T-10. Si se quiere E4 a T-5 hay que decidir antes qué hacer con esa regla.

**Actualización 17-nov-2026 (IA-142, decisión del dueño).** El E4 del ciclo de evaluaciones pasa a T-5, pero **no decide**: juzga con la última decisión guardada de `decision-v2` (la de este disparador E4, de T-20 a T-10) y con el precio leído otra vez. La ventana de este disparador **no cambia** y la regla de 10 min tampoco. El espejo de `decision-v1` no tiene nada que copiar a T-5 (`decision-v1` no decide por debajo de su umbral) y el E4 del ciclo nunca adopta un momento guardado por debajo de él. Ver `IA_140_DECISIONES_DUENO_20261117.md`.

**Cómo decide.** Con la **misma función** que la repetición (`replay.decide_at`), así que una decisión guardada **es** la decisión de la repetición de ese momento. Configuración única por ahora (`decision-v2.1|book|common|forecast-v2|core`):

- **cifra única** `forecast-v2` (IA-083): la probabilidad de cada mercado de goles con su sello (calibrada o «sin calibrar» con su motivo);
- **precio del libro** con la regla de edad por horizonte 195/75/45 min (`decision-v2.1`, IA-067), leído del RAW tal como estaba en ese momento;
- los **candidatos del núcleo** (los de `decision-v1`); las familias de F10 siguen con su propia capa.

El precio de cierre del libro **no se guarda** en la decisión: no existía en el momento de decidir.

## 2. Qué guarda (migración 0150, tablas de solo añadido)

- `intel.decision_v2_moments`: una fila por partido y momento —el disparador (E1, E4, espejo), la configuración, cuántos candidatos y cuántas decisiones, la **evidencia tipada** del partido que podía citar (`ai.evidence` hasta ese momento: tipo, tipo de afirmación, estado, **nivel** —oficial, dos orígenes, un medio, proveedor o rumor— y sus fechas; nunca el texto), y la **huella** (sha-256) del mundo que leyó.
- `intel.decisions_v2`: una fila por decisión —selección, estado, motivo y códigos; la cifra juzgada (fuente, versión, sello); el precio con su fuente, edad y estado; **las entradas con su hora**; la evidencia que leyó la etapa de contexto (ids, recuentos, la revisión); todas las etapas; y la **versión anterior** de la misma selección (`previous_id`), de modo que cada selección es una cadena de versiones. En el espejo, `mirror_of` apunta a la fila de `decision-v1` del mismo momento.
- **Ninguna entrada posterior al momento.** Una decisión con un precio o un corte de modelo posterior no se escribe (se cuenta como `leaks`), y además la base la rechaza (CHECK).
- Las dos tablas rechazan `UPDATE` y `DELETE` (`ai.refuse_change()`).
- La base del ciclo de estados (`intel.selection_lifecycle`, 0142) solo aceptaba nombres de tabla sin dígitos en `source`; la 0150 amplía esa regla para que quepa `intel.decisions_v2`. Nada más de esa tabla cambia.

## 3. Enlace con el ciclo de estados (IA-068)

Las decisiones guardadas pasan al ciclo de estados **por su API** (`fbi.lifecycle.store.extend`), con su propio escritor `decision-v2-shadow-v1`, capa `decision-v2` y fuente `intel.decisions_v2`; cada paso lleva su evaluación (E1, E4). Esta pieza no escribe en esa tabla por su cuenta. Solo entran las decisiones con más de 30 minutos (`LINK_LAG`): `decision-v1` escribe sus filas al terminar su pase (mediana 579 s), y un momento que llegara tarde quedaría en medio de una cadena ya guardada, que el ciclo rechaza.

## 4. Pruebas

- **Unitarias** (sin base): ventanas de E1 y E4 (incluido que E4 nunca baja de los 10 min de `decision-v1`), planificación del espejo (agrupa por momento, salta las copias del «pick del día» y lo ya guardado), evidencia sin texto, entradas posteriores al momento, lectura de una decisión en el ciclo (con su evaluación), configuración, huella determinista, interruptor y trabajo del worker (no conecta si está apagado y nunca lanza).
- **Aislamiento**: el único importador nuevo de `fbi.decision` es `fbi/shadowjobs/decision_v2.py`, que solo importa el planificador y que importa el motor dentro del pase; `test_decision_version_guard` sigue en verde; el paquete solo escribe sus dos tablas, con INSERT.
- **Integración** (PostgreSQL local, base propia): en la escena de la repetición, el espejo guarda **una decisión por cada fila de `decision-v1`** en el mismo momento, sus estados son los de `decision-v1` leídos por `state-v2`, `verify` da **cobertura 1,0 y 0 diferencias** con la repetición; las entradas nunca son posteriores; la cadena de versiones enlaza bien; E4 decide solo; E1 guarda su momento aunque no haya candidatos; nada se decide dos veces; las tablas rechazan UPDATE/DELETE; `intel.decisions` no se mueve; el ciclo recibe cadenas legales y terminan donde terminan las de `decision-v1`; y con la configuración real (precio del libro) una selección sin respuesta en el libro queda «sin precio» con su motivo y nunca recomendada. Migración 0150: sube, rechaza filas ilegales y baja limpia.

## 5. Tamaño esperado (producción, 17-nov-2026, 14 días)

`decision-v1` escribió entre 23 y 4.600 filas al día (3–17 nov, días de Bogotá; el 17 incompleto), en 3 a 95 momentos al día; por partido, 4 momentos de mediana y 14 en el p90. El espejo guarda una fila por candidato y momento, así que la tabla crecerá del orden de lo que crece hoy `intel.decisions` (302 MB para 111.004 filas). E1 y E4 añaden 2 momentos por partido seguido (entre 18 y 44 partidos al día los próximos 3 días). El tamaño lo vigila AD-A07.

## 6. Cómo se activa en sombra (tras desplegar)

1. Comprobar que la migración **0150** está aplicada (el despliegue la aplica).
2. Poner `FBI_DECISION_V2=shadow` en el entorno del worker y reiniciarlo (un minuto). Opcionales: `FBI_DECISION_V2_MINUTES` (1–10, 5 por omisión) y `FBI_DECISION_V2_TRIGGERS` (`E1,E4,mirror` por omisión).
3. Para que el ciclo reciba las cadenas, el ciclo de estados (0142) debe estar desplegado; si no, la pasada lo dice y sigue.
4. Medir (solo lectura, dentro de la imagen del worker):
   - `python -m scripts.ia_decision_v2 verify --hours 24` — cobertura de las filas de `decision-v1` por una decisión guardada del mismo momento (criterio AD-D01: ≥ 99 %) y **equivalencia**: hasta 200 momentos decididos otra vez desde la misma base (criterio: 0 diferencias).
   - `python -m scripts.ia_decision_v2 dry-run` — qué decidiría una pasada ahora, sin escribir.

## 7. Cómo se apaga y se revierte

`FBI_DECISION_V2=off` (o quitar la variable) y reiniciar el worker: el trabajo ni se programa. Las filas se conservan; `decision-v1` sigue exactamente igual. Revertir el código no necesita tocar datos; bajar la migración borra las dos tablas (y devuelve la regla de `source` del ciclo a la de 0142).

## 8. Lo pendiente

- E2 (por hecho nuevo) y E3 (al llegar la alineación) son de AD-D06 y AD-D07: escribirán aquí con su evaluación.
- El criterio de cierre (≥ 99 % y 0 diferencias) se mide con `verify` en producción tras activarlo; aquí está probado en la base local.
- El Council y las señales de mercado no entran en la configuración de la sombra (sin `ctx-adj-v1` ni `market-signals-v1`): se añadirían como configuración nueva, con su propia clave.
