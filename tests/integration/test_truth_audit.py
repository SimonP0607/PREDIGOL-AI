"""The truth audit end to end, against a real database and a provider that answers from literals."""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest

from fbi.truth.audit import run_audit
from fbi.truth.freshness import measure
from fbi.truth.gate import MODEL_NEEDS, evaluate
from fbi.truth.internal import run_internal
from fbi.truth.sample import SampleSize
from tests.integration.conftest import Seed

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
LEAGUE, SEASON = 9901, 2026
TEAM_A, TEAM_B = 99011, 99012


@dataclass
class Reply:
    body: dict[str, Any]
    params: dict[str, str]
    fetched_at: datetime = NOW
    http_status: int = 200
    stored: Any = None

    @property
    def results_count(self) -> int:
        r = self.body.get("response")
        return len(r) if isinstance(r, list) else 0


def fixture_item(pid: int, status: str, kickoff: datetime, goals: tuple[int | None, int | None]) -> dict[str, Any]:
    return {
        "fixture": {"id": pid, "date": kickoff.isoformat(), "status": {"short": status}, "venue": {"id": None}},
        "league": {"id": LEAGUE, "name": "Truth League", "season": SEASON, "round": "Regular Season - 1"},
        "teams": {"home": {"id": TEAM_A, "name": "Truth A"}, "away": {"id": TEAM_B, "name": "Truth B"}},
        "goals": {"home": goals[0], "away": goals[1]},
        "score": {"halftime": {"home": None, "away": None}, "fulltime": {"home": goals[0], "away": goals[1]},
                  "extratime": {"home": None, "away": None}, "penalty": {"home": None, "away": None}},
    }


class FakeClient:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def get(self, endpoint: str, params: dict[str, Any]) -> Reply:
        self.calls.append((endpoint, dict(params)))
        p = {k: str(v) for k, v in params.items()}
        response: list[dict[str, Any]] = []
        if endpoint == "/leagues":
            response = [{"league": {"id": LEAGUE, "name": "Truth League", "type": "League"},
                         "seasons": [{"year": SEASON, "current": True, "start": "2026-08-01", "end": "2027-05-30",
                                      "coverage": {"standings": True, "odds": True}}]}]
        elif endpoint == "/fixtures" and p.get("league") == str(LEAGUE):
            response = [
                fixture_item(990001, "FT", NOW - timedelta(days=2), (2, 1)),
                fixture_item(990002, "Canc", NOW - timedelta(days=1), (None, None)),
                fixture_item(990003, "NS", NOW + timedelta(days=1), (None, None)),
                fixture_item(990005, "NS", NOW + timedelta(days=5), (None, None)),
            ]
        elif endpoint == "/standings" and p.get("league") == str(LEAGUE):
            response = [{"league": {"id": LEAGUE, "name": "Truth League", "season": SEASON, "standings": [[
                {"rank": 1, "team": {"id": TEAM_A, "name": "Truth A"}, "points": 3, "goalsDiff": 1,
                 "group": "Truth League", "form": "W", "status": "same", "description": "Promotion",
                 "all": {"played": 1, "win": 1, "draw": 0, "lose": 0, "goals": {"for": 2, "against": 1}},
                 "home": {"played": 1, "win": 1, "draw": 0, "lose": 0, "goals": {"for": 2, "against": 1}},
                 "away": {"played": 0, "win": 0, "draw": 0, "lose": 0, "goals": {"for": 0, "against": 0}},
                 "update": "2026-10-03T00:00:00+00:00"}]]}}]
        return Reply({"response": response, "errors": []}, p)


