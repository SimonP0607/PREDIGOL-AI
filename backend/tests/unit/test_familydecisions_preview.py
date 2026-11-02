"""Plan F11 - what a pass of the families would do, said before the switch is on (``fbi.familydecisions.preview``): the shape of a decision as the
preview says it, what the decisions lack added up the way the cost would add up, the order, and the text.

The pass itself, as a dry run in a real database, and the command line that prints this are in tests/integration/test_familydecisions_decide.py and
tests/unit/test_families_cli.py."""

from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest

from fbi.familydecisions import decide as fd
from fbi.familydecisions import preview, research
from fbi.intel import decision
from fbi.intel import stake as staking
from fbi.intel.score import Score

from .test_familydecisions_decide import AT, FIXTURE, KICKOFF, KNOWN_AT, STANDING, keyed, priced

D = Decimal
NO_FACTS = research.Facts(None, None, "LIMITED")
"""Nothing known of the match: no referee, no line-ups, and the outside world read and found nothing."""


def decided(*, fixture: int = 1, key: str = "CORNERS_OU", line: str = "9.5", selection: str = "Over", family: str = "CORNERS",
            model: str = "family-corners_ft", odds: float = 2.05, p: float = 0.55, state: str = "INVESTIGACION",
            facts: research.Facts | None = NO_FACTS, reasons: tuple[str, ...] = ("not_calibrated",), home: str = "Home FC",
            kickoff_in: timedelta = timedelta(0)) -> decision.Evaluated:
    """A decision of a family as the pass hands it over: the candidate's own row, the filters the judge wrote and the ones the family adds."""
    row = {**FIXTURE, "kickoff_at": KICKOFF + kickoff_in, "home_name": home}
    found = fd.candidates([fd.Forecast(100 + fixture, fixture, family, model, 7, key, D(line), selection, p, p, None, None, "UNCALIBRATED",
                                       AT - timedelta(hours=5), AT - timedelta(hours=5), row)],
                          keyed(fixture, key, line, selection, priced(odds)), {})
    [c] = found
    filters = [decision._f("model", True, f"{model}: p {p:.3f}", n=2, model=model, model_version_id=7),
               decision._f("calibration", False, "sin calibrador para este mercado y modelo", "INVESTIGACION", 4),
               decision._f("final", False, f"{state}: x", state, 10)]
    ev = odds * p - 1
    e = decision.Evaluated(c.key, c.row() | {"model_used": model}, "T-24h", state, list(reasons), filters, None, None, None, ev, None, None, None, None,
                           staking.stake_for(state, None, odds, 0.0), decision.Context("LIMITED"))
    return fd.finalise(e, c, fd.SPECS[family], facts=facts, standing=STANDING)


def rejected_by_the_market() -> decision.Evaluated:
    e = decided(state="RECHAZADO", reasons=("thin_market",))
    e.filters.append(decision._f("market", False, "solo 2 casas", "RECHAZADO", 3, n_bookmakers=2))
    e.filters.sort(key=lambda f: f["n"])
    return e


# ── a decision, as the preview says it ───────────────────────────────────────────────────────────────────────────

def test_a_decision_says_the_match_what_the_model_and_the_books_said_and_what_it_did_not_know() -> None:
    x = preview.line_of(decided(facts=research.Facts(KNOWN_AT, None, "PENDING")))
    assert (x["fixture_id"], x["home"], x["away"], x["competition"]) == (1, "Home FC", "B", "League")
    assert x["kickoff_at"] == KICKOFF.isoformat()
    assert (x["family"], x["model"], x["market"], x["selection"], x["line"]) == ("CORNERS", "family-corners_ft", "CORNERS_OU", "Over", 9.5)
    assert (x["p_model"], x["p_market"], x["odds"], x["books"]) == (0.55, 0.5, 2.05, 3)
    assert x["value"] == pytest.approx(2.05 * 0.55 - 1, abs=1e-6), "the value the family saw: the number that made it a candidate"
    assert (x["state"], x["reasons"], x["stake"], x["context"], x["score"]) == ("INVESTIGACION", ["not_calibrated", "family_research"], 0.0, "LIMITED", None)
    ask = x["research"]
    assert ask["open"] == ["lineups", "context"] and ask["levels"] == [1, 2, 3] and ask["searches"] == 3 and ask["served"] is False
    assert ask["said"].startswith("pedir investigación: le falta las alineaciones confirmadas")


