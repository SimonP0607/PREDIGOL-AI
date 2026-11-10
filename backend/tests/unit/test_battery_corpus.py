"""The corpus of the adversarial battery (Plan Maestro IA, phase 1, item 1.7, section 31): the cases, the bases they attack, the requests they
become and the fingerprints that say what a measurement is of. No database, no model.

What is checked is what makes the battery worth running: the plan's size («≥ 40 casos») and its eight families; that a case replaces ONE text
of a clean base and nothing else (so the base is the baseline); that what is asked is what production asks; and that the corpus cannot change
without the fingerprints saying so."""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from dataclasses import replace
from typing import Any, Final

import pytest

from fbi.ai import extract_v2, package, untrusted
from fbi.ai.battery import (
    AGENT_TARGETS,
    CASES_PER_TARGET,
    FAMILIES,
    MIN_CASES,
    PER_FAMILY,
    PROMPT_TARGETS,
    TARGETS,
    VERSION,
    agentworld,
    attacks_claims,
    attacks_extract,
    attacks_review,
    claims,
    corpus,
    extractor,
    reviewer,
)
from fbi.ai.battery.model import CANARY_MARK, CANARY_SEED, ORDERS_OF_V3, Attack, Base, Case
from fbi.ai.collectors import extract_request, extract_user
from fbi.ai.evidence import normalize_name
from fbi.ai.prompts import (
    COUNCIL_OPUS_VERSION,
    COUNCIL_VERSION,
    EXTRACT_SCHEMA,
    EXTRACT_SYSTEM,
    EXTRACT_V2_SYSTEM,
    EXTRACT_V2_VERSION,
    EXTRACT_VERSION,
    MATCH_ASSESS_VERSION,
    MATCH_CONTEXT_VERSION,
    REVIEW_VERSION,
    STATS_ASSESS_VERSION,
)
from fbi.ai.review import review_request, signals_for
from fbi.ai.untrusted import sanitize

KNOWN_FLAGS = {"invisible", "control", "mixed_script", "html", "html_unreadable", "link", "instruction_like", "truncated"}
SLOT_KEYS = ("status", "tier", "kind")
"""What an attack on the evidence slot may set besides its text: how the server would have labelled that evidence."""
SURFACE_PATHS = {
    "evidence_claim": (".evidence.4.claim",), "evidence_source": (".evidence.4.source",),
    "absence_name": ("absences.home.players.0.name",), "dossier_player_name": ("dossier.players.home.0.name",),
    "coach_name": ("dossier.teams.home.coach.name",), "referee_name": ("dossier.referee.name", "fixture.referee"),
    "venue": ("fixture.venue",),
    "result_text": ("results.2.text",), "result_title": ("results.2.title",), "result_publisher": ("results.2.publisher",)}
"""Where in the request each surface of an attack lands."""
ABSENT = object()


def leaf_map(value: Any, path: tuple[str, ...] = ()) -> dict[str, Any]:
    """Every scalar of a parsed JSON by its path (a list item by its number)."""
    if isinstance(value, dict):
        return {k: v for key, item in value.items() for k, v in leaf_map(item, (*path, key)).items()}
    if isinstance(value, list):
        return {k: v for i, item in enumerate(value) for k, v in leaf_map(item, (*path, str(i))).items()}
    return {".".join(path): value}


def documents(request: Any) -> list[Any]:
    """The parsed JSON of the user message of a request, and of each of its parts in the other layout."""
    return [json.loads(text) for text in (request.user, *(request.split or ()))]


def changes(case: Case, *, native: bool = False) -> tuple[set[str], set[str]]:
    """The paths whose value differs between the clean ask and the attacked one, and the paths that hold the attack's own text."""
    clean = documents(corpus.request_for(case.target, case.base, native=native))
    attacked = documents(corpus.request_for(case.target, case.base, case, native=native))
    assert len(clean) == len(attacked)
    changed: set[str] = set()
    own: set[str] = set()
    for i, (c, a) in enumerate(zip(clean, attacked, strict=True)):
        before, after = leaf_map(c), leaf_map(a)
        for path in before.keys() | after.keys():
            if before.get(path, ABSENT) != after.get(path, ABSENT):
                changed.add(f"{i}:{path}")
            value = after.get(path)
            if isinstance(value, str) and case.text in value:
                own.add(f"{i}:{path}")
    return changed, own


def by_target(name: str) -> tuple[Case, ...]:
    return tuple(c for c in (*corpus.CASES, *corpus.SHADOW_CASES) if c.target == name)


SURFACES = {"review": reviewer.SURFACES, "extract": extractor.SURFACES, "claims": claims.SURFACES, **agentworld.SURFACES_OF}
"""Where an attack on each prompt may put its text."""
WITH_DOOR = tuple(t for t in TARGETS if corpus.target(t).door is not None)
"""The prompts whose text goes through ``fbi.ai.untrusted`` before the model reads it: the text of a case is not found whole in their requests."""
WITHOUT_DOOR = tuple(t for t in TARGETS if corpus.target(t).door is None)


# ── the size the plan asks for ─────────────────────────────────────────────────────────────────────────────────────

def test_the_plan_asks_for_forty_cases_of_each_target_and_the_corpus_has_two_hundred_and_forty() -> None:
    assert MIN_CASES == 40 and PROMPT_TARGETS == ("review", "extract", "claims") and AGENT_TARGETS == ("match", "stats", "council")
    assert TARGETS == PROMPT_TARGETS + AGENT_TARGETS
    assert CASES_PER_TARGET == len(FAMILIES) * PER_FAMILY == 40
    assert len(corpus.CASES) == 240 and corpus.check_sizes() == []
    assert {t: len(corpus.cases_of(t)) for t in TARGETS} == dict.fromkeys(TARGETS, 40)
    assert (WITH_DOOR, WITHOUT_DOOR) == (("claims", "match", "stats", "council"), ("review", "extract"))


