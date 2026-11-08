"""IA-019: the owner's diagnosis of a match's news - the pass it waits for (``next_pass``, the rule of ``fbi.ai.day.due_pass``) and the
verdict (``verdict``: the first reason that applies). Pure: no database."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from fbi.ai.calendar import DAY_TZ, local_day
from fbi.ai.day import due_pass
from fbi.api.contracts.news import DiagnosisExa, DiagnosisNextPass, DiagnosisPass, DiagnosisSearches
from fbi.api.services.news_diagnosis import (
    Facts,
    next_pass,
    opens_at,
    pages_read,
    pass_of,
    searched_at,
    verdict,
)

KICKOFF = datetime(2026, 11, 8, 21, 0, tzinfo=UTC)  # 16:00 in Bogotá, Sunday 8 November
DAY = local_day(KICKOFF)
H, M = timedelta(hours=1), timedelta(minutes=1)


# ── the pass a match waits for ──────────────────────────────────────────────────────────────────────────────────────


def test_the_day_opens_at_five_past_midnight_in_bogota() -> None:
    assert opens_at(date(2026, 11, 8)) == datetime(2026, 11, 8, 0, 5, tzinfo=DAY_TZ)
    assert opens_at(DAY).astimezone(UTC) == datetime(2026, 11, 8, 5, 5, tzinfo=UTC)


def test_before_the_day_opens_the_first_pass_is_expected_at_the_opening() -> None:
    nxt = next_pass(KICKOFF, at=KICKOFF - 20 * H, done={})
    assert nxt is not None and nxt.kind == "first" and not nxt.due_now
    assert nxt.window_from == opens_at(DAY) and nxt.window_until == KICKOFF - 10 * M


def test_once_the_day_opened_the_first_pass_is_due() -> None:
    nxt = next_pass(KICKOFF, at=opens_at(DAY) + 30 * M, done={})
    assert nxt is not None and nxt.kind == "first" and nxt.due_now


def test_after_the_first_the_pre_pass_from_six_hours_and_two_after_the_first() -> None:
    first = opens_at(DAY) + 10 * M
    nxt = next_pass(KICKOFF, at=first + H, done={"first": first})
    assert nxt is not None and nxt.kind == "pre" and not nxt.due_now
    assert nxt.window_from == KICKOFF - 6 * H and nxt.window_until == KICKOFF - 90 * M
    late = KICKOFF - 5 * H  # a first pass this late: the pre waits two hours after it
    nxt = next_pass(KICKOFF, at=late + M, done={"first": late})
    assert nxt is not None and nxt.kind == "pre" and nxt.window_from == late + 2 * H


def test_when_the_pre_window_cannot_open_the_final_is_next() -> None:
    late = KICKOFF - 3 * H  # first + 2 h = 1 h before: after the pre's 90 min
    nxt = next_pass(KICKOFF, at=late + M, done={"first": late})
    assert nxt is not None and nxt.kind == "final"
    assert nxt.window_from == KICKOFF - 100 * M and nxt.lineups_until == KICKOFF - 50 * M and nxt.window_until == KICKOFF - 10 * M


def test_after_the_pre_the_final_and_after_the_final_nothing() -> None:
    first, pre = KICKOFF - 12 * H, KICKOFF - 5 * H
    nxt = next_pass(KICKOFF, at=KICKOFF - 99 * M, done={"first": first, "pre": pre})
    assert nxt is not None and nxt.kind == "final" and nxt.due_now
    assert next_pass(KICKOFF, at=KICKOFF - 30 * M, done={"first": first, "pre": pre, "final": KICKOFF - 40 * M}) is None


def test_in_the_last_ten_minutes_no_pass_is_left() -> None:
    assert next_pass(KICKOFF, at=KICKOFF - 10 * M, done={}) is None
    assert next_pass(KICKOFF, at=KICKOFF + H, done={"first": KICKOFF - 12 * H}) is None


def test_a_match_right_after_midnight_has_no_room_for_a_pass() -> None:
    early = datetime.combine(DAY, datetime.min.time(), tzinfo=DAY_TZ) + 12 * M  # 00:12: the day opens two minutes inside the last ten
    assert next_pass(early, at=early - 5 * H, done={}) is None


@pytest.mark.parametrize("done_keys", [(), ("first",), ("first", "pre")])
def test_a_pass_said_due_now_is_the_one_the_worker_runs(done_keys: tuple[str, ...]) -> None:
    """Whenever ``next_pass`` says its window is open, ``due_pass`` (with the line-ups confirmed) runs that same pass; while it says it is
    not, ``due_pass`` runs nothing - minute by minute over the match's day."""
    stamps = {"first": opens_at(DAY) + 10 * M, "pre": KICKOFF - 4 * H}
    done = {k: stamps[k] for k in done_keys}
    at = max([opens_at(DAY), *done.values()]) + M
    checked = 0
    while at < KICKOFF:
        nxt = next_pass(KICKOFF, at=at, done=done)
        worker = due_pass(KICKOFF, at=at, done=dict(done), lineups_confirmed=True)
        if nxt is not None and nxt.due_now:
            assert worker == nxt.kind, (at, nxt)
            checked += 1
        else:
            assert worker is None, (at, nxt, worker)
        at += 5 * M
    assert checked > 0


