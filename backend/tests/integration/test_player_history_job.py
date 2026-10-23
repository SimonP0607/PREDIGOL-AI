"""The ``player_history`` job as a run of the ledger (plan F3): a row only when it wrote something, an audit in the daily sweep that says
in the log what is off, and a pass that gives way to a person's build."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from fbi.ingestion import player_history as job
from fbi.people import coach_links, player_history
from fbi.people import spells as sp
from tests.integration.test_coach_links import World as CoachWorld
from tests.integration.test_player_history_store import T0, World, world  # noqa: F401  (the fixture and the data)

pytestmark = pytest.mark.integration


@pytest.fixture()
def ledger_runs(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    runs: list[dict[str, Any]] = []

    class FakeLedger:
        def __init__(self, conn: Any) -> None:
            self.conn = conn

        def open(self, job_type: str, *, params: dict[str, object] | None = None, **_: Any) -> int:
            runs.append({"job": job_type, "params": params, "counters": None, "notes": None})
            return len(runs)

        def close(self, run_id: int, counters: Any, *, notes: str | None = None) -> None:
            runs[run_id - 1].update(counters=counters, notes=notes)

    monkeypatch.setattr("fbi.ingestion.player_history.RunLedger", FakeLedger)
    return runs


class LogSpy:
    """Stands in for the module's logger and keeps what it was told, as (level, event, fields)."""

    def __init__(self) -> None:
        self.said: list[tuple[str, str, dict[str, Any]]] = []

    def __getattr__(self, level: str) -> Callable[..., None]:
        def record(event: str, **fields: Any) -> None:
            self.said.append((level, event, fields))
        return record


@pytest.fixture()
def log(monkeypatch: pytest.MonkeyPatch) -> LogSpy:
    spy = LogSpy()
    monkeypatch.setattr(job, "log", spy)
    return spy


def small_world(world: World) -> dict[str, int]:  # noqa: F811
    """A club player, a national-team match and a coach with a profile and a career at the club."""
    a, rival, spain, italy = world.team("Alpha FC", False), world.team("Rival FC", False), world.team("Spain", True), world.team("Italy", True)
    p = world.player()
    for day in (1, 5):
        world.lineup(world.fixture(a, rival, day), "home", [(p, True)])
    national = world.fixture(spain, italy, 8, national=True)
    world.lineup(national, "home", [(p, True)])
    coaches = CoachWorld(world.db, world.seed)
    coach = coaches.coach()
    coaches.profile(coach, "Ann Coach")
    coaches.career(coach, [(world.provider(a), "Alpha FC", -30, None)])
    return {"player": p, "club": a, "national": national, "coach": coach}


def test_a_pass_that_writes_leaves_one_ledger_row_and_a_quiet_one_leaves_none(world: World, ledger_runs: list[dict[str, Any]]) -> None:  # noqa: F811
    ids = small_world(world)
    report = job.run_job(world.db, sweep=True, commit=False)
    assert report.changed and report.history.changed and report.coaches.changed and not report.skipped_locked
    assert world.spells(ids["player"]) != [] and world.caps(ids["national"]) != {}
    assert coach_links.counts(world.db)["careers_without_coach"] == 0
    assert len(ledger_runs) == 1 and ledger_runs[0]["job"] == job.JOB == "player_history"
    counters = ledger_runs[0]["counters"]
    assert counters.rows_inserted == report.history.spells_written + report.history.caps_written + report.coaches.persons_created
    assert counters.rows_updated == report.coaches.careers_coach_linked + report.coaches.careers_team_linked > 0
    assert counters.rows_normalized == report.history.players + report.history.fixtures and counters.errors == []
    assert ledger_runs[0]["params"] == {"version": player_history.VERSION, "sweep": True}
    assert "persons_created" in str(ledger_runs[0]["notes"])

    quiet = job.run_job(world.db, sweep=True, commit=False)
    assert not quiet.changed and len(ledger_runs) == 1, "a pass that changed nothing leaves no row in the ledger"


def test_only_the_coaches_changing_is_a_run_too(world: World, ledger_runs: list[dict[str, Any]]) -> None:  # noqa: F811
    ids = small_world(world)
    job.run_job(world.db, sweep=True, commit=False)
    coaches = CoachWorld(world.db, world.seed)
    late = coaches.coach()
    coaches.profile(late, "Bob Coach")
    coaches.career(late, [(world.provider(ids["club"]), "Alpha FC", -3, None)])
    again = job.run_job(world.db, commit=False)
    assert again.coaches.changed and not again.history.changed and again.changed
    assert len(ledger_runs) == 2 and ledger_runs[1]["params"]["sweep"] is False


