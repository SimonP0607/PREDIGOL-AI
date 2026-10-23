"""PrediGol's forecast of a match (plan F5, ``forecast-v1``) in a real database.

What the pure tests (tests/unit/test_match_forecast.py) cannot say: that migration 0086 adds one table, one function and one trigger
and comes back out; that the table refuses what a reader could not mean and cannot be rewritten; that the forecast is read only from
what was known at ``at``; that it is written once, again only when it moved, and always as a whole market; that a champion
calibrator and a recent market make it CALIBRATED and their absence leaves it UNCALIBRATED with the reason; that the competitions the
decision layer does not trust get none; that the pipeline writes it in a step of its own whose defects cost nothing else; and that
writing a forecast creates no value decision, no candidate and no pick."""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fbi.intel.calibration import apply_params
from fbi.predictions import match_forecast as mf
from fbi.predictions.forecast import ForecastReport
from tests.integration.conftest import ADMIN_URL, REPO_ROOT, Seed, _dsn
from tests.integration.helpers import must_be_accepted, must_be_rejected_saying, scalar

pytestmark = pytest.mark.integration

AT = datetime(2026, 10, 3, 12, 0, tzinfo=UTC)
KO = AT + timedelta(hours=26)
CUT = AT - timedelta(hours=1)

# a sheet of numbers a goal model could have produced for one match (each market adds up to one)
SHEET: dict[tuple[str, str], dict[str, float]] = {
    ("1X2", "0"): {"Home": 0.50, "Draw": 0.26, "Away": 0.24},
    ("OU", "2.5"): {"Over": 0.62, "Under": 0.38},
    ("BTTS", "0"): {"Yes": 0.57, "No": 0.43},
}
COLUMNS = ("market_key, selection, line, family, model_name, model_version_id, data_cutoff_ts, p_model, p, p_lo, p_hi, calibration, "
           "calibrator_id, p_market_used, market_as_of, basis, known_at, version, code_version")


