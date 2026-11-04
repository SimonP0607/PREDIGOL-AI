"""The Post-Match Reviewer ``pmr-v1`` (Plan Maestro IA, section 12, phase 5): after the result, the class of the misses the attribution of the code could not
class, and a short narrative for the owner.

The ARITHMETIC is not here: whether each agent's stance was a hit, a miss or a void, toward the result and toward the closing line, is the server's
(``fbi.ai.agents.attribution``) and is already in ``intel.agent_attributions`` when this module reads it. What is left is what code cannot do well:

* the class of a MISS that the rule left ``UNKNOWN`` (a rejection that was wrong while the market agreed with the selection...), chosen among the words of
  the post-mortem ``pm-v6``. The answer is a SECOND row of the table (``classified_by = 'pmr-v1'``, ``basis_id`` the row it refines): the row of the code is
  never touched, and the reader that wants the model's class asks for it by name;
* a narrative of at most 900 characters, kept in ``ai.postmortem_narratives`` under the version ``pmr-v1``. It is shown, never measured and never read as an
  instruction by anything.

Everything the model may change is checked: a row it was not given, an outcome other than the server's, a class for a row the code had already classed, a
reference it was not offered - each is dropped and counted, and the rest stands. A model that answers nothing, or nonsense, leaves the attribution as it was.

It runs only in the Batch of the LAB (``fbi.ai.agents.lab_batch``): Haiku writes the narrative of a case, Sonnet the one of a loss worth explaining (a
Council's APPROVE that lost), at most four a day. The switch is ``FBI_AI_PM_REVIEWER``; off, nothing here is called.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final

import httpx
import psycopg
from psycopg.rows import dict_row, tuple_row
from psycopg.types.json import Jsonb

from fbi.ai.agents import attribution
from fbi.ai.agents.lab_batch import Submitted, submit
from fbi.ai.batch import BatchClient, Resolved, Task, register
from fbi.ai.config import SHADOW_ENGINES, AiSettings, Tier
from fbi.ai.contracts import parse, schema_of
from fbi.ai.contracts.base import POST_MATCH
from fbi.ai.contracts.postmatch import NARRATIVE_MAX, ROWS_MAX, PostMatchOut
from fbi.ai.prompts import PMR_SYSTEM, PMR_VERSION
from fbi.ai.providers.base import JsonRequest
from fbi.ai.untrusted import sanitize
from fbi.ai.usage import UsageLedger

AGENT: Final = "pmr"
VERSION: Final = PMR_VERSION
LOOKBACK: Final = timedelta(days=7)
"""A case nobody explained in a week is not explained: what ended yesterday is what is learned today."""
MAX_CASES: Final = 12
"""Cases a run may send."""
MAX_STRONG_PER_DAY: Final = 4
"""Cases a day that Sonnet explains (the plan: «como mucho 4 al día»)."""
NOTE_MAX: Final = 240
TYPICAL_OUTPUT: Final = 700
PURPOSE: Final = "postmortem"
NOTE_KEYS: Final = ("information", "key_absence", "ignored_signal", "lineup_changed")
"""The questions of the post-mortem whose DETAIL is text from outside (a report, a name): it travels in an untrusted block."""
YES_NO: Final = {"sí": "YES", "si": "YES", "no": "NO"}

ROWS_SQL: Final = """
SELECT a.id, a.postmortem_id, a.fixture_id, a.market_key, a.selection, a.line, a.engine, a.agent, a.agent_version, a.signal, a.stance, a.outcome,
       a.error_class, a.settled, a.toward_close, a.calibration, a.clv, f.kickoff_at
  FROM intel.agent_attributions a JOIN core.fixtures f ON f.id = a.fixture_id
 WHERE a.classified_by = 'code' AND a.attribution_version = %(version)s AND f.kickoff_at >= %(since)s AND f.kickoff_at < %(until)s
   AND NOT EXISTS (SELECT 1 FROM ai.postmortem_narratives n WHERE n.postmortem_id = a.postmortem_id AND n.version = %(pmr)s)
 ORDER BY a.postmortem_id, a.engine, a.agent, (a.signal <> 'VERDICT'), a.signal
"""
ANSWERS_SQL: Final = "SELECT id, answers FROM intel.postmortems WHERE id = ANY(%(ids)s)"
STRONG_TODAY_SQL: Final = """
SELECT count(*) FROM ai.batch_items WHERE purpose = 'postmortem' AND tier = 'analysis' AND context ? 'pmr' AND created_at >= %(since)s
"""
BASIS_SQL: Final = """
SELECT id, fixture_id, market_key, selection, line, engine, agent, agent_version, signal, stance, outcome, settled, toward_close, calibration, clv,
       review_id, run_id, postmortem_id
  FROM intel.agent_attributions WHERE id = ANY(%(ids)s) AND classified_by = 'code' AND outcome = 'MISS' AND error_class = 'UNKNOWN'
