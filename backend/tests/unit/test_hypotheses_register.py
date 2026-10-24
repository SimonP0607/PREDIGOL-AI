"""Plan F12.4: the hypotheses the repository proposes are well formed - they fit what the console and the API take, they read the same on the screen
as they were written, and they quote nothing that is not tied to a guide.

The figures against the guide they come from are in ``test_docs_match_code.py``; the writing in a real database is in
``tests/integration/test_hypotheses_register.py``. Here: no database."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from fbi.ai.text import shown
from fbi.api.contracts.evolution import HypothesisIn
from fbi.core.version import MODEL_PACKAGES
from fbi.families import bets
from fbi.research import evolution, hypotheses
from fbi.research.hypotheses import REGISTER


def test_the_register_is_not_empty_and_each_proposal_has_its_own_versioned_key() -> None:
    keys = [p.key for p in REGISTER]
    assert len(keys) >= 2 and len(set(keys)) == len(keys), "a key proposes once: two proposals cannot share it"
    for key in keys:
        assert re.fullmatch(r"f11:[a-z_]+:v[0-9]+", key), f"{key!r}: the origin (the measurement), what it proposes and its version"
    assert hypotheses.find(hypotheses.RECENT_LEVEL_KEY) is hypotheses.RECENT_LEVEL and hypotheses.find("nope") is None


def test_a_proposal_fits_what_the_owner_may_write_and_what_the_database_keeps() -> None:
    """The limits of ``HypothesisIn`` (what the owner may write by hand in Evolución) and of the title column are the proposal's: nothing is cut
    on the way in."""
    fields = HypothesisIn.model_fields
    limits = {name: next(m.max_length for m in fields[name].metadata if hasattr(m, "max_length")) for name in ("title", "hypothesis", "rationale")}
    assert (limits["title"], limits["hypothesis"], limits["rationale"]) == (hypotheses.MAX_TITLE, hypotheses.MAX_HYPOTHESIS, hypotheses.MAX_RATIONALE)
    for p in REGISTER:
        assert 10 <= len(p.title) <= hypotheses.MAX_TITLE, p.key
        assert 20 <= len(p.hypothesis) <= hypotheses.MAX_HYPOTHESIS, p.key
        assert 20 <= len(p.rationale) <= hypotheses.MAX_RATIONALE, p.key
        assert p.target in evolution.TARGETS, p.key
    assert hypotheses.PROPOSED_BY in ("ai", "owner", "system") and hypotheses.PROPOSED_BY == "system"


def test_the_evidence_is_what_the_card_reads_and_fits_what_it_shows() -> None:
    """The card shows the matches, the impact and the cost apart and up to six more values as chips (a text cut at 90 characters): everything
    a proposal puts in its evidence must be shown whole."""
    for p in REGISTER:
        e = p.evidence
        assert isinstance(e["n_matches"], int) and e["n_matches"] > 0, p.key
        for apart in ("impact", "investigation_cost"):
            assert isinstance(e[apart], str) and e[apart].strip(), (p.key, apart)
        chips = {k: v for k, v in e.items() if k not in hypotheses.APART}
        assert 1 <= len(chips) <= hypotheses.MAX_CHIPS, f"{p.key}: the card shows {hypotheses.MAX_CHIPS} chips, not {len(chips)}"
        for k, v in chips.items():
            assert isinstance(v, (str, int)) and not isinstance(v, bool), f"{p.key}.{k}: a plain value, not a structure"
            assert len(str(v)) <= hypotheses.MAX_CHIP, f"{p.key}.{k} would be cut on the page"
        assert e["guide"].startswith(hypotheses.GUIDE) and hypotheses.SECTION.startswith("## 7."), p.key
    assert "investigation_cost" in hypotheses.APART and "n_matches" in hypotheses.APART and "impact" in hypotheses.APART


def test_what_the_owner_reads_is_what_was_written() -> None:
    """The texts of the AI layer pass through ``shown`` on their way to the page (reference tags to words, older phrases to plain ones); a
    proposal that ``shown`` changed would be read differently from what the guide and the test compare."""
    for p in REGISTER:
        for name in ("title", "hypothesis", "rationale"):
            text = getattr(p, name)
            assert shown(text) == text, f"{p.key}.{name} is changed by ai.text.shown"
        for k, v in p.evidence.items():
            if isinstance(v, str):
                assert shown(v) == v, f"{p.key}.{k}"


def test_every_figure_a_proposal_cites_is_in_its_own_text() -> None:
    """The list of cited figures is the list the guide test checks: a figure the text no longer quotes, or a quoted figure left out of the list,
    would leave the guide and the proposal free to drift apart without a test noticing. (The window of the prices is in the evidence, not in the
    text.)"""
    for p in REGISTER:
        assert p.cited, f"{p.key} quotes nothing from a guide"
        said = [p.rationale, *(v for v in p.evidence.values() if isinstance(v, str))]
        for c in p.cited:
            assert any(c.text in text for text in said), f"{p.key} lists {c.text!r} but neither its rationale nor its evidence says it"
        # every number with a sign, a decimal comma or a thousands point that the rationale writes is a figure of the guide, listed as cited
        quoted = set(re.findall(r"[+\N{MINUS SIGN}]?\d+[.,]\d+(?: ?%)?(?: ± \d+[.,]\d+(?: ?%)?)?", p.rationale))
        listed = {c.text for c in p.cited}
        for q in quoted:
            assert any(q == text or q in text or text in q for text in listed), f"{p.key} quotes {q!r} without listing where the guide says it"


def test_a_proposal_that_depends_on_another_comes_after_it_and_names_it_by_its_title() -> None:
    titles = [p.title for p in REGISTER]
    for i, p in enumerate(REGISTER):
        needs = p.evidence.get("depends_on")
        if needs is not None:
            assert needs in titles[:i], f"{p.key} depends on {needs!r}, which must be registered before it"
    assert hypotheses.MARKET_BLEND.evidence["depends_on"] == hypotheses.RECENT_LEVEL.title
    assert titles.index(hypotheses.RECENT_LEVEL.title) < titles.index(hypotheses.MARKET_BLEND.title)


def test_the_criterion_a_proposal_quotes_is_the_plans() -> None:
    """The criterion is said in words in the proposal and in the guide, and lives in code as ``bets.MIN_BETS`` and a closing-line value that must
    not be negative."""
    said = re.search(r"al menos (\d+) apuestas simuladas y valor de cierre no negativo", hypotheses.CRITERION.text)
    assert said and int(said.group(1)) == bets.MIN_BETS
    assert hypotheses.CRITERION.text in hypotheses.RECENT_LEVEL.rationale
    assert bets.verdict(bets.MIN_BETS, 0.0) == bets.MEETS, "a value of exactly zero meets it: 'no negativo'"


def test_the_guide_a_proposal_names_exists_and_adding_a_proposal_does_not_change_the_model_code() -> None:
    """The module is not model code: its path is outside the packages the fingerprint covers, so adding a proposal opens no new model version
    and needs no row in the model-code ledger."""
    base = Path(hypotheses.__file__).resolve().parents[1]
    assert Path(hypotheses.__file__).resolve().relative_to(base).parts[0] == "research"
    assert "research" not in MODEL_PACKAGES
    guide = Path(__file__).resolve().parents[2] / "docs" / "owner" / hypotheses.GUIDE
    assert guide.is_file(), "the guide the proposals rest on is shipped next to the code"


def test_the_listing_says_what_is_registered_and_what_is_not() -> None:
    first, second = REGISTER[0], REGISTER[1]
    out = hypotheses.render({first.key: (7, "REJECTED")})
    assert f"{first.key}  [models]  registered as #7 (REJECTED)" in out and f"{second.key}  [models]  not registered" in out
    assert out.endswith("2 proposals in the register, 1 registered, 1 not yet.")
    everything = hypotheses.render({p.key: (i + 1, "PROPOSED") for i, p in enumerate(REGISTER)}, full=True)
    assert everything.endswith("all registered.") and "rationale:" in everything and "hypothesis:" in everything and "evidence:" in everything
    assert "rationale:" not in out


def test_every_evidence_key_has_its_label_on_the_page_in_both_languages() -> None:
    """The card says each chip by the label of its key (``ai.v2.evidenceKey``); a key without one would show as the raw name of the field."""
    root = Path(__file__).resolve().parents[3] / "web" / "src" / "locales"
    if not (root / "es" / "ai.json").is_file():
        pytest.skip("no web catalog next to the code")
    for language in ("es", "en"):
        labels = json.loads((root / language / "ai.json").read_text(encoding="utf-8"))["v2"]["evidenceKey"]
        for p in REGISTER:
            for key in p.evidence:
                assert labels.get(key, "").strip(), f"{p.key}: the page has no {language} label for the evidence key {key!r}"
