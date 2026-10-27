"""The gate of research v2 (``fbi.ai.gate_research``) on a built world.

The world is October 2032: five matches a day, each with its passes under shadow (v1 two searches, research v2 one it would have paid alone), the
facts v1 found - a player out on the home side and news about the away side - and the same two facts research v2 found as typed claims. Today is
the 20th at noon in Bogotá, so the window is the 13th to the 19th. Each test spoils ONE thing and says what the gate answers.

The figures are written by hand into a transaction that is rolled back and the gate only reads them: a test of the arithmetic of the verdict, not
evidence of anything. The real gate runs on the real database, over seven complete real days; the test that the cycle writes what the gate reads
is ``test_research_v2_cycle.test_the_pass_says_which_research_it_ran_under_and_the_gate_reads_it``."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb

from fbi.ai import gate_research as g
from fbi.ai import gates
from fbi.ai.calendar import day_start
from fbi.ai.config import AiSettings
from fbi.ai.evidence import STALE_AFTER, EvidenceIn, store
from fbi.ai.usage import UsageLedger, shared

from .conftest import Seed

pytestmark = pytest.mark.integration

D = Decimal
NOW = datetime(2032, 10, 20, 17, 0, tzinfo=UTC)  # 12:00 in Bogotá
FIRST, LAST = date(2032, 10, 13), date(2032, 10, 19)  # the window: seven complete days
EARLIEST = date(2032, 10, 8)  # the first day of the world
PER_DAY = 5
PASS_ROW = ("INSERT INTO ai.fixture_passes (fixture_id, day, pass, started_at, finished_at, kickoff_at, status, counts) "
            "VALUES (%s, %s, 'first', %s, %s, %s, 'ok', %s)")
REVIEW = ("INSERT INTO ai.pick_reviews (reviewed_at, fixture_id, market_key, selection, line, engine, engine_version, input_hash, decision, confidence, "
          "output, mode, status, evidence_ids) VALUES (%s, %s, 'over25', 'over', 0, 'llm', 'r-v1', 'h', 'APPROVE', 0.5, '{}'::jsonb, 'shadow', 'ok', %s)")
AUDIT = ("INSERT INTO intel.audit_checks (day, checked_at, version, rule, n_checked, n_violations, examples) "
         "VALUES (%s, %s, 'leak-audit-v7', 'evidence_known', %s, %s, '[]'::jsonb)")
DECISION = ("INSERT INTO intel.decisions (decision_version, known_at, checkpoint, fixture_id, kickoff_at, market_key, selection, line, model_name, "
            "odds, p_model, p_cal, p_market, filters, state, context_status, input_hash, evidence_ids) "
            "VALUES ('decision-v1', %s, 'T-3h', %s, %s, '1X2', 'Home', 0, 'dixon_coles', 2.10, 0.50, 0.50, 0.46, '[]'::jsonb, 'CAUTELA', 'PENDING', %s, %s)")
HEALTHY_PASS = {"research_v2_shadow": 1, "web_searches": 2, "web_items": 2, "web_new": 2, "v2_demand": 2, "v2_paid": 0, "v2_shared": 1,
                "v2_reused": 1, "v2_claims": 2, "v2_new": 2}


def settings(word: str = "shadow") -> AiSettings:
    return AiSettings(mode="shadow", research_v2=word)  # type: ignore[arg-type]


def noon(day: date) -> datetime:
    return datetime(day.year, day.month, day.day, 17, 0, tzinfo=UTC)


def span(first: date, last: date) -> list[date]:
    return [first + timedelta(days=k) for k in range((last - first).days + 1)]


@dataclass
class World:
    db: psycopg.Connection[Any]
    seed: Seed
    fixtures: dict[date, list[int]]

    @property
    def every(self) -> list[int]:
        return [f for day in sorted(self.fixtures) for f in self.fixtures[day]]

    def claim(self, fixture: int, *, side: str, name: str | None, kind: str, assertion: str, typed: bool, at: datetime | None = None,
              day: date | None = None, published: datetime | None = None, unscoped: bool = False) -> int:
        team = self.seed.home_team_id if side == "home" else self.seed.away_team_id
        when = at or (noon(day or next(d for d, fs in self.fixtures.items() if fixture in fs)) - timedelta(hours=2))
        who = (name or "team").lower().replace(" ", "-")
        extra: dict[str, Any] = (
            {"claim_type": "OUT" if assertion == "out" else "OTHER", "subject_type": "PLAYER" if name else "TEAM", "subject_id": 77 if name else team,
             "fresh_until": when + timedelta(hours=24)} if typed else {})
        item = EvidenceIn(fixture_id=None if unscoped else fixture, team_id=team, kind=kind, claim=f"{name or 'The team'}: {assertion}", origin="web", source_name="Marca",
                          retrieved_at=when, story_key=f"{'v2' if typed else 'web'}:{fixture}:{side}:{who}:{kind}:{assertion}",
                          source_url=f"https://www.marca.com/futbol/{fixture}-{side}-{who}.html",
                          assertion=assertion, source_tier="media", published_at=published or when - timedelta(hours=1),  # type: ignore[arg-type]
                          attributes={"player_name": name} if name else {}, **extra)
        eid, created = store(self.db, item, at=when)
        assert created
        return eid


Shape = Callable[[date, int, dict[str, int]], dict[str, int] | None]


def build(db: psycopg.Connection[Any], seed: Seed, *, shadow_from: date | None = FIRST, per_day: int = PER_DAY,
          counts: dict[str, int] | None = None, v2_misses_players: int = 0, v2_misses_news: int = 0, silent: int = 0,
          audited: dict[date, int | None] | None = None, shape: Shape | None = None, earliest: date = EARLIEST) -> World:
    """The world. ``earliest``: its first day; ``shadow_from``: the first day the passes carry the mark of shadow (None: none does); ``counts``: what a healthy pass counts;
    ``v2_misses_players`` / ``v2_misses_news``: how many of the matches research v2 did NOT find the player (the news) of; ``silent``: how many of
    the matches research v2 found nothing for; ``audited``: the violations of ``evidence_known`` night by night (the default: the six nights
    before the last day, clean; None: that night was not audited); ``shape(day, index of the match in its day, counts)``: what a pass counts instead
    (None: the match has no pass that day). The passes and the audits are append-only: a world is built as it is meant to be, never mended after."""
    fixtures: dict[date, list[int]] = {}
    n = 0
    for day in span(earliest, LAST):
        for k in range(per_day):
            row = db.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at) "
                             "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                             (9_700_000 + n, seed.season_id, seed.home_team_id, seed.away_team_id,
                              noon(day) + timedelta(hours=3, minutes=10 * k))).fetchone()
            assert row is not None
            fixtures.setdefault(day, []).append(int(row[0]))
            n += 1
    world = World(db, seed, fixtures)
    healthy = HEALTHY_PASS if counts is None else counts
    before_shadow = {"web_searches": 2, "web_items": 2, "web_new": 2}  # what the passes counted before research v2 existed
    for day in span(earliest, LAST):
        in_shadow = shadow_from is not None and day >= shadow_from
        for i, f in enumerate(fixtures[day]):
            counted = dict(healthy) if in_shadow else dict(before_shadow)
            counted_or_none = counted if shape is None else shape(day, i, counted)
            if counted_or_none is None:
                continue
            db.execute(PASS_ROW, (f, day, noon(day) - timedelta(hours=11), noon(day) - timedelta(hours=10, minutes=58),
                                  noon(day) + timedelta(hours=3), Jsonb(counted_or_none)))
    window = [f for day in span(FIRST, LAST) for f in fixtures[day]]
    for i, f in enumerate(window):
        world.claim(f, side="home", name=f"Delantero {f}", kind="injury", assertion="out", typed=False)
        world.claim(f, side="away", name=None, kind="news", assertion="info", typed=False)
        if i < silent:
            continue
        if i >= v2_misses_players + silent:
            world.claim(f, side="home", name=f"Delantero {f}", kind="injury", assertion="out", typed=True)
        if i >= v2_misses_news + silent:
            world.claim(f, side="away", name=None, kind="news", assertion="info", typed=True)
    for day in span(FIRST, LAST - timedelta(days=1)):
        violations = (audited or {}).get(day, 0)
        if violations is not None:
            db.execute(AUDIT, (day, noon(day + timedelta(days=1)), 10, violations))
    return world


@pytest.fixture()
def world(db: psycopg.Connection[Any], seed: Seed) -> Iterator[World]:
    yield build(db, seed)


def check(report: g.GateReport, check_id: str) -> Any:
    return next(c for c in report.checks if c.id == check_id)


def failing(report: g.GateReport) -> list[str]:
    return [c.id for c in report.checks if c.ok is False]


def evaluate(db: psycopg.Connection[Any], **kw: Any) -> g.GateReport:
    return g.evaluate(db, kw.pop("settings", settings()), at=kw.pop("at", NOW), **kw)


# ── a week that went well ────────────────────────────────────────────────────────────────────────────────────────────

def test_a_week_of_shadow_that_found_everything_with_fewer_searches_passes(world: World) -> None:
    report = evaluate(world.db)
    assert report.verdict == g.PASS, [(c.id, c.ok) for c in report.checks]
    assert [c.id for c in report.checks] == ["window", "fewer_searches", "coverage", "coverage_players", "shadow_invisible", "evidence_known", "sample"]
    assert all(c.ok is True for c in report.checks) and report.pending == () and report.consequence is None
    assert report.window.first == FIRST and report.window.last == LAST and report.window.stable_days == 7 and report.window.complete
    s, c = check(report, "fewer_searches").detail, check(report, "coverage").detail
    assert (s["passes_in_shadow"], s["passes_compared"], s["searches_v1"], s["searches_v2_alone"]) == (35, 35, 70, 35)
    assert (s["v2_demand"], s["v2_paid"], s["v2_shared"], s["v2_reused"], s["reuse_pct"], s["saved_pct"]) == (70, 0, 35, 35, "33.33", "50.00")
    assert (c["fixtures"], c["facts_v1"], c["facts_v2"], c["found_by_v2"], c["coverage_pct"], c["only_v2"]) == (35, 70, 70, 70, "100.00", 0)
    assert c["facts_about_players_v1"] == 35 and c["coverage_players_pct"] == "100.00" and c["missed_examples"] == []
    assert c["facts_per_match_v1"] == 2.0 and c["facts_per_match_v2"] == 2.0
    assert report.lines()[0] == "GATE DE RESEARCH V2 · PASA"


def test_the_days_of_the_window_are_the_seven_that_ended_yesterday_and_no_other(world: World) -> None:
    s = check(evaluate(world.db), "fewer_searches").detail
    assert sorted(s["per_day"]) == [d.isoformat() for d in span(FIRST, LAST)]
    assert all(day["web_searches"] == 10 for day in s["per_day"].values())


def test_looking_back_from_an_earlier_day_judges_that_week_and_never_records(world: World) -> None:
    report = evaluate(world.db, through=date(2032, 10, 18))
    assert report.verdict == g.PENDING_TIME, "the 18th looking back has only the six days from the 13th: the week before had no shadow"
    assert report.window.last == date(2032, 10, 18) and report.window.stable_days == 6


def test_a_day_that_is_not_complete_yet_is_refused(world: World) -> None:
    with pytest.raises(ValueError, match="not a complete day"):
        evaluate(world.db, through=date(2032, 10, 20))


# ── the window: seven days, all of them in shadow ───────────────────────────────────────────────────────────────────

def test_three_days_of_shadow_are_pending_for_real_time_and_say_when_the_week_can_be_judged(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed, shadow_from=date(2032, 10, 17))
    report = evaluate(db)
    assert report.verdict == g.PENDING_TIME and not report.recordable and report.checks == ()
    w = report.window
    assert (w.stable_days, w.anchor, w.eligible_on, w.complete) == (3, date(2032, 10, 17), date(2032, 10, 24), False)
    assert "3 de 7 días completos" in report.pending[0] and "2032-10-24" in report.pending[0]
    p = report.preview
    assert p["note"].startswith("NOT evidence") and p["days"] == ["2032-10-17", "2032-10-19"], "what the days gone show, labelled as no evidence"
    assert p["searches"]["searches_v1"] == 30 and p["coverage"]["coverage_pct"] == "100.00"
    assert report.consequence is None


def test_no_shadow_at_all_says_so_and_names_the_switch_when_it_is_off(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed, shadow_from=None)
    report = evaluate(db, settings=settings("off"))
    assert report.verdict == g.PENDING_TIME and report.window.stable_days == 0 and report.window.anchor is None
    assert "ningún día completo" in report.pending[0] and "FBI_AI_RESEARCH_V2 es off" in report.pending[0]
    assert "FBI_AI_RESEARCH_V2" not in evaluate(db, settings=settings("shadow")).pending[0]


def test_a_day_in_which_a_pass_ran_without_research_v2_is_not_a_day_of_the_week(db: psycopg.Connection[Any], seed: Seed) -> None:
    def unmarked(day: date, i: int, c: dict[str, int]) -> dict[str, int]:
        return {k: v for k, v in c.items() if k != "research_v2_shadow"} if (day, i) == (date(2032, 10, 16), 0) else c

    build(db, seed, shape=unmarked)
    report = evaluate(db)
    assert report.verdict == g.PENDING_TIME and report.window.stable_days == 3 and report.window.anchor == date(2032, 10, 17)
    assert "2032-10-16: 1 of 5 passes ran without research v2 in shadow" in report.window.anchored_by


def test_a_day_in_which_research_v2_replaced_v1_is_not_a_day_of_the_comparison(db: psycopg.Connection[Any], seed: Seed) -> None:
    def replaced(day: date, i: int, c: dict[str, int]) -> dict[str, int]:
        return ({k: v for k, v in c.items() if k != "research_v2_shadow"} | {"research_v2_on": 1}) if day == date(2032, 10, 17) else c

    build(db, seed, shape=replaced)
    report = evaluate(db)
    assert report.window.stable_days == 2 and "5 of 5 passes ran without research v2 in shadow (5 of them with research v2 instead of v1)" in \
        report.window.anchored_by


def test_a_day_without_passes_breaks_the_run(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed, shape=lambda day, i, c: None if day == date(2032, 10, 15) else c)
    report = evaluate(db)
    assert report.window.stable_days == 4 and report.window.anchored_by == "2032-10-15 had no passes"


def test_a_change_declared_by_whoever_deployed_delays_the_gate(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed, shadow_from=EARLIEST)  # twelve days of shadow
    assert evaluate(db).verdict == g.PASS
    declared = evaluate(db, changes=[date(2032, 10, 15)])
    assert declared.verdict == g.PENDING_TIME and declared.window.stable_days == 4 and "declared by whoever deployed" in declared.window.anchored_by
    assert evaluate(db, changes=[date(2032, 10, 12)]).verdict == g.PASS, "a change before the week does not touch it"


def test_of_several_declared_changes_the_latest_decides(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed, shadow_from=EARLIEST)
    declared = evaluate(db, changes=[date(2032, 10, 15), date(2032, 10, 17), date(2032, 10, 11)])
    assert declared.window.stable_days == 2 and declared.window.anchor == date(2032, 10, 18), "the 17th is the day of the change: the run starts after it"
    assert "on 2032-10-17" in declared.window.anchored_by


def test_the_week_needs_all_its_days_even_with_a_month_of_shadow_before(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed, shadow_from=EARLIEST, shape=lambda day, i, c: None if day == date(2032, 10, 18) else c)
    report = evaluate(db)
    assert report.window.stable_days == 1 and report.verdict == g.PENDING_TIME and report.window.eligible_on == date(2032, 10, 26)


def test_a_run_of_shadow_longer_than_the_week_is_counted_whole(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed, shadow_from=EARLIEST)  # the twelve days from the 8th to the 19th
    w = evaluate(db).window
    assert (w.stable_days, w.anchor, w.complete) == (12, EARLIEST, True)
    assert w.anchored_by == "2032-10-07 had no passes" and w.eligible_on == date(2032, 10, 20), "the week could have been judged already yesterday"
    assert (w.first, w.last) == (FIRST, LAST), "and the window is still the seven days that ended yesterday"


def test_the_run_is_looked_for_over_a_month_and_no_further(db: psycopg.Connection[Any], seed: Seed) -> None:
    start = date(2032, 9, 10)
    build(db, seed, shadow_from=start, earliest=start)  # forty days of shadow
    w = evaluate(db).window
    assert (w.stable_days, w.anchor, w.complete) == (g.LOOKBACK_DAYS, LAST - timedelta(days=g.LOOKBACK_DAYS - 1), True)
    assert w.anchored_by == f"{g.LOOKBACK_DAYS} days in a row"


# ── the checks ───────────────────────────────────────────────────────────────────────────────────────────────────────


def test_research_v2_that_would_have_paid_as_many_searches_as_v1_does_not_pass(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed, counts=HEALTHY_PASS | {"v2_paid": 1, "v2_shared": 1})
    report = evaluate(db)
    assert report.verdict == g.FAIL and failing(report) == ["fewer_searches"]
    assert check(report, "fewer_searches").detail["searches_v1"] == 70 == check(report, "fewer_searches").detail["searches_v2_alone"]
    assert "sigue en sombra" in (report.consequence or "")


def test_what_a_cache_answered_counts_as_paid_because_alone_research_v2_would_have_paid_it(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed, counts=HEALTHY_PASS | {"v2_paid": 0, "v2_shared": 2})
    assert failing(evaluate(db)) == ["fewer_searches"]


def test_passes_in_which_research_v2_failed_or_was_cut_short_are_not_compared(db: psycopg.Connection[Any], seed: Seed) -> None:
    def spoil(day: date, i: int, c: dict[str, int]) -> dict[str, int]:
        n = (day - FIRST).days * PER_DAY + i  # 0..34 inside the window
        if n < 3:
            return {k: v for k, v in c.items() if k not in ("v2_paid", "v2_shared")} | {"v2_failed": 1}
        if n < 5:
            return c | {"v2_skipped_budget_exa": 1}
        return c

    build(db, seed, shape=spoil)
    s = check(evaluate(db), "fewer_searches").detail
    assert (s["passes_in_shadow"], s["passes_compared"], s["passes_v2_failed"], s["passes_v2_cut_short"]) == (35, 30, 3, 2)
    assert (s["searches_v1"], s["searches_v2_alone"]) == (60, 30), "the five passes in which one of the two did not finish compare nothing"


def test_a_pass_in_which_research_v2_failed_and_was_cut_short_counts_once_as_failed(db: psycopg.Connection[Any], seed: Seed) -> None:
    both = HEALTHY_PASS | {"v2_failed": 1, "v2_skipped_budget_exa": 1}
    build(db, seed, shape=lambda day, i, c: both if (day, i) == (date(2032, 10, 15), 0) else c)
    s = check(evaluate(db), "fewer_searches").detail
    assert (s["passes_in_shadow"], s["passes_compared"], s["passes_v2_failed"], s["passes_v2_cut_short"]) == (35, 34, 1, 0)


def test_a_v2_that_does_not_search_because_it_fails_cannot_look_cheap(db: psycopg.Connection[Any], seed: Seed) -> None:
    """Every pass failed in research v2: nothing is compared, and the check cannot be judged (pending), never passed."""
    build(db, seed, counts={"research_v2_shadow": 1, "web_searches": 2, "v2_failed": 1})
    report = evaluate(db)
    assert report.verdict == g.PENDING_TIME and check(report, "fewer_searches").ok is None
    assert check(report, "fewer_searches").detail["passes_v2_failed"] == 35


def test_no_search_of_v1_in_the_week_leaves_the_comparison_pending(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed, counts={"research_v2_shadow": 1, "web_searches": 0})
    report = evaluate(db)
    assert check(report, "fewer_searches").ok is None and report.verdict == g.PENDING_TIME
    assert "no hay datos" in report.pending[0]


def test_the_figures_are_those_of_the_passes_under_shadow_whatever_days_are_asked_for(db: psycopg.Connection[Any], seed: Seed) -> None:
    """The days before the shadow had passes too (v1 alone): asked for, they are not part of any comparison."""
    build(db, seed)
    s = g.searches(db, EARLIEST, LAST)
    assert (s.passes, s.compared, s.v1) == (35, 35, 70)
    assert g.coverage(db, EARLIEST, LAST).fixtures == 35, "no research v2 beside v1 on those days: nothing to compare for their matches"


def test_missing_6_percent_of_the_facts_of_v1_fails_the_coverage(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed, v2_misses_news=5)  # 5 of 35 matches: 5 of 70 facts = 7.14 %
    report = evaluate(db)
    assert failing(report) == ["coverage"] and report.verdict == g.FAIL and report.recordable, "the facts about players were all found"
    c = check(report, "coverage").detail
    assert c["coverage_pct"] == "92.86" and len(c["missed_examples"]) == 5 and all(e[2:] == ["team", "news"] for e in c["missed_examples"])
    assert check(report, "coverage_players").detail["coverage_players_pct"] == "100.00"


def test_missing_four_percent_of_the_facts_passes_the_coverage(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed, v2_misses_news=2, per_day=5)  # 2 of 70 facts = 2.86 %
    report = evaluate(db)
    assert report.verdict == g.PASS and check(report, "coverage").detail["coverage_pct"] == "97.14"


def test_a_v2_that_misses_the_players_fails_their_coverage_even_when_the_whole_passes(db: psycopg.Connection[Any], seed: Seed) -> None:
    # 35 matches with a player out and 35 with the news of the side: 70 facts; missing 3 players is 4.3 % of all and 8.6 % of the players
    build(db, seed, v2_misses_players=3)
    report = evaluate(db)
    assert failing(report) == ["coverage_players"] and report.verdict == g.FAIL
    assert check(report, "coverage").ok is True and check(report, "coverage").detail["coverage_pct"] == "95.71"
    assert check(report, "coverage_players").detail["coverage_players_pct"] == "91.43"


def test_a_v2_that_found_nothing_for_a_match_loses_both_of_its_facts(db: psycopg.Connection[Any], seed: Seed) -> None:
    report = evaluate(build(db, seed, silent=2).db)  # 4 of 70 facts, 2 of 35 players
    assert failing(report) == ["coverage", "coverage_players"] and report.verdict == g.FAIL
    assert check(report, "coverage").detail["found_by_v2"] == 66 and check(report, "coverage").detail["coverage_pct"] == "94.29"
    assert check(report, "coverage_players").detail["coverage_players_pct"] == "94.29"


def test_facts_found_by_research_v2_that_v1_did_not_find_are_reported_and_do_not_pay_for_the_ones_it_missed(db: psycopg.Connection[Any], seed: Seed) -> None:
    world = build(db, seed, v2_misses_news=5)
    for f in world.fixtures[LAST]:
        world.claim(f, side="home", name=None, kind="coach", assertion="info", typed=True)
    c = check(evaluate(db), "coverage").detail
    assert c["only_v2"] == 5 and c["coverage_pct"] == "92.86", "a fact only v2 found is not a fact of v1 that it found"


def test_a_fact_is_the_same_whatever_the_wording_the_kind_of_absence_or_the_spelling_of_the_name(db: psycopg.Connection[Any], seed: Seed) -> None:
    world = build(db, seed, v2_misses_players=35)  # research v2 found the news of every side and no player
    for day in span(FIRST, LAST):
        for f in world.fixtures[day]:  # now it says it as a suspension, with the name written with an initial
            world.claim(f, side="home", name=f"D. {f}", kind="suspension", assertion="out", typed=True)
    c = check(evaluate(db), "coverage_players").detail
    assert c["coverage_players_pct"] == "100.00", "a player out for a suspension is out; «D. 123» and «Delantero 123» are one surname"


def test_the_facts_found_after_the_kick_off_or_outside_the_week_are_not_compared(db: psycopg.Connection[Any], seed: Seed) -> None:
    world = build(db, seed, v2_misses_players=35)
    f = world.fixtures[LAST][0]
    kickoff = noon(LAST) + timedelta(hours=3)
    world.claim(f, side="home", name=f"Delantero {f}", kind="injury", assertion="out", typed=True, at=kickoff + timedelta(minutes=5))
    world.claim(f + 1, side="home", name=f"Delantero {f + 1}", kind="injury", assertion="out", typed=True, at=noon(FIRST) - timedelta(days=2))
    c = check(evaluate(db), "coverage_players").detail
    assert c["found_about_players"] == 0, "one was read after the match began, the other before the week began"


def test_a_claim_of_research_v2_older_than_ten_days_is_not_what_the_packet_would_have_read(db: psycopg.Connection[Any], seed: Seed) -> None:
    world = build(db, seed, v2_misses_players=35)
    f = world.fixtures[LAST][0]
    kickoff = noon(LAST) + timedelta(hours=3)
    world.claim(f, side="home", name=f"Delantero {f}", kind="injury", assertion="out", typed=True, published=kickoff - timedelta(days=11))
    assert check(evaluate(db), "coverage_players").detail["found_about_players"] == 0


def test_a_claim_about_a_team_with_no_match_is_read_for_every_match_of_that_team_that_comes_after_it(db: psycopg.Connection[Any], seed: Seed) -> None:
    """What research v2 found for a player of a team without naming a match (``fixture_id`` NULL) is part of the evidence of each later match of the
    team - that is how a search is shared by matches. The same player is out in three matches of the week (v1 found it three times)."""
    world = build(db, seed, v2_misses_players=35)
    mid, later, last = (world.fixtures[date(2032, 10, d)][0] for d in (17, 18, 19))
    for f in (mid, later, last):
        world.claim(f, side="home", name="Comun Uno", kind="injury", assertion="out", typed=False)
    world.claim(mid, side="home", name="Comun Uno", kind="injury", assertion="out", typed=True, unscoped=True)
    c = check(evaluate(db), "coverage_players").detail
    assert c["found_about_players"] == 3, "found for the match it was read for and for the two that came after it - not for the earlier ones"


def extra_match(world: World, kickoff: datetime, *, provider_id: int, day: date = LAST) -> int:
    """A match that kicks off at ``kickoff`` and had its pass (under shadow) on ``day``: a match of the week whose kick-off is not on a day of it."""
    row = world.db.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at) "
                           "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                           (provider_id, world.seed.season_id, world.seed.home_team_id, world.seed.away_team_id, kickoff)).fetchone()
    assert row is not None
    f = int(row[0])
    world.db.execute("INSERT INTO ai.fixture_passes (fixture_id, day, pass, started_at, finished_at, kickoff_at, status, counts) "
                     "VALUES (%s, %s, 'pre', %s, %s, %s, 'ok', %s)",
                     (f, day, noon(day), noon(day) + timedelta(minutes=2), kickoff, Jsonb(HEALTHY_PASS)))
    return f


def test_what_is_read_after_the_week_is_not_compared_even_for_a_match_that_has_not_been_played(db: psycopg.Connection[Any], seed: Seed) -> None:
    """A match of the 21st that had its pass on the 19th: what v1 found on the 19th is a fact of the week, what research v2 found on the 20th is not."""
    world = build(db, seed)
    f = extra_match(world, noon(date(2032, 10, 21)) + timedelta(hours=3), provider_id=9799000)
    world.claim(f, side="home", name="Tarde Uno", kind="injury", assertion="out", typed=False, day=LAST)
    world.claim(f, side="home", name="Tarde Uno", kind="injury", assertion="out", typed=True, at=noon(date(2032, 10, 20)))
    c = check(evaluate(db), "coverage").detail
    assert (c["fixtures"], c["facts_v1"], c["found_by_v2"], c["coverage_pct"]) == (36, 71, 70, "98.59")
    assert c["missed_examples"] == [[f, "home", "uno", "out"]]


def test_a_fact_read_the_instant_the_week_starts_is_of_the_week_and_one_read_a_moment_before_is_not(db: psycopg.Connection[Any], seed: Seed) -> None:
    """The week is the half-open interval from midnight of Bogotá of its first day to midnight of the day after its last - for both researches."""
    world = build(db, seed)
    f = world.fixtures[FIRST][0]
    before = day_start(FIRST) - timedelta(microseconds=1)
    for typed in (False, True):
        world.claim(f, side="home", name="Antes Uno", kind="injury", assertion="out", typed=typed, at=before)
    c = check(evaluate(db), "coverage").detail
    assert (c["facts_v1"], c["facts_v2"]) == (70, 70), "read when the day before was ending: not a fact of the week"
    for typed in (False, True):
        world.claim(f, side="home", name="Justo Dos", kind="injury", assertion="out", typed=typed, at=day_start(FIRST))
    c = check(evaluate(db), "coverage").detail
    assert (c["facts_v1"], c["facts_v2"]) == (71, 71), "read at its first instant: it is"


def test_a_fact_read_the_instant_the_week_ends_is_of_the_next_day(db: psycopg.Connection[Any], seed: Seed) -> None:
    """A match at 01:00 of the 20th (Bogotá) that had its pass on the 19th: what is read until 23:59:59.999999 of the 19th is of the week."""
    world = build(db, seed)
    end = day_start(LAST + timedelta(days=1))
    f = extra_match(world, end + timedelta(hours=1), provider_id=9799001)
    for typed in (False, True):
        world.claim(f, side="home", name="Noche Uno", kind="injury", assertion="out", typed=typed, at=end - timedelta(microseconds=1))
        world.claim(f, side="home", name="Noche Dos", kind="injury", assertion="out", typed=typed, at=end)
    c = check(evaluate(db), "coverage").detail
    assert (c["fixtures"], c["facts_v1"], c["facts_v2"]) == (36, 71, 71), "the one read at midnight sharp is the next day's"


def test_a_fact_read_at_the_kick_off_is_of_the_match_and_one_read_after_it_is_not(db: psycopg.Connection[Any], seed: Seed) -> None:
    world = build(db, seed)
    f = world.fixtures[LAST][0]
    kickoff = noon(LAST) + timedelta(hours=3)
    for typed in (False, True):
        world.claim(f, side="home", name="Tarde Tres", kind="injury", assertion="out", typed=typed, at=kickoff + timedelta(microseconds=1))
    c = check(evaluate(db), "coverage").detail
    assert (c["facts_v1"], c["facts_v2"]) == (70, 70), "v1's reading after the match began is no fact of the match either"
    for typed in (False, True):
        world.claim(f, side="home", name="Justo Cuatro", kind="injury", assertion="out", typed=typed, at=kickoff)
    c = check(evaluate(db), "coverage").detail
    assert (c["facts_v1"], c["facts_v2"]) == (71, 71), "the packet of the last minute reads what was read at the kick-off"


def test_a_claim_of_v1_about_a_team_with_no_match_is_part_of_each_later_match_of_the_team(db: psycopg.Connection[Any], seed: Seed) -> None:
    """The same reading as for research v2: a player of a team read without a match (``fixture_id`` NULL) is evidence of each later match of the team.
    Read at 15:00 UTC of the 17th it is a fact of the fifteen matches of the 17th, the 18th and the 19th, and of none before."""
    world = build(db, seed)
    world.claim(world.fixtures[date(2032, 10, 17)][0], side="home", name="Comun Dos", kind="injury", assertion="out", typed=False, unscoped=True)
    c = check(evaluate(db), "coverage").detail
    assert c["facts_v1"] == 70 + 15 and c["found_by_v2"] == 70


def test_a_claim_published_exactly_ten_days_before_the_kick_off_is_stale_and_one_a_moment_fresher_is_not(db: psycopg.Connection[Any], seed: Seed) -> None:
    world = build(db, seed, v2_misses_players=35)
    stale, fresh = world.fixtures[LAST][0], world.fixtures[LAST][1]
    kickoff_stale, kickoff_fresh = noon(LAST) + timedelta(hours=3), noon(LAST) + timedelta(hours=3, minutes=10)
    world.claim(stale, side="home", name=f"Delantero {stale}", kind="injury", assertion="out", typed=True, published=kickoff_stale - STALE_AFTER)
    assert check(evaluate(db), "coverage_players").detail["found_about_players"] == 0, "the packet asks for a claim younger than ten days"
    world.claim(fresh, side="home", name=f"Delantero {fresh}", kind="injury", assertion="out", typed=True,
                published=kickoff_fresh - STALE_AFTER + timedelta(microseconds=1))
    assert check(evaluate(db), "coverage_players").detail["found_about_players"] == 1


def test_what_the_provider_reported_is_not_a_fact_of_either(db: psycopg.Connection[Any], seed: Seed) -> None:
    world = build(db, seed)
    f = world.fixtures[LAST][0]
    item = EvidenceIn(fixture_id=f, team_id=seed.home_team_id, kind="injury", claim="provider says out", origin="provider", source_name="API-Football",
                      retrieved_at=noon(LAST), story_key=f"absence:{f}:1", assertion="out", source_tier="provider", attributes={"player_name": "Otro"})
    store(db, item, at=noon(LAST))
    assert check(evaluate(db), "coverage").detail["facts_v1"] == 70


def test_a_typed_claim_that_did_not_come_from_the_web_is_not_a_fact_of_research_v2(db: psycopg.Connection[Any], seed: Seed) -> None:
    world = build(db, seed, v2_misses_players=35)
    f = world.fixtures[LAST][0]
    item = EvidenceIn(fixture_id=f, team_id=seed.home_team_id, kind="injury", claim="provider says out", origin="provider", source_name="API-Football",
                      retrieved_at=noon(LAST), story_key=f"v2:{f}:provider", assertion="out", source_tier="provider", claim_type="OUT",
                      subject_type="PLAYER", subject_id=77, fresh_until=noon(LAST) + timedelta(hours=24), attributes={"player_name": f"Delantero {f}"})
    store(db, item, at=noon(LAST))
    assert check(evaluate(db), "coverage_players").detail["found_about_players"] == 0


def test_a_review_that_cites_a_claim_of_research_v2_fails_the_gate_and_says_to_switch_it_off(world: World) -> None:
    f = world.fixtures[date(2032, 10, 17)][0]
    typed = world.db.execute("SELECT id FROM ai.evidence WHERE fixture_id = %s AND subject_type IS NOT NULL LIMIT 1", (f,)).fetchone()
    assert typed is not None
    world.db.execute(REVIEW, (noon(date(2032, 10, 17)), f, [typed[0]]))
    report = evaluate(world.db)
    assert report.verdict == g.FAIL and failing(report) == ["shadow_invisible"]
    assert check(report, "shadow_invisible").detail == {"reviews_citing": 1, "decisions_citing": 0}
    assert "FBI_AI_RESEARCH_V2=off" in (report.consequence or "")


def test_a_review_that_cites_only_what_v1_wrote_is_what_shadow_is(world: World) -> None:
    f = world.fixtures[date(2032, 10, 17)][0]
    untyped = world.db.execute("SELECT id FROM ai.evidence WHERE fixture_id = %s AND subject_type IS NULL LIMIT 1", (f,)).fetchone()
    assert untyped is not None
    world.db.execute(REVIEW, (noon(date(2032, 10, 17)), f, [untyped[0]]))
    assert check(evaluate(world.db), "shadow_invisible").detail == {"reviews_citing": 0, "decisions_citing": 0}


def test_a_decision_that_cites_a_claim_of_research_v2_fails_the_gate_as_well(world: World) -> None:
    f = world.fixtures[date(2032, 10, 17)][0]
    typed = world.db.execute("SELECT id FROM ai.evidence WHERE fixture_id = %s AND subject_type IS NOT NULL LIMIT 1", (f,)).fetchone()
    untyped = world.db.execute("SELECT id FROM ai.evidence WHERE fixture_id = %s AND subject_type IS NULL LIMIT 1", (f,)).fetchone()
    assert typed is not None and untyped is not None
    kickoff = noon(date(2032, 10, 17)) + timedelta(hours=3)
    world.db.execute(DECISION, (noon(date(2032, 10, 17)), f, kickoff, "d-clean", [untyped[0]]))
    assert check(evaluate(world.db), "shadow_invisible").detail == {"reviews_citing": 0, "decisions_citing": 0}
    world.db.execute(DECISION, (noon(date(2032, 10, 17)), f, kickoff, "d-leak", [untyped[0], typed[0]]))
    report = evaluate(world.db)
    assert check(report, "shadow_invisible").detail == {"reviews_citing": 0, "decisions_citing": 1} and failing(report) == ["shadow_invisible"]


def test_a_decision_of_another_day_does_not_count_for_the_week(world: World) -> None:
    f = world.fixtures[date(2032, 10, 17)][0]
    typed = world.db.execute("SELECT id FROM ai.evidence WHERE fixture_id = %s AND subject_type IS NOT NULL LIMIT 1", (f,)).fetchone()
    assert typed is not None
    for known, name in ((noon(date(2032, 10, 12)), "d-before"), (noon(date(2032, 10, 20)), "d-after")):
        world.db.execute(DECISION, (known, f, known + timedelta(hours=3), name, [typed[0]]))  # known before its kickoff: the table asks for it
    world.db.execute(REVIEW, (noon(date(2032, 10, 12)), f, [typed[0]]))
    assert check(evaluate(world.db), "shadow_invisible").detail == {"reviews_citing": 0, "decisions_citing": 0}


def test_the_week_of_reviews_and_decisions_is_the_same_half_open_interval_of_bogota(world: World) -> None:
    """A review or a decision at the first instant of the week is of it; one at midnight of the day after its last day is the next day's."""
    start, end = day_start(FIRST), day_start(LAST + timedelta(days=1))
    day = world.fixtures[date(2032, 10, 17)]

    def cite(i: int, known: datetime, name: str) -> None:
        typed = world.db.execute("SELECT id FROM ai.evidence WHERE fixture_id = %s AND subject_type IS NOT NULL LIMIT 1", (day[i],)).fetchone()
        assert typed is not None
        world.db.execute(REVIEW, (known, day[i], [typed[0]]))
        world.db.execute(DECISION, (known, day[i], known + timedelta(hours=3), name, [typed[0]]))

    cite(0, start - timedelta(microseconds=1), "d-before")
    cite(1, end, "d-after")
    assert check(evaluate(world.db), "shadow_invisible").detail == {"reviews_citing": 0, "decisions_citing": 0}
    cite(2, start, "d-first-instant")
    cite(3, end - timedelta(microseconds=1), "d-last-instant")
    assert check(evaluate(world.db), "shadow_invisible").detail == {"reviews_citing": 2, "decisions_citing": 2}


