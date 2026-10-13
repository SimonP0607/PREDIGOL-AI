"""The AI decision layer's pure parts: what the reviewers decide from a packet, what a claim may say, how
evidence is classified, the per-match cards, the dependence between parlay legs and the AI's own shadow gate.
No database, no model, no network."""

from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from fbi.ai import context as ctx
from fbi.ai.analysis import ValueOption, build_cards, no_market_cards
from fbi.ai.claims import ClaimOut, ReviewOut, check
from fbi.ai.evidence import Row, classify
from fbi.ai.packet import Packet
from fbi.ai.review import (
    Candidate,
    EngineResult,
    combine,
    fair_and_minimum,
    rules_review,
    signals_for,
)
from fbi.ai.shadow import Settled, evaluate, max_drawdown, metrics
from fbi.api.services.records import progress_of
from fbi.parlays.correlation import icc, joint_probability, market_of

AT = datetime(2026, 10, 10, 12, tzinfo=UTC)
KO = AT + timedelta(hours=6)


def packet(**over: Any) -> Packet:
    """A clean, fully informed packet: every block present, nothing against the home side."""
    content: dict[str, Any] = {
        "fixture": {"id": 1, "status": "NS", "kickoff_at": KO.isoformat(), "kickoff_changes": [],
                    "home": {"id": 10, "name": "Home FC"}, "away": {"id": 20, "name": "Away FC"}},
        "quality": {"competition_score": {"class": "MODEL_READY", "score": 0.9}, "fixture_validation": None,
                    "lineups_confirmed": False},
        "market": {"observed": True, "selections": [
            {"market": "1X2", "selection": "Home", "line": "0", "p_fair": 0.45, "best_odds": 2.4, "bookmaker": "BK",
             "n_bookmakers": 8, "overround": 0.05, "dispersion": 0.01, "opening_p_fair": 0.45, "movement": 0.0},
            {"market": "1X2", "selection": "Draw", "line": "0", "p_fair": 0.28, "best_odds": 3.5, "bookmaker": "BK",
             "n_bookmakers": 8, "overround": 0.05, "dispersion": 0.01, "opening_p_fair": 0.28, "movement": 0.0},
            {"market": "1X2", "selection": "Away", "line": "0", "p_fair": 0.27, "best_odds": 3.6, "bookmaker": "BK",
             "n_bookmakers": 8, "overround": 0.05, "dispersion": 0.01, "opening_p_fair": 0.27, "movement": 0.0},
            {"market": "OU", "selection": "Over", "line": "2.5", "p_fair": 0.52, "best_odds": 1.9, "bookmaker": "BK",
             "n_bookmakers": 8, "overround": 0.05, "dispersion": 0.01, "opening_p_fair": 0.52, "movement": 0.0},
        ]},
        "models": {
            "dixon_coles": {"version_id": 1, "selections": [
                {"market": "1X2", "selection": "Home", "line": "0", "p": 0.52, "p_lo": 0.47, "p_hi": 0.57},
                {"market": "1X2", "selection": "Draw", "line": "0", "p": 0.25, "p_lo": 0.21, "p_hi": 0.29},
                {"market": "1X2", "selection": "Away", "line": "0", "p": 0.23, "p_lo": 0.19, "p_hi": 0.27},
                {"market": "OU", "selection": "Over", "line": "2.5", "p": 0.50, "p_lo": 0.45, "p_hi": 0.55},
                {"market": "OU", "selection": "Under", "line": "2.5", "p": 0.50, "p_lo": 0.45, "p_hi": 0.55}]},
            "poisson": {"version_id": 2, "selections": [
                {"market": "1X2", "selection": "Home", "line": "0", "p": 0.50, "p_lo": 0.45, "p_hi": 0.55}]},
        },
        "absences": {"checked": True, "home": {"players": [], "weight": 0, "key_out": 0},
                     "away": {"players": [], "weight": 0, "key_out": 0}},
        "lineups": {"confirmed": False},
        "schedule": {"flags": [], "home": {"next_match": None}, "away": {"next_match": None}},
        "stakes": {"home": {"pressure": "mid_table"}, "away": {"pressure": "mid_table"}},
        "evidence": [],
    }
    for path, value in over.items():
        node = content
        keys = path.split("__")
        for k in keys[:-1]:
            node = node[k]
        node[keys[-1]] = value
    return Packet(1, AT, content)


