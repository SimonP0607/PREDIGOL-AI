"""The replay of a day: decision-v2 against decision-v1 and decision-fam-v1, row by row - the evidence of the P1 gate ("motor nuevo igual o
mejor"). Deterministic and READ-ONLY: it writes nothing, and the same database gives the same report.

For every row decision-v1 or decision-fam-v1 wrote during the day (Bogotá, ``fbi.ai.calendar.day_bounds``), grouped by its moment
``known_at`` and its version:

    the world        read as of that moment as the layer read it (``decision.read_world`` under the family's version), with two
                     corrections a replay needs: the previous decisions are the ones STRICTLY before the moment (the row being
                     replayed is not its own history), and the AI mode is the one the rows recorded (``AI_OFF``), not today's switch;
    the candidates   every candidate of the rows' matches, read by the family that decided them (``families``) as of the moment -
                     all of a match's, because correlation compares them;
    decision-v2      ``engine.decide_all`` over them; optionally with the Council's typed adjustment (``council``: ``ma-v1`` or
                     ``ma-v1-h``, ctx-adj-v1) and the market's signals (``signals``), each a separate measurement: without them the
                     replay is the equivalence of the engine;
    the price        the core candidates' price as decision-v1 read it (``price="consensus"``, the default: the newest consensus of a
                     capture) or as the odds book held it at the moment (``price="book"``, ``fbi.decision.book_price``: the answer in
                     force of a capture or of a book refresh, priced the same way, with its age and, as a measurement, the book's last
                     price before kick-off for the CLV). The book is a separate measurement too: the evidence of P1 is the default;
    the probability  the core candidates' probability as decision-v1 judges it (``probability="own"``, the default: the pick's, calibrated
                     by stage 4) or the common probability view's (``probability="common"``, ``fbi.decision.view.judged``: the number
                     the Match Center states, with its seal and its version, plan INT-A03). With the view, the same candidates are also
                     decided with their own probability, and the report says what the view changed and at which stage.

Then each row is compared with the decision of the same selection: decision-v1's state read through state-v2 (``state_v2.classify``)
against decision-v2's. The report: the agreement per family (and per market), the confusion table, the labels and checkpoints that
agree, every disagreement with the stage that caused it (the first stage, in order, whose reason codes differ; ``tie`` when it is
correlation deciding between equal scores, which decision-v1 breaks on the order of its rows), and every row whose
candidate the replay could not find. The PICKS DEL DÍA copies (checkpoint ``selection``) are counted and skipped: they are a label on a
decision, not a decision.
"""

from __future__ import annotations

import dataclasses
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.ai.calendar import day_bounds
from fbi.decision import book_price, engine, market_inputs
from fbi.decision import view as common_view
from fbi.decision.families import CORE, FAMILIES, INFO_CODES, Candidate, MarketFamily, family_of
from fbi.intel import context_adjustment as ctx_adj
from fbi.intel import decision, state_v2
from fbi.intel.decision import Key
from fbi.storage.payload_store import PayloadStore

VERSION: Final = "decision-v2-replay-v1"
SELECTION: Final = "selection"
"""The checkpoint of a copy of a decision as a PICK DEL DÍA (``decision.select_day``)."""
NOT_FOUND: Final = "candidate"
"""The ``stage`` of a row whose candidate decision-v2 could not rebuild."""

DAY_SQL: Final = """
SELECT d.id, d.decision_version, d.known_at, d.checkpoint, d.fixture_id, d.market_key, d.selection, d.line, d.model_name, d.state,
       d.reasons, d.filters, d.context_status, d.p_cal::float8 AS p_cal, d.odds::float8 AS odds, d.p_market::float8 AS p_market,
       d.price_at
  FROM intel.decisions d
 WHERE d.decision_version = ANY(%(versions)s) AND d.known_at >= %(start)s AND d.known_at < %(end)s
 ORDER BY d.known_at, d.id
"""
"""Every row the layers being replaced wrote during the day."""

