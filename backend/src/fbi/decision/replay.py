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
                     replay is the equivalence of the engine.

Then each row is compared with the decision of the same selection: decision-v1's state read through state-v2 (``state_v2.classify``)
against decision-v2's. The report: the agreement per family (and per market), the confusion table, the labels and checkpoints that
agree, every disagreement with the stage that caused it (the first stage, in order, whose reason codes differ), and every row whose
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
from fbi.decision import engine, market_inputs
from fbi.decision.families import FAMILIES, INFO_CODES, Candidate, MarketFamily, family_of
from fbi.intel import context_adjustment as ctx_adj
from fbi.intel import decision, state_v2
from fbi.intel.decision import Key

VERSION: Final = "decision-v2-replay-v1"
SELECTION: Final = "selection"
"""The checkpoint of a copy of a decision as a PICK DEL DÍA (``decision.select_day``)."""
NOT_FOUND: Final = "candidate"
"""The ``stage`` of a row whose candidate decision-v2 could not rebuild."""

DAY_SQL: Final = """
SELECT d.id, d.decision_version, d.known_at, d.checkpoint, d.fixture_id, d.market_key, d.selection, d.line, d.model_name, d.state,
       d.reasons, d.filters, d.context_status
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
    confusion: dict[str, Counter[str]] = dataclasses.field(default_factory=lambda: defaultdict(Counter))
    by_market: dict[str, list[int]] = dataclasses.field(default_factory=lambda: defaultdict(lambda: [0, 0]))

    def as_json(self) -> dict[str, Any]:
        return {"n": self.n, "agree": self.agree, "rate": _rate(self.agree, self.n), "unmatched": self.unmatched,
                "confusion": {a: dict(sorted(c.items())) for a, c in sorted(self.confusion.items())},
                "by_market": {m: {"n": v[0], "agree": v[1], "rate": _rate(v[1], v[0])} for m, v in sorted(self.by_market.items())},
                "labels": {"n": self.labels_n, "agree": self.labels_agree},
                "checkpoints": {"n": self.n - self.unmatched, "agree": self.checkpoints_agree},
                "same_state_other_reasons": self.reasons_differ}


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
            disagreements.append(_where(row, family) | {
                "v1_state": row["state"], "v1_state2": v1_state, "v1_reason": v1_reason, "v1_codes": v1_codes(row),
                "v2_state": d.state, "v2_reason": d.reason, "v2_codes": list(d.codes), "stage": stage,
                "v1_why": _v1_why(row, stage), "v2_why": d.verdict(stage).why if stage in engine.NUMBER else None})
    return {"agreement": {"n": total.n, "agree": total.agree, "rate": _rate(total.agree, total.n), "unmatched": total.unmatched},
            "confusion": total.as_json()["confusion"], "families": {f: a.as_json() for f, a in sorted(per.items())},
            "disagreements": disagreements, "unmatched": unmatched}


# -- the replay -----------------------------------------------------------------------------------------------------------------------

def _primary_p(world: decision.World, c: Candidate) -> float | None:
    names = sorted(c.models)
    model = world.cal.primary_model(c.key[1], names) or names[0]
    p = c.models[model].get("p_model")
    return None if p is None else float(p)


def replay_day(conn: psycopg.Connection[Any], *, day: date, families: Sequence[MarketFamily] = FAMILIES, council: str | None = None,
               signals: bool = False) -> dict[str, Any]:
    """decision-v2 over every row decision-v1 and decision-fam-v1 wrote during ``day``, compared. Read-only."""
    if council is not None and council not in ctx_adj.ENGINES:
        raise ValueError(f"council must be one of {ctx_adj.ENGINES}")
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
    for (at, _), items in sorted(groups.items()):
        fams = [f for f in families if any(f is g for _, g in items)]
        fixtures = sorted({int(r["fixture_id"]) for r, _ in items})
        world = world_at(conn, fams[0], fixtures, at=at, rows=[r for r, _ in items])
        cands = [c for f in fams for c in f.candidates(conn, at=at, fixtures=fixtures)]
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
        index = {d.ident: d for d in engine.decide_all(world, cands, adjustments=adjustments, markets=markets)}
        for r, fam in items:
            k = key_of(r)
            d = index.get((fam.name, k, str(r.get("model_name")))) or index.get((fam.name, k, None))
            pairs.append((r, fam.name, d))
    out = compare(pairs, families=[f.name for f in families])
    return {"version": engine.VERSION, "replay": VERSION, "day": day.isoformat(), "versions": versions,
            "inputs": {"council": council, "signals": signals, "previous": "strictly before known_at", "ai_mode": "as the rows recorded it"},
            "rows": len(rows), "moments": len(groups), "skipped": {"selection_copies": skipped_selection, "unclaimed": len(unclaimed)},
            "unclaimed_rows": unclaimed} | out
