"""Re-settling what a corrected result changed - with a trail (plan F0, defect 5; settle-v4).

WHY. The result of a match is overwritten in place whenever a writer reads a newer payload, and the settlement of the
bets on it runs once: on the FIRST read that says full time, which is before the re-reads (kick-off + 150 minutes and
+ 26 hours) that exist to catch corrections. A goal the provider gives or takes away an hour after the final whistle
therefore left every pick, pick of the day, parlay and user's bet settled on the wrong result, for ever, and nothing in
the database said so.

HOW. Migration 0080 records every correction of a result (``core.fixture_result_revisions``, written by a trigger so no
writer can skip it). This module reads the matches that were corrected, evaluates again every record settled on them
with the SAME rules that settled it (``fbi.picks.settlement``, ``product_settlement``), and where the current result
settles a record differently it changes the record - the result it shows, never what was decided before kick-off - and
writes a row to ``picks.resettlements`` (what it was, what it is, the rule version, the reason, the revision) and, for
a pick, an event on its own timeline. A parlay follows its legs: a leg corrected so that the parlay is decided
differently changes it, and a parlay that a corrected leg no longer decides goes back to ACTIVE (un-settled).

WHAT IT CHANGES, AND WHAT IT REFUSES TO GUESS. It acts only where a SCORE decided the record and the current score
decides it differently. Everything else is held and reported, never applied: a record settled void by rule (the match
was cancelled, or had no official result 72 hours after kick-off) that now has a result; a record settled on a score
whose match now settles by rule (it reads cancelled, say) or no longer settles at all (it reads postponed, or its
regulation score is gone). Whether a bookmaker would void a bet after the fact is a decision for a person, and a
status that flips for one read and flips back must not rewrite money twice.

IDEMPOTENT. The routine compares each record with what the current result gives, so a second pass finds nothing to do,
and a correction that is itself corrected moves the record back with a second row of the trail. Every UPDATE is guarded
by the record's own stored result: a record another pass changed in between is a conflict (counted), not an overwrite.

MASS GUARD. More than ``MAX_FIXTURES`` matches with a changed record in one pass is not a correction, it is something
upstream going wrong (a reprocess, a defect): nothing is written, the list is reported, and a person raises the limit
once they have looked.

NOT REWRITTEN HERE. What was DERIVED from the old result - the decision outcomes, the post-mortems, the memory and the
learning built on them - is append-only and is counted (``ResettlementReport.stale``), not touched: rebuilding it is
plan phase F8. The record itself, ``pick_results.settled_at`` included, keeps the moment it was first settled; the
moment of each correction is in the trail.

No provider request. The caller owns the transaction (the pipeline commits it; the command line commits it only with
``--apply``); a dry run (``apply=False``) writes inside a transaction it rolls back, so what it prints is exactly what
``--apply`` would do.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Literal

import psycopg
import structlog
from psycopg.rows import dict_row

from fbi.picks import settlement
from fbi.picks.engine import TAKEN_KICKOFF
from fbi.picks.product_settlement import (
    FINAL_LEG,
    PARLAY_RULE_VERSION,
    parlay_outcome,
    settle_single,
)

log = structlog.get_logger(__name__)

RECHECK_WINDOW = timedelta(days=7)
"""A routine pass looks at the matches corrected in this long: the pipeline runs every 30 minutes, so this survives a
worker that was down for days. ``audit`` reaches every settled record whatever its history."""
MAX_FIXTURES = 25
"""Matches with a changed record, in one pass, beyond which nothing is written (see the mass guard above)."""
LOCK = "picks.resettlement"
FINAL_PARLAY = ("WON", "LOST", "VOID", "PARTIAL_VOID")
"""The statuses of a settled parlay (an ACTIVE one is still being played)."""

Row = dict[str, Any]
Action = Literal["same", "change", "held"]


@dataclass(frozen=True)
class Verdict:
    """What the current result says about one settled record."""

    action: Action
    status: str | None = None
    profit: Decimal | None = None
    code: str = ""
    detail: str = ""


def judge(*, stored_status: str, stored_profit: Decimal | None, score_based: bool, outcome: settlement.Settlement,
          priced: bool, upper: bool, status_short: str) -> Verdict:
    """Compare a settled record with how the same rules settle it on the current result. Pure.

    ``score_based``: the stored result came from a score (not from a void by rule). ``priced``: the record keeps a
    profit and it is known (a leg keeps none; a user's bet can lack a price). ``upper``: the record keeps its status in capitals (the product's
    records) rather than lowercase (a pick's result)."""
    if not outcome.is_final:
        why = outcome.review_reason or f"the match reads {status_short.strip().upper()}, not finished"
        return Verdict("held", code="no_longer_settles", detail=f"the current state no longer settles it: {why}")
    new_status = outcome.status.value.upper() if upper else outcome.status.value
    new_profit = outcome.profit_units if priced else None
    if (new_status, new_profit) == (stored_status, stored_profit):
        return Verdict("same")
    if outcome.basis != settlement.BASIS:
        return Verdict("held", code="settles_by_rule_now",
                       detail=f"the match now settles by rule ({outcome.basis}: {new_status}) but the record was "
                              f"settled on a score ({stored_status}); a person decides whether to void it")
    if not score_based:
        return Verdict("held", code="void_by_rule_stands",
                       detail=f"settled {stored_status} by rule, and the match now has a result ({new_status}); "
                              "the void stands until a person decides otherwise")
    return Verdict("change", new_status, new_profit)


@dataclass(frozen=True)
class Revision:
    """The latest recorded correction of a match: what the reasons of the trail quote."""

    id: int
    kind: str
    old_state: dict[str, Any]
    new_state: dict[str, Any]
    changed: list[str]
    observed_at: datetime


def _regulation(state: dict[str, Any]) -> str:
    home, away = state.get("reg_goals_home"), state.get("reg_goals_away")
    return "?-?" if home is None or away is None else f"{home}-{away}"


def explain(revision: Revision | None) -> tuple[str, int | None]:
    """(reason, revision id) for the trail row of a record whose match was corrected."""
    if revision is None:
        return ("audit: the stored result is not the one the current result of the match gives, and no correction of "
                "the result was recorded (it predates revision 0080, or the record was never consistent)", None)
    when = f"revision {revision.id}, {revision.observed_at:%Y-%m-%d %H:%M} UTC"
    if revision.kind == "status":
        return (f"the status of the match moved from {revision.old_state.get('status_short')} to "
                f"{revision.new_state.get('status_short')} ({when})", revision.id)
    return (f"the provider corrected the result after 90 minutes: {_regulation(revision.old_state)} -> "
            f"{_regulation(revision.new_state)} ({', '.join(revision.changed)}; {when})", revision.id)


@dataclass(frozen=True)
class Change:
    """A record whose result changed (or, in a dry run, would)."""

    kind: str
    key: str
    fixture_id: int | None
    from_status: str
    from_profit: Decimal | None
    to_status: str
    to_profit: Decimal | None
    reason: str
    revision_id: int | None
    rule_version: str


@dataclass(frozen=True)
class Held:
    """A record the current result puts in question and this module does not decide."""

    kind: str
    key: str
    fixture_id: int | None
    status: str
    code: str
    detail: str


@dataclass
class ResettlementReport:
    applied: bool = False
    audit: bool = False
    busy: bool = False
    """Another pass was re-settling at the same moment: this one did nothing."""
    fixtures: list[int] = field(default_factory=list)
    """The matches examined (empty in an audit, which looks at every settled record)."""
    examined: dict[str, int] = field(default_factory=dict)
    changes: list[Change] = field(default_factory=list)
    held: list[Held] = field(default_factory=list)
    conflicts: int = 0
    """Records another pass changed between this pass's read and its write: left to the next pass."""
    refused: str | None = None
    """Why nothing was written, when the mass guard stopped the pass."""
    stale: dict[str, int] = field(default_factory=dict)
    """Derived records built on the old results (outcomes, post-mortems): counted, rebuilt in plan phase F8."""

    @property
    def changed_fixtures(self) -> list[int]:
        return sorted({c.fixture_id for c in self.changes if c.fixture_id is not None})

    def by_kind(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for c in self.changes:
            out[c.kind] = out.get(c.kind, 0) + 1
        return out

    def summary(self) -> str:
        done = "re-settled" if self.applied else "would re-settle"
        text = f"{done} {len(self.changes)} record(s) on {len(self.changed_fixtures)} match(es)"
        if self.held:
            text += f", {len(self.held)} held for a person"
        if self.conflicts:
            text += f", {self.conflicts} conflict(s)"
        if self.refused:
            text += f"; REFUSED: {self.refused}"
        return text

    def render(self) -> list[str]:
        """Plain lines for the command line and the logs."""
        mode = "AUDIT of every settled record" if self.audit else f"{len(self.fixtures)} corrected match(es) examined"
        lines = [f"{'APPLIED' if self.applied else 'DRY RUN'} - {mode}; records read: "
                 + (", ".join(f"{k} {n}" for k, n in sorted(self.examined.items())) or "none")]
        if self.busy:
            lines.append("Another re-settlement was running: nothing was done.")
        lines.append(self.summary() + ".")
        for c in self.changes:
            lines.append(f"  {c.kind} {c.key} (match {c.fixture_id}): {c.from_status} {_money(c.from_profit)} -> "
                         f"{c.to_status} {_money(c.to_profit)}  [{c.reason}]")
        for h in self.held:
            lines.append(f"  HELD {h.kind} {h.key} (match {h.fixture_id}, {h.status}): {h.code} - {h.detail}")
        if self.stale:
            lines.append("  built on the old results, not rewritten here (plan phase F8): "
                         + ", ".join(f"{t} {n}" for t, n in sorted(self.stale.items())))
        if not self.applied and self.changes and not self.refused:
            lines.append("Nothing was written. Run with --apply --by NAME to write it.")
        return lines


def _money(profit: Decimal | None) -> str:
    return "(no profit)" if profit is None else f"({profit:+.4f}u)"


# -------------------------------------------------------------------------------- what is read and where it is written

_SCOPE = " AND (%(fixtures)s::bigint[] IS NULL OR {a}.fixture_id = ANY(%(fixtures)s))"
"""Only some matches, or (None) every one: the routine pass and the audit read the same way."""
_FIXTURE = ("f.status_short, r.reg_goals_home, r.reg_goals_away, r.et_goals_home, r.et_goals_away, "
            "r.ft_goals_home, r.ft_goals_away, r.source_payload_hash AS payload_hash")


@dataclass(frozen=True)
class Kind:
    """One kind of settled record that rests on a score: how it is read, and how a changed result is written."""

    name: str
    select: str
    relation: str
    keys: tuple[str, ...]
    status_col: str
    profit_col: str | None
    upper: bool
    rule_version: str
    pick: bool = False


SINGLES: tuple[Kind, ...] = (
    Kind("pick", """
        SELECT p.id AS k1, NULL::int AS k2, p.fixture_id, p.market_key, p.selection, p.line, p.market_odds AS price,
               p.stake_units AS stake, pr.result_status AS status, pr.profit_units AS profit, pr.settled_at,
               pr.settlement_basis AS basis, """ + _FIXTURE + """,
               """ + TAKEN_KICKOFF.format(since="p.created_at") + """ AS taken_kickoff
          FROM picks.picks p JOIN picks.pick_results pr ON pr.pick_id = p.id
          JOIN core.fixtures f ON f.id = p.fixture_id
          LEFT JOIN core.fixture_results r ON r.fixture_id = p.fixture_id
         WHERE p.status = 'settled' AND pr.result_status <> 'pending'""" + _SCOPE.format(a="p") + " ORDER BY p.id",
         "picks.pick_results", ("pick_id",), "result_status", "profit_units", False, settlement.RULE_VERSION, pick=True),
    Kind("daily_item", """
        SELECT i.set_id AS k1, i.rank AS k2, i.fixture_id, i.market_key, i.selection, i.line, i.odds AS price,
               1 AS stake, i.status, i.profit_units AS profit, i.settled_at, NULL AS basis, """ + _FIXTURE + """,
               """ + TAKEN_KICKOFF.format(since="i.selected_at") + """ AS taken_kickoff
          FROM picks.daily_set_items i JOIN core.fixtures f ON f.id = i.fixture_id
          LEFT JOIN core.fixture_results r ON r.fixture_id = i.fixture_id
         WHERE i.status <> 'PENDING'""" + _SCOPE.format(a="i") + " ORDER BY i.set_id, i.rank",
         "picks.daily_set_items", ("set_id", "rank"), "status", "profit_units", True, settlement.RULE_VERSION),
    Kind("parlay_leg", """
        SELECT l.parlay_id AS k1, l.leg_no AS k2, l.fixture_id, l.market_key, l.selection, l.line, l.odds AS price,
               1 AS stake, l.status, NULL::numeric AS profit, l.settled_at, NULL AS basis, """ + _FIXTURE + """,
               """ + TAKEN_KICKOFF.format(since="pp.created_at") + """ AS taken_kickoff
          FROM picks.parlay_legs l JOIN picks.parlays pp ON pp.id = l.parlay_id
          JOIN core.fixtures f ON f.id = l.fixture_id
          LEFT JOIN core.fixture_results r ON r.fixture_id = l.fixture_id
         WHERE l.status <> 'PENDING'""" + _SCOPE.format(a="l") + " ORDER BY l.parlay_id, l.leg_no",
         "picks.parlay_legs", ("parlay_id", "leg_no"), "status", None, True, settlement.RULE_VERSION),
    Kind("user_pick", """
        SELECT u.id AS k1, NULL::int AS k2, u.fixture_id, u.market_key, u.selection, u.line,
               COALESCE(u.user_odds, u.odds) AS price, 1 AS stake, u.status, u.profit_units AS profit, u.settled_at,
               NULL AS basis, """ + _FIXTURE + """,
               """ + TAKEN_KICKOFF.format(since="u.saved_at") + """ AS taken_kickoff
          FROM picks.user_picks u JOIN core.fixtures f ON f.id = u.fixture_id
          LEFT JOIN core.fixture_results r ON r.fixture_id = u.fixture_id
         WHERE u.status <> 'PENDING'""" + _SCOPE.format(a="u") + " ORDER BY u.id",
         "picks.user_picks", ("id",), "status", "profit_units", True, settlement.RULE_VERSION),
    Kind("user_parlay_leg", """
        SELECT l.user_parlay_id AS k1, l.leg_no AS k2, l.fixture_id, l.market_key, l.selection, l.line,
               l.odds AS price, 1 AS stake, l.status, NULL::numeric AS profit, l.settled_at, NULL AS basis,
               """ + _FIXTURE + """,
               """ + TAKEN_KICKOFF.format(since="up.created_at") + """ AS taken_kickoff
          FROM picks.user_parlay_legs l JOIN picks.user_parlays up ON up.id = l.user_parlay_id
          JOIN core.fixtures f ON f.id = l.fixture_id
          LEFT JOIN core.fixture_results r ON r.fixture_id = l.fixture_id
         WHERE l.status <> 'PENDING'""" + _SCOPE.format(a="l") + " ORDER BY l.user_parlay_id, l.leg_no",
         "picks.user_parlay_legs", ("user_parlay_id", "leg_no"), "status", None, True, settlement.RULE_VERSION),
)


@dataclass(frozen=True)
class ParlayKind:
    name: str
    relation: str
    legs: str
    fk: str


PARLAYS: tuple[ParlayKind, ...] = (
    ParlayKind("parlay", "picks.parlays", "picks.parlay_legs", "parlay_id"),
    ParlayKind("user_parlay", "picks.user_parlays", "picks.user_parlay_legs", "user_parlay_id"),
)


def _parlay_select(k: ParlayKind) -> str:
    return f"""
        SELECT p.id, p.status, p.profit_units AS profit, p.settled_at,
               array_agg(l.status ORDER BY l.leg_no) AS statuses, array_agg(l.odds ORDER BY l.leg_no) AS odds,
               array_agg(l.leg_no ORDER BY l.leg_no) AS leg_nos, array_agg(l.fixture_id ORDER BY l.leg_no) AS fixtures
          FROM {k.relation} p JOIN {k.legs} l ON l.{k.fk} = p.id
         WHERE p.status = ANY(%(final)s)
           AND (%(fixtures)s::bigint[] IS NULL OR EXISTS (
                SELECT 1 FROM {k.legs} x WHERE x.{k.fk} = p.id AND x.fixture_id = ANY(%(fixtures)s)))
         GROUP BY p.id ORDER BY p.id"""


def _update_single(k: Kind) -> str:
    sets = [f"{k.status_col} = %(status)s"]
    if k.profit_col:
        sets.append(f"{k.profit_col} = %(profit)s")
    if k.pick:
        sets += ["settled_by = %(by)s", "rule_version = %(rule)s",
                 "result_payload_hash = COALESCE(%(hash)s, result_payload_hash)"]
    where = " AND ".join(f"{col} = %(k{i})s" for i, col in enumerate(k.keys, start=1))
    was = f"{k.status_col} = %(was)s" + (f" AND {k.profit_col} IS NOT DISTINCT FROM %(was_profit)s"
                                        if k.profit_col else "")
    return f"UPDATE {k.relation} SET {', '.join(sets)} WHERE {where} AND {was}"


def _key(row: Row) -> str:
    return str(row["k1"]) if row["k2"] is None else f"{row['k1']}/{row['k2']}"


def revised_fixtures(conn: psycopg.Connection[Any], *, since: datetime) -> list[int]:
    """The matches whose result or status was corrected since ``since``."""
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT fixture_id FROM core.fixture_result_revisions WHERE observed_at >= %s "
                    "ORDER BY fixture_id", (since,))
        return [int(r[0]) for r in cur.fetchall()]


def latest_revisions(conn: psycopg.Connection[Any], fixtures: Sequence[int] | None) -> dict[int, Revision]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT DISTINCT ON (fixture_id) id, fixture_id, kind, old_state, new_state, changed, observed_at "
                    "FROM core.fixture_result_revisions WHERE (%(f)s::bigint[] IS NULL OR fixture_id = ANY(%(f)s)) "
                    "ORDER BY fixture_id, id DESC", {"f": None if fixtures is None else list(fixtures)})
        return {int(r["fixture_id"]): Revision(int(r["id"]), r["kind"], r["old_state"], r["new_state"],
                                               list(r["changed"]), r["observed_at"]) for r in cur.fetchall()}


