"""EA-008: how well each current competition season records each statistic, measured read only, as JSON for a reviewed commit.

    python -m scripts.stats_coverage > src/fbi/stats/stats_coverage.json

For every competition season the nightly pass reads (``fbi.stats.data.seasons``): its finished matches and, per metric of the team
documents and of the players' templates, the share of the team-matches (appearances) that report it, and whether that share reaches
the threshold the documents publish at (``fbi.stats.team.COVERAGE``). The documents apply the same threshold themselves, every night;
this file is the record a reviewer reads. Reads only; asks the provider nothing.
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from typing import Any

import psycopg

from fbi.core.config import settings
from fbi.stats import data as sd
from fbi.stats import job
from fbi.stats import player as sp
from fbi.stats import team as st


def measure(conn: psycopg.Connection[Any]) -> dict[str, Any]:
    out = []
    for season in sd.seasons(conn, min_matches=job.MIN_MATCHES):
        data = sd.load_season(conn, season)
        team = st.coverage(data)
        players = sp.coverage(data.players)
        out.append({
            "competition_season_id": season.id, "competition": season.competition_name, "country": season.country,
            "season": season.season, "matches": len(data.matches), "player_lines": len(data.players),
            "team": {k: {"share": v, "publishable": v >= st.COVERAGE} for k, v in sorted(team.items())},
            "players": {k: {"share": v, "publishable": v >= sp.COVERAGE} for k, v in sorted(players.items())},
        })
    return {"version": "stats-coverage-v1", "measured_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
            "threshold": st.COVERAGE, "seasons": out}


def main() -> int:
    with psycopg.connect(settings.database.psycopg_url.replace("postgresql+psycopg://", "postgresql://")) as conn:
        conn.read_only = True
        json.dump(measure(conn), sys.stdout, ensure_ascii=False, indent=1)
        sys.stdout.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