# ── the verdict ─────────────────────────────────────────────────────────────────────────────────────────────────────


def a_pass(kind: str = "first", *, at: datetime | None = None, near: bool = False, **web: int) -> DiagnosisPass:
    end = at or opens_at(DAY) + 10 * M
    return DiagnosisPass(kind=kind, day=DAY, started_at=end - 2 * M, finished_at=end, status="ok", web=web,  # type: ignore[arg-type]
                         near_budget=near)


NONE = DiagnosisSearches(searches=0, failed=0, cost_usd=Decimal(0), sources_read=0)
OPEN_EXA = DiagnosisExa(allowed=True, reason="ok", budget_usd=Decimal(35), spent_month_usd=Decimal(3), spent_today_usd=Decimal("0.1"),
                        daily_cap_usd=Decimal(2))


def facts(**kw: Any) -> Facts:
    base: dict[str, Any] = {"at": KICKOFF - 8 * H, "kickoff": KICKOFF, "has_market": True, "opened": True, "covered": False,
                            "passes": [], "searches": NONE, "items": 0, "exa": OPEN_EXA, "next_pass": None}
    return Facts(**{**base, **kw})


def test_searched_says_when_how_many_searches_pages_and_items() -> None:
    paid_at = opens_at(DAY) + 9 * M
    searches = DiagnosisSearches(searches=2, failed=1, first_at=paid_at - M, last_at=paid_at, cost_usd=Decimal("0.03"), sources_read=6)
    later = opens_at(DAY) + 3 * H
    v = verdict(facts(passes=[a_pass(web_searches=2, web_asked=2, web_read=5), a_pass("pre", at=later, web_asked=1, web_read=1)],
                      searches=searches, items=4))
    assert v.code == "searched" and v.at == later, "a pass answered by the cache is the newest search"
    assert (v.searches, v.pages, v.items) == (2, 6, 4)


def test_searched_comes_first_even_without_a_market_now_or_after_kickoff() -> None:
    searches = DiagnosisSearches(searches=1, failed=0, last_at=KICKOFF - 9 * H, cost_usd=Decimal("0.015"), sources_read=None)
    v = verdict(facts(has_market=False, at=KICKOFF + 3 * H, searches=searches))
    assert v.code == "searched" and v.pages is None


def test_the_reasons_not_searched_in_their_order() -> None:
    soon = DiagnosisNextPass(kind="first", window_from=opens_at(DAY), window_until=KICKOFF - 10 * M, due_now=False)
    assert verdict(facts(has_market=None)).code == "not_tracked"
    assert verdict(facts(has_market=False)).code == "no_market"
    assert verdict(facts(at=KICKOFF - 5 * M)).code == "kicked_off"
    v = verdict(facts(opened=False, next_pass=soon))
    assert v.code == "day_not_open" and v.next_pass == "first" and v.next_at == opens_at(DAY)
    spent = OPEN_EXA.model_copy(update={"allowed": False, "reason": "month_spent"})
    v = verdict(facts(exa=spent, passes=[a_pass(web_searches=0)]))
    assert v.code == "exa_spent" and v.exa_reason == "month_spent"
    assert verdict(facts(exa=None)).code == "first_pending", "an envelope that could not be read says nothing"
    assert verdict(facts()).code == "first_pending"
    assert verdict(facts(passes=[a_pass(web_searches=0, near=True)])).code == "near_budget"
    assert verdict(facts(covered=True, passes=[a_pass(web_searches=0)])).code == "covered_not_searched"
    assert verdict(facts(passes=[a_pass(web_searches=0)])).code == "not_covered"


def test_a_first_pass_of_another_day_does_not_count_as_this_days() -> None:
    other = a_pass().model_copy(update={"day": DAY - timedelta(days=1)})
    assert verdict(facts(passes=[other])).code == "first_pending"


def test_the_pages_follow_the_readers_rule() -> None:
    assert pages_read([], NONE) == 0, "never searched: none read"
    assert pages_read([a_pass(web_searches=1, web_read=3), a_pass("pre", web_asked=1, web_read=2)], NONE) == 5
    assert pages_read([a_pass(web_searches=1)], NONE) is None, "a pass that did not count its pages: unknown"
    assert searched_at([a_pass(web_searches=0)], NONE) is None


def test_a_stored_pass_keeps_only_its_web_counts() -> None:
    row = {"pass": "first", "day": DAY, "started_at": KICKOFF - 9 * H, "finished_at": KICKOFF - 9 * H + M, "status": "ok",
           "counts": {"web_searches": 2, "web_read": 4, "web_priority": 1, "brief_llm": 1, "marginal_saved": 1, "web_note": "x"}}
    p = pass_of(row)
    assert p.web == {"web_searches": 2, "web_read": 4, "web_priority": 1} and p.near_budget
    assert not pass_of({**row, "counts": {}}).near_budget
