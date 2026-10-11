"""CIERRE DEL DÍA (fbi.ai.daily_review) and the AI's newest pre-match review on the day's records (9 Oct 2026).

Built on the world of test_daily_records: AT 2032-08-01 12:00 UTC (07:00 Bogotá); F1-F6 kick off that Bogotá day.
"""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb

from fbi.ai import daily_review
from fbi.api.services import daily_review as review_api
from fbi.api.services.records import daily_board
from fbi.picks.daily import build_daily_sets, product_day
from fbi.picks.fast_settlement import settle_fixtures

from .conftest import Seed
from .test_daily_records import AT, World

DAY = product_day(AT)
CLOSE = AT + timedelta(hours=16, minutes=59)  # 23:59 Bogotá


def _review(db: psycopg.Connection[Any], fixture: int, decision: str, at: Any) -> None:
    db.execute(
        "INSERT INTO ai.pick_reviews (reviewed_at, fixture_id, market_key, selection, line, engine, engine_version, "
        "input_hash, decision, confidence, output, mode, status) VALUES (%s, %s, '1X2', 'Home', 0, 'combined', "
        "'combined-v1+claude', 'h', %s, 0.6, %s, 'shadow', 'ok')",
        (at, fixture, decision, Jsonb({"summary": "ventaja pequeña"})))


def test_the_day_is_closed_then_revised_only_when_it_changes(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    w.review_all()
    build_daily_sets(db, at=AT)
    for name in ("F1", "F2", "F3"):
        _review(db, w.fixtures[name], "DOWNGRADE", AT + timedelta(minutes=5))
    w.result("F1", 2, 0)
    w.result("F3", 1, 1)
    settle_fixtures(db, [w.fixtures["F1"], w.fixtures["F3"]], path="live_follow", at=AT + timedelta(hours=9))

    first = daily_review.store(db, day=DAY, at=CLOSE, kind="close")
    assert first is not None
    row = db.execute("SELECT revision, kind, complete, pending_fixtures, content FROM ai.daily_reviews WHERE id = %s",
                     (first,)).fetchone()
    assert row is not None
    revision, kind, complete, pending, body = row
    assert (revision, kind, complete) == (1, "close", False)
    assert set(pending) >= {w.fixtures["F2"], w.fixtures["F4"]}, "matches not over at the close stay pending"
    daily = body["daily_picks"]
    assert daily["n"] == 5 and daily["won"] + daily["lost"] >= 1
    assert body["matches"]["tracked"] >= 6
    assert body["ai"]["reviewed"] == 6, "daily-set-v4/v5: every match of the day went through PrediGol Intelligence"
    assert body["ai"]["downgrade"] == 3
    assert body["ai"]["downgrade_won"] == 1, "F1 won at home 2-0; F3 drew"
    assert "pnl_units" in daily and "line_value" in daily

    # Nothing changed: no new revision. Something of that day changed: revision 2.
    assert daily_review.store(db, day=DAY, at=CLOSE + timedelta(minutes=30), kind="update") is None
    w.result("F2", 0, 1)
    settle_fixtures(db, [w.fixtures["F2"]], path="results_repair", at=AT + timedelta(hours=10))
    second = daily_review.store(db, day=DAY, at=CLOSE + timedelta(hours=8), kind="update")
    assert second is not None
    assert db.execute("SELECT revision, kind FROM ai.daily_reviews WHERE id = %s", (second,)).fetchone() == (2, "update")

    # Append-only.
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        db.execute("UPDATE ai.daily_reviews SET complete = true WHERE id = %s", (first,))

    # Read back: the history and the day with its revisions.
    hist = review_api.history(db, days=30).data
    assert hist and hist[0].day == DAY and hist[0].revisions == 2
    one = review_api.day_review(db, day=DAY).data
    assert one is not None and one.revision == 2 and [r.revision for r in one.revisions] == [2, 1]
    assert review_api.day_review(db, day=DAY + timedelta(days=1)).data is None


def test_an_update_never_writes_a_day_that_was_not_closed(db: psycopg.Connection[Any], seed: Seed) -> None:
    World(db, seed)
    assert daily_review.store(db, day=DAY, at=CLOSE, kind="update") is None
    # The worker was down at 23:59: the next follow closes yesterday late, and says when.
    written = daily_review.follow_days(db, at=CLOSE + timedelta(hours=2))
    assert len(written) == 1
    assert db.execute("SELECT day, kind, built_at FROM ai.daily_reviews WHERE id = %s",
                      (written[0],)).fetchone() == (DAY, "close", CLOSE + timedelta(hours=2))


def test_the_days_records_carry_the_ais_newest_pre_match_review(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    w.review_all()
    build_daily_sets(db, at=AT)
    f1 = w.fixtures["F1"]
    _review(db, f1, "APPROVE", AT + timedelta(minutes=10))
    _review(db, f1, "DOWNGRADE", AT + timedelta(minutes=50))
    _review(db, f1, "REJECT", AT + timedelta(hours=3))  # after kick-off: not a pre-match review
    owner = daily_board(db, day=DAY, include_shadow=True, at=AT + timedelta(hours=1)).data
    assert owner is not None and owner.set is not None
    item = next(i for i in owner.set.items if i.match.fixture_id == f1)
    assert item.ai_latest is not None
    assert (item.ai_latest.decision, item.ai_latest.reason) == ("DOWNGRADE", "ventaja pequeña")
    assert item.ai_latest.confidence == Decimal("0.600") and item.ai_latest.by_llm
    user = daily_board(db, day=DAY, include_shadow=False, at=AT + timedelta(hours=1)).data
    assert user is not None and user.set is not None
    seen = next(i for i in user.set.items if i.match.fixture_id == f1)
    assert seen.ai_latest is not None and seen.ai_latest.decision is None, "in shadow a user sees only that it was"