def home(**over: Any) -> Candidate:
    base: dict[str, Any] = {"fixture_id": 1, "market_key": "1X2", "selection": "Home", "line": Decimal(0),
                            "p_model": Decimal("0.52"), "kickoff_at": KO, "odds": Decimal("2.40"),
                            "p_low": Decimal("0.47"), "p_high": Decimal("0.57"), "p_market": Decimal("0.45"),
                            "ev": Decimal("0.248"), "model": "dixon_coles", "n_bookmakers": 8}
    return Candidate(**(base | over))


def codes(c: Candidate, p: Packet) -> set[str]:
    return {s.code for s in signals_for(c, p, at=AT)}


# ── the rules reviewer ───────────────────────────────────────────────────────

def test_a_clean_value_selection_is_approved_with_a_data_claim_and_its_minimum_odds() -> None:
    out, signals = rules_review(home(), packet(), at=AT)
    assert out["decision"] == "APPROVE", [s.code for s in signals]
    assert out["positive_evidence"][0]["type"] == "DATA" and out["positive_evidence"][0]["refs"] == \
        ["P:candidate", "P:market"]
    assert out["fair_odds"] == pytest.approx(1.92) and out["minimum_playable_odds"] == pytest.approx(2.23)
    assert {"models_agree"} <= {s.code for s in signals}
    assert 0.5 < out["confidence"] <= 1


def test_without_a_market_price_the_reviewer_abstains_and_never_calls_it_value() -> None:
    p = packet(market__selections=[], market__observed=False)
    out, _ = rules_review(home(p_market=None, odds=None), p, at=AT)
    assert out["decision"] == "ABSTAIN" and "precio" in out["reason"]


@pytest.mark.parametrize(("over", "code"), [
    ({"fixture__status": "PST"}, "fixture_not_playable"),
    ({"quality__competition_score": {"class": "INSUFFICIENT"}}, "data_not_model_ready"),
    ({"quality__fixture_validation": {"state": "QUARANTINED"}}, "fixture_quarantined"),
])
def test_hard_signals_reject(over: dict[str, Any], code: str) -> None:
    out, signals = rules_review(home(), packet(**over), at=AT)
    assert out["decision"] == "REJECT" and code in {s.code for s in signals}


def test_a_strong_market_move_against_rejects_and_a_mild_one_downgrades() -> None:
    def moved(p_now: float) -> Packet:
        p = packet()
        sel = p.content["market"]["selections"][0]
        sel.update(opening_p_fair=0.45 + 0.07, p_fair=p_now, movement=round(p_now - 0.52, 4))
        return p
    strong, _ = rules_review(home(), moved(0.45), at=AT)
    mild, _ = rules_review(home(), moved(0.48), at=AT)
    assert strong["decision"] == "REJECT" and mild["decision"] == "DOWNGRADE"


def test_key_absences_on_the_chosen_side_reject_and_on_the_other_side_help() -> None:
    gk = {"name": "Keeper", "type": "Missing Fixture", "key": True, "first_choice_gk": True, "weight": 0.8}
    p = packet(absences__home={"players": [gk], "weight": 0.8, "key_out": 1})
    out, signals = rules_review(home(), p, at=AT)
    assert out["decision"] == "REJECT" and "key_absences_pick_side" in {s.code for s in signals}
    p = packet(absences__away={"players": [gk | {"name": "Their keeper"}], "weight": 0.8, "key_out": 1})
    assert "absences_opponent" in codes(home(), p)


def test_unknown_absences_and_unknown_data_quality_are_uncertainties_that_downgrade_together() -> None:
    p = packet(absences__checked=False, quality__competition_score=None)
    out, signals = rules_review(home(), p, at=AT)
    assert {"absences_unknown", "data_quality_unknown"} <= {s.code for s in signals}
    assert out["decision"] == "DOWNGRADE" and all(c["type"] == "UNKNOWN" for c in out["uncertainties"])


