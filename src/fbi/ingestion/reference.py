"""Reference feeds: the API-Football endpoints about matches, seasons, people and the odds catalogue that
PrediGol did not request before the contract audit (4 Oct 2026), refreshed on the provider's documented
cadence and always behind the live reserve.

A feed names an endpoint, the targets in scope now (an upcoming match, a current season, a tracked team,
a batch of twenty players), how long an answer stays fresh for a target, and a normalizer. Every answer
is a RAW payload first; the normalizer writes what it says into a typed table, change-only, naming that
payload and ``NORMALIZER_VERSION``. ``core.reference_checks`` records each question - when it was asked,
what answered, when the answer last changed - whatever the answer, so "asked and empty" and "never
asked" are not confused.

Cadences (documented update frequency -> ours):

=====================  ==================================  ===============================================
feed                   provider                            PrediGol
=====================  ==================================  ===============================================
predictions            hourly; 1 call/day per match        48 h, 24 h and 3 h before kick-off (3 per match)
rounds, current_round  daily; 1 call/day                   daily per tracked current season
leaders (4 lists)      several times a week; 1 call/day    daily per current season the coverage flags allow
odds_bets/bookmakers   several times a week; 1 call/day    daily
odds_mapping           daily (100 a page); 1 call/day      daily, every page (up to 200); read by the capture
                                                           planner and the price status (see scripts.capture_odds)
team_statistics        twice a day; 1/day if playing, else  daily for teams playing within 24 h, else weekly
                       1/week
coachs                 daily; 1 call/day                   weekly per tracked team (line-ups name the coach
                                                           of every match)
transfers              several times a week; 1 call/day    weekly per tracked club (national sides have none)
sidelined, trophies    several times a week; 1 call/day    weekly, 20 people a request
countries              when a country is added; 1/day      weekly
venues                 several times a week; 1 call/day    by id, the venues of current tracked seasons not
                                                           described within 90 days (next matches first)
players_teams          several times a week; 1/day-1/week  every 60 days per player in scope, and at once when
                                                           the player's /transfers list changed since
profiles_players,      several times a week; 1/day         by id, the people of the last 365 days' line-ups
coachs_by_id                                               no sweep or round described; again after 30 days if
                                                           the provider had nothing
=====================  ==================================  ===============================================

Weekly instead of daily for people is deliberate: the tracked scope (4 Oct 2026: 5,525 teams, 8,121
team-seasons, 30,742 players, 4,571 coaches) asked daily would cost ~20,000 requests a day for answers
that change a few times a season; the first fill is ~23,500 requests (under two days at 300 a run), then
about 3,500 a day. Predictions and tables that feed match pages stay on the documented cadence.

Order: every feed with something due first gets a fair share of the run's allowance, then what is left
goes feed by feed in the order below (predictions first), so the first sweep of one feed never starves
the others. Within a feed, targets never asked come first, then the longest unasked; among the never
asked, the teams playing soonest and the people seen most recently on a pitch or a bench.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import psycopg
from psycopg.rows import tuple_row
from psycopg.types.json import Jsonb

from fbi.core.clock import now
from fbi.core.errors import ProviderError, QuotaExhaustedError
from fbi.core.logging import get_logger
from fbi.ingestion.ledger import RunCounters, RunLedger

log = get_logger(__name__)

NORMALIZER_VERSION = "reference-1"
RESERVE_MARGIN = 10
MAX_PAGES = 30
MAPPING_MAX_PAGES = 200
"""/odds/mapping lists every priced fixture, 100 a page: 29 pages on 4 Oct 2026, one short of ``MAX_PAGES``. A busier
day would have been cut at 3,000 fixtures without a word; 200 pages is 20,000 fixtures."""
BATCH_PEOPLE = 20
"""/sidelined and /trophies accept up to 20 ids (documented batch limit)."""


@dataclass(frozen=True)
class Target:
    key: str
    params: dict[str, Any]
    every: timedelta
    context: dict[str, Any] = field(default_factory=dict)
    """What the normalizer needs besides the body (the fixture or season id, the people asked about)."""


Apply = Callable[[psycopg.Connection, Target, dict[str, Any], str, datetime], int]


@dataclass(frozen=True)
class Feed:
    name: str
    endpoint: str
    targets: Callable[[psycopg.Connection, datetime], list[Target]]
    apply: Apply
    max_per_run: int
    """Requests a run may spend on this feed."""
    paged: bool = False
    batch: int = 1
    """Targets asked together in one request (``batch_param`` joined with '-'): /sidelined and /trophies
    take 20 people. Each target keeps its own check, so a batch is formed from the people due, not fixed."""
    batch_param: str = ""
    max_pages: int = 0
    """Pages a paged answer may be read to (0 = ``MAX_PAGES``). An answer with more pages than that is read to the
    cap and its check records the truncation as an error - never a silent partial sweep."""


# ── values ──────────────────────────────────────────────────────────────────────────────────────────


def _int(v: Any) -> int | None:
    if isinstance(v, bool):
        return None
    if isinstance(v, int):
        return v
    if isinstance(v, str) and v.strip().lstrip("-").isdigit():
        return int(v.strip())
    return None


def _small(v: Any) -> int | None:
    n = _int(v)
    return n if n is not None and 0 <= n < 32768 else None


def _text(v: Any) -> str | None:
    return v.strip() if isinstance(v, str) and v.strip() else None


def _date(v: Any) -> date | None:
    if not isinstance(v, str) or not v.strip():
        return None
    try:
        return date.fromisoformat(v.strip()[:10])
    except ValueError:
        return None


def _stamp(v: Any) -> datetime | None:
    if not isinstance(v, str) or not v.strip():
        return None
    try:
        d = datetime.fromisoformat(v.strip().replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo is not None else d.replace(tzinfo=UTC)


PERCENT = re.compile(r"^\s*(\d{1,3}(?:\.\d+)?)\s*%?\s*$")


def _percent(v: Any) -> Decimal | None:
    """'45%' -> 45. Anything else (None, '', 'n/a') -> None: never guessed."""
    if isinstance(v, int | float) and not isinstance(v, bool):
        d = Decimal(str(v))
    elif isinstance(v, str) and (m := PERCENT.match(v)):
        try:
            d = Decimal(m.group(1))
        except InvalidOperation:
            return None
    else:
        return None
    return d if 0 <= d <= 100 else None


def _rating(v: Any) -> Decimal | None:
    try:
        d = Decimal(str(v)) if isinstance(v, str | int | float) and not isinstance(v, bool) else None
    except InvalidOperation:
        return None
    return d if d is not None and 0 <= d < 100 else None


def _response(body: Mapping[str, Any]) -> list[Any]:
    r = body.get("response")
    return r if isinstance(r, list) else []


def _map(v: Any) -> Mapping[str, Any]:
    return v if isinstance(v, Mapping) else {}


def _dig(d: Any, *keys: str) -> Any:
    for k in keys:
        if not isinstance(d, Mapping):
            return None
        d = d.get(k)
    return d


# ── change-only writers ───────────────────────────────────────────────────────────────────────────────


def _canon(v: Any) -> Any:
    """One form for a value as written and as read back (Jsonb vs dict, 45 vs 45.00, list vs tuple)."""
    if isinstance(v, Jsonb):
        v = v.obj
    if isinstance(v, dict):
        return json.dumps(v, sort_keys=True, default=str)
    if isinstance(v, Decimal):
        return v.normalize()
    if isinstance(v, list):
        return tuple(_canon(x) for x in v)
    return v


def write_row_if_changed(cur: psycopg.Cursor[Any], table: str, keys: Mapping[str, Any], values: Mapping[str, Any],
                         *, observed_at: datetime, payload_hash: str, version: str = NORMALIZER_VERSION,
                         time_col: str = "observed_at") -> int:
    """Add one row when ``values`` differ from the newest row for ``keys`` and the payload is newer than it."""
    where = " AND ".join(f"{k} = %({k})s" for k in keys)
    cols = list(values)
    cur.execute(f"SELECT {time_col}, {', '.join(cols)} FROM {table} WHERE {where} ORDER BY {time_col} DESC LIMIT 1",
                dict(keys))
    row = cur.fetchone()
    if row is not None:
        if row[0] >= observed_at:
            return 0
        if tuple(_canon(x) for x in row[1:]) == tuple(_canon(values[c]) for c in cols):
            return 0
    allcols = [*keys, time_col, *cols, "payload_hash", "normalizer_version"]
    cur.execute(f"INSERT INTO {table} ({', '.join(allcols)}) VALUES ({', '.join('%(' + c + ')s' for c in allcols)}) "
                "ON CONFLICT DO NOTHING",
                {**keys, **values, time_col: observed_at, "payload_hash": payload_hash, "normalizer_version": version})
    return max(cur.rowcount, 0)


def write_snapshot_if_changed(cur: psycopg.Cursor[Any], table: str, keys: Mapping[str, Any],
                              rows: Sequence[Mapping[str, Any]], *, observed_at: datetime, payload_hash: str) -> int:
    """Add the whole list under ``observed_at`` when it differs from the newest list stored for ``keys``.

    An empty answer adds nothing here - it is visible in ``core.reference_checks`` (results 0) - so it
    never erases a list held before.
    """
    if not rows:
        return 0
    cols = list(rows[0])
    where = " AND ".join(f"{k} = %({k})s" for k in keys)
    cur.execute(f"SELECT observed_at, {', '.join(cols)} FROM {table} WHERE {where} AND observed_at = "
                f"(SELECT max(observed_at) FROM {table} WHERE {where}) ORDER BY ordinal", dict(keys))
    held = cur.fetchall()
    if held:
        if held[0][0] >= observed_at:
            return 0
        if [tuple(_canon(x) for x in h[1:]) for h in held] == [tuple(_canon(r[c]) for c in cols) for r in rows]:
            return 0
    allcols = [*keys, "observed_at", "ordinal", *cols, "payload_hash", "normalizer_version"]
    sql = (f"INSERT INTO {table} ({', '.join(allcols)}) VALUES ({', '.join('%(' + c + ')s' for c in allcols)}) "
           "ON CONFLICT DO NOTHING")
    added = 0
    for i, r in enumerate(rows):
        cur.execute(sql, {**keys, **r, "observed_at": observed_at, "ordinal": i, "payload_hash": payload_hash,
                          "normalizer_version": NORMALIZER_VERSION})
        added += max(cur.rowcount, 0)
    return added


# ── normalizers ───────────────────────────────────────────────────────────────────────────────────────


def prediction_values(entry: Mapping[str, Any]) -> dict[str, Any] | None:
    """What one /predictions entry forecasts; None when it forecasts nothing."""
    p = entry.get("predictions")
    if not isinstance(p, Mapping):
        return None
    winner, percent, goals = _map(p.get("winner")), _map(p.get("percent")), _map(p.get("goals"))
    comparison = entry.get("comparison")
    values = {
        "winner_team_id": _int(winner.get("id")), "winner_name": _text(winner.get("name")),
        "winner_comment": _text(winner.get("comment")),
        "win_or_draw": p.get("win_or_draw") if isinstance(p.get("win_or_draw"), bool) else None,
        "under_over": _text(p.get("under_over")), "goals_home": _text(goals.get("home")),
        "goals_away": _text(goals.get("away")), "advice": _text(p.get("advice")),
        "percent_home": _percent(percent.get("home")), "percent_draw": _percent(percent.get("draw")),
        "percent_away": _percent(percent.get("away")),
        "comparison": Jsonb(comparison) if isinstance(comparison, Mapping) and comparison else None,
    }
    return values if any(v is not None for v in values.values()) else None


def apply_predictions(conn: psycopg.Connection, t: Target, body: dict[str, Any], payload_hash: str,
                      observed_at: datetime) -> int:
    added = 0
    with conn.cursor() as cur:
        for entry in _response(body):
            v = prediction_values(entry) if isinstance(entry, Mapping) else None
            if v is None:
                continue
            added += write_row_if_changed(cur, "core.provider_predictions", {"fixture_id": t.context["fixture_id"]}, v,
                                          observed_at=observed_at, payload_hash=payload_hash)
    return added


def apply_rounds(conn: psycopg.Connection, t: Target, body: dict[str, Any], payload_hash: str,
                 observed_at: datetime) -> int:
    rows: list[dict[str, Any]] = []
    for item in _response(body):
        if isinstance(item, str) and item.strip():
            rows.append({"round": item.strip(), "dates": None})
        elif isinstance(item, Mapping) and _text(item.get("round")):
            dates = [d for d in (_date(x) for x in item.get("dates") or []) if d is not None]
            rows.append({"round": _text(item.get("round")), "dates": dates or None})
    with conn.cursor() as cur:
        return write_snapshot_if_changed(cur, "core.season_rounds", {"competition_season_id": t.context["cs_id"]},
                                         rows, observed_at=observed_at, payload_hash=payload_hash)


def apply_current_round(conn: psycopg.Connection, t: Target, body: dict[str, Any], payload_hash: str,
                        observed_at: datetime) -> int:
    rounds = [r.strip() for r in _response(body) if isinstance(r, str) and r.strip()]
    if not rounds:
        return 0
    with conn.cursor() as cur:
        return write_row_if_changed(cur, "core.season_current_round", {"competition_season_id": t.context["cs_id"]},
                                    {"rounds": rounds}, observed_at=observed_at, payload_hash=payload_hash)


def leader_row(entry: Mapping[str, Any], league_id: int, season: int) -> dict[str, Any] | None:
    player = _map(entry.get("player"))
    pid = _int(player.get("id"))
    if pid is None or pid <= 0:
        return None
    stats = [s for s in entry.get("statistics") or [] if isinstance(s, Mapping)]
    mine = [s for s in stats if _int(_dig(s, "league", "id")) == league_id
            and _int(_dig(s, "league", "season")) in (season, None)] or stats[:1]
    s = mine[0] if mine else {}
    return {
        "provider_player_id": pid, "player_name": _text(player.get("name")), "photo_url": _text(player.get("photo")),
        "provider_team_id": _int(_dig(s, "team", "id")), "team_name": _text(_dig(s, "team", "name")),
        "appearances": _small(_dig(s, "games", "appearences")), "minutes": _int(_dig(s, "games", "minutes")),
        "goals": _small(_dig(s, "goals", "total")), "assists": _small(_dig(s, "goals", "assists")),
        "penalties_scored": _small(_dig(s, "penalty", "scored")), "yellow_cards": _small(_dig(s, "cards", "yellow")),
        "yellowred_cards": _small(_dig(s, "cards", "yellowred")), "red_cards": _small(_dig(s, "cards", "red")),
        "rating": _rating(_dig(s, "games", "rating")), "statistics": Jsonb(mine if len(mine) > 1 else s),
    }


def apply_leaders(conn: psycopg.Connection, t: Target, body: dict[str, Any], payload_hash: str,
                  observed_at: datetime) -> int:
    rows = [r for r in (leader_row(e, t.params["league"], t.params["season"]) for e in _response(body)
                        if isinstance(e, Mapping)) if r is not None]
    with conn.cursor() as cur:
        return write_snapshot_if_changed(cur, "core.season_leaders",
                                         {"competition_season_id": t.context["cs_id"], "list": t.context["list"]},
                                         rows, observed_at=observed_at, payload_hash=payload_hash)


def apply_coachs(conn: psycopg.Connection, t: Target, body: dict[str, Any], payload_hash: str,
                 observed_at: datetime) -> int:
    added = 0
    with conn.cursor() as cur:
        for c in _response(body):
            if not isinstance(c, Mapping) or (cid := _int(c.get("id"))) is None or cid <= 0:
                continue
            profile = {
                "name": _text(c.get("name")), "firstname": _text(c.get("firstname")),
                "lastname": _text(c.get("lastname")), "birth_date": _date(_dig(c, "birth", "date")),
                "birth_place": _text(_dig(c, "birth", "place")), "birth_country": _text(_dig(c, "birth", "country")),
                "nationality": _text(c.get("nationality")), "height": _text(c.get("height")),
                "weight": _text(c.get("weight")), "photo_url": _text(c.get("photo")),
                "provider_team_id": _int(_dig(c, "team", "id")),
            }
            added += write_row_if_changed(cur, "core.coach_profiles", {"provider_coach_id": cid}, profile,
                                          observed_at=observed_at, payload_hash=payload_hash)
            career = [{"provider_team_id": _int(_dig(x, "team", "id")), "team_name": _text(_dig(x, "team", "name")),
                       "start_date": _date(x.get("start")), "end_date": _date(x.get("end"))}
                      for x in c.get("career") or [] if isinstance(x, Mapping)]
            added += write_snapshot_if_changed(cur, "core.coach_careers", {"provider_coach_id": cid}, career,
                                               observed_at=observed_at, payload_hash=payload_hash)
    return added


def apply_transfers(conn: psycopg.Connection, t: Target, body: dict[str, Any], payload_hash: str,
                    observed_at: datetime) -> int:
    added = 0
    with conn.cursor() as cur:
        for e in _response(body):
            if not isinstance(e, Mapping) or (pid := _int(_dig(e, "player", "id"))) is None or pid <= 0:
                continue
            update = _stamp(e.get("update"))
            rows = [{"transfer_date": _date(x.get("date")), "type": _text(x.get("type")),
                     "team_in_id": _int(_dig(x, "teams", "in", "id")),
                     "team_in_name": _text(_dig(x, "teams", "in", "name")),
                     "team_out_id": _int(_dig(x, "teams", "out", "id")),
                     "team_out_name": _text(_dig(x, "teams", "out", "name")), "provider_update_at": update}
                    for x in e.get("transfers") or [] if isinstance(x, Mapping)]
            added += write_snapshot_if_changed(cur, "core.player_transfers", {"provider_player_id": pid}, rows,
                                               observed_at=observed_at, payload_hash=payload_hash)
    return added


def _people_entries(body: dict[str, Any], t: Target) -> dict[int, list[Mapping[str, Any]]]:
    """/sidelined and /trophies list entries for ONE person ({type,start,end} / {league,...}); a batched
    request (``players=a-b``) answers one block per person, each naming the person. A single-person
    answer is attributed to the person asked about; a batched answer without names is not attributed."""
    out: dict[int, list[Mapping[str, Any]]] = {}
    asked = list(t.context["ids"])
    entries = [e for e in _response(body) if isinstance(e, Mapping)]
    blocks = [e for e in entries if _int(e.get("id")) is not None and isinstance(e.get(t.context["list_key"]), list)]
    if blocks:
        for b in blocks:
            pid = _int(b.get("id"))
            if pid is not None and pid in asked:
                out[pid] = [x for x in b[t.context["list_key"]] if isinstance(x, Mapping)]
        return out
    if len(asked) == 1:
        out[asked[0]] = entries
    return out


def _apply_people(table: str, columns: Callable[[Mapping[str, Any]], dict[str, Any]]) -> Apply:
    def apply(conn: psycopg.Connection, t: Target, body: dict[str, Any], payload_hash: str,
              observed_at: datetime) -> int:
        added = 0
        found = t.context.setdefault("found", {})
        with conn.cursor() as cur:
            for pid, entries in _people_entries(body, t).items():
                found[pid] = len(entries)
                rows = [columns(x) for x in entries]
                added += write_snapshot_if_changed(cur, table, {"person_kind": t.context["kind"],
                                                                "provider_person_id": pid}, rows,
                                                   observed_at=observed_at, payload_hash=payload_hash)
        return added
    return apply


apply_sidelined = _apply_people("core.person_sidelined", lambda x: {
    "type": _text(x.get("type")), "start_date": _date(x.get("start")), "end_date": _date(x.get("end"))})
apply_trophies = _apply_people("core.person_trophies", lambda x: {
    "league": _text(x.get("league")), "country": _text(x.get("country")), "season": _text(x.get("season")),
    "place": _text(x.get("place"))})


def apply_countries(conn: psycopg.Connection, t: Target, body: dict[str, Any], payload_hash: str,
                    observed_at: datetime) -> int:
    added = 0
    with conn.cursor() as cur:
        for c in _response(body):
            if isinstance(c, Mapping) and (name := _text(c.get("name"))):
                added += write_row_if_changed(cur, "core.countries", {"name": name},
                                              {"code": _text(c.get("code")), "flag_url": _text(c.get("flag"))},
                                              observed_at=observed_at, payload_hash=payload_hash)
    return added


def apply_odds_mapping(conn: psycopg.Connection, t: Target, body: dict[str, Any], payload_hash: str,
                       observed_at: datetime) -> int:
    rows = []
    for e in _response(body):
        if isinstance(e, Mapping) and (fid := _int(_dig(e, "fixture", "id"))) is not None and fid > 0:
            ts = _int(_dig(e, "fixture", "timestamp"))
            rows.append((fid, _int(_dig(e, "league", "id")), _int(_dig(e, "league", "season")),
                         datetime.fromtimestamp(ts, UTC) if ts and ts > 0 else _stamp(_dig(e, "fixture", "date")),
                         observed_at, _stamp(e.get("update")), payload_hash, NORMALIZER_VERSION))
    if not rows:
        return 0
    with conn.cursor() as cur:
        cur.executemany(
            "INSERT INTO market.odds_mapping_seen (provider_fixture_id, provider_league_id, season, fixture_date, "
            "first_seen_at, provider_update_at, payload_hash, normalizer_version) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
            "ON CONFLICT (provider_fixture_id) DO NOTHING", rows)
        return max(cur.rowcount, 0)


MAX_CAPACITY = 250_000
"""A stadium's capacity above this (or 0) is not a capacity: stored as unknown, never guessed."""


