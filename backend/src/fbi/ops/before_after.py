"""The board BEFORE and AFTER: every indicator of section 23 of the restructuring plan against its frozen baseline (RP-13.1).

A difference between two dates proves nothing unless the same thing was measured twice, so this module refuses to say «mejoró» without the
rules of the plan:

    same population ... the two measurements share the definition (``definition_version``) and the fixed set of competitions
                        (``base_before_utc``); otherwise the indicator is «no comparable» and nothing else is said about it
    an interval ....... every figure travels with its standard error or its counts; a difference whose interval includes zero is
                        «sin cambio demostrado»; a figure that has no way to be given an interval is never called better
    three columns ..... improved, no change proven, worsened (the three are always filled, empty or not), beside what could not be compared
    attribution ....... each indicator is tied to the pieces of the plan that could move it, to see which ones contributed nothing

The thresholds are those proposed in section 23 and approved by the owner (decision D7) BEFORE measuring; they are written once below, a test
pins their fingerprint, and nothing in this module reads a result to choose them.

Pure: it reads two documents in the format of ``scripts/intel_baseline_report.py`` (``baseline-v1.json``) and writes a document. The measurement
itself is the saved query (``scripts/intel_baseline.sql``) run again with a new cut: the same query, so the same definition.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final

VERSION: Final = "before-after-v1"
Z: Final = 1.96

IMPROVED: Final = "mejoro"
NO_CHANGE: Final = "sin_cambio_demostrado"
WORSENED: Final = "empeoro"
INFORMED: Final = "informado"
NOT_COMPARABLE: Final = "no_comparable"
NOT_MEASURED: Final = "sin_medir"
COLUMNS: Final = (IMPROVED, NO_CHANGE, WORSENED)

LOWER: Final = "lower"
HIGHER: Final = "higher"


@dataclass(frozen=True, slots=True)
class Measure:
    """One figure of an indicator. ``se`` is its standard error; ``successes`` and ``n`` give a proportion its own interval; ``count`` a
    count its Poisson one. A figure with none of them has no interval and is never called better."""

    key: str
    value: float | None
    n: int | None = None
    se: float | None = None
    successes: float | None = None
    count: float | None = None
    direction: str | None = None  # LOWER or HIGHER is better; None: informed only
    unit: str = ""


def _f(x: Any) -> float | None:
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if math.isfinite(v) else None


def _one(rows: Sequence[Mapping[str, Any]]) -> Mapping[str, Any] | None:
    return rows[0] if rows else None


def _share(x: float | None, n: float | None) -> float | None:
    return None if x is None or not n else x / n


def _proportion(key: str, x: float | None, n: float | None, direction: str, unit: str = "proporción") -> Measure:
    return Measure(key, _share(x, n), n=None if n is None else int(n), successes=x, direction=direction, unit=unit)


def _poisson(key: str, x: float | None, direction: str, unit: str = "recuento") -> Measure:
    return Measure(key, x, count=x, direction=direction, unit=unit)


# ── the readers of each indicator: rows of its section -> measures ────────────────────────────────────────────────────────────────────────

def _i1(rows: Sequence[Mapping[str, Any]]) -> list[Measure]:
    r = _one(rows)
    return [] if r is None else [Measure("raw_minus_market", _f(r.get("raw_minus_market")), _int(r.get("matches")), _f(r.get("raw_se")),
                                         direction=LOWER, unit="log-loss")]


def _i2(rows: Sequence[Mapping[str, Any]]) -> list[Measure]:
    r = _one(rows)
    return [] if r is None else [Measure("shown_minus_market", _f(r.get("shown_minus_market")), _int(r.get("matches")), _f(r.get("shown_se")),
                                         direction=LOWER, unit="log-loss")]


def _i3(rows: Sequence[Mapping[str, Any]]) -> list[Measure]:
    out = []
    for r in rows:
        gap, freq, n = _f(r.get("gap_points")), _f(r.get("freq")), _int(r.get("n"))
        se = 100 * math.sqrt(freq * (1 - freq) / n) if freq is not None and n else None
        out.append(Measure(f"{r.get('layer')}/{r.get('family')}", None if gap is None else abs(gap), n, se, direction=LOWER, unit="puntos"))
    return out


def _i4(rows: Sequence[Mapping[str, Any]]) -> list[Measure]:
    return [Measure(f"{r.get('layer')}/{r.get('family')}", _f(r.get("loss_minus_market")), _int(r.get("n")), _f(r.get("se")),
                    direction=LOWER, unit="log-loss") for r in rows]


def _i5(rows: Sequence[Mapping[str, Any]]) -> list[Measure]:
    out = []
    for r in rows:
        lo, hi = _f(r.get("skill_low")), _f(r.get("skill_high"))
        se = (hi - lo) / (2 * Z) if lo is not None and hi is not None else None
        out.append(Measure(f"{r.get('level')}/{r.get('market_key')}/{r.get('model_name')}/{r.get('source')}", _f(r.get("skill")),
                           _int(r.get("n")), se, direction=None, unit="habilidad"))
    return out


def _state(rows: Sequence[Mapping[str, Any]]) -> list[Measure]:
    return []


def _i7(rows: Sequence[Mapping[str, Any]]) -> list[Measure]:
    r = _one(rows)
    if r is None:
        return []
    n = _f(r.get("matches"))
    return [Measure("median_min", _f(r.get("median_min")), _int(r.get("matches")), direction=LOWER, unit="minutos"),
            _proportion("within_30_min", _f(r.get("within_30_min")), n, HIGHER)]


def _i8(rows: Sequence[Mapping[str, Any]]) -> list[Measure]:
    r = _one(rows)
    return [] if r is None else [_proportion("with_web_search", _f(r.get("with_web_search")), _f(r.get("matches")), HIGHER)]


def _i9(rows: Sequence[Mapping[str, Any]]) -> list[Measure]:
    r = _one(rows)
    return [] if r is None else [_proportion("searched_before_day", _f(r.get("searched_before_day")), _f(r.get("matches")), HIGHER)]


def _i10(rows: Sequence[Mapping[str, Any]]) -> list[Measure]:
    r = _one(rows)
    if r is None:
        return []
    facts, matches = _f(r.get("confirmed_facts")), _f(r.get("researched_matches"))
    value = _share(facts, matches)
    se = None if facts is None or not matches else math.sqrt(max(facts, 1.0)) / matches
    return [Measure("confirmed_per_match", value, None if matches is None else int(matches), se, direction=HIGHER, unit="hechos por partido")]


def _i11(rows: Sequence[Mapping[str, Any]]) -> list[Measure]:
    total = sum(_f(r.get("facts")) or 0.0 for r in rows)
    unknown = sum(_f(r.get("facts")) or 0.0 for r in rows if r.get("tier") == "unknown")
    return [_proportion("unknown_tier", unknown, total, LOWER)] if total else []


def _i12(rows: Sequence[Mapping[str, Any]]) -> list[Measure]:
    r = _one(rows)
    return [] if r is None else [_proportion("stories_with_text", _f(r.get("stories_with_text")), _f(r.get("stories")), HIGHER)]


def _i13(rows: Sequence[Mapping[str, Any]]) -> list[Measure]:
    total = sum(_f(r.get("n")) or 0.0 for r in rows)
    ok = sum(_f(r.get("n")) or 0.0 for r in rows if r.get("status") == "ok")
    return [_proportion("complete_texts", ok, total, HIGHER)] if total else []


def _i15(rows: Sequence[Mapping[str, Any]]) -> list[Measure]:
    r = _one(rows)
    return [] if r is None else [Measure("usd_per_fixture", _f(r.get("usd_per_fixture")), _int(r.get("fixtures")), direction=LOWER, unit="USD")]


def _i16(rows: Sequence[Mapping[str, Any]]) -> list[Measure]:
    r = _one(rows)
    if r is None:
        return []
    return [Measure("usd_per_confirmed_fact", _share(_f(r.get("search_extraction_usd")), _f(r.get("confirmed_web_facts"))),
                    _int(r.get("confirmed_web_facts")), direction=LOWER, unit="USD")]


def _i17(rows: Sequence[Mapping[str, Any]]) -> list[Measure]:
    total = sum(_f(r.get("cost_usd")) or 0.0 for r in rows)
    review = sum(_f(r.get("cost_usd")) or 0.0 for r in rows if r.get("purpose") == "pick_review")
    return [Measure("review_share", _share(review, total), None, direction=None, unit="proporción del gasto")] if total else []


def _i18(rows: Sequence[Mapping[str, Any]]) -> list[Measure]:
    undecided = sum(_f(r.get("n")) or 0.0 for r in rows if r.get("status") == "PROPOSED")
    return [_poisson("hypotheses_without_destination", undecided, LOWER)] if rows else []


def _i19(rows: Sequence[Mapping[str, Any]]) -> list[Measure]:
    r = _one(rows)
    return [] if r is None else [_poisson("experiments_with_gate_since_5_oct", _f(r.get("since_5_oct_with_gate")), HIGHER)]


def _i20(rows: Sequence[Mapping[str, Any]]) -> list[Measure]:
    bad = sum(_f(r.get("runs")) or 0.0 for r in rows if r.get("status") in ("aborted", "interrupted"))
    return [_poisson("aborted_or_interrupted_7d", bad, LOWER)] if rows else []


def _i21(rows: Sequence[Mapping[str, Any]]) -> list[Measure]:
    r = _one(rows)
    return [] if r is None else [Measure("calibration_error", _f(r.get("calibration_error")), _int(r.get("parlays")), direction=LOWER)]


def _int(x: Any) -> int | None:
    v = _f(x)
    return None if v is None else int(v)


READERS: Final[Mapping[int, Callable[[Sequence[Mapping[str, Any]]], list[Measure]]]] = {
    1: _i1, 2: _i2, 3: _i3, 4: _i4, 5: _i5, 6: _state, 7: _i7, 8: _i8, 9: _i9, 10: _i10, 11: _i11, 12: _i12, 13: _i13, 14: _state,
    15: _i15, 16: _i16, 17: _i17, 18: _i18, 19: _i19, 20: _i20, 21: _i21, 22: _state}

# ── the thresholds of section 23 (approved before measuring, D7) ───────────────────────────────────────────────────────────────────────
# indicator -> {measure key (or "*" for every one): (operator, target)}; the text is the plan's, for the report.
THRESHOLDS: Final[Mapping[int, dict[str, Any]]] = {
    1: {"text": "Sin meta global; lo decide EXP-E1 por segmento", "targets": {}},
    2: {"text": "No empeora", "targets": {"shown_minus_market": ("<=", "base")}},
    3: {"text": "2 puntos o menos con 1.500 selecciones", "targets": {"*": ("<=", 2.0)}, "min_n": 1500},
    4: {"text": "Familias a +0,005 o menos, o declaradas sin habilidad", "targets": {"*": ("<=", 0.005)}},
    5: {"text": "Se informa; sin meta", "targets": {}},
    6: {"text": "Cero violaciones", "targets": {}},
    7: {"text": "30 minutos o menos en el 80 % de los partidos", "targets": {"within_30_min": (">=", 0.80)}},
    8: {"text": "Nivel A 95 %; nivel B 90 % (el recuento por nivel se mide con RP-5.4)", "targets": {}},
    9: {"text": "95 % del nivel A (el recuento por nivel se mide con RP-5.4)", "targets": {}},
    10: {"text": "Sube, con intervalo", "targets": {}},
    11: {"text": "30 % o menos", "targets": {"unknown_tier": ("<=", 0.30)}},
    12: {"text": "80 % de las que tienen fuente elegible", "targets": {}},
    13: {"text": "98 %", "targets": {"complete_texts": (">=", 0.98)}},
    14: {"text": "Cero afirmaciones sin respaldo en la muestra de 50", "targets": {}},
    15: {"text": "No sube", "targets": {"usd_per_fixture": ("<=", "base")}},
    16: {"text": "Baja", "targets": {}},
    17: {"text": "La que resulte de D1", "targets": {}},
    18: {"text": "Ninguna por encima del umbral de triage", "targets": {}},
    19: {"text": "Los ocho con veredicto o con muestra en curso y fecha de condición", "targets": {}},
    20: {"text": "0 fuera del libro; ninguna ejecución abortada o interrumpida atribuible a Intelligence", "targets": {
        "aborted_or_interrupted_7d": ("<=", 0.0)}},
    21: {"text": "0,03 o menos en repetición histórica", "targets": {"calibration_error": ("<=", 0.03)}},
    22: {"text": "No empeorar más de un 10 %", "targets": {}},
}


def thresholds_fingerprint() -> str:
    return hashlib.sha256(json.dumps(THRESHOLDS, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()


# What could move each indicator: the pieces of the plan, so that those that moved nothing are seen.
ATTRIBUTION: Final[Mapping[int, tuple[str, ...]]] = {
    1: ("RP-2.1", "RP-3.3", "RP-3.4", "RP-3.5", "RP-4.2", "RP-4.3", "RP-4.4", "RP-9.1"),
    2: ("RP-2.1", "RP-2.4", "RP-4.2", "RP-4.3", "RP-4.4"),
    3: ("RP-2.3", "RP-3.3", "RP-3.4", "RP-11.1"),
    4: ("RP-3.3", "RP-3.4", "RP-3.5", "RP-9.3", "RP-9.4", "RP-9.5"),
    5: ("RP-3.1", "RP-3.5"),
    6: ("RP-2.2",),
    7: ("RP-1.4",),
    8: ("RP-5.4", "RP-5.1"),
    9: ("RP-5.4",),
    10: ("RP-5.1", "RP-5.6", "RP-5.7"),
    11: ("RP-5.7",),
    12: ("RP-5.1", "RP-5.2"),
    13: ("RP-1.3", "RP-7.2", "RP-7.3"),
    14: ("RP-7.4", "RP-13.2"),
    15: ("RP-5.5", "RP-7.4", "RP-12.2"),
    16: ("RP-5.5", "RP-9.8"),
    17: ("RP-12.2",),
    18: ("RP-8.2",),
    19: ("RP-8.3", "RP-1.6", "RP-9.1", "RP-9.2", "RP-9.3", "RP-9.4", "RP-9.5", "RP-9.6", "RP-9.7"),
    20: ("RP-1.1", "RP-1.5", "RP-1.6"),
    21: ("RP-11.1", "RP-11.2", "RP-11.3"),
    22: ("RP-1.3", "RP-1.6", "RP-12.2"),
}


# ── the comparison ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _wilson(x: float, n: float) -> tuple[float, float]:
    p = x / n
    d = 1 + Z * Z / n
    centre = (p + Z * Z / (2 * n)) / d
    half = Z * math.sqrt(p * (1 - p) / n + Z * Z / (4 * n * n)) / d
    return centre - half, centre + half


def difference_interval(a: Measure, b: Measure) -> tuple[float, float, float] | None:
    """(difference ``b - a``, low, high) at 95 %, or None when one of the figures has no way to be given an interval. A proportion pair uses the
    hybrid of Newcombe over Wilson's intervals; a count its Poisson variance; a figure with a standard error the normal one."""
    if a.value is None or b.value is None:
        return None
    diff = b.value - a.value
    if a.successes is not None and a.n and b.successes is not None and b.n:
        la, ua = _wilson(a.successes, a.n)
        lb, ub = _wilson(b.successes, b.n)
        pa, pb = a.value, b.value
        return diff, diff - math.sqrt((pb - lb) ** 2 + (ua - pa) ** 2), diff + math.sqrt((ub - pb) ** 2 + (pa - la) ** 2)
    if a.count is not None and b.count is not None:
        half = Z * math.sqrt(max(a.count, 0.0) + max(b.count, 0.0))
        return diff, diff - half, diff + half
    if a.se is not None and b.se is not None:
        half = Z * math.sqrt(a.se**2 + b.se**2)
        return diff, diff - half, diff + half
    return None


