"""PM-12-06 on a real database: the three sources read as of a moment (the newest set before kick-off, never one made after it), the
90-minute result, the matrix's summary level of each competition season, the segments adding back to the global figures, a LAB
session's runs reproduced as the server stored them, the report appended once a day, and state 5 of the resolver reading the
competition's own verdict (``apta`` with 320 matches of a sharp model; nothing for a competition without a verdict)."""

from __future__ import annotations

import math
import random
from datetime import UTC, datetime, timedelta
from itertools import count
from typing import Any

import psycopg
import pytest

import fbi.coverage.resolve as resolve
from fbi.coverage import levels
from fbi.coverage import model_segments as sg
from tests.integration.conftest import Seed
from tests.integration.helpers import scalar
from tests.unit.test_coverage_resolve import parlay_rules

pytestmark = pytest.mark.integration
AT = datetime(2026, 11, 20, 12, tzinfo=UTC)
START = AT - timedelta(days=45)
_ids = count(95_000)


def competition(db: psycopg.Connection[Any]) -> tuple[int, int]:
    with db.cursor() as cur:
        cur.execute("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type) "
                    "VALUES (%s, 'L', 'league', 'club', 'domestic_league') RETURNING id", (next(_ids),))
        comp = scalar(cur)
        cur.execute("INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, 2026) RETURNING id", (comp,))
        return comp, scalar(cur)


def played(db: psycopg.Connection[Any], cs: int, teams: tuple[int, int], k: int, score: tuple[int, int], *,
           settled: datetime | None = None) -> tuple[int, datetime]:
    ko = START + timedelta(days=k % 40, hours=k % 7)
    with db.cursor() as cur:
        cur.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at, "
                    "status_short, status_group) VALUES (%s, %s, %s, %s, %s, 'FT', 'finished') RETURNING id",
                    (next(_ids), cs, teams[0], teams[1], ko))
        fid = scalar(cur)
        # extra time: the 90-minute score is what is judged (ft_goals_*)
        cur.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away, ft_goals_home, ft_goals_away, settled_at) "
                    "VALUES (%s, %s, %s, %s, %s, %s)", (fid, score[0], score[1] + 1, score[0], score[1], settled or ko + timedelta(hours=2)))
    return fid, ko


def forecast(db: psycopg.Connection[Any], seed: Seed, fid: int, known: datetime, p: tuple[float, float, float]) -> None:
    for sel, q in zip(("Home", "Draw", "Away"), p, strict=True):
        db.execute("INSERT INTO models.match_forecasts (version, known_at, fixture_id, family, market_key, selection, line, model_name, "
                   "model_version_id, data_cutoff_ts, p_model, p, calibration, basis, input_hash, code_version) VALUES ('forecast-v1', "
                   "%s, %s, 'RESULT', '1X2', %s, 0, 'elo_ologit', %s, %s, %s, %s, 'UNCALIBRATED', 'no_champion', %s, 'c')",
                   (known, fid, sel, seed.model_version_id, known, q, q, f"h{next(_ids)}"))


def prediction(db: psycopg.Connection[Any], seed: Seed, fid: int, cutoff: datetime, p: tuple[float, float]) -> None:
    for sel, q in zip(("Over", "Under"), p, strict=True):
        db.execute("INSERT INTO models.predictions (fixture_id, model_version_id, market_key, selection, line, p_raw, p_calibrated, "
                   "feature_set_hash, data_cutoff_ts, created_at) VALUES (%s, %s, 'OU', %s, 2.5, %s, %s, 'f', %s, %s)",
                   (fid, seed.model_version_id, sel, q, q, cutoff, cutoff))


def sharp(y: int, hi: float = 0.7) -> tuple[float, float, float]:
    p = [(1 - hi) / 2] * 3
    p[y] = hi
    return (p[0], p[1], p[2])