def test_a_decision_with_no_request_for_research_says_so_rather_than_that_it_lacks_nothing() -> None:
    x = preview.line_of(decided(facts=None))
    assert x["research"] is None, "the pass could not read the referees: it wrote no request, and a request of nothing missing is another thing"
    done = preview.line_of(decided(facts=research.Facts(KNOWN_AT, KNOWN_AT, "FULL")))
    assert done["research"]["open"] == [] and done["research"]["searches"] == 0 and done["research"]["levels"] == []
    assert "no le falta nada" in done["research"]["said"]


def test_the_filters_that_failed_are_listed_with_what_they_did() -> None:
    x = preview.line_of(rejected_by_the_market())
    assert {f["filter"] for f in x["failed"]} == {"calibration", "market", "final"}
    market = next(f for f in x["failed"] if f["filter"] == "market")
    assert market == {"filter": "market", "why": "solo 2 casas", "effect": "RECHAZADO"}
    assert all(f["filter"] != "model" for f in x["failed"]), "a filter that passed is not a failure"


def test_the_value_is_the_one_the_family_wrote_and_the_judges_when_it_wrote_none() -> None:
    e = decided()
    e.ev_raw = 0.9  # the judge's own number is not the one that made the selection a candidate
    assert preview.line_of(e)["value"] == pytest.approx(2.05 * 0.55 - 1, abs=1e-6)
    e.filters = [f for f in e.filters if f["key"] != "family"]
    e.ev_raw = 0.25
    assert preview.line_of(e)["value"] == 0.25 and preview.line_of(e)["family"] is None
    e.ev_raw = None
    assert preview.line_of(e)["value"] is None


def test_the_score_the_stake_and_the_context_are_the_judges() -> None:
    e = decided()
    e.score = Score(total=71.5)
    e.stake = staking.Stake(units=0.5, kelly=0.1, fraction=0.25, cap=1.0, capped=False)
    e.context = decision.Context("FULL")
    x = preview.line_of(e)
    assert (x["score"], x["stake"], x["context"]) == (71.5, 0.5, "FULL")


# ── what they lack, added up ─────────────────────────────────────────────────────────────────────────────────────

def test_the_searches_of_one_match_are_united_and_the_searches_of_two_matches_are_added() -> None:
    cards = decided(fixture=1, key="CARDS_OU", line="4.5", family="CARDS", model="family-cards_lines_ft")
    corners = decided(fixture=1)
    other = decided(fixture=2)
    lines = [preview.line_of(e) for e in (cards, corners, other)]
    assert lines[0]["research"]["open"] == ["referee", "context"] and lines[1]["research"]["open"] == ["lineups", "context"]
    assert lines[0]["research"]["searches"] == lines[1]["research"]["searches"] == 3
    got = preview.lacking(lines)
    assert got["asked"] == 3 and got["needs"] == {"context": 3, "lineups": 2, "referee": 1}
    assert list(got["needs"]) == ["context", "lineups", "referee"], "alphabetical, whatever the order they were asked in: the same pass reads the same"
    assert got["matches"] == 2 and got["searches"] == 6, "three searches for match 1 whatever the number of its selections, and three for match 2"


def test_a_match_with_nothing_to_search_costs_nothing_and_a_decision_with_no_request_is_not_counted() -> None:
    full = preview.line_of(decided(fixture=1, facts=research.Facts(KNOWN_AT, KNOWN_AT, "FULL")))
    none = preview.line_of(decided(fixture=2, facts=None))
    only_provider = preview.line_of(decided(fixture=3, family="CARDS", key="CARDS_OU", line="4.5", model="family-cards_lines_ft",
                                            facts=research.Facts(None, None, "FULL")))
    assert only_provider["research"]["open"] == ["referee"] and only_provider["research"]["searches"] == 0, "the referee arrives from the provider: no search"
    got = preview.lacking([full, none, only_provider])
    assert got == {"asked": 2, "needs": {"referee": 1}, "matches": 0, "searches": 0}
    assert preview.lacking([]) == {"asked": 0, "needs": {}, "matches": 0, "searches": 0}


