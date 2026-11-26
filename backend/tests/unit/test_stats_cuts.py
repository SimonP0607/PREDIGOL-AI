"""RP-6.3: the team at home and away, the goals of each half and a player's rates per 90 are read from the SAME documents, each with its own
sample; one under the minimum is marked insufficient and keeps its figures; the cut by rival strength says it is not in the documents; a
player's cut carries no forecast."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from fbi.stats import cuts
from fbi.stats import reading as rd

NOW = datetime(2026, 11, 26, 12, tzinfo=UTC)


def trend(key: str, hits: int, n: int, league: int) -> dict[str, Any]:
    pct = round(100 * hits / n)
    return {"key": key, "family": "goles", "rule_key": "goals_ft@v1", "line": 2.5, "hits": hits, "n": n, "pct": pct,
            "wilson_low": max(0, pct - 20), "wilson_high": min(100, pct + 20), "league_pct": league, "deviation_pts": 0, "fixture_ids": []}


def doc(context: str, sample: int, *, halves: Any = None, kind: str = "team", body: dict[str, Any] | None = None) -> rd.Document:
    base: dict[str, Any] = {"figures": [{"key": "goals_for", "unit": "por_partido", "better": "high", "value": 1.6, "matches_with_data": sample,
                                         "percentile": 70, "league_value": 1.4}],
                            "trends": {"items": [trend("over_2_5", 7, sample, 55)] if sample else []}}
    if halves is not None:
        base["halves"] = halves
    base.update(body or {})
    return rd.document_of({"kind": kind, "entity_id": 9, "competition_season_id": 7, "scope": "season", "context": context,
                           "calc_version": "stats-docs-v1", "sample": sample, "doc": base, "computed_at": NOW})


HALVES = {"goals_for_1h": 0.6, "goals_against_1h": 0.5, "goals_for_2h": 1.0, "goals_against_2h": 0.7, "matches_with_data": 18}


def test_home_and_away_are_cuts_of_their_own_documents_with_their_own_sample() -> None:
    c = cuts.team_cuts({"all": doc("all", 20, halves=HALVES), "home": doc("home", 10), "away": doc("away", 10)})
    assert (c.home.name, c.home.sample, c.home.state) == ("home", 10, "ok")
    assert (c.away.name, c.away.sample, c.away.state) == ("away", 10, "ok")
    assert c.home.document_id != c.away.document_id and c.home.document_id is not None
    assert c.home.values["goals_for"] == 1.6 and c.home.facts and c.home.facts[0].n == 10


def test_a_cut_under_the_minimum_is_insufficient_and_keeps_its_figures() -> None:
    c = cuts.team_cuts({"all": doc("all", 20, halves=HALVES), "home": doc("home", 2), "away": doc("away", 9)})
    assert c.home.state == cuts.INSUFFICIENT and c.home.sample == 2 and c.home.values["goals_for"] == 1.6
    assert c.away.state == cuts.OK
    assert cuts.available([c.home, c.away, c.halves]) == 2


def test_a_context_with_no_document_is_not_invented() -> None:
    c = cuts.team_cuts({"all": doc("all", 20, halves=HALVES)})
    assert c.home.state == "sin_documento" and c.home.sample == 0 and c.home.values == {}


def test_the_halves_come_from_the_documents_block_and_count_the_matches_with_both_halves() -> None:
    c = cuts.team_cuts({"all": doc("all", 20, halves=HALVES)})
    assert c.halves.sample == 18 and c.halves.state == "ok"
    assert c.halves.values == {"goals_for_1h": 0.6, "goals_against_1h": 0.5, "goals_for_2h": 1.0, "goals_against_2h": 0.7}
    short = cuts.halves_cut(doc("all", 20, halves={**HALVES, "matches_with_data": 2}))
    assert short.state == cuts.INSUFFICIENT and short.sample == 2


def test_halves_the_document_does_not_publish_are_sin_datos_with_the_reason() -> None:
    c = cuts.halves_cut(doc("all", 20, halves={"missing_reason": "sin_cobertura"}))
    assert (c.state, c.reason, c.sample) == ("sin_datos", "sin_cobertura", 0)
    assert cuts.halves_cut(doc("all", 20)).state == "sin_datos"


def test_the_cut_by_rival_strength_says_it_is_not_in_the_documents() -> None:
    c = cuts.team_cuts({"all": doc("all", 20, halves=HALVES)})
    assert (c.rival_strength.state, c.rival_strength.reason) == ("sin_datos", cuts.NOT_IN_DOCUMENTS)


PLAYER = {"appearances": 12, "starts": 9, "minutes": 900, "nineties": 10.0,
          "figures": [{"key": "shots_per90", "unit": "por_90", "better": "high", "value": 2.4, "matches_with_data": 12, "percentile": 80,
                       "league_value": 1.8},
                      {"key": "tackles_per90", "unit": "por_90", "better": "high", "value": {"missing_reason": "sin_cobertura"},
                       "matches_with_data": 0, "percentile": {"missing_reason": "sin_cobertura"}, "league_value": 1.0},
                      {"key": "goals", "unit": "por_partido", "better": "high", "value": 0.3, "matches_with_data": 12, "percentile": 60,
                       "league_value": 0.2}]}


def test_a_player_has_minutes_starts_share_and_only_his_rates_per_90() -> None:
    p = cuts.player_rates(doc("all", 12, kind="player", body=PLAYER))
    assert (p.appearances, p.starts, p.minutes, p.start_share) == (12, 9, 900, 0.75)
    assert p.rates == {"shots_per90": 2.4}, "a figure with no data is absent, never zero; a per-match figure is not a rate per 90"
    assert p.cut.state == "ok" and p.cut.sample == 900


def test_a_player_under_the_minutes_is_insufficient_and_never_carries_a_forecast() -> None:
    p = cuts.player_rates(doc("all", 2, kind="player", body={**PLAYER, "minutes": 120, "appearances": 2, "starts": 1}))
    assert p.cut.state == cuts.INSUFFICIENT and p.cut.reason == "minutos_insuficientes" and p.start_share == 0.5
    assert p.forecast is None


def test_a_player_with_no_document_is_sin_documento() -> None:
    p = cuts.player_rates(rd.Document("no_document", "player", 9, 7, "season", "all"))
    assert p.cut.state == "sin_documento" and p.minutes == 0 and p.start_share is None