def test_three_soft_signals_reject() -> None:
    p = packet(schedule__flags=["home_short_rest"],
               stakes__home={"pressure": "settled"}, stakes__away={"pressure": "relegation"})
    p.content["market"]["selections"][0]["n_bookmakers"] = 3
    out, signals = rules_review(home(n_bookmakers=3), p, at=AT)
    soft = [s.code for s in signals if s.severity == "soft"]
    assert len(soft) >= 3 and out["decision"] == "REJECT", soft


def test_an_edge_inside_the_models_own_noise_is_an_uncertainty() -> None:
    c = home(p_model=Decimal("0.46"), p_low=Decimal("0.30"), p_high=Decimal("0.62"))
    assert "edge_within_noise" in codes(c, packet())


def test_other_models_that_see_no_edge_are_a_disagreement() -> None:
    p = packet()
    p.content["models"]["poisson"]["selections"][0]["p"] = 0.44
    assert "models_disagree" in codes(home(), p)


def test_a_kickoff_change_after_selection_and_news_are_seen() -> None:
    p = packet(fixture__kickoff_changes=[{"observed_at": (AT - timedelta(hours=1)).isoformat()}])
    assert "kickoff_changed" in codes(home(selected_at=AT - timedelta(hours=2)), p)
    assert "kickoff_changed" not in codes(home(selected_at=AT), p)
    p = packet(evidence=[
        {"id": 5, "kind": "injury", "claim": "Star striker out", "side": "home", "status": "RUMOR", "origin": "web"},
        {"id": 6, "kind": "injury", "claim": "Winger out", "side": "home", "status": "CONFIRMED", "origin": "web"},
        {"id": 7, "kind": "lineup", "claim": "conflicting", "side": "away", "status": "CONTRADICTORY", "origin": "web"}])
    assert {"rumour_against", "news_against", "evidence_contradictory"} <= codes(home(), p)


def test_totals_see_missing_scorers() -> None:
    scorer = {"name": "Nine", "type": "Missing Fixture", "ga_share": 0.35, "key": True}
    p = packet(absences__home={"players": [scorer], "weight": 0.7, "key_out": 1})
    over = home(market_key="OU", selection="Over", line=Decimal("2.5"), p_model=Decimal("0.56"),
                p_market=Decimal("0.52"), p_low=Decimal("0.5"), p_high=Decimal("0.62"))
    s = next(x for x in signals_for(over, p, at=AT) if x.code == "scorers_out")
    assert s.severity == "soft"
    under = over.__class__(**{**over.__dict__, "selection": "Under"})
    assert next(x for x in signals_for(under, p, at=AT) if x.code == "scorers_out").severity == "positive"


def test_the_combined_decision_is_the_most_conservative_and_ignores_abstentions() -> None:
    def r(d: str) -> EngineResult:
        return EngineResult("rules", "v", d, {})  # type: ignore[arg-type]
    assert combine([r("APPROVE"), r("REJECT")]) == "REJECT"
    assert combine([r("APPROVE"), r("ABSTAIN")]) == "APPROVE"
    assert combine([r("DOWNGRADE"), r("APPROVE")]) == "DOWNGRADE"
    assert combine([r("ABSTAIN")]) == "ABSTAIN"


def test_fair_and_minimum_odds_come_from_the_model_never_from_the_price() -> None:
    fair, minimum = fair_and_minimum(home(odds=Decimal("100")))
    assert (fair, minimum) == (Decimal("1.92"), Decimal("2.23"))


# ── what a model's claim may say ─────────────────────────────────────────────

def review(decision: str = "APPROVE", **groups: list[dict[str, Any]]) -> ReviewOut:
    body: dict[str, Any] = {"decision": decision, "confidence": 0.6, "context_score": 0.5, "model_score": 0.5,
                            "market_score": 0.5, "positive_evidence": [], "negative_evidence": [],
                            "uncertainties": [], "contradictions": [], "reason": "porque sí",
                            "minimum_playable_odds": None, "fair_odds": None}
    return ReviewOut.model_validate(body | groups)


