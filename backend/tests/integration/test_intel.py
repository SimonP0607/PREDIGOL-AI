"""PrediGol Intelligence on a built world (``fbi.intel``): calibration from settled history, the decision layer at its
checkpoints, outcomes and closing-line value, post-mortems pm-v3, memory, the daily learning report, the leakage audit,
the runs' record and the append-only guard.

HISTORY: twelve Bogotá days of settled OU selections flagged by ``dixon_coles`` whose probability is 12 points too
high, while the de-vigged market is the true probability (outcomes are drawn from it). The calibrator must learn to
follow the market; the market's edge must NOT be validated (every price is 3 % under fair: closing-line value -3 %).

AT is 2032-09-20 12:00 UTC (07:00 Bogotá). One upcoming match at AT + 5 h with three candidates:
    OU 2.5 Over  model 0.66, best price 2.10 against a fair 0.50 -> calibrated EV about +10 %, but no validated
                 edge: INVESTIGACION
    OU 3.5 Over  best price 2.40 against a fair 0.38 -> calibrated EV negative: RECHAZADO
    BTTS Yes     no calibrator for (BTTS, dixon_coles): INVESTIGACION
The transaction is rolled back afterwards."""

from __future__ import annotations

import random
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest

from fbi.ai.calendar import local_day
from fbi.intel import calibration, cycle, decision, leakage, memory, outcomes, postmortem, report

from .conftest import Seed
from .helpers import scalar

AT = datetime(2032, 9, 20, 12, tzinfo=UTC)
PICK_COLS = (
    "candidate_id,fixture_id,market_key,selection,line,model_version_id,calibrator_id,"
    "feature_set_hash,data_cutoff_ts,decision_rule_version,code_version,bookmaker_id,"
    "market_odds,odds_captured_at,p_model,p_calibrated,p_calibrated_lo,p_calibrated_hi,"
    "p_market_fair,fair_odds,edge,price_edge,ev,ev_adjusted,kelly_fraction,stake_units,"
    "selection_reason,created_at"
)


