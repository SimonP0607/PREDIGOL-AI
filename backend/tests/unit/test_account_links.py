"""The pieces of account and access that need no database (plan UX, A7): how a one-use link is made, the e-mails that
carry one or tell an account about its security, what a sign-in notice may say about a device, the switches, and the
short-lived hash of a client's address."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta

import pytest

from fbi.auth import account_mail, crypto, passwords, recovery, tokens
from fbi.messaging.templates import (
    BROWSERS,
    CHANGES,
    PREVIEW_LINK,
    SEND_FIELDS,
    SYSTEMS,
    TEMPLATES,
    TemplateError,
    check_params,
    moment,
    placeholders,
    render,
)

LINK_TEMPLATES = {name: t for name, t in TEMPLATES.items() if t.grant is not None}
UNTIL = datetime(2026, 11, 1, 18, 5, tzinfo=UTC)


# ── the link ──────────────────────────────────────────────────────────────────────────

def test_a_link_is_derived_from_its_row_and_its_nonce_under_the_servers_key(monkeypatch: pytest.MonkeyPatch) -> None:
    nonce = b"n" * tokens.NONCE_BYTES
    link = crypto.account_token(7, nonce)
    assert link == crypto.account_token(7, nonce), "the same e-mail, retried, carries the same link"
    assert len(link) == 43 and tokens.looks_like_token(link)
    assert crypto.account_token(8, nonce) != link and crypto.account_token(7, b"m" * tokens.NONCE_BYTES) != link
    assert tokens.token_id(link) == hashlib.sha256(link.encode()).hexdigest(), "the database keeps only this"
    monkeypatch.setenv("FBI_AUTH_SECRET_KEY", crypto.new_key_b64())
    from fbi.auth.settings import reset

    reset()
    try:
        assert crypto.account_token(7, nonce) != link, "another key, another link: the database alone makes none"
        monkeypatch.delenv("FBI_AUTH_SECRET_KEY")
        reset()
        with pytest.raises(crypto.KeyUnavailableError):
            crypto.account_token(7, nonce)
    finally:
        monkeypatch.undo()
        reset()


def test_the_lifetimes_and_the_states_each_link_is_for() -> None:
    lifetimes = {"invite": timedelta(days=7), "reset": timedelta(minutes=30), "unlock": timedelta(hours=1),
                 "verify": timedelta(hours=24)}
    assert lifetimes == tokens.LIFETIME
    assert tokens.STATUS_FOR == {"invite": "invited", "reset": "active", "unlock": "active", "verify": "pending"}
    assert tokens.PER_HOUR == 3 and tokens.KEEP_DAYS == 30 and tokens.NONCE_BYTES == 32
    assert {t.grant for t in LINK_TEMPLATES.values()} == set(tokens.LIFETIME)
    assert {TEMPLATES[name].grant for name in account_mail.LINK_TEMPLATES.values()} == set(tokens.LIFETIME)
    for purpose, name in account_mail.LINK_TEMPLATES.items():
        assert TEMPLATES[name].grant == purpose


def test_an_unusable_hash_satisfies_the_rule_and_opens_nothing() -> None:
    a, b = passwords.unusable_hash(), passwords.unusable_hash()
    assert a.startswith("$argon2id$") and a != b
    for guess in ("", "password", "not-a-password-anybody-has"):
        assert not passwords.verify_password(a, guess)


@pytest.mark.parametrize(("raw", "on"), [(None, False), ("", False), ("0", False), ("off", False), ("1", True),
                                         ("on", True), ("true", True), ("YES", True)])
def test_the_switch_is_born_off(monkeypatch: pytest.MonkeyPatch, raw: str | None, on: bool) -> None:
    if raw is None:
        monkeypatch.delenv(tokens.SWITCH, raising=False)
    else:
        monkeypatch.setenv(tokens.SWITCH, raw)
    assert tokens.self_service_enabled() is on


@pytest.mark.parametrize(("raw", "mode"), [(None, "dry"), ("", "dry"), ("dry", "dry"), ("on", "on"),
                                           ("1", "on"), ("off", "off"), ("whatever", "dry")])
def test_the_purge_is_born_dry(monkeypatch: pytest.MonkeyPatch, raw: str | None, mode: str) -> None:
    if raw is None:
        monkeypatch.delenv("FBI_LINKS_PURGE", raising=False)
    else:
        monkeypatch.setenv("FBI_LINKS_PURGE", raw)
    assert tokens.purge_mode() == mode


# ── the e-mails ───────────────────────────────────────────────────────────────────────

def test_a_link_goes_only_in_the_buttons_address_and_the_queue_keeps_only_its_rows_number() -> None:
    assert set(LINK_TEMPLATES) == {"invitation", "password_reset", "account_unlock", "activation_reminder",
                                   "email_verification"}
    for t in LINK_TEMPLATES.values():
        assert t.params == ("grant",), t.name
        assert t.path is not None and t.path.endswith("#t={link}"), "in the fragment: never sent to a server"
        for locale in ("es", "en"):
            c = t.copy(locale)
            words = " ".join([c.subject, *c.paragraphs, c.button or ""])
            assert "{link}" not in words, f"{t.name}/{locale}: the link only in the button's address"
            assert "{until}" in words, f"{t.name}/{locale}: the reader is told until when it works"
            assert placeholders(t, locale) - {"name"} == SEND_FIELDS
    with pytest.raises(TemplateError):
        check_params("invitation", {"grant": "7; DROP"})
    with pytest.raises(TemplateError):
        check_params("invitation", {"grant": "7", "token": "abc"})


@pytest.mark.parametrize("name", sorted(LINK_TEMPLATES))
def test_a_link_e_mail_renders_with_its_link_and_until_when_it_works(name: str,
                                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FBI_WEB_BASE_URL", raising=False)  # the default address of the web app
    out = render(name, "es", {"grant": "41"}, {"name": "Ana"}, zone="America/Bogota", link="L" * 43, until=UNTIL)
    t = TEMPLATES[name]
    assert t.path is not None
    assert out.link == f"http://localhost:5173{t.path.replace('{link}', 'L' * 43)}"
    assert out.link in out.text and out.link in out.html
    assert "1 de noviembre de 2026, 13:05 (hora de Bogota)" in out.text
    assert "41" not in out.text, "the row's number never reaches the reader"
    with pytest.raises(TemplateError, match="expires"):
        render(name, "es", {"grant": "41"}, {"name": "Ana"})
    preview = render(name, "en", {"grant": "41"}, {"name": "Ann"}, until=UNTIL)
    assert PREVIEW_LINK in preview.text, "the console's preview never makes a link"


def test_the_moment_is_said_in_the_readers_time_zone() -> None:
    at = "2026-10-25T18:05:00+00:00"
    assert moment(at, "es", "America/Bogota") == "25 de octubre de 2026, 13:05 (hora de Bogota)"
    assert moment(at, "en", "Europe/Madrid") == "25 October 2026, 19:05 (Madrid time)"  # winter time from today
    assert moment(at, "es", "UTC") == "25 de octubre de 2026, 18:05 (hora UTC)"
    assert moment(at, "en", "America/Argentina/Buenos_Aires") == "25 October 2026, 15:05 (Buenos Aires time)"
    assert moment(at, "es", "Not/AZone") == "25 de octubre de 2026, 18:05 (hora UTC)", "an unknown zone: UTC"
    for bad in ("yesterday", "2026-10-25T18:05:00"):
        with pytest.raises(TemplateError):
            moment(bad, "es", "UTC")


def test_the_security_notices_say_what_happened_from_closed_lists(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FBI_WEB_BASE_URL", raising=False)
    text = render("new_sign_in", "es", {"browser": "samsung", "system": "android", "when": "2026-10-25T18:05:00Z"},
                  {"name": "Ana"}, zone="America/Bogota").text
    assert "Alguien entró a tu cuenta desde Samsung Internet en Android el 25 de octubre de 2026, 13:05" in text
    text = render("new_sign_in", "en", {"browser": "other", "system": "other", "when": "2026-10-25T18:05:00Z"},
                  {"name": "Ann"}).text
    assert "from a browser on an unknown system on 25 October 2026, 18:05 (UTC)" in text
    for change in CHANGES:
        out = render("security_change", "es", {"change": change, "when": "2026-10-25T18:05:00Z"}, {"name": "Ana"})
        assert CHANGES[change]["es"] in out.text and out.link == "http://localhost:5173/profile#security"
    for params in ({"browser": "netscape", "system": "android", "when": "2026-10-25T18:05:00Z"},
                   {"browser": "chrome", "system": "beos", "when": "2026-10-25T18:05:00Z"},
                   {"browser": "chrome", "system": "android", "when": "anytime"}):
        with pytest.raises(TemplateError):
            check_params("new_sign_in", params)
    with pytest.raises(TemplateError):
        check_params("security_change", {"change": "everything", "when": "2026-10-25T18:05:00Z"})
    assert set(BROWSERS) >= {"chrome", "safari", "firefox", "edge", "samsung", "opera", "other"}
    assert set(SYSTEMS) >= {"android", "ios", "windows", "macos", "linux", "chromeos", "other"}


def test_the_queue_does_not_send_a_message_past_its_moment() -> None:
    from fbi.messaging.outbox import suppression

    at = datetime(2026, 10, 25, 20, 0, tzinfo=UTC)
    base = {"email": "lector@example.com", "email_status": None, "email_off": None, "category": "security",
            "template": "password_reset"}
    assert suppression(base | {"created_at": at - timedelta(minutes=30)}, at) is None
    assert suppression(base | {"created_at": at - timedelta(hours=2)}, at) == "too late: its moment has passed"
    assert suppression(base | {"created_at": at - timedelta(hours=2)}) is None, "without a moment, no staleness"
    invitation = base | {"category": "account", "template": "invitation", "created_at": at - timedelta(days=20)}
    assert suppression(invitation, at) is None


def test_a_message_past_its_moment_is_stale() -> None:
    assert TEMPLATES["password_reset"].stale_after == timedelta(hours=1)
    assert TEMPLATES["account_unlock"].stale_after == timedelta(hours=1)
    assert TEMPLATES["new_sign_in"].stale_after == timedelta(hours=24)
    assert TEMPLATES["security_change"].stale_after == timedelta(hours=24)
    assert TEMPLATES["invitation"].stale_after is None, "an invitation's link counts its days from when it leaves"
    assert all(TEMPLATES[n].stale_after is None for n in ("privacy_request_received", "legal_change"))


# ── a device, as a sign-in notice may name it ─────────────────────────────────────────

@pytest.mark.parametrize(("agent", "family"), [
    ("Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 "
     "Mobile/15E148 Safari/604.1", ("safari", "ios")),
    ("Mozilla/5.0 (iPad; CPU OS 18_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) CriOS/130.0 "
     "Mobile/15E148 Safari/604.1", ("chrome", "ios")),
    ("Mozilla/5.0 (Linux; Android 14; SM-S918B) AppleWebKit/537.36 (KHTML, like Gecko) SamsungBrowser/26.0 "
     "Chrome/122.0.0.0 Mobile Safari/537.36", ("samsung", "android")),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 "
     "Safari/537.36 Edg/130.0.0.0", ("edge", "windows")),
    ("Mozilla/5.0 (X11; Linux x86_64; rv:131.0) Gecko/20100101 Firefox/131.0", ("firefox", "linux")),
    ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 "
     "Safari/537.36", ("chrome", "macos")),
    ("Mozilla/5.0 (X11; CrOS x86_64 14541.0.0) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 "
     "Safari/537.36", ("chrome", "chromeos")),
    ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 "
     "Safari/537.36 OPR/114.0.0.0", ("opera", "windows")),
    ("curl/8.5.0", ("other", "other")),
    (None, ("other", "other")),
])
def test_a_device_is_named_by_its_browser_family_and_system_only(agent: str | None, family: tuple[str, str]) -> None:
    assert account_mail.device_family(agent) == family
    browser, system = family
    assert browser in BROWSERS and system in SYSTEMS


# ── a client's address, for the limits ────────────────────────────────────────────────

def test_a_clients_address_becomes_a_short_lived_hash() -> None:
    key = recovery.client_key("203.0.113.9")
    assert key == recovery.client_key("203.0.113.9"), "the same client, the same window, in this process"
    assert key != recovery.client_key("203.0.113.10")
    assert "203.0.113.9" not in key
    assert key != hashlib.sha256(b"203.0.113.9").hexdigest()[:24], "salted: meaningless outside this process"