def test_the_sources_the_segments_and_the_verdicts(db: psycopg.Connection[Any], seed: Seed) -> None:
    rnd = random.Random(7)
    big, big_cs = competition(db)
    small, small_cs = competition(db)
    _new, new_cs = competition(db)
    teams = (seed.home_team_id, seed.away_team_id)
    for datum in levels.DATA:  # the big one is graded; the small one is not measured
        db.execute("INSERT INTO analytics.coverage_cells (competition_season_id, phase_key, datum, n_finished, n_with_data, share, level, "
                   "measured_level, rules_version, measured_at) VALUES (%s, 'todas', %s, 40, 40, 1, 'B', 'B', 'coverage-levels-v1', now())",
                   (big_cs, datum))
    expected_ll = []
    first = 0
    for k in range(320):
        score = rnd.choice([(2, 0), (1, 1), (0, 1), (3, 2)])
        fid, ko = played(db, big_cs, teams, k, score)
        first = first or fid
        y = 0 if score[0] > score[1] else 1 if score[0] == score[1] else 2
        forecast(db, seed, fid, ko - timedelta(hours=30), (0.34, 0.33, 0.33))     # an older set
        forecast(db, seed, fid, ko - timedelta(hours=3), sharp(y))                 # the newest before kick-off
        forecast(db, seed, fid, ko + timedelta(minutes=10), (0.98, 0.01, 0.01))   # made after kick-off: never read
        expected_ll.append(-math.log(0.7))
        prediction(db, seed, fid, ko - timedelta(hours=5), (0.5, 0.5))
        prediction(db, seed, fid, ko - timedelta(hours=1), (0.6, 0.4))
    for k in range(20):
        fid, ko = played(db, small_cs, teams, k, (1, 0))
        forecast(db, seed, fid, ko - timedelta(hours=3), sharp(0))
    late, ko = played(db, small_cs, teams, 21, (1, 0), settled=AT + timedelta(hours=1))   # its result recorded after the moment
    forecast(db, seed, late, ko - timedelta(hours=3), sharp(0))

    found, incomplete = sg.load(db, source="forecast", at=AT, start=START.date())
    assert incomplete == 0 and len(found) == 340
    assert all(max(s.p) == 0.7 and s.p[s.y] == 0.7 for s in found if s.competition_id == big)  # the newest set before kick-off
    lv = {s.competition_id: s.level for s in found}
    d: dict[str, levels.Level] = dict.fromkeys(levels.DATA, "B")
    m: dict[str, levels.Level] = dict.fromkeys(levels.MARKETS, "MI")
    assert lv[big] == levels.summary_level(d, m).label and lv[small] == sg.UNMEASURED
    preds, _ = sg.load(db, source="prediction", at=AT, start=START.date())
    assert len(preds) == 320 and {s.p for s in preds} == {(0.6, 0.4)} and {s.model for s in preds} == {"dixon_coles"}

    rep = sg.report(db, at=AT, start=START.date())
    assert rep["reproduced"] is True and len(rep["reproduction"]) == 4
    by = {(s["source"], s["kind"], s["key"]): s for s in rep["segments"]}
    g = by[("forecast", "competition", str(big))]
    assert g["n"] == 320 and g["log_loss"] == pytest.approx(sum(expected_ll) / 320, abs=1e-6) and g["verdict"] == "apta"
    assert by[("forecast", "competition", str(small))]["verdict"] == "insuficiente"
    assert by[("forecast", "global", "*")]["n"] == 340

    report_id = sg.store(db, rep, code_version="abc")
    assert report_id is not None and sg.store(db, rep, code_version="abc") is None   # once a day
    stored = db.execute("SELECT count(*), count(*) FILTER (WHERE verdict = 'apta') FROM analytics.evaluation_segments "
                        "WHERE report_id = %s", (report_id,)).fetchone()
    assert stored is not None and stored[0] == len(rep["segments"]) and stored[1] >= 1
    rows = db.execute(sg.LATEST_SQL, {"key": str(big)}).fetchall()
    assert rows == [("1X2", "apta")]

    # state 5 of the resolver: the competition's own verdict, only when asked for
    def own(fixture: int) -> Any:
        found = resolve.load(db, fixture, at=AT, rules=parlay_rules(), by_competition=True)
        assert found is not None
        return found.own_sample

    assert own(first) == {"1X2": "apta"}
    assert own(late) == {"1X2": "insuficiente"}
    newcomer, _ = played(db, new_cs, teams, 1, (0, 0))
    assert own(newcomer) == {}                                                   # a new competition: no verdict, not authorised
    off = resolve.load(db, first, at=AT, rules=parlay_rules())
    assert off is not None and off.own_sample is None