# ── the summary ──────────────────────────────────────────────────────────────────────────────────────────────────

def report_of(*, evaluated: int = 3, would_write: int = 2, errors: list[str] | None = None, **kw: Any) -> fd.FamilyReport:
    base: dict[str, Any] = {"forecasts": 40, "fixtures": 4, "priced_selections": 25, "candidates": 3, "evaluated": evaluated, "written": 0,
                            "failed": len(errors or []), "by_family": {"CORNERS": 2, "CARDS": 1}, "by_state": {"INVESTIGACION": 2, "RECHAZADO": 1},
                            "by_reason": {"family_research": 3, "family_shadow_only": 2, "not_calibrated": 2, "thin_market": 1}, "errors": errors or [],
                            "would_write": would_write}
    return fd.FamilyReport(**{**base, **kw})


def three() -> list[decision.Evaluated]:
    return [decided(fixture=2, odds=2.20), decided(fixture=1, odds=2.60), rejected_by_the_market()]


def test_the_summary_orders_the_decisions_by_the_value_they_saw_and_then_by_match_so_that_a_pass_reads_the_same() -> None:
    a, b, c = decided(fixture=2, odds=2.20), decided(fixture=1, odds=2.60), decided(fixture=3, odds=2.20)
    s = preview.summarise(report_of(), [a, b, c], at=AT, horizon=timedelta(hours=36), mode="shadow")
    assert [x["fixture_id"] for x in s["decisions"]] == [1, 2, 3], "2.60 x 0.55 sees more than 2.20 x 0.55, and a tie goes by match"
    again = preview.summarise(report_of(), [c, a, b], at=AT, horizon=timedelta(hours=36), mode="shadow")
    assert again == s
    unknown = decided(fixture=9)
    unknown.filters = [f for f in unknown.filters if f["key"] != "family"]
    unknown.ev_raw = None
    last = preview.summarise(report_of(), [unknown, a], at=AT, horizon=timedelta(hours=36), mode="shadow")["decisions"]
    assert [x["fixture_id"] for x in last] == [2, 9], "a decision whose value is not known goes last"


@pytest.mark.parametrize("first,second", [
    # the same value in the same match: by market first (the line of the market that comes later is the lower one), then by line, then by selection
    ({"key": "CARDS_OU", "line": "10.5", "family": "CARDS", "model": "family-cards_lines_ft"}, {"key": "CORNERS_OU", "line": "9.5"}),
    ({"line": "9.5"}, {"line": "10.5"}),
    ({"selection": "Over"}, {"selection": "Under"}),
])
def test_a_tie_in_value_goes_by_market_then_line_then_selection_whatever_the_order_the_decisions_came_in(first: dict[str, Any], second: dict[str, Any]) -> None:
    a, b = decided(fixture=1, odds=2.60, **first), decided(fixture=1, odds=2.60, **second)
    assert preview.line_of(a)["value"] == preview.line_of(b)["value"], "a tie is what this is about"
    want = [(x.get("key", "CORNERS_OU"), float(x.get("line", "9.5")), x.get("selection", "Over")) for x in (first, second)]
    for order in ([a, b], [b, a]):
        got = preview.summarise(report_of(), order, at=AT, horizon=timedelta(hours=36), mode="shadow")["decisions"]
        assert [(x["market"], x["line"], x["selection"]) for x in got] == want


def test_the_summary_carries_the_version_the_moment_the_window_the_switch_and_the_counts_of_the_report() -> None:
    s = preview.summarise(report_of(), three(), at=AT, horizon=timedelta(hours=36), mode="off")
    assert (s["version"], s["at"], s["horizon_hours"], s["mode"]) == (fd.VERSION, AT.isoformat(), 36.0, "off")
    assert s["report"] == {**report_of().as_dict(), "would_write": 2} and s["report"]["would_write"] == 2
    assert s["lacking"] == preview.lacking(s["decisions"]) and len(s["decisions"]) == 3
    assert preview.summarise(report_of(), [], at=AT, horizon=timedelta(hours=1.5), mode="shadow")["horizon_hours"] == 1.5


def test_the_summary_is_json() -> None:
    s = preview.summarise(report_of(), three(), at=AT, horizon=timedelta(hours=36), mode="shadow")
    assert json.loads(json.dumps(s))["decisions"][0]["market"] == "CORNERS_OU", "nothing in it needs a custom encoder"


