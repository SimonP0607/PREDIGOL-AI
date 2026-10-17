"""The pre-purchase probe reads the answer from the payload: detail blocks present
or not, coverage stored with the provider's names, every request counted."""

from __future__ import annotations

import json
from pathlib import Path

import httpx
import psycopg

from fbi.core.config.providers import ApiFootballSettings
from fbi.ingestion.payload_store import PayloadStore
from fbi.migration.fake_api import LEAGUES, FakeApi, fixtures_of
from fbi.migration.probe import run_probe
from fbi.providers.api_football.client import ApiFootballClient
from fbi.providers.api_football.provider import ApiFootballProvider
from fbi.providers.quota import PersistentDailyQuota
from fbi.providers.ratelimit import TokenBucket
from tests.integration.conftest import Seed


def _provider(dsn: str, root: Path, handler: object) -> tuple[ApiFootballProvider, PersistentDailyQuota]:
    async def no_sleep(_s: float) -> None:
        return None

    quota = PersistentDailyQuota(budget=100, connect=lambda: psycopg.connect(dsn, autocommit=True),
                                 provider="probe-test")
    settings = ApiFootballSettings(key="probe-test-not-a-key", plan="free", daily_budget=100, max_retries=0)
    client = ApiFootballClient(settings, PayloadStore(root), transport=httpx.MockTransport(handler),  # type: ignore[arg-type]
                               rate_limiter=TokenBucket(10_000, sleep=no_sleep), quota=quota)
    return ApiFootballProvider(client), quota


def _ids() -> list[int]:
    return [int(f["fixture"]["id"]) for f in fixtures_of(9901, 2024)[:2]]


async def test_blocks_present_means_batching_available(db: psycopg.Connection, seed: Seed, tmp_path: Path,
                                                       migrated_database: str) -> None:
    api = FakeApi()
    provider, quota = _provider(migrated_database, tmp_path, api.handle)
    rep = await run_probe(db, provider, _ids(), configured={9901: "Dry-run League A", 9902: "Totally Other Cup"})
    await provider.aclose()
    assert rep.fixtures_returned == 2 and rep.ids_batching_available
    assert rep.blocks_present == {"events": 2, "lineups": 2, "statistics": 2, "players": 2}
    assert rep.detail_kb_per_fixture is not None and rep.detail_kb_per_fixture > 0
    assert rep.coverage_rows == len(LEAGUES) * 2 and rep.requests == 2 and quota.spent == 2
    assert rep.name_mismatches == [(9902, "Totally Other Cup", "Dry-run League B (Nowhere)")]
    with db.cursor() as cur:
        cur.execute("SELECT count(*) FROM raw.ingestion_payloads WHERE run_id = %s", (rep.run_id,))
        assert cur.fetchone() == (2,), "both payloads are indexed with the probe's run"


async def test_missing_blocks_mean_no_batching(db: psycopg.Connection, seed: Seed, tmp_path: Path,
                                              migrated_database: str) -> None:
    api = FakeApi()

    def stripped(request: httpx.Request) -> httpx.Response:
        res = api.handle(request)
        if request.url.path.endswith("/fixtures") and "ids" in request.url.params:
            body = json.loads(res.content)
            for fx in body["response"]:
                for block in ("events", "lineups", "statistics", "players"):
                    fx.pop(block, None)
            return httpx.Response(200, json=body)
        return res

    provider, _ = _provider(migrated_database, tmp_path, stripped)
    rep = await run_probe(db, provider, _ids(), configured={})
    await provider.aclose()
    assert rep.fixtures_returned == 2 and not rep.ids_batching_available
    assert rep.blocks_present == {"events": 0, "lineups": 0, "statistics": 0, "players": 0}


async def test_a_plan_refusal_is_an_answer_and_coverage_still_comes(db: psycopg.Connection, seed: Seed,
                                                                    tmp_path: Path, migrated_database: str) -> None:
    """The Free plan answers ids= with errors.plan (observed 25 Sep 2026): record it, ask /leagues anyway."""
    api = FakeApi()
    words = "Free plans do not have access to the Ids parameter."

    def refusing(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/fixtures") and "ids" in request.url.params:
            return httpx.Response(200, json={"get": "fixtures", "parameters": {"ids": request.url.params["ids"]},
                                             "errors": {"plan": words}, "results": 0, "response": []})
        return api.handle(request)

    provider, quota = _provider(migrated_database, tmp_path, refusing)
    spent_before = quota.spent  # the quota row is shared by every test of the day
    rep = await run_probe(db, provider, _ids(), configured={9901: "Dry-run League A"})
    await provider.aclose()
    assert rep.ids_verdict == "refused_by_plan" and not rep.ids_batching_available
    assert rep.ids_refusal is not None and words in rep.ids_refusal
    assert rep.fixtures_returned == 0 and rep.detail_kb_per_fixture is None
    assert rep.coverage_rows == len(LEAGUES) * 2, "the coverage question is still answered"
    assert rep.requests == 2 and quota.spent - spent_before == 2, "the refused request was issued, so it counts"
    with db.cursor() as cur:
        cur.execute("SELECT status, notes FROM raw.ingestion_runs WHERE id = %s", (rep.run_id,))
        status, notes = cur.fetchone()  # type: ignore[misc]
    assert status == "completed" and words in notes