def venue_values(v: Mapping[str, Any]) -> dict[str, Any] | None:
    """One /venues entry; None without an id or a name (an unkeyable venue is not stored)."""
    vid = _int(v.get("id"))
    name = _text(v.get("name"))
    if vid is None or vid <= 0 or name is None:
        return None
    capacity = _int(v.get("capacity"))
    return {"provider_venue_id": vid, "name": name, "city": _text(v.get("city")), "country": _text(v.get("country")),
            "capacity": capacity if capacity is not None and 0 < capacity <= MAX_CAPACITY else None,
            "surface": _text(v.get("surface")), "address": _text(v.get("address")),
            "image_url": _text(v.get("image"))}


def apply_venues(conn: psycopg.Connection, t: Target, body: dict[str, Any], payload_hash: str,
                 observed_at: datetime) -> int:
    """/venues?id into core.venues, the identity table the fixtures and teams point at: the newest payload wins, and
    a value the provider leaves empty does not erase one already held (the venue block of /teams may have sent it)."""
    written = 0
    with conn.cursor() as cur:
        for entry in _response(body):
            v = venue_values(entry) if isinstance(entry, Mapping) else None
            if v is None:
                continue
            cur.execute(
                "INSERT INTO core.venues (provider_venue_id, name, city, country, capacity, surface, address, image_url, "
                "source_payload_hash, source_fetched_at) VALUES (%(provider_venue_id)s, %(name)s, %(city)s, "
                "%(country)s, %(capacity)s, %(surface)s, %(address)s, %(image_url)s, %(h)s, %(at)s) "
                "ON CONFLICT (provider_venue_id) DO UPDATE SET name = EXCLUDED.name, "
                "  city = COALESCE(EXCLUDED.city, core.venues.city), "
                "  country = COALESCE(EXCLUDED.country, core.venues.country), "
                "  capacity = COALESCE(EXCLUDED.capacity, core.venues.capacity), "
                "  surface = COALESCE(EXCLUDED.surface, core.venues.surface), "
                "  address = COALESCE(EXCLUDED.address, core.venues.address), "
                "  image_url = COALESCE(EXCLUDED.image_url, core.venues.image_url), "
                "  source_payload_hash = EXCLUDED.source_payload_hash, source_fetched_at = EXCLUDED.source_fetched_at "
                "WHERE core.venues.source_fetched_at IS NULL OR core.venues.source_fetched_at <= EXCLUDED.source_fetched_at",
                {**v, "h": payload_hash, "at": observed_at})
            written += max(cur.rowcount, 0)
    return written


