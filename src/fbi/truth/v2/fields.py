"""What the provider sends that PrediGol drops: FIELD / API PRESENT / NORMALIZED / STORED / USED.

For each endpoint, a sample of stored RAW payloads (read from disk, never modified) is flattened to
JSON paths (list items as ``[]``) with how often each path carries a value. Each path is matched
against ``REGISTRY``: where our normalizers put it (``table.column``) or why they do not
(``ignore:<reason>``). A stored column counts as USED when the code that builds features, models,
picks or product pages names it.

Classes (the mandate's):

* stored                 - kept (and USED or not);
* INTENTIONALLY_IGNORED  - dropped on purpose: derivable, presentation (logos, photos), or held elsewhere;
* DROPPED_USEFUL_FIELD   - dropped although a feature, a market or a page could use it;
* UNSUPPORTED_FIELD      - no place for it in our schema and no decision taken (unmapped).
"""

from __future__ import annotations

import gzip
import json
import re
from collections import Counter
from collections.abc import Iterator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import psycopg

from fbi.truth.v2.ledger import Evidence

Rule = str
"""'core.table.column' (stored), 'ignore:<why>' (intentionally) or 'useful:<why>' (dropped, useful)."""

REGISTRY: dict[str, dict[str, Rule]] = {
    "/fixtures": {
        "fixture.id": "core.fixtures.provider_fixture_id",
        "fixture.date": "core.fixtures.kickoff_at",
        "fixture.timestamp": "ignore:same instant as fixture.date",
        "fixture.timezone": "ignore:requests are made in UTC",
        "fixture.referee": "core.fixture_facts.referee",
        "fixture.periods.first": "core.fixture_facts.first_half_at",
        "fixture.periods.second": "core.fixture_facts.second_half_at",
        "fixture.venue.id": "core.fixtures.venue_id",
        "fixture.venue.name": "core.venues.name",
        "fixture.venue.city": "core.venues.city",
        "fixture.status.short": "core.fixtures.status_short",
        "fixture.status.long": "ignore:label of status.short",
        "fixture.status.elapsed": "ignore:live minute (live tables keep their own)",
        "fixture.status.extra": "ignore:live added time",
        "league.id": "core.competitions.provider_league_id",
        "league.season": "core.competition_seasons.season",
        "league.round": "core.fixtures.round",
        "league.name": "ignore:catalogue (/leagues)",
        "league.country": "ignore:catalogue (/leagues)",
        "league.logo": "ignore:presentation",
        "league.flag": "ignore:presentation",
        "league.standings": "ignore:held per season by the /leagues coverage flag (raw.league_coverage.standings), "
                            "which the standings refresh reads",
        "teams.home.id": "core.fixtures.home_team_id",
        "teams.away.id": "core.fixtures.away_team_id",
        "teams.home.name": "ignore:catalogue (/teams)",
        "teams.away.name": "ignore:catalogue (/teams)",
        "teams.home.logo": "ignore:presentation",
        "teams.away.logo": "ignore:presentation",
        "teams.home.winner": "core.fixture_facts.home_winner",
        "teams.away.winner": "core.fixture_facts.away_winner",
        "goals.home": "core.fixture_results.goals_home",
        "goals.away": "core.fixture_results.goals_away",
        "score.halftime.home": "core.fixture_results.ht_goals_home",
        "score.halftime.away": "core.fixture_results.ht_goals_away",
        "score.fulltime.home": "core.fixture_results.ft_goals_home",
        "score.fulltime.away": "core.fixture_results.ft_goals_away",
        "score.extratime.home": "core.fixture_results.et_goals_home",
        "score.extratime.away": "core.fixture_results.et_goals_away",
        "score.penalty.home": "core.fixture_results.pen_home",
        "score.penalty.away": "core.fixture_results.pen_away",
        "events[].time.elapsed": "core.fixture_events.minute",
        "events[].time.extra": "core.fixture_events.extra_minute",
        "events[].team.id": "core.fixture_events.team_side",
        "events[].team.name": "ignore:catalogue",
        "events[].team.logo": "ignore:presentation",
        "events[].player.id": "core.fixture_events.provider_player_id",
        "events[].player.name": "core.fixture_events.player_name",
        "events[].assist.id": "core.fixture_events.provider_assist_id",
        "events[].assist.name": "core.fixture_events.assist_name",
        "events[].type": "core.fixture_events.event_type",
        "events[].detail": "core.fixture_events.detail",
        "events[].comments": "core.fixture_events.comments",
        "lineups[].team.id": "core.fixture_lineups.team_side",
        "lineups[].team.name": "ignore:catalogue",
        "lineups[].team.logo": "ignore:presentation",
        "lineups[].team.colors.player.primary": "ignore:shirt colours",
        "lineups[].team.colors.player.number": "ignore:shirt colours",
        "lineups[].team.colors.player.border": "ignore:shirt colours",
        "lineups[].team.colors.goalkeeper.primary": "ignore:shirt colours",
        "lineups[].team.colors.goalkeeper.number": "ignore:shirt colours",
        "lineups[].team.colors.goalkeeper.border": "ignore:shirt colours",
        "lineups[].formation": "core.fixture_lineups.formation",
        "lineups[].coach.id": "core.fixture_lineups.provider_coach_id",
        "lineups[].coach.name": "core.fixture_lineups.coach_name",
        "lineups[].coach.photo": "ignore:presentation",
        "lineups[].startXI[].player.id": "core.fixture_lineup_players.provider_player_id",
        "lineups[].startXI[].player.name": "core.fixture_lineup_players.player_name",
        "lineups[].startXI[].player.number": "core.fixture_lineup_players.shirt_number",
        "lineups[].startXI[].player.pos": "core.fixture_lineup_players.position",
        "lineups[].startXI[].player.grid": "core.fixture_lineup_players.grid",
        "lineups[].substitutes[].player.id": "core.fixture_lineup_players.provider_player_id",
        "lineups[].substitutes[].player.name": "core.fixture_lineup_players.player_name",
        "lineups[].substitutes[].player.number": "core.fixture_lineup_players.shirt_number",
        "lineups[].substitutes[].player.pos": "core.fixture_lineup_players.position",
        "lineups[].substitutes[].player.grid": "ignore:always null for substitutes",
        "statistics[].team.id": "core.fixture_team_stats.team_side",
        "statistics[].team.name": "ignore:catalogue",
        "statistics[].team.logo": "ignore:presentation",
        "statistics[].statistics[].type": "core.fixture_team_stats (one column per type: STAT_TYPES)",
        "statistics[].statistics[].value": "core.fixture_team_stats (one column per type: STAT_TYPES)",
        "players[].team.id": "core.fixture_player_stats.team_side",
        "players[].team.name": "ignore:catalogue",
        "players[].team.logo": "ignore:presentation",
        "players[].team.update": "ignore:payload stamp",
        "players[].players[].player.id": "core.fixture_player_stats.provider_player_id",
        "players[].players[].player.name": "core.fixture_player_stats.player_name",
        "players[].players[].player.photo": "ignore:presentation",
        "players[].players[].statistics[].games.minutes": "core.fixture_player_stats.minutes",
        "players[].players[].statistics[].games.number": "ignore:held by the line-up (shirt_number)",
        "players[].players[].statistics[].games.position": "core.fixture_player_extras.position_played",
        "players[].players[].statistics[].games.rating": "core.fixture_player_stats.rating",
        "players[].players[].statistics[].games.captain": "core.fixture_player_stats.is_captain",
        "players[].players[].statistics[].games.substitute": "core.fixture_player_stats.is_substitute",
        "players[].players[].statistics[].offsides": "core.fixture_player_extras.offsides",
        "players[].players[].statistics[].shots.total": "core.fixture_player_stats.shots_total",
        "players[].players[].statistics[].shots.on": "core.fixture_player_stats.shots_on",
        "players[].players[].statistics[].goals.total": "core.fixture_player_stats.goals",
        "players[].players[].statistics[].goals.conceded": "core.fixture_player_stats.goals_conceded",
        "players[].players[].statistics[].goals.assists": "core.fixture_player_stats.assists",
        "players[].players[].statistics[].goals.saves": "core.fixture_player_stats.saves",
        "players[].players[].statistics[].passes.total": "core.fixture_player_stats.passes_total",
        "players[].players[].statistics[].passes.key": "core.fixture_player_stats.passes_key",
        "players[].players[].statistics[].passes.accuracy": "core.fixture_player_stats.passes_accuracy_pct",
        "players[].players[].statistics[].tackles.total": "core.fixture_player_stats.tackles",
        "players[].players[].statistics[].tackles.blocks": "core.fixture_player_stats.blocks",
        "players[].players[].statistics[].tackles.interceptions": "core.fixture_player_stats.interceptions",
        "players[].players[].statistics[].duels.total": "core.fixture_player_stats.duels_total",
        "players[].players[].statistics[].duels.won": "core.fixture_player_stats.duels_won",
        "players[].players[].statistics[].dribbles.attempts": "core.fixture_player_stats.dribbles_attempts",
        "players[].players[].statistics[].dribbles.success": "core.fixture_player_stats.dribbles_success",
        "players[].players[].statistics[].dribbles.past": "core.fixture_player_extras.dribbled_past",
        "players[].players[].statistics[].fouls.drawn": "core.fixture_player_stats.fouls_drawn",
        "players[].players[].statistics[].fouls.committed": "core.fixture_player_stats.fouls_committed",
        "players[].players[].statistics[].cards.yellow": "core.fixture_player_stats.yellow_cards",
        "players[].players[].statistics[].cards.red": "core.fixture_player_stats.red_cards",
        "players[].players[].statistics[].penalty.won": "core.fixture_player_extras.penalties_won",
        "players[].players[].statistics[].penalty.commited": "core.fixture_player_extras.penalties_committed",
        "players[].players[].statistics[].penalty.scored": "core.fixture_player_stats.penalties_scored",
        "players[].players[].statistics[].penalty.missed": "core.fixture_player_stats.penalties_missed",
        "players[].players[].statistics[].penalty.saved": "core.fixture_player_extras.penalties_saved",
    },
    "/standings": {
        "league.id": "core.standings.competition_season_id", "league.season": "core.standings.competition_season_id",
        "league.name": "ignore:catalogue", "league.country": "ignore:catalogue", "league.logo": "ignore:presentation",
        "league.flag": "ignore:presentation",
        "league.standings[][].rank": "core.standings.rank",
        "league.standings[][].team.id": "core.standings.team_id",
        "league.standings[][].team.name": "ignore:catalogue", "league.standings[][].team.logo": "ignore:presentation",
        "league.standings[][].points": "core.standings.points",
        "league.standings[][].goalsDiff": "core.standings.goals_diff",
        "league.standings[][].group": "core.standings.group",
        "league.standings[][].form": "core.standings.form",
        "league.standings[][].status": "core.standings.zone_status",
        "league.standings[][].description": "core.standings.description",
        "league.standings[][].update": "core.standings.provider_updated_at",
        **{f"league.standings[][].{side}.{k}": f"core.standings.{'' if side == 'all' else side + '_'}{col}"
           for side in ("all", "home", "away")
           for k, col in (("played", "played"), ("win", "wins"), ("draw", "draws"), ("lose", "losses"),
                          ("goals.for", "goals_for"), ("goals.against", "goals_against"))},
    },
    "/injuries": {
        "player.id": "core.player_absences.provider_player_id", "player.name": "core.player_absences.player_name",
        "player.photo": "ignore:presentation", "player.type": "core.player_absences.absence_type",
        "player.reason": "core.player_absences.reason", "team.id": "core.player_absences.provider_team_id",
        "team.name": "ignore:catalogue", "team.logo": "ignore:presentation",
        "fixture.id": "core.player_absences.provider_fixture_id", "fixture.timezone": "ignore:UTC",
        "fixture.date": "ignore:held by the fixture", "fixture.timestamp": "ignore:held by the fixture",
        "league.id": "ignore:held by the fixture", "league.season": "ignore:held by the fixture",
        "league.name": "ignore:catalogue", "league.country": "ignore:catalogue", "league.logo": "ignore:presentation",
        "league.flag": "ignore:presentation",
    },
}


