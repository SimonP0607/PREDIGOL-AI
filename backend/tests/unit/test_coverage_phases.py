"""The phases of a cup (plan PM, PM-02-07; BE-067): ``fbi.coverage.job.cup_phases`` from the round labels the provider writes, read by
``fbi.competitions.stages`` (the one reader of a label). The labels are the provider's own for the Champions League, the Libertadores
and the FA Cup."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fbi.coverage.job import CUP_PHASES, PHASE_KNOCKOUT, PHASE_LEAGUE, PHASE_PRE, cup_phases

START = datetime(2025, 7, 8, 19, 0, tzinfo=UTC)


def _season(labels: list[tuple[str | None, int]]) -> list[tuple[int, str | None, datetime]]:
    """(label, day offset) -> rows of ``cup_phases``, ids from 1."""
    return [(i, label, START + timedelta(days=day)) for i, (label, day) in enumerate(labels, start=1)]


def test_the_champions_league() -> None:
    rows = _season([("1st Qualifying Round", 0), ("2nd Qualifying Round", 14), ("3rd Qualifying Round", 28), ("Play-offs", 42),
                    ("League Stage - 1", 70), ("League Stage - 8", 200), ("Knockout Round Play-offs", 220), ("Round of 16", 245),
                    ("Quarter-finals", 270), ("Semi-finals", 290), ("Final", 320)])
    got = cup_phases(rows)
    assert [got[i] for i in range(1, 5)] == [PHASE_PRE] * 4, "the qualifying rounds and the play-offs before the league stage"
    assert got[5] == got[6] == PHASE_LEAGUE
    assert [got[i] for i in range(7, 12)] == [PHASE_KNOCKOUT] * 5, "the knock-out play-offs after the league stage are knock-out"


def test_the_libertadores() -> None:
    rows = _season([("1st Round", 0), ("2nd Round", 10), ("3rd Round", 20), ("Group Stage - 1", 40), ("Group Stage - 6", 100),
                    ("Round of 16", 130), ("Quarter-finals", 150), ("Semi-finals", 170), ("Final", 200)])
    got = cup_phases(rows)
    assert [got[i] for i in (1, 2, 3)] == [PHASE_PRE] * 3
    assert got[4] == got[5] == PHASE_LEAGUE
    assert {got[i] for i in (6, 7, 8, 9)} == {PHASE_KNOCKOUT}


def test_the_fa_cup_has_no_league_stage() -> None:
    rows = _season([("Extra Preliminary Round", 0), ("Preliminary Round", 14), ("1st Qualifying Round", 28),
                    ("4th Qualifying Round", 70), ("1st Round", 100), ("3rd Round", 150), ("Quarter-finals", 250), ("Final", 300)])
    got = cup_phases(rows)
    assert [got[i] for i in (1, 2, 3, 4)] == [PHASE_PRE] * 4
    assert [got[i] for i in (5, 6, 7, 8)] == [PHASE_KNOCKOUT] * 4


def test_a_cup_in_one_phase_is_not_split() -> None:
    assert cup_phases(_season([("Round of 32", 0), ("Round of 16", 30), ("Quarter-finals", 60), ("Final", 120)])) == {}
    assert cup_phases(_season([("Group Stage - 1", 0), ("Group Stage - 3", 10)])) == {}
    assert cup_phases([]) == {}


def test_an_unread_label_or_a_friendly_counts_only_in_todas() -> None:
    got = cup_phases(_season([("1st Qualifying Round", 0), ("Group Stage - 1", 30), ("R60310", 40), (None, 45), ("Friendlies", 50)]))
    assert set(got) == {1, 2}, "an internal id, an empty label and a friendly have no phase"


def test_the_phase_keys_fit_the_table() -> None:
    import re

    assert all(re.fullmatch(r"[a-z][a-z0-9_]{0,31}", k) for k in CUP_PHASES)
    assert len(set(CUP_PHASES)) == 3
