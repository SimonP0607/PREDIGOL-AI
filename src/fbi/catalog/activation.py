"""Apply config/competitions.yaml to core.competitions.is_tracked.

``known`` (a row exists) and ``active_for_ingestion`` (is_tracked = true) are
different things. The importer only ever produces the first; this module is
the only writer of the second, and it reads a file a human edited.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg
import structlog
import yaml
from psycopg.rows import tuple_row

from fbi.core.errors import ConfigError

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