STALE_SQL = {
    "intel.decision_outcomes": "SELECT count(*) FROM intel.decision_outcomes o JOIN intel.decisions d "
                               "ON d.id = o.decision_id WHERE d.fixture_id = ANY(%s)",
    "intel.postmortems": "SELECT count(*) FROM intel.postmortems WHERE fixture_id = ANY(%s)",
    "intel.match_postmortems": "SELECT count(*) FROM intel.match_postmortems WHERE fixture_id = ANY(%s)",
    "ai.pick_postmortems": "SELECT count(*) FROM ai.pick_postmortems WHERE fixture_id = ANY(%s)",
    "ai.postmortems": "SELECT count(*) FROM ai.postmortems WHERE fixture_id = ANY(%s)",
}
"""Derived, append-only records built on the result of a match: the ones plan phase F8 rebuilds."""


def _stale(conn: psycopg.Connection[Any], fixtures: list[int]) -> dict[str, int]:
    out: dict[str, int] = {}
    with conn.cursor() as cur:
        for table, sql in STALE_SQL.items():
            cur.execute(sql, (fixtures,))
            row = cur.fetchone()
            if row is not None and int(row[0]):
                out[table] = int(row[0])
    return out


# ------------------------------------------------------------------------------------------------------- the pass

def resettle(conn: psycopg.Connection[Any], *, at: datetime, run_id: int | None = None, apply: bool = True,
             fixture_ids: Sequence[int] | None = None, since: datetime | None = None, audit: bool = False,
             max_fixtures: int = MAX_FIXTURES, note: str = "") -> ResettlementReport:
    """Re-settle the records on corrected matches.

    Which matches: ``fixture_ids`` if given; else those corrected since ``since`` (by default ``RECHECK_WINDOW``
    before ``at``); ``audit`` reads every settled record instead, corrected or not (what predates revision 0080,
    parlays settled under the old formula). ``apply=False`` is a dry run: the same writes in a transaction that is
    rolled back. The caller commits. ``note`` is appended to every reason (the command line puts who ran it)."""
    report = ResettlementReport(applied=apply, audit=audit)
    with conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_xact_lock(hashtext(%s))", (LOCK,))
        got = cur.fetchone()
    if got is None or not got[0]:
        report.busy, report.applied = True, False
        return report
    fixtures: list[int] | None
    if audit:
        fixtures = None
    elif fixture_ids is not None:
        fixtures = sorted(set(fixture_ids))
    else:
        fixtures = revised_fixtures(conn, since=since if since is not None else at - RECHECK_WINDOW)
    if fixtures is not None:
        report.fixtures = fixtures
        if not fixtures:
            return report
    with conn.transaction():
        _pass(conn, report, fixtures, at=at, run_id=run_id, max_fixtures=max_fixtures, note=note)
        if report.refused is not None or not apply:
            report.applied = False
            raise psycopg.Rollback()  # the block, and with it every write above, is undone
    if report.changes or report.held or report.conflicts:
        log.info("resettlement.done", applied=report.applied, changes=len(report.changes), held=len(report.held),
                 fixtures=len(report.changed_fixtures), conflicts=report.conflicts, refused=report.refused)
    return report