# ── the text ─────────────────────────────────────────────────────────────────────────────────────────────────────

def text_of(evaluated: list[decision.Evaluated], report: fd.FamilyReport | None = None, *, top: int = 20, mode: str = "off") -> str:
    s = preview.summarise(report or report_of(), evaluated, at=AT, horizon=timedelta(hours=36), mode=mode)
    return preview.render(s, top=top)


def test_the_text_opens_with_what_it_is_the_switch_and_the_funnel() -> None:
    out = text_of(three()).splitlines()
    assert out[0] == (f"decisions of the families, dry run: what a pass would do at 2035-03-01 12:00 UTC over the next 36 h under {fd.VERSION} - "
                      "it reads, it writes nothing, it asks nobody")
    assert out[1] == "  FBI_FAMILY_DECISIONS is off: the worker runs no pass; set to 'shadow' it runs one an hour and writes rows like these"
    assert out[2] == ("  funnel: 40 forecasts of 4 matches -> 25 priced selections -> 3 candidates -> 3 judged (0 failed) -> 2 rows to write "
                      "(what is already written is not written again)")
    failing = text_of(three(), report_of(evaluated=3, candidates=5, errors=["1/CORNERS_OU/Over/9.5: ValueError: x", "2/CORNERS_OU/Over/9.5: KeyError: y"]))
    assert "-> 5 candidates -> 3 judged (2 failed) -> 2 rows to write" in failing, "the candidates that failed were not judged"
    assert preview.render(preview.summarise(report_of(), [], at=AT, horizon=timedelta(hours=36), mode="shadow")).splitlines()[1] == (
        "  FBI_FAMILY_DECISIONS is shadow: the worker runs one pass an hour and writes rows like these")


def test_every_position_of_the_switch_is_explained() -> None:
    assert set(preview.MODE_SAYS) == set(fd.MODES), "a new position of the switch needs its sentence"


def test_the_counts_are_listed_biggest_first_and_a_tie_by_name() -> None:
    out = text_of(three())
    assert "  by family: CARDS 1, CORNERS 2" not in out and "  by family: CORNERS 2, CARDS 1" in out
    assert "  by state: INVESTIGACION 2, RECHAZADO 1 (a family never goes above INVESTIGACION: that is the owner's to give)" in out
    assert "  by reason: family_research 3, family_shadow_only 2, not_calibrated 2, thin_market 1" in out
    tie = text_of(three(), report_of(by_family={"YELLOW": 1, "CARDS": 1, "GOALS_HALF": 1}))
    assert "  by family: CARDS 1, GOALS_HALF 1, YELLOW 1" in tie


def test_a_count_with_nothing_in_it_says_none() -> None:
    assert "  by reason: none" in text_of(three(), report_of(by_reason={}))


def test_what_the_pass_could_not_state_is_a_question_mark_and_not_a_number() -> None:
    e = decided(fixture=4)
    e.row = {**e.row, "p_model": None, "p_fair": None, "best_odds": None}
    e.filters = [f for f in e.filters if f["key"] != "family"]
    e.ev_raw = None
    out = text_of([e], report_of(evaluated=1))
    assert "model ?, books ? (3), best price ?, value ? -> INVESTIGACION" in out


def test_what_they_lack_is_one_line_with_the_cost_of_finding_it_out() -> None:
    out = text_of(three())
    assert ("  what they lack (the request for research each carries; nothing serves it): context 3, lineups 3 of 3 decisions; "
            "6 searches in 2 matches if anyone served them") in out


def test_what_they_lack_counts_the_decisions_that_carry_a_request_and_not_all_the_pass_judged() -> None:
    out = text_of([decided(fixture=1), decided(fixture=2), decided(fixture=3, facts=None)], report_of(evaluated=3))
    assert "context 2, lineups 2 of 2 decisions; 6 searches in 2 matches if anyone served them" in out


def test_a_pass_that_could_not_read_the_referees_says_why_there_is_no_request() -> None:
    out = text_of([decided(facts=None)], report_of(evaluated=1))
    assert "  what they lack: not said - the referees could not be read, so the decisions carry no request for research" in out
    assert "what they lack (" not in out


