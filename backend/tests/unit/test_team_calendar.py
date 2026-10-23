"""A team's calendar in every competition (plan F4): what the provider's list gives, how often a team is asked about, and what rest,
congestion and "is this calendar whole?" mean once the matches of the competitions PrediGol does not follow are in it."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fbi.competitions import team_calendar as tc
from fbi.ingestion import team_calendar as ing

NOW = datetime(2026, 10, 23, 9, 0, tzinfo=UTC)
KICKOFF = NOW + timedelta(days=2)


def entry(fixture: int = 5_001, *, date: str | None = "2026-10-24T19:00:00+02:00", short: str | None = "NS", league: int = 9,
          name: str | None = "Copa del Rey", season: int = 2026, home: int | None = 541, away: int | None = 529,
          home_name: str | None = "Real Madrid", away_name: str | None = "Barcelona", goals: tuple[Any, Any] = (None, None),
          rnd: str | None = "Round of 32") -> dict[str, Any]:
    """One element of the provider's `/fixtures` answer."""
    return {"fixture": {"id": fixture, "date": date, "status": {"short": short}},
            "league": {"id": league, "name": name, "country": "Spain", "season": season, "round": rnd},
            "teams": {"home": {"id": home, "name": home_name}, "away": {"id": away, "name": away_name}},
            "goals": {"home": goals[0], "away": goals[1]}}


# ── what the provider's list gives ───────────────────────────────────────────────────────────────────────────────────────


def test_a_match_of_the_list_is_read_whole() -> None:
    [e] = list(ing.entries({"response": [entry(goals=(None, None))]}))
    assert (e.provider_fixture_id, e.provider_league_id, e.league_name, e.league_country, e.season, e.round) == (
        5_001, 9, "Copa del Rey", "Spain", 2026, "Round of 32")
    assert e.kickoff_at == datetime(2026, 10, 24, 17, 0, tzinfo=UTC), "the provider's offset is honoured and the moment kept in UTC"
    assert (e.home_provider_team_id, e.home_name, e.away_provider_team_id, e.away_name) == (541, "Real Madrid", 529, "Barcelona")
    assert (e.status_short, e.status_group, e.goals_home, e.goals_away) == ("NS", "scheduled", None, None)


def test_the_state_of_the_match_is_the_one_every_other_layer_reads() -> None:
    groups = {short: next(ing.entries({"response": [entry(short=short)]})).status_group
              for short in ("NS", "TBD", "1H", "HT", "FT", "AET", "PEN", "PST", "SUSP", "CANC", "ABD", "AWD", "WO")}
    assert groups == {"NS": "scheduled", "TBD": "scheduled", "1H": "live", "HT": "live", "FT": "finished", "AET": "finished",
                      "PEN": "finished", "PST": "postponed", "SUSP": "postponed", "CANC": "cancelled", "ABD": "cancelled",
                      "AWD": "cancelled", "WO": "cancelled"}
    [lower] = ing.entries({"response": [entry(short="canc")]})
    assert (lower.status_short, lower.status_group) == ("CANC", "cancelled"), "the provider spells the same code two ways"
    [score] = ing.entries({"response": [entry(short="FT", goals=(2, 1))]})
    assert (score.goals_home, score.goals_away) == (2, 1)


def test_an_entry_that_cannot_be_read_whole_is_left_out_never_half_written() -> None:
    bad = [entry(date=None), entry(date="2026-10-24T19:00:00"), entry(date="not a date"), entry(home=None), entry(away=0),
           entry(home=529, away=529), entry(fixture=0), entry(name=None), entry(home_name=None), entry(away_name="  "),
           {"fixture": "x", "league": {}, "teams": {}}, "text", None, {}]
    assert list(ing.entries({"response": bad})) == []
    good = entry(5_002)
    assert [e.provider_fixture_id for e in ing.entries({"response": [*bad, good]})] == [5_002]
    assert list(ing.entries({})) == [] and list(ing.entries({"response": None})) == [] and list(ing.entries({"response": {}})) == []


