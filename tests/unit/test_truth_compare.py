"""The truth audit's comparators, on small literals shaped like the provider's JSON."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from fbi.catalog.segments import CompetitionFacts, Segment, age_group_of, gender_of, segment_of
from fbi.truth import compare
from fbi.truth.findings import FINDINGS_KEPT_PER_KIND, Finding, Kind, Severity, Tally
from fbi.truth.report import render_markdown

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)
KICKOFF = NOW - timedelta(days=2)


def api_fixture(status: str = "FT", goals: tuple[int | None, int | None] = (2, 1), **extra: object) -> dict:
    item: dict = {
        "fixture": {"id": 99, "date": KICKOFF.isoformat(), "status": {"short": status}, "venue": {"id": 5}},
        "league": {"id": 39, "name": "Premier League", "season": 2026, "round": "Regular Season - 7"},
        "teams": {"home": {"id": 1, "name": "H"}, "away": {"id": 2, "name": "A"}},
        "goals": {"home": goals[0], "away": goals[1]},
        "score": {"halftime": {"home": 1, "away": 0}, "fulltime": {"home": goals[0], "away": goals[1]},
                  "extratime": {"home": None, "away": None}, "penalty": {"home": None, "away": None}},
    }
    item.update(extra)
    return item


def db_fixture(status: str = "FT", group: str = "finished", result: tuple[int, int] | None = (2, 1)) -> dict:
    row = {"provider_fixture_id": 99, "provider_league_id": 39, "season": 2026, "kickoff_at": KICKOFF,
           "status_short": status, "status_group": group, "round": "Regular Season - 7", "home_provider_id": 1,
           "away_provider_id": 2, "venue_provider_id": 5, "has_result": result is not None,
           "source_fetched_at": KICKOFF + timedelta(hours=3)}
    if result is not None:
        row.update({"goals_home": result[0], "goals_away": result[1], "ht_goals_home": 1, "ht_goals_away": 0,
                    "ft_goals_home": result[0], "ft_goals_away": result[1], "et_goals_home": None,
                    "et_goals_away": None, "pen_home": None, "pen_away": None})
    return row


def test_agreement_is_counted_not_reported() -> None:
    fixtures, results = Tally("fixtures"), Tally("results")
    compare.compare_fixture(api_fixture(), db_fixture(), now=NOW, tally=fixtures, results=results)
    assert (fixtures.checked, fixtures.matched, fixtures.total_findings) == (1, 1, 0)
    assert (results.checked, results.matched, results.total_findings) == (1, 1, 0)


def test_a_cancelled_match_stored_as_scheduled_is_a_stale_status() -> None:
    fixtures = Tally("fixtures")
    compare.compare_fixture(api_fixture("Canc", (None, None)), db_fixture("Canc", "scheduled", None), now=NOW,
                            tally=fixtures)
    kinds = {(f.field, f.kind, f.severity) for f in fixtures.findings}
    assert ("status_group", Kind.INCONSISTENT, Severity.HIGH) in kinds, "Canc -> scheduled does not follow"
    assert fixtures.matched == 0


def test_a_played_match_stored_as_not_started_is_critical() -> None:
    fixtures = Tally("fixtures")
    compare.compare_fixture(api_fixture("FT"), db_fixture("NS", "scheduled", None), now=NOW, tally=fixtures)
    [f] = [f for f in fixtures.findings if f.field == "status_short"]
    assert (f.kind, f.severity) == (Kind.STALE, Severity.CRITICAL)


def test_a_match_the_provider_has_not_updated_is_its_lag_not_ours() -> None:
    fixtures = Tally("fixtures")
    compare.compare_fixture(api_fixture("NS", (None, None)), db_fixture("NS", "scheduled", None), now=NOW,
                            tally=fixtures)
    [f] = fixtures.findings
    assert (f.kind, f.severity) == (Kind.PROVIDER_LAG, Severity.INFO)


def test_a_wrong_score_is_critical_and_a_missing_one_too() -> None:
    results = Tally("results")
    compare.compare_result(api_fixture("FT", (2, 1)), db_fixture(result=(1, 1)), tally=results, now=NOW)
    assert {(f.field, f.severity) for f in results.findings} >= {("final", Severity.CRITICAL)}
    missing = Tally("results")
    compare.compare_result(api_fixture("FT", (2, 1)), db_fixture("NS", "scheduled", None), tally=missing, now=NOW)
    [f] = missing.findings
    assert (f.kind, f.severity) == (Kind.MISSING_IN_DB, Severity.CRITICAL)


def test_a_stated_fulltime_above_the_final_is_not_held_against_us() -> None:
    """The writer ignores it (the provider contradicting itself); so must the audit."""
    item = api_fixture("AET", (2, 2))
    item["score"]["fulltime"] = {"home": 4, "away": 0}
    item["score"]["extratime"] = {"home": 0, "away": 1}
    row = db_fixture("AET", "finished", (2, 2))
    row.update({"ft_goals_home": None, "ft_goals_away": None, "et_goals_home": 0, "et_goals_away": 1})
    results = Tally("results")
    compare.compare_result(item, row, tally=results, now=NOW)
    assert results.total_findings == 0


def test_kickoff_moved_for_an_upcoming_match_is_stale_and_high() -> None:
    later = NOW + timedelta(days=1)
    item = api_fixture("NS", (None, None))
    item["fixture"]["date"] = later.isoformat()
    row = db_fixture("NS", "scheduled", None)
    row["kickoff_at"] = later - timedelta(hours=2)
    fixtures = Tally("fixtures")
    compare.compare_fixture(item, row, now=NOW, tally=fixtures)
    [f] = [f for f in fixtures.findings if f.field == "kickoff_at"]
    assert (f.kind, f.severity) == (Kind.STALE, Severity.HIGH)


def test_events_compare_as_a_multiset() -> None:
    item = api_fixture(events=[
        {"time": {"elapsed": 10, "extra": None}, "team": {"id": 1}, "player": {"id": 7}, "type": "Goal",
         "detail": "Normal Goal"},
        {"time": {"elapsed": 50, "extra": None}, "team": {"id": 2}, "player": {"id": 8}, "type": "Card",
         "detail": "Yellow Card"},
    ])
    stored = [{"minute": 10, "extra_minute": None, "event_type": "Goal", "detail": "Normal Goal",
               "provider_team_id": 1, "provider_player_id": 7}]
    t = Tally("events")
    compare.compare_events(item, stored, {"fetched_at": KICKOFF + timedelta(hours=3), "kickoff_at": KICKOFF}, tally=t)
    [f] = t.findings
    assert f.kind is Kind.MISMATCH and "1 not stored" in (f.api or "")
    same = Tally("events")
    compare.compare_events(item, [*stored, {"minute": 50, "extra_minute": None, "event_type": "card",
                                            "detail": "yellow card", "provider_team_id": 2,
                                            "provider_player_id": 8}], None, tally=same)
    assert same.matched == 1, "case of the type and detail does not matter"


def standings_body(rows: list[list[dict]]) -> dict:
    return {"response": [{"league": {"id": 253, "name": "Major League Soccer", "season": 2026, "standings": rows}}]}


def row(team: int, group: str, played: int = 26, points: int = 50) -> dict:
    return {"rank": 1, "team": {"id": team, "name": f"T{team}"}, "points": points, "goalsDiff": 3, "group": group,
            "form": "WWDLW", "status": "same", "description": "Promotion", "update": "2026-10-03T00:00:00+00:00",
            "all": {"played": played, "win": 15, "draw": 5, "lose": 6, "goals": {"for": 59, "against": 26}},
            "home": {"played": 13}, "away": {"played": 13}}


def db_row(team: int, group: str, played: int = 26, points: int = 50) -> dict:
    return {"provider_team_id": team, "group": group, "rank": 1, "points": points, "played": played, "wins": 15,
            "draws": 5, "losses": 6, "goals_for": 59, "goals_against": 26, "form": "WWDLW",
            "snapshot_at": NOW - timedelta(hours=1)}


def test_a_team_in_two_tables_is_two_rows() -> None:
    body = standings_body([[row(1, "Western Conference")], [row(1, "Supporters Shield")]])
    t = Tally("standings")
    compare.compare_standings(body, [db_row(1, "Western Conference")], label="MLS 2026",
                              last_finished=NOW - timedelta(hours=5), now=NOW, tally=t)
    missing = [f for f in t.findings if f.kind is Kind.MISSING_IN_DB]
    assert missing and "other groups" in (missing[0].db or "")


def test_a_table_behind_the_provider_is_stale() -> None:
    body = standings_body([[row(1, "Western Conference", played=27, points=53)]])
    t = Tally("standings")
    compare.compare_standings(body, [db_row(1, "Western Conference")], label="MLS 2026",
                              last_finished=NOW - timedelta(hours=5), now=NOW, tally=t)
    kinds = {(f.field, f.kind) for f in t.findings}
    assert ("played", Kind.STALE) in kinds
    assert any(f.kind is Kind.NOT_STORED for f in t.findings), "home/away and description were dropped"


def test_a_table_the_provider_updated_after_our_last_ask_is_its_lag_not_ours() -> None:
    """5 Oct 2026: twelve "stale" rows were tables the provider updated after our last ask."""
    later = row(1, "Western Conference", played=27, points=53)
    later["update"] = (NOW - timedelta(minutes=20)).isoformat()
    t = Tally("standings")
    compare.compare_standings(standings_body([[later]]), [db_row(1, "Western Conference")], label="MLS 2026",
                              last_finished=NOW - timedelta(hours=5), now=NOW, tally=t,
                              checked_at=NOW - timedelta(minutes=45))
    played = [f for f in t.findings if f.field == "played"]
    assert [(f.kind, f.severity) for f in played] == [(Kind.PROVIDER_LAG, Severity.INFO)]
    t2 = Tally("standings")
    compare.compare_standings(standings_body([[later]]), [db_row(1, "Western Conference")], label="MLS 2026",
                              last_finished=NOW - timedelta(hours=5), now=NOW, tally=t2,
                              checked_at=NOW - timedelta(minutes=5))
    assert [f.kind for f in t2.findings if f.field == "played"] == [Kind.STALE], "asked after it changed: ours"


def test_a_snapshot_older_than_the_last_match_is_stale() -> None:
    body = standings_body([[row(1, "West")]])
    old = db_row(1, "West")
    old["snapshot_at"] = NOW - timedelta(days=2)
    t = Tally("standings")
    compare.compare_standings(body, [old], label="L", last_finished=NOW - timedelta(hours=10), now=NOW, tally=t,
                              stored_extended=True)
    assert [f.kind for f in t.findings] == [Kind.STALE]


def test_odds_captured_after_the_provider_update_must_match_exactly() -> None:
    update = NOW - timedelta(hours=1)
    quotes = [{"provider_bookmaker_id": 8, "market_key": "1X2", "selection": "Home", "line": Decimal(0),
               "odds_decimal": Decimal("2.10")}]
    after = [{"provider_bookmaker_id": 8, "bookmaker": "Bet365", "market_key": "1X2", "selection": "Home",
              "line": Decimal(0), "odds_decimal": Decimal("2.05"), "captured_at": NOW - timedelta(minutes=30)}]
    t = Tally("odds")
    compare.compare_odds(quotes, {8: "Bet365", 32: "Betano"}, update, after, {8: "Bet365"}, provider_fixture_id=1,
                         kickoff=NOW + timedelta(hours=5), now=NOW, tally=t)
    kinds = {(f.field, f.kind, f.severity) for f in t.findings}
    assert ("prices", Kind.MISMATCH, Severity.HIGH) in kinds
    assert ("bookmakers", Kind.MISSING_IN_DB, Severity.MEDIUM) in kinds
    before = [dict(after[0], captured_at=NOW - timedelta(hours=4))]
    t2 = Tally("odds")
    compare.compare_odds(quotes, {8: "Bet365"}, update, before, {8: "Bet365"}, provider_fixture_id=1,
                         kickoff=NOW + timedelta(days=3), now=NOW, tally=t2)
    [f] = t2.findings
    assert (f.kind, f.severity) == (Kind.STALE, Severity.LOW)


def test_a_player_without_a_profile_is_reported_as_never_fetched() -> None:
    api = {"player": {"id": 5, "name": "A. Player", "birth": {"date": "2000-01-31"}, "nationality": "Spain",
                      "height": "180 cm", "weight": "75 kg"}}
    t = Tally("players")
    compare.compare_player(api, {"name": "A. Player", "birth_date": None, "nationality": None, "height_cm": 180,
                                 "weight_kg": None}, provider_player_id=5, tally=t)
    fields = {f.field: f for f in t.findings}
    assert fields["birth_date"].kind is Kind.MISSING_IN_DB and "never fetched" in fields["birth_date"].note
    assert "height_cm" not in fields, "180 cm equals 180"


def test_the_tally_keeps_examples_and_counts_everything() -> None:
    t = Tally("x")
    for i in range(FINDINGS_KEPT_PER_KIND + 25):
        t.add(Finding.of("x", f"e{i}", "f", Kind.MISMATCH, Severity.LOW))
    assert len(t.findings) == FINDINGS_KEPT_PER_KIND
    assert t.total_findings == FINDINGS_KEPT_PER_KIND + 25
    assert t.difference() == f"{FINDINGS_KEPT_PER_KIND + 25:,} mismatch"


def test_segments_by_name() -> None:
    assert gender_of("FA WSL") == "women" and gender_of("Feminine Division 1") == "women"
    assert gender_of("Frauen Bundesliga") == "women" and gender_of("Premier League") == "men"
    assert age_group_of("UEFA U21 Championship") == "youth" and age_group_of("Bundesliga") == "senior"
    assert segment_of(CompetitionFacts("UEFA Champions League Women", "continental", "club", 4)) is Segment.WOMEN
    assert segment_of(CompetitionFacts("Friendlies Clubs", "continental", "club", 4)) is Segment.CLUB_FRIENDLY
    assert segment_of(CompetitionFacts("Friendlies", "international", "national_team", 3)) is Segment.NATIONAL_TEAM
    assert segment_of(CompetitionFacts("Premier League", "domestic_league", "club", 1)) is Segment.TOP_LEAGUE
    assert segment_of(CompetitionFacts("Championship", "domestic_league", "club", 2)) is Segment.OTHER_LEAGUE
    assert segment_of(CompetitionFacts("FA Cup", "domestic_cup", "club", 2)) is Segment.DOMESTIC_CUP


def test_the_report_leads_with_the_matrix() -> None:
    summary = {"run_id": 1, "started_at": NOW.isoformat(), "requests": 3, "failures": [],
               "matrix": [{"dataset": "fixtures", "api": "10", "db": "9", "difference": "1 missing in db",
                           "checked": 10, "matched": 9, "freshness": "FRESH 100%", "model_safe": "YES"}],
               "freshness": [], "gate": {}, "datasets": {}}
    text = render_markdown(summary, [])
    assert "| Dataset | API | DB | Difference | Freshness | Model safe? |" in text
    assert "9/10 agree; 1 missing in db" in text


def test_a_price_is_fresh_when_it_follows_the_capture_plan() -> None:
    from fbi.truth.freshness import Freshness, price_state

    windows, tol = [4320, 2880, 1440, 720, 360, 180], 45
    ko = NOW + timedelta(hours=40)  # the T-48h window has been reached, T-24h has not

    def state(last: datetime | None, asked: datetime | None = None, covered: bool | None = True) -> Freshness:
        return price_state(kickoff=ko, at=NOW, last_capture=last, last_asked=asked, covered=covered, windows=windows,
                           tolerance=tol)[0]

    assert state(ko - timedelta(hours=47)) is Freshness.FRESH, "captured at the T-48h window"
    assert state(ko - timedelta(hours=60)) is Freshness.STALE, "only the T-72h price: the T-48h one is missing"
    assert state(None) is Freshness.STALE, "a window passed and nobody asked"
    assert state(None, asked=NOW - timedelta(hours=7)) is Freshness.UNAVAILABLE, "asked; the provider had nothing"
    far = price_state(kickoff=NOW + timedelta(days=5), at=NOW, last_capture=None, last_asked=None, covered=True,
                      windows=windows, tolerance=tol)
    assert far[0] is Freshness.FRESH and "no capture window" in far[1]


def test_a_table_is_judged_against_the_last_match_it_should_show() -> None:
    from fbi.truth.freshness import Freshness, table_reason

    last = NOW - timedelta(hours=10)
    assert table_reason(NOW - timedelta(hours=7), last, NOW - timedelta(hours=7), True) == \
        (Freshness.FRESH, "reflects_last_match")
    assert table_reason(NOW - timedelta(days=2), last, NOW - timedelta(hours=1), True) == \
        (Freshness.UNAVAILABLE, "provider_not_updated")
    assert table_reason(NOW - timedelta(days=2), last, NOW - timedelta(days=2), True) == \
        (Freshness.STALE, "not_asked_since")
    assert table_reason(None, last, None, False) == (Freshness.UNAVAILABLE, "not_covered")


def test_an_unrated_match_is_stale_only_after_the_next_elo_recompute() -> None:
    from fbi.truth.freshness import Freshness, _elo

    at = datetime(2026, 10, 4, 12, tzinfo=UTC)
    rows = [
        {"competition": "L", "season": None, "provider_fixture_id": 1, "kickoff_at": at - timedelta(days=3),
         "rated": True, "scored": True},
        {"competition": "L", "season": None, "provider_fixture_id": 2, "kickoff_at": at - timedelta(hours=5),
         "rated": False, "scored": True},   # ended 3 h ago: waiting for the next recompute
        {"competition": "L", "season": None, "provider_fixture_id": 3, "kickoff_at": at - timedelta(hours=12),
         "rated": False, "scored": True},   # a recompute has run since it ended: missed
        {"competition": "L", "season": None, "provider_fixture_id": 4, "kickoff_at": at - timedelta(days=2),
         "rated": False, "scored": False},  # no score to rate (an AET match without its 90-minute score)
    ]
    out = _elo(rows, at)
    assert out.counts[Freshness.FRESH] == 2
    assert out.counts[Freshness.STALE] == 1
    assert out.counts[Freshness.UNAVAILABLE] == 1
    assert out.status is Freshness.STALE


def test_no_result_for_a_self_contradicting_provider_score_is_the_providers_fault() -> None:
    # UEFA Europa League 2026, Pafos v Hajduk: final 2-0 after extra time, "fulltime" 4-0, "extratime" 0-2
    item = api_fixture("AET", (2, 0))
    item["score"] = {"halftime": {"home": 1, "away": 0}, "fulltime": {"home": 4, "away": 0},
                     "extratime": {"home": 0, "away": 2}, "penalty": {"home": None, "away": None}}
    results = Tally("results")
    compare.compare_result(item, db_fixture("AET", result=None), tally=results, now=NOW)
    [f] = results.findings
    assert (f.kind, f.severity) == (Kind.PROVIDER_CONTRADICTION, Severity.MEDIUM)
    assert "fulltime 4-0" in (f.api or "") and "extratime 0-2" in (f.api or "")
    from fbi.truth.v2.fixtures import evidence

    [ev] = evidence(Tally("fixtures"), results, {})
    assert (ev.issue_type, ev.at_fault) == ("RESULT_MISMATCH", "provider")