class World:
    """A match, the numbers two goal models gave it, and what the decision layer would read beside them."""

    def __init__(self, db: psycopg.Connection[Any], seed: Seed) -> None:
        self.db, self.seed = db, seed
        self.version: dict[str, int] = {}
        self._provider = 770_000
        db.execute("INSERT INTO market.markets (key, name, n_outcomes, has_line, is_exclusive, line_is_signed) VALUES "
                   "('OU', 'Over/Under', 2, true, true, false), ('BTTS', 'Both teams to score', 2, false, true, false) "
                   "ON CONFLICT DO NOTHING")
        for name, family in (("poisson", "goals"), ("dixon_coles", "goals"), ("elo_ologit", "rating")):
            model = scalar(db.execute(
                "INSERT INTO models.model_registry (name, family, description) VALUES (%s, %s, 'test') "
                "ON CONFLICT (name) DO UPDATE SET description = models.model_registry.description RETURNING id", (name, family)))
            self.version[name] = scalar(db.execute(
                "INSERT INTO models.model_versions (model_id, version, train_from, train_to, n_train, code_version) "
                "VALUES (%s, 'forecast-test', '2020-01-01', '2026-09-30', 1000, 'test') "
                "ON CONFLICT (model_id, version) DO UPDATE SET code_version = models.model_versions.code_version RETURNING id",
                (model,)))

    def fixture(self, ko: datetime = KO) -> int:
        self._provider += 1
        return int(scalar(self.db.execute(
            "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (self._provider, self.seed.season_id, self.seed.home_team_id, self.seed.away_team_id, ko))))

    def predict(self, fid: int, model: str, market: str, line: str, probs: dict[str, float], *, cutoff: datetime = CUT,
                spread: float | None = 0.05) -> None:
        for selection, p in probs.items():
            lo = None if spread is None else max(p - spread, 0.0)
            hi = None if spread is None else min(p + spread, 1.0)
            self.db.execute(
                "INSERT INTO models.predictions (fixture_id, model_version_id, market_key, selection, line, p_raw, p_calibrated, "
                "p_lo, p_hi, feature_set_hash, data_cutoff_ts) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                (fid, self.version[model], market, selection, Decimal(line), p, p, lo, hi, f"hash-{model}-{cutoff:%d%H%M}", cutoff))

    def predict_all(self, fid: int, model: str, *, cutoff: datetime = CUT, shift: float = 0.0,
                    only: tuple[str, ...] | None = None, spread: float | None = 0.05) -> None:
        """The core markets, the first outcome of each moved up by ``shift`` and the last down by it (so each still adds up)."""
        for (market, line), sheet in SHEET.items():
            if only is not None and market not in only:
                continue
            probs = dict(sheet)
            names = list(probs)
            probs[names[0]] = round(probs[names[0]] + shift, 6)
            probs[names[-1]] = round(probs[names[-1]] - shift, 6)
            self.predict(fid, model, market, line, probs, cutoff=cutoff, spread=spread)

    def champion(self, market: str, model: str, method: str, params: dict[str, float], *,
                 known_at: datetime = AT - timedelta(days=3), promoted: datetime = AT - timedelta(days=2)) -> int:
        calibrator = int(scalar(self.db.execute(
            "INSERT INTO intel.calibrators (market_key, model_name, method, version, params, known_at, fitted_at, n_train, "
            "train_hash, wf, gate) VALUES (%s, %s, %s, 'test', %s, %s, %s, 500, 'h', %s, '{}'::jsonb) RETURNING id",
            (market, model, method, Jsonb(params), known_at, known_at, Jsonb({"logloss_cal": 0.66})))))
        self.db.execute(
            "INSERT INTO intel.promotions (at, entity, market_key, model_name, entity_id, from_role, to_role, gate_version, "
            "criteria, reason, decided_by) VALUES (%s, 'calibrator', %s, %s, %s, NULL, 'CHAMPION', 'calib-gate-v1', "
            "'{}'::jsonb, 'test', 'system')", (promoted, market, model, calibrator))
        return calibrator

    def consensus(self, fid: int, market: str, line: str, probs: dict[str, float], *, as_of: datetime) -> None:
        for selection, p in probs.items():
            self.db.execute(
                "INSERT INTO market.market_consensus (fixture_id, market_key, selection, line, as_of, devig_method, p_fair, "
                "n_bookmakers, overround, best_odds, best_bookmaker_id) VALUES (%s, %s, %s, %s, %s, 'shin', %s, 5, 0.05, 2.0, %s)",
                (fid, market, selection, Decimal(line), as_of, p, self.seed.bookmaker_id))

    def data_class(self, data_class: str, *, computed_at: datetime = AT - timedelta(hours=2)) -> None:
        self.db.execute(
            "INSERT INTO analytics.competition_data_scores (competition_season_id, computed_at, rule_version, class, score, "
            "finished, approved, quarantined, components) VALUES (%s, %s, 'test', %s, 0.5, 0, 0, 0, '{}'::jsonb) "
            "ON CONFLICT (competition_season_id) DO UPDATE SET class = EXCLUDED.class, computed_at = EXCLUDED.computed_at",
            (self.seed.season_id, computed_at, data_class))

    def quarantine(self, fid: int) -> None:
        self.db.execute("INSERT INTO analytics.fixture_validation (fixture_id, state, rule_version, failed, validated_at) "
                        "VALUES (%s, 'QUARANTINED', 'test', '[]'::jsonb, %s)", (fid, AT - timedelta(hours=2)))

    def write(self, fid: int | list[int], at: datetime = AT) -> mf.MatchForecastReport:
        ids = fid if isinstance(fid, list) else [fid]
        return mf.write_match_forecasts(self.db, at=at, code_version="test", fixture_ids=ids)

    def stored(self, fid: int, market: str | None = None) -> list[dict[str, Any]]:
        with self.db.cursor(row_factory=dict_row) as cur:
            cur.execute(f"SELECT {COLUMNS} FROM models.match_forecasts WHERE fixture_id = %s AND (%s::text IS NULL OR market_key = %s) "
                        "ORDER BY id", (fid, market, market))
            return cur.fetchall()

    def said_at(self, fid: int, at: datetime) -> dict[tuple[str, str], tuple[Decimal, str]]:
        """What PrediGol said about the match at ``at``: the newest forecast of each market, as (market, outcome) -> (p, status)."""
        with self.db.cursor(row_factory=dict_row) as cur:
            cur.execute("SELECT f.market_key, f.selection, f.p, f.calibration FROM models.match_forecasts f "
                        "WHERE f.fixture_id = %s AND f.known_at = (SELECT max(g.known_at) FROM models.match_forecasts g "
                        "WHERE g.fixture_id = f.fixture_id AND g.market_key = f.market_key AND g.line = f.line AND g.known_at <= %s)",
                        (fid, at))
            return {(r["market_key"], r["selection"]): (r["p"], r["calibration"]) for r in cur.fetchall()}


@pytest.fixture()
def world(db: psycopg.Connection[Any], seed: Seed) -> World:
    return World(db, seed)


def by_market(rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for r in rows:
        out.setdefault(str(r["market_key"]), []).append(r)
    return out


# ── the migration ────────────────────────────────────────────────────────────────────────────────────────────────

SCRATCH = "fbi_test_m0086"


def _cfg() -> Config:
    cfg = Config(os.path.join(REPO_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(REPO_ROOT, "migrations"))
    return cfg


def _drop() -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()", (SCRATCH,))
        admin.execute(f'DROP DATABASE IF EXISTS "{SCRATCH}"')


def _exists(c: psycopg.Connection[Any], name: str) -> bool:
    row = c.execute("SELECT to_regclass(%s)", (name,)).fetchone()
    return row is not None and row[0] is not None


def _function(c: psycopg.Connection[Any]) -> bool:
    return c.execute("SELECT count(*) FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace "
                     "WHERE n.nspname = 'models' AND p.proname = 'refuse_forecast_change'").fetchone() == (1,)


def _shape(c: psycopg.Connection[Any]) -> list[tuple[Any, ...]]:
    """Every column of every table of the schemas the migration must leave alone."""
    return c.execute("SELECT table_schema, table_name, column_name, data_type, is_nullable, column_default "
                     "FROM information_schema.columns WHERE table_schema IN ('core', 'market', 'models', 'intel', 'picks', 'analytics') "
                     "AND NOT (table_schema = 'models' AND table_name = 'match_forecasts') ORDER BY 1, 2, ordinal_position").fetchall()


def test_0086_adds_one_table_one_function_one_trigger_and_nothing_else_and_comes_back_out(migrated_database: str) -> None:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), "0085")
        with psycopg.connect(dsn) as c:
            assert not _exists(c, "models.match_forecasts") and not _function(c)
            before = _shape(c)

        command.upgrade(_cfg(), "0086")
        with psycopg.connect(dsn) as c:
            assert _exists(c, "models.match_forecasts") and _function(c)
            assert _shape(c) == before, "nothing that existed was changed"
            assert c.execute("SELECT count(*) FROM models.match_forecasts").fetchone() == (0,), "the migration writes no forecast"
            triggers = c.execute("SELECT tgname, tgtype & 2 = 2, tgtype & 1 = 1 FROM pg_trigger WHERE tgrelid = 'models.match_forecasts'::regclass "
                                 "AND NOT tgisinternal").fetchall()
            assert triggers == [("match_forecasts_append_only", True, True)], "BEFORE, for each row"
            indexes = {r[0] for r in c.execute("SELECT indexname FROM pg_indexes WHERE schemaname = 'models' "
                                               "AND tablename = 'match_forecasts'").fetchall()}
            assert {"match_forecasts_read", "match_forecasts_known_at"} <= indexes
            assert c.execute("SELECT obj_description('models.match_forecasts'::regclass)").fetchone() != (None,), "the table says what it is"
            assert c.execute("SELECT version_num FROM alembic_version").fetchone() == ("0086",)

        command.downgrade(_cfg(), "0085")
        with psycopg.connect(dsn) as c:
            assert not _exists(c, "models.match_forecasts") and not _function(c)
            assert _shape(c) == before, "and it leaves as it came"

        command.upgrade(_cfg(), "0086")  # and applies again
        with psycopg.connect(dsn) as c:
            assert _exists(c, "models.match_forecasts") and _function(c)
    finally:
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
        _drop()


# ── the table ────────────────────────────────────────────────────────────────────────────────────────────────────

def _row(world: World, fid: int, **over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "version": "forecast-v1", "known_at": AT, "fixture_id": fid, "family": "TOTAL_GOALS", "market_key": "OU", "selection": "Over",
        "line": Decimal("2.5"), "model_name": "dixon_coles", "model_version_id": world.version["dixon_coles"], "data_cutoff_ts": CUT,
        "p_model": Decimal("0.62"), "p": Decimal("0.62"), "p_lo": Decimal("0.55"), "p_hi": Decimal("0.69"), "p_push": Decimal("0"),
        "calibration": "UNCALIBRATED", "calibrator_id": None, "p_market_used": None, "market_as_of": None, "basis": "no_champion",
        "input_hash": "digest", "code_version": "test"}
    base.update(over)
    return base


def _insert(cur: psycopg.Cursor[Any], row: dict[str, Any]) -> None:
    cols = ", ".join(row)
    cur.execute(f"INSERT INTO models.match_forecasts ({cols}) VALUES ({', '.join('%(' + k + ')s' for k in row)})", row)


def test_the_table_refuses_what_a_reader_could_not_mean(db: psycopg.Connection[Any], world: World) -> None:
    fid = world.fixture()
    calibrator = world.champion("OU", "dixon_coles", "platt", {"a": 0.0, "b": 1.0})
    with must_be_accepted(db) as cur:
        _insert(cur, _row(world, fid))
        _insert(cur, _row(world, fid, selection="Under", p_model=Decimal("0.38"), p=Decimal("0.38"), p_lo=None, p_hi=None))
        _insert(cur, _row(world, fid, calibration="CALIBRATED", calibrator_id=calibrator, basis="champion", known_at=AT + timedelta(hours=1),
                          p_market_used=Decimal("0.5"), market_as_of=AT - timedelta(hours=1)))
    refused: dict[str, tuple[dict[str, Any], str]] = {
        "a probability of exactly 0": ({"p": Decimal("0"), "p_lo": None, "p_hi": None}, "match_forecasts_p_check"),
        "a model probability of exactly 1": ({"p_model": Decimal("1")}, "match_forecasts_p_model_check"),
        "a family in lower case": ({"family": "total_goals"}, "match_forecasts_family_check"),
        "a status nobody reads": ({"calibration": "MAYBE"}, "match_forecasts_calibration_check"),
        "a basis nobody reads": ({"basis": "because"}, "match_forecasts_basis_check"),
        "no version": ({"version": " "}, "match_forecasts_version_check"),
        "no digest": ({"input_hash": ""}, "match_forecasts_input_hash_check"),
        "a push of the whole probability": ({"p_push": Decimal("1")}, "match_forecasts_p_push_check"),
        "an interval with one end": ({"p_hi": None}, "match_forecasts_interval_pair"),
        "an interval that leaves the probability out": ({"p_lo": Decimal("0.63")}, "match_forecasts_interval_holds_p"),
        "calibrated by nobody": ({"calibration": "CALIBRATED", "basis": "champion"}, "match_forecasts_calibrated_iff_calibrator"),
        "a calibrator on an uncalibrated forecast": ({"calibrator_id": calibrator}, "match_forecasts_calibrated_iff_calibrator"),
        "a champion basis on an uncalibrated forecast": ({"basis": "champion"}, "match_forecasts_basis_says_calibration"),
        "a missing price as the basis of a calibrated one": ({"calibration": "CALIBRATED", "calibrator_id": calibrator,
                                                                   "basis": "needs_price"}, "match_forecasts_basis_says_calibration"),
        "a market probability of 0": ({"p_market_used": Decimal("0")}, "match_forecasts_p_market_used_check"),
        "a match that does not exist": ({"fixture_id": 999_999_999}, "match_forecasts_fixture_id_fkey"),
        "a market that does not exist": ({"market_key": "NOPE"}, "match_forecasts_market_key_fkey"),
        "a model version that does not exist": ({"model_version_id": 999_999_999}, "match_forecasts_model_version_id_fkey"),
        "a calibrator that does not exist": ({"calibration": "CALIBRATED", "calibrator_id": 999_999_999, "basis": "champion"},
                                              "match_forecasts_calibrator_id_fkey"),
    }
    for what, (over, constraint) in refused.items():
        with must_be_rejected_saying(db, constraint) as cur:
            _insert(cur, _row(world, fid, **over))
        _ = what
    with must_be_rejected_saying(db, "match_forecasts_once") as cur:  # the same outcome twice at one instant
        _insert(cur, _row(world, fid))
        _insert(cur, _row(world, fid, p=Decimal("0.63")))


def test_a_forecast_is_never_rewritten_unless_a_maintenance_session_says_so(db: psycopg.Connection[Any], world: World) -> None:
    fid = world.fixture()
    with db.cursor() as cur:
        _insert(cur, _row(world, fid))
    with must_be_rejected_saying(db, "append-only") as cur:
        cur.execute("UPDATE models.match_forecasts SET p = 0.5 WHERE fixture_id = %s", (fid,))
    with must_be_rejected_saying(db, "append-only") as cur:
        cur.execute("DELETE FROM models.match_forecasts WHERE fixture_id = %s", (fid,))
    assert scalar(db.execute("SELECT p FROM models.match_forecasts WHERE fixture_id = %s", (fid,))) == Decimal("0.620000")
    with db.transaction(force_rollback=True):  # the maintenance switch lifts it, for one transaction
        db.execute("SELECT set_config('fbi.models_maintenance', 'on', true)")
        db.execute("UPDATE models.match_forecasts SET p = 0.5, p_lo = NULL, p_hi = NULL WHERE fixture_id = %s", (fid,))
        assert scalar(db.execute("SELECT p FROM models.match_forecasts WHERE fixture_id = %s", (fid,))) == Decimal("0.500000")
        db.execute("DELETE FROM models.match_forecasts WHERE fixture_id = %s", (fid,))
        assert scalar(db.execute("SELECT count(*) FROM models.match_forecasts WHERE fixture_id = %s", (fid,))) == 0
    assert scalar(db.execute("SELECT count(*) FROM models.match_forecasts WHERE fixture_id = %s", (fid,))) == 1, "and only for it"
    with must_be_rejected_saying(db, "append-only") as cur:  # the switch did not outlive its transaction
        cur.execute("DELETE FROM models.match_forecasts WHERE fixture_id = %s", (fid,))


# ── what is written ──────────────────────────────────────────────────────────────────────────────────────────────

def test_a_match_with_a_model_gets_the_forecast_of_its_three_core_markets(db: psycopg.Connection[Any], world: World) -> None:
    fid = world.fixture()
    world.predict_all(fid, "poisson", shift=0.03)
    world.predict_all(fid, "dixon_coles")
    report = world.write(fid)
    assert (report.targets, report.with_model, report.not_fit) == (1, 1, 0)
    assert (report.markets_written, report.rows_written, report.unchanged) == (3, 7, 0)
    assert report.calibrated == 0 and dict(report.uncalibrated) == {"no_champion": 3}

    rows = world.stored(fid)
    markets = by_market(rows)
    assert set(markets) == {"1X2", "OU", "BTTS"}
    assert {m: {r["family"] for r in rs} for m, rs in markets.items()} == {
        "1X2": {"RESULT"}, "OU": {"TOTAL_GOALS"}, "BTTS": {"BOTH_TEAMS_SCORE"}}
    assert {(r["market_key"], r["selection"]) for r in rows} == {(m, s) for (m, _), sheet in SHEET.items() for s in sheet}
    for market, rs in markets.items():
        assert float(sum(r["p"] for r in rs)) == pytest.approx(1.0, abs=1e-5), f"{market} adds up to one"
        assert {r["model_name"] for r in rs} == {"dixon_coles"}, "one model per market: the first by name where nothing ranks them"
        assert {r["model_version_id"] for r in rs} == {world.version["dixon_coles"]}
        assert {r["data_cutoff_ts"] for r in rs} == {CUT}, "and the data cut-off it was made with"
    for r in rows:
        assert (r["calibration"], r["basis"], r["calibrator_id"]) == ("UNCALIBRATED", "no_champion", None)
        assert r["p"] == r["p_model"], "no champion: the model's own number, stated as such"
        assert r["p_market_used"] is None and r["market_as_of"] is None, "the market is not part of an uncalibrated forecast"
        assert r["p_lo"] is not None and r["p_lo"] <= r["p"] <= r["p_hi"], "with the interval the model measured"
        assert (r["known_at"], r["version"], r["code_version"]) == (AT, "forecast-v1", "test")
    home = next(r for r in rows if r["selection"] == "Home")
    assert home["p"] == Decimal("0.500000") and (home["p_lo"], home["p_hi"]) == (Decimal("0.450000"), Decimal("0.550000")), (
        "the numbers of dixon_coles, not those of the other model (0.53)")


def test_a_model_without_an_interval_gives_a_forecast_without_one(db: psycopg.Connection[Any], world: World) -> None:
    fid = world.fixture()
    world.predict_all(fid, "dixon_coles", spread=None, only=("OU",))
    assert world.write(fid).markets_written == 1
    assert [(r["p_lo"], r["p_hi"]) for r in world.stored(fid)] == [(None, None), (None, None)]


def test_a_forecast_is_written_once_and_again_only_when_it_moved(db: psycopg.Connection[Any], world: World) -> None:
    fid = world.fixture()
    world.predict_all(fid, "dixon_coles")
    world.write(fid)
    assert scalar(db.execute("SELECT count(*) FROM models.match_forecasts WHERE fixture_id = %s", (fid,))) == 7

    again = world.write(fid, AT + timedelta(hours=1))  # no new information
    assert (again.markets_written, again.rows_written, again.unchanged) == (0, 0, 3)
    same_instant = world.write(fid)  # the same run again: the instant already holds it
    assert (same_instant.markets_written, same_instant.unchanged) == (0, 3)

    # a new prediction that moved every number by 0.4 points: not worth a row
    world.predict_all(fid, "dixon_coles", cutoff=CUT + timedelta(minutes=30), shift=0.004)
    quiet = world.write(fid, AT + timedelta(hours=2))
    assert (quiet.markets_written, quiet.unchanged) == (0, 3)

    # one point in the total only: that market is written again, whole, and the others are not
    world.predict_all(fid, "dixon_coles", cutoff=CUT + timedelta(hours=1), shift=0.0, only=("1X2", "BTTS"))
    world.predict(fid, "dixon_coles", "OU", "2.5", {"Over": 0.63, "Under": 0.37}, cutoff=CUT + timedelta(hours=1))
    moved = world.write(fid, AT + timedelta(hours=3))
    assert (moved.markets_written, moved.rows_written, moved.unchanged) == (1, 2, 2)
    totals = list(world.stored(fid, "OU"))
    assert [(r["selection"], r["known_at"], r["p"]) for r in totals] == [
        ("Over", AT, Decimal("0.620000")), ("Under", AT, Decimal("0.380000")),
        ("Over", AT + timedelta(hours=3), Decimal("0.630000")), ("Under", AT + timedelta(hours=3), Decimal("0.370000"))]
    assert {r["known_at"] for r in world.stored(fid, "1X2")} == {AT}, "the result market was not repeated"
    assert scalar(db.execute("SELECT count(*) FROM models.match_forecasts WHERE fixture_id = %s", (fid,))) == 9

    # what PrediGol said at any moment is the newest set of each market known by then
    assert world.said_at(fid, AT + timedelta(minutes=1))[("OU", "Over")][0] == Decimal("0.620000")
    assert world.said_at(fid, AT + timedelta(hours=3))[("OU", "Over")][0] == Decimal("0.630000")
    assert world.said_at(fid, AT - timedelta(minutes=1)) == {}, "before it was made, nothing"


def test_a_change_of_model_version_is_a_new_forecast_even_if_the_number_did_not_move(db: psycopg.Connection[Any], world: World) -> None:
    fid = world.fixture()
    world.predict_all(fid, "dixon_coles", only=("OU",))
    world.write(fid)
    old = world.version["dixon_coles"]
    new = int(scalar(db.execute(
        "INSERT INTO models.model_versions (model_id, version, train_from, train_to, n_train, code_version) "
        "SELECT model_id, 'forecast-test-2', '2020-01-01', '2026-10-01', 1100, 'test' FROM models.model_versions WHERE id = %s RETURNING id",
        (old,))))
    world.version["dixon_coles"] = new
    world.predict_all(fid, "dixon_coles", cutoff=CUT + timedelta(minutes=30), only=("OU",))  # the very same numbers
    again = world.write(fid, AT + timedelta(hours=2))
    assert again.markets_written == 1, "another version of the model is another forecast"
    assert [(r["model_version_id"], r["known_at"]) for r in world.stored(fid, "OU") if r["selection"] == "Over"] == [
        (old, AT), (new, AT + timedelta(hours=2))]


# ── only what was known ──────────────────────────────────────────────────────────────────────────────────────────

def test_the_forecast_reads_what_was_known_at_the_moment_and_nothing_later(db: psycopg.Connection[Any], world: World) -> None:
    fid = world.fixture()
    world.predict_all(fid, "dixon_coles", cutoff=CUT - timedelta(hours=2), only=("OU",))
    world.predict(fid, "dixon_coles", "OU", "2.5", {"Over": 0.70, "Under": 0.30}, cutoff=AT + timedelta(hours=2))  # the future
    report = world.write(fid)
    assert report.markets_written == 1
    assert {r["p"] for r in world.stored(fid, "OU") if r["selection"] == "Over"} == {Decimal("0.620000")}, "the older number: the other is later"
    assert {r["data_cutoff_ts"] for r in world.stored(fid)} == {CUT - timedelta(hours=2)}
    # a match with only future predictions has no forecast yet
    other = world.fixture()
    world.predict_all(other, "dixon_coles", cutoff=AT + timedelta(minutes=1))
    assert world.write(other).with_model == 0 and world.stored(other) == []


def test_a_backtest_is_not_a_forecast(db: psycopg.Connection[Any], world: World) -> None:
    fid = world.fixture()
    session = scalar(db.execute(
        "INSERT INTO analytics.backtest_sessions (name, protocol, competition_ids, validation_season, test_season, test_from, test_to, "
        "config, selection, primary_baseline, n_targets, dataset_hash, code_version, status, finished_at) VALUES "
        "('forecast-test', 'walk_forward', %s, 2024, 2025, '2025-08-01', '2026-05-31', '{}', '{}', 'pinnacle/closing/shin', 10, 'h', 'c', "
        "'completed', now()) RETURNING id", ([world.seed.competition_id],)))
    db.execute("INSERT INTO models.predictions (fixture_id, model_version_id, market_key, selection, line, p_raw, p_calibrated, "
               "feature_set_hash, data_cutoff_ts, backtest_session_id) VALUES (%s, %s, 'OU', 'Over', 2.5, 0.6, 0.6, 'h', %s, %s), "
               "(%s, %s, 'OU', 'Under', 2.5, 0.4, 0.4, 'h', %s, %s)",
               (fid, world.version["dixon_coles"], CUT, session, fid, world.version["dixon_coles"], CUT, session))
    assert world.write(fid).with_model == 0 and world.stored(fid) == []


# ── calibrated or not, and why ───────────────────────────────────────────────────────────────────────────────────

def test_a_champion_that_uses_the_market_makes_the_total_calibrated_and_the_rest_stays_as_it_is(db: psycopg.Connection[Any],
                                                                                              world: World) -> None:
    fid = world.fixture()
    for model in ("poisson", "dixon_coles"):
        world.predict_all(fid, model)
    params = {"a": 0.0, "b": 0.5, "c": 0.5}
    champion = world.champion("OU", "dixon_coles", "logit2", params)
    market = {"Over": 0.55, "Under": 0.45}
    seen = AT - timedelta(minutes=40)
    world.consensus(fid, "OU", "2.5", market, as_of=seen)
    report = world.write(fid)
    assert (report.markets_written, report.calibrated, dict(report.uncalibrated)) == (3, 1, {"no_champion": 2})

    totals = {r["selection"]: r for r in world.stored(fid, "OU")}
    raw = {"Over": apply_params("logit2", params, 0.62, 0.55), "Under": apply_params("logit2", params, 0.38, 0.45)}
    assert None not in raw.values()
    scale = sum(v for v in raw.values() if v is not None)
    for selection, row in totals.items():
        assert (row["calibration"], row["basis"], row["calibrator_id"], row["model_name"]) == (
            "CALIBRATED", "champion", champion, "dixon_coles")
        assert float(row["p_model"]) == pytest.approx(SHEET[("OU", "2.5")][selection], abs=1e-6)
        assert float(row["p"]) == pytest.approx(float(raw[selection] or 0) / scale, abs=2e-6), "the champion's number, the market scaled to one"
        assert float(row["p_market_used"]) == pytest.approx(market[selection], abs=1e-6) and row["market_as_of"] == seen, (
            "and which market it leaned on")
        assert row["p_lo"] <= row["p"] <= row["p_hi"]
    assert float(sum(r["p"] for r in totals.values())) == pytest.approx(1.0, abs=1e-5)
    assert totals["Over"]["p"] < totals["Over"]["p_model"], "the model was too sure of the over: the stated number follows the market"
    for market_key in ("1X2", "BTTS"):
        assert {(r["calibration"], r["basis"]) for r in world.stored(fid, market_key)} == {("UNCALIBRATED", "no_champion")}


def test_a_champion_that_needs_a_price_does_not_calibrate_against_a_stale_one_or_none(db: psycopg.Connection[Any], world: World) -> None:
    fid = world.fixture()
    world.predict_all(fid, "dixon_coles", only=("OU",))
    world.champion("OU", "dixon_coles", "logit2", {"a": 0.0, "b": 0.5, "c": 0.5})
    nothing = world.write(fid, AT - timedelta(minutes=30))  # no price at all
    assert (nothing.calibrated, dict(nothing.uncalibrated)) == (0, {"needs_price": 1})

    # a price from seven hours ago is stale and one from five minutes after the forecast is not known yet: neither is used
    world.consensus(fid, "OU", "2.5", {"Over": 0.55, "Under": 0.45}, as_of=AT - timedelta(hours=7))
    world.consensus(fid, "OU", "2.5", {"Over": 0.60, "Under": 0.40}, as_of=AT + timedelta(minutes=5))
    stale = world.write(fid, AT)
    assert (stale.markets_written, stale.calibrated) == (0, 0), "still uncalibrated, so there is nothing new to say"
    assert {(r["calibration"], r["basis"], r["p"] == r["p_model"], r["p_market_used"]) for r in world.stored(fid)} == {
        ("UNCALIBRATED", "needs_price", True, None)}

    # the recent price becomes known: the same model number is now a calibrated forecast, and both are in the record
    late = world.write(fid, AT + timedelta(minutes=10))
    assert (late.markets_written, late.calibrated) == (1, 1)
    assert world.said_at(fid, AT + timedelta(minutes=1))[("OU", "Over")][1] == "UNCALIBRATED"
    over, status = world.said_at(fid, AT + timedelta(minutes=10))[("OU", "Over")]
    assert status == "CALIBRATED" and over != Decimal("0.620000")
    assert {r["p_market_used"] for r in world.stored(fid, "OU") if r["calibration"] == "CALIBRATED"} == {
        Decimal("0.600000"), Decimal("0.400000")}, "the newest price known by then, not the older one"


def test_a_champion_that_does_not_use_the_market_calibrates_without_one(db: psycopg.Connection[Any], world: World) -> None:
    fid = world.fixture()
    world.predict_all(fid, "dixon_coles", only=("OU",))
    champion = world.champion("OU", "dixon_coles", "platt", {"a": -0.1, "b": 0.8})
    report = world.write(fid)
    assert (report.calibrated, report.markets_written) == (1, 1)
    totals = {r["selection"]: r for r in world.stored(fid, "OU")}
    assert {r["calibrator_id"] for r in totals.values()} == {champion}
    assert {r["p_market_used"] for r in totals.values()} == {None}, "it never looked at a price"
    assert float(sum(r["p"] for r in totals.values())) == pytest.approx(1.0, abs=1e-5)


def test_the_champion_in_force_at_the_moment_is_the_one_used(db: psycopg.Connection[Any], world: World) -> None:
    fid = world.fixture()
    world.predict_all(fid, "dixon_coles", only=("OU",))
    world.champion("OU", "dixon_coles", "platt", {"a": -0.1, "b": 0.8}, known_at=AT + timedelta(days=1), promoted=AT + timedelta(days=1))
    assert world.write(fid).calibrated == 0, "a champion promoted tomorrow does not calibrate today's forecast"


# ── which matches ────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("data_class", ["PRODUCT_ONLY", "INSUFFICIENT"])
def test_a_competition_the_decision_layer_does_not_trust_gets_no_forecast(db: psycopg.Connection[Any], world: World, data_class: str) -> None:
    fid = world.fixture()
    world.predict_all(fid, "dixon_coles")
    world.data_class(data_class)
    report = world.write(fid)
    assert (report.targets, report.not_fit, report.with_model, report.markets_written) == (1, 1, 0, 0)
    assert world.stored(fid) == []


@pytest.mark.parametrize("data_class", ["MODEL_READY", "PARTIAL"])
def test_a_competition_with_usable_data_gets_it(db: psycopg.Connection[Any], world: World, data_class: str) -> None:
    fid = world.fixture()
    world.predict_all(fid, "dixon_coles", only=("OU",))
    world.data_class(data_class)
    assert world.write(fid).markets_written == 1


def test_a_quarantined_match_gets_none_and_its_neighbour_does(db: psycopg.Connection[Any], world: World) -> None:
    sick, well = world.fixture(), world.fixture()
    for fid in (sick, well):
        world.predict_all(fid, "dixon_coles", only=("OU",))
    world.quarantine(sick)
    report = world.write([sick, well])
    assert (report.targets, report.not_fit, report.with_model, report.markets_written) == (2, 1, 1, 1)
    assert world.stored(sick) == [] and len(world.stored(well)) == 2


def test_the_matches_forecast_are_the_ones_about_to_be_played_in_a_tracked_competition(db: psycopg.Connection[Any], world: World) -> None:
    db.execute("UPDATE core.competitions SET is_tracked = false WHERE id = %s", (world.seed.competition_id,))
    soon, later, started = world.fixture(KO), world.fixture(AT + timedelta(days=9)), world.fixture(AT - timedelta(hours=3))
    for fid in (soon, later, started):
        world.predict_all(fid, "dixon_coles", only=("OU",))
    assert mf.write_match_forecasts(db, at=AT, code_version="test").targets == 0, "a competition nobody tracks is not forecast"
    db.execute("UPDATE core.competitions SET is_tracked = true WHERE id = %s", (world.seed.competition_id,))
    report = mf.write_match_forecasts(db, at=AT, code_version="test")
    assert (report.targets, report.markets_written) == (1, 1)
    assert len(world.stored(soon)) == 2 and world.stored(later) == [] and world.stored(started) == []


# ── a forecast is not a value and not a pick ─────────────────────────────────────────────────────────────────────

def test_a_sure_forecast_at_a_short_price_creates_no_decision_candidate_or_pick(db: psycopg.Connection[Any], world: World) -> None:
    """The case this exists for: the models are sure of the favourite and the price is 1.28. Before, the match left no trace; now it
    has a forecast - and the decision layer and the pick engine are exactly where they were."""
    fid = world.fixture()
    world.predict(fid, "dixon_coles", "1X2", "0", {"Home": 0.80, "Draw": 0.12, "Away": 0.08})
    world.consensus(fid, "1X2", "0", {"Home": 0.77, "Draw": 0.14, "Away": 0.09}, as_of=AT - timedelta(minutes=30))
    tables = ("picks.picks", "picks.pick_candidates", "picks.daily_set_items", "intel.decisions", "intel.day_selections")

    def counts() -> dict[str, int]:
        return {t: int(scalar(db.execute(f"SELECT count(*) FROM {t}"))) for t in tables}

    before = counts()
    report = world.write(fid)
    assert report.markets_written == 1
    forecast = {r["selection"]: r["p"] for r in world.stored(fid, "1X2")}
    assert mf.most_likely([mf.Outcome(s, float(p), float(p), None, None, 0.0) for s, p in forecast.items()]) == "Home"
    assert forecast["Home"] == Decimal("0.800000"), "the favourite is stated as the likely result"
    assert counts() == before, "and nothing was decided, selected or frozen because of it"
    assert scalar(db.execute("SELECT count(*) FROM picks.pick_candidates WHERE fixture_id = %s", (fid,))) == 0


# ── the pipeline ─────────────────────────────────────────────────────────────────────────────────────────────────

class _NoCommit:
    """The test's connection with ``commit()`` turned into nothing: the pipeline commits when it is done and the fixture rolls back."""

    def __init__(self, conn: psycopg.Connection[Any]) -> None:
        self._conn = conn

    def commit(self) -> None:
        return None

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


def test_the_pipeline_writes_the_forecasts_in_a_step_of_its_own_and_a_defect_there_costs_nothing_else(
        db: psycopg.Connection[Any], world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    from fbi.picks import pipeline

    now = datetime.now(UTC).replace(microsecond=0)
    db.execute("UPDATE core.competitions SET is_tracked = true WHERE id = %s", (world.seed.competition_id,))
    fid = world.fixture(now + timedelta(hours=26))
    world.predict_all(fid, "dixon_coles", cutoff=now - timedelta(hours=1))
    monkeypatch.setattr(pipeline, "forecast_upcoming", lambda conn, **kw: ForecastReport(at=kw["at"]))
    conn: Any = _NoCommit(db)

    report = pipeline.run_pipeline(conn, at=now, code_version="test", apply=True)
    assert report.run_id is not None and report.match_forecasts is not None and report.picks is not None
    assert (report.match_forecasts.markets_written, report.match_forecasts.rows_written) == (3, 7)
    ran = db.execute("SELECT notes, errors FROM raw.ingestion_runs WHERE id = %s", (report.run_id,)).fetchone()
    assert ran is not None
    notes, errors = ran
    assert errors == 0 and "match forecasts 3 markets written (7 rows)/0 unchanged for 1 of 1 fixtures" in notes
    assert len(world.stored(fid)) == 7 and {r["known_at"] for r in world.stored(fid)} == {now}

    again = pipeline.run_pipeline(conn, at=now + timedelta(minutes=30), code_version="test", apply=True)
    assert again.match_forecasts is not None and (again.match_forecasts.markets_written, again.match_forecasts.unchanged) == (0, 3)
    assert len(world.stored(fid)) == 7, "a pass with nothing new adds nothing"

    # a defect in the forecast - one the database itself reports, so the transaction would be dead without the savepoint -
    # is recorded on the run and every other step of the pass still happens
    def broken(c: Any, **kw: Any) -> Any:
        c.execute("SELECT 1 / 0")

    monkeypatch.setattr(pipeline, "write_match_forecasts", broken)
    failed = pipeline.run_pipeline(conn, at=now + timedelta(minutes=60), code_version="test", apply=True)
    assert failed.picks is not None and failed.settlement is not None and failed.daily is not None, "the rest of the pass ran"
    assert failed.match_forecasts is not None and failed.match_forecasts.markets_written == 0
    failure = db.execute("SELECT errors, last_error FROM raw.ingestion_runs WHERE id = %s", (failed.run_id,)).fetchone()
    assert failure is not None
    assert failure[0] == 1 and failure[1].startswith("match forecasts: DivisionByZero"), "recorded on the run, not hidden"
    assert len(world.stored(fid)) == 7


def test_the_pass_can_stop_writing_the_forecast_without_a_deploy(
        db: psycopg.Connection[Any], world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    from fbi.picks import pipeline

    assert pipeline.FORECAST_SWITCH == "FBI_MATCH_FORECAST" and pipeline.match_forecast_enabled(), "on unless the owner says otherwise"
    now = datetime.now(UTC).replace(microsecond=0)
    db.execute("UPDATE core.competitions SET is_tracked = true WHERE id = %s", (world.seed.competition_id,))
    fid = world.fixture(now + timedelta(hours=26))
    world.predict_all(fid, "dixon_coles", cutoff=now - timedelta(hours=1))
    monkeypatch.setattr(pipeline, "forecast_upcoming", lambda conn, **kw: ForecastReport(at=kw["at"]))
    monkeypatch.setenv("FBI_MATCH_FORECAST", "0")
    conn: Any = _NoCommit(db)

    assert not pipeline.match_forecast_enabled()
    off = pipeline.run_pipeline(conn, at=now, code_version="test", apply=True)
    assert off.match_forecasts is not None and off.match_forecasts.rows_written == 0
    assert off.picks is not None and off.settlement is not None, "the rest of the pass ran"
    assert world.stored(fid) == []
    ran = db.execute("SELECT notes, errors FROM raw.ingestion_runs WHERE id = %s", (off.run_id,)).fetchone()
    assert ran is not None and ran[1] == 0 and "match forecasts OFF (FBI_MATCH_FORECAST=0)" in ran[0]

    monkeypatch.setenv("FBI_MATCH_FORECAST", "1")
    on = pipeline.run_pipeline(conn, at=now + timedelta(minutes=30), code_version="test", apply=True)
    assert on.match_forecasts is not None and on.match_forecasts.rows_written == 7 and len(world.stored(fid)) == 7
