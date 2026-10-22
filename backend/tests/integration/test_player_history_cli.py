"""``python -m scripts.player_history`` and what it prints (plan F3): a dry run until ``--apply``, the one player's streaks and record on a
day, the coach's career, and what the exit code says.

The commands are run with the test's own connection (the pass is a block of a transaction - a savepoint here - so the test's
transaction is never ended by it); ``main`` is run against the scratch database itself, for the paths that open their own connection."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import psycopg
import pytest
from scripts import player_history as cli

from fbi.people import coach_links, player_history
from fbi.people import spells as sp
from tests.integration.test_player_history_job import ledger_runs, small_world  # noqa: F401  (the fixture and the data)
from tests.integration.test_player_history_store import T0, World, d, world  # noqa: F401  (the fixture and the data)

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def no_real_ledger(ledger_runs: list[dict[str, Any]]) -> None:  # noqa: F811
    """No test of this file opens a row in the real ledger: the ledger commits when it opens one, and with it everything the test
    had written in its transaction (the world of the test would stay in the scratch database for the tests that come after)."""


def run(db: psycopg.Connection[Any], *argv: str) -> int:
    args = cli.build_parser().parse_args(list(argv))
    if args.command == "build":
        return cli.build_command(db, args, commit=False)
    return int(cli.READ_ONLY[args.command](db, args))


def said(capsys: pytest.CaptureFixture[str]) -> str:
    return capsys.readouterr().out


def placed(w: World) -> dict[str, int]:
    """The small world with its history built, and a transfer that says since when the player is at his club."""
    ids = small_world(w)
    w.transfer(ids["player"], -20, w.provider(ids["club"]), None, names=("Alpha FC", "Out FC"))
    player_history.build(w.db, apply=True, sweep=True)
    coach_links.build(w.db, apply=True)
    return ids


def test_build_is_a_dry_run_until_apply(world: World, ledger_runs: list[dict[str, Any]], capsys: pytest.CaptureFixture[str]) -> None:  # noqa: F811
    ids = small_world(world)
    assert run(world.db, "build") == 0
    out = said(capsys)
    assert "DRY RUN" in out and "everyone" in out and "streaks the facts give" in out and "persons to create (from a profile)" in out
    assert world.spells(ids["player"]) == [] and world.caps(ids["national"]) == {} and not ledger_runs
    assert coach_links.counts(world.db)["careers_without_coach"] == 1

    assert run(world.db, "build", "--apply") == 0
    out = said(capsys)
    assert "APPLIED" in out and "nothing to write" not in out and "persons created (from a profile)" in out
    assert world.spells(ids["player"]) != [] and len(world.caps(ids["national"])) == 1 and len(ledger_runs) == 1
    assert coach_links.counts(world.db)["careers_without_coach"] == 0

    assert run(world.db, "build", "--apply") == 0
    assert "(there was nothing to write)" in said(capsys)
    assert len(ledger_runs) == 1


def test_the_recent_pass_looks_at_the_last_days_only(world: World, ledger_runs: list[dict[str, Any]], capsys: pytest.CaptureFixture[str]) -> None:  # noqa: F811
    ids = small_world(world)     # the matches of a test are months ago: the last days hold nothing
    assert run(world.db, "build", "--recent") == 0
    out = said(capsys)
    assert "the last days only" in out and "players looked at" in out and "everyone" not in out
    assert run(world.db, "build", "--recent", "--apply") == 0
    out = said(capsys)
    assert "APPLIED" in out and "the last days only" in out
    assert world.spells(ids["player"]) == [], "nobody played lately"
    assert run(world.db, "build", "--apply") == 0, "and the pass over everyone does find him"
    assert world.spells(ids["player"]) != []
    assert "everyone" in said(capsys)


def test_build_for_chosen_players_writes_their_streaks_only(world: World, capsys: pytest.CaptureFixture[str]) -> None:  # noqa: F811
    ids = small_world(world)
    other = world.player()
    world.lineup(world.fixture(ids["club"], world.team("Rival FC", False), 3), "home", [(other, True)])
    assert run(world.db, "build", "--player", str(ids["player"])) == 0
    out = said(capsys)
    assert "DRY RUN" in out and "1 players" in out and world.spells(ids["player"]) == []

    assert run(world.db, "build", "--player", str(ids["player"]), "--player", str(ids["player"]), "--apply") == 0
    out = said(capsys)
    assert "APPLIED" in out and "1 players" in out, "the same player twice is one"
    assert world.spells(ids["player"]) != [] and world.spells(other) == [], "only the one asked for"
    assert world.caps(ids["national"]) == {}, "no caps from a build of chosen players"
    assert coach_links.counts(world.db)["careers_without_coach"] == 1, "and no coaches"


def test_status_and_audit_say_what_is_in_the_database(world: World, capsys: pytest.CaptureFixture[str]) -> None:  # noqa: F811
    placed(world)
    assert run(world.db, "status") == 0
    out = said(capsys)
    assert f"player_history {player_history.VERSION}" in out and "players with streaks" in out
    assert "caps (players / matches)" in out and "caps of the last year with a club known" in out
    assert "spells_out_of_order  (must be 0)" in out and "coach_links_to_another_person  (must be 0)" in out
    assert "persons / careers (rows)" in out and "last 0 runs of the job" in out

    assert run(world.db, "audit") == 0
    out = said(capsys)
    assert out.rstrip().endswith("OK") and "a pass would write  (must be 0)" in out and "coaches: a pass would write" in out


def test_audit_fails_when_something_is_off_and_names_it(world: World, capsys: pytest.CaptureFixture[str]) -> None:  # noqa: F811
    small_world(world)  # nothing built yet: a pass would still write
    assert run(world.db, "audit") == 1
    out = said(capsys)
    last = out.rstrip().splitlines()[-1]
    assert last.startswith("FAILED:") and "history.pass_would_write" in last and "coaches.pass_would_write" in last

    run(world.db, "build", "--apply")
    capsys.readouterr()
    assert run(world.db, "audit") == 0 and said(capsys).rstrip().endswith("OK")
    stray = world.player()    # streaks of a man no fact is about: no pass looks at him
    world.db.execute("INSERT INTO core.player_spells (provider_player_id, ordinal, provider_team_id, valid_from, valid_to, source, last_evidence, "
                     "version) VALUES (%(p)s, 0, 1, '2026-01-01', '2026-03-01', 'lineup', '2026-01-01', %(v)s), "
                     "(%(p)s, 1, 2, '2026-02-01', NULL, 'lineup', '2026-02-01', %(v)s)", {"p": stray, "v": sp.VERSION})
    assert run(world.db, "audit") == 1
    assert said(capsys).rstrip().splitlines()[-1] == "FAILED: history.spells_out_of_order"


def test_show_prints_the_streaks_and_the_record_and_where_he_was_on_a_day(world: World, capsys: pytest.CaptureFixture[str]) -> None:  # noqa: F811
    ids = placed(world)
    player, club = ids["player"], world.provider(ids["club"])
    home, away = world.team("Portugal", True), world.team("Norway", True)
    later = world.fixture(home, away, 12, national=True)
    world.lineup(later, "home", [(player, False)])          # on the bench of a later match, the statistics not in yet
    player_history.build(world.db, apply=True, sweep=True)
    first_team = world.one("SELECT team_id FROM core.player_national_caps WHERE fixture_id = %s", ids["national"])

    assert run(world.db, "show", str(player)) == 0
    out = said(capsys)
    assert f"player {player}: 1 streaks at clubs, 2 national-team squad entries" in out
    assert "Alpha FC" in out and f"(club {club})" in out and f"{d(-20)} .. ?" in out
    assert "from a transfer" in out and "2 matches" in out and "via 'Free'" in out and f"last evidence {d(5)}" in out
    entries = out.split("squad entries (newest first):")[1].strip().splitlines()
    assert [line.split() for line in entries] == [
        [str(d(12)), "match", str(later), "team", str(home), "sub", "?"],
        [str(d(8)), "match", str(ids["national"]), "team", str(first_team), "started", "played"]]

    assert run(world.db, "show", str(player), "--at", d(10).isoformat()) == 0
    out = said(capsys)
    assert f"on {d(10)}: Alpha FC (club {club}), last evidence {d(5)}" in out
    assert (f"before {d(10)}: 1 squad entries, 1 played (1 starts, 0 minutes), 0 waiting for the statistics; "
            f"last in a squad {d(8)}, last cap {d(8)}") in out

    assert run(world.db, "show", str(player), "--at", d(20).isoformat()) == 0
    out = said(capsys)
    assert (f"before {d(20)}: 2 squad entries, 1 played (1 starts, 0 minutes), 1 waiting for the statistics; "
            f"last in a squad {d(12)}, last cap {d(8)}") in out

    early = d(-30)    # before the transfer and before his first squad entry: no club, no record
    assert run(world.db, "show", str(player), "--at", early.isoformat()) == 0
    out = said(capsys)
    assert f"on {early}: no club is known" in out
    assert (f"before {early}: 0 squad entries, 0 played (0 starts, 0 minutes), 0 waiting for the statistics; "
            "last in a squad ?, last cap ?") in out

    assert run(world.db, "show", str(player), "--caps", "1") == 0
    assert said(capsys).count(" match ") == 1, "the newest only"
    assert run(world.db, "show", str(player), "--caps", "0") == 0
    assert " match " not in said(capsys)


def test_show_and_coach_of_someone_unknown_exit_1(world: World, capsys: pytest.CaptureFixture[str]) -> None:  # noqa: F811
    placed(world)
    assert run(world.db, "show", "424242") == 1 and "nothing about player 424242" in said(capsys)
    assert run(world.db, "coach", "424242") == 1 and "nothing about coach 424242" in said(capsys)


def test_coach_prints_the_person_and_the_career_with_the_links(world: World, capsys: pytest.CaptureFixture[str]) -> None:  # noqa: F811
    ids = small_world(world)
    assert run(world.db, "coach", str(ids["coach"])) == 0
    out = said(capsys)
    assert f"coach {ids['coach']}: no person yet" in out and "-> not a club we hold" in out, "nothing is tied before a pass"

    coach_links.build(world.db, apply=True)
    assert run(world.db, "coach", str(ids["coach"])) == 0
    out = said(capsys)
    assert f"coach {ids['coach']}: person " in out and "Ann Coach" in out and "career as the provider last listed it (1 rows):" in out
    assert "Alpha FC" in out and "-> team " in out and "now" in out


def test_main_runs_on_its_own_connection_and_a_pass_that_finds_the_lock_taken_says_so(
        migrated_database: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(cli, "settings", SimpleNamespace(database=SimpleNamespace(psycopg_url=migrated_database)))
    monkeypatch.setattr(cli, "configure_logging", lambda _level: None)     # (it would reconfigure the logs of the rest of the session)
    monkeypatch.setattr(player_history, "MANUAL_LOCK_WAIT", "200ms")
    assert cli.main(["status"]) == 0 and "players with streaks" in said(capsys)
    assert cli.main(["build"]) == 0 and "DRY RUN" in said(capsys)
    assert cli.main(["audit"]) == 0 and said(capsys).rstrip().endswith("OK")
    assert cli.main(["show", "424242"]) == 1 and cli.main(["coach", "424242"]) == 1
    capsys.readouterr()
    with psycopg.connect(migrated_database) as other:
        other.execute("SELECT pg_advisory_xact_lock(hashtext(%s))", (player_history.LOCK_KEY,))
        assert cli.main(["build", "--apply"]) == 1
        assert "another pass is writing; try again in a minute" in said(capsys)
        assert cli.main(["build", "--player", "1", "--apply"]) == 1
        assert "another pass is writing" in said(capsys)
        assert cli.main(["build"]) == 0, "looking goes on"
        other.rollback()
    capsys.readouterr()
    # (a player no fact is about: the pass is made and has nothing to write, whatever other tests left committed in the scratch database)
    assert cli.main(["build", "--player", "424242", "--apply"]) == 0, "and once the lock is free the pass is made"
    assert "APPLIED" in said(capsys)
