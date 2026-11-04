"""The rules of the readers' notices that need no database (plan UX, B7; section 34): the quiet hours in the reader's zone,
their day, the switch, the categories and limits, and the words of every notice in both languages - short, without a
price or an amount, opening a page of PrediGol."""

from __future__ import annotations

import re
from datetime import UTC, datetime

import pytest

from fbi.customer import push
from fbi.messaging import push_texts as texts

URL = re.compile(r"^/([A-Za-z0-9_?=&#.-][A-Za-z0-9/_?=&#.-]{0,198})?$")
"""customer.push_notices.url (migration 0104)."""
KEY = re.compile(r"^[a-z_]+:[A-Za-z0-9:_-]{1,100}$")


@pytest.mark.parametrize(("utc", "zone", "until"), [
    ("2026-10-27T02:59:00", "America/Bogota", None),                   # 21:59 Bogotá: not yet quiet
    ("2026-10-27T03:00:00", "America/Bogota", "2026-10-27T13:00:00"),  # 22:00 Bogotá: until 08:00
    ("2026-10-27T10:30:00", "America/Bogota", "2026-10-27T13:00:00"),  # 05:30 Bogotá
    ("2026-10-27T13:00:00", "America/Bogota", None),                   # 08:00 Bogotá: over
    ("2026-10-27T22:30:00", "Europe/Madrid", "2026-10-28T07:00:00"),   # 23:30 Madrid (UTC+1)
    ("2026-10-27T15:00:00", "Not/AZone", None),                        # a zone it cannot read: Bogotá's (10:00)
])
def test_the_quiet_hours_are_22_to_08_in_the_readers_zone(utc: str, zone: str, until: str | None) -> None:
    at = datetime.fromisoformat(utc).replace(tzinfo=UTC)
    got = push.quiet_until(at, zone)
    assert got == (datetime.fromisoformat(until).replace(tzinfo=UTC) if until else None)


def test_the_readers_day_is_theirs() -> None:
    at = datetime(2026, 10, 28, 3, 30, tzinfo=UTC)  # 22:30 of the 27th in Bogotá
    assert push.local_day(at, "America/Bogota").isoformat() == "2026-10-27"
    start, end = push.day_bounds(push.local_day(at, "America/Bogota"), "America/Bogota")
    assert (start.isoformat(), end.isoformat()) == ("2026-10-27T05:00:00+00:00", "2026-10-28T05:00:00+00:00")


@pytest.mark.parametrize(("value", "on"), [(None, True), ("", True), ("1", True), ("on", True), ("0", False),
                                           ("off", False), ("maybe", False)])
def test_the_switch_is_on_until_the_owner_says_otherwise(monkeypatch: pytest.MonkeyPatch, value: str | None,
                                                         on: bool) -> None:
    if value is None:
        monkeypatch.delenv(push.SWITCH, raising=False)
    else:
        monkeypatch.setenv(push.SWITCH, value)
    assert push.enabled() is on


def test_without_the_owners_key_nothing_is_offered(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(push.SWITCH, raising=False)
    monkeypatch.delenv("FBI_VAPID_PRIVATE_KEY", raising=False)
    monkeypatch.setattr("fbi.messaging.push.environment", lambda: {})
    assert push.enabled() and not push.available()


def test_the_plans_categories_and_limits() -> None:
    assert push.CATEGORIES == ("result", "lineup", "digest", "account")
    assert push.CAPPED == ("result", "lineup", "digest") and push.DAILY_CAP == 3
    assert (push.QUIET_START.hour, push.QUIET_END.hour) == (22, 8)
    assert push.ALERT_MINUTES == (15, 30, 60) and push.ALERT_AHEAD.days == 7
    assert push.RETENTION.days == 90


KICKOFF = datetime(2026, 10, 27, 23, 30, tzinfo=UTC)


def every_notice(locale: texts.Locale) -> list[texts.Words]:
    return [
        *(texts.pick_result(s, "Atlético Nacional", "Millonarios", locale) for s in texts.RESULT_WORD),
        *(texts.parlay_result(s, "Mi combinada del sábado", locale) for s in texts.PARLAY_WORD),
        texts.parlay_result("WON", None, locale),
        texts.lineups("Atlético Nacional", "Millonarios", KICKOFF, "America/Bogota", locale),
        *(texts.reminder(m, "Atlético Nacional", "Millonarios", locale) for m in push.ALERT_MINUTES),
        texts.digest("Atlético Nacional", "Millonarios", 0, locale),
        texts.digest("Atlético Nacional", "Millonarios", 1, locale),
        texts.digest("Atlético Nacional", "Millonarios", 5, locale),
        texts.membership_tomorrow(locale),
        texts.new_sign_in("Chrome en Android" if locale == "es" else "Chrome on Android", locale),
        texts.test_notice(locale),
    ]


def test_every_notice_has_its_words_in_both_languages_short_and_without_a_price_or_an_amount() -> None:
    es, en = every_notice("es"), every_notice("en")
    assert len(es) == len(en)
    for a, b in zip(es, en, strict=True):
        assert a != b, "each language its own words"
        for w in (a, b):
            assert 1 <= len(w.title) <= 120 and 1 <= len(w.body) <= 300, w
            assert not re.search(r"\$|COP|USD|€|\bcuota\b|\bodds\b|\bapuesta\b|\bbet\b|\d+[.,]\d+", f"{w.title} {w.body}",
                                 re.IGNORECASE), w


def test_the_words_say_what_happened() -> None:
    assert texts.pick_result("WIN", "Nacional", "Millonarios", "es").title == "Ganado: tu pick de Nacional\u2013Millonarios"
    assert texts.pick_result("LOSS", "Nacional", "Millonarios", "en").title == "Lost: your pick of Nacional\u2013Millonarios"
    assert texts.lineups("A", "B", KICKOFF, "America/Bogota", "es").body == "Empieza a las 18:30."
    assert texts.reminder(30, "A", "B", "es").title == "Empieza en 30 minutos"
    assert texts.digest("A", "B", 2, "es").body == "A\u2013B y 2 partidos más: mira su análisis."
    assert texts.locale_of("en-GB") == "en" and texts.locale_of(None) == "es" and texts.locale_of("es") == "es"


@pytest.mark.parametrize("url", ["/matches/123#postmatch", "/matches/123#lineups", "/matches/123", "/my-picks", "/home",
                                 "/profile#membership", "/profile#security", "/profile#notifications"])
def test_every_page_a_notice_opens_is_one_the_queue_accepts(url: str) -> None:
    assert URL.fullmatch(url) and push.PAGE.fullmatch(url)
    assert URL.pattern == push.PAGE.pattern, "the queue checks what the table checks"


@pytest.mark.parametrize("url", ["//evil.example/x", "https://evil.example", "matches/1", "/x y", "/" + "a" * 200,
                                 "/\\evil.example", "javascript:alert(1)"])
def test_a_notice_never_opens_another_site(url: str) -> None:
    assert not URL.fullmatch(url) and not push.PAGE.fullmatch(url)


@pytest.mark.parametrize("key", ["result:pick:123", "result:parlay:9", "lineup:456", "reminder:456:30", "digest:2026-10-27",
                                 "account:membership:12", "account:sign_in:Ab_9-xY", "test:1793065148099"])
def test_every_deduplication_key_is_one_the_queue_accepts(key: str) -> None:
    assert KEY.fullmatch(key)