class IntelWorld:
    def __init__(self, db: psycopg.Connection[Any], seed: Seed) -> None:
        self.db, self.seed = db, seed
        self.cur = db.cursor()
        cur = self.cur
        cur.execute("INSERT INTO market.markets (key,name,n_outcomes,has_line,is_exclusive) VALUES "
                    "('OU','Goals Over/Under',2,true,true),('BTTS','Both Teams Score',2,false,true) "
                    "ON CONFLICT (key) DO NOTHING")
        cur.execute("INSERT INTO core.competitions (provider_league_id, name, country, type, entity_scope, "
                    "competition_type, is_tracked) VALUES (98801, 'Intel League', 'Colombia', 'league', 'club', "
                    "'domestic_league', true) RETURNING id")
        self.competition = scalar(cur)
        cur.execute("INSERT INTO core.competition_seasons (competition_id, season, is_current) VALUES (%s, 2032, true) "
                    "RETURNING id", (self.competition,))
        self.season = scalar(cur)
        cur.execute(
            "INSERT INTO models.calibrators (model_version_id,market_key,scope,method,params,n_train,train_from,"
            "train_to,n_val,val_from,val_to,val_ece,val_mce,val_brier,val_logloss,reliability_weight) VALUES "
            "(%s,'OU','global','isotonic','{}',1000,'2020-01-01','2024-06-30',500,'2024-07-01','2025-06-30',"
            "0.018,0.04,0.19,0.58,0.82) RETURNING id", (seed.model_version_id,))
        self.model_calibrator = scalar(cur)
        self.n_teams = 0
        self.n_fixtures = 0

    def team(self) -> int:
        self.n_teams += 1
        self.cur.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (%s, %s) RETURNING id",
                         (988000 + self.n_teams, f"Intel Team {self.n_teams}"))
        return int(scalar(self.cur))

    def fixture(self, kickoff: datetime) -> int:
        self.n_fixtures += 1
        self.cur.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, "
                         "away_team_id, kickoff_at) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                         (9880000 + self.n_fixtures, self.season, self.team(), self.team(), kickoff))
        return int(scalar(self.cur))

    def pick(self, fid: int, market: str, selection: str, line: str, *, p_model: float, p_market: float, odds: float,
             created: datetime) -> int:
        cur = self.cur
        cutoff = created - timedelta(hours=2)
        cur.execute("INSERT INTO models.predictions (fixture_id,model_version_id,calibrator_id,market_key,selection,"
                    "line,p_raw,p_calibrated,p_lo,p_hi,feature_set_hash,data_cutoff_ts) VALUES "
                    "(%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'fh',%s) RETURNING id",
                    (fid, self.seed.model_version_id, self.model_calibrator, market, selection, line, p_model, p_model,
                     max(0.01, p_model - 0.05), min(0.99, p_model + 0.05), cutoff))
        prediction = scalar(cur)
        cur.execute("INSERT INTO picks.pick_candidates (run_id,fixture_id,prediction_id,market_key,selection,line,"
                    "bookmaker_id,market_odds,p_calibrated,p_market_fair,edge,price_edge,ev,ev_adjusted,decision) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,0.05,0.01,0.05,0.04,'selected') RETURNING id",
                    (self.seed.run_id, fid, prediction, market, selection, line, self.seed.bookmaker_id, odds, p_model,
                     p_market))
        candidate = scalar(cur)
        cur.execute(f"INSERT INTO picks.picks ({PICK_COLS}) VALUES (%s,%s,%s,%s,%s,%s,%s,'fh',%s,'shadow-rule-v2',"
                    "'abc',%s,%s,%s,%s,%s,%s,%s,%s,2.0,0.05,0.01,0.05,0.04,0.01,1,'{}',%s) RETURNING id",
                    (candidate, fid, market, selection, line, self.seed.model_version_id, self.model_calibrator,
                     cutoff, self.seed.bookmaker_id, odds, created - timedelta(minutes=1), p_model, p_model,
                     max(0.01, p_model - 0.05), min(0.99, p_model + 0.05), p_market, created))
        return int(scalar(cur))

    def settle(self, pick: int, won: bool, at: datetime) -> None:
        self.cur.execute("INSERT INTO picks.pick_results (pick_id,result_status,profit_units,settled_at,"
                         "settlement_basis,rule_version) VALUES (%s,%s,%s,%s,'regulation_90','settle-v3')",
                         (pick, "win" if won else "loss", 1 if won else -1, at))

    def line_value(self, pick: int, odds: float, p_close: float, kickoff: datetime) -> None:
        self.cur.execute("INSERT INTO picks.pick_line_value (pick_id, near_close_odds, near_close_captured_at, "
                         "near_close_source, near_close_minutes_to_ko, lv_raw, lv_devigged) VALUES "
                         "(%s,%s,%s,'prematch',5,0,%s)", (pick, odds, kickoff - timedelta(minutes=5),
                                                          round(odds * p_close - 1, 6)))

    def consensus(self, fid: int, market: str, selection: str, line: str, *, p_fair: float, best: float,
                  as_of: datetime, books: int = 6) -> None:
        self.cur.execute("INSERT INTO market.market_consensus (fixture_id,market_key,selection,line,as_of,devig_method,"
                         "p_fair,n_bookmakers,overround,best_odds,best_bookmaker_id) VALUES "
                         "(%s,%s,%s,%s,%s,'shin',%s,%s,0.05,%s,%s)",
                         (fid, market, selection, line, as_of, p_fair, books, best, self.seed.bookmaker_id))

    def history(self, days: int = 12, per_day: int = 60, seed: int = 11) -> int:
        rng = random.Random(seed)
        n = 0
        for d in range(days, 0, -1):
            kickoff_base = AT - timedelta(days=d)
            for k in range(per_day // 10):
                fid = self.fixture(kickoff_base + timedelta(minutes=10 * k))
                for j, line in enumerate(("0.5", "1.5", "2.5", "3.5", "4.5")):
                    for selection in ("Over", "Under"):
                        p_mkt = rng.uniform(0.3, 0.7)
                        odds = round(0.97 / p_mkt, 3)
                        p_model = min(0.95, p_mkt + 0.12)
                        ko = kickoff_base + timedelta(minutes=10 * k)
                        pid = self.pick(fid, "OU", selection, line, p_model=p_model, p_market=p_mkt, odds=odds,
                                        created=ko - timedelta(hours=3))
                        self.settle(pid, rng.random() < p_mkt, ko + timedelta(hours=2))
                        self.line_value(pid, odds, p_mkt, ko)
                        n += 1
                        _ = j
        return n


@pytest.fixture()
def world(db: psycopg.Connection[Any], seed: Seed) -> IntelWorld:
    return IntelWorld(db, seed)


def small_gates(monkeypatch: pytest.MonkeyPatch) -> None:
    """The gates' sample sizes scaled to a test world (the rules themselves unchanged)."""
    monkeypatch.setattr(calibration, "MIN_TRAIN", 100)
    monkeypatch.setattr(calibration, "MIN_OOS_N", 300)
    monkeypatch.setattr(calibration, "MIN_OOS_DAYS", 5)
    monkeypatch.setattr(calibration, "MIN_RULE_N", 50)
    monkeypatch.setattr(calibration, "MAX_ECE", 0.08)
    monkeypatch.setattr(calibration, "MAX_LOSS_VS_MARKET", 0.01)


def test_the_schema_is_append_only_and_alerts_at_50(db: psycopg.Connection[Any], world: IntelWorld) -> None:
    cur = db.cursor()
    cur.execute("INSERT INTO intel.promotions (at, entity, market_key, model_name, to_role, gate_version, criteria, "
                "reason, decided_by) VALUES (%s, 'market_edge', 'OU', 'dixon_coles', 'NOT_VALIDATED', 'edge-gate-v1', "
                "'{}', 'test', 'system') RETURNING id", (AT,))
    pid = scalar(cur)
    with pytest.raises(psycopg.errors.CheckViolation):
        cur.execute("UPDATE intel.promotions SET reason = 'rewritten' WHERE id = %s", (pid,))
    db.rollback()
    cur = db.cursor()
    cur.execute("INSERT INTO ai.budget_alerts (month, threshold, created_at, spent_usd, budget_usd) "
                "VALUES ('2032-09-01', 50, %s, 90, 180) RETURNING threshold", (AT,))
    assert scalar(cur) == 50


def test_calibration_learns_the_market_and_does_not_validate_an_edge(
        db: psycopg.Connection[Any], world: IntelWorld, monkeypatch: pytest.MonkeyPatch) -> None:
    small_gates(monkeypatch)
    n = world.history()
    obs = calibration.load_observations(db, cutoff=AT)
    assert len(obs) == n
    # no leakage: a cutoff in the middle sees only what was settled before it
    mid = AT - timedelta(days=6)
    assert all(o.settled_at < mid for o in calibration.load_observations(db, cutoff=mid))
    wf = calibration.walk_forward(obs, "logit2")
    assert wf.n > 300 and wf.days >= 5
    assert wf.logloss_cal is not None and wf.logloss_raw is not None
    assert wf.logloss_cal < wf.logloss_raw - 0.005, "the overconfidence is corrected out of sample"
    assert wf.rule_clv is not None and wf.rule_clv < 0, "every price was under fair: no edge"
    rep = calibration.run_calibration(db, at=AT, commit=False)
    assert rep.fitted == 3
    assert rep.promoted and rep.promoted[0].startswith("OU/dixon_coles:")
    assert rep.edge_changes == ["OU/dixon_coles:NOT_VALIDATED"]
    state = calibration.calibration_state(db, at=AT + timedelta(minutes=1))
    champ = state.champions[("OU", "dixon_coles")]
    assert champ.method in ("logit2", "platt")
    assert state.edge[("OU", "dixon_coles")] is False
    p = champ.apply(0.62, 0.50)
    assert p is not None and abs(p - 0.50) < 0.08, "it follows the market, not the overconfident model"
    # a second run the same day refits nothing (the champion is fresh) and promotes nothing
    again = calibration.run_calibration(db, at=AT + timedelta(minutes=5), commit=False)
    assert again.fitted == 0 and not again.promoted


def test_the_decision_layer_end_to_end(db: psycopg.Connection[Any], world: IntelWorld,
                                       monkeypatch: pytest.MonkeyPatch) -> None:
    small_gates(monkeypatch)
    world.history()
    calibration.run_calibration(db, at=AT - timedelta(hours=1), commit=False)
    ko = AT + timedelta(hours=5)
    fid = world.fixture(ko)
    created = AT - timedelta(minutes=30)
    over25 = world.pick(fid, "OU", "Over", "2.5", p_model=0.66, p_market=0.50, odds=2.10, created=created)
    over35 = world.pick(fid, "OU", "Over", "3.5", p_model=0.50, p_market=0.38, odds=2.40, created=created)
    btts = world.pick(fid, "BTTS", "Yes", "0", p_model=0.66, p_market=0.52, odds=2.05, created=created)
    as_of = AT - timedelta(minutes=10)
    world.consensus(fid, "OU", "Over", "2.5", p_fair=0.50, best=2.10, as_of=as_of)
    world.consensus(fid, "OU", "Over", "3.5", p_fair=0.38, best=2.40, as_of=as_of)
    world.consensus(fid, "BTTS", "Yes", "0", p_fair=0.52, best=2.05, as_of=as_of)

    rep, evaluated = decision.decide(db, at=AT)
    states = {(e.key[1], e.key[2], str(e.key[3])): e for e in evaluated}
    e25, e35, eb = states[("OU", "Over", "2.50")], states[("OU", "Over", "3.50")], states[("BTTS", "Yes", "0.00")]
    assert e25.state == "INVESTIGACION" and "edge_not_validated" in e25.reasons, e25.reasons
    assert e25.ev_cal is not None and e25.ev_cal > 0.02 and e25.ev_raw is not None and e25.ev_raw > e25.ev_cal
    assert e35.state == "RECHAZADO" and "ev_cal_below" in e35.reasons, e35.reasons
    assert eb.state == "INVESTIGACION" and "not_calibrated" in eb.reasons
    assert e25.stake.units == 0 and e35.stake.units == 0, "no stake without approval"
    assert e25.context.status == "PENDING", "PrediGol Intelligence has not read the match yet"
    assert e25.checkpoint == "T-6h"
    assert len([f for f in e25.filters if f["key"] != "correlation"]) >= 9
    assert e25.score is not None and 0 < e25.score.total < 100
    assert rep.written == 3

    # idempotent: the same moment writes nothing; a later checkpoint writes the live ones again, not the rejected
    again, _ = decision.decide(db, at=AT)
    assert again.written == 0
    later, _ = decision.decide(db, at=AT + timedelta(hours=2, minutes=30))  # T-3h, same price
    assert later.written == 2

    # nothing approved: no pick of the day, honestly
    assert decision.select_day(db, at=AT + timedelta(hours=1), ready=True) == (0, 0)

    # the match is played: 2-1, Over 2.5 wins, Over 3.5 loses, BTTS yes wins
    db.execute("UPDATE core.fixtures SET status_short = 'FT', status_group = 'finished' WHERE id = %s", (fid,))
    db.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away) VALUES (%s, 2, 1)", (fid,))
    world.consensus(fid, "OU", "Over", "2.5", p_fair=0.52, best=2.05, as_of=ko - timedelta(minutes=5))
    settled = ko + timedelta(hours=2)
    world.settle(over25, True, settled)
    world.settle(over35, False, settled)
    world.settle(btts, True, settled)
    after = settled + timedelta(minutes=5)
    assert outcomes.settle_decisions(db, at=after) == 5
    row = db.execute("SELECT o.result_status, o.profit_flat, o.clv FROM intel.decision_outcomes o JOIN intel.decisions d "
                     "ON d.id = o.decision_id WHERE d.market_key = 'OU' AND d.line = 2.5 ORDER BY d.id DESC LIMIT 1"
                     ).fetchone()
    assert row is not None and row[0] == "win" and row[1] == Decimal("1.1000")
    assert row[2] == Decimal("0.092000"), "2.10 x the closing fair 0.52 - 1"
    assert outcomes.settle_decisions(db, at=after) == 0, "an outcome is written once"

    pms = postmortem.run_postmortems(db, at=after)
    assert pms == 2, "the two INVESTIGACION selections (top of the day); the rejected one is not reviewed"
    pm = db.execute("SELECT verdict, decision_quality FROM intel.postmortems p JOIN intel.decisions d "
                    "ON d.id = p.decision_id WHERE d.market_key = 'OU'").fetchone()
    assert pm == ("MERECIDO", "GOOD")

    day = local_day(ko)
    assert memory.build_memory(db, day=day, at=after) >= 4
    mem = db.execute("SELECT stats FROM intel.entity_memory WHERE entity_type = 'market' AND entity_id = 'OU' "
                     "AND as_of_day = %s", (day,)).fetchone()
    assert mem is not None and mem[0]["decisions"] == 1 and mem[0]["wins"] == 1 and mem[0]["last10"] == ["W"]
    assert memory.build_memory(db, day=day, at=after) == 0, "a day's memory is written once"

    audit = leakage.audit_day(db, day=local_day(AT), at=after)
    assert all(v["violations"] == 0 for v in audit.values()), audit
    assert audit["pick_known"]["checked"] >= 5

    rid = report.write_report(db, day=day, at=after)
    assert rid is not None
    text = db.execute("SELECT text, content FROM intel.daily_reports WHERE id = %s", (rid,)).fetchone()
    assert text is not None and "DAILY LEARNING REPORT" in text[0]
    assert text[1]["decisions"]["by_state"]["INVESTIGACION"] == 2
    assert report.write_report(db, day=day, at=after + timedelta(minutes=1)) is None, "same content: no revision"


