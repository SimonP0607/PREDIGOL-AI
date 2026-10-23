"""The calendar of a match over HTTP (plan F4): who sees it, what the page may say that the packet may not, and how it admits that a list
is not whole.

The page shows each team's matches in every competition as they stand now. A user sees it only once the owner decides
(``FBI_CALENDAR_USERS``); the Admin Console's preview sees it either way. The transaction is rolled back afterwards."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from fbi.api.app import create_app
from fbi.api.deps import get_db
from fbi.api.services import match_calendar as service
from tests.integration.calendar_helpers import (
    AT,
    FRESH,
    KICKOFF,
    cup_tie,
    known_competition,
    own_followed,
    read,
    read_both,
    world,
)
from tests.integration.conftest import Seed
from tests.integration.signed_in import SAME_SITE, signed_in

pytestmark = pytest.mark.integration


def client(db: psycopg.Connection[Any], role: str, monkeypatch: pytest.MonkeyPatch, *, users: bool,
           at: datetime = AT) -> TestClient:
    monkeypatch.setenv(service.USERS_SWITCH, "1" if users else "0")
    monkeypatch.setattr(service, "now", lambda: at)
    app = signed_in(create_app(), role)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app, headers=SAME_SITE)


def url(fid: int, preview: bool = False) -> str:
    return f"/api/v1/matches/{fid}/calendar" + ("?preview=shadow" if preview else "")


def test_a_user_gets_nothing_until_the_owner_decides_and_then_the_calendar_of_each_side(
        db: psycopg.Connection[Any], seed: Seed, monkeypatch: pytest.MonkeyPatch) -> None:
    w = world(db, home_last=8.0, away_last=7.0)
    read_both(db, seed, w)

    off = client(db, "USER", monkeypatch, users=False).get(url(w.fixture_id))
    assert off.status_code == 200
    assert off.json()["status"] == "not_available" and off.json()["data"] is None and off.json()["reason"], "said, not left blank"
    assert "Other FC" not in off.text

    on = client(db, "USER", monkeypatch, users=True).get(url(w.fixture_id))
    assert on.status_code == 200
    body = on.json()
    assert body["status"] == "ok" and body["meta"]["data_as_of"] is not None
    data = body["data"]
    assert data["fixture_id"] == w.fixture_id and data["complete"] is True and data["scope"] == "provider_calendar"

    home, away = data["home"], data["away"]
    assert (home["team"], away["team"]) == ("Home FC", "Away FC")
    assert (home["complete"], home["reason"], home["age_hours"]) == (True, None, 20.0)
    assert home["fetched_at"] is not None and datetime.fromisoformat(home["fetched_at"]) == FRESH
    assert home["rest_days"] == 2.0
    assert (home["matches_last_7d"], home["matches_last_14d"], home["matches_last_30d"], home["outside_last_14d"]) == (1, 2, 2, 1)
    cup, league = home["recent"]
    assert (cup["competition"], cup["followed"], cup["days"], cup["home"]) == ("Copa del Rey", False, 2.0, True)
    assert (cup["opponent"], cup["result"]) == ("Other FC", "2-1"), "the page may say who and how it ended: they are facts of the past"
    assert (league["competition"], league["followed"], league["days"]) == ("Calendar League", True, 8.0)
    assert (league["opponent"], league["result"], league["competition_type"]) == ("Other FC", "1-0", "domestic_league")
    (coming,) = home["upcoming"]
    assert (coming["competition"], coming["followed"], coming["days"], coming["result"]) == ("Champions League", False, 3.0, None)
    assert away["rest_days"] == 7.0 and away["complete"] is True and away["upcoming"] == [] and len(away["recent"]) == 1

    for users in (False, True):
        refused = client(db, "USER", monkeypatch, users=users).get(url(w.fixture_id, preview=True))
        assert refused.status_code == 403, "403 for an account without the shadow-preview permission"
        assert "Copa del Rey" not in refused.text


def test_the_admin_preview_sees_it_whether_or_not_users_do(db: psycopg.Connection[Any], seed: Seed,
                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    w = world(db, home_last=8.0, away_last=7.0)
    read_both(db, seed, w)
    admin = client(db, "SUPER_ADMIN", monkeypatch, users=False)

    assert admin.get(url(w.fixture_id)).json()["status"] == "not_available", "without the preview the switch decides"
    shown = admin.get(url(w.fixture_id, preview=True)).json()
    assert shown["status"] == "ok" and shown["data"]["home"]["recent"][0]["competition"] == "Copa del Rey"


def test_a_side_whose_list_was_never_read_says_so_and_the_scope_follows(db: psycopg.Connection[Any], seed: Seed,
                                                                         monkeypatch: pytest.MonkeyPatch) -> None:
    w = world(db, home_last=8.0, away_last=7.0)
    read(db, seed, w.away, [own_followed(w, "away", 7.0)], FRESH)  # only the away side was read
    body = client(db, "USER", monkeypatch, users=True).get(url(w.fixture_id)).json()
    data = body["data"]

    assert data["complete"] is False and data["scope"] == "tracked_competitions"
    assert (data["home"]["complete"], data["home"]["reason"], data["home"]["fetched_at"]) == (False, "never_fetched", None)
    assert data["home"]["rest_days"] == 8.0 and [m["competition"] for m in data["home"]["recent"]] == ["Calendar League"], (
        "what PrediGol follows is still there")
    assert (data["away"]["complete"], data["away"]["reason"]) == (True, None)
    assert datetime.fromisoformat(body["meta"]["data_as_of"]) == FRESH, "as old as the list it stands on"


def test_a_list_read_too_long_ago_and_a_match_nobody_confirmed_say_why(db: psycopg.Connection[Any], seed: Seed,
                                                                      monkeypatch: pytest.MonkeyPatch) -> None:
    w = world(db, home_last=8.0, away_last=7.0)
    read(db, seed, w.home, [own_followed(w, "home", 8.0)], AT - timedelta(days=6))
    unconfirmed = cup_tie(w, "away", days_before=3.0, short="NS")  # kicked off three days ago and the list still says to-be-played
    read(db, seed, w.away, [own_followed(w, "away", 7.0), unconfirmed], FRESH)
    data = client(db, "USER", monkeypatch, users=True).get(url(w.fixture_id)).json()["data"]

    assert (data["home"]["complete"], data["home"]["reason"], data["home"]["age_hours"]) == (False, "stale", 144.0)
    assert (data["away"]["complete"], data["away"]["reason"]) == (False, "unconfirmed_match")
    assert data["away"]["rest_days"] == 7.0, "a match that is not known to have been played is not rest"
    assert data["complete"] is False and data["scope"] == "tracked_competitions"


def test_the_competition_type_is_the_platforms_where_it_knows_the_competition(db: psycopg.Connection[Any], seed: Seed,
                                                                            monkeypatch: pytest.MonkeyPatch) -> None:
    w = world(db, home_last=8.0, away_last=7.0)
    tie = cup_tie(w, "home", days_after=2.0, league=known_competition(db, "Known Cup"), name="Known Cup")
    read(db, seed, w.home, [own_followed(w, "home", 8.0), tie], FRESH)
    data = client(db, "USER", monkeypatch, users=True).get(url(w.fixture_id)).json()["data"]
    (coming,) = data["home"]["upcoming"]
    assert (coming["competition"], coming["competition_type"], coming["days"]) == ("Known Cup", "domestic_cup", 2.0)


def test_a_match_that_does_not_exist_is_a_404(db: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch) -> None:
    for role in ("USER", "SUPER_ADMIN"):
        missing = client(db, role, monkeypatch, users=True).get(url(2**40))
        assert missing.status_code == 404 and missing.json()["error"]["code"] == "not_found", role


def test_the_page_is_the_calendar_at_the_moment_it_is_asked(db: psycopg.Connection[Any], seed: Seed,
                                                            monkeypatch: pytest.MonkeyPatch) -> None:
    w = world(db, home_last=8.0, away_last=7.0)
    announced = cup_tie(w, "home", days_after=2.0, name="Supercopa")
    read(db, seed, w.home, [own_followed(w, "home", 8.0), announced], AT + timedelta(hours=1))
    before = client(db, "USER", monkeypatch, users=True, at=AT).get(url(w.fixture_id)).json()["data"]["home"]
    after = client(db, "USER", monkeypatch, users=True, at=AT + timedelta(hours=2)).get(url(w.fixture_id)).json()["data"]["home"]

    assert before["upcoming"] == [] and before["reason"] == "never_fetched", "nobody had read the list yet"
    assert [m["competition"] for m in after["upcoming"]] == ["Supercopa"] and after["complete"] is True
    assert KICKOFF > AT, "the match itself is still to come in both"
