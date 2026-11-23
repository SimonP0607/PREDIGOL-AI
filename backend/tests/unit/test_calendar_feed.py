"""PM-14-06 (BE-084): the reader's secret calendar link and its iCalendar file, without a database. The secret has 256 bits and only its
SHA-256 is kept; a malformed secret never reaches the database; the file is valid RFC 5545 (CRLF, lines folded at 75 octets without
splitting a character, TEXT escaped, the required properties) - the same checks the three calendar clients apply - and it carries no
price, probability, pick or account data; a secret never reaches a log line."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta

import pytest

from fbi.api import switches
from fbi.api.routers import calendar_feed as router
from fbi.api.services import calendar_feed as ics
from fbi.customer import calendar_feed as feeds

AT = datetime(2026, 11, 21, 12, tzinfo=UTC)


def test_the_secret_has_256_bits_and_only_its_hash_is_kept() -> None:
    a, b = feeds.new_token(), feeds.new_token()
    assert a != b and feeds.looks_like_token(a) and len(a) == 43
    assert re.fullmatch(r"[0-9a-f]{64}", feeds.token_id(a)) and feeds.token_id(a) != feeds.token_id(b)
    assert feeds.token_id(a) == feeds.token_id(a)


@pytest.mark.parametrize("bad", [None, "", "abc", "a" * 42, "a" * 44, "a" * 42 + "=", "../../etc/passwd" + "a" * 27, "a" * 42 + " "])
def test_a_malformed_secret_is_refused_before_the_database(bad: str | None) -> None:
    assert not feeds.looks_like_token(bad)
    assert feeds.resolve(None, bad) is None  # type: ignore[arg-type]


def test_the_switch_is_off_unless_said(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(switches.CALENDAR_FEED, raising=False)
    assert not switches.calendar_feed_on()
    monkeypatch.setenv(switches.CALENDAR_FEED, "1")
    assert switches.calendar_feed_on()
    monkeypatch.setenv(switches.CALENDAR_FEED, "maybe")
    assert not switches.calendar_feed_on()


def test_a_secret_never_reaches_a_log_line() -> None:
    token = feeds.new_token()
    assert token not in router.redact(f"/api/v1/calendar/feed/{token}.ics")
    assert router.redact("/api/v1/calendar/feed/x.ics") == "/api/v1/calendar/feed/<secreto>.ics"
    assert router.redact("/api/v1/me/calendar-feed") == "/api/v1/me/calendar-feed"


def ev(i: int, **kw: object) -> ics.Event:
    base: dict[str, object] = {"fixture_id": 1000 + i, "kickoff_at": AT + timedelta(days=i, hours=1), "status_short": "NS",
                               "status_group": "scheduled", "home": "Atlético Nacional", "away": "Millonarios, B; \\ «x»",
                               "competition": "Liga BetPlay DIMAYOR", "round": "Regular Season - 18", "venue": "Atanasio Girardot",
                               "city": "Medellín"}
    base.update(kw)
    return ics.Event(**base)  # type: ignore[arg-type]


def unfold(text: str) -> list[str]:
    return text.replace("\r\n ", "").split("\r\n")


def check_rfc5545(text: str) -> list[str]:
    """What Google, Apple and Outlook refuse or misread: bare LF, a line over 75 octets, a broken UTF-8 fold, missing properties."""
    problems = []
    raw = text.encode("utf-8")
    if b"\n" in raw.replace(b"\r\n", b""):
        problems.append("bare LF")
    if not text.endswith("\r\n"):
        problems.append("no final CRLF")
    for line in text.split("\r\n"):
        if len(line.encode("utf-8")) > 75:
            problems.append(f"line over 75 octets: {line[:30]}")
    lines = unfold(text)
    if lines[0] != "BEGIN:VCALENDAR" or lines[-2] != "END:VCALENDAR":
        problems.append("not one VCALENDAR")
    for need in ("VERSION:2.0", "PRODID:"):
        if not any(x.startswith(need) for x in lines):
            problems.append(f"missing {need}")
    begins, ends = lines.count("BEGIN:VEVENT"), lines.count("END:VEVENT")
    if begins != ends:
        problems.append("unbalanced VEVENT")
    block: list[str] = []
    for x in lines:
        if x == "BEGIN:VEVENT":
            block = []
        elif x == "END:VEVENT":
            names = {y.split(":", 1)[0].split(";", 1)[0] for y in block}
            for need in ("UID", "DTSTAMP", "DTSTART", "SUMMARY"):
                if need not in names:
                    problems.append(f"VEVENT without {need}")
        else:
            block.append(x)
    return problems


def test_the_file_is_valid_rfc5545_with_one_event_per_match() -> None:
    text = ics.render([ev(1), ev(2, status_short="TBD"), ev(3, status_short="PST", status_group="postponed", venue=None, city=None)], at=AT)
    assert check_rfc5545(text) == []
    lines = unfold(text)
    assert lines.count("BEGIN:VEVENT") == 3
    assert "UID:fixture-1001@predigol" in lines and "DTSTART:20261122T130000Z" in lines and "DTSTAMP:20261121T120000Z" in lines
    assert [x for x in lines if x.startswith("STATUS:")] == ["STATUS:CONFIRMED", "STATUS:TENTATIVE", "STATUS:CANCELLED"]
    assert "SUMMARY:Atlético Nacional vs Millonarios\\, B\\; \\\\ «x»" in lines
    assert "LOCATION:Atanasio Girardot\\, Medellín" in lines and sum(x.startswith("LOCATION:") for x in lines) == 2
    assert "DESCRIPTION:Liga BetPlay DIMAYOR · Regular Season - 18" in lines
    assert "X-WR-CALNAME:PrediGol · Mis equipos" in lines and "METHOD:PUBLISH" in lines


def test_an_empty_calendar_is_still_a_calendar() -> None:
    text = ics.render([], at=AT)
    assert check_rfc5545(text) == [] and "BEGIN:VEVENT" not in text


def test_folding_never_splits_a_character_and_unfolds_to_the_line() -> None:
    long = "SUMMARY:" + "Ñandú «Atlético» " * 12
    folded = ics.fold(long)
    assert all(len(p.encode("utf-8")) <= 75 for p in folded.split("\r\n"))
    assert folded.replace("\r\n ", "") == long
    assert ics.fold("SHORT:x") == "SHORT:x"


def test_text_is_escaped_and_control_characters_dropped() -> None:
    assert ics.escape("a,b;c\\d\ne\r\nf\x00g\x7f") == "a\\,b\\;c\\\\d\\ne\\nfg"


def test_the_file_carries_nothing_but_the_fixtures() -> None:
    text = ics.render([ev(1)], at=AT).lower()
    for word in (r"cuota", r"\bodds\b", r"probab", r"\bpicks?\b", r"apuesta", r"\bbets?\b", r"%", r"https?:", r"mailto", r"@predigol\."):
        assert re.search(word, text) is None, word
