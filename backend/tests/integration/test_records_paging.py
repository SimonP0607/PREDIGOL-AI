"""My picks and my parlays are never cut (plan UX, A1, defect F53): the real total and a cursor to the rest.

The audit found GET /me/picks capped at 500 rows and /me/parlays at 200, each answering `total = len(page)`: "Todo"
in Mis picks showed whatever fitted in one answer and called it everything. From A1 both lists answer the real total
of the account's records (with the same filter) and, when more remain, `meta.next_cursor`, which the next request
passes back as `cursor` to get the following page. The cursor is the position of the last record shown (the order
of the list: picks by kick-off and id, parlays by creation and id, newest first), so a page never repeats or skips
a record whatever is saved in between; a cursor the API did not write is refused.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from fbi.core.clock import FrozenClock, SystemClock, set_clock
from fbi.core.config import reset_cache
from tests.integration.helpers import scalar
from tests.integration.signed_in import SAME_SITE, principal

NOW = datetime(2033, 10, 1, 15, tzinfo=UTC)
FIXTURES = 7
PARLAYS = 25


@pytest.fixture()
def world(migrated_database: str) -> Iterator[dict[str, Any]]:
    ids: dict[str, Any] = {"fixtures": [], "teams": []}
    with psycopg.connect(migrated_database, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO auth.users (email, display_name, password_hash, timezone) VALUES "
                    "('records-paging@test.local', 'Paging', '$argon2id$x', 'America/Bogota') RETURNING id")
        ids["user"] = scalar(cur)
        cur.execute("INSERT INTO auth.users (email, display_name, password_hash, timezone) VALUES "
                    "('records-paging-2@test.local', 'Other', '$argon2id$x', 'America/Bogota') RETURNING id")
        ids["other"] = scalar(cur)
        cur.execute("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type) "
                    "VALUES (97601, 'Paging League', 'league', 'club', 'domestic_league') RETURNING id")
        ids["competition"] = scalar(cur)
        cur.execute("INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, 2033) RETURNING id",
                    (ids["competition"],))
        season = scalar(cur)
        for n in range(FIXTURES):
            teams = []
            for side in (0, 1):
                cur.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (%s, %s) RETURNING id",
                            (976000 + 2 * n + side, f"P{n}-{side}"))
                teams.append(scalar(cur))
            ids["teams"].extend(teams)
            # one match every day, the newest yesterday; and two of them at the same minute, to test the tie
            kickoff = NOW - timedelta(days=1 + n if n != 3 else 3)
            cur.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, "
                        "away_team_id, kickoff_at) VALUES (%s, %s, %s, %s, %s) RETURNING id",
                        (7360100 + n, season, teams[0], teams[1], kickoff))
            fid = scalar(cur)
            ids["fixtures"].append(fid)
            for k, selection in enumerate(("Home", "Draw", "Away")):
                status = ("WIN", "LOSS", "VOID")[k] if n % 2 == 0 else "PENDING"
                cur.execute("INSERT INTO picks.user_picks (user_id, fixture_id, market_key, selection, line, origin, "
                            "odds, snapshot, saved_at, status, profit_units, settled_at) VALUES "
                            "(%s, %s, '1X2', %s, 0, 'market', 2.000, '{}', %s, %s, %s, %s)",
                            (ids["user"], fid, selection, kickoff - timedelta(hours=2), status,
                             None if status == "PENDING" else {"WIN": 1, "LOSS": -1, "VOID": 0}[status],
                             None if status == "PENDING" else kickoff + timedelta(hours=2)))
        # the other account has records too: a page of one account never shows the other's
        cur.execute("INSERT INTO picks.user_picks (user_id, fixture_id, market_key, selection, line, origin, odds, "
                    "snapshot, saved_at) VALUES (%s, %s, '1X2', 'Home', 0, 'market', 2.000, '{}', %s)",
                    (ids["other"], ids["fixtures"][0], NOW - timedelta(days=2)))
        for n in range(PARLAYS):
            cur.execute("INSERT INTO picks.user_parlays (user_id, name, created_at, combined_odds, validation) "
                        "VALUES (%s, %s, %s, 4.000, '{}')",
                        (ids["user"], f"Parlay {n}", NOW - timedelta(hours=n // 2)))  # pairs share a minute
    mp = pytest.MonkeyPatch()
    mp.setenv("FBI_DATABASE_URL", migrated_database.replace("postgresql://", "postgresql+psycopg://"))
    reset_cache()
    set_clock(FrozenClock(NOW))
    yield ids
    set_clock(SystemClock())
    mp.undo()
    reset_cache()
    with psycopg.connect(migrated_database, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM auth.users WHERE id = ANY(%s)", ([ids["user"], ids["other"]],))
        cur.execute("DELETE FROM core.fixtures WHERE id = ANY(%s)", (ids["fixtures"],))
        cur.execute("DELETE FROM core.teams WHERE id = ANY(%s)", (ids["teams"],))
        cur.execute("DELETE FROM core.competition_seasons WHERE competition_id = %s", (ids["competition"],))
        cur.execute("DELETE FROM core.competitions WHERE id = %s", (ids["competition"],))


def client_for(user_id: int) -> TestClient:
    from fbi.api.app import create_app
    from fbi.api.security import optional_principal

    app = create_app()
    who = dataclasses.replace(principal("USER", user_id=user_id), timezone="America/Bogota")
    app.dependency_overrides[optional_principal] = lambda: who
    return TestClient(app, headers=SAME_SITE)


def walk(c: TestClient, path: str, **params: Any) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Every page of a list, following the cursor: the records in order, and each page's meta."""
    records: list[dict[str, Any]] = []
    metas: list[dict[str, Any]] = []
    cursor: str | None = None
    for _ in range(50):
        r = c.get(path, params={**params, **({"cursor": cursor} if cursor else {})})
        assert r.status_code == 200, r.text
        body = r.json()
        records.extend(body["data"])
        metas.append(body["meta"])
        cursor = body["meta"].get("next_cursor")
        if not cursor:
            return records, metas
    raise AssertionError("the cursor never ended")