def _pass(conn: psycopg.Connection[Any], report: ResettlementReport, fixtures: list[int] | None, *, at: datetime,
          run_id: int | None, max_fixtures: int, note: str) -> None:
    revisions = latest_revisions(conn, fixtures)
    suffix = f" [{note}]" if note else ""
    legs: dict[tuple[str, int], list[Change]] = {}
    for kind in SINGLES:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(kind.select, {"fixtures": fixtures})
            rows = list(cur.fetchall())
        report.examined[kind.name] = len(rows)
        for row in rows:
            fid = int(row["fixture_id"])
            price = Decimal(row["price"]) if row["price"] is not None else None
            if kind.pick:
                outcome = settlement.settle(
                    row["market_key"], row["selection"], Decimal(row["line"]), price or Decimal("2"),
                    Decimal(row["stake"]),
                    settlement.MatchState(row["status_short"], row["reg_goals_home"], row["reg_goals_away"],
                                          row["et_goals_home"], row["et_goals_away"], row["ft_goals_home"],
                                          row["ft_goals_away"], row["taken_kickoff"]), at=at)
                score_based = row["basis"] == settlement.BASIS
            else:
                outcome = settle_single(row, price, at=at)
                score_based = row["status"] != "VOID"
            verdict = judge(stored_status=row["status"], stored_profit=row["profit"], score_based=score_based,
                            outcome=outcome, priced=kind.profit_col is not None and price is not None,
                            upper=kind.upper, status_short=row["status_short"])
            if verdict.action == "same":
                continue
            if verdict.action == "held":
                report.held.append(Held(kind.name, _key(row), fid, row["status"], verdict.code, verdict.detail))
                continue
            reason, revision_id = explain(revisions.get(fid))
            change = Change(kind.name, _key(row), fid, row["status"], row["profit"], str(verdict.status),
                            verdict.profit, reason + suffix, revision_id, kind.rule_version)
            params = {"k1": row["k1"], "k2": row["k2"], "status": verdict.status, "profit": verdict.profit,
                      "was": row["status"], "was_profit": row["profit"], "by": f"worker:{kind.rule_version}:resettled",
                      "rule": kind.rule_version, "hash": row["payload_hash"]}
            if not _write(conn, report, kind, change, params, row["settled_at"], at=at, run_id=run_id):
                continue
            if kind.name in ("parlay_leg", "user_parlay_leg"):
                legs.setdefault((kind.name, int(row["k1"])), []).append(report.changes[-1])
    for pk in PARLAYS:
        _parlays(conn, report, pk, fixtures, legs, at=at, run_id=run_id, revisions=revisions, suffix=suffix)
    if len(report.changed_fixtures) > max_fixtures:
        report.refused = (f"{len(report.changed_fixtures)} matches would change result (more than {max_fixtures}): "
                          "that is not a correction, it is something upstream going wrong; nothing was written. "
                          "Look at the list; raise --max-fixtures only if every one is expected")
        return
    if report.changes:
        report.stale = _stale(conn, report.changed_fixtures)


