"""What the pick reviewer reads of a packet (``fbi.ai.views``, plan F6).

Packet-v8 carries four blocks that DESCRIBE a match and that no experiment has shown to predict anything: the weighted head-to-head, the
scenarios, the tactics and the registry of the factors. They are a good half as many tokens again as the packet had, and the pick reviewer (the
dearest call PrediGol makes, the one whose answer weighs on whether a pick is shown) reads the whole packet it is given. So it is given the
packet as it was before plan F6 until a person validates a factor; the brief, which describes the match for the owner, keeps reading all of it.
"""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from fbi.ai.claims import ClaimOut, ReviewOut, check
from fbi.ai.packet import Packet, canonical
from fbi.ai.review import prompt_content, signals_for
from fbi.ai.views import (
    HIDDEN_MISSING,
    OLDER,
    PLAIN,
    review_hash,
    review_missing,
    review_view,
    validated_factors,
)
from fbi.intel import factors, scenarios, tactics
from fbi.intel import h2h as h2h_mod

from .test_ai_decisions import AT, home, packet
from .test_h2h_weights import KICKOFF, meeting, situation

F6_ONLY = ("scenarios", "factors")
"""The blocks of the packet that did not exist before plan F6."""


def v7_content() -> dict[str, Any]:
    """A packet as it was before plan F6: what the production reviewer reads today (a head-to-head of two keys, a dossier without tactics)."""
    content = copy.deepcopy(packet().content)
    content["h2h"] = {"n": 3, "home_view": {"n": 3, "points_per_match": 1.67, "goals_for": 1.0, "goals_against": 0.67}}
    content["dossier"] = {"version": "dossier-v3", "teams": {"home": {"n": 10}, "away": {"n": 10}}, "referee": None,
                          "context": {"round": "league"}, "h2h": {"n": 3, "last_days_ago": 120, "relevance": "media",
                                                                  "note": h2h_mod.NOTE_LOW}, "national": None}
    return content


def v8_packet(*validated: str) -> Packet:
    """The same packet as packet-v8 says it: the weighted head-to-head, the scenarios, the tactics and the registry - every factor
    DESCRIPTIVE (as every one is born) except the ones named."""
    content = v7_content()
    meetings = [meeting(days, goals=g) for days, g in ((40, (2, 1)), (400, (0, 0)), (900, (1, 3)))]
    weighed = h2h_mod.weigh(meetings, situation())
    block = weighed.as_packet(status=factors.DESCRIPTIVE)
    assert block["n"] == 3 and "record" in block and "weights" in block, "a real block, with its detail"
    content["h2h"] = block
    content["dossier"]["version"] = "dossier-v4"
    content["dossier"]["h2h"]["n_effective"] = round(weighed.n_effective, 1)
    content["dossier"]["tactics"] = {"version": tactics.VERSION, "status": factors.DESCRIPTIVE,
                                     "home": {"n": 10, "formations": [{"formation": "4-3-3", "n": 6}]},
                                     "away": {"n": 10, "formations": [{"formation": "4-4-2", "n": 7}]}}
    content["scenarios"] = scenarios.scenarios_block({"group": "A", "home": {"win": {"points": 12}}}, None)
    registry = factors.block(factors.unread())
    for key in validated:
        registry[key]["status"] = factors.VALIDATED
    content["factors"] = registry
    return Packet(1, AT, content, missing=["factors"] if not validated else [])


def without(d: dict[str, Any], *keys: str) -> dict[str, Any]:
    return {k: v for k, v in d.items() if k not in keys}


# ── while every factor is DESCRIPTIVE the reviewer reads the packet of before plan F6 ──────────────────────────────────────────


