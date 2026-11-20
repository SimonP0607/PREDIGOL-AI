"""C-16 over the real application and a migrated database (PM-02-05): with ``FBI_AVAILABILITY`` off every one of the five routes answers
404 (the private ones too); on, the three public ones answer the public projection and the two private ones the private one to the owner,
403 to a reader. The cells are written by the nightly batch itself (``fbi.coverage.job``), not by hand."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import psycopg
import pytest
from fastapi.testclient import TestClient

from fbi.api.app import create_app
from fbi.api.cache import clear as clear_cache
from fbi.api.deps import get_db
from fbi.coverage import job
from tests.integration.conftest import Seed
from tests.integration.signed_in import SAME_SITE, signed_in

pytestmark = pytest.mark.integration
PUBLIC = ("/api/v1/availability/competitions", "/api/v1/availability/competitions/{c}", "/api/v1/matches/{f}/availability")
PRIVATE = ("/api/v1/admin/availability/matrix", "/api/v1/admin/availability/changes")
NOW = datetime(2026, 11, 22, 8, 0, tzinfo=UTC)


@pytest.fixture(scope="module")
def graded(migrated_database: str, seed: Seed) -> Iterator[tuple[int, int]]:
    """A tracked competition of its own with 12 finished matches with events and one to come, graded once by the batch (which commits:
    the module's database keeps it)."""
    with psycopg.connect(migrated_database, autocommit=True) as c:
        c.execute("UPDATE core.competitions SET is_tracked = false")
        comp = c.execute("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type, is_tracked) "
                         "VALUES (880001, 'Liga Ficticia', 'league', 'club', 'domestic_league', true) RETURNING id").fetchone()
        assert comp is not None
        cs = c.execute("INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, 2026) RETURNING id", (comp[0],)).fetchone()
        assert cs is not None

        def fixture(n: int, kickoff: datetime, status: tuple[str, str]) -> int:
            row = c.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at, "
                            "status_short, status_group) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                            (880100 + n, cs[0], seed.home_team_id, seed.away_team_id, kickoff, *status)).fetchone()
            assert row is not None
            return int(row[0])

        for i in range(12):
            fid = fixture(i, NOW - timedelta(days=40 - i), ("FT", "finished"))
            c.execute("INSERT INTO core.fixture_events (fixture_id, source, seq, minute, team_side, event_type, payload_hash, fetched_at) "
                      "VALUES (%s, 'api-football', 0, 3, 'home', 'Goal', %s, now())", (fid, seed.payload_hash))
        upcoming = fixture(50, NOW + timedelta(days=1), ("NS", "scheduled"))
    with psycopg.connect(migrated_database) as c:
        report = job.run_pass(c, now=NOW, full=True)
        assert report.graded >= 1, report.as_json()
    clear_cache()
    yield int(comp[0]), upcoming
    clear_cache()


def client(db: psycopg.Connection, role: str) -> TestClient:
    app = signed_in(create_app(), role)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app, headers=SAME_SITE)


def concrete(route: str, competition: int, fixture: int) -> str:
    return route.replace("{c}", str(competition)).replace("{f}", str(fixture))


def test_off_every_route_answers_404(graded: tuple[int, int], db: psycopg.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FBI_AVAILABILITY", raising=False)
    owner = client(db, "SUPER_ADMIN")
    for route in (*PUBLIC, *PRIVATE):
        answer = owner.get(concrete(route, *graded))
        assert answer.status_code == 404, (route, answer.status_code)


def test_on_the_five_routes_answer(graded: tuple[int, int], db: psycopg.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FBI_AVAILABILITY", "1")
    competition, fixture = graded
    reader = client(db, "USER")
    directory = reader.get(PUBLIC[0])
    assert directory.status_code == 200, directory.text
    data = directory.json()["data"]
    assert (data["contract"], data["contract_version"], data["projection"], data["scope"]) == ("C-16", "1.1.0", "public", "directorio")
    assert [c["competition_id"] for c in data["competitions"]] == [competition]
    assert data["competitions"][0]["seasons"] == []
    one = reader.get(concrete(PUBLIC[1], competition, fixture)).json()["data"]
    cells = {c["key"]: c for c in one["competitions"][0]["seasons"][0]["data"]}
    assert cells["events"]["level"] == "B" and cells["events"]["n"] == 12 and "measured_level" not in cells["events"]
    match = reader.get(concrete(PUBLIC[2], competition, fixture))
    assert match.status_code == 200, match.text
    body = match.json()["data"]["match"]
    assert body["fixture_id"] == fixture and {m["key"] for m in body["markets"]} >= {"1X2", "OU", "BTTS", "AH", "DC"}
    assert all("selections" not in m for m in body["markets"])  # Mi parlay's verdict by selection is the owner's
    assert reader.get(concrete(PUBLIC[1], 999_999_999, fixture)).status_code == 404
    assert reader.get(concrete(PUBLIC[2], competition, 999_999_999)).status_code == 404
    for route in PRIVATE:
        assert reader.get(route).status_code == 403
    owner = client(db, "SUPER_ADMIN")
    matrix = owner.get(PRIVATE[0]).json()["data"]
    assert matrix["projection"] == "private" and matrix["scope"] == "matriz"
    assert "measured_level" in matrix["competitions"][0]["seasons"][0]["data"][0]
    assert matrix["changes"]["items"], "the first grading is a change of every cell"
    changes = owner.get(PRIVATE[1]).json()["data"]
    assert changes["scope"] == "cambios" and changes["competitions"] == []
    assert changes["discrepancies"] == {"items": [], "missing_reason": "sin_datos"}
