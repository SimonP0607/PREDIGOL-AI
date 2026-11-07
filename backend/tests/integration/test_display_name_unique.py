"""The nickname (``display_name``) is unique, ignoring case and spaces, among the accounts that are not deleted (tramo 1
of the user's flow, UX-027; the owner's decision of 7 Nov 2026).

* A nickname someone typed is refused when taken (409 ``display_name_taken``), whoever creates the account or changes it.
* A nickname the service derives from an address is made distinct (``ana``, ``ana-2``...), never refused.
* A nickname is released when its account is deleted.
"""

from __future__ import annotations

from collections.abc import Iterator

import psycopg
import pytest

from fbi.auth import invitations, service
from fbi.auth.settings import reset as reset_auth_settings
from fbi.core.config import reset_cache
from tests.integration.helpers import forget_memberships
from tests.integration.signed_in import principal

PASSWORD = "Quiet-harbour-2026-long"  # gitleaks:allow - the password of the test accounts this module creates


@pytest.fixture()
def people(migrated_database: str, monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    monkeypatch.setenv("FBI_DATABASE_URL", migrated_database.replace("postgresql://", "postgresql+psycopg://"))
    monkeypatch.setenv("FBI_SELF_SERVICE", "on")
    reset_cache()
    reset_auth_settings()
    with psycopg.connect(migrated_database, autocommit=True) as conn:
        conn.execute("SET fbi.customer_maintenance = 'on'")
        conn.execute("DELETE FROM customer.messages_outbox")  # the invitation links queued by the invites above
        forget_memberships(conn)
        for t in ("auth.sessions", "auth.recovery_codes", "auth.audit_events", "auth.account_tokens", "auth.users"):
            conn.execute(f"DELETE FROM {t}")
    yield migrated_database
    with psycopg.connect(migrated_database, autocommit=True) as conn:
        conn.execute("SET fbi.customer_maintenance = 'on'")
        conn.execute("DELETE FROM customer.messages_outbox")  # the invitation links queued by the invites above
        forget_memberships(conn)
        for t in ("auth.sessions", "auth.recovery_codes", "auth.audit_events", "auth.account_tokens", "auth.users"):
            conn.execute(f"DELETE FROM {t}")
    reset_cache()
    reset_auth_settings()


def make(email: str, name: str | None) -> dict[str, object]:
    return service.create_user_unattended(email=email, display_name=name, role="USER", password=PASSWORD)


def test_a_typed_nickname_is_refused_when_taken_ignoring_case_and_spaces(people: str) -> None:
    make("uno@example.org", "Carlos")
    for typed in ("Carlos", "carlos", "  CARLOS  "):
        with pytest.raises(service.AuthError) as exc:
            make(f"otro{len(typed)}@example.org", typed)
        assert (exc.value.status, exc.value.code) == (409, "display_name_taken")
    actor = principal("SUPER_ADMIN", user_id=int(str(make("dueno@example.org", "Dueño")["id"])))
    with pytest.raises(service.AuthError) as exc:
        invitations.invite(actor, email="invitado@example.org", display_name="carlos", language="es",
                           timezone="America/Bogota", ip=None)
    assert exc.value.code == "display_name_taken"


def test_a_nickname_derived_from_the_address_is_made_distinct(people: str) -> None:
    first = make("ana@example.org", None)
    second = make("ana@example.net", None)
    third = make("ana@example.com", None)
    assert [first["display_name"], second["display_name"], third["display_name"]] == ["ana", "ana-2", "ana-3"]
    owner = make("dueno@example.org", "Dueño")
    invited = invitations.invite(principal("SUPER_ADMIN", user_id=int(str(owner["id"]))), email="ana@example.edu", display_name=None,
                                 language="es", timezone="America/Bogota", ip=None)
    assert invited["display_name"] == "ana-4"


def test_changing_the_nickname_in_the_profile_follows_the_same_rule(people: str) -> None:
    a = make("a@example.org", "Alfa")
    make("b@example.org", "Beta")
    me = principal("USER", user_id=int(str(a["id"])))
    with pytest.raises(service.AuthError) as exc:
        service.update_preferences(me, display_name=" beta ")
    assert (exc.value.status, exc.value.code) == (409, "display_name_taken")
    assert service.update_preferences(me, display_name="ALFA")["display_name"] == "ALFA"  # its own, in another case
    assert service.update_preferences(me, display_name="Gamma")["display_name"] == "Gamma"
    make("c@example.org", "Alfa")  # released by the change


def test_a_deleted_account_releases_its_nickname(people: str) -> None:
    gone = make("gone@example.org", "Libre")
    with psycopg.connect(people, autocommit=True) as conn:
        conn.execute("UPDATE auth.users SET status = 'deleted', display_name = %s WHERE id = %s",
                     (f"deleted-{gone['id']}", gone["id"]))
    assert make("new@example.org", "Libre")["display_name"] == "Libre"
