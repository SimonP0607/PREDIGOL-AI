"""The agents in the Admin Console (plan IA, phase 1), read from a real database: which engine each family reads, what the job that writes the state
of each match wrote, the Orchestrator's queue, the audit, and the file of one match.

Every test puts its own rows in the transaction of the ``db`` fixture, which is rolled back, and asks the service as of a moment in 2036 so that no
row another test left behind can be in its window. The figures are worked out by hand from the rows put in.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb

from fbi.ai.agents.registry import RegistryError
from fbi.ai.contracts.base import FAMILIES
from fbi.api.contracts.ai_agents import RegistryProblem
from fbi.api.envelope import DataStatus
from fbi.api.services import ai_agents
from fbi.picks.daily import DAY_TZ
from tests.integration.agent_tables import (
    ABSTAIN,
    HASH,
    INVALID,
    UNPAID,
    insert,
    run_values,
    shaped,
    task_values,
)
from tests.integration.conftest import Seed

AT = datetime(2036, 3, 10, 18, 0, tzinfo=UTC)
SINCE = AT - timedelta(days=7)


def digest(*parts: object) -> str:
    return hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()


def measures(name: str, tokens: int, *, cap: int = 18000, trimmed: tuple[str, ...] = (), fits: bool = True,
             blocks: tuple[str, ...] = ("form", "market")) -> dict[str, Any]:
    """A slice as ``Slice.measures()`` writes it."""
    return {"name": name, "hash": digest(name, tokens), "tokens": tokens, "cap": cap, "fits": fits, "trimmed": list(trimmed), "blocks": list(blocks)}


def put_state(db: psycopg.Connection[Any], fixture: int, known_at: datetime, *, created_at: datetime | None = None, pass_kind: str = "first",
              run_kind: str = "live", match: int = 1000, stats: int = 500, trimmed: tuple[str, ...] = (), fits: bool = True,
              blocking: tuple[str, ...] = (), flags: tuple[str, ...] = (), elapsed: int | None = 100, code: str | None = "mc9a7bec97ca",
              **over: Any) -> int:
    """One row of ``ai.match_runs`` as the job writes it."""
    values: dict[str, Any] = {
        "fixture_id": fixture, "run_kind": run_kind, "pass_kind": pass_kind, "known_at": known_at,
        "created_at": created_at or known_at + timedelta(minutes=1), "state_version": "ms-v1", "package_version": "package-v1",
        "package_hash": digest(fixture, pass_kind, known_at), "packet_id": 7, "elapsed_ms": elapsed,
        "slices": Jsonb([measures("match", match, trimmed=trimmed, fits=fits), measures("stats", stats)]), "blocking": list(blocking),
        "flags": list(flags), "model_status": Jsonb({"code": code} if code else {})}
    return insert(db, "ai.match_runs", values | over)


def put_cycle(db: psycopg.Connection[Any], status: str, started_at: datetime, *, kind: str = "package", counts: dict[str, Any] | None = None,
              error: str | None = None) -> int:
    return insert(db, "ai.cycles", {"kind": kind, "started_at": started_at, "finished_at": None if status == "running" else started_at + timedelta(seconds=9),
                                    "status": status, "mode": "shadow", "budget_state": "NORMAL", "counts": Jsonb(counts or {}), "error": error})


def promotion(**over: Any) -> dict[str, Any]:
    """An agent promotion as the owner signs it."""
    values: dict[str, Any] = {
        "at": AT - timedelta(days=2), "entity": "agent", "market_key": "1X2", "model_name": "council@council-v1+match-v1", "entity_id": None,
        "from_role": None, "to_role": "CHAMPION", "gate_version": "ma-gate-v1", "criteria": Jsonb({"report_hash": HASH}),
        "reason": "passed the gate of the family with 312 selections in 41 days", "decided_by": "owner"}
    return values | over


# ── the engine of each family ─────────────────────────────────────────────────────────────────────────────────────────────────────

def test_without_a_promotion_every_family_reads_the_language_model_of_today(db: psycopg.Connection[Any]) -> None:
    rows = ai_agents.families(db)
    assert [r.family for r in rows] == list(FAMILIES), "every family of the contracts, in their order"
    assert all(r.engine == "llm" and r.promotion is None and r.agent is None and r.since is None and r.promotion_id is None for r in rows)
    assert ai_agents.decisions(db) == []


def test_a_champion_row_sends_its_family_to_that_agent_and_only_that_family(db: psycopg.Connection[Any]) -> None:
    row_id = insert(db, "intel.promotions", promotion())
    rows = {r.family: r for r in ai_agents.families(db)}
    one = rows["1X2"]
    assert (one.engine, one.promotion, one.agent, one.version, one.upstream) == ("agent", "council@council-v1+match-v1", "council", "council-v1",
                                                                                 ["match-v1"])
    assert one.since == AT - timedelta(days=2) and one.promotion_id == row_id
    assert {f: r.engine for f, r in rows.items() if f != "1X2"} == dict.fromkeys(set(FAMILIES) - {"1X2"}, "llm")


def test_the_pipeline_a_verdict_came_through_is_all_of_its_upstream_versions_sorted(db: psycopg.Connection[Any]) -> None:
    insert(db, "intel.promotions", promotion(market_key="OU", model_name="council@council-v1+match-v1+stats-v1"))
    insert(db, "intel.promotions", promotion(market_key="CORNERS", model_name="statistics@stats-v1"))
    rows = {r.family: r for r in ai_agents.families(db)}
    assert rows["OU"].upstream == ["match-v1", "stats-v1"] and rows["OU"].agent == "council"
    assert (rows["CORNERS"].agent, rows["CORNERS"].version, rows["CORNERS"].upstream) == ("statistics", "stats-v1", [])


@pytest.mark.parametrize(("ending", "signed_by"), [("CHALLENGER", "system"), ("RETIRED", "system"), ("RETIRED", "owner"), ("CHALLENGER", "owner"),
                                                  ("REJECTED", "owner")])
def test_a_later_row_that_ends_the_champion_sends_the_family_back_to_the_language_model(db: psycopg.Connection[Any], ending: str,
                                                                                         signed_by: str) -> None:
    insert(db, "intel.promotions", promotion())
    insert(db, "intel.promotions", promotion(at=AT - timedelta(days=1), from_role="CHAMPION", to_role=ending, decided_by=signed_by,
                                             reason="automatic roll-back: the guard of the family was broken twice in a week"))
    assert {r.family: r.engine for r in ai_agents.families(db)}["1X2"] == "llm"


def test_a_report_ends_nothing_and_a_newer_champion_takes_over(db: psycopg.Connection[Any]) -> None:
    insert(db, "intel.promotions", promotion())
    insert(db, "intel.promotions", promotion(at=AT - timedelta(days=1), from_role="CHALLENGER", to_role="NOT_VALIDATED"))
    assert {r.family: r.agent for r in ai_agents.families(db)}["1X2"] == "council", "a gate report is not a demotion"
    successor = insert(db, "intel.promotions", promotion(at=AT - timedelta(hours=1), model_name="council@council-v2+match-v1", from_role="CHALLENGER"))
    one = {r.family: r for r in ai_agents.families(db)}["1X2"]
    assert (one.version, one.promotion_id) == ("council-v2", successor)


def test_a_promotion_name_this_code_does_not_read_is_shown_whole_and_not_guessed_at(db: psycopg.Connection[Any],
                                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    insert(db, "intel.promotions", promotion())

    def refuses(name: str) -> None:
        raise RegistryError("not the name of a promotion")

    monkeypatch.setattr(ai_agents, "parse_promotion_name", refuses)
    one = {r.family: r for r in ai_agents.families(db)}["1X2"]
    assert one.engine == "agent" and one.promotion == "council@council-v1+match-v1"
    assert one.agent is None and one.version is None and one.upstream == []


def test_the_decisions_are_the_agent_rows_newest_first_and_only_those(db: psycopg.Connection[Any]) -> None:
    first = insert(db, "intel.promotions", promotion())
    second = insert(db, "intel.promotions", promotion(at=AT - timedelta(days=1), from_role="CHAMPION", to_role="RETIRED", decided_by="system",
                                                      reason="automatic roll-back: the guard of the family was broken twice in a week"))
    insert(db, "intel.promotions", {"at": AT, "entity": "calibrator", "market_key": "1X2", "model_name": "platt", "to_role": "CHAMPION",
                                    "gate_version": "cal-gate-v1", "criteria": Jsonb({}), "reason": "not an agent", "decided_by": "system"})
    rows = ai_agents.decisions(db)
    assert [r.id for r in rows] == [second, first]
    assert (rows[0].family, rows[0].promotion, rows[0].from_role, rows[0].to_role, rows[0].decided_by) == (
        "1X2", "council@council-v1+match-v1", "CHAMPION", "RETIRED", "system")
    assert rows[1].gate_version == "ma-gate-v1" and rows[1].reason.startswith("passed the gate")


def test_two_decisions_of_the_same_moment_are_listed_with_the_one_written_last_first(db: psycopg.Connection[Any]) -> None:
    first = insert(db, "intel.promotions", promotion())
    second = insert(db, "intel.promotions", promotion(market_key="OU"))
    assert [r.id for r in ai_agents.decisions(db)] == [second, first]


def test_only_the_last_ten_decisions_are_listed(db: psycopg.Connection[Any]) -> None:
    for n in range(ai_agents.DECISIONS + 3):
        insert(db, "intel.promotions", promotion(at=AT - timedelta(days=30 - n), model_name=f"council@council-v{n + 1}+match-v1"))
    rows = ai_agents.decisions(db)
    assert len(rows) == ai_agents.DECISIONS
    assert [r.at for r in rows] == sorted((r.at for r in rows), reverse=True)
    assert rows[0].promotion == f"council@council-v{ai_agents.DECISIONS + 3}+match-v1"


# ── what the job that writes the state of each match did ──────────────────────────────────────────────────────────────────────────

def test_with_nothing_written_the_figures_are_zeros_and_not_made_up(db: psycopg.Connection[Any]) -> None:
    p = ai_agents.package_stats(db, at=AT)
    assert (p.states, p.matches, p.blocked, p.flagged, p.by_pass, p.slices, p.per_day) == (0, 0, 0, 0, {}, [], [])
    assert (p.build_ms.p50, p.build_ms.p95, p.build_ms.max) == (None, None, None), "no state, no time: never a zero that looks measured"
    assert (p.cycles.total, p.cycles.ok, p.cycles.partial, p.cycles.failed, p.cycles.running, p.cycles.last) == (0, 0, 0, 0, 0, None)
    assert (p.days, p.since) == (7, SINCE)


def test_the_figures_of_a_week_worked_out_by_hand(db: psycopg.Connection[Any]) -> None:
    created = [AT - timedelta(hours=1), AT - timedelta(hours=2), AT - timedelta(hours=3), AT - timedelta(hours=4),
               datetime(2036, 3, 10, 3, 30, tzinfo=UTC)]  # the last one is 22:30 of 9 March in Bogotá
    tokens = [(1000, 100), (2000, 200), (3000, 300), (4000, 400), (20000, 500)]
    elapsed = [10, 20, 30, 40, 1000]
    passes = ["first", "first", "pre", "pre", "final"]
    for n, (when, (match_tokens, stats_tokens), ms, kind) in enumerate(zip(created, tokens, elapsed, passes, strict=True)):
        put_state(db, 9001 + n % 2, when - timedelta(minutes=30), created_at=when, pass_kind=kind, match=match_tokens, stats=stats_tokens, elapsed=ms,
                  trimmed=("news", "injuries") if match_tokens == 20000 else (), fits=match_tokens != 20000,
                  blocking=("competition_score:PRODUCT_ONLY",) if n == 1 else (), flags=("news.0.text:instruction_like",) if n == 3 else ())
    p = ai_agents.package_stats(db, at=AT)
    assert (p.states, p.matches, p.blocked, p.flagged) == (5, 2, 1, 1)
    assert p.by_pass == {"first": 2, "pre": 2, "final": 1}
    assert [s.name for s in p.slices] == ["match", "stats"]
    match, stats = p.slices
    # percentile_cont over 1000, 2000, 3000, 4000, 20000: the median is the third, the 95th is 4000 + 0.8 * 16000
    assert (match.states, match.tokens_p50, match.tokens_p95, match.tokens_max, match.cap) == (5, 3000, 16800, 20000, 18000)
    assert (match.trimmed, match.over_cap) == (1, 1)
    assert (stats.states, stats.tokens_p50, stats.tokens_p95, stats.tokens_max, stats.cap, stats.trimmed, stats.over_cap) == (5, 300, 480, 500, 18000, 0, 0)
    assert (p.build_ms.p50, p.build_ms.p95, p.build_ms.max) == (30, 808, 1000)
    assert [(d.day, d.states, d.matches, d.blocked, d.flagged) for d in p.per_day] == [
        (date(2036, 3, 10), 4, 2, 1, 1), (date(2036, 3, 9), 1, 1, 0, 0)], "the days are Bogotá's, the newest first"


def test_what_blocks_and_what_is_marked_are_counted_apart_in_the_total_and_in_each_day(db: psycopg.Connection[Any]) -> None:
    def put(fixture: int, hours: int, *, blocked: bool, marked: bool) -> None:
        when = AT - timedelta(hours=hours)
        put_state(db, fixture, when - timedelta(minutes=30), created_at=when, blocking=("validation:QUARANTINED",) if blocked else (),
                  flags=("news.0.text:instruction_like",) if marked else ())

    put(9411, 1, blocked=True, marked=False)
    put(9411, 2, blocked=True, marked=True)
    put(9412, 3, blocked=False, marked=False)
    put(9413, 20, blocked=False, marked=True)  # 17:00 and 16:00 of 9 March in Bogotá
    put(9413, 21, blocked=False, marked=True)
    p = ai_agents.package_stats(db, at=AT)
    assert (p.states, p.matches, p.blocked, p.flagged) == (5, 3, 2, 3)
    assert [(d.day, d.states, d.matches, d.blocked, d.flagged) for d in p.per_day] == [
        (date(2036, 3, 10), 3, 2, 2, 1), (date(2036, 3, 9), 2, 1, 0, 2)]


def test_a_pass_that_ran_twice_for_a_match_is_two_states_and_not_one(db: psycopg.Connection[Any]) -> None:
    put_state(db, 9421, AT - timedelta(hours=8), pass_kind="first")
    put_state(db, 9421, AT - timedelta(hours=6), pass_kind="pre")
    put_state(db, 9421, AT - timedelta(hours=4), pass_kind="pre")  # the same pass again, knowing more
    put_state(db, 9422, AT - timedelta(hours=5), pass_kind="pre")
    p = ai_agents.package_stats(db, at=AT)
    assert (p.states, p.matches, p.by_pass) == (4, 2, {"first": 1, "pre": 3})


def test_a_slice_counts_apart_the_states_that_cut_it_and_those_it_did_not_fit_and_shows_the_cap_in_force(db: psycopg.Connection[Any]) -> None:
    def put(fixture: int, hours: int, cap: int, *, trimmed: tuple[str, ...] = (), fits: bool = True) -> None:
        when = AT - timedelta(hours=hours)
        put_state(db, fixture, when - timedelta(minutes=30), created_at=when,
                  slices=Jsonb([measures("odds", 900 + hours, cap=cap, trimmed=trimmed, fits=fits)]))

    put(9431, 9, 12000, trimmed=("news",))  # the oldest: a smaller cap, one block taken out
    put(9432, 3, 24000, trimmed=("news",))  # the largest cap of the window, one block taken out; written just before the next, at the same moment
    put(9433, 3, 18000, fits=False)  # the last written: the cap in force; it does not fit and nothing was taken out of it
    (odds,) = ai_agents.package_stats(db, at=AT).slices
    assert (odds.name, odds.states, odds.trimmed, odds.over_cap, odds.cap) == ("odds", 3, 2, 1, 18000)
    assert (odds.tokens_max, odds.tokens_p50) == (909, 903)


def test_only_live_states_inside_the_window_are_counted(db: psycopg.Connection[Any]) -> None:
    put_state(db, 9101, AT - timedelta(hours=5))
    put_state(db, 9102, SINCE - timedelta(hours=1), created_at=SINCE, pass_kind="pre")  # created exactly at the start of the window: in
    put_state(db, 9103, SINCE - timedelta(hours=2), created_at=SINCE - timedelta(seconds=1), pass_kind="final")  # a second before: out
    put_state(db, 9104, AT - timedelta(hours=5), run_kind="shadow", match=99999)
    put_state(db, 9105, AT - timedelta(hours=5), run_kind="replay", match=99999)
    p = ai_agents.package_stats(db, at=AT)
    assert (p.states, p.matches) == (2, 2) and p.by_pass == {"first": 1, "pre": 1}
    assert p.slices[0].tokens_max == 1000, "a shadow arm or a replay never moves the figures of the live states"
    assert p.slices[0].states == 2, "the state created at the very start of the window is in the sizes of the slices too"
    assert [(d.day, d.states, d.matches) for d in p.per_day] == [(date(2036, 3, 10), 1, 1), (date(2036, 3, 3), 1, 1)], "by day: no shadow, no replay"
    wider = ai_agents.package_stats(db, at=AT, days=30)
    assert (wider.states, wider.days, wider.since) == (3, 30, AT - timedelta(days=30))


def test_a_state_without_a_timing_does_not_move_the_timings(db: psycopg.Connection[Any]) -> None:
    put_state(db, 9201, AT - timedelta(hours=5), elapsed=None)
    assert (ai_agents.package_stats(db, at=AT).build_ms.p50) is None
    put_state(db, 9202, AT - timedelta(hours=6), elapsed=80)
    t = ai_agents.package_stats(db, at=AT).build_ms
    assert (t.p50, t.p95, t.max) == (80, 80, 80)


def test_a_median_and_a_95th_that_fall_between_two_figures_are_rounded_and_not_cut(db: psycopg.Connection[Any]) -> None:
    put_state(db, 9203, AT - timedelta(hours=5), elapsed=10, match=1000)
    put_state(db, 9204, AT - timedelta(hours=6), elapsed=13, match=1003)
    p = ai_agents.package_stats(db, at=AT)
    assert (p.build_ms.p50, p.build_ms.p95, p.build_ms.max) == (12, 13, 13), "11.5 and 12.85 milliseconds"
    assert (p.slices[0].tokens_p50, p.slices[0].tokens_p95, p.slices[0].tokens_max) == (1002, 1003, 1003), "1001.5 and 1002.85 tokens"


def test_a_slice_nobody_wrote_is_left_out_of_the_figures_and_does_not_break_them(db: psycopg.Connection[Any]) -> None:
    odd = [measures("match", 700), "text", 7, None, {"name": "match"}, {"name": "match", "tokens": "many", "cap": 1, "fits": True},
           {"name": "stats", "tokens": 9, "cap": "big", "fits": True},
           {"name": "stats", "tokens": 10, "cap": 20, "fits": "yes", "trimmed": []},
           {"name": "stats", "tokens": 12.0, "cap": 20, "fits": True, "trimmed": "news"},
           {"name": 4, "tokens": 5, "cap": 6, "fits": True}]
    put_state(db, 9301, AT - timedelta(hours=2), slices=Jsonb(odd))
    p = ai_agents.package_stats(db, at=AT)
    by = {s.name: s for s in p.slices}
    assert set(by) == {"match", "stats"}
    assert (by["match"].states, by["match"].tokens_max) == (1, 700)
    assert (by["stats"].states, by["stats"].tokens_max, by["stats"].trimmed) == (1, 12, 0), "a trimmed that is not a list counts for nothing"
    assert p.states == 1


def test_the_runs_of_the_job_are_counted_by_how_they_ended_and_the_last_one_is_shown_whole(db: psycopg.Connection[Any]) -> None:
    put_cycle(db, "ok", AT - timedelta(days=1), counts={"pending": 2, "built": 2})
    put_cycle(db, "ok", AT - timedelta(days=2))
    put_cycle(db, "partial", AT - timedelta(days=3), counts={"refused": 1, "built": 1}, error=None)
    put_cycle(db, "failed", AT - timedelta(days=4), error="failed, match 7: boom")
    put_cycle(db, "failed", AT - timedelta(days=5), error="failed, match 8: boom")
    put_cycle(db, "ok", AT - timedelta(days=9))  # outside the window
    last = put_cycle(db, "running", AT - timedelta(minutes=3), counts={"pending": 4})
    put_cycle(db, "ok", AT - timedelta(minutes=1), kind="analysis")  # another job of the AI layer, and a newer one
    c = ai_agents.package_stats(db, at=AT).cycles
    assert (c.total, c.ok, c.partial, c.failed, c.running) == (6, 2, 1, 2, 1), "six package cycles in the window; the old one and the analysis are not"
    assert c.last is not None and c.last.id == last and c.last.kind == "package" and c.last.status == "running" and c.last.counts == {"pending": 4}


def test_a_run_of_the_job_at_the_very_start_of_the_window_is_in_it(db: psycopg.Connection[Any]) -> None:
    put_cycle(db, "ok", SINCE)
    put_cycle(db, "ok", SINCE - timedelta(seconds=1))
    assert ai_agents.package_stats(db, at=AT).cycles.total == 1


def test_of_two_runs_that_started_together_the_last_is_the_one_written_last(db: psycopg.Connection[Any]) -> None:
    put_cycle(db, "ok", AT - timedelta(hours=1))
    second = put_cycle(db, "failed", AT - timedelta(hours=1), error="the second of the same minute")
    last = ai_agents.package_stats(db, at=AT).cycles.last
    assert last is not None and last.id == second and last.status == "failed"


def test_the_last_run_is_the_newest_even_when_it_is_older_than_the_window(db: psycopg.Connection[Any]) -> None:
    old = put_cycle(db, "failed", AT - timedelta(days=20), error="the schema went back")
    c = ai_agents.package_stats(db, at=AT).cycles
    assert c.total == 0 and c.last is not None and c.last.id == old and c.last.error == "the schema went back"


def test_what_the_page_says_the_rule_of_the_job_is_the_rule_of_the_code(db: psycopg.Connection[Any]) -> None:
    from fbi.ai import match_runs, package

    rule = ai_agents.package_stats(db, at=AT).rule
    assert rule == {"state_version": match_runs.STATE_VERSION, "package_version": package.VERSION, "window_days": match_runs.WINDOW.days,
                    "limit": match_runs.LIMIT, "max_seconds": match_runs.MAX_SECONDS}
    assert rule["state_version"] == "ms-v1" and rule["package_version"] == "package-v2" and (rule["window_days"], rule["limit"]) == (4, 200)


# ── the queue ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_an_empty_queue_says_zero_for_every_state_and_every_status(db: psycopg.Connection[Any]) -> None:
    q = ai_agents.queue_stats(db, at=AT)
    assert q.tasks == dict.fromkeys(ai_agents.TASK_STATES, 0) and q.runs == dict.fromkeys(ai_agents.RUN_STATUSES, 0)
    assert (q.open, q.reserved_usd, q.days) == (0, Decimal(0), 7)


def put_run(db: psycopg.Connection[Any], seed: Seed, n: int, status: str, started: datetime) -> int:
    base = {"ok": {}, "invalid": INVALID, "abstain": ABSTAIN, "timeout": UNPAID, "skipped": UNPAID | {"status": "skipped"},
            "expired": UNPAID | {"status": "expired"}, "budget_skip": UNPAID | {"status": "budget_skip"}}[status]
    return insert(db, "ai.agent_runs", run_values(seed, n, started_at=started, finished_at=started + timedelta(seconds=3),
                                                   known_at=started - timedelta(hours=1)) | base)


def put_task(db: psycopg.Connection[Any], seed: Seed, n: int, state: str, created: datetime, *, run: int = 0, cost: str = "0.031") -> int:
    return insert(db, "ai.agent_tasks", task_values(seed, n, created_at=created, not_before=created, deadline_at=created + timedelta(hours=6),
                                                    est_cost_usd=Decimal(cost)) | shaped(state, run))


def test_the_queue_counts_by_state_what_is_open_and_what_it_has_reserved(db: psycopg.Connection[Any], seed: Seed) -> None:
    day = AT - timedelta(days=1)
    ended = {state: put_run(db, seed, 100 + i, status, day) for i, (state, status) in enumerate(
        [("done", "ok"), ("failed", "invalid"), ("skipped", "skipped"), ("expired", "expired")])}
    for n, state in enumerate(["planned", "planned", "queued", "running", "done", "failed", "skipped", "expired"], start=1):
        put_task(db, seed, n, state, day, run=ended.get(state, 0))
    put_task(db, seed, 50, "planned", AT - timedelta(days=30), cost="0.5")  # old and still waiting: open, but not of this week
    q = ai_agents.queue_stats(db, at=AT)
    assert q.tasks == {"planned": 2, "queued": 1, "running": 1, "done": 1, "failed": 1, "skipped": 1, "expired": 1}
    assert q.open == 5, "planned, queued and running now, whatever their age"
    assert q.reserved_usd == Decimal("0.062000"), "only a queued or a running task reserves its estimate: 0.031 + 0.031"


def test_a_task_and_an_attempt_at_the_very_start_of_the_window_are_in_it(db: psycopg.Connection[Any], seed: Seed) -> None:
    run = put_run(db, seed, 1, "ok", SINCE)
    put_run(db, seed, 2, "ok", SINCE - timedelta(seconds=1))
    put_task(db, seed, 1, "done", SINCE, run=run)
    put_task(db, seed, 2, "planned", SINCE - timedelta(seconds=1))
    q = ai_agents.queue_stats(db, at=AT)
    assert q.runs["ok"] == 1 and q.tasks["done"] == 1 and q.tasks["planned"] == 0


def test_the_attempts_are_counted_by_status_inside_the_window(db: psycopg.Connection[Any], seed: Seed) -> None:
    for n, status in enumerate(["ok", "invalid", "abstain", "timeout", "skipped", "expired", "budget_skip", "timeout"], start=1):
        put_run(db, seed, n, status, AT - timedelta(days=2))
    put_run(db, seed, 90, "ok", AT - timedelta(days=9))  # before the window
    q = ai_agents.queue_stats(db, at=AT)
    assert q.runs == {"ok": 1, "invalid": 1, "timeout": 2, "abstain": 1, "skipped": 1, "expired": 1, "budget_skip": 1}


# ── the audit of what an agent may know ───────────────────────────────────────────────────────────────────────────────────────────

def check(db: psycopg.Connection[Any], rule: str, day: date, checked: int, bad: int, at: datetime, *, examples: list[Any] | None = None,
          version: str = "leak-audit-v8") -> None:
    insert_audit = ("INSERT INTO intel.audit_checks (day, checked_at, version, rule, n_checked, n_violations, examples) "
                    "VALUES (%s, %s, %s, %s, %s, %s, %s)")
    db.execute(insert_audit, (day, at, version, rule, checked, bad, Jsonb(examples or [])))


def test_each_day_of_the_audit_shows_its_latest_verdict_and_the_totals_add_those_up(db: psycopg.Connection[Any]) -> None:
    d = AT.date()
    check(db, "slice_known", d, 40, 0, AT - timedelta(hours=1))
    check(db, "slice_known", d - timedelta(days=1), 30, 2, AT - timedelta(days=1, hours=2), examples=[11, 12])
    check(db, "slice_known", d - timedelta(days=1), 30, 0, AT - timedelta(days=1, hours=1))  # re-run later the same day: this one stands
    check(db, "slice_known", d - timedelta(days=3), 25, 1, AT - timedelta(days=3), examples=[5])
    check(db, "slice_known", d - timedelta(days=10), 99, 9, AT - timedelta(days=10))  # outside the window
    check(db, "some_other_rule", d, 500, 50, AT)  # a rule that is not about agents
    rules = {r.rule: r for r in ai_agents.audit(db, at=AT)}
    assert list(rules) == list(ai_agents.AUDIT_RULES)
    r = rules["slice_known"]
    assert [x.day for x in r.days] == [d, d - timedelta(days=1), d - timedelta(days=3)], "newest first, one per day"
    assert [(x.n_checked, x.n_violations) for x in r.days] == [(40, 0), (30, 0), (25, 1)]
    assert r.days[2].examples == [5] and r.days[0].version == "leak-audit-v8" and r.days[0].checked_at == AT - timedelta(hours=1)
    assert (r.days_audited, r.checked, r.violations) == (3, 95, 1)


def test_each_rule_has_its_own_days_and_its_own_totals(db: psycopg.Connection[Any]) -> None:
    d = AT.date()
    check(db, "slice_known", d, 40, 3, AT - timedelta(hours=1), examples=[1, 2, 3])
    check(db, "review_known", d, 7, 0, AT - timedelta(hours=1))
    check(db, "review_known", d - timedelta(days=1), 5, 2, AT - timedelta(days=1, hours=1), examples=[9, 8])
    rules = {r.rule: r for r in ai_agents.audit(db, at=AT)}
    mine, theirs = rules["slice_known"], rules["review_known"]
    assert ([x.day for x in mine.days], mine.days_audited, mine.checked, mine.violations) == ([d], 1, 40, 3)
    assert ([x.day for x in theirs.days], theirs.days_audited, theirs.checked, theirs.violations) == ([d, d - timedelta(days=1)], 2, 12, 2)
    assert mine.days[0].examples == [1, 2, 3] and theirs.days[1].examples == [9, 8]


def test_a_rule_the_audit_has_not_run_is_shown_without_days_and_never_as_a_clean_record(db: psycopg.Connection[Any]) -> None:
    for rule in ai_agents.audit(db, at=AT):
        assert (rule.days, rule.days_audited, rule.checked, rule.violations) == ([], 0, 0, 0)


def test_the_window_of_the_audit_is_counted_in_days_of_bogota(db: psycopg.Connection[Any]) -> None:
    first = AT.astimezone(DAY_TZ).date() - timedelta(days=6)
    check(db, "slice_known", first, 10, 0, AT - timedelta(days=6))
    check(db, "slice_known", first - timedelta(days=1), 10, 0, AT - timedelta(days=7))
    r = ai_agents.audit(db, at=AT)[0]
    assert [x.day for x in r.days] == [first], "seven days: today and the six before it"
    assert [x.day for x in ai_agents.audit(db, at=AT, days=8)[0].days] == [first, first - timedelta(days=1)]


def test_when_it_is_already_tomorrow_in_utc_the_window_still_starts_at_bogotas_date(db: psycopg.Connection[Any]) -> None:
    at = datetime(2036, 3, 10, 2, 0, tzinfo=UTC)  # 21:00 of 9 March in Bogotá
    check(db, "slice_known", date(2036, 3, 3), 10, 0, at - timedelta(days=6))
    check(db, "slice_known", date(2036, 3, 2), 10, 0, at - timedelta(days=7))
    assert [x.day for x in ai_agents.audit(db, at=at)[0].days] == [date(2036, 3, 3)]


# ── the file of a match ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_current_state_is_the_newest_live_one_and_the_history_goes_back_newest_first(db: psycopg.Connection[Any]) -> None:
    k1, k2, k3 = AT - timedelta(hours=9), AT - timedelta(hours=5), AT - timedelta(hours=1)
    a = put_state(db, 9401, k1, pass_kind="first", match=900)
    b = put_state(db, 9401, k2, pass_kind="pre", match=1100, blocking=("validation:QUARANTINED",), flags=("news.2.text:instruction_like",))
    c = put_state(db, 9401, k3, pass_kind="final", match=1300, trimmed=("news",), agents=Jsonb([{"agent": "match"}]), candidates=Jsonb([1, 2]),
                  risks=Jsonb([1, 2, 3, 4]), contradictions=Jsonb([1, 2, 3]), final=Jsonb({"verdict": "NO_PICK"}))
    envelope = ai_agents.match_state(db, 9401)
    assert envelope.status is DataStatus.OK
    state = envelope.data
    assert state.fixture_id == 9401
    assert [h.id for h in state.history] == [c, b, a], "by what was known, then by what was written"
    assert state.current is not None and state.current.id == c
    cur = state.current
    assert (cur.pass_kind, cur.known_at, cur.run_kind, cur.state_version, cur.package_version) == ("final", k3, "live", "ms-v1", "package-v1")
    assert cur.package_hash == digest(9401, "final", k3) and cur.packet_id == 7 and cur.elapsed_ms == 100 and cur.code == "mc9a7bec97ca"
    assert [(s.name, s.tokens, s.cap, s.fits, s.trimmed, s.blocks) for s in cur.slices] == [
        ("match", 1300, 18000, True, ["news"], ["form", "market"]), ("stats", 500, 18000, True, [], ["form", "market"])]
    assert (cur.agents, cur.candidates, cur.risks, cur.contradictions, cur.final) == (1, 2, 4, 3, True), "four different figures: none can stand for another"
    earlier = state.history[1]
    assert earlier.blocking == ["validation:QUARANTINED"] and earlier.flags == ["news.2.text:instruction_like"]
    assert (earlier.agents, earlier.candidates, earlier.final) == (0, 0, False), "a state written before any agent ran has none of them"
    assert state.tasks == [] and state.runs == []


def test_the_current_state_follows_what_was_known_and_not_what_was_written_last(db: psycopg.Connection[Any]) -> None:
    newer_knowledge = put_state(db, 9501, AT - timedelta(hours=2), created_at=AT - timedelta(hours=1, minutes=50), pass_kind="pre")
    written_later = put_state(db, 9501, AT - timedelta(hours=8), created_at=AT - timedelta(minutes=5), pass_kind="first")  # written late, known early
    state = ai_agents.match_state(db, 9501).data
    assert state.current is not None and state.current.id == newer_knowledge
    assert [h.id for h in state.history] == [newer_knowledge, written_later]


def test_two_states_known_at_the_same_moment_go_by_what_was_written_last_and_that_one_is_current(db: psycopg.Connection[Any]) -> None:
    known = AT - timedelta(hours=3)
    pre = put_state(db, 9441, known, pass_kind="pre")
    final = put_state(db, 9441, known, pass_kind="final")
    state = ai_agents.match_state(db, 9441).data
    assert [h.id for h in state.history] == [final, pre]
    assert state.current is not None and state.current.id == final, "the file and the view agree on which is current"


def test_a_shadow_state_is_history_but_never_current(db: psycopg.Connection[Any]) -> None:
    live = put_state(db, 9601, AT - timedelta(hours=6))
    shadow = put_state(db, 9601, AT - timedelta(hours=2), run_kind="shadow", pass_kind="pre")
    state = ai_agents.match_state(db, 9601).data
    assert state.current is not None and state.current.id == live and state.current.run_kind == "live"
    assert [(h.id, h.run_kind) for h in state.history] == [(shadow, "shadow"), (live, "live")]


def test_a_match_with_only_a_shadow_state_has_history_and_no_current_one(db: psycopg.Connection[Any]) -> None:
    put_state(db, 9602, AT - timedelta(hours=2), run_kind="shadow")
    envelope = ai_agents.match_state(db, 9602)
    assert envelope.status is DataStatus.EMPTY and envelope.reason == "no_live_state_yet"
    assert envelope.data.current is None and len(envelope.data.history) == 1


def test_a_match_without_a_state_is_empty_with_a_reason_and_not_an_error(db: psycopg.Connection[Any]) -> None:
    envelope = ai_agents.match_state(db, 9999)
    assert envelope.status is DataStatus.EMPTY and envelope.reason == "no_live_state_yet"
    assert (envelope.data.fixture_id, envelope.data.current, envelope.data.history, envelope.data.tasks, envelope.data.runs) == (9999, None, [], [], [])


def test_the_state_of_another_match_is_not_in_the_file(db: psycopg.Connection[Any]) -> None:
    put_state(db, 9701, AT - timedelta(hours=2))
    put_state(db, 9702, AT - timedelta(hours=2))
    assert [h.fixture_id for h in ai_agents.match_state(db, 9701).data.history] == [9701]


def test_when_the_current_state_is_older_than_the_list_it_is_read_on_its_own(db: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch) -> None:
    live = put_state(db, 9801, AT - timedelta(hours=9))
    shadows = [put_state(db, 9801, AT - timedelta(hours=h), run_kind="shadow", pass_kind="pre") for h in (4, 3, 2)]
    monkeypatch.setattr(ai_agents, "HISTORY", 2)
    state = ai_agents.match_state(db, 9801).data
    assert [h.id for h in state.history] == [shadows[2], shadows[1]], "the list is bounded"
    assert state.current is not None and state.current.id == live and state.current.run_kind == "live"


def test_a_state_with_odd_content_is_still_shown(db: psycopg.Connection[Any]) -> None:
    put_state(db, 9901, AT - timedelta(hours=2),
              slices=Jsonb([measures("match", 5), "text", {"name": "stats", "tokens": "many", "fits": "yes", "trimmed": 3, "blocks": None},
                            {"name": "other", "tokens": True, "cap": 2.9, "fits": True},
                            {"name": "named", "tokens": 1, "cap": 2, "fits": True, "trimmed": [3, "news"], "blocks": ["form", 7]}]),
              model_status=Jsonb({"code": 42}), final=Jsonb({}), agents=Jsonb([]))
    cur = ai_agents.match_state(db, 9901).data.current
    assert cur is not None
    assert [(s.name, s.tokens, s.cap, s.fits, s.trimmed, s.blocks) for s in cur.slices] == [
        ("match", 5, 18000, True, [], ["form", "market"]), ("stats", 0, 0, False, [], []), ("other", 0, 2, True, [], []),
        ("named", 1, 2, True, ["3", "news"], ["form", "7"]),
    ], "what is not a slice is not shown; what is missing is zero; a boolean is no number and only true is true; the names in a slice are text"
    assert cur.slices[1].hash == "" and cur.code is None, "a code that is not text is no code"
    assert cur.final is False and cur.agents == 0


def test_the_tasks_and_attempts_of_the_agents_on_a_match_are_listed_newest_first(db: psycopg.Connection[Any], seed: Seed) -> None:
    fixture = seed.fixture_id
    earlier, later = AT - timedelta(hours=5), AT - timedelta(hours=1)
    run_a = insert(db, "ai.agent_runs", run_values(seed, 1, fixture_id=fixture, started_at=earlier, finished_at=earlier + timedelta(seconds=3),
                                                    known_at=earlier - timedelta(hours=1)))
    insert(db, "ai.agent_runs", run_values(seed, 2, fixture_id=fixture, started_at=later, finished_at=later + timedelta(seconds=3),
                                            known_at=later - timedelta(hours=1)) | UNPAID | {"status": "budget_skip", "reason": "the month's budget is spent"})
    insert(db, "ai.agent_runs", run_values(seed, 3, fixture_id=fixture + 1000, started_at=later, finished_at=later + timedelta(seconds=3),
                                            known_at=later - timedelta(hours=1)))  # another match's
    done = insert(db, "ai.agent_tasks", task_values(seed, 1, created_at=earlier, not_before=earlier, deadline_at=earlier + timedelta(hours=6))
                  | shaped("done", run_a))
    queued = insert(db, "ai.agent_tasks", task_values(seed, 2, created_at=later, not_before=later, deadline_at=later + timedelta(hours=6),
                                                      priority=50) | shaped("queued", 0))
    insert(db, "ai.agent_tasks", task_values(seed, 3, fixture_id=fixture + 1000, created_at=later, not_before=later, deadline_at=later + timedelta(hours=6)))
    state = ai_agents.match_state(db, fixture).data
    assert [t.id for t in state.tasks] == [queued, done]
    first = state.tasks[0]
    assert (first.agent, first.agent_version, first.task_kind, first.pass_kind, first.state, first.run_kind, first.priority) == (
        "council", "council-v1", "council", "first", "queued", "live", 50)
    assert first.est_cost_usd == Decimal("0.031") and first.attempts == 0 and first.created_at == later and first.deadline_at == later + timedelta(hours=6)
    assert [(r.status, r.model, r.verdict) for r in state.runs] == [("budget_skip", None, None), ("ok", "claude-sonnet-5-5", "NO_PICK")]
    assert state.runs[1].cost_usd == Decimal("0.0123") and state.runs[0].agent == "council"
    assert state.current is None, "no state was written for it: the agents' work does not make one"


def test_the_tasks_and_attempts_listed_are_the_latest_few_and_equal_moments_go_by_what_was_written_last(
        db: psycopg.Connection[Any], seed: Seed, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(ai_agents, "HISTORY", 2)
    earlier, later = AT - timedelta(hours=5), AT - timedelta(hours=1)
    runs = [insert(db, "ai.agent_runs", run_values(seed, n, fixture_id=seed.fixture_id, started_at=when, finished_at=when + timedelta(seconds=3),
                                                    known_at=when - timedelta(hours=1))) for n, when in ((1, earlier), (2, later), (3, later))]
    tasks = [insert(db, "ai.agent_tasks", task_values(seed, n, created_at=when, not_before=when, deadline_at=when + timedelta(hours=6))
                    | shaped("queued", 0)) for n, when in ((1, earlier), (2, later), (3, later))]
    state = ai_agents.match_state(db, seed.fixture_id).data
    assert [t.id for t in state.tasks] == [tasks[2], tasks[1]], "two of three, the newest; of the two made together, the last written first"
    assert [r.id for r in state.runs] == [runs[2], runs[1]]


def test_the_overview_puts_the_parts_together_for_the_window_it_is_asked(db: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FBI_AI_MODE", "shadow")
    monkeypatch.delenv("FBI_AI_PACKAGE", raising=False)
    put_state(db, 9001, AT - timedelta(days=10))
    put_state(db, 9002, AT - timedelta(days=2))
    seven = ai_agents.overview(db, at=AT)
    assert seven.status is DataStatus.OK
    o = seven.data
    assert o.problems == [] and {v.status for v in o.registry} == {"built"}, "IA-017 built the Player Agent: nothing is postponed"
    assert [f.family for f in o.families] == list(FAMILIES) and o.decisions == []
    assert (o.package.days, o.package.states) == (7, 1) and o.queue.days == 7 and o.queue.open == 0
    assert [a.rule for a in o.audit] == list(ai_agents.AUDIT_RULES)
    assert o.settings == {"mode": "shadow", "package": True}
    assert ai_agents.overview(db, at=AT, days=30).data.package.states == 2
    monkeypatch.setenv("FBI_AI_PACKAGE", "0")
    assert ai_agents.overview(db, at=AT).data.settings == {"mode": "shadow", "package": False}


def test_the_overview_gives_the_mode_in_force_the_problems_the_registry_has_and_the_audit_of_the_window_asked(
        db: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FBI_AI_MODE", "off")
    problem = RegistryProblem(code="drift", subject="brief", text="the code that runs is not the one registered")
    monkeypatch.setattr(ai_agents, "registry", lambda: ([], [problem]))
    check(db, "slice_known", AT.date() - timedelta(days=12), 11, 1, AT - timedelta(days=12))
    week = ai_agents.overview(db, at=AT).data
    month = ai_agents.overview(db, at=AT, days=30).data
    assert week.settings["mode"] == "off" and week.problems == [problem] and month.problems == [problem]
    assert week.audit[0].days_audited == 0, "twelve days ago is not in a week"
    assert (month.audit[0].days_audited, month.audit[0].checked, month.audit[0].violations) == (1, 11, 1), "and it is in a month"


def test_a_key_is_nowhere_in_what_the_page_is_given(db: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FBI_AI_KEY_ANTHROPIC", "sk-must-never-leak")
    monkeypatch.setenv("FBI_AI_KEY_ANTHROPIC_LAB", "sk-lab-must-never-leak")
    text = ai_agents.overview(db, at=AT).model_dump_json() + ai_agents.match_state(db, 1).model_dump_json()
    assert "sk-" not in text and "must-never-leak" not in text
