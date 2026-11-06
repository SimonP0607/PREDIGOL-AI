"""``state-v2``: five states read off what decision-v1 already records - RECOMMENDED, CAUTION, WATCH, ABSTAIN, REJECTED (plan IA, P0).

WHY. decision-v1 has one word, INVESTIGACION, for two different things: a selection parked for a reason that can clear before the kick-off (a
price older than three hours: the next capture may refresh it) and one parked for a reason no amount of waiting fixes today (no champion
calibrator for the market and model, an edge not validated out of sample). A reader that cannot tell them apart cannot say "wait for it" from
"we do not know enough to have an opinion". state-v2 splits them - WATCH and ABSTAIN - and maps the other three one to one. It is RECORDED, not
decided: ``classify`` reads a row of ``intel.decisions`` (its ``state``, its ``reasons``, its ``filters``) and nothing else; the state the
production shows, stakes and selects is still decision-v1's. Nothing here is imported by the decision layer.

    APROBADO, PICK_PREMIUM, CANDIDATO_PARLAY, PICK_DEL_DIA    -> RECOMMENDED   (the labels stay labels: ``label_of``)
    CAUTELA                                                    -> CAUTION
    RECHAZADO                                                  -> REJECTED
    INVESTIGACION                                              -> WATCH or ABSTAIN by ``INVESTIGATION_RULES``; a parking reason no rule
                                                                  knows -> ABSTAIN ``unclassified`` (counted and listed, never guessed)

The rule table is built from the reason codes decision-v1 writes (``fbi.intel.decision.evaluate``) with the filter that writes each; a row whose
``reasons`` name none of them is read from the filters that record an ``effect`` of INVESTIGACION (``FILTER_RULES``).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import date
from typing import Any, Final, Literal, get_args

import psycopg
from psycopg.rows import dict_row

from fbi.ai.calendar import day_bounds
from fbi.core.decision_versions import DECISION_CORE

VERSION: Final = "state-v2"

StateV2 = Literal["RECOMMENDED", "CAUTION", "WATCH", "ABSTAIN", "REJECTED"]
STATES: Final = get_args(StateV2)
Kind = Literal["WATCH", "ABSTAIN"]

LABELS: Final = ("PICK_DEL_DIA", "PICK_PREMIUM", "CANDIDATO_PARLAY")
"""The labels of an approval in decision-v1: on RECOMMENDED they stay labels, they are not states of their own."""
DIRECT: Final[Mapping[str, StateV2]] = {
    "APROBADO": "RECOMMENDED", "PICK_PREMIUM": "RECOMMENDED", "CANDIDATO_PARLAY": "RECOMMENDED", "PICK_DEL_DIA": "RECOMMENDED",
    "CAUTELA": "CAUTION", "RECHAZADO": "REJECTED"}

REASON_EFFECT: Final[Mapping[str, str]] = {
    "data": "RECHAZADO", "model": "RECHAZADO", "no_price": "RECHAZADO", "thin_market": "RECHAZADO", "price_outlier": "RECHAZADO",
    "price_stale": "INVESTIGACION", "not_calibrated": "INVESTIGACION", "ev_unknown": "INVESTIGACION", "ev_cal_below": "RECHAZADO",
    "context_stop": "RECHAZADO", "key_absence_confirmed": "RECHAZADO", "key_absence_reported": "CAUTELA", "ai_reject": "CAUTELA",
    "ai_downgrade": "CAUTELA", "risk": "CAUTELA", "price_not_fresh": "CAUTELA", "edge_not_validated": "INVESTIGACION",
    "correlated_same_match": "CAUTELA"}
"""Every reason code decision-v1 appends to ``reasons`` and the state it pushes to (``fbi.intel.decision.evaluate`` and ``correlate``). The
reason a CAUTION or a REJECTED carries is the first of its reasons with that effect."""

INVESTIGATION_RULES: Final[tuple[tuple[str, int, str, Kind], ...]] = (
    ("not_calibrated", 4, "calibration", "ABSTAIN"),
    ("ev_unknown", 5, "ev", "ABSTAIN"),
    ("edge_not_validated", 10, "final", "ABSTAIN"),
    ("price_stale", 3, "market", "WATCH"),
)
"""(reason code, filter number, filter key, state-v2) of every INVESTIGACION decision-v1 records, the structural ones first:

    not_calibrated      filter 4  calibration  ABSTAIN  no CHAMPION calibrator for (market, model): only a promotion fixes it, not the clock
    ev_unknown          filter 5  ev           ABSTAIN  a price but no calibrated probability: the EV cannot be judged (follows from filter 4)
    edge_not_validated  filter 10 final        ABSTAIN  the market's edge is not validated out of sample (edge-gate-v1): research, not waiting
    price_stale         filter 3  market       WATCH    the consensus price is older than 3 h: the next capture before the kick-off can clear it

