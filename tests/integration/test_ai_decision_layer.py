"""The AI decision layer on a built world (``test_daily_records.World``): the frozen packet and its change log,
append-only storage, evidence with provenance, the analysis cycle with a scripted model (approve, invalid answer,
timeout, exhausted budget, an answer reused instead of paid twice), the picks of the day with the AI's review
recorded and - only with enforcement on AND a passed gate - applied, and the evolution decisions.

No network and no key: the model is ``FakeProvider``. Everything happens inside one transaction (commits become
savepoints) and is rolled back."""

from __future__ import annotations

import json
from collections.abc import Iterator
from datetime import timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb

from fbi.ai.config import AiSettings
from fbi.ai.cycle import run_analysis_cycle, run_learning_cycle
from fbi.ai.evidence import EvidenceIn, refresh_statuses, seed_sources, store
from fbi.ai.packet import build_packet, store_packet
from fbi.ai.providers.base import JsonRequest
from fbi.ai.providers.fake import FakeProvider
from fbi.ai.usage import UsageLedger, shared
from fbi.picks.daily import build_daily_sets, product_day
from fbi.research import evolution

from .conftest import Seed
from .test_daily_records import AT, World

SHADOW = AiSettings(mode="shadow")


class Savepoints:
    """The connection as the worker sees it, except that commit and rollback stay inside the test's own
    transaction (a savepoint), so the whole test can still be rolled back."""

    def __init__(self, conn: psycopg.Connection[Any]) -> None:
        self._conn = conn
        self._n = 0
        self._open()

    def _open(self) -> None:
        self._n += 1
        self._conn.execute(f"SAVEPOINT ai_test_{self._n}")

    def commit(self) -> None:
        self._conn.execute(f"RELEASE SAVEPOINT ai_test_{self._n}")
        self._open()

    def rollback(self) -> None:
        self._conn.execute(f"ROLLBACK TO SAVEPOINT ai_test_{self._n}")

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)


@pytest.fixture()
def world(db: psycopg.Connection[Any], seed: Seed) -> Iterator[World]:
    yield World(db, seed)


def review_reply(decision: str = "APPROVE", **over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "decision": decision, "confidence": 0.7, "context_score": 0.6, "model_score": 0.6, "market_score": 0.5,
        "positive_evidence": [{"text": "Modelo 50.0 % frente a mercado 43.0 %.", "type": "DATA",
                               "refs": ["P:candidate", "P:market"]}],
        "negative_evidence": [{"text": "El mercado ya descuenta parte de la ventaja.", "type": "INFERENCE",
                               "refs": ["P:market"]}] if decision in ("REJECT", "DOWNGRADE") else [],
        "uncertainties": [], "contradictions": [], "reason": "Revisión de prueba.",
        "minimum_playable_odds": 1.01, "fair_odds": 1.01,
    }
    return body | over


def brief_reply(**over: Any) -> dict[str, Any]:
    body: dict[str, Any] = {"summary": "Partido de prueba con mercado observado.", "context": [], "injuries": [],
                            "changes": [], "data_quality": "good", "uncertainty": "low", "contradiction": False,
                            "escalate": False, "cards": []}
    return body | over


def fake(decision: str = "APPROVE", **kw: Any) -> FakeProvider:
    """A model that answers each kind of request in its own shape (a brief, a review)."""
    return FakeProvider(lambda r: brief_reply() if r.schema_name == "submit_brief" else review_reply(decision),
                        name="anthropic", **kw)


def reviews_asked(model: FakeProvider) -> list[JsonRequest]:
    return [r for r in model.requests if r.schema_name == "submit_review"]


def cycle(conn: Any, *, at: Any = AT, provider: FakeProvider | None = None, model: str = "claude-haiku-5-5",
          only: list[int] | None = None, settings: AiSettings = SHADOW) -> Any:
    return run_analysis_cycle(conn, at=at, settings=settings, ledger=UsageLedger(shared(conn._conn)),
                              only_fixtures=only, provider=None if provider is None else (provider, model))


def count(db: psycopg.Connection[Any], sql: str, *params: Any) -> int:
    row = db.execute(sql, params).fetchone()
    return int(row[0]) if row else 0


# ── packets: what a review could know, and only that ────────────────────────

