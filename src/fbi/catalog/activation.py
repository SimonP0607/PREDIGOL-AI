"""Apply config/competitions.yaml to core.competitions.is_tracked.

``known`` (a row exists) and ``active_for_ingestion`` (is_tracked = true) are
different things. The importer only ever produces the first; this module is
the only writer of the second, and it reads a file a human edited.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
import structlog
import yaml
from psycopg.rows import tuple_row

from fbi.core.errors import ConfigError
from fbi.providers.base import SeasonRef

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class CompetitionToggle:
    league_id: int
    enabled: bool
    note: str | None


@dataclass(frozen=True)
class ActivationDiff:
    enabled: list[int]
    disabled: list[int]
    unknown: list[int]
    unchanged: int

    @property
    def is_noop(self) -> bool:
        return not self.enabled and not self.disabled


def load_config(path: Path) -> list[CompetitionToggle]:
    raw: Any = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or raw.get("provider") != "api_football":
        raise ConfigError(f"{path}: expected a mapping with provider: api_football")
    items = raw.get("competitions")
    if not isinstance(items, list):
        raise ConfigError(f"{path}: 'competitions' must be a list")
    toggles: list[CompetitionToggle] = []
    seen: set[int] = set()
    for item in items:
        if not isinstance(item, dict) or "league_id" not in item:
            raise ConfigError(f"{path}: every entry needs a league_id")
        lid = int(item["league_id"])
        if lid in seen:
            raise ConfigError(f"{path}: league_id {lid} listed twice")
        seen.add(lid)
        toggles.append(CompetitionToggle(lid, bool(item.get("enabled", False)), item.get("note")))
    return toggles


def apply(conn: psycopg.Connection, toggles: list[CompetitionToggle], *, dry_run: bool) -> ActivationDiff:
    """Compute and (unless dry_run) write the diff. Does NOT commit: the caller
    owns the transaction, which is what keeps this testable and composable."""
    wanted = {t.league_id: t.enabled for t in toggles}
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT provider_league_id, is_tracked FROM core.competitions")
        current = {int(a): bool(b) for a, b in cur.fetchall()}

    unknown = sorted(lid for lid in wanted if lid not in current)
    enable = sorted(lid for lid, on in wanted.items() if on and lid in current and not current[lid])
    disable = sorted(
        lid for lid, on in current.items() if on and (lid not in wanted or not wanted[lid])
    )
    unchanged = sum(1 for lid in wanted if lid in current and current[lid] == wanted[lid])

    if not dry_run and (enable or disable):
        with conn.cursor() as cur:
            if enable:
                cur.execute(
                    "UPDATE core.competitions SET is_tracked = true, updated_at = now() "
                    "WHERE provider_league_id = ANY(%s)",
                    (enable,),
                )
            if disable:
                cur.execute(
                    "UPDATE core.competitions SET is_tracked = false, updated_at = now() "
                    "WHERE provider_league_id = ANY(%s)",
                    (disable,),
                )
    log.info("activation.applied", dry_run=dry_run, enabled=enable, disabled=disable, unknown=unknown)
    return ActivationDiff(enabled=enable, disabled=disable, unknown=unknown, unchanged=unchanged)


def active_league_ids(conn: psycopg.Connection) -> list[int]:
    """The ONLY way the rest of the system learns which leagues are active."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT provider_league_id FROM core.competitions WHERE is_tracked ORDER BY 1")
        return [int(r[0]) for r in cur.fetchall()]


@dataclass(frozen=True)
class SeasonUpdate:
    provider_league_id: int
    name: str
    was_current: int | None
    now_current: int | None
    has_odds: bool
    start_date: str | None
    end_date: str | None
    seasons_seen: int
    seasons_written: int = 0
    """Rows upserted into core.competition_seasons. Every season the provider
    listed, not only the current one - which is what this used to be."""
    without_fixtures: int = 0
    """Seasons the provider lists and says have no fixture list. Not a gap in our
    backfill: nothing to fetch."""


def refresh_seasons(
    conn: psycopg.Connection, refs: Sequence[SeasonRef], *, dry_run: bool
) -> list[SeasonUpdate]:
    """Correct ``core.competition_seasons`` from what the provider says today.

    Our catalogue came from a backup, so ``is_current`` is wrong by one whole
    season every August. Nothing else in the platform can fix that, which means
    a pilot would query a season that ended months ago and silently find no
    fixtures. This is the only writer of ``is_current`` on seasons.
    """
    by_league: dict[int, list[SeasonRef]] = {}
    for ref in refs:
        by_league.setdefault(ref.provider_league_id, []).append(ref)

    updates: list[SeasonUpdate] = []
    for league_id, seasons in sorted(by_league.items()):
        with conn.cursor(row_factory=tuple_row) as cur:
            cur.execute(
                "SELECT id, name FROM core.competitions WHERE provider_league_id = %s", (league_id,)
            )
            found = cur.fetchone()
            if found is None:
                log.warning("refresh_seasons.unknown_competition", league=league_id)
                continue
            competition_id, name = int(found[0]), str(found[1])
            cur.execute(
                "SELECT season FROM core.competition_seasons WHERE competition_id = %s AND is_current",
                (competition_id,),
            )
            previous = cur.fetchone()
            was = int(previous[0]) if previous else None

        current = next((s for s in seasons if s.is_current), None)
        without_fixtures = sum(1 for s in seasons if s.has_fixtures is False)
        update = SeasonUpdate(
            provider_league_id=league_id,
            name=name,
            was_current=was,
            now_current=current.season if current else None,
            has_odds=bool(current and current.has_odds),
            start_date=current.start_date if current else None,
            end_date=current.end_date if current else None,
            seasons_seen=len(seasons),
            seasons_written=0 if dry_run else len(seasons),
            without_fixtures=without_fixtures,
        )
        updates.append(update)
        if dry_run:
            continue

        # EVERY season the provider lists, not only the current one. A season we
        # have no row for cannot be planned against, cannot carry fixtures, and
        # cannot be reported as "known and not fetched": it is simply invisible.
        with conn.cursor() as cur:
            for s in sorted(seasons, key=lambda r: r.season):
                cur.execute(
                    "INSERT INTO core.competition_seasons (competition_id, season, start_date, end_date, "
                    " is_current, has_odds, has_fixtures, listed_at) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,now()) "
                    "ON CONFLICT (competition_id, season) DO UPDATE SET "
                    "  start_date = EXCLUDED.start_date, end_date = EXCLUDED.end_date, "
                    "  is_current = EXCLUDED.is_current, has_odds = EXCLUDED.has_odds, "
                    "  has_fixtures = EXCLUDED.has_fixtures, listed_at = EXCLUDED.listed_at",
                    (competition_id, s.season, s.start_date, s.end_date, s.is_current, s.has_odds,
                     s.has_fixtures),
                )
            # Exactly one current season per competition. The provider may list
            # none as current mid-transition; then nothing is marked current
            # rather than the wrong thing being left behind.
            if current is not None:
                cur.execute(
                    "UPDATE core.competition_seasons SET is_current = false "
                    "WHERE competition_id = %s AND season <> %s AND is_current",
                    (competition_id, current.season),
                )
    log.info("refresh_seasons.done", dry_run=dry_run, leagues=len(updates))
    return updates
