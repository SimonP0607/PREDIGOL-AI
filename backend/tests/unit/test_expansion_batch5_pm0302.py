"""PM-03-02 (Plan Maestro PM, OPS-015; decision DM-03): batch 5 of config/expansion.yaml - Colombia's Superliga and Liga Femenina,
CONMEBOL Recopa, OFC Champions League, AFC Challenge League and the Africa Cup of Nations qualification - decided on the probe
pm-03-01 and migrated as its own tier."""

from __future__ import annotations

from typing import Any

import yaml

from fbi.migration.config import EXPANSION_FILE, expansion_batches, load_migration_config

LEAGUES = [713, 712, 541, 27, 1132, 36]
NAMES = {713: ("Superliga", "Colombia"), 712: ("Liga Femenina", "Colombia"), 541: ("CONMEBOL Recopa", "World"),
         27: ("OFC Champions League", "World"), 1132: ("AFC Challenge League", "World"),
         36: ("Africa Cup of Nations - Qualification", "World")}


def _batch5() -> dict[str, Any]:
    return next(b for b in expansion_batches(EXPANSION_FILE) if int(b["batch"]) == 5)


def test_batch_5_holds_the_six_competitions_of_the_plan() -> None:
    b = _batch5()
    assert b["leagues"] == LEAGUES and int(b["tier"]) == 9
    for lid, (name, country) in NAMES.items():
        assert b["names"][lid] == name and b["countries"][lid] == country, "expand_leagues checks both against the provider"
    assert "DM-03" in b["rule"] and "pm-03-01" in b["probe"]


def test_every_league_of_batch_5_was_probed_and_planned_for_it() -> None:
    raw = yaml.safe_load(EXPANSION_FILE.read_text(encoding="utf-8"))
    probe = next(p for p in raw["probes"] if p["key"] == "pm-03-01")
    cands = {int(c["league_id"]): c for c in raw["candidates"]}
    for lid in LEAGUES:
        assert probe["leagues"][lid]["batch"] == 5 and cands[lid]["planned_batch"] == 5, lid
        assert probe["leagues"][lid]["player_stats"] == 0.0 or lid == 36


def test_batch_5_is_migrated_as_its_own_tier() -> None:
    cfg = load_migration_config()
    assert cfg.tiers[9] == "P3 expansion - batch 5"
    assert sorted(c.league_id for c in cfg.competitions if c.tier == 9) == sorted(LEAGUES)