def test_the_columns_that_can_change_are_all_but_the_key() -> None:
    [e] = list(ing.entries({"response": [entry(short="FT", goals=(1, 0))]}))
    values = e.values()
    assert "provider_fixture_id" not in values
    assert set(values) == {"kickoff_at", "status_short", "status_group", "provider_league_id", "league_name", "league_country",
                           "season", "round", "home_provider_team_id", "home_name", "away_provider_team_id", "away_name",
                           "goals_home", "goals_away"}


# ── how often a team is asked about ──────────────────────────────────────────────────────────────────────────────────────


def test_the_nearer_the_next_match_the_fresher_the_list_has_to_be() -> None:
    def every(days: float) -> timedelta:
        return ing.every_for(NOW + timedelta(days=days), NOW)

    assert every(0.1) == every(2.0) == ing.EVERY_NEAR, "within two days: about daily"
    assert every(2.01) == every(4.0) == ing.EVERY_SOON, "within four days: about every other day"
    assert every(4.01) == every(7.0) == ing.EVERY_WEEK, "within seven: weekly"
    assert ing.EVERY_NEAR < timedelta(days=1) < ing.EVERY_SOON < timedelta(days=2) < ing.EVERY_WEEK <= timedelta(days=7)


# ── the calendar as a team lives it ──────────────────────────────────────────────────────────────────────────────────────


def match(day: float, *, status: str = "finished", followed: bool = True, competition: str = "La Liga", fixture: int | None = None,
          goals: tuple[int | None, int | None] = (2, 1)) -> tc.Match:
    """A match ``day`` days from NOW (negative: already played)."""
    return tc.Match(provider_fixture_id=fixture or 1_000 + int(day * 10) + 1_000_000, kickoff_at=NOW + timedelta(days=day),
                    status_group=status, followed=followed, home=True, opponent="Rival", competition=competition, country="Spain",
                    competition_type="domestic_league" if followed else None, season=2026, round="R", goals_for=goals[0],
                    goals_against=goals[1])


def calendar(*matches: tc.Match, fetched: float | None = -1.0, at: datetime = NOW) -> tc.TeamCalendar:
    return tc.TeamCalendar(team_id=1, at=at, matches=tuple(sorted(matches, key=lambda m: m.kickoff_at)),
                           fetched_at=None if fetched is None else NOW + timedelta(days=fetched))


def test_rest_is_counted_from_the_last_match_played_in_any_competition() -> None:
    league = match(-7.0, competition="La Liga")
    cup = match(-3.0, followed=False, competition="Copa del Rey", goals=(1, 0))
    cal = calendar(league, cup)
    assert cal.previous(KICKOFF) == cup, "the cup tie of three days ago, not the league match of a week ago"
    assert cal.rest_days(KICKOFF) == 5.0 and cal.rest_days(NOW + timedelta(days=2, hours=12)) == 5.5
    only_followed = calendar(league)
    assert only_followed.rest_days(KICKOFF) == 9.0, "the bound the packet had until now: at most what is recorded"
    assert calendar().rest_days(KICKOFF) is None and calendar().previous(KICKOFF) is None


def test_a_match_not_played_is_not_rest() -> None:
    for status in ("cancelled", "postponed", "scheduled", "live"):
        assert calendar(match(-3.0, status=status)).previous(KICKOFF) is None, status
    assert calendar(match(-3.0, status="postponed"), match(-6.0)).rest_days(KICKOFF) == 8.0


def test_nothing_after_the_moment_is_played_yet() -> None:
    """A packet built now does not count a match of the afternoon as played because it is 'finished' in the table today."""
    late = match(0.5)
    assert late.played
    assert calendar(late, match(-4.0)).previous(KICKOFF).kickoff_at == NOW - timedelta(days=4)  # type: ignore[union-attr]
    assert calendar(late, match(-4.0), at=NOW + timedelta(days=1)).previous(KICKOFF) == late, "a day later it is"


