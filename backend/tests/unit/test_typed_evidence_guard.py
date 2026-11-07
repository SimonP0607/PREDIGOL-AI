"""Nobody reads what research v2 wrote by accident (plan IA, phase 2). Its claims are rows of ``ai.evidence`` with a ``subject_type``; they exist beside
v1's items for the comparison and are part of what the system knows only when ``FBI_AI_RESEARCH_V2=on`` and the evidence of its gate says so
(``fbi.ai.gates.typed_visible``). This test reads the code, not the data (``tests/integration/test_typed_evidence_readers.py`` is the behaviour):

* every statement that reads ``ai.evidence`` - every ``FROM`` and every ``JOIN`` of it, subqueries included - either filters the claims
  (``subject_type IS NULL OR <what the caller says>``), or is a reader that chooses on purpose (v1's own: ``subject_type IS NULL``; research v2's
  own: ``IS NOT NULL``), or is one of the few lookups BY ID of something a packet or a decision already cited, listed below with its reason;
* the code that gives the answer to the filter exists wherever the filter is;
* only research v2's extractor writes a ``subject_type``: v1 never does.

A new reader of the table that forgets the filter fails here, with the file and the statement."""

from __future__ import annotations

import ast
import functools
import re
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parents[2]
SOURCES = sorted([*(BACKEND / "src" / "fbi").rglob("*.py"), *(BACKEND / "scripts").glob("*.py")])

READS = re.compile(r"\b(?:FROM|JOIN)\s+ai\.evidence\b", re.IGNORECASE)
"""A statement reads the table when it names it after FROM or JOIN (a write says INSERT INTO / UPDATE)."""
HIDES = re.compile(r"\bsubject_type\s+IS\s+NULL\s+OR\s+\(?\s*(?:%\(typed\)s|%s)", re.IGNORECASE)
"""The shadow-invisibility filter: the claim is shown only when the caller says so."""
V1_ONLY = re.compile(r"\bsubject_type\s+IS\s+NULL\b(?!\s+OR)", re.IGNORECASE)
TYPED_ONLY = re.compile(r"\bsubject_type\s+IS\s+NOT\s+NULL\b", re.IGNORECASE)

OWN_READERS = {"src/fbi/ai/evidence.py", "src/fbi/ai/gate_research.py", "src/fbi/api/services/ai_research.py",
               "src/fbi/evidence/engine.py"}
"""The modules that read one kind on purpose. ``fbi.ai.evidence`` decides the statuses of v1's items (``LOAD_SQL``: untyped only) and those of
research v2's claims (``TYPED_SQL``: typed only) apart from each other; ``fbi.ai.gate_research`` is the measure of the week in which both ran side by
side: it counts what v1 found (untyped) against what research v2 found (typed) and what reviews and decisions cite of the second. It writes only its own
row of ``ai.feature_gates``; nothing it reads reaches a packet, a card or a pick. ``fbi.api.services.ai_research`` is the owner's page about research v2
in the Admin Console: it counts the claims research v2 wrote (class of source, type, status) and reads nothing else of ``ai.evidence``; it writes
nothing and what it shows goes nowhere but to that page. ``fbi.evidence.engine`` is the Evidence Engine of IA-012, in shadow: it reads v1's items and
research v2's claims, each kind by its own statement, to compute tiers, statuses, confidence and validity; it writes nothing and nothing that decides,
publishes or serves a user imports it (``tests/unit/test_evidence_engine_isolation.py``)."""