def test_a_violation_of_the_nightly_audit_fails_the_gate(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed, audited={date(2032, 10, 15): 1})
    report = evaluate(db)
    assert failing(report) == ["evidence_known"] and check(report, "evidence_known").detail["violations"] == 1
    assert report.verdict == g.FAIL and report.recordable


def test_the_nights_of_the_week_but_the_latest_are_audited(world: World) -> None:
    c = check(evaluate(world.db), "evidence_known")
    assert c.ok is True and c.detail["days_audited"] == 6 and c.detail["days_needed"] == 6 and c.detail["checked"] == 60


def test_two_nights_without_audit_are_pending_not_clean(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed, audited={date(2032, 10, 14): None})
    report = evaluate(db)
    assert check(report, "evidence_known").ok is None and report.verdict == g.PENDING_TIME
    assert "evidence_known" in report.pending[0] and check(report, "evidence_known").detail["days_audited"] == 5


def test_the_last_audit_of_a_night_is_the_one_that_counts(db: psycopg.Connection[Any], seed: Seed) -> None:
    """The audit of a night is run again after a fix (or a regression): the newest run of the night is the truth about it."""
    build(db, seed, audited={date(2032, 10, 15): 2})
    db.execute(AUDIT, (date(2032, 10, 15), noon(date(2032, 10, 20)), 10, 0))  # the 15th, audited again later: clean
    db.execute(AUDIT, (date(2032, 10, 16), noon(date(2032, 10, 20)), 10, 1))  # the 16th, audited again later: one violation
    c = check(evaluate(db), "evidence_known")
    assert c.ok is False and c.detail["violations"] == 1 and c.detail["days_audited"] == 6 and c.detail["checked"] == 60