def player_team_rows(body: Mapping[str, Any]) -> list[dict[str, Any]]:
    """/players/teams: ``[{"team": {id, name, logo}, "seasons": [2024, 2023]}]`` in the provider's order. Seasons are
    kept newest first (one canonical form, so a reordering alone is not a change); a year that is not a season
    (outside 1850-2100) is left out, never corrected."""
    rows = []
    for e in _response(body):
        if not isinstance(e, Mapping):
            continue
        team = _map(e.get("team"))
        seasons = sorted({y for y in (_int(x) for x in e.get("seasons") or []) if y is not None and 1850 <= y <= 2100},
                         reverse=True)
        tid = _int(team.get("id"))
        if (tid is None or tid <= 0) and not seasons:
            continue
        rows.append({"provider_team_id": tid if tid and tid > 0 else None, "team_name": _text(team.get("name")),
                     "team_logo": _text(team.get("logo")), "seasons": seasons})
    return rows


def apply_player_teams(conn: psycopg.Connection, t: Target, body: dict[str, Any], payload_hash: str,
                       observed_at: datetime) -> int:
    with conn.cursor() as cur:
        return write_snapshot_if_changed(cur, "core.player_team_seasons", {"provider_player_id": t.context["ids"][0]},
                                         player_team_rows(body), observed_at=observed_at, payload_hash=payload_hash)


