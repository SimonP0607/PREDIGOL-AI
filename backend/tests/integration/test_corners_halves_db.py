"""PM-05-03 on a real database: ``market.fixture_outcomes`` carries the corners of each half read from what PM-05-01 kept, and only when they
can be trusted - the four figures came, the halves add up to the match total and, for the second half, no extra time. Real answers of the
probe (``tests/fixtures/period_stats``): the figures the view gives are compared with the ones written in the answer itself, and a bet
on them is graded with the rule of version 2."""

from __future__ import annotations

from copy import deepcopy
from decimal import Decimal
from typing import Any

import psycopg
import pytest

from fbi.ingestion import period_stats as ps
from fbi.market.rules import RULES_BY_KEY
from fbi.picks.count_settlement import settle_numbers
from fbi.picks.settlement import Status
from tests.integration.test_period_stats_db import (  # noqa: F401
    NOW,
    FakeProvider,
    Raw,
    body_of,
    conn,
    league,
    switch,
)

pytestmark = pytest.mark.integration
COLUMNS = ("corners_1h_home", "corners_1h_away", "corners_2h_home", "corners_2h_away", "corners_ft_home", "corners_ft_away")


def corner(body: dict[str, Any], team: int, block: str) -> int:
    return int(next(i["value"] for i in body["response"][team][block] if i["type"] == "Corner Kicks"))


def outcome(c: psycopg.Connection, fid: int) -> dict[str, Any]:
    cur = c.execute(f"SELECT {', '.join(COLUMNS)} FROM market.fixture_outcomes WHERE fixture_id = %s", (fid,))
    row = cur.fetchone()
    assert row is not None
    return dict(zip(COLUMNS, row, strict=True))


class Answering(FakeProvider):
    def __init__(self, c: psycopg.Connection, body: dict[str, Any]) -> None:
        super().__init__(c)
        self.body = body

    async def fetch_raw(self, endpoint: str, params: dict[str, Any]) -> Raw:
        self.calls += 1
        row = self.c.execute("SELECT th.provider_team_id, ta.provider_team_id FROM core.fixtures f JOIN core.teams th ON th.id = "
                             "f.home_team_id JOIN core.teams ta ON ta.id = f.away_team_id WHERE f.provider_fixture_id = %s",
                             (int(params["fixture"]),)).fetchone()
        assert row is not None
        body = deepcopy(self.body)
        body["response"][0]["team"]["id"], body["response"][1]["team"]["id"] = int(row[0]), int(row[1])
        return Raw(body, self.calls + 1000 * int(params["fixture"]))


async def ask_one(c: psycopg.Connection, n: int, body: dict[str, Any]) -> int:
    _, _, fids = league(c, n, matches=1)
    await ps.refresh_period_stats(c, Answering(c, body), at=NOW)
    return fids[0]


@pytest.mark.asyncio
@pytest.mark.parametrize(("answer", "n"), [("typical", 40), ("no_fouls", 45), ("kleague", 46), ("libertadores", 47), ("sum_off", 48)])
async def test_the_halves_of_a_real_answer_are_what_the_answer_says(conn: psycopg.Connection, answer: str, n: int) -> None:  # noqa: F811
    c = conn
    body = body_of(answer, 1, 2)
    fid = await ask_one(c, n, body)
    # the match's own corners, as the match table keeps them (the helper wrote 5 and 4): make them the answer's
    c.execute("UPDATE core.fixture_team_stats SET corners = %s WHERE fixture_id = %s AND team_side = 'home'", (corner(body, 0, "statistics"), fid))
    c.execute("UPDATE core.fixture_team_stats SET corners = %s WHERE fixture_id = %s AND team_side = 'away'", (corner(body, 1, "statistics"), fid))
    got = outcome(c, fid)
    assert (got["corners_1h_home"], got["corners_1h_away"]) == (corner(body, 0, "statistics_1h"), corner(body, 1, "statistics_1h"))
    assert (got["corners_2h_home"], got["corners_2h_away"]) == (corner(body, 0, "statistics_2h"), corner(body, 1, "statistics_2h"))
    assert got["corners_1h_home"] + got["corners_2h_home"] == got["corners_ft_home"]
    assert got["corners_1h_away"] + got["corners_2h_away"] == got["corners_ft_away"]
    # graded by the rule of version 2: the over of a line the first half passes or not
    total = got["corners_1h_home"] + got["corners_1h_away"]
    rule = RULES_BY_KEY["corners_1h@v2"]
    over = settle_numbers(rule, "over_under", "match", "Over", Decimal(total) - Decimal("0.5"), got)
    under = settle_numbers(rule, "over_under", "match", "Under", Decimal(total) - Decimal("0.5"), got)
    assert (over, under) == (Status.WIN, Status.LOSS)
    push_free = settle_numbers(rule, "over_under", "match", "Over", Decimal(total) + Decimal("0.5"), got)
    assert push_free == Status.LOSS


@pytest.mark.asyncio
async def test_halves_that_do_not_add_up_to_the_match_are_not_known(conn: psycopg.Connection) -> None:  # noqa: F811
    body = body_of("typical", 1, 2)
    for item in body["response"][0]["statistics"]:
        if item["type"] == "Corner Kicks":
            item["value"] = 9  # the halves say 5 + 2
    fid = await ask_one(conn, 41, body)
    got = outcome(conn, fid)
    assert got["corners_1h_home"] is None and got["corners_2h_away"] is None, "a half is never graded on a figure the match contradicts"
    assert conn.execute("SELECT 'corners' = ANY(sums_off) FROM core.fixture_period_asks WHERE fixture_id = %s", (fid,)).fetchone() == (True,)


@pytest.mark.asyncio
async def test_a_missing_figure_is_not_known_and_never_zero(conn: psycopg.Connection) -> None:  # noqa: F811
    body = body_of("typical", 1, 2)
    body["response"][1]["statistics_2h"] = [i for i in body["response"][1]["statistics_2h"] if i["type"] != "Corner Kicks"]
    fid = await ask_one(conn, 42, body)
    got = outcome(conn, fid)
    assert all(got[k] is None for k in COLUMNS[:4])


@pytest.mark.asyncio
async def test_a_match_never_asked_has_no_halves(conn: psycopg.Connection) -> None:  # noqa: F811
    _, _, fids = league(conn, 43, matches=1)
    assert all(v is None for k, v in outcome(conn, fids[0]).items() if k.startswith("corners_1h") or k.startswith("corners_2h"))


@pytest.mark.asyncio
async def test_after_extra_time_the_first_half_stands_and_the_second_does_not(conn: psycopg.Connection) -> None:  # noqa: F811
    body = body_of("typical", 1, 2)
    fid = await ask_one(conn, 44, body)
    conn.execute("UPDATE core.fixtures SET status_short = 'AET' WHERE id = %s", (fid,))
    got = outcome(conn, fid)
    assert got["corners_1h_home"] == corner(body, 0, "statistics_1h")
    assert got["corners_2h_home"] is None and got["corners_2h_away"] is None


@pytest.mark.asyncio
async def test_the_hand_comparison_draws_its_sample_from_known_halves(conn: psycopg.Connection) -> None:  # noqa: F811
    from scripts.corners_halves_check import SAMPLE_SQL

    await ask_one(conn, 49, body_of("typical", 1, 2))
    rows = conn.execute(SAMPLE_SQL, {"n": 5, "seed": "0"}).fetchall()
    assert all(r[4] is not None and r[6] is not None for r in rows), "only matches with both halves known are drawn"
