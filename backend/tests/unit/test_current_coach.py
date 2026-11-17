"""IA-075 (AD-H03): the rule coach-current-v1 - the current coach is the one of the newest match sheet, and only strong
evidence closes another coach's open career."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from fbi.people.current_coach import (
    RULES_VERSION,
    OpenCareer,
    Sheet,
    decide,
    decide_all,
    same_person_by_names,
    summary,
)

NOW = datetime(2026, 11, 16, 12, tzinfo=UTC)
SNAP = datetime(2026, 10, 1, tzinfo=UTC)


def sheet(fid: int, days_ago: int, coach: int | None, name: str | None = None) -> Sheet:
    return Sheet(fid, NOW - timedelta(days=days_ago), coach, None, name)


def career(coach: int, start: date | None, ordinal: int = 0) -> OpenCareer:
    return OpenCareer(coach, SNAP, ordinal, start)


def test_a_change_between_two_matches_moves_the_answer_to_the_newer_coach() -> None:
    d = decide(1, [sheet(10, 14, 100, "Old"), sheet(11, 7, 200, "New")], [], now=NOW)
    assert d.current.provider_coach_id == 200 and d.current.coach_name == "New"
    assert d.current.source == "lineup" and d.current.as_of == (NOW - timedelta(days=7)).date()
    assert d.current.fixture_id == 11 and d.current.streak == 1 and d.current.fresh
    assert d.current.rules_version == RULES_VERSION


def test_an_interim_is_the_current_coach_while_on_the_bench_but_one_sheet_closes_nothing() -> None:
    opens = [career(100, date(2024, 7, 1))]
    d = decide(1, [sheet(10, 21, 100), sheet(11, 14, 100), sheet(12, 3, 300, "Caretaker")], opens, now=NOW)
    assert d.current.provider_coach_id == 300 and d.current.career_known is False
    assert d.current.contradicted == 1
    assert d.closures == ()  # a suspended head coach or an assistant for one day is not a cessation


def test_two_sheets_of_the_successor_close_the_old_career_at_his_last_match() -> None:
    opens = [career(100, date(2024, 7, 1)), career(200, None, 1)]
    d = decide(1, [sheet(10, 30, 100), sheet(11, 14, 200), sheet(12, 7, 200)], opens, now=NOW)
    assert d.current.provider_coach_id == 200 and d.current.streak == 2 and d.current.career_known
    assert d.current.since == (NOW - timedelta(days=14)).date()
    (k,) = d.closures
    assert (k.provider_coach_id, k.basis, k.end_date, k.last_fixture_id) == (
        100, "last_lineup", (NOW - timedelta(days=30)).date(), 10)
    assert k.successor_provider_coach_id == 200 and k.successor_fixture_id == 11


def test_the_providers_own_open_career_of_the_successor_is_strong_evidence_even_after_one_sheet() -> None:
    opens = [career(100, date(2023, 1, 1)), career(200, date(2026, 11, 1))]
    d = decide(1, [sheet(12, 5, 200)], opens, now=NOW)
    (k,) = d.closures
    assert k.provider_coach_id == 100 and k.basis == "before_successor"
    assert k.end_date == (NOW - timedelta(days=5)).date() - timedelta(days=1)


def test_a_career_is_never_closed_before_it_started() -> None:
    since = (NOW - timedelta(days=10)).date()
    opens = [career(100, since - timedelta(days=1))]
    d = decide(1, [sheet(11, 10, 200), sheet(12, 3, 200)], opens, now=NOW)
    (k,) = d.closures
    assert k.end_date == since - timedelta(days=1) and k.end_date >= opens[0].start_date  # type: ignore[operator]


def test_a_career_that_starts_after_the_run_began_is_not_contradicted_and_is_announced_when_after_the_last_sheet() -> None:
    opens = [career(400, (NOW - timedelta(days=2)).date())]
    d = decide(1, [sheet(11, 10, 200), sheet(12, 4, 200)], opens, now=NOW)
    assert d.closures == () and d.current.contradicted == 0
    assert d.current.announced == [400] and d.current.provider_coach_id == 200


def test_sheets_without_a_coach_are_skipped_and_counted() -> None:
    d = decide(1, [sheet(10, 20, 100), sheet(11, 9, None), sheet(12, 2, None)], [], now=NOW)
    assert d.current.provider_coach_id == 100 and d.current.sheets_without_coach == 2
    assert d.current.fixture_id == 10


def test_no_sheet_falls_back_to_the_one_open_career_only() -> None:
    one = decide(1, [], [career(100, date(2025, 7, 1))], now=NOW)
    assert one.current.source == "provider_career" and one.current.provider_coach_id == 100
    assert one.current.as_of == date(2025, 7, 1) and one.closures == ()
    two = decide(1, [sheet(10, 3, None)], [career(100, date(2025, 7, 1)), career(200, date(2020, 1, 1))], now=NOW)
    assert two.current.source is None and two.current.reason == "several_open_careers"
    assert decide(1, [], [], now=NOW).current.reason == "no_sheet"


def test_an_old_sheet_still_answers_but_is_not_fresh_and_future_sheets_are_ignored() -> None:
    d = decide(1, [sheet(10, 200, 100), Sheet(99, NOW + timedelta(days=2), 500)], [], now=NOW)
    assert d.current.provider_coach_id == 100 and not d.current.fresh


def test_decide_all_contrasts_the_providers_profile_and_summary_counts_two_current_coaches_as_none() -> None:
    sheets = [(1, sheet(10, 9, 200)), (1, sheet(11, 2, 200)), (2, sheet(20, 3, 300))]
    opens = [(1, career(100, date(2022, 1, 1))), (1, career(200, date(2026, 9, 1))), (2, career(300, None))]
    out = decide_all(sheets, opens, now=NOW, profile_teams={200: 5000, 300: 9999}, team_provider_ids={1: 5000, 2: 6000})
    assert out[1].current.profile_team_agrees is True and out[2].current.profile_team_agrees is False
    s = summary(out, open_before={1: 2, 2: 1})
    assert s["lineup"] == 2 and s["closures"] == 1 and s["closures_last_lineup"] == 0
    assert s["teams_open_gt1_before"] == 1 and s["teams_open_gt1_after"] == 0 and s["profile_disagrees"] == 1


def test_the_same_input_in_any_order_gives_the_same_answer() -> None:
    sheets = [sheet(10, 30, 100), sheet(11, 14, 200), sheet(12, 7, 200)]
    opens = [career(100, date(2024, 7, 1)), career(300, date(2019, 1, 1))]
    a = decide(1, sheets, opens, now=NOW)
    b = decide(1, list(reversed(sheets)), list(reversed(opens)), now=NOW)
    assert a.closures == b.closures and a.current.as_dict() == b.current.as_dict()


def test_two_ids_of_one_person_make_one_run_and_never_close_each_other() -> None:
    names = {100: ("Mariusz Jop",), 200: ("M. Jop",), 300: ("Tencati Claudio",), 400: ("Cláudio Tencati",),
             500: ("Kazimierz Moskal",)}
    same = same_person_by_names(names)
    assert same(100, 200) and same(300, 400) and not same(100, 500) and not same(100, 999)
    assert not same_person_by_names(names, {100: date(1970, 8, 3), 200: date(1980, 1, 1)})(100, 200)
    opens = [career(100, date(2025, 10, 1)), career(500, date(2024, 1, 1), 1)]
    d = decide(1, [sheet(10, 60, 500), sheet(11, 40, 100), sheet(12, 20, 200), sheet(13, 5, 200)], opens, now=NOW,
               same_person=same)
    assert d.current.provider_coach_id == 200 and d.current.streak == 3 and d.current.same_person_ids == [100]
    assert d.current.since == (NOW - timedelta(days=40)).date() and d.current.career_known
    assert [k.provider_coach_id for k in d.closures] == [500]
    assert d.current.open_after == 1
