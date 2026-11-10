"""BE-037: matches the provider filed under another ground's id are pointed at the ground they were played at.

The provider keeps one venue id for two grounds: 143 is the Raiffeisen Arena of Linz (2023) and the LASK's old ground at
Pasching. ``scripts.reassign_fixture_venue`` moves those matches with one audit row each, the sync keeps the move while the
payload repeats the old id, the truth audit does not report it as a difference, and the match page stops showing the
capacity of the other ground.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from fbi.api.repositories.fixtures import fixture_venue, get_fixture
from fbi.ingestion.fixtures import FixtureRepository, PayloadLineage
from fbi.providers.base import FixtureRef
from fbi.truth.audit import db_fixtures
from tests.integration.conftest import Seed

pytestmark = pytest.mark.integration

T0 = datetime(2026, 11, 10, 12, 0, tzinfo=UTC)
LEAGUE, SEASON = 9961, 2019
LINZ_ID, PASCHING_ID, WELS_ID = 99143, 99623, 99700
HOME, AWAY = 99611, 99612
FIRST = 9961001
# (provider fixture id, city the payload names)
OLD = [(FIRST, "Pasching"), (FIRST + 1, "Pasching"), (FIRST + 2, "PASCHING")]
NEW = (FIRST + 3, "Linz")


@pytest.fixture
def grounds(migrated_database: str, seed: Seed) -> Iterator[dict[str, Any]]:
    """Two grounds under two provider ids (the Linz arena and the Pasching ground) and a third one in Wels; five matches
    of one club filed under the Linz arena: three named 'Pasching' (the old ones) and one named 'Linz'."""
    with psycopg.connect(migrated_database, autocommit=True) as conn, conn.cursor() as cur:
        comp = cur.execute("INSERT INTO core.competitions (provider_league_id, name, country, type, entity_scope, "
                           "competition_type, tier, is_tracked) VALUES (%s, 'Reassign League', 'Austria', 'league', "
                           "'club', 'domestic_league', 1, true) RETURNING id", (LEAGUE,)).fetchone()[0]  # type: ignore[index]
        season = cur.execute("INSERT INTO core.competition_seasons (competition_id, season, is_current) "
                             "VALUES (%s, %s, false) RETURNING id", (comp, SEASON)).fetchone()[0]  # type: ignore[index]
        ids = {}
        for key, pid, name, city, capacity, address in (
                ("linz", LINZ_ID, "Raiffeisen Arena", "Linz", 19080, "Ziegeleistrasse 76"),
                ("pasching", PASCHING_ID, "voestalpine Stadion", "Pasching", 7870, "Poststrasse 38"),
                ("wels", WELS_ID, "Stadion Wels", "Wels", 5000, "Stadionstrasse 1")):
            ids[key] = cur.execute("INSERT INTO core.venues (provider_venue_id, name, city, country, capacity, address) "
                                   "VALUES (%s, %s, %s, 'Austria', %s, %s) RETURNING id",
                                   (pid, name, city, capacity, address)).fetchone()[0]  # type: ignore[index]
        home = cur.execute("INSERT INTO core.teams (provider_team_id, name, country, venue_id) "
                           "VALUES (%s, 'Linz FC', 'Austria', %s) RETURNING id", (HOME, ids["linz"])).fetchone()[0]  # type: ignore[index]
        away = cur.execute("INSERT INTO core.teams (provider_team_id, name, country) VALUES (%s, 'Wels FC', 'Austria') "
                           "RETURNING id", (AWAY,)).fetchone()[0]  # type: ignore[index]
        fixtures = []
        for i, (pid, city) in enumerate([*OLD, NEW]):
            fixtures.append(cur.execute(
                "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
                "kickoff_at, status_short, status_group, venue_id, venue_name, venue_city) "
                "VALUES (%s, %s, %s, %s, %s, 'FT', 'finished', %s, 'Raiffeisen Arena', %s) RETURNING id",
                (pid, season, home, away, T0 - timedelta(days=900 - 30 * i), ids["linz"], city)).fetchone()[0])  # type: ignore[index]
    yield {"venues": ids, "fixtures": fixtures, "season": season, "home": home, "away": away, "run": seed.run_id}
    with psycopg.connect(migrated_database, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM audit.data_repairs WHERE entity = 'core.fixtures' AND entity_id = ANY(%s)", (fixtures,))
        cur.execute("DELETE FROM core.fixtures WHERE id = ANY(%s)", (fixtures,))
        cur.execute("DELETE FROM core.teams WHERE provider_team_id = ANY(%s)", ([HOME, AWAY],))
        cur.execute("DELETE FROM core.venues WHERE id = ANY(%s)", (list(ids.values()),))
        cur.execute("DELETE FROM core.competition_seasons WHERE id = %s", (season,))
        cur.execute("DELETE FROM core.competitions WHERE id = %s", (comp,))
        cur.execute("DELETE FROM raw.ingestion_payloads WHERE hash LIKE 'be037-%%'")


def _venue_of(conn: psycopg.Connection, provider_fixture_id: int) -> int:
    row = conn.execute("SELECT venue_id FROM core.fixtures WHERE provider_fixture_id = %s", (provider_fixture_id,)).fetchone()
    assert row is not None
    return int(row[0])


def _rows(conn: psycopg.Connection, fixtures: list[int]) -> list[tuple[Any, ...]]:
    return conn.execute("SELECT rule, field, provider_ref, before_value, after_value, reason, evidence "
                        "FROM audit.data_repairs WHERE rule = 'fixture_venue_reassigned' AND entity = 'core.fixtures' "
                        "AND entity_id = ANY(%s) ORDER BY provider_ref", (fixtures,)).fetchall()


def test_a_dry_run_lists_the_matches_of_that_city_and_writes_nothing(migrated_database: str,
                                                                      grounds: dict[str, Any]) -> None:
    from scripts.reassign_fixture_venue import reassign

    v = grounds["venues"]
    with psycopg.connect(migrated_database) as conn:
        plan = reassign(conn, v["linz"], v["pasching"], "Pasching", reason="test", apply=False)
        assert not plan.refused and not plan.problems
        assert [m.provider_fixture_id for m in plan.moves] == [p for p, _ in OLD], "the three of 'Pasching', whatever the case"
        assert plan.left == 1 and plan.written == 0, "the one named 'Linz' stays"
        assert all(_venue_of(conn, p) == v["linz"] for p, _ in [*OLD, NEW]), "a dry run writes nothing"
        assert _rows(conn, grounds["fixtures"]) == []


def test_applying_moves_only_those_matches_with_one_audit_row_each_and_is_idempotent(migrated_database: str,
                                                                                      grounds: dict[str, Any]) -> None:
    from scripts.reassign_fixture_venue import RULE, reassign

    v = grounds["venues"]
    with psycopg.connect(migrated_database) as conn:
        done = reassign(conn, v["linz"], v["pasching"], "Pasching", reason="the LASK played at Pasching until 2022",
                        apply=True)
        assert done.written == 3 and not done.problems
        assert [_venue_of(conn, p) for p, _ in OLD] == [v["pasching"]] * 3
        assert _venue_of(conn, NEW[0]) == v["linz"], "a match of Linz stays at the Linz arena"
        rows = _rows(conn, grounds["fixtures"])
        assert [r[:5] for r in rows] == [(RULE, "venue_id", pid, str(v["linz"]), str(v["pasching"])) for pid, _ in OLD]
        assert all(r[5] == "the LASK played at Pasching until 2022" and "core.venues" in (r[6] or "") for r in rows)
        assert conn.execute("SELECT venue_name, venue_city FROM core.fixtures WHERE provider_fixture_id = %s",
                            (OLD[0][0],)).fetchone() == ("Raiffeisen Arena", "Pasching"), "name and city stay as sent"

        again = reassign(conn, v["linz"], v["pasching"], "Pasching", reason="again", apply=True)
        assert again.moves == [] and again.written == 0 and again.left == 1, "idempotent"
        assert len(_rows(conn, grounds["fixtures"])) == 3


def test_it_refuses_what_the_check_does_not_support_and_writes_nothing(migrated_database: str,
                                                                        grounds: dict[str, Any]) -> None:
    from scripts.reassign_fixture_venue import reassign

    v = grounds["venues"]
    with psycopg.connect(migrated_database) as conn:
        cases = {
            "same ground": reassign(conn, v["linz"], v["linz"], "Pasching", reason="x", apply=True),
            "matches of the ground's own city": reassign(conn, v["linz"], v["pasching"], "Linz", reason="x", apply=True),
            "a ground of another city": reassign(conn, v["linz"], v["wels"], "Pasching", reason="x", apply=True),
            "a ground that does not exist": reassign(conn, v["linz"], 987654321, "Pasching", reason="x", apply=True),
            "no city": reassign(conn, v["linz"], v["pasching"], "  ", reason="x", apply=True),
        }
        for name, plan in cases.items():
            assert plan.refused and plan.written == 0 and plan.moves == [], name
        assert all(_venue_of(conn, p) == v["linz"] for p, _ in [*OLD, NEW])
        assert _rows(conn, grounds["fixtures"]) == []


def test_the_sync_keeps_the_pointed_venue_until_the_provider_says_another(migrated_database: str,
                                                                          grounds: dict[str, Any]) -> None:
    """The payload of every refresh repeats id 143 (here the Linz arena's): that is the id the match was moved away from."""
    from scripts.reassign_fixture_venue import reassign

    v, season = grounds["venues"], grounds["season"]
    first = OLD[0][0]

    def sync(venue_provider_id: int, hash_: str, hours: int) -> None:
        with psycopg.connect(migrated_database, autocommit=True) as conn:
            conn.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, params, fetched_at, http_status, "
                         "file_path, bytes) VALUES (%s, %s, '/fixtures', '{}', %s, 200, %s, 1) ON CONFLICT DO NOTHING",
                         (hash_, grounds["run"], T0 + timedelta(hours=hours), hash_))
            ref = FixtureRef(provider_fixture_id=first, provider_league_id=LEAGUE, season=SEASON,
                             kickoff_at=T0 - timedelta(days=900), status_short="FT", provider_home_team_id=HOME,
                             provider_away_team_id=AWAY, round="R1", provider_venue_id=venue_provider_id,
                             venue_name="Raiffeisen Arena", venue_city="Pasching")
            FixtureRepository(conn).upsert_fixtures(
                [ref], {(LEAGUE, SEASON): season}, {HOME: grounds["home"], AWAY: grounds["away"]},
                lineage=PayloadLineage(hash_, T0 + timedelta(hours=hours)),
                venue_ids={LINZ_ID: v["linz"], WELS_ID: v["wels"]})

    sync(LINZ_ID, "be037-sync-0", 1)
    with psycopg.connect(migrated_database) as conn:
        assert _venue_of(conn, first) == v["linz"], "before the move the sync sets what the payload says"
        reassign(conn, v["linz"], v["pasching"], "Pasching", reason="test", apply=True)
        assert _venue_of(conn, first) == v["pasching"]
    sync(LINZ_ID, "be037-sync-1", 2)
    with psycopg.connect(migrated_database) as conn:
        assert _venue_of(conn, first) == v["pasching"], "the next refresh repeats id 143 and does not undo the move"
    sync(WELS_ID, "be037-sync-2", 3)
    with psycopg.connect(migrated_database) as conn:
        assert _venue_of(conn, first) == v["wels"], "another venue from the provider is a real change and is taken"
    sync(LINZ_ID, "be037-sync-3", 4)
    with psycopg.connect(migrated_database) as conn:
        assert _venue_of(conn, first) == v["linz"], "and the move no longer holds once the match is somewhere else"


