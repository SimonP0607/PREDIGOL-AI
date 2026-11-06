"""The legal texts, their versions and their sha256, and the gate's rules (plan UX, A4; plan de seguridad, section 23).

A text cannot change without a new version: the register's hash of every document in every language is recomputed
here. The two languages say the same thing in the same places (same sections, same boxes). A reader owes the gate a
purpose they never answered, withdrew, or answered on a version a material change replaced - never one a
non-material change touched.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from pathlib import Path

import pytest

from fbi.customer import consents, legal

TEXTS = legal.TEXTS


@pytest.fixture(autouse=True)
def fresh_caches() -> Iterator[None]:
    legal.register.cache_clear()
    legal.load.cache_clear()
    legal.controller.cache_clear()
    yield
    legal.register.cache_clear()
    legal.load.cache_clear()
    legal.controller.cache_clear()


def test_every_text_has_the_hash_the_register_gives_it() -> None:
    for name in legal.DOCUMENTS:
        version = legal.current(name)
        for locale in legal.LOCALES:
            doc = legal.load(name, locale)
            assert doc.sha256 == version.sha256[locale], (
                f"{locale}/{name}.json (or controller.json) changed without a new version: add one to versions.json "
                f"(python -m scripts.legal_texts hashes)")


def test_the_hash_is_of_the_text_shown_so_one_changed_letter_changes_it(monkeypatch: pytest.MonkeyPatch,
                                                                        tmp_path: Path) -> None:
    original = legal.load("terms", "es")
    copy = tmp_path / "texts"
    copy.mkdir()
    for item in TEXTS.rglob("*.json"):
        target = copy / item.relative_to(TEXTS)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(item.read_text(encoding="utf-8"), encoding="utf-8")
    data = json.loads((copy / "es" / "terms.json").read_text(encoding="utf-8"))
    data["sections"][1]["blocks"][0]["p"] = data["sections"][1]["blocks"][0]["p"].replace("garantiza", "asegura")
    (copy / "es" / "terms.json").write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(legal, "TEXTS", copy)
    legal.load.cache_clear()
    changed = legal.load("terms", "es")
    assert changed.sha256 != original.sha256
    assert changed.version == original.version  # the register is what the test above catches


def test_the_two_languages_have_the_same_sections_and_the_same_boxes() -> None:
    for name in legal.DOCUMENTS:
        es, en = legal.load(name, "es"), legal.load(name, "en")
        assert [s["id"] for s in es.sections] == [s["id"] for s in en.sections], name
        assert [len(s["blocks"]) for s in es.sections] == [len(s["blocks"]) for s in en.sections], name
        assert set(es.statements) == set(en.statements), name
        assert len({s["id"] for s in es.sections}) == len(es.sections), f"{name}: an anchor appears twice"


def test_every_purpose_has_its_box_in_both_languages_and_the_database_takes_it() -> None:
    assert legal.REQUIRED == ("terms", "privacy", "age_18", "risk_notice")
    for purpose in legal.PURPOSES:
        for locale in legal.LOCALES:
            doc, sentence = legal.statement(purpose.kind, locale)
            assert doc.document == purpose.document
            assert 1 <= len(sentence.strip()) <= 500, "customer.consents.statement holds 1 to 500 characters"
    # B8: the weekly summary by e-mail, optional and withdrawable, on the processing policy (its box, never ticked
    # beforehand) - the gate never asks for it
    marketing = legal.BY_KIND["marketing_email"]
    assert (marketing.document, marketing.required, marketing.withdrawable) == ("privacy", False, True)
    assert "marketing_email" not in legal.REQUIRED
    with pytest.raises(legal.LegalTextError):
        legal.statement("nonsense", "es")  # only the purposes of the register have a box


def test_the_texts_are_plain_text_with_every_placeholder_filled() -> None:
    for name in legal.DOCUMENTS:
        for locale in legal.LOCALES:
            raw = (TEXTS / locale / f"{name}.json").read_text(encoding="utf-8")
            assert "{{" not in json.dumps(legal._fill(json.loads(raw)), ensure_ascii=False)
            assert "<" not in raw and "](" not in raw, f"{locale}/{name}: no HTML or markdown, the page renders text"
            for section in json.loads(raw)["sections"]:
                for block in section["blocks"]:
                    assert set(block) <= {"p", "ul"} and len(block) == 1, (name, section["id"])


def test_the_versions_are_dated_ordered_and_bilingual() -> None:
    for name in legal.DOCUMENTS:
        versions = legal.register()[name]
        assert versions[0].material
        for v in versions:
            assert legal.VERSION_FORMAT.match(v.version) and v.version.startswith(v.date)
            assert set(v.changes) == {"es", "en"} and all(v.changes.values())


def _words(name: legal.DocumentName, locale: legal.Locale) -> str:
    doc = legal.load(name, locale)
    return json.dumps([doc.summary, doc.sections], ensure_ascii=False).lower()


def test_the_terms_and_the_policy_say_what_predigol_is_and_what_it_is_not_in_both_languages() -> None:
    """Plan de cierre UX, 1.1: one sentence everywhere - an analysis and value-detection platform that guarantees no
    result or profit, is not a bookmaker, takes no money for bets and is for people aged 18 or over."""
    must: dict[legal.Locale, list[str]] = {
        "es": ["plataforma de análisis deportivo y detección de valor", "no garantiza resultados ni beneficios",
               "no es una casa de apuestas", "recibe dinero de apuestas", "18 años"],
        "en": ["sports-analysis and value-detection platform", "does not guarantee results or profits",
               "is not a bookmaker", "money for bets", "18 or over"],
    }
    for locale, phrases in must.items():
        for name in ("terms", "privacy"):
            text = _words(name, locale)
            for phrase in phrases:
                assert phrase in text, f"{locale}/{name} must say: {phrase}"
        # the summary of the terms is what a reader sees first: it carries the whole sentence
        summary = legal.load("terms", locale).summary.lower()
        assert phrases[0] in summary and phrases[1] in summary and phrases[2] in summary


def test_the_membership_section_states_the_decided_facts_and_leaves_the_lawyers_to_the_lawyer() -> None:
    for locale in legal.LOCALES:
        doc = legal.load("terms", locale)
        section = next(s for s in doc.sections if s["id"] == "membresia")
        text = json.dumps(section, ensure_ascii=False)
        assert "[Pend" in text, "the right of withdrawal, taxes and refunds stay with the lawyer (P5)"
        assert "P6" not in text, "the price was decided by the owner: no longer pending"
        # nothing in a hashed legal text may hard-code a price, a trial length or a discount: they live in the
        # configuration and the profile shows them (a change of price must not need a new legal version)
        for figure in ("150", "50 usd", "usd 50", "20 días", "20 days", "%"):
            assert figure not in text.lower(), (locale, figure)


def test_draft3_is_registered_as_a_draft_and_only_the_terms_ask_to_accept_again() -> None:
    terms, privacy, gaming = (legal.current(n) for n in ("terms", "privacy", "responsible_gaming"))
    assert terms.version == "2026-11-05-draft3" and privacy.version == "2026-11-05-draft4"
    assert terms.draft and privacy.draft and terms.material and not privacy.material
    assert gaming.version == "2026-10-25-draft1", "the responsible-gaming page did not change"
    assert legal.valid_versions("terms") == frozenset({"2026-11-05-draft3"})
    assert legal.valid_versions("privacy") == frozenset(
        {"2026-10-25-draft1", "2026-10-27-draft2", "2026-11-05-draft3", "2026-11-05-draft4"}
    ), "what was accepted on the policy still holds: nothing on it asked anyone again"


def test_the_usage_statistics_are_an_optional_box_of_their_own_never_part_of_the_general_authorisation() -> None:
    """Plan de cierre UX, 1.2: unticked, withdrawable, never asked for by the gate, and the policy's general
    authorisation no longer says «statistics»."""
    purpose = legal.BY_KIND["analytics"]
    assert (purpose.document, purpose.required, purpose.withdrawable) == ("privacy", False, True)
    assert "analytics" not in legal.REQUIRED
    assert legal.due({}) == ["terms", "privacy", "age_18", "risk_notice"], "the gate never waits for it"
    for locale in legal.LOCALES:
        _, sentence = legal.statement("analytics", locale)
        assert ("seudónimo" if locale == "es" else "pseudonymous") in sentence
        _, general = legal.statement("privacy", locale)
        assert ("estadística" if locale == "es" else "statistic") not in general.lower()


def test_until_the_lawyer_says_so_the_texts_are_drafts_and_the_gate_stays_off(
        monkeypatch: pytest.MonkeyPatch) -> None:
    assert legal.any_draft(), "the first texts are drafts until P5"
    monkeypatch.setenv(consents.GATE_ENV, "1")
    assert consents.gate_mode() == "on" and not consents.gate_enabled()
    monkeypatch.setenv(consents.GATE_ENV, "drafts")
    assert consents.gate_enabled(), "QA turns it on over the drafts"
    monkeypatch.setenv(consents.GATE_ENV, "0")
    assert not consents.gate_enabled()
    monkeypatch.delenv(consents.GATE_ENV)
    assert consents.gate_mode() == "off" and not consents.gate_enabled()
    monkeypatch.setenv(consents.GATE_ENV, "1")
    monkeypatch.setattr(legal, "any_draft", lambda: False)
    assert consents.gate_enabled(), "with the lawyer's OK, 1 turns it on"


def test_the_controller_and_the_synthetic_journey_are_exempt(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FBI_SYNTHETIC_EMAIL", " Robot@PrediGol.test ")
    assert consents.exempt("robot@predigol.test", super_admin=False)
    assert consents.exempt("owner@predigol.test", super_admin=True)
    assert not consents.exempt("reader@predigol.test", super_admin=False)
    monkeypatch.delenv("FBI_SYNTHETIC_EMAIL")
    assert not consents.exempt("", super_admin=False), "no synthetic account set: nobody matches an empty address"


def _register(versions: list[dict[str, object]]) -> dict[str, tuple[legal.Version, ...]]:
    def v(e: dict[str, object]) -> legal.Version:
        return legal.Version(version=str(e["version"]), date=str(e["version"])[:10], draft=False,
                             material=bool(e["material"]), changes={"es": "x", "en": "x"},
                             sha256={"es": "0" * 64, "en": "0" * 64})
    fixed = (v({"version": "2026-10-25", "material": True}),)
    return {"terms": tuple(v(e) for e in versions), "privacy": fixed, "responsible_gaming": fixed}


def test_a_reader_owes_what_they_never_answered_withdrew_or_answered_before_a_material_change(
        monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(legal, "register", lambda: _register([
        {"version": "2026-10-25", "material": True},
        {"version": "2026-11-02", "material": False},   # a clearer sentence
        {"version": "2026-12-01", "material": True},    # a new obligation
        {"version": "2026-12-05", "material": False},
    ]))
    assert legal.valid_versions("terms") == frozenset({"2026-12-01", "2026-12-05"})
    everything = {"terms": (True, "2026-12-05"), "privacy": (True, "2026-10-25"), "age_18": (True, "2026-12-01"),
                  "risk_notice": (True, "2026-10-25")}
    assert legal.due(everything) == []
    assert legal.due({}) == ["terms", "privacy", "age_18", "risk_notice"], "in the order of the boxes"
    assert legal.due({**everything, "privacy": (False, "2026-10-25")}) == ["privacy"], "withdrawn"
    assert legal.due({**everything, "terms": (True, "2026-11-02")}) == ["terms"], "before the material change"
    assert legal.due({**everything, "age_18": (True, "2026-10-25")}) == ["age_18"]


def test_a_broken_register_is_refused_before_it_reaches_a_reader(monkeypatch: pytest.MonkeyPatch,
                                                                tmp_path: Path) -> None:
    good = json.loads((TEXTS / "versions.json").read_text(encoding="utf-8"))
    cases = {
        "undated": lambda d: d["terms"]["versions"][0].update(version="draft1"),
        "one language": lambda d: d["terms"]["versions"][0]["sha256"].pop("en"),
        "first not material": lambda d: d["terms"]["versions"][0].update(material=False),
        "out of order": lambda d: d["terms"]["versions"].insert(0, {**d["terms"]["versions"][0],
                                                                    "version": "2026-12-01", "date": "2026-12-01"}),
        "missing": lambda d: d.pop("privacy"),
    }
    for label, damage in cases.items():
        data = json.loads(json.dumps(good))
        damage(data)
        folder = tmp_path / label.replace(" ", "_")
        folder.mkdir()
        (folder / "versions.json").write_text(json.dumps(data), encoding="utf-8")
        monkeypatch.setattr(legal, "TEXTS", folder)
        legal.register.cache_clear()
        with pytest.raises(legal.LegalTextError):
            legal.register()