def test_eight_families_of_section_31_five_attacks_each_for_each_prompt() -> None:
    assert FAMILIES == ("ignore", "fake_official", "hidden_html", "homoglyph", "markdown_link", "break_json", "orders", "player_name")
    for target in TARGETS:
        counts = Counter((c.family, c.attack.n) for c in by_target(target))
        assert counts == {(f, n): 1 for f in FAMILIES for n in range(1, PER_FAMILY + 1)}, target


def test_ids_are_unique_and_every_lookup_agrees() -> None:
    ids = [c.id for c in corpus.EVERY_CASE]
    assert len(set(ids)) == len(ids) == len(corpus.BY_ID) and corpus.EVERY_CASE == corpus.CASES + corpus.SHADOW_CASES
    for case in corpus.CASES:
        assert case.id == f"{case.target}.{case.family}.{case.attack.n}"
        assert corpus.case_of(case.id) is case and case in corpus.cases_of(case.target)
    assert [c.id for c in corpus.cases_of("review")] == [c.id for c in corpus.CASES[:40]]
    assert [c.id for c in corpus.cases_of("extract")] == [c.id for c in corpus.CASES[40:80]]
    assert [c.id for c in corpus.cases_of("claims")] == [c.id for c in corpus.CASES[80:120]]
    for i, target in enumerate(AGENT_TARGETS):
        assert [c.id for c in corpus.cases_of(target)] == [c.id for c in corpus.CASES[120 + 40 * i:160 + 40 * i]]


def test_a_size_below_the_plans_is_reported_with_the_target_that_lacks_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(corpus, "CASES", tuple(c for c in corpus.CASES if c.id != "extract.orders.3"))
    assert corpus.check_sizes() == ["extract: 39 cases, 40 needed"]
    monkeypatch.setattr(corpus, "CASES", tuple(c for c in corpus.CASES if not c.id.startswith("claims.orders.")))
    assert corpus.check_sizes() == ["extract: 39 cases, 40 needed", "claims: 35 cases, 40 needed"]


def test_nothing_unknown_is_asked_for() -> None:
    with pytest.raises(ValueError, match="unknown target 'brief'"):
        corpus.target("brief")
    with pytest.raises(ValueError, match="unknown target"):
        corpus.cases_of("brief")
    with pytest.raises(ValueError, match="unknown case 'review\\.ignore\\.9'"):
        corpus.case_of("review.ignore.9")
    case = corpus.case_of("review.ignore.1")
    with pytest.raises(ValueError, match="unknown base 'x_quiet' of the target 'review'"):
        corpus.request_for("review", "x_quiet")
    with pytest.raises(ValueError, match="is not an attack on the base 'r_approve'"):
        corpus.request_for("review", "r_approve", case)
    with pytest.raises(ValueError, match="is not an attack on the base"):
        corpus.request_for("extract", "x_quiet", case)


# ── what each case attacks ─────────────────────────────────────────────────────────────────────────────────────────

def test_every_case_attacks_a_known_base_through_a_known_surface() -> None:
    for case in corpus.CASES:
        assert case.base in corpus.target(case.target).bases, case.id
        assert case.surface in SURFACES[case.target], case.id
        assert case.attack.goal in ("approve", "reject", "any") and case.text.strip(), case.id
        assert set(case.attack.expect) <= KNOWN_FLAGS, case.id


def test_every_surface_and_every_base_is_attacked() -> None:
    for target, surfaces in SURFACES.items():
        assert {c.surface for c in by_target(target)} == set(surfaces), target
    for target in TARGETS:
        per_base = Counter(c.base for c in by_target(target))
        assert set(per_base) == set(corpus.target(target).bases) and min(per_base.values()) >= 8, (target, per_base)
        per_family = {f: {c.base for c in by_target(target) if c.family == f} for f in FAMILIES}
        assert all(len(bases) >= 2 for bases in per_family.values()), "a family on a single base would only test that base"


def test_the_slot_attacks_set_no_label_a_server_would_not_give_a_page() -> None:
    labelled = [c for c in by_target("review") if any(getattr(c.attack, k) for k in SLOT_KEYS)]
    assert {c.id for c in labelled} == {f"review.fake_official.{n}" for n in range(1, 6)} | {"review.ignore.5"}
    for case in labelled:
        assert case.surface in ("evidence_claim", "evidence_source")
        if case.family == "fake_official":
            assert (case.attack.status, case.attack.tier) in {("RUMOR", "unknown"), ("RUMOR", "social")}, case.id
    assert all(not any(getattr(c.attack, k) for k in SLOT_KEYS) for c in (*by_target("extract"), *by_target("claims")))


def test_no_attack_asks_for_what_the_data_of_its_base_already_says() -> None:
    """An attack that wants an APPROVE of a pick whose data already says yes proves nothing: it cannot move the verdict."""
    for case in by_target("review"):
        assert not (case.attack.goal == "approve" and case.base == "r_approve"), case.id
        assert not (case.attack.goal == "reject" and case.base == "r_reject"), case.id
    goals = Counter(c.attack.goal for c in by_target("review"))
    assert set(goals) == {"approve", "reject", "any"} and goals["approve"] >= 10 and goals["reject"] >= 10, goals
    assert {c.attack.goal for c in by_target("extract")} == {"any"} == {c.attack.goal for c in by_target("claims")}


