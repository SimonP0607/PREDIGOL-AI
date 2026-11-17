"""The unified deep research in shadow (IA-087; ``fbi.ai.unified_research``). No database, no model: ``read_page`` with a scripted ``ask``.

* only a source the directory lists as authorised AND the owner signed reaches a model (a spy counts 0 calls for the others);
* a page with an order ANYWHERE - the 64 deep attacks of ``attacks_deep``, past the 700th character - is never sent, and the eight honest pages
  with honest imperatives are;
* one page, one call; a page already extracted (its fingerprint) is never paid again;
* what a model writes is checked again by ``name-match-v2`` («Copa del Rey» is not Oriol Rey) and must sit in ONE window;
* line-ups and lists of absentees are grouped by code (``LIST``);
* the switch is off by default and its word is in the switches' ledger only once moved.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

import pytest

from fbi.ai import commands, gates, mentions, quarantine, source_policy, unified_research
from fbi.ai.battery import attacks_deep
from fbi.ai.config import AiSettings
from fbi.ai.contracts.claim import words as claim_words
from fbi.ai.providers.base import JsonRequest
from fbi.analyst.search import SearchResult

AT = datetime(2026, 11, 16, 12, 0, tzinfo=UTC)
AUTHORISED = source_policy.Standing("diario.example", "diario.example", "verificada_autorizada", "x-diario", signed=True)
PENDING = source_policy.Standing("otro.example", "otro.example", "verificada_pendiente_derechos", "x-otro")
RESERVED = source_policy.Standing("eltiempo.com", "eltiempo.com", "solo_referencia", "co-eltiempo", ai_reserved=True)
BLOCK = {"id": 1, "home": "Home FC", "away": "Away CF", "kickoff_at": AT.isoformat(), "competition": "Liga"}


def roster(*players: tuple[int, int, str], teams: tuple[tuple[int, str], ...] = ((1, "Home FC"), (2, "Away CF"))) -> unified_research.Roster:
    cands = [mentions.Candidate("TEAM", tid, tid, (name,), "home" if tid == 1 else "away") for tid, name in teams]
    cands += [mentions.Candidate("PLAYER", pid, tid, (name,), "home" if tid == 1 else "away") for pid, tid, name in players]
    persons = [p for c in cands if (p := quarantine.person(c.kind, c.id, c.name, team_id=c.team_id, side=c.side)) is not None]  # type: ignore[arg-type]
    return unified_research.Roster(mentions.Catalogue.of(cands, context_names=["Copa del Rey"]), tuple(persons), frozenset(), None, ())


DEEP_ROSTER = roster((101, 2, "D. Keeper"), (102, 2, "C. Defender"))


def page(text: str, title: str = "Home FC - Away CF: previa", url: str = "https://diario.example/a") -> SearchResult:
    return SearchResult(url, title, "diario.example", "2026-11-16T08:00:00+00:00", AT.isoformat(), text)


class Spy:
    """The model: records every request; answers with ``script(doc)`` (the message as JSON) or an honest reader."""

    def __init__(self, script: Any = None) -> None:
        self.asked: list[JsonRequest] = []
        self.script = script

    def __call__(self, req: JsonRequest, h: str) -> quarantine.Asked:
        assert h.startswith(unified_research.LEDGER_PREFIX)
        self.asked.append(req)
        doc = json.loads(req.user)
        body = self.script(doc) if self.script else honest(doc)
        return quarantine.Asked(body, None, 0.0005)


def honest(doc: dict[str, Any]) -> dict[str, Any]:
    """One claim per listed player: the sentence of the page that names him, typed by the first type whose words it holds."""
    text = doc["page"]["text"]
    claims = []
    for s in doc["subjects"]:
        if s["kind"] != "PLAYER":
            continue
        surname = s["name"].split()[-1]
        sentence = next((x.strip() for x in commands.sentences(text) if surname in x), None)
        if sentence is None:
            continue
        kind = next((t for t in ("SUSPENSION", "DOUBT", "OUT", "STARTER", "AVAILABLE") if quarantine.CUE_PATTERNS[t].search(
            " ".join(claim_words(sentence)))), "OUT")
        claims.append({"subject": s["ref"], "claim_type": kind, "applies_to": "THIS_MATCH", "quote": sentence[:290]})
    return {"contract": "claim-v2", "call": doc["call"], "claims": claims}


def read(result: SearchResult, r: unified_research.Roster = DEEP_ROSTER, *, standing: source_policy.Standing = AUTHORISED, spy: Spy | None = None,
         known: dict[str, Any] | None = None) -> unified_research.PageRead:
    return unified_research.read_page(result, r, match_block=BLOCK, standing=standing, common=frozenset(), ask=spy,
                                      known=lambda fp: (known or {}).get(fp))


def test_the_switch_is_off_by_default_and_its_word_is_recorded_only_once_moved(monkeypatch: pytest.MonkeyPatch) -> None:
    assert AiSettings().research_unified == "off"
    for word, want in (("", "off"), ("on", "off"), ("1", "off"), ("Shadow", "shadow")):
        monkeypatch.setenv("FBI_AI_RESEARCH_UNIFIED", word)
        assert AiSettings.from_env().research_unified == want
    assert "research_unified" not in gates.switch_words(AiSettings())
    assert gates.switch_words(AiSettings(research_unified="shadow"))["research_unified"] == "shadow"


@pytest.mark.parametrize("case", attacks_deep.DEEP, ids=[c.id for c in attacks_deep.DEEP])
def test_a_page_with_an_order_anywhere_is_never_sent(case: attacks_deep.DeepCase) -> None:
    spy = Spy()
    got = read(page(case.text, case.title), spy=spy)
    assert spy.asked == [] and got.outcome in ("tainted", "unnamed"), got.outcome


@pytest.mark.parametrize("case", attacks_deep.BENIGN, ids=[c.id for c in attacks_deep.BENIGN])
def test_an_honest_page_with_honest_imperatives_is_sent_once_and_its_facts_stand(case: attacks_deep.DeepCase) -> None:
    spy = Spy()
    got = read(page(case.text, case.title), spy=spy)
    assert len(spy.asked) == 1 and got.outcome == "read"
    assert {c.id for c in got.claims} == {101, 102}, (case.id, got.dropped)


def test_only_an_authorised_and_signed_source_reaches_a_model() -> None:
    text = attacks_deep.BENIGN[1].text
    for standing, outcome in ((PENDING, "not_authorised"), (RESERVED, "blocked_ai_reserved"),
                              (source_policy.Standing("x.example", "x.example", "verificada_autorizada", "x", signed=False), "not_authorised")):
        spy = Spy()
        assert read(page(text), standing=standing, spy=spy).outcome == outcome
        assert spy.asked == []


def test_a_page_extracted_once_is_never_paid_again() -> None:
    spy = Spy()
    first = read(page(attacks_deep.BENIGN[1].text), spy=spy)
    assert first.fp is not None
    stored: dict[str, Any] = {first.fp: {"claims": [c.as_json(keep_quote=True) for c in first.claims], "lists": []}}
    again = read(page(attacks_deep.BENIGN[1].text, url="https://copia.example/b"), spy=spy, known=stored)
    assert len(spy.asked) == 1 and again.outcome == "reused" and {c.id for c in again.claims} == {101, 102}


def test_no_call_when_the_day_has_no_calls_left() -> None:
    got = unified_research.read_page(page(attacks_deep.BENIGN[1].text), DEEP_ROSTER, match_block=BLOCK, standing=AUTHORISED, common=frozenset(),
                                     ask=None, known=lambda fp: None)
    assert got.outcome == "capped"


def test_copa_del_rey_written_about_oriol_rey_does_not_stand() -> None:
    r = roster((10, 1, "Oriol Rey"), (11, 1, "Iván Romero"))
    text = "Iván Romero no jugará el domingo por lesión. El Home FC quedó eliminado de la Copa del Rey y sigue de baja en la tabla."

    def lie(doc: dict[str, Any]) -> dict[str, Any]:
        refs = {s["name"]: s["ref"] for s in doc["subjects"]}
        return {"contract": "claim-v2", "call": doc["call"], "claims": [
            {"subject": refs.get("Oriol Rey", "S9"), "claim_type": "OUT", "applies_to": "THIS_MATCH",
             "quote": "quedó eliminado de la Copa del Rey y sigue de baja"},
            {"subject": refs["Iván Romero"], "claim_type": "OUT", "applies_to": "THIS_MATCH", "quote": "Iván Romero no jugará el domingo por lesión"}]}

    spy = Spy(lie)
    got = read(page(text), r, spy=spy)
    assert [c.id for c in got.claims] == [11]
    assert sum(got.dropped.values()) == 1


def test_a_quote_across_two_windows_does_not_stand() -> None:
    filler = "El club informó de la venta de abonos para la próxima temporada y del horario de la tienda oficial. " * 25
    text = f"Delantero Uno no jugará el domingo.\n\n{filler}\n\nExtremo Dos es duda para el partido."
    r = roster((101, 1, "Delantero Uno"), (201, 2, "Extremo Dos"))

    def stitch(doc: dict[str, Any]) -> dict[str, Any]:
        refs = {s["name"]: s["ref"] for s in doc["subjects"]}
        sent = doc["page"]["text"]
        assert unified_research.SEPARATOR in sent, "two windows of one page in one call"
        across = sent[sent.index("domingo"):sent.index("Extremo") + 11]
        return {"contract": "claim-v2", "call": doc["call"], "claims": [
            {"subject": refs["Delantero Uno"], "claim_type": "OUT", "applies_to": "THIS_MATCH", "quote": across[:290]}]}

    got = read(page(text), r, spy=Spy(stitch))
    assert got.claims == []


def test_a_line_up_is_grouped_into_a_list() -> None:
    names = ["Arquero Alfa", "Lateral Beto", "Central Ceta", "Medio Delta"]
    r = roster(*((300 + i, 1, n) for i, n in enumerate(names)))
    text = "Alineación probable del Home FC: " + ", ".join(names) + " serán titulares ante el Away CF."

    def lineup(doc: dict[str, Any]) -> dict[str, Any]:
        sent = doc["page"]["text"]
        claims = [{"subject": s["ref"], "claim_type": "STARTER", "applies_to": "THIS_MATCH",
                   "quote": sent[sent.index(s["name"]):sent.index("titulares") + len("titulares")]}
                  for s in doc["subjects"] if s["kind"] == "PLAYER"]
        return {"contract": "claim-v2", "call": doc["call"], "claims": claims}

    got = read(page(text), r, spy=Spy(lineup))
    assert got.lists and got.lists[0]["type"] == "LIST_STARTER" and len(got.lists[0]["players"]) >= unified_research.LIST_MIN
    assert len(got.lists[0]["quote"]) <= unified_research.LIST_QUOTE_MAX


def test_an_answer_with_the_wrong_code_word_stands_for_nothing() -> None:
    got = read(page(attacks_deep.BENIGN[1].text), spy=Spy(lambda doc: {**honest(doc), "call": "DONE"}))
    assert got.outcome == "invalid" and got.claims == []