_COVERAGE = ("events", "lineups", "statistics_fixtures", "statistics_players")
REGISTRY.update({
    "/leagues": {
        "league.id": "core.competitions.provider_league_id", "league.name": "core.competitions.name",
        "league.type": "core.competitions.type", "league.logo": "core.competitions.logo_url",
        "country.name": "core.competitions.country", "country.code": "core.competitions.country_code",
        "country.flag": "core.competitions.flag_url",
        "seasons[].year": "core.competition_seasons.season", "seasons[].start": "core.competition_seasons.start_date",
        "seasons[].end": "core.competition_seasons.end_date", "seasons[].current": "core.competition_seasons.is_current",
        **{f"seasons[].coverage.fixtures.{k}": f"raw.league_coverage.{k}" for k in _COVERAGE},
        **{f"seasons[].coverage.{k}": f"raw.league_coverage.{k}" for k in
           ("standings", "players", "top_scorers", "top_assists", "top_cards", "injuries", "predictions", "odds")},
    },
    "/teams": {
        "team.id": "core.teams.provider_team_id", "team.name": "core.teams.name", "team.code": "core.teams.short_name",
        "team.country": "core.teams.country", "team.founded": "core.teams.founded",
        "team.national": "core.teams.is_national", "team.logo": "core.teams.logo_url",
        "venue.id": "core.venues.provider_venue_id", "venue.name": "core.venues.name",
        "venue.address": "core.venues.address", "venue.city": "core.venues.city",
        "venue.capacity": "core.venues.capacity", "venue.surface": "core.venues.surface",
        "venue.image": "ignore:presentation (the URL is media.api-sports.io/football/venues/{id}.png)",
    },
    "/players/profiles": {
        "player.id": "core.players.provider_player_id", "player.name": "core.players.name",
        "player.firstname": "core.players.firstname", "player.lastname": "core.players.lastname",
        "player.age": "ignore:derivable from player.birth.date at any date",
        "player.birth.date": "core.players.birth_date", "player.birth.place": "core.players.birth_place",
        "player.birth.country": "core.players.birth_country", "player.nationality": "core.players.nationality",
        "player.height": "core.players.height_cm", "player.weight": "core.players.weight_kg",
        "player.number": "ignore:held per team by /players/squads (core.squad_members.shirt_number)",
        "player.position": "core.players.position", "player.photo": "core.players.photo_url",
    },
    "/players/squads": {
        "team.id": "core.squad_members.team_id", "team.name": "ignore:catalogue", "team.logo": "ignore:presentation",
        "players[].id": "core.squad_members.provider_player_id", "players[].name": "core.squad_members.player_name",
        "players[].age": "core.squad_members.age", "players[].number": "core.squad_members.shirt_number",
        "players[].position": "core.squad_members.position", "players[].photo": "core.squad_members.photo_url",
    },
    "/odds": {
        "league.id": "ignore:held by the fixture", "league.name": "ignore:catalogue", "league.country": "ignore:catalogue",
        "league.logo": "ignore:presentation", "league.flag": "ignore:presentation", "league.season": "ignore:held by the fixture",
        "fixture.id": "market.odds_snapshots.fixture_id", "fixture.timezone": "ignore:UTC",
        "fixture.date": "ignore:held by the fixture", "fixture.timestamp": "ignore:held by the fixture",
        "update": "ignore:the provider's update stamp; our captured_at is the observation time",
        "bookmakers[].id": "market.odds_snapshots.bookmaker_id", "bookmakers[].name": "market.bookmakers.name",
        "bookmakers[].bets[].id": "market.odds_snapshots.market_key (the modelled bets; every bet id is catalogued in "
                                  "market.provider_markets, the rest of the prices stay in RAW)",
        "bookmakers[].bets[].name": "market.provider_markets.name",
        "bookmakers[].bets[].values[].value": "market.odds_snapshots.selection",
        "bookmakers[].bets[].values[].odd": "market.odds_snapshots.odds_decimal",
    },
    "/odds/live": {
        "fixture.id": "market.live_odds_snapshots.fixture_id",
        "fixture.status.long": "market.live_fixture_states.status_long",
        "fixture.status.elapsed": "market.live_fixture_states.elapsed_minute",
        "fixture.status.seconds": "market.live_fixture_states.elapsed_seconds",
        "league.id": "ignore:held by the fixture", "league.season": "ignore:held by the fixture",
        "teams.home.id": "ignore:held by the fixture", "teams.away.id": "ignore:held by the fixture",
        "teams.home.goals": "market.live_fixture_states.score_home", "teams.away.goals": "market.live_fixture_states.score_away",
        "status.stopped": "market.live_fixture_states.is_stopped", "status.blocked": "market.live_fixture_states.is_blocked",
        "status.finished": "market.live_fixture_states.is_finished",
        "update": "market.live_fixture_states.provider_updated_at",
        "odds[].id": "market.live_odds_snapshots.provider_bet_id", "odds[].name": "market.provider_markets.name",
        "odds[].values[].value": "market.live_odds_snapshots.selection",
        "odds[].values[].odd": "market.live_odds_snapshots.odds_decimal",
        "odds[].values[].handicap": "market.live_odds_snapshots.line",
        "odds[].values[].main": "market.live_odds_snapshots.is_main_line",
        "odds[].values[].suspended": "market.live_odds_snapshots.is_suspended",
    },
})
_PRED = "core.provider_predictions."
_LEAD = "core.season_leaders."
_LEADERS = {
    "player.id": _LEAD + "provider_player_id", "player.name": _LEAD + "player_name", "player.photo": _LEAD + "photo_url",
    "statistics[].team.id": _LEAD + "provider_team_id", "statistics[].team.name": _LEAD + "team_name",
    "statistics[].games.appearences": _LEAD + "appearances", "statistics[].games.minutes": _LEAD + "minutes",
    "statistics[].games.rating": _LEAD + "rating", "statistics[].goals.total": _LEAD + "goals",
    "statistics[].goals.assists": _LEAD + "assists", "statistics[].penalty.scored": _LEAD + "penalties_scored",
    "statistics[].cards.yellow": _LEAD + "yellow_cards", "statistics[].cards.yellowred": _LEAD + "yellowred_cards",
    "statistics[].cards.red": _LEAD + "red_cards",
}
REGISTRY.update({
    "/predictions": {
        "predictions.winner.id": _PRED + "winner_team_id", "predictions.winner.name": _PRED + "winner_name",
        "predictions.winner.comment": _PRED + "winner_comment", "predictions.win_or_draw": _PRED + "win_or_draw",
        "predictions.under_over": _PRED + "under_over", "predictions.goals.home": _PRED + "goals_home",
        "predictions.goals.away": _PRED + "goals_away", "predictions.advice": _PRED + "advice",
        "predictions.percent.home": _PRED + "percent_home", "predictions.percent.draw": _PRED + "percent_draw",
        "predictions.percent.away": _PRED + "percent_away",
    },
    "/fixtures/rounds": {"round": "core.season_rounds.round", "dates[]": "core.season_rounds.dates",
                         "": "core.season_rounds.round (current=true: core.season_current_round.rounds)"},
    **{f"/players/top{k}": _LEADERS for k in ("scorers", "assists", "yellowcards", "redcards")},
    "/coachs": {
        "id": "core.coach_profiles.provider_coach_id", "name": "core.coach_profiles.name",
        "firstname": "core.coach_profiles.firstname", "lastname": "core.coach_profiles.lastname",
        "age": "ignore:derivable from birth.date at any date", "birth.date": "core.coach_profiles.birth_date",
        "birth.place": "core.coach_profiles.birth_place", "birth.country": "core.coach_profiles.birth_country",
        "nationality": "core.coach_profiles.nationality", "height": "core.coach_profiles.height",
        "weight": "core.coach_profiles.weight", "photo": "core.coach_profiles.photo_url",
        "team.id": "core.coach_profiles.provider_team_id", "team.name": "ignore:catalogue (/teams)",
        "team.logo": "ignore:presentation", "career[].team.id": "core.coach_careers.provider_team_id",
        "career[].team.name": "core.coach_careers.team_name", "career[].team.logo": "ignore:presentation",
        "career[].start": "core.coach_careers.start_date", "career[].end": "core.coach_careers.end_date",
    },
    "/transfers": {
        "player.id": "core.player_transfers.provider_player_id", "player.name": "ignore:catalogue (/players/profiles)",
        "update": "core.player_transfers.provider_update_at", "transfers[].date": "core.player_transfers.transfer_date",
        "transfers[].type": "core.player_transfers.type", "transfers[].teams.in.id": "core.player_transfers.team_in_id",
        "transfers[].teams.in.name": "core.player_transfers.team_in_name",
        "transfers[].teams.out.id": "core.player_transfers.team_out_id",
        "transfers[].teams.out.name": "core.player_transfers.team_out_name",
        "transfers[].teams.in.logo": "ignore:presentation", "transfers[].teams.out.logo": "ignore:presentation",
    },
    "/sidelined": {
        "type": "core.person_sidelined.type", "start": "core.person_sidelined.start_date",
        "end": "core.person_sidelined.end_date", "id": "core.person_sidelined.provider_person_id",
        "sidelined[].type": "core.person_sidelined.type", "sidelined[].start": "core.person_sidelined.start_date",
        "sidelined[].end": "core.person_sidelined.end_date",
    },
    "/trophies": {
        "league": "core.person_trophies.league", "country": "core.person_trophies.country",
        "season": "core.person_trophies.season", "place": "core.person_trophies.place",
        "id": "core.person_trophies.provider_person_id", "trophies[].league": "core.person_trophies.league",
        "trophies[].country": "core.person_trophies.country", "trophies[].season": "core.person_trophies.season",
        "trophies[].place": "core.person_trophies.place",
    },
    "/countries": {"name": "core.countries.name", "code": "core.countries.code", "flag": "core.countries.flag_url"},
    "/odds/mapping": {
        "fixture.id": "market.odds_mapping_seen.provider_fixture_id",
        "league.id": "market.odds_mapping_seen.provider_league_id", "league.season": "market.odds_mapping_seen.season",
        "fixture.date": "market.odds_mapping_seen.fixture_date", "fixture.timestamp": "ignore:same instant as fixture.date",
        "update": "market.odds_mapping_seen.provider_update_at",
    },
    "/odds/bets": {"id": "market.provider_markets.provider_bet_id", "name": "market.provider_markets.name"},
    "/odds/live/bets": {"id": "market.provider_markets.provider_bet_id", "name": "market.provider_markets.name"},
    "/odds/bookmakers": {"id": "market.bookmakers.provider_bookmaker_id", "name": "market.bookmakers.name"},
})
_PSS = "core.player_season_stats."
_PLAYER_STATS = {
    "games.appearences": "appearances", "games.lineups": "lineups", "games.minutes": "minutes",
    "games.number": "shirt_number", "games.position": "position", "games.rating": "rating", "games.captain": "captain",
    "substitutes.in": "subs_in", "substitutes.out": "subs_out", "substitutes.bench": "subs_bench",
    "shots.total": "shots_total", "shots.on": "shots_on", "goals.total": "goals", "goals.conceded": "goals_conceded",
    "goals.assists": "assists", "goals.saves": "saves", "passes.total": "passes_total", "passes.key": "passes_key",
    "passes.accuracy": "passes_accuracy", "tackles.total": "tackles", "tackles.blocks": "blocks",
    "tackles.interceptions": "interceptions", "duels.total": "duels_total", "duels.won": "duels_won",
    "dribbles.attempts": "dribbles_attempts", "dribbles.success": "dribbles_success", "dribbles.past": "dribbled_past",
    "fouls.drawn": "fouls_drawn", "fouls.committed": "fouls_committed", "cards.yellow": "yellow_cards",
    "cards.yellowred": "yellowred_cards", "cards.red": "red_cards", "penalty.won": "penalties_won",
    "penalty.commited": "penalties_committed", "penalty.scored": "penalties_scored",
    "penalty.missed": "penalties_missed", "penalty.saved": "penalties_saved",
}
_TSS = "core.team_season_stats."
REGISTRY.update({
    "/players": {
        "player.id": _PSS + "provider_player_id",
        "statistics[].team.id": _PSS + "provider_team_id", "statistics[].league.id": _PSS + "provider_league_id",
        "statistics[].league.season": _PSS + "season",
        **{f"statistics[].{k}": _PSS + v for k, v in _PLAYER_STATS.items()},
    },
    "/teams/statistics": {
        "team.id": _TSS + "team_id", "form": _TSS + "form",
        **{f"fixtures.{k}.{side}": f"{_TSS}{c}_{side}" for k, c in
           (("played", "played"), ("wins", "wins"), ("draws", "draws"), ("loses", "loses")) for side in ("home", "away")},
        **{f"goals.{d}.average.{side}": f"{_TSS}goals_{d}_{side}" for d in ("for", "against") for side in ("home", "away")},
        **{f"goals.{d}.total.{side}": f"{_TSS}goals_{d}_total_{side}" for d in ("for", "against")
           for side in ("home", "away")},
        **{f"clean_sheet.{side}": f"{_TSS}clean_sheets_{side}" for side in ("home", "away")},
        **{f"failed_to_score.{side}": f"{_TSS}failed_to_score_{side}" for side in ("home", "away")},
        "penalty.scored.total": _TSS + "penalties_scored", "penalty.missed.total": _TSS + "penalties_missed",
    },
})
PREFIX: dict[str, tuple[tuple[str, Rule], ...]] = {
    "/fixtures": (
        ("lineups[].team.colors", "ignore:presentation (shirt colours, for a pitch graphic); kept in RAW"),
    ),
    "/fixtures/statistics": (
        ("statistics[].", "ignore:the full-match block arrives with /fixtures?ids= (core.fixture_team_stats)"),
        ("statistics_1h[].", "ignore:first-half statistics (half=true) are not requested on a schedule - one request "
                             "per match, ~200 a day; the contract probe confirmed the block"),
        ("statistics_2h[].", "ignore:second-half statistics (half=true) are not requested on a schedule - one request "
                             "per match, ~200 a day; the contract probe confirmed the block"),
        ("team.", "ignore:held by the fixture"),
    ),
    "/players": (
        ("player.", "ignore:the profile is held by /players/profiles (core.players)"),
        ("statistics[].team.", "ignore:catalogue (/teams)"), ("statistics[].league.", "ignore:catalogue (/leagues)"),
    ),
    "/teams/statistics": (
        ("league.", "ignore:held by the competition season"), ("team.", "ignore:catalogue (/teams)"),
        ("fixtures.", "ignore:the total is home + away"), ("goals.for.total.total", "ignore:home + away"),
        ("goals.against.total.total", "ignore:home + away"), ("goals.for.average.total", "ignore:derivable"),
        ("goals.against.average.total", "ignore:derivable"), ("clean_sheet.total", "ignore:home + away"),
        ("failed_to_score.total", "ignore:home + away"), ("penalty.", "ignore:derivable (scored + missed)"),
        ("goals.", _TSS + "raw"), ("biggest.", _TSS + "raw"), ("lineups[].", _TSS + "raw"), ("cards.", _TSS + "raw"),
    ),
    "/predictions": (
        ("comparison.", _PRED + "comparison"),
        ("league.", "ignore:held by the fixture"),
        ("teams.home.last_5.", "ignore:the provider's form figures at prediction time - its team statistics "
                               "(/teams/statistics, RAW) and our fixtures hold the same"),
        ("teams.away.last_5.", "ignore:the provider's form figures at prediction time - its team statistics "
                               "(/teams/statistics, RAW) and our fixtures hold the same"),
        ("teams.home.league.", "ignore:the provider's season statistics at prediction time (/teams/statistics)"),
        ("teams.away.league.", "ignore:the provider's season statistics at prediction time (/teams/statistics)"),
        ("teams.", "ignore:held by the fixture"),
        ("h2h[].", "ignore:past meetings - held by our fixtures (/fixtures), read with a date cut-off"),
    ),
    **{f"/players/top{k}": (("player.", "ignore:catalogue (/players/profiles)"),
                            ("statistics[].", "core.season_leaders.statistics")) for k in
       ("scorers", "assists", "yellowcards", "redcards")},
}
"""Rules for every path under a prefix, after the exact ones."""
RAW_ONLY: dict[str, str] = {
    "/venues": "ignore:kept as RAW (audit samples) - the same venue fields arrive with /teams?league&season "
               "(core.venues)",
    "/players/teams": "ignore:kept as RAW (audit samples) - one request per player; the club / national-team split "
                      "comes from squads and appearances",
    "/timezone": "ignore:kept as RAW only - requests are made in UTC (reference_refresh, every 90 days)",
    "/leagues/seasons": "ignore:kept as RAW only - every season is listed per league by /leagues (weekly)",
    "/players/seasons": "ignore:kept as RAW only - the seasons the provider has player statistics for (weekly)",
    "/teams/countries": "ignore:kept as RAW only - /countries holds names, codes and flags (weekly)",
    "/teams/seasons": "ignore:kept as RAW only - derivable from /teams?league&season and our fixtures",
}
"""Endpoints PrediGol requests without normalizing them: every field is kept in RAW only."""


