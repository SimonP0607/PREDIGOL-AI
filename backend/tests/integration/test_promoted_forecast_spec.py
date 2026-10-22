"""Plan F0, defect 2, on a real database: production forecasts with the PROMOTED spec, and only a promotion changes it.

Before, the forecast read "the latest completed backtest session". The weekly research-V2 job stores a completed session
whenever the model code or the dataset changes (or every four weeks), so production's hyper-parameters could change in
any week with no decision and no record. Now ``analytics.promoted_forecast_spec`` is the only thing the forecast reads;
a session, the research ones included, is research until a person promotes it. The transaction is rolled back after each
test (the pipeline fixture commits its world and cleans it up)."""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from scripts import promote_forecast_spec as cli

from fbi.core.config import reset_cache
from fbi.predictions import spec as fs
from fbi.predictions.forecast import forecast_upcoming

from .test_migration_0079_promoted_spec import OLD_RULE
from .test_pick_pipeline import AT, league  # noqa: F401 (the fixture)

NOW = datetime(2032, 8, 1, 12, 0, tzinfo=UTC)


def session(db: psycopg.Connection[Any], name: str, *, finished: datetime, xi: float = 0.002, penalty: float = 1.0,
            competitions: tuple[int, ...] = (1,), history_days: int = 730, status: str = "completed",
            protocol: str = "walk_forward", goal: tuple[str, ...] = ("poisson", "dixon_coles")) -> int:
    row = db.execute(
        "INSERT INTO analytics.backtest_sessions (name, protocol, competition_ids, validation_season, test_season, "
        "test_from, test_to, config, selection, primary_baseline, n_targets, dataset_hash, code_version, status, "
        "finished_at) VALUES (%s,%s,%s,2023,2024,'2024-08-01','2025-05-31',%s,%s,'pinnacle/closing/shin',100,'h','c',"
        "%s,%s) RETURNING id",
        (name, protocol, list(competitions), json.dumps({"history_days": history_days}),
         json.dumps({k: {"chosen": {"xi": xi, "penalty": penalty}} for k in goal}), status, finished)).fetchone()
    assert row is not None
    return int(row[0])


def count(db: psycopg.Connection[Any]) -> int:
    row = db.execute("SELECT count(*) FROM analytics.promoted_forecast_spec").fetchone()
    assert row is not None
    return int(row[0])


def test_a_completed_session_is_research_until_somebody_promotes_it(db: psycopg.Connection[Any]) -> None:
    session(db, "leagues-2025-wf", finished=NOW - timedelta(days=30))
    session(db, "research-v2-2024-20261012T080000Z", finished=NOW - timedelta(days=10), xi=0.01)
    assert fs.promoted(db) is None and fs.current_spec(db) is None, "no promotion, no spec: the forecast says so"
    assert db.execute(OLD_RULE).fetchone() is not None, "the old rule would have used the newest of them"


def test_a_newer_session_does_not_move_production(db: psycopg.Connection[Any]) -> None:
    """The defect itself: production forecasts with A; the weekly research run stores B; production must not move."""
    a = session(db, "leagues-2025-wf", finished=NOW - timedelta(days=30), xi=0.002, penalty=1.0, competitions=(1, 2))
    fs.promote(db, a, by="owner", reason="the 2025 league backtest, chosen on the 2023 validation season")
    b = session(db, "research-v2-2024-20261012T080000Z", finished=NOW - timedelta(days=1), xi=0.05, penalty=4.0,
                competitions=(1, 2, 3), history_days=365)
    old = db.execute(OLD_RULE).fetchone()
    assert old is not None and old[0] == b, "the old rule moved to the research session without anybody deciding it"
    now = fs.current_spec(db)
    assert now is not None and now.session_id == a
    assert (now.goal["poisson"].xi, now.goal["poisson"].penalty) == (0.002, 1.0)
    assert now.competition_ids == (1, 2) and now.cfg.history_days == 730


