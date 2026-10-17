"""GATE D on a built world: the day's set chosen and frozen, the parlays built by expected log
growth, everything settled after the matches, and a user's own picks, parlays and history.

AT is 2032-08-01 12:00 UTC (07:00 in Bogota). Six matches that day, one the next:

    F1  +2h   qualified  p 0.50 (low 0.45)  price 2.30
    F2  +4h   qualified  p 0.50 (low 0.30)  price 2.30   gate passes, pessimistic growth negative
    F3  +6h   qualified  p 0.55 (low 0.50)  price 2.10
    F4  +8h   shadow     p 0.50 (low 0.45)  price 2.30
    F5  +10h  shadow     p 0.50 (low 0.46)  price 2.30
    F6  +13h  shadow     p 0.50 (low 0.44)  price 2.30
    F7  +30h  shadow     (next day, beyond 24 h)
The transaction is rolled back afterwards."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb

from fbi.parlays.persist import build_parlays
from fbi.picks.daily import build_daily_sets, product_day
from fbi.picks.product_settlement import settle_products
from fbi.userdata import records as userdata

from .conftest import Seed
from .helpers import scalar

AT = datetime(2032, 8, 1, 12, tzinfo=UTC)
PICK_COLS = (
    "candidate_id,fixture_id,market_key,selection,model_version_id,calibrator_id,"
    "feature_set_hash,data_cutoff_ts,decision_rule_version,code_version,bookmaker_id,"
    "market_odds,odds_captured_at,p_model,p_calibrated,p_calibrated_lo,p_calibrated_hi,"
    "p_market_fair,fair_odds,edge,price_edge,ev,ev_adjusted,kelly_fraction,stake_units,"
    "selection_reason"
)
PLAN = [  # name, hours, status, p, p_low, price
    ("F1", 2, "qualified", "0.50", "0.45", "2.30"), ("F2", 4, "qualified", "0.50", "0.30", "2.30"),
    ("F3", 6, "qualified", "0.55", "0.50", "2.10"), ("F4", 8, "shadow", "0.50", "0.45", "2.30"),
    ("F5", 10, "shadow", "0.50", "0.46", "2.30"), ("F6", 13, "shadow", "0.50", "0.44", "2.30"),
    ("F7", 30, "shadow", "0.50", "0.45", "2.30"),
]


class World:
    def __init__(self, db: psycopg.Connection[Any], seed: Seed) -> None:
        self.db, self.seed, self.cur = db, seed, db.cursor()
        self.fixtures: dict[str, int] = {}
        self.picks: dict[str, int] = {}
        cur = self.cur
        # Two leagues (F1-F3 in one, F4-F7 in the other): a parlay holds at most two legs of one competition
        # (parlay-v4's exposure cap), so the multi-day parlay needs the second league.
        seasons = []
        for league, name in ((97401, "Daily League"), (97402, "Daily League B")):
            cur.execute("INSERT INTO core.competitions (provider_league_id, name, country, type, entity_scope, "
                        "competition_type, is_tracked) VALUES (%s, %s, 'Colombia', 'league', 'club', "
                        "'domestic_league', true) RETURNING id", (league, name))
            comp = scalar(cur)
            cur.execute("INSERT INTO core.competition_seasons (competition_id, season, is_current) VALUES "
                        "(%s, 2032, true) RETURNING id", (comp,))
            seasons.append(scalar(cur))
        cur.execute(
            "INSERT INTO models.calibrators (model_version_id,market_key,scope,method,params,n_train,train_from,"
            "train_to,n_val,val_from,val_to,val_ece,val_mce,val_brier,val_logloss,reliability_weight) VALUES "
            "(%s,'1X2','global','isotonic','{}',1000,'2020-01-01','2024-06-30',500,'2024-07-01','2025-06-30',"
            "0.018,0.04,0.19,0.58,0.82) RETURNING id", (seed.model_version_id,))
        calibrator = scalar(cur)
        for n, (name, hours, status, p, low, price) in enumerate(PLAN):
            teams = []
            for side in ("H", "A"):
                cur.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (%s, %s) RETURNING id",
                            (974000 + 2 * n + (side == "A"), f"{name}-{side}"))
                teams.append(scalar(cur))
            cur.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, "
                        "away_team_id, kickoff_at) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                        (7340100 + n, seasons[0] if n < 3 else seasons[1], teams[0], teams[1],
                         AT + timedelta(hours=hours)))
            fid = self.fixtures[name] = scalar(cur)
            cutoff = AT - timedelta(days=1)
            cur.execute("INSERT INTO models.predictions (fixture_id,model_version_id,calibrator_id,market_key,"
                        "selection,p_raw,p_calibrated,p_lo,p_hi,feature_set_hash,data_cutoff_ts) VALUES "
                        "(%s,%s,%s,'1X2','Home',%s,%s,%s,0.70,'fh',%s) RETURNING id",
                        (fid, seed.model_version_id, calibrator, p, p, low, cutoff))
            prediction = scalar(cur)
            cur.execute("INSERT INTO picks.pick_candidates (run_id,fixture_id,prediction_id,market_key,selection,"
                        "bookmaker_id,market_odds,p_calibrated,p_market_fair,edge,price_edge,ev,ev_adjusted,decision)"
                        " VALUES (%s,%s,%s,'1X2','Home',%s,%s,%s,0.43,0.07,0.08,0.15,0.10,'selected') RETURNING id",
                        (seed.run_id, fid, prediction, seed.bookmaker_id, price, p))
            candidate = scalar(cur)
            cur.execute(
                f"INSERT INTO picks.picks ({PICK_COLS}) VALUES (%s,%s,'1X2','Home',%s,%s,'fh',%s,'shadow-rule-v2',"
                "'abc',%s,%s,%s,%s,%s,%s,0.70,0.43,2.0,0.07,0.08,0.15,0.10,0.11,1,'{}') RETURNING id",
                (candidate, fid, seed.model_version_id, calibrator, cutoff, seed.bookmaker_id, price,
                 cutoff + timedelta(minutes=5), p, p, low))
            self.picks[name] = scalar(cur)
            cur.execute("UPDATE picks.picks SET status = %s WHERE id = %s", (status, self.picks[name]))
            self.price(name, price, AT - timedelta(minutes=30))

    def review(self, name: str, decision: str = "APPROVE", at: datetime | None = None, *,
               day_pass: bool = True) -> None:
        """PrediGol Intelligence looked at the match's pick (a combined review, rules only) - in the first pass of the
        match's day (``day_pass``): daily-set-v5 takes only selections reviewed in the 12 hours before whose match had
        its pass of the day (context-v2); parlay-v5 needs the review only (context-v1)."""
        when = at or AT - timedelta(minutes=10)
        self.cur.execute(
            "INSERT INTO ai.pick_reviews (reviewed_at, fixture_id, market_key, selection, line, engine, engine_version, "
            "input_hash, decision, confidence, output, mode, status) VALUES (%s, %s, '1X2', 'Home', 0, 'combined', "
            "'rules-review-v1+none', 'h', %s, 0.6, %s, 'shadow', 'ok')",
            (when, self.fixtures[name], decision, Jsonb({"reason": "revisión de prueba"})))
        if day_pass:
            self.day_pass(name, at=when)

    def day_pass(self, name: str, *, at: datetime | None = None, web: bool = False) -> None:
        """The first pass of the match's day (``ai.fixture_passes``), over at ``at``; ``web``: it searched the web."""
        when = at or AT - timedelta(minutes=10)
        self.cur.execute(
            "INSERT INTO ai.fixture_passes (fixture_id, day, pass, started_at, finished_at, kickoff_at, status, counts) "
            "SELECT id, (kickoff_at AT TIME ZONE 'America/Bogota')::date, 'first', %s, %s, kickoff_at, 'ok', %s "
            "FROM core.fixtures WHERE id = %s ON CONFLICT (fixture_id, day, pass) DO NOTHING",
            (when - timedelta(minutes=1), when, Jsonb({"web_searches": 2 if web else 0}), self.fixtures[name]))

    def review_all(self, at: datetime | None = None) -> None:
        for name in self.fixtures:
            self.review(name, at=at)

    def price(self, name: str, home: str, as_of: datetime) -> None:
        for sel, p_fair, odds in (("Home", "0.43", home), ("Draw", "0.28", "3.40"), ("Away", "0.29", "3.30")):
            self.cur.execute("INSERT INTO market.market_consensus (fixture_id,market_key,selection,line,as_of,"
                             "devig_method,p_fair,n_bookmakers,overround,best_odds,best_bookmaker_id) VALUES "
                             "(%s,'1X2',%s,0,%s,'shin',%s,5,0.05,%s,%s)",
                             (self.fixtures[name], sel, as_of, p_fair, odds, self.seed.bookmaker_id))

    def result(self, name: str, home: int, away: int) -> None:
        self.cur.execute("UPDATE core.fixtures SET status_short = 'FT', status_group = 'finished' WHERE id = %s",
                         (self.fixtures[name],))
        self.cur.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away) VALUES (%s, %s, %s)",
                         (self.fixtures[name], home, away))

    def items(self, source: str) -> list[tuple[Any, ...]]:
        return self.db.execute(
            "SELECT i.rank, i.fixture_id, i.odds, i.stage, i.status, i.profit_units FROM picks.daily_set_items i "
            "JOIN picks.daily_sets s ON s.id = i.set_id WHERE s.source = %s AND s.day = %s ORDER BY i.rank",
            (source, product_day(AT))).fetchall()


