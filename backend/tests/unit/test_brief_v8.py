"""brief-v8 (plan F6, pre-match v3): the brief keeps what DESCRIBES a match apart from what a person has shown to be a signal, and it can ASK
the server to look into something on the web - never write the query. What the prompt asks for, the server enforces:

* a reason for a selection (``cards[*].why``) that cites the block of a context factor still DESCRIPTIVE is refused and listed
  (``fbi.ai.brief.validate``); risks, context and the narrative may still say it, as a count;
* a request is a topic and a side of the server's own list with its reason as a claim, checked like any other; a key of the model's own
  (``query``, ``url``) goes no further; a malformed request is left out, it does not cost the brief a second try;
* the levels of the tiered search a request is served with are the ones its topic maps to (``fbi.ai.research.levels_for``,
  ``fbi.ai.collectors.queries_for``);
* the text the owner reads when no model answers says the scenarios and the tactics as counts, and how little a short head-to-head tells.

No database, no model, no network."""

from __future__ import annotations

import json
from typing import Any

import pytest

from fbi.ai import research
from fbi.ai.brief import (
    BriefOut,
    descriptive_factor,
    lenient,
    rules_brief,
    validate,
    validated_factors,
)
from fbi.ai.collectors import levels_wanted, queries_for
from fbi.ai.packet import Packet
from fbi.ai.prompts import BRIEF_SCHEMA, BRIEF_SYSTEM, BRIEF_VERSION
from fbi.ai.text import plain
from fbi.intel import factors, narrative

from .test_ai_decisions import KO, packet


def cards() -> list[dict[str, Any]]:
    return [{"market": "1X2", "selection": "Home", "line": "0", "kind": "value", "p_model": "0.5200",
             "p_market": "0.4500", "ai": None}]


def claim(text: str, *refs: str, kind: str = "DATA") -> dict[str, Any]:
    return {"text": text, "type": kind, "refs": list(refs)}


def brief(**over: Any) -> BriefOut:
    base: dict[str, Any] = {"summary": "Partido de prueba.", "data_quality": "good", "uncertainty": "medium",
                            "contradiction": False, "escalate": False, "context": [], "injuries": [], "changes": [], "cards": []}
    return BriefOut.model_validate(base | over)