A row with a structural reason is ABSTAIN even if it also has a resolvable one: a fresh price does not give the market a calibrator. decision-v1
records NO INVESTIGACION for the line-ups, a pending context or a missing model output: a key absence before the line-ups is CAUTELA
(``key_absence_reported``), a review is CAUTELA at most, the data, the quarantine and the model are RECHAZADO (filters 1 and 2). So the WATCH
side has one rule today; a new parking reason of decision-v1 lands in ``unclassified`` until it is added here."""

FILTER_RULES: Final[Mapping[str, tuple[str, Kind]]] = {
    key: (code, kind) for code, _, key, kind in INVESTIGATION_RULES if key in ("calibration", "market")}
"""The filters whose ``effect: INVESTIGACION`` names ONE parking reason (``decision._f``): calibration (4) and market (3). Filter 5 records no
effect (its ``ok`` is None), and filter 10 (``final``) records the row's own state as its effect whatever parked it, so neither can say why:
``ev_unknown`` and ``edge_not_validated`` are read from ``reasons`` only."""
UNCLASSIFIED: Final = "unclassified"
NO_REASON: Final = "none"


def label_of(row: Mapping[str, Any]) -> str | None:
    """The label a RECOMMENDED carries (PICK_DEL_DIA, PICK_PREMIUM, CANDIDATO_PARLAY), None for a plain APROBADO or any other state."""
    state = row.get("state")
    return state if state in LABELS else None


def _reasons(row: Mapping[str, Any]) -> list[str]:
    raw = row.get("reasons") or []
    return [str(r) for r in raw]


def classify(row: Mapping[str, Any]) -> tuple[StateV2, str]:
    """(state-v2, reason code) of one row of ``intel.decisions``. Pure. An unknown decision-v1 state raises ``ValueError``."""
    state = row.get("state")
    reasons = _reasons(row)
    if state in DIRECT:
        mapped = DIRECT[str(state)]
        if mapped == "RECOMMENDED":
            return mapped, "approved"
        want = "CAUTELA" if mapped == "CAUTION" else "RECHAZADO"
        first = next((r for r in reasons if REASON_EFFECT.get(r) == want), None)
        return mapped, first or (reasons[0] if reasons else NO_REASON)
    if state != "INVESTIGACION":
        raise ValueError(f"unknown decision-v1 state {state!r}")
    have = set(reasons)
    for code, _, _, kind in INVESTIGATION_RULES:
        if code in have:
            return kind, code
    parked = {f.get("key") for f in row.get("filters") or [] if isinstance(f, Mapping) and f.get("effect") == "INVESTIGACION"}
    for key, (code, kind) in FILTER_RULES.items():
        if key in parked:
            return kind, code
    return "ABSTAIN", UNCLASSIFIED


# -- the day's report ------------------------------------------------------------------------------------------------------------------

DAY_SQL: Final = """
SELECT DISTINCT ON (d.fixture_id, d.market_key, d.selection, d.line, d.checkpoint)
       d.id, d.known_at, d.checkpoint, d.fixture_id, d.market_key, d.selection, d.line, d.state, d.reasons, d.filters
  FROM intel.decisions d
 WHERE d.decision_version = %(version)s AND d.known_at >= %(start)s AND d.known_at < %(end)s
 ORDER BY d.fixture_id, d.market_key, d.selection, d.line, d.checkpoint, d.known_at DESC, d.id DESC
"""
"""The newest row of each selection at each checkpoint among those decision-v1 recorded during the day (Bogotá), core layer only."""


def classify_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The counts of state-v2 over some rows: per state, per (state, reason), the labels on RECOMMENDED, decision-v1 x state-v2, and the
    unclassified rows listed."""
    by_state: Counter[str] = Counter()
    by_reason: dict[str, Counter[str]] = defaultdict(Counter)
    labels: Counter[str] = Counter()
    crosswalk: dict[str, Counter[str]] = defaultdict(Counter)
    unclassified: list[dict[str, Any]] = []
    for r in rows:
        state, reason = classify(r)
        by_state[state] += 1
        by_reason[state][reason] += 1
        crosswalk[str(r["state"])][state] += 1
        label = label_of(r)
        if state == "RECOMMENDED":
            labels[label or "APROBADO"] += 1
        if reason == UNCLASSIFIED:
            unclassified.append({"decision_id": int(r["id"]), "checkpoint": r.get("checkpoint"), "fixture_id": int(r["fixture_id"]),
                                 "market_key": r.get("market_key"), "selection": r.get("selection"), "line": str(r.get("line")),
                                 "reasons": _reasons(r)})
    return {"rows": len(rows), "by_state": {s: by_state.get(s, 0) for s in STATES},
            "by_reason": {s: dict(sorted(by_reason[s].items())) for s in STATES if s in by_reason},
            "labels": dict(sorted(labels.items())), "crosswalk": {k: dict(sorted(v.items())) for k, v in sorted(crosswalk.items())},
            "unclassified": len(unclassified), "unclassified_rows": unclassified}


def day_report(conn: psycopg.Connection[Any], *, day: date) -> dict[str, Any]:
    """state-v2 over the day's newest row per selection and checkpoint (``DAY_SQL``). Read-only."""
    start, end = day_bounds(day)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(DAY_SQL, {"version": DECISION_CORE, "start": start, "end": end})
        rows = [dict(r) for r in cur.fetchall()]
    return {"version": VERSION, "decision_version": DECISION_CORE, "day": day.isoformat()} | classify_rows(rows)
