"""The own protocols, as records that can be signed (IA-143): AD-F04, AD-F05 and AD-F06 of IA-117..IA-119, and AD-D11 of IA-125 (IA-145).

They are not ``fbi.research.protocol`` protocols: each is the record of the module that applies it - the thresholds of the stock phrases
(``repeat-check-v1``, ``fbi.chronicle.repetition``), the preregistered comparison of the retirement of the duplicated texts
(``retire-compare-v1``, ``fbi.chronicle.retire``), the human review by sample (``chronicle-protocol-v1``, ``fbi.chronicle.protocol``) and
the preregistered non-inferiority comparison of the retirement of ``review-v2`` (``review-retire-v1``, ``fbi.ai.review_retirement``: its
``PROTOCOL`` word for word and the control of its step ``sample``).
Their figures are written out HERE because a reader that may not import the chronicle or the AI layer (the console, through the import
cycle of ``tests/unit/test_architecture.py``) needs their fingerprint; ``tests/unit/test_protocol_signatures.py`` holds every figure equal
to the constant its module applies, and pins every fingerprint. Changing a threshold is therefore three visible changes: the module, this record
and its pinned fingerprint - and the owner's signature of the old fingerprint stops counting.

The fingerprint is the SHA-256 of the record's canonical JSON (sorted keys, no spaces, UTF-8 kept), the same canonical form as
``fbi.research.protocol``. Texts in Spanish: the owner reads them. Pure."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from typing import Any, Final

FRAMEWORK: Final = "own-record-v1"

STOCK_LIST_SHA256: Final = "7ccb3253ef3c223a1269b7aef3d50b5646a91b3dcee0310caf260dcae97def54"
"""The SHA-256 of the closed list of stock phrases of ``repeat-check-v1`` (``repetition.GENERIC``, its patterns by language as canonical
JSON): a new formula in the list is a different rule, so it changes the fingerprint of AD-F04."""

F04: Final[Mapping[str, Any]] = {
    "key": "AD-F04",
    "version": "repeat-check-v1",
    "framework": FRAMEWORK,
    "piece": "IA-117",
    "where": "fbi/chronicle/repetition.py",
    "title": "Coletillas y repeticiones de la crónica única: umbrales",
    "registered_on": "2026-11-17",
    "rule": {
        "share_max": 0.30, "min_corpus": 20, "window_days": 14, "corpus_limit": 300, "generic_rate_max": 0.10, "repeat_rate_max": 0.10,
        "stock_list_sha256": STOCK_LIST_SHA256,
    },
    "says": (
        "Una frase es coletilla si está en la lista cerrada de fórmulas (alineaciones no confirmadas, sin datos suficientes, la jerga del "
        "sistema) o si su plantilla (nombres, números y cifras enmascarados) la llevan al menos el 30 % de las crónicas recientes de otros "
        "partidos (las 300 más nuevas de los últimos 14 días; con menos de 20 no se mide). Es repetición si la crónica anterior de uno de "
        "los dos equipos ya dijo la misma frase. Por crónica: como mucho 1 frase de cada 10 coletilla y 1 de cada 10 repetición. Una frase "
        "que cita un hecho obligatorio del plan nunca se quita (exenta). En shadow mide y no quita nada; on las quitaría como frases sin "
        "apoyo. Firmar estos umbrales no pone on: lo pone el dueño cambiando FBI_CHRONICLE_REPEAT."
    ),
}

F05: Final[Mapping[str, Any]] = {
    "key": "AD-F05",
    "version": "retire-compare-v1",
    "framework": FRAMEWORK,
    "piece": "IA-119",
    "where": "fbi/chronicle/retire.py",
    "title": "Retirada de los textos duplicados: la comparación preregistrada",
    "registered_on": "2026-11-17",
    "rule": {
        "chronicle": "chronicle-v4", "texts": ["user-narrative-v3", "brief-v8", "match-analysis-v1"],
        "metrics": {"support": "higher", "coverage": "higher", "unsupported": "lower", "stock": "lower", "cost": "lower"},
        "applies": {"user-narrative-v3": ["support", "coverage", "unsupported", "stock", "cost"],
                    "brief-v8": ["support", "coverage", "unsupported", "stock", "cost"], "match-analysis-v1": ["coverage"]},
        "interval": "wilson-95", "margin": 0.05, "cost_margin": "0.10", "min_matches": 100,
    },
    "says": (
        "Sobre los mismos partidos (los que Intelligence analizó en la ventana y para los que se intentó la crónica única) se compara "
        "chronicle-v4 con cada texto que sustituiría: apoyo (más alto; v4 debe ser MEJOR, su intervalo por encima), cobertura antes del "
        "saque (más alta), textos con una frase de alto riesgo que el plan no autoriza (más baja), coletillas (más baja) y coste por texto "
        "aceptado (más bajo, sin intervalo). No peor: una tasa, si el intervalo del 95 % (Wilson) de v4 alcanza la del otro con un margen "
        "de 5 puntos; el coste, si no lo supera en más de un 10 %. Mínimo 100 partidos; con menos, INSUFICIENTE. Las tarjetas de análisis "
        "(reglas, sin modelo) solo comparan su cobertura. Firmar la comparación no retira ningún texto: cada retirada es un cambio de "
        "interruptor que hace y firma el dueño, y no se borra ninguna fila."
    ),
}

F06: Final[Mapping[str, Any]] = {
    "key": "AD-F06",
    "version": "chronicle-protocol-v1",
    "framework": FRAMEWORK,
    "piece": "IA-118",
    "where": "fbi/chronicle/protocol.py",
    "title": "Evaluación factual de la crónica única: revisión humana por muestreo",
    "registered_on": "2026-11-17",
    "rule": {
        "seed": "chronicle-protocol-v1", "sample": 50, "double": 10, "unsupported_max": 0, "agreement_min": 0.90, "confidence": 0.95,
        "labels": ["SUPPORTED", "NOT_IN_SOURCES", "CONTRADICTED_BY_SOURCES", "UNCLEAR"],
        "thresholds": {"unsupported_sentences_max": 0, "sample": 50, "double": 10, "agreement_min": 0.90, "stock_share_max": 0.30,
                       "generic_rate_max": 0.10, "repeat_rate_max": 0.10, "min_corpus": 20},
    },
    "says": (
        "50 crónicas revisadas por chronicle-review-v2, elegidas por un hash fijo de la semilla y su id (la misma muestra cada vez); 10 de "
        "ellas las lee a ciegas una segunda persona. Cada frase: SUPPORTED, NOT_IN_SOURCES, CONTRADICTED_BY_SOURCES o UNCLEAR, viendo los "
        "hechos que cita y nunca el veredicto del código. Criterio: 0 frases sin apoyo en las 50 (con n = 50 y 0 fallos solo se puede "
        "afirmar una tasa por debajo del 5,8 %, cota unilateral al 95 %); acuerdo de la doble lectura de al menos el 90 %, y un desacuerdo "
        "se lista, no lo resuelve el código. La crónica se mide además con los umbrales de coletillas de AD-F04. Las etiquetas humanas no "
        "entrenan ni ajustan nada."
    ),
}

D11: Final[Mapping[str, Any]] = {
    "key": "AD-D11",
    "version": "review-retire-v1",
    "framework": FRAMEWORK,
    "piece": "IA-125",
    "where": "fbi/ai/review_retirement.py",
    "title": "Retirada de review-v2: comparación preregistrada de no inferioridad frente al cierre",
    "registered_on": "2026-11-17",
    "rule": {
        "protocol": {
            "version": "review-retire-v1",
            "status": "propuesto: lo firma el dueño antes de mirar la ventana",
            "population": "las selecciones que review-v2 revisó con modelo (ai.pick_reviews, engine llm, status ok) y que decision-v2 "
                          "decidió en sombra antes del saque, con su evaluación eval-sel-v1 y un precio de cierre (clv-v1)",
            "reference": "review-v2: la selección se queda cuando la revisión combinada más reciente antes del saque es APPROVE",
            "new_path": "decision-v2 + reglas + Council reducido: la selección se queda cuando decision-v2 la toma (taken de eval-sel-v1)",
            "metric": "diferencia pareada, por selección examinada, del valor frente al cierre de lo que cada camino deja pasar: "
                      "clv x (se queda en el camino nuevo - se queda en review-v2)",
            "interval": "IC95 bilateral por remuestreo de días enteros de Bogotá (2.000 réplicas, semilla fija)",
            "margin": "0.005",
            "rule": "NO_INFERIOR si el extremo inferior del IC95 es mayor o igual que -margen; INFERIOR si no; INSUFICIENTE bajo la muestra",
            "min_selections": 300,
            "min_days": 14,
            "seed": 20261117,
            "replicates": 2000,
            "window": "las 4 semanas siguientes a la firma; nada anterior a la firma cuenta",
        },
        "control": {"share": "0.20", "salt": "review-v2-control-v1", "buckets": 10000},
    },
    "says": (
        "Sobre las mismas selecciones (las que review-v2 revisó con modelo y decision-v2 decidió en sombra antes del saque, con su "
        "evaluación y su precio de cierre) se compara lo que cada camino deja pasar: la diferencia pareada del CLV por selección "
        "examinada entre el camino nuevo (decision-v2, reglas y Council reducido) y review-v2. Intervalo del 95 % por remuestreo de días "
        "enteros de Bogotá (2.000 réplicas, semilla 20261117). NO_INFERIOR si su extremo inferior es mayor o igual que -0,005 (medio "
        "punto de CLV); INFERIOR si no; con menos de 300 selecciones o de 14 días, INSUFICIENTE. Cuenta solo la ventana de las 4 semanas "
        "siguientes a la firma. En el paso sample el modelo sigue revisando un 20 % fijo de las selecciones (sal review-v2-control-v1) "
        "como grupo de control. Firmar el protocolo no retira nada ni mueve FBI_REVIEW_V2: cada paso (no_opus, sample, off) es un cambio "
        "de interruptor que hace y firma el dueño, y no se borra ninguna fila de ai.pick_reviews."
    ),
}

RECORDS: Final[tuple[Mapping[str, Any], ...]] = (F04, F05, F06, D11)


def canonical(record: Mapping[str, Any]) -> str:
    return json.dumps(record, sort_keys=True, ensure_ascii=False, separators=(",", ":"))


def fingerprint(record: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical(record).encode("utf-8")).hexdigest()


def stock_list_hash(patterns: Mapping[str, str]) -> str:
    """The hash of a closed list of stock phrases (its patterns by language), as ``STOCK_LIST_SHA256`` is computed."""
    return hashlib.sha256(canonical(dict(patterns)).encode("utf-8")).hexdigest()


__all__ = ["D11", "F04", "F05", "F06", "FRAMEWORK", "RECORDS", "STOCK_LIST_SHA256", "canonical", "fingerprint", "stock_list_hash"]