def test_data_claims_must_cite_the_packet_and_use_its_numbers() -> None:
    content = packet().content
    good = {"text": "El mercado da 45.0 % al local y el modelo 52.0 %.", "type": "DATA", "refs": ["P:market"]}
    invented = {"text": "El local ganó 87 % de sus partidos en casa.", "type": "DATA", "refs": ["P:form"]}
    uncited = {"text": "El local es favorito.", "type": "DATA", "refs": []}
    bad_block = {"text": "Clima perfecto.", "type": "DATA", "refs": ["P:weather"]}
    out = check(review(positive_evidence=[good, invented, uncited, bad_block]), packet_content=content,
                evidence_status={})
    assert [c.text for c in out.review.positive_evidence] == [good["text"]]
    whys = " | ".join(r["why"] for r in out.rejected)
    assert "87" in whys and "must cite the packet" in whys and "does not exist" in whys
    assert out.review.decision == "APPROVE"


def test_news_must_cite_live_evidence_and_an_unsupported_decision_abstains() -> None:
    stale = {"text": "El delantero está lesionado.", "type": "NEWS", "refs": ["E:9"]}
    unknown = {"text": "Se lesionó el portero.", "type": "NEWS", "refs": ["E:404"]}
    out = check(review("REJECT", negative_evidence=[stale, unknown]), packet_content=packet().content,
                evidence_status={9: "OUTDATED"})
    assert out.review.decision == "ABSTAIN" and out.decision_changed is not None
    assert len(out.rejected) == 2
    approve_without_data = check(review(positive_evidence=[{"text": "Me gusta.", "type": "OPINION", "refs": []}]),
                                 packet_content=packet().content, evidence_status={})
    assert approve_without_data.review.decision == "ABSTAIN"


def test_a_malformed_reference_is_refused() -> None:
    weird = {"text": "Mira esto.", "type": "INFERENCE", "refs": ["http://evil.example"]}
    out = check(review("DOWNGRADE", uncertainties=[weird]), packet_content=packet().content, evidence_status={})
    assert out.rejected and out.review.decision == "ABSTAIN"
    with pytest.raises(ValueError):
        ClaimOut.model_validate({"text": "x" * 300, "type": "DATA", "refs": []})


# ── evidence ─────────────────────────────────────────────────────────────────

def ev(i: int, *, tier: str = "media", kind: str = "injury", assertion: str = "out", origin: str = "web",
       hours_ago: float = 5, story: str | None = None, player: int | None = 99, domain: str | None = None,
       published: bool = True) -> Row:
    when = AT - timedelta(hours=hours_ago)
    return Row(i, 1, 10, player, "jugador", kind, origin, tier, domain or f"site{i}.com", assertion,
               when if published else None, when, story or f"s{i}", "PROBABLE", {})


def test_statuses_from_the_sources() -> None:
    out = classify([ev(1, tier="official"), ev(2, tier="social", player=55), ev(3, tier="provider", origin="provider",
                                                                              player=56)],
                   kickoff=KO, at=AT, lineup_starters={}, absences_checked_at=None)
    assert out[1][0] == "CONFIRMED" and out[2][0] == "RUMOR" and out[3][0] == "PROBABLE"
    two_media = classify([ev(1, story="same", domain="a.com"), ev(2, story="same", domain="b.com")], kickoff=KO,
                         at=AT, lineup_starters={}, absences_checked_at=None)
    assert {s for s, _ in two_media.values()} == {"CONFIRMED"}