"""
REFINE_SQL: Final = """
INSERT INTO intel.agent_attributions (attribution_version, classified_by, fixture_id, market_key, selection, line, engine, agent, agent_version, signal,
    stance, outcome, error_class, settled, toward_close, calibration, clv, review_id, run_id, postmortem_id, basis_id, source, computed_at)
VALUES (%(version)s, 'pmr-v1', %(fixture_id)s, %(market_key)s, %(selection)s, %(line)s, %(engine)s, %(agent)s, %(agent_version)s, %(signal)s, %(stance)s,
    'MISS', %(error_class)s, %(settled)s, %(toward_close)s, %(calibration)s, %(clv)s, %(review_id)s, %(run_id)s, %(postmortem_id)s, %(basis)s, 'live', %(at)s)
ON CONFLICT DO NOTHING
"""
NARRATIVE_SQL: Final = ("INSERT INTO ai.postmortem_narratives (postmortem_id, created_at, version, narrative, usage_ids) VALUES (%s, %s, %s, %s, %s) "
                        "ON CONFLICT DO NOTHING")


@dataclass(frozen=True, slots=True)
class CaseRow:
    """One row of the attribution as the model is shown it: the server's outcome and class, under a name the model can cite."""

    ref: str
    candidate: str
    engine: str
    agent: str
    agent_version: str
    signal: str
    stance: str
    outcome: str
    error_class: str
    row_id: int
    toward_close: bool | None = None

    def key(self) -> tuple[str, str, str]:
        return (self.candidate, self.agent, self.signal)

    def to_json(self) -> dict[str, Any]:
        """What the model reads and what the batch item keeps: codes and ids, nothing that came from outside."""
        return {"ref": self.ref, "candidate": self.candidate, "agent": self.agent, "version": self.agent_version, "signal": self.signal,
                "stance": self.stance, "outcome": self.outcome, "error_class": self.error_class, "toward_close": self.toward_close,
                "row": self.row_id}


@dataclass(frozen=True, slots=True)
class Case:
    """One settled selection with every attribution of the code about it, ready to ask about."""

    postmortem_id: int
    fixture_id: int
    settled: str
    calibration: str | None
    clv_sign: str
    engines: Mapping[str, str]
    """candidate name -> shadow engine."""
    rows: tuple[CaseRow, ...]
    notes: tuple[dict[str, Any], ...] = ()
    """Untrusted blocks: the details of the post-mortem that came from outside."""
    facts: Mapping[str, str] = field(default_factory=dict)

    @property
    def ambiguous(self) -> int:
        return sum(1 for r in self.rows if r.outcome == "MISS" and r.error_class == "UNKNOWN")

    @property
    def loss_worth_explaining(self) -> bool:
        """The Council's APPROVE that lost: the case the plan gives to Sonnet."""
        return any(r.agent == "council" and r.signal == "VERDICT" and r.stance == "APPROVE" and r.outcome == "MISS" for r in self.rows)

    @property
    def worth_asking(self) -> bool:
        return self.ambiguous > 0 or self.loss_worth_explaining

    def input_hash(self) -> str:
        body = json.dumps([VERSION, self.postmortem_id, [r.to_json() for r in self.rows]], sort_keys=True, default=str)
        return hashlib.sha256(body.encode()).hexdigest()[:40]


def clv_sign(clv: Any) -> str:
    return "UNKNOWN" if clv is None else "POSITIVE" if clv > 0 else "NEGATIVE" if clv < 0 else "ZERO"


