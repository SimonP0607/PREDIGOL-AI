"""«Cómo le va a PrediGol» (plan UX, A12) on a built world: every figure of the page against the hand count and against the
independent queries of ``scripts/transparency_check.py``, the evaluation set never counted, Mis picks' formula, the small
samples without a ROI, and the switch (off for readers, the owner's preview).

AT is 2032-09-20 12:00 UTC (07:00 Bogota); the window of the days without picks is 2032-08-21 .. 2032-09-19. Every match
kicks off at 20:00 UTC (15:00 Bogota, the same date).

PUBLISHED (the qualified set)
    09-20  1X2  PENDING (kick-off AT + 5 h)
    09-19  1X2  WIN 2.00 (+1), LOSS (-1)
    09-15  1X2  WIN 2.10 (+1.10), PUSH (0), HALF_WIN (+0.45), HALF_LOSS (-0.50), VOID (0)
    09-01..09-05  OU  13 WIN at 1.90 (+0.90), 12 LOSS (-1); the closing consensus 0.55 for 20 of them, 0.50 for 5 (3 h before)
    08-10  BTTS WIN 2.50 (+1.50), LOSS, LOSS
THE EVALUATION SET: an item on 09-17 and two on 09-12, all won - never counted.
PARLAYS (legs on days that already have picks, or before the window, so the days without picks below stay as they are)
    daily    09-19 WON (+3.10) - 09-15 LOST (-1) - 08-06 PARTIAL_VOID (+0.80) - 09-20 ACTIVE - 08-05 BUILDING with no legs
    multiday 08-07 VOID - 09-22 READY (kicks off after the reader's today: not counted yet)
    and an evaluation parlay on 09-19, won (+9) - never counted
DAYS WITHOUT PICKS
    09-18  two qualified candidates stopped by «risk», three others by «calibration»      -> not_chosen, stop risk
    09-17  no qualified candidate; five selections measured (calibration 3, market 2)     -> no_qualified_candidates
    09-12  the evaluation set's matches only                                               -> no_qualified_candidates
    09-16  a match of a league PrediGol does not follow only                                -> no_matches
FORECASTS (matches of a league PrediGol does not follow): OU 2.5 calibrated for 320 matches (100 said 0.35, 100 said 0.55, 100 said 0.65 with exactly that share of Overs;
20 said 0.85 - a range too small to show) plus 10 older uncalibrated; 1X2 uncalibrated for 40 matches; no BTTS.
EVALUATION: OU x dixon_coles NOT_VALIDATED then VALIDATED, 1X2 x poisson and BTTS x dixon_coles NOT_VALIDATED.
The transaction is rolled back afterwards."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb
from scripts import transparency_check

from fbi.api.app import create_app
from fbi.api.deps import get_db
from fbi.api.services import records as records_service
from fbi.api.services import transparency as service
from fbi.api.services import transparency_picks
from fbi.api.switches import TRANSPARENCY
from fbi.core.clock import FrozenClock, SystemClock, set_clock
from fbi.userdata import records
from tests.integration.signed_in import SAME_SITE, signed_in

from .conftest import Seed
from .helpers import scalar
from .test_intel import IntelWorld

AT = datetime(2032, 9, 20, 12, tzinfo=UTC)
TZ = "America/Bogota"


def ko(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 20, tzinfo=UTC)


class World(IntelWorld):
    def __init__(self, db: psycopg.Connection[Any], seed: Seed) -> None:
        super().__init__(db, seed)
        self.cur.execute("INSERT INTO market.markets (key,name,n_outcomes,has_line,is_exclusive) VALUES "
                         "('1X2','Match Winner',3,false,true) ON CONFLICT (key) DO NOTHING")
        self.sets: dict[tuple[date, str], int] = {}
        self.items: dict[int, int] = {}

    def daily_set(self, day: date, source: str) -> int:
        if (day, source) not in self.sets:
            self.cur.execute("INSERT INTO picks.daily_sets (day, timezone, source, rule_version, status, created_at, "
                             "updated_at) VALUES (%s, 'America/Bogota', %s, 'daily-set-v5', 'COMPLETE', %s, %s) "
                             "RETURNING id", (day, source, AT - timedelta(days=60), AT - timedelta(days=60)))
            self.sets[(day, source)] = scalar(self.cur)
        return self.sets[(day, source)]

    def item(self, day: date, market: str, selection: str, line: str, status: str, profit: str | None, odds: str,
             *, source: str = "qualified", kickoff: datetime | None = None) -> tuple[int, int]:
        """One published item (its own match and pick): the match id and the item's pick."""
        kick = kickoff or ko(day)
        fid = self.fixture(kick)
        pick = self.pick(fid, market, selection, line, p_model=0.55, p_market=0.50, odds=float(odds),
                         created=kick - timedelta(hours=6))
        set_id = self.daily_set(day, source)
        rank = self.items[set_id] = self.items.get(set_id, 0) + 1
        self.cur.execute(
            "INSERT INTO picks.daily_set_items (set_id, rank, pick_id, fixture_id, market_key, selection, line, stage, "
            "selected_at, odds, bookmaker_id, price_at, p_model, p_low, p_push, p_market, ev, model_version_id, inputs, "
            "status, profit_units, settled_at) VALUES (%s,%s,%s,%s,%s,%s,%s,'T-6h',%s,%s,%s,%s,0.55,0.50,0,0.50,0.05,%s,"
            "'{}',%s,%s,%s)",
            (set_id, rank, pick, fid, market, selection, line, kick - timedelta(hours=6), odds, self.seed.bookmaker_id,
             kick - timedelta(hours=6), self.seed.model_version_id, status, profit,
             None if status == "PENDING" else kick + timedelta(hours=2)))
        return fid, pick

    def parlay(self, kind: str, day: date, status: str, profit: str | None, *, source: str = "qualified", legs: int = 2,
               kickoff: datetime | None = None) -> int:
        """A stored parlay of ``legs`` legs, each on its own match (kicking off the minute after the one before)."""
        kick = kickoff or ko(day)
        settled = status in ("WON", "LOST", "VOID", "PARTIAL_VOID")
        self.cur.execute(
            "INSERT INTO picks.parlays (kind, day, source, rule_version, status, min_legs, max_legs, window_from, "
            "window_to, combined_odds, p_all_low, expected_log_growth, created_at, ready_at, settled_at, profit_units) "
            "VALUES (%s, %s, %s, 'parlay-v5', %s, 2, 7, %s, %s, 5.29, 0.20, 0.001, %s, %s, %s, %s) RETURNING id",
            (kind, day, source, status, kick - timedelta(hours=8), kick + timedelta(hours=40), kick - timedelta(hours=8),
             None if status == "BUILDING" else kick - timedelta(hours=8),
             kick + timedelta(hours=3) if settled else None, profit))
        parlay_id = scalar(self.cur)
        for n in range(1, (0 if status == "BUILDING" else legs) + 1):
            when = kick + timedelta(minutes=n)
            fid = self.fixture(when)
            pick = self.pick(fid, "1X2", "Home", "0", p_model=0.50, p_market=0.43, odds=2.30, created=when - timedelta(hours=6))
            self.cur.execute(
                "INSERT INTO picks.parlay_legs (parlay_id, leg_no, pick_id, fixture_id, market_key, selection, line, "
                "added_at, odds, bookmaker_id, price_at, p_model, p_low, p_push, p_market, ev, inputs, status, settled_at) "
                "VALUES (%s, %s, %s, %s, '1X2', 'Home', 0, %s, 2.30, %s, %s, 0.50, 0.45, 0, 0.43, 0.15, '{}', %s, %s)",
                (parlay_id, n, pick, fid, when - timedelta(hours=6), self.seed.bookmaker_id, when - timedelta(hours=6),
                 "WIN" if settled else "PENDING", when + timedelta(hours=2) if settled else None))
        return int(parlay_id)

    def untracked(self) -> int:
        """A season of a league PrediGol does not follow (its matches are not «the day's matches»)."""
        if not hasattr(self, "_untracked"):
            self.cur.execute("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, "
                             "competition_type, is_tracked) VALUES (98802, 'Untracked', 'league', 'club', "
                             "'domestic_league', false) RETURNING id")
            comp = scalar(self.cur)
            self.cur.execute("INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, 2032) "
                             "RETURNING id", (comp,))
            self._untracked = int(scalar(self.cur))
        return self._untracked

    def other_fixture(self, kickoff: datetime) -> int:
        self.n_fixtures += 1
        self.cur.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, "
                         "away_team_id, kickoff_at) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                         (9880000 + self.n_fixtures, self.untracked(), self.team(), self.team(), kickoff))
        return int(scalar(self.cur))

    def qualify(self, pick: int, qualified: bool) -> None:
        self.cur.execute("UPDATE picks.picks SET qualification = %s WHERE id = %s",
                         (Jsonb({"qualified": qualified, "reasons": []}), pick))

    def decision(self, fid: int, kickoff: datetime, selection: str, stop: str | None, *, pick: int | None = None,
                 known: timedelta = timedelta(hours=3), market: str = "OU", line: str = "2.5") -> None:
        filters = []
        for n, key in enumerate(service.STOPS, start=1):
            ok = stop is None or service.STOPS.index(key) < service.STOPS.index(stop)
            filters.append({"n": n, "key": key, "ok": ok if key != stop else False, "why": "test"})
        self.cur.execute(
            "INSERT INTO intel.decisions (decision_version, known_at, checkpoint, fixture_id, kickoff_at, market_key, "
            "selection, line, pick_id, model_name, odds, p_model, p_cal, p_market, filters, state, context_status, "
            "input_hash) VALUES ('decision-v1', %s, 'T-3h', %s, %s, %s, %s, %s, %s, 'dixon_coles', 2.0, 0.6, 0.6, 0.5, "
            "%s, 'INVESTIGACION', 'PENDING', %s)",
            (kickoff - known, fid, kickoff, market, selection, line, pick, Jsonb(filters),
             f"t-{fid}-{selection}-{known.total_seconds()}"))

    def finished(self, fid: int, home: int, away: int) -> None:
        self.cur.execute("UPDATE core.fixtures SET status_short = 'FT', status_group = 'finished' WHERE id = %s", (fid,))
        self.cur.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away) VALUES (%s, %s, %s)",
                         (fid, home, away))

    def calibrator(self) -> int:
        if not hasattr(self, "_calibrator"):
            self.cur.execute("INSERT INTO intel.calibrators (market_key, model_name, method, version, params, known_at, "
                             "fitted_at, n_train, train_hash, wf, gate) VALUES ('OU', 'dixon_coles', 'logit2', 'test', "
                             "'{}', %s, %s, 500, 'h', '{}', '{}') RETURNING id", (AT - timedelta(days=90),) * 2)
            self._calibrator = int(scalar(self.cur))
        return self._calibrator

    def forecast(self, fid: int, kickoff: datetime, market: str, line: str, probs: dict[str, float],
                 calibration: str) -> None:
        calibrated = calibration == "CALIBRATED"
        for selection, p in probs.items():
            self.cur.execute(
                "INSERT INTO models.match_forecasts (version, known_at, fixture_id, family, market_key, selection, line, "
                "model_name, model_version_id, data_cutoff_ts, p_model, p, calibration, calibrator_id, basis, input_hash, "
                "code_version) VALUES ('forecast-v1', %s, %s, 'GOALS', %s, %s, %s, 'dixon_coles', %s, %s, %s, %s, %s, %s, "
                "%s, 'h', 'c')",
                (kickoff - timedelta(hours=2), fid, market, selection, line, self.seed.model_version_id,
                 kickoff - timedelta(hours=3), p, p, calibration, self.calibrator() if calibrated else None,
                 "champion" if calibrated else "no_champion"))

    def edge(self, market: str, model: str, role: str, at: datetime) -> None:
        self.cur.execute("INSERT INTO intel.promotions (at, entity, market_key, model_name, to_role, gate_version, "
                         "criteria, reason, decided_by) VALUES (%s, 'market_edge', %s, %s, %s, 'edge-gate-v1', '{}', "
                         "'test', 'system')", (at, market, model, role))


