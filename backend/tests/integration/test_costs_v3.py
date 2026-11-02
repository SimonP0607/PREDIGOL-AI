"""The cost panel of Phase 0 (Plan Maestro IA, sections 26, 28 and 29) on the built month of the budget tests (August 2032, today the 15th at
noon in Bogotá): the three envelopes against their own budgets, the savings read from the ledger, what the open batches have reserved, the reuse
counted by the cycles, the switches and the spent-limit state - and a panel that fails leaves the rest of the overview standing.

No network, no key: the ledger is written by hand. One transaction, rolled back."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb

from fbi.ai import costs_v3
from fbi.ai.config import AiSettings
from fbi.ai.pricing import token_cost
from fbi.ai.providers.base import LlmUsage
from fbi.ai.usage import UsageLedger, shared
from fbi.api.services import ai_layer, ai_v2

from .test_budget_v3 import NOW, SONNET, limit_hit, month, settings, spend

D = Decimal


def tokens(db: psycopg.Connection[Any], *, usage: LlmUsage, batch_id: int | None = None, custom_id: str | None = None,
           workspace: str = "PREDIGOL") -> int:
    """One priced call with its tokens, the way the ledger writes it: the cost is the verified price of exactly these tokens."""
    cost = token_cost("anthropic", SONNET.model, input_tokens=usage.input_tokens, output_tokens=usage.output_tokens,
                      cached_tokens=usage.cached_tokens, cache_write_5m_tokens=usage.cache_write_5m_tokens,
                      cache_write_1h_tokens=usage.cache_write_1h_tokens, batch=batch_id is not None, at=NOW)
    return UsageLedger(shared(db)).record(
        at=NOW - timedelta(hours=1), purpose="pick_review", tier="analysis", provider="anthropic", model=SONNET.model,
        usage=usage, cost=cost, status="ok", workspace=workspace, batch_id=batch_id, custom_id=custom_id)


def panel(db: psycopg.Connection[Any], **kw: Any) -> dict[str, Any]:
    return costs_v3.envelopes(db, at=NOW, settings=settings(**kw))


def test_production_the_lab_and_exa_are_three_envelopes_with_their_own_budget(db: psycopg.Connection[Any]) -> None:
    month(db, unit="0.50")  # 14 closed days x US$5.00 and US$2.00 today = US$72.00 of production
    spend(db, NOW - timedelta(hours=3), "4.00", workspace="PREDIGOL-LAB")
    spend(db, NOW - timedelta(hours=1), "0.30", search=True)
    p = panel(db)
    prod, lab, exa, claude = p["production"], p["lab"], p["exa"], p["claude"]
    assert p["month"] == "2032-08-01" and p["days_left"] == 17 and p["budget_version"] == "v3"
    assert (prod["spent_usd"], prod["budget_usd"], prod["share"]) == ("72.0000", "185", round(72 / 185, 4))
    assert (prod["projected_usd"], prod["projection_share"], prod["state"]) == ("155.0000", round(155 / 185, 4), "NORMAL")
    assert (prod["reserve_usd"], prod["workspace"]) == ("10", "PREDIGOL")
    assert (lab["spent_usd"], lab["budget_usd"], lab["share"], lab["workspace"]) == ("4.0000", "55", round(4 / 55, 4), "PREDIGOL-LAB")
    assert (exa["spent_usd"], exa["budget_usd"], exa["searches"]) == ("0.3000", "35", 1)
    # Claude is production and the LAB under ONE ceiling; Exa's money is not in it
    assert (claude["spent_usd"], claude["ceiling_usd"], claude["share"]) == ("76.0000", "190", round(76 / 190, 4))
    assert claude["projected_usd"] == "159.0000" and claude["projection_share"] == round(159 / 190, 4)


def test_no_envelope_moves_another_ones_figures(db: psycopg.Connection[Any]) -> None:
    month(db, unit="0.50")
    before = panel(db)
    spend(db, NOW - timedelta(hours=1), "9.00", workspace="PREDIGOL-LAB")
    spend(db, NOW - timedelta(hours=1), "1.50", search=True)
    after = panel(db)
    assert after["production"]["spent_usd"] == before["production"]["spent_usd"] == "72.0000"
    assert after["production"]["projected_usd"] == before["production"]["projected_usd"]
    assert after["lab"]["spent_usd"] == "9.0000" and after["exa"]["spent_usd"] == "1.5000"


def test_the_savings_are_read_from_the_tokens_of_the_ledger_and_the_batch_is_priced_at_half(db: psycopg.Connection[Any]) -> None:
    month(db, unit="0.50")  # these rows carry a cost and no tokens: there is nothing to measure a saving on
    tokens(db, usage=LlmUsage(input_tokens=10_000, cached_tokens=6_000))
    tokens(db, usage=LlmUsage(input_tokens=10_000, cached_tokens=6_000), batch_id=7, custom_id="c1")
    saved = panel(db)["savings"]["month"]
    assert (saved["cache_usd"], saved["batch_usd"], saved["total_usd"]) == ("0.0171", "0.0100", "0.0271")
    assert (saved["calls"], saved["batch_calls"], saved["batch_share"]) == (2, 1, 0.5)
    assert (saved["input_tokens"], saved["cached_tokens"], saved["read_share"]) == (20_000, 12_000, 0.6)


def test_the_cache_writes_are_split_the_way_the_ledger_stores_them(db: psycopg.Connection[Any]) -> None:
    # the ledger keeps the TOTAL written in cache_write_tokens and, apart, the part written for an hour
    tokens(db, usage=LlmUsage(input_tokens=10_000, cache_write_5m_tokens=2_000, cache_write_1h_tokens=3_000))
    saved = panel(db)["savings"]["month"]
    assert saved["write_tokens"] == 5_000
    # 2,000 x 1.25 + 3,000 x 2 + 5,000 fresh = 13,500 token-prices against 10,000: US$0.0070 over the fresh price
    assert saved["cache_usd"] == "-0.0070"


def test_the_open_batches_are_reserved_and_counted(db: psycopg.Connection[Any]) -> None:
    month(db, unit="0.50")
    before = panel(db)
    row = db.execute("INSERT INTO ai.batches (batch_ref, provider, workspace, key_label, kind, status, created_at, submitted_at, "
                     "n_items) VALUES ('msgbatch_x', 'anthropic', 'PREDIGOL', 'worker-prod', 'production', 'in_progress', %s, %s, 1) "
                     "RETURNING id", (NOW - timedelta(hours=1), NOW - timedelta(hours=1))).fetchone()
    assert row is not None
    db.execute("INSERT INTO ai.batch_items (batch_id, custom_id, purpose, tier, model, input_hash, est_cost_usd, status, created_at) "
               "VALUES (%s, 'task1', 'pick_review', 'analysis', %s, 'h', 0.5, 'submitted', %s)",
               (row[0], SONNET.model, NOW - timedelta(hours=1)))
    p = panel(db)
    assert p["production"]["reserved_for_batches_usd"] == "0.5000" and p["lab"]["reserved_for_batches_usd"] == "0.0000"
    assert p["batch"]["open_items"] == 1 and p["batch"]["open_batches"] == 1
    # the reservation is part of today's expected cost, which the projection already held: it moves nothing, and it is not spent money
    assert p["production"]["projected_usd"] == before["production"]["projected_usd"] == "155.0000"
    assert p["production"]["spent_usd"] == before["production"]["spent_usd"] and p["production"]["spent_today_usd"] == "2.0000"


def test_the_reuse_is_counted_by_the_cycles_of_the_month_and_only_of_it(db: psycopg.Connection[Any]) -> None:
    def cycle(at: Any, counts: dict[str, int]) -> None:
        db.execute("INSERT INTO ai.cycles (kind, started_at, finished_at, status, mode, budget_state, counts) "
                   "VALUES ('analysis', %s, %s, 'ok', 'shadow', 'NORMAL', %s)", (at, at, Jsonb(counts)))

    cycle(NOW - timedelta(days=3), {"briefs_llm": 5, "briefs_reused": 3, "briefs_reused_material": 2, "llm_reused": 4, "reviews_batched": 6})
    cycle(NOW - timedelta(days=1), {"briefs_llm": 1, "briefs_reused": 1, "reviews_batched": 2})
    cycle(NOW - timedelta(days=40), {"briefs_llm": 99, "briefs_reused": 99})  # July
    assert panel(db)["reuse"] == {"briefs_paid": 6, "briefs_reused": 4, "briefs_reused_material": 2, "reviews_reused": 4,
                                  "reviews_batched": 8}


def test_a_spent_limit_and_the_switches_are_reported(db: psycopg.Connection[Any]) -> None:
    month(db, unit="0.50")
    assert panel(db)["production"]["limit"] == {"active": False, "until": None, "hits": 0}
    limit_hit(db, NOW - timedelta(minutes=10))
    limit = panel(db)["production"]["limit"]
    assert limit["active"] is True and limit["hits"] == 1 and limit["until"] is not None
    switches = panel(db)["switches"]
    assert switches["cache"]["on"] is True and switches["batch"]["on"] is False and switches["native_schema"]["on"] is False
    assert switches["cache_layout"]["on"] is False and switches["gates"]["batch"]["passed"] is False
    assert "waiting for" in switches["batch"]["why"]


def test_the_daily_series_has_one_line_per_day_of_the_last_two_weeks(db: psycopg.Connection[Any]) -> None:
    month(db, unit="0.50")
    spend(db, NOW - timedelta(hours=1), "1.25", workspace="PREDIGOL-LAB")
    days = panel(db)["days"]
    assert len(days) == costs_v3.SERIES_DAYS and days[-1]["day"] == "2032-08-15" and days[0]["day"] == "2032-08-02"
    assert days[-1] == {"day": "2032-08-15", "production_usd": "2.0000", "lab_usd": "1.2500", "exa_usd": "0.0000"}
    assert days[-2]["production_usd"] == "5.0000"


def test_the_overview_carries_the_panel(db: psycopg.Connection[Any]) -> None:
    month(db, unit="0.50")
    out = ai_layer.overview(db, at=NOW)
    assert out.data.envelopes["month"] == "2032-08-01" and out.data.envelopes["production"]["spent_usd"] == "72.0000"
    assert set(out.data.envelopes) >= {"production", "lab", "exa", "claude", "savings", "reuse", "batch", "switches", "days"}


def test_a_panel_that_fails_leaves_the_rest_of_the_overview_standing(db: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch) -> None:
    def broken(conn: psycopg.Connection[Any], **_: Any) -> dict[str, Any]:
        conn.execute("SELECT 1 / 0")  # a SQL error: it aborts the transaction unless a savepoint contains it
        return {}

    monkeypatch.setattr(costs_v3, "envelopes", broken)
    assert ai_v2.envelopes(db, at=NOW, settings=AiSettings()) == {}
    assert db.execute("SELECT 1").fetchone() == (1,), "the connection is still usable"
    out = ai_layer.overview(db, at=NOW)
    assert out.data.envelopes == {} and out.data.budget["state"] in {"NORMAL", "AJUSTE", "REDUCED", "CHEAP_ONLY", "EXHAUSTED"}