def apply_catalogue(conn: psycopg.Connection, t: Target, body: dict[str, Any], payload_hash: str,
                    observed_at: datetime) -> int:
    """/odds/bets, /odds/live/bets, /odds/bookmakers into the existing catalogue tables; a rename is kept in
    market.provider_catalogue_changes (the old name, the new one, this payload)."""
    from fbi.catalog.provider_markets import PROVIDER, _mapping_for

    entries = [(int(e["id"]), str(e.get("name") or "").strip()) for e in _response(body)
               if isinstance(e, Mapping) and isinstance(e.get("id"), int) and not isinstance(e.get("id"), bool)]
    catalogue = t.context["catalogue"]
    added = 0
    with conn.cursor(row_factory=tuple_row) as cur:
        if catalogue == "bookmakers":
            cur.execute("SELECT provider_bookmaker_id, name FROM market.bookmakers")
        else:
            cur.execute("SELECT provider_bet_id, name FROM market.provider_markets WHERE provider = %s AND scope = %s",
                        (PROVIDER, catalogue))
        held: dict[int, str] = {int(a): str(b) for a, b in cur.fetchall()}
        mapping = {} if catalogue == "bookmakers" else _mapping_for(catalogue)
        for pid, name in entries:
            old = held.get(pid)
            if old is not None and name and old != name:
                cur.execute("INSERT INTO market.provider_catalogue_changes (catalogue, provider_id, observed_at, "
                            "old_name, new_name, payload_hash, normalizer_version) VALUES (%s,%s,%s,%s,%s,%s,%s) "
                            "ON CONFLICT DO NOTHING",
                            (catalogue, pid, observed_at, old, name, payload_hash, NORMALIZER_VERSION))
            if catalogue == "bookmakers":
                cur.execute("INSERT INTO market.bookmakers (provider_bookmaker_id, name) VALUES (%s, %s) "
                            "ON CONFLICT (provider_bookmaker_id) DO UPDATE SET name = EXCLUDED.name "
                            "WHERE market.bookmakers.name IS DISTINCT FROM EXCLUDED.name", (pid, name or str(pid)))
            else:
                cur.execute(
                    "INSERT INTO market.provider_markets (provider, scope, provider_bet_id, name, market_key, source, "
                    "provider_version) VALUES (%s,%s,%s,%s,%s,'catalogue','v3.9.3') "
                    "ON CONFLICT (provider, scope, provider_bet_id) DO UPDATE SET name = EXCLUDED.name, "
                    "source = 'catalogue', last_seen_at = now()",
                    (PROVIDER, catalogue, pid, name, mapping.get(pid)))
            added += 1 if old is None else 0
    return added