def test_a_packet_has_provenance_and_is_stored_as_a_change_log(db: psycopg.Connection[Any], world: World) -> None:
    f1 = world.fixtures["F1"]
    p = build_packet(db, f1, at=AT)
    assert p is not None
    assert p.content["market"]["observed"] is True and "dixon_coles" in p.content["models"]
    blocks = {s["block"] for s in p.sources}
    assert {"fixture", "market", "models", "quality"} <= blocks
    assert "absences" in p.missing and "standings" in p.missing, "what could not be filled is said, not invented"
    first = store_packet(db, p, built_at=AT)
    assert store_packet(db, build_packet(db, f1, at=AT + timedelta(minutes=5)) or p, built_at=AT) == first, \
        "the same context is stored once"
    world.price("F1", "2.60", AT + timedelta(minutes=10))
    changed = build_packet(db, f1, at=AT + timedelta(minutes=15))
    assert changed is not None and changed.hash != p.hash
    second = store_packet(db, changed, built_at=AT + timedelta(minutes=15))
    assert second != first
    # nothing recorded after the packet's moment is in it
    late = build_packet(db, f1, at=AT - timedelta(hours=2))
    assert late is not None and late.content["market"]["observed"] is False


def test_ai_results_are_append_only(db: psycopg.Connection[Any], world: World) -> None:
    p = build_packet(db, world.fixtures["F1"], at=AT)
    assert p is not None
    pid = store_packet(db, p, built_at=AT)
    for sql in ("UPDATE ai.match_packets SET approx_tokens = 1 WHERE id = %s", "DELETE FROM ai.match_packets WHERE id = %s"):
        with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
            db.execute(sql, (pid,))
    with db.transaction():
        db.execute("SET LOCAL fbi.ai_maintenance = 'on'")
        db.execute("UPDATE ai.match_packets SET approx_tokens = approx_tokens WHERE id = %s", (pid,))


# ── evidence ─────────────────────────────────────────────────────────────────

def test_evidence_is_stored_once_classified_and_its_content_never_changes(db: psycopg.Connection[Any],
                                                                          world: World) -> None:
    f1 = world.fixtures["F1"]
    seed_sources(db, at=AT)
    team = db.execute("SELECT home_team_id FROM core.fixtures WHERE id = %s", (f1,)).fetchone()
    assert team is not None
    unknown = EvidenceIn(fixture_id=f1, team_id=int(team[0]), kind="injury", claim="Dicen que el 10 no juega",
                         origin="web", source_name="Blog", retrieved_at=AT - timedelta(hours=3),
                         story_key=f"web:{f1}:home:10:injury:out", assertion="out", provider_player_id=10,
                         source_url="https://blog-de-rumores.example/x", attributes={"player_name": "Diez"})
    item = EvidenceIn(fixture_id=f1, team_id=int(team[0]), kind="injury", claim="El 9 no juega por lesión",
                      origin="web", source_name="El Tiempo", retrieved_at=AT - timedelta(hours=3),
                      story_key=f"web:{f1}:home:9:injury:out", assertion="out", provider_player_id=9,
                      source_url="https://www.eltiempo.com/deportes/nota", published_at=AT - timedelta(hours=4),
                      attributes={"player_name": "Nueve"})
    rumour, _ = store(db, unknown, at=AT)
    first, created = store(db, item, at=AT)
    again, created_again = store(db, item, at=AT)
    assert created and not created_again and first == again, "a duplicate story is one row"
    other = EvidenceIn(**{**item.__dict__, "source_name": "El Espectador",
                          "source_url": "https://www.elespectador.com/deportes/x"})
    store(db, other, at=AT)
    counts = refresh_statuses(db, f1, at=AT, kickoff=AT + timedelta(hours=2), lineup_starters={},
                              absences_checked_at=None)
    assert counts.get("CONFIRMED") == 2, "two independent reputable outlets confirm"
    assert db.execute("SELECT status, source_tier FROM ai.evidence WHERE id = %s", (rumour,)).fetchone() == \
        ("RUMOR", "unknown"), "an unknown site is a rumour"
    # the confirmed eleven then says otherwise: the report is outdated, and the history keeps both statuses
    refresh_statuses(db, f1, at=AT, kickoff=AT + timedelta(hours=2), lineup_starters={int(team[0]): {9}},
                     absences_checked_at=None)
    row = db.execute("SELECT status, status_history FROM ai.evidence WHERE id = %s", (first,)).fetchone()
    assert row is not None and row[0] == "OUTDATED" and len(row[1]) >= 2
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        db.execute("UPDATE ai.evidence SET claim = 'otra cosa' WHERE id = %s", (first,))
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        db.execute("DELETE FROM ai.evidence WHERE id = %s", (first,))