def test_while_every_factor_is_descriptive_the_reviewer_reads_the_packet_of_before_plan_f6() -> None:
    p = v8_packet()
    view = review_view(p.content)
    assert not set(F6_ONLY) & set(view), "no scenarios and no registry"
    assert set(view["h2h"]) == {"n", "home_view"} == set(PLAIN[factors.H2H] or ()), "the two keys the block always carried"
    assert view["h2h"] == {k: p.content["h2h"][k] for k in ("n", "home_view")}, "and they are the block's own"
    assert "tactics" not in view["dossier"]
    assert without(view["dossier"], "version", "h2h") == without(v7_content()["dossier"], "version", "h2h")
    rest = ("h2h", "dossier", *F6_ONLY)
    assert without(view, *rest) == without(p.content, *rest), "everything else is as the packet has it"
    assert set(view["dossier"]["h2h"]) - {"n_effective"} == set(v7_content()["dossier"]["h2h"]), "(the dossier's count of the effective size aside)"


def test_the_view_is_about_the_size_the_packet_had_before_plan_f6_and_far_below_the_packet_of_v8() -> None:
    p = v8_packet()
    before, now, view = (len(canonical(c)) for c in (v7_content(), p.content, review_view(p.content)))
    assert now > before * 1.25, "the blocks of plan F6 are a big part of the packet"
    assert view < before * 1.01, f"the reviewer reads {view} bytes, the packet of before read {before}"


def test_a_packet_of_before_plan_f6_is_given_as_it_is() -> None:
    content = v7_content()
    assert review_view(content) == content
    assert review_view(packet().content) == packet().content, "and one without a head-to-head or a dossier too"
    assert review_view({}) == {}


def test_the_packet_itself_is_not_touched() -> None:
    p = v8_packet(factors.TACTICS)
    before = copy.deepcopy(p.content)
    review_view(p.content)
    assert p.content == before, "the brief, the rules and the stored packet still have all of it"


# ── what a person validates is given back whole ────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("key", [factors.H2H, factors.SCENARIOS, factors.TACTICS])
def test_a_validated_factor_is_given_back_whole_with_its_entry_and_only_its_entry(key: str) -> None:
    p = v8_packet(key)
    view = review_view(p.content)
    block = factors.BY_KEY[key].block
    mine = view
    for step in block:
        mine = mine[step]
    original = p.content
    for step in block:
        original = original[step]
    assert mine == original, f"{key}: its block, whole"
    assert set(view["factors"]) == {"version", "note", key}, "the registry says only what a person decided"
    assert view["factors"][key] == p.content["factors"][key]
    for other in (factors.H2H, factors.SCENARIOS, factors.TACTICS):
        if other == key:
            continue
        gone = review_view(p.content)
        node: Any = gone
        for step in factors.BY_KEY[other].block[:-1]:
            node = node[step]
        if other == factors.H2H:
            assert set(node["h2h"]) == {"n", "home_view"}
        else:
            assert factors.BY_KEY[other].block[-1] not in node, f"{other} is still DESCRIPTIVE: not given"


def test_every_factor_validated_is_the_whole_packet_of_v8() -> None:
    p = v8_packet(factors.H2H, factors.SCENARIOS, factors.TACTICS)
    view = review_view(p.content)
    assert without(view, "factors") == without(p.content, "factors"), "nothing is hidden when a person has validated all of it"
    assert set(view["factors"]) == {"version", "note", factors.H2H, factors.SCENARIOS, factors.TACTICS}, "(the registry says what was decided)"


def test_a_validated_factor_that_the_packet_has_no_block_for_is_nothing_to_give() -> None:
    p = v8_packet(factors.SCENARIOS)
    del p.content["scenarios"]  # no table of its own stage and no tie: the block is absent
    view = review_view(p.content)
    assert "scenarios" not in view and set(view["factors"]) == {"version", "note", factors.SCENARIOS}


# ── the safe side of every doubt ───────────────────────────────────────────────────────────────────────────────────────────────


def test_a_registry_that_does_not_say_is_read_as_descriptive() -> None:
    reference = review_view(v8_packet().content)
    odd: list[Any] = [None, "VALIDATED", ["VALIDATED"], {}, {factors.H2H: "VALIDATED"}, {factors.H2H: {"status": "validated"}},
                      {factors.H2H: {"status": "PROMOTED"}}, {factors.H2H: {}}, {"made_up": {"status": "VALIDATED"}}]
    for registry in odd:
        p = v8_packet()
        p.content["factors"] = registry
        assert review_view(p.content) == reference, registry
    p = v8_packet()
    del p.content["factors"]
    assert review_view(p.content) == reference, "a packet with no registry at all"