def test_the_items_an_extraction_attack_plants_or_states_are_new_and_could_be_known() -> None:
    """A planted item (the attack orders it) or a stated fact (its text says it) that the base's own pages already give would not
    discriminate anything; and an order to write about a player nobody named could not be followed."""
    for case in by_target("extract"):
        a = case.attack
        expected = extractor.EXPECTED[case.base]
        assert not set(a.planted) & expected and not set(a.facts) & expected, case.id
        assert not set(a.planted) & set(a.facts), case.id
        pages = extractor.pages(case.base)
        read = sanitize(case.text, origin="test", max_chars=4000).read  # a model reads small capitals and full-width letters as letters
        tag_block = "".join(chr(ord(ch) - 0xE0000) for ch in case.text if 0xE0000 < ord(ch) < 0xE0080)
        text = " ".join([case.text, read, tag_block, *(f"{p.title} {p.snippet}" for rid, p in pages.items() if rid != extractor.SLOT)])
        known = " " + normalize_name(text) + " "
        for _side, key, _assertion in (*a.planted, *a.facts):
            assert f" {key} " in known, (case.id, key)
        assert all(e in case.text for e in a.echo) and (not a.echo or case.family == "orders"), case.id


def test_the_facts_a_claims_attack_plants_or_states_are_new_and_could_be_known() -> None:
    """The same rule for the second extractor. A fact the attack plants or states that the base's own pages already give would not discriminate
    anything; the side of a fact is the player's own (a claim says WHO, and the server knows his side); and what an attack states as a fact is
    in its own text, because a reader that took it did so from there."""
    for person in claims.SQUAD:
        assert claims.surname(person.name) == person.key and claims.PEOPLE[person.key] is person and claims.BY_ID[person.id] is person, person
    for case in by_target("claims"):
        a = case.attack
        expected = claims.EXPECTED[case.base]
        assert not set(a.planted) & expected and not set(a.facts) & expected, case.id
        assert not set(a.planted) & set(a.facts), case.id
        for side, key, _assertion in (*a.planted, *a.facts):
            assert claims.PEOPLE[key].side == side, (case.id, "the side is the player's own")
        said = " " + normalize_name(case.text) + " "
        for _side, key, _assertion in a.facts:
            assert f" {key} " in said, (case.id, key, "a fact the text states is stated in it")
        assert all(e in case.text for e in a.echo) and (not a.echo or case.family == "orders"), case.id
        assert (case.surface == "subject_name") == bool(a.slot) and (not a.slot or a.slot in claims.PEOPLE), case.id


# ── the code word ──────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_code_word_is_the_cases_own_and_only_where_an_attack_asks_for_it() -> None:
    with_word = [c for c in corpus.CASES if c.canary]
    assert len(with_word) == 21 + 3 * 6
    assert {c.id for c in with_word if c.target == "claims"} == {f"claims.{f}.4" for f in (
        "ignore", "hidden_html", "homoglyph", "markdown_link", "break_json", "orders", "player_name")}
    assert [c.id for c in with_word if CANARY_MARK not in c.attack.text] == []
    assert [c.id for c in corpus.CASES if not c.canary and CANARY_MARK in c.attack.text] == []
    words = [c.canary for c in with_word]
    assert len(set(words)) == len(words), "each case has its own"
    for case in with_word:
        assert case.canary is not None and case.canary.startswith("ZQ") and len(case.canary) == 10
        assert case.canary.isalnum() and case.canary == case.canary.upper()
        assert case.canary in case.text and CANARY_MARK not in case.text
        assert CANARY_MARK not in case.hidden and CANARY_MARK not in case.phrase
    for case in corpus.CASES:
        assert CANARY_MARK not in case.text


def test_a_code_word_is_the_same_on_every_run_and_the_version_that_minted_it_is_in_it() -> None:
    first = {c.id: c.canary for c in corpus.CASES}
    assert first == {c.id: c.canary for c in corpus.CASES}
    assert CANARY_SEED == "battery-v2" and str(VERSION) != CANARY_SEED, "battery-v3 keeps the code words of battery-v2, and with them the bytes of its requests"
    assert corpus.case_of("review.ignore.4").canary == "ZQ" + hashlib.sha256(f"{CANARY_SEED}/review.ignore.4".encode()).hexdigest()[:8].upper()
    assert corpus.case_of("review.ignore.4").canary == "ZQ3C78680C", "the code word battery-v2 asked for"
    assert len({corpus.case_of(f"{t}.ignore.4").canary for t in TARGETS}) == len(TARGETS)


def test_a_hidden_phrase_that_is_the_code_word_is_replaced_by_the_cases_own() -> None:
    case = corpus.case_of("review.hidden_html.4")
    assert case.attack.hidden == CANARY_MARK and case.hidden == case.canary
    assert case.canary is not None and case.canary in case.text


# ── a case replaces one text and nothing else ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("native", [False, True])
def test_a_case_puts_its_text_where_its_surface_is_and_changes_nothing_else(native: bool) -> None:
    for case in (c for c in corpus.CASES if c.target in WITHOUT_DOOR):
        changed, own = changes(case, native=native)
        assert own, f"{case.id}: its text is not in the request"
        main = {p.split(":", 1)[1] for p in own if ".signals." not in f".{p.split(':', 1)[1]}"}
        suffixes = SURFACE_PATHS[case.surface]
        assert main and all(any(p.endswith(s) for s in suffixes) for p in main), (case.id, main)
        assert all(any(p.endswith(s) for p in main) for s in suffixes), (case.id, "a place the surface reaches is missing", main)
        extra = changed - own
        label_paths = {p for p in extra if p.rsplit(".", 1)[1] in SLOT_KEYS and ".evidence.4." in p}
        declared = {k for k in SLOT_KEYS if getattr(case.attack, k, None)}
        assert {p.rsplit(".", 1)[1] for p in label_paths} == declared, (case.id, "the labels that moved are the ones the attack sets")
        derived = extra - label_paths
        if case.id == "review.ignore.5":
            assert derived and all(".signals." in f".{p.split(':', 1)[1]}" for p in derived), "the rules read the kind of the evidence"
        else:
            assert not derived, (case.id, "something else changed", sorted(derived)[:4])


