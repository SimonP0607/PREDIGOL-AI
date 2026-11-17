"""IA-075 and IA-076 against the database: the current coach and the corrections of careers (append-only, retractable, never
touching the provider's rows); the stadium load from a pinned snapshot with its altitude, the links of matches, the review
queue and the views of what is in force.

Every test runs in a transaction that is rolled back (the shared test database keeps nothing of it)."""

from __future__ import annotations

import itertools
import json
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import psycopg
import pytest

from fbi.people import current_coach_store as coaches
from fbi.venues import elevation, store
from fbi.venues.wikidata import parse
from tests.integration.conftest import Seed
from tests.integration.helpers import scalar
from tests.unit.test_venue_elevation import make_tiff

NOW = datetime.now(UTC)
_ids = itertools.count(9_750_000)


@pytest.fixture
def db(migrated_database: str, seed: Seed) -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(migrated_database) as conn:
        yield conn
        conn.rollback()


def one(db: psycopg.Connection[Any], sql: str, *params: object) -> Any:
    return scalar(db.execute(sql, params))


def team(db: psycopg.Connection[Any], name: str, venue_id: int | None = None) -> int:
    return int(one(db, "INSERT INTO core.teams (provider_team_id, name, venue_id) VALUES (%s, %s, %s) RETURNING id",
                   next(_ids), name, venue_id))


def fixture(db: psycopg.Connection[Any], seed: Seed, home: int, away: int, days_ago: float, *,
            venue_id: int | None = None, venue_name: str | None = None, venue_city: str | None = None,
            status: str = "finished", neutral: bool = False) -> int:
    return int(one(db, "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
                       "kickoff_at, status_group, status_short, venue_id, venue_name, venue_city, is_neutral) "
                       "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                   next(_ids), seed.season_id, home, away, NOW - timedelta(days=days_ago), status,
                   "FT" if status == "finished" else "NS", venue_id, venue_name, venue_city, neutral))


def lineup(db: psycopg.Connection[Any], seed: Seed, fixture_id: int, side: str, coach: int | None, name: str) -> None:
    db.execute("INSERT INTO core.fixture_lineups (fixture_id, team_side, source, provider_coach_id, coach_name, "
               "payload_hash, fetched_at) VALUES (%s, %s, 'api-football', %s, %s, %s, now())",
               (fixture_id, side, coach, name, seed.payload_hash))


def career(db: psycopg.Connection[Any], seed: Seed, coach: int, team_id: int, start: date | None,
           end: date | None = None, ordinal: int = 0) -> None:
    pid = int(one(db, "SELECT provider_team_id FROM core.teams WHERE id = %s", team_id))
    db.execute("INSERT INTO core.coach_careers (provider_coach_id, observed_at, ordinal, provider_team_id, team_name, "
               "start_date, end_date, payload_hash, normalizer_version, team_id) "
               "VALUES (%s, '2026-10-01Z', %s, %s, 'x', %s, %s, %s, 'test', %s)",
               (coach, ordinal, pid, start, end, seed.payload_hash, team_id))


def test_the_current_coach_and_a_correction_that_is_written_once_and_can_be_retracted(
        db: psycopg.Connection[Any], seed: Seed) -> None:
    a, b = team(db, "Club A"), team(db, "Club B")
    old, new = next(_ids), next(_ids)
    career(db, seed, old, a, date(2023, 7, 1))
    for days, coach, name in ((40, old, "Old Coach"), (20, new, "Nuevo Entrenador"), (8, new, "Nuevo Entrenador")):
        lineup(db, seed, fixture(db, seed, a, b, days), "home", coach, name)
    lineup(db, seed, fixture(db, seed, a, b, 2), "home", None, "")  # a sheet without a coach

    got = coaches.current_coach(db, [a, b])
    assert got[a]["provider_coach_id"] == new and got[a]["source"] == "lineup" and got[a]["streak"] == 2
    assert got[a]["sheets_without_coach"] == 1 and got[a]["as_of"] == (NOW - timedelta(days=8)).astimezone(UTC).date().isoformat()
    assert got[b]["source"] is None

    dry = coaches.close(db, apply=False, actor="test", team_ids=[a])
    assert (dry.proposed, dry.written) == (1, 0)
    assert one(db, "SELECT count(*) FROM core.coach_career_corrections") == 0
    first = coaches.close(db, apply=True, actor="test", team_ids=[a])
    again = coaches.close(db, apply=True, actor="test", team_ids=[a])
    assert (first.written, again.written, again.proposed) == (1, 0, 0)
    row = db.execute("SELECT provider_end_date, corrected_end_date, effective_end_date, end_date_source, correction_basis "
                     "FROM core.coach_careers_audited WHERE provider_coach_id = %s", (old,)).fetchone()
    assert row == (None, (NOW - timedelta(days=40)).date(), (NOW - timedelta(days=40)).date(), "correction",
                   "last_lineup")
    assert one(db, "SELECT end_date FROM core.coach_careers WHERE provider_coach_id = %s", old) is None, \
        "the provider's row is never written"

    cid = int(one(db, "SELECT id FROM core.coach_career_corrections WHERE provider_coach_id = %s", old))
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        db.execute("UPDATE core.coach_career_corrections SET end_date = now() WHERE id = %s", (cid,))
    assert coaches.retract(db, cid, actor="test", note="wrong", apply=True)["ok"]
    assert coaches.retract(db, cid, actor="test", note="again", apply=True)["reason"] == "already_retracted"
    assert one(db, "SELECT effective_end_date FROM core.coach_careers_audited WHERE provider_coach_id = %s", old) is None
    counts = coaches.team_open_counts(db)
    assert counts["teams_open_gt1_audited"] <= counts["teams_open_gt1_provider"]
    audit = coaches.audit(db)
    assert audit["corrections_written"] == 1 and audit["corrections_retracted"] == 1