@pytest.fixture
def truth_league(migrated_database: str, seed: Seed) -> Iterator[dict[str, int]]:
    with psycopg.connect(migrated_database, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type, "
                    "tier, is_tracked) VALUES (%s, 'Truth League', 'league', 'club', 'domestic_league', 1, true) "
                    "RETURNING id", (LEAGUE,))
        comp = cur.fetchone()[0]  # type: ignore[index]
        cur.execute("INSERT INTO core.competition_seasons (competition_id, season, is_current) VALUES (%s, %s, true) "
                    "RETURNING id", (comp, SEASON))
        season = cur.fetchone()[0]  # type: ignore[index]
        ids = []
        for pid, name in ((TEAM_A, "Truth A"), (TEAM_B, "Truth B")):
            cur.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (%s, %s) RETURNING id", (pid, name))
            ids.append(cur.fetchone()[0])  # type: ignore[index]
        rows = [(990001, NOW - timedelta(days=2), "FT", "finished"),
                (990002, NOW - timedelta(days=1), "Canc", "scheduled"),   # the spelling defect, as it was stored
                (990003, NOW + timedelta(days=1), "NS", "scheduled"),
                (990004, NOW + timedelta(days=2), "NS", "scheduled")]     # the provider no longer lists it
        fixture_ids = []
        for pid, ko, short, group in rows:
            cur.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, "
                        "away_team_id, kickoff_at, status_short, status_group, source_payload_hash, "
                        "source_fetched_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
                        (pid, season, ids[0], ids[1], ko, short, group, seed.payload_hash,
                         NOW - timedelta(hours=1)))
            fixture_ids.append(cur.fetchone()[0])  # type: ignore[index]
        cur.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away, ft_goals_home, "
                    "ft_goals_away) VALUES (%s, 2, 1, 2, 1)", (fixture_ids[0],))
        cur.execute("INSERT INTO core.standings (competition_season_id, team_id, snapshot_at, rank, points, played, "
                    "wins, draws, losses, goals_for, goals_against, \"group\") VALUES (%s,%s,%s,1,0,0,0,0,0,0,0,"
                    "'Truth League')", (season, ids[0], NOW - timedelta(days=3)))
    yield {"competition": comp, "season": season}
    with psycopg.connect(migrated_database, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM audit.truth_runs WHERE ingestion_run_id IN "
                    "(SELECT id FROM raw.ingestion_runs WHERE job_type = 'truth_audit')")
        cur.execute("DELETE FROM raw.ingestion_runs WHERE job_type = 'truth_audit'")
        cur.execute("DELETE FROM core.standings WHERE competition_season_id = %s", (season,))
        cur.execute("DELETE FROM core.fixture_results WHERE fixture_id = ANY(%s)", (fixture_ids,))
        cur.execute("DELETE FROM core.fixtures WHERE competition_season_id = %s", (season,))
        cur.execute("DELETE FROM core.teams WHERE provider_team_id IN (%s, %s)", (TEAM_A, TEAM_B))
        cur.execute("DELETE FROM core.competition_seasons WHERE id = %s", (season,))
        cur.execute("DELETE FROM core.competitions WHERE id = %s", (comp,))


async def test_the_audit_finds_what_disagrees_and_writes_it_down(migrated_database: str, truth_league: dict[str, int],
                                                                 tmp_path: Path) -> None:
    client = FakeClient()
    with psycopg.connect(migrated_database, autocommit=True) as conn:
        result = await run_audit(conn, client, at=NOW, seed=0.5, size=SampleSize(players=0, coaches=0, squads=0),
                                 out_root=tmp_path, skip=frozenset({"identities"}))
        findings = conn.execute("SELECT dataset, entity, field, kind, severity FROM audit.truth_findings "
                                "WHERE run_id = %s", (result.run_id,)).fetchall()
        status, requests, summary = conn.execute("SELECT status, requests, summary FROM audit.truth_runs "
                                                 "WHERE id = %s", (result.run_id,)).fetchone()  # type: ignore[misc]
    assert requests == len(client.calls) and status == "completed"
    assert (LEAGUE, SEASON) in [tuple(s) for s in result.sample.current_seasons]

    def has(dataset: str, entity_part: str, field: str, kind: str) -> bool:
        return any(d == dataset and entity_part in e and f == field and k == kind for d, e, f, k, _ in findings)

    assert has("fixtures", "990005", "fixture", "missing_in_db"), "the provider lists a fixture we lack"
    assert has("fixtures", "990004", "fixture", "missing_in_api"), "we hold a fixture the provider dropped"
    assert has("fixtures", "990002", "status_group", "inconsistent"), "Canc stored as scheduled"
    assert has("standings", "Truth League", "played", "stale"), "our table is behind the provider's"
    assert not any(d == "results" and "990001" in e for d, e, *_ in findings), "the 2-1 agrees"
    assert {row["dataset"] for row in summary["matrix"]} >= {"fixtures", "results", "standings"}
    report = (result.folder / "REPORT.md").read_text()  # type: ignore[operator]
    assert "| Dataset | API | DB | Difference | Freshness | Model safe? |" in report


