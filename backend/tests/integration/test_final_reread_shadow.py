"""IA-061 (plan AD-A04) over a real database: the last reading of a match before the shadow's final pass, the door of the moments of the facts an
agent reads, and ``leak-audit-v10`` over what they wrote - beside ``leak-audit-v9``, whose rows stay its own.

The case of 12 Nov 2026 (match 180277: the provider moved the kick-off after the packet was built) is replayed both ways: the provider's correction
seen by the reading (the pass stops, nothing is written), and a state written before the correction (the audit says EXPLAINED, never clean in silence
and never a violation of the reading)."""

from __future__ import annotations

import copy
from datetime import timedelta
from typing import Any

import psycopg
import pytest
from psycopg.rows import dict_row

from fbi.ai import final_reread, known_at, orchestrator
from fbi.ai.calendar import local_day
from fbi.ai.evidence import EvidenceIn, store
from fbi.ai.packet import load_packet
from fbi.intel import leakage, leakage_v10
from tests.integration.conftest import Seed
from tests.integration.orchestrator_world import (
    AT,
    RUN,
    SELECTIONS,
    Gear,
    World,
    assign,
    provider,
    rules_review,
    settings,
    world,
)
from tests.integration.test_ai_decision_layer import Savepoints
from tests.integration.test_availability_history import KICKOFF, H
from tests.integration.test_match_runs import passed
from tests.integration.test_slice_leak_audit import STORED, by_hand, honest, scene, stored_at, write

pytestmark = pytest.mark.integration
MINUTE = timedelta(minutes=1)


@pytest.fixture(autouse=True)
def clean_memory() -> None:
    orchestrator._failed.clear()
    orchestrator._aborted.clear()


def go(db: psycopg.Connection[Any], prov: Any = None, **kw: Any) -> orchestrator.Report:
    gear = Gear(db)
    kw.setdefault("at", RUN)
    return orchestrator.run(Savepoints(db), settings(), provider=prov or provider(), ledger=gear.ledger, slots=gear.slots,  # type: ignore[arg-type]
                            circuit=gear.circuit, **kw)


def shadow_rows(db: psycopg.Connection[Any], fixture: int) -> list[dict[str, Any]]:
    with db.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM ai.match_runs WHERE fixture_id = %s AND run_kind = 'shadow' ORDER BY id", (fixture,))
        return list(cur.fetchall())


def written_by_shadow(db: psycopg.Connection[Any], fixture: int) -> int:
    total = 0
    for sql in ("SELECT count(*) FROM ai.agent_tasks WHERE fixture_id = %s", "SELECT count(*) FROM ai.agent_runs WHERE fixture_id = %s",
                "SELECT count(*) FROM ai.match_runs WHERE fixture_id = %s AND run_kind = 'shadow'",
                "SELECT count(*) FROM ai.pick_reviews WHERE fixture_id = %s AND engine IN ('ma-v1', 'ma-v1-h', 'cs-v1')"):
        row = db.execute(sql, (fixture,)).fetchone()
        assert row is not None
        total += int(row[0])
    return total


