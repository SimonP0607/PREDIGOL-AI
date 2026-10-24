"""The command of plan F12 (python -m scripts.promotion_trace): `show` reads through a connection that cannot write; `sync` is a dry run until
--confirm and commits only then; a ledger entry that cites what does not exist is refused and leaves nothing."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
from scripts import promotion_trace as cli

from fbi.research import trace

LEDGER_SINCE = datetime(2026, 10, 22, 13, 0, tzinfo=UTC)


class Connection:
    def __init__(self, seen: dict[str, Any]) -> None:
        self.seen = seen

    def __enter__(self) -> Connection:
        return self

    def __exit__(self, *exc: object) -> None:
        self.seen["closed"] = True

    def commit(self) -> None:
        self.seen["committed"] = True

    def rollback(self) -> None:
        self.seen["rolled_back"] = True


@pytest.fixture()
def seen(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    state: dict[str, Any] = {}

    def connect(url: str, **kwargs: Any) -> Connection:
        state["options"] = kwargs.get("options")
        return Connection(state)

    monkeypatch.setattr(psycopg, "connect", connect)  # the very module the command calls through
    return state


def test_show_reads_through_a_connection_that_cannot_write_and_passes_the_window(
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], seen: dict[str, Any]) -> None:
    def fake_trace(conn: Connection, **kwargs: Any) -> dict[str, Any]:
        seen["asked"] = kwargs
        return {"now": kwargs["now"], "since": kwargs["now"], "days": kwargs["days"], "ledger_since": LEDGER_SINCE, "ledger_in_force": "mc9a7bec97ca",
                "fingerprints": [], "counts": {"fingerprints": 0, "counted": 0, "traced": 0, "untraced": 0, "pending_sync": 0, "after_use": 0,
                                               "pre_ledger": 0}, "coverage": None, "other": {"goal_spec": 1}}

    monkeypatch.setattr(trace, "trace", fake_trace)
    assert cli.main(["show", "--days", "7"]) == 0
    out = capsys.readouterr().out
    assert seen["options"] == "-c default_transaction_read_only=on", "it reads; it cannot write by mistake"
    assert seen["asked"]["days"] == 7 and "no change since the ledger began" in out and "mc9a7bec97ca" in out
    assert cli.main(["show", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["ledger_since"] == LEDGER_SINCE.isoformat(), "datetimes print as text"
    assert seen["asked"]["days"] == trace.DEFAULT_DAYS == 30, "the plan's window by default"


def test_sync_writes_nothing_until_confirmed_and_commits_only_then(
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], seen: dict[str, Any]) -> None:
    def fake_sync(conn: Connection, *, now: datetime, confirm: bool) -> list[str]:
        seen["confirm"] = confirm
        return [f"{'WRITE' if confirm else 'WOULD WRITE'} mc9a7bec97ca (F0, system, baseline): a baseline"]

    monkeypatch.setattr(trace, "sync", fake_sync)
    assert cli.main(["sync"]) == 0
    assert seen["confirm"] is False and seen.get("rolled_back") and not seen.get("committed")
    assert "WOULD WRITE mc9a7bec97ca" in capsys.readouterr().out and seen["options"] is None, "sync is the one that may write"
    seen.clear()
    assert cli.main(["sync", "--confirm"]) == 0
    assert seen["confirm"] is True and seen.get("committed") and not seen.get("rolled_back")
    out = capsys.readouterr().out
    assert "WRITE mc9a7bec97ca" in out and "Nothing was written" not in out


def test_sync_refuses_an_entry_that_cites_what_does_not_exist_and_leaves_nothing(
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], seen: dict[str, Any]) -> None:
    def refuse(conn: Connection, *, now: datetime, confirm: bool) -> list[str]:
        raise LookupError("mc9a7bec97ca: hypothesis 12 does not exist")

    monkeypatch.setattr(trace, "sync", refuse)
    assert cli.main(["sync", "--confirm"]) == 3
    assert "refused: mc9a7bec97ca: hypothesis 12 does not exist" in capsys.readouterr().err
    assert seen.get("rolled_back") and not seen.get("committed")
