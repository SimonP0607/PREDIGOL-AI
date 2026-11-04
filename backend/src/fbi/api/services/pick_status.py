"""The visible state of the picks a page shows (plan UX, B3): the one table of ``fbi/picks/user_status.py``, fed with what the page
already read and - only while the AI's review acts on picks - with the review's newest decision on each selection.

Read only, and free while the review is not applied (production since the AI layer exists: ``FBI_AI_MODE=shadow``): the mode is a
setting, so no query is made at all. In enforce mode it reads the shadow gate's newest report (``fbi.ai.gating.enforcement``)
and the newest combined review of each selection made in the 12 hours before the moment asked about - the review the day's set
reads (``fbi.ai.review.latest_reviews``; ``REVIEWS_SQL`` repeats its query so that a client's request never loads the module that
calls the language models, and ``tests/unit/test_pick_status.py`` holds the two together).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Final

from fbi.ai.config import AiSettings
from fbi.ai.gating import enforcement
from fbi.api.repositories import Conn, fetch_all
from fbi.picks import user_status

SelectionKey = tuple[int, str, str, Decimal]

REVIEW_WINDOW_HOURS: Final = 12
REVIEWS_SQL: Final = """
SELECT DISTINCT ON (r.fixture_id, r.market_key, r.selection, r.line)
       r.fixture_id, r.market_key, r.selection, r.line, r.decision
  FROM ai.pick_reviews r
 WHERE r.engine = 'combined' AND r.fixture_id = ANY(%(fixtures)s) AND r.reviewed_at <= %(at)s
   AND r.reviewed_at >= %(at)s - make_interval(hours => %(hours)s)
 ORDER BY r.fixture_id, r.market_key, r.selection, r.line, r.reviewed_at DESC, r.id DESC
"""


@dataclass(frozen=True)
class Applied:
    """Whether the AI's review acts on picks at a moment and, when it does, its newest decision on each selection."""

    enforced: bool = False
    decisions: Mapping[SelectionKey, str] = field(default_factory=dict)

    def decision(self, fixture_id: int, market_key: str, selection: str, line: Decimal) -> str | None:
        return self.decisions.get((int(fixture_id), market_key, selection, Decimal(line))) if self.enforced else None

    def shown(self, *, pick_status: str | None, value: bool, fixture_id: int, market_key: str, selection: str,
              line: Decimal) -> user_status.Shown:
        """The visible state of a pick read now: its publication state, whether it passes the value rule at the best price now
        and, while the review is applied, the review's newest decision on it."""
        return user_status.shown(published=user_status.is_published(pick_status), value=value,
                                 review=self.decision(fixture_id, market_key, selection, line), applied=self.enforced)


NOT_APPLIED: Final = Applied()


def applied_now(conn: Conn, fixture_ids: Iterable[int], *, at: datetime) -> Applied:
    """The AI's review as it stands at ``at`` for these matches: not applied (no query) unless the owner's switch is on AND the
    shadow gate passed."""
    if not enforcement(conn, AiSettings.from_env()).enforced:
        return NOT_APPLIED
    fixtures = sorted({int(f) for f in fixture_ids})
    if not fixtures:
        return Applied(True)
    rows = fetch_all(conn, REVIEWS_SQL, {"fixtures": fixtures, "at": at, "hours": REVIEW_WINDOW_HOURS})
    return Applied(True, {(int(r["fixture_id"]), r["market_key"], r["selection"], Decimal(r["line"])): str(r["decision"])
                          for r in rows})