# ── the cycle ────────────────────────────────────────────────────────────────

def test_without_a_model_the_rules_review_every_shortlisted_selection(db: psycopg.Connection[Any],
                                                                      world: World) -> None:
    conn = Savepoints(db)
    report = cycle(conn)
    assert report.status == "ok", report.errors
    assert report.counts["shortlist"] >= 3 and report.counts["llm_reviews"] == 0
    reviews = db.execute("SELECT engine, decision, mode FROM ai.pick_reviews WHERE fixture_id = ANY(%s)",
                         (list(world.fixtures.values()),)).fetchall()
    assert {r[0] for r in reviews} == {"rules", "combined"} and {r[2] for r in reviews} == {"shadow"}
    analyses = count(db, "SELECT count(*) FROM ai.match_analyses WHERE fixture_id = ANY(%s)",
                     list(world.fixtures.values()))
    assert analyses == len(world.fixtures)
    rows_before = count(db, "SELECT count(*) FROM ai.pick_reviews")
    cycle(conn, at=AT + timedelta(minutes=10))
    assert count(db, "SELECT count(*) FROM ai.pick_reviews") == rows_before, "nothing changed, nothing added"
    assert count(db, "SELECT count(*) FROM ai.usage") == 0, "no model, no search, no cost"


def test_a_model_review_is_validated_combined_conservatively_and_paid_once(db: psycopg.Connection[Any],
                                                                           world: World) -> None:
    conn = Savepoints(db)
    model = fake("REJECT")
    only = [world.fixtures["F1"]]
    report = cycle(conn, provider=model, only=only)
    assert report.counts["llm_reviews"] == 1 and len(reviews_asked(model)) == 1
    assert [r.schema_name for r in model.requests] == ["submit_brief", "submit_review"], "the L1 brief comes first"
    sent = json.loads(reviews_asked(model)[0].user)
    assert sent["candidate"]["fixture_id"] == only[0] and "packet" in sent and "untrusted" in sent["note"]
    rows = {r[0]: r for r in db.execute(
        "SELECT engine, decision, status, cost_usd, output FROM ai.pick_reviews WHERE fixture_id = %s", (only[0],))}
    assert rows["llm"][1] == "REJECT" and rows["llm"][2] == "ok" and rows["llm"][3] > 0
    assert rows["combined"][1] == "REJECT", "the most conservative opinion wins"
    out = rows["llm"][4]
    assert out["fair_odds"] != 1.01 and out["model_fair_odds"] == 1.01, "the server's own odds, not the model's"
    usage = db.execute("SELECT purpose, status, input_tokens > 0, cost_usd > 0 FROM ai.usage ORDER BY id").fetchall()
    assert usage == [("match_brief", "ok", True, True), ("pick_review", "ok", True, True)]
    # ten minutes later, nothing changed: the review stays in force and is not bought again
    cycle(conn, at=AT + timedelta(minutes=10), provider=model, only=only)
    assert len(model.requests) == 2
    newest = db.execute("SELECT decision, output->'engines' FROM ai.pick_reviews WHERE fixture_id = %s AND "
                        "engine = 'combined' ORDER BY reviewed_at DESC, id DESC LIMIT 1", (only[0],)).fetchone()
    assert newest is not None and newest[0] == "REJECT"


def test_an_invalid_answer_or_a_timeout_falls_back_to_the_rules(db: psycopg.Connection[Any], world: World) -> None:
    conn = Savepoints(db)
    broken = FakeProvider(lambda r: {"decision": "MAYBE"}, name="anthropic")
    cycle(conn, provider=broken, only=[world.fixtures["F1"]])
    llm = db.execute("SELECT status, decision FROM ai.pick_reviews WHERE engine = 'llm' AND fixture_id = %s",
                     (world.fixtures["F1"],)).fetchone()
    combined = db.execute("SELECT status, decision FROM ai.pick_reviews WHERE engine = 'combined' AND fixture_id = %s",
                          (world.fixtures["F1"],)).fetchone()
    rules = db.execute("SELECT decision FROM ai.pick_reviews WHERE engine = 'rules' AND fixture_id = %s",
                       (world.fixtures["F1"],)).fetchone()
    assert llm == ("invalid_output", "ABSTAIN") and combined is not None and rules is not None
    assert combined == ("fallback", rules[0])

    slow = fake(fail="timeout")
    cycle(conn, provider=slow, only=[world.fixtures["F3"]])
    assert len(slow.requests) == 1, "the provider timed out on the brief: nothing more is asked of it this cycle"
    assert db.execute("SELECT count(*) FROM ai.pick_reviews WHERE engine = 'llm' AND fixture_id = %s",
                      (world.fixtures["F3"],)).fetchone() == (0,)
    assert ("timeout",) in db.execute("SELECT status FROM ai.usage").fetchall()
    assert db.execute("SELECT engine, status FROM ai.match_briefs WHERE fixture_id = %s ORDER BY id DESC LIMIT 1",
                      (world.fixtures["F3"],)).fetchone() == ("rules", "failed"), "the rules wrote the brief"
    assert count(db, "SELECT count(*) FROM ai.fixture_passes WHERE fixture_id = %s", world.fixtures["F3"]) == 0, \
        "a pass the provider failed is not recorded"
    # a timeout is tried again at the next cycle (an answer would have been reused)
    cycle(conn, at=AT + timedelta(minutes=30), provider=slow, only=[world.fixtures["F3"]])
    assert len(slow.requests) == 2