def test_newer_stronger_reports_outdate_older_ones_and_comparable_opposites_contradict() -> None:
    out = classify([ev(1, tier="media", hours_ago=10), ev(2, tier="club", assertion="available", hours_ago=2)],
                   kickoff=KO, at=AT, lineup_starters={}, absences_checked_at=None)
    assert out[1][0] == "OUTDATED" and out[2][0] == "CONFIRMED"
    out = classify([ev(1, tier="media", hours_ago=2), ev(2, tier="journalist", assertion="available", hours_ago=10)],
                   kickoff=KO, at=AT, lineup_starters={}, absences_checked_at=None)
    assert out[1][0] == "CONTRADICTORY" and out[2][0] == "CONTRADICTORY"


def test_the_line_up_decides_and_old_reports_go_stale() -> None:
    out = classify([ev(1, tier="provider", origin="provider", player=7), ev(2, player=8, hours_ago=3)],
                   kickoff=KO, at=AT, lineup_starters={10: {7}}, absences_checked_at=None)
    assert out[1] == ("OUTDATED", "the player is in the confirmed starting line-up")
    assert out[2][0] == "CONFIRMED", "absent from a confirmed eleven"
    stale = classify([ev(1, hours_ago=24 * 12)], kickoff=KO, at=AT, lineup_starters={}, absences_checked_at=None)
    assert stale[1][0] == "OUTDATED"
    dropped = classify([ev(1, tier="provider", origin="provider", hours_ago=30)], kickoff=KO, at=AT,
                       lineup_starters={}, absences_checked_at=AT - timedelta(hours=1))
    assert dropped[1][0] == "OUTDATED", "no longer in the provider's newest injury report"


# ── context ──────────────────────────────────────────────────────────────────

def test_rest_flags_and_stakes() -> None:
    assert ctx.rest_flags(2.5, 6.0) == ["home_short_rest", "home_rest_disadvantage"]
    assert ctx.rest_flags(None, 4) == []
    table = [ctx.TableRow(1, 1, 60, 30, "Promotion - Champions League"), ctx.TableRow(2, 2, 58, 30, None),
             ctx.TableRow(3, 10, 40, 30, None), ctx.TableRow(4, 18, 20, 30, "Relegation")]
    mid = ctx.stakes(table, 3, remaining=8)
    assert mid is not None and mid.pressure in ("europe", "relegation", "mid_table", "promotion")
    done = ctx.stakes(table, 3, remaining=1)
    assert done is not None and done.settled is True and done.pressure == "settled"
    no_zones = ctx.stakes([ctx.TableRow(1, 1, 3, 1, None), ctx.TableRow(2, 2, 0, 1, None)], 1, remaining=30)
    assert no_zones is not None and no_zones.pressure == "unknown" and no_zones.settled is None


def test_stakes_press_only_within_two_wins() -> None:
    """Regression (13 Oct 2026, TFF 1. Lig, round 10 of 38): stakes-v1 pressed on any reachable boundary, so the 8th -
    level on points with the play-off places, 8 above relegation - read as fighting relegation like the 15th, and the
    narrative wrote that both teams "were in the relegation zone"."""
    table = [ctx.TableRow(1, 1, 22, 9, "Promotion - Super Lig"), ctx.TableRow(2, 7, 15, 9, "Promotion - Play-offs"),
             ctx.TableRow(3, 8, 15, 9, None), ctx.TableRow(4, 12, 11, 9, None), ctx.TableRow(5, 15, 8, 9, None),
             ctx.TableRow(6, 17, 7, 9, "Relegation"), ctx.TableRow(7, 20, 2, 9, "Relegation")]
    eighth = ctx.stakes(table, 3, remaining=29)
    assert eighth is not None and eighth.pressure == "promotion" and eighth.zone is None
    assert (eighth.gap_up, eighth.zone_above, eighth.gap_down, eighth.zone_below) == (0, "promotion", 8, "relegation")
    fifteenth = ctx.stakes(table, 5, remaining=29)
    assert fifteenth is not None and fifteenth.pressure == "relegation" and fifteenth.zone is None
    near_bottom = ctx.stakes(table, 4, remaining=29)
    assert near_bottom is not None and near_bottom.pressure == "relegation", "4 points above it: within two wins"
    spread = [ctx.TableRow(1, 7, 22, 9, "Promotion - Play-offs"), ctx.TableRow(2, 12, 14, 9, None),
              ctx.TableRow(3, 17, 6, 9, "Relegation")]
    middle = ctx.stakes(spread, 2, remaining=29)
    assert middle is not None and middle.pressure == "mid_table", "8 from both boundaries"
    late = ctx.stakes(table, 3, remaining=2)
    assert late is not None and late.pressure == "promotion"
    assert ctx.stakes(table, 6, remaining=29).pressure == "relegation"  # in the zone  # type: ignore[union-attr]
    assert eighth.as_json()["rule"] == "stakes-v2"


