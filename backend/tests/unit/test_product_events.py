"""The closed catalog of product events (plan UX, A6 and section 39): 35 events, each with only the properties it may
carry - an enumeration, a bounded integer, a boolean, a slug or an id; never free text - and the switches."""

from __future__ import annotations

import json
from collections import Counter

import pytest

from fbi.customer import events
from fbi.customer.events import CATALOG_FILE, EventError, check

GROUPS = {"entry": 6, "use": 7, "picks": 5, "parlays": 3, "news": 2, "notices": 4, "support": 3, "membership": 3,
          "other": 2}
SERVER = {"account_activated", "ticket_created", "trial_started", "membership_renewed", "membership_expired"}


def test_the_catalog_is_the_plans_35_events_in_their_groups() -> None:
    cat = events.catalog()
    assert len(cat) == 35
    assert Counter(e.group for e in cat.values()) == GROUPS
    assert {e.name for e in cat.values() if e.source == "server"} == SERVER
    raw = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
    assert raw["_comment"] and set(raw["events"]) == set(cat)


def test_no_property_can_carry_free_text_an_address_or_a_secret() -> None:
    for spec in events.catalog().values():
        for name, prop in spec.props.items():
            assert prop.kind in ("enum", "int", "bool", "slug", "id"), (spec.name, name)
            words = set(name.split("_"))
            assert not words & {"text", "query", "email", "mail", "ip", "name", "message", "comment", "token",
                                "password", "url", "address", "phone"}, (spec.name, name)


@pytest.mark.parametrize(("name", "props", "clean"), [
    ("match_opened", {"origin": "home", "match_id": 1234}, {"origin": "home", "match_id": 1234}),
    ("match_opened", {}, {}),
    ("market_viewed", {"market": "OU_2.5", "match_id": 1}, {"market": "OU_2.5", "match_id": 1}),
    ("analysis_helpful_voted", {"helpful": False}, {"helpful": False}),
    ("session_started", {"device": "tablet", "width": 820, "client": "pwa", "lang": "en"},
     {"device": "tablet", "width": 820, "client": "pwa", "lang": "en"}),
])
def test_what_the_catalog_allows(name: str, props: dict[str, object], clean: dict[str, object]) -> None:
    assert check(name, props, source="web") == clean


@pytest.mark.parametrize(("name", "props", "code"), [
    ("no_such_event", {}, "unknown_event"),
    (42, {}, "unknown_event"),
    ("account_activated", {}, "server_event"),
    ("match_opened", {"query": "real madrid"}, "unknown_property"),
    ("match_opened", {"origin": "an email"}, "invalid_property"),
    ("match_opened", {"match_id": 0}, "invalid_property"),
    ("match_opened", {"match_id": True}, "invalid_property"),
    ("match_opened", {"match_id": "12"}, "invalid_property"),
    ("search_submitted", {"results": 1001}, "invalid_property"),
    ("term_explained", {"term": "a reader's sentence"}, "invalid_property"),
    ("term_explained", {"term": "x" * 41}, "invalid_property"),
    ("analysis_helpful_voted", {"helpful": 1}, "invalid_property"),
    ("match_opened", ["origin", "home"], "invalid_properties"),
])
def test_anything_else_is_refused(name: object, props: object, code: str) -> None:
    with pytest.raises(EventError) as caught:
        check(name, props, source="web")
    assert caught.value.code == code and caught.value.status == 422


def test_a_server_event_is_the_servers_only() -> None:
    assert check("account_activated", {}, source="server") == {}
    with pytest.raises(EventError, match="recorded by the server"):
        check("account_activated", {}, source="web")
    with pytest.raises(EventError):
        check("match_opened", {}, source="server")


def test_measuring_is_born_off_and_the_purge_dry(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FBI_PRODUCT_EVENTS", raising=False)
    monkeypatch.delenv("FBI_EVENTS_PURGE", raising=False)
    monkeypatch.delenv("FBI_PRODUCT_MIN_SUBJECTS", raising=False)
    assert events.mode() == "off" and events.purge_mode() == "dry" and events.min_subjects() == 20
    for value, mode in (("1", "on"), ("on", "on"), ("consent", "consent"), ("0", "off"), ("maybe", "off")):
        monkeypatch.setenv("FBI_PRODUCT_EVENTS", value)
        assert events.mode() == mode
    for value, mode in (("on", "on"), ("off", "off"), ("dry", "dry"), ("anything", "dry")):
        monkeypatch.setenv("FBI_EVENTS_PURGE", value)
        assert events.purge_mode() == mode
    monkeypatch.setenv("FBI_PRODUCT_MIN_SUBJECTS", "0")
    assert events.min_subjects() == 1


def test_a_bogota_day_and_its_bounds() -> None:
    from datetime import UTC, date, datetime

    assert events.bogota_day(datetime(2026, 10, 26, 4, 59, tzinfo=UTC)) == date(2026, 10, 25)
    assert events.bogota_day(datetime(2026, 10, 26, 5, 0, tzinfo=UTC)) == date(2026, 10, 26)
    start, end = events.day_bounds(date(2026, 10, 25))
    assert start == datetime(2026, 10, 25, 5, 0, tzinfo=UTC) and end == datetime(2026, 10, 26, 5, 0, tzinfo=UTC)