def _write(conn: psycopg.Connection[Any], report: ResettlementReport, kind: Kind, change: Change,
           params: dict[str, Any], was_settled_at: datetime | None, *, at: datetime, run_id: int | None) -> bool:
    """The guarded UPDATE of one record and its trail. False (a conflict) when the record is no longer as it was read."""
    with conn.cursor() as cur:
        cur.execute(_update_single(kind), params)
        if cur.rowcount == 0:
            report.conflicts += 1
            return False
        _trail(cur, change, was_settled_at, at=at, run_id=run_id)
        if kind.pick:
            cur.execute("INSERT INTO picks.pick_events (pick_id, from_status, to_status, at, reason, run_id, "
                        "event_kind) VALUES (%s, 'settled', 'settled', %s, %s, %s, 'resettlement')",
                        (params["k1"], at, f"{change.from_status} -> {change.to_status}: {change.reason}", run_id))
    report.changes.append(change)
    return True


def _trail(cur: psycopg.Cursor[Any], c: Change, was_settled_at: datetime | None, *, at: datetime,
           run_id: int | None) -> None:
    cur.execute("INSERT INTO picks.resettlements (at, record_kind, record_key, fixture_id, revision_id, from_status, "
                "from_profit, from_settled_at, to_status, to_profit, rule_version, reason, run_id) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (at, c.kind, c.key, c.fixture_id, c.revision_id, c.from_status, c.from_profit, was_settled_at,
                 c.to_status, c.to_profit, c.rule_version, c.reason, run_id))


