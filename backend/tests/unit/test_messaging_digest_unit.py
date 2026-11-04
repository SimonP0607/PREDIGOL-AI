"""The weekly summary by e-mail without a database (plan UX, B8; section 33).

* Its words in both languages: how the week's saved picks ended (counts only), the teams' matches of the next seven
  days, the week's Novedades by their titles - a paragraph without words left out - and the commercial footer: why the
  reader gets it and the one-click way out; never an odd, an amount or an address.
* The one-click link: the account and the day, signed; a changed letter, another account, a link older than a year or
  from the future, or the server's key missing: nobody.
* Its own flow: the commercial sender on another domain than the account's, or no summary at all; offered only with the
  switch, the e-mail on and that sender.
* The week spread over the days: a reader's day, from 09:00 in their zone, one summary per ISO week.
* The queue's categories are the database's (migration 0105), and commercial e-mail is never one of the account's.
"""

from __future__ import annotations

import importlib.util
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType

import pytest

from fbi.auth import crypto
from fbi.messaging import digest, templates, unsubscribe
from fbi.messaging.templates import COMMERCIAL, OUTBOX_CATEGORIES, TEMPLATES, Locale, render

MIGRATION = Path(__file__).resolve().parents[2] / "migrations" / "versions" / "0105_customer_marketing.py"
NOW = datetime(2026, 10, 27, 15, 0, tzinfo=UTC)
SAMPLE = dict(TEMPLATES["weekly_digest"].sample)


def migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("m0105", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def words(**changes: str) -> dict[str, str]:
    return {**SAMPLE, **changes}


# ── the words ─────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("won", "lost", "void", "es", "en"), [
    ("0", "0", "0", "Esta semana no terminó ninguno de los picks que guardaste.",
     "None of the picks you saved ended this week."),
    ("1", "0", "0", "Esta semana terminó 1 de los picks que guardaste: 1 ganado.",
     "1 of the picks you saved ended this week: 1 won."),
    ("2", "1", "1", "Esta semana terminaron 4 de los picks que guardaste: 2 ganados, 1 perdido y 1 devuelto.",
     "4 of the picks you saved ended this week: 2 won, 1 lost and 1 returned."),
    ("0", "3", "0", "Esta semana terminaron 3 de los picks que guardaste: 3 perdidos.",
     "3 of the picks you saved ended this week: 3 lost."),
])
def test_how_the_weeks_picks_ended_counts_only(won: str, lost: str, void: str, es: str, en: str) -> None:
    pairs: tuple[tuple[Locale, str], ...] = (("es", es), ("en", en))
    for locale, sentence in pairs:
        text = render("weekly_digest", locale, words(won=won, lost=lost, void=void), {"name": "Ana"}).text
        assert sentence in text
        assert "%" not in text and "unidad" not in text.lower() and "unit" not in text.lower()


@pytest.mark.parametrize(("follows", "matches", "es", "en"), [
    ("no", "0", "Aún no sigues ningún equipo: elígelos en tu perfil y aquí verás sus partidos.",
     "You follow no team yet: choose them in your profile and their matches will show here."),
    ("yes", "0", "Tus equipos no juegan en los próximos 7 días.", "Your teams do not play in the next 7 days."),
    ("yes", "1", "Tus equipos juegan 1 partido en los próximos 7 días.", "Your teams play 1 match in the next 7 days."),
    ("yes", "5", "Tus equipos juegan 5 partidos en los próximos 7 días.", "Your teams play 5 matches in the next 7 days."),
])
def test_the_teams_matches_of_the_coming_week(follows: str, matches: str, es: str, en: str) -> None:
    assert es in render("weekly_digest", "es", words(follows=follows, matches=matches), {"name": "Ana"}).text
    assert en in render("weekly_digest", "en", words(follows=follows, matches=matches), {"name": "Ana"}).text