def test_my_picks_answer_the_real_total_and_a_cursor_to_the_rest(world: dict[str, Any]) -> None:
    c = client_for(world["user"])
    first = c.get("/api/v1/me/picks", params={"limit": 5}).json()
    assert len(first["data"]) == 5
    assert first["meta"]["total"] == FIXTURES * 3, "the total is the account's, not the page's"
    assert first["meta"]["next_cursor"], "more remain, so the answer says where to go on"
    picks, metas = walk(c, "/api/v1/me/picks", limit=5)
    assert len(picks) == FIXTURES * 3 and len({p["id"] for p in picks}) == FIXTURES * 3, "no record twice, none lost"
    order = [(p["match"]["kickoff_at"], p["id"]) for p in picks]
    assert order == sorted(order, reverse=True), "newest kick-off first, the id breaking a tie"
    assert metas[-1]["next_cursor"] is None
    assert all(m["total"] == FIXTURES * 3 for m in metas)


def test_the_status_filter_counts_and_pages_alike(world: dict[str, Any]) -> None:
    c = client_for(world["user"])
    settled_fixtures = len([n for n in range(FIXTURES) if n % 2 == 0])
    settled, metas = walk(c, "/api/v1/me/picks", status="settled", limit=4)
    assert len(settled) == settled_fixtures * 3 and metas[0]["total"] == settled_fixtures * 3
    assert {p["status"] for p in settled} == {"WIN", "LOSS", "VOID"}
    open_, metas = walk(c, "/api/v1/me/picks", status="open", limit=4)
    assert {p["status"] for p in open_} == {"PENDING"} and metas[0]["total"] == len(open_)


def test_my_parlays_answer_the_real_total_and_a_cursor(world: dict[str, Any]) -> None:
    c = client_for(world["user"])
    first = c.get("/api/v1/me/parlays", params={"limit": 10}).json()
    assert len(first["data"]) == 10 and first["meta"]["total"] == PARLAYS and first["meta"]["next_cursor"]
    parlays, metas = walk(c, "/api/v1/me/parlays", limit=10)
    assert len(parlays) == PARLAYS and len({p["id"] for p in parlays}) == PARLAYS
    order = [(p["created_at"], p["id"]) for p in parlays]
    assert order == sorted(order, reverse=True)
    assert [m["count"] for m in metas] == [10, 10, 5]


def test_a_page_shows_only_the_accounts_own_records(world: dict[str, Any]) -> None:
    other = client_for(world["other"]).get("/api/v1/me/picks", params={"limit": 5}).json()
    assert other["meta"]["total"] == 1 and len(other["data"]) == 1 and other["meta"]["next_cursor"] is None


@pytest.mark.parametrize("cursor", ["not-a-cursor", "MjAzMw", "eyJ4IjogMX0"])
def test_a_cursor_the_api_did_not_write_is_refused(world: dict[str, Any], cursor: str) -> None:
    c = client_for(world["user"])
    for path in ("/api/v1/me/picks", "/api/v1/me/parlays"):
        r = c.get(path, params={"cursor": cursor})
        assert r.status_code == 422 and r.json()["error"]["code"] == "invalid_cursor", (path, r.text)