def _snapshot(team_qid: str) -> dict[str, Any]:
    return {"query_version": "venue-wd-v1", "fetched_at": "2026-11-17T00:00:00+00:00", "batches": [{
        "team_qids": [team_qid], "answer": {"results": {"bindings": [{
            "team": {"value": f"http://www.wikidata.org/entity/{team_qid}"},
            "venue": {"value": "http://www.wikidata.org/entity/Q999001"},
            "rank": {"value": "http://wikiba.se/ontology#NormalRank"},
            "coords": {"value": "Point(-68.15 -16.35)"}, "caps": {"value": "41143"}, "elevs": {"value": "3637"},
            "names": {"value": "Estadio Hernando Siles"}, "places": {"value": "La Paz"}, "countries": {"value": "Bolivia"},
        }]}}}]}


def _team_qid(db: psycopg.Connection[Any], team_id: int, qid: str) -> None:
    load = int(one(db, "INSERT INTO core.entity_id_loads (source, release, rules_version, loaded_by) "
                       "VALUES ('core', %s, 'test', 'test') RETURNING id", f"t{next(_ids)}"))
    db.execute("INSERT INTO core.entity_ids (load_id, row_key, entity_type, entity_id, system, external_id, method, "
               "confidence, review) VALUES (%s, %s, 'team', %s, 'wikidata', %s, 'bridge_chain', 0.85, 'accepted')",
               (load, f"team:{team_id}:wikidata", team_id, qid))


def _dem() -> elevation.DemReader:
    grid = [[3600.0] * 10 for _ in range(10)]
    blob = make_tiff(grid, lon0=-69.0, lat0=-16.0, step=0.1)
    url = elevation.tile_url(elevation.tile_name(-16.35, -68.15))
    return elevation.DemReader(lambda u, a, b: blob[a:b + 1] if u == url else None)


def test_a_stadium_load_from_a_pinned_snapshot_with_its_altitude_once_and_retired(
        db: psycopg.Connection[Any], seed: Seed) -> None:
    vid = int(one(db, "INSERT INTO core.venues (provider_venue_id, name, city, country, capacity) "
                      "VALUES (%s, 'Estadio Hernando Siles', 'La Paz', 'Bolivia', 42000) RETURNING id", next(_ids)))
    t = team(db, "Bolívar", vid)
    _team_qid(db, t, "Q999000")
    snap = parse(_snapshot("Q999000"), "b" * 64)
    dry = store.load(db, snap, snapshot_name="wd_test.json", actor="test", apply=False, reader=_dem())
    assert dry.matched == 1 and dry.load_id is None
    assert one(db, "SELECT count(*) FROM core.venue_geo WHERE venue_id = %s", vid) == 0
    report = store.load(db, snap, snapshot_name="wd_test.json", actor="test", apply=True, reader=_dem())
    assert report.matched == 1 and report.with_elevation == 1 and report.by_method == {"home_venue_name": 1}
    assert report.elevation_checks == {"agrees": 1}
    assert store.load(db, snap, snapshot_name="wd_test.json", actor="test", apply=True).already_loaded
    live = db.execute("SELECT qid, latitude, longitude, elevation_m, elevation_source, capacity_wikidata, method "
                      "FROM core.venue_geo_live WHERE venue_id = %s", (vid,)).fetchone()
    assert live is not None and live[0] == "Q999001" and float(live[1]) == -16.35 and float(live[3]) == 3600.0
    assert live[4:] == ("copernicus_glo90", 41143, "home_venue_name")
    assert one(db, "SELECT capacity FROM core.venues WHERE id = %s", vid) == 42000, "the provider's row is not touched"
    licenses = one(db, "SELECT licenses FROM core.venue_geo_loads WHERE id = %s", report.load_id)
    assert "Copernicus" in licenses["dem_notice"] and licenses["wikidata"] == "CC0-1.0"
    assert store.retire(db, int(report.load_id or 0), actor="test", note="bad", apply=True)["retired"]
    assert one(db, "SELECT count(*) FROM core.venue_geo_live WHERE venue_id = %s", vid) == 0