def test_runs_are_recorded_and_recovered(migrated_database: str, seed: Seed) -> None:
    """A run commits its own record (its own connection here, cleaned up after)."""
    with psycopg.connect(migrated_database) as conn:
        try:
            r = cycle.run_decide(conn, at=AT)
            assert r.status in ("ok", "partial") and r.run_id is not None
            row = conn.execute("SELECT status, finished_at IS NOT NULL, versions->>'decision' FROM intel.runs "
                               "WHERE id = %s", (r.run_id,)).fetchone()
            assert row == (r.status, True, decision.VERSION)
            conn.execute("INSERT INTO intel.runs (job, started_at, status) VALUES ('nightly', %s, 'running')",
                         (AT - timedelta(hours=1),))
            conn.commit()
            assert cycle.recover_interrupted(conn, before=AT) == 1
            assert conn.execute("SELECT count(*) FROM intel.runs WHERE status = 'interrupted'").fetchone() == (1,)
        finally:
            conn.rollback()
            conn.execute("DELETE FROM intel.runs")
            conn.commit()


def test_a_day_without_decisions_says_so(db: psycopg.Connection[Any]) -> None:
    """The first production report (13 Oct 2026, for 11 and 12 Oct, before the decision layer existed) read
    "0 selecciones evaluadas — ." and "Contexto: ; ...": the empty day now says what it is."""
    content = report.build_report(db, day=date(2031, 1, 1), at=datetime(2031, 1, 3, tzinfo=UTC))
    text = report.render(content)
    assert "ninguna registrada" in text and "— ." not in text and "**Contexto:** ;" not in text