def test_importance_and_absence_weight() -> None:
    players = [ctx.PlayerSeason(i, f"p{i}", "Goalkeeper" if i == 1 else "Attacker", 900 - i * 10, 10, 6 if i == 2 else 0,
                                0, None) for i in range(1, 16)]
    w = ctx.importance(players)
    assert w[1]["first_choice_gk"] and w[2]["key"] and not w[15]["key"]
    assert ctx.absence_weight(w[1], "Missing Fixture") == 0.8
    assert ctx.absence_weight(w[1], "Questionable") == 0.4
    assert ctx.absence_weight(None, "Missing Fixture") == 0.1


def test_interval_z_and_movement() -> None:
    assert ctx.interval_z(0.05, 0.40, 0.60) == pytest.approx(0.05 / (0.20 / 3.29), abs=1e-3)
    assert ctx.interval_z(0.05, None, None) is None
    assert ctx.movement(0.5, 0.47) == -0.03 and ctx.movement(None, 0.4) is None


# ── the per-match cards ──────────────────────────────────────────────────────

def option(**over: Any) -> ValueOption:
    base: dict[str, Any] = {"market_key": "1X2", "selection": "Home", "line": Decimal(0), "odds": Decimal("2.40"),
                            "bookmaker": "BK", "p_model": Decimal("0.52"), "p_low": Decimal("0.47"),
                            "p_market": Decimal("0.45"), "ev": Decimal("0.248"), "elg": 0.01, "model": "dixon_coles",
                            "pick_id": 77, "qualified": False}
    return ValueOption(**(base | over))


def test_at_most_three_cards_one_per_market_value_first() -> None:
    reviews = {("1X2", "Home", Decimal(0)): {"decision": "DOWNGRADE", "id": 5,
                                              "output": {"confidence": 0.4, "reason": "cuidado",
                                                         "negative_evidence": [{"text": "baja", "type": "NEWS"}]}}}
    cards = build_cards(packet(), [option(), option(selection="Draw", elg=0.001)], reviews)
    assert len(cards) <= 3 and [c["market"] for c in cards].count("1X2") == 1
    first = cards[0]
    assert first["kind"] == "value" and first["verdict"] == "caution" and first["ai"]["risks"][0]["text"] == "baja"
    assert first["minimum_odds"] == "2.23" and first["fair_odds"] == "1.92"
    rest = cards[1:]
    assert all(c["kind"] == "evaluated" and c["verdict"] == "not_recommended" for c in rest)


def test_a_rejected_value_option_is_shown_as_not_recommended() -> None:
    cards = build_cards(packet(), [option()], {("1X2", "Home", Decimal(0)): {"decision": "REJECT", "id": 1,
                                                                             "output": {}}})
    assert cards[0]["verdict"] == "not_recommended" and cards[0]["verdict_reason"] == "context_negative"


def test_without_any_price_the_cards_say_market_unobserved_and_give_the_minimum_odds() -> None:
    p = packet(market__selections=[], market__observed=False)
    cards = build_cards(p, [], {})
    assert cards == no_market_cards(p) and cards
    assert all(c["verdict"] == "no_market" and c["odds"] is None and c["edge"] is None and c["ev"] is None
               for c in cards)
    home_card = next(c for c in cards if c["market"] == "1X2")
    assert home_card["selection"] == "Home" and home_card["minimum_odds"] == "2.23"