def test_links_of_matches_without_an_id_the_queue_and_a_decision(db: psycopg.Connection[Any], seed: Seed) -> None:
    city = f"Ciudad{next(_ids)}"
    vid = int(one(db, "INSERT INTO core.venues (provider_venue_id, name, city) VALUES (%s, 'Estadio Kappa Uno', %s) "
                      "RETURNING id", next(_ids), city))
    twin_a = int(one(db, "INSERT INTO core.venues (provider_venue_id, name, city) VALUES (%s, 'Arena Gemela', %s) "
                         "RETURNING id", next(_ids), city))
    twin_b = int(one(db, "INSERT INTO core.venues (provider_venue_id, name, city) VALUES (%s, 'Arena Gemela', %s) "
                         "RETURNING id", next(_ids), city))
    home, away = team(db, "Kappa FC", vid), team(db, "Visitante")
    fixture(db, seed, home, away, 60, venue_id=vid, venue_name="Sponsor Park", venue_city=city)
    by_history = fixture(db, seed, home, away, -3, venue_name="Sponsor Park", venue_city=city, status="scheduled")
    by_home = fixture(db, seed, home, away, -5, venue_name="Estadio Kappa Uno", venue_city=city, status="scheduled")
    neutral = fixture(db, seed, home, away, -6, venue_name="Estadio Kappa Uno", venue_city="Otra", status="scheduled",
                      neutral=True)
    twins = fixture(db, seed, away, home, -7, venue_name="Arena Gemela", venue_city=city, status="scheduled")
    dry = store.link(db, apply=False)
    assert dry.linked >= 2 and one(db, "SELECT count(*) FROM core.fixture_venue_links WHERE fixture_id = %s",
                                   by_history) == 0
    report = store.link(db, apply=True)
    methods = dict(db.execute("SELECT fixture_id, method FROM core.fixture_venue_links WHERE fixture_id = ANY(%s)",
                              ([by_history, by_home, neutral, twins],)).fetchall())
    assert methods == {by_history: "provider_history_team", by_home: "home_ground"}
    assert report.questions.get("same_name_same_city", 0) >= 1
    assert store.link(db, apply=True).linked == 0, "a second pass writes nothing"
    resolved = dict(db.execute("SELECT fixture_id, venue_id FROM core.fixture_venue_resolved WHERE fixture_id = ANY(%s)",
                               ([by_history, by_home, twins],)).fetchall())
    assert resolved[by_history] == vid and resolved[by_home] == vid and resolved[twins] is None
    assert one(db, "SELECT venue_id FROM core.fixtures WHERE id = %s", by_history) is None, "the provider's row stays"

    qid = int(one(db, "SELECT id FROM core.venue_review_open WHERE kind = 'fixture_venue' AND subject_id = %s", twins))
    assert not store.decide(db, qid, "accept", actor="test", chosen="1", apply=True)["ok"]
    assert store.decide(db, qid, "accept", actor="test", chosen=str(twin_b), apply=True)["ok"]
    assert one(db, "SELECT venue_id FROM core.fixture_venue_resolved WHERE fixture_id = %s", twins) == twin_b
    assert one(db, "SELECT method FROM core.fixture_venue_resolved WHERE fixture_id = %s", twins) == "manual"
    assert one(db, "SELECT count(*) FROM core.venue_review_open WHERE id = %s", qid) == 0
    assert store.decide(db, qid, "undo", actor="test", apply=True)["ok"]
    assert one(db, "SELECT count(*) FROM core.venue_review_open WHERE id = %s", qid) == 1
    assert twin_a != twin_b
    q2 = store.decide(db, qid, "reject", actor="test", chosen=str(twin_a), apply=True)
    assert q2["ok"]
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        db.execute("DELETE FROM core.fixture_venue_links WHERE fixture_id = %s", (by_home,))
    cov = store.coverage(db)
    assert cov["fixtures_next14_resolved"] >= cov["fixtures_next14_provider_id"]
    assert json.dumps(cov)
