"""The private evaluation of corners and cards (IA-096, plan piece AD-E03): the cycle of states of the selections that the admission lets
in, and only of those. SHADOW, OFF by default (``FBI_COUNT_EVAL``); nothing reaches a reader or a published pick.

One pass (``run_pass``):

1. the matches with a decision of the families (``decision-fam-v1``) whose kick-off is in ``[now - back, now + ahead)`` - the same read
   as the shadow writer of the cycle (``fbi.lifecycle.store``);
2. of their selections, those of the six markets of the counts (``fbi.countcal.calibrator.FAMILY_OF_KEY``);
3. for each one, the admission (``fbi.countcal.admission``): the family's settlement rule, a VALIDADO calibrator signed by the owner
   (``fbi.countcal.store.champions``) and the complete books quoting its line at the moment (the last price of each book at or before
   ``min(now, kick-off - 10 min)``, as ``fbi.families.versus`` counts them);
4. an admitted selection gets its chain - the same chain the cycle derives from the layer (``fbi.lifecycle.derive``) - appended under the
   writer ``count-eval-v1``; a selection whose chain already started keeps being followed to its end. The rest are counted by reason and
   nothing is written for them.

Today no calibrator is signed, so the pass admits nothing: its report says why each selection stays out. ``dry_run`` reads the same
and writes nothing (it works before the tables exist). Writes only ``intel.selection_lifecycle``, append-only.
"""

from __future__ import annotations

import os
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.core.decision_versions import DECISION_FAMILIES
from fbi.countcal import admission, store
from fbi.countcal import calibrator as cc
from fbi.countcal.walkforward import VALIDATED
from fbi.families import versus
from fbi.lifecycle import derive, machine
from fbi.lifecycle import store as lstore
from fbi.lifecycle.derive import Fixture, Key, Row

SWITCH: Final = "FBI_COUNT_EVAL"
WRITER: Final = admission.WRITER
LAYER: Final = DECISION_FAMILIES
BACK: Final = lstore.BACK
AHEAD: Final = lstore.AHEAD
CHUNK: Final = 100
LOCK: Final = 0x1A096
TIMEOUT_MS: Final = 60_000
PRICE_WINDOW: Final = timedelta(days=10)
KEYS: Final = tuple(cc.FAMILY_OF_KEY)


def mode() -> str:
    """``shadow`` writes; any other word (``off``, the default) is off."""
    return "shadow" if os.environ.get(SWITCH, "off").strip().lower() == "shadow" else "off"


BOOKS_SQL: Final = """
SELECT DISTINCT ON (q.fixture_id, q.bookmaker_id, q.definition_id, q.selection, q.line)
       q.fixture_id, q.bookmaker_id, d.market_key, d.kind, q.selection, q.line, q.odds_decimal
  FROM unnest(%(fixtures)s::bigint[], %(ats)s::timestamptz[]) AS x(fixture_id, at)
  JOIN market.odds_quotes q ON q.fixture_id = x.fixture_id
  JOIN market.market_definitions d ON d.id = q.definition_id
 WHERE d.scope = 'prematch' AND d.kind = 'over_under' AND d.market_key = ANY(%(keys)s::text[])
   AND q.captured_at <= x.at AND q.captured_at >= x.at - %(window)s::interval
 ORDER BY q.fixture_id, q.bookmaker_id, q.definition_id, q.selection, q.line, q.captured_at DESC
"""
"""The last price of each selection at each book at the moment of each match: a price counts from its capture until the next one."""


