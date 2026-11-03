"""The nightly proof of the shadow (plan IA, phase 3): ``agent_known`` over ``ai.agent_runs`` and ``shadow_review_known`` over the reviews of the
engines of the shadow (``ma-v1``, ``ma-v1-h``, ``cs-v1``) in ``ai.pick_reviews``; and the pin of ``review_known`` (it filters no engine).

The rows are seeded by hand (the orchestrator that writes them is another module): good ones give 0 violations with n > 0; each way a row can
leak, one at a time, is the only violation of a day that also has honest rows; the tables empty give ``(0, 0, [])``; and ``audit_day`` keeps one
row per rule in ``intel.audit_checks``, which is where Gate B reads ``n`` (``shadow_review_known_has_data``)."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb

from fbi.ai.calendar import local_day
from fbi.intel import leakage
from tests.integration.conftest import Seed

pytestmark = pytest.mark.integration

H = timedelta(hours=1)
MIN = timedelta(minutes=1)
KICKOFF = datetime.fromisoformat("2026-09-15T19:00:00+00:00")  # the kick-off of the seeded fixture
KNOWN = KICKOFF - 6 * H  # the moment of the packet and of the package: 08:00 in Bogota
STORED = KNOWN + MIN
START = KNOWN + 5 * MIN  # an agent run begins
REVIEWED = KNOWN + 30 * MIN
RAN = KICKOFF + 12 * H
DAY = local_day(START)


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def scalar(db: psycopg.Connection[Any], sql: str, *args: object) -> Any:
    row = db.execute(sql, args).fetchone()
    assert row is not None
    return row[0]


def audited(db: psycopg.Connection[Any], rule: str) -> tuple[int, int, list[int]]:
    start, end = leakage.day_bounds(DAY)
    return leakage.PYTHON_RULES[rule](db, start, end)


def packet(db: psycopg.Connection[Any], seed: Seed, *, at: datetime = KNOWN, stored: datetime = STORED, fixture: int | None = None,
           tag: str = "a") -> int:
    content = {"tag": tag}
    return int(scalar(db, "INSERT INTO ai.match_packets (fixture_id, packet_version, as_of, built_at, packet_hash, content) "
                          "VALUES (%s, 'packet-v8', %s, %s, %s, %s) RETURNING id",
                      fixture or seed.fixture_id, at, stored, digest(f"{tag}{at}{json.dumps(content)}"), Jsonb(content)))


def evidence(db: psycopg.Connection[Any], seed: Seed, tag: str, *, retrieved: datetime = KNOWN - H, published: datetime | None = None) -> int:
    return int(scalar(db, "INSERT INTO ai.evidence (fixture_id, kind, claim, origin, source_name, source_tier, published_at, retrieved_at, "
                          "story_key, content_hash, confidence, relevance, status, status_reason, status_changed_at) "
                          "VALUES (%s, 'injury', %s, 'provider', 'test', 'provider', %s, %s, %s, %s, 0.9, 0.9, 'CONFIRMED', 'test', %s) RETURNING id",
                      seed.fixture_id, f"claim of {tag} for the audit", published, retrieved, f"story-{tag}", digest(tag), retrieved))


def state(db: psycopg.Connection[Any], seed: Seed, packet_id: int, *, package: str, known: datetime = KNOWN, pass_kind: str = "pre",
          run_kind: str = "shadow") -> int:
    return int(scalar(db, "INSERT INTO ai.match_runs (fixture_id, run_kind, pass_kind, known_at, created_at, state_version, package_version, "
                          "package_hash, packet_id) VALUES (%s, %s, %s, %s, %s, 'ms-v1', 'mcp-v1', %s, %s) RETURNING id",
                      seed.fixture_id, run_kind, pass_kind, known, START + 10 * MIN, package, packet_id))


def agent_run(db: psycopg.Connection[Any], seed: Seed, key: str, *, package: str | None = None, known: datetime | None = KNOWN,
              started: datetime = START, finished: datetime | None = None, evidence_ids: list[int] | None = None, parent: int | None = None,
              output: dict[str, Any] | None = None, agent: str = "council", run_kind: str = "shadow", fixture: int | None = None) -> int:
    """One paid run of an agent (status ok: a model, its tokens and an output) as the orchestrator writes it."""
    return int(scalar(
        db,
        "INSERT INTO ai.agent_runs (run_kind, reason, parent_run_id, task_kind, pass_kind, fixture_id, started_at, finished_at, known_at, model, "
        "agent, agent_version, prompt_version, schema_version, router_version, package_hash, idem_key, evidence_ids, output, verdict, "
        "input_tokens, output_tokens, status) VALUES (%s, 'pre pass', %s, 'council', 'pre', %s, %s, %s, %s, 'claude-sonnet-5-5', %s, 'council-v1', "
        "'council-v1', 'cd-v1', 'router-v1', %s, %s, %s, %s, 'APPROVE', 100, 20, 'ok') RETURNING id",
        run_kind, parent, fixture if fixture is not None else seed.fixture_id, started, finished or started + MIN, known, agent, package,
        digest(key), evidence_ids or [], Jsonb(output if output is not None else {"refs": []})))


def review(db: psycopg.Connection[Any], seed: Seed, key: str, *, engine: str = "ma-v1", packet_id: int | None, reviewed: datetime = REVIEWED,
           evidence_ids: list[int] | None = None, fixture: int | None = None, selection: str = "HOME") -> int:
    return int(scalar(
        db,
        "INSERT INTO ai.pick_reviews (reviewed_at, fixture_id, market_key, selection, line, odds, bookmaker_id, p_model, p_low, p_market, edge, "
        "ev, engine, engine_version, packet_id, input_hash, decision, confidence, output, evidence_ids, mode, status) VALUES (%s, %s, '1X2', %s, "
        "0, 2.1, %s, 0.5, 0.45, 0.45, 0.05, 0.05, %s, 'ma-v1', %s, %s, 'APPROVE', 0.6, '{}'::jsonb, %s, 'shadow', 'ok') RETURNING id",
        reviewed, fixture or seed.fixture_id, selection, seed.bookmaker_id, engine, packet_id, digest(key), evidence_ids or []))


# ── agent_known ──────────────────────────────────────────────────────────────────────────────────────────────────────

def good_runs(db: psycopg.Connection[Any], seed: Seed) -> dict[str, int]:
    """A Match Agent run and the Council run that read it, over a package of a stored packet and one evidence known before the package."""
    pk = packet(db, seed)
    package = digest("package")
    state(db, seed, pk, package=package)
    ev = evidence(db, seed, "good")
    match = agent_run(db, seed, "match", package=package, evidence_ids=[ev], agent="match", output={"refs": [f"E:{ev}", "P:market"]})
    council = agent_run(db, seed, "council", package=package, evidence_ids=[ev], parent=match, started=START + 2 * MIN, finished=START + 3 * MIN)
    return {"packet": pk, "match": match, "council": council, "evidence": ev}


def test_good_runs_pass_and_are_counted(db: psycopg.Connection[Any], seed: Seed) -> None:
    good_runs(db, seed)
    assert audited(db, "agent_known") == (2, 0, [])


def test_a_run_that_cites_evidence_retrieved_after_its_package_is_the_one_violation(db: psycopg.Connection[Any], seed: Seed) -> None:
    g = good_runs(db, seed)
    late = evidence(db, seed, "late", retrieved=KNOWN + 2 * MIN)  # known before the run began, not by the moment of the package
    bad = agent_run(db, seed, "leak-evidence", package=digest("package"), evidence_ids=[late], started=START + 4 * MIN)
    assert audited(db, "agent_known") == (3, 1, [bad])
    assert g["council"] != bad


def test_a_run_that_cites_evidence_only_in_its_output_is_judged_too(db: psycopg.Connection[Any], seed: Seed) -> None:
    good_runs(db, seed)
    late = evidence(db, seed, "late-output", retrieved=KNOWN + 2 * MIN)
    bad = agent_run(db, seed, "leak-output", package=digest("package"), started=START + 4 * MIN, output={"drivers": [{"refs": [f"E:{late}"]}]})
    assert audited(db, "agent_known") == (3, 1, [bad])


def test_a_run_that_cites_evidence_published_later_or_that_does_not_exist_is_a_violation(db: psycopg.Connection[Any], seed: Seed) -> None:
    good_runs(db, seed)
    known = evidence(db, seed, "exists")  # (published_at <= retrieved_at is a CHECK: a later publication cannot be seeded; the unit tests hold it)
    ghost = agent_run(db, seed, "ghost", package=digest("package"), evidence_ids=[known + 100000], started=START + 4 * MIN)
    assert audited(db, "agent_known") == (3, 1, [ghost])


def test_a_run_over_a_package_no_state_of_its_match_names_is_a_violation(db: psycopg.Connection[Any], seed: Seed) -> None:
    good_runs(db, seed)
    bad = agent_run(db, seed, "no-package", package=digest("a package nobody stored"), started=START + 4 * MIN)
    assert audited(db, "agent_known") == (3, 1, [bad])


def test_a_run_whose_package_came_from_a_packet_stored_after_it_began_is_a_violation(db: psycopg.Connection[Any], seed: Seed) -> None:
    pk = packet(db, seed, stored=START + 20 * MIN, tag="late")
    package = digest("late package")
    state(db, seed, pk, package=package, pass_kind="final")
    bad = agent_run(db, seed, "early", package=package)
    assert audited(db, "agent_known") == (1, 1, [bad])


def test_a_run_with_another_moment_than_the_package_or_after_the_kickoff_or_with_none_is_a_violation(db: psycopg.Connection[Any], seed: Seed) -> None:
    good_runs(db, seed)
    other = agent_run(db, seed, "other-moment", package=digest("package"), known=KNOWN - MIN, started=START + 4 * MIN)
    none = agent_run(db, seed, "no-moment", package=digest("package"), known=None, started=START + 5 * MIN)
    assert audited(db, "agent_known") == (4, 2, [other, none])


def test_a_council_that_read_an_assessment_that_finished_after_it_began_is_a_violation(db: psycopg.Connection[Any], seed: Seed) -> None:
    g = good_runs(db, seed)
    late_parent = agent_run(db, seed, "slow-match", package=digest("package"), agent="match", started=START + 6 * MIN, finished=START + 9 * MIN)
    bad = agent_run(db, seed, "early-council", package=digest("package"), parent=late_parent, started=START + 7 * MIN)
    assert audited(db, "agent_known") == (4, 1, [bad])
    assert g["match"] != late_parent


def test_a_council_whose_assessment_is_of_another_match_is_a_violation(db: psycopg.Connection[Any], seed: Seed) -> None:
    good_runs(db, seed)
    other_fixture = int(scalar(db, "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at) "
                                   "VALUES (1002, %s, %s, %s, %s) RETURNING id", seed.season_id, seed.away_team_id, seed.home_team_id, KICKOFF))
    foreign = agent_run(db, seed, "foreign-match", agent="match", package=None, known=None, started=START - MIN, fixture=other_fixture)
    bad = agent_run(db, seed, "council-of-another", package=digest("package"), parent=foreign, started=START + 4 * MIN)
    assert audited(db, "agent_known") == (4, 1, [bad])


def test_the_battery_and_the_runs_of_other_days_are_not_read(db: psycopg.Connection[Any], seed: Seed) -> None:
    good_runs(db, seed)
    agent_run(db, seed, "battery", run_kind="battery", package=digest("synthetic"), started=START + 4 * MIN)
    agent_run(db, seed, "yesterday", package=digest("old"), known=KNOWN - 48 * H, started=START - 48 * H)
    assert audited(db, "agent_known") == (2, 0, [])


# ── shadow_review_known ──────────────────────────────────────────────────────────────────────────────────────────────

def test_good_shadow_reviews_of_every_shadow_engine_pass_and_are_counted(db: psycopg.Connection[Any], seed: Seed) -> None:
    pk = packet(db, seed)
    ev = evidence(db, seed, "review-good")
    for i, engine in enumerate(("ma-v1", "ma-v1-h", "cs-v1")):
        review(db, seed, f"good-{engine}", engine=engine, packet_id=pk, evidence_ids=[ev], selection=f"S{i}")
    assert audited(db, "shadow_review_known") == (3, 0, [])


def test_a_shadow_review_that_cites_evidence_known_after_it_was_written_is_the_one_violation(db: psycopg.Connection[Any], seed: Seed) -> None:
    pk = packet(db, seed)
    good = evidence(db, seed, "before")
    after = evidence(db, seed, "after", retrieved=REVIEWED + MIN)
    review(db, seed, "honest", packet_id=pk, evidence_ids=[good])
    bad = review(db, seed, "leaky", packet_id=pk, evidence_ids=[good, after], selection="DRAW")
    assert audited(db, "shadow_review_known") == (2, 1, [bad])


def test_a_shadow_review_that_cites_evidence_after_its_packet_but_before_itself_is_a_violation(db: psycopg.Connection[Any], seed: Seed) -> None:
    pk = packet(db, seed)
    between = evidence(db, seed, "between", retrieved=KNOWN + 10 * MIN)
    bad = review(db, seed, "not-in-the-packet", packet_id=pk, evidence_ids=[between])
    assert audited(db, "shadow_review_known") == (1, 1, [bad])


def test_a_shadow_review_with_no_packet_a_late_packet_or_after_the_kickoff_is_a_violation(db: psycopg.Connection[Any], seed: Seed) -> None:
    good_pk = packet(db, seed)
    late_pk = packet(db, seed, at=KNOWN + 20 * MIN, stored=REVIEWED + MIN, tag="late")
    review(db, seed, "honest", packet_id=good_pk)
    none = review(db, seed, "none", packet_id=None, selection="DRAW")
    late = review(db, seed, "late", packet_id=late_pk, selection="AWAY")
    after_kickoff = review(db, seed, "kickoff", packet_id=good_pk, reviewed=KICKOFF, selection="OVER")
    assert leakage.day_bounds(DAY)[0] <= KICKOFF < leakage.day_bounds(DAY)[1]
    assert audited(db, "shadow_review_known") == (4, 3, [none, late, after_kickoff])


def test_the_reviews_of_production_are_not_this_rules_business(db: psycopg.Connection[Any], seed: Seed) -> None:
    review(db, seed, "rules-no-packet", engine="rules", packet_id=None)
    review(db, seed, "combined-no-packet", engine="combined", packet_id=None, selection="DRAW")
    assert audited(db, "shadow_review_known") == (0, 0, [])


# ── review_known: it filters no engine ───────────────────────────────────────────────────────────────────────────────

def test_review_known_has_no_filter_on_the_engine_and_reads_whatever_review_a_decision_links() -> None:
    sql = leakage.RULES["review_known"]
    assert "engine" not in sql and "JOIN ai.pick_reviews r ON r.id = d.review_id" in sql, "any engine a decision links is judged; the shadow links none"


# ── nothing to read ──────────────────────────────────────────────────────────────────────────────────────────────────

def test_empty_tables_give_nothing_checked_and_no_violation(db: psycopg.Connection[Any], seed: Seed) -> None:
    assert audited(db, "agent_known") == (0, 0, [])
    assert audited(db, "shadow_review_known") == (0, 0, [])


# ── the night ────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_night_keeps_one_row_per_rule_and_gate_b_reads_n_from_it(db: psycopg.Connection[Any], seed: Seed) -> None:
    out = leakage.audit_day(db, day=DAY, at=RAN)
    assert out["shadow_review_known"] == {"checked": 0, "violations": 0, "examples": []}
    assert leakage.shadow_review_known_has_data(db, day=DAY) is False, "the shadow wrote nothing: Gate B does not count that night as seen"
    assert leakage.passes_gate("shadow_review_known", out["shadow_review_known"]["checked"], out["shadow_review_known"]["violations"]) is False

    pk = packet(db, seed)
    ev = evidence(db, seed, "night")
    review(db, seed, "night-honest", packet_id=pk, evidence_ids=[ev])
    bad = review(db, seed, "night-bad", packet_id=None, selection="DRAW")
    good_runs(db, seed)
    out = leakage.audit_day(db, day=DAY, at=RAN + H)
    assert list(out) == list(leakage.RULE_NAMES)
    assert out["shadow_review_known"] == {"checked": 2, "violations": 1, "examples": [bad]}
    assert out["agent_known"]["checked"] == 2 and out["agent_known"]["violations"] == 0
    assert leakage.shadow_review_known_has_data(db, day=DAY) is True, "the newest row of the day is the one Gate B reads"
    assert leakage.shadow_review_known_has_data(db, day=DAY + timedelta(days=3)) is False, "a day not audited has no row"
    for rule in ("agent_known", "shadow_review_known"):
        n = scalar(db, "SELECT count(*) FROM intel.audit_checks WHERE day = %s AND rule = %s", DAY, rule)
        assert n == 2, "one row per rule per run, both runs kept"
    kept = db.execute("SELECT version, n_checked, n_violations, examples FROM intel.audit_checks WHERE rule = 'shadow_review_known' "
                      "AND checked_at = %s", (RAN + H,)).fetchall()
    assert kept == [("leak-audit-v8", 2, 1, [bad])]