def judge(a: Measure, b: Measure) -> dict[str, Any]:
    """The verdict of one figure: the difference, its interval and which column it falls in."""
    out: dict[str, Any] = {"key": a.key, "unit": a.unit, "before": a.value, "after": b.value, "n_before": a.n, "n_after": b.n}
    if a.value is None or b.value is None:
        return {**out, "verdict": NOT_MEASURED, "reason": "sin_cifra_en_uno_de_los_dos"}
    interval = difference_interval(a, b)
    if interval is None:
        out.update(difference=round(b.value - a.value, 6), interval=None)
        if a.direction is None:
            return {**out, "verdict": INFORMED, "reason": "sin_meta"}
        return {**out, "verdict": NO_CHANGE, "reason": "sin_intervalo"}
    diff, low, high = interval
    out.update(difference=round(diff, 6), interval=[round(low, 6), round(high, 6)])
    if a.direction is None:
        return {**out, "verdict": INFORMED, "reason": "sin_meta"}
    if low <= 0.0 <= high:
        return {**out, "verdict": NO_CHANGE, "reason": "el_intervalo_incluye_el_cero"}
    better = diff < 0 if a.direction == LOWER else diff > 0
    return {**out, "verdict": IMPROVED if better else WORSENED, "reason": "el_intervalo_excluye_el_cero"}