def flatten(value: Any, prefix: str = "") -> Iterator[tuple[str, bool]]:
    """(path, has a value) for every leaf; list items collapse to ``[]``."""
    if isinstance(value, dict):
        for k, v in value.items():
            yield from flatten(v, f"{prefix}.{k}" if prefix else str(k))
    elif isinstance(value, list):
        if not value:
            yield prefix + "[]", False
        for item in value:
            yield from flatten(item, prefix + "[]")
    else:
        yield prefix, value is not None and value != ""


def items_of(body: Mapping[str, Any]) -> list[Any]:
    resp = body.get("response")
    return resp if isinstance(resp, list) else [resp] if isinstance(resp, dict) else []


@dataclass
class FieldRow:
    endpoint: str
    path: str
    seen: int
    present: int
    rule: str
    used: bool | None

    @property
    def klass(self) -> str:
        if self.rule.startswith(("core.", "market.", "raw.league_coverage")):
            return "stored"
        if self.rule.startswith("raw:"):
            return "RAW_ONLY"
        if self.rule.startswith("ignore:"):
            return "INTENTIONALLY_IGNORED"
        if self.rule.startswith("useful:"):
            return "DROPPED_USEFUL_FIELD"
        return "UNSUPPORTED_FIELD"


def inventory(endpoint: str, bodies: Sequence[Mapping[str, Any]], *, used_columns: set[str]) -> list[FieldRow]:
    seen: Counter[str] = Counter()
    present: Counter[str] = Counter()
    for body in bodies:
        for item in items_of(body):
            for path, has in flatten(item):
                seen[path] += 1
                present[path] += int(has)
    reg = REGISTRY.get(endpoint, {})
    rows = []
    for path in sorted(seen):
        rule = (reg.get(path) or _stat_rule(endpoint, path) or _prefix_rule(endpoint, path)
                or _container_rule(endpoint, path) or RAW_ONLY.get(endpoint) or "unmapped")
        col = rule.split(" ")[0].split(".")[-1] if rule.startswith(("core.", "market.", "raw.league")) else None
        rows.append(FieldRow(endpoint, path, seen[path], present[path], rule,
                             (col in used_columns) if col else None))
    return rows


