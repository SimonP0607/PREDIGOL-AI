"""F23 end to end, one match through the whole cycle, on a real database (9 Oct 2026):

    1 scheduled -> 2 pre-match pick -> 3 kick-off -> 4 LIVE -> 5 the pick still visible, as taken -> 6 full time
    -> 7 settled at once -> 8 the day's board updated -> 9 post-mortem -> 10 learning -> 11 the day's close (Evolución)

The provider is a fake that answers /fixtures?ids= as API-Football does; everything else is the production code.
World of test_daily_records: F1 kicks off at AT + 2 h (qualified, 1X2 Home at 2.30)."""

from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg

from fbi.ai import daily_review
from fbi.ai.config import AiSettings
from fbi.ai.cycle import run_learning_cycle
from fbi.api.services import daily_review as review_api
from fbi.api.services.product import picks_board
from fbi.api.services.records import daily_board
from fbi.ingestion.live_match import capture_live_matches
from fbi.picks.daily import build_daily_sets, product_day
from fbi.picks.fast_settlement import settle_fixtures
from fbi.providers.api_football.details import iter_fixture_details
from fbi.providers.base import RawResponse

from .conftest import Seed
from .test_ai_decision_layer import Savepoints
from .test_daily_records import AT, World

KO = AT + timedelta(hours=2)
_HASHES = itertools.count(1)


class Provider:
    """/fixtures?ids= as API-Football answers it, one prepared body per call."""

    def __init__(self, bodies: list[dict[str, Any]]) -> None:
        from fbi.providers.api_football import ApiFootballProvider
        self._parser = ApiFootballProvider.__new__(ApiFootballProvider)
        self.bodies = bodies

    def parse_fixtures(self, body: dict[str, Any]) -> Any:
        return self._parser.parse_fixtures(body)

    def parse_results(self, body: dict[str, Any]) -> Any:
        return self._parser.parse_results(body)

    async def fetch_fixture_details(self, *, provider_fixture_ids: list[int]) -> Any:
        body = self.bodies.pop(0)
        raw = RawResponse(endpoint="/fixtures", params={}, fetched_at=datetime.now(UTC), http_status=200,
                          results_count=1, payload_hash=f"e2e-{next(_HASHES)}-{datetime.now(UTC).timestamp()}",
                          file_path="x", bytes_written=1, body=body)
        return list(iter_fixture_details(body)), raw


def _body(db: psycopg.Connection[Any], fixture: int, *, short: str, minute: int | None, home: int,
          away: int) -> dict[str, Any]:
    row = db.execute(
        "SELECT f.provider_fixture_id, c.provider_league_id, cs.season, th.provider_team_id, ta.provider_team_id, "
        "th.name, ta.name FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id "
        "JOIN core.competitions c ON c.id = cs.competition_id JOIN core.teams th ON th.id = f.home_team_id "
        "JOIN core.teams ta ON ta.id = f.away_team_id WHERE f.id = %s", (fixture,)).fetchone()
    assert row is not None
    pid, league, season, hid, aid, hname, aname = row
    ended = short in ("FT", "AET", "PEN")
    return {"response": [{
        "fixture": {"id": pid, "date": KO.isoformat(), "timestamp": int(KO.timestamp()),
                    "status": {"short": short, "long": short, "elapsed": minute, "extra": None},
                    "venue": {"id": None, "name": None, "city": None}},
        "league": {"id": league, "season": season, "round": "Regular Season - 1"},
        "teams": {"home": {"id": hid, "name": hname}, "away": {"id": aid, "name": aname}},
        "goals": {"home": home, "away": away},
        "score": {"halftime": {"home": None, "away": None},
                  "fulltime": {"home": home if ended else None, "away": away if ended else None},
                  "extratime": {"home": None, "away": None}, "penalty": {"home": None, "away": None}},
        "events": [], "lineups": [], "statistics": [], "players": [],
    }]}