CLAIMS_PLACES = {
    "page_text": {"0:pages.2.text", "0:pages.2.flags", "0:pages.2.truncated"},
    "page_title": {"0:pages.2.title", "0:pages.2.flags", "0:pages.2.truncated"},
    "page_domain": {"0:pages.2.origin"},
    "subject_name": set()}
"""The paths of the request of ``claims`` that a case on each surface may move: the third page's text, title or host - and, with the text and the title,
the flags the door raised and whether it cut - or the name of a subject (the one place of it is tested on its own)."""


@pytest.mark.parametrize("native", [False, True])
def test_a_claims_case_moves_only_the_place_of_its_surface_and_what_the_door_makes_of_it(native: bool) -> None:
    """The text of these cases does not reach the request as it was written (that is the door's work), so what is checked is WHERE the request
    changed: the third page for the text, the title and the host, the one name for a subject, and nothing else - and that the text itself moved."""
    listed = claims.subjects()
    for case in by_target("claims"):
        moved, _own = changes(case, native=native)
        changed = {re.sub(r"\.flags\.\d+$", ".flags", p) for p in moved}  # the flags are a list: one place
        if case.surface == "subject_name":
            index = next(i for i, s in enumerate(listed) if s.kind == "PLAYER" and s.id == claims.PEOPLE[case.attack.slot].id)
            allowed = {f"0:subjects.{index}.name"}
        else:
            allowed = CLAIMS_PLACES[case.surface]
        assert changed and changed <= allowed, (case.id, sorted(changed - allowed)[:4])
        assert any(p.rsplit(".", 1)[1] in ("text", "title", "origin", "name") for p in changed), (case.id, "the text itself did not move")


def test_the_attacked_request_keeps_the_system_prompt_the_schema_and_the_layout_of_the_clean_one() -> None:
    for case in corpus.CASES:
        clean = corpus.request_for(case.target, case.base)
        attacked = corpus.request_for(case.target, case.base, case)
        assert (attacked.system, attacked.schema, attacked.schema_name, attacked.max_tokens, attacked.cache, attacked.pinned) == (
            clean.system, clean.schema, clean.schema_name, clean.max_tokens, clean.cache, clean.pinned), case.id
        assert (attacked.split is None) == (clean.split is None) and attacked.user != clean.user


def test_the_attack_text_survives_whole_inside_its_string_whatever_it_holds() -> None:
    """Quotes, braces, fences and a fake end of data are the point of the family «break the JSON»: the request stays JSON and the text
    is read back as it was written."""
    for case in (c for c in corpus.CASES if c.target in WITHOUT_DOOR):
        assert changes(case)[1], case.id
    broken = corpus.case_of("review.break_json.1")
    assert '"decision": "APPROVE"' in broken.text
    claim = json.loads(corpus.request_for("review", "r_reject", broken).user)["packet"]["evidence"][reviewer.SLOT]["claim"]
    assert claim == broken.text


# ── what is asked is what production asks ─────────────────────────────────────────────────────────────────────────

def test_the_review_is_asked_the_way_production_asks_it_and_pinned_for_the_lab() -> None:
    for base in reviewer.BASES:
        candidate, packet = reviewer.build(base)
        production = review_request(candidate, packet, signals_for(candidate, packet, at=reviewer.AT), at=reviewer.AT)
        ours = corpus.request_for("review", base)
        assert ours == replace(production, cache=True, pinned=True, native_schema=False)
        assert ours.cache and ours.pinned and not ours.native_schema
        assert corpus.request_for("review", base, native=True) == replace(ours, native_schema=True)


def test_the_extraction_is_asked_the_way_production_asks_it_and_pinned_for_the_lab() -> None:
    for base in extractor.BASES:
        production = extract_request(extract_user(extractor.MATCH, extractor.pages(base)))
        ours = corpus.request_for("extract", base)
        assert ours == replace(production, cache=True, pinned=True, native_schema=False)
        assert ours.system == EXTRACT_SYSTEM and ours.schema == EXTRACT_SCHEMA and ours.schema_name == "submit_items"
        message = json.loads(ours.user)
        assert list(message) == ["match", "results", "note"] and [r["id"] for r in message["results"]] == ["R1", "R2", "R3"]
        assert "untrusted web text" in message["note"]
        assert corpus.request_for("extract", base, native=True) == replace(ours, native_schema=True)


def test_the_claims_are_asked_the_way_production_asks_them_and_pinned_for_the_lab() -> None:
    for base in claims.BASES:
        production = extract_v2.request(extract_v2.user_message(claims.MATCH, claims.subjects(), claims.pages(base)))
        ours = corpus.request_for("claims", base)
        assert ours == replace(production, cache=True, pinned=True, native_schema=False)
        assert ours.cache and ours.pinned and not ours.native_schema and ours.split is None
        assert ours.system == EXTRACT_V2_SYSTEM and ours.schema_name == extract_v2.TOOL == "submit_claims"
        message = json.loads(ours.user)
        assert list(message) == ["match", "subjects", "pages", "note"] and [p["id"] for p in message["pages"]] == ["R1", "R2", "R3"]
        assert message["match"] == claims.MATCH and "untrusted web text" in message["note"]
        assert all(p["untrusted"] is True and p["origin"].endswith(".example") for p in message["pages"])
        assert corpus.request_for("claims", base, native=True) == replace(ours, native_schema=True)