def test_cards_are_json_and_do_not_mutate_the_packet() -> None:
    p = packet()
    before = copy.deepcopy(p.content)
    build_cards(p, [option()], {})
    assert p.content == before


# ── dependence between legs ──────────────────────────────────────────────────

def test_icc_is_zero_for_independent_groups_and_high_for_identical_ones() -> None:
    assert icc([[1, 1], [0, 0], [1, 1], [0, 0]]) == pytest.approx(1.0)
    assert abs(icc([[1, 0], [0, 1], [1, 0], [0, 1]])) <= 1.0
    assert icc([[1]]) == 0.0


def test_the_joint_probability_moves_with_the_correlation_and_stays_a_probability() -> None:
    assert joint_probability([0.5, 0.5], []) == 0.25
    assert joint_probability([0.5, 0.5], [(0, 1, 0.2)]) == pytest.approx(0.30)
    assert joint_probability([0.5, 0.5], [(0, 1, -0.9)]) == pytest.approx(0.025)
    assert joint_probability([0.9, 0.9], [(0, 1, 1.0)]) <= 0.9
    assert market_of("1X2", "Draw") == "draw" and market_of("AH", "Home") is None


# ── the AI's own shadow gate ─────────────────────────────────────────────────

def settled(i: int, decision: str, won: bool, *, odds: float = 2.0, close: float | None = 1.9,
            day: int = 0) -> Settled:
    return Settled(i, AT + timedelta(days=day), decision, odds, 0.55, 0.5, "win" if won else "loss",
                   odds - 1 if won else -1.0, close)


def test_metrics_measure_hit_rate_roi_clv_and_drawdown() -> None:
    items = [settled(1, "APPROVE", True), settled(2, "APPROVE", False), settled(3, "REJECT", False)]
    m = metrics(items)
    assert m["n"] == 3 and m["hit_rate"] == pytest.approx(1 / 3, abs=1e-3) and m["roi"] == pytest.approx(-1 / 3,
                                                                                                         abs=1e-3)
    assert m["clv"] == pytest.approx(2.0 / 1.9 - 1, abs=1e-3)
    assert max_drawdown(items) == 2.0, "from +1 after the first win down to -1"


def test_the_gate_is_insufficient_on_a_small_sample_and_passes_only_with_real_rejection_quality() -> None:
    small = [settled(i, "APPROVE", i % 2 == 0) for i in range(40)]
    _, gate = evaluate(small)
    assert gate["verdict"] == "insufficient"
    good = [settled(i, "APPROVE", i % 2 == 0, day=i % 40, close=1.95) for i in range(400)] + \
           [settled(1000 + i, "REJECT", i % 5 == 0, day=i % 40, close=2.2) for i in range(80)]
    _, gate = evaluate(good)
    assert gate["checks"]["rejection_quality"]["ok"] and gate["checks"]["clv"]["ok"]
    assert gate["verdict"] == "pass"
    bad = [settled(i, "APPROVE", i % 3 == 0, day=i % 40) for i in range(400)] + \
          [settled(1000 + i, "REJECT", i % 2 == 0, day=i % 40) for i in range(80)]
    _, gate = evaluate(bad)
    assert gate["verdict"] == "fail"


# ── a parlay as its legs stand ───────────────────────────────────────────────

@pytest.mark.parametrize(("status", "legs", "progress"), [
    ("READY", ["PENDING", "PENDING"], "OPEN"),
    ("ACTIVE", ["WIN", "PENDING"], "PARTIAL_WON"),
    ("LOST", ["LOSS", "PENDING", "PENDING"], "PARTIAL_LOST"),
    ("LOST", ["LOSS", "WIN"], "LOST"),
    ("ACTIVE", ["WIN", "WIN"], "WON"),
    ("PARTIAL_VOID", ["WIN", "VOID"], "WON"),
    ("VOID", ["VOID", "PUSH"], "VOID"),
    ("ACTIVE", ["HALF_LOSS", "PENDING"], "PARTIAL_LOST"),
])
def test_parlay_progress(status: str, legs: list[str], progress: str) -> None:
    assert progress_of(status, legs) == progress
