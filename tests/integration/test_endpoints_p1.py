"""P1 (5 Oct 2026): the four API-Football endpoints the contract audit left PARTIAL, completed.

* /venues: a stadium asked by id fills core.venues (capacity, surface, address, picture) without erasing what /teams
  said; the fixture keeps the venue its payload names even without an id (0065), and the existing rows are filled
  from each fixture's own payload, nothing inferred.
* /players: the provider's season aggregate is on the player page, labelled as the provider's.
* /players/teams: a player's teams and seasons as the provider lists them, a snapshot per change, asked every 60 days
  and at once after the player's transfers changed.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg

from fbi.api.envelope import DataStatus
from fbi.api.repositories.fixtures import fixture_venue, get_fixture
from fbi.api.services import center
from fbi.ingestion import reference as ref
from fbi.ingestion.fixtures import FixtureRepository
from fbi.ingestion.payload_store import PayloadStore
from fbi.ops.reprocess import reprocess_fixture_venues
from fbi.providers.base import FixtureRef
from tests.integration.conftest import Seed

T0 = datetime(2026, 10, 5, 12, 0, tzinfo=UTC)


def payload(db: psycopg.Connection, seed: Seed, h: str, at: datetime = T0, endpoint: str = "/x") -> str:
    db.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, params, fetched_at, http_status, file_path, "
               "bytes) VALUES (%s, %s, %s, '{}', %s, 200, %s, 1) ON CONFLICT DO NOTHING",
               (h, seed.run_id, endpoint, at, h))
    return h


def target(**context: Any) -> ref.Target:
    return ref.Target("k", dict(context.pop("params", {})), timedelta(days=1), context)


# ── /venues ───────────────────────────────────────────────────────────────────────────────────────────


def ref_(fid: int, venue_id: int | None, name: str | None, city: str | None) -> FixtureRef:
    return FixtureRef(provider_fixture_id=fid, provider_league_id=39, season=2025, kickoff_at=T0 + timedelta(days=3),
                      status_short="NS", provider_home_team_id=33, provider_away_team_id=40, round="R1",
                      provider_venue_id=venue_id, venue_name=name, venue_city=city)


def test_a_fixture_keeps_the_venue_its_payload_names_even_without_an_id(db: psycopg.Connection, seed: Seed) -> None:
    repo = FixtureRepository(db)
    seasons = {(39, 2025): seed.season_id}
    teams = {33: seed.home_team_id, 40: seed.away_team_id}
    payload(db, seed, "vn-1", T0)
    payload(db, seed, "vn-2", T0 + timedelta(hours=1))
    payload(db, seed, "vn-3", T0 + timedelta(hours=2))
    from fbi.ingestion.fixtures import PayloadLineage

    def apply(r: FixtureRef, h: str, at: datetime) -> None:
        venues = repo.ensure_venues([r])
        repo.upsert_fixtures([r], seasons, teams, lineage=PayloadLineage(h, at), venue_ids=venues)

    apply(ref_(86001, None, "Estadio Atanasio Girardot", "Medellín"), "vn-1", T0)
    row = db.execute("SELECT venue_id, venue_name, venue_city FROM core.fixtures WHERE provider_fixture_id = 86001"
                     ).fetchone()
    assert row == (None, "Estadio Atanasio Girardot", "Medellín"), "no id: no venue row, the name is kept as sent"
    apply(ref_(86001, None, None, None), "vn-2", T0 + timedelta(hours=1))
    assert db.execute("SELECT venue_name FROM core.fixtures WHERE provider_fixture_id = 86001").fetchone() \
        == ("Estadio Atanasio Girardot",), "a later payload that names nothing does not erase it"
    apply(ref_(86001, 1062, "Estadio Atanasio Girardot", "Medellín"), "vn-3", T0 + timedelta(hours=2))
    fx = db.execute("SELECT id FROM core.fixtures WHERE provider_fixture_id = 86001").fetchone()
    assert fx is not None
    full = get_fixture(db, int(fx[0]))
    assert full is not None and full["venue_id"] is not None
    venue = fixture_venue(db, full)
    assert venue is not None and venue["name"] == "Estadio Atanasio Girardot" and venue["id"] == full["venue_id"]


def test_a_fixture_without_an_identified_venue_shows_the_name_it_was_given(db: psycopg.Connection,
                                                                          seed: Seed) -> None:
    db.execute("UPDATE core.fixtures SET venue_id = NULL, venue_name = 'Estadio X', venue_city = 'Y' WHERE id = %s",
               (seed.fixture_id,))
    full = get_fixture(db, seed.fixture_id)
    assert full is not None
    assert fixture_venue(db, full) == {"id": None, "name": "Estadio X", "city": "Y"}
    db.execute("UPDATE core.fixtures SET venue_name = NULL, venue_city = NULL WHERE id = %s", (seed.fixture_id,))
    full = get_fixture(db, seed.fixture_id)
    assert full is not None and fixture_venue(db, full) is None, "nothing named: nothing shown"


def store_fixture_payload(db: psycopg.Connection, seed: Seed, root: Path, body: dict[str, Any], at: datetime) -> str:
    stored = PayloadStore(root).store(endpoint="/fixtures", params={"league": 39, "season": 2025}, fetched_at=at,
                                      http_status=200, body=body)
    db.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, params, fetched_at, http_status, "
               "results_count, file_path, bytes) VALUES (%s, %s, '/fixtures', %s, %s, 200, %s, %s, %s) "
               "ON CONFLICT (hash) DO NOTHING",
               (stored.hash, seed.run_id, json.dumps({"league": 39, "season": 2025}), at,
                len(body["response"]), stored.file_path, stored.bytes_written))
    return stored.hash


def test_existing_fixtures_get_the_venue_their_own_payload_named(db: psycopg.Connection, seed: Seed,
                                                                tmp_path: Path) -> None:
    def entry(fid: int, venue: dict[str, Any]) -> dict[str, Any]:
        return {"fixture": {"id": fid, "date": "2026-10-08T19:00:00+00:00", "status": {"short": "NS"},
                            "venue": venue}, "league": {"id": 39, "season": 2025},
                "teams": {"home": {"id": 33}, "away": {"id": 40}}}

    body = {"response": [entry(86101, {"id": None, "name": "Estadio Pascual Guerrero", "city": "Cali"}),
                         entry(86102, {"id": None, "name": None, "city": None}),
                         entry(86199, {"id": None, "name": "Not ours", "city": "Z"})], "errors": []}
    h = store_fixture_payload(db, seed, tmp_path, body, T0)
    for fid in (86101, 86102):
        db.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
                   "kickoff_at, source_payload_hash, source_fetched_at) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                   (fid, seed.season_id, seed.home_team_id, seed.away_team_id, T0 + timedelta(days=3), h, T0))
    db.commit()  # the reprocess commits (and a dry run rolls back): the rows it reads must be committed
    try:
        dry = reprocess_fixture_venues(db, tmp_path, apply=False)
        assert dry.fixtures_touched == 1 and dry.coverage_rows == 0 and dry.payloads_not_rehashing == 0
        assert db.execute("SELECT count(*) FROM core.fixtures WHERE provider_fixture_id IN (86101, 86102) "
                          "AND venue_name IS NOT NULL").fetchone() == (0,), "a dry run writes nothing"
        done = reprocess_fixture_venues(db, tmp_path, apply=True)
        assert done.coverage_rows == 1
        got: dict[int, str | None] = dict(db.execute("SELECT provider_fixture_id, venue_name FROM core.fixtures "
                              "WHERE provider_fixture_id IN (86101, 86102, 86199)").fetchall())
        assert got == {86101: "Estadio Pascual Guerrero", 86102: None}, \
            "named where named; nothing invented, no new row"
        run = db.execute("SELECT status, rows_updated, api_calls FROM raw.ingestion_runs "
                         "WHERE job_type = 'reprocess_fixture_venues' ORDER BY id DESC LIMIT 1").fetchone()
        assert run == ("completed", 1, 0), "recorded in the ledger, at zero requests"
        again = reprocess_fixture_venues(db, tmp_path, apply=True)
        assert again.coverage_rows == 0, "idempotent: a named row is never rewritten"
    finally:
        db.rollback()
        db.execute("DELETE FROM core.fixtures WHERE provider_fixture_id IN (86101, 86102)")
        db.execute("DELETE FROM raw.ingestion_runs WHERE job_type = 'reprocess_fixture_venues'")
        db.execute("DELETE FROM raw.ingestion_payloads WHERE hash = %s", (h,))
        db.commit()


VENUE = {"id": 1062, "name": "Estadio Atanasio Girardot", "address": "Carrera 74 #48-10", "city": "Medellín",
         "country": "Colombia", "capacity": 40943, "surface": "grass",
         "image": "https://media.api-sports.io/football/venues/1062.png"}


def test_a_venue_asked_by_id_is_completed_without_erasing_what_was_known(db: psycopg.Connection, seed: Seed) -> None:
    db.execute("INSERT INTO core.venues (provider_venue_id, name, city) VALUES (1062, 'Atanasio Girardot', NULL)")
    for i, at in enumerate((T0, T0 + timedelta(days=1), T0 - timedelta(days=1))):
        payload(db, seed, f"ve-{i}", at, "/venues")
    assert ref.apply_venues(db, target(), {"response": [VENUE]}, "ve-0", T0) == 1
    assert db.execute("SELECT name, city, country, capacity, surface, address, image_url, source_payload_hash "
                      "FROM core.venues WHERE provider_venue_id = 1062").fetchone() == (
        "Estadio Atanasio Girardot", "Medellín", "Colombia", 40943, "grass", "Carrera 74 #48-10",
        "https://media.api-sports.io/football/venues/1062.png", "ve-0")
    blank = {**VENUE, "capacity": 0, "surface": None, "image": None}
    assert ref.apply_venues(db, target(), {"response": [blank]}, "ve-1", T0 + timedelta(days=1)) == 1
    assert db.execute("SELECT capacity, surface, image_url, source_payload_hash FROM core.venues "
                      "WHERE provider_venue_id = 1062").fetchone() == (
        40943, "grass", "https://media.api-sports.io/football/venues/1062.png", "ve-1"), \
        "a capacity of 0 is unknown; an empty value does not erase a known one"
    assert ref.apply_venues(db, target(), {"response": [{**VENUE, "capacity": 1}]}, "ve-2",
                            T0 - timedelta(days=1)) == 0, "an older payload changes nothing"
    assert ref.apply_venues(db, target(), {"response": [{"id": 1063, "name": None}, {"id": None, "name": "X"}]},
                            "ve-0", T0) == 0, "no id or no name: not a venue"


def test_the_venues_asked_are_those_of_current_tracked_seasons_not_described_lately(db: psycopg.Connection,
                                                                                   seed: Seed) -> None:
    db.execute("UPDATE core.competitions SET is_tracked = true WHERE id = %s", (seed.competition_id,))
    db.execute("UPDATE core.competition_seasons SET is_current = true WHERE id = %s", (seed.season_id,))
    payload(db, seed, "vt-0", T0)
    ids = {}
    for vid, fetched in ((7001, None), (7002, T0 - timedelta(days=10)), (7003, T0 - timedelta(days=100)),
                         (7004, None)):
        r = db.execute("INSERT INTO core.venues (provider_venue_id, name, source_payload_hash, source_fetched_at) "
                       "VALUES (%s, %s, %s, %s) RETURNING id",
                       (vid, f"V{vid}", "vt-0" if fetched else None, fetched)).fetchone()
        assert r is not None
        ids[vid] = int(r[0])
    db.execute("UPDATE core.fixtures SET venue_id = %s, kickoff_at = %s, status_group = 'scheduled' WHERE id = %s",
               (ids[7001], T0 + timedelta(days=2), seed.fixture_id))
    db.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
               "kickoff_at, venue_id) VALUES (86201, %s, %s, %s, %s, %s)",
               (seed.season_id, seed.away_team_id, seed.home_team_id, T0 + timedelta(days=1), ids[7002]))
    db.execute("UPDATE core.teams SET venue_id = %s WHERE id = %s", (ids[7003], seed.away_team_id))
    keys = [t.key for t in ref.venue_targets(db, T0)]
    assert keys == ["venue:7001", "venue:7003"], \
        "never described (next match first), described 100 days ago (a tracked team's ground); not the fresh one, " \
        "not one no tracked match or team uses"
    assert all(t.every == ref.VENUE_REFRESH for t in ref.venue_targets(db, T0))


# ── /players and /players/teams ─────────────────────────────────────────────────────────────────────


CAREER = {"response": [
    {"team": {"id": 1138, "name": "America de Cali", "logo": "https://media.api-sports.io/football/teams/1138.png"},
     "seasons": [2024, 2026, 2025, 2025]},
    {"team": {"id": 33, "name": "Manchester United", "logo": None}, "seasons": [2023]},
    {"team": {"id": 8, "name": "Colombia"}, "seasons": [2026, 1066]},
]}


def test_a_players_teams_are_kept_as_a_snapshot_per_change(db: psycopg.Connection, seed: Seed) -> None:
    for i in range(3):
        payload(db, seed, f"pt-{i}", T0 + timedelta(days=i), "/players/teams")
    t = target(ids=[13491])
    assert ref.apply_player_teams(db, t, CAREER, "pt-0", T0) == 3
    reordered = {"response": [{**CAREER["response"][0], "seasons": [2025, 2024, 2026]}, *CAREER["response"][1:]]}
    assert ref.apply_player_teams(db, t, reordered, "pt-1", T0 + timedelta(days=1)) == 0, \
        "the same seasons in another order are not a change"
    moved = {"response": [{"team": {"id": 50, "name": "City"}, "seasons": [2027]}, *CAREER["response"]]}
    assert ref.apply_player_teams(db, t, moved, "pt-2", T0 + timedelta(days=2)) == 4
    rows = db.execute("SELECT ordinal, provider_team_id, seasons FROM core.player_team_seasons_latest "
                      "WHERE provider_player_id = 13491 ORDER BY ordinal").fetchall()
    assert rows[0] == (0, 50, [2027]) and rows[1] == (1, 1138, [2026, 2025, 2024])
    assert rows[3] == (3, 8, [2026]), "1066 is not a season: left out, not corrected"


def test_a_player_is_asked_again_at_once_when_his_transfers_changed(db: psycopg.Connection, seed: Seed) -> None:
    db.execute("UPDATE core.competitions SET is_tracked = true WHERE id = %s", (seed.competition_id,))
    db.execute("UPDATE core.competition_seasons SET is_current = true WHERE id = %s", (seed.season_id,))
    db.execute("UPDATE core.fixtures SET kickoff_at = %s, status_group = 'finished' WHERE id = %s",
               (T0 - timedelta(days=3), seed.fixture_id))
    for player in (5, 9):
        db.execute("INSERT INTO core.fixture_player_stats (fixture_id, source, provider_player_id, team_side, minutes, "
                   "payload_hash, fetched_at) VALUES (%s, 'api-football', %s, 'home', 90, %s, now())",
                   (seed.fixture_id, player, seed.payload_hash))
    first = {t.key: t.every for t in ref.player_team_targets(db, T0)}
    assert first == {"player:5": ref.CAREER_REFRESH, "player:9": ref.CAREER_REFRESH}
    ref.record_check(db, "players_teams", "player:5", checked_at=T0, payload_hash=None, results=1, rows_added=1)
    ref.record_check(db, "players_teams", "player:9", checked_at=T0, payload_hash=None, results=1, rows_added=1)
    payload(db, seed, "tf-9", T0 + timedelta(days=1), "/transfers")
    ref.apply_transfers(db, target(), {"response": [{"player": {"id": 9}, "update": "2026-10-06T00:00:00+00:00",
                                                     "transfers": [{"date": "2026-10-01", "type": "Free",
                                                                    "teams": {"in": {"id": 50}, "out": {"id": 33}}}]}]},
                        "tf-9", T0 + timedelta(days=1))
    later = {t.key: t.every for t in ref.player_team_targets(db, T0 + timedelta(days=2))}
    assert later == {"player:5": ref.CAREER_REFRESH, "player:9": timedelta(0)}, "a new transfer: due at once"
    feed = next(f for f in ref.FEEDS if f.name == "players_teams")
    due = [t.key for t in ref.due_targets(db, feed, T0 + timedelta(days=2))]
    assert due == ["player:9"]


def test_the_player_page_shows_the_providers_aggregate_and_teams_labelled_as_the_providers(
        db: psycopg.Connection, seed: Seed) -> None:
    row = db.execute("INSERT INTO core.players (provider_player_id, name) VALUES (13491, 'Y. Guzmán') "
                     "RETURNING id").fetchone()
    assert row is not None
    pid = int(row[0])
    first = center.player(db, pid).data
    assert first is not None and first.provider_seasons is not None and first.career is not None
    assert first.provider_seasons.status is DataStatus.EMPTY and first.career.status is DataStatus.EMPTY
    assert first.career.reason and "not been read" in first.career.reason
    payload(db, seed, "ps-1", T0, "/players")
    db.execute("INSERT INTO core.player_season_stats (provider_player_id, provider_league_id, season, provider_team_id, "
               "observed_at, appearances, lineups, minutes, goals, assists, rating, payload_hash, normalizer_version) "
               "VALUES (13491, 39, 2025, 33, %s, 9, 8, 800, 8, 2, 7.25, 'ps-1', 'season-stats-1')", (T0,))
    payload(db, seed, "pt-1", T0, "/players/teams")
    ref.apply_player_teams(db, target(ids=[13491]), CAREER, "pt-1", T0)
    ref.record_check(db, "players_teams", "player:13491", checked_at=T0 + timedelta(hours=1), payload_hash="pt-1",
                     results=3, rows_added=3)
    d = center.player(db, pid).data
    assert d is not None and d.provider_seasons is not None and d.career is not None
    s = d.provider_seasons.data[0]
    assert (s.competition, s.team, s.team_id, s.appearances, s.goals, str(s.rating)) == (
        "Premier League", "Manchester United", seed.home_team_id, 9, 8, "7.250000")
    assert d.provenance["provider_seasons"].source == "API-Football /players"
    assert d.provenance["provider_seasons"].payload_hash == "ps-1"
    assert [c.team for c in d.career.data] == ["America de Cali", "Manchester United", "Colombia"]
    assert d.career.data[1].team_id == seed.home_team_id and d.career.data[0].team_id is None
    assert d.provenance["career"].checked_at == T0 + timedelta(hours=1)


# ── venue identity (found while completing /venues) ─────────────────────────────────────────────────


def test_id_zero_is_not_a_venue_and_a_fixture_block_never_renames_one(db: psycopg.Connection, seed: Seed) -> None:
    from fbi.providers.api_football.normalize import iter_fixtures

    body = {"response": [{"fixture": {"id": 86301, "date": "2026-10-08T19:00:00+00:00", "status": {"short": "NS"},
                                      "venue": {"id": 0, "name": "Allianz Arena", "city": "Munich"}},
                          "league": {"id": 39, "season": 2025}, "teams": {"home": {"id": 33}, "away": {"id": 40}}}]}
    parsed = next(iter_fixtures(body))
    assert parsed.provider_venue_id is None and parsed.venue_name == "Allianz Arena", "0 is the provider's 'no id'"
    repo = FixtureRepository(db)
    assert repo.ensure_venues([ref_(86302, 0, "Estadio Banorte", "Mexico City")]) == {}
    db.execute("INSERT INTO core.venues (provider_venue_id, name, city) VALUES (907, 'Stadio Giuseppe Meazza', NULL)")
    perth = ref_(86302, 907, "Optus Stadium", "Perth")
    venues = repo.ensure_venues([perth])
    assert db.execute("SELECT name, city FROM core.venues WHERE provider_venue_id = 907").fetchone() == (
        "Stadio Giuseppe Meazza", None), "a fixture block never changes a known venue (not even a missing city)"
    repo.upsert_fixtures([perth], {(39, 2025): seed.season_id}, {33: seed.home_team_id, 40: seed.away_team_id},
                         venue_ids=venues)
    fx = db.execute("SELECT id FROM core.fixtures WHERE provider_fixture_id = 86302").fetchone()
    assert fx is not None
    full = get_fixture(db, int(fx[0]))
    assert full is not None and full["venue_id"] == venues[907]
    shown = fixture_venue(db, full)
    assert shown == {"id": None, "name": "Optus Stadium", "city": "Perth"}, \
        "the match is shown where its payload says it is played; San Siro's details are not attached to Perth"
    db.execute("UPDATE core.venues SET capacity = 75817 WHERE provider_venue_id = 907")
    db.execute("UPDATE core.fixtures SET venue_name = 'Stadio Giuseppe  Meazza', venue_city = 'Milano' "
               "WHERE provider_fixture_id = 86302")
    full = get_fixture(db, int(fx[0]))
    assert full is not None
    same = fixture_venue(db, full)
    assert same is not None and same["id"] == venues[907] and same["capacity"] == 75817, \
        "the same ground (spelling aside): its details are shown"


def test_the_venue_identity_repair_unpoints_id_zero_and_restores_described_names(db: psycopg.Connection, seed: Seed,
                                                                                tmp_path: Path) -> None:
    from scripts.repair_venue_identity import repair

    teams_body = {"response": [{"team": {"id": 33, "name": "Manchester United"},
                                "venue": {"id": 7101, "name": "Old Trafford", "city": "Manchester"}}]}
    stored = PayloadStore(tmp_path).store(endpoint="/teams", params={"league": 39, "season": 2025}, fetched_at=T0,
                                          http_status=200, body=teams_body)
    db.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, params, fetched_at, http_status, "
               "results_count, file_path, bytes) VALUES (%s, %s, '/teams', '{}', %s, 200, 1, %s, %s)",
               (stored.hash, seed.run_id, T0, stored.file_path, stored.bytes_written))
    zero = db.execute("INSERT INTO core.venues (provider_venue_id, name, city) VALUES (0, 'Estadio Banorte', "
                      "'Mexico City') RETURNING id").fetchone()
    real = db.execute("INSERT INTO core.venues (provider_venue_id, name, city, source_payload_hash, source_fetched_at) "
                      "VALUES (7101, 'Optus Stadium', 'Perth', %s, %s) RETURNING id", (stored.hash, T0)).fetchone()
    assert zero is not None and real is not None
    db.execute("UPDATE core.fixtures SET venue_id = %s WHERE id = %s", (zero[0], seed.fixture_id))
    db.execute("UPDATE core.teams SET venue_id = %s WHERE id = %s", (zero[0], seed.away_team_id))
    db.commit()
    try:
        dry = repair(db, tmp_path, apply=False)
        assert dry.pointers == {"core.fixtures": 1, "core.teams": 1} and dry.renamed == 1 and dry.city_restored == 1
        assert db.execute("SELECT venue_id FROM core.fixtures WHERE id = %s", (seed.fixture_id,)).fetchone() \
            == (zero[0],), "a dry run writes nothing"
        done = repair(db, tmp_path, apply=True)
        assert not done.problems
        assert db.execute("SELECT venue_id FROM core.fixtures WHERE id = %s", (seed.fixture_id,)).fetchone() == (None,)
        assert db.execute("SELECT venue_id FROM core.teams WHERE id = %s", (seed.away_team_id,)).fetchone() == (None,)
        assert db.execute("SELECT name, city FROM core.venues WHERE id = %s", (real[0],)).fetchone() \
            == ("Old Trafford", "Manchester")
        assert db.execute("SELECT count(*) FROM core.venues WHERE id = %s", (zero[0],)).fetchone() == (1,), \
            "the id-0 row is kept, unreferenced"
        rows = db.execute("SELECT rule, entity, field, before_value, after_value FROM audit.data_repairs "
                          "WHERE rule IN ('venue_id_zero', 'venue_name_from_source') ORDER BY entity, field").fetchall()
        assert rows == [("venue_id_zero", "core.fixtures", "venue_id", str(zero[0]), None),
                        ("venue_id_zero", "core.teams", "venue_id", str(zero[0]), None),
                        ("venue_name_from_source", "core.venues", "city", "Perth", "Manchester"),
                        ("venue_name_from_source", "core.venues", "name", "Optus Stadium", "Old Trafford")]
        again = repair(db, tmp_path, apply=True)
        assert again.pointers == {} and again.renamed == 0, "idempotent"
    finally:
        db.rollback()
        db.execute("UPDATE core.fixtures SET venue_id = NULL WHERE id = %s", (seed.fixture_id,))
        db.execute("UPDATE core.teams SET venue_id = NULL WHERE id = %s", (seed.away_team_id,))
        db.execute("DELETE FROM audit.data_repairs WHERE rule IN ('venue_id_zero', 'venue_name_from_source')")
        db.execute("DELETE FROM core.venues WHERE id IN (%s, %s)", (zero[0], real[0]))
        db.execute("DELETE FROM raw.ingestion_payloads WHERE hash = %s", (stored.hash,))
        db.commit()