def test_discovery_reads_an_active_markets_priced_history(db: psycopg.Connection[Any], seed: Seed,
                                                          tmp_path: Any) -> None:
    """discovery-v1 on the database. Regression (13 Oct 2026): the catalogue was loaded on one day for all 338 bets,
    so every market - the five active ones too, priced since 2022 - failed "history" (>= 28 days)."""
    from fbi.intel import discovery

    at = datetime.now(UTC) + timedelta(days=1)
    db.execute("UPDATE market.provider_markets SET first_seen_at = %s, last_seen_at = %s",
               (at - timedelta(days=2), at - timedelta(days=1)))
    db.execute("INSERT INTO market.historical_odds (fixture_id, source, bookmaker_code, market_key, selection, line, "
               "price_kind, odds_decimal, source_payload_hash) VALUES (%s, 'test', 'PS', 'OU', 'Over', 2.5, "
               "'closing', 1.9, %s)", (seed.fixture_id, seed.payload_hash))
    kickoff = db.execute("SELECT kickoff_at FROM core.fixtures WHERE id = %s", (seed.fixture_id,)).fetchone()
    assert kickoff is not None
    run = db.execute("INSERT INTO intel.runs (job, started_at, status) VALUES ('weekly', %s, 'running') RETURNING id",
                     (at,)).fetchone()[0]  # not cycle.open_run: it commits, and this test must leave nothing behind
    discovery.run_discovery(db, at=at, run_id=run, root=tmp_path)
    crit = {int(r[0]): r[1] for r in db.execute("SELECT provider_bet_id, criteria FROM intel.market_registry "
                                                 "WHERE run_id = %s", (run,)).fetchall()}
    assert crit[5]["history"] == {"ok": (at - kickoff[0]).days >= 28, "value": (at - kickoff[0]).days}
    assert crit[8]["history"] == {"ok": False, "value": 2}, "no stored prices: the catalogue's date only"
