"""The team page's record says its scope: the domestic league's season first, every competition of the
campaign next, the lifetime figure last and labelled (data truth audit V2, PRODUCT_SCOPE)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fbi.api.services.catalog import team_record_sections

T = datetime(2026, 9, 20, tzinfo=UTC)


def row(comp: str, kind: str, season: int, played: int, won: int, last: datetime) -> dict[str, Any]:
    return {"competition": comp, "competition_type": kind, "season": season, "played": played, "won": won,
            "drawn": 0, "lost": played - won, "goals_for": won * 2, "goals_against": played - won,
            "first": last - timedelta(days=40), "last": last}


def test_the_headline_is_the_domestic_league_season_not_everything() -> None:
    rows = [row("UEFA Champions League", "cup", 2026, 1, 1, T - timedelta(days=10)),
            row("Premier League", "league", 2026, 5, 5, T),
            row("Premier League", "league", 2025, 38, 23, T - timedelta(days=130)),
            row("FA Cup", "cup", 2024, 6, 6, T - timedelta(days=700))]
    head, campaign, lifetime = team_record_sections(rows)
    assert head.data is not None and (head.data.competition, head.data.season, head.data.played) == \
        ("Premier League", 2026, 5)
    assert [(r.competition, r.season) for r in campaign.data or []] == \
        [("UEFA Champions League", 2026), ("Premier League", 2026), ("Premier League", 2025)]
    assert lifetime.data is not None and lifetime.data.scope == "all" and lifetime.data.played == 50
    assert lifetime.data.competitions == 3


def test_a_national_side_without_a_league_gets_its_latest_competition() -> None:
    head, _, _ = team_record_sections([row("Friendlies", "cup", 2026, 6, 2, T),
                                      row("World Cup", "cup", 2026, 5, 3, T - timedelta(days=80))])
    assert head.data is not None and head.data.competition == "Friendlies"


def test_no_result_no_record() -> None:
    head, campaign, lifetime = team_record_sections([])
    assert head.data is None and campaign.data == [] and lifetime.data is None