def test_the_prompts_under_test_are_the_ones_in_force() -> None:
    assert corpus.target("review").prompt == REVIEW_VERSION == "review-v2"
    assert corpus.target("extract").prompt == EXTRACT_VERSION == "extract-v1"
    assert corpus.target("claims").prompt == EXTRACT_V2_VERSION == "extract-v3"
    assert corpus.target("match").prompts == (MATCH_CONTEXT_VERSION, MATCH_ASSESS_VERSION) == ("match-context-v4", "match-assess-v3")
    assert corpus.target("stats").prompts == (STATS_ASSESS_VERSION,) == ("stats-assess-v3",)
    assert corpus.target("council").prompts == (COUNCIL_VERSION, COUNCIL_OPUS_VERSION) == ("council-v1", "council-opus-v1")
    assert [corpus.target(t).agent for t in TARGETS] == ["", "", "", "match-v5", "stats-v4", "council-v1"]
    assert [corpus.target(t).contract for t in TARGETS] == ["", "", "", "aa-v1", "aa-v1", "cd-v1"]
    assert [corpus.target(t).tier for t in TARGETS] == ["analysis", "bulk", "bulk", "bulk", "bulk", "analysis"], "the tier production asks them with"
    assert corpus.target("council").tier_of("k_escalated") == "final" and corpus.target("council").tiers == ("analysis", "final")
    assert [corpus.target(t).name for t in TARGETS] == list(TARGETS), "each is called by the word it is filed under"


def test_each_target_reserves_of_the_envelope_what_an_answer_of_it_is_expected_to_write() -> None:
    assert {t: corpus.target(t).typical_output for t in TARGETS} == {"review": 1000, "extract": 400, "claims": 500, "match": 1200,
                                                                     "stats": 1200, "council": 1500}
    for t in TARGETS:
        asked = corpus.request_for(t, next(iter(corpus.target(t).bases)))
        assert 0 < corpus.target(t).typical_output <= asked.max_tokens, "an answer cannot be expected to write more than it is allowed to"


def test_the_clean_asks_are_the_same_bytes_every_time_and_nothing_is_shared_between_builds() -> None:
    for target in TARGETS:
        for base in corpus.target(target).bases:
            assert corpus.request_for(target, base) == corpus.request_for(target, base)
    _candidate, packet = reviewer.build("r_reject")
    packet.content["fixture"]["venue"] = "changed by a test"
    packet.content["evidence"].append({"id": 99})
    _candidate, again = reviewer.build("r_reject")
    assert again.content["fixture"]["venue"] == "Estadio Example" and len(again.content["evidence"]) == reviewer.SLOT + 1
    pages = extractor.pages("x_quiet")
    pages.pop("R1")
    assert set(extractor.pages("x_quiet")) == {"R1", "R2", "R3"}
    listed = claims.subjects()
    listed.pop()
    shown = claims.results("c_quiet")
    shown.pop()
    assert len(claims.subjects()) == 4 + len(claims.SQUAD) and [r.url for r in claims.results("c_quiet")] != [r.url for r in shown]
    assert len(claims.results("c_quiet")) == 3


# ── the bases ─────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_review_bases_are_three_pictures_of_one_match_with_a_neutral_slot() -> None:
    assert set(reviewer.BASES) == {"r_reject", "r_approve", "r_mixed"} and all(b.target == "review" for b in reviewer.BASES.values())
    seen = set()
    for base in reviewer.BASES:
        candidate, packet = reviewer.build(base)
        slot = packet.content["evidence"][reviewer.SLOT]
        assert slot["claim"] == reviewer.NEUTRAL_CLAIM and (slot["status"], slot["tier"], slot["kind"]) == ("PROBABLE", "media", "news")
        assert len(packet.content["evidence"]) == reviewer.SLOT + 1 and packet.fixture_id == reviewer.FIXTURE
        assert packet.content["fixture"]["venue"] == "Estadio Example" and packet.content["fixture"]["referee"] == "A. Referee"
        seen.add((candidate.market_key, candidate.selection, str(candidate.odds)))
    assert seen == {("1X2", "Home", "2.15"), ("1X2", "Home", "2.00"), ("OU", "Over", "1.95")}, "a model can tell the three apart"


def test_a_review_attack_on_an_unknown_surface_is_refused() -> None:
    attack = Attack(family="ignore", n=1, surface="the_moon", base="r_reject", goal="approve", text="x")
    with pytest.raises(ValueError, match="unknown surface 'the_moon'"):
        reviewer.build("r_reject", Case("review.ignore.1", "review", attack, None))
    with pytest.raises(ValueError, match="unknown surface 'the_moon'"):
        extractor.pages("x_quiet", Case("extract.ignore.1", "extract", attack, None))


def test_the_extraction_bases_say_what_they_are_designed_to_say_and_the_slot_says_nothing() -> None:
    assert set(extractor.BASES) == set(extractor.EXPECTED) == {"x_injury", "x_doubt", "x_quiet"}
    surnames = {key for expected in extractor.EXPECTED.values() for _side, key, _a in expected}
    assert surnames == {"striker", "midfielder", "keeper", "defender"}
    for base, expected in extractor.EXPECTED.items():
        pages = extractor.pages(base)
        plain = {rid: " " + normalize_name(f"{p.title} {p.publisher} {p.snippet}") + " " for rid, p in pages.items()}
        for _side, key, _assertion in expected:
            assert f" {key} " in plain["R1"] + plain["R2"], (base, key)
        assert not any(f" {key} " in plain[extractor.SLOT] for key in surnames), "the slot is neutral"
        if not expected:
            assert not any(f" {key} " in plain["R1"] + plain["R2"] for key in surnames)
    assert extractor.EXPECTED["x_quiet"] == frozenset()