def test_an_exhausted_budget_calls_no_model_and_the_rules_carry_on(db: psycopg.Connection[Any], world: World) -> None:
    conn = Savepoints(db)
    db.execute("INSERT INTO ai.usage (at, purpose, tier, provider, model, cost_usd, status) VALUES "
               "(%s, 'other', 'analysis', 'anthropic', 'm', 5, 'ok')", (AT - timedelta(minutes=5),))
    model = fake()
    report = cycle(conn, provider=model, only=[world.fixtures["F1"]])
    assert model.requests == [] and report.status == "ok"
    assert db.execute("SELECT count(*) FROM ai.pick_reviews WHERE engine = 'llm' AND fixture_id = %s",
                      (world.fixtures["F1"],)).fetchone() == (0,), "an exhausted day does not even ask"
    assert db.execute("SELECT engine, status FROM ai.match_briefs WHERE fixture_id = %s",
                      (world.fixtures["F1"],)).fetchone() == ("rules", "over_budget")
    assert db.execute("SELECT decision FROM ai.pick_reviews WHERE engine = 'combined' AND fixture_id = %s",
                      (world.fixtures["F1"],)).fetchone() is not None, "the rules carry on"
    assert db.execute("SELECT budget_state FROM ai.cycles ORDER BY id DESC LIMIT 1").fetchone() == ("EXHAUSTED",)


def test_mode_off_does_nothing(db: psycopg.Connection[Any], world: World) -> None:
    conn: Any = Savepoints(db)
    report = run_analysis_cycle(conn, at=AT, settings=AiSettings(mode="off"))
    assert report.counts["skipped_mode_off"] == 1 and count(db, "SELECT count(*) FROM ai.cycles") == 0


# ── the picks of the day: recorded in shadow, applied only when enforced ─────

def _reject(db: psycopg.Connection[Any], fixture: int) -> None:
    db.execute(
        "INSERT INTO ai.pick_reviews (reviewed_at, fixture_id, market_key, selection, line, engine, engine_version, "
        "input_hash, decision, confidence, output, mode, status) VALUES (%s, %s, '1X2', 'Home', 0, 'combined', "
        "'rules-review-v1+review-v1', 'h', 'REJECT', 0.8, %s, 'shadow', 'ok')",
        (AT - timedelta(minutes=10), fixture, Jsonb({"reason": "baja del portero", "decision": "REJECT"})))