def test_the_truth_audit_reads_the_move_as_deliberate_only_while_the_match_holds_it(migrated_database: str,
                                                                                    grounds: dict[str, Any]) -> None:
    from scripts.reassign_fixture_venue import reassign

    v = grounds["venues"]
    first = OLD[0][0]
    with psycopg.connect(migrated_database) as conn:
        before = db_fixtures(conn, [first, NEW[0]])
        assert before[first]["venue_reassigned"] is False and before[first]["venue_provider_id"] == LINZ_ID
        reassign(conn, v["linz"], v["pasching"], "Pasching", reason="test", apply=True)
        after = db_fixtures(conn, [first, NEW[0]])
        assert after[first]["venue_reassigned"] is True and after[first]["venue_provider_id"] == PASCHING_ID
        assert after[NEW[0]]["venue_reassigned"] is False, "a match that was not moved is compared as before"
        conn.execute("UPDATE core.fixtures SET venue_id = %s WHERE provider_fixture_id = %s", (v["wels"], first))
        assert db_fixtures(conn, [first])[first]["venue_reassigned"] is False, "the audit row is about the venue it gave"
        conn.rollback()


def test_the_match_page_stops_showing_the_capacity_of_the_other_ground(migrated_database: str,
                                                                        grounds: dict[str, Any]) -> None:
    from scripts.reassign_fixture_venue import reassign

    v = grounds["venues"]
    first_id, linz_id = grounds["fixtures"][0], grounds["fixtures"][3]
    with psycopg.connect(migrated_database) as conn:
        old = get_fixture(conn, first_id)
        assert old is not None
        shown = fixture_venue(conn, old)
        assert shown is not None and shown["capacity"] == 19080, "before: Pasching with the capacity of the Linz arena"

        reassign(conn, v["linz"], v["pasching"], "Pasching", reason="test", apply=True)
        moved, new = get_fixture(conn, first_id), get_fixture(conn, linz_id)
        assert moved is not None and new is not None
        assert fixture_venue(conn, moved) == {"id": None, "name": "Raiffeisen Arena", "city": "Pasching"}, \
            "the page says where the payload says it was played; the Linz arena's details are not attached to it"
        linz = fixture_venue(conn, new)
        assert linz is not None and linz["capacity"] == 19080 and linz["id"] == v["linz"], "the Linz arena keeps its own"