def _container_rule(endpoint: str, path: str) -> str | None:
    """An empty list shows up as a leaf (``events[]``); it is the container of fields with their own rules."""
    if not path.endswith("[]"):
        return None
    inner = path + "."
    if any(k.startswith(inner) for k in REGISTRY.get(endpoint, {})) or any(
            p.startswith(inner) or inner.startswith(p) for p, _ in PREFIX.get(endpoint, ())) or (
            endpoint == "/fixtures" and path == "statistics[].statistics[]"):
        return "ignore:an empty list - its items have their own rules"
    return None


def _prefix_rule(endpoint: str, path: str) -> str | None:
    return next((rule for prefix, rule in PREFIX.get(endpoint, ()) if path.startswith(prefix)), None)


def _stat_rule(endpoint: str, path: str) -> str | None:
    if endpoint == "/fixtures" and re.fullmatch(r"statistics\[\]\.statistics\[\]\.(type|value)", path):
        return "core.fixture_team_stats (STAT_TYPES)"
    return None


def load_bodies(conn: psycopg.Connection[Any], raw_root: Path, endpoint: str, *, ids_only: bool | None = None,
                n: int = 40) -> list[dict[str, Any]]:
    """Up to ``n`` stored payloads of an endpoint, newest first, read from disk (never modified)."""
    cond = ""
    if ids_only is True:
        cond = "AND params ? 'ids'"
    elif ids_only is False:
        cond = "AND NOT params ? 'ids'"
    with conn.cursor() as cur:
        cur.execute(f"SELECT file_path FROM raw.ingestion_payloads WHERE endpoint = %s AND http_status = 200 {cond} "
                    "AND results_count > 0 ORDER BY fetched_at DESC LIMIT %s", (endpoint, n))
        paths = [str(r[0]) for r in cur.fetchall()]
    out = []
    for p in paths:
        f = Path(p) if Path(p).is_absolute() else raw_root / p
        try:
            data = f.read_bytes()
        except OSError:
            continue
        if data[:2] == b"\x1f\x8b":
            data = gzip.decompress(data)
        doc = json.loads(data)
        body = doc.get("body", doc) if isinstance(doc, dict) else {}
        if isinstance(body, dict):
            out.append(body)
    return out


