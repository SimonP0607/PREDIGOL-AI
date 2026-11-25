"""PM-03-06 (Plan Maestro PM, OPS-022; decision DM-03): batch 9 of config/expansion.yaml - the English pyramid, levels 5 to 7, and the FA Trophy (section 3 of the plan, annex A): National League and its North and South divisions, the Isthmian, Northern, Southern South and Southern Central Premier Divisions, and the FA Trophy - decided on the probe
pm-03-01 and migrated as its own tier."""

from __future__ import annotations

from typing import Any

import yaml

from fbi.migration.config import EXPANSION_FILE, expansion_batches, load_migration_config

LEAGUES = [43, 47, 50, 51, 58, 59, 60, 931]


def _batch() -> dict[str, Any]:
    return next(b for b in expansion_batches(EXPANSION_FILE) if int(b["batch"]) == 9)


def test_batch_9_holds_the_competitions_of_the_plan() -> None:
    b = _batch()
    assert b["leagues"] == LEAGUES and int(b["tier"]) == 13
    assert len(set(LEAGUES)) == len(LEAGUES) == 8
    assert all(b["names"][lid] != str(lid) and lid in b["countries"] for lid in LEAGUES), "expand_leagues checks name and country"
    assert "DM-03" in b["rule"] and "pm-03-01" in b["probe"]


def test_no_league_of_batch_9_is_in_another_batch() -> None:
    mine = set(LEAGUES)
    for b in expansion_batches(EXPANSION_FILE):
        if int(b["batch"]) != 9:
            assert not mine & {int(x) for x in b["leagues"]}, b["batch"]


def test_every_league_of_batch_9_was_probed_and_planned_for_it() -> None:
    raw = yaml.safe_load(EXPANSION_FILE.read_text(encoding="utf-8"))
    probe = next(p for p in raw["probes"] if p["key"] == "pm-03-01")
    cands = {int(c["league_id"]): c for c in raw["candidates"]}
    for lid in LEAGUES:
        assert probe["leagues"][lid]["batch"] == 9 and cands[lid]["planned_batch"] == 9, lid


def test_batch_9_is_migrated_as_its_own_tier() -> None:
    cfg = load_migration_config()
    assert cfg.tiers[13] == "P3 expansion - batch 9"
    assert sorted(c.league_id for c in cfg.competitions if c.tier == 13) == sorted(LEAGUES)
