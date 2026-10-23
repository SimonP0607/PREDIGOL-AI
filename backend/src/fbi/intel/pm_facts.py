"""What a post-mortem of one selection starts from: the CANDIDATE (the selection with everything the system stored about it before
kick-off, from the three places that ever stored one) and the FACTS it is judged by (plan F8, ``pm-v6``). Pure: nothing here reads a
database - ``fbi.intel.postmortem`` reads in batches and hands the rows over, so every rule of this module is tested with plain data.

A selection (fixture, market, selection, line) can be known to up to three parts of PrediGol, and each priced it:

    item      a pick of the day or a leg of a parlay (``picks.daily_set_items`` / ``picks.parlay_legs``): the price a USER was shown;
    decision  the newest decision of the decision layer before kick-off (``intel.decisions``): the price it froze, with the bookmaker and
              the moment of that price;
    review    the newest combined review of the AI before kick-off (``ai.pick_reviews``): the price the reviewer was shown, which is read
              from the consensus of every market and can lag the selection's own price.

THE PRICE TAKEN is the first of them in that order (what a person could act on, then what the system committed to with a recorded
moment, then what a reviewer read); the others stay in the evidence (``evidence.prices``) with where each came from. They are NOT the same
price: measured in production on 23 Oct 2026 over 14 days, the same selection carried the same odds in only 31 % of the pairs of item and
review (mean difference 2.6 %) and 36 % of the pairs of decision and review (mean 3.7 %) - as large as the +-1 % that separates a good price
from a bad one - so which one is taken decides verdicts, and it is written down in every row (``evidence.price_from``) and counted
(``python -m scripts.postmortems status``). The probability of the model is read in the same order (the calibrated one for a decision, as
the decision layer judges it), so that the price and the probability a post-mortem compares come from the same part of the system.

A key absence, an unfit competition, a kick-off that changed, a report that proved wrong: the AI's evidence about the match is read
from the review's packet and output and from the match's own findings (``fbi.intel.match_review.analyse``) exactly as the first
post-mortem by selection (pm-v2) read it - ``tests/integration/test_pm_v6_equals_v2.py`` holds the two to the same classes and
verdicts over the same selections.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from fbi.ai.review import side_of
from fbi.ai.text import TIER_ES, fit
from fbi.intel.pm_questions import NOT_FIT, STALE_PRICE, Facts

Key = tuple[int, str, str, Decimal]

AI_ROLES = frozenset({"daily_pick", "parlay_leg", "llm", "reviewed", "rejected"})
"""Why the AI studied a selection (the roles of pm-v2); a selection only the decision layer judged has the role ``decision``."""

__all__ = ["AI_ROLES", "Candidate", "Key", "build_facts", "resolve", "who"]


def _f(x: Any) -> float | None:
    return None if x is None else float(x)


@dataclass
class Candidate:
    """A selection to study, with everything stored about it before kick-off. ``odds`` and ``bookmaker_id`` are the price taken."""

    key: Key
    roles: set[str] = field(default_factory=set)
    ai_studied: bool = False
    """The selection is in the universe of pm-v2: only these emit the memory event ``pick_postmortem`` the patterns count."""
    odds: float | None = None
    bookmaker_id: int | None = None
    price_from: str | None = None
    price_at: datetime | None = None
    taken_at: datetime | None = None
    p_model: float | None = None
    p_market: float | None = None
    prices: dict[str, dict[str, Any]] = field(default_factory=dict)
    # the decision layer
    decision_id: int | None = None
    state: str | None = None
    checkpoint: str | None = None
    known_at: datetime | None = None
    score: float | None = None
    context_status: str | None = None
    context: dict[str, Any] = field(default_factory=dict)
    decision_clv: float | None = None
    decision_result: str | None = None
    # the AI review
    review_id: int | None = None
    review_decision: str | None = None
    reviewed_at: datetime | None = None
    output: dict[str, Any] = field(default_factory=dict)
    packet_id: int | None = None

    @property
    def fixture_id(self) -> int:
        return self.key[0]


def resolve(key: Key, *, item: dict[str, Any] | None, review: dict[str, Any] | None, decision: dict[str, Any] | None,
            roles: set[str], ai_studied: bool) -> Candidate:
    """Merge what the three parts stored about one selection into one candidate. Any of the three may be absent (not all of them)."""
    c = Candidate(key=key, roles=set(roles), ai_studied=ai_studied)
    ordered = (("item", item), ("decision", decision), ("review", review))
    for name, row in ordered:
        if row is None or row.get("odds") is None:
            continue
        c.prices[name] = {"odds": _f(row["odds"]), "bookmaker_id": row.get("bookmaker_id"),
                          "at": None if row.get("price_at") is None else row["price_at"].isoformat()}
    for name, row in ordered:
        if row is not None and row.get("odds") is not None:
            c.odds, c.bookmaker_id, c.price_from = _f(row["odds"]), row.get("bookmaker_id"), name
            c.price_at = row.get("price_at")
            # when the price was taken: the moment the item was selected, or the moment the decision was known; a review's
            # price has no recorded age (it reads the consensus of every market, which can lag the selection's own price)
            c.taken_at = (row.get("selected_at") if name == "item" else row.get("known_at") if name == "decision" else None)
            break
    for name, row in ordered:
        # the model's probability, in the same order as the price: the calibrated one for a decision, as the decision layer judges
        value = None if row is None else _f(row["p_cal"]) if name == "decision" and row.get("p_cal") is not None else _f(row.get("p_model"))
        if value is not None:
            c.p_model = value
            break
    for _, row in ordered:
        if row is not None and row.get("p_market") is not None:
            c.p_market = _f(row["p_market"])
            break
    if review is not None:
        c.review_id = int(review["review_id"])
        c.review_decision = review.get("decision")
        c.reviewed_at = review.get("reviewed_at")
        c.output = dict(review.get("output") or {})
        c.packet_id = review.get("packet_id")
        c.roles.add("reviewed")
        if review.get("decision") == "REJECT":
            c.roles.add("rejected")
    if decision is not None:
        c.decision_id = int(decision["id"])
        c.state, c.checkpoint, c.known_at = decision.get("state"), decision.get("checkpoint"), decision.get("known_at")
        c.score = _f(decision.get("score"))
        c.context_status = decision.get("context_status")
        c.context = dict(decision.get("context") or {})
        c.decision_clv = _f(decision.get("decision_clv"))
        c.decision_result = decision.get("decision_result")
        c.roles.add("decision")
        if c.review_decision is None:
            c.review_decision = (c.context.get("review") or {}).get("decision")
    return c


def who(e: dict[str, Any]) -> str:
    """Who a report was about, as the owner reads it: the provider writes "Guga (Fluminense): Missing Fixture - Inactive" - the
    player and the team are kept, the provider's English reason is not."""
    claim = str(e.get("claim", "")).strip()
    if e.get("tier") == "provider" and ": " in claim:
        claim = claim.split(": ", 1)[0]
    return fit(claim, 80)


