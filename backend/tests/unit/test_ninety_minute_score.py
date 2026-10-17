"""The 90-minute score is read from the provider, never reconstructed by subtraction.

Four columns settle the core markets and all four derived it as
``goals - COALESCE(et_goals, 0)``. That is right only while ``extratime`` means "goals
scored during extra time". Measured across the 1,645 extra-time fixtures in the raw
store: the increment on 1,557, the RUNNING TOTAL on 82, neither on 4. In those 82 the
subtraction gives 0, so a tie that stood 2-1 after ninety minutes was stored as 0-0 and
settled 'Draw' - 78 rows in the database were wrong that way.

The provider states the score at ninety minutes in ``score.fulltime``. These tests pin
reading it, and pin the two guards that let the fault through.
"""

from __future__ import annotations

from typing import Any

from fbi.providers.api_football.normalize import ScoreDisagreement, iter_fixture_results


def payload(*entries: dict[str, Any]) -> dict[str, Any]:
    return {"response": list(entries)}


def fixture(fid: int, status: str, *, goals: tuple[int, int],
            halftime: tuple[int | None, int | None] = (None, None),
            fulltime: tuple[int | None, int | None] = (None, None),
            extratime: tuple[int | None, int | None] = (None, None),
            penalty: tuple[int | None, int | None] = (None, None)) -> dict[str, Any]:
    def block(pair: tuple[int | None, int | None]) -> dict[str, int | None]:
        return {"home": pair[0], "away": pair[1]}
    return {
        "fixture": {"id": fid, "status": {"short": status}},
        "goals": block(goals),
        "score": {"halftime": block(halftime), "fulltime": block(fulltime),
                  "extratime": block(extratime), "penalty": block(penalty)},
    }


def only(body: dict[str, Any], **kwargs: Any) -> Any:
    got = list(iter_fixture_results(body, **kwargs))
    assert len(got) == 1, f"expected one result, got {len(got)}"
    return got[0]


# ── the corruption that was measured ────────────────────────────────────────


def test_a_running_total_extratime_no_longer_flattens_the_score_to_a_draw() -> None:
    """The exact shape of the 78 wrong rows: extratime equals goals, so goals minus
    extratime is 0-0 and a 2-1 tie settled as a draw."""
    r = only(payload(fixture(65915, "AET", goals=(3, 1), fulltime=(2, 1), extratime=(3, 1))))
    assert (r.ft_goals_home, r.ft_goals_away) == (2, 1)
    assert (r.goals_home, r.goals_away) == (3, 1), "the final score is kept as the provider gives it"


def test_the_disagreement_is_recorded_rather_than_hidden() -> None:
    """It is the provider contradicting itself, not our arithmetic, so it is the
    caller's to record - as a fact with fields, not a log line."""
    notes: list[ScoreDisagreement] = []
    only(payload(fixture(65915, "AET", goals=(3, 1), fulltime=(2, 1), extratime=(3, 1))),
         disagreements=notes)
    assert len(notes) == 1
    assert notes[0].provider_fixture_id == 65915
    assert notes[0].dropped is False, "the stated fulltime is still used"
    assert "fulltime 2-1" in notes[0].observed


def test_an_incremental_extratime_agrees_and_records_nothing() -> None:
    notes: list[ScoreDisagreement] = []
    r = only(payload(fixture(1378902, "AET", goals=(3, 1), fulltime=(2, 1), extratime=(1, 0))),
             disagreements=notes)
    assert (r.ft_goals_home, r.ft_goals_away) == (2, 1)
    assert notes == [], "1,557 of 1,645 fixtures look like this; they are not a problem"


# ── the fixtures that had no result row at all ──────────────────────────────


def test_penalties_straight_after_ninety_minutes_now_produce_a_result() -> None:
    """A null extratime on a PEN fixture is not missing data: the tie went from ninety
    minutes straight to penalties, and fulltime says the score. Six Champions League
    ties had no result row because this was skipped wholesale."""
    r = only(payload(fixture(1591938, "PEN", goals=(1, 0), halftime=(1, 0), fulltime=(1, 0),
                             penalty=(6, 5))))
    assert (r.ft_goals_home, r.ft_goals_away) == (1, 0)
    assert (r.pen_home, r.pen_away) == (6, 5), "the shoot-out decides the tie, not the market"


def test_extra_time_with_neither_a_stated_score_nor_a_breakdown_is_still_refused() -> None:
    """`goals` includes extra time, so on its own it cannot settle a 1X2. Better an
    awaited result than a wrong one."""
    assert list(iter_fixture_results(payload(
        fixture(1, "AET", goals=(3, 1))))) == []


# ── invariants ─────────────────────────────────────────────────────────────


def test_a_ninety_minute_score_above_the_final_score_is_refused_not_stored() -> None:
    """Impossible: goals includes extra time and excludes penalties, so it can only be
    greater or equal. The row is kept, without the impossible value."""
    r = only(payload(fixture(2, "FT", goals=(1, 0), fulltime=(3, 0))))
    assert r.ft_goals_home is None and r.ft_goals_away is None
    assert (r.goals_home, r.goals_away) == (1, 0)


def test_extra_time_above_the_final_score_is_still_refused() -> None:
    assert list(iter_fixture_results(payload(
        fixture(3, "AET", goals=(1, 0), fulltime=(1, 0), extratime=(5, 0))))) == []


def test_a_normal_full_time_fixture_is_unaffected() -> None:
    r = only(payload(fixture(4, "FT", goals=(2, 1), halftime=(1, 0), fulltime=(2, 1))))
    assert (r.ft_goals_home, r.ft_goals_away) == (2, 1)
    assert (r.et_goals_home, r.et_goals_away) == (None, None)


def test_a_fixture_that_has_not_finished_yields_nothing() -> None:
    assert list(iter_fixture_results(payload(
        fixture(5, "NS", goals=(0, 0))))) == []


# ── the provider contradicting itself, recorded rather than left a mystery ───


def test_a_fulltime_above_the_final_score_is_recorded_as_a_contradiction() -> None:
    """Five finished AET fixtures on the machine look like this - fulltime 4-0 with a
    final of 2-0. Impossible, and an operator later asking why the match has no result
    deserves the provider's own numbers as the answer."""
    notes: list[ScoreDisagreement] = []
    only(payload(fixture(1477537, "FT", goals=(2, 0), fulltime=(4, 0))), disagreements=notes)
    assert len(notes) == 1
    assert notes[0].provider_fixture_id == 1477537
    assert notes[0].dropped is False, "only the impossible field is ignored; the row still lands"
    assert "4-0" in notes[0].observed and "2-0" in notes[0].observed


def test_an_extratime_above_the_final_score_is_recorded_and_the_fixture_dropped() -> None:
    """extratime 0-2 with a final of 2-0: the numbers contradict each other and nothing
    says which is wrong, so no result is written - and that is now explained."""
    notes: list[ScoreDisagreement] = []
    got = list(iter_fixture_results(
        payload(fixture(1593527, "AET", goals=(2, 0), fulltime=(4, 0), extratime=(0, 2))),
        disagreements=notes))
    assert got == [], "a self-contradictory score yields no result"
    assert any(n.dropped and n.field == "et_goals_home" for n in notes)


def test_extra_time_with_nothing_to_derive_from_is_recorded_too() -> None:
    notes: list[ScoreDisagreement] = []
    assert list(iter_fixture_results(payload(fixture(7, "AET", goals=(3, 1))),
                                     disagreements=notes)) == []
    assert len(notes) == 1 and notes[0].dropped is True
