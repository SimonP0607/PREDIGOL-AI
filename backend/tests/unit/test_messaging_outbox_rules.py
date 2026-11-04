"""The queue's rules that need no database (plan UX, A5): what stops a message, the key the provider deduplicates on,
the retry schedule, the switches - and the messenger's place among the jobs and the owner's notices."""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
import yaml

from fbi.messaging import notices, outbox, runner
from fbi.messaging.outbox import MAX_ATTEMPTS, RETRY_DELAYS, idempotency_key, suppression
from fbi.notify.service import KINDS
from fbi.ops.run_watchdog import JOB_TIMEOUTS, timeout_for

BACKEND = Path(__file__).resolve().parents[2]


def row(**kw: object) -> dict[str, object]:
    base: dict[str, object] = {"email": "lector@example.com", "email_status": None, "email_off": None,
                               "category": "privacy"}
    return base | kw


@pytest.mark.parametrize(("kw", "reason"), [
    ({}, None),
    ({"email": ""}, "no address"),
    ({"email": "deleted-12@predigol.invalid"}, "no address"),
    ({"email_status": "bounced", "category": "security"}, "address bounced"),
    ({"email_status": "complained", "category": "security"}, None),
    ({"email_status": "complained", "category": "membership"}, "address complained"),
    ({"email_off": ["membership"], "category": "membership"}, "switched off by the reader"),
    ({"email_off": ["membership"], "category": "support"}, None),
    ({"email_off": ["privacy"], "category": "privacy"}, None),  # mandatory: a stray value switches nothing off
])
def test_what_stops_a_message(kw: dict[str, object], reason: str | None) -> None:
    assert suppression(row(**kw)) == reason


def test_the_same_message_has_the_same_key_whichever_attempt() -> None:
    created = datetime(2026, 10, 25, 20, 0, tzinfo=UTC)
    key = idempotency_key("privacy_request_received:12", created)
    assert key == idempotency_key("privacy_request_received:12", created) == "privacy_request_received:12@1792958400"
    assert key != idempotency_key("privacy_request_received:12", created + timedelta(seconds=1))
    assert len(idempotency_key("k" * 300, created)) == 256


def test_the_retries_are_one_five_thirty_minutes_two_and_twelve_hours_then_failed() -> None:
    assert [d.total_seconds() for d in RETRY_DELAYS] == [60, 300, 1800, 7200, 43200]
    assert MAX_ATTEMPTS == 6


def test_sending_is_born_off_and_the_cap_under_the_free_quota(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FBI_EMAIL_SEND", raising=False)
    assert not outbox.sending_enabled()
    for value, on in (("1", True), ("on", True), ("true", True), ("0", False), ("off", False), ("", False)):
        monkeypatch.setenv("FBI_EMAIL_SEND", value)
        assert outbox.sending_enabled() is on
    monkeypatch.delenv("FBI_EMAIL_DAILY_CAP", raising=False)
    assert outbox.daily_cap() == 90 < 100
    monkeypatch.setenv("FBI_EMAIL_DAILY_CAP", "lots")
    assert outbox.daily_cap() == 90


def test_the_messenger_is_a_job_the_watchdog_knows_and_its_notices_are_kinds_the_notifier_sends() -> None:
    assert runner.JOB_TYPE in JOB_TIMEOUTS and timeout_for(runner.JOB_TYPE) >= timedelta(seconds=3 * runner.CYCLE_S)
    spec = importlib.util.spec_from_file_location("m0096", BACKEND / "migrations/versions/0096_customer_messaging.py")
    assert spec and spec.loader
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    assert set(m.KINDS_BEFORE + m.KINDS_NEW) == set(KINDS) - {"lifecycle_daily"}
    source = Path(notices.__file__).read_text(encoding="utf-8")
    drafted = {k for k in m.KINDS_NEW if f'"{k}", f"' in source}
    assert drafted == {"ticket_new", "privacy_due", "outbox_failing", "synthetic_failed",
                       "membership_due"}  # A8
    # the lifecycle's morning count (plan UX, B11) joined the kinds in 0106
    spec = importlib.util.spec_from_file_location("m0106", BACKEND / "migrations/versions/0106_customer_lifecycle.py")
    assert spec and spec.loader
    m6 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m6)
    assert {*m6.KINDS_BEFORE, "lifecycle_daily"} == set(KINDS)
    assert '"lifecycle_daily", f"lifecycle_daily:' in source


def test_the_messenger_runs_alone_with_the_apis_role_and_no_raw_store() -> None:
    compose = yaml.safe_load((BACKEND / "deploy/vps/docker-compose.yml").read_text(encoding="utf-8"))
    services = compose["services"]
    messenger = services["messenger"]
    assert messenger["command"] == ["python", "-m", "apps.messenger.main"]
    assert messenger["environment"]["FBI_DATABASE_URL"].startswith("postgresql+psycopg://predigol_api:")
    assert "volumes" not in messenger, "the messenger reads no file of the RAW store"
    assert messenger["healthcheck"]["test"] == ["CMD", "python", "-m", "apps.messenger.main", "--alive"]
    assert "ports" not in messenger
    assert services["worker"]["environment"]["FBI_DATABASE_URL"].startswith("postgresql+psycopg://predigol_worker:")


def test_the_health_check_reads_the_alive_file(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.messenger import main as entry

    alive = tmp_path / "alive"
    monkeypatch.setattr(entry, "ALIVE_FILE", str(alive))
    assert entry.main(["--alive"]) == 1
    runner.touch_alive(alive)
    assert entry.main(["--alive"]) == 0 and runner.alive(alive)