def newsy(db: psycopg.Connection[Any], seed: Seed, *, pass_kind: str = "final", tamper: bool = False) -> tuple[World, dict[str, Any]]:
    """A match whose packet carries a piece of news (``ai.evidence``) and a pass that stored it, reviewed by production; with ``tamper`` the packet
    is a copy that says the news was known a minute earlier than its row says."""
    w = world(db, seed, n=0, with_pass=False)
    item = EvidenceIn(fixture_id=w.fixture, team_id=w.scene.w.home_team, kind="news", claim="El delantero titular vuelve a la convocatoria.",
                      origin="web", source_name="club.example.com", retrieved_at=AT - H, story_key="ia061-news-1", source_tier="club",
                      source_url="https://club.example.com/news/1", published_at=AT - 2 * H)
    evidence_id, created = store(db, item, at=AT - H)
    assert created
    packet = stored_at(db, w.fixture, AT + 10 * MINUTE, stored=STORED + 10 * MINUTE)
    stored = load_packet(db, packet)
    assert stored is not None and [e["id"] for e in stored.content["evidence"]] == [evidence_id]
    first = stored.content["evidence"][0]
    if tamper:
        content = copy.deepcopy(stored.content)
        moment = final_reread.parse_moment(content["evidence"][0]["retrieved_at"])
        assert moment is not None
        content["evidence"][0]["retrieved_at"] = (moment - MINUTE).isoformat()
        packet = by_hand(db, w.fixture, content, at=AT + 10 * MINUTE, stored=STORED + 10 * MINUTE)
    passed(db, w.fixture, pass_kind, packet)
    for spec in SELECTIONS:
        rules_review(db, w.fixture, packet, spec)
    w.packet = packet
    return w, first


def v10(db: psycopg.Connection[Any], *, run: int = 0) -> dict[str, dict[str, Any]]:
    return leakage_v10.audit_day(db, day=local_day(RUN), at=RUN + timedelta(hours=20, minutes=run))


# ── the final pass that goes on ─────────────────────────────────────────────────────────────────────────────────

def test_an_honest_final_pass_runs_and_its_state_keeps_the_reading_and_the_check_of_its_facts(db: psycopg.Connection[Any], seed: Seed) -> None:
    w, _ = newsy(db, seed)
    assign(db, w.fixture)
    pv = provider()
    report = go(db, pv)
    assert (report.ran, report.reread_aborted, report.reread) == (1, 0, []) and pv.requests
    (state,) = shadow_rows(db, w.fixture)
    rec = state["data_status"]["reread"]
    assert rec["version"] == final_reread.VERSION and rec["ok"] is True and rec["status"] == "NS"
    assert final_reread.parse_moment(rec["kickoff_at"]) == KICKOFF == final_reread.parse_moment(rec["packet_kickoff_at"])
    assert state["known_at"] <= final_reread.parse_moment(rec["at"]) <= state["created_at"]
    facts = state["data_status"]["known_at"]
    assert (facts["version"], facts["ok"], facts["facts"]) == (known_at.VERSION, True, 1)

    out = v10(db)
    assert out["final_reread_known"] == {"checked": 1, "violations": 0, "examples": []}
    assert out["final_started_known"]["violations"] == 0 and out["final_started_explained"]["checked"] == 0
    assert out["news_known"] == {"checked": 1, "violations": 0, "examples": []}
    versions = {r[0] for r in db.execute("SELECT DISTINCT version FROM intel.audit_checks").fetchall()}
    assert versions == {leakage_v10.VERSION}, "v10 writes its own rows only"


def test_a_pre_pass_is_not_read_again_but_its_facts_are_checked(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, seed, pass_kind="pre")
    assign(db, w.fixture)
    assert go(db).ran == 1
    (state,) = shadow_rows(db, w.fixture)
    assert "reread" not in state["data_status"] and state["data_status"]["known_at"]["ok"] is True


# ── the final pass that stops: nothing is written ───────────────────────────────────────────────────────────────

