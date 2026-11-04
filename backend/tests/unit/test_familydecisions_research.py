"""Plan F11 - the formal request for research of a family (``fbi.familydecisions.research``, ``research-fam-v1``): what a decision lacks, what finding out
would cost, that nothing serves it and which context factors could explain the family. Pure, checked against cases worked by hand.

The record on a real decision (its place among the filters, that it changes nothing of the decision, the reading of the referee and of the registry) is in
tests/unit/test_familydecisions_decide.py and tests/integration/test_familydecisions_decide.py."""

from __future__ import annotations

import itertools
import json
from datetime import UTC, datetime

import pytest

from fbi.ai import research as ai_research
from fbi.families import forecast as family_forecast
from fbi.familydecisions import decide as fd
from fbi.familydecisions import research
from fbi.intel import decision, factors

SEEN = datetime(2035, 3, 1, 9, 30, tzinfo=UTC)
LINEUPS = datetime(2035, 3, 1, 10, 45, tzinfo=UTC)
NOTHING = research.Facts(None, None, "PENDING")
EVERYTHING = research.Facts(SEEN, LINEUPS, "FULL")
STANDING = {f.key: (f.version, factors.DESCRIPTIVE) for f in factors.CATALOGUE}


# ── the vocabulary: the AI's and the registry's, not a new one ─────────────────────────────────────────────────────

def test_what_a_search_can_look_for_is_the_closed_list_of_the_ai_and_nothing_else() -> None:
    for need in research.NEEDS.values():
        assert set(need.topics) <= set(ai_research.BY_KEY), need.key
        assert need.source in (research.PROVIDER, research.SEARCH), need.key
        assert bool(need.topics) == (need.source == research.SEARCH), "a need a search serves names its topics, one the provider fills names none"
        assert need.label and need.label == need.label.strip()
    assert research.NEEDS["referee"].levels == () and research.NEEDS["lineups"].levels == ()
    assert research.NEEDS["context"].levels == tuple(range(1, ai_research.FULL + 1)), "the context is the tiered search of a match with a candidate: every level"
    assert all(key == need.key for key, need in research.NEEDS.items())


def test_the_reason_nothing_is_served_is_not_one_the_ai_gives_for_a_request_of_a_brief() -> None:
    assert research.UNSERVED == "family_shadow"
    assert research.UNSERVED not in ai_research.UNSERVED, "those reasons are counted in the passes of the AI, and no pass of the AI reads this record"
    assert (research.KNOWN, research.PARTIAL, research.MISSING) == research.STATES == ("KNOWN", "PARTIAL", "MISSING")
    assert research.VERSION == "research-fam-v1" and research.KEY == "research"


def test_every_family_that_decides_says_what_it_needs_and_what_could_explain_it() -> None:
    assert set(research.OF_FAMILY) == set(research.HYPOTHESES) == set(fd.SPECS)
    for family, keys in research.OF_FAMILY.items():
        assert set(keys) <= set(research.NEEDS) and len(set(keys)) == len(keys) and "context" in keys, family
    for family, hypotheses in research.HYPOTHESES.items():
        assert hypotheses and set(hypotheses) <= set(factors.BY_KEY) and len(set(hypotheses)) == len(hypotheses), family
    assert research.DESCRIPTIVE == factors.DESCRIPTIVE and factors.STATUSES == (factors.DESCRIPTIVE, factors.VALIDATED)


def test_a_family_wants_the_referee_exactly_when_its_model_reads_him() -> None:
    reads_him = {s.family for s in family_forecast.SPECS if s.referee_kappa}
    assert reads_him == {"CARDS", "YELLOW"}, "the test must see the families that scale their means by the referee, or it proves nothing"
    assert {family for family, keys in research.OF_FAMILY.items() if "referee" in keys} == reads_him
    assert {family for family, keys in research.OF_FAMILY.items() if "lineups" in keys} == set(research.OF_FAMILY) - reads_him


def test_each_family_lists_what_the_provider_brings_before_what_only_a_search_can_and_the_sentence_follows_that_order() -> None:
    assert {family: list(keys) for family, keys in research.OF_FAMILY.items()} == {
        "GOALS_HALF": ["lineups", "context"], "CORNERS": ["lineups", "context"], "CARDS": ["referee", "context"], "YELLOW": ["referee", "context"]}
    for family, keys in research.OF_FAMILY.items():
        assert [research.NEEDS[key].source for key in keys] == [research.PROVIDER, research.SEARCH], family
    why, data = research.request("GOALS_HALF", NOTHING, STANDING)
    assert [n["key"] for n in data["needs"]] == data["open"] == ["lineups", "context"]
    assert why == ("pedir investigación: le falta las alineaciones confirmadas (lo trae el proveedor) y el contexto de fuera (bajas y previa); "
                   "3 búsquedas si se sirviera; no se sirve: las familias están en sombra")


