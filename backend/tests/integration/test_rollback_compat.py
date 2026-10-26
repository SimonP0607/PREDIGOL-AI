"""A real rollback (Plan Maestro IA, directive 36): the code of the release BEFORE this plan keeps working on the schema this plan
migrates.

The statements below are copied, frozen, from that release (commit c6ed649: ``fbi.ai.usage``, ``fbi.ai.brief``, ``fbi.ai.costs``,
``fbi.notify.service``). They are NOT imported: the point is that they do not change. Putting the earlier code back after a
migration must find a schema it can use, so every migration of the plan is additive - a new table, a view, a nullable column -
and if one of the statements below stops working, the migration is wrong and is corrected in a NEW file (``0110`` is not
released yet; the ones after it are).

The schema under test is the head: each later phase that adds a migration keeps these statements working too."""

from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from fbi.ai.usage import MONTH_ALERT_SQL

from .conftest import Seed

AT = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
MONTH = date(2026, 10, 1)

OLD_USAGE_INSERT = (
    "INSERT INTO ai.usage (at, purpose, tier, provider, model, prompt_version, fixture_id, input_tokens, "
    "output_tokens, cached_tokens, searches, vision_items, cost_usd, latency_ms, status, error, input_hash, "
    "request_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id")

OLD_ALERT_INSERT = ("INSERT INTO ai.budget_alerts (month, threshold, created_at, spent_usd, budget_usd) "
                    "VALUES (%s, %s, %s, %s, %s) ON CONFLICT (month, threshold) DO NOTHING RETURNING threshold")
OLD_ALERTS_READ = ("SELECT month, threshold, created_at, spent_usd, budget_usd FROM ai.budget_alerts "
                   "WHERE month = %s ORDER BY threshold")
OLD_NOTIFIER_READ = ("SELECT month, threshold, spent_usd, budget_usd, created_at FROM ai.budget_alerts "
                     "WHERE created_at > %s - interval '40 days'")

OLD_BRIEF_INSERT = """
INSERT INTO ai.match_briefs (fixture_id, created_at, pass, version, engine, provider, model, packet_id, input_hash,
    status, escalate, reasons, uncertainty, data_quality, content, rejected, usage_ids, cost_usd, error)
VALUES (%(fixture)s, %(at)s, %(pass)s, %(version)s, %(engine)s, %(provider)s, %(model)s, %(packet)s, %(hash)s,
    %(status)s, %(escalate)s, %(reasons)s, %(uncertainty)s, %(quality)s, %(content)s, %(rejected)s, %(usage)s, %(cost)s,
    %(error)s)
RETURNING id
"""
OLD_BRIEF_LATEST = """
SELECT id, fixture_id, created_at, pass, version, engine, provider, model, packet_id, input_hash, status, escalate,
       reasons, uncertainty, data_quality, content, rejected, usage_ids, cost_usd, error
  FROM ai.match_briefs WHERE fixture_id = %(fixture)s AND (%(at)s::timestamptz IS NULL OR created_at <= %(at)s)
 ORDER BY created_at DESC, id DESC LIMIT 1
"""
OLD_BRIEF_BY_HASH = """
SELECT id, engine, status, escalate, reasons, content FROM ai.match_briefs
 WHERE fixture_id = %(fixture)s AND input_hash = %(hash)s ORDER BY created_at DESC, id DESC LIMIT 1
"""


def test_the_alert_of_the_month_is_written_by_the_new_code_with_the_statement_of_the_old() -> None:
    assert MONTH_ALERT_SQL == OLD_ALERT_INSERT, \
        "production's month alert is one statement, one table, one key for both generations of code"


def test_the_earlier_code_writes_and_reads_its_ledger_and_its_alerts_on_the_new_schema(db: psycopg.Connection[Any],
                                                                                         seed: Seed) -> None:
    row = db.execute(OLD_USAGE_INSERT, (AT, "pick_review", "analysis", "anthropic", "claude-sonnet-5-5", "pr-v3",
                                        seed.fixture_id, 1000, 100, 0, 0, 0, Decimal("0.0123"), 900, "ok", None, "h1",
                                        "req_1")).fetchone()
    assert row is not None
    assert db.execute("SELECT scope, cache_write_tokens, batch_id, workspace, key_label FROM ai.usage_scoped WHERE id = %s",
                      (row[0],)).fetchone() == ("production", None, None, None, None), \
        "what the earlier code wrote is production's, with the new columns empty"

    args = (MONTH, 50, AT, Decimal("92.5"), Decimal("185"))
    assert db.execute(OLD_ALERT_INSERT, args).fetchone() == (50,)
    assert db.execute(OLD_ALERT_INSERT, args).fetchone() is None, "ON CONFLICT (month, threshold) still holds"
    assert db.execute(MONTH_ALERT_SQL, args).fetchone() is None, "and the new code does not raise it a second time"
    assert [r[1] for r in db.execute(OLD_ALERTS_READ, (MONTH,)).fetchall()] == [50]
    assert len(db.execute(OLD_NOTIFIER_READ, (AT,)).fetchall()) == 1
    assert db.execute("SELECT scope, kind, threshold FROM ai.budget_alerts_all").fetchall() == [("production", "month", 50)]


def test_the_earlier_code_writes_and_reads_its_briefs_on_the_new_schema(db: psycopg.Connection[Any], seed: Seed) -> None:
    params: dict[str, Any] = {
        "fixture": seed.fixture_id, "at": AT, "pass": "first", "version": "brief-v8", "engine": "llm",
        "provider": "anthropic", "model": "claude-haiku-5-5", "packet": None, "hash": "abc", "status": "ok",
        "escalate": False, "reasons": [], "uncertainty": "low", "quality": "good",
        "content": Jsonb({"summary": "s"}), "rejected": Jsonb([]), "usage": [], "cost": Decimal("0.01"), "error": None}
    row = db.execute(OLD_BRIEF_INSERT, params).fetchone()
    assert row is not None
    latest = db.execute(OLD_BRIEF_LATEST, {"fixture": seed.fixture_id, "at": None}).fetchone()
    assert latest is not None and latest[0] == row[0] and latest[3] == "first"
    assert db.execute(OLD_BRIEF_BY_HASH, {"fixture": seed.fixture_id, "hash": "abc"}).fetchone() is not None
    assert db.execute("SELECT material_hash, material FROM ai.match_briefs WHERE id = %s", (row[0],)).fetchone() \
        == (None, None), "a brief of the earlier code has no material snapshot: the new code simply writes a new one"
