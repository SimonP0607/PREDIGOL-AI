"""How a reader reaches PrediGol (closing plan 4.2): the channels the app offers and their order come from the server's
settings, the hours someone answers are the owner's own words, and the number never leaves the server's configuration."""

from __future__ import annotations

import pytest

from fbi.customer import support

WHATSAPP, EMAIL = "573001234567", "ayuda@example.org"


@pytest.fixture(autouse=True)
def clean(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (support.CHANNELS_ENV, support.HOURS_ENV, support.SWITCH):
        monkeypatch.delenv(name, raising=False)


def test_without_a_setting_the_three_channels_are_offered_in_the_plans_order() -> None:
    assert support.contact_channels(whatsapp=WHATSAPP, email=EMAIL) == ["whatsapp", "tickets", "email"]


def test_a_channel_that_is_not_available_is_left_out() -> None:
    assert support.contact_channels(whatsapp=None, email=EMAIL) == ["tickets", "email"]
    assert support.contact_channels(whatsapp=None, email=None) == ["tickets"]


def test_the_owner_chooses_which_and_in_what_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(support.CHANNELS_ENV, " Tickets , whatsapp ,tickets, telegram")
    assert support.contact_channels(whatsapp=WHATSAPP, email=EMAIL) == ["tickets", "whatsapp"], \
        "the order is the owner's, a repeat counts once, a channel the app does not know is ignored, one not named is hidden"
    monkeypatch.setenv(support.CHANNELS_ENV, "email,whatsapp")
    assert support.contact_channels(whatsapp=WHATSAPP, email=None) == ["whatsapp"], "named but unavailable: out"


def test_a_setting_with_no_known_name_is_as_if_it_were_absent(monkeypatch: pytest.MonkeyPatch) -> None:
    for raw in ("", " , ", "telegram", "carrier-pigeon"):
        monkeypatch.setenv(support.CHANNELS_ENV, raw)
        assert support.contact_channels(whatsapp=WHATSAPP, email=EMAIL) == ["whatsapp", "tickets", "email"], raw


def test_the_tickets_leave_the_list_when_the_line_is_switched_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(support.SWITCH, "0")
    assert support.contact_channels(whatsapp=WHATSAPP, email=EMAIL) == ["whatsapp", "email"]


@pytest.mark.parametrize(("raw", "shown"), [
    ("Lun-Vie 9:00-18:00, hora de Bogotá", "Lun-Vie 9:00-18:00, hora de Bogotá"),
    ("  Todos los días 8-20  ", "Todos los días 8-20"),
    ("", None),
    ("x" * 81, None),
    ("<b>9 a 6</b>", None),
    ("9 a 6\nescríbenos", None),
])
def test_the_hours_are_plain_words_or_nothing(monkeypatch: pytest.MonkeyPatch, raw: str, shown: str | None) -> None:
    monkeypatch.setenv(support.HOURS_ENV, raw)
    assert support.contact_hours() == shown


def test_the_hours_are_absent_by_default() -> None:
    assert support.contact_hours() is None