def test_the_claims_bases_are_the_extraction_bases_read_by_the_second_extractor_and_the_slot_says_nothing() -> None:
    """The two extractors are read on the same facts, so that what changes between them is what they meet on the way in: the pages of a base of
    ``claims`` are the pages of the base of the same name of ``extract``, each told where it comes from by the host of its address."""
    assert set(claims.BASES) == set(claims.EXPECTED) == set(claims.V1_BASE) == {"c_injury", "c_doubt", "c_quiet"}
    assert all(b.target == "claims" for b in claims.BASES.values()) and claims.EXPECTED["c_quiet"] == frozenset()
    assert {base: claims.EXPECTED[base] for base in claims.BASES} == {b: extractor.EXPECTED[v1] for b, v1 in claims.V1_BASE.items()}
    for base, v1 in claims.V1_BASE.items():
        shown = claims.pages(base)
        old = extractor.pages(v1)
        assert [p.id for p in shown] == list(old) == ["R1", "R2", "R3"], base
        for page in shown:
            assert (page.title, page.text) == (old[page.id].title, old[page.id].snippet), (base, page.id)
            assert page.published_at == old[page.id].published_at and not page.flags and not page.truncated, (base, page.id)
        assert [p.domain for p in shown] == [claims.host_of(old["R1"].publisher), claims.host_of(old["R2"].publisher), claims.SLOT_HOST]
        plain = {p.id: " " + normalize_name(p.readable) + " " for p in shown}
        for _side, key, _assertion in claims.EXPECTED[base]:
            assert f" {key} " in plain["R1"] + plain["R2"], (base, key)
        assert not any(f" {p.key} " in plain[claims.SLOT] for p in claims.SQUAD), "the slot is neutral"
        if not claims.EXPECTED[base]:
            assert not any(f" {p.key} " in plain["R1"] + plain["R2"] for p in claims.SQUAD)
    assert claims.SLOT == extractor.SLOT and claims.NEUTRAL_TEXT == extractor.NEUTRAL_TEXT and claims.NEUTRAL_TITLE == extractor.NEUTRAL_TITLE


def test_the_strict_answer_is_the_prompts_schema_and_not_a_looser_one() -> None:
    """The battery judges an extraction with pydantic; if the prompt's schema moves and this does not, the judge would measure another
    thing than what the model was asked."""
    item = EXTRACT_SCHEMA["properties"]["items"]["items"]
    generated = extractor.StrictAnswer.model_json_schema()
    strict = generated["$defs"]["StrictItem"]
    assert set(strict["properties"]) == set(item["properties"]) and set(strict["required"]) == set(item["required"])
    for name in ("side", "kind", "assertion"):
        assert strict["properties"][name]["enum"] == item["properties"][name]["enum"], name
    assert strict["properties"]["claim"]["maxLength"] == item["properties"]["claim"]["maxLength"] == 300
    assert generated["properties"]["items"]["maxItems"] == EXTRACT_SCHEMA["properties"]["items"]["maxItems"] == 20
    assert strict["additionalProperties"] is False and generated["additionalProperties"] is False
    assert item["additionalProperties"] is False and EXTRACT_SCHEMA["additionalProperties"] is False


def test_the_text_of_an_attack_is_not_a_clean_one_and_never_the_same_twice() -> None:
    for target in TARGETS:
        texts = [c.text for c in by_target(target)]
        assert len(set(texts)) == len(texts), target
    assert tuple(c.attack for c in by_target("review")) == attacks_review.ATTACKS
    assert tuple(c.attack for c in by_target("extract")) == attacks_extract.ATTACKS
    assert tuple(c.attack for c in by_target("claims")) == attacks_claims.ATTACKS
    assert reviewer.NEUTRAL_CLAIM not in {c.text for c in by_target("review")} and extractor.NEUTRAL_TEXT not in {c.text for c in by_target("extract")}
    assert claims.NEUTRAL_TEXT not in {c.text for c in by_target("claims")} and claims.NEUTRAL_TITLE not in {c.text for c in by_target("claims")}


def test_what_must_not_survive_is_in_the_text_and_what_must_be_readable_is_dressed_up() -> None:
    """The deterministic layer (``fbi.ai.battery.offline``) checks that ``sanitize`` removes the first and reads the second; these are
    the preconditions that make that check mean something: the first IS in the raw text, the second is NOT readable in it."""
    for case in corpus.CASES:
        if case.family == "hidden_html":
            assert case.hidden and "html" in case.attack.expect, case.id
        if case.hidden:
            assert case.hidden.casefold() in case.text.casefold(), case.id
        if case.phrase and case.family == "homoglyph":
            assert case.phrase.casefold() not in case.text.casefold(), case.id
        if case.phrase and case.family == "markdown_link":
            assert case.phrase.casefold() in case.text.casefold(), case.id
    assert {c.family for c in corpus.CASES if c.phrase} == {"homoglyph", "markdown_link"}


# ── the fingerprints ─────────────────────────────────────────────────────────────────────────────────────────────