def build(db: psycopg.Connection[Any], seed: Seed) -> World:
    w = World(db, seed)
    d = date
    w.item(d(2032, 9, 20), "1X2", "Home", "0", "PENDING", None, "2.00", kickoff=AT + timedelta(hours=5))
    won, _ = w.item(d(2032, 9, 19), "1X2", "Home", "0", "WIN", "1", "2.00")
    w.finished(won, 2, 1)
    w.item(d(2032, 9, 19), "1X2", "Away", "0", "LOSS", "-1", "3.00")
    for status, profit, odds in (("WIN", "1.10", "2.10"), ("PUSH", "0", "1.80"), ("HALF_WIN", "0.45", "1.90"),
                                 ("HALF_LOSS", "-0.50", "1.95"), ("VOID", "0", "2.20")):
        w.item(d(2032, 9, 15), "1X2", "Home", "0", status, profit, odds)
    for k in range(25):
        day = d(2032, 9, 1) + timedelta(days=k // 5)
        fid, _ = w.item(day, "OU", "Over", "2.5", "WIN" if k < 13 else "LOSS", "0.90" if k < 13 else "-1", "1.90")
        w.consensus(fid, "OU", "Over", "2.5", p_fair=0.55 if k < 20 else 0.50, best=1.90, as_of=ko(day) - timedelta(hours=3))
        w.consensus(fid, "OU", "Over", "2.5", p_fair=0.99, best=1.01, as_of=ko(day) + timedelta(minutes=5))
    for status, profit, odds in (("WIN", "1.50", "2.50"), ("LOSS", "-1", "2.50"), ("LOSS", "-1", "2.40")):
        w.item(d(2032, 8, 10), "BTTS", "Yes", "0", status, profit, odds)
    # the evaluation set: won, and never counted
    w.item(d(2032, 9, 17), "OU", "Over", "2.5", "WIN", "5", "6.00", source="evaluation")
    w.item(d(2032, 9, 12), "OU", "Over", "2.5", "WIN", "5", "6.00", source="evaluation")
    w.item(d(2032, 9, 12), "OU", "Under", "2.5", "WIN", "5", "6.00", source="evaluation")
    # the parlays
    w.parlay("daily", d(2032, 9, 19), "WON", "3.10")
    w.parlay("daily", d(2032, 9, 15), "LOST", "-1")
    w.parlay("daily", d(2032, 8, 6), "PARTIAL_VOID", "0.80")
    w.parlay("daily", d(2032, 9, 20), "ACTIVE", None, kickoff=AT + timedelta(hours=5))
    w.parlay("daily", d(2032, 8, 5), "BUILDING", None)
    w.parlay("multiday", d(2032, 8, 7), "VOID", "0")
    w.parlay("multiday", d(2032, 9, 22), "READY", None)
    w.parlay("daily", d(2032, 9, 19), "WON", "9", source="evaluation")
    # 09-18: two qualified candidates stopped by risk, three others by calibration
    for k in range(2):
        fid = w.fixture(ko(d(2032, 9, 18)))
        pick = w.pick(fid, "OU", "Over", "2.5", p_model=0.6, p_market=0.5, odds=2.0, created=ko(d(2032, 9, 18)) - timedelta(hours=8))
        w.qualify(pick, True)
        w.decision(fid, ko(d(2032, 9, 18)), "Over", "risk", pick=pick)
        w.decision(fid, ko(d(2032, 9, 18)), "Under", "calibration")
        if k == 0:
            w.decision(fid, ko(d(2032, 9, 18)), "Over", "calibration", market="BTTS", line="0")
    # 09-17: no qualified candidate, five selections (calibration 3, market 2); an older decision does not count
    fid = w.fixture(ko(d(2032, 9, 17)))
    pick = w.pick(fid, "OU", "Over", "2.5", p_model=0.6, p_market=0.5, odds=2.0, created=ko(d(2032, 9, 17)) - timedelta(hours=8))
    w.qualify(pick, False)
    w.decision(fid, ko(d(2032, 9, 17)), "Over", "data", pick=pick, known=timedelta(hours=10))
    for selection, stop in (("Over", "calibration"), ("Under", "calibration")):
        w.decision(fid, ko(d(2032, 9, 17)), selection, stop, pick=pick if selection == "Over" else None)
    w.decision(fid, ko(d(2032, 9, 17)), "Over", "calibration", market="OU", line="3.5")
    w.decision(fid, ko(d(2032, 9, 17)), "Over", "market", market="OU", line="1.5")
    w.decision(fid, ko(d(2032, 9, 17)), "Yes", "market", market="BTTS", line="0")
    # 09-16: a match of a league PrediGol does not follow
    w.other_fixture(ko(d(2032, 9, 16)))
    # forecasts (in that league: their days are not the days of the block above): OU calibrated 320 + 10 older
    # uncalibrated, 1X2 uncalibrated 40
    n = 0
    for said, count, overs in ((0.35, 100, 35), (0.55, 100, 55), (0.65, 100, 65), (0.85, 20, 17)):
        for k in range(count):
            n += 1
            kick = AT - timedelta(days=1 + n % 13, hours=n % 7)
            fid = w.other_fixture(kick)
            w.finished(fid, *((2, 1) if k < overs else (1, 0)))
            w.forecast(fid, kick, "OU", "2.5", {"Over": said, "Under": round(1 - said, 4)}, "CALIBRATED")
    for k in range(10):
        kick = AT - timedelta(days=60 + k)
        fid = w.other_fixture(kick)
        w.finished(fid, 1, 1)
        w.forecast(fid, kick, "OU", "2.5", {"Over": 0.5, "Under": 0.5}, "UNCALIBRATED")
    for k in range(40):
        kick = AT - timedelta(days=2 + k % 20, hours=3)
        fid = w.other_fixture(kick)
        w.finished(fid, k % 3, 1)
        w.forecast(fid, kick, "1X2", "0", {"Home": 0.45, "Draw": 0.27, "Away": 0.28}, "UNCALIBRATED")
    # the edge gate
    w.edge("OU", "dixon_coles", "NOT_VALIDATED", AT - timedelta(days=40))
    w.edge("OU", "dixon_coles", "VALIDATED", AT - timedelta(days=5))
    w.edge("1X2", "poisson", "NOT_VALIDATED", AT - timedelta(days=39))
    w.edge("BTTS", "dixon_coles", "NOT_VALIDATED", AT - timedelta(days=38))
    return w


@pytest.fixture
def world(db: psycopg.Connection[Any], seed: Seed) -> World:
    return build(db, seed)


def test_the_published_picks_by_period_with_their_sample(db: psycopg.Connection[Any], world: World) -> None:
    page = service.build(db, tz=TZ, at=AT)
    by = {p.period: p for p in page.periods}
    week = by["7d"]
    assert (week.since, week.until) == (date(2032, 9, 14), date(2032, 9, 20))
    assert (week.published, week.pending, week.won, week.lost, week.half_won, week.half_lost, week.push, week.void,
            week.settled) == (8, 1, 2, 1, 1, 1, 1, 1, 6)
    assert (week.units, week.roi, week.margin, week.conclusive) == (None, None, None, False), "6 settled: counts only"
    month = by["30d"]
    assert (month.published, month.settled) == (33, 31)
    assert month.units == Decimal("0.75")
    assert month.roi == Decimal("0.0242") and month.margin == Decimal("0.1796") and not month.conclusive
    whole = by["all"]
    assert whole.since is None and (whole.published, whole.settled) == (36, 34)
    assert (whole.units, whole.roi, whole.margin) == (Decimal("0.25"), Decimal("0.0074"), Decimal("0.1715"))
    assert page.data_as_of is not None


def test_the_parlays_by_kind_counted_like_mis_picks(db: psycopg.Connection[Any], world: World) -> None:
    page = service.build(db, tz=TZ, at=AT)
    daily, multiday = page.parlays
    assert (daily.kind, daily.published, daily.pending, daily.won, daily.partial, daily.lost, daily.void,
            daily.settled) == ("daily", 4, 1, 2, 1, 1, 0, 3), "the one being built, the one after today's end and the evaluation one are not there"
    assert (daily.units, daily.roi, daily.conclusive) == (None, None, False), "3 settled: counts only"
    assert (multiday.kind, multiday.published, multiday.void, multiday.settled, multiday.units) == (
        "multiday", 1, 1, 0, None)
    mine = records.history(db, user_id=-1, period="all", tz=TZ, at=AT, include_evaluation=False)["predigol_parlays"]
    assert (mine.total, mine.pending, mine.won, mine.lost, mine.void) == (5, 1, 2, 1, 1), "Mis picks reads them the same"
    assert mine.staked == daily.settled + multiday.settled and mine.profit == Decimal("2.90")
    assert transparency_check.check(db, tz="Europe/Madrid", at=AT) == []


def test_the_published_picks_one_by_one_newest_first(db: psycopg.Connection[Any], world: World) -> None:
    seen: list[Any] = []
    cursor: str | None = None
    pages = 0
    while True:
        page = transparency_picks.published_picks(db, tz=TZ, limit=10, cursor=cursor, at=AT)
        pages += 1
        assert page.meta.total == 36 and page.status.value == "ok"
        seen.extend(page.data)
        cursor = page.meta.next_cursor
        if cursor is None:
            break
    assert (pages, len(seen)) == (4, 36), "as many as the counts say, a page at a time"
    assert [i.kickoff_at for i in seen] == sorted((i.kickoff_at for i in seen), reverse=True)
    pending = seen[0]
    assert (pending.day, pending.result, pending.units, pending.score_home) == (date(2032, 9, 20), "PENDING", None, None)
    lost, won = seen[1], seen[2]
    assert (lost.market, lost.selection, lost.result, lost.units, lost.odds) == ("1X2", "Away", "LOSS", Decimal("-1"), Decimal("3"))
    assert (won.selection, won.result, won.units, won.odds, won.p_model, won.p_market) == (
        "Home", "WIN", Decimal("1"), Decimal("2"), Decimal("0.55"), Decimal("0.50"))
    assert (won.score_home, won.score_away) == (2, 1) and (lost.score_home, lost.score_away) == (None, None)
    assert won.published_at < won.kickoff_at and won.home != won.away and won.competition
    assert max(i.odds for i in seen) < Decimal("6"), "the evaluation items (all at 6.00) are not in it"
    assert {i.day for i in seen}.isdisjoint({date(2032, 9, 17), date(2032, 9, 12)})
    assert [i.result for i in seen].count("VOID") == 1 and [i.result for i in seen].count("HALF_WIN") == 1
    again: list[Any] = []
    cursor = None
    while True:
        page = transparency_picks.published_picks(db, tz=TZ, limit=1, cursor=cursor, at=AT)
        again.extend(page.data)
        cursor = page.meta.next_cursor
        if cursor is None:
            break
    assert again == seen, "the same list at any page size: two picks of one kick-off are never repeated or skipped"


def test_the_list_ends_at_the_readers_today_like_the_counts(db: psycopg.Connection[Any], world: World) -> None:
    madrid = transparency_picks.published_picks(db, tz="Europe/Madrid", limit=50, at=AT)
    whole = next(p for p in service.build(db, tz="Europe/Madrid", at=AT).periods if p.period == "all")
    assert madrid.meta.total == whole.published == len(madrid.data)
    early = AT - timedelta(days=30)
    old = transparency_picks.published_picks(db, tz=TZ, limit=50, at=early)
    assert old.meta.total == 3 and {i.market for i in old.data} == {"BTTS"}, "on 08-21 only the three of 08-10 had started"


def test_a_cursor_of_another_list_is_refused(db: psycopg.Connection[Any], world: World) -> None:
    for cursor in ("nonsense", records_service.encode_cursor("p", AT, 7)):
        with pytest.raises(records_service.CursorError):
            transparency_picks.published_picks(db, tz=TZ, cursor=cursor, at=AT)


def test_the_evaluation_set_is_never_counted(db: psycopg.Connection[Any], world: World) -> None:
    page = service.build(db, tz=TZ, at=AT)
    assert next(p for p in page.periods if p.period == "all").published == 36, "the three evaluation items are not there"
    days = {d.day: d for d in page.days.items}
    assert date(2032, 9, 17) in days and date(2032, 9, 12) in days, "a day with evaluation items only has no picks"


def test_the_same_formula_as_mis_picks(db: psycopg.Connection[Any], world: World) -> None:
    whole = next(p for p in service.build(db, tz=TZ, at=AT).periods if p.period == "all")
    mine = records.history(db, user_id=-1, period="all", tz=TZ, at=AT, include_evaluation=False)["predigol_picks"]
    assert mine.staked == whole.settled and mine.profit.quantize(Decimal("0.01")) == whole.units
    assert mine.roi is not None and whole.roi == Decimal(mine.roi).quantize(Decimal("0.0001"))
    assert (mine.won, mine.lost, mine.push, mine.void, mine.pending) == (
        whole.won + whole.half_won, whole.lost + whole.half_lost, whole.push, whole.void, whole.pending)


def test_by_kind_of_bet_the_small_ones_together(db: psycopg.Connection[Any], world: World) -> None:
    markets = service.build(db, tz=TZ, at=AT).markets
    assert [m.market for m in markets] == ["OU", "other"]
    ou, other = markets
    assert (ou.settled, ou.units, ou.roi) == (25, Decimal("-0.30"), Decimal("-0.0120"))
    assert (other.published, other.settled, other.units, other.roi) == (11, 9, None, None), "1X2 6 + BTTS 3 settled"


def test_the_days_without_picks_and_why(db: psycopg.Connection[Any], world: World) -> None:
    days = service.build(db, tz=TZ, at=AT).days
    assert (days.since, days.until, days.days) == (date(2032, 8, 21), date(2032, 9, 19), 30)
    assert days.with_picks == 7 and days.without == 23, "09-01..09-05, 09-15 and 09-19 had picks"
    by = {d.day: d for d in days.items}
    chosen = by[date(2032, 9, 18)]
    assert (chosen.reason, chosen.matches, chosen.measured, chosen.stop) == ("not_chosen", 2, 5, "risk"), (
        "the qualified candidates' commonest stop, not the day's (calibration 3)")
    none = by[date(2032, 9, 17)]
    assert (none.reason, none.matches, none.measured, none.stop) == ("no_qualified_candidates", 2, 5, "calibration"), (
        "the last decision of a selection counts, not its older «data» one; the evaluation item's match is a match")
    assert (by[date(2032, 9, 16)].reason, by[date(2032, 9, 16)].matches) == ("no_matches", 0)
    assert (by[date(2032, 9, 12)].reason, by[date(2032, 9, 12)].matches, by[date(2032, 9, 12)].measured,
            by[date(2032, 9, 12)].stop) == ("no_qualified_candidates", 2, 0, None), "the evaluation items' matches"
    assert days.reasons == {"no_matches": 20, "no_qualified_candidates": 2, "not_chosen": 1}
    assert [d.day for d in days.items] == sorted(by, reverse=True)
    assert days.stops == {"calibration": 1, "risk": 1}


def test_the_line_value_follows_the_canonical_definition(db: psycopg.Connection[Any], world: World) -> None:
    lv = service.build(db, tz=TZ, at=AT).line_value
    assert (lv.version, lv.since) == ("clv-v1", date(2026, 10, 22))
    assert lv.n == 25, "only the published picks with a consensus before kick-off"
    assert lv.mean == Decimal("0.0260"), "20 x (1.90 x 0.55 - 1) and 5 x (1.90 x 0.50 - 1), never the one after kick-off"
    assert (lv.positive, lv.minutes) == (Decimal("0.8000"), 180)


def test_the_forecasts_calibration_only_when_it_is_calibrated_and_enough(db: psycopg.Connection[Any],
                                                                        world: World) -> None:
    forecasts = {f.market: f for f in service.build(db, tz=TZ, at=AT).forecasts}
    ou = forecasts["OU"]
    assert (ou.state, ou.matches, ou.calibrated, ou.selection) == ("CALIBRATED", 330, 320, "Over")
    assert [(b.low, b.n, b.observed) for b in ou.bins] == [
        (Decimal("0.3"), 100, Decimal("0.350")), (Decimal("0.5"), 100, Decimal("0.550")),
        (Decimal("0.6"), 100, Decimal("0.650"))]
    assert ou.omitted == 20, "the 0.85 range has 20 cases: left out"
    x12 = forecasts["1X2"]
    assert (x12.state, x12.matches, x12.calibrated, x12.bins) == ("UNCALIBRATED", 40, 0, []), "«sin calibrar»: no figures"
    assert (forecasts["BTTS"].matches, forecasts["BTTS"].state) == (0, "UNCALIBRATED")


def test_what_is_in_evaluation(db: psycopg.Connection[Any], world: World) -> None:
    page = service.build(db, tz=TZ, at=AT)
    ev = page.evaluation
    assert (ev.markets, ev.pairs, ev.passed_markets, ev.passed_pairs) == (3, 3, 1, 1), "the newest role of each pair"
    assert ev.since == date(2032, 8, 11)
    assert ev.qualified == 2, "the two qualified candidates of 09-18"
    assert {x.key for x in page.definitions} == {"roi", "sample", "no_pick_day", "line_value", "calibration",
                                                 "evaluation"}


def test_every_figure_matches_its_independent_query(db: psycopg.Connection[Any], world: World) -> None:
    assert transparency_check.check(db, tz=TZ, at=AT) == []
    assert transparency_check.check(db, tz="Europe/Madrid", at=AT) == []


def test_the_contrast_sees_a_wrong_parlay_and_a_wrong_list(db: psycopg.Connection[Any], world: World,
                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    real_parlays = service.parlays

    def one_more_win(rows: Any) -> Any:
        out = real_parlays(rows)
        out[0] = out[0].model_copy(update={"won": out[0].won + 1})
        return out

    monkeypatch.setattr(service, "parlays", one_more_win)
    assert any(m.figure == "parlays.daily.won" for m in transparency_check.check(db, tz=TZ, at=AT))
    monkeypatch.setattr(service, "parlays", real_parlays)
    monkeypatch.setattr(transparency_picks, "TOTAL_SQL", transparency_picks.TOTAL_SQL.replace("count(*)", "count(*) + 1"))
    assert any(m.figure == "picks.list.total" for m in transparency_check.check(db, tz=TZ, at=AT))


def test_the_contrast_sees_a_wrong_figure(db: psycopg.Connection[Any], world: World,
                                          monkeypatch: pytest.MonkeyPatch) -> None:
    real = service.count

    def off_by_one(rows: Any) -> service.Count:
        c = real(rows)
        c.won += 1
        return c

    monkeypatch.setattr(service, "count", off_by_one)
    found = transparency_check.check(db, tz=TZ, at=AT)
    assert any(m.figure == "periods.7d.won" for m in found)


def test_an_empty_history_says_nothing_it_does_not_have(db: psycopg.Connection[Any], seed: Seed) -> None:
    page = service.build(db, tz=TZ, at=AT)
    whole = next(p for p in page.periods if p.period == "all")
    assert (whole.published, whole.settled, whole.units, whole.roi) == (0, 0, None, None)
    assert page.markets == [] and page.line_value.n == 0 and page.line_value.mean is None
    assert [(p.kind, p.published, p.settled, p.units) for p in page.parlays] == [("daily", 0, 0, None), ("multiday", 0, 0, None)]
    empty = transparency_picks.published_picks(db, tz=TZ, at=AT)
    assert (empty.status.value, empty.data, empty.meta.total, empty.meta.next_cursor) == ("empty", [], 0, None)
    assert empty.reason == "PrediGol has not published a pick yet."
    assert transparency_check.check(db, tz=TZ, at=AT) == []


def client(db: psycopg.Connection[Any], role: str, monkeypatch: pytest.MonkeyPatch, switch: str | None) -> TestClient:
    if switch is None:
        monkeypatch.delenv(TRANSPARENCY, raising=False)
    else:
        monkeypatch.setenv(TRANSPARENCY, switch)
    app = signed_in(create_app(), role)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app, headers=SAME_SITE)


def test_readers_see_it_only_once_the_owner_opens_it(db: psycopg.Connection[Any], world: World,
                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    hidden = client(db, "USER", monkeypatch, None).get("/api/v1/transparency")
    assert hidden.status_code == 200 and hidden.json()["status"] == "not_available" and hidden.json()["data"] is None
    assert client(db, "USER", monkeypatch, None).get("/api/v1/auth/me").json()["transparency"] is False
    assert client(db, "USER", monkeypatch, None).get("/api/v1/transparency?preview=shadow").status_code == 403
    preview = client(db, "SUPER_ADMIN", monkeypatch, None).get("/api/v1/transparency?preview=shadow")
    assert preview.json()["status"] == "ok" and preview.json()["data"]["min_sample"] == 25
    opened = client(db, "USER", monkeypatch, "1")
    body = opened.get("/api/v1/transparency").json()
    assert body["status"] == "ok" and {p["period"] for p in body["data"]["periods"]} == {"7d", "30d", "all"}
    assert opened.get("/api/v1/auth/me").json()["transparency"] is True
    assert client(db, "USER", monkeypatch, "maybe").get("/api/v1/transparency").json()["status"] == "not_available"


def test_the_list_follows_the_same_gate_and_pages(db: psycopg.Connection[Any], world: World,
                                                  monkeypatch: pytest.MonkeyPatch) -> None:
    set_clock(FrozenClock(AT))
    try:
        hidden = client(db, "USER", monkeypatch, None).get("/api/v1/transparency/picks")
        assert hidden.status_code == 200 and hidden.json()["status"] == "not_available" and hidden.json()["data"] == []
        assert client(db, "USER", monkeypatch, None).get("/api/v1/transparency/picks?preview=shadow").status_code == 403
        owner = client(db, "SUPER_ADMIN", monkeypatch, None).get("/api/v1/transparency/picks?preview=shadow&limit=5").json()
        assert owner["status"] == "ok" and len(owner["data"]) == 5 and owner["meta"]["total"] == 36
        opened = client(db, "USER", monkeypatch, "1")
        first = opened.get("/api/v1/transparency/picks?limit=5").json()
        assert first["data"] == owner["data"], "the owner's preview and the readers' page are the same list"
        second = opened.get(f"/api/v1/transparency/picks?limit=5&cursor={first['meta']['next_cursor']}").json()
        assert second["data"][0] != first["data"][0] and second["data"][0]["kickoff_at"] <= first["data"][-1]["kickoff_at"]
        assert set(first["data"][0]) == {"day", "kickoff_at", "published_at", "competition", "country", "home", "away",
                                         "market", "selection", "line", "odds", "p_model", "p_market", "result", "units",
                                         "score_home", "score_away"}, "a price, a probability and a result: nothing internal"
        refused = opened.get("/api/v1/transparency/picks?cursor=nonsense")
        assert refused.status_code == 422 and refused.json()["error"]["code"] == "invalid_cursor"
        assert opened.get("/api/v1/transparency/picks?limit=0").status_code == 422
        assert opened.get("/api/v1/transparency/picks?limit=51").status_code == 422
    finally:
        set_clock(SystemClock())
