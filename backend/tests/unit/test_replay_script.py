"""The script of the replay bank (IA-047): what runs read-only, what may write, the window it reads and its exit codes."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import psycopg
import pytest
from scripts import ia_replay_bank as script

from fbi.ai.calendar import day_start
from fbi.ai.replay import harness

AT = datetime(2026, 11, 11, 15, 0, tzinfo=UTC)


class Session:
    def __init__(self) -> None:
        self.commits = 0

    def __enter__(self) -> Session:
        return self

    def __exit__(self, *a: Any) -> None:
        return None

    def commit(self) -> None:
        self.commits += 1


@pytest.mark.parametrize("argv, writes", [
    (["build"], False), (["build", "--write"], True), (["plan"], False), (["run"], False), (["run", "--confirm-owner"], True),
    (["report"], True), (["report", "--no-record"], False)])
def test_only_what_the_owner_or_the_operator_asked_to_write_opens_a_session_that_can_write(monkeypatch: pytest.MonkeyPatch,
                                                                                           argv: list[str], writes: bool) -> None:
    opened: list[str] = []

    def connect(dsn: str, *, options: str) -> Session:
        opened.append(options)
        return Session()

    monkeypatch.setattr(psycopg, "connect", connect)
    monkeypatch.setattr(script, "execute", lambda command, conn, settings, args, at: ({"command": command}, script.OK))
    assert script.main([*argv, "--dsn", "postgresql://x/y"]) == script.OK
    [options] = opened
    assert ("default_transaction_read_only=on" in options) is not writes
    assert "statement_timeout" in options and "TimeZone=UTC" in options


def test_the_window_is_the_complete_bogota_days_before_today_unless_it_is_said() -> None:
    args = script.build_parser().parse_args(["plan"])
    since, until = script.window_of(args, AT)
    assert (since, until) == (day_start(date(2026, 10, 28)), day_start(date(2026, 11, 11)))
    args = script.build_parser().parse_args(["plan", "--since", "2026-11-04", "--until", "2026-11-10"])
    assert script.window_of(args, AT) == (day_start(date(2026, 11, 4)), day_start(date(2026, 11, 10)))
    with pytest.raises(ValueError):
        script.window_of(script.build_parser().parse_args(["plan", "--since", "2026-11-10", "--until", "2026-11-10"]), AT)


def test_the_defaults_are_the_dry_ones_and_the_scopes_are_the_banks() -> None:
    args = script.build_parser().parse_args(["run"])
    assert args.confirm_owner is False and args.write is False and args.no_record is False
    assert args.limit_per_scope == 200 and str(args.max_usd) == "5.00" and args.scope is None
    with pytest.raises(SystemExit):
        script.build_parser().parse_args(["run", "--scope", "council/escalation"])


def test_a_report_of_a_scope_that_does_not_pass_is_not_a_success(monkeypatch: pytest.MonkeyPatch) -> None:
    args = script.build_parser().parse_args(["report"])
    session = Session()
    for state, scopes, code in (("ended", {"a": {"verdict": "PASA"}}, script.OK), ("ended", {"a": {"verdict": "INSUFICIENTE"}}, script.NO),
                                ("waiting", {}, script.WAITING), ("nothing_submitted", {}, script.CANNOT)):
        monkeypatch.setattr(harness, "report", lambda conn, *, at, record, s=state, v=scopes: {"state": s, "scopes": v})
        assert script.execute("report", session, None, args, at=AT)[1] == code  # type: ignore[arg-type]
