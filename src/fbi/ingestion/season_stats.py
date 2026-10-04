"""The provider's season aggregates, kept as the provider's: a player's for one team in one competition
(/players?league&season) and a team's in one competition season (/teams/statistics).

PrediGol computes its own aggregates from the per-match statistics; these tables hold what the provider
says, change-only and with the payload that said it, for display (labelled as the provider's) and for
the audit that compares the two. The rating is the provider's own metric: stored as sent, never
re-derived. Averages and totals are kept in different columns (the legacy ``_parse_avg`` once fell
back from an average to a total).
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from fbi.ingestion.reference import (
    _dig,
    _int,
    _map,
    _rating,
    _response,
    _small,
    _text,
    write_row_if_changed,
)

NORMALIZER_VERSION = "season-stats-1"


def _bool(v: Any) -> bool | None:
    return v if isinstance(v, bool) else None


def _avg(v: Any) -> Decimal | None:
    """'1.3' -> 1.3 (an AVERAGE per match); never a total."""
    if v is None or isinstance(v, bool):
        return None
    try:
        d = Decimal(str(v).strip())
    except (InvalidOperation, ValueError):
        return None
    return d if 0 <= d < 1000 else None


PLAYER_FIELDS: tuple[tuple[str, tuple[str, ...], Callable[[Any], Any]], ...] = (
    ("appearances", ("games", "appearences"), _small), ("lineups", ("games", "lineups"), _small),
    ("minutes", ("games", "minutes"), _int), ("shirt_number", ("games", "number"), _small),
    ("position", ("games", "position"), _text), ("rating", ("games", "rating"), _rating),
    ("captain", ("games", "captain"), _bool), ("subs_in", ("substitutes", "in"), _small),
    ("subs_out", ("substitutes", "out"), _small), ("subs_bench", ("substitutes", "bench"), _small),
    ("shots_total", ("shots", "total"), _small), ("shots_on", ("shots", "on"), _small),
    ("goals", ("goals", "total"), _small), ("goals_conceded", ("goals", "conceded"), _small),
    ("assists", ("goals", "assists"), _small), ("saves", ("goals", "saves"), _small),
    ("passes_total", ("passes", "total"), _int), ("passes_key", ("passes", "key"), _small),
    ("passes_accuracy", ("passes", "accuracy"), _small), ("tackles", ("tackles", "total"), _small),
    ("blocks", ("tackles", "blocks"), _small), ("interceptions", ("tackles", "interceptions"), _small),
    ("duels_total", ("duels", "total"), _small), ("duels_won", ("duels", "won"), _small),
    ("dribbles_attempts", ("dribbles", "attempts"), _small), ("dribbles_success", ("dribbles", "success"), _small),
    ("dribbled_past", ("dribbles", "past"), _small), ("fouls_drawn", ("fouls", "drawn"), _small),
    ("fouls_committed", ("fouls", "committed"), _small), ("yellow_cards", ("cards", "yellow"), _small),
    ("yellowred_cards", ("cards", "yellowred"), _small), ("red_cards", ("cards", "red"), _small),
    ("penalties_won", ("penalty", "won"), _small), ("penalties_committed", ("penalty", "commited"), _small),
    ("penalties_scored", ("penalty", "scored"), _small), ("penalties_missed", ("penalty", "missed"), _small),
    ("penalties_saved", ("penalty", "saved"), _small),
)
"""Column, path in a statistics entry, conversion. The provider spells it 'appearences' and 'commited'."""


def player_season_rows(body: Mapping[str, Any]) -> Iterator[tuple[dict[str, int], dict[str, Any]]]:
    """(keys, values) per player, team and competition season in a /players answer."""
    for entry in _response(body):
        if not isinstance(entry, Mapping):
            continue
        pid = _int(_dig(entry, "player", "id"))
        if pid is None or pid <= 0:
            continue
        for st in entry.get("statistics") or []:
            if not isinstance(st, Mapping):
                continue
            league, season, team = (_int(_dig(st, "league", "id")), _int(_dig(st, "league", "season")),
                                    _int(_dig(st, "team", "id")))
            if league is None or season is None or team is None or team <= 0:
                continue
            values = {col: conv(_dig(st, *path)) for col, path, conv in PLAYER_FIELDS}
            if all(v is None for v in values.values()):
                continue
            yield ({"provider_player_id": pid, "provider_league_id": league, "season": season,
                    "provider_team_id": team}, values)


def apply_player_season_stats(conn: psycopg.Connection, body: Mapping[str, Any], *, payload_hash: str,
                              observed_at: datetime) -> int:
    added = 0
    with conn.cursor() as cur:
        for keys, values in player_season_rows(body):
            added += write_row_if_changed(cur, "core.player_season_stats", keys, values, observed_at=observed_at,
                                          payload_hash=payload_hash, version=NORMALIZER_VERSION)
    return added


def team_statistics_values(resp: Mapping[str, Any]) -> dict[str, Any] | None:
    """The typed figures of a /teams/statistics answer, and the whole answer (minus league and team) as ``raw``."""
    fx, g = _map(resp.get("fixtures")), _map(resp.get("goals"))
    values: dict[str, Any] = {
        "played_home": _small(_dig(fx, "played", "home")), "played_away": _small(_dig(fx, "played", "away")),
        "wins_home": _small(_dig(fx, "wins", "home")), "wins_away": _small(_dig(fx, "wins", "away")),
        "draws_home": _small(_dig(fx, "draws", "home")), "draws_away": _small(_dig(fx, "draws", "away")),
        "loses_home": _small(_dig(fx, "loses", "home")), "loses_away": _small(_dig(fx, "loses", "away")),
        "goals_for_home": _avg(_dig(g, "for", "average", "home")),
        "goals_for_away": _avg(_dig(g, "for", "average", "away")),
        "goals_against_home": _avg(_dig(g, "against", "average", "home")),
        "goals_against_away": _avg(_dig(g, "against", "average", "away")),
        "goals_for_total_home": _small(_dig(g, "for", "total", "home")),
        "goals_for_total_away": _small(_dig(g, "for", "total", "away")),
        "goals_against_total_home": _small(_dig(g, "against", "total", "home")),
        "goals_against_total_away": _small(_dig(g, "against", "total", "away")),
        "clean_sheets_home": _small(_dig(resp, "clean_sheet", "home")),
        "clean_sheets_away": _small(_dig(resp, "clean_sheet", "away")),
        "failed_to_score_home": _small(_dig(resp, "failed_to_score", "home")),
        "failed_to_score_away": _small(_dig(resp, "failed_to_score", "away")),
        "form": _text(resp.get("form")),
        "penalties_scored": _small(_dig(resp, "penalty", "scored", "total")),
        "penalties_missed": _small(_dig(resp, "penalty", "missed", "total")),
    }
    if all(v is None for v in values.values()):
        return None
    values["raw"] = Jsonb({k: v for k, v in resp.items() if k not in ("league", "team")})
    return values


def apply_team_statistics(conn: psycopg.Connection, competition_season_id: int, team_id: int,
                          body: Mapping[str, Any], *, payload_hash: str, observed_at: datetime) -> int:
    resp = body.get("response")
    if not isinstance(resp, Mapping):
        return 0
    values = team_statistics_values(resp)
    if values is None:
        return 0
    with conn.cursor() as cur:
        return write_row_if_changed(cur, "core.team_season_stats",
                                    {"competition_season_id": competition_season_id, "team_id": team_id}, values,
                                    observed_at=observed_at, payload_hash=payload_hash, version=NORMALIZER_VERSION,
                                    time_col="snapshot_at")
