"""The streaks of a player at his clubs (plan F3, ``fbi.people.spells``): what each kind of evidence does, the edges, and the two
properties the dossier relies on - the history does not depend on the order of the input, and reading it as of a past day never
uses anything that happened later."""

from __future__ import annotations

import itertools
import random
from datetime import date, timedelta

import pytest

from fbi.people import spells
from fbi.people.spells import Build, Event, Spell, build, club_at

BASE = date(2024, 1, 1)


def day(n: int) -> date:
    return BASE + timedelta(days=n)


def seen(club: int, n: int, ref: int | None = None) -> Event:
    return Event(day(n), "seen", club, ref if ref is not None else n * 1000 + club)


def joined(club: int, n: int, via: str | None = None) -> Event:
    return Event(day(n), "joined", club, via=via)


def left(club: int, n: int, via: str | None = None) -> Event:
    return Event(day(n), "left", club, via=via)


def squad(club: int, n: int) -> Event:
    return Event(day(n), "squad", club)


def n_of(value: date | None) -> int | None:
    return None if value is None else (value - BASE).days


def streaks(events: list[Event]) -> list[tuple[int, int | None, int | None]]:
    """(club, first day, first day he is not there), the days counted from BASE."""
    return [(s.club, n_of(s.valid_from), n_of(s.valid_to)) for s in build(events).spells]


def club_on(events: list[Event], n: int) -> int | None:
    found = club_at(build(events).spells, day(n))
    return None if found is None else found.club


# ── what each kind of evidence does ───────────────────────────────────────────────────────────────────────────────────


def test_nothing_known_is_no_history() -> None:
    result = build([])
    assert result == Build(spells=[], phantoms=0)
    assert club_at(result.spells, day(0)) is None
    assert spells.VERSION == "spells-v1"


def test_a_chain_of_transfers_dates_every_streak() -> None:
    events = [left(1, 10, "€ 5M"), joined(2, 10, "€ 5M"), left(2, 30, "Loan"), joined(3, 30, "Loan")]
    result = build(events).spells
    assert result == [
        Spell(club=1, valid_from=None, valid_to=day(10), source="transfer", matches=0, last_evidence=day(10), via=None),
        Spell(club=2, valid_from=day(10), valid_to=day(30), source="transfer", matches=0, last_evidence=day(10), via="€ 5M"),
        Spell(club=3, valid_from=day(30), valid_to=None, source="transfer", matches=0, last_evidence=day(30), via="Loan"),
    ]


def test_a_player_who_goes_a_b_a_has_three_streaks() -> None:
    events = [seen(1, 0), seen(1, 5), seen(2, 20), seen(2, 25), seen(1, 40)]
    result = build(events).spells
    assert [(s.club, n_of(s.valid_from), n_of(s.valid_to), s.matches, s.source) for s in result] == [
        (1, 0, 20, 2, "lineup"), (2, 20, 40, 2, "lineup"), (1, 40, None, 1, "lineup")]
    assert [n_of(s.last_evidence) for s in result] == [5, 25, 40]
    # valid_from is the first day he is there, valid_to the first day he is not
    assert [club_on(events, n) for n in (-1, 0, 19, 20, 39, 40, 500)] == [None, 1, 1, 2, 2, 1, 1]


def test_the_same_match_from_two_sources_counts_once() -> None:
    twice = [seen(1, 3, ref=77), seen(1, 3, ref=77), seen(1, 3, ref=78)]
    [only] = build(twice).spells
    assert only.matches == 2
    assert only.last_evidence == day(3)


def test_a_loan_and_its_return() -> None:
    events = [seen(1, 0), left(1, 10, "Loan"), joined(2, 10, "Loan"), seen(2, 15),
              left(2, 40, "Return from loan"), joined(1, 40, "Return from loan"), seen(1, 45)]
    result = build(events).spells
    assert [(s.club, n_of(s.valid_from), n_of(s.valid_to), s.via, s.matches) for s in result] == [
        (1, 0, 10, None, 1), (2, 10, 40, "Loan", 1), (1, 40, None, "Return from loan", 1)]
    assert [s.source for s in result] == ["lineup", "transfer", "transfer"]


def test_a_return_nobody_recorded_shows_as_soon_as_he_plays() -> None:
    events = [seen(1, 0), left(1, 10), joined(2, 10), seen(2, 12), seen(1, 50)]
    assert streaks(events) == [(1, 0, 10), (2, 10, 50), (1, 50, None)]