def test_only_the_audit_of_the_rule_about_evidence_counts(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed)
    db.execute("INSERT INTO intel.audit_checks (day, checked_at, version, rule, n_checked, n_violations, examples) "
               "VALUES (%s, %s, 'leak-audit-v7', 'odds_known', 10, 4, '[]'::jsonb)", (date(2032, 10, 15), noon(date(2032, 10, 16))))
    c = check(evaluate(db), "evidence_known")
    assert c.ok is True and c.detail["violations"] == 0 and c.detail["checked"] == 60


def test_a_week_with_too_few_matches_or_facts_is_pending_not_a_pass(db: psycopg.Connection[Any], seed: Seed) -> None:
    build(db, seed, per_day=2)  # 14 matches
    report = evaluate(db)
    assert report.verdict == g.PENDING_TIME and check(report, "sample").ok is None and "sample" not in failing(report)
    assert check(report, "sample").detail["fixtures_with_facts_of_v1"] == 14


# ── the verdict ──────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("failed_check", "spoil"), [
    ("fewer_searches", {"counts": HEALTHY_PASS | {"v2_paid": 1, "v2_shared": 1}}),
    ("coverage", {"v2_misses_news": 5}),
    ("coverage_players", {"v2_misses_players": 3}),
    ("evidence_known", {"audited": {date(2032, 10, 15): 1}}),
])
def test_any_check_that_fails_alone_makes_the_week_a_failure_that_is_recorded(db: psycopg.Connection[Any], seed: Seed, failed_check: str,
                                                                               spoil: dict[str, Any]) -> None:
    report = evaluate(build(db, seed, **spoil).db)
    assert failing(report) == [failed_check] and report.verdict == g.FAIL and report.recordable and report.pending == ()
    assert report.consequence and report.lines()[0] == "GATE DE RESEARCH V2 · NO PASA"
    row = g.record(db, report)
    assert row is not None and gates.gate_state(db, "research_v2").passed is False


