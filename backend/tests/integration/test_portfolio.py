"""portfolio-v1 (IA-013, shadow) against the real schema: the day's decision-v1 rows read the way select_day reads them (the newest per
selection known by the moment, of the day's matches, more than ten minutes before kick-off; nothing of another layer or another day),
mapped through state-v2 and built into the shadow portfolio. Read-only: the transaction writes nothing.

Every test builds its own competitions, teams, matches and decisions (``PortfolioWorld``): nothing here reads or moves the session's
shared seed match. The transaction is rolled back afterwards."""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb
from scripts import ia_portfolio as cli

from fbi.intel import stake as staking
from fbi.portfolio import build, correlation

from .helpers import scalar

pytestmark = pytest.mark.integration

AT = datetime(2033, 3, 15, 15, tzinfo=UTC)  # 10:00 Bogotá
DAY = date(2033, 3, 15)
WRITES_SQL = "SELECT COALESCE(sum(n_tup_ins + n_tup_upd + n_tup_del), 0) FROM pg_stat_xact_user_tables"


class PortfolioWorld:
    def __init__(self, db: psycopg.Connection[Any]) -> None:
        self.db = db
        self.cur = db.cursor()
        self.n = 0

    def competition(self, provider_league_id: int, name: str) -> int:
        """A competition and its season; a provider id another test may already hold is reused."""
        self.cur.execute("SELECT id FROM core.competitions WHERE provider_league_id = %s", (provider_league_id,))
        row = self.cur.fetchone()
        if row is None:
            self.cur.execute("INSERT INTO core.competitions (provider_league_id, name, country, type, entity_scope, competition_type, "
                             "is_tracked) VALUES (%s, %s, 'Testland', 'league', 'club', 'domestic_league', true) RETURNING id",
                             (provider_league_id, name))
            row = self.cur.fetchone()
        assert row is not None
        self.cur.execute("INSERT INTO core.competition_seasons (competition_id, season, is_current) VALUES (%s, 2033, true) RETURNING id",
                         (int(row[0]),))
        return int(scalar(self.cur))

    def team(self) -> int:
        self.n += 1
        self.cur.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (%s, %s) RETURNING id",
                         (977000 + self.n, f"Portfolio Team {self.n}"))
        return int(scalar(self.cur))

    def fixture(self, season: int, kickoff: datetime) -> int:
        self.n += 1
        self.cur.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at) "
                         "VALUES (%s, %s, %s, %s, %s) RETURNING id", (9770000 + self.n, season, self.team(), self.team(), kickoff))
        return int(scalar(self.cur))

    def decision(self, fid: int, state: str, *, market: str = "1X2", selection: str = "Home", line: str = "0",
                 known: datetime = AT - timedelta(minutes=10), odds: str = "2.050", p_cal: str = "0.600000",
                 score: float = 60.0, reasons: tuple[str, ...] = (), version: str = "decision-v1", premium: bool = False) -> int:
        self.n += 1
        self.cur.execute(
            "INSERT INTO intel.decisions (decision_version, known_at, checkpoint, fixture_id, kickoff_at, market_key, selection, line, "
            "model_name, odds, price_at, n_bookmakers, p_model, p_low, p_high, p_push, p_cal, p_market, filters, state, reasons, premium, "
            "parlay_eligible, score, stake_units, context_status, input_hash) "
            "SELECT %s, %s, 'T-3h', f.id, f.kickoff_at, %s, %s, %s, 'dixon_coles', %s, %s, 4, %s, 0.55, 0.65, 0, %s, 0.48, %s, %s, %s, "
            "%s, true, %s, 0, 'FULL', %s FROM core.fixtures f WHERE f.id = %s RETURNING id",
            (version, known, market, selection, line, odds, known - timedelta(minutes=5), p_cal, p_cal, Jsonb([]), state,
             list(reasons), premium, score, f"portfolio-{self.n}", fid))
        return int(scalar(self.cur))

    def estimate(self, market: str, rho: float, se: float, n_groups: int) -> None:
        self.cur.execute("INSERT INTO ai.correlation_estimates (estimated_at, scope, market, rho, se, n_groups, n_matches, window_from, "
                         "window_to, version) VALUES (%s, 'same_competition_day', %s, %s, %s, %s, %s, '2030-01-01', '2033-01-01', 'icc-v1')",
                         (AT - timedelta(days=1), market, rho, se, n_groups, 5 * n_groups))


@pytest.fixture()
def w(db: psycopg.Connection[Any]) -> PortfolioWorld:
    return PortfolioWorld(db)


def writes(db: psycopg.Connection[Any]) -> int:
    row = db.execute(WRITES_SQL).fetchone()
    assert row is not None
    return int(row[0])