def test_the_weeks_novedades_by_their_titles_and_no_empty_paragraph_without_them() -> None:
    two = "2026-10-27-tu-opinion,2026-10-27-mis-picks"
    es = render("weekly_digest", "es", words(news=two), {"name": "Ana"})
    assert "Nuevo en PrediGol: «Tu opinión, una vez al mes»; «Mis picks, completo»." in es.text
    en = render("weekly_digest", "en", words(news=two), {"name": "Ana"})
    assert "New in PrediGol: “Your opinion, once a month”; “My picks, complete”." in en.text
    none = render("weekly_digest", "es", words(news="-"), {"name": "Ana"})
    assert "Nuevo en PrediGol" not in none.text and "\n\n\n" not in none.text
    assert none.html.count("<p ") == es.html.count("<p ") - 1
    with pytest.raises(templates.TemplateError):
        render("weekly_digest", "es", words(news="2026-01-01-nada"), {"name": "Ana"})


def test_counts_and_words_the_queue_refuses() -> None:
    for bad in ({"won": "-1"}, {"lost": "x"}, {"matches": "1e9"}, {"follows": "maybe"}):
        with pytest.raises(templates.TemplateError):
            templates.check_params("weekly_digest", words(**bad))


def test_the_commercial_footer_says_why_and_how_to_leave_in_one_click() -> None:
    page = "https://predigol.example/unsubscribe#t=1x2xabc"
    cases: tuple[tuple[Locale, str, str], ...] = (
        ("es", "Recibes este resumen porque lo pediste en tu perfil.", "Darte de baja en un clic"),
        ("en", "You get this summary because you asked for it in your profile.", "Leave it in one click"),
    )
    for locale, why, leave in cases:
        r = render("weekly_digest", locale, SAMPLE, {"name": "Ana"}, unsubscribe=page)
        assert why in r.text and f"{leave}: {page}" in r.text
        assert f'href="{page}"' in r.html and leave in r.html
        assert r.unsubscribe == page
        assert "puedes elegir qué avisos" not in r.text and "choose which notices" not in r.text
    preview = render("weekly_digest", "es", SAMPLE, {"name": "Ana"})
    assert preview.unsubscribe == templates.PREVIEW_UNSUBSCRIBE  # the console's preview never makes a real link
    account = render("legal_change", "es", dict(TEMPLATES["legal_change"].sample), {"name": "Ana"},
                     unsubscribe=page)
    assert account.unsubscribe is None and page not in account.text, "an account's e-mail has no leaving link"


def test_commercial_mail_is_not_one_of_the_accounts_categories_and_the_database_takes_it() -> None:
    m = migration()
    assert set(OUTBOX_CATEGORIES) == set(m.CATEGORIES) and {"marketing"} == COMMERCIAL
    assert "marketing" not in templates.CATEGORIES and "marketing" not in templates.OPTIONAL
    assert set(m.CATEGORIES_BEFORE) == set(templates.CATEGORIES)
    assert TEMPLATES["weekly_digest"].category == "marketing"
    assert all(t.category not in COMMERCIAL for t in TEMPLATES.values() if t.name != "weekly_digest")
    assert m.SOURCES == ("gate", "profile", "activation", "email")


# ── the one-click link ────────────────────────────────────────────────────────────────

@pytest.fixture()
def key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(crypto, "_master_key", lambda: b"k" * 32)


def test_a_link_names_its_account_and_nothing_else_can_be_made_of_it(key: None) -> None:
    token = unsubscribe.make(42, NOW)
    assert unsubscribe.read(token, NOW) == 42
    assert unsubscribe.read(token, NOW + timedelta(days=365)) == 42
    assert unsubscribe.read(token, NOW + timedelta(days=368)) is None, "a year, then nobody"
    user, day, mac = token.split("x", 2)
    assert user == "42" and len(mac) == 22
    assert unsubscribe.read(f"43x{day}x{mac}", NOW) is None, "another account"
    assert unsubscribe.read(f"{user}x{int(day) - 1}x{mac}", NOW) is None, "another day"
    flipped = mac[:-1] + ("A" if mac[-1] != "A" else "B")
    assert unsubscribe.read(f"{user}x{day}x{flipped}", NOW) is None, "a changed letter"
    assert unsubscribe.read(unsubscribe.make(42, NOW + timedelta(days=3)), NOW) is None, "from the future"
    for junk in ("", "42", "42x1x2", "0x1xaaaaaaaaaaaaaaaaaaaaaa", "xyz", f"{token}x", token.replace("x", ".", 2)):
        assert unsubscribe.read(junk, NOW) is None