BY_ID = (
    ("src/fbi/api/services/intelligence.py", "FROM ai.evidence WHERE id = ANY(%(ids)s)", r"\bid\s*=\s*ANY\(",
     "the evidence a brief or a packet CITED, by id: when research v2 is not on, no packet cites a claim of it"),
    ("src/fbi/api/services/ai_layer.py", "FROM ai.evidence WHERE id = ANY(%(ids)s)", r"\bid\s*=\s*ANY\(",
     "the same: the sources a stored packet cites, by id"),
    ("src/fbi/intel/leakage.py", "JOIN ai.evidence ev ON ev.id = x.eid", r"\bev\.id\s*=\s*x\.eid",
     "the audit of the evidence a decision cited (``decision.evidence_ids``), by id - it measures what the decision saw, whatever it was"),
    ("src/fbi/intel/leakage.py", "FROM ai.evidence ev WHERE ev.id = ANY(%(ids)s)", r"\bev\.id\s*=\s*ANY\(",
     "the audit of the evidence an agent run or a review of the shadow CITED (``agent_known``, ``shadow_review_known``), by id - it measures what "
     "was cited, whatever it was"),
    ("src/fbi/ai/evidence.py", "FROM ai.evidence WHERE story_key = %s AND content_hash = %s", r"story_key\s*=\s*%s\s+AND\s+content_hash\s*=\s*%s",
     "the deduplication of ``store``: the row that already has the identity (story, content hash) of the item being written - the hash of a "
     "typed claim is another one, so a claim of research v2 is never found for an item of v1"),
)
"""Lookups by id: they read what something else already pointed at, so they show a claim of research v2 only if a packet or a decision
cited it - which only ``on`` does. Everything else filters."""


class Strings(ast.NodeVisitor):
    """Every string of a module that could be SQL: a constant, or an f-string as one text (its constant parts together), once each."""

    def __init__(self) -> None:
        self.found: list[tuple[int, str]] = []

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str):
            self.found.append((node.lineno, node.value))

    def visit_JoinedStr(self, node: ast.JoinedStr) -> None:
        self.found.append((node.lineno, "".join(v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str))))
        for part in node.values:  # the expressions inside the braces can hold strings of their own
            if isinstance(part, ast.FormattedValue):
                self.visit(part.value)


def strings(path: Path) -> list[tuple[int, str]]:
    visitor = Strings()
    visitor.visit(ast.parse(path.read_text()))
    return visitor.found


def readings(text: str) -> list[str]:
    """The part of a statement that belongs to each read of the table: from its ``FROM``/``JOIN`` up to the next read (or the end)."""
    starts = [m.start() for m in READS.finditer(text)]
    ends = [*starts[1:], len(text)]
    return [text[a:b] for a, b in zip(starts, ends, strict=False)]


def unfiltered(text: str) -> list[str]:
    """The reads of a statement that neither filter the claims of research v2 nor choose them on purpose."""
    return [r for r in readings(text) if not HIDES.search(r) and not V1_ONLY.search(r) and not TYPED_ONLY.search(r)]


@functools.cache
def statements() -> list[tuple[str, int, str]]:
    found: list[tuple[str, int, str]] = []
    for path in SOURCES:
        for line, text in strings(path):
            if READS.search(text):
                found.append((str(path.relative_to(BACKEND)), line, text))
    return found


# ── the guard itself: it must see what it is meant to see ────────────────────────────────────────────────────────────

def test_the_guard_sees_an_unfiltered_read_a_filtered_one_and_one_filter_for_two_reads() -> None:
    assert unfiltered("SELECT 1 FROM ai.evidence e WHERE e.fixture_id = 1")
    assert unfiltered("SELECT 1 FROM ai.evidence e JOIN x ON x.id = e.id WHERE e.kind = 'lineup'")
    assert not unfiltered("SELECT 1 FROM ai.evidence e WHERE e.fixture_id = 1 AND (e.subject_type IS NULL OR %(typed)s)")
    assert not unfiltered("SELECT 1 FROM ai.evidence WHERE (subject_type IS NULL OR (%(typed)s AND published_at > %(at)s))")
    assert not unfiltered("SELECT 1 FROM ai.evidence e WHERE (e.subject_type IS NULL OR %s) GROUP BY 1")
    assert not unfiltered("SELECT 1 FROM ai.evidence e WHERE e.subject_type IS NULL AND e.retrieved_at <= %(at)s"), "v1's own reader"
    assert not unfiltered("SELECT 1 FROM ai.evidence e WHERE e.subject_type IS NOT NULL"), "research v2's own reader"
    two = ("SELECT (SELECT count(*) FROM ai.evidence WHERE kind = 'lineup' AND (subject_type IS NULL OR %(typed)s)) AS a, "
           "(SELECT count(*) FROM ai.evidence WHERE kind = 'injury') AS b")
    assert len(readings(two)) == 2 and len(unfiltered(two)) == 1, "a filter in the first read does not cover the second"
    assert not unfiltered("INSERT INTO ai.evidence (claim) VALUES (%s)"), "writing is not reading"
    assert unfiltered("SELECT 1 FROM ai.evidence e WHERE e.subject_type IS NULL OR e.fixture_id = 3"), "``IS NULL OR`` something that is not the caller's word"


