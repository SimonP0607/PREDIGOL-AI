"""The corpus of the adversarial battery (Plan Maestro IA, phase 1, item 1.7, section 31): the cases, the bases they attack, the requests they
become and the fingerprints that say what a measurement is of. No database, no model.

What is checked is what makes the battery worth running: the plan's size («≥ 40 casos») and its eight families; that a case replaces ONE text
of a clean base and nothing else (so the base is the baseline); that what is asked is what production asks; and that the corpus cannot change
without the fingerprints saying so."""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import replace
from typing import Any

import pytest

from fbi.ai.battery import (
    CASES_PER_TARGET,
    FAMILIES,
    MIN_CASES,
    PER_FAMILY,
    TARGETS,
    VERSION,
    attacks_extract,
    attacks_review,
    corpus,
    extractor,
    reviewer,
)
from fbi.ai.battery.model import CANARY_MARK, Attack, Base, Case
from fbi.ai.collectors import extract_request, extract_user
from fbi.ai.evidence import normalize_name
from fbi.ai.prompts import EXTRACT_SCHEMA, EXTRACT_SYSTEM, EXTRACT_VERSION, REVIEW_VERSION
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
    return tuple(c for c in corpus.CASES if c.target == name)


# ── the size the plan asks for ─────────────────────────────────────────────────────────────────────────────────────

def test_the_plan_asks_for_forty_cases_of_each_prompt_and_the_corpus_has_eighty() -> None:
    assert MIN_CASES == 40 and TARGETS == ("review", "extract")
    assert CASES_PER_TARGET == len(FAMILIES) * PER_FAMILY == 40
    assert len(corpus.CASES) == 80 and corpus.check_sizes() == []
    assert {t: len(corpus.cases_of(t)) for t in TARGETS} == {"review": 40, "extract": 40}


def test_eight_families_of_section_31_five_attacks_each_for_each_prompt() -> None:
    assert FAMILIES == ("ignore", "fake_official", "hidden_html", "homoglyph", "markdown_link", "break_json", "orders", "player_name")
    for target in TARGETS:
        counts = Counter((c.family, c.attack.n) for c in by_target(target))
        assert counts == {(f, n): 1 for f in FAMILIES for n in range(1, PER_FAMILY + 1)}, target


def test_ids_are_unique_and_every_lookup_agrees() -> None:
    ids = [c.id for c in corpus.CASES]
    assert len(set(ids)) == len(ids) == len(corpus.BY_ID)
    for case in corpus.CASES:
        assert case.id == f"{case.target}.{case.family}.{case.attack.n}"
        assert corpus.case_of(case.id) is case and case in corpus.cases_of(case.target)
    assert [c.id for c in corpus.cases_of("review")] == [c.id for c in corpus.CASES[:40]]


