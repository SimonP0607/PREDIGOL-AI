"""IA-137 (AD-K05) on a database: every dollar of the month given to a capability, read from both ledgers by ``fbi.ai.envelopes_readers``,
adds up to the ledgers' own sums; an input paid twice is counted once as a repeat; the cost panel carries it under ``attribution``.

No network, no key: the ledger is written by hand. One transaction, rolled back."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest

from fbi.ai import capability_costs, costs_v3, envelopes_readers
from fbi.ai.usage import UsageLedger, shared

from .test_budget_v3 import NOW, settings

pytestmark = pytest.mark.integration
D = Decimal


def call(db: psycopg.Connection[Any], prompt: str | None, cost: str, *, purpose: str = "other", tier: str = "analysis",
         input_hash: str | None = None, workspace: str = "PREDIGOL", status: str = "ok") -> int:
    return UsageLedger(shared(db)).record(at=NOW - timedelta(hours=2), purpose=purpose, tier=tier, provider="anthropic",  # type: ignore[arg-type]
                                          model="claude-haiku-5-5", usage=None, cost=D(cost), status=status, prompt_version=prompt,
                                          input_hash=input_hash, workspace=workspace)


def test_the_month_is_given_to_capabilities_and_adds_up_to_both_ledgers(db: psycopg.Connection[Any]) -> None:
    call(db, "extract-v4", "0.30", purpose="evidence_extraction", tier="bulk", input_hash="page-1")
    call(db, "extract-v4", "0.30", purpose="evidence_extraction", tier="bulk", input_hash="page-1")   # the same page paid again
    call(db, "extract-v4", "0.20", purpose="evidence_extraction", tier="bulk", input_hash="page-2")
    call(db, "extract-v4", "0", purpose="evidence_extraction", tier="bulk", input_hash="page-2", status="failed")  # not paid, not a repeat
    call(db, "review-v2", "1.50", purpose="pick_review", input_hash="r-1")
    call(db, "battery-v4", "0.40", workspace="PREDIGOL_LAB", input_hash="b-1")
    call(db, None, "0.015", purpose="web_search", tier="search")
    db.execute("INSERT INTO ai.user_usage (at, purpose, tier, provider, model, prompt_version, cost_usd, status) "
               "VALUES (%s, 'user_narrative', 'bulk', 'anthropic', 'claude-haiku-5-5', 'user-narrative-v3', 0.25, 'ok')",
               (NOW - timedelta(hours=1),))
    since, until = NOW - timedelta(days=1), NOW + timedelta(seconds=1)
    rows, totals = envelopes_readers.attribution_inputs(db, since, until)
    out = capability_costs.report(rows, totals)
    assert out["complete"] is True and out["total"]["reconciles"] is True and out["total"]["ledger_usd"] == "2.965000"
    by = {c["key"]: c for c in out["capabilities"]}
    assert set(by) == {"research.extraction", "production.review", "battery_v4", "research.search", "chronicles.chronicle"}
    assert (by["research.extraction"]["calls"], by["research.extraction"]["repeat_calls"], by["research.extraction"]["repeat_usd"]) == (4, 1, "0.30")
    assert by["battery_v4"]["envelopes"] == ["lab"] and by["research.search"]["envelopes"] == ["exa"]
    assert by["chronicles.chronicle"]["spent_usd"] == "0.25" and out["total"]["readers_usd"] == "0.25"
    panel = costs_v3.envelopes(db, at=NOW, settings=settings())
    assert panel["attribution"]["version"] == capability_costs.VERSION and panel["attribution"]["complete"] is True


def test_a_statement_that_fails_leaves_the_panel_standing(db: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(envelopes_readers, "ATTRIBUTION_SQL", "SELECT * FROM ai.no_such_table")
    out = costs_v3.attribution(db, NOW - timedelta(days=1), NOW)
    assert out["read_failed"] is True and out["error"] == "UndefinedTable"
    assert db.execute("SELECT 1").fetchone() == (1,), "the transaction is still usable"
