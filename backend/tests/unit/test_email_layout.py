"""The brand's e-mail layout (plan de correcciones UX, AP-M01, decision D13) - behind ``FBI_EMAIL_V2``, born off.

The layout changes how an e-mail looks, never what it says: the subject, the plain text and the button's address are the
same with the switch on and off. What it must never carry is the same short list as before - no script, no external style
sheet, no remote image or tracking pixel - and it stays under 100 KB, in both languages, for every template.
"""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime

import pytest

from fbi.messaging import layout
from fbi.messaging.templates import TEMPLATES, Locale, Rendered, render

TOKEN = "abcdefghijklmnopqrstuvwxyz0123456789"
UNTIL = datetime(2026, 11, 12, 15, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def web_address(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FBI_WEB_BASE_URL", "https://predigol.example")


def made(name: str, locale: Locale, name_of_reader: str = "Ana") -> Rendered:
    t = TEMPLATES[name]
    return render(name, locale, dict(t.sample), {"name": name_of_reader}, zone="America/Bogota",
                  link=TOKEN if t.grant else None, until=UNTIL if t.grant else None)


@pytest.mark.parametrize(("raw", "on"), [(None, False), ("", False), ("0", False), ("off", False), ("1", True),
                                         ("TRUE", True), (" on ", True), ("yes", True)])
def test_the_switch_is_born_off_and_reads_as_the_owner_writes_it(monkeypatch: pytest.MonkeyPatch, raw: str | None,
                                                                 on: bool) -> None:
    if raw is None:
        monkeypatch.delenv(layout.SWITCH, raising=False)
    else:
        monkeypatch.setenv(layout.SWITCH, raw)
    assert layout.switch_on() is on


def test_every_template_has_one_of_the_eight_tones() -> None:
    assert len(layout.TONES) == 8 and set(layout.EYEBROW) == set(layout.TONES) == set(layout.ACCENT)
    for name, t in TEMPLATES.items():
        assert layout.tone_of(name, t.category) in layout.TONES, name
    assert layout.tone_of("welcome", "account") == "welcome"
    assert layout.tone_of("password_reset", "security") == "security"
    assert layout.tone_of("weekly_digest", "marketing") == "digest"


@pytest.mark.parametrize("locale", ["es", "en"])
def test_the_words_are_the_same_with_the_switch_on_and_off(monkeypatch: pytest.MonkeyPatch, locale: Locale) -> None:
    for name in TEMPLATES:
        monkeypatch.delenv(layout.SWITCH, raising=False)
        plain = made(name, locale)
        monkeypatch.setenv(layout.SWITCH, "1")
        branded = made(name, locale)
        assert (branded.subject, branded.text, branded.link, branded.unsubscribe) == (
            plain.subject, plain.text, plain.link, plain.unsubscribe), name
        assert branded.html != plain.html, name


@pytest.mark.parametrize("locale", ["es", "en"])
def test_the_branded_html_is_safe_light_and_readable_without_images(monkeypatch: pytest.MonkeyPatch, locale: Locale) -> None:
    monkeypatch.setenv(layout.SWITCH, "1")
    for name, t in TEMPLATES.items():
        out = made(name, locale)
        low = out.html.lower()
        assert "<script" not in low and "<link" not in low and "<img" not in low and "<iframe" not in low, name
        assert "url(" not in low and "@import" not in low and "javascript:" not in low, name
        assert len(out.html.encode()) < 100_000, name
        assert not re.search(r'(src|background)\s*=\s*"https?:', low), name
        assert 'lang="' + locale + '"' in out.html and "prefers-color-scheme: dark" in out.html, name
        assert out.html.count("<a ") == (1 if out.link and t.es.button else 0) + (1 if out.unsubscribe else 0), name
        if out.link and t.es.button:
            assert "min-height:44px" in out.html, name
        assert html.escape(layout.EYEBROW[layout.tone_of(name, t.category)][locale]) in out.html, name


def test_what_comes_from_the_account_is_escaped(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(layout.SWITCH, "1")
    out = made("welcome", "es", name_of_reader='<script>alert("x")</script>')
    assert "<script" not in out.html.lower() and "&lt;script&gt;" in out.html