def _fetch(conn: psycopg.Connection[Any], sql: str, params: Mapping[str, Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def books(conn: psycopg.Connection[Any], moments: Mapping[int, datetime]) -> dict[tuple[int, str, Decimal], int]:
    """How many complete books quote each (match, market key, line) of the counts at the match's moment."""
    if not moments:
        return {}
    ids = sorted(moments)
    rows = _fetch(conn, BOOKS_SQL, {"fixtures": ids, "ats": [moments[i] for i in ids], "keys": list(KEYS), "window": PRICE_WINDOW})
    quotes = [versus.Quote("at", int(r["fixture_id"]), int(r["bookmaker_id"]), str(r["market_key"]), str(r["kind"]), str(r["selection"]),
                           Decimal(r["line"]), float(r["odds_decimal"])) for r in rows]
    out: Counter[tuple[int, str, Decimal]] = Counter()
    for b in versus.complete_books(quotes):
        out[(b.fixture_id, b.key, b.line.quantize(derive.LINE_Q))] += 1
    return dict(out)


@dataclass
class PassReport:
    fixtures: int = 0
    selections: int = 0
    admitted: int = 0
    followed: int = 0
    """Selections admitted earlier whose chain is followed although today they would not be admitted."""
    by_reason: Counter[str] = field(default_factory=Counter)
    by_family: Counter[str] = field(default_factory=Counter)
    appended: int = 0
    unchanged: int = 0
    divergent: int = 0
    illegal: int = 0
    champions: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        return {"fixtures": self.fixtures, "selections": self.selections, "admitted": self.admitted, "followed": self.followed,
                "by_reason": dict(sorted(self.by_reason.items())), "by_family": dict(sorted(self.by_family.items())),
                "appended": self.appended, "unchanged": self.unchanged, "divergent": self.divergent, "illegal": self.illegal,
                "champions": self.champions, "errors": self.errors[:20]}


def _exists(conn: psycopg.Connection[Any], table: str) -> bool:
    row = conn.execute("SELECT to_regclass(%s) IS NOT NULL", (table,)).fetchone()
    return bool(row and row[0])


def _chunks(xs: Sequence[int], n: int) -> Iterable[list[int]]:
    for i in range(0, len(xs), n):
        yield list(xs[i:i + n])


def _insert(conn: psycopg.Connection[Any], *, key: Key, row: Row, previous_id: int | None, from_state: str | None) -> int:
    s = row.step
    got = conn.execute(lstore.INSERT_SQL, {
        "chain_key": lstore.chain_key(WRITER, key), "writer": WRITER, "fixture_id": key.fixture_id, "market_key": key.market_key,
        "selection": key.selection, "line": key.line, "layer": row.layer, "previous_id": previous_id, "from_state": from_state,
        "state": s.state, "reason": s.reason, "actor": s.actor, "owner_signature": s.owner_signature, "evaluation": s.evaluation,
        "evaluation_version": s.evaluation_version, "settlement_result": s.settlement_result, "known_at": row.known_at,
        "source": row.source, "source_id": row.source_id, "machine_version": machine.VERSION,
        "map_version": derive.MAP_VERSION}).fetchone()
    assert got is not None
    return int(got[0])


def run_pass(conn: psycopg.Connection[Any], *, now: datetime, dry_run: bool = True, back: timedelta = BACK, ahead: timedelta = AHEAD,
             chunk: int = CHUNK) -> PassReport:
    """One pass. ``dry_run`` (the default) reads and writes nothing; a write needs ``FBI_COUNT_EVAL=shadow`` and revisions 0142 and 0152."""
    rep = PassReport()
    have_cycle = _exists(conn, "intel.selection_lifecycle")
    have_cal = _exists(conn, "intel.count_calibrators")
    if not dry_run:
        if mode() != "shadow":
            raise RuntimeError(f"{SWITCH} is not shadow: the private evaluation writes nothing")
        if not (have_cycle and have_cal):
            raise RuntimeError("intel.selection_lifecycle or intel.count_calibrators does not exist: apply revisions 0142 and 0152")
        got = conn.execute("SELECT pg_try_advisory_lock(%s)", (LOCK,)).fetchone()
        if not got or not got[0]:
            rep.errors.append("another pass holds the lock")
            conn.rollback()
            return rep
    try:
        conn.execute(f"SET statement_timeout = {TIMEOUT_MS}")
        champs = store.champions(conn, at=now) if have_cal else {}
        validated = {f for f, v in (store.latest_verdicts(conn, at=now) if have_cal else {}).items() if v == VALIDATED}
        rep.champions = {f: s.id for f, s in champs.items()}
        fixtures = {int(r["id"]): Fixture(int(r["id"]), r["kickoff_at"], r["status_short"], r["status_group"])
                    for r in _fetch(conn, lstore.FIXTURES_SQL, {"start": now - back, "end": now + ahead, "layers": [LAYER]})}
        rep.fixtures = len(fixtures)
        for ids in _chunks(sorted(fixtures), chunk):
            try:
                _one_chunk(conn, ids, fixtures, now=now, dry_run=dry_run, have_cycle=have_cycle, champs=champs,
                           validated=validated | set(champs), rep=rep)
                if dry_run:
                    conn.rollback()
                else:
                    conn.commit()
            except psycopg.Error as exc:
                conn.rollback()
                rep.errors.append(f"{ids[0]}..{ids[-1]}: {type(exc).__name__}: {exc}"[:300])
    finally:
        if not dry_run:
            conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK,))
            conn.commit()
    return rep