# ── the ledger and the row of the gate ───────────────────────────────────────────────────────────────────────────────

def test_the_extractor_is_counted_by_its_calls_of_extraction_alone(world: World) -> None:
    ledger = UsageLedger(shared(world.db))
    for purpose in ("evidence_extraction", "match_brief"):
        ledger.record(at=noon(date(2032, 10, 17)), purpose=purpose, tier="bulk", provider="anthropic", model="m", usage=None, cost=D("0.001"),
                      status="ok", agent="claim_extractor")
    assert evaluate(world.db).preview["extractor"] == {"calls": 1, "by_status": {"ok": 1}, "invalid_pct": "0.00"}


def test_the_report_carries_what_each_arm_spent_on_exa_and_how_the_extractor_ended(world: World) -> None:
    db = world.db
    ledger = UsageLedger(shared(db))
    for k in range(3):
        ledger.record(at=noon(date(2032, 10, 16)) + timedelta(minutes=k), purpose="web_search", tier="search", provider="exa", model="exa", usage=None,
                      cost=D("0.007"), status="ok", input_hash=f"q{k}")
    ledger.record(at=noon(date(2032, 10, 16)), purpose="web_search", tier="search", provider="exa", model="exa", usage=None, cost=D("0.007"),
                  status="ok", input_hash="rk-v2:search:1")
    ledger.record(at=noon(date(2032, 10, 16)), purpose="web_search", tier="search", provider="exa", model="exa", usage=None, cost=D(0),
                  status="failed", input_hash="rk-v2:search:2", error="x")
    ledger.record(at=noon(date(2032, 10, 3)), purpose="web_search", tier="search", provider="exa", model="exa", usage=None, cost=D("0.007"),
                  status="ok", input_hash="before-the-week")
    for status in ("ok", "ok", "ok", "invalid_output"):
        ledger.record(at=noon(date(2032, 10, 17)), purpose="evidence_extraction", tier="bulk", provider="anthropic", model="m", usage=None, cost=D("0.001"),
                      status=status, agent="claim_extractor")
    ledger.record(at=noon(date(2032, 10, 17)), purpose="evidence_extraction", tier="bulk", provider="anthropic", model="m", usage=None, cost=D("0.001"),
                  status="invalid_output", agent="evidence_extractor")
    preview = evaluate(db).preview
    assert preview["exa"] == {"v1": {"searches": 3, "usd": "0.021000"}, "v2": {"searches": 1, "usd": "0.007000"}}, "only the paid ones, inside the week"
    assert preview["extractor"] == {"calls": 4, "by_status": {"invalid_output": 1, "ok": 3}, "invalid_pct": "25.00"}


