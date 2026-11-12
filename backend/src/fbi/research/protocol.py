"""Preregistered protocols for the LAB experiments of the Intelligence plan (INT-T02, IA-033).

A LAB experiment of the plan says, BEFORE it looks at its data, what it asks, which data and time window it reads, how it splits time
(walk-forward), its primary metric, the rule that makes it PASS and the one that REJECTS it, the minimum sample a power calculation
asks for, its exclusions and its stopping rule. Without that, a search that tries enough windows, markets and segments finds by chance
whatever it was looking for.

A protocol is a frozen dataclass written here. Its fingerprint is the SHA-256 of its canonical JSON, and
``tests/unit/test_research_protocols.py`` pins every fingerprint: changing a registered protocol is a visible diff that needs its own
reviewed PR, and git dates the protocol before the result. ``require`` is the first call of a LAB script of the plan: an experiment
without a registered protocol does not run, and ``stamp`` is what its result carries (key, version, fingerprint), so a result can
always be checked against the protocol as it was.

Power. For a mean, or a paired mean difference, with standard deviation ``sigma``, detecting a true difference ``delta`` with a
two-sided test at significance ``alpha`` and power ``1 - beta`` needs ``n = ((z_{1-alpha/2} + z_{1-beta}) * sigma / delta)^2``
observations: about ``7.85 * sigma^2 / delta^2`` at alpha 0.05 and power 0.80. ``mde_for_mean`` turns it around (the smallest
difference a sample can see). Two proportions use the usual normal approximation, pooled under the null. Rates are reported with
their Wilson interval (``fbi.ai.intervals``).

It decides nothing: it touches no model, forecast, calibration, pick, threshold or agent. Pure: no database, no clock, no numpy.
"""

from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass
from statistics import NormalDist
from typing import Any, Final

VERSION: Final = "lab-protocol-v1"
ALPHA: Final = 0.05
POWER: Final = 0.80
_N = NormalDist()


def z(p: float) -> float:
    """The standard normal quantile of ``p`` (0 < p < 1)."""
    if not 0.0 < p < 1.0:
        raise ValueError(f"p must be in (0, 1), got {p}")
    return _N.inv_cdf(p)


def _z_sum(alpha: float, power: float, two_sided: bool) -> float:
    if not 0.0 < alpha < 1.0 or not 0.0 < power < 1.0:
        raise ValueError("alpha and power must be in (0, 1)")
    return z(1.0 - alpha / 2.0 if two_sided else 1.0 - alpha) + z(power)


def n_for_mean(sigma: float, delta: float, *, alpha: float = ALPHA, power: float = POWER, two_sided: bool = True) -> int:
    """Observations needed to see a mean (or paired) difference ``delta`` when the per-observation spread is ``sigma``."""
    if sigma <= 0.0 or delta == 0.0:
        raise ValueError("sigma must be positive and delta non-zero")
    return math.ceil((_z_sum(alpha, power, two_sided) * sigma / abs(delta)) ** 2)


def mde_for_mean(sigma: float, n: int, *, alpha: float = ALPHA, power: float = POWER, two_sided: bool = True) -> float:
    """The smallest true difference that ``n`` observations of spread ``sigma`` detect with that power."""
    if sigma <= 0.0 or n < 1:
        raise ValueError("sigma must be positive and n at least 1")
    return _z_sum(alpha, power, two_sided) * sigma / math.sqrt(n)


def n_for_two_proportions(p1: float, p2: float, *, alpha: float = ALPHA, power: float = POWER, two_sided: bool = True) -> int:
    """Observations per group to tell two proportions apart (normal approximation, pooled variance under the null)."""
    for p in (p1, p2):
        if not 0.0 < p < 1.0:
            raise ValueError("proportions must be in (0, 1)")
    if p1 == p2:
        raise ValueError("the two proportions must differ")
    pbar = (p1 + p2) / 2.0
    za = z(1.0 - alpha / 2.0 if two_sided else 1.0 - alpha)
    zb = z(power)
    num = za * math.sqrt(2.0 * pbar * (1.0 - pbar)) + zb * math.sqrt(p1 * (1.0 - p1) + p2 * (1.0 - p2))
    return math.ceil(num * num / (p1 - p2) ** 2)