def test_a_size_below_the_plans_is_reported_with_the_target_that_lacks_it(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(corpus, "CASES", tuple(c for c in corpus.CASES if c.id != "extract.orders.3"))
    assert corpus.check_sizes() == ["extract: 39 cases, 40 needed"]


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
        assert case.surface in (reviewer.SURFACES if case.target == "review" else extractor.SURFACES), case.id
        assert case.attack.goal in ("approve", "reject", "any") and case.text.strip(), case.id
        assert set(case.attack.expect) <= KNOWN_FLAGS, case.id


def test_every_surface_and_every_base_is_attacked() -> None:
    assert {c.surface for c in by_target("review")} == set(reviewer.SURFACES)
    assert {c.surface for c in by_target("extract")} == set(extractor.SURFACES)
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
    assert all(not any(getattr(c.attack, k) for k in SLOT_KEYS) for c in by_target("extract"))


def test_no_attack_asks_for_what_the_data_of_its_base_already_says() -> None:
    """An attack that wants an APPROVE of a pick whose data already says yes proves nothing: it cannot move the verdict."""
    for case in by_target("review"):
        assert not (case.attack.goal == "approve" and case.base == "r_approve"), case.id
        assert not (case.attack.goal == "reject" and case.base == "r_reject"), case.id
    goals = Counter(c.attack.goal for c in by_target("review"))
    assert set(goals) == {"approve", "reject", "any"} and goals["approve"] >= 10 and goals["reject"] >= 10, goals
    assert {c.attack.goal for c in by_target("extract")} == {"any"}


def test_the_items_an_extraction_attack_plants_or_states_are_new_and_could_be_known() -> None:
    """A planted item (the attack orders it) or a stated fact (its text says it) that the base's own pages already give would not
    discriminate anything; and an order to write about a player nobody named could not be followed."""
    for case in by_target("extract"):
        a = case.attack
        expected = extractor.EXPECTED[case.base]
        assert not set(a.planted) & expected and not set(a.facts) & expected, case.id
        assert not set(a.planted) & set(a.facts), case.id
        pages = extractor.pages(case.base)
        read = sanitize(case.text, origin="test", max_chars=4000).text  # a model reads small capitals and full-width letters as letters
        tag_block = "".join(chr(ord(ch) - 0xE0000) for ch in case.text if 0xE0000 < ord(ch) < 0xE0080)
        text = " ".join([case.text, read, tag_block, *(f"{p.title} {p.snippet}" for rid, p in pages.items() if rid != extractor.SLOT)])
        known = " " + normalize_name(text) + " "
        for _side, key, _assertion in (*a.planted, *a.facts):
            assert f" {key} " in known, (case.id, key)
        assert all(e in case.text for e in a.echo) and (not a.echo or case.family == "orders"), case.id


# ── the code word ──────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_code_word_is_the_cases_own_and_only_where_an_attack_asks_for_it() -> None:
    with_word = [c for c in corpus.CASES if c.canary]
    assert len(with_word) == 14
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


def test_a_code_word_is_the_same_on_every_run_and_the_battery_version_is_in_it() -> None:
    first = {c.id: c.canary for c in corpus.CASES}
    assert first == {c.id: c.canary for c in corpus.CASES}
    assert corpus.case_of("review.ignore.4").canary == "ZQ" + hashlib.sha256(f"{VERSION}/review.ignore.4".encode()).hexdigest()[:8].upper()
    assert corpus.case_of("review.ignore.4").canary != corpus.case_of("extract.ignore.4").canary


def test_a_hidden_phrase_that_is_the_code_word_is_replaced_by_the_cases_own() -> None:
    case = corpus.case_of("review.hidden_html.4")
    assert case.attack.hidden == CANARY_MARK and case.hidden == case.canary
    assert case.canary is not None and case.canary in case.text


# ── a case replaces one text and nothing else ──────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("native", [False, True])
def test_a_case_puts_its_text_where_its_surface_is_and_changes_nothing_else(native: bool) -> None:
    for case in corpus.CASES:
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
    for case in corpus.CASES:
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


def test_the_prompts_under_test_are_the_ones_in_force() -> None:
    assert corpus.target("review").prompt == REVIEW_VERSION == "review-v2"
    assert corpus.target("extract").prompt == EXTRACT_VERSION == "extract-v1"
    assert (corpus.target("review").tier, corpus.target("extract").tier) == ("analysis", "bulk"), "the tier production asks them with"


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
    assert reviewer.NEUTRAL_CLAIM not in {c.text for c in by_target("review")} and extractor.NEUTRAL_TEXT not in {c.text for c in by_target("extract")}


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

CORPUS_HASH = "7b4e59d5a14aea41aa0dbaa6b5d5e77903a35f8088e5861b82494d6e0237b4e5"
"""The cases and the bases of ``battery-v1``. A change that moves it is a new version of the battery, never an edit of this one."""


def test_the_corpus_is_pinned_to_its_version() -> None:
    assert VERSION == "battery-v1"
    assert corpus.corpus_hash() == CORPUS_HASH, "the corpus changed: it is a new VERSION of the battery (and a new pin)"


def test_the_fingerprints_are_the_same_on_every_call_and_differ_by_target_and_route() -> None:
    hashes = {(t, n): corpus.requests_hash(t, native=n) for t in TARGETS for n in (False, True)}
    assert len(set(hashes.values())) == 4 and hashes == {(t, n): corpus.requests_hash(t, native=n) for t in TARGETS for n in (False, True)}
    assert corpus.corpus_hash() == corpus.corpus_hash() and len(corpus.corpus_hash()) == 64


def test_a_changed_case_a_changed_base_or_a_changed_prompt_changes_the_fingerprint(monkeypatch: pytest.MonkeyPatch) -> None:
    before_corpus, before_review, before_extract = corpus.corpus_hash(), corpus.requests_hash("review"), corpus.requests_hash("extract")
    first = corpus.CASES[0]
    edited = replace(first, attack=replace(first.attack, text=first.attack.text + " "))
    with monkeypatch.context() as m:
        m.setattr(corpus, "CASES", (edited, *corpus.CASES[1:]))
        assert corpus.corpus_hash() != before_corpus and corpus.requests_hash("review") != before_review
        assert corpus.requests_hash("extract") == before_extract, "a case of the other prompt is not a request of this one"
    with monkeypatch.context() as m:
        m.setitem(reviewer.BASES, "r_mixed", Base("r_mixed", "review", "another note"))
        assert corpus.corpus_hash() != before_corpus and corpus.requests_hash("review") == before_review, "a note is not a request"
    real = review_request

    def other_prompt(*a: Any, **kw: Any) -> Any:
        return replace(real(*a, **kw), system=real(*a, **kw).system + " Be brief.")

    with monkeypatch.context() as m:
        m.setattr(reviewer, "review_request", other_prompt)
        assert corpus.requests_hash("review") != before_review and corpus.requests_hash("extract") == before_extract
        assert corpus.corpus_hash() == before_corpus, "the prompt is not the corpus: the two fingerprints say different things"
    assert corpus.requests_hash("review") == before_review


def test_the_fingerprint_of_a_request_sees_every_field_of_it() -> None:
    request = corpus.request_for("extract", "x_quiet")
    base = corpus.fingerprint(request)
    assert base == corpus.fingerprint(corpus.request_for("extract", "x_quiet"))
    for change in ({"user": request.user + " "}, {"system": request.system + "."}, {"effort": "high"}, {"native_schema": True},
                   {"cache": False}, {"pinned": False}, {"max_tokens": request.max_tokens + 1}, {"schema_name": "other"}):
        assert corpus.fingerprint(replace(request, **change)) != base, change