def test_a_call_whose_answer_was_not_claim_v1_is_an_invalid_output_in_the_extractor_figures(db: psycopg.Connection[Any], seed: Seed) -> None:
    """The ledger writes down ``ok`` for a call the provider answered, whatever the answer was; the pass counts the answers that were not
    claim-v1 (``v2_invalid``, review of 27 Oct 2026, M2). Without that the figure of the report - and the page of the Console - would say that
    the extractor never fails on content."""
    def shape(day: date, index: int, counts: dict[str, int]) -> dict[str, int]:
        return counts | {"v2_invalid": 1} if day == date(2032, 10, 17) and index < 2 else counts

    world = build(db, seed, shape=shape)
    ledger = UsageLedger(shared(world.db))
    for _ in range(4):
        ledger.record(at=noon(date(2032, 10, 17)), purpose="evidence_extraction", tier="bulk", provider="anthropic", model="m", usage=None,
                      cost=D("0.001"), status="ok", agent="claim_extractor")
    ledger.record(at=noon(date(2032, 10, 18)), purpose="evidence_extraction", tier="bulk", provider="anthropic", model="m", usage=None,
                  cost=D("0.001"), status="invalid_output", agent="claim_extractor")
    assert evaluate(world.db).preview["extractor"] == {"calls": 5, "by_status": {"invalid_output": 3, "ok": 2}, "invalid_pct": "60.00"}
    assert "v2_invalid" in g.DAILY_KEYS


