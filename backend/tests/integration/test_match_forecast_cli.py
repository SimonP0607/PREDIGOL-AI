"""``python -m scripts.match_forecast`` and what it prints (plan F5): what PrediGol has said, set by set and when, the matches that have
none and why, and a dry run until ``--apply``.

The commands are run with the test's own connection; ``main`` is run against the scratch database itself, for the paths that open
their own connection (and so see only what is committed)."""

from __future__ import annotations

import re
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import psycopg
import pytest
from scripts import match_forecast as cli

from tests.integration.test_forecast_in_the_packet import forecast_world
from tests.integration.test_match_forecast import AT, World, world  # noqa: F401  (the fixture and the data)

pytestmark = pytest.mark.integration


def run(db: psycopg.Connection[Any], *argv: str) -> int:
    args = cli.build_parser().parse_args(list(argv))
    if args.command == "write":
        return cli.write_command(db, args)
    return int(cli.READ_ONLY[args.command](db, args))


def said(capsys: pytest.CaptureFixture[str]) -> str:
    return capsys.readouterr().out


def test_status_counts_what_was_said_and_how_much_of_it_is_calibrated(world: World, capsys: pytest.CaptureFixture[str]) -> None:  # noqa: F811
    forecast_world(world)
    assert run(world.db, "status", "--days", "400") == 0
    out = said(capsys)

    assert "PrediGol's forecast (forecast-v1)" in out
    assert "market sets (one per market and moment)" in out
    assert "1X2  UNCALIBRATED no_champion" in out and "dixon_coles" in out
    assert "OU   CALIBRATED   champion" in out
    assert "BTTS UNCALIBRATED no_champion" in out
    assert "2026-10-03" in out, "the per-day count"


def test_show_prints_each_set_with_when_it_was_said_and_what_it_had_said_by_a_moment(
        world: World, capsys: pytest.CaptureFixture[str]) -> None:  # noqa: F811
    fid = forecast_world(world, champion=False)
    world.predict_all(fid, "dixon_coles", cutoff=AT, shift=0.12)
    world.write(fid, AT + timedelta(hours=3))

    assert run(world.db, "show", str(fid), "--at", (AT + timedelta(hours=1)).isoformat()) == 0
    first = said(capsys)
    assert f"match {fid}: what PrediGol had said by" in first
    assert re.search(r"Home\s+50\.0%", first) and not re.search(r"Home\s+62\.0%", first), "the later set had not been said yet"

    assert run(world.db, "show", str(fid), "--at", (AT + timedelta(hours=4)).isoformat()) == 0
    both = said(capsys)
    older, newer = re.search(r"Home\s+50\.0%", both), re.search(r"Home\s+62\.0%", both)
    assert older and newer, "both sets"
    assert older.start() < newer.start(), "in the order they were said"

    assert run(world.db, "show", str(fid), "--at", (AT - timedelta(hours=1)).isoformat()) == 0
    assert "PrediGol had said nothing by" in said(capsys)


def test_the_calibrated_total_shows_the_models_own_number(world: World, capsys: pytest.CaptureFixture[str]) -> None:  # noqa: F811
    fid = forecast_world(world)
    assert run(world.db, "show", str(fid), "--at", (AT + timedelta(hours=1)).isoformat()) == 0
    out = said(capsys)
    assert "CALIBRATED (champion)" in out and "model  62.0%" in out


def test_write_is_a_dry_run_until_apply(world: World, capsys: pytest.CaptureFixture[str]) -> None:  # noqa: F811
    fid = world.fixture()
    world.predict_all(fid, "dixon_coles")
    assert run(world.db, "write", "--fixture", str(fid)) == 0
    assert said(capsys).startswith("dry run, would write: ")
    assert run(world.db, "write", "--fixture", str(fid), "--apply") == 0
    assert said(capsys).startswith("written: ")


def test_main_runs_on_its_own_connection(migrated_database: str, monkeypatch: pytest.MonkeyPatch,
                                         capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(cli, "settings", SimpleNamespace(database=SimpleNamespace(psycopg_url=migrated_database)))
    monkeypatch.setattr(cli, "configure_logging", lambda _level: None)     # (it would reconfigure the logs of the rest of the session)
    assert cli.main(["status"]) == 0 and "PrediGol's forecast (forecast-v1)" in said(capsys)
    assert cli.main(["show", "424242"]) == 0 and "had said nothing" in said(capsys)
    assert cli.main(["write"]) == 0 and "dry run, would write: " in said(capsys)