def test_a_confirmation_does_not_open_or_close_anything() -> None:
    # the club signs him for good while he is already there
    [only] = build([seen(1, 0), joined(1, 10, "Free")]).spells
    assert (only.club, n_of(only.valid_from), only.valid_to, only.source, only.matches) == (1, 0, None, "lineup", 1)
    assert only.last_evidence == day(10)
    [later] = build([squad(1, 0), joined(1, 10, "Free")]).spells
    assert (later.source, later.via, n_of(later.valid_from), later.last_evidence) == ("squad", None, 0, day(10)), "the first streak is kept"


def test_the_first_thing_known_can_be_a_departure() -> None:
    [only] = build([left(1, 10, "Free")]).spells
    assert only == Spell(club=1, valid_from=None, valid_to=day(10), source="transfer", matches=0, last_evidence=day(10), via=None)
    assert club_on([left(1, 10)], -100) is None, "a streak with no known start is history, not where he was on a day"
    assert club_on([left(1, 10)], 5) is None
    assert club_on([left(1, 10)], 10) is None
    after = build([left(1, 10, "Free"), joined(2, 10, "Free")]).spells
    assert [(s.club, s.via) for s in after] == [(1, None), (2, "Free")], "how he came to the first club is not what the departure says"


def test_a_departure_from_a_club_he_is_not_at_changes_nothing() -> None:
    assert streaks([seen(2, 0), left(1, 10)]) == [(2, 0, None)]
    assert streaks([seen(1, 0), left(1, 10), left(3, 20)]) == [(1, 0, 10)]


# ── the squad lists: weight zero ──────────────────────────────────────────────────────────────────────────────────────


def test_a_squad_list_alone_is_a_streak_from_the_first_sighting() -> None:
    [only] = build([squad(1, 0), squad(1, 30)]).spells
    assert (only.club, n_of(only.valid_from), only.valid_to, only.source, only.matches) == (1, 0, None, "squad", 0)
    assert only.last_evidence == day(30)


def test_a_squad_list_confirms_the_club_he_is_at_and_never_takes_him_from_it() -> None:
    [only] = build([seen(1, 0), squad(2, 5), squad(2, 50), squad(1, 60)]).spells
    assert (only.club, n_of(only.valid_from), only.valid_to, only.source, only.matches) == (1, 0, None, "lineup", 1)
    assert only.last_evidence == day(60), "the list of his own club is a confirmation"
    assert streaks([joined(1, 5), squad(2, 9)]) == [(1, 5, None)], "nor a transfer's club"
    [other] = build([seen(1, 0), squad(2, 50)]).spells
    assert other.last_evidence == day(0), "the list of another club confirms nothing"


def test_a_squad_list_fills_the_gap_after_a_departure_and_a_match_ends_a_squad_streak() -> None:
    assert streaks([left(1, 10), squad(2, 20)]) == [(1, None, 10), (2, 20, None)]
    result = build([squad(2, 0), seen(1, 10)]).spells
    assert [(s.club, n_of(s.valid_from), n_of(s.valid_to), s.source) for s in result] == [(2, 0, 10, "squad"), (1, 10, None, "lineup")]


def test_a_match_beats_a_squad_list_of_the_same_day() -> None:
    result = build([squad(2, 5), seen(1, 5)])
    assert [(s.club, n_of(s.valid_from)) for s in result.spells] == [(1, 5)]
    assert result.phantoms == 1, "the club of a squad list of one day is a phantom"


# ── the edges ─────────────────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("paper", [3, 9])
def test_a_paper_transfer_is_not_a_streak_whatever_the_order_of_its_records(paper: int) -> None:
    # A -> paper club -> C on the same day (bought and lent out at once); the paper club is bigger or smaller than the others
    events = [seen(5, 4), left(5, 10), joined(paper, 10), left(paper, 10), joined(7, 10)]
    rng = random.Random(paper)
    for _ in range(12):
        rng.shuffle(events)
        result = build(events)
        assert [(s.club, n_of(s.valid_from), n_of(s.valid_to)) for s in result.spells] == [(5, 4, 10), (7, 10, None)]
        assert result.phantoms == 0, "it was skipped, not dropped"


def test_a_paper_transfer_with_no_known_origin_does_not_invent_a_streak_before_it() -> None:
    # nobody says where he came from: the paper club is not where he was before the day
    result = build([joined(9, 10), left(9, 10), joined(7, 10)])
    assert [(s.club, n_of(s.valid_from), n_of(s.valid_to)) for s in result.spells] == [(7, 10, None)]
    assert result.phantoms == 0


def test_a_match_for_the_paper_club_the_same_day_has_the_last_word() -> None:
    # he played for the paper club that day: the hardest evidence of the day is where he is at its end
    result = build([joined(9, 10), left(9, 10), joined(7, 10), seen(9, 10)])
    assert [(s.club, n_of(s.valid_from), n_of(s.valid_to), s.source) for s in result.spells] == [(9, 10, None, "lineup")]
    assert result.phantoms == 1