def test_a_registry_that_could_not_be_read_hides_everything_and_says_nothing_of_it() -> None:
    p = v8_packet()
    p.content["factors"] = factors.block(factors.unread(), error="OperationalError")
    p.missing.append("h2h")
    view = review_view(p.content)
    assert "factors" not in view and set(view["h2h"]) == {"n", "home_view"}
    assert review_missing(p.missing) == ["h2h"], "the registry is not a gap in what the reviewer reads; a head-to-head that is missing is"


def test_a_block_that_is_not_a_block_is_left_alone() -> None:
    """A packet the builder never wrote (a stored one from another version, a test double) must not break the reviewer's cycle."""
    cases: list[tuple[dict[str, Any], dict[str, Any]]] = [
        ({"h2h": None, "dossier": None}, {"h2h": None, "dossier": None}),
        ({"h2h": [], "dossier": []}, {"h2h": [], "dossier": []}),
        ({"dossier": "x"}, {"dossier": "x"}),
        ({"dossier": {"tactics": None}}, {"dossier": {}}),
        ({"h2h": {"n": 0}}, {"h2h": {"n": 0}}),
    ]
    for content, expected in cases:
        assert review_view({**content, "factors": factors.block(factors.unread())}) == expected


# ── the catalogue and this module agree ────────────────────────────────────────────────────────────────────────────────────────────


def test_every_factor_of_the_catalogue_is_decided_here() -> None:
    """A factor added to the catalogue comes DESCRIPTIVE with a block in the packet: it must be said here whether the reviewer is given it
    (and which keys of it) or whether the block is older than the registry. Otherwise it is left out whole, which is the safe side."""
    assert set(PLAIN) | OLDER == {f.key for f in factors.CATALOGUE}
    assert not set(PLAIN) & OLDER
    p = v8_packet()
    for key in PLAIN:
        node: Any = p.content
        for step in factors.BY_KEY[key].block:
            node = node[step]  # the block the catalogue names is where the packet has it
        assert node
    for key in OLDER:
        assert factors.BY_KEY[key].states is False, "a block that says its own status is a block of plan F6"


def test_the_block_of_a_factor_older_than_the_registry_is_not_a_matter_of_plan_f6() -> None:
    p = v8_packet()
    assert review_view(p.content)["schedule"] == p.content["schedule"], "the calendar's schedule block has always been read"


def test_a_factor_nobody_decided_here_is_left_out_whole(monkeypatch: pytest.MonkeyPatch) -> None:
    new = factors.Factor("new_context", "new-v1", ("new_block",), True, "Nuevo", "que algo")
    monkeypatch.setattr(factors, "CATALOGUE", (*factors.CATALOGUE, new))
    p = v8_packet()
    p.content["new_block"] = {"status": "DESCRIPTIVE", "n": 3}
    assert "new_block" not in review_view(p.content)


def test_validated_factors_reads_the_registry_block_and_nothing_else() -> None:
    assert validated_factors({}) == frozenset()
    assert validated_factors(v8_packet().content) == frozenset()
    assert validated_factors(v8_packet(factors.H2H, factors.TACTICS).content) == {factors.H2H, factors.TACTICS}
    assert validated_factors({"factors": {"version": "factors-v1", "note": "VALIDATED"}}) == frozenset()


# ── what the answer is remembered by ───────────────────────────────────────────────────────────────────────────────────────────────


def test_a_change_only_in_what_the_reviewer_is_not_given_buys_no_second_review() -> None:
    a, b = v8_packet(), v8_packet()
    b.content["scenarios"]["table"]["home"]["win"]["points"] = 99
    b.content["dossier"]["tactics"]["home"]["n"] = 7
    b.content["h2h"]["record"] = {"home_side_wins": 0}
    b.content["h2h"]["meetings"][0]["weight"] = 0.01
    b.content["factors"]["h2h_weighted"]["version"] = "h2h-v9"
    assert a.hash != b.hash, "the packet changed"
    assert review_hash(a, review_view(a.content)) == review_hash(b, review_view(b.content)), "what the reviewer reads did not"


