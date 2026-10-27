"""The claims about a team that belong to no match have ONE definition for the readers that choose evidence by match (plan IA, phase 2, finding H4 of
the independent review): ``fbi.ai.team_claims``. This test reads the code, not the data (``tests/integration/test_team_claims_readers.py`` is the
behaviour):

* the term says what the packet says - only research v2's claims, only the ones that belong to no match and are about one of the two teams, only while
  they are fresh and had been read - and keeps the claims the server set aside only for the readers that look back;
* the four readers (the decision layer, the set of the day, the post-match review, the report of the day) each use it, with the moment and the choice
  that fit them, and hand their statement the two words it needs;
* nobody else spells the predicate out again: the packet and the measure of the week of research v2 have theirs on purpose, and no other module has one."""

from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

from fbi.ai import packet
from fbi.ai.evidence import STALE_AFTER
from fbi.ai.team_claims import team_claims, words
from fbi.intel import decision, match_review, report
from fbi.picks import daily

BACKEND = Path(__file__).resolve().parents[2]


def the_term(at: str, *, set_aside: bool = False) -> str:
    """The term as a reader that has a row ``f`` of ``core.fixtures`` in its statement asks for it."""
    return team_claims(home="f.home_team_id", away="f.away_team_id", at=at, set_aside=set_aside)


def test_the_term_is_false_unless_the_caller_says_research_v2_is_on() -> None:
    term = the_term("%(at)s")
    assert term.startswith("(%(typed)s AND "), "the first thing it asks is the caller's word: with off, shadow or on without its gate it is false"
    assert words(False) == {"typed": False, "stale": STALE_AFTER} and words(True) == {"typed": True, "stale": STALE_AFTER}
    assert timedelta(days=10) == STALE_AFTER, "the freshness of the packet, which the term shares by importing it"


def test_the_term_asks_what_the_packet_asks() -> None:
    term = the_term("%(at)s")
    for part in ("e.fixture_id IS NULL", "e.subject_type IS NOT NULL", "e.team_id IN (f.home_team_id, f.away_team_id)", "e.status <> 'OUTDATED'",
                 "e.retrieved_at <= %(at)s", "COALESCE(e.published_at, e.retrieved_at) > %(at)s - %(stale)s"):
        assert part in term, part
    shown = packet.EVIDENCE_SQL
    for part in ("e.fixture_id IS NULL AND e.team_id = ANY(%(teams)s)", "e.status <> 'OUTDATED'", "e.retrieved_at <= %(at)s",
                 "COALESCE(e.published_at, e.retrieved_at) > %(at)s - %(stale)s"):
        assert part in shown, f"the packet no longer says «{part}»: the term must follow it"


def test_the_readers_that_look_back_keep_what_the_server_set_aside_and_the_ones_that_look_forward_do_not() -> None:
    standing, kept = the_term("%(at)s"), the_term("%(at)s", set_aside=True)
    assert "OUTDATED" in standing and "OUTDATED" not in kept
    assert standing.replace(" AND e.status <> 'OUTDATED'", "") == kept, "that is the only difference"


def test_each_of_the_four_readers_uses_the_term_for_its_own_moment() -> None:
    expected = {
        "the decision layer": (decision.EVIDENCE_SQL, the_term("%(at)s")),
        "the set of the day": (daily.EVIDENCE_SQL, the_term("%(at)s")),
        "the post-match review": (match_review.EVIDENCE_SQL, the_term("f.kickoff_at", set_aside=True)),
        "the report of the day": (report.EVIDENCE_SQL, the_term("f.kickoff_at", set_aside=True)),
    }
    for name, (sql, term) in expected.items():
        assert f"JOIN ai.evidence e ON (e.fixture_id = f.id OR {term})" in sql, f"{name}: the claims of the match, or the ones about its teams"
        assert "(e.subject_type IS NULL OR %(typed)s)" in sql, f"{name}: and the claims of research v2 only when the caller says so"


def test_each_of_the_four_readers_hands_its_statement_the_words_the_term_needs() -> None:
    for module in ("intel/decision.py", "picks/daily.py", "intel/match_review.py", "intel/report.py"):
        text = (BACKEND / "src" / "fbi" / module).read_text()
        assert "from fbi.ai.team_claims import team_claims" in text and "from fbi.ai.team_claims import words as team_words" in text, module
        assert re.search(r"\|\s*team_words\(", text), f"{module}: the statement has %(typed)s and %(stale)s in it, and somebody has to answer them"


def test_nobody_else_spells_the_predicate_out_again() -> None:
    """The claims about a team that belong to no match - ``fixture_id IS NULL`` and the team in a list - are read in four places on purpose: here (the
    readers by match), the packet (what the model reads), the decider of the statuses of research v2's claims (``fbi.ai.evidence.TYPED_SQL``) and the
    measure of the week of research v2 (``fbi.ai.gate_research``, which counts what v1 found against what research v2 found). A fifth would be a fifth
    definition to keep alike."""
    spelled = re.compile(r"fixture_id\s+IS\s+NULL\s+AND\s+\w+\.team_id\s+(?:IN|=\s*ANY)", re.IGNORECASE)
    where = sorted(str(p.relative_to(BACKEND)) for p in (BACKEND / "src" / "fbi").rglob("*.py") if spelled.search(p.read_text()))
    assert where == ["src/fbi/ai/evidence.py", "src/fbi/ai/gate_research.py", "src/fbi/ai/packet.py"], where
    term = (BACKEND / "src" / "fbi" / "ai" / "team_claims.py").read_text()
    assert "e.fixture_id IS NULL AND e.subject_type IS NOT NULL AND e.team_id IN (" in term, "and this is the fourth, with the claims of research v2 only"
