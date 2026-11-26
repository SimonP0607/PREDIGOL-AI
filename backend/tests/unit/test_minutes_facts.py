"""RP-4.3, second tranche: the minutes of the usual starters and the probable rotation (``fbi.ai.minutes_facts``). The line-ups are built by hand so every
number is known: a usual starter is the one who opened at least 60 % of the last five matches with a full line-up, the minutes count only the 14 days before the
match and only matches with statistics, the rotation needs the rest to be short AND the team's own history to show the drop, it is never said without enough pairs,
and it can only be «probable». The database side is ``tests/integration/test_minutes_facts_db.py``."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fbi.ai import calendar_facts as cf
from fbi.ai import factor_schema
from fbi.ai import minutes_facts as mf
from fbi.ai import stakes_facts as sf

KICKOFF = datetime(2026, 11, 28, 20, tzinfo=UTC)
XI = tuple(range(1, 12))


def game(fid: int, days_before: float, starters: tuple[int, ...] = XI, *, minutes: int | None = 90) -> mf.Game:
    return mf.Game(fid, KICKOFF - timedelta(days=days_before), frozenset(starters),
                   {} if minutes is None else dict.fromkeys(starters, minutes))


def test_a_usual_starter_opened_at_least_sixty_percent_of_the_last_five_full_lineups() -> None:
    games = [game(i, 30 - 5 * i, XI if i < 4 else (*range(1, 10), 20, 21)) for i in range(1, 6)]
    found = mf.usual_starters(games, KICKOFF)
    assert found is not None
    players, recent = found
    assert len(recent) == 5 and players == frozenset(range(1, 12)), "20 and 21 started only 2 of 5, 10 and 11 started 3 of 5"


def test_fewer_than_three_full_lineups_say_nothing() -> None:
    assert mf.usual_starters([game(1, 5), game(2, 10)], KICKOFF) is None
    short = mf.Game(3, KICKOFF - timedelta(days=3), frozenset(range(1, 10)), {})
    assert mf.usual_starters([game(1, 5), game(2, 10), short], KICKOFF) is None, "a line-up of nine is not a full line-up"
    assert mf.minutes_fact([game(1, 5), game(2, 10)], KICKOFF, "Leones") is None


def test_the_minutes_count_only_the_fortnight_before_and_only_matches_with_statistics() -> None:
    games = [game(1, 20), game(2, 12, minutes=90), game(3, 6, minutes=60), game(4, 3, minutes=None), game(5, 1, minutes=90)]
    fact = mf.minutes_fact(games, KICKOFF, "Leones")
    assert fact is not None
    calc = fact.calculation
    assert calc["usual_starters"] == 11 and calc["matches_in_14d"] == 3 and calc["fixtures_in_14d"] == [2, 3, 5]
    assert calc["mean_minutes"] == 240.0 and calc["heavy_180_or_more"] == 11 and calc["max_minutes"] == calc["min_minutes"] == 240
    assert "sus 11 titulares habituales" in fact.claim and "240,0 minutos de media en los 14 días anteriores, en 3 partidos con estadísticas" in fact.claim
    assert "11 de ellos jugó 180 minutos o más" in fact.claim and fact.certainty is None and fact.kind == "schedule"
    assert not any(w in fact.claim for w in ("cansad", "fatiga", "desgaste"))


def test_without_a_match_of_the_fortnight_with_statistics_there_is_no_minutes_fact() -> None:
    assert mf.minutes_fact([game(1, 30), game(2, 25), game(3, 20), game(4, 3, minutes=None)], KICKOFF, "Leones") is None


def test_a_match_played_after_the_kickoff_asked_is_never_used() -> None:
    games = [game(1, 30), game(2, 25), game(3, 20), game(4, 2), game(5, -1)]
    fact = mf.minutes_fact(games, KICKOFF, "Leones")
    assert fact is not None and fact.calculation["fixtures_in_14d"] == [4]


def history(short_repeat: int, long_repeat: int, *, short_n: int = 3, long_n: int = 3) -> list[mf.Game]:
    """Pairs of full line-ups: ``short_n`` pairs 3 days apart that repeat ``short_repeat`` starters and ``long_n`` pairs 7 days apart that repeat ``long_repeat``."""
    games: list[mf.Game] = []
    day, current = 170.0, set(XI)
    spec = [(3.0, short_repeat)] * short_n + [(7.0, long_repeat)] * long_n
    games.append(mf.Game(0, KICKOFF - timedelta(days=day), frozenset(current), {}))
    fresh = 100
    for fid, (gap, repeat) in enumerate(spec, start=1):
        day -= gap
        kept = sorted(current)[:repeat]
        new = set(kept) | set(range(fresh, fresh + 11 - repeat))
        fresh += 20
        games.append(mf.Game(fid, KICKOFF - timedelta(days=day), frozenset(new), {}))
        current = new
    return games


def test_a_probable_rotation_needs_a_short_rest_and_the_pattern_in_the_teams_own_history() -> None:
    games = history(short_repeat=7, long_repeat=10)
    fact = mf.rotation_fact(games, KICKOFF, 3.0, "Leones")
    assert fact is not None and fact.certainty == "probable" and fact.kind == "rotation" and fact.story == "rotation"
    assert fact.calculation["pairs_short"] == 3 and fact.calculation["pairs_longer"] == 3
    assert fact.calculation["mean_repeated_short"] == 7.0 and fact.calculation["mean_repeated_longer"] == 10.0 and fact.calculation["difference"] == 3.0
    assert "rotación probable" in fact.claim and "7,0 de 11 titulares" in fact.claim and "no una alineación anunciada" in fact.claim
    assert mf.rotation_fact(games, KICKOFF, 5.0, "Leones") is None, "the rest before this match is longer than 4 days"
    assert mf.rotation_fact(games, KICKOFF, None, "Leones") is None, "no calendar, no rest: nothing is said"


def test_the_history_must_show_a_drop_of_one_and_a_half_starters_with_at_least_three_pairs_each_way() -> None:
    assert mf.rotation_fact(history(9, 10), KICKOFF, 3.0, "Leones") is None, "a drop of one starter is not a pattern"
    assert mf.rotation_fact(history(7, 10), KICKOFF, 3.0, "Leones") is not None
    assert mf.rotation_fact(history(8, 10, short_n=2), KICKOFF, 3.0, "Leones") is None, "two short pairs are too few"
    assert mf.rotation_fact(history(7, 10, long_n=2), KICKOFF, 3.0, "Leones") is None, "two long pairs are too few"
    assert mf.rotation_fact(history(10, 7), KICKOFF, 3.0, "Leones") is None, "more rotation with more rest is the opposite of the pattern"


def test_the_rotation_is_an_informacion_probable_and_never_a_confirmed_fact() -> None:
    assert factor_schema.category_of("PROBABLE", "own_calc", None, "probable") == "informacion_probable"
    assert factor_schema.category_of("CONFIRMED", "own_calc", None, "probable") == "informacion_probable"
    assert factor_schema.category_of("PROBABLE", "own_calc") == "hecho_confirmado", "the calculated facts of before are untouched"
    assert factor_schema.category_of("PROBABLE", "web", "media", "probable") == "informacion_probable"
    assert factor_schema.category_of("RUMOR", "web", "social", "probable") == "rumor", "only our own calculation can say it of itself"


def side(story: mf.Derived) -> cf.SideFact:
    match = sf.Match(10, KICKOFF, 1, 2)
    return cf.SideFact(match, 1, "home", story.claim, story.calculation, story.kind, story.claim_type, story.story, story.certainty)


def test_both_facts_become_complete_items_of_their_own_story_and_the_rotation_says_it_is_probable() -> None:
    at = KICKOFF - timedelta(days=2)
    minutes = mf.minutes_fact([game(1, 30), game(2, 25), game(3, 20), game(4, 3)], KICKOFF, "Leones")
    rotation = mf.rotation_fact(history(7, 10), KICKOFF, 3.0, "Leones")
    assert minutes is not None and rotation is not None
    a, b = cf.item_of(side(minutes), at=at), cf.item_of(side(rotation), at=at)
    for item in (a, b):
        assert item.origin == "own_calc" and item.fact_schema == factor_schema.VERSION and item.fresh_until == KICKOFF and item.side == "home"
        assert factor_schema.missing(item.fact_view()) == [], "complete in the seven attributes"
    assert (a.kind, a.claim_type, a.story_key) == ("schedule", "SCHEDULE", "minutes:10:1") and a.attributes["calculation"] == mf.VERSION
    assert "certainty" not in a.attributes
    assert (b.kind, b.claim_type, b.story_key) == ("rotation", "OTHER", "rotation:10:1") and b.attributes["certainty"] == "probable"
    assert b.confidence < a.confidence and b.relevance <= a.relevance


def test_no_fact_names_a_player_or_judges_the_condition_of_the_team() -> None:
    minutes = mf.minutes_fact([game(1, 30), game(2, 25), game(3, 20), game(4, 3)], KICKOFF, "Leones")
    rotation = mf.rotation_fact(history(7, 10), KICKOFF, 3.0, "Leones")
    assert minutes is not None and rotation is not None
    for fact in (minutes, rotation):
        assert len(fact.claim) <= mf.MAX_CLAIM and "player" not in str(fact.calculation.keys())
        assert not any(w in fact.claim.lower() for w in ("cansad", "fatiga", "lesion", "lesión", "probabilidad de ganar"))