def test_the_day_is_chosen_frozen_and_settled(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    assert build_daily_sets(db, at=AT).items_added == 0, \
        "daily-set-v4/v5: no pick of the day that PrediGol Intelligence has not looked at"
    w.review_all()
    first = build_daily_sets(db, at=AT)
    f = w.fixtures
    qualified = w.items("qualified")
    assert [r[1] for r in qualified] == [f["F3"], f["F1"]], \
        "ranked by pessimistic growth; F2's uncertainty makes it not worth taking, F4-F6 are shadow"
    assert [r[3] for r in qualified] == ["T-6h", "T-3h"]
    evaluation = [r[1] for r in w.items("evaluation")]
    assert len(evaluation) == 5 and f["F2"] not in evaluation and f["F7"] not in evaluation
    assert first.items_added == 7

    # The price moves; the record does not, and nothing is added twice.
    w.price("F1", "2.80", AT + timedelta(minutes=50))
    again = build_daily_sets(db, at=AT + timedelta(hours=1))
    assert again.items_added == 0
    assert [str(r[2]) for r in w.items("qualified")] == ["2.100", "2.300"]

    # After the matches: F1 won at the frozen 2.30, F3 drawn.
    w.result("F1", 2, 0)
    w.result("F3", 1, 1)
    settled = settle_products(db, at=AT + timedelta(hours=9))
    assert settled.items >= 4
    rows = {r[1]: (r[4], r[5]) for r in w.items("qualified")}
    assert rows[f["F1"]] == ("WIN", Decimal("1.3000"))
    assert rows[f["F3"]] == ("LOSS", Decimal("-1.0000"))


def test_the_daily_parlay_grows_or_is_not_built_and_follows_its_legs(db: psycopg.Connection[Any],
                                                                      seed: Seed) -> None:
    w = World(db, seed)
    w.review_all()
    report = build_parlays(db, at=AT)
    assert report.built >= 1
    parlay = db.execute("SELECT id, status, combined_odds, expected_log_growth FROM picks.parlays WHERE kind = 'daily' "
                        "AND source = 'qualified' AND day = %s", (product_day(AT),)).fetchone()
    assert parlay is not None and parlay[1] == "READY"
    legs = [r[0] for r in db.execute("SELECT fixture_id FROM picks.parlay_legs WHERE parlay_id = %s ORDER BY leg_no",
                                     (parlay[0],)).fetchall()]
    assert set(legs) == {w.fixtures["F1"], w.fixtures["F3"]}, "F2 would lower the growth"
    assert parlay[2] == Decimal("4.830") and parlay[3] > 0
    assert build_parlays(db, at=AT + timedelta(minutes=30)).built == 0, "built once, then frozen"

    settle_products(db, at=AT + timedelta(hours=3))
    assert db.execute("SELECT status FROM picks.parlays WHERE id = %s", (parlay[0],)).fetchone() == ("ACTIVE",)
    w.result("F1", 2, 0)
    w.result("F3", 0, 1)
    settle_products(db, at=AT + timedelta(hours=9))
    assert db.execute("SELECT status, profit_units FROM picks.parlays WHERE id = %s",
                      (parlay[0],)).fetchone() == ("LOST", Decimal("-1.0000"))


def test_a_user_saves_picks_builds_a_parlay_and_reads_the_history(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    user = db.execute("INSERT INTO auth.users (email, display_name, password_hash) VALUES "
                      "('records@test.local', 'Records', '$argon2id$x') RETURNING id").fetchone()
    assert user is not None
    uid = int(user[0])
    f = w.fixtures
    saved = userdata.save_pick(db, user_id=uid, fixture_id=f["F4"], market_key="1X2", selection="Home",
                               line=Decimal(0), at=AT, user_odds=Decimal("2.45"))
    assert saved["snapshot"]["price"]["odds"] == "2.300"
    with pytest.raises(userdata.RecordError) as dup:
        userdata.save_pick(db, user_id=uid, fixture_id=f["F4"], market_key="1X2", selection="Home",
                           line=Decimal(0), at=AT)
    assert dup.value.code == "already_saved"
    with pytest.raises(userdata.RecordError) as shadow:
        userdata.save_pick(db, user_id=uid, fixture_id=f["F5"], market_key="1X2", selection="Home",
                           line=Decimal(0), at=AT, pick_id=w.picks["F5"])
    assert shadow.value.code == "unknown_pick", "a user cannot save a shadow pick as PrediGol's"
    from_pick = userdata.save_pick(db, user_id=uid, fixture_id=f["F1"], market_key="1X2", selection="Home",
                                   line=Decimal(0), at=AT, pick_id=w.picks["F1"])
    assert from_pick["snapshot"]["pick"]["status"] == "qualified"
    with pytest.raises(userdata.RecordError) as started:
        userdata.save_pick(db, user_id=uid, fixture_id=f["F1"], market_key="1X2", selection="Draw",
                           line=Decimal(0), at=AT + timedelta(hours=3))
    assert started.value.code == "started"

    bad = userdata.validate_parlay(db, [
        userdata.LegIn(f["F4"], "1X2", "Home", Decimal(0)), userdata.LegIn(f["F4"], "OU", "Over", Decimal("2.5")),
        userdata.LegIn(f["F5"], "AH", "Home", Decimal("-0.25"))], at=AT)
    assert not bad.ok and {e["code"] for e in bad.errors} == {"same_fixture", "quarter_line"}
    good = userdata.create_parlay(db, user_id=uid, name="Mi combinada", at=AT, legs=[
        userdata.LegIn(f["F4"], "1X2", "Home", Decimal(0)), userdata.LegIn(f["F5"], "1X2", "Home", Decimal(0))])
    assert good["combined_odds"] == Decimal("5.290")

    w.result("F1", 3, 1)
    w.result("F4", 1, 0)
    w.result("F5", 0, 0)
    report = settle_products(db, at=AT + timedelta(hours=12))
    assert report.user_picks == 2 and report.user_parlays == 1
    picks = dict(db.execute("SELECT fixture_id, profit_units FROM picks.user_picks WHERE user_id = %s",
                            (uid,)).fetchall())
    assert picks[f["F4"]] == Decimal("1.4500"), "settled at the price the user said they got"
    assert db.execute("SELECT status FROM picks.user_parlays WHERE id = %s", (good["id"],)).fetchone() == ("LOST",)

    hist = userdata.history(db, user_id=uid, period="7d", tz="America/Bogota", at=AT + timedelta(hours=12),
                            include_evaluation=False)
    mine = hist["my_picks"]
    assert (mine.total, mine.won, mine.lost) == (2, 2, 0)
    assert mine.profit == Decimal("2.7500") and mine.roi == pytest.approx(1.375)
    assert hist["my_parlays"].lost == 1


def test_a_parlay_never_built_is_void_once_its_day_is_over(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    w.review_all()
    build_parlays(db, at=AT)
    multiday = "SELECT id, status, window_from, window_to FROM picks.parlays WHERE kind = 'multiday' AND source = %s " \
               "AND day = %s"
    qualified = db.execute(multiday, ("qualified", product_day(AT))).fetchone()
    assert qualified is not None and qualified[1] == "BUILDING", "every qualified match is today: no two-day parlay"
    evaluation = db.execute(multiday, ("evaluation", product_day(AT))).fetchone()
    assert evaluation is not None and evaluation[1] == "READY", "F7 tomorrow makes a two-day parlay possible"
    assert (evaluation[2], evaluation[3]) == (AT, AT + timedelta(hours=72)), "the window its legs came from"
    assert w.fixtures["F7"] in [r[0] for r in db.execute(
        "SELECT fixture_id FROM picks.parlay_legs WHERE parlay_id = %s", (evaluation[0],)).fetchall()]

    report = build_parlays(db, at=AT + timedelta(hours=24))
    after = db.execute("SELECT status, profit_units, settled_at FROM picks.parlays WHERE id = %s",
                       (qualified[0],)).fetchone()
    assert after == ("VOID", Decimal("0.0000"), AT + timedelta(hours=24)), \
        "the day ended without one: the record says there was no parlay, not a parlay still being built"
    assert report.voided_unbuilt >= 1
    assert db.execute("SELECT status FROM picks.parlays WHERE id = %s", (evaluation[0],)).fetchone() == ("READY",), \
        "a built parlay is never voided for its day ending"


def test_the_preview_history_reads_the_evaluation_records_alone(db: psycopg.Connection[Any], seed: Seed) -> None:
    World(db, seed).review_all()
    build_daily_sets(db, at=AT)
    user = db.execute("INSERT INTO auth.users (email, display_name, password_hash) VALUES "
                      "('preview-history@test.local', 'Preview', '$argon2id$x') RETURNING id").fetchone()
    assert user is not None
    as_user = userdata.history(db, user_id=int(user[0]), period="today", tz="America/Bogota", at=AT,
                               include_evaluation=False)
    preview = userdata.history(db, user_id=int(user[0]), period="today", tz="America/Bogota", at=AT,
                               include_evaluation=True)
    assert as_user["predigol_picks"].total == 2
    assert preview["predigol_picks"].total == 5, "the evaluation set alone: the qualified items are not added again"
