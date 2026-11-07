"""``sim-v1`` (IA-013, shadow) against the real schema, on a world of its OWN (not the session's shared seed): a day with three fixtures,
the goal models' and the Elo model's real-time forecasts stored the way the forecast writer stores them, an older version and a forecast
made after kick-off that are not in force, and one model whose double chance disagrees with its own 1X2. The check reads what is in force,
recovers the intensities, compares and lists the incoherence - and writes nothing. The transaction is rolled back afterwards."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from scripts import ia_simulator as cli

from fbi.models.lines import asian_handicap, double_chance, over_under
from fbi.models.scoring import MARKET_ROWS, dc_tau, from_matrix, poisson_matrix
from fbi.simulator import consistency

pytestmark = pytest.mark.integration

DAY = datetime.fromisoformat("2031-03-12T00:00:00-05:00").date()  # a Bogotá day nothing else in the suite uses
KO = datetime.fromisoformat("2031-03-12T20:00:00+00:00")
CUTOFF = KO - timedelta(hours=6)
NOW = KO + timedelta(days=1)


def one(cur: psycopg.Cursor[Any], sql: str, *args: Any) -> Any:
    row = cur.execute(sql, args).fetchone()
    assert row is not None
    return row[0]


def rows_of(lh: float, la: float, rho: float | None) -> list[tuple[str, str, float, float, float]]:
    """(market, selection, line, p_win, p_push) as ``fbi.predictions.forecast`` writes them for a goal model, at 6 decimals."""
    m = poisson_matrix(lh, la)
    if rho is not None:
        m = dc_tau(m, lh, la, rho)
    out = [(mk, s, ln, round(v, 6), 0.0) for (mk, s, ln), v in zip(MARKET_ROWS, from_matrix(m, lh, la).as_rows(), strict=True)]
    for line in ("-1", "-0.75", "-0.25", "0", "0.5"):
        for side, ln in (("Home", Decimal(line)), ("Away", -Decimal(line))):
            o = asian_handicap(m, selection=side, line=ln)
            out.append(("AH", side, float(ln), round(o.win, 6), round(o.push, 6)))
    for line in ("1.5", "2.25", "3"):
        for side in ("Over", "Under"):
            o = over_under(m, selection=side, line=Decimal(line))
            out.append(("OU", side, float(line), round(o.win, 6), round(o.push, 6)))
    out += [("DC", s, 0.0, round(v, 6), 0.0) for s, v in double_chance(m).items()]
    return out


class World:
    def __init__(self, conn: psycopg.Connection[Any]) -> None:
        self.conn = conn
        cur = self.cur = conn.cursor()
        comp = one(cur, "INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type) "
                        "VALUES (99013, 'Simulator League', 'league', 'club', 'domestic_league') RETURNING id")
        season = one(cur, "INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, 2031) RETURNING id", comp)
        teams = [one(cur, "INSERT INTO core.teams (provider_team_id, name) VALUES (%s, %s) RETURNING id", 99130 + i, f"Sim {i}")
                 for i in range(6)]
        self.fixtures = [one(cur, "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
                                  "kickoff_at) VALUES (%s, %s, %s, %s, %s) RETURNING id", 990130 + i, season, teams[2 * i], teams[2 * i + 1],
                                  KO + timedelta(minutes=30 * i)) for i in range(3)]
        self.versions: dict[tuple[str, str], int] = {}

    def version(self, model: str, tag: str) -> int:
        family = "rating" if model == "elo_ologit" else "goals"
        mid = one(self.cur, "INSERT INTO models.model_registry (name, family, description) VALUES (%s, %s, 'sim test') "
                            "ON CONFLICT (name) DO UPDATE SET name = EXCLUDED.name RETURNING id", model, family)
        vid = int(one(self.cur, "INSERT INTO models.model_versions (model_id, version, train_from, train_to, n_train, code_version) "
                                "VALUES (%s, %s, '2030-01-01', '2031-03-01', 500, 'sim') RETURNING id", mid, f"sim-test-{tag}"))
        self.versions[(model, tag)] = vid
        return vid

    def forecast(self, fixture: int, version: int, rows: list[tuple[str, str, float, float, float]], *,
                 cutoff: datetime = CUTOFF) -> None:
        for mk, sel, line, p, push in rows:
            self.cur.execute("INSERT INTO models.predictions (fixture_id, model_version_id, market_key, selection, line, p_raw, p_calibrated, "
                             "feature_set_hash, data_cutoff_ts, p_push) VALUES (%s, %s, %s, %s, %s, %s, %s, 'sim', %s, %s)",
                             (fixture, version, mk, sel, line, p, p, cutoff, push))

    def standard(self) -> None:
        a, b, _ = self.fixtures
        old = self.version("poisson", "old")
        self.forecast(a, old, rows_of(2.5, 0.5, None), cutoff=CUTOFF - timedelta(days=1))  # an older forecast: not in force
        self.forecast(a, self.version("poisson", "now"), rows_of(1.6, 1.05, None))
        self.forecast(a, self.version("poisson", "late"), rows_of(0.6, 2.4, None), cutoff=KO + timedelta(minutes=5))  # after kick-off
        self.forecast(a, self.version("dixon_coles", "now"), rows_of(1.55, 1.1, -0.09))
        self.forecast(a, self.version("elo_ologit", "now"), [("1X2", "Home", 0.0, 0.47, 0.0), ("1X2", "Draw", 0.0, 0.27, 0.0),
                                                             ("1X2", "Away", 0.0, 0.26, 0.0)])
        bad = [(mk, s, ln, round(p + 0.03, 6) if (mk, s) == ("DC", "1X") else p, push) for mk, s, ln, p, push in rows_of(1.2, 1.3, -0.05)]
        self.forecast(b, self.version("dixon_coles", "b"), bad)


@pytest.fixture()
def world(migrated_database: str) -> Iterator[World]:
    conn = psycopg.connect(migrated_database, options="-c TimeZone=UTC")
    try:
        yield World(conn)
    finally:
        conn.rollback()
        conn.close()


def fixture_doc(doc: dict[str, Any], fixture_id: int) -> dict[str, Any]:
    return next(f for f in doc["fixtures"] if f["fixture_id"] == fixture_id)


def model_doc(f: dict[str, Any], model: str) -> dict[str, Any]:
    return next(m for m in f["models"] if m["model"] == model)


def test_the_day_against_the_models_in_force(world: World) -> None:
    world.standard()
    a, b, c = world.fixtures
    doc = consistency.check_day(world.conn, DAY, now=NOW)
    assert doc["version"] == "sim-v1" and doc["shadow"] is True and doc["constants"]["max_half_goals"] == 10
    ids = {f["fixture_id"] for f in doc["fixtures"]}
    assert {a, b} <= ids and c not in ids  # c has no prediction
    fa = fixture_doc(doc, a)
    assert fa["as_of"] == KO.isoformat()  # never after kick-off
    assert {m["model"] for m in fa["models"]} == {"poisson", "dixon_coles", "elo_ologit"}
    poisson = model_doc(fa, "poisson")
    assert poisson["version_id"] == world.versions[("poisson", "now")]  # not the older, not the one made after kick-off
    assert poisson["status"] == "compared" and poisson["lambda_home"] == pytest.approx(1.6, rel=1e-4)
    assert poisson["max_abs"] < 1e-5 and poisson["incoherences"] == []
    dc = model_doc(fa, "dixon_coles")
    assert dc["status"] == "compared" and dc["rho"] == pytest.approx(-0.09, abs=1e-3) and dc["max_abs"] < 1e-5
    assert set(dc["markets"]) == {"1X2 (inversion rows)", "OU (inversion rows)", "BTTS (inversion rows)", "AH", "OU", "DC"}
    assert model_doc(fa, "elo_ologit")["status"] == "not_simulable"
    home = next(s for s in fa["spread"] if (s["market_key"], s["selection"]) == ("1X2", "Home"))
    assert set(home["models"]) == {"poisson", "dixon_coles", "elo_ologit"} and home["spread"] > 0

    fb = model_doc(fixture_doc(doc, b), "dixon_coles")
    assert [i["rule"] for i in fb["incoherences"]] == ["dc_is_1x2_sum"]
    assert fb["markets"]["DC"]["max_abs"] == pytest.approx(0.03, abs=1e-5)
    assert fb["markets"]["AH"]["max_abs"] < 1e-5
    assert doc["incoherences"] >= 1
    assert doc["markets"]["dixon_coles"]["DC"]["max_abs"] == pytest.approx(0.03, abs=1e-5)

    text = cli.render(cli.check(world.conn, DAY, now=NOW)[0])
    assert "sim-v1 (shadow)" in text and "dc_is_1x2_sum" in text


def test_the_check_writes_nothing_and_runs_on_a_read_only_transaction(world: World) -> None:
    world.standard()
    tables = ("models.predictions", "models.model_versions", "models.match_forecasts", "core.fixtures")
    before = [world.conn.execute(f"SELECT count(*) FROM {t}").fetchone() for t in tables]
    world.conn.execute("SET LOCAL transaction_read_only = on")
    doc, code = cli.check(world.conn, DAY, now=NOW)
    assert code == cli.OK and doc["fixtures_with_predictions"] >= 2
    assert [world.conn.execute(f"SELECT count(*) FROM {t}").fetchone() for t in tables] == before


def test_before_the_forecasts_nothing_is_in_force(world: World) -> None:
    world.standard()
    doc = consistency.check_day(world.conn, DAY, now=CUTOFF - timedelta(days=2))
    assert not {f["fixture_id"] for f in doc["fixtures"]} & set(world.fixtures)
    early = consistency.check_day(world.conn, DAY, now=CUTOFF - timedelta(hours=1))  # only the older poisson version is known
    pa = model_doc(fixture_doc(early, world.fixtures[0]), "poisson")
    assert pa["version_id"] == world.versions[("poisson", "old")] and pa["lambda_home"] == pytest.approx(2.5, rel=1e-4)
