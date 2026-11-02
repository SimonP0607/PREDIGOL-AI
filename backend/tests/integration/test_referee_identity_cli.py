"""``python -m scripts.referee_identity`` and the readers it prints (plan F3): what a person sees, what a dry run does not write,
and what the exit code says.

The commands are run with the test's own connection: the actions are blocks of a transaction (a savepoint here), so the test's
transaction is never ended by them."""

from __future__ import annotations

from typing import Any

import psycopg
import pytest
from scripts import referee_identity as cli

from fbi.people import referees as store
from tests.integration.test_referee_identity_job import ledger_runs  # noqa: F401  (the fixture)
from tests.integration.test_referee_identity_store import World, small_world, world  # noqa: F401  (the fixture and the data)

pytestmark = pytest.mark.integration


def run(db: psycopg.Connection[Any], *argv: str) -> int:
    args = cli.build_parser().parse_args(list(argv))
    if args.command == "build":
        return cli.build_command(db, args, commit=False)
    if args.command in cli.READ_ONLY:
        return int(cli.READ_ONLY[args.command](db, args))
    return cli.act(db, args)


def placed(w: World) -> dict[str, int]:
    ids = small_world(w)
    store.build(w.db, apply=True)
    return ids


def test_build_is_a_dry_run_until_apply(world: World, ledger_runs: list[dict[str, Any]], capsys: pytest.CaptureFixture[str]) -> None:  # noqa: F811
    small_world(world)
    assert run(world.db, "build") == 0
    said = capsys.readouterr().out
    assert "DRY RUN" in said and "referees to write" in said
    assert world.one("SELECT count(*) FROM core.referees") == 0 and not ledger_runs

    assert run(world.db, "build", "--apply") == 0
    said = capsys.readouterr().out
    assert "APPLIED" in said and "referees written" in said and "nothing to write" not in said
    assert world.one("SELECT count(*) FROM core.referees") == 2 and len(ledger_runs) == 1

    assert run(world.db, "build", "--apply") == 0
    assert "there was nothing to write" in capsys.readouterr().out
    assert len(ledger_runs) == 1


def test_status_and_audit_say_what_is_in_the_database(world: World, capsys: pytest.CaptureFixture[str]) -> None:  # noqa: F811
    placed(world)
    assert run(world.db, "status") == 0
    said = capsys.readouterr().out
    assert "referees (active / merged)" in said and "2 / 0" in said
    assert "queue (open / rejected / merged)" in said and "1 / 0 / 0" in said
    assert "same_name_other_scope" in said and "problems" in said and "none" in said
    assert "last 0 runs of the job" in said

    assert run(world.db, "audit") == 0
    said = capsys.readouterr().out
    assert said.rstrip().endswith("OK") and "placed_share  (>= 95%)" in said and "100.00%" in said


def test_audit_fails_when_a_criterion_does_not_hold(world: World, capsys: pytest.CaptureFixture[str]) -> None:  # noqa: F811
    small_world(world)  # nothing placed yet: a pass would write, and no match has a referee id
    assert run(world.db, "audit") == 1
    said = capsys.readouterr().out
    assert said.rstrip().splitlines()[-1].startswith("FAILED:") and "placed_share" in said and "pass_would_write" in said

    store.build(world.db, apply=True)
    world.db.execute("UPDATE core.referees SET status = 'merged', merged_into = id + 1 WHERE id = (SELECT min(id) FROM core.referees)")
    assert run(world.db, "audit") == 1
    assert "aliases_on_merged_referee" in capsys.readouterr().out


