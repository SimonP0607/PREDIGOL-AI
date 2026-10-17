"""Leagues/seasons verdicts and the field inventory of the data truth audit V2."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from fbi.truth.v2 import fields as fl
from fbi.truth.v2 import leagues as lg


def api_league(lid: int, type_: str, country: str, seasons: list[tuple[int, bool, str, str]]) -> dict[str, Any]:
    return {"league": {"id": lid, "type": type_}, "country": {"name": country},
            "seasons": [{"year": y, "current": c, "start": s, "end": e} for y, c, s, e in seasons]}


COMP = {"provider_league_id": 39, "name": "Premier League", "type": "league", "country": "England"}


def season(year: int, current: bool, fixtures: int = 380, start: str = "2026-08-22",
           end: str = "2027-05-23") -> dict[str, Any]:
    return {"season": year, "is_current": current, "start_date": date.fromisoformat(start),
            "end_date": date.fromisoformat(end), "fixtures": fixtures}


def test_a_matching_competition_has_no_label() -> None:
    item = api_league(39, "League", "England", [(2025, False, "2025-08-15", "2026-05-24"),
                                                (2026, True, "2026-08-22", "2027-05-23")])
    v = lg.judge(COMP, item, [season(2025, False, start="2025-08-15", end="2026-05-24"), season(2026, True)])
    assert v.labels == []


def test_last_season_still_current_is_stale_current_season() -> None:
    item = api_league(39, "League", "England", [(2025, False, "2025-08-15", "2026-05-24"),
                                                (2026, True, "2026-08-22", "2027-05-23")])
    v = lg.judge(COMP, item, [season(2025, True, start="2025-08-15", end="2026-05-24"), season(2026, False)])
    assert "STALE_CURRENT_SEASON" in v.labels


def test_type_country_and_unmigrated_seasons_are_labelled() -> None:
    item = api_league(39, "Cup", "Wales", [(2019, False, "2019-08-01", "2020-05-01"),
                                           (2026, True, "2026-08-22", "2027-05-23")])
    v = lg.judge(COMP, item, [season(2019, False, fixtures=0), season(2026, True)])
    assert {"WRONG_TYPE", "WRONG_COUNTRY", "SEASON_NOT_MIGRATED"} <= set(v.labels)
    assert lg.judge(COMP, None, []).labels == ["STALE_ENTITY"]


def test_duplicate_competitions_share_a_folded_name_and_country() -> None:
    comps = [{"provider_league_id": 1, "name": "Copa Perú", "country": "Peru"},
             {"provider_league_id": 2, "name": "Copa Peru", "country": "Peru"},
             {"provider_league_id": 3, "name": "Copa Peru", "country": "Chile"}]
    assert lg.duplicates(comps) == [[1, 2]]


def test_the_inventory_classifies_every_path(monkeypatch: pytest.MonkeyPatch) -> None:
    body = {"response": [{"fixture": {"id": 1, "referee": "A. Ref", "timezone": "UTC", "attendance": 41000},
                          "teams": {"home": {"id": 5, "winner": True}},
                          "players": [{"players": [{"statistics": [{"games": {"minutes": 90}, "offsides": None,
                                                                     "new_metric": 3}]}]}]}]}
    monkeypatch.setitem(fl.REGISTRY["/fixtures"], "fixture.attendance", "useful:crowd size (a hypothetical field)")
    rows = {r.path: r for r in fl.inventory("/fixtures", [body], used_columns={"minutes"})}
    assert rows["fixture.id"].klass == "stored"
    assert rows["fixture.referee"].klass == "stored", "kept in core.fixture_facts since 4 Oct 2026"
    assert rows["fixture.attendance"].klass == "DROPPED_USEFUL_FIELD" and rows["fixture.attendance"].present == 1
    assert rows["fixture.timezone"].klass == "INTENTIONALLY_IGNORED"
    assert rows["players[].players[].statistics[].new_metric"].klass == "UNSUPPORTED_FIELD"
    assert rows["players[].players[].statistics[].games.minutes"].used is True
    assert rows["players[].players[].statistics[].offsides"].present == 0
    keys = {e.key for e in fl.evidence(list(rows.values()))}
    assert {"normalization:DROPPED_USEFUL_FIELD", "normalization:UNSUPPORTED_FIELD"} <= keys


def test_a_golden_season_passes_only_when_every_part_agrees() -> None:
    from fbi.truth.v2.golden import GoldenSeason, evidence

    g = GoldenSeason(39, 2024, "Premier League", fixtures_api=380, fixtures_db=380, fixtures_checked=380,
                     fixtures_matched=380, results_checked=380, results_matched=380, table_rows=20, table_ok=20,
                     external_rows=380, external_matched=380, external_score_disagree=0, external_other=0)
    assert g.verdict == "GOLDEN_VALIDATED" and g.score == 1.0 and evidence([g]) == []
    g.external_matched, g.external_score_disagree = 376, 4
    assert g.verdict == "NEEDS_REVIEW"
    assert [e.issue_type for e in evidence([g])] == ["RESULT_MISMATCH"]
    assert GoldenSeason(2, 2024).verdict == "NOT_CHECKED"
