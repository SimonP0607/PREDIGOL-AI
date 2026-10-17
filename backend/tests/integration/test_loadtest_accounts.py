"""scripts.loadtest_accounts: the load test's accounts appear with one private password, are switched off after
the test, and come back for the next one - nothing is ever deleted."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from scripts import loadtest_accounts

from fbi.auth import throttle
from fbi.auth.settings import reset as reset_auth_settings
from fbi.core.config import reset_cache

SAME_SITE = {"x-requested-with": "predigol"}


@pytest.fixture()
def db(migrated_database: str) -> Iterator[str]:
    mp = pytest.MonkeyPatch()
    mp.setenv("FBI_DATABASE_URL", migrated_database.replace("postgresql://", "postgresql+psycopg://"))
    reset_cache()
    reset_auth_settings()
    throttle.reset_all()
    with psycopg.connect(migrated_database, autocommit=True) as conn:
        for t in ("auth.sessions", "auth.recovery_codes", "auth.audit_events", "auth.users"):
            conn.execute(f"DELETE FROM {t}")
    yield migrated_database
    mp.undo()
    reset_cache()
    reset_auth_settings()


def run(*argv: str, monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.setattr(sys, "argv", ["loadtest_accounts", *argv])
    return loadtest_accounts.main()


def sign_in(email: str, password: str) -> int:
    from fbi.api.app import create_app

    with TestClient(create_app(), headers=SAME_SITE) as c:
        return c.post("/api/v1/auth/login", json={"email": email, "password": password}).status_code


def test_create_disable_and_create_again(db: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    out = tmp_path / "accounts.txt"
    assert run("create", "--count", "3", "--out", str(out), monkeypatch=monkeypatch) == 0
    assert not out.exists()  # a dry run without --confirm
    assert run("create", "--count", "3", "--out", str(out), "--confirm", monkeypatch=monkeypatch) == 0
    assert oct(out.stat().st_mode & 0o777) == "0o600"
    lines = [line.split("\t") for line in out.read_text().splitlines()]
    assert [e for e, _ in lines] == [f"loadtest-00{i}@loadtest.predigol.local" for i in (1, 2, 3)]
    email, password = lines[0]
    assert sign_in(email, password) == 200

    assert run("disable", "--confirm", monkeypatch=monkeypatch) == 0
    with psycopg.connect(db) as conn:
        row = conn.execute("SELECT count(*) FILTER (WHERE status = 'disabled'), count(*) FROM auth.users").fetchone()
        assert row == (3, 3)
        open_sessions = conn.execute("SELECT count(*) FROM auth.sessions WHERE revoked_at IS NULL").fetchone()
        assert open_sessions == (0,)
    assert sign_in(email, password) != 200

    # the next test run: the same accounts, active again, with a new password
    assert run("create", "--count", "3", "--out", str(out), "--confirm", monkeypatch=monkeypatch) == 0
    email, password = out.read_text().splitlines()[0].split("\t")
    assert sign_in(email, password) == 200
    with psycopg.connect(db) as conn:
        total = conn.execute("SELECT count(*) FROM auth.users").fetchone()
        assert total == (3,)
