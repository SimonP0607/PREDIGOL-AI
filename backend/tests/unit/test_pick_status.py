"""The visible state of the picks a page shows (plan UX, B3; ``fbi.api.services.pick_status``): the review it reads is the day's
set's; a rejection or a downgrade keep a pick from a reader even while the review is not applied (D1, UX-039)."""

from __future__ import annotations

import inspect
import re
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from fbi.ai import review as ai_review
from fbi.api.services import pick_status
from fbi.api.services.pick_status import Applied

KEY = (7, "OU", "Over", Decimal("2.5"))


def flat(sql: str) -> str:
    return re.sub(r"\s+", " ", sql).strip()


def test_the_review_read_is_the_one_the_days_set_reads() -> None:
    """``REVIEWS_SQL`` repeats ``fbi.ai.review.LATEST_SQL`` (so that a client's request never loads the module that calls the
    language models): the same rows - the newest combined review per selection, made at most 12 hours before the moment."""
    window = inspect.signature(ai_review.latest_reviews).parameters["window"].default
    assert window == timedelta(hours=pick_status.REVIEW_WINDOW_HOURS)
    ours, theirs = flat(pick_status.REVIEWS_SQL), flat(ai_review.LATEST_SQL)
    for clause in ("SELECT DISTINCT ON (r.fixture_id, r.market_key, r.selection, r.line)", "FROM ai.pick_reviews r",
                   "WHERE r.engine = 'combined' AND r.fixture_id = ANY(%(fixtures)s) AND r.reviewed_at <= %(at)s",
                   "ORDER BY r.fixture_id, r.market_key, r.selection, r.line, r.reviewed_at DESC, r.id DESC"):
        assert clause in ours and clause in theirs, clause
    assert "r.reviewed_at >= %(at)s - make_interval(hours => %(hours)s)" in ours
    assert "r.reviewed_at >= %(at)s - %(window)s::interval" in theirs


def test_a_review_that_is_not_applied_still_keeps_back_what_it_rejects_or_downgrades() -> None:
    for decision, expected in (("REJECT", ("NOT_RECOMMENDED", "rejected", False)),
                               ("DOWNGRADE", ("CAUTION", "downgraded", False)),
                               ("APPROVE", ("RECOMMENDED", "value", True)),
                               ("ABSTAIN", ("RECOMMENDED", "value", True))):
        applied = Applied(False, {KEY: decision})
        assert applied.decision(*KEY) == decision
        s = applied.shown(pick_status="qualified", value=True, fixture_id=7, market_key="OU", selection="Over",
                          line=Decimal("2.5"))
        assert (s.status, s.reason, s.context_pending) == expected, decision


def test_an_applied_review_decides_through_the_table() -> None:
    applied = Applied(True, {KEY: "DOWNGRADE"})
    s = applied.shown(pick_status="published", value=True, fixture_id=7, market_key="OU", selection="Over",
                      line=Decimal("2.50"))
    assert (s.status, s.reason, s.context_pending) == ("CAUTION", "downgraded", False)
    other = applied.shown(pick_status="published", value=True, fixture_id=7, market_key="OU", selection="Under",
                          line=Decimal("2.5"))
    assert (other.status, other.reason, other.context_pending) == ("RECOMMENDED", "not_reviewed", True)
    shadow = applied.shown(pick_status="shadow", value=True, fixture_id=7, market_key="OU", selection="Over",
                           line=Decimal("2.5"))
    assert shadow.status == "EVALUATION"


class NoDatabase:
    def cursor(self, *args: Any, **kwargs: Any) -> Any:
        raise AssertionError("no query may be made while the AI is off")


@pytest.mark.parametrize("mode", ["off", " OFF "])
def test_while_the_ai_is_off_nothing_is_asked_of_the_database(monkeypatch: pytest.MonkeyPatch, mode: str) -> None:
    monkeypatch.setenv("FBI_AI_MODE", mode)
    got = pick_status.applied_now(NoDatabase(), [1, 2, 3], at=datetime(2026, 10, 27, tzinfo=UTC))  # type: ignore[arg-type]
    assert got is pick_status.NOT_APPLIED and not got.enforced