def test_without_the_servers_key_no_link_is_made_and_none_is_read(monkeypatch: pytest.MonkeyPatch, key: None) -> None:
    token = unsubscribe.make(42, NOW)

    def missing() -> bytes:
        raise crypto.KeyUnavailableError("FBI_AUTH_SECRET_KEY is not set")

    monkeypatch.setattr(crypto, "_master_key", missing)
    with pytest.raises(crypto.KeyUnavailableError):
        unsubscribe.make(42, NOW)
    assert unsubscribe.read(token, NOW) is None


# ── its own flow and its switches ─────────────────────────────────────────────────────

def test_the_commercial_sender_is_on_another_domain_or_there_is_no_summary(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FBI_EMAIL_FROM", "PrediGol <hola@mail.predigol.example>")
    for value, expected in (("PrediGol <resumen@news.predigol.example>", "PrediGol <resumen@news.predigol.example>"),
                            ("resumen@news.predigol.example", "resumen@news.predigol.example"),
                            ("PrediGol <otro@mail.predigol.example>", None), ("", None), ("not an address", None)):
        monkeypatch.setenv(digest.FROM_ENV, value)
        assert digest.sender() == expected, value


def test_offered_only_with_the_switch_the_email_on_and_the_commercial_sender(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FBI_EMAIL_FROM", "PrediGol <hola@mail.predigol.example>")
    monkeypatch.setenv(digest.FROM_ENV, "PrediGol <resumen@news.predigol.example>")
    monkeypatch.setenv("FBI_EMAIL_SEND", "1")
    monkeypatch.setenv(digest.ENV, "1")
    assert digest.offered()
    for name, off in ((digest.ENV, "0"), ("FBI_EMAIL_SEND", "0"), (digest.FROM_ENV, "")):
        with monkeypatch.context() as m:
            m.setenv(name, off)
            assert not digest.offered(), name
    monkeypatch.delenv(digest.ENV)
    assert not digest.offered(), "born off"


def test_the_week_spread_over_the_days_from_nine_in_the_readers_zone() -> None:
    monday_15_utc = datetime(2026, 10, 26, 15, 0, tzinfo=UTC)  # 10:00 in Bogotá
    reader = 7  # day 0: Monday
    assert digest.day_of(reader) == 0 and digest.day_of(8) == 1
    assert digest.due_now(reader, "America/Bogota", monday_15_utc)
    assert not digest.due_now(reader, "America/Bogota", monday_15_utc.replace(hour=13)), "08:00 in Bogotá"
    assert not digest.due_now(8, "America/Bogota", monday_15_utc), "another reader's day"
    assert digest.due_now(reader, "Not/AZone", monday_15_utc), "an unknown zone reads as UTC"
    week = digest.dedup_key(reader, "America/Bogota", monday_15_utc)
    assert week == "weekly_digest:7:2026-W44"
    assert digest.dedup_key(reader, "America/Bogota", monday_15_utc + timedelta(days=6)) == week
    assert digest.dedup_key(reader, "America/Bogota", monday_15_utc + timedelta(days=7)) != week


def test_the_daily_cap_reads_its_switch(monkeypatch: pytest.MonkeyPatch) -> None:
    assert digest.daily_cap() == 30
    monkeypatch.setenv(digest.CAP_ENV, "5")
    assert digest.daily_cap() == 5
    monkeypatch.setenv(digest.CAP_ENV, "many")
    assert digest.daily_cap() == 30
