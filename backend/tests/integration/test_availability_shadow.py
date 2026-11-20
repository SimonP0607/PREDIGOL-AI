"""PM-02-06: the shadow comparison on a real database - a seeded match with a known discrepancy (Cuotas lists a market two houses price,
the matrix says no price in force) is written once, with its module, subject and reason; a second pass the same day adds nothing; the
sample takes only matches still to be played of tracked competitions."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from itertools import count

import psycopg
import pytest

import fbi.api.services.market_probs as market_probs
import fbi.coverage.resolve as resolve
from fbi.api.services import availability_shadow
from fbi.coverage import shadow
from fbi.odds.quote_current import CurrentBook, CurrentQuote

pytestmark = pytest.mark.integration
AT = datetime(2026, 11, 21, 9, 0, tzinfo=UTC)
_ids = count(970_000)


def one(c: psycopg.Connection, sql: str, params: tuple[object, ...] | None = None) -> int:
    row = c.execute(sql, params).fetchone()
    assert row is not None
    return int(row[0])


@pytest.fixture()
def world(migrated_database: str) -> Iterator[tuple[psycopg.Connection, int, dict[int, tuple[CurrentQuote, ...]]]]:
    with psycopg.connect(migrated_database) as c:
        c.execute("UPDATE core.competitions SET is_tracked = false")
        c.execute("DELETE FROM analytics.availability_discrepancies")
        comp = one(c, "INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type, is_tracked) "
                      "VALUES (%s, 'Liga S', 'league', 'club', 'domestic_league', true) RETURNING id", (next(_ids),))
        cs = one(c, "INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, 2026) RETURNING id", (comp,))
        books = [one(c, "INSERT INTO market.bookmakers (provider_bookmaker_id, name) VALUES (%s, %s) RETURNING id", (next(_ids), f"Casa {i}"))
                 for i in range(2)]
        a = one(c, "INSERT INTO core.teams (provider_team_id, name) VALUES (%s, 'A') RETURNING id", (next(_ids),))
        b = one(c, "INSERT INTO core.teams (provider_team_id, name) VALUES (%s, 'B') RETURNING id", (next(_ids),))
        fid = one(c, "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at, "
                     "status_short, status_group) VALUES (%s, %s, %s, %s, %s, 'NS', 'scheduled') RETURNING id",
                  (next(_ids), cs, a, b, AT + timedelta(hours=8)))
        # a match far ahead and one started: neither is in the sample
        one(c, "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at, "
               "status_short, status_group) VALUES (%s, %s, %s, %s, %s, 'NS', 'scheduled') RETURNING id",
            (next(_ids), cs, a, b, AT + timedelta(days=5)))
        quotes = tuple(CurrentQuote(bookmaker_id=bk, bookmaker=f"Casa {bk}", bet_id=45, family="corners", period="FT", subject="match",
                                    kind="over_under", has_line=True, market_key=None, provider_name="Corners Over Under",
                                    selection=sel, line=Decimal("9.5"), odds=Decimal("1.90"), captured_at=AT, since=AT)
                       for bk in books for sel in ("Over", "Under"))
        c.commit()
        yield c, fid, {fid: quotes}


def _book(quotes: dict[int, tuple[CurrentQuote, ...]]) -> Callable[..., CurrentBook | None]:
    def fake(conn: object, fixture_id: int) -> CurrentBook | None:
        qs = quotes.get(fixture_id)
        return None if qs is None else CurrentBook(fixture_id=fixture_id, kickoff_at=AT, in_force=None, quotes=qs)  # type: ignore[arg-type]
    return fake


def test_a_known_discrepancy_is_recorded_once(world, monkeypatch: pytest.MonkeyPatch) -> None:
    c, fid, quotes = world
    fake = _book(quotes)
    monkeypatch.setattr(market_probs, "book_in_force", fake)
    monkeypatch.setattr(resolve, "book", fake)
    assert shadow.sample(c, at=AT) == [fid]
    report = availability_shadow.run(c, at=AT, code_version="test")
    assert report.matches == 1 and report.errors == []
    rows = c.execute("SELECT module, subject, shown, matrix, reason FROM analytics.availability_discrepancies WHERE fixture_id = %s "
                     "ORDER BY module, subject", (fid,)).fetchall()
    assert ("cuotas", "corners_over_under.FT.match", True, False, "menos_de_3_casas") in rows
    assert report.written == len(rows) and report.by_module["cuotas"] == 1
    again = availability_shadow.run(c, at=AT + timedelta(minutes=30), code_version="test")
    assert again.written == 0
    assert c.execute("SELECT count(*) FROM analytics.availability_discrepancies").fetchone() == (len(rows),)
