"""The ONE post-mortem (plan F8, ``pm-v6``, ``fbi.intel.postmortem``) on a built world: a selection that the picks, the AI and the decision layer
all priced is studied ONCE, whoever looked at it, with the three prices kept and the one taken named; what only one of them looked at is
studied as well; a match three hours old is studied, a half day of INVESTIGACION is not ranked; a run writes each selection once, never
commits the caller's transaction and loses only the selection that fails.

The world is ``test_daily_records.World`` (six matches on 1 Aug 2032 in Bogotá, one the next day: F1 at +2 h of AT = 12:00 UTC, ..., F6 at +13 h)
plus what the post-mortem reads, one scenario per selection:

    A  F1 1X2 Home        a pick of the day, a CAUTELA decision and an approved review, each with its own price; it LOST (0-2)
    B  F3 1X2 Home        a pick of the day and an approved review; it WON (2-0)
    C  F4 OU Over 2.5     a CAUTELA decision only; it lost (0-1)
    D  F2 1X2 Away        a rejected review of a match the AI worked on (it had a pass); it would have WON (0-1)
    H  F4 1X2 Home        a pick of the day whose price was already stale when it was taken; it lost
    F  F6 OU Over 1.0     an approved decision on a line that pushes (1-0)
    I  F5 OU x.5          22 INVESTIGACION decisions, scored 1..22 (the twenty best are studied, once their Bogotá day is over)

The transaction is rolled back afterwards."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from psycopg.errors import UniqueViolation
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fbi.ai import memory as ai_memory
from fbi.intel import pm_facts, postmortem
from fbi.market import closing_reference

from .conftest import Seed
from .helpers import scalar
from .test_daily_records import AT, World

pytestmark = pytest.mark.integration

EARLY = datetime(2032, 8, 2, 3, 59, tzinfo=UTC)
"""F6 (01:00 UTC) is not three hours old yet and the Bogotá day of 1 Aug is not over."""
LATE = datetime(2032, 8, 2, 12, 0, tzinfo=UTC)
"""Every match of the 1st is old enough and the day is over (07:00 of the 2nd in Bogotá)."""
RESULTS = {"F1": (0, 2), "F2": (0, 1), "F3": (2, 0), "F4": (0, 1), "F5": (1, 1), "F6": (1, 0)}
ZERO = Decimal("0")

Key = tuple[int, str, str, Decimal]


class Pm:
    """The world of the daily records, finished, and the scenarios above."""

    def __init__(self, db: psycopg.Connection[Any], seed: Seed, *, results: dict[str, tuple[int, int]] | None = None,
                 investigation: bool = True, scenarios: bool = True) -> None:
        self.db, self.seed = db, seed
        self.w = World(db, seed)
        self.f = self.w.fixtures
        self.cur = db.cursor()
        self.book = seed.bookmaker_id
        self.cur.execute("INSERT INTO market.bookmakers (provider_bookmaker_id, name) VALUES (9, 'Other') RETURNING id")
        self.other = int(scalar(self.cur))
        for name, (home, away) in (RESULTS if results is None else results).items():
            self.w.result(name, home, away)
        self.decisions: dict[str, int] = {}
        if scenarios:
            self._scenarios(investigation)

    # ── the building blocks ────────────────────────────────────────────────

    def kickoff(self, name: str) -> datetime:
        got = scalar(self.db.execute("SELECT kickoff_at FROM core.fixtures WHERE id = %s", (self.f[name],)))
        assert isinstance(got, datetime)
        return got

    def key(self, name: str, market: str = "1X2", selection: str = "Home", line: str = "0") -> Key:
        return self.f[name], market, selection, Decimal(line)

    def consensus(self, name: str, market: str, selection: str, line: str, p_fair: str, minutes_before: int = 175, *,
                  method: str = "shin") -> None:
        """A consensus snapshot ``minutes_before`` kick-off (a negative number: after it)."""
        self.cur.execute("INSERT INTO market.market_consensus (fixture_id,market_key,selection,line,as_of,devig_method,p_fair,n_bookmakers,"
                         "overround,best_odds,best_bookmaker_id) VALUES (%s,%s,%s,%s,%s,%s,%s,5,0.05,2.0,%s)",
                         (self.f[name], market, selection, line, self.kickoff(name) - timedelta(minutes=minutes_before), method, p_fair,
                          self.book))

    def book_close(self, name: str, book: int, market: str, selection: str, line: str, odds: str, minutes_to_ko: int = 20) -> None:
        ko = self.kickoff(name)
        self.cur.execute("INSERT INTO market.final_prematch_odds (fixture_id,bookmaker_id,market_key,selection,line,odds_decimal,"
                         "provider_update_at,minutes_to_ko,fetched_at,payload_hash) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                         (self.f[name], book, market, selection, line, odds, ko - timedelta(minutes=minutes_to_ko), minutes_to_ko,
                          ko + timedelta(hours=1), self.seed.payload_hash))

    def packet(self, name: str, *, absences: dict[str, Any] | None = None, quality: dict[str, Any] | None = None) -> int:
        n = int(scalar(self.db.execute("SELECT count(*) FROM ai.match_packets"))) + 1
        self.cur.execute("INSERT INTO ai.match_packets (fixture_id, packet_version, as_of, built_at, packet_hash, content) "
                         "VALUES (%s,'packet-v1',%s,%s,%s,%s) RETURNING id",
                         (self.f[name], AT, AT, f"{n:064x}", Jsonb({"quality": quality or {}, "absences": absences or {}})))
        return int(scalar(self.cur))

    def review(self, name: str, market: str, selection: str, line: str, *, decision: str = "APPROVE", odds: str | None = None,
               book: int | None = None, p_model: str | None = None, p_market: str | None = None, packet: int | None = None,
               output: dict[str, Any] | None = None, at: datetime | None = None) -> int:
        self.cur.execute(
            "INSERT INTO ai.pick_reviews (reviewed_at, fixture_id, market_key, selection, line, odds, bookmaker_id, p_model, p_market, "
            "engine, engine_version, packet_id, input_hash, decision, confidence, output, mode, status) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,"
            "'combined','rules-review-v1+none',%s,'h',%s,0.6,%s,'shadow','ok') RETURNING id",
            (at or AT + timedelta(minutes=10), self.f[name], market, selection, line, odds, book, p_model, p_market, packet, decision,
             Jsonb(output or {})))
        return int(scalar(self.cur))

    def decide(self, name: str, market: str, selection: str, line: str, *, state: str = "CAUTELA", odds: str = "2.05",
               book: int | None = None, p_model: str = "0.50", p_cal: str | None = "0.48", p_market: str = "0.45", score: int = 60,
               review_id: int | None = None, known_at: datetime | None = None, pick: str | None = None) -> int:
        ko = self.kickoff(name)
        known = known_at or ko - timedelta(hours=1)
        self.cur.execute(
            "INSERT INTO intel.decisions (decision_version, known_at, checkpoint, fixture_id, kickoff_at, market_key, selection, line, "
            "model_name, bookmaker_id, odds, price_at, p_model, p_cal, p_market, filters, state, context_status, input_hash, score, "
            "review_id, pick_id) VALUES ('decision-v1',%s,'T-3h',%s,%s,%s,%s,%s,'dixon_coles',%s,%s,%s,%s,%s,%s,%s,%s,'PARTIAL',%s,%s,%s,%s) "
            "RETURNING id",
            (known, self.f[name], ko, market, selection, line, book or self.book, odds, known - timedelta(minutes=10), p_model, p_cal,
             p_market, Jsonb([]), state, f"pm6-{name}-{market}-{selection}-{line}", score, review_id,
             None if pick is None else self.w.picks[pick]))
        decision = int(scalar(self.cur))
        self.decisions[f"{name}:{market}:{selection}:{line}"] = decision
        return decision

    def settle(self, decision: int, status: str, clv: str, name: str) -> None:
        ko = self.kickoff(name)
        self.cur.execute("INSERT INTO intel.decision_outcomes (decision_id, settled_at, result_status, profit_flat, profit_staked, "
                         "close_p_fair, close_odds, close_as_of, clv, version, computed_at) VALUES (%s,%s,%s,1.1,0,0.46,2.0,%s,%s,"
                         "'outcome-v1',%s)", (decision, ko + timedelta(hours=4), status, ko - timedelta(hours=1), clv, ko + timedelta(hours=5)))

    def item(self, name: str, *, odds: str, price_at: datetime, selected_at: datetime, source: str = "qualified", rank: int = 1,
             p_model: str = "0.55", p_market: str = "0.46") -> None:
        self.cur.execute("INSERT INTO picks.daily_sets (day, timezone, source, rule_version, status, created_at, updated_at) VALUES "
                         "(%s,'America/Bogota',%s,'daily-set-v5','COMPLETE',%s,%s) ON CONFLICT (day, source) DO UPDATE SET "
                         "updated_at = excluded.updated_at RETURNING id", (AT.date(), source, AT, AT))
        set_id = int(scalar(self.cur))
        self.cur.execute("INSERT INTO picks.daily_set_items (set_id, rank, pick_id, fixture_id, market_key, selection, line, stage, "
                         "selected_at, odds, bookmaker_id, price_at, p_model, p_low, p_push, p_market, ev, model_version_id, inputs) VALUES "
                         "(%s,%s,%s,%s,'1X2','Home',0,'T-3h',%s,%s,%s,%s,%s,0.5,0,%s,0.1,%s,%s)",
                         (set_id, rank, self.w.picks[name], self.f[name], selected_at, odds, self.book, price_at, p_model, p_market,
                          self.seed.model_version_id, Jsonb({})))

    # ── the scenarios ──────────────────────────────────────────────────────

    def _scenarios(self, investigation: bool) -> None:
        w = self.w
        # A: three parts, three prices (an item at 2.30 of the bookmaker, a decision at 2.25 and a review at 2.20 of the other one)
        self.item("F1", odds="2.30", price_at=AT - timedelta(minutes=30), selected_at=AT)
        packet = self.packet("F1", absences={"home": {"players": [{"key": True, "name": "Nine", "type": "Missing Fixture"}]}})
        review = self.review("F1", "1X2", "Home", "0", odds="2.20", book=self.other, p_model="0.52", p_market="0.47", packet=packet)
        decision = self.decide("F1", "1X2", "Home", "0", odds="2.25", book=self.other, p_cal="0.48", p_market="0.45", score=61,
                               review_id=review, known_at=AT + timedelta(minutes=30))
        self.settle(decision, "loss", "-0.011", "F1")
        self.book_close("F1", self.book, "1X2", "Home", "0", "2.00")
        # B: a pick of the day and an approved review; won
        self.item("F3", odds="2.10", price_at=AT - timedelta(minutes=30), selected_at=AT, rank=2)
        self.review("F3", "1X2", "Home", "0", odds="2.05", book=self.book, p_model="0.54", p_market="0.47")
        # C: a decision only (no pick, no review, the match had no pass of the AI); it lost, and the decision layer settled it a win
        decision_c = self.decide("F4", "OU", "Over", "2.5", odds="1.95", book=self.book, p_model="0.52", p_cal="0.48", p_market="0.45",
                                 score=55)
        self.consensus("F4", "OU", "Over", "2.5", "0.50")
        self.settle(decision_c, "win", "0.05", "F4")
        # D: a rejected review of a match the AI worked on
        self.review("F2", "1X2", "Away", "0", decision="REJECT", odds="3.30", book=self.book, p_model="0.30", p_market="0.29")
        w.day_pass("F2", at=AT)
        # H: a pick of the day whose price was five and a half hours old when it was taken
        self.item("F4", odds="2.40", price_at=AT - timedelta(hours=6), selected_at=AT - timedelta(minutes=30), source="evaluation")
        # F: an approved decision on a line that pushes
        self.decide("F6", "OU", "Over", "1.0", state="APROBADO", odds="1.85", book=self.book, p_cal="0.52", score=70)
        # I: the INVESTIGACION decisions of the last match of the day 1st (Bogotá), scored 1..22
        if investigation:
            n = 0
            for tenths in range(1, 22, 2):
                for selection in ("Over", "Under"):
                    n += 1
                    self.decide("F5", "OU", selection, f"{tenths / 2:.1f}", state="INVESTIGACION", odds="1.90", score=n)

    # ── what the tests read ────────────────────────────────────────────────

    def row(self, name: str, market: str = "1X2", selection: str = "Home", line: str = "0") -> dict[str, Any]:
        with self.db.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT * FROM intel.postmortems WHERE fixture_id = %s AND market_key = %s AND selection = %s AND line = %s "
                        "AND version = %s", (self.f[name], market, selection, line, postmortem.VERSION))
            got = cur.fetchone()
        assert got is not None, f"no post-mortem of {name} {market} {selection} {line}"
        return dict(got)

    def count(self, where: str = "true") -> int:
        return int(scalar(self.db.execute(f"SELECT count(*) FROM intel.postmortems WHERE market_key IS NOT NULL AND {where}")))


def events(db: psycopg.Connection[Any]) -> list[str]:
    return sorted(str(r[0]) for r in db.execute("SELECT dedup_key FROM ai.memory_events WHERE kind = 'pick_postmortem'").fetchall())


# ── one row per selection, whoever looked at it ─────────────────────────────

def test_a_selection_three_parts_priced_is_studied_once_with_the_price_a_person_saw_and_the_other_two_beside_it(
        db: psycopg.Connection[Any], seed: Seed) -> None:
    pm = Pm(db, seed)
    report = postmortem.study(db, at=EARLY)
    assert report.errors == [] and report.candidates == 5 and report.studied == 5, "A, B, C, D and H: F6 is not three hours old yet"
    a = pm.row("F1")
    assert a["roles"] == ["daily_pick", "decision", "reviewed"], "why it was studied: every part that looked at it"
    assert a["decision_id"] == pm.decisions["F1:1X2:Home:0"] and a["review_id"] is not None
    assert (a["odds"], a["evidence"]["price_from"]) == (Decimal("2.300"), "item"), "the price a PERSON was shown comes first"
    prices = a["evidence"]["prices"]
    assert {k: v["odds"] for k, v in prices.items()} == {"item": 2.3, "decision": 2.25, "review": 2.2}
    assert (prices["item"]["bookmaker_id"], prices["decision"]["bookmaker_id"]) == (pm.book, pm.other)
    assert (a["p_model"], a["p_market"], a["p_close"]) == (Decimal("0.550000"), Decimal("0.460000"), Decimal("0.430000")), \
        "the probability is read from the same part as the price"
    # the close: the last Shin consensus before kick-off (150 minutes before it, so far), and the SAME book's last price
    assert a["evidence"]["close"]["reference"] == closing_reference.REFERENCE
    assert (a["evidence"]["close"]["minutes_to_ko"], a["evidence"]["close"]["far"]) == (150, True)
    assert a["evidence"]["same_book_close"] == {"odds": 2.0, "minutes_to_ko": 20}
    assert (a["close_odds"], a["price_move"], a["clv"]) == (Decimal("2.000"), Decimal("0.1500"), Decimal("-0.0110")), \
        "two numbers, two names: the price move 2.30 / 2.00 and the CLV 2.30 x 0.43 - 1"
    assert (a["decision_quality"], a["verdict"], a["outcome"]) == ("BAD", "ERROR", "lost"), "lost at a price worse than the close"
    assert a["review_decision"] == "APPROVE" and a["review_verdict"] == "approved_lost"
    assert a["loss_class"] == "CONTEXT_ERROR", "a known key absence on the chosen side, approved anyway"
    assert a["answers"]["key_absence"]["answer"] == "sí" and "Nine (local)" in a["answers"]["key_absence"]["detail"]
    assert a["answers"]["suerte_o_decision"] == "ERROR" and set(a["answers"]) >= {"expected", "variance", "precio", "aprendizaje"}
    assert a["evidence"]["decision_outcome"] == {"result": "loss", "clv": -0.011, "agrees": True}


def test_a_selection_only_the_ai_looked_at_and_one_only_the_decision_layer_judged_are_studied_too(
        db: psycopg.Connection[Any], seed: Seed) -> None:
    pm = Pm(db, seed)
    report = postmortem.study(db, at=EARLY)
    assert report.by_source == {"both": 1, "ai": 3, "decision": 1}
    b = pm.row("F3")
    assert (b["roles"], b["decision_id"], b["evidence"]["price_from"], b["odds"]) == (["daily_pick", "reviewed"], None, "item", Decimal("2.100"))
    assert (b["outcome"], b["review_verdict"], b["loss_class"], b["verdict"]) == ("won", "approved_won", None, "SUERTE"), \
        "a win at a price worse than the close is luck, and a win has no class"
    assert b["close_odds"] is None and b["price_move"] is None, "no last price of that bookmaker was read: it is not invented"
    c = pm.row("F4", "OU", "Over", "2.5")
    assert (c["roles"], c["decision_id"], c["review_id"]) == (["decision"], pm.decisions["F4:OU:Over:2.5"], None)
    assert (c["evidence"]["price_from"], c["odds"], c["p_model"], c["outcome"]) == ("decision", Decimal("1.950"), Decimal("0.480000"), "lost"), \
        "the probability of a decision is the calibrated one"
    assert (c["loss_class"], c["decision_quality"], c["verdict"]) == ("NORMAL_VARIANCE", "BAD", "ERROR")
    d = pm.row("F2", "1X2", "Away")
    assert (d["roles"], d["decision_id"], d["evidence"]["price_from"]) == (["rejected", "reviewed"], None, "review"), \
        "a rejected selection of a match the AI worked on teaches as much as an approved one"
    assert (d["outcome"], d["review_verdict"], d["review_decision"], d["loss_class"]) == ("won", "rejected_would_have_won", "REJECT", None)
    h = pm.row("F4")
    assert (h["roles"], h["loss_class"]) == (["daily_pick"], "EXECUTION_ERROR"), "a price older than three hours when it was taken"
    assert h["answers"]["expected"]["data"]["odds"] == 2.4


def test_only_what_the_ai_studied_leaves_the_event_its_patterns_count(db: psycopg.Connection[Any], seed: Seed) -> None:
    pm = Pm(db, seed)
    report = postmortem.study(db, at=EARLY)
    f = pm.f
    assert events(db) == sorted([f"pm2:{f['F1']}:1X2:Home:0.00", f"pm2:{f['F3']}:1X2:Home:0.00", f"pm2:{f['F2']}:1X2:Away:0.00",
                                 f"pm2:{f['F4']}:1X2:Home:0.00"]), "the same key as the pick post-mortem of the AI: a selection is not counted twice"
    assert report.memory_events == 4, "the decision-only selection (C) leaves none: patterns are the AI's"
    event = db.execute("SELECT version, result, evidence FROM ai.memory_events WHERE dedup_key = %s", (f"pm2:{f['F1']}:1X2:Home:0.00",)).fetchone()
    assert event is not None and event[0] == postmortem.VERSION and event[1] == "CONTEXT_ERROR"
    assert event[2]["verdict"] == "approved_lost" and event[2]["postmortem_id"] == pm.row("F1")["id"] and event[2]["clv_v1"] == -0.011


# ── once, and without touching the caller's transaction ─────────────────────

def test_a_run_that_finds_everything_written_writes_nothing_and_the_unique_index_holds_the_line(db: psycopg.Connection[Any],
                                                                                                seed: Seed) -> None:
    pm = Pm(db, seed)
    first = postmortem.study(db, at=EARLY)
    assert first.studied == 5 and pm.count() == 5
    again = postmortem.study(db, at=EARLY)
    assert (again.studied, again.done, again.candidates, again.memory_events) == (0, 5, 5, 0)
    assert pm.count() == 5 and len(events(db)) == 4
    a = pm.row("F1")
    with pytest.raises(UniqueViolation), db.transaction():
        db.execute("INSERT INTO intel.postmortems (fixture_id, created_at, version, outcome, decision_quality, verdict, answers, "
                   "market_key, selection, line, roles) VALUES (%s, %s, %s, 'lost', 'BAD', 'ERROR', '{}', '1X2', 'Home', 0, '{}')",
                   (a["fixture_id"], EARLY, postmortem.VERSION))
    assert pm.count() == 5


def test_the_post_mortem_never_commits_the_callers_transaction(db: psycopg.Connection[Any], seed: Seed) -> None:
    pm = Pm(db, seed)
    db.execute("SAVEPOINT before_the_study")
    assert postmortem.study(db, at=EARLY).studied == 5
    db.execute("ROLLBACK TO SAVEPOINT before_the_study")  # it would not exist any more if the study had committed
    assert pm.count() == 0 and events(db) == []


# ── a failure loses the selection that failed, nothing else ─────────────────

def test_a_selection_whose_facts_cannot_be_built_is_reported_and_the_others_are_written(db: psycopg.Connection[Any], seed: Seed,
                                                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    pm = Pm(db, seed)
    real = pm_facts.build_facts
    b = pm.key("F3")

    def broken(c: Any, **kw: Any) -> Any:
        if c.key == b:
            raise RuntimeError("the facts of this one cannot be built")
        return real(c, **kw)

    monkeypatch.setattr(postmortem, "build_facts", broken)
    report = postmortem.study(db, at=EARLY)
    assert report.studied == 4 and len(report.errors) == 1 and "RuntimeError" in report.errors[0] and report.errors[0].startswith(f"{b[0]}:")
    assert pm.count() == 4
    monkeypatch.setattr(postmortem, "build_facts", real)
    assert postmortem.study(db, at=EARLY).studied == 1, "the next run writes the one that failed"
    assert pm.count() == 5


def test_a_selection_is_written_with_its_memory_event_or_not_at_all(db: psycopg.Connection[Any], seed: Seed,
                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    pm = Pm(db, seed)
    real = ai_memory.remember
    b = pm.f["F3"]

    def broken(conn: Any, **kw: Any) -> bool:
        if kw["fixture_id"] == b:
            raise psycopg.errors.DataError("the memory refused it")
        return bool(real(conn, **kw))

    monkeypatch.setattr(postmortem, "remember", broken)
    report = postmortem.study(db, at=EARLY)
    assert report.studied == 4 and len(report.errors) == 1 and "DataError" in report.errors[0]
    assert pm.count(f"fixture_id = {b}") == 0, "the row written before the failure went with its savepoint"
    assert pm.count() == 4, "and the rows before and after it are there: the transaction is usable"
    monkeypatch.setattr(postmortem, "remember", real)
    assert postmortem.study(db, at=EARLY).studied == 1 and pm.count() == 5


# ── which selections wait ───────────────────────────────────────────────────

def test_a_match_is_studied_three_hours_after_kickoff_and_not_before(db: psycopg.Connection[Any], seed: Seed) -> None:
    pm = Pm(db, seed, investigation=False)
    ko = pm.kickoff("F6")
    before = postmortem.study(db, at=ko + timedelta(hours=2, minutes=59))
    assert (before.candidates, before.studied) == (5, 5), "F6 is not three hours old: its decision waits"
    report = postmortem.study(db, at=ko + timedelta(hours=3))
    assert (report.candidates, report.done, report.studied) == (6, 5, 1), "three hours after kick-off, F6's decision is studied"
    f = pm.row("F6", "OU", "Over", "1.0")
    assert (f["outcome"], f["verdict"], f["review_verdict"], f["loss_class"]) == ("push", "NULO", "push", None), "a push has no verdict to give"


def test_the_twenty_best_investigation_selections_are_studied_once_their_bogota_day_is_over(db: psycopg.Connection[Any], seed: Seed) -> None:
    pm = Pm(db, seed)
    early = postmortem.study(db, at=EARLY)
    assert early.studied == 5 and pm.count(f"fixture_id = {pm.f['F5']} AND market_key = 'OU'") == 0, \
        "half a day would rank differently every hour: none is studied while the day is open"
    late = postmortem.study(db, at=LATE)
    assert late.studied == 21, "the twenty best of 22, and F6's approved decision"
    scores = [int(r[0]) for r in db.execute(
        "SELECT d.score FROM intel.postmortems p JOIN intel.decisions d ON d.id = p.decision_id WHERE p.fixture_id = %s "
        "AND d.state = 'INVESTIGACION'", (pm.f["F5"],)).fetchall()]
    assert len(scores) == 20 and min(scores) == 3 and max(scores) == 22, "the two worst (1 and 2) are not studied"
    row = db.execute("SELECT roles, review_verdict FROM intel.postmortems WHERE fixture_id = %s AND market_key = 'OU' LIMIT 1",
                     (pm.f["F5"],)).fetchone()
    assert row is not None and row[0] == ["decision"] and row[1] in ("unreviewed_won", "unreviewed_lost")
    assert len(events(db)) == 4, "nothing the AI did not study leaves an event"


def test_a_selection_nobody_can_judge_yet_does_not_take_the_place_of_one_that_can_be(db: psycopg.Connection[Any], seed: Seed) -> None:
    results = {k: v for k, v in RESULTS.items() if k != "F1"}
    pm = Pm(db, seed, results=results, investigation=False)
    pm.w.day_pass("F1", at=AT)  # the AI worked on F1 and it was reviewed; the match has no result (postponed, say)
    first = postmortem.study(db, at=EARLY, limit=2)
    assert (first.studied, first.left, first.skipped) == (2, 2, {"no_regulation_score": 1}), \
        "F1 sorts first and has no result: it must not eat the limit"
    second = postmortem.study(db, at=EARLY, limit=2)
    assert (second.studied, second.left) == (2, 0)
    assert pm.count() == 4 and pm.count(f"fixture_id = {pm.f['F1']}") == 0


# ── the readers ─────────────────────────────────────────────────────────────

def test_the_view_gives_the_newest_post_mortem_of_each_selection_and_the_decision_stays_on_the_row(db: psycopg.Connection[Any],
                                                                                                    seed: Seed) -> None:
    pm = Pm(db, seed)
    postmortem.study(db, at=EARLY)
    a = pm.row("F1")
    db.execute("INSERT INTO intel.postmortems (decision_id, fixture_id, created_at, version, outcome, decision_quality, verdict, causes, "
               "answers, evidence, market_key, selection, line, roles, review_id, review_decision, review_verdict, loss_class, odds, "
               "close_odds, p_model, p_market, p_close, price_move, clv) SELECT NULL, fixture_id, created_at + interval '1 day', 'pm-v7', "
               "outcome, decision_quality, verdict, causes, answers, evidence, market_key, selection, line, roles, review_id, "
               "review_decision, review_verdict, loss_class, odds, close_odds, p_model, p_market, p_close, price_move, clv "
               "FROM intel.postmortems WHERE id = %s", (a["id"],))
    rows = {(r[0], r[1], r[2]): r for r in db.execute(
        "SELECT fixture_id, market_key, selection, version, decision_id, settled FROM intel.selection_postmortems").fetchall()}
    assert len(rows) == 5, "one row per selection"
    assert rows[(pm.f["F1"], "1X2", "Home")][3] == "pm-v7", "the newest version of a selection"
    assert rows[(pm.f["F3"], "1X2", "Home")][3] == postmortem.VERSION
    assert rows[(pm.f["F4"], "OU", "Over")][4] == pm.decisions["F4:OU:Over:2.5"], "a decision's post-mortem keeps its decision"
    assert rows[(pm.f["F3"], "1X2", "Home")][4] is None
    assert {r[5] for r in rows.values()} == {"win", "loss"}, "the settled vocabulary of the picks, not the one of the first table"


def test_the_outcome_the_decision_layer_settled_is_kept_beside_the_one_computed_from_the_regulation_score(db: psycopg.Connection[Any],
                                                                                                         seed: Seed) -> None:
    pm = Pm(db, seed)
    report = postmortem.study(db, at=EARLY)
    assert report.outcome_disagreements == 1, "C was settled a win by the decision layer; the regulation score says it lost"
    c = pm.row("F4", "OU", "Over", "2.5")
    assert c["outcome"] == "lost", "the post-mortem judges by the regulation score, as every market settles"
    assert c["evidence"]["decision_outcome"] == {"result": "win", "clv": 0.05, "agrees": False}
