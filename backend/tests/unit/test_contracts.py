"""Every normaliser, against payloads the provider really sent.

The fixtures in ``tests/fixtures/contracts`` were extracted from our own raw store
by ``scripts.extract_contract_fixtures``: trimmed to a couple of entries, sanitised,
and carrying the sha256 of the payload they came from. No test here touches the
network, so they keep working when the provider is down, when the plan changes, and
in CI.

They exist because the two worst faults found this session were both invisible to
hand-written JSON:

  * Asian Handicap repeats the HOME handicap on both rows of a pair, so reading the
    away row verbatim inverts the sign of every away handicap;
  * `/odds` and `/odds/live` number their bets in DIFFERENT spaces, so one shared id
    map would have stored extra-time corner prices as Over/Under.

A normaliser that only ever sees what we believe the provider sends cannot catch
either.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from fbi.providers.api_football.details import (
    iter_coverage,
    iter_fixture_details,
    iter_injuries,
    iter_standings,
    iter_teams,
)
from fbi.providers.api_football.normalize import (
    OddsParseLog,
    iter_fixtures,
    iter_league_seasons,
    iter_odds,
)

CONTRACTS = Path(__file__).parents[1] / "fixtures" / "contracts"
KICKOFF = datetime(2026, 9, 28, 19, 0, tzinfo=UTC)
CAPTURED = datetime(2026, 9, 28, 18, 48, tzinfo=UTC)

SECRET_PATTERN = re.compile(
    r"apisports|x-apisports|authorization|bearer\s|api[-_]?key|[a-f0-9]{32}", re.IGNORECASE
)


def load(name: str) -> dict[str, Any]:
    path = CONTRACTS / f"{name}.json"
    if not path.is_file():
        pytest.skip(f"{path.name} has not been extracted: run scripts.extract_contract_fixtures")
    fixture: dict[str, Any] = json.loads(path.read_text())
    return fixture


def body(name: str) -> dict[str, Any]:
    payload: dict[str, Any] = load(name)["body"]
    return payload


# ── the fixtures themselves ─────────────────────────────────────────────────


def test_every_fixture_names_the_payload_it_came_from() -> None:
    """A contract fixture without provenance is just more hand-written JSON."""
    files = sorted(CONTRACTS.glob("*.json"))
    assert files, "no contract fixtures: run scripts.extract_contract_fixtures"
    for path in files:
        source = json.loads(path.read_text())["_source"]
        assert len(source["payload_sha256"]) == 64
        assert source["endpoint"].startswith("/")
        assert source["http_status"] == 200
        datetime.fromisoformat(source["fetched_at"])


def test_no_fixture_carries_anything_that_looks_like_a_credential() -> None:
    """Enforced rather than assumed: these files are in the repository for ever."""
    for path in sorted(CONTRACTS.glob("*.json")):
        text = path.read_text()
        offenders = sorted(set(SECRET_PATTERN.findall(text)))
        # The payload hash is 64 hex characters and is meant to be there.
        source_hash = json.loads(text)["_source"]["payload_sha256"]
        offenders = [o for o in offenders if o.lower() not in source_hash.lower()]
        assert offenders == [], f"{path.name}: {offenders}"


def test_a_trimmed_fixture_does_not_claim_the_full_count() -> None:
    """results is rewritten to what the file carries. Some normalisers compare the
    two, and a fixture claiming 468 results while holding 2 would be a lie."""
    for path in sorted(CONTRACTS.glob("*.json")):
        payload = json.loads(path.read_text())["body"]
        response = payload.get("response")
        if isinstance(response, list) and "results" in payload:
            assert payload["results"] == len(response), path.name


# ── /fixtures ───────────────────────────────────────────────────────────────


def test_a_real_season_fixture_list_parses() -> None:
    refs = list(iter_fixtures(body("fixtures_by_league_season")))
    assert refs, "the payload has entries and none parsed"
    first = refs[0]
    assert first.provider_fixture_id > 0
    assert first.provider_league_id > 0 and first.season > 0
    assert first.provider_home_team_id != first.provider_away_team_id
    assert first.kickoff_at.tzinfo is not None, "an aware instant, always"
    assert first.status_short


def test_a_real_date_fixture_list_parses() -> None:
    refs = list(iter_fixtures(body("fixtures_by_date")))
    assert refs and all(r.kickoff_at.tzinfo is not None for r in refs)


# ── /fixtures?ids= ──────────────────────────────────────────────────────────


def test_a_real_detail_payload_carries_all_four_blocks() -> None:
    details = list(iter_fixture_details(body("fixture_details_ids")))
    assert details
    d = details[0]
    assert d.blocks_present == frozenset({"events", "lineups", "statistics", "players"}), \
        "this is the whole reason /fixtures?ids= costs one request per twenty fixtures"
    assert d.stats and d.events and d.lineups and d.players


def test_a_real_lineup_names_eleven_starters_and_a_coach() -> None:
    details = list(iter_fixture_details(body("fixture_details_ids")))
    lineup = details[0].lineups[0]
    assert sum(1 for p in lineup.players if p.is_starter) == 11
    assert lineup.formation and lineup.provider_coach_id and lineup.coach_name


def test_real_team_statistics_are_coherent() -> None:
    """The two contradictions the schema refuses, checked against real values."""
    details = list(iter_fixture_details(body("fixture_details_ids")))
    for stats in details[0].stats:
        shots = stats.values.get("shots")
        on_target = stats.values.get("shots_on_target")
        if shots is not None and on_target is not None:
            assert on_target <= shots
        passes = stats.values.get("passes")
        accurate = stats.values.get("passes_accurate")
        if passes is not None and accurate is not None:
            assert accurate <= passes


def test_a_real_detail_payload_names_its_players_and_coaches() -> None:
    from fbi.providers.api_football.details import iter_lineup_people

    first = next(iter_fixture_details(body("fixture_details_ids")))
    players, coaches = iter_lineup_people(first)
    assert len(players) >= 22 and coaches
    assert all(p.provider_id > 0 and p.name for p in players)


# ── /odds ───────────────────────────────────────────────────────────────────


def test_a_real_odds_payload_yields_prices_for_the_markets_we_model() -> None:
    log = OddsParseLog()
    quotes = list(iter_odds(body("odds_prematch"), kickoff_at=KICKOFF, captured_at=CAPTURED,
                            payload_hash="contract", source="prematch", parse_log=log))
    assert quotes
    markets = {q.market_key for q in quotes}
    assert {"1X2", "OU", "BTTS", "DC", "AH"} & markets, markets
    assert all(q.odds_decimal > 1 for q in quotes)
    assert log.renamed_bets == [], "the catalogue names still match the payload"


def test_the_real_asian_handicap_pairs_devig_only_one_way() -> None:
    """The measurement, against the provider's own bytes rather than a transcript.

    Pair each stored Home line with the Away line of the SAME handicap - which is
    what negating the away row produces - and every pair is a book a bookmaker could
    offer. Pair them verbatim, as the payload writes them, and at least one pair pays
    out more than it takes in.

    The discriminating fact is that impossibility, not a tolerance: a real book's
    margin genuinely widens on extreme handicaps (1.045 to 1.106 across one
    bookmaker's lines here), so any tight spread assertion would be a guess.
    """
    quotes = [q for q in iter_odds(body("odds_prematch"), kickoff_at=KICKOFF,
                                   captured_at=CAPTURED, payload_hash="contract",
                                   source="prematch") if q.market_key == "AH"]
    if not quotes:
        pytest.skip("this payload carries no Asian Handicap prices")
    by_book: dict[int, dict[tuple[str, object], object]] = {}
    for q in quotes:
        by_book.setdefault(q.provider_bookmaker_id, {})[(q.selection, q.line)] = q.odds_decimal

    checked = impossible_under_the_other_reading = 0
    for priced in by_book.values():
        correct, verbatim = [], []
        for (side, line), odds in priced.items():
            if side != "Home":
                continue
            negated = priced.get(("Away", -line))  # type: ignore[operator]
            if negated is not None:
                correct.append(round(1 / odds + 1 / negated, 3))  # type: ignore[operator]
            same = priced.get(("Away", line))
            if same is not None:
                verbatim.append(round(1 / odds + 1 / same, 3))  # type: ignore[operator]
        if len(correct) < 3:
            continue
        checked += 1
        assert all(1 < b < 1.25 for b in correct), \
            f"every pair must be a book a bookmaker could offer: {correct}"
        if any(b <= 1 for b in verbatim):
            impossible_under_the_other_reading += 1

    assert checked, "no bookmaker quoted three complete handicap pairs"
    assert impossible_under_the_other_reading, \
        "reading the away row verbatim should produce a book below 1 somewhere"


def test_every_stored_handicap_line_is_a_quarter_multiple() -> None:
    from decimal import Decimal

    quotes = [q for q in iter_odds(body("odds_prematch"), kickoff_at=KICKOFF,
                                   captured_at=CAPTURED, payload_hash="contract",
                                   source="prematch") if q.market_key == "AH"]
    for q in quotes:
        assert (q.line * 4) % 1 == Decimal(0), q.line


# ── /leagues, /standings, /injuries, /teams ─────────────────────────────────


def test_a_real_leagues_payload_yields_seasons_and_coverage() -> None:
    seasons = list(iter_league_seasons(body("leagues_coverage")))
    assert seasons, "this is the payload the whole plan is priced from"
    assert len({s.season for s in seasons}) > 1, "every season, not only the current one"
    # One current season PER LEAGUE. The payload carries several leagues, which is
    # the shape of a single /leagues call.
    by_league: dict[int, int] = {}
    for s in seasons:
        by_league[s.provider_league_id] = by_league.get(s.provider_league_id, 0) + int(s.is_current)
    assert by_league and all(n <= 1 for n in by_league.values()), by_league
    assert len(by_league) > 1, "one call returns many leagues: that is why it costs one request"

    coverage = list(iter_coverage(body("leagues_coverage")))
    assert coverage
    flags = coverage[0]
    assert isinstance(flags.flags, dict) and flags.flags


def test_a_real_standings_payload_parses() -> None:
    rows = list(iter_standings(body("standings")))
    assert rows
    assert all(r.rank >= 1 for r in rows)
    assert len({r.provider_team_id for r in rows}) == len(rows), "one row per team"


def test_a_real_injuries_payload_parses() -> None:
    absences = list(iter_injuries(body("injuries")))
    assert absences
    assert all(a.provider_player_id > 0 for a in absences)


def test_a_real_teams_payload_yields_teams_and_venues() -> None:
    teams = list(iter_teams(body("teams")))
    assert teams
    assert all(t.provider_team_id > 0 and t.name for t in teams)
    assert any(t.venue is not None and t.venue.provider_venue_id for t in teams), \
        "the venue block is why this endpoint is worth normalising"
