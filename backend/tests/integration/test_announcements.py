"""The owner's communiqués against the migrated database (closing plan 4.3), with a fake Telegram.

* Publishing takes two steps: the preview gives a code that lives ten minutes, then the code and the word PUBLICAR.
* A day holds at most the cap; a published communiqué is retracted, never deleted; every step is a line of the record.
* The banner shows between its dates, urgent kinds first; Novedades take only published updates.
* An e-mail goes only for a critical communiqué, to every active reader whose address works, once each.
* A communiqué never touches picks, models or the inteligence tables.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from fbi.auth import service
from fbi.core.config import reset_cache
from fbi.customer import announcements as ann
from fbi.customer.db import CustomerError
from tests.integration.helpers import forget_memberships

PASSWORD = "Quiet-harbour-2026-long"  # gitleaks:allow - the password of the test accounts this module creates
OWNER = "owner.ux022@predigol.test"
READERS = ("lector.uno.ux022@example.org", "lector.dos.ux022@example.org")
NOW = datetime.now(UTC)


def content(**changes: Any) -> ann.Content:
    base: dict[str, Any] = {
        "kind": "maintenance", "title_es": "Mantenimiento esta noche", "title_en": "Maintenance tonight",
        "body_es": "Habrá una pausa corta.", "body_en": "There will be a short pause.",
        "starts_at": NOW - timedelta(minutes=5), "ends_at": NOW + timedelta(hours=6), "critical": True}
    return ann.Content(**{**base, **changes})


def wipe(dsn: str) -> None:
    with psycopg.connect(dsn) as conn:
        conn.execute("SET LOCAL fbi.customer_maintenance = 'on'")
        conn.execute("TRUNCATE customer.announcement_log, customer.announcements RESTART IDENTITY")
        conn.execute("DELETE FROM customer.messages_outbox WHERE template = 'critical_notice'")


@pytest.fixture(scope="module")
def database(migrated_database: str) -> Iterator[str]:
    mp = pytest.MonkeyPatch()
    mp.setenv("FBI_DATABASE_URL", migrated_database.replace("postgresql://", "postgresql+psycopg://"))
    mp.setenv("FBI_AUTH_MFA_ROLES", "")
    reset_cache()
    with psycopg.connect(migrated_database, autocommit=True) as conn:
        conn.execute("DELETE FROM auth.sessions")
        forget_memberships(conn)
    with psycopg.connect(migrated_database) as conn:
        conn.execute("SET LOCAL fbi.customer_maintenance = 'on'")
        conn.execute("DELETE FROM customer.messages_outbox")
    with psycopg.connect(migrated_database, autocommit=True) as conn:
        conn.execute("DELETE FROM auth.users")
    for email, role in ((OWNER, "SUPER_ADMIN"), *[(r, "USER") for r in READERS]):
        service.create_user_unattended(email=email, display_name=email.split("@")[0], role=role, password=PASSWORD)
    yield migrated_database
    wipe(migrated_database)
    mp.undo()
    reset_cache()


@pytest.fixture()
def conn(database: str) -> Iterator[psycopg.Connection[Any]]:
    wipe(database)
    with psycopg.connect(database) as c:
        yield c


def owner_id(conn: psycopg.Connection[Any]) -> int:
    row = conn.execute("SELECT id FROM auth.users WHERE email = %s", (OWNER,)).fetchone()
    assert row is not None
    return int(row[0])


def publish(conn: psycopg.Connection[Any], actor: int, new_id: int, *, at: datetime | None = None) -> ann.Published:
    code, _, _ = ann.ask_to_publish(conn, actor, new_id, at=at)
    return ann.publish(conn, actor, new_id, code=code, phrase="PUBLICAR", at=at)


def test_a_draft_shows_to_nobody_until_it_is_published(conn: psycopg.Connection[Any]) -> None:
    actor = owner_id(conn)
    new_id = ann.create(conn, actor, content())
    assert ann.active_banners(conn) == []
    publish(conn, actor, new_id)
    banners = ann.active_banners(conn)
    assert [b["id"] for b in banners] == [new_id]
    assert banners[0]["title_es"] == "Mantenimiento esta noche"


def test_publishing_needs_the_code_and_the_word(conn: psycopg.Connection[Any]) -> None:
    actor = owner_id(conn)
    new_id = ann.create(conn, actor, content())
    with pytest.raises(CustomerError) as early:
        ann.publish(conn, actor, new_id, code="whatever-code", phrase="PUBLICAR")
    assert early.value.code == "confirmation_expired"
    code, expires, shown = ann.ask_to_publish(conn, actor, new_id)
    assert expires > NOW and "banner" in shown["destinations"]
    with pytest.raises(CustomerError) as phrase:
        ann.publish(conn, actor, new_id, code=code, phrase="publicar ya")
    assert phrase.value.code == "bad_phrase"
    with pytest.raises(CustomerError) as wrong:
        ann.publish(conn, actor, new_id, code="not-the-code-at-all", phrase="PUBLICAR")
    assert wrong.value.code == "bad_code"
    assert ann.publish(conn, actor, new_id, code=code, phrase="PUBLICAR").id == new_id
    with pytest.raises(CustomerError) as again:
        ann.publish(conn, actor, new_id, code=code, phrase="PUBLICAR")
    assert again.value.code == "not_a_draft"


def test_the_code_lasts_ten_minutes_and_editing_voids_it(conn: psycopg.Connection[Any]) -> None:
    actor = owner_id(conn)
    new_id = ann.create(conn, actor, content())
    code, _, _ = ann.ask_to_publish(conn, actor, new_id, at=NOW)
    late = NOW + ann.CONFIRM_TTL + timedelta(seconds=1)
    with pytest.raises(CustomerError) as expired:
        ann.publish(conn, actor, new_id, code=code, phrase="PUBLICAR", at=late)
    assert expired.value.code == "confirmation_expired"
    code, _, _ = ann.ask_to_publish(conn, actor, new_id, at=NOW)
    ann.edit(conn, actor, new_id, content(title_es="Mantenimiento corregido"))
    with pytest.raises(CustomerError) as voided:
        ann.publish(conn, actor, new_id, code=code, phrase="PUBLICAR")
    assert voided.value.code == "confirmation_expired"


def test_a_day_holds_at_most_the_cap(conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FBI_ANNOUNCE_DAILY_CAP", "2")
    actor = owner_id(conn)
    first, second, third = (ann.create(conn, actor, content(title_es=f"Aviso número {i}")) for i in range(3))
    publish(conn, actor, first)
    publish(conn, actor, second)
    code, _, _ = ann.ask_to_publish(conn, actor, third)
    with pytest.raises(CustomerError) as capped:
        ann.publish(conn, actor, third, code=code, phrase="PUBLICAR")
    assert capped.value.code == "daily_cap" and capped.value.status == 429
    assert ann.published_today(conn) == 2


def test_retracting_hides_it_and_keeps_the_record(conn: psycopg.Connection[Any]) -> None:
    actor = owner_id(conn)
    new_id = ann.create(conn, actor, content())
    publish(conn, actor, new_id)
    ann.retract(conn, actor, new_id)
    assert ann.active_banners(conn) == []
    assert ann.get(conn, new_id)["status"] == "retracted"
    assert [line["action"] for line in ann.log_of(conn, new_id)] == ["created", "previewed", "published", "retracted"]
    with pytest.raises(CustomerError) as nothing:
        ann.retract(conn, actor, new_id)
    assert nothing.value.code == "not_published"


def test_nothing_is_ever_deleted_and_the_record_is_append_only(conn: psycopg.Connection[Any]) -> None:
    actor = owner_id(conn)
    new_id = ann.create(conn, actor, content())
    conn.commit()
    for sql in ("DELETE FROM customer.announcements", "UPDATE customer.announcement_log SET action = 'created'",
                "DELETE FROM customer.announcement_log"):
        with pytest.raises(psycopg.errors.RaiseException):
            conn.execute(sql)
        conn.rollback()
    assert ann.get(conn, new_id)["id"] == new_id


def test_the_banner_respects_its_dates_and_puts_incidents_first(conn: psycopg.Connection[Any]) -> None:
    actor = owner_id(conn)
    past = ann.create(conn, actor, content(title_es="Ya pasó el aviso", starts_at=NOW - timedelta(days=2),
                                           ends_at=NOW - timedelta(days=1)))
    future = ann.create(conn, actor, content(title_es="Todavía no es hora", starts_at=NOW + timedelta(days=1),
                                             ends_at=NOW + timedelta(days=2)))
    general = ann.create(conn, actor, content(kind="general", critical=False, title_es="Un aviso general"))
    incident = ann.create(conn, actor, content(kind="incident", title_es="Una incidencia en curso"))
    for new_id in (general, incident, future):
        publish(conn, actor, new_id)
    with pytest.raises(CustomerError) as over:
        ann.ask_to_publish(conn, actor, past)
    assert over.value.code == "already_over"
    assert [b["id"] for b in ann.active_banners(conn)] == [incident, general]
    assert ann.active_banners(conn, NOW + timedelta(days=7)) == []


def test_novedades_take_published_updates_only(conn: psycopg.Connection[Any]) -> None:
    actor = owner_id(conn)
    update = ann.create(conn, actor, content(kind="update", to_updates=True, critical=False, to_banner=False,
                                             title_es="Nueva forma de seguir equipos"))
    draft = ann.create(conn, actor, content(kind="update", to_updates=True, critical=False, to_banner=False,
                                            title_es="Todavía es un borrador"))
    other = ann.create(conn, actor, content(kind="general", critical=False))
    publish(conn, actor, update)
    publish(conn, actor, other)
    assert [u["id"] for u in ann.published_updates(conn)] == [update]
    assert ann.get(conn, draft)["status"] == "draft"


def test_an_email_goes_to_every_active_reader_once_and_only_when_critical(conn: psycopg.Connection[Any]) -> None:
    actor = owner_id(conn)
    mail = ann.create(conn, actor, content(to_email=True))
    quiet = ann.create(conn, actor, content(title_es="Mantenimiento sin correo", to_email=False))
    assert publish(conn, actor, quiet).emails_queued == 0
    done = publish(conn, actor, mail)
    assert done.emails_queued == len(READERS)
    queued = conn.execute("SELECT count(*), count(DISTINCT user_id) FROM customer.messages_outbox "
                          "WHERE template = 'critical_notice'").fetchone()
    assert queued == (len(READERS), len(READERS))
    # the owner's account is not a reader: it gets nothing
    assert conn.execute("SELECT count(*) FROM customer.messages_outbox WHERE user_id = %s",
                        (actor,)).fetchone() == (0,)


def test_an_address_that_bounced_gets_no_critical_mail(conn: psycopg.Connection[Any]) -> None:
    actor = owner_id(conn)
    bounced = conn.execute("SELECT id FROM auth.users WHERE email = %s", (READERS[0],)).fetchone()
    assert bounced is not None
    conn.execute("INSERT INTO customer.preferences (user_id, email_status, email_status_at) "
                 "VALUES (%s, 'bounced', now()) ON CONFLICT (user_id) DO UPDATE SET email_status = 'bounced'",
                 (bounced[0],))
    new_id = ann.create(conn, actor, content(to_email=True))
    assert publish(conn, actor, new_id).emails_queued == len(READERS) - 1
    conn.execute("UPDATE customer.preferences SET email_status = 'ok', email_status_at = NULL WHERE user_id = %s", (bounced[0],))
    conn.commit()


def test_the_telegram_outcome_is_recorded_and_never_blocks(conn: psycopg.Connection[Any]) -> None:
    actor = owner_id(conn)
    new_id = ann.create(conn, actor, content(to_telegram=True))
    done = publish(conn, actor, new_id)
    assert done.telegram
    ann.record_telegram(conn, new_id, actor, sent=False, reason="telegram answered HTTP 500")
    assert ann.get(conn, new_id)["status"] == "published"
    assert ann.log_of(conn, new_id)[-1]["detail"] == {"sent": False, "reason": "telegram answered HTTP 500"}
