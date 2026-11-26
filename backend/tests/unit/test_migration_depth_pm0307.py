"""PM-03-07 (Plan Maestro PM, OPS-019; decision DM-03): ``scripts.migration --depth N`` plans the current season and the N completed
seasons before it, so the history of the new competitions (priorities P0 to P2) is two seasons and not the eight of the first tiers."""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts import migration as cli

from fbi.migration.config import load_migration_config
from fbi.migration.planner import plan_migration
from tests.unit.test_migration_planner import FULL, DictFacts


@pytest.fixture(scope="module")
def cfg():
    return load_migration_config()


def test_depth_none_leaves_the_configs_own_depth_in_force(cfg) -> None:
    assert cli.depth_seasons(cfg, None) is None


def test_depth_two_is_the_current_season_and_the_two_before_it(cfg) -> None:
    assert cli.depth_seasons(cfg, 2) == [cfg.current_season, cfg.current_season - 1, cfg.current_season - 2]
    assert cli.depth_seasons(cfg, 0) == [cfg.current_season]
    assert cli.depth_seasons(cfg, cfg.target_depth) == cfg.seasons()


def test_a_negative_depth_is_refused(cfg) -> None:
    with pytest.raises(SystemExit):
        cli.depth_seasons(cfg, -1)


def test_the_plan_with_depth_two_prices_only_those_seasons_and_less_than_the_default(cfg) -> None:
    tier = max(cfg.tiers)  # any tier: the first competition of it
    lid = next(c.league_id for c in cfg.tier_competitions({tier}))
    listed = {lid: set(range(cfg.current_season - 10, cfg.current_season + 1))}
    facts = DictFacts(coverage={(lid, s): FULL for s in listed[lid]}, listed=listed)
    short = plan_migration(cfg, facts, tiers={tier}, seasons=cli.depth_seasons(cfg, 2))
    full = plan_migration(cfg, facts, tiers={tier})
    assert sorted({s.season for s in short.seasons if s.league_id == lid}) == [cfg.current_season - 2, cfg.current_season - 1, cfg.current_season]
    assert short.requests < full.requests


def test_the_option_is_on_plan_capacity_and_seed() -> None:
    """The subcommands are built inside main(); the source is the contract the owner guide relies on."""
    src = Path(cli.__file__).read_text(encoding="utf-8")
    assert src.count('"--depth"') == 1 and 'for name in ("plan", "capacity", "seed")' in src