def test_the_answers_that_were_not_claim_v1_of_a_day_outside_the_window_are_not_counted(db: psycopg.Connection[Any], seed: Seed) -> None:
    world = build(db, seed, shape=lambda day, i, c: c | {"v2_invalid": 3} if day == EARLIEST else c)
    ledger = UsageLedger(shared(world.db))
    ledger.record(at=noon(date(2032, 10, 17)), purpose="evidence_extraction", tier="bulk", provider="anthropic", model="m", usage=None,
                  cost=D("0.001"), status="ok", agent="claim_extractor")
    assert evaluate(world.db).preview["extractor"] == {"calls": 1, "by_status": {"ok": 1}, "invalid_pct": "0.00"}


def extraction_calls(db: psycopg.Connection[Any], *calls: tuple[date, str, int]) -> None:
    """``(day, status, how many)`` calls of the claim extractor in the ledger, on the day (at noon, Bogotá)."""
    ledger = UsageLedger(shared(db))
    for day, status, count in calls:
        for k in range(count):
            ledger.record(at=noon(day) + timedelta(minutes=k), purpose="evidence_extraction", tier="bulk", provider="anthropic", model="m", usage=None,
                          cost=D("0.001"), status=status, agent="claim_extractor")


def test_the_answers_that_were_not_claim_v1_are_counted_for_the_days_asked_and_for_no_other(db: psycopg.Connection[Any], seed: Seed) -> None:
    """One such answer a day (the first pass of each day), from the first day of the world to the last: asking for the 14th to the 17th finds
    four, not the one of the 13th nor the ones of the 18th and 19th."""
    build(db, seed, shape=lambda day, i, c: c | {"v2_invalid": 1} if i == 0 else c)
    days = span(EARLIEST, LAST)
    extraction_calls(db, *[(day, "ok", 3) for day in days], (date(2032, 10, 15), "timeout", 1), (date(2032, 10, 16), "invalid_output", 1))
    got = g.extractor(db, date(2032, 10, 14), date(2032, 10, 17))
    assert got == {"calls": 14, "by_status": {"invalid_output": 5, "ok": 8, "timeout": 1}, "invalid_pct": "35.71"}, got
    one = g.extractor(db, date(2032, 10, 14), date(2032, 10, 14))
    assert one == {"calls": 3, "by_status": {"invalid_output": 1, "ok": 2}, "invalid_pct": "33.33"}, one


