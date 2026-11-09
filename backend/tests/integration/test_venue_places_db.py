"""The venue control and its repair against the database, with a ground like the real case (BE-005).

7 Nov 2026: ``GET /matches/9207`` (Valencia v Real Madrid, LaLiga) named venue 80 "Estadio de Mestalla", "Avenida de
Suecia", Spain, in "Valdivia" (Chile). Here: the venue's stored city is Valdivia while the provider's stored /venues
record says Valencia, Chilean grounds are in Valdivia, eighteen home matches name Mestalla in Valencia and one in
Valdivia. The truth audit's internal checks flag the venue and that match; the repair proposes both corrections in a
dry run, writes them only with ``apply``, logs each in ``audit.data_repairs`` and then has nothing left to do."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Json

from fbi.storage.payload_store import PayloadStore
from fbi.truth.findings import Kind, Severity
from fbi.truth.internal import run_internal
from tests.integration.conftest import Seed

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 7, 12, 0, tzinfo=UTC)
LEAGUE = 9951
VALENCIA, MADRID = 99511, 99512
MESTALLA, PARQUE, FELIX = 99801, 99802, 99803
ODD = 9952099
FIRST = 9952001


@pytest.fixture
def mestalla(migrated_database: str, seed: Seed, tmp_path: Path) -> Iterator[dict[str, Any]]:
    body = {"response": [{"id": MESTALLA, "name": "Estadio de Mestalla", "address": "Avenida de Suecia",
                          "city": "Valencia", "country": "Spain", "capacity": 49430}]}
    stored = PayloadStore(tmp_path).store(endpoint="/venues", params={"id": MESTALLA}, fetched_at=NOW - timedelta(days=3),
                                          http_status=200, body=body)
    with psycopg.connect(migrated_database, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, params, fetched_at, http_status, "
                    "results_count, file_path, bytes) VALUES (%s, %s, '/venues', %s, %s, 200, 1, %s, %s) "
                    "ON CONFLICT (hash) DO NOTHING",
                    (stored.hash, seed.run_id, Json({"id": str(MESTALLA)}), NOW - timedelta(days=3), stored.file_path,
                     stored.bytes_written))
        comp = cur.execute("INSERT INTO core.competitions (provider_league_id, name, country, type, entity_scope, "
                           "competition_type, tier, is_tracked) VALUES (%s, 'Venue League', 'Spain', 'league', 'club', "
                           "'domestic_league', 1, true) RETURNING id", (LEAGUE,)).fetchone()[0]  # type: ignore[index]
        season = cur.execute("INSERT INTO core.competition_seasons (competition_id, season, is_current) "
                             "VALUES (%s, 2026, true) RETURNING id", (comp,)).fetchone()[0]  # type: ignore[index]
        venue = cur.execute("INSERT INTO core.venues (provider_venue_id, name, city, country, address) "
                            "VALUES (%s, 'Estadio de Mestalla', 'Valdivia', 'Spain', 'Avenida de Suecia') RETURNING id",
                            (MESTALLA,)).fetchone()[0]  # type: ignore[index]
        others = [cur.execute("INSERT INTO core.venues (provider_venue_id, name, city, country) "
                              "VALUES (%s, %s, 'Valdivia', 'Chile') RETURNING id", (pid, name)).fetchone()[0]  # type: ignore[index]
                  for pid, name in ((PARQUE, "Estadio Parque Municipal"), (FELIX, "Estadio Félix Gallardo"))]
        home = cur.execute("INSERT INTO core.teams (provider_team_id, name, country, venue_id) "
                           "VALUES (%s, 'Valencia', 'Spain', %s) RETURNING id", (VALENCIA, venue)).fetchone()[0]  # type: ignore[index]
        away = cur.execute("INSERT INTO core.teams (provider_team_id, name, country) VALUES (%s, 'Real Madrid', 'Spain') "
                           "RETURNING id", (MADRID,)).fetchone()[0]  # type: ignore[index]
        fixtures = []
        day = datetime(2026, 8, 20, 19, 0, tzinfo=UTC)
        for i in range(19):
            pid, city = (ODD, "Valdivia") if i == 18 else (FIRST + i, "Valencia")
            fixtures.append(cur.execute(
                "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
                "kickoff_at, status_short, status_group, venue_id, venue_name, venue_city) "
                "VALUES (%s, %s, %s, %s, %s, 'FT', 'finished', %s, 'Estadio de Mestalla', %s) RETURNING id",
                (pid, season, home, away, day + timedelta(days=7 * i), venue, city)).fetchone()[0])  # type: ignore[index]
    yield {"venue": venue, "fixtures": fixtures, "store": PayloadStore(tmp_path), "root": tmp_path}
    with psycopg.connect(migrated_database, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM audit.data_repairs WHERE (entity = 'core.venues' AND entity_id = %s) "
                    "OR (entity = 'core.fixtures' AND entity_id = ANY(%s))", (venue, fixtures))
        cur.execute("DELETE FROM core.fixtures WHERE id = ANY(%s)", (fixtures,))
        cur.execute("DELETE FROM core.teams WHERE provider_team_id = ANY(%s)", ([VALENCIA, MADRID],))
        cur.execute("DELETE FROM core.venues WHERE id = ANY(%s)", ([venue, *others],))
        cur.execute("DELETE FROM core.competition_seasons WHERE id = %s", (season,))
        cur.execute("DELETE FROM core.competitions WHERE id = %s", (comp,))
        cur.execute("DELETE FROM raw.ingestion_payloads WHERE hash = %s", (stored.hash,))


def _mine(tallies: Any, venue: int) -> list[Any]:
    return [f for f in tallies["venues"].findings if f"core.venues {venue})" in f.entity]


def test_the_control_flags_the_ground_and_the_odd_match_without_writing(migrated_database: str,
                                                                        mestalla: dict[str, Any]) -> None:
    with psycopg.connect(migrated_database) as conn:
        conn.read_only = True
        tallies = run_internal(conn, at=NOW, store=mestalla["store"])
    found = _mine(tallies, mestalla["venue"])
    city = [f for f in found if f.field == "city"]
    assert [(f.kind, f.severity, f.api, f.db) for f in city] == [(Kind.MISMATCH, Severity.MEDIUM, "Valencia",
                                                                   "Valdivia")]
    assert "Chile" in city[0].note and "/venues payload" in city[0].note
    odd = [f for f in found if f.field == "venue_city"]
    assert [(f.entity.split(" at ")[0], f.api, f.db) for f in odd] == [(f"fixture {ODD}", "Valencia", "Valdivia")]
    assert not [f for f in found if f.field == "country"], "the country (Spain) is the competition's"

    with psycopg.connect(migrated_database) as conn:
        conn.read_only = True
        without_raw = run_internal(conn, at=NOW)
    assert any(f.field == "city" and f.kind is Kind.INCONSISTENT for f in _mine(without_raw, mestalla["venue"])), \
        "without the raw store the matches and the Chilean grounds still flag it"
    assert any("raw store not given" in n for n in without_raw["venues"].notes)


def test_the_repair_is_dry_first_then_logged_and_idempotent(migrated_database: str,
                                                           mestalla: dict[str, Any]) -> None:
    from scripts.repair_venue_city import RULE_FIXTURE, RULE_VENUE, repair

    venue, root = mestalla["venue"], mestalla["root"]
    with psycopg.connect(migrated_database) as conn:
        dry = repair(conn, root, apply=False, venue_ids=[venue])
        assert [(v.before, v.after) for v in dry.venues] == [("Valdivia", "Valencia")]
        assert [(f.provider_fixture_id, f.before, f.after) for f in dry.fixtures] == [(ODD, "Valdivia", "Valencia")]
        assert dry.written == 0 and not dry.problems
        assert conn.execute("SELECT city FROM core.venues WHERE id = %s", (venue,)).fetchone() == ("Valdivia",), \
            "a dry run writes nothing"

        done = repair(conn, root, apply=True, venue_ids=[venue])
        assert done.written == 2 and not done.problems
        assert conn.execute("SELECT city, address, country FROM core.venues WHERE id = %s", (venue,)).fetchone() \
            == ("Valencia", "Avenida de Suecia", "Spain")
        assert conn.execute("SELECT venue_city FROM core.fixtures WHERE provider_fixture_id = %s",
                            (ODD,)).fetchone() == ("Valencia",)
        rows = conn.execute(
            "SELECT rule, entity, provider_ref, field, before_value, after_value FROM audit.data_repairs "
            "WHERE rule IN (%s, %s) AND ((entity = 'core.venues' AND entity_id = %s) OR "
            "(entity = 'core.fixtures' AND entity_id = ANY(%s))) ORDER BY entity",
            (RULE_VENUE, RULE_FIXTURE, venue, mestalla["fixtures"])).fetchall()
        assert rows == [(RULE_FIXTURE, "core.fixtures", ODD, "venue_city", "Valdivia", "Valencia"),
                        (RULE_VENUE, "core.venues", MESTALLA, "city", "Valdivia", "Valencia")]
        evidence = conn.execute("SELECT evidence FROM audit.data_repairs WHERE rule = %s AND entity_id = %s",
                                (RULE_VENUE, venue)).fetchone()
        assert evidence is not None and "/venues payload" in evidence[0]

        again = repair(conn, root, apply=True, venue_ids=[venue])
        assert again.venues == [] and again.fixtures == [] and again.written == 0, "idempotent"
        after = run_internal(conn, at=NOW, store=mestalla["store"])
        assert _mine(after, venue) == [], "once corrected, the control has nothing to say"
        conn.rollback()


def test_a_restored_city_is_given_back_with_its_audit_row_and_the_repair_does_not_redo_it(
        migrated_database: str, mestalla: dict[str, Any]) -> None:
    """BE-029: when a person checks that a repaired city was wrong, ``restore_venue_city`` gives the provider's value back
    (one audit row each, only where the city is still the repaired one) and ``repair_venue_city`` leaves it alone."""
    from scripts.repair_venue_city import RULE_FIXTURE, repair
    from scripts.restore_venue_city import RULE_RESTORED, restore

    venue, root = mestalla["venue"], mestalla["root"]
    with psycopg.connect(migrated_database) as conn:
        repair(conn, root, apply=True, venue_ids=[venue])
        city = "SELECT venue_city FROM core.fixtures WHERE provider_fixture_id = %s"
        assert conn.execute(city, (ODD,)).fetchone() == ("Valencia",)

        dry = restore(conn, [venue], reason="test", apply=False)
        assert [(r.provider_fixture_id, r.current, r.restored) for r in dry.restores] == [(ODD, "Valencia", "Valdivia")]
        assert dry.written == 0 and conn.execute(city, (ODD,)).fetchone() == ("Valencia",), "a dry run writes nothing"

        done = restore(conn, [venue], reason="the stadium is in Valdivia in this test", apply=True)
        assert done.written == 1 and not done.problems
        assert conn.execute(city, (ODD,)).fetchone() == ("Valdivia",)
        row = conn.execute("SELECT rule, provider_ref, field, before_value, after_value, reason, evidence "
                           "FROM audit.data_repairs WHERE rule = %s AND entity_id = ANY(%s)",
                           (RULE_RESTORED, mestalla["fixtures"])).fetchone()
        assert row is not None and row[:5] == (RULE_RESTORED, ODD, "venue_city", "Valencia", "Valdivia")
        assert row[5] == "the stadium is in Valdivia in this test" and "undoes audit.data_repairs id" in (row[6] or "")
        assert conn.execute("SELECT count(*) FROM audit.data_repairs WHERE rule = %s AND entity_id = ANY(%s)",
                            (RULE_FIXTURE, mestalla["fixtures"])).fetchone() == (1,), "the repair row it undoes stays"

        assert restore(conn, [venue], reason="again", apply=True).restores == [], "idempotent"

        after = repair(conn, root, apply=False, venue_ids=[venue])
        assert after.fixtures == [] and after.reviewed == 1, "the rule does not repair a restored match again"
        assert conn.execute(city, (ODD,)).fetchone() == ("Valdivia",)

        conn.execute("UPDATE core.fixtures SET venue_city = 'Paterna' WHERE provider_fixture_id = %s", (ODD,))
        conn.commit()
        changed = repair(conn, root, apply=False, venue_ids=[venue])
        assert [(f.provider_fixture_id, f.before) for f in changed.fixtures] == [(ODD, "Paterna")], \
            "a city changed after the restoration is judged as before"
        assert restore(conn, [venue], reason="x", apply=False).restores == []


def test_restoring_leaves_alone_a_city_changed_since_the_repair_and_other_venues(
        migrated_database: str, mestalla: dict[str, Any]) -> None:
    from scripts.repair_venue_city import repair
    from scripts.restore_venue_city import restore

    venue, root = mestalla["venue"], mestalla["root"]
    with psycopg.connect(migrated_database) as conn:
        repair(conn, root, apply=True, venue_ids=[venue])
        other = venue + 100000
        assert restore(conn, [other], reason="x", apply=True).restores == [], "only the venues asked"
        conn.execute("UPDATE core.fixtures SET venue_city = 'Paterna' WHERE provider_fixture_id = %s", (ODD,))
        plan = restore(conn, [venue], reason="x", apply=True)
        assert plan.restores == [] and plan.written == 0
        assert any(str(ODD) in s and "no longer" in s for s in plan.skipped)
        assert conn.execute("SELECT venue_city FROM core.fixtures WHERE provider_fixture_id = %s",
                            (ODD,)).fetchone() == ("Paterna",)
