"""scripts/sentry_drill.py - the drill of the "new exception" alert (security plan S3.5): ONE made-up error, with the settings of the API and the worker, a new issue on
every run, and never the DSN in what it prints. The Sentry SDK is replaced by a recorder: nothing leaves the machine."""

from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
from scripts import sentry_drill

from fbi.core import sentry

BACKEND = Path(__file__).resolve().parents[2]
DSN = "https://0123456789abcdef0123456789abcdef@o4500000000.ingest.example.invalid/4500000001"


class FakeScope:
    def __init__(self) -> None:
        self.fingerprint: list[str] | None = None
        self.tags: dict[str, str] = {}

    def set_tag(self, key: str, value: str) -> None:
        self.tags[key] = value

    def __enter__(self) -> FakeScope:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


class FakeSdk:
    """What sentry_drill and fbi.core.sentry call on the SDK, recorded."""

    def __init__(self, *, drop: bool = False, start_fails: bool = False) -> None:
        self.drop, self.start_fails = drop, start_fails
        self.init_options: list[dict[str, Any]] = []
        self.global_tags: dict[str, str] = {}
        self.events: list[dict[str, Any]] = []
        self.flushed: list[float | None] = []
        self._scope = FakeScope()

    def init(self, **options: Any) -> None:
        if self.start_fails:
            raise ValueError("Unsupported scheme")
        self.init_options.append(options)

    def set_tag(self, key: str, value: str) -> None:
        self.global_tags[key] = value

    def new_scope(self) -> FakeScope:
        self._scope = FakeScope()
        return self._scope

    def capture_exception(self, exc: BaseException) -> str | None:
        if self.drop:
            return None
        self.events.append(
            {
                "exc": exc,
                "fingerprint": self._scope.fingerprint,
                "tags": dict(self._scope.tags),
                "traceback": exc.__traceback__,
            }
        )
        return f"{len(self.events):032x}"

    def flush(self, timeout: float | None = None) -> None:
        self.flushed.append(timeout)


@pytest.fixture
def sdk(monkeypatch: pytest.MonkeyPatch) -> FakeSdk:
    fake = FakeSdk()
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake)
    monkeypatch.setenv("FBI_SENTRY_DSN", DSN)
    monkeypatch.setenv("FBI_ENV", "production")
    return fake


def test_without_a_dsn_nothing_is_sent_and_it_says_so(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeSdk()
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake)
    monkeypatch.delenv("FBI_SENTRY_DSN", raising=False)
    assert sentry_drill.main() == 2
    assert fake.init_options == [] and fake.events == [] and fake.flushed == []
    assert "FBI_SENTRY_DSN is empty" in capsys.readouterr().err


def test_one_made_up_error_with_the_settings_of_the_api(
    sdk: FakeSdk, capsys: pytest.CaptureFixture[str]
) -> None:
    assert sentry_drill.main() == 0
    # the SDK started with exactly what the API and the worker start it with: no user, no IP, no cookies, no local variables, no tracing
    assert sdk.init_options == [sentry.options("drill")]
    options = sdk.init_options[0]
    assert options["send_default_pii"] is False
    assert options["include_local_variables"] is False
    assert options["max_request_body_size"] == "never"
    assert options["traces_sample_rate"] == 0.0
    assert options["server_name"] == "drill"  # the issue says where it came from
    assert options["environment"] == "production"
    assert sdk.global_tags == {"component": "drill"}
    # one event, with a stack (the issue is worth reading), and the SDK was flushed before the process ended
    assert len(sdk.events) == 1
    event = sdk.events[0]
    assert type(event["exc"]).__name__ == "SentryDrillError"
    assert str(event["exc"]).startswith("SIMULACRO ") and "no es un fallo" in str(event["exc"])
    assert event["traceback"] is not None
    assert event["tags"] == {"drill": "true"}
    assert sdk.flushed == [10]
    out = capsys.readouterr()
    assert re.search(r"sent at \d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ UTC", out.out)
    assert event["fingerprint"][1] in out.out  # the time the owner is told is the time in the event


def test_every_run_is_a_new_issue(sdk: FakeSdk, monkeypatch: pytest.MonkeyPatch) -> None:
    """Sentry groups by fingerprint; two runs that shared one would be a single issue and the second would not alert."""
    times = iter(["2026-10-27T20:00:01Z", "2026-10-27T20:09:44Z"])
    monkeypatch.setattr(sentry_drill, "stamp", lambda: next(times))
    assert sentry_drill.main() == 0
    assert sentry_drill.main() == 0
    prints = [e["fingerprint"] for e in sdk.events]
    assert prints == [["simulacro", "2026-10-27T20:00:01Z"], ["simulacro", "2026-10-27T20:09:44Z"]]
    assert prints[0] != prints[1]


def test_the_dsn_is_never_printed(
    sdk: FakeSdk, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for fake in (sdk, FakeSdk(drop=True), FakeSdk(start_fails=True)):
        monkeypatch.setitem(sys.modules, "sentry_sdk", fake)
        sentry_drill.main()
    seen = capsys.readouterr()
    for secret in ("0123456789abcdef", "example.invalid", "4500000001"):
        assert secret not in seen.out + seen.err


def test_a_dropped_event_is_a_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeSdk(drop=True)
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake)
    monkeypatch.setenv("FBI_SENTRY_DSN", DSN)
    assert sentry_drill.main() == 1
    assert "dropped the event" in capsys.readouterr().err


def test_an_sdk_that_does_not_start_is_a_failure(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    fake = FakeSdk(start_fails=True)
    monkeypatch.setitem(sys.modules, "sentry_sdk", fake)
    monkeypatch.setenv("FBI_SENTRY_DSN", "not-a-dsn")
    assert sentry_drill.main() == 1
    assert fake.events == []
    assert "did not start" in capsys.readouterr().err


def test_run_as_a_module_without_a_dsn_it_exits_with_2() -> None:
    """`python -m scripts.sentry_drill` is what `predigolctl sentry-drill` runs in the ops container."""
    env = {k: v for k, v in os.environ.items() if k != "FBI_SENTRY_DSN"}
    result = subprocess.run(
        [sys.executable, "-m", "scripts.sentry_drill"],
        cwd=BACKEND,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
        check=False,
    )
    assert result.returncode == 2, result.stderr
    assert "FBI_SENTRY_DSN is empty" in result.stderr
