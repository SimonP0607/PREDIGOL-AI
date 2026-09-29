"""Choose which competitions to migrate, from the provider's own coverage flags.

    python -m scripts.select_competitions                 # the reasoned selection
    python -m scripts.select_competitions --json
    python -m scripts.select_competitions --write-config  # rewrite the tiers block
    python -m scripts.select_competitions --excluded      # and why each was left out

Reads raw.league_coverage - already in the database from one /leagues call - so it
costs NO provider request. A competition is selected on the depth of its FULL DETAIL
coverage (events + line-ups + fixture statistics + player statistics), because that
is the only combination the models can use; a season with fixtures and no statistics
is a scoreline, not a dataset. Everything excluded is listed with the count that
excluded it.

Exit status: 0 good, 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import psycopg
import yaml

from fbi.core.config import settings
from fbi.core.logging import configure as configure_logging
from fbi.migration.selection import MIN_FULL_DETAIL_SEASONS, select_competitions

REPO = Path(__file__).resolve().parents[1]
CONFIG = REPO / "config" / "migration.yaml"

TIER_NAMES = {
    1: "Reference set: top-5 European leagues and the Champions League",
    2: "Deep coverage: 8+ seasons with events, line-ups and both statistics blocks",
    3: "Solid coverage: 5-7 such seasons",
    4: "Usable coverage: 3-4 such seasons",
}


def _fixtures_estimate(seasons_listed: int, league_type: str | None) -> int:
    """A planning estimate only. The fixtures_season unit replaces it with the
    provider's real count before any detail unit is created, so this never decides
    what is fetched - only what the plan SAYS it will cost."""
    return 240 if league_type == "Cup" else 380


def main() -> int:
    configure_logging(settings.runtime.log_level)
    parser = argparse.ArgumentParser(prog="select_competitions", description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--excluded", action="store_true")
    parser.add_argument("--write-config", action="store_true")
    parser.add_argument("--min-detail", type=int, default=MIN_FULL_DETAIL_SEASONS)
    args = parser.parse_args()

    with psycopg.connect(settings.database.psycopg_url) as conn:
        report = select_competitions(conn)

    if args.json:
        print(json.dumps(report.as_dict(), indent=2))
        return 0

    by_tier = report.by_tier()
    print(f"{len(report.candidates)} competition(s) evaluated from the provider's own coverage")
    for tier, cs in by_tier.items():
        seasons = sum(c.full_detail_seasons for c in cs)
        print(f"  tier {tier}: {len(cs):>3} competition(s), {seasons:>4} season(s) with full detail"
              f"   {TIER_NAMES.get(tier, '')}")
    print(f"  selected  : {len(report.selected)}")
    print(f"  excluded  : {len(report.excluded)} (fewer than {args.min_detail} seasons of full detail,"
          " or no current season)")
    print(f"  league-seasons worth requesting: {report.league_seasons_to_migrate}")

    if args.excluded:
        print("\nExcluded, with the reason:")
        for c in sorted(report.excluded, key=lambda c: -c.seasons_listed)[:40]:
            print(f"  {c.provider_league_id:>5} {(c.name or '')[:34]:<34} {(c.country or '')[:16]:<16} "
                  f"{c.reason}")

    if not args.write_config:
        print("\nadd --write-config to write these tiers into config/migration.yaml")
        return 0

    raw = yaml.safe_load(CONFIG.read_text())
    raw["tiers"] = {
        tier: {
            "name": TIER_NAMES.get(tier, f"Tier {tier}"),
            "selected_because": (
                "computed by scripts.select_competitions from raw.league_coverage: "
                "depth of seasons where events, line-ups, fixture statistics and player "
                "statistics are ALL covered"
            ),
            "competitions": [
                {
                    "league_id": c.provider_league_id,
                    "name": f"{c.name} ({c.country})" if c.country else c.name,
                    "fixtures": _fixtures_estimate(c.seasons_listed, c.league_type),
                    "full_detail_seasons": c.full_detail_seasons,
                    "seasons_listed": c.seasons_listed,
                    "oldest": c.oldest_season,
                    "newest": c.newest_season,
                }
                for c in cs
            ],
        }
        for tier, cs in by_tier.items()
    }
    CONFIG.write_text(yaml.safe_dump(raw, sort_keys=False, allow_unicode=True, width=120))
    print(f"\nwrote {len(report.selected)} competition(s) in {len(by_tier)} tier(s) to {CONFIG}")
    print("review the diff, then: python -m scripts.migration plan --tiers 1,2,3,4")
    return 0


if __name__ == "__main__":
    sys.exit(main())