def _meets(measure: Measure, base: Measure | None, spec: Mapping[str, Any]) -> bool | None:
    targets = spec.get("targets", {})
    rule = targets.get(measure.key) or targets.get("*")
    if rule is None or measure.value is None:
        return None
    if measure.n is not None and spec.get("min_n") and measure.n < spec["min_n"]:
        return None  # not enough selections to judge the threshold
    op, target = rule
    if target == "base":
        if base is None or base.value is None:
            return None
        target = base.value
    return bool(measure.value <= target) if op == "<=" else bool(measure.value >= target)


def same_population(before: Mapping[str, Any], after: Mapping[str, Any]) -> tuple[bool, list[str]]:
    """The rule «same population or no comparison»: the same definition and the same fixed set of competitions."""
    reasons = []
    if before.get("definition_version") != after.get("definition_version"):
        reasons.append(f"definición distinta: {before.get('definition_version')} y {after.get('definition_version')}")
    b, a = before.get("meta", {}), after.get("meta", {})
    if b.get("base_before_utc") != a.get("base_before_utc"):
        reasons.append("conjunto de competiciones distinto (base_before_utc)")
    if str(a.get("cut_utc", "")) <= str(b.get("cut_utc", "")):
        reasons.append("el corte del después no es posterior al del antes")
    return not reasons, reasons