def test_a_transfer_contradicted_the_same_day_by_a_match_for_a_third_club_is_a_phantom() -> None:
    result = build([seen(1, 0), left(1, 10), joined(2, 10), seen(3, 10)])
    assert [(s.club, n_of(s.valid_from), n_of(s.valid_to)) for s in result.spells] == [(1, 0, 10), (3, 10, None)]
    assert result.phantoms == 1


def test_a_match_on_the_day_he_left_is_the_old_clubs() -> None:
    events = [seen(1, 0), left(1, 10), joined(2, 10), seen(1, 10, ref=777)]
    result = build(events).spells
    assert [(s.club, n_of(s.valid_from), n_of(s.valid_to), s.matches) for s in result] == [(1, 0, 10, 2), (2, 10, None, 0)]
    assert result[0].last_evidence == day(10)
    assert club_on(events, 10) == 2, "the new streak starts that day"
    # a departure with no arrival: the match still counts for the club he left, which stays left
    assert [(s.club, n_of(s.valid_to), s.matches) for s in build([seen(1, 0), left(1, 10), seen(1, 10, ref=5)]).spells] == [(1, 10, 2)]
    assert streaks([seen(1, 0), left(1, 10), seen(1, 10, ref=5), seen(1, 11, ref=6)]) == [(1, 0, 10), (1, 11, None)]


def test_the_club_of_one_day_between_two_streaks_of_the_same_club_is_nothing() -> None:
    # two arrivals on one day: the one with the larger club id has the last word, the other is a phantom
    result = build([seen(2, 0), joined(1, 10), joined(2, 10), seen(2, 20)])
    [only] = result.spells
    assert (only.club, n_of(only.valid_from), only.valid_to, only.matches) == (2, 0, None, 2)
    assert only.last_evidence == day(20)
    assert result.phantoms == 1


def test_two_arrivals_on_one_day_the_larger_club_id_has_the_last_word() -> None:
    result = build([joined(1, 10), joined(2, 10)])
    assert [(s.club, n_of(s.valid_from)) for s in result.spells] == [(2, 10)]
    assert result.phantoms == 1


def test_an_event_of_an_unknown_kind_is_refused() -> None:
    with pytest.raises(ValueError, match="unknown kind"):
        Event(day(0), "visited", 1)


# ── properties ────────────────────────────────────────────────────────────────────────────────────────────────────────


def random_history(rng: random.Random) -> list[Event]:
    out: list[Event] = []
    for i in range(rng.randint(0, 40)):
        kind = rng.choice(["seen", "seen", "seen", "joined", "left", "squad"])
        out.append(Event(day(rng.randint(0, 60)), kind, rng.randint(1, 4), ref=i + 1 if kind == "seen" else 0,
                         via=rng.choice([None, "Loan", "Free"]) if kind in ("joined", "left") else None))
    return out


def test_the_input_order_does_not_matter() -> None:
    rng = random.Random(2026)
    for _ in range(150):
        events = random_history(rng)
        want = build(events)
        for _ in range(3):
            rng.shuffle(events)
            assert build(events) == want


def test_streaks_do_not_overlap_and_are_never_empty() -> None:
    rng = random.Random(7)
    for _ in range(400):
        result = build(random_history(rng)).spells
        for before, after in itertools.pairwise(result):
            assert before.valid_to is not None, "only the last streak can be open"
            assert after.valid_from is not None, "only the first streak can have an unknown start"
            assert before.valid_to <= after.valid_from
            assert not (before.club == after.club and before.valid_to == after.valid_from), "the same club on both sides is one streak"
        for spell in result:
            if spell.valid_from is not None and spell.valid_to is not None:
                assert spell.valid_from < spell.valid_to
        for n in range(-1, 62):
            assert sum(1 for s in result if club_at([s], day(n)) is not None) <= 1


def test_reading_the_past_never_uses_the_future() -> None:
    rng = random.Random(11)
    for _ in range(250):
        events = random_history(rng)
        whole = build(events).spells
        for n in range(-1, 62, 3):
            as_of = build([e for e in events if e.day <= day(n)]).spells
            a, b = club_at(whole, day(n)), club_at(as_of, day(n))
            assert (None if a is None else a.club) == (None if b is None else b.club), (n, events)


def test_every_match_is_counted_once_unless_a_phantom_dropped_it() -> None:
    rng = random.Random(5)
    for _ in range(400):
        events = random_history(rng)
        result = build(events)
        refs = {e.ref for e in events if e.kind == "seen"}
        counted = sum(s.matches for s in result.spells)
        assert counted <= len(refs)
        if result.phantoms == 0:
            assert counted == len(refs), events
