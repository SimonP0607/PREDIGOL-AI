"""Live matches are ordered by how much of them can actually be shown."""

from __future__ import annotations

from fbi.api.services.live_quality import completeness


def test_a_fully_covered_match_scores_100_and_is_rich() -> None:
    score, level, signals = completeness(goals_home=1, goals_away=0, elapsed=60, events=3, stats=2, lineups=True,
                                         players=True, live_quotes=5, markets_offered=40)
    assert score == 100 and level == "rich" and all(signals.values())


def test_score_and_minute_alone_is_basic() -> None:
    score, level, signals = completeness(goals_home=0, goals_away=1, elapsed=30, events=0, stats=0, lineups=False,
                                         players=False, live_quotes=0, markets_offered=None)
    assert score == 20 and level == "basic"
    assert signals["events"] is False and signals["live_odds"] is False


def test_a_goalless_match_with_statistics_is_not_missing_events() -> None:
    _, _, signals = completeness(goals_home=0, goals_away=0, elapsed=12, events=0, stats=2, lineups=False,
                                 players=False, live_quotes=0, markets_offered=None)
    assert signals["events"] is True


def test_a_thin_in_play_book_counts_half() -> None:
    thin, _, _ = completeness(goals_home=0, goals_away=0, elapsed=1, events=0, stats=0, lineups=False,
                              players=False, live_quotes=1, markets_offered=3)
    full, _, _ = completeness(goals_home=0, goals_away=0, elapsed=1, events=0, stats=0, lineups=False,
                              players=False, live_quotes=1, markets_offered=12)
    assert full - thin == 5


def test_more_information_sorts_first() -> None:
    rich = completeness(goals_home=2, goals_away=1, elapsed=70, events=4, stats=2, lineups=True, players=False,
                        live_quotes=4, markets_offered=20)[0]
    partial = completeness(goals_home=0, goals_away=0, elapsed=70, events=0, stats=2, lineups=False,
                           players=False, live_quotes=0, markets_offered=None)[0]
    bare = completeness(goals_home=None, goals_away=None, elapsed=None, events=0, stats=0, lineups=False,
                        players=False, live_quotes=0, markets_offered=None)[0]
    assert rich > partial > bare == 0