def test_the_scheduled_pass_looks_at_the_recent_players_and_the_sweep_at_everyone(world: World, ledger_runs: list[dict[str, Any]]) -> None:  # noqa: F811
    a, rival = world.team("Alpha FC", False), world.team("Rival FC", False)
    old = world.player()
    world.lineup(world.fixture(a, rival, -400), "home", [(old, True)])
    # (the clock of a test is not the clock of the match: the window is the days before now, and the match is a year ago)
    scheduled = job.run_job(world.db, commit=False)
    assert world.spells(old) == [] and scheduled.history.mode == player_history.SCHEDULED
    swept = job.run_job(world.db, sweep=True, commit=False)
    assert world.spells(old) != [] and swept.history.mode == player_history.SWEEP


def test_the_sweep_audits_and_logs_what_is_off(world: World, ledger_runs: list[dict[str, Any]], log: LogSpy) -> None:  # noqa: F811
    ids = small_world(world)
    job.run_job(world.db, sweep=True, commit=False)
    levels = [(level, event) for level, event, _ in log.said]
    assert levels == [("info", "player_history.audit")]
    fields = log.said[0][2]
    assert fields["problems"] == [] and fields["history_pass_would_write"] == {"spells": 0, "spells_deleted": 0, "caps": 0, "caps_deleted": 0}
    assert fields["coaches_pass_would_write"] == {"persons": 0, "coach_links": 0, "team_links": 0}
    assert fields["history_pass_would_write_news"] == {"players": 0, "spells": 0}
    assert "pass_would_write" not in fields["history"] and "pass_would_write_news" not in fields["history"]
    assert fields["history"]["spells"] >= 1 and fields["coaches"]["careers"] >= 1

    # the sweep heals what it can: a cap of a match that is no longer played is deleted before the audit looks
    world.db.execute("UPDATE core.fixtures SET status_group = 'postponed' WHERE id = (SELECT min(fixture_id) FROM core.player_national_caps)")
    # and the audit says what is left: streaks of a man no fact is about (nothing selects him) that overlap, a career tied to the wrong club
    stray = world.player()
    world.db.execute("INSERT INTO core.player_spells (provider_player_id, ordinal, provider_team_id, valid_from, valid_to, source, last_evidence, "
                     "version) VALUES (%(p)s, 0, 1, '2026-01-01', '2026-03-01', 'lineup', '2026-01-01', %(v)s), "
                     "(%(p)s, 1, 2, '2026-02-01', NULL, 'lineup', '2026-02-01', %(v)s)", {"p": stray, "v": sp.VERSION})
    world.db.execute("UPDATE core.coach_careers SET team_id = (SELECT min(id) FROM core.teams WHERE id <> team_id) WHERE team_id IS NOT NULL")
    log.said.clear()
    healed = job.run_job(world.db, sweep=True, commit=False)
    assert healed.history.caps_deleted == 1 and world.caps(ids["national"]) == {}
    (level, event, fields), *rest = log.said
    assert (level, event) == ("warning", "player_history.audit") and not rest
    assert fields["problems"] == ["history.spells_out_of_order", "coaches.team_links_to_another_club"]


def test_a_match_played_while_the_sweep_ran_is_logged_as_news_and_not_as_a_problem(world: World, ledger_runs: list[dict[str, Any]],  # noqa: F811
                                                                                   log: LogSpy) -> None:
    """Regression (23 Oct 2026): the audit after the first full build in production warned about 46 players for whom "a pass would
    still write", all of them one match more played while the build ran. The log says it as information, with the news apart."""
    ids = small_world(world)
    job.run_job(world.db, sweep=True, commit=False)
    log.said.clear()
    just_now = datetime.now(UTC) - timedelta(hours=1)
    world.lineup(world.fixture(ids["club"], world.team("Rival FC", False), 0, at=just_now), "home", [(ids["player"], True)])
    result = job._audit(world.db, commit=False)
    (level, event, fields), *rest = log.said
    assert (level, event) == ("info", "player_history.audit") and not rest
    assert fields["problems"] == [] and job.problems_of(result) == []
    assert fields["history_pass_would_write"] == {"spells": 0, "spells_deleted": 0, "caps": 0, "caps_deleted": 0}
    assert fields["history_pass_would_write_news"] == {"players": 1, "spells": 1}
    assert result["history"]["pass_would_write_news"] == {"players": 1, "spells": 1}

    # ... and the pass that follows folds it in
    job.run_job(world.db, sweep=True, commit=False)
    assert world.spells(ids["player"])[-1][6:8] == (3, just_now.date())