def test_promoting_changes_the_spec_and_a_rollback_is_another_promotion(db: psycopg.Connection[Any]) -> None:
    a = session(db, "A", finished=NOW - timedelta(days=30), xi=0.002, penalty=1.0)
    b = session(db, "B", finished=NOW - timedelta(days=1), xi=0.004, penalty=2.0, history_days=365)
    first = fs.promote(db, a, by="owner", reason="the first spec in force, chosen on the validation season")
    assert first.changed and first.promotion.previous_id is None and "first spec" in first.changes[0]
    second = fs.promote(db, b, by="owner", reason="the re-fit on the new dataset beat A on the validation season",
                        who="simon", at=NOW)
    assert second.changed and second.promotion.previous_id == first.promotion.id
    assert second.changes == ["dixon_coles: xi 0.002 -> 0.004, penalty 1 -> 2", "poisson: xi 0.002 -> 0.004, penalty 1 -> 2",
                              "training window 730 -> 365 days"]
    assert second.promotion.evidence["who"] == "simon" and second.promotion.evidence["session"] == "B"
    assert second.promotion.promoted_at == NOW
    now = fs.current_spec(db)
    assert now is not None and now.session_id == b and now.goal["dixon_coles"].xi == 0.004
    back = fs.promote(db, a, by="owner", reason="B worsened the forecast in production: back to A")
    assert back.changed and back.promotion.previous_id == second.promotion.id
    now = fs.current_spec(db)
    assert now is not None and now.session_id == a and now.goal["dixon_coles"].xi == 0.002
    assert [p.session_id for p in fs.history(db)] == [a, b, a], "newest first; nothing was rewritten"
    assert count(db) == 3


def test_promoting_what_is_in_force_writes_nothing(db: psycopg.Connection[Any]) -> None:
    a = session(db, "A", finished=NOW - timedelta(days=30))
    fs.promote(db, a, by="owner", reason="the first spec in force, chosen on the validation season")
    again = fs.promote(db, a, by="owner", reason="the same session, a second time")
    assert not again.changed and again.changes == [] and count(db) == 1


def test_the_same_forecast_from_another_session_is_a_promotion_with_no_change(db: psycopg.Connection[Any]) -> None:
    """Two sessions that chose the same parameters: promoting the newer one records the move without changing a thing."""
    a = session(db, "A", finished=NOW - timedelta(days=30))
    b = session(db, "B", finished=NOW - timedelta(days=1))
    fs.promote(db, a, by="owner", reason="the first spec in force, chosen on the validation season")
    moved = fs.promote(db, b, by="owner", reason="the newer research run chose the same parameters")
    assert moved.changed and moved.changes == [] and moved.promotion.evidence["changes"] == [
        "same forecast, another session"]


@pytest.mark.parametrize(("kwargs", "error", "message"), [
    ({"status": "running"}, PermissionError, "only a completed walk-forward"),
    ({"status": "failed"}, PermissionError, "only a completed walk-forward"),
    ({"protocol": "holdout"}, PermissionError, "only a completed walk-forward"),
    ({"goal": ("elo_ologit",)}, PermissionError, "chose no hyper-parameters for a goal model"),
], ids=["running", "failed", "holdout", "no goal model"])
def test_a_session_that_cannot_be_a_spec_is_refused(db: psycopg.Connection[Any], kwargs: dict[str, Any],
                                                    error: type[Exception], message: str) -> None:
    finished = None if kwargs.get("status") == "running" else NOW
    s = session(db, "X", finished=finished, **kwargs)  # type: ignore[arg-type]
    with pytest.raises(error, match=message):
        fs.promote(db, s, by="owner", reason="a perfectly good reason to try")
    assert count(db) == 0


def test_a_promotion_without_a_session_a_reason_or_a_person_is_refused(db: psycopg.Connection[Any]) -> None:
    s = session(db, "A", finished=NOW)
    with pytest.raises(LookupError, match="no backtest session"):
        fs.promote(db, s + 999, by="owner", reason="a perfectly good reason to try")
    with pytest.raises(ValueError, match="at least 10 characters"):
        fs.promote(db, s, by="owner", reason="because")
    with pytest.raises(ValueError, match="promoted_by"):
        fs.promote(db, s, by="research_v2", reason="a perfectly good reason to try")
    assert count(db) == 0


def test_editing_a_session_afterwards_cannot_move_production(db: psycopg.Connection[Any]) -> None:
    a = session(db, "A", finished=NOW - timedelta(days=30), xi=0.002)
    fs.promote(db, a, by="owner", reason="the first spec in force, chosen on the validation season")
    db.execute("UPDATE analytics.backtest_sessions SET selection = %s, competition_ids = %s WHERE id = %s",
               (json.dumps({"poisson": {"chosen": {"xi": 0.9, "penalty": 9.0}}}), [7], a))
    now = fs.current_spec(db)
    assert now is not None and now.goal["poisson"].xi == 0.002 and now.competition_ids == (1,)
    assert set(now.goal) == {"poisson", "dixon_coles"}