def test_a_lab_session_is_reproduced_as_the_server_stored_it(db: psycopg.Connection[Any], seed: Seed) -> None:
    _comp, cs = competition(db)
    session = scalar(db.execute(
        "INSERT INTO analytics.backtest_sessions (name, protocol, competition_ids, test_season, test_from, test_to, primary_baseline, "
        "n_targets, dataset_hash, code_version) VALUES ('s', 'walk_forward', '{1}', 2025, '2025-08-01', '2026-05-31', 'p', 10, 'h', 'c') "
        "RETURNING id"))
    run = scalar(db.execute(
        "INSERT INTO analytics.backtest_runs (name, model_version_id, competition_ids, test_from, test_to, protocol, train_window, "
        "code_version, dataset_hash, n_samples, accuracy_pct, brier_score, logloss, ece, session_id, status, finished_at) VALUES ('elo', %s, "
        "'{1}', '2025-08-01', '2026-05-31', 'walk_forward', 'w', 'c', 'h', 12, 50, 0, 0, 0, %s, 'completed', now()) RETURNING id",
        (seed.model_version_id, session)))
    ll = br = 0.0
    for k in range(12):
        score = (1, 0) if k % 2 else (1, 1)
        fid, _ = played(db, cs, (seed.home_team_id, seed.away_team_id), k, score)
        y = 0 if k % 2 else 1
        p = (0.5, 0.3, 0.2)
        ll += -math.log(p[y])
        br += sum((q - (1.0 if j == y else 0.0)) ** 2 for j, q in enumerate(p))
        for sel, q in zip(("Home", "Draw", "Away"), p, strict=True):
            db.execute("INSERT INTO analytics.backtest_samples (backtest_run_id, fixture_id, market_key, selection, p_calibrated, "
                       "outcome_correct, p_actual) VALUES (%s, %s, '1X2', %s, %s, %s, %s)", (run, fid, sel, q, sel == ("Home", "Draw")[y], q))
    db.execute("UPDATE analytics.backtest_runs SET logloss = %s, brier_score = %s WHERE id = %s", (ll / 12, br / 12, run))
    rep = sg.report(db, at=AT, start=START.date(), sources=("backtest",), session=session)
    assert rep["reproduced"] is True
    assert rep["backtest_reproduction"] == [{"model": f"elo #{run}", "n": 12, "stored_n": 12, "log_loss": round(ll / 12, 6),
                                             "stored_log_loss": pytest.approx(ll / 12, abs=1e-6), "brier": round(br / 12, 6),
                                             "stored_brier": pytest.approx(br / 12, abs=1e-6), "reproduced": True}]
    db.execute("UPDATE analytics.backtest_runs SET logloss = logloss + 0.01 WHERE id = %s", (run,))
    again = sg.report(db, at=AT, start=START.date(), sources=("backtest",), session=session)
    assert again["backtest_reproduction"][0]["reproduced"] is False


def test_the_weekly_phase_of_the_nightly_process(migrated_database: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Off: nothing. On: one ledger row and one report, once per ISO week (another night of the same week does nothing)."""
    import time

    from scripts import availability_refresh

    with psycopg.connect(migrated_database) as c:
        def runs() -> int:
            return int(scalar(c.execute("SELECT count(*) FROM raw.ingestion_runs WHERE job_type = %s", (sg.JOB,))))

        from fbi.core.clock import now

        monday = now()  # the ledger's rows carry the application clock: the week is the one of now
        monkeypatch.delenv(sg.SWITCH, raising=False)
        before = runs()
        availability_refresh.evaluation_phase(c, at=monday, process_started=time.monotonic(), scheduled=True)
        assert runs() == before
        monkeypatch.setenv(sg.SWITCH, "1")
        availability_refresh.evaluation_phase(c, at=monday, process_started=time.monotonic(), scheduled=True)
        assert runs() == before + 1
        row = c.execute("SELECT status, params->>'report_id' FROM raw.ingestion_runs WHERE job_type = %s ORDER BY id DESC LIMIT 1",
                        (sg.JOB,)).fetchone()
        assert row is not None and row[0] == "completed"
        availability_refresh.evaluation_phase(c, at=monday, process_started=time.monotonic(), scheduled=True)  # done this week
        assert runs() == before + 1