@pytest.mark.parametrize("change, reason", [
    ("UPDATE core.fixtures SET kickoff_at = kickoff_at - interval '1 hour' WHERE id = %s", "kickoff_moved"),  # 12 Nov: moved earlier after the packet
    ("UPDATE core.fixtures SET kickoff_at = kickoff_at + interval '2 hours' WHERE id = %s", "kickoff_moved"),
    ("UPDATE core.fixtures SET status_short = 'PST', status_group = 'postponed' WHERE id = %s", "postponed"),
    ("UPDATE core.fixtures SET status_short = '1H', status_group = 'live' WHERE id = %s", "started"),
    ("UPDATE core.fixtures SET status_short = 'SUSP', status_group = 'postponed' WHERE id = %s", "suspended"),
    ("UPDATE core.fixtures SET status_short = 'CANC', status_group = 'cancelled' WHERE id = %s", "cancelled"),
])
def test_a_final_pass_whose_match_changed_since_the_packet_stops_and_writes_nothing(db: psycopg.Connection[Any], seed: Seed, change: str,
                                                                                     reason: str) -> None:
    w = world(db, seed, pass_kind="final")
    assign(db, w.fixture)
    db.execute(change, (w.fixture,))
    pv = provider()
    report = go(db, pv)
    assert (report.reread_aborted, report.reread, report.ran, report.calls) == (1, [reason], 0, 0) and pv.requests == []
    assert written_by_shadow(db, w.fixture) == 0, "no task, no run, no state, no review: nothing of a match already changed"
    again = go(db, pv)
    assert (again.reread_aborted, again.ran, again.calls) == (0, 0, 0) and written_by_shadow(db, w.fixture) == 0, "not read again by the process"


def test_a_match_the_in_play_odds_feed_sees_playing_stops_the_final_pass(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, seed, pass_kind="final")
    assign(db, w.fixture)
    db.execute("INSERT INTO market.live_fixture_current (fixture_id, first_seen_at, captured_at, is_finished, payload_hash) VALUES (%s, %s, %s, false, 'h')",
               (w.fixture, RUN - 3 * MINUTE, RUN - MINUTE))
    report = go(db)
    assert (report.reread_aborted, report.reread) == (1, ["started"]) and written_by_shadow(db, w.fixture) == 0


def test_a_capture_of_the_in_play_feed_that_is_old_or_finished_does_not_stop_it(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, seed, pass_kind="final")
    assign(db, w.fixture)
    db.execute("INSERT INTO market.live_fixture_current (fixture_id, first_seen_at, captured_at, is_finished, payload_hash) VALUES (%s, %s, %s, false, 'h')",
               (w.fixture, RUN - 30 * MINUTE, RUN - 20 * MINUTE))
    assert go(db).ran == 1


# ── the door of the moments of the facts ────────────────────────────────────────────────────────────────────────

def test_a_packet_that_copied_the_moment_of_a_fact_wrong_is_not_given_to_an_agent_and_the_audit_finds_it(db: psycopg.Connection[Any],
                                                                                                           seed: Seed) -> None:
    w, first = newsy(db, seed, pass_kind="pre", tamper=True)
    assign(db, w.fixture)
    pv = provider()
    report = go(db, pv)
    assert (report.not_run, report.ran, report.calls) == (1, 0, 0) and pv.requests == []
    (state,) = shadow_rows(db, w.fixture)
    assert (state["final"]["status"], state["final"]["reason"]) == ("not_run", "known_at:fact_stamp_differs")
    rec = state["data_status"]["known_at"]
    assert (rec["version"], rec["ok"], rec["codes"], rec["ids"]) == (known_at.VERSION, False, ["fact_stamp_differs"], [first["id"]])
    out = v10(db)
    assert out["news_known"] == {"checked": 1, "violations": 1, "examples": [state["id"]]}


# ── leak-audit-v10 over the states of the day ───────────────────────────────────────────────────────────────────

def _final_state(db: psycopg.Connection[Any], seed: Seed, *, kickoff_now: Any, change: Any = None) -> int:
    """A live state of a final pass written at ``WRITTEN`` from the scene's packet; then the kick-off of today is ``kickoff_now`` and, when ``change``
    is given, a change of the kick-off observed after the writing that says what the provider stated when it was written."""
    s = scene(db, seed)
    row = write(db, honest(db, s.packet, pass_kind="final", written=RUN))
    db.execute("UPDATE core.fixtures SET kickoff_at = %s WHERE id = %s", (kickoff_now, s.w.fixture))
    if change is not None:
        before, observed = change
        db.execute("INSERT INTO core.fixture_kickoff_changes (fixture_id, observed_at, before_kickoff, after_kickoff, payload_hash) "
                   "VALUES (%s, %s, %s, %s, NULL)", (s.w.fixture, observed, before, kickoff_now))
    return row