def test_in_shadow_the_review_is_recorded_with_the_pick_and_changes_nothing(db: psycopg.Connection[Any],
                                                                            world: World,
                                                                            monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FBI_AI_MODE", "shadow")
    world.review_all(at=AT - timedelta(minutes=20))
    _reject(db, world.fixtures["F1"])
    build_daily_sets(db, at=AT)
    rows = db.execute("SELECT i.fixture_id, i.inputs->'ai' FROM picks.daily_set_items i JOIN picks.daily_sets s "
                      "ON s.id = i.set_id WHERE s.source = 'qualified' AND s.day = %s", (product_day(AT),)).fetchall()
    ai = {r[0]: r[1] for r in rows}
    assert world.fixtures["F1"] in ai, "shadow: a rejected selection is still chosen"
    assert ai[world.fixtures["F1"]]["decision"] == "REJECT" and ai[world.fixtures["F1"]]["enforced"] is False


def test_enforce_without_a_passed_gate_behaves_as_shadow_and_with_it_keeps_rejections_out(
        db: psycopg.Connection[Any], world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FBI_AI_MODE", "enforce")
    world.review_all(at=AT - timedelta(minutes=20))
    _reject(db, world.fixtures["F1"])
    savepoint = db.execute("SAVEPOINT before_sets")
    assert savepoint is not None
    build_daily_sets(db, at=AT)
    chosen = {r[0] for r in db.execute("SELECT i.fixture_id FROM picks.daily_set_items i JOIN picks.daily_sets s ON "
                                       "s.id = i.set_id WHERE s.source = 'qualified'")}
    assert world.fixtures["F1"] in chosen, "no passed gate: enforcement stays off"
    db.execute("ROLLBACK TO SAVEPOINT before_sets")
    db.execute("INSERT INTO ai.shadow_reports (created_at, window_from, window_to, engine, arms, gate, version) "
               "VALUES (%s, %s, %s, 'combined', '{}', %s, 'ai-gate-v1')",
               (AT - timedelta(hours=1), (AT - timedelta(days=60)).date(), AT.date(), Jsonb({"verdict": "pass"})))
    build_daily_sets(db, at=AT)
    rows = db.execute("SELECT i.fixture_id, i.inputs->'ai'->>'enforced' FROM picks.daily_set_items i JOIN "
                      "picks.daily_sets s ON s.id = i.set_id WHERE s.source = 'qualified'").fetchall()
    assert world.fixtures["F1"] not in {r[0] for r in rows} and rows and {r[1] for r in rows} == {"true"}


# ── learning and the owner's decisions ───────────────────────────────────────

def test_the_learning_cycle_writes_memory_and_reports_an_insufficient_gate(db: psycopg.Connection[Any],
                                                                            world: World) -> None:
    conn: Any = Savepoints(db)
    cycle(conn)
    world.result("F1", 2, 0)
    world.result("F3", 0, 1)
    report = run_learning_cycle(conn, at=AT + timedelta(hours=12), settings=SHADOW)
    assert report.status in ("ok", "partial"), report.errors
    assert report.counts["postmortems"] >= 2
    kinds = {r[0] for r in db.execute("SELECT DISTINCT kind FROM ai.memory_events")}
    assert {"match_result", "pick_result"} <= kinds
    gate = db.execute("SELECT gate->>'verdict' FROM ai.shadow_reports WHERE engine = 'combined' ORDER BY id DESC "
                      "LIMIT 1").fetchone()
    assert gate == ("insufficient",), "two matches prove nothing"
    assert count(db, "SELECT count(*) FROM analytics.research_hypotheses WHERE proposed_by = 'system' AND "
                     "dedup_key LIKE 'pattern:%%'") == 0, "no pattern on two results"


def test_the_owner_decides_investigates_approves_and_only_a_passed_gate_can_be_promoted(
        db: psycopg.Connection[Any], seed: Seed) -> None:
    owner = db.execute("INSERT INTO auth.users (email, display_name, password_hash) VALUES "
                       "('ai-owner@test.local', 'Owner', '$argon2id$x') RETURNING id").fetchone()
    assert owner is not None
    hid = evolution.propose(db, title="Probar exigir dos casas más", hypothesis="h", rationale="r", evidence={},
                            proposed_by="ai", at=AT, target="decision_rules")
    assert hid is not None
    assert evolution.decide(db, hid, decision="investigate", user_id=owner[0], note=None, at=AT) == "INVESTIGATING"
    assert evolution.decide(db, hid, decision="approve_experiment", user_id=owner[0], note="ok", at=AT) == "ACCEPTED"
    with pytest.raises(evolution.DecisionError):
        evolution.promote(db, hid, user_id=owner[0], at=AT)
    evolution.advance(db, hid, stage="RUNNING", at=AT)
    evolution.advance(db, hid, stage="DONE", at=AT, outcome={"gate_passed": False})
    with pytest.raises(evolution.DecisionError, match="gate passed: False"):
        evolution.promote(db, hid, user_id=owner[0], at=AT)
    hid2 = evolution.propose(db, title="Otra hipótesis distinta", hypothesis="h", rationale="r", evidence={},
                             proposed_by="owner", at=AT)
    assert hid2 is not None
    evolution.decide(db, hid2, decision="approve_experiment", user_id=owner[0], note=None, at=AT)
    evolution.advance(db, hid2, stage="SHADOW", at=AT)
    evolution.advance(db, hid2, stage="DONE", at=AT, outcome={"gate_passed": True})
    assert evolution.promote(db, hid2, user_id=owner[0], at=AT, note="tras el gate") == "PROMOTED"
    history = db.execute("SELECT stage_history FROM analytics.research_hypotheses WHERE id = %s", (hid2,)).fetchone()
    assert history is not None and [h["to"] for h in history[0]] == ["ACCEPTED", "SHADOW", "DONE", "PROMOTED"]


def test_a_model_may_propose_but_a_hypothesis_without_memory_references_is_refused(db: psycopg.Connection[Any],
                                                                                    world: World) -> None:
    from fbi.ai.patterns import run_patterns

    db.execute("INSERT INTO ai.memory_events (created_at, kind, entity_type, entity_id, evidence, version, dedup_key) "
               "VALUES (%s, 'pick_result', 'pick', '1', '{}', 'pm-v1', 'k1') RETURNING id", (AT,))
    mem = db.execute("SELECT id FROM ai.memory_events WHERE dedup_key = 'k1'").fetchone()
    assert mem is not None

    def answer(r: JsonRequest) -> dict[str, Any]:
        return {"hypotheses": [
            {"title": "Ligas con poca liquidez", "hypothesis": "Exigir más casas", "rationale": "Pocas casas fallan",
             "target": "decision_rules",
             "memory_refs": [mem[0]]},
            {"title": "Inventada sin memoria", "hypothesis": "Cambiar el modelo", "rationale": "Porque sí, sin datos",
             "target": "models",
             "memory_refs": [999999]}]}
    report = run_patterns(db, at=AT + timedelta(minutes=1), settings=SHADOW, use_llm=True,
                          ledger=UsageLedger(shared(db)), provider=(FakeProvider(answer, name="anthropic"), "m"))
    assert len(report.ai_proposed) == 1 and report.ai_rejected == ["Inventada sin memoria"]
    row = db.execute("SELECT status, proposed_by, target FROM analytics.research_hypotheses WHERE id = %s",
                     (report.ai_proposed[0],)).fetchone()
    assert row == ("PROPOSED", "ai", "decision_rules"), "a proposal, never a change"


def test_the_correlation_estimate_and_the_parlay_rule_version(db: psycopg.Connection[Any], world: World) -> None:
    from fbi.parlays import correlation
    from fbi.parlays.persist import RULE_VERSION, build_parlays

    est = correlation.estimate(db, since=AT - timedelta(days=30), until=AT)
    assert {e.market for e in est} == set(correlation.MARKETS)
    assert all(e.n_groups < correlation.MIN_GROUPS for e in est) and not any(e.significant_negative for e in est)
    world.review_all()
    build_parlays(db, at=AT)
    versions = {r[0] for r in db.execute("SELECT rule_version FROM picks.parlays")}
    assert versions <= {RULE_VERSION} and RULE_VERSION == "parlay-v5"
    legs = db.execute("SELECT l.parlay_id, count(*) FROM picks.parlay_legs l JOIN core.fixtures f ON f.id = l.fixture_id "
                      "GROUP BY l.parlay_id, f.competition_season_id HAVING count(*) > 2").fetchall()
    assert legs == [], "never more than two legs of one competition"


def test_cost_per_purpose_is_measured(db: psycopg.Connection[Any], world: World) -> None:
    from fbi.ai.costs import summary

    conn = Savepoints(db)
    cycle(conn, provider=fake(), only=[world.fixtures["F1"]])
    s = summary(db, at=AT + timedelta(minutes=1), settings=SHADOW)
    today = s["periods"]["today"]
    assert today["requests"] == 2 and today["llm_reviews"] == 1 and today["briefs"] == 1 and today["cost_usd"] > 0
    review = next(x for x in today["by_purpose"] if x["key"] == "pick_review")
    brief = next(x for x in today["by_purpose"] if x["key"] == "match_brief")
    assert today["cost_per_review"] == pytest.approx(review["cost_usd"], rel=1e-6)
    assert today["cost_per_analysis"] == pytest.approx(brief["cost_usd"], rel=1e-6)
    assert today["cost_per_match"] == pytest.approx(today["cost_usd"], rel=1e-6), "one match analysed"
    assert {x["key"] for x in today["by_level"]} <= {"L1", "L2", "L3", "web"}
    assert Decimal(s["budget"]["spent_today_usd"]) > 0 and s["budget"]["state"] == "NORMAL"
    assert s["projection"]["monthly_budget_usd"] == 20.0 and s["thresholds"] == [50, 70, 85, 95, 100]
