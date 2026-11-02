"""Plan F12 in a real database: the trace reads what production forecast with, and sync writes the ledger's own rows to intel.promotions.

The pure parts (the ledger well formed, the statuses, the text) are in tests/unit/test_model_code_ledger.py. Here: model versions that came into being
at different moments and were used by the worker, a ledger that covers some of them, and the rows it leaves in the append-only table."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from fbi.api.services import evolution as page
from fbi.research import promotions, trace
from fbi.research.promotions import CodePromotion
from tests.integration.conftest import Seed

pytestmark = pytest.mark.integration

NOW = datetime(2035, 3, 1, 12, tzinfo=UTC)
REASON = "a reason a person can look back on, longer than the forty characters the ledger asks for"


def version(db: psycopg.Connection[Any], name: str, code: str, created: datetime) -> int:
    row = db.execute("INSERT INTO models.model_registry (name, family, description) VALUES (%s, 'goals', 'test') "
                     "ON CONFLICT (name) DO UPDATE SET description = models.model_registry.description RETURNING id", (name,)).fetchone()
    assert row is not None
    made = db.execute("INSERT INTO models.model_versions (model_id, version, train_from, train_to, n_train, code_version, created_at) "
                      "VALUES (%s, %s, '2020-01-01', '2035-02-01', 1000, 'test', %s) RETURNING id",
                      (row[0], f"2.0.0/xi=0.002,penalty=1@{code}", created)).fetchone()
    assert made is not None
    return int(made[0])


def predict(db: psycopg.Connection[Any], seed: Seed, version_id: int, when: datetime, *, n: int = 1, session: int | None = None) -> None:
    db.execute("INSERT INTO market.markets (key, name, n_outcomes, has_line, is_exclusive, line_is_signed) "
               "VALUES ('OU', 'Over/Under', 2, true, true, false) ON CONFLICT DO NOTHING")
    for i in range(n):
        db.execute("INSERT INTO models.predictions (fixture_id, model_version_id, market_key, selection, line, p_raw, p_calibrated, feature_set_hash, "
                   "data_cutoff_ts, created_at, backtest_session_id) VALUES (%s, %s, 'OU', 'Over', %s, 0.5, 0.5, 'h', %s, %s, %s)",
                   (seed.fixture_id, version_id, 0.5 + i, when, when, session))


def backtest_session(db: psycopg.Connection[Any]) -> int:
    row = db.execute(
        "INSERT INTO analytics.backtest_sessions (name, protocol, competition_ids, validation_season, test_season, test_from, test_to, config, "
        "selection, primary_baseline, n_targets, dataset_hash, code_version, status, finished_at) VALUES ('s', 'walk_forward', %s, 2023, 2024, "
        "'2024-08-01', '2025-05-31', %s, %s, 'pinnacle/closing/shin', 100, 'h', 'c', 'completed', %s) RETURNING id",
        ([1], json.dumps({}), json.dumps({}), NOW)).fetchone()
    assert row is not None
    return int(row[0])


def entry(fingerprint: str, days_ago: int, *, baseline: bool = False, evidence: dict[str, Any] | None = None) -> CodePromotion:
    return CodePromotion(fingerprint, NOW - timedelta(days=days_ago), "owner" if not baseline else "system", "F12", REASON, baseline, evidence or {})


def rows(db: psycopg.Connection[Any]) -> list[tuple[str, str | None, str, str]]:
    return [(str(r[0]), r[1], str(r[2]), str(r[3])) for r in db.execute(
        "SELECT criteria->>'model_code', from_role, to_role, decided_by FROM intel.promotions WHERE entity = 'model' ORDER BY id").fetchall()]


@pytest.fixture()
def world(db: psycopg.Connection[Any], seed: Seed) -> list[CodePromotion]:
    """Five fingerprints: a commit-keyed one and one older than the ledger (never counted), the baseline, a promoted change and an untraced one."""
    for name, code, ago in (("poisson", "ea1d0c8", 20), ("poisson", "mc1111111111", 12), ("poisson", "mcaaaaaaaaaa", 9), ("dixon_coles", "mcaaaaaaaaaa", 9),
                            ("poisson", "mcbbbbbbbbbb", 4), ("poisson", "mcdddddddddd", 3)):
        v = version(db, name, code, NOW - timedelta(days=ago))
        predict(db, seed, v, NOW - timedelta(days=ago), n=2)
    predict(db, seed, version(db, "elo_ologit", "mcaaaaaaaaaa", NOW - timedelta(days=9)), NOW - timedelta(hours=5))
    return [entry("mcaaaaaaaaaa", 10, baseline=True), entry("mcbbbbbbbbbb", 5)]


def by_code(report: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {f["fingerprint"]: f for f in report["fingerprints"]}


def count(db: psycopg.Connection[Any]) -> int:
    row = db.execute("SELECT count(*) FROM intel.promotions WHERE entity = 'model'").fetchone()
    assert row is not None
    return int(row[0])


def test_the_trace_names_every_fingerprint_that_forecast_and_what_covers_it(db: psycopg.Connection[Any], world: list[CodePromotion]) -> None:
    before = by_code(trace.trace(db, now=NOW, ledger=world))
    assert {k: v["status"] for k, v in before.items()} == {
        "legacy": "PRE_LEDGER", "mc1111111111": "PRE_LEDGER", "mcaaaaaaaaaa": "PENDING_SYNC", "mcbbbbbbbbbb": "PENDING_SYNC", "mcdddddddddd": "UNTRACED"}
    assert before["mcaaaaaaaaaa"]["versions"] == 3 and before["mcaaaaaaaaaa"]["models"] == ["dixon_coles", "elo_ologit", "poisson"]
    assert before["mcaaaaaaaaaa"]["rows"] == {"predictions": 5} and before["mcaaaaaaaaaa"]["in_force_now"] is True, "used five hours ago"
    assert before["mcbbbbbbbbbb"]["in_force_now"] is False and before["mcbbbbbbbbbb"]["rows"] == {"predictions": 2}

    assert trace.sync(db, now=NOW, confirm=False, ledger=world)[0].startswith("WOULD WRITE mcaaaaaaaaaa")
    assert count(db) == 0, "a dry run writes nothing"
    written = trace.sync(db, now=NOW, confirm=True, ledger=world)
    assert [line.split()[1] for line in written] == ["mcaaaaaaaaaa", "mcbbbbbbbbbb"]
    assert rows(db) == [("mcaaaaaaaaaa", None, "CHAMPION", "system"), ("mcaaaaaaaaaa", "CHAMPION", "RETIRED", "owner"), ("mcbbbbbbbbbb", "CHAMPION", "CHAMPION", "owner")]
    assert trace.sync(db, now=NOW, confirm=True, ledger=world) == ["nothing to write: every entry of the ledger is already in intel.promotions"]
    assert count(db) == 3, "the second pass wrote nothing: the table is append-only and the entries are idempotent"

    report = trace.trace(db, now=NOW, ledger=world)
    after = by_code(report)
    assert {k: v["status"] for k, v in after.items()}["mcaaaaaaaaaa"] == "BASELINE", "recorded after the code ran, and said so"
    assert after["mcbbbbbbbbbb"]["status"] == "PROMOTED", "decided five days ago, the code first ran four days ago"
    assert after["mcdddddddddd"]["status"] == "UNTRACED" and after["mcdddddddddd"]["promotion"] is None
    assert after["mcbbbbbbbbbb"]["promotion"]["decided_by"] == "owner" and after["mcbbbbbbbbbb"]["promotion"]["reason"] == REASON
    assert report["counts"] == {"fingerprints": 5, "counted": 3, "traced": 2, "untraced": 1, "pending_sync": 0, "after_use": 0, "pre_ledger": 2}
    assert report["coverage"] == pytest.approx(2 / 3)
    assert "2 of 3 = 67 %" in trace.render(report)


def test_what_a_backtest_ran_is_research_not_production(db: psycopg.Connection[Any], seed: Seed, world: list[CodePromotion]) -> None:
    research = version(db, "poisson", "mceeeeeeeeee", NOW - timedelta(days=2))
    predict(db, seed, research, NOW - timedelta(days=2), n=3, session=backtest_session(db))
    assert "mceeeeeeeeee" not in by_code(trace.trace(db, now=NOW, ledger=world)), "predictions that carry a backtest session are not what users saw"


def test_a_window_looks_back_only_as_far_as_asked(db: psycopg.Connection[Any], world: list[CodePromotion]) -> None:
    short = by_code(trace.trace(db, now=NOW, days=5, ledger=world))
    assert set(short) == {"mcbbbbbbbbbb", "mcdddddddddd", "mcaaaaaaaaaa"}, "the baseline is listed because the worker used it five hours ago"


def test_the_ledger_cannot_cite_a_hypothesis_or_an_experiment_that_does_not_exist(db: psycopg.Connection[Any]) -> None:
    with pytest.raises(LookupError, match="hypothesis 999999 does not exist"):
        trace.sync(db, now=NOW, confirm=True, ledger=[entry("mcaaaaaaaaaa", 10, baseline=True, evidence={"hypothesis_id": 999999})])
    with pytest.raises(LookupError, match=r"experiment\(s\) \[999998\] do not exist"):
        trace.sync(db, now=NOW, confirm=True, ledger=[entry("mcaaaaaaaaaa", 10, baseline=True, evidence={"experiment_ids": [999998]})])
    assert count(db) == 0
    hypothesis = db.execute("INSERT INTO analytics.research_hypotheses (proposed_by, title, hypothesis, rationale, created_at) "
                            "VALUES ('owner', 'A real hypothesis', 'h', 'r', %s) RETURNING id", (NOW,)).fetchone()
    assert hypothesis is not None
    trace.sync(db, now=NOW, confirm=True, ledger=[entry("mcaaaaaaaaaa", 10, baseline=True, evidence={"hypothesis_id": int(hypothesis[0])})])
    row = db.execute("SELECT criteria->'evidence'->>'hypothesis_id' FROM intel.promotions WHERE entity = 'model'").fetchone()
    assert row is not None and row[0] == str(hypothesis[0]), "the promotion carries the hypothesis it rested on"


def test_the_other_promotions_of_the_window_are_counted_for_context(db: psycopg.Connection[Any], world: list[CodePromotion]) -> None:
    db.execute("INSERT INTO intel.promotions (at, entity, market_key, model_name, to_role, gate_version, criteria, reason, decided_by) "
               "VALUES (%s, 'calibrator', 'OU', 'poisson', 'CHAMPION', 'calib-gate-v1', '{}', 'test', 'system')", (NOW - timedelta(days=1),))
    other = trace.trace(db, now=NOW, ledger=world)["other"]
    assert other["calibrator"] == 1 and other["market_edge"] == 0 and other["goal_spec"] >= 0 and other["neutral_rule"] >= 0


def test_the_admin_page_gets_the_trace_with_the_ledger_and_the_code_the_server_runs(db: psycopg.Connection[Any], world: list[CodePromotion],
                                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    """The panel «Código de los modelos»: the same trace the CLI prints, typed, plus the ledger entries (recorded? used?) and whether the code
    that is running is the one the ledger has in force."""
    monkeypatch.setattr(promotions, "LEDGER", tuple(world))
    monkeypatch.setattr(page, "model_code_version", lambda: "mcbbbbbbbbbb")
    before = page.code_promotions(db, days=30, at=NOW).data
    assert before is not None
    assert [(e.fingerprint, e.recorded, e.used) for e in before.ledger] == [("mcaaaaaaaaaa", False, True), ("mcbbbbbbbbbb", False, True)], \
        "the ledger is not in the database yet: the page says so"
    assert {f.fingerprint: f.status for f in before.fingerprints}["mcbbbbbbbbbb"] == "PENDING_SYNC"
    assert before.counts.pending_sync == 2 and before.counts.traced == 0 and before.coverage == 0.0

    trace.sync(db, now=NOW, confirm=True, ledger=world)
    shown = page.code_promotions(db, days=30, at=NOW).data
    assert shown is not None
    assert [f.fingerprint for f in shown.fingerprints] == [f["fingerprint"] for f in trace.trace(db, now=NOW, ledger=world)["fingerprints"]], \
        "the page lists what the trace lists, oldest first"
    status = {f.fingerprint: f.status for f in shown.fingerprints}
    assert status == {"legacy": "PRE_LEDGER", "mc1111111111": "PRE_LEDGER", "mcaaaaaaaaaa": "BASELINE", "mcbbbbbbbbbb": "PROMOTED",
                      "mcdddddddddd": "UNTRACED"}
    assert shown.counts.model_dump() == {"fingerprints": 5, "counted": 3, "traced": 2, "untraced": 1, "pending_sync": 0, "after_use": 0, "pre_ledger": 2}
    assert shown.coverage == pytest.approx(2 / 3)
    assert [(e.fingerprint, e.recorded, e.used, e.baseline) for e in shown.ledger] == [("mcaaaaaaaaaa", True, True, True),
                                                                                        ("mcbbbbbbbbbb", True, True, False)]
    promoted = next(f for f in shown.fingerprints if f.fingerprint == "mcbbbbbbbbbb")
    assert promoted.promotion is not None and promoted.promotion.decided_by == "owner" and promoted.promotion.reason == REASON
    assert promoted.versions == 1 and promoted.models == ["poisson"] and promoted.rows == {"predictions": 2} and promoted.in_force_now is False
    assert next(f for f in shown.fingerprints if f.fingerprint == "mcdddddddddd").promotion is None, "no decision anywhere: nothing to show"
    assert shown.ledger_in_force == "mcbbbbbbbbbb" and shown.running_code == "mcbbbbbbbbbb" and shown.in_force_matches_running is True
    assert shown.other["calibrator"] == 0 and shown.days == 30 and shown.now == NOW and shown.since == NOW - timedelta(days=30)

    monkeypatch.setattr(page, "model_code_version", lambda: "mcdddddddddd")  # the server runs a code the ledger does not have in force
    moved = page.code_promotions(db, days=30, at=NOW).data
    assert moved is not None and moved.running_code == "mcdddddddddd" and moved.in_force_matches_running is False

    upcoming = entry("mc9999999999", 0)  # decided, written in the ledger, the code not released yet: no fingerprint of it has forecast
    monkeypatch.setattr(promotions, "LEDGER", (*world, upcoming))
    ahead = page.code_promotions(db, days=30, at=NOW).data
    assert ahead is not None
    assert [(e.fingerprint, e.recorded, e.used) for e in ahead.ledger] == [("mcaaaaaaaaaa", True, True), ("mcbbbbbbbbbb", True, True),
                                                                          ("mc9999999999", False, False)], "an entry nobody used yet is said so"
    assert ahead.ledger_in_force == "mc9999999999" and "mc9999999999" not in {f.fingerprint for f in ahead.fingerprints}


def test_the_page_reads_and_cannot_write(db: psycopg.Connection[Any], world: list[CodePromotion], monkeypatch: pytest.MonkeyPatch) -> None:
    """Asking for the page changes nothing: no row in ``intel.promotions`` whatever the ledger holds, and the answer is the same twice."""
    monkeypatch.setattr(promotions, "LEDGER", tuple(world))
    first = page.code_promotions(db, days=30, at=NOW).data
    second = page.code_promotions(db, days=30, at=NOW).data
    assert first == second and count(db) == 0, "the ledger is copied to the database by `sync` at a release, never by looking at it"