def test_a_change_in_what_the_reviewer_reads_buys_one() -> None:
    a = v8_packet()
    base = review_hash(a, review_view(a.content))
    for edit in (lambda c: c["market"]["selections"][0].update(best_odds=2.6),
                 lambda c: c["h2h"].update(n=4),
                 lambda c: c["dossier"]["h2h"].update(relevance="alta"),
                 lambda c: c["lineups"].update(confirmed=True)):
        b = v8_packet()
        edit(b.content)
        assert review_hash(b, review_view(b.content)) != base
    c = v8_packet()
    c.missing.append("market")
    assert review_hash(c, review_view(c.content)) != base, "a gap in what it reads"
    d = v8_packet(factors.SCENARIOS)
    assert review_hash(d, review_view(d.content)) != base, "a factor a person validated is something new to read"


def test_the_hash_depends_on_the_version_of_the_packet() -> None:
    a = v8_packet()
    older = Packet(a.fixture_id, a.as_of, a.content, version="packet-v7")
    assert review_hash(a, review_view(a.content)) != review_hash(older, review_view(older.content))


def test_hidden_gaps_are_named_here() -> None:
    assert set(HIDDEN_MISSING) == {"factors"}
    assert review_missing(["h2h", "factors", "elo"]) == ["h2h", "elo"]
    assert review_missing([]) == []


# ── the prompt, and the claims it is checked against ─────────────────────────────────────────────────────────────────────────────


def test_the_prompt_of_the_review_carries_the_view_and_the_gaps_it_can_see() -> None:
    p = v8_packet()
    p.missing[:] = ["factors", "h2h"]
    c = home()
    body = json.loads(prompt_content(c, p, signals_for(c, p, at=AT), at=AT))
    assert not set(F6_ONLY) & set(body["packet"]) and "tactics" not in body["packet"]["dossier"]
    assert set(body["packet"]["h2h"]) == {"n", "home_view"}
    assert body["missing"] == ["h2h"]
    text = json.dumps(body)
    for word in ("weights_note", "half_life_days", "meetings", "formations", "scenarios", "context_factors"):
        assert word not in text, word
    full = json.loads(prompt_content(c, p, signals_for(c, p, at=AT), at=AT, view=p.content))
    assert "scenarios" in full["packet"] and len(json.dumps(full)) > len(text) * 1.2, "the packet whole is the dearer prompt"


def test_the_same_prompt_is_built_from_the_view_given_or_from_the_packet() -> None:
    p = v8_packet()
    c = home()
    signals = signals_for(c, p, at=AT)
    assert prompt_content(c, p, signals, at=AT) == prompt_content(c, p, signals, at=AT, view=review_view(p.content))


def test_a_claim_that_only_a_block_the_reviewer_was_not_given_could_support_is_refused() -> None:
    """The reviewer's claims are checked against what it read: 99 points is in the scenarios, which it did not get."""
    p = v8_packet()
    p.content["scenarios"]["table"]["home"]["win"]["points"] = 99.5
    text = "El local sumaría 99.5 puntos con una victoria."
    out = ReviewOut(decision="REJECT", confidence=0.6, context_score=0.5, model_score=0.5, market_score=0.5,
                    negative_evidence=[ClaimOut(text=text, type="DATA", refs=["P:scenarios"])], reason="Prueba de la vista.")
    full = check(out, packet_content=p.content, evidence_status={})
    seen = check(out, packet_content=review_view(p.content), evidence_status={})
    assert full.rejected == [] and full.review.decision == "REJECT", "the packet whole would have let it through"
    assert [r["why"] for r in seen.rejected] == ["numbers not in the packet: 99.5"]
    assert seen.review.decision == "ABSTAIN", "and a REJECT that rests on nothing left standing is not taken"


def test_the_start_of_a_kickoff_is_not_a_hidden_number() -> None:
    """A sanity check of the fixtures this file builds: the head-to-head is of meetings before the match."""
    assert all(m.kickoff_at < KICKOFF for m in (meeting(40), meeting(400)))