def compare(before: Mapping[str, Any], after: Mapping[str, Any], *, allow_identical: bool = False) -> dict[str, Any]:
    """The board: one entry per indicator, the three columns and what could not be compared. ``allow_identical`` lets the very same document be
    compared with itself (the reproduction check of the baseline), where the cut is not later."""
    ok, reasons = same_population(before, after)
    if not ok and allow_identical and before.get("meta") == after.get("meta") and before.get("definition_version") == after.get("definition_version"):
        ok, reasons = True, []
    indicators: list[dict[str, Any]] = []
    for item in before["indicators"]:
        n, section = int(item["n"]), str(item["section"])
        entry: dict[str, Any] = {"n": n, "area": item["area"], "section": section, "threshold": THRESHOLDS[n]["text"],
                                 "pieces": list(ATTRIBUTION[n])}
        if not ok:
            entry.update(verdict=NOT_COMPARABLE, reasons=reasons, measures=[])
            indicators.append(entry)
            continue
        reader = READERS[n]
        base_rows = before["sections"].get(section, {}).get("rows", [])
        after_rows = after.get("sections", {}).get(section, {}).get("rows", [])
        base_by = {m.key: m for m in reader(base_rows)}
        after_by = {m.key: m for m in reader(after_rows)}
        measures = []
        for key, a in base_by.items():
            b = after_by.get(key)
            if b is None:
                measures.append({"key": key, "unit": a.unit, "before": a.value, "after": None, "verdict": NOT_MEASURED,
                                 "reason": "sin_cifra_en_el_despues"})
                continue
            j = judge(a, b)
            met = _meets(b, a, THRESHOLDS[n])
            if met is not None:
                j["meets_threshold"] = met
            measures.append(j)
        entry["measures"] = measures
        entry["verdict"] = _indicator_verdict([str(m["verdict"]) for m in measures], measured=bool(base_by))
        indicators.append(entry)
    columns: dict[str, list[int]] = {c: [] for c in COLUMNS}
    apart: dict[str, list[int]] = {INFORMED: [], NOT_COMPARABLE: [], NOT_MEASURED: []}
    for e in indicators:
        verdict, number = str(e["verdict"]), int(e["n"])
        (columns if verdict in columns else apart).setdefault(verdict, []).append(number)
    return {"version": VERSION, "thresholds_fingerprint": thresholds_fingerprint(), "comparable": ok, "reasons": reasons,
            "before_cut": before.get("meta", {}).get("cut_utc"), "after_cut": after.get("meta", {}).get("cut_utc"),
            "indicators": indicators, "columns": columns, "apart": apart}


