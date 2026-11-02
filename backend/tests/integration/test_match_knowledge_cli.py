"""``python -m scripts.match_knowledge``: what a person sees and what the exit code says (plan F7).

The commands are run with the test's own connection (``commit=False``: a build must not end the test's transaction)."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb
from scripts import match_knowledge as cli

from fbi.knowledge import builder, layers, reader

from .conftest import Seed
from .knowledge_world import KICKOFF, NOW, World

pytestmark = pytest.mark.integration


def parse(*argv: str) -> Any:
    return cli.build_parser().parse_args(argv)


def run_build(db: psycopg.Connection[Any], *argv: str) -> int:
    return cli.build_command(db, parse("build", *argv), now=NOW, commit=False)


def stored(db: psycopg.Connection[Any], fid: int) -> int:
    return int(db.execute("SELECT count(*) FROM intel.match_knowledge WHERE fixture_id = %s", (fid,)).fetchone()[0])  # type: ignore[index]


def test_build_is_a_dry_run_until_apply_and_says_so(db: psycopg.Connection[Any], seed: Seed, capsys: pytest.CaptureFixture[str]) -> None:
    fid = World(db, seed).golden()

    assert run_build(db) == 0
    said = capsys.readouterr().out
    assert said.startswith("dry run (nothing is written): 1 finished matches settled in the last 10 days (followed competitions)")
    assert "1 due, 1 that would be built" in said and "dry run: re-run with --apply to write it" in said
    assert "completeness: complete 1" in said and "c6_market" in said and "c7_context" in said
    assert stored(db, fid) == 0

    assert run_build(db, "--apply") == 0
    said = capsys.readouterr().out
    assert said.startswith("APPLY: 1 finished matches") and "1 due, 1 built" in said and "lines of events written or deleted: 8" in said
    assert "re-run" not in said and stored(db, fid) == 1

    assert run_build(db, "--apply") == 0
    again = capsys.readouterr().out
    assert "0 due, 0 built" in again and stored(db, fid) == 1, "built once: the second time writes nothing"


def test_build_takes_the_days_the_competitions_and_the_fixtures_it_is_told(db: psycopg.Connection[Any], seed: Seed,
                                                                         capsys: pytest.CaptureFixture[str]) -> None:
    w = World(db, seed)
    recent, old = w.golden(), w.golden(KICKOFF - timedelta(days=60))
    live = w.match(KICKOFF + timedelta(hours=1), group="live", status="2H", goals=None)

    assert run_build(db, "--apply") == 0 and stored(db, recent) == 1 and stored(db, old) == 0
    assert run_build(db, "--apply", "--days", "400") == 0 and stored(db, old) == 1
    capsys.readouterr()

    assert run_build(db, "--apply", "--fixture", str(live), "--fixture", "999999999") == 0
    said = capsys.readouterr().out
    assert "0 matches asked for (2 not finished: left alone)" in said and stored(db, live) == 0, "a match that is not over has no Match Knowledge"

    db.execute("UPDATE core.competitions SET is_tracked = false WHERE provider_league_id = 98971")
    assert run_build(db, "--days", "400") == 0
    assert "0 finished matches settled in the last 400 days (followed competitions)" in capsys.readouterr().out
    assert run_build(db, "--days", "400", "--all-competitions") == 0
    assert "(all competitions)" in capsys.readouterr().out


def test_build_asked_for_a_fixture_builds_it_whatever_its_age(db: psycopg.Connection[Any], seed: Seed, capsys: pytest.CaptureFixture[str]) -> None:
    old = World(db, seed).golden(KICKOFF - timedelta(days=200))
    assert run_build(db, "--fixture", str(old), "--apply") == 0
    assert "1 matches asked for" in capsys.readouterr().out and stored(db, old) == 1


def test_build_says_when_it_stopped_and_what_failed_and_exits_1_then(db: psycopg.Connection[Any], seed: Seed, capsys: pytest.CaptureFixture[str],
                                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    w = World(db, seed)
    ids = [w.golden(KICKOFF + timedelta(hours=i)) for i in range(3)]
    assert run_build(db, "--apply", "--limit", "2") == 0
    said = capsys.readouterr().out
    assert "2 built" in said and "STOPPED (limit): 1 matches not reached" in said

    real = layers.build

    def build(inp: layers.Inputs) -> layers.Knowledge:
        raise RuntimeError("a rule that cannot read this match")

    monkeypatch.setattr(layers, "build", build)
    assert run_build(db, "--apply") == 1
    said = capsys.readouterr().out
    assert "1 failed" in said and "FAILED match" in said and "a rule that cannot read this match" in said
    monkeypatch.setattr(layers, "build", real)
    assert sum(stored(db, i) for i in ids) == 2


def test_coverage_says_how_many_have_a_build_and_exits_1_under_the_criterion(db: psycopg.Connection[Any], seed: Seed,
                                                                           capsys: pytest.CaptureFixture[str]) -> None:
    w = World(db, seed)
    a, b = w.golden(), w.golden(KICKOFF + timedelta(hours=1))
    cover = lambda: cli.coverage_command(db, parse("coverage", "--days", "30"), now=NOW + timedelta(days=1))  # noqa: E731

    assert cover() == 1
    said = capsys.readouterr().out
    assert "followed competitions, kicked off in the last 30 days and settled: 2 finished matches, 0 with a build (0.00 %)" in said
    assert "NOT MET" in said and "all competitions" in said

    builder.build_many(db, [a], commit=False)
    assert cover() == 1 and "1 with a build (50.00 %)" in capsys.readouterr().out
    builder.build_many(db, [b], commit=False)
    assert cover() == 0
    said = capsys.readouterr().out
    assert "2 with a build (100.00 %): complete 2, partial 0, minimal 0" in said and "criterion of the plan" in said and "MET" in said.replace("NOT MET", "")
    assert "events: 2 matches have lines; the kind of each line is read for 2, not yet for 0, stale for 0" in said

    assert cli.coverage_command(db, parse("coverage", "--days", "1"), now=NOW + timedelta(days=100)) == 0, "no match in the window: nothing to be short of"


def test_status_lists_the_tables_the_rules_and_the_runs(db: psycopg.Connection[Any], seed: Seed, capsys: pytest.CaptureFixture[str]) -> None:
    fid = World(db, seed).golden()
    builder.build_many(db, [fid], commit=False)
    db.execute("INSERT INTO raw.ingestion_runs (job_name, job_type, started_at, finished_at, status, rows_written, rows_updated, rows_normalized) "
               "VALUES ('match_knowledge', 'match_knowledge', %s, %s, 'completed', 7, 56, 9)", (NOW, NOW + timedelta(seconds=30)))

    assert cli.status_command(db, parse("status"), now=NOW + timedelta(days=1)) == 0
    said = capsys.readouterr().out
    assert f"rules: layers {layers.VERSION}, events events-v1, sides sides-v1" in said
    assert "intel.match_knowledge: 1 rows of 1 matches" in said and "core.fixture_event_kinds: 8 lines" in said
    assert "built 7, lines 56, looked at 9" in said


def test_show_prints_the_layers_one_layer_or_the_whole_row(db: psycopg.Connection[Any], seed: Seed, capsys: pytest.CaptureFixture[str]) -> None:
    fid = World(db, seed).golden()
    assert cli.show_command(db, parse("show", str(fid))) == 1
    assert "has no build" in capsys.readouterr().out
    builder.build_many(db, [fid], commit=False)

    assert cli.show_command(db, parse("show", str(fid), "--fresh")) == 0
    said = capsys.readouterr().out
    assert f"match {fid}: build" in said and "complete" in said and "c6_market" in said and "c7_context" in said
    assert "building it today says the same" in said

    assert cli.show_command(db, parse("show", str(fid), "--layer", "c6_market")) == 0
    layer = json.loads(capsys.readouterr().out)
    assert layer["status"] == "ok" and layer["data"]["1X2"]["final"]["odds"]["Home"] == 1.85
    assert cli.show_command(db, parse("show", str(fid), "--layer", "c0_nothing")) == 1 and "no layer c0_nothing" in capsys.readouterr().out

    assert cli.show_command(db, parse("show", str(fid), "--json")) == 0
    row = json.loads(capsys.readouterr().out)
    assert row["fixture_id"] == fid and row["version"] == layers.VERSION and set(row["layers"]) == set(layers.LAYERS)

    db.execute("UPDATE core.fixture_results SET goals_home = 3, ft_goals_home = 3 WHERE fixture_id = %s", (fid,))
    assert cli.show_command(db, parse("show", str(fid), "--fresh")) == 0
    assert "something else" in capsys.readouterr().out, "the stored build is out of date"


def insert_row(db: psycopg.Connection[Any], fid: int, built: layers.Knowledge, *, inputs: str, content: str | None = None,
               supersedes: int | None = None) -> None:
    db.execute("INSERT INTO intel.match_knowledge (fixture_id, version, supersedes, known_at, inputs_hash, content_hash, completeness, layers, quality) "
               "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
               (fid, built.version, supersedes, built.known_at, inputs, content or built.content_hash, built.completeness, Jsonb(built.layers),
                Jsonb(built.quality)))


def test_audit_passes_on_what_the_builder_wrote_and_names_what_is_wrong_otherwise(db: psycopg.Connection[Any], seed: Seed,
                                                                                capsys: pytest.CaptureFixture[str]) -> None:
    w = World(db, seed)
    ids = [w.golden(KICKOFF + timedelta(hours=i)) for i in range(4)]
    builder.build_many(db, ids, commit=False)
    audit = lambda *extra: cli.audit_command(db, parse("audit", "--days", "30", *extra), now=NOW + timedelta(days=1))  # noqa: E731

    assert audit() == 0
    said = capsys.readouterr().out
    assert "sample of 4 newest builds (seed 1): 0 whose content_hash is not the hash of their layers, 0 out of date" in said
    assert "0 up to date that building today would say differently" in said and "audit: ok" in said
    assert "completeness: complete 4" in said and "c6_market" in said

    assert audit("--sample", "2", "--seed", "7") == 0 and "sample of 2 newest builds (seed 7)" in capsys.readouterr().out

    # a match whose inputs changed since its build is out of date, which is for the worker to fix and not a failure
    db.execute("UPDATE core.fixture_team_stats SET shots = 15 WHERE fixture_id = %s AND team_side = 'home'", (ids[0],))
    assert audit() == 0 and "1 out of date" in capsys.readouterr().out


def test_audit_fails_on_a_row_that_is_not_the_hash_of_its_layers_and_on_a_rule_that_changed_without_a_new_version(
        db: psycopg.Connection[Any], seed: Seed, capsys: pytest.CaptureFixture[str]) -> None:
    w = World(db, seed)
    torn, drifted = w.golden(), w.golden(KICKOFF + timedelta(hours=1))
    audit = lambda: cli.audit_command(db, parse("audit", "--days", "30"), now=NOW + timedelta(days=1))  # noqa: E731
    signatures = reader.signatures(db, [torn, drifted])

    built = layers.build(reader.read(db, [torn])[torn].inputs)
    insert_row(db, torn, built, inputs=signatures[torn], content="0" * 64)
    assert audit() == 1
    said = capsys.readouterr().out
    assert "1 whose content_hash is not the hash of their layers" in said and f"match {torn}: the stored content_hash is not the hash of its layers" in said
    assert "FAIL:" in said and "audit: FAILED" in said

    # the other match: stored by an older rule (its layers say something else, hashed honestly), but up to date as far as its inputs go
    other = layers.build(reader.read(db, [drifted])[drifted].inputs)
    changed = {**other.layers, layers.C6_MARKET: {"status": "missing", "sources": []}}
    forged = layers.Knowledge(version=other.version, layers=changed, quality=other.quality, completeness=other.completeness,
                              known_at=other.known_at, content_hash=layers.content_hash(changed, other.quality, other.completeness))
    insert_row(db, drifted, forged, inputs=signatures[drifted])
    assert audit() == 1
    said = capsys.readouterr().out
    assert "1 up to date that building today would say differently" in said and "a rule changed and its version did not" in said
    assert f"match {drifted}: up to date, and building it today says something else" in said