def test_matches_in_the_last_fortnight_count_every_competition() -> None:
    cal = calendar(match(-15.0), match(-13.0), match(-8.0, followed=False), match(-3.0, followed=False), match(-1.0, status="cancelled"))
    assert [m.kickoff_at for m in cal.played_within(KICKOFF, tc.FORTNIGHT)] == [NOW - timedelta(days=3), NOW - timedelta(days=8)]
    assert len(cal.played_within(KICKOFF, timedelta(days=30))) == 4
    assert len(cal.played_within(KICKOFF, timedelta(days=4))) == 0


def test_the_next_match_is_the_first_to_be_played_within_the_week() -> None:
    nxt = match(5.0, status="scheduled", followed=False, competition="Champions League")
    cal = calendar(match(3.0, status="cancelled"), match(4.0, status="postponed"), nxt, match(6.0, status="scheduled"))
    assert cal.next_after(KICKOFF) == nxt
    assert cal.next_after(KICKOFF, timedelta(days=2)) is None, "after the window it is not 'next'"
    assert calendar(match(8.5, status="scheduled")).next_after(KICKOFF) is not None, "6.5 days after the kick-off is inside the week"
    assert calendar(match(9.5, status="scheduled")).next_after(KICKOFF) is None, "7.5 days after the kick-off is outside it"
    assert calendar().next_after(KICKOFF) is None


def test_a_result_is_told_from_the_teams_side_and_only_once_played() -> None:
    assert match(-1.0, goals=(3, 2)).result() == "3-2"
    assert match(-1.0, goals=(None, None)).result() is None
    assert match(1.0, status="scheduled", goals=(None, None)).result() is None
    assert match(-1.0, status="cancelled", goals=(0, 0)).result() is None


# ── is the calendar whole? ───────────────────────────────────────────────────────────────────────────────────────────────


def test_a_fresh_list_without_doubts_is_whole() -> None:
    state = calendar(match(-3.0, followed=False), fetched=-1.0).state(KICKOFF)
    assert state == tc.CalendarState(True, None, NOW - timedelta(days=1), 24.0)


def test_a_list_never_read_or_read_too_long_ago_is_not_whole() -> None:
    assert calendar(match(-3.0), fetched=None).state(KICKOFF) == tc.CalendarState(False, "never_fetched", None, None)
    edge = calendar(fetched=-(tc.FRESH.total_seconds() / 86400)).state(KICKOFF)
    assert edge.complete, "exactly at the limit still counts"
    old = calendar(fetched=-(tc.FRESH.total_seconds() / 86400) - 0.1).state(KICKOFF)
    assert not old.complete and old.reason == "stale" and old.age_hours is not None and old.age_hours > 96


def test_a_match_whose_kickoff_has_passed_and_the_list_has_not_heard_of_is_a_doubt() -> None:
    doubt = match(-2.0, status="scheduled", followed=False)
    state = calendar(doubt, fetched=-3.0).state(KICKOFF)
    assert not state.complete and state.reason == "unconfirmed_match"
    assert calendar(doubt, fetched=-3.0).unconfirmed(KICKOFF) == [doubt]
    assert calendar(match(-2.0, status="scheduled", followed=True), fetched=-1.0).state(KICKOFF).complete, "a followed match is kept up to date"
    assert calendar(match(-20.0, status="scheduled", followed=False), fetched=-1.0).state(KICKOFF).complete, "older than a fortnight: not doubted"
    assert calendar(match(-2.0, status="postponed", followed=False), fetched=-1.0).state(KICKOFF).complete, "it was heard of: moved"
    assert calendar(match(1.0, status="scheduled", followed=False), fetched=-1.0).state(KICKOFF).complete, "a match to come is no doubt"