def _parlays(conn: psycopg.Connection[Any], report: ResettlementReport, pk: ParlayKind, fixtures: list[int] | None,
             legs: dict[tuple[str, int], list[Change]], *, at: datetime, run_id: int | None,
             revisions: dict[int, Revision], suffix: str) -> None:
    """A parlay follows its legs: decide it again from the legs as they now stand (the legs were written above)."""
    leg_kind = "parlay_leg" if pk.name == "parlay" else "user_parlay_leg"
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_parlay_select(pk), {"fixtures": fixtures, "final": list(FINAL_PARLAY)})
        rows = list(cur.fetchall())
    report.examined[pk.name] = len(rows)
    for row in rows:
        pairs = [(str(s), Decimal(o) if o is not None else None) for s, o in zip(row["statuses"], row["odds"],
                                                                                 strict=True)]
        outcome = parlay_outcome(pairs)
        stored = (row["status"], row["profit"])
        moved = legs.get((leg_kind, int(row["id"])), [])
        fid = int(moved[0].fixture_id) if moved and moved[0].fixture_id is not None else int(row["fixtures"][0])
        if outcome is None:
            if all(s in FINAL_LEG for s, _ in pairs):
                report.held.append(Held(pk.name, str(row["id"]), fid, row["status"], "profit_unknown",
                                        "every leg is settled but the profit cannot be known (a half loss and a leg "
                                        "with no price); it is never guessed"))
                continue
            target: tuple[str, Decimal | None, bool] = ("ACTIVE", None, True)  # un-settled: a leg no longer decides it
        else:
            target = (outcome[0], outcome[1], False)
        if (target[0], target[1]) == stored:
            continue
        if moved:
            why = "; ".join(f"leg {m.key.split('/')[-1]}: {m.from_status} -> {m.to_status}" for m in moved)
            reason, revision_id = explain(revisions.get(fid))
            reason = f"{why} - {reason}"
        else:
            reason, revision_id = (f"audit: its settled legs decide it {target[0]} under {PARLAY_RULE_VERSION}, "
                                   f"not {row['status']}", None)
        change = Change(pk.name, str(row["id"]), fid, row["status"], row["profit"], target[0], target[1],
                        reason + suffix, revision_id, PARLAY_RULE_VERSION)
        with conn.cursor() as cur:
            cur.execute(f"UPDATE {pk.relation} SET status = %s, profit_units = %s, settled_at = %s WHERE id = %s "
                        "AND status = %s AND profit_units IS NOT DISTINCT FROM %s",
                        (target[0], target[1], None if target[2] else row["settled_at"], row["id"], row["status"],
                         row["profit"]))
            if cur.rowcount == 0:
                report.conflicts += 1
                continue
            _trail(cur, change, row["settled_at"], at=at, run_id=run_id)
        report.changes.append(change)
