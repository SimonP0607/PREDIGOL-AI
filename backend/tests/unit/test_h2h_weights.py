"""The weighted head-to-head (``fbi.intel.h2h``, plan F6) - the pure part: what a meeting weighs for the match being described, the
effective sample size, the words the narrative reads, and the two shapes (packet and page) of one and the same list."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from fbi.ai.context import PastMatch, form
from fbi.intel import h2h as h2h_mod

KICKOFF = datetime(2030, 6, 1, 18, tzinfo=UTC)
A, B, C = 1, 2, 3  # the match's home side, its away side, somebody else


def meeting(
    days: int,
    *,
    home: int = A,
    away: int = B,
    goals: tuple[int, int] = (1, 0),
    reg: tuple[int, int] | None = None,
    competition_id: int = 10,
    kind: str | None = "domestic_league",
    friendly: bool = False,
    neutral: bool = False,
    extra_time: bool = False,
    coaches: tuple[h2h_mod.Coach | None, h2h_mod.Coach | None] = (None, None),
    fixture_id: int = 0,
) -> h2h_mod.Meeting:
    r = reg or goals
    return h2h_mod.Meeting(
        fixture_id=fixture_id or days, kickoff_at=KICKOFF - timedelta(days=days), home_team_id=home, away_team_id=away,
        home=f"T{home}", away=f"T{away}", competition_id=competition_id, competition=f"Comp {competition_id}",
        competition_kind=kind, friendly=friendly, neutral=neutral, goals_home=goals[0], goals_away=goals[1],
        reg_goals_home=r[0], reg_goals_away=r[1], extra_time=extra_time, pen_home=None, pen_away=None,
        coach_home=coaches[0], coach_away=coaches[1])


def situation(**kw: object) -> h2h_mod.Situation:
    base: dict[str, object] = {"home_team_id": A, "away_team_id": B, "kickoff_at": KICKOFF, "competition_id": 10,
                               "competition_kind": "domestic_league"}
    return h2h_mod.Situation(**(base | kw))  # type: ignore[arg-type]


# ── recency, competition, ground ────────────────────────────────────────────────────────────────────────────────────────


def test_a_meeting_loses_half_its_weight_every_three_years() -> None:
    w = h2h_mod.weigh_one(meeting(1095), situation())
    assert w.w_recency == pytest.approx(0.5)
    assert h2h_mod.weigh_one(meeting(0), situation()).w_recency == 1.0
    assert h2h_mod.weigh_one(meeting(2190), situation()).w_recency == pytest.approx(0.25)


@pytest.mark.parametrize(
    ("kw", "now", "scope", "weight"),
    [
        ({}, {}, "same_competition", 1.0),
        ({"competition_id": 11}, {}, "same_kind", 0.85),
        ({"competition_id": 11, "kind": "domestic_cup"}, {}, "other_official", 0.6),
        ({"competition_id": 11, "kind": None}, {}, "other_official", 0.6),
        ({"competition_id": 12, "friendly": True}, {}, "friendly", 0.25),
        ({"competition_id": 12, "friendly": True}, {"friendly": True}, "same_kind", 0.85),
        ({"competition_id": 11}, {"friendly": True}, "other_official", 0.6),
    ],
)
def test_what_kind_of_meeting_it_was(kw: dict[str, object], now: dict[str, object], scope: str, weight: float) -> None:
    w = h2h_mod.weigh_one(meeting(100, **kw), situation(**now))  # type: ignore[arg-type]
    assert (w.scope, w.w_scope) == (scope, weight)


def test_the_ground_is_mirrored_unless_the_match_is_on_neutral_ground() -> None:
    same = h2h_mod.weigh_one(meeting(100), situation())
    assert (same.ground, same.w_ground, same.home_side_was) == ("same", 1.0, "home")
    rev = h2h_mod.weigh_one(meeting(100, home=B, away=A), situation())
    assert (rev.ground, rev.w_ground, rev.home_side_was) == ("reversed", 0.8, "away")
    neu = h2h_mod.weigh_one(meeting(100, neutral=True), situation())
    assert (neu.ground, neu.w_ground, neu.home_side_was) == ("neutral", 0.9, "neutral")
    # on neutral ground there is no ground to mirror: every meeting counts the same on that score
    on_neutral = h2h_mod.weigh_one(meeting(100, home=B, away=A), situation(neutral=True))
    assert (on_neutral.ground, on_neutral.w_ground) == ("same", 1.0)


def test_the_score_is_read_from_the_match_s_home_side_and_in_regulation_time() -> None:
    # B hosted A and won 3-1 AFTER extra time (it was 1-1 at 90 minutes): for A, the match's home side, a draw 1-1
    m = meeting(100, home=B, away=A, goals=(3, 1), reg=(1, 1), extra_time=True)
    w = h2h_mod.weigh_one(m, situation())
    assert (w.goals_home_side, w.goals_away_side, w.result) == (1, 1, "D")
    w2 = h2h_mod.weigh_one(meeting(100, home=B, away=A, goals=(0, 2)), situation())
    assert (w2.goals_home_side, w2.goals_away_side, w2.result) == (2, 0, "W")
    w3 = h2h_mod.weigh_one(meeting(100, home=B, away=A, goals=(2, 0)), situation())
    assert (w3.goals_home_side, w3.goals_away_side, w3.result) == (0, 2, "L")


# ── coaches ──────────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_a_coach_is_the_same_by_the_providers_id_or_by_the_folded_name_and_otherwise_nothing_is_guessed() -> None:
    assert h2h_mod.Coach(7, "Carlo Ancelotti").same_as(h2h_mod.Coach(7, "C. Ancelotti")) is True
    assert h2h_mod.Coach(7, "Carlo Ancelotti").same_as(h2h_mod.Coach(8, "Carlo Ancelotti")) is False, "two ids settle it"
    assert h2h_mod.Coach(None, "Ángel  Pérez").same_as(h2h_mod.Coach(None, "angel perez")) is True
    assert h2h_mod.Coach(None, "Ángel Pérez").same_as(h2h_mod.Coach(None, "Angel Gomez")) is False
    assert h2h_mod.Coach(7, None).same_as(h2h_mod.Coach(None, "Carlo Ancelotti")) is None, "an id against a name cannot be compared"
    assert h2h_mod.Coach(None, None).same_as(h2h_mod.Coach(None, None)) is None
    assert h2h_mod.Coach(7, "x").same_as(None) is None


def test_the_coach_of_each_side_then_against_the_one_it_has_now() -> None:
    now = situation(coach_home=h2h_mod.Coach(1, "Uno"), coach_away=h2h_mod.Coach(2, "Dos"))
    same = h2h_mod.weigh_one(meeting(100, coaches=(h2h_mod.Coach(1, "Uno"), h2h_mod.Coach(2, "Dos"))), now)
    assert (same.coach_changed_home, same.coach_changed_away, same.w_coach) == (False, False, 1.0)
    one = h2h_mod.weigh_one(meeting(100, coaches=(h2h_mod.Coach(9, "Nueve"), h2h_mod.Coach(2, "Dos"))), now)
    assert (one.coach_changed_home, one.coach_changed_away, one.w_coach) == (True, False, 0.75)
    both = h2h_mod.weigh_one(meeting(100, coaches=(h2h_mod.Coach(9, "Nueve"), h2h_mod.Coach(8, "Ocho"))), now)
    assert both.w_coach == pytest.approx(0.75 * 0.75)
    unknown = h2h_mod.weigh_one(meeting(100, coaches=(None, h2h_mod.Coach(2, "Dos"))), now)
    assert (unknown.coach_changed_home, unknown.coach_changed_away, unknown.w_coach) == (None, False, 0.9)
    nothing = h2h_mod.weigh_one(meeting(100), situation())
    assert nothing.coach_changed_home is None and nothing.w_coach == pytest.approx(0.81)


def test_the_coaches_are_followed_to_the_side_even_when_the_ground_was_reversed() -> None:
    now = situation(coach_home=h2h_mod.Coach(1, "Uno"), coach_away=h2h_mod.Coach(2, "Dos"))
    # in the meeting B hosted A: the bench of A is the AWAY one that day
    w = h2h_mod.weigh_one(meeting(100, home=B, away=A, coaches=(h2h_mod.Coach(2, "Dos"), h2h_mod.Coach(1, "Uno"))), now)
    assert (w.coach_changed_home, w.coach_changed_away) == (False, False)
    swapped = h2h_mod.weigh_one(meeting(100, home=B, away=A, coaches=(h2h_mod.Coach(1, "Uno"), h2h_mod.Coach(2, "Dos"))), now)
    assert (swapped.coach_changed_home, swapped.coach_changed_away) == (True, True)


def test_the_weight_is_the_product_of_the_four_factors() -> None:
    now = situation(coach_home=h2h_mod.Coach(1, "Uno"), coach_away=h2h_mod.Coach(2, "Dos"))
    m = meeting(1095, home=B, away=A, competition_id=11, coaches=(h2h_mod.Coach(2, "Dos"), h2h_mod.Coach(7, "Siete")))
    w = h2h_mod.weigh_one(m, now)
    assert w.weight == pytest.approx(0.5 * 0.85 * 0.8 * (1.0 * 0.75))


# ── the sample ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_effective_sample_size_is_kishs() -> None:
    equal = h2h_mod.weigh([meeting(30, fixture_id=i) for i in range(1, 5)], situation())
    assert equal.n == 4 and equal.n_effective == pytest.approx(4.0), "four meetings of the same weight are four"
    old_friendly = meeting(4000, competition_id=11, kind="domestic_cup", friendly=True)
    one = h2h_mod.weigh([meeting(10), old_friendly, old_friendly, old_friendly], situation())
    assert one.n == 4 and 1.0 < one.n_effective < 1.2, "one meeting carries nearly all of it"
    two = h2h_mod.weigh([meeting(10), meeting(11), old_friendly, old_friendly], situation())
    assert 1.9 < two.n_effective < 2.2
    assert h2h_mod.weigh([], situation()).n_effective == 0.0


def test_relevance_in_the_words_the_narrative_reads() -> None:
    assert h2h_mod.relevance(0.0, None) == "nula"
    assert h2h_mod.relevance(1.9, 30) == "baja"
    assert h2h_mod.relevance(5.0, 731) == "baja", "the newest meeting is two years old"
    assert h2h_mod.relevance(3.9, 30) == "media"
    assert h2h_mod.relevance(4.0, 30) == "alta"


def test_the_weighted_record_adds_up_to_one_and_leans_on_the_meetings_that_count() -> None:
    ms = [meeting(10, goals=(2, 0)), meeting(3000, goals=(0, 3), competition_id=11, kind=None, friendly=True)]
    h = h2h_mod.weigh(ms, situation())
    w = h.weighted()
    assert w is not None
    assert w["home_side_win"] + w["draw"] + w["away_side_win"] == pytest.approx(1.0, abs=0.002)
    assert w["home_side_win"] > 0.9
    assert h.record() == {"n": 2, "home_side_wins": 1, "draws": 0, "away_side_wins": 1}
    assert h2h_mod.weigh([], situation()).weighted() is None


def test_the_same_venue_record_is_not_said_on_neutral_ground() -> None:
    ms = [meeting(10, goals=(2, 0)), meeting(40, home=B, away=A, goals=(1, 1))]
    assert h2h_mod.weigh(ms, situation()).same_venue() == {"n": 1, "home_side_wins": 1, "draws": 0, "away_side_wins": 0}
    assert h2h_mod.weigh(ms, situation(neutral=True)).same_venue() is None


def test_the_coaches_summary_counts_the_meetings_by_what_is_known() -> None:
    now = situation(coach_home=h2h_mod.Coach(1, "Uno"), coach_away=h2h_mod.Coach(2, "Dos"))
    ms = [
        meeting(10, coaches=(h2h_mod.Coach(1, "Uno"), h2h_mod.Coach(2, "Dos"))),
        meeting(20, coaches=(h2h_mod.Coach(9, "Nueve"), h2h_mod.Coach(2, "Dos"))),
        meeting(30),
        meeting(40, coaches=(h2h_mod.Coach(1, "Uno"), None)),
    ]
    assert h2h_mod.weigh(ms, now).coaches() == {"both_same": 1, "some_changed": 1, "unknown": 2}


# ── the two shapes of one list ──────────────────────────────────────────────────────────────────────────────────────────


def test_the_packet_block_keeps_what_it_always_carried() -> None:
    ms = [meeting(10, goals=(2, 1)), meeting(60, home=B, away=A, goals=(0, 0)), meeting(90, goals=(1, 1), reg=(0, 0))]
    h = h2h_mod.weigh(ms, situation())
    block = h.as_packet()
    assert block["n"] == 3
    old = form(A, [PastMatch(m.kickoff_at, m.home_team_id, m.away_team_id, m.reg_goals_home, m.reg_goals_away) for m in ms])
    assert block["home_view"] == old, "the 90-minute form of the home side in these meetings, as before"
    assert (block["version"], block["status"]) == (h2h_mod.VERSION, "DESCRIPTIVE")
    assert block["weights"]["fitted"] is False and "no ajustados" in block["weights_note"]
    assert [x["fixture_id"] for x in block["meetings"]] == [m.fixture_id for m in ms]
    assert {"days_ago", "scope", "home_side_was", "goals_home_side", "goals_away_side", "weight", "coach_changed"} <= set(
        block["meetings"][0])
    assert block["oldest_days_ago"] == 90 and block["last_days_ago"] == 10


def test_the_packet_block_of_no_meetings_says_so_and_nothing_else() -> None:
    block = h2h_mod.weigh([], situation()).as_packet()
    assert block["n"] == 0 and block["relevance"] == "nula" and block["last_days_ago"] is None
    assert "meetings" not in block and "weighted" not in block


def test_the_page_rows_carry_the_final_score_the_regulation_score_and_how_it_was_decided() -> None:
    m = meeting(10, goals=(3, 2), reg=(2, 2), extra_time=True)
    rows = h2h_mod.weigh([m], situation()).as_api()
    assert len(rows) == 1
    r = rows[0]
    assert (r["goals_home"], r["goals_away"]) == (3, 2), "what the page always showed: the final score, extra time in"
    assert (r["regulation_goals_home"], r["regulation_goals_away"]) == (2, 2), "what the packet always read"
    assert r["after_extra_time"] is True and r["scope"] == "same_competition" and r["home_side_was"] == "home"
    assert r["home"] == "T1" and r["away"] == "T2"


def test_the_packet_and_the_page_list_the_same_meetings_in_the_same_order() -> None:
    ms = [meeting(10), meeting(60, home=B, away=A), meeting(90)]
    h = h2h_mod.weigh(ms, situation())
    assert [x["fixture_id"] for x in h.as_packet()["meetings"]] == [x["fixture_id"] for x in h.as_api()]
    assert [x["weight"] for x in h.as_packet()["meetings"]] == [x["weight"] for x in h.as_api()]


def test_the_ages_are_counted_from_the_kickoff_so_the_block_does_not_move_with_the_clock() -> None:
    ms = [meeting(10), meeting(500)]
    first = h2h_mod.weigh(ms, situation()).as_packet()
    second = h2h_mod.weigh(ms, situation()).as_packet()
    assert first == second


def test_a_friendly_is_the_pinned_ids_and_not_the_name() -> None:
    assert h2h_mod.is_friendly(10) and h2h_mod.is_friendly(666) and h2h_mod.is_friendly(667)
    assert not h2h_mod.is_friendly(39) and not h2h_mod.is_friendly(None)