def test_the_history_is_append_only_and_a_promoted_session_cannot_be_deleted(db: psycopg.Connection[Any]) -> None:
    a = session(db, "A", finished=NOW - timedelta(days=30))
    fs.promote(db, a, by="owner", reason="the first spec in force, chosen on the validation season")
    for sql in ("UPDATE analytics.promoted_forecast_spec SET reason = 'edited quietly, after the fact'",
                "DELETE FROM analytics.promoted_forecast_spec"):
        with pytest.raises(psycopg.errors.CheckViolation, match="append-only"), db.transaction():
            db.execute(sql)
    with pytest.raises(psycopg.errors.ForeignKeyViolation), db.transaction():
        db.execute("DELETE FROM analytics.backtest_sessions WHERE id = %s", (a,))
    never = session(db, "never promoted", finished=NOW)
    db.execute("DELETE FROM analytics.backtest_sessions WHERE id = %s", (never,))
    assert count(db) == 1


def test_a_stored_spec_must_be_well_formed(db: psycopg.Connection[Any]) -> None:
    a = session(db, "A", finished=NOW)
    for bad in ({"version": "spec-v0", "competition_ids": [1], "history_days": 730, "goal": {}},
                {"version": "spec-v1", "competition_ids": "1", "history_days": 730, "goal": {}},
                {"version": "spec-v1", "competition_ids": [1], "history_days": "730", "goal": {}},
                {"version": "spec-v1", "competition_ids": [1], "history_days": 730, "goal": []}):
        with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
            db.execute("INSERT INTO analytics.promoted_forecast_spec (session_id, promoted_by, reason, spec) "
                       "VALUES (%s, 'owner', 'a reason that is long enough', %s)", (a, json.dumps(bad)))
    good = json.dumps(fs.snapshot([1], {}, {"poisson": {"chosen": {"xi": 0.1, "penalty": 1.0}}}))
    for who, reason in (("research_v2", "a reason that is long enough"), ("owner", "short"), ("owner", "         ")):
        with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
            db.execute("INSERT INTO analytics.promoted_forecast_spec (session_id, promoted_by, reason, spec) "
                       "VALUES (%s, %s, %s, %s)", (a, who, reason, good))
    assert count(db) == 0


# ── the forecast, end to end ──────────────────────────────────────────────────────────────────────────────────────


def versions_used(db: psycopg.Connection[Any], fixture: int) -> set[str]:
    """The ``xi`` of every goal-model version that forecast this fixture in real time."""
    rows = db.execute(
        "SELECT DISTINCT v.hyperparameters ->> 'xi' FROM models.predictions p JOIN models.model_versions v "
        "ON v.id = p.model_version_id JOIN models.model_registry m ON m.id = v.model_id WHERE p.fixture_id = %s "
        "AND p.backtest_session_id IS NULL AND m.name IN ('poisson', 'dixon_coles')", (fixture,)).fetchall()
    return {str(r[0]) for r in rows}


def test_the_forecast_follows_the_promotion_and_ignores_a_newer_research_session(
        db: psycopg.Connection[Any], league: dict[str, object]) -> None:  # noqa: F811
    target = int(league["target"])  # type: ignore[call-overload]
    first = forecast_upcoming(db, at=AT, code_version="pipetest")
    assert first.predicted["poisson"] >= 1 and first.written > 0
    assert versions_used(db, target) == {"0.002"}, "the fixture's promoted session chose xi 0.002"

    # the weekly research-V2 run stores a completed session whose choice differs: the old rule would have moved to it
    research = session(db, "research-v2-2024-20261026T080000Z", finished=datetime.now(UTC), xi=0.004, penalty=3.0,
                       competitions=(int(league["comp"]),))  # type: ignore[call-overload]
    old = db.execute(OLD_RULE).fetchone()
    assert old is not None and old[0] == research
    again = forecast_upcoming(db, at=AT + timedelta(hours=1), code_version="pipetest")
    assert again.written == 0 and again.unchanged >= 2, "no promotion, no new forecast"
    assert versions_used(db, target) == {"0.002"}, "no model version of the research session was ever created"

    # a person promotes it: the next run forecasts with it, and the earlier forecasts keep the version that made them
    fs.promote(db, research, by="owner", reason="the research run beat the league backtest on the validation season")
    after = forecast_upcoming(db, at=AT + timedelta(hours=2), code_version="pipetest")
    assert after.written > 0
    assert versions_used(db, target) == {"0.002", "0.004"}


