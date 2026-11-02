"""The command line of the battery (``scripts/ia_battery.py``), the part that needs no database and no key: what it accepts, what its guide
says, and the ``offline`` command - the one that is run first, before any money is at stake, and must work on a machine that has neither.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
from scripts import ia_battery

from fbi.ai.battery import MIN_CASES, TARGETS, corpus, offline, run
from fbi.ai.battery.offline import Finding, OfflineReport
from fbi.ai.config import AiSettings
from fbi.core.config import settings as platform


def parse(*argv: str) -> Any:
    return ia_battery.build_parser().parse_args(list(argv))


# ── what it accepts ─────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("command", ia_battery.COMMANDS)
def test_every_command_of_the_guide_is_accepted_and_the_options_default_to_the_whole_battery(command: str) -> None:
    args = parse(command)
    assert args.command == command and args.targets == list(TARGETS) and args.native is False
    assert args.suffix == "" and args.no_record is False and args.dsn is None


def test_the_commands_are_these_five_in_this_order() -> None:
    assert ia_battery.COMMANDS == ("offline", "plan", "submit", "collect", "status")


def test_the_options_say_what_they_say() -> None:
    args = parse("collect", "--targets", "extract", "--native", "--suffix", "2", "--no-record", "--dsn", "postgresql://example/none")
    assert (args.targets, args.native, args.suffix, args.no_record, args.dsn) == (["extract"], True, "2", True, "postgresql://example/none")
    assert parse("plan", "--targets", "review", "extract").targets == ["review", "extract"]
    assert parse("plan", "--targets", "claims").targets == ["claims"] and parse("plan", "--targets", "extract", "claims").targets == ["extract", "claims"]


@pytest.mark.parametrize("argv", [[], ["ask"], ["submit", "--targets", "brief"], ["submit", "--targets"], ["plan", "--unknown"], ["Submit"]])
def test_whatever_else_is_a_usage_error_and_a_usage_error_exits_with_two(argv: list[str], capsys: pytest.CaptureFixture[str]) -> None:
    with pytest.raises(SystemExit) as stop:
        ia_battery.build_parser().parse_args(argv)
    assert stop.value.code == ia_battery.CANNOT == 2
    assert capsys.readouterr().err, "and it says why"


def test_the_exit_statuses_are_the_ones_of_every_other_command_of_the_lab() -> None:
    from scripts import ia_probe

    assert (ia_battery.OK, ia_battery.NO, ia_battery.CANNOT, ia_battery.WAITING) == (ia_probe.OK, ia_probe.NO, ia_probe.CANNOT, ia_probe.WAITING)
    assert (ia_battery.OK, ia_battery.NO, ia_battery.CANNOT, ia_battery.WAITING) == (0, 1, 2, 3)


# ── what its guide says ─────────────────────────────────────────────────────────────────────────────────────────────

def test_the_guide_names_every_command_and_every_option_and_the_four_exit_statuses() -> None:
    guide = ia_battery.__doc__ or ""
    for command in ia_battery.COMMANDS:
        assert f"python -m scripts.ia_battery {command}" in guide, command
    parser = ia_battery.build_parser()
    options = {s for action in parser._actions for s in action.option_strings if s.startswith("--")} - {"--help"}
    assert options == {"--targets", "--native", "--suffix", "--no-record", "--dsn"}
    for option in options:
        assert f"``{option}" in guide, option
    for status in ("0 done and PASA", "1 done and not PASA", "2 could not run", "3 asks still on their way"):
        assert status in guide, status
    assert f"{len(corpus.CASES)} cases" in guide and len(corpus.CASES) == 120, "it says how many cases there are"


def test_the_help_is_the_first_paragraph_of_the_guide() -> None:
    text = ia_battery.build_parser().format_help()
    assert "ia_battery" in text and "adversarial battery" in text
    assert re.search(r"\{offline,plan,submit,collect,status\}", text)


# ── offline ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_offline_is_ok_for_the_corpus_in_force_and_counts_what_it_checked() -> None:
    report, code = ia_battery.run_offline(list(TARGETS), native=False)
    assert code == ia_battery.OK and report["verdict"] == "PASA" and report["findings"] == []
    assert report["checked"] == {"cases": 120, "bases": 9, "minimum": MIN_CASES}
    only, code = ia_battery.run_offline(["extract"], native=True)
    assert code == ia_battery.OK and only["checked"] == {"cases": 40, "bases": 3, "minimum": MIN_CASES}
    third, code = ia_battery.run_offline(["claims"], native=False)
    assert code == ia_battery.OK and third["checked"] == {"cases": 40, "bases": 3, "minimum": MIN_CASES}


def test_a_defect_found_offline_is_exit_one_and_is_listed(monkeypatch: pytest.MonkeyPatch) -> None:
    found = Finding("review.hidden_html.2", "hidden_survives", "the hidden text is still in what the model reads")
    monkeypatch.setattr(offline, "run", lambda targets, native=False: OfflineReport({"cases": 120, "bases": 9, "minimum": MIN_CASES}, (found,)))
    report, code = ia_battery.run_offline(list(TARGETS), native=False)
    assert code == ia_battery.NO and report["verdict"] == "NO PASA" and report["findings"] == [found.as_json()]


def test_main_offline_prints_the_report_as_json_and_returns_its_status_with_no_database_and_no_settings(
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    def never(*_a: object, **_k: object) -> None:
        raise AssertionError("the offline command touched what it must not need")

    monkeypatch.setattr(psycopg, "connect", never)
    monkeypatch.setattr(AiSettings, "from_env", never)
    assert ia_battery.main(["offline"]) == ia_battery.OK
    printed = json.loads(capsys.readouterr().out)
    assert printed["verdict"] == "PASA" and printed["checked"]["cases"] == 120
    assert ia_battery.main(["offline", "--targets", "review"]) == ia_battery.OK
    assert json.loads(capsys.readouterr().out)["checked"]["cases"] == 40
    assert ia_battery.main(["offline", "--targets", "claims"]) == ia_battery.OK
    assert json.loads(capsys.readouterr().out)["checked"]["cases"] == 40


def test_main_offline_returns_one_when_something_was_found(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(offline, "run", lambda targets, native=False: OfflineReport({"cases": 1, "bases": 1, "minimum": MIN_CASES},
                                                                                    (Finding("review.ignore.1", "flag_missing", "no flag"),)))
    assert ia_battery.main(["offline"]) == ia_battery.NO
    assert json.loads(capsys.readouterr().out)["findings"][0]["check"] == "flag_missing"


# ── the command line, from the arguments to the command ────────────────────────────────────────────────────────────

class Connection:
    """What ``psycopg.connect`` gives back, as far as ``main`` uses it: a context manager."""

    def __enter__(self) -> Connection:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def main_with_a_stub(monkeypatch: pytest.MonkeyPatch, argv: list[str], status: int = ia_battery.WAITING) -> dict[str, Any]:
    """Run ``main`` with the database, the settings and the command replaced by stubs that remember what they were given."""
    seen: dict[str, Any] = {}

    def connect(url: str, **kw: Any) -> Connection:
        seen["connect"] = (url, kw)
        return Connection()

    def execute(command: str, conn: Any, settings: Any, **kw: Any) -> tuple[dict[str, Any], int]:
        seen["execute"] = (command, conn, settings, kw)
        return {"state": "waiting"}, status

    monkeypatch.setattr(psycopg, "connect", connect)
    monkeypatch.setattr(AiSettings, "from_env", staticmethod(lambda: "the settings"))
    monkeypatch.setattr(ia_battery, "execute", execute)
    seen["code"] = ia_battery.main(argv)
    return seen


def test_main_hands_every_option_to_the_command_and_exits_with_its_status(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    seen = main_with_a_stub(monkeypatch, ["collect", "--targets", "extract", "--native", "--suffix", "2", "--no-record", "--dsn", "postgresql://example/none"])
    assert seen["code"] == ia_battery.WAITING and json.loads(capsys.readouterr().out) == {"state": "waiting"}
    assert seen["connect"] == ("postgresql://example/none", {"options": "-c TimeZone=UTC"}), "in UTC, in the database it was given"
    command, conn, settings, kw = seen["execute"]
    assert (command, settings) == ("collect", "the settings") and isinstance(conn, Connection)
    at = kw.pop("at")
    assert kw == {"targets": ["extract"], "native": True, "suffix": "2", "record": False}
    assert at.tzinfo is not None and abs((datetime.now(UTC) - at).total_seconds()) < 60, "now, with its zone"


def test_main_without_options_asks_for_the_whole_battery_in_the_workers_database_and_records(
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    seen = main_with_a_stub(monkeypatch, ["submit"], status=ia_battery.OK)
    assert seen["code"] == ia_battery.OK and capsys.readouterr().out
    assert seen["connect"][0] == platform.database.psycopg_url
    command, _conn, _settings, kw = seen["execute"]
    kw.pop("at")
    assert command == "submit" and kw == {"targets": list(TARGETS), "native": False, "suffix": "", "record": True}


@pytest.mark.parametrize("command", ["plan", "submit", "collect", "status"])
def test_every_command_that_uses_the_database_goes_through_execute_and_offline_never_does(
        command: str, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    seen = main_with_a_stub(monkeypatch, [command, "--dsn", "postgresql://example/none"])
    assert seen["execute"][0] == command and seen["code"] == ia_battery.WAITING
    capsys.readouterr()


# ── what a command says in its exit status, from the report of the round ──────────────────────────────────────────

class Writes:
    """A connection that only remembers how many times it was committed."""

    def __init__(self) -> None:
        self.commits = 0

    def commit(self) -> None:
        self.commits += 1


def test_offline_asks_the_corpus_of_the_route_and_of_the_targets_it_was_given(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    seen: list[tuple[tuple[str, ...], bool]] = []

    def spy(targets: Any, native: bool = False) -> OfflineReport:
        seen.append((tuple(targets), native))
        return OfflineReport({"cases": 0, "bases": 0, "minimum": MIN_CASES}, ())

    monkeypatch.setattr(offline, "run", spy)
    ia_battery.run_offline(["review"], native=True)
    assert ia_battery.main(["offline", "--targets", "extract", "--native"]) == ia_battery.OK
    assert ia_battery.main(["offline"]) == ia_battery.OK
    capsys.readouterr()
    assert seen == [(("review",), True), (("extract",), True), (("review", "extract", "claims"), False)]


@pytest.mark.parametrize(("report", "code"), [
    ({"submitted": 0, "failed": 110, "error": "timeout"}, ia_battery.NO),
    ({"submitted": 0, "failed": 110, "error": None}, ia_battery.NO),
    ({"submitted": 55, "failed": 0, "error": "the provider said no"}, ia_battery.NO),
    ({"submitted": 110, "failed": 0, "error": None}, ia_battery.OK),
    ({"submitted": 0, "nothing_due": True}, ia_battery.OK),
    ({"submitted": 0, "dry_run": True}, ia_battery.OK),
    ({"submitted": 0, "blockers": ["no LAB key"]}, ia_battery.CANNOT),
])
def test_submit_exits_one_when_any_part_of_the_round_did_not_go_and_the_command_commits_what_it_wrote(
        report: dict[str, Any], code: int, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run, "submit", lambda *a, **kw: report)
    conn: Any = Writes()
    settings: Any = "settings"
    assert ia_battery.execute("submit", conn, settings, targets=["review"], at=datetime.now(UTC)) == (report, code)
    assert conn.commits == 1


@pytest.mark.parametrize(("report", "code"), [
    ({"state": "waiting", "open": 3}, ia_battery.WAITING),
    ({"state": "incomplete", "verdict": "INCOMPLETA"}, ia_battery.WAITING),
    ({"state": "ended", "verdict": "PASA"}, ia_battery.OK),
    ({"state": "ended", "verdict": "NO PASA"}, ia_battery.NO),
    ({"state": "ended", "verdict": "INSUFICIENTE"}, ia_battery.NO),
])
def test_collect_exits_with_what_the_measurement_decided_and_commits(report: dict[str, Any], code: int, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run, "collect", lambda *a, **kw: report)
    conn: Any = Writes()
    settings: Any = "settings"
    assert ia_battery.execute("collect", conn, settings, targets=["review"], at=datetime.now(UTC)) == (report, code)
    assert conn.commits == 1


def test_collect_before_a_round_was_sent_says_what_to_do_first(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(run, "collect", lambda *a, **kw: {"state": "nothing_submitted"})
    conn: Any = Writes()
    settings: Any = "settings"
    report, code = ia_battery.execute("collect", conn, settings, targets=["review"], at=datetime.now(UTC))
    assert code == ia_battery.CANNOT and report["blockers"] == ["no round was sent for this corpus: run submit first"] and conn.commits == 1