def build_facts(c: Candidate, *, settled: str, kickoff: datetime, findings: dict[str, Any] | None,
                packet: dict[str, Any] | None, p_close: float | None, close_odds: float | None,
                first_lineup: datetime | None) -> Facts:
    """The facts a selection is judged by. ``packet`` is ``{"quality": ..., "absences": ...}`` of the packet the review used."""
    f = Facts(settled=settled, decision=c.review_decision, p_model=c.p_model, p_market=c.p_market, p_close=p_close,
              odds=c.odds, close_odds=close_odds)
    output = c.output or {}
    codes = [x.get("code") for g in ("negative_evidence", "uncertainties", "contradictions") for x in (output.get(g) or [])
             if x.get("code")]
    f.ignored = sorted(set(codes) - {"lineups_confirmed"})
    f.edge_in_noise = "edge_within_noise" in codes
    f.kickoff_changed = "kickoff_changed" in codes
    side = side_of(c.key[1], c.key[2])
    opp = "away" if side == "home" else "home" if side == "away" else None
    quality_block = (packet or {}).get("quality") or {}
    quality = (quality_block.get("competition_score") or {}).get("class")
    validation = (quality_block.get("fixture_validation") or {}).get("state")
    f.data_unfit = quality in NOT_FIT or validation == "QUARANTINED"
    # a stale price is judged only where the price taken and the moment it was taken are recorded (a pick of the day, a parlay
    # leg, a decision): a review reads the consensus of every market, which can lag the selection's own price
    if c.price_at is not None and c.taken_at is not None and c.taken_at - c.price_at > STALE_PRICE:
        f.stale_price = True
    absences = (packet or {}).get("absences") or {}
    for sd in [side] if side in ("home", "away") else ["home", "away"]:
        for p in (absences.get(sd) or {}).get("players", []):
            if p.get("key") and not str(p.get("type") or "").startswith("Quest"):
                f.key_absence.append(f"{p.get('name')} ({'local' if sd == 'home' else 'visitante'})")
    for e in (findings or {}).get("evidence", []):
        # a report that proved wrong hurts the pick when it made the opponent look weaker (or any, for a total/draw)
        if e.get("verdict") == "wrong" and (opp is None or e.get("side") in (opp, None)):
            f.information.append(f"reportado fuera y fue titular, según {TIER_ES.get(str(e.get('tier')), 'una fuente')}: {who(e)}")
    for m in (findings or {}).get("missing_information", []):
        # an absence nobody reported counts against a side pick; for a draw or a total its direction is unknown
        if side in ("home", "away") and m.get("side") == side:
            name = m.get("player") or f"jugador {m.get('player_id')}"
            f.information.append(f"titular habitual ausente sin reporte: {name} "
                                 f"({'local' if m.get('side') == 'home' else 'visitante'})")
    f.information_failed = bool(f.information)
    if first_lineup is not None and first_lineup < kickoff and not output.get("lineups_seen") \
            and c.reviewed_at is not None and first_lineup > c.reviewed_at:
        f.lineup_changed = True
        f.lineup_detail = "las alineaciones se confirmaron después de la última revisión"
    if any(e.get("verdict") == "wrong" for e in (findings or {}).get("evidence", [])):
        f.lineup_changed = True
        f.lineup_detail = (f.lineup_detail + "; " if f.lineup_detail else "") + "un jugador reportado fuera fue titular"
    return f