def _one_chunk(conn: psycopg.Connection[Any], ids: list[int], fixtures: Mapping[int, Fixture], *, now: datetime, dry_run: bool,
               have_cycle: bool, champs: Mapping[str, store.Stored], validated: set[str], rep: PassReport) -> None:
    hists = {k: h for k, h in lstore.histories(conn, ids, layers=[LAYER]).items() if k.market_key in cc.FAMILY_OF_KEY}
    if not hists:
        return
    moments = {i: min(now, fixtures[i].kickoff_at - derive.LAST_WORD) for i in {k.fixture_id for k in hists}}
    priced = books(conn, moments)
    stored: dict[str, list[dict[str, Any]]] = {}
    if have_cycle:
        for r in _fetch(conn, lstore.STORED_SQL, {"fixtures": ids, "writer": WRITER}):
            stored.setdefault(str(r["chain_key"]), []).append(r)
    for key, hist in sorted(hists.items(), key=lambda kv: (kv[0].fixture_id, kv[0].market_key, kv[0].selection, kv[0].line)):
        rep.selections += 1
        family = admission.family_of(key.market_key) or ""
        rep.by_family[family] += 1
        verdict = admission.admit(admission.Facts(key.market_key, key.line, priced.get((key.fixture_id, key.market_key, key.line), 0),
                                                  validated=family in validated, signed=family in champs))
        rep.by_reason[verdict.reason] += 1
        have = stored.get(lstore.chain_key(WRITER, key), [])
        if not verdict.admitted and not have:
            continue
        rep.admitted += int(verdict.admitted)
        rep.followed += int(not verdict.admitted)
        try:
            chain = derive.derive(hist, fixtures[key.fixture_id], now=now)
        except machine.IllegalTransitionError as exc:
            rep.illegal += 1
            rep.errors.append(f"{lstore.chain_key(WRITER, key)}: {exc}"[:300])
            continue
        kept = [lstore.Stored(int(s["id"]), str(s["state"]), str(s["reason"]), str(s["source"]),
                              None if s["source_id"] is None else int(s["source_id"])) for s in have]
        plan, rest = lstore.plan(kept, chain)
        if plan == "divergent":
            rep.divergent += 1
            continue
        if plan == "unchanged":
            rep.unchanged += 1
            continue
        previous_id = kept[-1].id if kept else None
        from_state = kept[-1].state if kept else None
        for step_row in rest:
            rep.appended += 1
            if not dry_run:
                previous_id = _insert(conn, key=key, row=step_row, previous_id=previous_id, from_state=from_state)
            from_state = step_row.step.state
