"""``council-research-v1`` without a database: ONE round per match, only for a material contradiction on a selection worth it."""

from __future__ import annotations

from decimal import Decimal

from fbi.ai import router
from fbi.council import contradictions as c
from fbi.council import research_round as r
from fbi.intel import decision

D = Decimal


def pos(agent: str, stance: str, drivers: tuple[str, ...], *, run_id: int, candidate: str = "c1") -> c.Position:
    return c.Position(agent, f"{agent}-v2", f"{agent}_evaluation", candidate, stance, drivers, (), (), run_id, D(1))


def case(*, ev: str | None = "0.05", edge: str | None = "0.04", contra: tuple[str, ...] = (), key: str = "c1",
         positions: tuple[c.Position, ...] | None = None, market: c.Market | None = None) -> r.Case:
    p_model, p_market = (None, None) if edge is None else (D("0.55"), D("0.50"))
    s = c.Selection(key, "1X2", "1X2", "Home", D(0), p_model, p_market, None if edge is None else D(edge), None if ev is None else D(ev), contra)
    ps = positions if positions is not None else (pos("match", "SUPPORT", ("ABSENCES",), run_id=1, candidate=key),
                                                   pos("stats", "CONCERN", ("LINEUP",), run_id=2, candidate=key))
    return r.Case(s, c.detect(s, ps, market or c.Market("ok", 0.0, stale=False)), ps)


def test_the_thresholds_are_the_decision_layers_and_the_routers() -> None:
    assert Decimal(str(decision.EV_MIN)) == r.MIN_EV and Decimal(str(decision.EDGE_MIN)) == r.MIN_EDGE
    assert router.PARAMS["research_min_minutes"] == r.MIN_MINUTES
    assert r.TOPICS == ("availability", "confirmation", "preview")
    assert set(r.TOPIC_OF_SIGNAL.values()) <= set(r.TOPICS)


def test_a_material_contradiction_on_a_selection_worth_it_warrants_one_round() -> None:
    got = r.decide([case()], minutes_to_kickoff=180)
    assert got.requested and got.candidates == ("c1",) and got.topics == ("availability", "confirmation")
    assert got.per_candidate[0].value_basis == "ev" and got.reasons == ("requested",)


def test_no_material_contradiction_no_round() -> None:
    agree = (pos("match", "SUPPORT", ("ABSENCES",), run_id=1), pos("stats", "SUPPORT", ("RATE",), run_id=2))
    got = r.decide([case(positions=agree)], minutes_to_kickoff=180)
    assert not got.requested and got.topics == () and "no_material_contradiction" in got.per_candidate[0].reasons
    unweighted = (c.Position("match", "match-v2", "match_evaluation", "c1", "SUPPORT", ("ABSENCES",), (), (), 1, D(0)),
                  c.Position("stats", "stats-v2", "stats_evaluation", "c1", "CONCERN", ("LINEUP",), (), (), 2, D(0)))
    assert not r.decide([case(positions=unweighted)], minutes_to_kickoff=180).requested, "voices that weigh nothing are not material"


def test_the_value_at_stake_must_clear_the_bar() -> None:
    low = r.decide([case(ev="0.01")], minutes_to_kickoff=180)
    assert not low.requested and "value_below_ev_threshold" in low.per_candidate[0].reasons
    by_edge = r.decide([case(ev=None, edge="0.02")], minutes_to_kickoff=180)
    assert by_edge.requested and by_edge.per_candidate[0].value_basis == "edge", "without an ev the edge is read"
    none = r.decide([case(ev=None, edge=None)], minutes_to_kickoff=180)
    assert not none.requested and "no_value_measure" in none.per_candidate[0].reasons


def test_evidence_in_conflict_is_material_by_itself_and_asks_a_confirmation() -> None:
    quiet = (pos("match", "NEUTRAL", (), run_id=1),)
    got = r.decide([case(positions=quiet, contra=("C07",))], minutes_to_kickoff=180)
    assert got.requested and got.topics == ("confirmation",)


def test_a_round_too_close_to_the_kickoff_or_with_no_kickoff_is_not_requested() -> None:
    late = r.decide([case()], minutes_to_kickoff=r.MIN_MINUTES - 1)
    assert not late.requested and late.reasons == ("too_close_to_kickoff",) and late.per_candidate[0].warranted
    assert r.decide([case()], minutes_to_kickoff=r.MIN_MINUTES).requested
    assert r.decide([case()], minutes_to_kickoff=None).reasons == ("kickoff_unknown",)


def test_a_contradiction_no_topic_of_the_catalogue_can_settle_asks_nothing() -> None:
    numbers = (pos("match", "SUPPORT", ("FORM",), run_id=1), pos("stats", "CONCERN", ("H2H",), run_id=2))
    got = r.decide([case(positions=numbers)], minutes_to_kickoff=180)
    assert not got.requested and "no_topic_in_the_catalogue" in got.per_candidate[0].reasons


def test_the_market_moving_against_a_stance_asks_who_can_play() -> None:
    ps = (pos("match", "SUPPORT", ("FORM",), run_id=1),)
    got = r.decide([case(positions=ps, market=c.Market("ok", -5.0, stale=False))], minutes_to_kickoff=180)
    assert got.requested and got.topics == ("availability",)


def test_one_round_per_match_with_at_most_two_topics_in_the_catalogues_order() -> None:
    a = case(key="c1", positions=(pos("match", "SUPPORT", ("STAKES",), run_id=1, candidate="c1"),
                                  pos("stats", "CONCERN", ("TACTICS",), run_id=2, candidate="c1")))
    b = case(key="c2", positions=(pos("match", "SUPPORT", ("NEWS",), run_id=1, candidate="c2"),
                                  pos("stats", "CONCERN", ("ABSENCES",), run_id=2, candidate="c2")))
    d = case(key="c3", positions=(pos("match", "SUPPORT", ("SCHEDULE",), run_id=1, candidate="c3"),
                                  pos("stats", "CONCERN", ("LINEUP",), run_id=2, candidate="c3")))
    got = r.decide([d, b, a], minutes_to_kickoff=180)
    assert got.requested and got.candidates == ("c1", "c2", "c3")
    assert len(got.topics) == r.TOPICS_MAX and got.topics == ("confirmation", "preview"), "the two most asked, in the catalogue's order"
    assert r.decide([a, b, d], minutes_to_kickoff=180) == got, "the order the cases come in changes nothing"