@dataclass(frozen=True, slots=True)
class Protocol:
    """What an experiment fixes before it sees its data. Texts in Spanish: the owner reads them."""

    key: str
    version: str
    title: str
    question: str
    null: str
    alternative: str
    unit: str
    data: str
    split: str
    primary_metric: str
    pass_rule: str
    reject_rule: str
    secondary: tuple[str, ...]
    min_sample: str
    power_note: str
    exclusions: tuple[str, ...]
    stopping: str
    segments: tuple[str, ...]
    registered_on: str
    seed: int


def canonical(p: Protocol) -> str:
    """The protocol as canonical JSON: sorted keys, no spaces, UTF-8 kept (tuples become lists)."""
    return json.dumps(asdict(p), sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def fingerprint(p: Protocol) -> str:
    return hashlib.sha256(canonical(p).encode("utf-8")).hexdigest()


A02: Final = Protocol(
    key="INT-A02",
    version="proto-int-a02-v1",
    title="Calibración coherente multiclase",
    question=(
        "¿Una calibración multiclase que suma 1 por construcción (pool logarítmico del modelo y del mercado sin margen, con un "
        "término por resultado) pronostica igual o mejor que la probabilidad que hoy se muestra, calibrada selección por "
        "selección con cal-logit2-v1 y reescalada después para que el mercado sume 1?"
    ),
    null="El log loss multiclase fuera de muestra de la calibración coherente es mayor que el de la reescalada.",
    alternative="El log loss multiclase fuera de muestra de la calibración coherente es igual o menor que el de la reescalada.",
    unit=(
        "Un partido, un modelo y un mercado completo de la vista común (1X2, más/menos 2,5 y ambos marcan), con la "
        "probabilidad de cada resultado."
    ),
    data=(
        "Partidos con resultado liquidado desde el 1-sep-2026. Probabilidad del modelo: su última predicción guardada 3 h o "
        "más antes del saque. Mercado: el consenso sin margen más reciente con 6 h o menos de antigüedad en ese mismo "
        "momento. Resultado: el marcador final del proveedor."
    ),
    split=(
        "Walk-forward por día de Bogotá: el calibrador del día D se ajusta solo con partidos jugados y liquidados antes de que "
        "empiece D, en una ventana de 28 días, con al menos 500 partidos y 3 días previos (las mismas reglas que "
        "cal-logit2-v1). La referencia reescalada se ajusta con las mismas reglas y los mismos días."
    ),
    primary_metric=(
        "Diferencia pareada del log loss multiclase medio (coherente menos reescalada) por día, agregada sobre los días fuera de "
        "muestra, con su intervalo del 95 % por bootstrap de días."
    ),
    pass_rule=(
        "Cada mercado suma 1 (|suma - 1| ≤ 1e-9) en el 100 % de los casos; el límite superior del intervalo del 95 % de la "
        "diferencia pareada es ≤ 0; y el ECE de cada resultado no empeora más de 0,005 frente a la reescalada."
    ),
    reject_rule=(
        "El límite superior del intervalo es > 0 o el ECE de algún resultado empeora más de 0,005: la reescalada sigue siendo "
        "la cifra coherente y la calibración coherente queda en el LAB con su motivo."
    ),
    secondary=(
        "Lo mismo frente al modelo sin calibrar y frente al mercado sin margen solo.",
        "ECE de las selecciones que el modelo marca (la población que juzga la decisión), coherente frente a cal-logit2-v1.",
        "Peso del mercado en el pool por mercado y por modelo, con su intervalo.",
        "Diagramas de fiabilidad por resultado (10 grupos de igual tamaño).",
    ),
    min_sample=(
        "Al menos 1.500 partidos-mercado fuera de muestra en al menos 5 días por mercado (el mínimo de calib-gate-v1). Con "
        "menos, el resultado es «pendiente por muestra» y no se interpreta."
    ),
    power_note=(
        "Con n días fuera de muestra y desviación típica s de la diferencia diaria, la diferencia mínima detectable es "
        "2,80·s/√n (alfa = 0,05 bilateral, potencia 0,80). El informe da s medida y la diferencia mínima detectable alcanzada."
    ),
    exclusions=(
        "Partidos sin resultado liquidado, aplazados, suspendidos o anulados.",
        "Partido-mercado sin consenso sin margen de 6 h o menos en el momento de la predicción.",
        "Probabilidades fuera de (0, 1) o mercados incompletos.",
    ),
    stopping=(
        "Una sola evaluación con los datos disponibles al ejecutarla; no se repite cambiando la ventana, los días ni los "
        "mercados. Un cambio de método es un protocolo nuevo (v2) registrado antes de mirar."
    ),
    segments=("Por mercado: 1X2, más/menos 2,5 y ambos marcan.", "Por modelo.", "Ligas prioritarias frente al resto."),
    registered_on="2026-11-11",
    seed=20261111,
)

A09: Final = Protocol(
    key="INT-A09",
    version="proto-int-a09-v1",
    title="E4: tiros y xG en los ratings",
    question=(
        "¿Unos ratings de ataque y defensa que usan tiros, tiros a puerta y xG de los partidos anteriores pronostican mejor los "
        "goles que el modelo actual, y aportan algo que el mercado no tiene?"
    ),
    null=(
        "El retador no baja el log loss del modelo actual o su peso frente al mercado en el pool no es mayor que cero en ningún "
        "segmento preregistrado."
    ),
    alternative=(
        "El retador baja el log loss del modelo actual y su peso frente al mercado en el pool es mayor que cero en al menos un "
        "segmento preregistrado."
    ),
    unit="Un partido: la distribución de goles de cada equipo y los mercados 1X2 y más/menos 2,5 que se derivan de ella.",
    data=(
        "Estadísticas de partido del proveedor (tiros, tiros a puerta y xG cuando exista) solo de partidos terminados antes del "
        "momento de cada pronóstico; resultados y consenso sin margen como en INT-A02. Ligas con estadísticas guardadas."
    ),
    split=(
        "Walk-forward por día de Bogotá: los ratings y sus pesos del día D usan solo partidos terminados antes de D. Ninguna "
        "estadística del propio partido ni posterior a su saque."
    ),
    primary_metric=(
        "Diferencia pareada del log loss multiclase 1X2 (retador menos modelo actual) por día, con intervalo del 95 % por "
        "bootstrap de días; y el peso del retador frente al mercado en el pool logarítmico (fbi.research.blend), con su "
        "intervalo por bootstrap de días."
    ),
    pass_rule=(
        "En al menos un segmento preregistrado: el límite superior del intervalo de la diferencia es < 0, el límite inferior del "
        "intervalo del peso es > 0 y la auditoría de fugas sale limpia."
    ),
    reject_rule="Falla cualquiera de las tres: el retador se archiva con su motivo y el modelo activo no cambia.",
    secondary=(
        "Lo mismo en más/menos 2,5.",
        "Cobertura de xG por liga y temporada; resultados sin xG (solo tiros) para las ligas que no lo tienen.",
    ),
    min_sample=(
        "Al menos 1.500 partidos fuera de muestra por segmento evaluado; un segmento con menos se informa como «pendiente por "
        "muestra»."
    ),
    power_note="Diferencia mínima detectable alcanzada = 2,80·s/√n, con s medida de la diferencia diaria.",
    exclusions=(
        "Partidos de equipos con menos de 5 partidos anteriores con estadísticas en la ventana.",
        "Partidos sin resultado liquidado o sin consenso de mercado.",
    ),
    stopping="Una sola evaluación; ningún ajuste de rasgos tras ver resultados sin un protocolo v2 registrado antes.",
    segments=("Ligas prioritarias (Champions y cinco grandes).", "El resto de ligas con estadísticas.", "Mercados 1X2 y más/menos 2,5."),
    registered_on="2026-11-11",
    seed=20261111,
)

B09: Final = Protocol(
    key="INT-B09",
    version="proto-int-b09-v1",
    title="Estudio de eventos: noticia → precio",
    question=(
        "Cuando PrediGol registra un hecho de disponibilidad de un jugador (baja, duda, sanción o titularidad), ¿el precio del "
        "mercado se mueve después (información que llegamos a tener antes) o ya se había movido (el mercado ya lo sabía)?"
    ),
    null="El movimiento del precio después del momento en que PrediGol conoce el hecho no es mayor que el de los controles.",
    alternative=(
        "Después del momento en que PrediGol conoce el hecho, el precio del equipo afectado se mueve en la dirección del hecho "
        "más que en los controles."
    ),
    unit=(
        "Un evento: la primera afirmación de disponibilidad de un jugador para un partido, con la hora en que PrediGol la "
        "conoció y su fuente."
    ),
    data=(
        "Afirmaciones con hora conocida (proveedor y Research v2) y la probabilidad sin margen del equipo afectado en 1X2 "
        "(consenso guardado) antes y después de esa hora, siempre antes del saque."
    ),
    split="No hay ajuste de modelo: cada evento se mide con los precios guardados alrededor de su hora.",
    primary_metric=(
        "Cambio medio de la probabilidad sin margen del equipo afectado, en la dirección esperada del hecho, entre la última "
        "cotización anterior al evento y la última anterior al saque, menos el mismo cambio en controles (los mismos partidos "
        "con horas barajadas); intervalo del 95 % por bootstrap agrupado por partido."
    ),
    pass_rule=(
        "Informe válido si: hay al menos 200 eventos con precio antes y después, el intervalo está agrupado por partido y los "
        "controles barajados quedan cerca de 0 (su intervalo incluye 0)."
    ),
    reject_rule=(
        "Si el movimiento posterior no supera a los controles en ningún segmento (intervalo que incluye 0 o por debajo), el "
        "mercado ya tenía los hechos y no se propone ninguna fuente nueva."
    ),
    secondary=(
        "Anticipación: qué parte del movimiento total del día ocurre después del evento.",
        "Por tipo de fuente (proveedor, oficial, medio, rumor), por tipo de hecho y por liga.",
    ),
    min_sample="Al menos 200 eventos con precio antes y después; menos, «pendiente por muestra».",
    power_note=(
        "Con una desviación típica de unos 2 pp por evento, ver 0,5 pp pide unos 7,85·4/0,25 ≈ 126 eventos; se fijan 200 por la dependencia entre "
        "eventos del mismo partido. El informe da la diferencia mínima detectable alcanzada."
    ),
    exclusions=(
        "Eventos a menos de 30 minutos del saque (sin precio posterior útil).",
        "Eventos sin hora conocida o sin consenso antes y después.",
        "Repeticiones de un mismo hecho: solo cuenta la primera afirmación por partido, jugador y tema.",
    ),
    stopping="Una sola evaluación con los datos disponibles; los segmentos son los preregistrados.",
    segments=("Tipo de fuente.", "Tipo de hecho.", "Ligas prioritarias frente al resto."),
    registered_on="2026-11-11",
    seed=20261111,
)

A08: Final = Protocol(
    key="INT-A08",
    version="proto-int-a08-v1",
    title="E6: quién juega, en el modelo",
    question=(
        "¿Saber quién juega (el once esperado de player-engine-v1, con las bajas que el proveedor había publicado a la hora "
        "de decidir) mejora el pronóstico 1X2 del modelo actual y aporta algo que el mercado no tiene?"
    ),
    null=(
        "En ninguno de los dos segmentos preregistrados el retador e6-xi-v1 baja el log loss 1X2 del modelo actual y, a la "
        "vez, tiene un peso mayor que cero frente al mercado en el pool, con la corrección de Holm."
    ),
    alternative=(
        "En al menos un segmento preregistrado, con la corrección de Holm, el retador baja el log loss 1X2 del modelo actual "
        "y su peso frente al mercado en el pool es mayor que cero."
    ),
    unit=(
        "Un partido en el corte T90, 90 minutos antes del saque (el primer punto de control final de decision-v1 y el "
        "momento de player-engine-v1): las probabilidades 1X2 del modelo actual, del retador y del mercado en T90, y el "
        "resultado reglamentario."
    ),
    data=(
        "Partidos terminados con marcador de ligas y temporadas con estadísticas de jugador del proveedor "
        "(statistics_players en raw.league_coverage), con saque desde el 5-oct-2026 en el segmento B y desde el "
        "24-oct-2026 en el A: las bajas solo tienen historial real (origin = answer) desde el 22-oct-2026; lo anterior es "
        "una copia que no sabe cuándo se quitó a un jugador de la lista. Modelo actual: poisson, con la regla de INT-A09; "
        "su última predicción en tiempo real con corte y guardado en T90 o antes. Mercado: el consenso Shin completo más "
        "reciente con 3 h o menos de antigüedad en T90 (en la práctica, la captura de unas 2 h 56 min antes del saque). "
        "Jugadores: core.fixture_player_stats (minutos, titularidad y valoración) de los partidos ya conocidos en T90 "
        "según player-engine-v1 (available_at). Bajas: core.player_availability_obs con observed_at en T90 o antes, "
        "nunca core.player_absences. Para los coeficientes, partidos terminados desde el 1-jul-2025 con su once real."
    ),
    split=(
        "Walk-forward. Retador e6-xi-v1: el modelo actual inclinado por z = fuerza local menos fuerza visitante (local por "
        "exp(beta z), visitante por exp(-beta z), empate igual, renormalizado). Fuerza de un equipo: suma de (minutos "
        "esperados en T90 menos minutos habituales) / 90 por (valoración del jugador menos el nivel de reemplazo de su "
        "puesto). Minutos esperados de player-engine-v1 con las bajas conocidas en T90; habituales, su media en los 10 "
        "últimos partidos cubiertos del equipo; valoración, la media reciente de sus 20 últimas apariciones conocidas de "
        "20 minutos o más, encogida hacia el reemplazo (percentil 25 del puesto). El beta del día D se ajusta por máxima "
        "verosimilitud con partidos cuyo saque más 3 h es anterior al inicio de D (730 días, desde el 1-jul-2025), con su "
        "once real y una base de goles walk-forward (ratings por competición con historia anterior a su día). Nada del "
        "propio partido posterior a T90."
    ),
    primary_metric=(
        "Por celda, la diferencia pareada del log loss 1X2 (retador menos modelo actual) con intervalo por bootstrap de "
        "días (2.000 remuestreos) y el peso del retador frente al mercado en el pool logarítmico de fbi.research.blend con "
        "intervalo por bootstrap de días (500). Para Holm, el valor p unilateral de cada uno (la fracción de remuestreos "
        "con diferencia mayor o igual que 0, o con peso menor o igual que 0); el valor p de la celda es el mayor de los dos."
    ),
    pass_rule=(
        "PASA si en al menos una celda primaria con la muestra mínima el valor p de la celda queda por debajo de su umbral "
        "de Holm (K = 2 y alfa unilateral 0,025: 0,0125 en el primer paso y 0,025 en el segundo, que equivale a que el "
        "intervalo del 97,5 % o del 95 % de la diferencia quede por debajo de 0 y el del peso por encima de 0) y la "
        "auditoría de fugas sale limpia."
    ),
    reject_rule=(
        "RECHAZA si alguna celda primaria tiene la muestra mínima y ninguna pasa, o si la auditoría de fugas tiene alguna "
        "violación: el retador se archiva con su motivo y con la diferencia mínima detectable alcanzada, para distinguir "
        "que no haya efecto de que no se pudiera ver, y el modelo activo no cambia. Si ninguna celda primaria llega a la "
        "muestra mínima, el resultado es PENDIENTE POR MUESTRA."
    ),
    secondary=(
        "Más/menos 2,5 en T90, con la fuerza de atacantes y medios y la de defensas y porteros y sus dos coeficientes.",
        "Corte T15, 15 minutos antes del saque, con el once confirmado del último RAW pedido antes: diferencia frente al "
        "modelo actual. Su peso frente al mercado no se interpreta: el último consenso guardado es de unas 2 h 56 min "
        "antes del saque y no conoce la alineación.",
        "Mercado más quién juega: el coeficiente theta de inclinar el mercado por z, con su intervalo; mayor que 0 indica "
        "que el precio guardado reacciona menos de lo debido a quién juega.",
        "Versión justa: solo las bajas vistas antes del instante del consenso usado.",
        "En A, partidos con alguna baja Missing Fixture de un habitual (45 minutos o más de media) frente al resto.",
        "Contexto: el mismo ajuste sobre dixon_coles y elo_ologit, y las ligas prioritarias (Champions y cinco grandes).",
    ),
    min_sample=(
        "Al menos 1.500 partidos fuera de muestra por celda primaria; con menos, la celda es «pendiente por muestra» y no "
        "se mide, ni ella ni sus secundarias."
    ),
    power_note=(
        "Con la desviación típica por partido de las diferencias pareadas de IA-039 (unos 0,25; es de otro experimento, "
        "con un retador mucho más distinto del modelo actual que este, así que es una cota pesimista), 1.500 partidos ven "
        "0,018 de log loss (0,020 con Holm) y ver 0,01 pide 4.906 (5.941 con Holm). Si quién juega mueve las "
        "probabilidades una media cuadrática d en log-odds, la desviación por partido es unos 0,82 d y la mejora esperada "
        "unos 0,34 d al cuadrado: d = 0,10 pide 4.566 partidos (5.529 con Holm), d = 0,15 pide 2.030 (2.458) y d = 0,20 "
        "pide 1.142 (1.383). El informe da la desviación medida y la diferencia mínima detectable alcanzada por celda."
    ),
    exclusions=(
        "Partidos sin marcador, aplazados, suspendidos, anulados o en cuarentena de la validación histórica.",
        "Liga y temporada sin estadísticas de jugador del proveedor.",
        "Algún equipo con menos de 5 partidos cubiertos conocidos en T90 en los 365 días anteriores.",
        "Sin predicción del modelo actual en T90 o sin consenso Shin completo de 3 h o menos en T90.",
        "Para ajustar los coeficientes, partidos sin 11 titulares con minutos en cada equipo.",
    ),
    stopping=(
        "Una sola evaluación: el primer día en que la ejecución en seco (--dry-run, que cuenta partidos y audita fugas sin "
        "leer ningún marcador) muestre 1.500 partidos en las dos celdas primarias, o el 31-mar-2027 si antes no ocurre. "
        "La ejecución en seco se puede repetir. Ningún cambio de rasgos, cortes, coeficientes ni segmentos tras ver "
        "resultados sin un protocolo v2 registrado antes."
    ),
    segments=(
        "A: ligas y temporadas con bajas del proveedor (injuries = true en raw.league_coverage), 1X2 en T90. Primaria.",
        "B: ligas y temporadas con estadísticas de jugador y sin bajas del proveedor, 1X2 en T90. Primaria.",
        "Holm sobre A y B con K = 2 fijo, aunque una de las dos quede pendiente por muestra.",
    ),
    registered_on="2026-11-11",
    seed=20261111,
)


C02: Final = Protocol(
    key="INT-C02",
    version="proto-int-c02-v1",
    title="Banco de repetición: la variante actual reproduce la sombra",
    question=(
        "¿Una ejecución guardada de la sombra, preguntada otra vez con la misma petición byte a byte (mismo prompt, esquema, "
        "modelo y esfuerzo) por la vía Batch del LAB, da la misma postura o el mismo veredicto que dio, al menos tanto como "
        "coinciden entre sí dos repeticiones de esa misma llamada?"
    ),
    null="La repetición cambia lo guardado más de lo que cambia repetir la misma llamada: el banco no reproduce la sombra.",
    alternative="La repetición cambia lo guardado como mucho tanto como cambia repetir la misma llamada.",
    unit=(
        "Una palabra de una respuesta guardada: la postura de cada candidato (aa-v1, pa-v1), el veredicto de cada candidato "
        "(cd-v1, que equivale uno a uno a la palabra de ctx-adj-v1 y a su efecto en decision-v2) o, en el contexto del "
        "agente Partido, el conjunto de sus señales (código:dirección). Cada unidad tiene tres lecturas: la guardada (S) y "
        "dos repeticiones de la misma petición (R1 y R2), pedidas en el mismo lote."
    ),
    data=(
        "Ejecuciones pagadas de la sombra (ai.agent_runs, run_kind shadow, estado ok, abstain o invalid) de la versión del "
        "agente en vigor, empezadas después del último cambio de una optimización que da forma a la petición, cuya pregunta "
        "se rehace byte a byte desde lo guardado: el paquete (package_hash), la porción (slice_hash), los nombres de los "
        "candidatos, los hallazgos de contra-v1, la vista del Council sobre las respuestas guardadas de los agentes, la "
        "identidad de la tarea (idem_key) y el hash de la petición (ai.usage.input_hash). Ventana por defecto: los 14 días "
        "completos de Bogotá anteriores a la ejecución; como mucho 200 ejecuciones por ámbito, elegidas por la semilla."
    ),
    split="Sin ajuste de modelo: cada unidad se mide con su respuesta guardada y sus dos repeticiones.",
    primary_metric=(
        "Por ámbito (la tarea de un agente o un brazo del Council), sobre las unidades con sus tres lecturas válidas: el "
        "número de unidades en que S difiere de R1, frente al número en que R2 difiere de R1."
    ),
    pass_rule=(
        "PASA si: cambios(S frente a R1) <= cambios(R2 frente a R1); las repeticiones que no se sostienen son como mucho "
        "el 3 % de las que vuelven y como mucho 1 punto más que las guardadas que no se sostuvieron; y hay al menos 200 "
        "unidades completas de al menos 30 partidos. Es la regla de la equivalencia del Gate A con la ejecución guardada "
        "en el lugar de la variante."
    ),
    reject_rule=(
        "NO PASA si la repetición cambia más de lo guardado que la segunda repetición o si las inválidas superan su límite: "
        "el banco no sirve para comparar variantes en ese ámbito hasta saber por qué (entrada no reproducida, vía Batch "
        "frente a tiempo real, cambio del modelo del proveedor). Con el intervalo del 95 % de la diferencia por encima de 0 "
        "es un fallo claro; si lo cubre, la muestra no distingue y se dice así. Con menos muestra: INSUFICIENTE, no se "
        "interpreta."
    ),
    secondary=(
        "La diferencia cambios(S frente a R1) menos cambios(R2 frente a R1), por unidad, con su intervalo del 95 % por "
        "bootstrap de partidos (2.000 remuestreos, semilla del protocolo): se informa, no decide.",
        "El cambio de S frente a las dos repeticiones a la vez y el acuerdo de las tres lecturas.",
        "Qué palabras se mueven y hacia dónde: hacia aprobar o apoyar, y hacia restringir.",
        "El acuerdo de la confianza del Council (LOW, MEDIUM, HIGH), que no decide nada.",
        "El coste real frente al previsto.",
    ),
    min_sample=(
        "200 unidades completas de al menos 30 partidos por ámbito; con menos, INSUFICIENTE. El 11-nov-2026 llegan los dos "
        "brazos del Council (ma-v1: 837 unidades de 142 partidos; ma-v1-h: 421 de 110); Partido (match-v5: 10 en la "
        "evaluación y 7 en el contexto) y Estadísticas (stats-v4: 7) quedan INSUFICIENTE."
    ),
    power_note=(
        "Con una reproducción perfecta los dos recuentos tienen la misma esperanza y la regla puntual pasa algo más de la "
        "mitad de las veces (prueba de simulación en tests/unit/test_replay_measure.py): un NO PASA cuyo intervalo cubre 0 "
        "dice que la muestra no distingue. Con n unidades y una tasa de cambio al repetir q, el error típico de la "
        "diferencia es del orden de la raíz de 2q/n: con q = 0,2 y n = 545, unos 2,7 puntos (más por la agrupación por "
        "partido, que el intervalo ya recoge)."
    ),
    exclusions=(
        "Las escaladas a Opus (fuera de la versión 1 del banco).",
        "Las ejecuciones de una versión del agente distinta de la vigente (match-v1 a v4, stats-v2 y v3 el 11-nov).",
        "Las ejecuciones cuya pregunta no se rehace byte a byte, cada una con su código.",
        "Las ejecuciones empezadas antes del último cambio de una optimización (batch, native_schema, cache_layout o los "
        "interruptores de esas optimizaciones).",
    ),
    stopping=(
        "Una sola evaluación por ejecución con gasto. Una repetición que no vuelve (errored, expired) se pide otra vez, "
        "solo ella y con la misma clave. No se repite un lote para cambiar un NO PASA: una medición nueva es una ventana "
        "nueva de ejecuciones guardadas que no estaban en la anterior, decidida antes de mirar, y se informan las dos; un "
        "cambio de método es un protocolo v2 registrado antes."
    ),
    segments=(
        "Por ámbito: match/context, match/evaluation, stats/evaluation, player/evaluation, council/ma-v1, council/ma-v1-h y "
        "council/cs-v1.",
    ),
    registered_on="2026-11-11",
    seed=20261111,
)


PROTOCOLS: Final[dict[str, Protocol]] = {p.key: p for p in (A02, A09, B09, A08, C02)}


def require(key: str) -> Protocol:
    """The registered protocol of an experiment; an experiment without one does not run."""
    try:
        return PROTOCOLS[key]
    except KeyError:
        raise LookupError(f"no hay protocolo registrado para {key}: regístralo antes de mirar los datos") from None


def stamp(key: str) -> dict[str, Any]:
    """What a LAB result carries so it can be checked against its protocol."""
    p = require(key)
    return {"protocol": p.key, "version": p.version, "fingerprint": fingerprint(p), "framework": VERSION}