def used_columns(src_root: Path) -> set[str]:
    """Column names named anywhere in the code that builds features, models, picks and pages."""
    words: set[str] = set()
    for sub in ("features", "models", "research", "picks", "api", "markets", "odds", "backtesting"):
        for f in (src_root / sub).rglob("*.py"):
            words.update(re.findall(r"[a-z_][a-z0-9_]+", f.read_text(errors="ignore")))
    return words


def evidence(rows: list[FieldRow]) -> list[Evidence]:
    out = []
    for klass, issue, sev in (("DROPPED_USEFUL_FIELD", "DROPPED_USEFUL_FIELD", "medium"),
                              ("UNSUPPORTED_FIELD", "UNSUPPORTED_FIELD", "low")):
        items = [r for r in rows if r.klass == klass and r.present]
        if not items:
            continue
        ex = [{"endpoint": r.endpoint, "path": r.path, "present": f"{r.present}/{r.seen}", "why": r.rule}
              for r in items[:25]]
        out.append(Evidence(key=f"normalization:{klass}", area="normalization", issue_type=issue, severity=sev,
                            at_fault="predigol", entity=f"{len(items)} fields",
                            claim=f"{len(items)} provider fields that carry values are {klass.lower().replace('_', ' ')} "
                                  "by our normalizers",
                            api={"fields": ex}, fix="store the useful ones (new columns, from RAW, no requests)"
                            if klass == "DROPPED_USEFUL_FIELD" else "decide: store or ignore, and say why"))
    stored_unused = [r for r in rows if r.klass == "stored" and r.used is False and r.present]
    if stored_unused:
        out.append(Evidence(key="normalization:stored_unused", area="normalization", issue_type="INTENTIONALLY_IGNORED",
                            severity="info", at_fault="none", entity=f"{len(stored_unused)} fields",
                            claim=f"{len(stored_unused)} stored fields are read by no feature, model, pick or page",
                            api={"fields": [{"endpoint": r.endpoint, "path": r.path, "column": r.rule}
                                            for r in stored_unused[:25]]}, status="ACCEPTED"))
    return out
