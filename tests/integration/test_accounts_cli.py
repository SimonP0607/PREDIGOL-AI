"""scripts.accounts: the operator's tools for the cut-over (QA accounts off, everyone signs in again, the owner
chooses a new password) and for emergencies."""

from __future__ import annotations

import base64
import sys
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from scripts import accounts

from fbi.auth import service, throttle, totp
from fbi.auth.settings import reset as reset_auth_settings
from fbi.core.config import reset_cache

SAME_SITE = {"x-requested-with": "predigol"}


@pytest.fixture()
def people(migrated_database: str) -> Iterator[str]:
    mp = pytest.MonkeyPatch()
    mp.setenv("FBI_DATABASE_URL", migrated_database.replace("postgresql://", "postgresql+psycopg://"))
    mp.delenv("FBI_AUTH_MFA_ROLES", raising=False)
    reset_cache()
    reset_auth_settings()
    throttle.reset_all()
    with psycopg.connect(migrated_database, autocommit=True) as conn:
        for t in ("auth.sessions", "auth.recovery_codes", "auth.audit_events", "auth.users"):
            conn.execute(f"DELETE FROM {t}")
    service.create_user_unattended(email="owner@example.com", display_name="Owner", role="SUPER_ADMIN",
                                   password="Owner-pass-2026!")
    service.create_user_unattended(email="qa.admin@predigol.local", display_name="QA", role="SUPER_ADMIN",
                                   password="Qa-admin-pass-26")
    for i in range(2):
        service.create_user_unattended(email=f"qa.user{i}@predigol.local", display_name="QA", role="USER",
                                       password="Qa-user-pass-26")
    yield migrated_database
    mp.undo()
    reset_cache()
    reset_auth_settings()


def run(*argv: str, monkeypatch: pytest.MonkeyPatch) -> int:
    monkeypatch.setattr(sys, "argv", ["accounts", *argv])
    return accounts.main()


def statuses(dsn: str) -> dict[str, str]:
    with psycopg.connect(dsn) as conn:
        return dict(conn.execute("SELECT email, status FROM auth.users").fetchall())


def test_qa_accounts_go_off_only_with_confirm_and_never_the_last_admin(people: str, monkeypatch: pytest.MonkeyPatch,
                                                                       capsys: pytest.CaptureFixture[str]) -> None:
    assert run("disable", "--domain", "predigol.local", monkeypatch=monkeypatch) == 0
    assert "would disable" in capsys.readouterr().out
    assert set(statuses(people).values()) == {"active"}
    assert run("disable", "--domain", "predigol.local", "--confirm", monkeypatch=monkeypatch) == 0
    s = statuses(people)
    assert s["owner@example.com"] == "active"
    assert {v for k, v in s.items() if k.endswith("@predigol.local")} == {"disabled"}
    assert "qa.admin@predigol.local" not in capsys.readouterr().out  # addresses are printed masked
    assert run("disable", "--email", "owner@example.com", "--confirm", monkeypatch=monkeypatch) == 1
    assert statuses(people)["owner@example.com"] == "active"


def test_the_owner_chooses_a_new_password_at_the_next_sign_in(people: str, monkeypatch: pytest.MonkeyPatch) -> None:
    assert run("require-password-change", "--email", "OWNER@example.com", monkeypatch=monkeypatch) == 0
    from fbi.api.app import create_app

    with TestClient(create_app(), headers=SAME_SITE) as c:
        me = c.post("/api/v1/auth/login", json={"email": "owner@example.com", "password": "Owner-pass-2026!"}).json()
        assert me["stage"] == "enroll"  # a SUPER_ADMIN: the authenticator first, then the new password


def test_a_test_account_gets_an_authenticator_secret_in_a_private_file(people: str, tmp_path: Path,
                                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    out = tmp_path / "qa-admin-totp.txt"
    assert run("mfa-enroll", "--email", "owner@example.com", "--secret-out", str(out), monkeypatch=monkeypatch) == 1
    assert not out.exists()
    assert run("mfa-enroll", "--email", "qa.admin@predigol.local", "--secret-out", str(out),
               monkeypatch=monkeypatch) == 0
    assert oct(out.stat().st_mode & 0o777) == "0o600"
    raw = out.read_text().strip()
    secret = base64.b32decode(raw + "=" * (-len(raw) % 8))
    from fbi.api.app import create_app

    with TestClient(create_app(), headers=SAME_SITE) as c:
        me = c.post("/api/v1/auth/login",
                    json={"email": "qa.admin@predigol.local", "password": "Qa-admin-pass-26"}).json()
        assert me["stage"] == "mfa"
        ok = c.post("/api/v1/auth/mfa/verify", json={"code": totp.code_at(secret, totp.step_at())})
        assert ok.status_code == 200 and ok.json()["stage"] == "full"
    assert run("revoke-sessions", "--all", monkeypatch=monkeypatch) == 0
    assert run("mfa-reset", "--email", "qa.admin@predigol.local", monkeypatch=monkeypatch) == 0
    with psycopg.connect(people) as conn:
        row = conn.execute("SELECT totp_secret IS NULL, (SELECT count(*) FROM auth.sessions WHERE revoked_at IS NULL) "
                           "FROM auth.users WHERE email = 'qa.admin@predigol.local'").fetchone()
        assert row == (True, 0)
        by = conn.execute("SELECT count(*) FROM auth.audit_events WHERE detail->>'by' = 'command_line'").fetchone()
        assert by is not None and by[0] >= 3