def test_a_merge_is_a_dry_run_until_apply_and_an_undo_puts_it_back(world: World, capsys: pytest.CaptureFixture[str]) -> None:  # noqa: F811
    ids = placed(world)
    keep, other = world.referee_of(ids["full"]), world.referee_of(ids["dutch"])
    assert keep is not None and other is not None

    assert run(world.db, "merge", str(keep), str(other), "--note", "same man") == 0
    assert "DRY RUN, nothing was written" in capsys.readouterr().out
    assert world.referee_of(ids["dutch"]) == other and world.one("SELECT count(*) FROM core.referee_events") == 0

    assert run(world.db, "merge", str(keep), str(other), "--note", "same man", "--apply") == 0
    said = capsys.readouterr().out
    assert said.startswith("done:") and f"{other} merged into {keep}" in said
    event = int(world.one("SELECT id FROM core.referee_events WHERE action = 'merge'"))
    assert f"undo {event}" in said
    assert world.referee_of(ids["dutch"]) == keep
    assert world.one("SELECT actor FROM core.referee_events WHERE id = %s", event) == "script:referee_identity"
    assert world.one("SELECT detail->>'note' FROM core.referee_events WHERE id = %s", event) == "same man"

    assert run(world.db, "undo", str(event)) == 0
    assert "DRY RUN" in capsys.readouterr().out and world.referee_of(ids["dutch"]) == keep
    assert run(world.db, "undo", str(event), "--apply") == 0
    assert "taken back" in capsys.readouterr().out
    assert world.referee_of(ids["dutch"]) == other
    assert run(world.db, "undo", str(event), "--apply") == 1, "an undone merge cannot be undone twice"
    assert "refused (conflict)" in capsys.readouterr().out


def test_a_refused_action_says_why_and_exits_1(world: World, capsys: pytest.CaptureFixture[str]) -> None:  # noqa: F811
    a = world.match("England", 1, "Michael Oliver", "England", hour=15)
    b = world.match("Netherlands", 1, "M. Oliver", hour=16)  # an hour later: one man cannot be at both
    store.build(world.db, apply=True)
    keep, other = world.referee_of(a), world.referee_of(b)
    assert keep is not None and other is not None and keep != other

    assert run(world.db, "merge", str(keep), str(other), "--apply") == 1
    assert "refused (collision)" in capsys.readouterr().out
    assert world.referee_of(b) == other and world.one("SELECT count(*) FROM core.referee_events") == 0
    assert run(world.db, "merge", str(keep), str(keep), "--apply") == 1
    assert "refused (invalid)" in capsys.readouterr().out
    assert run(world.db, "merge", str(keep), "999999", "--apply") == 1
    assert "refused (not_found)" in capsys.readouterr().out
    assert run(world.db, "merge", str(keep), str(other), "--apply", "--force") == 0, "a person may insist"
    assert world.referee_of(b) == keep


def test_split_reject_reopen_and_rename(world: World, capsys: pytest.CaptureFixture[str]) -> None:  # noqa: F811
    ids = placed(world)
    keep, other = world.referee_of(ids["full"]), world.referee_of(ids["dutch"])
    assert keep is not None and other is not None
    initial_alias = world.alias("m oliver", "england")

    assert run(world.db, "split", str(keep), "--alias", str(initial_alias)) == 0
    assert "DRY RUN" in capsys.readouterr().out and world.referee_of(ids["initial"]) == keep
    assert run(world.db, "split", str(keep), "--alias", str(initial_alias), "--name", "Mark Oliver", "--apply") == 0
    assert "are now referee" in capsys.readouterr().out
    assert world.referee_of(ids["initial"]) not in (keep, other, None)
    assert world.one("SELECT name_locked FROM core.referees WHERE name = 'Mark Oliver'") is True

    assert run(world.db, "reject", str(keep), str(other), "--apply") == 0
    assert "will not be suggested again" in capsys.readouterr().out
    assert world.one("SELECT status FROM core.referee_candidates WHERE referee_a = %s AND referee_b = %s", min(keep, other), max(keep, other)) == "rejected"
    assert run(world.db, "reopen", str(keep), str(other), "--apply") == 0
    assert "a question again" in capsys.readouterr().out
    assert run(world.db, "reopen", str(keep), str(other), "--apply") == 1, "it is not rejected any more"
    assert "refused (not_found)" in capsys.readouterr().out

    assert run(world.db, "rename", str(keep), "--name", "Michael J. Oliver", "--apply") == 0
    assert world.one("SELECT name FROM core.referees WHERE id = %s", keep) == "Michael J. Oliver"
    assert run(world.db, "rename", str(keep), "--release") == 0
    assert "DRY RUN" in capsys.readouterr().out and world.one("SELECT name_locked FROM core.referees WHERE id = %s", keep) is True
    assert run(world.db, "rename", str(keep), "--release", "--apply") == 0
    assert world.one("SELECT name_locked FROM core.referees WHERE id = %s", keep) is False
    assert world.one("SELECT name FROM core.referees WHERE id = %s", keep) == "Michael Oliver", "the rules name him again"