def test_the_context_need_reads_every_word_the_decision_layer_can_say() -> None:
    said = {decision.context_status(ai_mode=mode, first_pass=first, reviewed=reviewed, searched=searched, web_good=web, provider_items=items,
                                    lineups=lineups)
            for mode, first, reviewed, searched, web, items, lineups in itertools.product(
                ("off", "shadow"), (False, True), (False, True), (False, True), (0, 1), (0, 1), (False, True))}
    assert said == {"AI_OFF", "PENDING", "FULL", "PARTIAL", "LIMITED"}, "the test must see every word, or it proves nothing"
    assert set(research.CONTEXT_STATE) == said
    states = {word: research.state_of("context", research.Facts(None, None, word)) for word in sorted(said)}
    assert states == {"AI_OFF": ("MISSING", None), "FULL": ("KNOWN", None), "LIMITED": ("MISSING", None), "PARTIAL": ("PARTIAL", None),
                      "PENDING": ("MISSING", None)}


# ── the state of each need ─────────────────────────────────────────────────────────────────────────────────────────

def test_the_referee_and_the_lineups_are_known_since_the_moment_they_were_seen() -> None:
    assert research.state_of("referee", research.Facts(SEEN, None, "PENDING")) == ("KNOWN", SEEN)
    assert research.state_of("referee", research.Facts(None, LINEUPS, "FULL")) == ("MISSING", None)
    assert research.state_of("lineups", research.Facts(None, LINEUPS, "PENDING")) == ("KNOWN", LINEUPS)
    assert research.state_of("lineups", research.Facts(SEEN, None, "FULL")) == ("MISSING", None)
    assert research.state_of("context", research.Facts(SEEN, LINEUPS, "bogus")) == ("MISSING", None), "a word nobody knows is a context nobody read"
    with pytest.raises(KeyError):
        research.state_of("weather", NOTHING)


# ── the request ────────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_decision_that_lacks_everything_asks_for_it_and_says_what_it_would_cost_and_that_nothing_serves_it() -> None:
    why, data = research.request("CARDS", NOTHING, STANDING)
    assert [n["key"] for n in data["needs"]] == ["referee", "context"] and data["open"] == ["referee", "context"]
    assert [n["state"] for n in data["needs"]] == ["MISSING", "MISSING"]
    assert data["needs"][0] == {"key": "referee", "state": "MISSING", "source": "provider", "topics": [], "levels": [], "since": None}
    assert data["needs"][1] == {"key": "context", "state": "MISSING", "source": "search", "topics": ["availability", "preview"], "levels": [1, 2, 3],
                                "since": None}
    assert (data["levels"], data["searches"], data["served"], data["unserved"]) == ([1, 2, 3], 3, False, "family_shadow")
    assert data["version"] == "research-fam-v1" and data["family"] == "CARDS" and data["registry"] == "read"
    assert why == ("pedir investigación: le falta el árbitro designado (lo trae el proveedor) y el contexto de fuera (bajas y previa); "
                   "3 búsquedas si se sirviera; no se sirve: las familias están en sombra")


def test_a_decision_that_lacks_nothing_asks_for_nothing() -> None:
    for family in research.OF_FAMILY:
        why, data = research.request(family, EVERYTHING, STANDING)
        assert data["open"] == [] and data["levels"] == [] and data["searches"] == 0 and data["unserved"] is None, family
        assert all(n["state"] == "KNOWN" for n in data["needs"]) and data["served"] is False
        assert why == "pedir investigación: no le falta nada de lo que se puede saber antes del partido"


def test_what_is_known_says_since_when_in_the_text_of_the_instant() -> None:
    _, data = research.request("CARDS", research.Facts(SEEN, None, "FULL"), STANDING)
    assert [(n["key"], n["state"], n["since"]) for n in data["needs"]] == [("referee", "KNOWN", "2035-03-01T09:30:00+00:00"), ("context", "KNOWN", None)]
    _, data = research.request("CORNERS", research.Facts(None, LINEUPS, "PARTIAL"), STANDING)
    assert [(n["key"], n["state"], n["since"]) for n in data["needs"]] == [("lineups", "KNOWN", "2035-03-01T10:45:00+00:00"), ("context", "PARTIAL", None)]


