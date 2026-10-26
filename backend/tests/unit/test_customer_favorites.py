"""A reader's favourites, the welcome and the hints (plan UX, A13) - the rules that need no database.

Limits refuse rather than trim, a search ignores accents and case, a hint the plan does not have is refused, the switches read
as the owner writes them, and on Home a match says why it is the reader's: a followed team first (the nearer reason), then a
followed league. The database half - the table, the API, the identical boards for two readers - is
``tests/integration/test_customer_favorites.py``."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, cast

import psycopg
import pytest

from fbi.api.contracts.product import CompetitionBadge, TeamBadge
from fbi.api.contracts.today import TodayMatch
from fbi.api.services import today
from fbi.customer import favorites
from fbi.customer.db import CustomerError


class Rows:
    """A connection that answers every query with the given rows (enough for validate's two lookups)."""

    def __init__(self, *answers: Sequence[tuple[Any, ...]]) -> None:
        self.answers = list(answers)
        self.queries: list[str] = []

    def execute(self, sql: str, params: Any = None) -> Rows:
        self.queries.append(sql)
        self._next = self.answers.pop(0) if self.answers else []
        return self

    def fetchall(self) -> list[tuple[Any, ...]]:
        return list(self._next)

    def fetchone(self) -> tuple[Any, ...] | None:
        return self._next[0] if self._next else None


def conn(*answers: Sequence[tuple[Any, ...]]) -> psycopg.Connection[Any]:
    return cast("psycopg.Connection[Any]", Rows(*answers))


def test_the_limits_refuse_rather_than_trim() -> None:
    with pytest.raises(CustomerError) as leagues:
        favorites.validate(conn(), list(range(1, favorites.MAX_LEAGUES + 2)), [])
    assert (leagues.value.status, leagues.value.code) == (422, "too_many_leagues")
    with pytest.raises(CustomerError) as teams:
        favorites.validate(conn(), [], list(range(1, favorites.MAX_TEAMS + 2)))
    assert (teams.value.status, teams.value.code) == (422, "too_many_teams")
    # the same id twice counts once: ten distinct leagues and a repeat are within the limit
    ten = list(range(1, favorites.MAX_LEAGUES + 1))
    kept = favorites.validate(conn([(i,) for i in ten]), [*ten, 3], [])
    assert kept.leagues == tuple(ten) and kept.teams == ()


def test_only_leagues_predigol_follows_and_teams_that_play_in_them() -> None:
    with pytest.raises(CustomerError) as league:
        favorites.validate(conn([(1,)]), [1, 2], [])
    assert league.value.code == "unknown_league" and "2" in str(league.value)
    with pytest.raises(CustomerError) as team:
        favorites.validate(conn([(7,)]), [], [7, 8])
    assert team.value.code == "unknown_team" and "8" in str(team.value)
    chosen = favorites.validate(conn([(2,), (1,)], [(8,), (7,)]), [2, 1], [8, 7])
    assert chosen == favorites.Chosen(leagues=(2, 1), teams=(8, 7)), "kept in the reader's own order"


def test_nothing_is_asked_of_the_database_for_an_empty_choice() -> None:
    rows = Rows()
    assert favorites.validate(cast("psycopg.Connection[Any]", rows), [], []) == favorites.Chosen((), ())
    assert rows.queries == []


def test_a_search_ignores_accents_and_case() -> None:
    assert favorites.fold("Atlético NACIONAL") == favorites.fold("atletico nacional") == "atletico nacional"
    assert favorites.fold("São Paulo") == "sao paulo" and favorites.fold("Peñarol") == "penarol"
    assert len(favorites.ACCENTS[0]) == len(favorites.ACCENTS[1]), "the same pair in Python and in SQL's translate"


def test_a_hint_the_plan_does_not_have_is_refused_before_anything_is_written() -> None:
    with pytest.raises(CustomerError) as refused:
        favorites.dismiss(1, "everything", at=datetime.now(UTC))
    assert (refused.value.status, refused.value.code) == (422, "unknown_hint")
    assert favorites.HINTS == ("picks", "match", "parlay", "my_picks"), "the four pages of plan section 20"


@pytest.mark.parametrize(("raw", "on"), [(None, True), ("", True), ("  ", True), ("1", True), ("on", True),
                                         ("TRUE", True), ("0", False), ("off", False), ("no", False),
                                         ("maybe", False)])
def test_the_switches_are_born_on_and_turn_off_with_a_line(monkeypatch: pytest.MonkeyPatch, raw: str | None,
                                                           on: bool) -> None:
    for name in (favorites.ONBOARDING_SWITCH, favorites.PERSONALIZATION_SWITCH):
        if raw is None:
            monkeypatch.delenv(name, raising=False)
        else:
            monkeypatch.setenv(name, raw)
    assert favorites.onboarding_on() is on and favorites.personalization_on() is on


def test_the_welcome_is_owed_to_readers_only_once_and_never_with_the_switch_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(favorites.ONBOARDING_SWITCH, raising=False)
    done = datetime(2026, 10, 1, tzinfo=UTC)
    assert favorites.welcome_due(conn([]), 1, reader=True) is True, "no preferences yet: owed"
    assert favorites.welcome_due(conn([(None, [])]), 1, reader=True) is True
    assert favorites.welcome_due(conn([(done, [])]), 1, reader=True) is False, "once"
    assert favorites.welcome_due(conn([]), 1, reader=False) is False, "never the owner's"
    monkeypatch.setenv(favorites.ONBOARDING_SWITCH, "0")
    assert favorites.welcome_due(conn([]), 1, reader=True) is False, "FBI_ONBOARDING=0: straight to Home"


def test_a_new_account_sees_the_whole_welcome_an_older_one_the_favourites_alone() -> None:
    assert favorites.welcome_steps(conn([(True,)]), 1) == ("football", "about")
    assert favorites.welcome_steps(conn([(False,)]), 1) == ("football",)
    assert favorites.welcome_steps(conn([]), 1) == ("football",)


def match(home: tuple[int, str], away: tuple[int, str], league: tuple[int, str]) -> TodayMatch:
    return TodayMatch(
        fixture_id=1, kickoff_at=datetime(2026, 10, 26, 20, tzinfo=UTC), status_group="scheduled", status="NS",
        elapsed=None, goals_home=None, goals_away=None,
        competition=CompetitionBadge(id=league[0], name=league[1], country=None, logo_url=None, flag_url=None),
        home=TeamBadge(id=home[0], name=home[1], logo_url=None), away=TeamBadge(id=away[0], name=away[1], logo_url=None),
        suggested=False, forecast=None, headline=None, has_reading=False)


def test_a_match_says_why_it_is_the_readers_a_team_first_then_the_league() -> None:
    m = match((10, "Atlético Nacional"), (11, "Millonarios"), (5, "Liga BetPlay"))
    follows = today.Follows(leagues=(5,), teams=(11,), suggested=False)
    reason = today.why(m, follows)
    assert reason is not None and (reason.kind, reason.names) == ("team", ["Millonarios"]), "the nearer reason"
    both = today.why(m, today.Follows(leagues=(), teams=(11, 10), suggested=False))
    assert both is not None and both.names == ["Atlético Nacional", "Millonarios"], "home first"
    league = today.why(m, today.Follows(leagues=(5,), teams=(), suggested=False))
    assert league is not None and (league.kind, league.names) == ("league", ["Liga BetPlay"])
    assert today.why(m, today.Follows(leagues=(6,), teams=(12,), suggested=False)) is None, "not theirs"
