"""THE VISIBLE STATE OF A PICK (plan UX, B3; section 28 of the plan): one table from the states PrediGol Intelligence already
records to the four a reader sees, and nothing else in the product decides it. The list of picks, the day's set, a match's
analysis and «¿Por qué este pick?» all ask here, and ``tests/unit/test_user_status.py`` walks every combination.

    visible           equals                                                                where a reader sees it
    RECOMMENDED       a published pick (qualified or published) that passes the value       Picks, Inicio and the match
                      rule at its price and, with the AI's review applied, was approved.
                      While that review is not applied (``FBI_AI_MODE`` shadow or off, its
                      gate not passed) - or applied but without a decision on this pick -
                      the state carries ``context_pending``: «revisión de contexto aún no
                      aplicada»
    CAUTION           the review is applied and downgrades it (DOWNGRADE -> caution)         Picks and the match
    NOT_RECOMMENDED   no value at its price, or the applied review rejects it                only the match, never the list
                      (REJECT -> not_recommended)                                            of picks
    EVALUATION        a candidate of a model that has not beaten the market yet (a shadow    only counted (Transparencia);
                      pick)                                                                  the owner's preview labels it

Precedence: EVALUATION > NOT_RECOMMENDED (no value) > the applied review > RECOMMENDED. A review that is not applied changes
nothing here, exactly as it changes nothing in the picks (``fbi.picks.daily.AiView.apply``).

It only reads what it is given: the pick's publication state (``picks.picks.status``), whether it passes the value rule at its
price (the engine's verdict, computed elsewhere), the AI's newest decision on it and whether that decision is applied
(``fbi.ai.gating.enforcement``). It imports neither the rules nor the engine, touches no database and changes nothing of
Intelligence: no model, probability, threshold, rule or state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

VERSION: Final = "user-status-v1"

UserStatus = Literal["RECOMMENDED", "CAUTION", "NOT_RECOMMENDED", "EVALUATION"]
StatusReason = Literal["approved", "value", "not_reviewed", "downgraded", "rejected", "no_value_now", "evaluation"]
"""Why the state is the one it is, as a code the web words:

approved      the applied review approved it
value         the value rule alone: the review is not applied (shadow, off or its gate not passed)
not_reviewed  the review is applied but has no decision on this pick (none yet, or it abstained)
downgraded    the applied review downgrades it
rejected      the applied review rejects it
no_value_now  it does not pass the value rule at its price
evaluation    its model has not beaten the market yet: never a recommendation"""

STATES: Final[tuple[UserStatus, ...]] = ("RECOMMENDED", "CAUTION", "NOT_RECOMMENDED", "EVALUATION")
REASONS: Final[tuple[StatusReason, ...]] = (
    "approved", "value", "not_reviewed", "downgraded", "rejected", "no_value_now", "evaluation")
DECISIONS: Final = ("APPROVE", "DOWNGRADE", "REJECT", "ABSTAIN")
"""The AI's combined decisions (``ai.pick_reviews.decision``)."""
PUBLISHED: Final = frozenset({"qualified", "published"})
"""The publication states of a pick a reader may be shown (``picks.picks.status``); ``shadow`` is a candidate in evaluation."""
IN_LIST: Final[frozenset[UserStatus]] = frozenset({"RECOMMENDED", "CAUTION"})
"""What a list of picks (Picks, Inicio) shows: NOT_RECOMMENDED stays on its match and EVALUATION is only counted."""
ORDER: Final[dict[UserStatus, int]] = {"RECOMMENDED": 0, "EVALUATION": 0, "CAUTION": 1, "NOT_RECOMMENDED": 2}
"""A list's order among equals: the downgraded ones after the rest, as the day's set orders them (``AiView.apply``)."""


@dataclass(frozen=True, slots=True)
class Shown:
    status: UserStatus
    reason: StatusReason
    context_pending: bool
    """RECOMMENDED by the value rule alone: «revisión de contexto aún no aplicada» is said beside it."""


def shown(*, published: bool, value: bool, review: str | None, applied: bool) -> Shown:
    """The visible state of one selection.

    ``published``: its pick is qualified or published - not a shadow pick of a model that has not beaten the market.
    ``value``: it passes the value rule at its price (the best price now, or the price a record froze).
    ``review``: the AI's newest combined decision on it (APPROVE, DOWNGRADE, REJECT, ABSTAIN), or None.
    ``applied``: that review acts on picks (enforce mode with its gate passed); otherwise it is ignored here."""
    if not published:
        return Shown("EVALUATION", "evaluation", False)
    if not value:
        return Shown("NOT_RECOMMENDED", "no_value_now", False)
    if applied:
        if review == "REJECT":
            return Shown("NOT_RECOMMENDED", "rejected", False)
        if review == "DOWNGRADE":
            return Shown("CAUTION", "downgraded", False)
        if review == "APPROVE":
            return Shown("RECOMMENDED", "approved", False)
        return Shown("RECOMMENDED", "not_reviewed", True)
    return Shown("RECOMMENDED", "value", True)


def is_published(pick_status: str | None) -> bool:
    """A pick's publication state (``picks.picks.status``, or what it was before it was settled) as the table reads it."""
    return pick_status in PUBLISHED


def of_card(*, kind: str, qualified: bool, review: str | None, applied: bool) -> Shown | None:
    """A card of a match's analysis (``ai.match_analyses``, rule match-analysis-v1, read only):

    value       a selection that passed the value rule at the analysis's price: published when its pick is qualified
    evaluated   the model's view of a main market without value at its price (the owner's evaluation view only): NOT_RECOMMENDED
    no_market   no bookmaker prices it - not a pick, no state (the card keeps its own «sin mercado»)"""
    if kind == "no_market":
        return None
    if kind == "value":
        return shown(published=qualified, value=True, review=review, applied=applied)
    return shown(published=True, value=False, review=review, applied=applied)
