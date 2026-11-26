"""Do not pay for a review whose answer is already known (plan RP-12.2, finding H27): ``review-prefilter-v1``. Pure, plus a reading of the history.

``combine`` (``fbi.ai.review``) takes the most conservative of the engines that gave an opinion (REJECT < DOWNGRADE < APPROVE). When the rules
(``rules-review-v1``, free, deterministic) already say REJECT, the combined review is REJECT whatever the language model answers: a model review of
that selection can neither approve it nor change what the pick filter and the user status read. In 30 days of production 302 of 2,087 model
reviews were of such selections (US$ 15.72 of 82.78). This module is the rule that skips them and the measure that proves, on the history, what
skipping would have changed:

    skips(decision, ...) ...... True when the rules decided REJECT and the selection is not in the CONTROL (a fixed share the model still reviews,
                                so the claim «the model could not have changed it» keeps being checked on live rows)
    replay(rows) .............. over the model reviews of a window: how many the rule would have skipped, what they cost, whether any combined
                                review that approved would have changed (it cannot: it asserts it), and the control that stays

The switch is ``FBI_AI_REVIEW_PREFILTER`` (``AiSettings.review_prefilter``), OFF unless it says ``1``/``on``/``true``/``yes``: turning it on is the
owner's decision D1 with this report in view, through the audited kit. Nothing here rewrites a row of ``ai.pick_reviews`` or touches a
probability.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

VERSION: Final = "review-prefilter-v1"
SALT: Final = "review-prefilter-control-v1"
BUCKETS: Final = 10_000
CONTROL_SHARE: Final = Decimal("0.10")
"""The share of the selections the rules reject that the model still reviews, to keep verifying that it never changes the outcome (proposed)."""


def bucket(fixture_id: int, market_key: str, selection: str, line: Decimal) -> int:
    """A selection's bucket, 0 to 9999: no state, no clock, independent of the result."""
    text = f"{SALT}:{int(fixture_id)}:{market_key}:{selection}:{format(Decimal(line).normalize(), 'f')}"
    return int.from_bytes(hashlib.sha256(text.encode("utf-8")).digest()[:8], "big") % BUCKETS


def in_control(fixture_id: int, market_key: str, selection: str, line: Decimal) -> bool:
    return bucket(fixture_id, market_key, selection, line) < int(CONTROL_SHARE * BUCKETS)


def skips(rules_decision: str, fixture_id: int, market_key: str, selection: str, line: Decimal) -> bool:
    """Whether the model review of a selection is not asked: the rules rejected it and it is not in the control."""
    return rules_decision == "REJECT" and not in_control(fixture_id, market_key, selection, line)


@dataclass(frozen=True, slots=True)
class Replay:
    window_days: int
    reviews: int
    cost: Decimal
    skipped: int
    skipped_cost: Decimal
    control: int
    approved_by_model: int
    approved_where_rules_rejected: int
    combined_approvals_changed: int


def replay(rows: Iterable[Mapping[str, Any]], *, window_days: int) -> Replay:
    """The rule over the model reviews of a window. Each row: fixture_id, market_key, selection, line, rules (the rules' decision on the same
    packet, None if unknown), llm (the model's decision), cost, combined (the combined decision of that packet, None if unknown)."""
    n, cost, skipped, skipped_cost, control, approved, bad, changed = 0, Decimal(0), 0, Decimal(0), 0, 0, 0, 0
    for r in rows:
        n += 1
        c = Decimal(str(r.get("cost") or 0))
        cost += c
        rules = r.get("rules")
        approved += r["llm"] == "APPROVE"
        if rules != "REJECT":
            continue
        bad += r["llm"] == "APPROVE"
        if skips(str(rules), int(r["fixture_id"]), str(r["market_key"]), str(r["selection"]), Decimal(str(r["line"]))):
            skipped += 1
            skipped_cost += c
            changed += r.get("combined") not in (None, "REJECT")  # a skipped review whose combined decision was not REJECT would be a change
        else:
            control += 1
    return Replay(window_days, n, cost, skipped, skipped_cost, control, approved, bad, changed)


SQL = """
WITH l AS (
  SELECT fixture_id, market_key, selection, line, packet_id, decision, cost_usd, reviewed_at
    FROM ai.pick_reviews
   WHERE engine = 'llm' AND status = 'ok' AND reviewed_at >= %(since)s AND reviewed_at < %(until)s
), r AS (
  SELECT DISTINCT ON (fixture_id, market_key, selection, line, packet_id) fixture_id, market_key, selection, line, packet_id, decision
    FROM ai.pick_reviews WHERE engine = 'rules' AND reviewed_at >= %(since)s - interval '1 day' AND reviewed_at < %(until)s
   ORDER BY fixture_id, market_key, selection, line, packet_id, reviewed_at DESC, id DESC
), c AS (
  SELECT DISTINCT ON (fixture_id, market_key, selection, line, packet_id) fixture_id, market_key, selection, line, packet_id, decision
    FROM ai.pick_reviews WHERE engine = 'combined' AND reviewed_at >= %(since)s AND reviewed_at < %(until)s
   ORDER BY fixture_id, market_key, selection, line, packet_id, reviewed_at DESC, id DESC
)
SELECT l.fixture_id, l.market_key, l.selection, l.line, l.decision AS llm, l.cost_usd AS cost, r.decision AS rules, c.decision AS combined
  FROM l LEFT JOIN r USING (fixture_id, market_key, selection, line, packet_id)
         LEFT JOIN c USING (fixture_id, market_key, selection, line, packet_id)
"""


def read(conn: psycopg.Connection[Any], *, since: Any, until: Any) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(SQL, {"since": since, "until": until})
        return [dict(x) for x in cur.fetchall()]


def as_dict(p: Replay) -> dict[str, Any]:
    share = float(p.skipped_cost / p.cost) if p.cost else 0.0
    return {"version": VERSION, "window_days": p.window_days, "model_reviews": p.reviews, "cost_usd": float(p.cost), "would_skip": p.skipped,
            "would_skip_cost_usd": float(p.skipped_cost), "share_of_cost": round(share, 4), "kept_as_control": p.control,
            "control_share": float(CONTROL_SHARE), "model_approvals": p.approved_by_model,
            "model_approvals_where_rules_rejected": p.approved_where_rules_rejected,
            "combined_decisions_the_skip_would_change": p.combined_approvals_changed}