def apply_team_statistics(conn: psycopg.Connection, t: Target, body: dict[str, Any], payload_hash: str,
                          observed_at: datetime) -> int:
    """/teams/statistics into core.team_season_stats (fbi.ingestion.season_stats)."""
    from fbi.ingestion.season_stats import apply_team_statistics as write

    return write(conn, t.context["cs_id"], t.context["team_id"], body, payload_hash=payload_hash,
                 observed_at=observed_at)


def apply_nothing(conn: psycopg.Connection, t: Target, body: dict[str, Any], payload_hash: str,
                  observed_at: datetime) -> int:
    """Kept as RAW only (a list the provider documents and PrediGol has no table for: timezones, the seasons
    and countries the provider covers - each already implied by /leagues)."""
    return 0


# ── targets ───────────────────────────────────────────────────────────────────────────────────────────

CURRENT_SEASONS_SQL = """
SELECT cs.id, c.provider_league_id, cs.season,
       coalesce(lc.top_scorers, false), coalesce(lc.top_assists, false), coalesce(lc.top_cards, false)
  FROM core.competition_seasons cs
  JOIN core.competitions c ON c.id = cs.competition_id
  LEFT JOIN raw.league_coverage lc ON lc.provider_league_id = c.provider_league_id AND lc.season = cs.season
 WHERE c.is_tracked AND cs.is_current
 ORDER BY c.provider_league_id
"""

UPCOMING_SQL = """
SELECT f.id, f.provider_fixture_id, f.kickoff_at
  FROM core.fixtures f
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  LEFT JOIN raw.league_coverage lc ON lc.provider_league_id = c.provider_league_id AND lc.season = cs.season
 WHERE c.is_tracked AND f.status_group = 'scheduled' AND f.kickoff_at > %(at)s
   AND f.kickoff_at <= %(at)s + interval '48 hours' AND coalesce(lc.predictions, true)
 ORDER BY f.kickoff_at
"""

NEXT_KICKOFF = """
WITH nxt AS (
    SELECT team_id, min(kickoff_at) AS kickoff_at
      FROM (SELECT home_team_id AS team_id, kickoff_at FROM core.fixtures
             WHERE status_group = 'scheduled' AND kickoff_at > %(at)s
            UNION ALL
            SELECT away_team_id, kickoff_at FROM core.fixtures
             WHERE status_group = 'scheduled' AND kickoff_at > %(at)s) x
     GROUP BY team_id)
"""
"""Each team's next scheduled kick-off: the teams playing soonest are asked first."""

TEAMS_SQL = NEXT_KICKOFF + """, scope AS (
    SELECT DISTINCT t.id FROM core.fixtures f
      JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
      JOIN core.competitions c ON c.id = cs.competition_id
      JOIN core.teams t ON t.id IN (f.home_team_id, f.away_team_id)
     WHERE c.is_tracked AND cs.is_current)
SELECT t.provider_team_id, COALESCE(n.kickoff_at <= %(at)s + interval '72 hours', false)
  FROM scope JOIN core.teams t ON t.id = scope.id
  LEFT JOIN nxt n ON n.team_id = t.id
  LEFT JOIN core.team_kind k ON k.team_id = t.id
 WHERE t.provider_team_id > 0 AND (NOT %(clubs_only)s OR NOT COALESCE(k.is_national, t.is_national, false))
 ORDER BY n.kickoff_at NULLS LAST, t.provider_team_id
"""
"""Teams of the current tracked seasons, the soonest to play first. ``clubs_only`` leaves out national sides
(PrediGol's classification, core.team_kind): the provider lists no transfer for them - asked on 4 Oct 2026,
/transfers?team=1..4 answered nothing."""

PEOPLE_SQL = {
    "player": """
SELECT ps.provider_player_id FROM core.fixture_player_stats ps
  JOIN core.fixtures f ON f.id = ps.fixture_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE c.is_tracked AND cs.is_current AND ps.provider_player_id > 0 AND coalesce(ps.minutes, 0) > 0
 GROUP BY 1
 ORDER BY max(f.kickoff_at) DESC, 1""",
    "coach": """
SELECT l.provider_coach_id FROM core.fixture_lineups l
  JOIN core.fixtures f ON f.id = l.fixture_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE c.is_tracked AND cs.is_current AND l.provider_coach_id > 0
 GROUP BY 1
 ORDER BY max(f.kickoff_at) DESC, 1""",
}
"""The people in scope, the most recently seen on a pitch or a bench first."""

TEAM_SEASONS_SQL = NEXT_KICKOFF + """
SELECT cs.id, c.provider_league_id, cs.season, t.id, t.provider_team_id,
       bool_or(f.status_group = 'scheduled' AND f.kickoff_at BETWEEN %(at)s AND %(at)s + interval '24 hours')
  FROM core.fixtures f
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  JOIN core.teams t ON t.id IN (f.home_team_id, f.away_team_id)
  LEFT JOIN nxt n ON n.team_id = t.id
 WHERE c.is_tracked AND cs.is_current AND t.provider_team_id > 0
 GROUP BY 1, 2, 3, 4, 5, n.kickoff_at
 ORDER BY n.kickoff_at NULLS LAST, 2, 5
"""

PREDICTION_WINDOWS = (timedelta(hours=48), timedelta(hours=24), timedelta(hours=3))
NEVER_AGAIN = timedelta(days=3650)
DAY = timedelta(hours=23)
"""Just under a day, so a daily feed that ran a little late is not pushed a whole day later."""
WEEK = timedelta(days=7) - timedelta(hours=1)


def prediction_targets(conn: psycopg.Connection, at: datetime) -> list[Target]:
    """Each upcoming match once in each window it has entered (48 h, 24 h, 3 h before kick-off)."""
    out = []
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(UPCOMING_SQL, {"at": at})
        for fid, pf, kickoff in cur.fetchall():
            opened = [w for w in PREDICTION_WINDOWS if at >= kickoff - w]
            if opened:
                w = min(opened)
                out.append(Target(f"fixture:{pf}:{int(w.total_seconds() // 3600)}h", {"fixture": int(pf)},
                                  NEVER_AGAIN, {"fixture_id": int(fid)}))
    return out


def _seasons(conn: psycopg.Connection) -> list[tuple[int, int, int, bool, bool, bool]]:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(CURRENT_SEASONS_SQL)
        return [(int(a), int(b), int(c), bool(d), bool(e), bool(f)) for a, b, c, d, e, f in cur.fetchall()]


def round_targets(conn: psycopg.Connection, at: datetime) -> list[Target]:
    return [Target(f"season:{lg}:{s}", {"league": lg, "season": s, "dates": "true"}, DAY, {"cs_id": cs})
            for cs, lg, s, *_ in _seasons(conn)]


def current_round_targets(conn: psycopg.Connection, at: datetime) -> list[Target]:
    return [Target(f"season:{lg}:{s}", {"league": lg, "season": s, "current": "true"}, DAY, {"cs_id": cs})
            for cs, lg, s, *_ in _seasons(conn)]


def leader_targets(name: str, flag: int) -> Callable[[psycopg.Connection, datetime], list[Target]]:
    def targets(conn: psycopg.Connection, at: datetime) -> list[Target]:
        return [Target(f"season:{row[1]}:{row[2]}", {"league": row[1], "season": row[2]}, DAY,
                       {"cs_id": row[0], "list": name})
                for row in _seasons(conn) if row[flag]]
    return targets


