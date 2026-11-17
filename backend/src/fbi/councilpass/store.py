"""The shadow writer of the reduced Council (IA-124, AD-D10): append to ``ai.council_reduced`` what is missing.

One pass (``run_pass``), every ``EVERY`` minutes from the worker while ``FBI_COUNCIL_REDUCED=shadow`` (``off`` by default: the job is not
even scheduled):

1. the passes of the shadow (``ai.match_runs``, run kind ``shadow``) of the matches that kick off in ``[now - BACK, now + AHEAD]``,
   written by ``now`` and with no row of this version yet, oldest first, at most ``LIMIT``;
2. each one deliberated by the protocol AS OF the moment it was written (``protocol.deliberate``: the positions of the readers over its
   package, their weights, the market and the findings - what the judge of that pass had), never past the kick-off;
3. reduced (``reduced.reduce``): the rules for every selection; the judge is not given in this version of the pass, so a selection that
   would need it is kept ``not_asked`` and the rules stand - which measures how many cases (and so how many readings) the judge would cost;
4. one row per selection, written once (``ON CONFLICT DO NOTHING`` on ``council_reduced_once``): the same database gives the same rows.

It writes ``ai.council_reduced`` and nothing else, under an advisory lock; a pass that fails is rolled back to its savepoint and counted.
No model is called.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fbi.council import protocol, reduced

SWITCH: Final = "FBI_COUNCIL_REDUCED"
EVERY: Final = 30
BACK: Final = timedelta(days=2)
AHEAD: Final = timedelta(days=2)
LIMIT: Final = 60
LOCK: Final = 0x1A124
TABLE: Final = "ai.council_reduced"
TIMEOUT_MS: Final = 95_000

PENDING_SQL: Final = """
SELECT r.id, r.fixture_id, r.pass_kind, r.package_hash, r.created_at, f.kickoff_at
  FROM ai.match_runs r JOIN core.fixtures f ON f.id = r.fixture_id
 WHERE r.run_kind = 'shadow' AND r.created_at <= %(now)s AND r.created_at < f.kickoff_at
   AND f.kickoff_at >= %(start)s AND f.kickoff_at <= %(end)s
   AND NOT EXISTS (SELECT 1 FROM ai.council_reduced c WHERE c.match_run_id = r.id AND c.version = %(version)s)
 ORDER BY r.created_at, r.id
 LIMIT %(limit)s
"""

INSERT_SQL: Final = """
INSERT INTO ai.council_reduced (version, protocol, match_run_id, fixture_id, pass_kind, package_hash, deliberated_at, kickoff_at, candidate,
    family, market_key, selection, line, rules_verdict, rules_word, judge_wanted, judge_status, material, majority, final_verdict, source,
    detail, code_version)
VALUES (%(version)s, %(protocol)s, %(match_run_id)s, %(fixture_id)s, %(pass_kind)s, %(package_hash)s, %(deliberated_at)s, %(kickoff_at)s,
    %(candidate)s, %(family)s, %(market_key)s, %(selection)s, %(line)s, %(rules_verdict)s, %(rules_word)s, %(judge_wanted)s,
    %(judge_status)s, %(material)s, %(majority)s, %(final_verdict)s, %(source)s, %(detail)s, %(code_version)s)