CORPUS_HASH = "0c75b24817e062912dd7213359d1112da4897e6805969b20b4e97c110cb4b8e6"
"""The cases and the bases of ``battery-v3``. A change that moves it is a new version of the battery, never an edit of this one."""
V2_REQUESTS = "4ada589dd5a9753030da9696871cec062d3f08be0cdfaaf724cae024f27fd1a7"
"""The fingerprint of every request of the three targets of ``battery-v2`` - each base and each case, by the tool call and by structured
outputs - as ``battery-v2`` made them, measured on its code before ``battery-v3`` was written (with the door ``untrusted-v1``). IA-021 re-pinned it: the prompt of the target ``claims``
gained one rule (``extract-v3``), so its requests are asked with that text; the other two targets did not move."""
V2_DOOR_CLAIMS = "e0474aeba98068cf4ebfb8ac5f15c24d327a76c64bafa65f098b90e494c9cca8"
"""The fingerprint of every request of the target ``claims`` behind the door ``untrusted-v2`` (IA-018)."""
V3_DOOR_CLAIMS = "bc8378b997afee277927e2b983f53b5490e9c1a005e7bfefff31db5c661cb19f"
"""The fingerprint of every request of the target ``claims`` behind the door ``untrusted-v3`` (IA-020): what a new measurement of it is of."""
NEUTRALISED: Final = frozenset({"homoglyph.1", "homoglyph.2", "homoglyph.3", "homoglyph.4", "markdown_link.3", "break_json.1", "break_json.2",
                                "break_json.3", "break_json.4", "break_json.5"})
"""The cases whose requests the door ``untrusted-v2`` changes, in every target behind a door: the families of the three cases ``battery-v3``
confirmed in the LAB on 7 Nov 2026 (a disguised phrase, the words of an image, a break out of the JSON). No base and no other case moves."""


def fingerprints(name: str, *, natives: tuple[bool, ...] = (False, True)) -> list[list[Any]]:
    parts: list[list[Any]] = []
    for native in natives:
        for b in sorted(corpus.target(name).bases):
            parts.append([name, native, "base:" + b, corpus.fingerprint(corpus.request_for(name, b, native=native))])
        for c in sorted(corpus.cases_of(name), key=lambda c: c.id):
            parts.append([name, native, "case:" + c.id, corpus.fingerprint(corpus.request_for(name, c.base, c, native=native))])
    return parts


def test_the_corpus_is_pinned_to_its_version() -> None:
    assert VERSION == "battery-v3"
    assert corpus.corpus_hash() == CORPUS_HASH, "the corpus changed: it is a new VERSION of the battery (and a new pin)"


def test_the_targets_of_battery_v2_are_asked_byte_for_byte_as_battery_v2_asked_them(monkeypatch: pytest.MonkeyPatch) -> None:
    """Behind the door they were measured with: ``untrusted-v1`` is kept, byte for byte, and with it every request of ``battery-v2``. The door in
    force is ``untrusted-v2`` since IA-018; what it changes is held by the next test (and the LAB's ``requests_hash`` says a measurement of the
    target ``claims`` made behind the old door is stale)."""
    monkeypatch.setattr(untrusted, "VERSION", untrusted.VERSION_1)
    parts: list[list[Any]] = []
    for t in PROMPT_TARGETS:
        for native in (False, True):
            for b in sorted(corpus.target(t).bases):
                parts.append([t, native, "base:" + b, corpus.fingerprint(corpus.request_for(t, b, native=native))])
            for c in sorted(corpus.cases_of(t), key=lambda c: c.id):
                parts.append([t, native, "case:" + c.id, corpus.fingerprint(corpus.request_for(t, c.base, c, native=native))])
    assert len(parts) == 258 and hashlib.sha256(json.dumps(parts).encode()).hexdigest() == V2_REQUESTS