def test_a_state_like_6912_is_explained_by_the_provider_and_v9_still_counts_it(db: psycopg.Connection[Any], seed: Seed) -> None:
    """The state was written before the kick-off the provider stated then; the provider moved the kick-off before that moment afterwards."""
    s_kick = AT - 30 * MINUTE  # today's kick-off: before the state's moment of knowledge (the packet's, AT)
    row = _final_state(db, seed, kickoff_now=s_kick, change=(KICKOFF, RUN + timedelta(hours=15)))
    out = v10(db)
    assert out["final_started_known"]["violations"] == 0 and out["final_started_explained"] == {"checked": 1, "violations": 0, "examples": [row]}
    assert out["final_reread_known"]["checked"] == 0, "a live state is not the shadow's: the reading is the shadow's"
    v9 = leakage.slice_known(db, *_bounds())
    assert v9[1] == 1 and v9[2] == [row], "v9 is not relaxed: the state was written with the match under way, and v9 still says so"


def test_a_state_written_when_its_own_data_had_the_match_started_is_a_violation_of_v10(db: psycopg.Connection[Any], seed: Seed) -> None:
    row = _final_state(db, seed, kickoff_now=AT - 30 * MINUTE)
    out = v10(db)
    assert out["final_started_known"] == {"checked": 1, "violations": 1, "examples": [row]}
    assert out["final_started_explained"]["checked"] == 0


def test_once_the_reading_exists_a_shadow_final_state_without_one_is_a_violation(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, seed, pass_kind="final")
    assign(db, w.fixture)
    assert go(db).ran == 1
    (state,) = shadow_rows(db, w.fixture)
    other = honest(db, w.packet, pass_kind="final", run_kind="shadow", written=state["created_at"] + MINUTE)
    other["known_at"] = other["known_at"] + timedelta(seconds=1)  # another moment: the table keeps one state per match, pass and moment
    bare = write(db, other)
    out = v10(db)
    assert out["final_reread_known"]["checked"] == 2 and out["final_reread_known"]["examples"] == [bare]


def test_a_state_of_before_the_reading_existed_is_not_judged_for_it(db: psycopg.Connection[Any], seed: Seed) -> None:
    s = scene(db, seed)
    write(db, honest(db, s.packet, pass_kind="final", run_kind="shadow", written=RUN))
    out = v10(db)
    assert out["final_reread_known"] == {"checked": 0, "violations": 0, "examples": []}


def test_a_package_this_code_cannot_derive_again_is_a_violation_of_news_known(db: psycopg.Connection[Any], seed: Seed) -> None:
    s = scene(db, seed)
    values = honest(db, s.packet, written=RUN)
    values["package_version"] = "package-v99"
    row = write(db, values)
    out = v10(db)
    assert out["news_known"]["violations"] >= 1 and row in out["news_known"]["examples"]


def test_v10_runs_after_v9_in_the_night_with_its_own_rows(db: psycopg.Connection[Any], seed: Seed) -> None:
    s = scene(db, seed)
    write(db, honest(db, s.packet, pass_kind="final", written=RUN))
    day, at = local_day(RUN), RUN + timedelta(hours=20)
    leakage.audit_day(db, day=day, at=at)
    leakage_v10.audit_day(db, day=day, at=at)
    got = {(v, r) for v, r in db.execute("SELECT version, rule FROM intel.audit_checks WHERE day = %s", (day,)).fetchall()}
    assert {r for v, r in got if v == leakage.VERSION} == set(leakage.RULE_NAMES)
    assert {r for v, r in got if v == leakage_v10.VERSION} == set(leakage_v10.RULE_NAMES)


def _bounds() -> tuple[Any, Any]:
    from fbi.ai.calendar import day_bounds

    return day_bounds(local_day(RUN))
