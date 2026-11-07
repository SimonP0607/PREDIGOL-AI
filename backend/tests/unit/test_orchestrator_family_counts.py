"""IA-014: the count candidates of the Statistics Agent come from the families' decisions (``fam-counts-v1``). What holds without a database: the mapping
of the markets is the agent's families and the catalogue's rules, a pass of the Batch keeps what its first run did, and the names of goals and result
are the same whatever counts are added."""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from fbi.ai import orchestrator_store
from fbi.ai.agents import stats
from fbi.ai.agents.common import is_full_time, name_candidates, name_with_counts
from fbi.ai.contracts.base import COUNTS
from fbi.ai.contracts.mcp import family_of
from fbi.ai.orchestrator import _Runner
from fbi.ai.review import Candidate
from fbi.market.rules import RULES_BY_KEY

KICKOFF = datetime(2026, 11, 8, 20, 0, tzinfo=UTC)
D = Decimal


def candidate(market: str, selection: str, line: str, p: str, ev: str | None = None, **kw: Any) -> Candidate:
    return Candidate(fixture_id=7, market_key=market, selection=selection, line=D(line), p_model=D(p), kickoff_at=KICKOFF,
                     ev=None if ev is None else D(ev), **kw)


def test_every_market_maps_to_the_agents_family_and_to_a_rule_of_the_catalogue_that_grades_the_whole_match() -> None:
    assert orchestrator_store.COUNTS_SOURCE_VERSION == "fam-counts-v1"
    for market, (family, rule) in orchestrator_store.COUNT_MARKETS.items():
        assert family in COUNTS and family_of(market) == family, market
        assert is_full_time(market), market
        assert stats.SETTLEMENT[family] == rule, market
        assert RULES_BY_KEY[rule].period == "FT" and RULES_BY_KEY[rule].liquidable, rule
    assert not {m for m in orchestrator_store.COUNT_MARKETS if m.startswith(("YELLOW", "OU_", "1X2_"))}


def test_the_source_of_the_counts_is_read_only_with_the_agent_on_and_a_batch_pass_keeps_its_first_word() -> None:
    def task(route: dict[str, Any]) -> Any:
        return SimpleNamespace(route=route)

    assert _Runner.counts_wanted((), stats_on=True) is True
    assert _Runner.counts_wanted((), stats_on=False) is False
    assert _Runner.counts_wanted((task({"stats": True, "counts": "fam-counts-v1"}),), stats_on=True) is True
    assert _Runner.counts_wanted((task({"stats": True}),), stats_on=True) is False, "a pass queued before the source existed is resumed as one"
    assert _Runner.counts_wanted((task({"stats": True, "counts": None}),), stats_on=True) is False
    assert _Runner.counts_wanted((task({"stats": True, "counts": "fam-counts-v9"}),), stats_on=True) is False
    assert _Runner.counts_wanted((task({"counts": "fam-counts-v1"}),), stats_on=False) is False


def test_goals_and_result_keep_their_names_whatever_counts_of_the_families_are_added() -> None:
    reviewed = (candidate("OU", "Over", "2.5", "0.58", "0.10"), candidate("1X2", "Home", "0", "0.55", "0.15"), candidate("1X2", "Draw", "0", "0.27", "-0.02"))
    family = (candidate("CORNERS_OU", "Over", "9.5", "0.58", "0.10", model="family-corners_ft", n_bookmakers=3),
              candidate("CARDS_OU", "Over", "4.5", "0.55", "0.07", model="family-cards_lines_ft"),
              candidate("CORNERS_1X2", "Home", "0", "0.52", "0.09"))
    base = name_candidates(reviewed)
    for added in (family, family[::-1], family[:1], ()):
        naming = name_with_counts((*reviewed, *added))
        assert naming.named[: len(base.named)] == base.named
        assert len(stats.asked_keys(naming)) == len(added)
    naming = name_with_counts((*reviewed, *family))
    assert [(n.key, n.candidate.market_key) for n in naming.named[3:]] == [("c4", "CORNERS_1X2"), ("c5", "CORNERS_OU"), ("c6", "CARDS_OU")]
    assert stats.asked_keys(name_with_counts(reviewed)) == (), "the defect: the reviews of production alone have no count"


def test_a_selection_production_reviewed_keeps_its_own_numbers_over_the_familys() -> None:
    mine = candidate("CORNERS_OU", "Over", "9.5", "0.56", "0.05")
    theirs = candidate("CORNERS_OU", "Over", "9.50", "0.58", "0.10", model="family-corners_ft")
    counts = orchestrator_store.FamilyCounts((theirs,), (41,))
    naming = name_with_counts((mine, theirs))
    [key] = stats.asked_keys(naming)
    picked = naming.resolve(key)
    assert picked is not None and picked.candidate is mine
    assert counts.decision_of(mine) is None and counts.decision_of(theirs) == 41