def test_a_day_without_recommended_says_so_and_the_what_if_is_hypothetical(w: PortfolioWorld) -> None:
    season = w.competition(97701, "Portfolio Quiet League")
    a, b, c = (w.fixture(season, AT + timedelta(hours=h)) for h in (4, 5, 6))
    w.decision(a, "CAUTELA", reasons=("risk",))
    w.decision(b, "INVESTIGACION", reasons=("price_stale",))
    w.decision(c, "RECHAZADO", reasons=("ev_cal_below",))
    before = writes(w.db)
    doc = build.build_day(w.db, DAY, at=AT)
    assert doc["counts"]["by_state_v2"] == {"RECOMMENDED": 0, "CAUTION": 1, "WATCH": 1, "ABSTAIN": 0, "REJECTED": 1}
    assert doc["message"].startswith("No RECOMMENDED selection for 2033-03-15") and doc["selections"] == []
    assert doc["day_set"] == [] and doc["pick_of_the_day"] is None and doc["parlays"]["built"] == []
    hypo = build.build_day(w.db, DAY, at=AT, what_if=True)
    assert hypo["hypothetical"] is True and hypo["mode"] == build.MODE_WHAT_IF
    [only] = hypo["selections"]
    assert only["hypothetical"] and only["stake"]["final_units"] == staking.CAPS["CAUTELA"] and only["stake"]["hypothetical"]
    assert writes(w.db) == before, "read-only"


def test_the_day_portfolio_from_the_rows_select_day_reads(w: PortfolioWorld) -> None:
    top = w.competition(135, "Serie A")  # comp-priority-v1 group 1
    other = w.competition(97702, "Portfolio Other League")
    f1, f2 = w.fixture(top, AT + timedelta(hours=4)), w.fixture(top, AT + timedelta(hours=4, minutes=30))
    f3 = w.fixture(other, AT + timedelta(hours=7))
    tomorrow = w.fixture(other, AT + timedelta(hours=16))  # 02:00 Bogotá of the next day
    d1 = w.decision(f1, "APROBADO", score=60.0)
    d2 = w.decision(f2, "APROBADO", score=58.0)
    w.decision(f3, "RECHAZADO", reasons=("ev_cal_below",), known=AT - timedelta(hours=2))
    d3 = w.decision(f3, "APROBADO", score=95.0)  # newer: the one read
    w.decision(f3, "APROBADO", score=99.0, version="decision-fam-v1")  # another layer: never read
    w.decision(tomorrow, "APROBADO", score=99.0)
    w.decision(f1, "APROBADO", score=99.0, market="OU", selection="Over", line="2.5", known=AT + timedelta(minutes=5))  # after `at`
    before = writes(w.db)
    doc = build.build_day(w.db, DAY, at=AT)
    assert writes(w.db) == before, "read-only"
    ids = [s["decision_id"] for s in doc["selections"]]
    assert ids == [d1, d2, d3], "RECOMMENDED only, in the day's order: the priority group first, then the score"
    st = {s["decision_id"]: s["stake"] for s in doc["selections"]}
    v1 = staking.stake_for("APROBADO", 0.6, 2.05)
    assert all(x["individual"]["units"] == v1.units for x in st.values())
    pair = next(c for c in doc["correlations"] if {c["a"], c["b"]} == {d1, d2})
    assert pair["source"] == "same_league_window" and pair["shares_budget"]
    assert st[d1]["final_units"] == st[d2]["final_units"] == 0.75 and st[d3]["final_units"] == v1.units
    assert doc["budget_groups"] == [[d1, d2]]
    assert [d["decision_id"] for d in doc["day_set"]] == [d1, d2, d3] and doc["pick_of_the_day"]["decision_id"] == d1
    [parlay] = doc["parlays"]["built"]
    legs = {leg["decision_id"] for leg in parlay["legs"]}
    assert d3 in legs and len(legs & {d1, d2}) == 1, "one competition's matchday is not combined without a measured dependence"
    assert parlay["stake"]["final_units"] <= staking.PARLAY_CAP

    w.estimate("home_win", 0.20, 0.02, 40)
    measured = build.build_day(w.db, DAY, at=AT)
    pair = next(c for c in measured["correlations"] if {c["a"], c["b"]} == {d1, d2})
    assert (pair["source"], pair["rho"]) == ("measured_icc", 0.2)
    assert {s["decision_id"]: s["stake"]["final_units"] for s in measured["selections"]}[d1] == 0.75
    [parlay] = measured["parlays"]["built"]
    assert {leg["decision_id"] for leg in parlay["legs"]} == {d1, d2, d3}, "measured now: the guard lets the matchday combine"
    assert "icc-v1 estimates" in parlay["correlation"]["method"]
    assert correlation.VERSION in measured["versions"].values()


def test_the_command_reports_the_day_as_json(w: PortfolioWorld) -> None:
    season = w.competition(97703, "Portfolio Command League")
    d = w.decision(w.fixture(season, AT + timedelta(hours=5)), "PICK_PREMIUM", premium=True, odds="2.400", p_cal="0.620000",
                   score=85.0)
    doc, code = cli.run(w.db, day=DAY, at=AT)
    assert code == cli.OK and json.loads(json.dumps(doc, default=str))["version"] == "portfolio-v1"
    [s] = doc["selections"]
    assert s["decision_id"] == d and s["label"] == "PICK_PREMIUM" and s["stake"]["stake_v1_state"] == "PICK_PREMIUM"
    assert s["stake"]["final_units"] <= staking.CAPS["PICK_PREMIUM"]
    text = cli.render(doc)
    assert f"#{d}" in text and "pick of the day: #" in text
    empty, _ = cli.run(w.db, day=date(2033, 3, 20), at=AT)
    assert "No RECOMMENDED" in cli.render(empty)