def single_target(every: timedelta, **context: Any) -> Callable[[psycopg.Connection, datetime], list[Target]]:
    def targets(conn: psycopg.Connection, at: datetime) -> list[Target]:
        return [Target("-", {}, every, dict(context))]
    return targets


def team_targets(daily_if_playing: bool, clubs_only: bool = False) -> Callable[[psycopg.Connection, datetime],
                                                                              list[Target]]:
    def targets(conn: psycopg.Connection, at: datetime) -> list[Target]:
        with conn.cursor(row_factory=tuple_row) as cur:
            cur.execute(TEAMS_SQL, {"at": at, "clubs_only": clubs_only})
            rows = cur.fetchall()
        return [Target(f"team:{tid}", {"team": int(tid)}, DAY if (daily_if_playing and playing) else WEEK, {})
                for tid, playing in rows]
    return targets


def team_season_targets(conn: psycopg.Connection, at: datetime) -> list[Target]:
    """Each team of each current tracked season: daily while it plays within 24 h, weekly otherwise (documented:
    1 call a day for teams with a match that day, else 1 a week)."""
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(TEAM_SEASONS_SQL, {"at": at})
        rows = cur.fetchall()
    return [Target(f"team:{lg}:{s}:{tp}", {"league": int(lg), "season": int(s), "team": int(tp)},
                   DAY if soon else WEEK, {"cs_id": int(cs), "team_id": int(tid)})
            for cs, lg, s, tid, tp, soon in rows]


def people_targets(kind: str, list_key: str) -> Callable[[psycopg.Connection, datetime], list[Target]]:
    """One target per person (a player who played in a current tracked season, a coach on a current line-up),
    fresh for a week; the run asks the due ones twenty at a time."""
    param = "players" if kind == "player" else "coachs"

    def targets(conn: psycopg.Connection, at: datetime) -> list[Target]:
        with conn.cursor(row_factory=tuple_row) as cur:
            cur.execute(PEOPLE_SQL[kind])
            ids = [int(r[0]) for r in cur.fetchall()]
        return [Target(f"{kind}:{i}", {param: str(i)}, WEEK, {"kind": kind, "ids": [i], "list_key": list_key})
                for i in ids]
    return targets


VENUE_REFRESH = timedelta(days=90)
"""A stadium's capacity, surface, address and picture change seldom; a venue described within 90 days (by /venues or
by the venue block of /teams) is not asked again."""

VENUES_SQL = """
WITH cur AS (
    SELECT f.venue_id, f.home_team_id, f.away_team_id, f.kickoff_at FROM core.fixtures f
      JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
      JOIN core.competitions c ON c.id = cs.competition_id
     WHERE c.is_tracked AND cs.is_current),
scope AS (
    SELECT venue_id AS id, min(kickoff_at) FILTER (WHERE kickoff_at > %(at)s) AS next_at FROM cur
     WHERE venue_id IS NOT NULL GROUP BY 1
    UNION ALL
    SELECT t.venue_id, NULL FROM core.teams t
     WHERE t.venue_id IS NOT NULL AND t.id IN (SELECT home_team_id FROM cur UNION SELECT away_team_id FROM cur))
SELECT v.provider_venue_id FROM scope s JOIN core.venues v ON v.id = s.id
 WHERE v.provider_venue_id > 0
   AND (v.source_fetched_at IS NULL OR v.source_fetched_at < %(at)s - %(refresh)s)
 GROUP BY 1
 ORDER BY min(s.next_at) NULLS LAST, 1
"""
"""Venues of the current seasons of tracked competitions (where their matches are played, and the tracked teams'
grounds) not described within ``VENUE_REFRESH``: the ones hosting the next matches first."""


def venue_targets(conn: psycopg.Connection, at: datetime) -> list[Target]:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(VENUES_SQL, {"at": at, "refresh": VENUE_REFRESH})
        return [Target(f"venue:{vid}", {"id": int(vid)}, VENUE_REFRESH, {}) for (vid,) in cur.fetchall()]


CAREER_REFRESH = timedelta(days=60)
"""/players/teams changes when a player moves, a couple of times a year at most: asked every 60 days, and at once
when the player's /transfers list changed after the last ask."""

CAREER_SQL = """
WITH people AS (
    SELECT ps.provider_player_id, max(f.kickoff_at) AS seen FROM core.fixture_player_stats ps
      JOIN core.fixtures f ON f.id = ps.fixture_id
      JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
      JOIN core.competitions c ON c.id = cs.competition_id
     WHERE c.is_tracked AND cs.is_current AND ps.provider_player_id > 0 AND coalesce(ps.minutes, 0) > 0
     GROUP BY 1)
SELECT p.provider_player_id,
       EXISTS (SELECT 1 FROM core.player_transfers x WHERE x.provider_player_id = p.provider_player_id
                 AND x.observed_at > k.checked_at) AS moved
  FROM people p
  LEFT JOIN core.reference_checks k ON k.feed = 'players_teams' AND k.target = 'player:' || p.provider_player_id
 ORDER BY p.seen DESC, 1
"""
"""The players of the people feeds (played in a current season of a tracked competition), the latest seen first;
``moved``: their transfers changed after /players/teams was last asked for them."""


def player_team_targets(conn: psycopg.Connection, at: datetime) -> list[Target]:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(CAREER_SQL)
        rows = cur.fetchall()
    return [Target(f"player:{pid}", {"player": int(pid)}, timedelta(0) if moved else CAREER_REFRESH,
                   {"ids": [int(pid)]}) for pid, moved in rows]


PROFILE_RETRY = timedelta(days=30)
"""A person the provider had no profile for is asked again a month later (a profile can appear); one it described is
then kept current by the monthly /players/profiles sweep or the weekly /coachs round."""

MISSING_PLAYER_PROFILES_SQL = """
WITH appeared AS (
    SELECT lp.provider_player_id, max(f.kickoff_at) AS seen
      FROM core.fixture_lineup_players lp JOIN core.fixtures f ON f.id = lp.fixture_id
     WHERE f.kickoff_at > %(at)s - interval '365 days' AND lp.provider_player_id > 0
     GROUP BY 1)
SELECT a.provider_player_id FROM appeared a JOIN core.players p ON p.provider_player_id = a.provider_player_id
 WHERE p.profile_fetched_at IS NULL
 ORDER BY a.seen DESC, 1
"""
"""Players in a line-up of the last 365 days whose profile no sweep of /players/profiles gave (5 Oct 2026: 6,260 -
the register's 'players: never read'). Asked one by one (``?player=``), the latest seen first."""

MISSING_COACH_PROFILES_SQL = """
SELECT x.provider_coach_id
  FROM (SELECT l.provider_coach_id, max(f.kickoff_at) AS seen FROM core.fixture_lineups l
          JOIN core.fixtures f ON f.id = l.fixture_id
         WHERE f.kickoff_at > %(at)s - interval '365 days' AND l.provider_coach_id > 0 GROUP BY 1) x
  LEFT JOIN core.coaches co ON co.provider_coach_id = x.provider_coach_id
  LEFT JOIN core.coach_profiles_latest cp ON cp.provider_coach_id = x.provider_coach_id
 WHERE NOT COALESCE(co.birth_date IS NOT NULL OR co.nationality IS NOT NULL OR cp.birth_date IS NOT NULL
                    OR cp.nationality IS NOT NULL, false)
 ORDER BY x.seen DESC, 1
"""
"""Coaches on a line-up of the last 365 days without a birth date or nationality (5 Oct 2026: 4,206): the weekly
/coachs round asks per tracked team, which misses coaches of teams outside the current seasons and those who left.
Asked by id."""


