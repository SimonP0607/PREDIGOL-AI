"""The product API answers honestly: real rows, or a status and a reason.

Every endpoint is exercised over HTTP (FastAPI TestClient) against the
migrated test database, with a small, fully known dataset:

    F1  Man Utd v Liverpool   3 days ago     FT 2-1, lineage, near-close row
    F2  Alpha v Beta          yesterday      still 'NS'  -> awaiting result
    F3  Liverpool v Alpha     in 5 hours     odds at T-1430 and T-715, 2 bookmakers
    F4  Beta v Man Utd        in 3 days      postponed
    F5  Man Utd v Beta        10 days ago    FT 0-0, no lineage

Nothing is asserted about data the dataset does not contain: where there is
nothing, the test checks that the API says so - with a reason - instead of
answering 0.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from fbi.core.clock import FrozenClock, SystemClock, set_clock
from fbi.core.config import reset_cache
from tests.integration.conftest import Seed
from tests.integration.helpers import scalar

NOW = datetime(2026, 9, 24, 12, 0, tzinfo=UTC)
SECRET = "k3y-that-must-never-appear-in-a-response"


@pytest.fixture(scope="module")
def dataset(migrated_database: str, seed: Seed) -> Iterator[dict[str, int]]:
    ids: dict[str, int] = {}
    with psycopg.connect(migrated_database, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("UPDATE core.competitions SET is_tracked = true WHERE id = %s", (seed.competition_id,))
        cur.execute("UPDATE core.competition_seasons SET is_current = true WHERE id = %s", (seed.season_id,))
        cur.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (9101,'Alpha FC') RETURNING id")
        ids["alpha"] = scalar(cur)
        cur.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (9102,'Beta FC') RETURNING id")
        ids["beta"] = scalar(cur)
        cur.execute("INSERT INTO market.bookmakers (provider_bookmaker_id, name) VALUES (4,'Pinnacle') RETURNING id")
        ids["pinnacle"] = scalar(cur)
        cur.execute("INSERT INTO core.venues (provider_venue_id, name, city) VALUES (9556,'Old Trafford','Manchester') RETURNING id")
        ids["venue"] = scalar(cur)
        cur.execute(
            "INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, params, fetched_at, http_status, file_path, bytes) "
            "VALUES ('api-fx-payload', %s, '/fixtures', '{\"date\": \"2026-09-21\"}'::jsonb, %s, 200, 'x', 1)",
            (seed.run_id, NOW - timedelta(days=3) + timedelta(hours=8)),
        )
        mu, liv = seed.home_team_id, seed.away_team_id

        def fixture(pid: int, home: int, away: int, ko: datetime, status: str, group: str, **extra: Any) -> int:
            cur.execute(
                "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
                "kickoff_at, status_short, status_group, round, venue_id, source_payload_hash, source_fetched_at) "
                "VALUES (%s,%s,%s,%s,%s,%s,%s,'Regular Season - 5',%s,%s,%s) RETURNING id",
                (pid, seed.season_id, home, away, ko, status, group, extra.get("venue"),
                 extra.get("payload"), extra.get("fetched")),
            )
            return int(scalar(cur))

        ids["f1"] = fixture(95001, mu, liv, NOW - timedelta(days=3), "FT", "finished", venue=ids["venue"],
                            payload="api-fx-payload", fetched=NOW - timedelta(days=3) + timedelta(hours=8))
        ids["f2"] = fixture(95002, ids["alpha"], ids["beta"], NOW - timedelta(days=1), "NS", "scheduled")
        ids["f3"] = fixture(95003, liv, ids["alpha"], NOW + timedelta(hours=5), "NS", "scheduled")
        ids["f4"] = fixture(95004, ids["beta"], mu, NOW + timedelta(days=3), "PST", "postponed")
        ids["f5"] = fixture(95005, mu, ids["beta"], NOW - timedelta(days=10), "FT", "finished")
        cur.execute(
            "INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away, ht_goals_home, ht_goals_away, "
            "source_payload_hash, source_fetched_at) VALUES (%s,2,1,1,0,'api-fx-payload',%s)",
            (ids["f1"], NOW - timedelta(days=3) + timedelta(hours=8)),
        )
        cur.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away) VALUES (%s,0,0)", (ids["f5"],))
        kickoff3 = NOW + timedelta(hours=5)
        for mtk in (1430, 715):
            captured = kickoff3 - timedelta(minutes=mtk)
            for bm, prices in ((seed.bookmaker_id, (2.10, 3.40, 3.60)), (ids["pinnacle"], (2.05, 3.55, 3.75))):
                drift = 0.05 if mtk == 715 else 0.0
                for sel, price in zip(("Home", "Draw", "Away"), prices, strict=True):
                    cur.execute(
                        "INSERT INTO market.odds_snapshots (fixture_id, bookmaker_id, market_key, selection, line, "
                        "odds_decimal, captured_at, minutes_to_ko, source, payload_hash) "
                        "VALUES (%s,%s,'1X2',%s,0,%s,%s,%s,'prematch',%s)",
                        (ids["f3"], bm, sel, round(price - drift, 3), captured, mtk, seed.payload_hash),
                    )
        cur.execute(
            "INSERT INTO market.near_close_snapshots (fixture_id, bookmaker_id, market_key, selection, line, "
            "odds_decimal, captured_at, minutes_to_ko, source) VALUES (%s,%s,'1X2','Home',0,1.95,%s,10,'live')",
            (ids["f1"], seed.bookmaker_id, NOW - timedelta(days=3) - timedelta(minutes=10)),
        )
    yield ids
    with psycopg.connect(migrated_database, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM core.fixtures WHERE provider_fixture_id BETWEEN 95001 AND 95005")
        cur.execute("DELETE FROM raw.ingestion_payloads WHERE hash = 'api-fx-payload'")
        cur.execute("DELETE FROM core.teams WHERE provider_team_id IN (9101, 9102)")
        cur.execute("DELETE FROM core.venues WHERE provider_venue_id = 9556")
        cur.execute("DELETE FROM market.bookmakers WHERE provider_bookmaker_id = 4")
        cur.execute("UPDATE core.competitions SET is_tracked = false WHERE id = %s", (seed.competition_id,))


@pytest.fixture(scope="module")
def client(dataset: dict[str, int], migrated_database: str) -> Iterator[TestClient]:
    mp = pytest.MonkeyPatch()
    mp.setenv("FBI_DATABASE_URL", migrated_database.replace("postgresql://", "postgresql+psycopg://"))
    mp.setenv("FBI_APIFOOTBALL_PLAN", "free")
    mp.setenv("FBI_APIFOOTBALL_DAILY_BUDGET", "60")
    mp.setenv("FBI_APIFOOTBALL_KEY", SECRET)
    reset_cache()
    set_clock(FrozenClock(NOW))
    from fbi.api.app import create_app

    with TestClient(create_app()) as c:
        yield c
    set_clock(SystemClock())
    mp.undo()
    reset_cache()


def get(client: TestClient, path: str, status: int = 200) -> dict[str, Any]:
    r = client.get(path)
    assert r.status_code == status, f"{path} -> {r.status_code}: {r.text[:400]}"
    body: dict[str, Any] = r.json()
    assert SECRET not in r.text, f"{path} leaked the provider key"
    assert "fbi_local_dev" not in r.text, f"{path} leaked the database password"
    return body


# ---------------------------------------------------------------------------
# Matches and Match Center
# ---------------------------------------------------------------------------

def test_the_match_list_carries_scores_and_flags_rows_that_are_out_of_date(
    client: TestClient, dataset: dict[str, int]
) -> None:
    body = get(client, "/api/v1/matches?date_from=2026-09-14&date_to=2026-09-28&order=asc")
    assert body["status"] == "ok"
    ours = {m["provider_fixture_id"]: m for m in body["data"] if 95001 <= m["provider_fixture_id"] <= 95005}
    assert set(ours) == {95001, 95002, 95003, 95004, 95005}
    assert ours[95001]["score"]["home"] == 2 and ours[95001]["score"]["outcome_1x2"] == "Home"
    assert ours[95002]["score"] is None and ours[95002]["awaiting_result"] is True, (
        "a fixture that kicked off yesterday and still says NS is out of date, and says so")
    assert ours[95003]["awaiting_result"] is False
    assert ours[95003]["odds"] == {**ours[95003]["odds"], "snapshots": 12, "bookmakers": 2, "markets": 1}
    assert ours[95004]["status_group"] == "postponed"
    kickoffs = [m["kickoff_at"] for m in body["data"]]
    assert kickoffs == sorted(kickoffs), "order=asc"
    assert body["meta"]["total"] >= 5 and body["meta"]["count"] == len(body["data"])


def test_filters_narrow_the_list_and_an_empty_answer_says_why(client: TestClient, dataset: dict[str, int]) -> None:
    postponed = get(client, "/api/v1/matches?status=postponed")
    assert [m["provider_fixture_id"] for m in postponed["data"]] == [95004]
    alpha = get(client, f"/api/v1/matches?team_id={dataset['alpha']}")
    assert {m["provider_fixture_id"] for m in alpha["data"]} == {95002, 95003}
    nothing = get(client, "/api/v1/matches?date_from=2030-01-01&date_to=2030-01-02")
    assert nothing["status"] == "empty" and nothing["data"] == []
    assert nothing["reason"] == "No fixtures match these filters."


def test_pagination_is_reported(client: TestClient) -> None:
    page = get(client, "/api/v1/matches?limit=2&offset=1")
    assert page["meta"]["limit"] == 2 and page["meta"]["offset"] == 1 and len(page["data"]) <= 2


def test_the_match_center_traces_the_score_to_its_payload(client: TestClient, dataset: dict[str, int]) -> None:
    body = get(client, f"/api/v1/matches/{dataset['f1']}")
    d = body["data"]
    assert d["venue"]["name"] == "Old Trafford"
    assert d["lineage"]["recorded"] is True
    assert d["lineage"]["source_endpoint"] == "/fixtures"
    assert d["lineage"]["source_params"] == {"date": "2026-09-21"}
    assert d["match"]["score"]["source_payload_hash"] == "api-fx-payload"
    assert d["match"]["score"]["ht_home"] == 1


def test_a_row_without_lineage_says_it_was_not_recorded(client: TestClient, dataset: dict[str, int]) -> None:
    d = get(client, f"/api/v1/matches/{dataset['f5']}")["data"]
    assert d["lineage"]["recorded"] is False
    assert "before lineage was recorded" in d["lineage"]["note"]


def test_markets_say_there_is_no_data_instead_of_showing_zero(client: TestClient, dataset: dict[str, int]) -> None:
    d = get(client, f"/api/v1/matches/{dataset['f2']}")["data"]
    assert d["markets"] == {"status": "empty", "data": [], "reason": "No captured market data yet."}
    assert d["predictions"]["status"] == "not_available" and d["predictions"]["reason"]


def test_the_board_shows_the_latest_price_per_bookmaker_with_raw_implied_probability(
    client: TestClient, dataset: dict[str, int]
) -> None:
    d = get(client, f"/api/v1/matches/{dataset['f3']}")["data"]
    board = d["markets"]["data"]
    assert d["markets"]["status"] == "ok" and len(board) == 6, "2 bookmakers x 3 selections, latest only"
    assert all(q["minutes_to_ko"] == 715 for q in board), "the newer capture wins"
    home_b365 = next(q for q in board if q["bookmaker"] == "Bet365" and q["selection"] == "Home")
    assert float(home_b365["odds_decimal"]) == pytest.approx(2.05)
    assert float(home_b365["implied_probability"]) == pytest.approx(1 / 2.05, abs=1e-6)


def test_the_timeline_separates_captured_missed_unreachable_and_pending(
    client: TestClient, dataset: dict[str, int]
) -> None:
    events = {e["key"]: e for e in get(client, f"/api/v1/matches/{dataset['f3']}")["data"]["timeline"]}
    assert events["odds_1440"]["state"] == "done" and "T-1430" in events["odds_1440"]["detail"]
    assert events["odds_720"]["state"] == "done"
    assert events["odds_4320"]["state"] == "skipped" and "free plan" in events["odds_4320"]["detail"], (
        "a window the plan can never reach is not a missed window")
    assert events["odds_360"]["state"] == "skipped" and "without a capture" in events["odds_360"]["detail"]
    assert events["odds_180"]["state"] == "pending"
    assert events["result"]["state"] == "pending"
    past = {e["key"]: e for e in get(client, f"/api/v1/matches/{dataset['f2']}")["data"]["timeline"]}
    assert past["result"]["state"] == "failed", "kicked off yesterday, no result: that is a failure to show"


def test_an_unknown_match_is_a_404_in_the_error_envelope(client: TestClient) -> None:
    body = get(client, "/api/v1/matches/999999999", status=404)
    assert body["status"] == "error" and body["error"]["code"] == "not_found" and body["request_id"]


def test_invalid_parameters_are_rejected_without_echoing_them(client: TestClient) -> None:
    body = get(client, "/api/v1/matches?limit=0", status=422)
    assert body["error"]["code"] == "invalid" and "limit" in body["error"]["message"]
    probe = "<script>alert(1)</script>"
    r = client.get("/api/v1/matches", params={"status": probe})
    assert r.status_code == 422 and probe not in r.text


# ---------------------------------------------------------------------------
# Odds
# ---------------------------------------------------------------------------

def test_the_odds_list_contains_only_fixtures_with_prices(client: TestClient, dataset: dict[str, int]) -> None:
    body = get(client, "/api/v1/odds")
    assert [m["provider_fixture_id"] for m in body["data"]] == [95003]


def test_fixture_odds_give_series_near_close_and_an_honest_consensus(
    client: TestClient, dataset: dict[str, int]
) -> None:
    d = get(client, f"/api/v1/odds/fixtures/{dataset['f3']}")["data"]
    assert len(d["series"]["data"]) == 6
    pts = d["series"]["data"][0]["points"]
    assert [p["minutes_to_ko"] for p in pts] == [1430, 715], "oldest first"
    assert d["near_close"]["status"] == "empty" and "not a closing line" in d["near_close"]["reason"]
    assert d["consensus"]["status"] == "not_available"
    past = get(client, f"/api/v1/odds/fixtures/{dataset['f1']}")["data"]
    assert past["near_close"]["status"] == "ok"
    assert past["near_close"]["data"][0]["is_validated_close"] is False
    assert d["historical"]["status"] == "empty" and d["historical"]["reason"], "second source kept apart, and says so"


def test_odds_intelligence_needs_the_historical_source_and_says_so(client: TestClient) -> None:
    body = get(client, "/api/v1/odds/intelligence")
    assert body["status"] == "not_available" and body["reason"]
    d = body["data"]
    assert d["margins"]["status"] == "not_available" and d["movement"]["status"] == "not_available"
    assert d["live"]["status"] == "ok" and d["live"]["data"]["snapshots"] > 0, "our own captures are counted apart"
    assert "not captured by this platform" in d["note"]


def test_a_market_filter_narrows_the_board(client: TestClient, dataset: dict[str, int]) -> None:
    d = get(client, f"/api/v1/odds/fixtures/{dataset['f3']}?market=DC")["data"]
    assert d["board"]["status"] == "empty"


# ---------------------------------------------------------------------------
# Catalogue
# ---------------------------------------------------------------------------

def test_competitions_list_and_detail(client: TestClient, seed: Seed) -> None:
    body = get(client, "/api/v1/competitions?tracked=true")
    pl = next(c for c in body["data"] if c["id"] == seed.competition_id)
    assert pl["is_tracked"] is True and pl["fixtures"] >= 5 and pl["current_season"] == 2025
    detail = get(client, f"/api/v1/competitions/{seed.competition_id}")["data"]
    season = detail["seasons"][0]
    assert season["season"] == 2025 and season["with_results"] >= 2
    assert {"Alpha FC", "Beta FC", "Liverpool", "Manchester United"} <= {t["name"] for t in detail["teams"]}


def test_a_team_record_counts_recorded_results_only(client: TestClient, seed: Seed, dataset: dict[str, int]) -> None:
    mu = get(client, f"/api/v1/teams/{seed.home_team_id}")["data"]
    assert mu["record"]["status"] == "ok"
    assert mu["record"]["data"]["won"] >= 1 and mu["record"]["data"]["drawn"] >= 1
    alpha = get(client, f"/api/v1/teams/{dataset['alpha']}")["data"]
    assert alpha["record"]["status"] == "insufficient_data", (
        "Alpha's only past fixture has no score; it is not a draw, it is unknown")
    assert alpha["record"]["data"] is None
    assert [m["provider_fixture_id"] for m in alpha["upcoming"]] == [95003]


def test_search_finds_teams_and_fixtures(client: TestClient) -> None:
    body = get(client, "/api/v1/search?q=Alpha")
    kinds = {h["type"] for h in body["data"]}
    assert {"team", "fixture"} <= kinds


# ---------------------------------------------------------------------------
# Overview, quality, analytics
# ---------------------------------------------------------------------------

def test_the_overview_reports_real_counts_and_withholds_what_does_not_exist(client: TestClient) -> None:
    d = get(client, "/api/v1/overview")["data"]
    assert d["database"]["odds_snapshots"] >= 12 and d["database"]["fixtures_with_result"] >= 2
    assert d["provider"]["plan"] == "free" and d["provider"]["daily_budget"] == 60
    assert d["fixtures"]["awaiting_result"] >= 1
    assert d["fixtures"]["next_fixture"]["provider_fixture_id"] == 95003
    assert d["picks"]["status"] == "not_available" and d["picks"]["data"] is None
    assert d["performance"]["status"] == "insufficient_data" and "Insufficient sample" in d["performance"]["reason"]


def test_quality_explains_every_null_it_reports(client: TestClient) -> None:
    body = get(client, "/api/v1/health/quality")
    snap, why = body["data"]["snapshot"], body["data"]["explanations"]
    for field in ("fixture_odds_coverage", "bookmaker_coverage", "market_coverage", "window_coverage_24h"):
        if snap[field] is None:
            assert field in why, f"{field} is null with no explanation for the tooltip"


def test_issues_are_derived_from_the_data(client: TestClient) -> None:
    keys = {i["key"] for i in get(client, "/api/v1/data-quality/issues")["data"]}
    assert "awaiting_result" in keys
    assert "results_without_lineage" in keys


def test_models_list_the_registry_and_the_baseline_says_it_has_no_odds(client: TestClient) -> None:
    d = get(client, "/api/v1/models")["data"]
    assert d["market_baseline"]["status"] == "insufficient_data"
    assert d["models"]["status"] == "ok" and d["models"]["data"][0]["latest_backtest"] is None


def test_picks_and_performance_do_not_pretend(client: TestClient) -> None:
    picks = get(client, "/api/v1/picks")
    assert picks["status"] == "not_available" and picks["data"]["picks"]["data"] == []
    perf = get(client, "/api/v1/performance")
    assert perf["status"] == "insufficient_data"
    assert perf["data"]["roi_pct"] is None and perf["data"]["profit_units"] is None


def test_health_reports_components_and_the_unversioned_alias_still_works(client: TestClient) -> None:
    v1 = get(client, "/api/v1/health", status=client.get("/api/v1/health").status_code)
    assert set(v1) >= {"status", "app", "database", "worker", "football_provider"}
    legacy = client.get("/health")
    assert legacy.status_code in (200, 503) and legacy.json()["database"]["status"] == "ok"


# ---------------------------------------------------------------------------
# Transport and safety
# ---------------------------------------------------------------------------

def test_every_response_carries_a_request_id_and_safe_headers(client: TestClient) -> None:
    r = client.get("/api/v1/competitions", headers={"x-request-id": "abc123"})
    assert r.headers["x-request-id"] == "abc123"
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["cache-control"] == "no-store"


def test_cors_allows_the_local_frontend_and_nobody_else(client: TestClient) -> None:
    ok = client.options("/api/v1/overview", headers={
        "origin": "http://localhost:5173", "access-control-request-method": "GET"})
    assert ok.headers.get("access-control-allow-origin") == "http://localhost:5173"
    evil = client.options("/api/v1/overview", headers={
        "origin": "https://evil.example", "access-control-request-method": "GET"})
    assert "access-control-allow-origin" not in evil.headers


def test_the_api_cannot_write_even_if_code_tried(client: TestClient) -> None:
    from fbi.api.deps import read_only_connection

    with read_only_connection() as conn, pytest.raises(psycopg.errors.ReadOnlySqlTransaction):
        conn.execute("INSERT INTO core.venues (name) VALUES ('should never exist')")


def test_an_unexpected_error_is_a_json_500_that_the_browser_can_read(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Without this the browser sees a CORS failure instead of the 500."""
    from fbi.api.services import analytics

    def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("database says: password=fbi_local_dev")

    monkeypatch.setattr(analytics, "performance", boom)
    r = client.get("/api/v1/performance", headers={"origin": "http://localhost:5173"})
    assert r.status_code == 500
    assert r.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert r.json()["error"]["code"] == "internal" and "password" not in r.text


def test_rankings_need_an_elo_history_and_say_so(client: TestClient) -> None:
    body = get(client, "/api/v1/rankings")
    assert body["status"] == "not_available" and "build_features" in body["reason"]
    assert client.get("/api/v1/rankings?limit=0").status_code == 422