ON CONFLICT DO NOTHING
"""


@dataclass
class Report:
    passes: int = 0
    deliberated: int = 0
    written: int = 0
    already: int = 0
    superseded: int = 0
    failed: int = 0
    judge_wanted: int = 0
    lowered: int = 0
    final: Counter[str] = field(default_factory=Counter)
    reasons: Counter[str] = field(default_factory=Counter)
    errors: list[str] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        return {"version": reduced.VERSION, "passes": self.passes, "deliberated": self.deliberated, "written": self.written,
                "already": self.already, "superseded": self.superseded, "failed": self.failed, "judge_wanted": self.judge_wanted,
                "lowered": self.lowered, "final": dict(sorted(self.final.items())), "reasons": dict(sorted(self.reasons.items())),
                "errors": self.errors[:5]}


def rows_of(r: reduced.Reduced, *, pass_kind: str, code_version: str | None) -> list[dict[str, Any]]:
    """The rows of one reduced deliberation (pure)."""
    d = r.deliberation
    if d.status != "ok" or d.match_run_id is None or d.kickoff_at is None:
        return []
    by_key = {s.selection.key: s for s in d.selections}
    out: list[dict[str, Any]] = []
    for o in r.outcomes:
        sel = by_key[o.key].selection
        out.append({"version": reduced.VERSION, "protocol": reduced.PROTOCOL, "match_run_id": d.match_run_id, "fixture_id": d.fixture_id,
                    "pass_kind": pass_kind, "package_hash": d.package_hash, "deliberated_at": d.at, "kickoff_at": d.kickoff_at,
                    "candidate": o.key, "family": sel.family, "market_key": sel.market_key, "selection": sel.selection, "line": sel.line,
                    "rules_verdict": o.rules.adjustment.verdict, "rules_word": o.rules.word, "judge_wanted": o.need.wanted,
                    "judge_status": o.judge_status, "material": list(o.need.material),
                    "majority": None if o.majority is None else o.majority.word, "final_verdict": o.final.verdict, "source": o.source,
                    "detail": Jsonb(o.as_json() | {"selection": by_key[o.key].as_json()}), "code_version": code_version})
    return out


def _pending(conn: psycopg.Connection[Any], now: datetime, limit: int) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(PENDING_SQL, {"now": now, "start": now - BACK, "end": now + AHEAD, "version": reduced.VERSION, "limit": limit})
        return [dict(x) for x in cur.fetchall()]


def run_pass(conn: psycopg.Connection[Any], *, now: datetime, code_version: str | None = None, limit: int = LIMIT) -> Report:
    """One pass in the shadow. Commits its own work."""
    if now.tzinfo is None:
        raise ValueError("a pass runs at a moment with its time zone")
    rep = Report()
    with conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_xact_lock(%s)", (LOCK,))
        got = cur.fetchone()
        cur.execute(f"SET LOCAL statement_timeout = {TIMEOUT_MS}")
    if not got or not got[0]:
        rep.errors.append("another pass holds the lock")
        conn.rollback()
        return rep
    for p in _pending(conn, now, limit):
        rep.passes += 1
        moment = min(p["created_at"], p["kickoff_at"] - timedelta(microseconds=1))
        try:
            with conn.transaction():
                d = protocol.deliberate(conn, int(p["fixture_id"]), at=moment, match_run_id=int(p["id"]))
                if d.status != "ok" or d.match_run_id != int(p["id"]):
                    rep.superseded += 1  # the pass could not be read as of its own moment (it should not happen): nothing is written
                    continue
                r = reduced.reduce(d, judge=None)
                rep.deliberated += 1
                with conn.cursor() as cur:
                    for row in rows_of(r, pass_kind=str(p["pass_kind"]), code_version=code_version):
                        cur.execute(INSERT_SQL, row)
                        if cur.rowcount == 1:
                            rep.written += 1
                        else:
                            rep.already += 1
                for o in r.outcomes:
                    rep.final[o.final.verdict] += 1
                    rep.judge_wanted += int(o.need.wanted)
                    rep.lowered += int(o.lowered)
                    rep.reasons.update(o.need.reasons)
        except Exception as exc:  # one pass that fails never stops the others
            rep.failed += 1
            rep.errors.append(f"{p['id']}: {type(exc).__name__}: {exc}"[:200])
    conn.commit()
    return rep


__all__ = ["AHEAD", "BACK", "EVERY", "LIMIT", "SWITCH", "TABLE", "Report", "rows_of", "run_pass"]