def card(why: list[dict[str, Any]], risks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    return {"market": "1X2", "selection": "Home", "line": "0", "why": why, "risks": risks or []}


def informed(*validated: str) -> Packet:
    """A packet with the registry's block: every factor DESCRIPTIVE (as every one is born) except the ones named."""
    p = packet()
    block = factors.block(factors.unread())
    for key in validated:
        block[key]["status"] = factors.VALIDATED
    p.content["factors"] = block
    return p


MODEL = claim("Modelo 52 % frente a 45 % del mercado.", "P:models", "P:market")
ON_FACTOR = {
    factors.H2H: claim("En los 4 cruces con peso, el local ganó 3.", "P:h2h"),
    factors.SCENARIOS: claim("Con una victoria sumaría 3 puntos más.", "P:scenarios"),
    factors.TACTICS: claim("Usó la misma formación en 4 de sus últimos 5.", "P:dossier.tactics.home"),
    factors.CALENDAR: claim("El visitante descansó 3 días.", "P:schedule.away"),
}
ASK = {"topic": "availability", "side": "both", "why": claim("El paquete no trae bajas de ninguno de los dos.", "P:absences")}


# ── a descriptive factor does not justify a selection ───────────────────────────────────────────────────────────────────

def test_the_catalogue_and_the_blocks_a_claim_cites_agree() -> None:
    """The guard is only as good as the map from a block to its factor: one block per factor, none shared."""
    from fbi.ai.brief import FACTOR_OF_BLOCK

    assert set(FACTOR_OF_BLOCK.values()) == set(factors.BY_KEY) == set(ON_FACTOR)
    assert len(FACTOR_OF_BLOCK) == len(factors.CATALOGUE)


@pytest.mark.parametrize("key", list(ON_FACTOR))
def test_a_reason_for_a_selection_cannot_rest_on_a_descriptive_factor(key: str) -> None:
    out = brief(cards=[card([MODEL, ON_FACTOR[key]], risks=[ON_FACTOR[key]])], context=[ON_FACTOR[key]])
    content, rejected = validate(out, informed(), cards())
    note = content["cards"][0]
    assert [c["text"] for c in note["why"]] == [MODEL["text"]], "the reason that rests on the factor is dropped"
    assert [c["text"] for c in note["risks"]] == [ON_FACTOR[key]["text"]], "it may still be said as a risk"
    assert [c["text"] for c in content["context"]] == [ON_FACTOR[key]["text"]], "and as context"
    dropped = [r for r in rejected if r["group"] == "cards.why"]
    assert len(dropped) == 1 and key in dropped[0]["why"] and "DESCRIPTIVE" in dropped[0]["why"], rejected
    assert not [r for r in rejected if r["group"] != "cards.why"]


def test_a_validated_factor_may_be_cited_and_only_that_one() -> None:
    out = brief(cards=[card([ON_FACTOR[factors.H2H], ON_FACTOR[factors.TACTICS]])])
    content, rejected = validate(out, informed(factors.H2H), cards())
    assert [c["refs"] for c in content["cards"][0]["why"]] == [["P:h2h"]]
    assert len(rejected) == 1 and factors.TACTICS in rejected[0]["why"]
    both, none = validate(out, informed(factors.H2H, factors.TACTICS), cards()), validate(out, informed(), cards())
    assert len(both[0]["cards"][0]["why"]) == 2 and both[1] == []
    assert none[0]["cards"][0]["why"] == [] and len(none[1]) == 2


def test_a_packet_that_does_not_say_is_read_as_descriptive() -> None:
    """The safe side of every doubt: a packet before F6 (no registry block), an entry that is not one, a status that is not the word."""
    old = packet()
    assert "factors" not in old.content
    content, rejected = validate(brief(cards=[card([ON_FACTOR[factors.H2H]])]), old, cards())
    assert content["cards"][0]["why"] == [] and len(rejected) == 1
    for odd in ("VALIDATED", ["VALIDATED"], None, {factors.H2H: "VALIDATED"}, {factors.H2H: {"status": "validated"}},
                {factors.H2H: {"status": "PROMOTED"}}, {factors.H2H: {}}, {"made_up": {"status": "VALIDATED"}}):
        assert validated_factors({"factors": odd}) == frozenset(), odd
    assert validated_factors({}) == frozenset()
    assert validated_factors({"factors": {factors.H2H: {"status": "VALIDATED"}, factors.TACTICS: {"status": "DESCRIPTIVE"}}}) \
        == frozenset({factors.H2H})


def test_which_references_count_as_citing_a_factor() -> None:
    none: frozenset[str] = frozenset()
    assert descriptive_factor(["P:h2h"], none) == factors.H2H
    assert descriptive_factor([" P:h2h "], none) == factors.H2H, "read stripped, as the claim check reads them"
    assert descriptive_factor(["P:h2h.weights"], none) == factors.H2H, "a part of the block is the block"
    assert descriptive_factor(["P:dossier.tactics"], none) == factors.TACTICS
    assert descriptive_factor(["P:dossier.tactics.home"], none) == factors.TACTICS
    assert descriptive_factor(["P:scenarios"], none) == factors.SCENARIOS
    assert descriptive_factor(["P:schedule.home"], none) == factors.CALENDAR
    assert descriptive_factor(["P:models", "E:4", "P:h2h"], none) == factors.H2H, "any of the references"
    for fine in ("P:dossier", "P:dossier.teams", "P:factors", "P:factors.h2h_weighted", "P:h2hx", "P:models", "E:12", "no tag"):
        assert descriptive_factor([fine], none) is None, fine
    assert descriptive_factor(["P:h2h"], frozenset({factors.H2H})) is None, "validated: it may be cited"
    assert descriptive_factor(["P:h2h"], frozenset({factors.TACTICS})) == factors.H2H, "another factor's validation is not its own"


# ── asking the server to look into something ────────────────────────────────────────────────────────────────────────────

def test_a_request_is_a_topic_and_a_side_of_the_servers_list_with_its_reason() -> None:
    preview = {"topic": " Preview ", "side": "HOME", "why": claim("Una previa diría cómo llegan los dos.", "P:evidence")}
    content, rejected = validate(brief(research=[ASK, preview, ASK]), informed(), cards())
    assert [(a["topic"], a["side"]) for a in content["research"]] == [("availability", "both"), ("preview", "home")], \
        "read stripped and in lower case; a request made twice is made once"
    assert [r["why"] for r in rejected] == ["asked twice"] and rejected[0]["group"] == "research"
    assert content["research"][0]["why"] == {"text": ASK["why"]["text"], "type": "DATA", "refs": ["P:absences"]}
    assert research.asks_in(content["research"]) == [research.Ask("availability", "both", content["research"][0]["why"]),
                                                     research.Ask("preview", "home", content["research"][1]["why"])], \
        "what is stored is read back as the same requests"


def test_a_word_outside_the_list_is_listed_as_refused_and_does_not_lose_the_brief() -> None:
    odd = [{"topic": "gossip", "side": "home", "why": claim("Quiero saber más del vestuario.", "P:evidence")},
           {"topic": "availability", "side": "everyone", "why": claim("Quiero saber más de las bajas.", "P:absences")}]
    content, rejected = validate(brief(research=odd), informed(), cards())
    assert content["research"] == [] and content["summary"] == "Partido de prueba."
    assert [r["group"] for r in rejected] == ["research", "research"]
    assert all(r["why"] == "not a topic and a side of the list" for r in rejected)


def test_the_reason_of_a_request_is_a_claim_like_any_other() -> None:
    made_up = {"topic": "confirmation", "side": "away", "why": claim("Faltan 913 confirmaciones oficiales.", "P:evidence")}
    news = {"topic": "confirmation", "side": "home", "why": claim("Dicen que el 9 no juega.", "E:999", kind="NEWS")}
    content, rejected = validate(brief(research=[made_up, news]), informed(), cards())
    assert content["research"] == []
    assert "numbers not in the packet" in rejected[0]["why"] and "evidence not given" in rejected[1]["why"]
    # asking to look into a descriptive block is not betting on it: the guard on reasons does not apply to a request
    about = {"topic": "preview", "side": "both", "why": claim("El cara a cara dice poco de cómo llegan.", "P:h2h")}
    content, rejected = validate(brief(research=[about]), informed(), cards())
    assert len(content["research"]) == 1 and rejected == []


def test_asking_to_look_closer_is_not_a_reason_to_escalate() -> None:
    """The match gets a closer reading only when the brief says ``escalate``; a request never makes it say so (nor the server say it)."""
    content, _ = validate(brief(research=[ASK]), informed(), cards())
    assert content["escalate"] is False and len(content["research"]) == 1
    content, _ = validate(brief(research=[ASK], escalate=True), informed(), cards())
    assert content["escalate"] is True


def test_the_ai_never_writes_a_query() -> None:
    d = lenient({"summary": "Partido parejo.", "research": [
        {"topic": "availability", "side": "home", "query": "site:marca.com lesión delantero", "url": "https://x.example",
         "searches": 9, "why": {"text": "Sin bajas en el paquete.", "type": "DATA", "refs": ["P:absences"], "source": "x"}}]})
    assert d["research"] == [{"topic": "availability", "side": "home",
                              "why": {"text": "Sin bajas en el paquete.", "type": "DATA", "refs": ["P:absences"]}}]
    assert set(BRIEF_SCHEMA["properties"]["research"]["items"]["properties"]) == {"topic", "side", "why"}
    assert BRIEF_SCHEMA["properties"]["research"]["items"]["additionalProperties"] is False


def test_a_brief_that_wraps_or_overfills_its_requests_is_read_not_refused() -> None:
    nothing = lenient({"summary": "Partido parejo."})
    assert nothing["research"] == [] and BriefOut.model_validate(nothing).research == [], "a brief of before v8 has none"
    wrapped = lenient({"summary": "Partido parejo.", "research": json.dumps([ASK])})
    assert wrapped["research"] == [ASK] and BriefOut.model_validate(wrapped).research[0].topic == "availability"
    many = lenient({"summary": "Partido parejo.", "research": [ASK] * 5})
    assert len(many["research"]) == research.MAX_ASKS == 3, "three at most; the rest is cut, the brief is read"
    long = lenient({"summary": "Partido parejo.", "research": [{**ASK, "why": {**ASK["why"], "text": "Muy largo. " * 40}}]})
    assert len(long["research"][0]["why"]["text"]) <= 240
    # an optional request that is not one costs the request, not the brief
    broken = lenient({"summary": "Partido parejo.", "research": ["availability", 3, None, {"topic": "preview"},
                                                                  {"topic": "preview", "side": "home", "why": "porque sí"}, ASK]})
    assert broken["research"] == [ASK] and BriefOut.model_validate(broken).summary == "Partido parejo."
    assert lenient({"summary": "Partido parejo.", "research": "no es json"})["research"] == []


def test_the_rules_brief_asks_for_nothing() -> None:
    b = rules_brief(packet(), cards(), ["candidate"])
    assert b["research"] == []


# ── the levels of the search a request is served with ───────────────────────────────────────────────────────────────────

def test_each_topic_maps_to_the_levels_of_the_tiered_search_that_serve_it() -> None:
    assert {t.key: t.levels for t in research.TOPICS} == {"availability": (1, 2), "confirmation": (2,), "preview": (3,)}
    ask = {k: research.Ask(k, "both", {}) for k in research.BY_KEY}
    assert research.levels_for([], candidates=False) == 1, "nothing asked: the first level, as ever"
    assert research.levels_for([ask["availability"]], candidates=False) == (1, 2)
    assert research.levels_for([ask["confirmation"]], candidates=False) == (2,)
    assert research.levels_for([ask["preview"]], candidates=False) == (3,)
    assert research.levels_for([ask["preview"], ask["availability"]], candidates=False) == (1, 2, 3)
    assert research.levels_for([ask["availability"], ask["confirmation"]], candidates=False) == (1, 2), "the union, once each"
    for asks in ([], [ask["preview"]], list(ask.values())):
        assert research.levels_for(asks, candidates=True) == research.FULL == 3, "a match with a candidate is read in full, as ever"


def test_a_search_asks_the_levels_it_is_given_and_never_fewer_than_one() -> None:
    assert levels_wanted(1) == (1,) and levels_wanted(3) == (1, 2, 3) and levels_wanted(9) == (1, 2, 3) and levels_wanted(0) == (1,)
    assert levels_wanted((3, 2)) == (2, 3), "in the order they are tried"
    assert levels_wanted((2, 2)) == (2,) and levels_wanted(()) == (1,) and levels_wanted((7,)) == (1,)
    when = KO
    full = queries_for("Millonarios", "Santa Fe", when, "Colombia", "Primera A", levels=3)
    assert queries_for("Millonarios", "Santa Fe", when, "Colombia", "Primera A", levels=(2,)) == [full[1]]
    assert queries_for("Millonarios", "Santa Fe", when, "Colombia", "Primera A", levels=(3,)) == [full[2]]
    assert queries_for("Millonarios", "Santa Fe", when, "Colombia", "Primera A", levels=(1, 2)) == full[:2]
    assert queries_for("Millonarios", "Santa Fe", when, "Colombia", "Primera A", levels=1) == full[:1], "level 1 as ever"
    assert "comunicado oficial" in full[1] and "preview" in full[2], "a topic is answered by the query the server wrote for it"


# ── the prompt and the schema ───────────────────────────────────────────────────────────────────────────────────────────

def test_the_prompt_the_schema_and_the_model_of_the_answer_agree() -> None:
    assert BRIEF_VERSION == "brief-v8"
    props = BRIEF_SCHEMA["properties"]
    assert set(props) == set(BriefOut.model_fields) and set(BRIEF_SCHEMA["required"]) <= set(props)
    assert "research" in BRIEF_SCHEMA["required"], "the model is asked to answer it, [] being the usual answer"
    item = props["research"]["items"]
    assert item["properties"]["topic"]["enum"] == [t.key for t in research.TOPICS]
    assert item["properties"]["side"]["enum"] == list(research.SIDES)
    assert props["research"]["maxItems"] == research.MAX_ASKS
    for t in research.TOPICS:
        assert f"«{t.key}»" in BRIEF_SYSTEM, f"the prompt says what {t.key} is"
    for word in ("DESCRIPTIVE", "VALIDATED", "P:factors", "P:scenarios", "P:dossier.tactics", "n_effective", "You never write a query"):
        assert word in BRIEF_SYSTEM, word
    assert "cards[*].why) cannot cite a DESCRIPTIVE block" in " ".join(BRIEF_SYSTEM.split()), "what the server enforces is said"


def test_the_blocks_the_prompt_names_can_be_cited_and_are_read_in_words() -> None:
    from fbi.ai.claims import BLOCKS, ClaimOut, refused

    for block in ("scenarios", "factors", "dossier", "h2h", "absences", "schedule"):
        assert block in BLOCKS and f"{block}" in BRIEF_SYSTEM, block
        ok = ClaimOut(text="Dato del paquete.", type="DATA", refs=[f"P:{block}"])
        assert refused(ok, stored=set(), evidence_status={}) is None, f"P:{block} can be cited"
    deep = ClaimOut(text="Dato del paquete.", type="DATA", refs=["P:dossier.tactics.home"])
    assert refused(deep, stored=set(), evidence_status={}) is None, "a part of a block, after a dot"
    assert plain("Según P:scenarios, empatar basta.") == "Según los escenarios, empatar basta."
    assert plain("Según P:factors.h2h_weighted no hay validación.") == "Según el estado de los factores no hay validación."
    assert plain("Lo dice P:dossier.tactics.") == "Lo dice el dossier."


# ── the text the owner reads when no model answers ──────────────────────────────────────────────────────────────────────

def _table_content() -> dict[str, Any]:
    from fbi.ai.context import TableRow
    from fbi.intel import scenarios

    title, europa, drop = "Promotion - Champions League", "Promotion - Europa League", "Relegation"
    table = [TableRow(1, 1, 15, 8, title), TableRow(2, 2, 13, 8, title), TableRow(3, 3, 10, 8, europa),
             TableRow(4, 4, 10, 8, europa), TableRow(5, 5, 7, 8, None), TableRow(6, 6, 3, 8, drop)]
    block = scenarios.table_effect(table, 3, 5)
    assert block is not None
    return {"fixture": {"home": {"name": "Alfa"}, "away": {"name": "Beta"}},
            "scenarios": scenarios.scenarios_block(block, None)}


def test_the_rules_narrative_says_what_the_match_alone_does_to_the_table() -> None:
    text = narrative.stakes(_table_content())
    assert "si gana Alfa, Alfa sumaría 13 puntos (puestos 2.º a 3.º, zona de plazas internacionales) y Beta 7 (puesto 5.º)" in text
    assert "si empatan, Alfa sumaría 11 puntos (puesto 3.º, zona de plazas internacionales) y Beta 8 (puesto 5.º)" in text
    assert "si gana Beta, Alfa sumaría 10 puntos (puestos 3.º a 5.º) y Beta 10 (puestos 3.º a 5.º)" in text, "no single zone: none said"
    assert "los demás partidos no se simulan" in text and "Con los demás equipos en sus puntos actuales" in text
    assert narrative.table_scenarios({}) is None and narrative.table_scenarios({"scenarios": {"table": None}}) is None
    unread = {"scenarios": {"table": {"unavailable": "rank_not_by_points"}}}
    assert narrative.table_scenarios(unread) is None, "a table the arithmetic cannot read is not told"
    assert narrative.table_scenarios({"fixture": {}, "scenarios": {"table": {"after": {"draw": {"home": {}, "away": {}}}}}}) is None


def test_the_rules_narrative_says_the_tactics_as_counts_with_their_size() -> None:
    sample = {"goals": {"n": 8, "late": {"for": 3, "against": 1}},
              "with_the_score": {"scored_first": {"n": 5, "wins": 4, "draws": 1, "losses": 0},
                                 "conceded_first": {"n": 1, "wins": 0, "draws": 0, "losses": 1}},
              "substitutions": {"with_substitutions": 7, "first_minute": {"median": 62.0}}}
    content = {"fixture": {"home": {"name": "Alfa"}, "away": {"name": "Beta"}}, "dossier": {"tactics": {"home": sample}}}
    assert narrative.tactic_notes(content, "home") == (
        "Alfa: en 8 partidos con eventos marcó 3 goles y encajó 1 gol después del minuto 75; "
        "cuando marcó primero (5 partidos): 4 victorias, 1 empate y 0 derrotas; "
        "cuando recibió primero (1 partido): 0 victorias, 0 empates y 1 derrota; "
        "el primer cambio llega, en la mediana, en el minuto 62.")
    assert narrative.tactic_notes(content, "away") is None, "a side without the block says nothing"
    text = narrative.tactics(content)
    assert "Alfa: en 8 partidos con eventos" in text and "Son conteos de pocos partidos: describen lo ocurrido, no predicen." in text
    assert narrative.tactic_notes({"dossier": {"tactics": {"home": {"goals": {"n": 0}}}}}, "home") is None
    assert "no predicen" not in narrative.tactics({"fixture": {}, "dossier": {"tactics": {}}}), "nothing to say, nothing said"
    assert not any(word in text.lower() for word in ("presiona", "presión alta", "se cierra atrás", "estilo")), \
        "a count is not a style: the provider has no positions and no pressure"


def test_a_short_head_to_head_says_how_short_it_is() -> None:
    content = {"dossier": {"h2h": {"relevance": "baja", "n": 1, "n_effective": 1.0}}}
    assert "El historial directo dice poco (1 cruce, 1.0 efectivos)." in narrative.risks(content, [])
    content["dossier"]["h2h"] = {"relevance": "nula", "n": 5, "n_effective": 1.4}
    assert "El historial directo dice poco (5 cruces, 1.4 efectivos)." in narrative.risks(content, [])
    content["dossier"]["h2h"] = {"relevance": "baja"}
    assert "El historial directo dice poco." in narrative.risks(content, []), "an older block has no size to say"
    content["dossier"]["h2h"] = {"relevance": "alta", "n": 9, "n_effective": 6.5}
    assert "dice poco" not in narrative.risks(content, [])
    assert narrative.VERSION == "narrative-v4"
