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


def test_the_shipped_config_enables_the_pilot_and_at_most_the_live_cycle_test() -> None:
    """The free plan is 100 requests/day and one Premier League matchday costs
    about 60-70: two leagues that play on the same days do not fit. The only
    second league allowed is the temporary live-cycle test that runs while the
    Premier League is on its international break (Segunda Division, 141), and
    it has to say so - the test keeps a second league from appearing by
    accident, or staying without a reason."""
    toggles = activation.load_config(Path(__file__).resolve().parents[2] / "config" / "competitions.yaml")
    assert len(toggles) == 10
    enabled = [t.league_id for t in toggles if t.enabled]
    assert enabled[:1] == [39] and set(enabled) <= {39, 141}, f"unexpected enabled leagues: {enabled}"
    assert all(t.note for t in toggles if t.enabled), "an enabled league must say why"
    assert all("live-cycle test" in (t.note or "") for t in toggles if t.enabled and t.league_id != 39)
