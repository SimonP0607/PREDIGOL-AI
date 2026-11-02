"""The MATCH after it ended (plan F8, ``pm-v6``, ``fbi.intel.match_review``): one row per match in ``intel.match_postmortems`` (what happened, what
the AI's evidence said against who started, the model's forecast against the close) and the memory events the patterns count - under the
SAME keys the first post-mortem of the AI (pm-v1.1, frozen in ``fbi.ai.postmortem``) used, so a match remembered by either is not
remembered twice. The world is the one of ``test_pm_v6_equals_v2`` (eleven reviewed selections of six matches, one report that proved wrong).

The transaction is rolled back afterwards."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import psycopg
import pytest

from fbi.ai.config import AiSettings
from fbi.ai.postmortem import run_postmortems as frozen_run
from fbi.intel import match_review, postmortem

from .conftest import Seed
from .helpers import scalar
from .test_ai_decision_layer import Savepoints
from .test_daily_records import AT
from .test_pm_v6_equals_v2 import world
from .test_postmortem_v6 import LATE, Pm

pytestmark = pytest.mark.integration

SHADOW = AiSettings(mode="shadow")


def keys(db: psycopg.Connection[Any]) -> list[str]:
    return sorted(str(r[0]) for r in db.execute("SELECT dedup_key FROM ai.memory_events WHERE dedup_key LIKE 'pm:pm-v1:%'").fetchall())


def test_every_match_the_ai_reviewed_gets_its_post_mortem_once_and_the_events_the_patterns_count(db: psycopg.Connection[Any],
                                                                                              seed: Seed) -> None:
    pm = world(db, seed)
    report = match_review.review_matches(db, at=LATE)
    assert report.errors == [] and report.matches == 6, "F1 .. F6, each reviewed"
    rows = {int(r[0]): r for r in db.execute("SELECT fixture_id, outcome, findings, version FROM intel.match_postmortems").fetchall()}
    assert set(rows) == {pm.f[n] for n in ("F1", "F2", "F3", "F4", "F5", "F6")} and {r[3] for r in rows.values()} == {match_review.VERSION}
    f1 = rows[pm.f["F1"]]
    assert f1[1] == {"score": [0, 2], "result": "Away", "total_goals": 2, "btts": False, "lineups_known": False}
    assert rows[pm.f["F4"]][1]["lineups_known"] is True
    wrong = rows[pm.f["F5"]][2]["evidence"]
    assert [(e["verdict"], e["side"], e["tier"]) for e in wrong] == [("wrong", "away", "official")], "reported out, and he started"
    assert report.context_errors == 1

    f = pm.f
    kinds = {str(r[0]) for r in db.execute("SELECT DISTINCT kind FROM ai.memory_events WHERE dedup_key LIKE 'pm:pm-v1:%'").fetchall()}
    assert kinds >= {"match_result", "pick_result", "review_quality", "context_error"}
    got = keys(db)
    assert f"pm:pm-v1:{f['F1']}:result" in got and f"pm:pm-v1:{f['F1']}:pick:1X2:Home:0.00" in got and f"pm:pm-v1:{f['F1']}:rq:1X2:Away:0.00" in got
    assert any(k.startswith(f"pm:pm-v1:{f['F5']}:ce:") for k in got), "a report that proved wrong is a context error of its source"
    assert scalar(db.execute("SELECT count(DISTINCT version) FROM ai.memory_events WHERE dedup_key LIKE 'pm:pm-v1:%'")) == 1
    assert scalar(db.execute("SELECT version FROM ai.memory_events WHERE dedup_key = %s", (f"pm:pm-v1:{f['F1']}:result",))) == match_review.VERSION

    again = match_review.review_matches(db, at=LATE)
    assert (again.matches, again.memory_events, again.errors) == (0, 0, []), "a match is written once per version"
    assert len(keys(db)) == len(got)


def test_a_match_the_first_post_mortem_of_the_ai_already_remembered_is_not_remembered_again(db: psycopg.Connection[Any],
                                                                                             seed: Seed) -> None:
    world(db, seed)
    frozen = frozen_run(Savepoints(db), at=LATE, settings=SHADOW)  # type: ignore[arg-type]
    assert frozen.errors == [] and frozen.fixtures == 6 and frozen.memory_events > 0
    before = keys(db)
    report = match_review.review_matches(db, at=LATE)
    assert (report.matches, report.memory_events) == (6, 0), "the row of the match is new, its events are the same events"
    assert keys(db) == before


def test_the_other_way_round_the_first_post_mortem_finds_the_events_already_there(db: psycopg.Connection[Any], seed: Seed) -> None:
    world(db, seed)
    report = match_review.review_matches(db, at=LATE)
    assert report.memory_events > 0
    frozen = frozen_run(Savepoints(db), at=LATE, settings=SHADOW)  # type: ignore[arg-type]
    assert (frozen.fixtures, frozen.memory_events) == (6, 0)


def test_a_match_the_decision_layer_judged_is_studied_even_when_the_ai_never_reviewed_it(db: psycopg.Connection[Any], seed: Seed) -> None:
    pm = Pm(db, seed)
    assert match_review.review_matches(db, at=LATE).matches == 3, "F1, F2 and F3 were reviewed; the others have nothing to study yet"
    postmortem.study(db, at=LATE)
    report = match_review.review_matches(db, at=LATE)
    assert report.matches == 3, "F4, F5 and F6 have selection post-mortems now"
    assert scalar(db.execute("SELECT count(*) FROM intel.match_postmortems")) == 6
    assert pm.count() > 0


def test_a_match_with_nothing_to_study_or_not_finished_is_not_written(db: psycopg.Connection[Any], seed: Seed) -> None:
    pm = Pm(db, seed, results={"F1": (0, 2)}, scenarios=False)
    assert match_review.review_matches(db, at=LATE).matches == 0, "finished, but nobody looked at it"
    pm.review("F3", "1X2", "Home", "0", odds="2.0", book=pm.book, p_model="0.5", p_market="0.45")
    assert match_review.review_matches(db, at=LATE).matches == 0, "reviewed, but the match was never played"


def test_a_match_that_fails_loses_only_itself(db: psycopg.Connection[Any], seed: Seed, monkeypatch: pytest.MonkeyPatch) -> None:
    pm = world(db, seed)
    real = match_review.analyse
    broken_fixture = pm.f["F2"]

    def broken(conn: Any, fixture_id: int) -> Any:
        if fixture_id == broken_fixture:
            raise RuntimeError("this match cannot be analysed")
        return real(conn, fixture_id)

    monkeypatch.setattr(match_review, "analyse", broken)
    report = match_review.review_matches(db, at=LATE)
    assert report.matches == 5 and len(report.errors) == 1 and report.errors[0].startswith(f"{broken_fixture}:")
    assert scalar(db.execute("SELECT count(*) FROM intel.match_postmortems WHERE fixture_id = %s", (broken_fixture,))) == 0
    assert not any(f":{broken_fixture}:" in k for k in keys(db))
    monkeypatch.setattr(match_review, "analyse", real)
    assert match_review.review_matches(db, at=LATE).matches == 1


def test_the_forecast_of_the_model_is_judged_against_the_close_and_a_large_difference_is_a_memory_event(db: psycopg.Connection[Any],
                                                                                                    seed: Seed) -> None:
    pm = Pm(db, seed)  # F3: a home win; the model said 0.55, the closing market 0.43
    match_review.review_matches(db, at=LATE)
    forecast = db.execute("SELECT findings->'model_vs_market' FROM intel.match_postmortems WHERE fixture_id = %s", (pm.f["F3"],)).fetchone()
    assert forecast is not None and forecast[0]["closer"] == "model" and forecast[0]["logloss_diff"] == pytest.approx(-0.2459, abs=1e-3)
    assert not any(k.endswith(":mf") for k in keys(db)), "0.246 is not yet a large difference (0.25)"
    # a newer forecast of the model, far more sure of the home win: a model success worth remembering
    cal = scalar(db.execute("SELECT calibrator_id FROM models.predictions WHERE fixture_id = %s", (pm.f["F3"],)))
    db.execute("INSERT INTO models.predictions (fixture_id,model_version_id,calibrator_id,market_key,selection,p_raw,p_calibrated,p_lo,p_hi,"
               "feature_set_hash,data_cutoff_ts) VALUES (%s,%s,%s,'1X2','Home',0.9,0.9,0.8,0.95,'fh2',%s)",
               (pm.f["F3"], seed.model_version_id, cal, AT - timedelta(hours=12)))
    again = match_review.analyse(db, pm.f["F3"])
    assert again is not None and again[2]["model_vs_market"]["p_model_actual"] == 0.9
    event_count = len(keys(db))
    n, errors = match_review.write_events(db, pm.f["F3"], again[0], again[1], again[2], at=LATE)
    assert errors == 0 and n >= 1 and len(keys(db)) > event_count
    assert db.execute("SELECT kind FROM ai.memory_events WHERE dedup_key = %s", (f"pm:pm-v1:{pm.f['F3']}:mf",)).fetchone() == ("model_success",)