def missing_player_profile_targets(conn: psycopg.Connection, at: datetime) -> list[Target]:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(MISSING_PLAYER_PROFILES_SQL, {"at": at})
        return [Target(f"player:{pid}", {"player": int(pid)}, PROFILE_RETRY, {"ids": [int(pid)]})
                for (pid,) in cur.fetchall()]


def missing_coach_profile_targets(conn: psycopg.Connection, at: datetime) -> list[Target]:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute(MISSING_COACH_PROFILES_SQL, {"at": at})
        return [Target(f"coach:{cid}", {"id": int(cid)}, PROFILE_RETRY, {"ids": [int(cid)]})
                for (cid,) in cur.fetchall()]


def apply_player_profile(conn: psycopg.Connection, t: Target, body: dict[str, Any], payload_hash: str,
                         observed_at: datetime) -> int:
    """/players/profiles?player=: the same normalizer as the monthly sweep (a value the provider leaves empty does not
    erase one held)."""
    from fbi.ingestion.people import apply_player_profiles
    from fbi.providers.api_football.details import iter_player_profiles

    return apply_player_profiles(conn, iter_player_profiles(body), payload_hash=payload_hash,
                                 fetched_at=observed_at).updated


def merge(group: Sequence[Target], param: str) -> Target:
    """Several people's targets as one request (``players=1-2-3``)."""
    if len(group) == 1:
        return group[0]
    ids = [i for t in group for i in t.context["ids"]]
    return Target("+".join(t.key for t in group), {param: "-".join(str(i) for i in ids)}, group[0].every,
                  {**group[0].context, "ids": ids})


FEEDS: tuple[Feed, ...] = (
    Feed("predictions", "/predictions", prediction_targets, apply_predictions, max_per_run=400),
    Feed("odds_bets", "/odds/bets", single_target(DAY, catalogue="prematch"), apply_catalogue, max_per_run=1),
    Feed("odds_live_bets", "/odds/live/bets", single_target(DAY, catalogue="inplay"), apply_catalogue, max_per_run=1),
    Feed("odds_bookmakers", "/odds/bookmakers", single_target(DAY, catalogue="bookmakers"), apply_catalogue,
         max_per_run=1),
    Feed("odds_mapping", "/odds/mapping", single_target(DAY), apply_odds_mapping, max_per_run=1, paged=True,
         max_pages=MAPPING_MAX_PAGES),
    Feed("rounds", "/fixtures/rounds", round_targets, apply_rounds, max_per_run=300),
    Feed("current_round", "/fixtures/rounds", current_round_targets, apply_current_round, max_per_run=300),
    Feed("topscorers", "/players/topscorers", leader_targets("topscorers", 3), apply_leaders, max_per_run=300),
    Feed("topassists", "/players/topassists", leader_targets("topassists", 4), apply_leaders, max_per_run=300),
    Feed("topyellowcards", "/players/topyellowcards", leader_targets("topyellowcards", 5), apply_leaders,
         max_per_run=300),
    Feed("topredcards", "/players/topredcards", leader_targets("topredcards", 5), apply_leaders, max_per_run=300),
    Feed("team_statistics", "/teams/statistics", team_season_targets, apply_team_statistics, max_per_run=400),
    Feed("coachs", "/coachs", team_targets(daily_if_playing=False), apply_coachs, max_per_run=500),
    Feed("transfers", "/transfers", team_targets(daily_if_playing=False, clubs_only=True), apply_transfers,
         max_per_run=500),
    Feed("sidelined_players", "/sidelined", people_targets("player", "sidelined"), apply_sidelined, max_per_run=150, batch=BATCH_PEOPLE,
         batch_param="players"),
    Feed("sidelined_coachs", "/sidelined", people_targets("coach", "sidelined"), apply_sidelined, max_per_run=20, batch=BATCH_PEOPLE,
         batch_param="coachs"),
    Feed("trophies_players", "/trophies", people_targets("player", "trophies"), apply_trophies, max_per_run=150, batch=BATCH_PEOPLE,
         batch_param="players"),
    Feed("trophies_coachs", "/trophies", people_targets("coach", "trophies"), apply_trophies, max_per_run=20, batch=BATCH_PEOPLE,
         batch_param="coachs"),
    Feed("profiles_players", "/players/profiles", missing_player_profile_targets, apply_player_profile,
         max_per_run=100),
    Feed("coachs_by_id", "/coachs", missing_coach_profile_targets, apply_coachs, max_per_run=60),
    Feed("venues", "/venues", venue_targets, apply_venues, max_per_run=100),
    Feed("players_teams", "/players/teams", player_team_targets, apply_player_teams, max_per_run=100),
    Feed("countries", "/countries", single_target(WEEK), apply_countries, max_per_run=1),
    Feed("timezone", "/timezone", single_target(timedelta(days=90)), apply_nothing, max_per_run=1),
    Feed("leagues_seasons", "/leagues/seasons", single_target(WEEK), apply_nothing, max_per_run=1),
    Feed("players_seasons", "/players/seasons", single_target(WEEK), apply_nothing, max_per_run=1),
    Feed("teams_countries", "/teams/countries", single_target(WEEK), apply_nothing, max_per_run=1),
)


# ── the run ───────────────────────────────────────────────────────────────────────────────────────────


def last_checks(conn: psycopg.Connection, feed: str) -> dict[str, datetime]:
    with conn.cursor(row_factory=tuple_row) as cur:
        cur.execute("SELECT target, checked_at FROM core.reference_checks WHERE feed = %s", (feed,))
        return {str(a): b for a, b in cur.fetchall()}


def due_targets(conn: psycopg.Connection, feed: Feed, at: datetime) -> list[Target]:
    held = last_checks(conn, feed.name)
    due = [t for t in feed.targets(conn, at) if t.key not in held or held[t.key] <= at - t.every]
    due.sort(key=lambda t: held.get(t.key, datetime.min.replace(tzinfo=UTC)))
    return due


def record_check(conn: psycopg.Connection, feed: str, target: str, *, checked_at: datetime, payload_hash: str | None,
                 results: int | None, rows_added: int, error: str | None = None) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO core.reference_checks (feed, target, checked_at, changed_at, payload_hash, results, rows_added, "
            "error) VALUES (%(f)s, %(t)s, %(at)s, %(at)s, %(h)s, %(n)s, %(r)s, %(e)s) "
            "ON CONFLICT (feed, target) DO UPDATE SET "
            "  changed_at = CASE WHEN core.reference_checks.payload_hash IS DISTINCT FROM EXCLUDED.payload_hash "
            "                    THEN EXCLUDED.checked_at ELSE core.reference_checks.changed_at END, "
            "  checked_at = EXCLUDED.checked_at, payload_hash = EXCLUDED.payload_hash, results = EXCLUDED.results, "
            "  rows_added = EXCLUDED.rows_added, error = EXCLUDED.error "
            "WHERE core.reference_checks.checked_at <= EXCLUDED.checked_at",
            {"f": feed, "t": target, "at": checked_at, "h": payload_hash, "n": results, "r": rows_added, "e": error})


