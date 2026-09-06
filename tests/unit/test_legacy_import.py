"""The legacy knowledge importer decides row by row and says what it did."""

from __future__ import annotations

import polars as pl

from fbi.catalog.legacy_import import (
    CUP_ELO_WEIGHT,
    MigrationReport,
    load_bookmakers,
    merge_competitions,
)


def ctx(*rows: tuple[int, str, str, str, float]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "provider_league_id": [r[0] for r in rows],
            "league_name": [r[1] for r in rows],
            "country": [None] * len(rows),
            "entity_scope": [r[2] for r in rows],
            "competition_type": [r[3] for r in rows],
            "elo_weight": [r[4] for r in rows],
            "notes": [None] * len(rows),
        },
        schema={"provider_league_id": pl.Int32, "league_name": pl.String, "country": pl.String,
                "entity_scope": pl.String, "competition_type": pl.String, "elo_weight": pl.Float64, "notes": pl.String},
    )


def tracked(*rows: tuple[int, str, str, str, int, bool, int]) -> pl.DataFrame:
    return pl.DataFrame(
        {
            "provider_league_id": [r[0] for r in rows],
            "name": [r[1] for r in rows],
            "country": [r[2] for r in rows],
            "type": [r[3] for r in rows],
            "season": [r[4] for r in rows],
            "current": [r[5] for r in rows],
            "is_active": [True] * len(rows),
            "sync_tier": ["tier_1_daily"] * len(rows),
            "priority": [r[6] for r in rows],
            "market_winner": [True] * len(rows),
            "market_ou25": [True] * len(rows),
        }
    )


def test_a_curated_row_matching_the_provider_is_accepted_untouched() -> None:
    report = MigrationReport(dry_run=True)
    rows = merge_competitions(
        ctx((39, "Premier League", "club", "domestic_league", 1.0)),
        tracked((39, "Premier League", "England", "League", 2025, True, 1)),
        report,
    )
    assert len(rows) == 1
    assert rows[0].name == "Premier League" and rows[0].country == "England" and rows[0].format == "league"
    assert rows[0].tier == 1 and rows[0].season == 2025 and rows[0].season_is_current
    assert report.accepted["competition_context"] == 1
    assert report.transformed.get("competition_context", 0) == 0


def test_the_provider_name_replaces_the_legacy_placeholder_and_is_reported() -> None:
    report = MigrationReport(dry_run=True)
    rows = merge_competitions(
        ctx((103, "League 103", "club", "domestic_league", 1.0)),
        tracked((103, "Eliteserien", "Norway", "League", 2026, True, 5)),
        report,
    )
    assert rows[0].name == "Eliteserien"
    assert report.transformed["competition_context"] == 1
    change = report.rows[0].changes["name"]
    assert change["from"] == "League 103" and change["to"] == "Eliteserien"


def test_a_cup_mislabelled_as_league_is_corrected_with_the_legacy_rule_and_a_warning() -> None:
    """Ten legacy rows contradicted the provider. The provider's format is
    objective; the Elo weight follows the legacy's own documented rule for
    cups. Both changes are named, and the row is flagged for review."""
    report = MigrationReport(dry_run=True)
    rows = merge_competitions(
        ctx((294, "League 294", "club", "domestic_league", 1.0)),
        tracked((294, "FA Cup", "England", "Cup", 2025, True, 4)),
        report,
    )
    assert rows[0].format == "cup"
    assert rows[0].competition_type == "domestic_cup"
    assert rows[0].elo_weight == CUP_ELO_WEIGHT
    assert len(report.warnings) == 1 and "FA Cup" in report.warnings[0]
    assert set(report.rows[0].changes) == {"name", "competition_type", "elo_weight"}


def test_a_curated_cup_weight_is_left_alone() -> None:
    report = MigrationReport(dry_run=True)
    rows = merge_competitions(
        ctx((143, "Copa del Rey", "club", "domestic_cup", 0.4)),
        tracked((143, "Copa del Rey", "Spain", "Cup", 2025, True, 4)),
        report,
    )
    assert rows[0].elo_weight == 0.4 and rows[0].competition_type == "domestic_cup"
    assert not report.warnings


def test_a_placeholder_row_absent_from_the_provider_is_rejected_not_invented() -> None:
    report = MigrationReport(dry_run=True)
    rows = merge_competitions(ctx((251, "League 251", "club", "domestic_league", 1.0)), tracked(), report)
    assert rows == []
    assert report.rejected["competition_context"] == 1
    assert "placeholder" in report.rows[0].reason


def test_a_provider_row_without_curation_is_rejected_for_lack_of_knowledge() -> None:
    report = MigrationReport(dry_run=True)
    rows = merge_competitions(ctx(), tracked((999, "Mystery League", "X", "League", 2025, True, 8)), report)
    assert rows == []
    assert report.rejected["tracked_competitions"] == 1


def test_bookmakers_need_an_id_and_a_name() -> None:
    report = MigrationReport(dry_run=True)
    books = pl.DataFrame({"id": [1, 2, 3], "provider_bookmaker_id": [8, 0, 4], "name": ["Bet365", "Ghost", "  "]})
    out = load_bookmakers(books, report)
    assert out == [(8, "Bet365")]
    assert report.rejected["ref_bookmakers"] == 2


def test_the_report_renders_a_summary_table() -> None:
    report = MigrationReport(dry_run=True)
    merge_competitions(
        ctx((39, "Premier League", "club", "domestic_league", 1.0), (251, "League 251", "club", "domestic_league", 1.0)),
        tracked((39, "Premier League", "England", "League", 2025, True, 1)),
        report,
    )
    table = report.summary_table()
    assert "| competition_context | 2 | 1 | 0 | 1 |" in table