PREVIOUS_BEFORE_SQL: Final = """
SELECT DISTINCT ON (fixture_id, market_key, selection, line) id, fixture_id, market_key, selection, line, checkpoint,
       state, odds::float8 AS odds, calibrator_id, context_status, input_hash, known_at, score
  FROM intel.decisions
 WHERE fixture_id = ANY(%(fixtures)s) AND known_at < %(at)s AND decision_version = %(version)s
 ORDER BY fixture_id, market_key, selection, line, known_at DESC, id DESC
"""
"""``decision.PREVIOUS_SQL`` strictly before the moment: what the layer had written when it decided."""


def key_of(r: Mapping[str, Any]) -> Key:
    return int(r["fixture_id"]), str(r["market_key"]), str(r["selection"]), Decimal(str(r["line"])).quantize(decision.LINE_Q)


def read_rows(conn: psycopg.Connection[Any], *, day: date, versions: Sequence[str]) -> list[dict[str, Any]]:
    start, end = day_bounds(day)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(DAY_SQL, {"versions": list(versions), "start": start, "end": end})
        return [dict(r) for r in cur.fetchall()]


def previous_before(conn: psycopg.Connection[Any], fixtures: Sequence[int], *, at: datetime, version: str) -> dict[Key, dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(PREVIOUS_BEFORE_SQL, {"fixtures": list(fixtures), "at": at, "version": version})
        return {key_of(r): dict(r) for r in cur.fetchall()}


def recorded_ai_mode(rows: Sequence[Mapping[str, Any]]) -> str:
    """The AI mode of a pass as its rows recorded it: ``off`` when they say ``AI_OFF`` (the only mode ``decision.context_status`` tells
    apart); otherwise a mode that is not ``off``."""
    return "off" if any(r.get("context_status") == "AI_OFF" for r in rows) else "recorded"


STARTED_STATUS: Final = frozenset({"1H", "HT", "2H", "ET", "BT", "P", "LIVE", "FT", "AET", "PEN"})
"""The statuses a match can only have once it has kicked off: seen on a row read after the fact, they say nothing about the moment before."""


def as_of_status(row: Mapping[str, Any], at: datetime) -> Mapping[str, Any]:
    """The row as the moment ``at`` saw its match. The candidates are read from today's ``core.fixtures``, whose status of a match
    already played is ``FT``: decision-v2's data stage would reject every row of a past day for «estado FT», a rejection the pipeline
    never had (it decides before kick-off only). A status that can only come after the whistle is read as it was before it; the others
    (postponed, cancelled, abandoned...) may have been true then and are left. Pure."""
    kickoff = row.get("kickoff_at")
    if kickoff is None or at >= kickoff or str(row.get("status_short") or "") not in STARTED_STATUS:
        return row
    return {**row, "status_short": "NS", "status_group": "scheduled"}


def candidates_as_of(cands: Sequence[Candidate], at: datetime) -> list[Candidate]:
    """The candidates with the status of their match as of ``at`` (see ``as_of_status``). Pure."""
    return [dataclasses.replace(c, models={m: as_of_status(r, at) for m, r in c.models.items()}) for c in cands]


def world_at(conn: psycopg.Connection[Any], family: MarketFamily, fixtures: Sequence[int], *, at: datetime,
             rows: Sequence[Mapping[str, Any]]) -> decision.World:
    version = family.params.decision_version
    w = decision.read_world(conn, list(fixtures), at=at, version=version)
    return dataclasses.replace(w, previous=previous_before(conn, fixtures, at=at, version=version), ai_mode=recorded_ai_mode(rows))


# -- comparing ------------------------------------------------------------------------------------------------------------------------

def v1_codes(row: Mapping[str, Any]) -> list[str]:
    return [str(c) for c in row.get("reasons") or [] if str(c) not in INFO_CODES]


def cause(row: Mapping[str, Any], d: engine.Decision2) -> str:
    """The stage that made the two disagree: the first, in stage order, of the stages of the codes only one of them gave; ``final`` when
    both gave the same codes."""
    diff = set(v1_codes(row)) ^ set(d.codes)
    stages = sorted({engine.CODE_STAGE.get(c, "final") for c in diff}, key=lambda s: engine.NUMBER[s])
    return stages[0] if stages else "final"


def _v1_why(row: Mapping[str, Any], stage: str) -> str | None:
    for f in row.get("filters") or []:
        if isinstance(f, Mapping) and engine.V1_STAGE.get(str(f.get("key")), str(f.get("key"))) == stage:
            return str(f.get("why"))
    return None


def _where(row: Mapping[str, Any], family: str) -> dict[str, Any]:
    return {"decision_id": int(row["id"]), "family": family, "known_at": row["known_at"].isoformat(), "checkpoint": row["checkpoint"],
            "fixture_id": int(row["fixture_id"]), "market_key": row["market_key"], "selection": row["selection"],
            "line": str(key_of(row)[3]), "model": row.get("model_name")}


def _rate(hit: int, n: int) -> float | None:
    return None if n == 0 else round(hit / n, 4)


@dataclasses.dataclass
class _Acc:
    n: int = 0
    agree: int = 0
    unmatched: int = 0
    labels_n: int = 0
    labels_agree: int = 0
    checkpoints_agree: int = 0
    reasons_differ: int = 0
    ties: int = 0
    """Disagreements of correlation on a tie of scores: decision-v1 breaks a tie on the order of its rows, decision-v2 on the selection."""
    confusion: dict[str, Counter[str]] = dataclasses.field(default_factory=lambda: defaultdict(Counter))
    by_market: dict[str, list[int]] = dataclasses.field(default_factory=lambda: defaultdict(lambda: [0, 0]))

    def as_json(self) -> dict[str, Any]:
        return {"n": self.n, "agree": self.agree, "rate": _rate(self.agree, self.n), "unmatched": self.unmatched,
                "confusion": {a: dict(sorted(c.items())) for a, c in sorted(self.confusion.items())},
                "by_market": {m: {"n": v[0], "agree": v[1], "rate": _rate(v[1], v[0])} for m, v in sorted(self.by_market.items())},
                "labels": {"n": self.labels_n, "agree": self.labels_agree},
                "checkpoints": {"n": self.n - self.unmatched, "agree": self.checkpoints_agree},
                "same_state_other_reasons": self.reasons_differ, "correlation_ties": self.ties}


Pair = tuple[Mapping[str, Any], str, engine.Decision2 | None]


def compare(pairs: Sequence[Pair], *, families: Sequence[str]) -> dict[str, Any]:
    """The comparison of each row with the decision decision-v2 made of it (None: not rebuilt). Pure; ordered by (known_at, id)."""
    per: dict[str, _Acc] = {f: _Acc() for f in families}
    total = _Acc()
    disagreements: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    for row, family, d in sorted(pairs, key=lambda p: (p[0]["known_at"], int(p[0]["id"]))):
        v1_state, v1_reason = state_v2.classify(row)
        accs = (per.setdefault(family, _Acc()), total)
        for acc in accs:
            acc.n += 1
            acc.by_market[str(row["market_key"])][0] += 1
        if d is None:
            for acc in accs:
                acc.unmatched += 1
                acc.confusion[v1_state]["(none)"] += 1
            unmatched.append(_where(row, family) | {"v1_state": row["state"], "v1_state2": v1_state, "stage": NOT_FOUND,
                                                    "why": "decision-v2 no reconstruyó el candidato en ese momento"})
            continue
        agree = d.state == v1_state
        for acc in accs:
            acc.confusion[v1_state][d.state] += 1
            acc.agree += agree
            acc.by_market[str(row["market_key"])][1] += agree
            acc.checkpoints_agree += d.checkpoint == row["checkpoint"]
            if agree and set(v1_codes(row)) != set(d.codes):
                acc.reasons_differ += 1
            if agree and d.state == "RECOMMENDED":
                acc.labels_n += 1
                acc.labels_agree += d.label == state_v2.label_of(row)
        if not agree:
            stage = cause(row, d)
            tie = stage == "correlation" and bool(d.verdict("correlation").data.get("tie"))
            for acc in accs:
                acc.ties += tie
            disagreements.append(_where(row, family) | {"tie": tie} | {
                "v1_state": row["state"], "v1_state2": v1_state, "v1_reason": v1_reason, "v1_codes": v1_codes(row),
                "v2_state": d.state, "v2_reason": d.reason, "v2_codes": list(d.codes), "stage": stage,
                "v1_why": _v1_why(row, stage), "v2_why": d.verdict(stage).why if stage in engine.NUMBER else None})
    return {"agreement": {"n": total.n, "agree": total.agree, "rate": _rate(total.agree, total.n), "unmatched": total.unmatched,
                          "correlation_ties": total.ties},
            "confusion": total.as_json()["confusion"], "families": {f: a.as_json() for f, a in sorted(per.items())},
            "disagreements": disagreements, "unmatched": unmatched}


# -- the common view ------------------------------------------------------------------------------------------------------------------

TOLERANCE_PP: Final = 0.5
"""The gap, in points, under which two readings of one selection are the same number (the criterion of plan PICKS, F3)."""
CAUSES: Final = ("different_model", "view_uncalibrated", "calibration")
"""Why decision-v1's calibrated probability and the common view differ, the first that applies: another model; the view is the model's own number
(it only calibrates with a champion and a fresh price, where decision-v1 also shows the best fit); or the calibration itself (the view scales
the whole market to one)."""


def _percentile(sorted_gaps: Sequence[float], q: float) -> float | None:
    return None if not sorted_gaps else round(sorted_gaps[min(len(sorted_gaps) - 1, int(q * len(sorted_gaps)))], 3)


def common_cause(row: Mapping[str, Any], view: engine.CommonView) -> str:
    model = row.get("model_name")
    if model is not None and str(model) != view.model:
        return "different_model"
    if view.calibration != "CALIBRATED":
        return "view_uncalibrated"
    return "calibration"


def common_summary(items: Sequence[tuple[Mapping[str, Any], engine.CommonView | None, float | None]]) -> dict[str, Any]:
    """How far decision-v1's calibrated probability (the row) and decision-v2's own (``p_cal``) are from the common view, in points, and why.
    ``items``: (the row decision-v1 wrote, the view of its selection as of its moment or None, decision-v2's own calibrated probability).
    Pure. A selection counts where the row has a calibrated probability and the view has the selection."""
    gaps: list[float] = []
    own: list[float] = []
    by_cause: dict[str, list[float]] = {c: [] for c in CAUSES}
    calibration: Counter[str] = Counter()
    with_view = with_p = 0
    for row, view, p2 in items:
        if view is None:
            continue
        with_view += 1
        calibration[view.calibration] += 1
        if row.get("p_cal") is None:
            continue
        with_p += 1
        g = abs(view.p - float(row["p_cal"])) * 100
        gaps.append(g)
        by_cause[common_cause(row, view)].append(g)
        if p2 is not None:
            own.append(abs(view.p - p2) * 100)
    gaps.sort()
    own.sort()
    causes = {c: {"selections": len(v), "median_pp": round(sorted(v)[len(v) // 2], 3) if v else None, "max_pp": round(max(v), 3) if v else None,
                  "over_tolerance": sum(1 for x in v if x > TOLERANCE_PP)} for c, v in by_cause.items()}
    return {"rows": len(items), "with_view": with_view, "with_v1_probability": with_p, "within_tolerance": sum(1 for g in gaps if g <= TOLERANCE_PP),
            "tolerance_pp": TOLERANCE_PP, "median_pp": _percentile(gaps, 0.5), "p90_pp": _percentile(gaps, 0.9), "max_pp": _percentile(gaps, 1.0),
            "v2_own_vs_view_median_pp": _percentile(own, 0.5), "v2_own_vs_view_max_pp": _percentile(own, 1.0),
            "view_calibration": dict(calibration.most_common()), "causes": causes}


# -- the price and its age ------------------------------------------------------------------------------------------------------------

def _spread(xs: Sequence[float]) -> dict[str, float | None]:
    s = sorted(xs)
    return {"n": len(s), "p50": _percentile(s, 0.5), "p75": _percentile(s, 0.75), "p90": _percentile(s, 0.9), "p95": _percentile(s, 0.95),
            "max": _percentile(s, 1.0)}


def _minutes(later: datetime, earlier: datetime) -> float:
    return (later - earlier).total_seconds() / 60


def price_summary(pairs: Sequence[Pair], *, source: str) -> dict[str, Any]:
    """The price decision-v2 judged each row with, and its age (G-PRECIO, plan INT-A06): how many decisions carry a price, how many of those
    carry no age (the gate asks for none), the age by checkpoint; with the book's price, also which ask confirmed it, why a selection had
    none, how far it is from decision-v1's own price on the same row (``PRICE_MOVE`` is decision-v1's 3 %), and the book's last price before
    kick-off (``engine.Close``). A measurement: nothing here changes a state. Pure."""
    decided = [(r, d) for r, _, d in pairs if d is not None]
    with_price = [(r, d) for r, d in decided if d.price.odds is not None]
    ages = [d.price.age_minutes for _, d in with_price if d.price.age_minutes is not None]
    by_checkpoint: dict[str, list[float]] = defaultdict(list)
    for _, d in with_price:
        if d.price.age_minutes is not None:
            by_checkpoint[d.checkpoint].append(d.price.age_minutes)
    out: dict[str, Any] = {"source": source, "decisions": len(decided), "with_price": len(with_price),
                           "without_age": sum(1 for _, d in with_price if d.price.age_minutes is None), "age_minutes": _spread(ages),
                           "by_checkpoint": {cp: _spread(v) for cp, v in sorted(by_checkpoint.items())}}
    if source != engine.BOOK:
        return out
    core = [(r, d) for r, f, d in pairs if d is not None and f == CORE.name]  # only the core is priced by the book: a family keeps its own
    core_priced = [(r, d) for r, d in core if d.price.odds is not None]
    v1_ages = [_minutes(r["known_at"], r["price_at"]) for r, _ in core if r.get("price_at") is not None and r.get("known_at") is not None]
    odds_gap: list[float] = []
    p_gap: list[float] = []
    for r, d in core_priced:
        if r.get("odds") and r.get("p_market") is not None and d.price.p_market is not None and d.price.odds is not None:
            odds_gap.append(abs(d.price.odds / float(r["odds"]) - 1) * 100)
            p_gap.append(abs(d.price.p_market - float(r["p_market"])) * 100)
    closes = [d.close for _, d in core if d.close is not None]
    out |= {"core_decisions": len(core), "confirmed_by": dict(sorted(Counter(str(d.price.confirmed_by) for _, d in core_priced).items())),
            "missing": dict(sorted(Counter(str(d.price.missing) for _, d in core if d.price.odds is None).items())),
            "v1_age_minutes": _spread(v1_ages),
            "against_v1": {"rows": len(odds_gap), "odds_gap_pct": _spread(odds_gap), "p_gap_pp": _spread(p_gap),
                           "odds_moved": sum(1 for g in odds_gap if g > decision.PRICE_MOVE * 100), "move_pct": decision.PRICE_MOVE * 100},
            "close": {"decisions": len(closes), "minutes_to_kickoff": _spread([c.minutes_to_kickoff for c in closes]),
                      "provider_minutes_to_kickoff": _spread([c.provider_minutes_to_kickoff for c in closes
                                                              if c.provider_minutes_to_kickoff is not None]),
                      "confirmed_by": dict(sorted(Counter(c.confirmed_by for c in closes).items()))}}
    return out


# -- the probability the stages judged -------------------------------------------------------------------------------------------------

Against = tuple[Mapping[str, Any], str, engine.Decision2 | None, engine.Decision2 | None]
"""A row, its family, decision-v2's decision of it judged with the common view, and the same decision judged with the pick's own probability."""
EXAMPLES: Final = 20


def changed_at(own: engine.Decision2, common: engine.Decision2) -> str:
    """The stage that made the common view's decision differ from the own one: the first, in stage order, of the stages of the codes only one
    of them gave; ``final`` when both gave the same codes."""
    diff = set(own.codes) ^ set(common.codes)
    stages = sorted({engine.CODE_STAGE.get(c, "final") for c in diff}, key=lambda s: engine.NUMBER[s])
    return stages[0] if stages else "final"


def probability_summary(items: Sequence[Against]) -> dict[str, Any]:
    """What judging with the common view did (plan INT-A03): how many decisions it judged and with which seal, which kept their own probability
    and why, and - against the same candidates judged with their own probability - how many states changed, from which to which, at which stage,
    and how far the calibrated probabilities are. A measurement: nothing here changes a state. Pure; ordered by (known_at, id)."""
    decided = [(r, f, d, o) for r, f, d, o in sorted(items, key=lambda x: (x[0]["known_at"], int(x[0]["id"]))) if d is not None]
    judged = [d for _, _, d, _ in decided if d.prediction.source == engine.COMMON]
    kept: Counter[str] = Counter("family" if f != CORE.name else str(d.prediction.missing) for _, f, d, _ in decided
                                 if d.prediction.source != engine.COMMON)
    both = [(r, d, o) for r, _, d, o in decided if o is not None]
    changed = [(r, d, o) for r, d, o in both if d.state != o.state]
    gaps = [abs(d.prediction.p_cal - o.prediction.p_cal) * 100 for _, d, o in both
            if d.prediction.source == engine.COMMON and d.prediction.p_cal is not None and o.prediction.p_cal is not None]
    lost = sum(1 for _, d, o in both if d.prediction.source == engine.COMMON and d.prediction.p_cal is None and o.prediction.p_cal is not None)
    examples = [{"decision_id": int(r["id"]), "known_at": r["known_at"].isoformat(), "fixture_id": int(r["fixture_id"]), "market_key": r["market_key"],
                 "selection": r["selection"], "line": str(key_of(r)[3]), "own": o.state, "own_reason": o.reason, "common": d.state,
                 "common_reason": d.reason, "stage": (stage := changed_at(o, d)), "why": d.verdict(stage).why,
                 "p_own": o.prediction.p_cal, "p_common": d.prediction.p_cal, "seal": d.prediction.calibration}
                for r, d, o in changed[:EXAMPLES]]
    return {"source": engine.COMMON, "decisions": len(decided), "judged_with_common": len(judged),
            "seal": dict(sorted(Counter(f"{d.prediction.calibration} ({d.prediction.basis})" for d in judged).items())),
            "versions": dict(sorted(Counter(str(d.prediction.version) for d in judged).items())),
            "kept_own": dict(sorted(kept.items())),
            "against_own": {"rows": len(both), "same_state": len(both) - len(changed), "changed": len(changed),
                            "transitions": dict(sorted(Counter(f"{o.state} -> {d.state}" for _, d, o in changed).items())),
                            "by_stage": dict(sorted(Counter(changed_at(o, d) for _, d, o in changed).items(), key=lambda kv: engine.NUMBER.get(kv[0], 99))),
                            "p_cal_gap_pp": _spread(gaps), "calibrated_lost": lost, "examples": examples}}


# -- the replay -----------------------------------------------------------------------------------------------------------------------

def _primary_p(world: decision.World, c: Candidate) -> float | None:
    names = sorted(c.models)
    model = world.cal.primary_model(c.key[1], names) or names[0]
    p = c.models[model].get("p_model")
    return None if p is None else float(p)


def replay_day(conn: psycopg.Connection[Any], *, day: date, families: Sequence[MarketFamily] = FAMILIES, council: str | None = None,
               signals: bool = False, view: bool = False, price: str = engine.CONSENSUS, store: PayloadStore | None = None,
               probability: str = engine.OWN) -> dict[str, Any]:
    """decision-v2 over every row decision-v1 and decision-fam-v1 wrote during ``day``, compared. ``price``: the core candidates' price as
    decision-v1 read it (``consensus``, the default) or as the odds book held it at each moment (``book``, which reads the bodies from the
    RAW ``store``). ``probability``: the core candidates' probability as decision-v1 judges it (``own``, the default) or the common view's
    (``common``). Read-only."""
    if council is not None and council not in ctx_adj.ENGINES:
        raise ValueError(f"council must be one of {ctx_adj.ENGINES}")
    if price not in engine.PRICE_SOURCES:
        raise ValueError(f"price must be one of {engine.PRICE_SOURCES}")
    if probability not in engine.PROBABILITY_SOURCES:
        raise ValueError(f"probability must be one of {engine.PROBABILITY_SOURCES}")
    if price == engine.BOOK and store is None:
        raise ValueError("the book's price is read from the RAW store: give the store")
    versions = sorted({f.params.decision_version for f in families})
    rows = read_rows(conn, day=day, versions=versions)
    skipped_selection = sum(1 for r in rows if r["checkpoint"] == SELECTION)
    groups: dict[tuple[datetime, str], list[tuple[dict[str, Any], MarketFamily]]] = defaultdict(list)
    unclaimed: list[dict[str, Any]] = []
    for r in rows:
        if r["checkpoint"] == SELECTION:
            continue
        fam = family_of(r, families)
        if fam is None:
            unclaimed.append({"decision_id": int(r["id"]), "decision_version": r["decision_version"], "market_key": r["market_key"]})
            continue
        groups[(r["known_at"], fam.params.decision_version)].append((r, fam))
    pairs: list[Pair] = []
    against: list[Against] = []
    measured: list[tuple[Mapping[str, Any], engine.CommonView | None, float | None]] = []
    book: book_price.BookReader | None = None
    closes: dict[Key, engine.Close] = {}
    if price == engine.BOOK:
        core_fixtures = sorted({int(r["fixture_id"]) for items in groups.values() for r, f in items if f.name == CORE.name})
        book = book_price.read(conn, store, core_fixtures)
        closes = book_price.closes(book, core_fixtures)
    for (at, _), items in sorted(groups.items()):
        fams = [f for f in families if any(f is g for _, g in items)]
        fixtures = sorted({int(r["fixture_id"]) for r, _ in items})
        world = world_at(conn, fams[0], fixtures, at=at, rows=[r for r, _ in items])
        cands = candidates_as_of([c for f in fams for c in f.candidates(conn, at=at, fixtures=fixtures)], at)
        if book is not None and any(f.name == CORE.name for f in fams):
            cands = book_price.priced(cands, book.answers_at(fixtures, at), family=CORE.name)
        adjustments: dict[Key, ctx_adj.ContextAdjustment] = {}
        if council is not None:
            seen = ctx_adj.adjustments_for(conn, at=at, fixture_ids=fixtures, engines=(council,))
            adjustments = {k: a for (k, _), a in seen.adjustments.items()}
        markets: dict[engine.Ident, engine.MarketRisk] = {}
        if signals:
            for c in cands:
                found = market_inputs.read(conn, c.key, at=at, p_model=_primary_p(world, c))
                if found is not None:
                    markets[c.ident] = found
        common = probability == engine.COMMON
        views = common_view.read(conn, fixtures, at=at, cal=world.cal) if view or common else {}
        judged = common_view.judged(cands, views, family=CORE.name) if common else cands
        index = {d.ident: d for d in engine.decide_all(world, judged, adjustments=adjustments, markets=markets, views=views if view else None,
                                                       closes=closes)}
        own = {d.ident: d for d in engine.decide_all(world, cands, adjustments=adjustments, markets=markets, closes=closes)} if common else {}
        for r, fam in items:
            k = key_of(r)
            d = index.get((fam.name, k, str(r.get("model_name")))) or index.get((fam.name, k, None))
            pairs.append((r, fam.name, d))
            if common:
                against.append((r, fam.name, d, own.get((fam.name, k, str(r.get("model_name")))) or own.get((fam.name, k, None))))
            # the view of the row's selection counts whether or not decision-v2 rebuilt its candidate: it is a measurement of the view
            measured.append((r, views.get(k), None if d is None else d.prediction.p_cal))
    out = compare(pairs, families=[f.name for f in families])
    prices = price_summary(pairs, source=price)
    if book is not None:
        prices |= {"reader": {"version": book_price.VERSION, "matches": len(book.fixtures), "bodies_read": len(book.bodies),
                              "unreadable": sum(1 for v in book.bodies.values() if v is None), "problems": book.problems[:5]}}
    return {"version": engine.VERSION, "replay": VERSION, "day": day.isoformat(), "versions": versions,
            "inputs": {"council": council, "signals": signals, "view": view, "price": price, "probability": probability,
                       "previous": "strictly before known_at", "ai_mode": "as the rows recorded it"},
            "rows": len(rows), "moments": len(groups), "skipped": {"selection_copies": skipped_selection, "unclaimed": len(unclaimed)},
            "unclaimed_rows": unclaimed} | out | ({"common_view": common_summary(measured)} if view else {}) | {"price": prices} | (
                {"probability": probability_summary(against)} if probability == engine.COMMON else {})