def test_each_decision_is_a_line_with_what_was_said_and_the_sentence_of_its_request() -> None:
    out = text_of([decided(fixture=1, odds=2.60)], report_of(evaluated=1)).splitlines()
    line = next(x for x in out if "Home FC - B" in x)
    assert line == ("  03-02 08:00 Home FC - B (League) CORNERS_OU Over 9.5 [CORNERS]: model 55.0 %, books 50.0 % (3), best price 2.60, value +43.0% "
                    "-> INVESTIGACION (not_calibrated, family_research); stake 0; context LIMITED")
    after = out[out.index(line) + 1]
    assert after.startswith("      pedir investigación: le falta las alineaciones confirmadas")


def test_a_rejection_says_which_filter_refused_it_and_why() -> None:
    out = text_of([rejected_by_the_market()], report_of(evaluated=1))
    assert "      rejected by market: solo 2 casas" in out
    assert "rejected by calibration" not in out, "a filter that only measures (INVESTIGACION) is not a rejection"
    assert "rejected by final" not in out, "the last filter adds up the others: it is not one more reason"
    assert "-> RECHAZADO (thin_market, family_research)" in out


def test_only_the_top_decisions_are_listed_and_the_text_says_how_many_more_there_are() -> None:
    many = [decided(fixture=i, odds=2.0 + i / 10) for i in range(1, 6)]
    out = text_of(many, report_of(evaluated=5), top=2)
    assert out.count(" [CORNERS]: ") == 2 and "  ... and 3 more (--top, or --json for all of them)" in out
    assert "best price 2.50" in out and "best price 2.40" in out and "best price 2.30" not in out, "the ones that see the most value"
    assert " more (" not in text_of(many, report_of(evaluated=5), top=5)
    zero = text_of(many, report_of(evaluated=5), top=0)
    assert " [CORNERS]: " not in zero and "  ... and 5 more" in zero
    assert " [CORNERS]: " not in text_of(many, report_of(evaluated=5), top=-3), "a negative number lists none, it does not drop the last ones"


def test_the_text_lists_twenty_decisions_when_nobody_says_how_many() -> None:
    many = [decided(fixture=i, odds=2.05 + i / 100) for i in range(1, 26)]
    out = preview.render(preview.summarise(report_of(evaluated=25), many, at=AT, horizon=timedelta(hours=36), mode="shadow"))
    assert preview.DEFAULT_TOP == 20 and out.count(" [CORNERS]: ") == 20
    assert out.splitlines()[-1] == "  ... and 5 more (--top, or --json for all of them)"


def test_the_errors_of_the_pass_are_in_the_text() -> None:
    out = text_of([], report_of(evaluated=0, candidates=2, would_write=0, errors=["1/CORNERS_OU/Over/9.5: ValueError: x"]))
    assert "  error: 1/CORNERS_OU/Over/9.5: ValueError: x" in out
    assert "  nothing was judged: every candidate failed (see the errors)" in out


@pytest.mark.parametrize("kw,says", [
    ({"forecasts": 0, "fixtures": 0, "priced_selections": 0, "candidates": 0, "evaluated": 0, "would_write": 0},
     "nothing to decide: the families have stated no forecast for a match that kicks off in the window"),
    ({"priced_selections": 0, "candidates": 0, "evaluated": 0, "would_write": 0},
     "nothing to decide: no selection that was forecast has a price from complete books by that moment"),
    ({"candidates": 0, "evaluated": 0, "would_write": 0},
     "nothing to decide: no priced selection shows the value the plan's criterion asks (at the best price, behind enough complete books)"),
])
def test_an_empty_pass_says_at_which_step_of_the_funnel_it_ran_dry(kw: dict[str, Any], says: str) -> None:
    out = text_of([], report_of(**kw)).splitlines()
    assert f"  {says}" in out
    assert not any(x.startswith("  by family") or x.startswith("  by state") for x in out), "there is nothing to count"
    assert not any("what they lack" in x for x in out), "and nothing that could lack anything"
    assert out.count(f"  {says}") == 1


def test_a_pass_that_decided_says_nothing_of_running_dry() -> None:
    out = text_of(three())
    assert "nothing to decide" not in out and "nothing was judged" not in out