def _indicator_verdict(verdicts: Sequence[str], *, measured: bool) -> str:
    if not measured or not verdicts:
        return NOT_MEASURED
    if WORSENED in verdicts:
        return WORSENED
    if IMPROVED in verdicts:
        return IMPROVED
    if NO_CHANGE in verdicts:
        return NO_CHANGE
    if INFORMED in verdicts:
        return INFORMED
    return NOT_MEASURED


def render(board: Mapping[str, Any]) -> str:
    """The board as text in Spanish: the three columns and then what was only informed, not comparable or not measured."""
    names = {IMPROVED: "Mejoró", NO_CHANGE: "Sin cambio demostrado", WORSENED: "Empeoró", INFORMED: "Solo informado",
             NOT_COMPARABLE: "No comparable", NOT_MEASURED: "Sin medir"}
    lines = [f"Tablero antes y después ({board['version']}) · antes {board['before_cut']} · después {board['after_cut']}"]
    if not board["comparable"]:
        lines.append("NO COMPARABLE: " + "; ".join(board["reasons"]))
    groups: dict[str, list[int]] = {**board["columns"], **board["apart"]}
    for key in (*COLUMNS, INFORMED, NOT_COMPARABLE, NOT_MEASURED):
        numbers = groups.get(key, [])
        lines.append(f"{names[key]} ({len(numbers)}): " + (", ".join(f"I{n}" for n in numbers) if numbers else "ninguno"))
    return "\n".join(lines)