def test_no_more_answers_are_taken_for_invalid_than_the_provider_answered(db: psycopg.Connection[Any], seed: Seed) -> None:
    """The passes counted twenty-five answers that were not claim-v1 on a day the ledger has two calls answered: a count that does not match the
    ledger moves what the ledger holds and no more, and leaves no status with a negative number of calls or an empty one."""
    build(db, seed, shape=lambda day, i, c: c | {"v2_invalid": 5})
    extraction_calls(db, (date(2032, 10, 16), "ok", 2), (date(2032, 10, 16), "timeout", 3))
    got = g.extractor(db, date(2032, 10, 16), date(2032, 10, 16))
    assert got == {"calls": 5, "by_status": {"invalid_output": 2, "timeout": 3}, "invalid_pct": "40.00"}, got
    assert g.extractor(db, date(2032, 10, 15), date(2032, 10, 15)) == {"calls": 0, "by_status": {}, "invalid_pct": None}, "no call, nothing to move"


def test_a_pass_is_recorded_and_a_pending_verdict_is_not(world: World) -> None:
    db = world.db
    assert gates.gate_state(db, "research_v2").passed is False and gates.research_mode(db, settings("on")) == "shadow"
    pending = evaluate(db, through=date(2032, 10, 18))
    assert g.record(db, pending) is None
    assert db.execute("SELECT count(*) FROM ai.feature_gates WHERE gate = 'research_v2'").fetchone() == (0,)
    report = evaluate(db)
    row = g.record(db, report, code_version="abc123")
    assert row is not None
    stored = db.execute("SELECT gate, passed, decided_by, code_version, evidence_hash, evidence ->> 'verdict' FROM ai.feature_gates WHERE id = %s",
                        (row,)).fetchone()
    assert stored is not None and stored[:4] == ("research_v2", True, "script", "abc123") and stored[5] == "PASA"
    assert stored[4] == gates.evidence_hash(report.as_json()), "anyone can recompute the hash from the stored evidence"
    assert gates.research_mode(db, settings("on")) == "on" and gates.research_mode(db, settings("shadow")) == "shadow"