def test_the_problems_of_an_audit() -> None:
    quiet_history = dict.fromkeys(player_history.INVARIANTS, 0) | {"pass_would_write": {"spells": 0, "caps": 0}}
    quiet_coaches = dict.fromkeys(coach_links.INVARIANTS, 0) | {"pass_would_write": {"persons": 0}}
    assert job.problems_of({"history": quiet_history, "coaches": quiet_coaches}) == []
    news = {"history": {**quiet_history, "pass_would_write_news": {"players": 46, "spells": 46}}, "coaches": quiet_coaches}
    assert job.problems_of(news) == [], "news of the day is not a problem"
    broken_history = {**quiet_history, "spells_out_of_order": 2, "pass_would_write": {"spells": 1, "caps": 0}}
    broken_coaches = {**quiet_coaches, "coach_links_to_another_person": 1, "pass_would_write": {"persons": 3}}
    assert job.problems_of({"history": broken_history, "coaches": broken_coaches}) == [
        "history.spells_out_of_order", "coaches.coach_links_to_another_person", "history.pass_would_write", "coaches.pass_would_write"]


def test_a_pass_that_finds_the_locks_taken_leaves_nothing(world: World, ledger_runs: list[dict[str, Any]], migrated_database: str) -> None:  # noqa: F811
    small_world(world)
    with psycopg.connect(migrated_database) as other:
        other.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (player_history.LOCK_KEY,))
        other.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (coach_links.LOCK_KEY,))
        report = job.run_job(world.db, sweep=True, commit=False)
        other.rollback()
    assert report.skipped_locked and not report.changed and not ledger_runs
    assert report.history.skipped_locked and report.coaches.skipped_locked


def test_one_pass_giving_way_does_not_stop_the_other(world: World, ledger_runs: list[dict[str, Any]], migrated_database: str) -> None:  # noqa: F811
    ids = small_world(world)
    with psycopg.connect(migrated_database) as other:
        other.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (player_history.LOCK_KEY,))
        report = job.run_job(world.db, commit=False)
        other.rollback()
    assert report.history.skipped_locked and not report.coaches.skipped_locked and not report.skipped_locked
    assert report.coaches.changed and world.spells(ids["player"]) == []
    assert len(ledger_runs) == 1, "what the coaches' pass wrote is a run"


def test_a_person_at_the_console_waits_for_the_locks_and_the_worker_does_not(world: World, ledger_runs: list[dict[str, Any]],  # noqa: F811
                                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[tuple[str, bool]] = []
    for module, name in ((player_history, "history"), (coach_links, "coaches")):
        real = module.build

        def spy(conn: Any, *, _real: Callable[..., Any] = real, _name: str = name, **kwargs: Any) -> Any:
            asked.append((_name, kwargs.get("wait", False)))
            return _real(conn, **kwargs)

        monkeypatch.setattr(module, "build", spy)
    small_world(world)
    job.run_job(world.db, commit=False)
    job.run_job(world.db, commit=False, wait=True)
    assert asked == [("history", False), ("coaches", False), ("history", True), ("coaches", True)]


def test_a_run_commits_what_it_wrote_unless_the_caller_keeps_the_transaction(world: World, ledger_runs: list[dict[str, Any]],  # noqa: F811
                                                                             monkeypatch: pytest.MonkeyPatch) -> None:
    commits: list[str] = []
    real_commit = type(world.db).commit

    def spy_commit(self: Any) -> None:
        commits.append("commit")  # the test's connection is not committed for real: the fixture rolls it back

    monkeypatch.setattr(type(world.db), "commit", spy_commit)
    try:
        small_world(world)
        job.run_job(world.db, commit=False)
        assert commits == []
        job.run_job(world.db, commit=True)
        assert len(commits) == 2, "once after each pass"
        job.run_job(world.db, sweep=True, commit=True)
        assert len(commits) == 5, "and once after the audit"
    finally:
        monkeypatch.setattr(type(world.db), "commit", real_commit)
        world.db.rollback()
