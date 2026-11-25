"""PM-03-05 (Plan Maestro PM, OPS-021; decision DM-03): batch 8 of config/expansion.yaml - the competitions of Asia, Africa and Oceania still missing (Australia, Egypt, India, Japan, Qatar, Saudi Arabia, South Korea and the United Arab Emirates; section 3 of the plan, annex A) - decided on the probe
pm-03-01 and migrated as its own tier."""

from __future__ import annotations

from typing import Any

import yaml

from fbi.migration.config import EXPANSION_FILE, expansion_batches, load_migration_config

LEAGUES = [874, 1202, 539, 887, 895, 324, 545, 101, 102, 306, 677, 824, 825, 308, 826, 293, 294, 302, 303, 560, 896]


def _batch() -> dict[str, Any]:
    return next(b for b in expansion_batches(EXPANSION_FILE) if int(b["batch"]) == 8)


def test_batch_8_holds_the_competitions_of_the_plan() -> None:
    b = _batch()
    assert b["leagues"] == LEAGUES and int(b["tier"]) == 12
    assert len(set(LEAGUES)) == len(LEAGUES) == 21
    assert all(b["names"][lid] != str(lid) and lid in b["countries"] for lid in LEAGUES), "expand_leagues checks name and country"
    assert "DM-03" in b["rule"] and "pm-03-01" in b["probe"]


def test_no_league_of_batch_8_is_in_another_batch() -> None:
    mine = set(LEAGUES)
    for b in expansion_batches(EXPANSION_FILE):
        if int(b["batch"]) != 8:
            assert not mine & {int(x) for x in b["leagues"]}, b["batch"]


def test_every_league_of_batch_8_was_probed_and_planned_for_it() -> None:
    raw = yaml.safe_load(EXPANSION_FILE.read_text(encoding="utf-8"))
    probe = next(p for p in raw["probes"] if p["key"] == "pm-03-01")
    cands = {int(c["league_id"]): c for c in raw["candidates"]}
    for lid in LEAGUES:
        assert probe["leagues"][lid]["batch"] == 8 and cands[lid]["planned_batch"] == 8, lid


def test_batch_8_is_migrated_as_its_own_tier() -> None:
    cfg = load_migration_config()
    assert cfg.tiers[12] == "P3 expansion - batch 8"
    assert sorted(c.league_id for c in cfg.competitions if c.tier == 12) == sorted(LEAGUES)