def test_a_context_read_in_part_is_still_asked_for_and_the_sentence_says_so() -> None:
    why, data = research.request("GOALS_HALF", research.Facts(None, LINEUPS, "PARTIAL"), STANDING)
    assert data["open"] == ["context"] and data["searches"] == 3 and data["unserved"] == "family_shadow"
    assert why == ("pedir investigación: le falta el contexto de fuera (bajas y previa), leído solo en parte; 3 búsquedas si se sirviera; "
                   "no se sirve: las familias están en sombra")


def test_what_only_the_provider_can_bring_costs_no_search_and_is_not_something_the_server_declines_to_serve() -> None:
    why, data = research.request("YELLOW", research.Facts(None, None, "FULL"), STANDING)
    assert data["open"] == ["referee"] and data["levels"] == [] and data["searches"] == 0 and data["unserved"] is None
    assert why == "pedir investigación: le falta el árbitro designado (lo trae el proveedor)"
    why, data = research.request("GOALS_HALF", research.Facts(SEEN, None, "FULL"), STANDING)
    assert data["open"] == ["lineups"] and data["searches"] == 0 and "las alineaciones confirmadas (lo trae el proveedor)" in why


def test_the_searches_are_the_levels_of_the_topics_together_one_a_level() -> None:
    for family in research.OF_FAMILY:
        for facts in (NOTHING, EVERYTHING, research.Facts(SEEN, LINEUPS, "LIMITED"), research.Facts(None, None, "FULL")):
            _, data = research.request(family, facts, STANDING)
            wanted = sorted({lvl for n in data["needs"] if n["state"] != "KNOWN" and n["source"] == "search" for lvl in n["levels"]})
            assert data["levels"] == wanted and data["searches"] == len(wanted), (family, facts)
            assert data["searches"] in (0, ai_research.FULL)
            assert (data["unserved"] is None) == (data["searches"] == 0)


def test_the_count_is_in_the_singular_when_it_is_one() -> None:
    assert research._searches(1) == "1 búsqueda" and research._searches(2) == "2 búsquedas" and research._searches(3) == "3 búsquedas"


def test_each_family_lists_the_factors_that_could_explain_it_with_their_version_and_standing() -> None:
    assert {f: [h["factor"] for h in research.request(f, NOTHING, STANDING)[1]["factors"]] for f in research.OF_FAMILY} == {
        "GOALS_HALF": ["tactics_profile", "scenarios", "rest_congestion"], "CORNERS": ["tactics_profile"], "CARDS": ["scenarios"], "YELLOW": ["scenarios"]}
    entry = research.request("CORNERS", NOTHING, STANDING)[1]["factors"][0]
    assert entry == {"factor": "tactics_profile", "version": factors.BY_KEY["tactics_profile"].version, "status": "DESCRIPTIVE"}
    validated = {**STANDING, "scenarios": ("scenarios-v9", "VALIDATED")}
    assert research.request("CARDS", NOTHING, validated)[1]["factors"] == [{"factor": "scenarios", "version": "scenarios-v9", "status": "VALIDATED"}]
    unknown = research.request("CARDS", NOTHING, {})[1]["factors"]
    assert unknown == [{"factor": "scenarios", "version": None, "status": "DESCRIPTIVE"}], "a factor nobody listed is the DESCRIPTIVE it is born as"


def test_the_record_says_when_the_registry_could_not_be_read() -> None:
    assert research.request("CARDS", NOTHING, STANDING)[1]["registry"] == "read"
    assert research.request("CARDS", NOTHING, STANDING, registry_read=False)[1]["registry"] == "unread"


def test_a_family_with_no_list_is_told_so_and_asks_for_nothing() -> None:
    why, data = research.request("REDS", EVERYTHING, STANDING)
    assert why == "pedir investigación: esta familia no tiene lista de lo que necesita saber"
    assert data["needs"] == [] and data["open"] == [] and data["factors"] == [] and data["searches"] == 0 and data["unserved"] is None


def test_the_record_is_plain_json_and_the_same_every_time_and_leaves_what_it_was_given_alone() -> None:
    standing = dict(STANDING)
    first = research.request("CARDS", research.Facts(SEEN, LINEUPS, "PARTIAL"), standing)
    second = research.request("CARDS", research.Facts(SEEN, LINEUPS, "PARTIAL"), standing)
    assert first == second and standing == STANDING
    assert json.loads(json.dumps(first[1])) == first[1], "what goes into the jsonb of the decision"
    assert research.Facts(SEEN, LINEUPS, "FULL") == research.Facts(SEEN, LINEUPS, "FULL")