def build_cases(rows: Sequence[Mapping[str, Any]], answers: Mapping[int, Mapping[str, Any]]) -> list[Case]:
    """The cases of a list of attribution rows (already ordered by post-mortem): pure. A case keeps at most ``ROWS_MAX`` rows (the contract's), the stance
    rows first. The engines are named ``c1``, ``c2``... in the order of ``SHADOW_ENGINES``: the contract speaks of candidates, and the same selection under
    two arms is two candidates for the one who reads."""
    by_pm: dict[int, list[Mapping[str, Any]]] = {}
    for r in rows:
        by_pm.setdefault(int(r["postmortem_id"]), []).append(r)
    cases: list[Case] = []
    for pm_id, group in sorted(by_pm.items()):
        present = [e for e in SHADOW_ENGINES if any(r["engine"] == e for r in group)]
        names = {e: f"c{i}" for i, e in enumerate(present, start=1)}
        ordered = sorted(group, key=lambda r: (str(r["signal"]) != "VERDICT", present.index(str(r["engine"])), str(r["agent"]), str(r["signal"])))
        kept = ordered[:ROWS_MAX]
        case_rows = tuple(CaseRow(ref=f"A:row{i}", candidate=names[str(r["engine"])], engine=str(r["engine"]), agent=str(r["agent"]),
                                  agent_version=str(r["agent_version"]), signal=str(r["signal"]), stance=str(r["stance"]), outcome=str(r["outcome"]),
                                  error_class=str(r["error_class"]), row_id=int(r["id"]), toward_close=r["toward_close"])
                          for i, r in enumerate(kept, start=1))
        first = group[0]
        detail = answers.get(pm_id, {})
        notes: list[dict[str, Any]] = []
        facts: dict[str, str] = {}
        for key in NOTE_KEYS:
            item = detail.get(key)
            if isinstance(item, Mapping):
                facts[key] = YES_NO.get(str(item.get("answer", "")).strip().lower(), "NA")
                text = sanitize(item.get("detail"), origin="postmortem", max_chars=NOTE_MAX)
                if text.text:
                    notes.append({"about": key} | text.as_block())
        cases.append(Case(postmortem_id=pm_id, fixture_id=int(first["fixture_id"]), settled=str(first["settled"]),
                          calibration=first["calibration"], clv_sign=clv_sign(first["clv"]), engines=names_inverse(names), rows=case_rows,
                          notes=tuple(notes), facts=facts))
    return cases


def names_inverse(names: Mapping[str, str]) -> dict[str, str]:
    return {candidate: engine for engine, candidate in names.items()}


def request_of(case: Case) -> JsonRequest:
    """The question: the case as JSON - the server's codes, and the notes that came from outside inside blocks that say so."""
    body = {"case": {"settled": case.settled, "clv": case.clv_sign, "calibration": case.calibration, "facts": dict(case.facts),
                     "candidates": [{"candidate": c, "engine": e} for c, e in sorted(case.engines.items())],
                     "rows": [r.to_json() for r in case.rows]},
            "notes": list(case.notes)}
    return JsonRequest(PMR_SYSTEM, json.dumps(body, ensure_ascii=False, sort_keys=True), schema_of(POST_MATCH), "submit_post_match", max_tokens=3000)


def task_of(case: Case, *, strong: bool, at: datetime) -> Task:
    tier: Tier = "analysis" if strong else "bulk"
    context = {"pmr": 1, "task": "loss_review" if strong else "narrative", "postmortem_id": case.postmortem_id, "fixture_id": case.fixture_id,
               "rows": [r.to_json() for r in case.rows], "offered": [r.ref for r in case.rows], "at": at.isoformat()}
    return Task(purpose=PURPOSE, tier=tier, request=request_of(case), prompt_version=VERSION, input_hash=case.input_hash(), fixture_id=case.fixture_id,
                context=context, lab=True, agent=AGENT, typical_output=TYPICAL_OUTPUT)


# -- what comes back (pure) -----------------------------------------------------------------------------------------------------------

@dataclass(slots=True)
class Accepted:
    """What stands of an answer: the classes to add (row id -> class), the narrative, and what was dropped and why."""

    refine: dict[int, str] = field(default_factory=dict)
    narrative: str = ""
    rejected: Counter[str] = field(default_factory=Counter)


def accept(rows: Sequence[CaseRow], out: PostMatchOut) -> Accepted:
    """The answer as the server keeps it. The model may add a class to a MISS the code left ``UNKNOWN``, and nothing else: the outcome is the server's, a
    class the code already gave stands, a row that was not asked about does not exist, a reference that was not offered drops the row."""
    verdict = Accepted()
    index = {r.key(): r for r in rows}
    offered = {r.ref for r in rows}
    for a in out.attributions:
        row = index.get((a.candidate, a.agent, a.signal))
        if row is None:
            verdict.rejected["unknown_row"] += 1
        elif any(ref not in offered and not ref.startswith("P:") for ref in a.refs):
            verdict.rejected["unknown_ref"] += 1
        elif a.outcome != row.outcome:
            verdict.rejected["outcome_changed"] += 1
        elif row.outcome == "MISS" and row.error_class != "UNKNOWN":
            if a.error_class != row.error_class:
                verdict.rejected["class_of_the_code_stands"] += 1
        elif row.outcome == "MISS" and a.error_class not in ("UNKNOWN", "NONE"):
            verdict.refine[row.row_id] = a.error_class
    verdict.narrative = sanitize(out.narrative, origin=VERSION, max_chars=NARRATIVE_MAX).text
    return verdict