def test_with_no_promoted_spec_the_forecast_writes_nothing_and_says_why(
        db: psycopg.Connection[Any], league: dict[str, object]) -> None:  # noqa: F811
    db.execute("SELECT set_config('fbi.analytics_maintenance', 'on', true)")  # a database that was never promoted
    db.execute("DELETE FROM analytics.promoted_forecast_spec")
    assert db.execute("SELECT count(*) FROM analytics.backtest_sessions WHERE status = 'completed'").fetchone() != (0,)
    report = forecast_upcoming(db, at=AT, code_version="pipetest")
    assert report.written == 0 and not report.predicted
    assert "no promoted forecast spec" in report.skipped_models["all"]
    assert "promote_forecast_spec" in report.skipped_models["all"]


# ── the command line ──────────────────────────────────────────────────────────────────────────────────────────────


def test_the_command_shows_the_spec_in_force_the_earlier_ones_and_the_sessions_that_may_be_promoted(
        db: psycopg.Connection[Any]) -> None:
    assert cli.show(db)[0].startswith("No forecast spec is in force")
    a = session(db, "leagues-2025-wf", finished=NOW - timedelta(days=30))
    b = session(db, "research-v2-2024-20261012T080000Z", finished=NOW - timedelta(days=1), xi=0.004)
    fs.promote(db, a, by="owner", reason="the first spec in force, chosen on the validation season")
    fs.promote(db, b, by="owner", reason="the research run beat the league backtest on the validation set")
    text = "\n".join(cli.show(db))
    assert "IN FORCE since" in text and f"session {b} (research-v2-2024-20261012T080000Z)" in text
    assert "dixon_coles: xi=0.004 penalty=1" in text
    assert "EARLIER:" in text and "the first spec in force" in text
    assert f" * {b:>5}" in text and f"   {a:>5}" in text, "the session in force is marked with *"


def test_the_command_is_a_dry_run_until_a_person_confirms(db: psycopg.Connection[Any]) -> None:
    a = session(db, "A", finished=NOW - timedelta(days=30), xi=0.002)
    b = session(db, "B", finished=NOW - timedelta(days=1), xi=0.004)
    fs.promote(db, a, by="owner", reason="the first spec in force, chosen on the validation season")

    code, lines = cli.promote_command(db, session=b, reason="the re-fit beat A on the validation season", by=None,
                                      confirm=False)
    assert code == 0 and lines[0].startswith(f"DRY RUN - session {b} (B) would change")
    assert any("xi 0.002 -> 0.004" in line for line in lines) and "Nothing was written" in lines[-1]
    assert count(db) == 1

    code, lines = cli.promote_command(db, session=b, reason="the re-fit beat A on the validation season", by=None,
                                      confirm=True)
    assert code == 2 and "--by NAME" in lines[0] and count(db) == 1

    code, lines = cli.promote_command(db, session=b, reason="the re-fit beat A on the validation season", by="simon",
                                      confirm=True)
    assert code == 0 and count(db) == 2 and "in force (promotion #" in lines[0]
    now = fs.promoted(db)
    assert now is not None and now.session_id == b and now.evidence["who"] == "simon" and now.promoted_by == "owner"

    code, lines = cli.promote_command(db, session=b, reason="the re-fit beat A on the validation season", by="simon",
                                      confirm=True)
    assert code == 0 and "already in force" in lines[0] and count(db) == 2


@pytest.mark.parametrize(("session_offset", "reason", "message"), [
    (999, "a perfectly good reason", "no backtest session"),
    (0, "short", "at least 10 characters"),
])
def test_the_command_refuses_what_cannot_be_promoted_and_writes_nothing(
        db: psycopg.Connection[Any], session_offset: int, reason: str, message: str) -> None:
    a = session(db, "A", finished=NOW)
    for confirm in (False, True):
        code, lines = cli.promote_command(db, session=a + session_offset, reason=reason, by="simon", confirm=confirm)
        assert code == 3 and lines[0].startswith("refused:") and message in lines[0]
    assert count(db) == 0
    assert db.execute("SELECT count(*) FROM analytics.backtest_sessions WHERE id = %s", (a,)).fetchone() == (1,), (
        "a refusal is an answer, not a rollback of what the caller had done")