def test_the_queue_find_and_show_print_what_the_people_decide_on(world: World, capsys: pytest.CaptureFixture[str]) -> None:  # noqa: F811
    ids = placed(world)
    keep, other = world.referee_of(ids["full"]), world.referee_of(ids["dutch"])
    assert keep is not None and other is not None

    assert run(world.db, "queue") == 0
    said = capsys.readouterr().out
    assert "open pairs: 1" in said and "same_name_other_scope" in said and "Michael Oliver" in said and "M. Oliver" in said
    assert run(world.db, "queue", "--reason", "spelling_variant") == 0
    said = capsys.readouterr().out
    assert "open pairs: 0" in said and "showing 0" in said

    assert run(world.db, "find", "oliver") == 0
    said = capsys.readouterr().out
    assert "Michael Oliver" in said and "M. Oliver" in said
    assert run(world.db, "find", "nobody here") == 1

    assert run(world.db, "show", str(keep)) == 0
    said = capsys.readouterr().out
    assert f"referee {keep}: Michael Oliver" in said and "spellings:" in said and "doubts waiting:" in said
    assert "initial" in said and "last matches:" in said
    assert run(world.db, "show", "999999") == 1


def test_the_readers_order_and_filter(world: World) -> None:  # noqa: F811
    ids = placed(world)
    keep, other = world.referee_of(ids["full"]), world.referee_of(ids["dutch"])
    assert keep is not None and other is not None

    # another referee of the same surname, with more matches than the first two have
    for day in range(30, 36):
        world.match("Spain", day, "Mike Oliver", "England")
    store.build(world.db, apply=True)
    pairs = store.queue(world.db)
    assert [p["impact"] for p in pairs] == sorted((p["impact"] for p in pairs), reverse=True)
    assert store.queue_size(world.db) == len(pairs) >= 1
    assert store.queue(world.db, limit=1) == pairs[:1] and store.queue(world.db, offset=1) == pairs[1:]
    assert store.queue_size(world.db, status="rejected") == 0 and store.queue(world.db, status="merged") == []
    assert store.queue(world.db, reason="spelling_variant") == [] and store.queue_size(world.db, reason="spelling_variant") == 0
    assert store.queue(world.db, reason="same_name_other_scope") and store.queue_size(world.db, reason="same_name_other_scope") >= 1
    first = pairs[0]
    assert first["matches_a"] >= 0 and first["name_a"] and first["name_b"]

    # find: by the name or by any spelling, without accents or case, the busiest first
    everyone = store.find(world.db, "OLIVER")
    assert [r["matches"] for r in everyone] == sorted((r["matches"] for r in everyone), reverse=True), "the busiest first"
    assert everyone[0]["matches"] == 6 and everyone[0]["name"] == "Mike Oliver"
    assert store.find(world.db, "michael oliver")[0]["id"] == keep
    assert len(store.find(world.db, "oliver", limit=1)) == 1
    assert store.find(world.db, "  ") == [] and store.find(world.db, "zzzz") == []
    assert {r["id"] for r in store.find(world.db, "m oliver")} >= {keep, other}

    row = store.referee_row(world.db, keep)
    assert row is not None and row["matches"] == 2 and row["status"] == "active" and row["first_match"] < row["last_match"]
    assert store.referee_row(world.db, 999_999) is None
    assert {c["other_id"] for c in store.candidates_of(world.db, keep)} >= {other}
    assert store.candidates_of(world.db, keep, status="rejected") == []

    store.merge(world.db, keep, other, actor="admin:test")
    assert other not in {r["id"] for r in store.find(world.db, "m oliver")}, "a merged referee is not offered any more"
    store.rename(world.db, keep, "Michael J. Oliver", actor="admin:test")
    events = store.events_of(world.db, keep)
    assert [e["action"] for e in events][:2] == ["rename", "merge"], "newest first"
    assert [e["action"] for e in store.events_of(world.db, other)] == ["merge"], "the one merged sees it too"
    matches = store.recent_matches(world.db, keep, limit=2)
    assert len(matches) == 2 and matches[0]["kickoff_at"] >= matches[1]["kickoff_at"]
    assert {m["spelling"] for m in store.recent_matches(world.db, keep)} >= {"M. Oliver"}
    assert store.recent_matches(world.db, 999_999) == []