def test_internal_checks_freshness_and_gate_need_no_provider(migrated_database: str,
                                                             truth_league: dict[str, int]) -> None:
    with psycopg.connect(migrated_database) as conn:
        conn.read_only = True
        tallies = run_internal(conn, at=NOW)
        spelled = [f for f in tallies["fixtures"].findings if f.field == "status_short" and "990002" in f.entity]
        assert spelled, "a mixed-case status is found without asking anyone"
        fresh = {f.dataset: f for f in measure(conn, at=NOW)}
        assert {"fixtures", "results", "standings", "odds_prematch", "elo"} <= set(fresh)
        assert fresh["standings"].counts["STALE"] >= 1, "a table older than the last match"
        summary, gates = evaluate(conn, at=NOW, horizon_hours=72)
        mine = [g for g in gates if g.provider_fixture_id == 990003]
        assert mine and not mine[0].passes("market_baseline")[0], "never priced: no pick"
        assert set(summary.by_model) == set(MODEL_NEEDS)


async def test_the_admin_console_reads_the_audit_back(migrated_database: str, truth_league: dict[str, int],
                                                     tmp_path: Path) -> None:
    from fastapi.testclient import TestClient

    from fbi.api.services import truth as truth_service
    from fbi.core.config import reset_cache
    from tests.integration.signed_in import SAME_SITE, admin_app

    with psycopg.connect(migrated_database, autocommit=True) as conn:
        result = await run_audit(conn, FakeClient(), at=NOW, seed=0.5, size=SampleSize(players=0, coaches=0,
                                                                                         squads=0),
                                 out_root=tmp_path, skip=frozenset({"identities"}))
    truth_service._cache.clear()
    mp = pytest.MonkeyPatch()
    mp.setenv("FBI_DATABASE_URL", migrated_database.replace("postgresql://", "postgresql+psycopg://"))
    reset_cache()
    try:
        _read_back(TestClient(admin_app(), headers=SAME_SITE), result.run_id)
    finally:
        mp.undo()
        reset_cache()
        truth_service._cache.clear()


def _read_back(client: Any, run_id: int) -> None:
    latest = client.get("/api/v1/admin/truth/latest").json()
    assert latest["status"] == "ok" and latest["data"]["run"]["id"] == run_id
    assert any(r["dataset"] == "fixtures" for r in latest["data"]["matrix"])
    page = client.get(f"/api/v1/admin/truth/runs/{run_id}/findings",
                      params={"dataset": "fixtures", "limit": 5}).json()
    assert page["status"] == "ok" and page["meta"]["total"] >= 3 and len(page["data"]) <= 5
    assert page["data"][0]["severity"] in ("critical", "high"), "worst first"
    assert client.get("/api/v1/admin/truth/runs").json()["data"][0]["id"] == run_id
    fresh = client.get("/api/v1/admin/data/freshness").json()
    assert fresh["status"] == "ok" and {d["dataset"] for d in fresh["data"]["datasets"]} >= {"standings", "results"}
    register = client.get("/api/v1/admin/data/datasets").json()
    rows = {r["dataset"]: r for r in register["data"]["rows"]}
    assert register["status"] == "ok" and len(rows) == 14
    assert all(r["klass"] in ("FRESH", "STALE", "INCOMPLETE", "INVALID", "UNKNOWN") for r in rows.values())
    assert rows["teams"]["model"] == "NOT_USED" and rows["odds_prematch"]["role"] == "REQUIRED"
    assert rows["fixtures"]["model"] in ("MODEL_READY", "NOT_MODEL_READY") and rows["fixtures"]["model_reason"]
    assert set(rows["fixtures"]["states"]) == {"VALID", "STALE", "NOT_REQUESTED", "PROVIDER_HAS_NO_DATA",
                                               "REQUEST_FAILED", "NORMALIZATION_FAILED"}, "the six answers, per dataset"
    tables = client.get("/api/v1/admin/data/standings").json()
    mine = [r for r in tables["data"] if r["provider_league_id"] == LEAGUE]
    assert mine and mine[0]["status"] in ("STALE", "FRESH", "UNAVAILABLE", "UNKNOWN") and mine[0]["reason"]
    gate = client.get("/api/v1/admin/data/gate").json()
    assert gate["status"] in ("ok", "empty") and {m["model"] for m in gate["data"]["models"]} == set(MODEL_NEEDS)
    assert client.get("/api/v1/admin/data/repairs").json()["status"] in ("ok", "empty")
