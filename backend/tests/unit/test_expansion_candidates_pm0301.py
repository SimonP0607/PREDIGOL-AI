"""PM-03-01 (BE-066, Plan Maestro PM, decision DM-03): the 60 competitions of batches 5-9 are candidates of
config/expansion.yaml with their planned batch and the read-only probe of 20 Nov 2026 - and none of them is tracked by the
file (no batch holds them), so batch 4 and everything already decided stay as they were."""

from __future__ import annotations

from typing import Any

import pytest
import yaml

import fbi.coverage.levels as lv
from fbi.market.settle_coverage import Coverage
from fbi.migration.config import EXPANSION_FILE, expansion_batches, load_migration_config

PLANNED: dict[int, list[int]] = {
    5: [713, 712, 541, 27, 1132, 36],
    6: [129, 130, 517, 810, 1178, 632, 266, 267, 527, 263, 857, 304, 257, 269, 842, 930],
    7: [220, 147, 519, 120, 121, 550, 181, 182, 185],
    8: [874, 1202, 539, 887, 895, 324, 545, 101, 102, 306, 677, 824, 825, 308, 826, 293, 294, 302, 303, 560, 896],
    9: [43, 47, 50, 51, 58, 59, 60, 931],
}
"""Batches 5-9 of section 3 of the plan and of annex A (DM-03)."""
ALREADY = {36, 129, 263, 269, 887, 101, 43, 59, 60}
"""Candidates before PM-03-01 (capacity report of 5 Oct 2026): they only gain ``planned_batch``."""
SHARES = ("events", "lineups", "team_stats", "xg", "player_stats", "referee", "goals_match_events")
CAP = 240
"""The card of PM-03-01: about 240 requests (4 per competition)."""


def _raw() -> dict[str, Any]:
    raw: dict[str, Any] = yaml.safe_load(EXPANSION_FILE.read_text(encoding="utf-8"))
    return raw


def _probe() -> dict[str, Any]:
    found = [p for p in _raw()["probes"] if p["key"] == "pm-03-01"]
    assert len(found) == 1
    return found[0]


def test_the_sixty_are_candidates_with_their_planned_batch_name_and_country() -> None:
    cands = {int(c["league_id"]): c for c in _raw()["candidates"]}
    for batch, leagues in PLANNED.items():
        for lid in leagues:
            c = cands[lid]
            assert c["planned_batch"] == batch, lid
            assert c.get("name") and c.get("country"), "expand_leagues checks both against raw.league_coverage"
    assert sum(len(v) for v in PLANNED.values()) == 60
    assert {lid for lid, c in cands.items() if "planned_batch" in c} == {lid for v in PLANNED.values() for lid in v}
    new = [c for lid, c in cands.items() if "planned_batch" in c and lid not in ALREADY]
    assert len(new) == 51 and min(int(c["rank"]) for c in new) == 59
    ranks = [int(c["rank"]) for c in _raw()["candidates"]]
    assert len(ranks) == len(set(ranks))


def test_only_the_written_batches_are_tracked_by_the_file() -> None:
    """Each batch is written by its own task (PM-03-02 batch 5, ... PM-03-06 batch 9) after the previous one was measured."""
    batches = expansion_batches(EXPANSION_FILE)
    written = {5}
    assert [int(b["batch"]) for b in batches] == [1, 2, 3, 4, *sorted(written)]
    in_batches = {int(lid) for b in batches for lid in b["leagues"]}
    assert not in_batches & {lid for b, v in PLANNED.items() if b not in written for lid in v}
    for b in written:
        assert next(x for x in batches if int(x["batch"]) == b)["leagues"] == PLANNED[b]
    assert next(b for b in batches if int(b["batch"]) == 4)["leagues"] == [268, 241], "batch 4 (Plan AD) untouched"
    cfg = load_migration_config()
    assert max(cfg.tiers) == 8 + len(written), "one tier per written batch, none for a candidate"


def test_every_candidate_has_a_dated_probe_within_the_cap() -> None:
    probe = _probe()
    assert probe["at"].startswith("2026-11-20") and probe["stored_in_raw"] is False
    assert probe["rules"] == lv.RULES_VERSION
    assert 0 < int(probe["requests"]) <= CAP
    measured = {int(k): v for k, v in probe["leagues"].items()}
    assert sorted(measured) == sorted(lid for v in PLANNED.values() for lid in v)
    for lid, m in measured.items():
        assert m["batch"] == next(b for b, v in PLANNED.items() if lid in v), lid
        assert m["finished"] + m["ahead"] <= m["fixtures"] and m["sampled"] <= min(m["finished"], 20), lid
        for k in SHARES:
            assert m[k] is None or 0.0 <= float(m[k]) <= 1.0, (lid, k)
        assert m["bookmakers"] is None or float(m["bookmakers"]) > 0, "null means not asked, never 0"


def _level(share: float | None, n: int) -> lv.Level:
    return lv.grade_datum(Coverage(n, round(float(share) * n))).level if share is not None and n else "MI"


@pytest.mark.parametrize("lid", [lid for v in PLANNED.values() for lid in v])
def test_the_expected_level_of_each_family_follows_coverage_levels_v1(lid: int) -> None:
    m = _probe()["leagues"][lid]
    exp = m["expected"]
    assert set(exp) == {*lv.FAMILIES, "summary"}
    n = int(m["sampled"])
    assert exp["base"] == lv.worst([_level(m["events"], n), _level(m["lineups"], n)]), lid
    for family in ("team_stats", "xg", "player_stats"):
        assert exp[family] == _level(m[family], n), (lid, family)
    assert exp["referee"] == _level(m["referee"], int(m["finished"])), lid
    if n < lv.A_SAMPLE:
        assert all(exp[f] != "A" for f in ("base", "team_stats", "xg", "player_stats")), "20 matches never say A"
    assert all(str(exp[f]).startswith("MI") for f in lv.MARKET_FAMILIES), "a probe does not grade the odds"
    assert str(exp["summary"]).rstrip("*") in lv.LEVELS