def test_two_promotions_at_once_are_serialized_and_the_history_stays_a_chain(
        committed: psycopg.Connection[Any], migrated_database: str) -> None:
    """Without the lock both read "nothing in force" and the second row would not point at the first: a fork."""
    a = session(committed, "cli-A", finished=NOW - timedelta(days=30), xi=0.002)
    b = session(committed, "cli-B", finished=NOW - timedelta(days=1), xi=0.004)
    one, two = psycopg.connect(migrated_database), psycopg.connect(migrated_database)
    outcome: dict[str, fs.PromotionResult] = {}

    def second() -> None:
        outcome["r"] = fs.promote(two, b, by="owner", reason="promoted while the first one was still deciding")
        two.commit()

    try:
        first = fs.promote(one, a, by="owner", reason="the first spec in force, chosen on the validation season")
        waiter = threading.Thread(target=second)
        waiter.start()
        deadline = time.monotonic() + 5
        while waiter.is_alive() and time.monotonic() < deadline:  # until it is blocked on the first one's lock
            row = committed.execute("SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s",
                                    (two.info.backend_pid,)).fetchone()
            if row is not None and row[0] == "Lock":
                break
            time.sleep(0.02)
        assert waiter.is_alive(), "the second promotion must wait for the first one to finish"
        one.commit()
        waiter.join(timeout=10)
        assert not waiter.is_alive()
        assert outcome["r"].changed and outcome["r"].promotion.previous_id == first.promotion.id
        assert [p.session_id for p in fs.history(committed)] == [b, a]
    finally:
        one.close()
        two.close()


@pytest.fixture()
def committed(migrated_database: str, seed: object, monkeypatch: pytest.MonkeyPatch) -> Iterator[psycopg.Connection[Any]]:
    """The command line commits, so its tests run on committed rows and take them away afterwards. The history is
    append-only: the maintenance switch is how a test cleans up after itself."""
    monkeypatch.setenv("FBI_DATABASE_URL", migrated_database.replace("postgresql://", "postgresql+psycopg://"))
    reset_cache()

    def clean(conn: psycopg.Connection[Any]) -> None:
        with conn.transaction():
            conn.execute("SELECT set_config('fbi.analytics_maintenance', 'on', true)")
            conn.execute("DELETE FROM analytics.promoted_forecast_spec")
            conn.execute("DELETE FROM analytics.backtest_sessions WHERE name LIKE 'cli-%%'")

    with psycopg.connect(migrated_database, autocommit=True) as conn:
        clean(conn)
        try:
            yield conn
        finally:
            clean(conn)
            reset_cache()


def test_the_command_line_commits_a_confirmed_promotion_and_nothing_else(
        committed: psycopg.Connection[Any], capsys: pytest.CaptureFixture[str]) -> None:
    a = session(committed, "cli-A", finished=NOW - timedelta(days=30), xi=0.002)
    b = session(committed, "cli-B", finished=NOW - timedelta(days=1), xi=0.004)
    why = "the re-fit beat the old one on the validation season"

    def run(*argv: str) -> tuple[int, str, str]:
        code = cli.main(list(argv))
        out, err = capsys.readouterr()
        return code, out, err

    code, out, _ = run("show")
    assert code == 0 and "No forecast spec is in force" in out and f"{a:>5}  " in out

    code, out, _ = run("promote", "--session", str(a), "--reason", why)
    assert code == 0 and "DRY RUN" in out and count(committed) == 0, "a dry run writes nothing"
    code, _, err = run("promote", "--session", str(a), "--reason", why, "--confirm")
    assert code == 2 and "--by NAME" in err and count(committed) == 0, "a promotion is a person's decision"
    code, _, err = run("promote", "--session", str(a))
    assert code == 2 and "--session ID and --reason" in err
    code, _, err = run("promote", "--session", str(b + 999), "--reason", why, "--by", "simon", "--confirm")
    assert code == 3 and "refused: no backtest session" in err and count(committed) == 0
    code, _, err = run("promote", "--session", str(a), "--reason", "short", "--by", "simon", "--confirm")
    assert code == 3 and "at least 10 characters" in err and count(committed) == 0

    code, out, _ = run("promote", "--session", str(a), "--reason", why, "--by", "simon", "--confirm")
    assert code == 0 and "is in force" in out
    seen = fs.promoted(committed)  # another connection than the command's own: committed, not just claimed
    assert seen is not None and seen.session_id == a and seen.evidence["who"] == "simon"
    code, out, _ = run("promote", "--session", str(a), "--reason", why, "--by", "simon", "--confirm")
    assert code == 0 and "already in force" in out and count(committed) == 1

    code, out, _ = run("promote", "--session", str(b), "--reason", "the rollback of the rollback, for the record",
                       "--by", "simon", "--confirm")
    assert code == 0 and "xi 0.002 -> 0.004" in out and count(committed) == 2
    code, out, _ = run("show")
    assert code == 0 and "EARLIER:" in out and f" * {b:>5}" in out