def test_the_guard_reads_a_good_part_of_the_code() -> None:
    found = statements()
    files = {f for f, _, _ in found}
    reads = sum(len(readings(t)) for _, _, t in found)
    assert reads >= 20 and len(files) >= 9, "the scan finds the readers of the table (a regex that matches nothing guards nothing)"
    assert {"src/fbi/ai/packet.py", "src/fbi/picks/daily.py", "src/fbi/intel/decision.py", "src/fbi/api/services/ai_v2.py"} <= files


# ── the code ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_every_read_of_the_evidence_table_filters_the_claims_of_research_v2_or_is_a_lookup_by_id() -> None:
    exempt = {(f, s) for f, s, _, _ in BY_ID}
    bad: list[str] = []
    for file, line, text in statements():
        for part in unfiltered(text):
            if any(f == file and s in part for f, s in exempt):
                continue
            bad.append(f"{file}:{line}: {' '.join(part.split())[:150]}")
    assert bad == [], "these statements read ai.evidence without filtering the claims of research v2 (``subject_type IS NULL OR %(typed)s``):\n" \
        + "\n".join(bad)


def test_each_lookup_of_something_already_named_is_still_there_still_by_its_name_and_says_why() -> None:
    for file, snippet, shape, reason in BY_ID:
        parts = [part for f, _, text in statements() if f == file for part in readings(text) if snippet in part]
        assert len(parts) == 1, f"{file}: «{snippet}» is not (or not only once) in the code: take it out of BY_ID"
        assert re.search(shape, parts[0]), f"{file}: a lookup of something already named is by its name"
        assert len(reason) > 40, f"{file}: say why it is safe"


def test_only_the_files_that_decide_on_purpose_read_one_kind_only() -> None:
    wrong: list[str] = []
    for file, line, text in statements():
        for part in readings(text):
            if (V1_ONLY.search(part) or TYPED_ONLY.search(part)) and not HIDES.search(part) and file not in OWN_READERS:
                wrong.append(f"{file}:{line}")
    assert wrong == [], "choosing one kind of evidence on purpose is for the module that decides the statuses (fbi.ai.evidence)"


def test_wherever_the_filter_is_the_code_that_answers_it_is_too() -> None:
    """A statement with ``%(typed)s`` or ``subject_type IS NULL OR %s`` is run by code that gives the answer: ``typed_visible`` (the settings
    and the gate), or the packet builder's ``typed_evidence`` (told by the cycle)."""
    asks = re.compile(r"typed_visible\(|typed_evidence|\btyped:\s*bool\b|\"typed\"")
    silent = [file for file in sorted({f for f, _, t in statements() if HIDES.search(t)})
              if not asks.search((BACKEND / file).read_text())]
    assert silent == [], f"filters without anyone to answer them: {silent}"


def test_only_the_extractor_of_research_v2_writes_a_subject_type() -> None:
    """v1's collectors build ``EvidenceIn`` without a subject: its rows are what they always were."""
    writers = sorted(str(p.relative_to(BACKEND)) for p in SOURCES if "subject_type=" in p.read_text())
    assert writers == ["src/fbi/ai/extract_v2.py"], \
        "``EvidenceIn(subject_type=...)`` is research v2's; ``fbi.ai.evidence`` only declares the field and stores what it is given"


@pytest.mark.parametrize("file", ["src/fbi/ai/collectors.py", "src/fbi/ai/research.py", "src/fbi/ai/cycle.py"])
def test_v1s_own_collectors_never_set_a_subject(file: str) -> None:
    assert "subject_type" not in (BACKEND / file).read_text().replace("research_v2", ""), file
