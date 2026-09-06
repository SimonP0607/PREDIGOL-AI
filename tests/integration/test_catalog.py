"""Importer writes are idempotent, and activation is the only writer of is_tracked."""

from __future__ import annotations

from pathlib import Path

import psycopg
import pytest

from fbi.catalog import activation, legacy_import
from fbi.catalog.activation import CompetitionToggle
from fbi.catalog.legacy_import import CompetitionRow, MigrationReport
from fbi.core.errors import ConfigError

ROWS = [
    CompetitionRow(39, "Premier League", "England", "league", "club", "domestic_league", 1.0, 1, 2025, True),
    CompetitionRow(294, "FA Cup", "England", "cup", "club", "domestic_cup", 0.4, 4, 2025, True),
]
BOOKS = [(8, "Bet365"), (4, "Pinnacle")]


@pytest.fixture()
def catalog(db: psycopg.Connection) -> psycopg.Connection:
    report = MigrationReport(dry_run=False)
    legacy_import.write(db, ROWS, BOOKS, report)
    return db


def _count(conn: psycopg.Connection, sql: str) -> int:
    with conn.cursor() as cur:
        cur.execute(sql)
        row = cur.fetchone()
        assert row is not None
        return int(row[0])


def test_write_is_idempotent(catalog: psycopg.Connection) -> None:
    before = _count(catalog, "SELECT count(*) FROM core.competitions")
    legacy_import.write(catalog, ROWS, BOOKS, MigrationReport(dry_run=False))
    assert _count(catalog, "SELECT count(*) FROM core.competitions") == before
    assert _count(catalog, "SELECT count(*) FROM core.competition_seasons WHERE season = 2025") >= 2
    assert _count(catalog, "SELECT count(*) FROM market.markets") == 4


def test_the_importer_never_activates_anything(catalog: psycopg.Connection) -> None:
    assert _count(catalog, "SELECT count(*) FROM core.competitions WHERE provider_league_id IN (39,294) AND is_tracked") == 0


def test_activation_flips_only_what_the_config_says(catalog: psycopg.Connection) -> None:
    diff = activation.apply(
        catalog,
        [CompetitionToggle(39, True, None), CompetitionToggle(294, False, None), CompetitionToggle(4242, True, None)],
        dry_run=False,
    )
    assert diff.enabled == [39]
    assert diff.unknown == [4242], "a league not in the catalogue is reported, never created"
    assert 39 in activation.active_league_ids(catalog)
    assert 294 not in activation.active_league_ids(catalog)


def test_a_league_dropped_from_the_config_is_disabled(catalog: psycopg.Connection) -> None:
    activation.apply(catalog, [CompetitionToggle(39, True, None)], dry_run=False)
    diff = activation.apply(catalog, [CompetitionToggle(294, True, None)], dry_run=False)
    assert diff.disabled == [39] and diff.enabled == [294]


def test_dry_run_changes_nothing(catalog: psycopg.Connection) -> None:
    diff = activation.apply(catalog, [CompetitionToggle(39, True, None)], dry_run=True)
    assert diff.enabled == [39]
    assert activation.active_league_ids(catalog) == []


def test_config_file_is_validated(tmp_path: Path) -> None:
    bad = tmp_path / "c.yaml"
    bad.write_text("provider: api_football\ncompetitions:\n  - league_id: 39\n  - league_id: 39\n")
    with pytest.raises(ConfigError, match="twice"):
        activation.load_config(bad)
    good = tmp_path / "g.yaml"
    good.write_text("provider: api_football\ncompetitions:\n  - league_id: 39\n    enabled: true\n  - league_id: 140\n")
    toggles = activation.load_config(good)
    assert [(t.league_id, t.enabled) for t in toggles] == [(39, True), (140, False)]


def test_the_shipped_config_parses_and_is_all_off_by_default() -> None:
    toggles = activation.load_config(Path(__file__).resolve().parents[2] / "config" / "competitions.yaml")
    assert len(toggles) == 9
    assert not any(t.enabled for t in toggles), "the pilot is chosen at run time, not shipped enabled"