@dataclass
class ReferenceReport:
    allowance: int = 0
    reserve: int = 0
    remaining_before: int = 0
    asked: dict[str, int] = field(default_factory=dict)
    rows: dict[str, int] = field(default_factory=dict)
    due: dict[str, int] = field(default_factory=dict)
    share: int = 0
    """Requests each feed with something due may spend before any feed spends more: a backlog in one feed
    (the first sweep of 5,525 teams) never starves the feeds after it."""
    deferred_reason: str | None = None


async def refresh_reference(conn: psycopg.Connection, provider: Any, *, daily_budget: int, max_requests: int = 600,
                            feeds: Iterable[Feed] = FEEDS, at: datetime | None = None,
                            prematch_windows: Iterable[int] = (4320, 2880, 1440, 720, 360, 180)) -> ReferenceReport:
    """Ask what is due within ``max_requests`` and never into the live reserve: first a fair share for every feed
    with something due, then what is left feed by feed in priority order (predictions first)."""
    from fbi.ingestion.backfill import live_reserve
    from fbi.providers.quota import read_usage

    moment = at or now()
    report = ReferenceReport()
    report.reserve = live_reserve(conn, at=moment, prematch_windows=prematch_windows) + RESERVE_MARGIN
    report.remaining_before = read_usage(conn, budget=daily_budget).remaining
    report.allowance = max(0, min(max_requests, report.remaining_before - report.reserve))
    feeds = list(feeds)
    plan = {f.name: due_targets(conn, f, moment)[:f.max_per_run * f.batch] for f in feeds}
    conn.commit()
    report.due = {k: len(v) for k, v in plan.items() if v}
    if not report.due:
        report.deferred_reason = "nothing due"
        return report
    if not report.allowance:
        report.deferred_reason = f"live reserve: {report.remaining_before} remaining, {report.reserve} reserved"
        log.info("reference.deferred", reason=report.deferred_reason)
        return report
    ledger = RunLedger(conn)
    run_id = ledger.open("reference_refresh", params={"due": report.due, "allowance": report.allowance},
                         scheduled_for=moment)
    counters = RunCounters()
    queues = {f.name: [plan[f.name][i:i + f.batch] for i in range(0, len(plan[f.name]), f.batch)] for f in feeds}
    active = [f for f in feeds if queues[f.name]]
    report.share = max(1, report.allowance // len(active))
    spent: dict[str, int] = {}
    try:
        for limit in (report.share, None):  # a share each first, then what is left in priority order
            for feed in active:
                queue = queues[feed.name]
                while queue and (limit is None or spent.get(feed.name, 0) < limit):
                    if counters.api_calls >= report.allowance:
                        counters.stopped_early = f"allowance {report.allowance}"
                        break
                    group = queue.pop(0)
                    before = counters.api_calls
                    asked = await _ask(conn, provider, ledger, run_id, counters, report, feed,
                                       merge(group, feed.batch_param), [g.key for g in group])
                    spent[feed.name] = spent.get(feed.name, 0) + counters.api_calls - before
                    if not asked:
                        break
                if counters.stopped_early:
                    break
            if counters.stopped_early:
                break
    finally:
        ledger.close(run_id, counters, notes=", ".join(f"{k} {v} asked/{report.rows.get(k, 0)} rows"
                                                       for k, v in report.asked.items()))
        conn.commit()
    log.info("reference.done", asked=report.asked, rows=report.rows, allowance=report.allowance)
    return report


async def _ask(conn: psycopg.Connection, provider: Any, ledger: RunLedger, run_id: int, counters: RunCounters,
               report: ReferenceReport, feed: Feed, t: Target, keys: Sequence[str]) -> bool:
    """One request (every page of it) for ``t``, checked under each of ``keys``. False when the run must stop."""
    first_hash: str | None = None
    results = 0
    added = 0
    checked_at: datetime | None = None
    page = 1
    while True:
        params = {**t.params, "page": page} if feed.paged and page > 1 else dict(t.params)
        try:
            raw = await provider.fetch_raw(feed.endpoint, params)
        except QuotaExhaustedError as exc:
            counters.errors.append(str(exc))
            counters.stopped_early = "quota"
            return False
        except ProviderError as exc:
            counters.api_calls += 1
            counters.errors.append(f"{feed.name} {t.key}: {exc}"[:300])
            for k in keys:
                record_check(conn, feed.name, k, checked_at=now(), payload_hash=None, results=None, rows_added=0,
                             error=str(exc)[:300])
            conn.commit()
            return True
        counters.api_calls += 1
        report.asked[feed.name] = report.asked.get(feed.name, 0) + 1
        counters.payloads_stored += ledger.record_payloads(run_id, [raw])
        conn.commit()  # the payload is indexed whatever its normalizer then does
        observed = ledger.indexed_at(raw.payload_hash) or raw.fetched_at
        checked_at = checked_at or raw.fetched_at
        first_hash = first_hash or raw.payload_hash
        body = raw.body if isinstance(raw.body, dict) else {}
        results += len(_response(body)) if isinstance(body.get("response"), list) else (1 if body.get("response") else 0)
        try:
            added += feed.apply(conn, t, body, raw.payload_hash, observed)
        except (psycopg.Error, ValueError, KeyError, TypeError) as exc:
            conn.rollback()
            counters.errors.append(f"{feed.name} {t.key}: normalizer {type(exc).__name__}: {exc}"[:300])
            for k in keys:
                record_check(conn, feed.name, k, checked_at=raw.fetched_at, payload_hash=raw.payload_hash,
                             results=results, rows_added=0, error=f"normalizer {type(exc).__name__}"[:300])
            conn.commit()
            return True
        total = _int(_map(body.get("paging")).get("total")) or 1
        cap = feed.max_pages or MAX_PAGES
        if not feed.paged or page >= min(total, cap):
            break
        page += 1
    truncated = None
    if feed.paged and total > cap:
        truncated = f"truncated: read {page} of {total} pages (cap {cap})"
        counters.errors.append(f"{feed.name} {t.key}: {truncated}")
        log.warning("reference.truncated", feed=feed.name, target=t.key, pages=page, total=total)
    report.rows[feed.name] = report.rows.get(feed.name, 0) + added
    counters.rows_inserted += added
    found = t.context.get("found")
    for k in keys:
        if isinstance(found, dict) and len(keys) > 1:
            n = found.get(int(k.split(":")[-1]), 0)
            record_check(conn, feed.name, k, checked_at=checked_at or now(), payload_hash=first_hash, results=n,
                         rows_added=0)
        else:
            record_check(conn, feed.name, k, checked_at=checked_at or now(), payload_hash=first_hash,
                         results=results, rows_added=added, error=truncated)
    conn.commit()
    return True
