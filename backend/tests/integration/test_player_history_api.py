"""The page of a player carries his history (plan F3): the streaks at clubs and the matches with a senior national team, as the
tables ``core.player_spells`` and ``core.player_national_caps`` hold them. The API only reads them."""

from __future__ import annotations

import pytest

from fbi.api.contracts.center import PlayerDetail, PlayerNationalCap
from fbi.api.envelope import DataStatus
from fbi.api.services import center
from fbi.people import player_history
from tests.integration.test_player_history_job import small_world
from tests.integration.test_player_history_store import World, d, world  # noqa: F401  (the fixture and the data)

pytestmark = pytest.mark.integration


def page_of(w: World, provider_player: int) -> PlayerDetail:
    """The detail the API gives for a player (a row of ``core.players`` is what its id is)."""
    row = w.db.execute("INSERT INTO core.players (provider_player_id, name) VALUES (%s, 'Pedro Uno') RETURNING id", (provider_player,)).fetchone()
    assert row is not None
    page = center.player(w.db, int(row[0])).data
    assert page is not None
    return page


def caps_of(w: World, provider_player: int) -> list[PlayerNationalCap]:
    page = page_of(w, provider_player)
    assert page.national_caps is not None
    return page.national_caps.data


def test_the_page_lists_the_streaks_newest_first_and_the_caps_with_the_result(world: World) -> None:  # noqa: F811
    ids = small_world(world)
    club = world.provider(ids["club"])
    world.transfer(ids["player"], -20, club, None, names=("Alpha FC", "Out FC"))
    world.db.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away, settled_at) VALUES (%s, 3, 1, now())", (ids["national"],))
    player_history.build(world.db, apply=True, sweep=True)

    page = page_of(world, ids["player"])
    assert page.club_history is not None and page.club_history.status is DataStatus.OK
    spells = page.club_history.data
    assert [s.team for s in spells] == ["Alpha FC"] and spells[0].provider_team_id == club
    assert spells[0].team_id == ids["club"] and spells[0].valid_to is None and spells[0].source == "transfer"
    assert spells[0].valid_from == d(-20) and spells[0].matches == 2 and spells[0].last_evidence == d(5) and spells[0].via == "Free"

    assert page.national_caps is not None and page.national_caps.status is DataStatus.OK
    (cap,) = page.national_caps.data
    assert (cap.fixture_id, cap.team, cap.opponent, cap.is_starter, cap.appeared) == (ids["national"], "Spain", "Italy", True, True)
    assert (cap.goals_for, cap.goals_against) == (3, 1), "from the point of view of his team"
    assert cap.kickoff_at.date() == d(8)


def test_the_result_is_given_from_the_side_of_his_team_whichever_side_it_played(world: World) -> None:  # noqa: F811
    spain, italy = world.team("Spain", True), world.team("Italy", True)
    p = world.player()
    away = world.fixture(italy, spain, 3, national=True)         # (Spain is the visitor)
    world.lineup(away, "away", [(p, True)])
    world.db.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away, settled_at) VALUES (%s, 0, 2, now())", (away,))
    player_history.build(world.db, apply=True, sweep=True)
    (cap,) = caps_of(world, p)
    assert (cap.team, cap.opponent, cap.goals_for, cap.goals_against) == ("Spain", "Italy", 2, 0)


def test_a_player_without_history_says_so_in_both_sections(world: World) -> None:  # noqa: F811
    page = page_of(world, world.player())
    assert page.club_history is not None and page.national_caps is not None
    assert page.club_history.status is DataStatus.EMPTY and page.club_history.data == []
    assert page.club_history.reason and "No club streak" in page.club_history.reason
    assert page.national_caps.status is DataStatus.EMPTY and "senior national team" in str(page.national_caps.reason)


def test_a_squad_entry_whose_statistics_have_not_arrived_is_not_called_played(world: World) -> None:  # noqa: F811
    spain, italy = world.team("Spain", True), world.team("Italy", True)
    p = world.player()
    match = world.fixture(spain, italy, 2, national=True)
    world.lineup(match, "home", [(p, False)])                    # on the bench; no statistics of the match at all
    player_history.build(world.db, apply=True, sweep=True)
    (cap,) = caps_of(world, p)
    assert (cap.is_starter, cap.appeared, cap.minutes) == (False, None, None)
    assert (cap.goals_for, cap.goals_against) == (None, None), "no result stored"
