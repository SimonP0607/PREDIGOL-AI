"""The provider's last pre-match prices, read after the match: kept when stamped before kick-off,
refused when stamped after, asked once per match, only inside the provider's 7-day history.

The recovery commits (its ledger and each fixture), so this world lives in 2033 and is deleted
afterwards."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from fbi.odds.final_prematch import recover_final_prematch
from fbi.providers.api_football.provider import ApiFootballProvider
from tests.integration.conftest import Seed

AT = datetime(2033, 5, 1, 12, tzinfo=UTC)
LEAGUE = 97101
PRICED, AFTER_KO, EMPTY, TOO_OLD, TOO_RECENT = 7330001, 7330002, 7330003, 7330004, 7330005
KICKOFFS = {PRICED: AT - timedelta(days=2), AFTER_KO: AT - timedelta(days=3), EMPTY: AT - timedelta(days=4),
            TOO_OLD: AT - timedelta(days=8), TOO_RECENT: AT - timedelta(hours=1)}


@dataclass
class Stored:
    hash: str
    file_path: str = "x"
    bytes_written: int = 1


@dataclass
class Reply:
    endpoint: str
    params: dict[str, str]
    body: dict[str, Any]
    stored: Stored
    fetched_at: datetime = AT
    http_status: int = 200

    @property
    def results_count(self) -> int:
        return len(self.body.get("response") or [])


def _book(book_id: int, name: str, home: str) -> dict[str, Any]:
    return {"id": book_id, "name": name, "bets": [
        {"id": 1, "name": "Match Winner", "values": [{"value": "Home", "odd": home}, {"value": "Draw", "odd": "3.40"},
                                                    {"value": "Away", "odd": "3.10"}]},
        {"id": 5, "name": "Goals Over/Under", "values": [{"value": "Over 2.5", "odd": "1.90"},
                                                         {"value": "Under 2.5", "odd": "1.95"}]}]}


@dataclass
class FakeClient:
    calls: list[int] = field(default_factory=list)

    async def get(self, endpoint: str, params: dict[str, Any]) -> Reply:
        assert endpoint == "/odds"
        pf = int(params["fixture"])
        self.calls.append(pf)
        response: list[dict[str, Any]] = []
        if pf in (PRICED, AFTER_KO):
            stamp = KICKOFFS[pf] + (timedelta(minutes=-30) if pf == PRICED else timedelta(minutes=10))
            response = [{"fixture": {"id": pf}, "update": stamp.isoformat(),
                         "bookmakers": [_book(9908, "Bet365", "2.20"), _book(9932, "Betano", "2.25")]}]
        return Reply(endpoint, {"fixture": str(pf)}, {"response": response, "errors": []}, Stored(f"fpm-{pf}"))

    async def aclose(self) -> None:
        return None


@pytest.fixture
def played(migrated_database: str, seed: Seed) -> Iterator[str]:
    with psycopg.connect(migrated_database, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type, "
                    "is_tracked) VALUES (%s, 'Final League', 'league', 'club', 'domestic_league', true) RETURNING id",
                    (LEAGUE,))
        comp = cur.fetchone()[0]  # type: ignore[index]
        cur.execute("INSERT INTO core.competition_seasons (competition_id, season, is_current) VALUES (%s, 2033, true) "
                    "RETURNING id", (comp,))
        cs = cur.fetchone()[0]  # type: ignore[index]
        cur.execute("INSERT INTO market.markets (key, name, n_outcomes, has_line, is_exclusive) VALUES "
                    "('OU', 'Over/Under', 2, true, true) ON CONFLICT (key) DO NOTHING")
        for pf, ko in KICKOFFS.items():
            cur.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, "
                        "away_team_id, kickoff_at, status_short, status_group) "
                        "VALUES (%s, %s, %s, %s, %s, 'FT', 'finished')",
                        (pf, cs, seed.home_team_id, seed.away_team_id, ko))
    yield migrated_database
    with psycopg.connect(migrated_database, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM core.fixtures WHERE provider_fixture_id = ANY(%s)", (list(KICKOFFS),))
        cur.execute("DELETE FROM core.competition_seasons WHERE competition_id = %s", (comp,))
        cur.execute("DELETE FROM core.competitions WHERE id = %s", (comp,))
        cur.execute("DELETE FROM raw.ingestion_payloads WHERE hash LIKE 'fpm-%%'")
        cur.execute("DELETE FROM market.bookmakers WHERE provider_bookmaker_id IN (9908, 9932)")
        cur.execute("DELETE FROM raw.ingestion_runs WHERE job_type = 'final_prematch' AND scheduled_for = %s", (AT,))


async def test_last_prices_are_kept_only_when_stamped_before_kick_off(played: str) -> None:
    client = FakeClient()
    with psycopg.connect(played) as conn:
        report = await recover_final_prematch(conn, ApiFootballProvider(client), at=AT)  # type: ignore[arg-type]
        assert sorted(client.calls) == [PRICED, AFTER_KO, EMPTY], "only matches inside the 7-day history, once over"
        assert (report.asked, report.priced, report.after_kickoff, report.empty) == (3, 1, 1, 1)
        assert report.quotes == 10 and report.median_minutes_before_kickoff == 30
        rows = conn.execute(
            "SELECT b.provider_bookmaker_id, o.market_key, o.selection, o.odds_decimal, o.minutes_to_ko, "
            "o.provider_update_at < f.kickoff_at, o.fetched_at > o.provider_update_at "
            "FROM market.final_prematch_odds o JOIN core.fixtures f ON f.id = o.fixture_id "
            "JOIN market.bookmakers b ON b.id = o.bookmaker_id WHERE f.provider_fixture_id = %s", (PRICED,)).fetchall()
        assert len(rows) == 10
        assert all(r[4] == 30 and r[5] and r[6] for r in rows)
        assert len({r[2] for r in rows if r[1] == "1X2"}) == 3
        assert {(r[0], str(r[3])) for r in rows if r[1] == "1X2" and str(r[3]) in ("2.200", "2.250")} == {
            (9908, "2.200"), (9932, "2.250")}, "each bookmaker's own last price, not a consensus"
        checks: dict[int, str] = dict(conn.execute(
            "SELECT f.provider_fixture_id, k.outcome FROM market.final_prematch_checks k "
            "JOIN core.fixtures f ON f.id = k.fixture_id WHERE f.provider_fixture_id = ANY(%s)",
            (list(KICKOFFS),)).fetchall())
        assert checks == {PRICED: "priced", AFTER_KO: "after_kickoff", EMPTY: "empty"}
        none_after = conn.execute(
            "SELECT count(*) FROM market.final_prematch_odds o JOIN core.fixtures f ON f.id = o.fixture_id "
            "WHERE f.provider_fixture_id = %s", (AFTER_KO,)).fetchone()
        assert none_after == (0,), "a price stamped after kick-off may be in-play: refused whole"
        again = await recover_final_prematch(conn, ApiFootballProvider(FakeClient()), at=AT)  # type: ignore[arg-type]
        assert again.due == 0 and again.run_id is None, "each match is asked once"
