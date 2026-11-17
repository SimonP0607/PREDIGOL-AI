"""The shadow writer of the evaluations after the match (IA-112, AD-K01): append to ``intel.selection_evaluations`` what is missing.

One pass (``run_pass``), every ``EVERY`` minutes from the worker while ``FBI_SELECTION_EVAL=shadow`` (``off`` by default: the job is not
even scheduled):

1. the matches with a decision of a followed layer that kicked off in ``[now - BACK, now - WAIT)``;
2. what each settled selection of them is made of (``fbi.evalpass.reads``, read only);
3. its evaluation (``fbi.evaluation.selection.evaluate``, pure), written once: a selection already evaluated under this version is
   not written again (``ON CONFLICT DO NOTHING`` on ``selection_evaluations_once``), so the pass is idempotent and the same database
   gives the same rows.

It writes ``intel.selection_evaluations`` and nothing else (``tests/unit/test_selection_evaluation_isolation.py`` scans every
statement); two passes cannot write at once (an advisory lock). ``dry_run`` computes the same evaluations without writing - the owner's
measurement (``scripts/ia_selection_eval.py``) and the board over a period before the table has rows.

The five old writers of the «after» - the post-mortem by decision (pm-v6), the families' post-mortem (pm-fam-v1), the review of the match,
the daily review and the review of the chronicle - are not touched: they keep writing until AD-K06 retires them one by one.
"""

from __future__ import annotations

import os
from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final

import psycopg
from psycopg.types.json import Jsonb

from fbi.evalpass import reads
from fbi.evaluation import selection
from fbi.evaluation.selection import Evaluation

SWITCH: Final = "FBI_SELECTION_EVAL"
EVERY: Final = 60
BACK: Final = timedelta(days=7)
"""How far back a match is still evaluated: its settlement (p90 48 h after kick-off; the cards of a family wait 30 h)."""
WAIT: Final = timedelta(hours=2)
LOCK: Final = 0x1A112
TABLE: Final = "intel.selection_evaluations"

INSERT_SQL: Final = """
INSERT INTO intel.selection_evaluations (version, layer, decision_source, decision_id, fixture_id, family, taken, market_key, selection, line,
    kickoff_at, decided_at, settled_at, result, p_judged, seal, p_market, odds, p_close, clv, hit, log_loss, brier, market_log_loss,
    market_brier, price_quality, verdict, evidence_held, evidence_contradicted, evidence_unevaluable, lineup_changed, parity, detail,
    input_hash, code_version)
VALUES (%(version)s, %(layer)s, %(decision_source)s, %(decision_id)s, %(fixture_id)s, %(family)s, %(taken)s, %(market_key)s, %(selection)s,
    %(line)s, %(kickoff_at)s, %(decided_at)s, %(settled_at)s, %(result)s, %(p_judged)s, %(seal)s, %(p_market)s, %(odds)s,
    %(p_close)s, %(clv)s, %(hit)s, %(log_loss)s, %(brier)s, %(market_log_loss)s, %(market_brier)s, %(price_quality)s, %(verdict)s,
    %(evidence_held)s, %(evidence_contradicted)s, %(evidence_unevaluable)s, %(lineup_changed)s, %(parity)s, %(detail)s,
    %(input_hash)s, %(code_version)s)
ON CONFLICT DO NOTHING
"""


def mode() -> str:
    """``shadow`` writes; any other word (``off`` the default) is off."""
    return "shadow" if os.environ.get(SWITCH, "off").strip().lower() == "shadow" else "off"


@dataclass
class Report:
    fixtures: int = 0
    evaluated: int = 0
    written: int = 0
    already: int = 0
    failed: int = 0
    skipped: Counter[str] = field(default_factory=Counter)
    parity: Counter[str] = field(default_factory=Counter)
    errors: list[str] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        return {"fixtures": self.fixtures, "evaluated": self.evaluated, "written": self.written, "already": self.already,
                "failed": self.failed, "skipped": dict(self.skipped), "parity": dict(self.parity), "errors": self.errors[:5]}


def evaluations(conn: psycopg.Connection[Any], fixture_ids: Iterable[int], report: Report | None = None) -> list[Evaluation]:
    """The evaluations of every settled selection of these matches (read only)."""
    rep = report if report is not None else Report()
    ids = sorted(set(fixture_ids))
    out: list[Evaluation] = []
    for i in range(0, len(ids), reads.CHUNK):
        b = reads.batch(conn, ids[i:i + reads.CHUNK])
        rep.skipped.update(b.skipped)
        for inputs in b.inputs:
            try:
                ev = selection.evaluate(inputs)
            except ValueError as exc:
                rep.failed += 1
                rep.errors.append(f"{inputs.decided.source}:{inputs.decided.decision_id}: {exc}"[:200])
                continue
            rep.parity[str(ev.row["parity"])] += 1
            out.append(ev)
    rep.evaluated += len(out)
    return out


def dry_run(conn: psycopg.Connection[Any], *, start: datetime, end: datetime) -> tuple[list[Evaluation], Report]:
    """The evaluations of the matches that kicked off in ``[start, end)``, computed and NOT written."""
    rep = Report()
    ids = reads.fixtures(conn, start, end)
    rep.fixtures = len(ids)
    return evaluations(conn, ids, rep), rep


def write(conn: psycopg.Connection[Any], evs: Iterable[Evaluation], *, code_version: str | None) -> tuple[int, int]:
    """Append the evaluations; (written, already there)."""
    written = already = 0
    with conn.cursor() as cur:
        for ev in evs:
            cur.execute(INSERT_SQL, {**ev.row, "detail": Jsonb(dict(ev.detail)), "code_version": code_version})
            if cur.rowcount == 1:
                written += 1
            else:
                already += 1
    return written, already


def run_pass(conn: psycopg.Connection[Any], *, now: datetime, code_version: str | None = None) -> Report:
    """One pass in the shadow: evaluate what was settled and is not evaluated yet, and append it. Commits its own work."""
    rep = Report()
    with conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_xact_lock(%s)", (LOCK,))
        got = cur.fetchone()
    if not got or not got[0]:
        rep.errors.append("another pass holds the lock")
        conn.rollback()
        return rep
    ids = reads.fixtures(conn, now - BACK, now - WAIT)
    rep.fixtures = len(ids)
    evs = evaluations(conn, ids, rep)
    rep.written, rep.already = write(conn, evs, code_version=code_version)
    conn.commit()
    return rep