def test_a_failing_run_after_a_pass_puts_research_v2_back_in_shadow(db: psycopg.Connection[Any], seed: Seed) -> None:
    world = build(db, seed)
    assert g.record(db, evaluate(db)) is not None
    assert gates.typed_visible(db, settings("on")) is True
    for f in world.fixtures[LAST]:  # a second pass of the last day, in which research v2 would have paid forty searches
        db.execute("INSERT INTO ai.fixture_passes (fixture_id, day, pass, started_at, finished_at, kickoff_at, status, counts) "
                   "VALUES (%s, %s, 'pre', %s, %s, %s, 'ok', %s)",
                   (f, LAST, noon(LAST), noon(LAST) + timedelta(minutes=2), noon(LAST) + timedelta(hours=3),
                    Jsonb({"research_v2_shadow": 1, "web_searches": 0, "v2_paid": 40, "v2_demand": 40})))
    later = evaluate(db, at=NOW + timedelta(days=1), through=LAST)
    assert later.verdict == g.FAIL and failing(later) == ["fewer_searches"]
    assert g.record(db, later) is not None
    assert gates.research_mode(db, settings("on")) == "shadow" and gates.typed_visible(db, settings("on")) is False
def test_the_same_data_gives_the_same_report_and_the_same_hash(world: World) -> None:
    a, b = evaluate(world.db), evaluate(world.db)
    assert a.as_json() == b.as_json() and gates.evidence_hash(a.as_json()) == gates.evidence_hash(b.as_json())


def test_evaluating_writes_nothing(world: World) -> None:
    tables = ("ai.feature_gates", "ai.evidence", "ai.fixture_passes", "ai.usage", "ai.research_cache")
    before = [world.db.execute(f"SELECT count(*) FROM {t}").fetchone() for t in tables]
    evaluate(world.db)
    evaluate(world.db, through=date(2032, 10, 18))
    assert [world.db.execute(f"SELECT count(*) FROM {t}").fetchone() for t in tables] == before