def settle(conn: psycopg.Connection[Any], r: Resolved) -> None:
    """The handler of the answers of the Batch (``fbi.ai.batch.poll``): validates the answer against the case it was asked about, writes the classes and the
    narrative that stand, and keeps a summary in the item. Nothing else is written; a failure of any kind leaves the attribution as the code made it."""
    ctx = r.item["context"] or {}
    if not ctx.get("pmr"):
        return  # an item of another purpose that shares the word
    summary: dict[str, Any] = {"pmr": 1, "usage_id": r.usage_id, "late": r.late, "task": ctx.get("task")}
    parsed = parse(POST_MATCH, r.result.data) if r.result is not None else None
    if parsed is None or not parsed.ok or not isinstance(parsed.value, PostMatchOut):
        summary |= {"ok": False, "error": "no_answer" if r.result is None else "invalid", "problems": [] if parsed is None else list(parsed.problems)}
    else:
        rows = tuple(CaseRow(ref=x["ref"], candidate=x["candidate"], engine="", agent=x["agent"], agent_version=x["version"], signal=x["signal"],
                             stance=x["stance"], outcome=x["outcome"], error_class=x["error_class"], row_id=int(x["row"]),
                             toward_close=x.get("toward_close")) for x in ctx.get("rows") or [])
        kept = accept(rows, parsed.value)
        written = write(conn, kept, postmortem_id=int(ctx["postmortem_id"]), at=r.at, usage_id=r.usage_id)
        summary |= {"ok": True, "refined": written, "rejected": dict(kept.rejected), "narrative": bool(kept.narrative)}
    with conn.cursor() as cur:
        cur.execute("UPDATE ai.batch_items SET context = context || %s WHERE id = %s", (Jsonb({"result": summary}), int(r.item["id"])))


def write(conn: psycopg.Connection[Any], kept: Accepted, *, postmortem_id: int, at: datetime, usage_id: int | None) -> int:
    """The second rows and the narrative. Idempotent: the unique keys of both tables leave what is there alone."""
    written = 0
    with conn.cursor(row_factory=dict_row) as cur:
        if kept.refine:
            for basis in cur.execute(BASIS_SQL, {"ids": sorted(kept.refine)}).fetchall():
                cur.execute(REFINE_SQL, dict(basis) | {"version": attribution.VERSION, "error_class": kept.refine[int(basis["id"])],
                                                       "basis": int(basis["id"]), "at": at})
                written += cur.rowcount
    if kept.narrative:
        with conn.cursor(row_factory=tuple_row) as cur:
            cur.execute(NARRATIVE_SQL, (postmortem_id, at, VERSION, kept.narrative, [usage_id] if usage_id else []))
    return written


register(PURPOSE, settle)


# -- the daily step -------------------------------------------------------------------------------------------------------------------

def due(conn: psycopg.Connection[Any], *, at: datetime, lookback: timedelta = LOOKBACK) -> list[Case]:
    """The cases worth asking about that nobody has narrated yet: a miss the code could not class, or a Council's approval that lost."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(ROWS_SQL, {"version": attribution.VERSION, "since": at - lookback, "until": at, "pmr": VERSION})
        rows = [dict(r) for r in cur.fetchall()]
        ids = sorted({int(r["postmortem_id"]) for r in rows})
        answers = {int(r["id"]): dict(r["answers"] or {}) for r in cur.execute(ANSWERS_SQL, {"ids": ids}).fetchall()} if ids else {}
    return [c for c in build_cases(rows, answers) if c.worth_asking]


def run(conn: psycopg.Connection[Any], settings: AiSettings, *, at: datetime, ledger: UsageLedger | None = None, client: BatchClient | None = None,
        transport: httpx.BaseTransport | None = None) -> dict[str, Any]:
    """The Post-Match Reviewer's part of the daily step: send the cases that are due, in the Batch of the LAB. The answers are written when the poll
    brings them. Never raises into the cycle that calls it (the caller isolates it all the same)."""
    cases = due(conn, at=at)
    out: dict[str, Any] = {"due": len(cases)}
    if not cases:
        return out
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(STRONG_TODAY_SQL, {"since": at.replace(hour=0, minute=0, second=0, microsecond=0)})
        row = cur.fetchone()
    strong_left = max(0, MAX_STRONG_PER_DAY - (int(row[0]) if row else 0))
    tasks: list[Task] = []
    for case in cases[:MAX_CASES]:
        strong = case.loss_worth_explaining and strong_left > 0
        if strong:
            strong_left -= 1
        tasks.append(task_of(case, strong=strong, at=at))
    sent: Submitted = submit(conn, settings, tasks, at=at, ledger=ledger, client=client, transport=transport)
    return out | sent.counts()


__all__ = ["VERSION", "Accepted", "Case", "CaseRow", "accept", "build_cases", "due", "request_of", "run", "settle", "task_of", "write"]
