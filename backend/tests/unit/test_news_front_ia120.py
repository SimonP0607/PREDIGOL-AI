"""The front page's order ``front-v1`` (IA-120, AD-G06): reproducible, by level then the nearness of a match then the newest; a single outlet
or a rumour never leads; «Última hora» only with a structured publication date; «Tus equipos» only from the reader's favourites; and every
empty block says why instead of being filled."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fbi.newsdesk import front
from fbi.newsdesk.front import Candidate, Followed

NOW = datetime(2026, 11, 21, 19, 0, tzinfo=UTC)
NORTE, SUR, OTRO = 1, 2, 3


def c(key: str, level: str | None, *, hours: float, structured: float | None = None, teams: tuple[int, ...] = (),
      players: tuple[int, ...] = ()) -> Candidate:
    ents = frozenset({("team", t) for t in teams} | {("player", p) for p in players})
    return Candidate(key, level, NOW - timedelta(hours=hours), None if structured is None else NOW - timedelta(hours=structured), ents)


STORIES = [
    c("st-a-un-medio", "un_medio", hours=1, structured=1, teams=(NORTE,)),
    c("st-b-oficial-lejos", "oficial", hours=6, teams=(OTRO,)),
    c("st-c-oficial-cerca", "oficial", hours=8, structured=30, teams=(SUR,)),
    c("st-d-rumor", "rumor", hours=0.5, structured=0.5, players=(77,)),
    c("st-e-sin-nivel", None, hours=2),
]
UPCOMING = {SUR: NOW + timedelta(hours=20), NORTE: NOW + timedelta(hours=40), OTRO: NOW + timedelta(days=5)}


def test_the_order_is_level_then_the_nearest_match_then_the_newest_and_the_lead_is_not_repeated() -> None:
    f = front.order(STORIES, now=NOW, followed=Followed(), upcoming=UPCOMING)
    assert f.lead == "st-c-oficial-cerca", "two official stories: the one whose team plays first leads (the other's match is too far)"
    assert f.featured == ["st-b-oficial-lejos", "st-a-un-medio", "st-d-rumor", "st-e-sin-nivel"]
    assert front.order(list(reversed(STORIES)), now=NOW, followed=Followed(), upcoming=UPCOMING) == f, "the same input, the same order"


def test_a_single_outlet_or_a_rumour_never_leads() -> None:
    f = front.order([s for s in STORIES if s.level in ("un_medio", "rumor", None)], now=NOW, followed=Followed(), upcoming=UPCOMING)
    assert f.lead is None and f.featured == ["st-a-un-medio", "st-d-rumor", "st-e-sin-nivel"]


def test_breaking_takes_only_structured_dates_of_the_last_day_newest_first() -> None:
    f = front.order(STORIES, now=NOW, followed=Followed(), upcoming=UPCOMING)
    assert f.breaking == ["st-d-rumor", "st-a-un-medio"], "the official story's structured date is 30 h old; the others have none"
    assert "st-b-oficial-lejos" not in f.breaking and "st-e-sin-nivel" not in f.breaking


def test_mine_is_the_reader_s_teams_and_players_and_none_without_favourites() -> None:
    assert front.order(STORIES, now=NOW, followed=Followed(), upcoming=UPCOMING).mine is None
    f = front.order(STORIES, now=NOW, followed=Followed(teams=frozenset({NORTE, SUR}), players=frozenset({77})), upcoming=UPCOMING)
    assert f.mine == ["st-d-rumor", "st-a-un-medio", "st-c-oficial-cerca"]
    assert front.order(STORIES, now=NOW, followed=Followed(teams=frozenset({99})), upcoming=UPCOMING).mine == []


def test_without_stories_every_block_is_empty() -> None:
    assert front.order([], now=NOW, followed=Followed(teams=frozenset({1})), upcoming={}) == front.Front(None, [], [], [])


def test_the_lists_are_cut_at_their_maximum() -> None:
    many = [c(f"st-x-{i:03d}", "un_medio", hours=i / 10, structured=i / 10, teams=(NORTE,)) for i in range(40)]
    f = front.order(many, now=NOW, followed=Followed(teams=frozenset({NORTE})), upcoming={})
    assert (len(f.featured), len(f.breaking), len(f.mine or [])) == (front.MAX_FEATURED, front.MAX_BREAKING, front.MAX_MINE)