async def test_one_match_through_the_whole_cycle(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    f1, pick = w.fixtures["F1"], w.picks["F1"]
    db.execute("UPDATE core.competitions SET is_tracked = true WHERE id IN (SELECT cs.competition_id FROM "
               "core.competition_seasons cs JOIN core.fixtures f ON f.competition_season_id = cs.id WHERE f.id = %s)",
               (f1,))

    # 1-2. Scheduled, with its pre-match pick on the board and in the day's set.
    board = picks_board(db, include_shadow=False, competition_id=None, market=None, min_odds=None, max_odds=None,
                        hours=72, at=AT).data
    assert board is not None and pick in [p.pick_id for p in board.picks]
    w.review_all()  # PrediGol Intelligence looked at it: daily-set-v4's context stage
    build_daily_sets(db, at=AT)
    day = daily_board(db, day=None, include_shadow=False, at=AT).data
    assert day is not None and day.set is not None
    assert next(i for i in day.set.items if i.match.fixture_id == f1).match.phase == "scheduled"

    # 3-4. Kick-off: the live follow reads it in play.
    provider = Provider([_body(db, f1, short="1H", minute=12, home=1, away=0),
                         _body(db, f1, short="FT", minute=90, home=2, away=0)])
    conn: Any = Savepoints(db)  # the worker's commits, kept inside this test's transaction
    first = await capture_live_matches(conn, provider, at=KO + timedelta(minutes=12))
    assert first.followed >= 1 and first.ended == []
    live_day = daily_board(db, day=None, include_shadow=False, at=KO + timedelta(minutes=13)).data
    assert live_day is not None and live_day.set is not None
    item = next(i for i in live_day.set.items if i.match.fixture_id == f1)
    assert (item.match.phase, item.match.live_minute, item.status) == ("live", 12, "PENDING")

    # 5. The pre-match pick is still visible, as it was taken, never re-priced.
    during = picks_board(db, include_shadow=False, competition_id=None, market=None, min_odds=None, max_odds=None,
                         hours=72, at=KO + timedelta(minutes=13)).data
    assert during is not None
    started = next(s for s in during.started if s.pick_id == pick)
    assert (started.phase, str(started.odds_taken), started.live_home, started.live_away) == ("live", "2.300", 1, 0)

    # 6-7. Full time: the live follow hands the match over, and it is settled at once.
    second = await capture_live_matches(conn, provider, at=KO + timedelta(minutes=110))
    assert second.ended == [f1]
    settled = settle_fixtures(db, second.ended, path="live_follow", at=KO + timedelta(minutes=111))
    assert settled.fixtures == 1 and settled.picks >= 1 and settled.items >= 1
    assert db.execute("SELECT result_status FROM picks.pick_results WHERE pick_id = %s", (pick,)).fetchone() == ("win",)
    assert db.execute("SELECT path FROM picks.settlement_latency WHERE fixture_id = %s", (f1,)).fetchone() == (
        "live_follow",)

    # 8. The day's board, updated.
    after = daily_board(db, day=None, include_shadow=False, at=KO + timedelta(minutes=115)).data
    assert after is not None and after.set is not None
    done = next(i for i in after.set.items if i.match.fixture_id == f1)
    assert (done.status, done.match.phase, done.match.score_home, done.match.score_away) == ("WIN", "finished", 2, 0)

    # 9-10. The next morning: post-mortem and learning (rules only, no language model, nothing in production moved).
    next_morning = datetime.combine(product_day(AT) + timedelta(days=1), datetime.min.time(), tzinfo=UTC) \
        + timedelta(hours=12, minutes=35)  # 07:35 Bogotá
    run_learning_cycle(conn, at=next_morning, settings=AiSettings(mode="shadow"))
    pm = db.execute("SELECT verdict, answers->'win_quality'->'data'->>'win_quality' FROM ai.pick_postmortems "
                    "WHERE fixture_id = %s", (f1,)).fetchone()
    assert pm is not None and pm[0].endswith("won")
    assert db.execute("SELECT count(*) FROM ai.learning_notes WHERE day = %s", (product_day(AT),)).fetchone()[0] >= 1  # type: ignore[index]

    # 11. The day's close, as Evolución shows it.
    assert daily_review.store(db, day=product_day(AT), at=next_morning, kind="close") is not None
    review = review_api.day_review(db, day=product_day(AT)).data
    assert review is not None
    c = review.content
    assert c["daily_picks"]["won"] >= 1 and c["postmortems"]["n"] >= 1 and c["learning"]
    assert c["settlement"]["by_path"].get("live_follow") == 1