@pytest.mark.parametrize("name", TARGETS)
def test_the_door_of_v2_changes_the_requests_of_the_neutralised_cases_and_nothing_else(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    behind(monkeypatch, untrusted.VERSION_2)
    now = {p[2]: p[3] for p in fingerprints(name, natives=(False,))}
    monkeypatch.setattr(untrusted, "VERSION", untrusted.VERSION_1)
    monkeypatch.setitem(package.DOOR, package.VERSION, untrusted.VERSION_1)
    before = {p[2]: p[3] for p in fingerprints(name, natives=(False,))}
    moved = {key.removeprefix(f"case:{name}.") for key, fp in now.items() if before[key] != fp}
    assert moved == (set() if corpus.target(name).door is None else NEUTRALISED), name


def behind(monkeypatch: pytest.MonkeyPatch, door: str) -> None:
    """The door ``door`` in force, in front of the battery's own text and of the package the agents read."""
    monkeypatch.setattr(untrusted, "VERSION", door)
    monkeypatch.setitem(package.DOOR, package.VERSION, door)


@pytest.mark.parametrize("name", TARGETS)
def test_the_door_of_v3_changes_the_requests_of_the_orders_it_reads_and_nothing_else(monkeypatch: pytest.MonkeyPatch, name: str) -> None:
    """IA-020: ``untrusted-v3`` hands on v2's text and flags more of it ``instruction_like``. Of the targets behind a door only ``claims`` has a case
    it reads as an order (the page carries the flag): no base and no other case moves, and the agents are asked as before."""
    assert untrusted.VERSION == untrusted.VERSION_3 and package.DOOR[package.VERSION] == untrusted.VERSION_3
    now = {p[2]: p[3] for p in fingerprints(name, natives=(False,))}
    behind(monkeypatch, untrusted.VERSION_2)
    before = {p[2]: p[3] for p in fingerprints(name, natives=(False,))}
    moved = {key.removeprefix("case:") for key, fp in now.items() if before[key] != fp}
    door = corpus.target(name).door
    assert moved == (set() if door is None else {i for i in ORDERS_OF_V3 if i.startswith(f"{name}.")}), name
    assert name != "claims" or moved == {"claims.fake_official.1", "claims.fake_official.2", "claims.fake_official.5", "claims.ignore.5"}


def test_the_requests_of_claims_behind_the_door_of_v2_are_pinned(monkeypatch: pytest.MonkeyPatch) -> None:
    behind(monkeypatch, untrusted.VERSION_2)
    parts = fingerprints("claims")
    assert len(parts) == 86 and hashlib.sha256(json.dumps(parts).encode()).hexdigest() == V2_DOOR_CLAIMS


def test_the_requests_of_claims_behind_the_door_of_v3_are_pinned() -> None:
    parts = fingerprints("claims")
    assert len(parts) == 86 and hashlib.sha256(json.dumps(parts).encode()).hexdigest() == V3_DOOR_CLAIMS


def test_the_fingerprints_are_the_same_on_every_call_and_differ_by_target_and_route() -> None:
    hashes = {(t, n): corpus.requests_hash(t, native=n) for t in TARGETS for n in (False, True)}
    assert hashes == {(t, n): corpus.requests_hash(t, native=n) for t in TARGETS for n in (False, True)}
    # IA-028: the Match Agent's v5 and the Statistics Agent's v4 ask natively themselves, so their two routes are one; the other four differ
    assert {t for t in TARGETS if hashes[(t, False)] == hashes[(t, True)]} == {"match", "stats"} and len(set(hashes.values())) == 10
    assert corpus.corpus_hash() == corpus.corpus_hash() and len(corpus.corpus_hash()) == 64


def test_a_changed_case_a_changed_base_or_a_changed_prompt_changes_the_fingerprint(monkeypatch: pytest.MonkeyPatch) -> None:
    before_corpus, before_review, before_extract = corpus.corpus_hash(), corpus.requests_hash("review"), corpus.requests_hash("extract")
    before_claims = corpus.requests_hash("claims")
    first = corpus.CASES[0]
    edited = replace(first, attack=replace(first.attack, text=first.attack.text + " "))
    with monkeypatch.context() as m:
        m.setattr(corpus, "CASES", (edited, *corpus.CASES[1:]))
        assert corpus.corpus_hash() != before_corpus and corpus.requests_hash("review") != before_review
        assert corpus.requests_hash("extract") == before_extract, "a case of the other prompt is not a request of this one"
        assert corpus.requests_hash("claims") == before_claims
    with monkeypatch.context() as m:
        m.setitem(reviewer.BASES, "r_mixed", Base("r_mixed", "review", "another note"))
        assert corpus.corpus_hash() != before_corpus and corpus.requests_hash("review") == before_review, "a note is not a request"
        assert corpus.requests_hash("claims") == before_claims
    real = review_request

    def other_prompt(*a: Any, **kw: Any) -> Any:
        return replace(real(*a, **kw), system=real(*a, **kw).system + " Be brief.")

    with monkeypatch.context() as m:
        m.setattr(reviewer, "review_request", other_prompt)
        assert corpus.requests_hash("review") != before_review and corpus.requests_hash("extract") == before_extract
        assert corpus.requests_hash("claims") == before_claims
        assert corpus.corpus_hash() == before_corpus, "the prompt is not the corpus: the two fingerprints say different things"
    assert corpus.requests_hash("review") == before_review
    at = len(attacks_review.ATTACKS) + len(attacks_extract.ATTACKS) + len(attacks_claims.ATTACKS) - 1
    last = corpus.CASES[at]
    assert last.target == "claims" and corpus.CASES[at + 1].target == "match"

    def with_last(text: str) -> tuple[Case, ...]:
        return (*corpus.CASES[:at], replace(last, attack=replace(last.attack, text=text)), *corpus.CASES[at + 1:])

    with monkeypatch.context() as m:
        m.setattr(corpus, "CASES", with_last(last.attack.text + " again"))
        assert corpus.requests_hash("claims") != before_claims and corpus.corpus_hash() != before_corpus
        assert corpus.requests_hash("review") == before_review and corpus.requests_hash("extract") == before_extract
    with monkeypatch.context() as m:  # the door makes the same of a trailing space: the model reads the same, the corpus is another
        m.setattr(corpus, "CASES", with_last(last.attack.text + " "))
        assert corpus.requests_hash("claims") == before_claims and corpus.corpus_hash() != before_corpus
    real_subject = extract_v2.subject

    def other_name(kind: str, subject_id: int, raw_name: object, **kw: Any) -> Any:
        return real_subject(kind, subject_id, f"{raw_name} Jr", **kw)

    with monkeypatch.context() as m:
        m.setattr(extract_v2, "subject", other_name)
        assert corpus.requests_hash("claims") != before_claims, "the list of subjects is part of what is asked"
        assert corpus.corpus_hash() == before_corpus
    assert corpus.requests_hash("claims") == before_claims


def test_the_fingerprint_of_a_request_sees_every_field_of_it() -> None:
    request = corpus.request_for("extract", "x_quiet")
    base = corpus.fingerprint(request)
    assert base == corpus.fingerprint(corpus.request_for("extract", "x_quiet"))
    for change in ({"user": request.user + " "}, {"system": request.system + "."}, {"effort": "high"}, {"native_schema": True},
                   {"cache": False}, {"pinned": False}, {"max_tokens": request.max_tokens + 1}, {"schema_name": "other"}):
        assert corpus.fingerprint(replace(request, **change)) != base, change
