"""The trace of a selection end to end (trace-v1) and the single registry of promotions (registry-v1), on the real schema.

THE WORLD: the seed's match (1001, kick-off 2026-09-15 19:00 UTC), finished, of a competition whose data class is MODEL_READY.

* 1X2 Home - complete: a prediction, its candidate and its pick; the Shin consensus the decisions priced against and the snapshot the pick took
  its odds from; two checkpoints of the decision layer citing the combined review and one item of evidence; a shadow review (ma-v1); an
  agent run; the pick of the day; the pick settled and both decisions with their outcome.
* 1X2 Away - incomplete: its decision cites a review that does not exist and a price no consensus row holds, and the pick of the finished match
  has no result. The trace must say exactly those three spans are missing, and invent none of them. (It also cites an evidence id that does not
  exist: the trace lists it with who cites it, ``not_read`` - the evidence table is not the trace's to read, ``fbi.observability.trace``.)

The transaction is rolled back afterwards; nothing here is committed.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb

from fbi.core.decision_versions import DECISION_CORE, OUTCOME_CORE
from fbi.governance import promotions as registry
from fbi.observability import trace as tr
from fbi.research import promotions as code_ledger

from .agent_tables import run_values
from .conftest import Seed

KO = datetime(2026, 9, 15, 19, tzinfo=UTC)
T24 = KO - timedelta(hours=24)  # 14 Sep, 14:00 in Bogotá
T6 = KO - timedelta(hours=6)  # 15 Sep, 08:00 in Bogotá
DAY = date(2026, 9, 15)
PRICE_AT = T6 - timedelta(minutes=20)
SNAP_AT = T24 - timedelta(hours=1)
HASH = "d" * 64


def put(db: psycopg.Connection[Any], table: str, values: dict[str, Any], *, returning: bool = True) -> int | None:
    columns = ", ".join(values)
    marks = ", ".join(["%s"] * len(values))
    cur = db.execute(f"INSERT INTO {table} ({columns}) VALUES ({marks})" + (" RETURNING id" if returning else ""), list(values.values()))
    if not returning:
        return None
    row = cur.fetchone()
    assert row is not None
    return int(row[0])


def put_id(db: psycopg.Connection[Any], table: str, values: dict[str, Any]) -> int:
    out = put(db, table, values)
    assert out is not None
    return out


class World:
    def __init__(self, db: psycopg.Connection[Any], seed: Seed) -> None:
        self.db, self.seed = db, seed
        db.execute("UPDATE core.fixtures SET status_short = 'FT', status_group = 'finished' WHERE id = %s", (seed.fixture_id,))
        put(db, "analytics.competition_data_scores", {
            "competition_season_id": seed.season_id, "computed_at": KO - timedelta(days=3), "rule_version": "data-score-v1", "class": "MODEL_READY",
            "score": Decimal("0.91"), "finished": 40, "approved": 40, "quarantined": 0, "components": Jsonb({})}, returning=False)

    def pick(self, selection: str, *, odds: str = "2.10") -> tuple[int, int]:
        db, s = self.db, self.seed
        cutoff = SNAP_AT - timedelta(hours=2)
        prediction = put(db, "models.predictions", {
            "fixture_id": s.fixture_id, "model_version_id": s.model_version_id, "market_key": "1X2", "selection": selection, "line": 0,
            "p_raw": Decimal("0.52"), "p_calibrated": Decimal("0.52"), "p_lo": Decimal("0.47"), "p_hi": Decimal("0.57"), "feature_set_hash": "fh",
            "data_cutoff_ts": cutoff})
        candidate = put(db, "picks.pick_candidates", {
            "run_id": s.run_id, "fixture_id": s.fixture_id, "prediction_id": prediction, "market_key": "1X2", "selection": selection, "line": 0,
            "bookmaker_id": s.bookmaker_id, "market_odds": Decimal(odds), "p_calibrated": Decimal("0.52"), "p_market_fair": Decimal("0.47"),
            "decision": "selected"})
        pick = put(db, "picks.picks", {
            "candidate_id": candidate, "fixture_id": s.fixture_id, "market_key": "1X2", "selection": selection, "line": 0,
            "model_version_id": s.model_version_id, "feature_set_hash": "fh", "data_cutoff_ts": cutoff, "decision_rule_version": "shadow-rule-v2",
            "code_version": "abc", "bookmaker_id": s.bookmaker_id, "market_odds": Decimal(odds), "odds_captured_at": SNAP_AT,
            "p_model": Decimal("0.52"), "p_calibrated": Decimal("0.52"), "p_market_fair": Decimal("0.47"), "fair_odds": Decimal("1.92"),
            "edge": Decimal("0.05"), "price_edge": Decimal("0.01"), "ev": Decimal("0.09"), "kelly_fraction": Decimal("0.01"), "stake_units": 1,
            "selection_reason": Jsonb({}), "created_at": SNAP_AT, "prediction_id": prediction, "odds_payload_hash": s.payload_hash,
            "consensus_method": "shin", "consensus_as_of": SNAP_AT})
        assert prediction is not None and pick is not None
        return pick, prediction

    def consensus(self, selection: str, as_of: datetime) -> None:
        put(self.db, "market.market_consensus", {
            "fixture_id": self.seed.fixture_id, "market_key": "1X2", "selection": selection, "line": 0, "as_of": as_of, "devig_method": "shin",
            "p_fair": Decimal("0.47"), "n_bookmakers": 6, "overround": Decimal("0.05"), "best_odds": Decimal("2.10"),
            "best_bookmaker_id": self.seed.bookmaker_id}, returning=False)

    def snapshot(self, selection: str) -> None:
        put(self.db, "market.odds_snapshots", {
            "fixture_id": self.seed.fixture_id, "bookmaker_id": self.seed.bookmaker_id, "market_key": "1X2", "selection": selection, "line": 0,
            "odds_decimal": Decimal("2.10"), "captured_at": SNAP_AT, "minutes_to_ko": int((KO - SNAP_AT).total_seconds() // 60),
            "source": "prematch", "payload_hash": self.seed.payload_hash}, returning=False)

    def evidence(self) -> int:
        e = put(self.db, "ai.evidence", {
            "fixture_id": self.seed.fixture_id, "kind": "lineup", "claim": "The home side confirmed its usual eleven.", "origin": "provider",
            "source_name": "provider", "source_tier": "provider", "retrieved_at": T24 - timedelta(hours=2), "story_key": "trace-story-1",
            "content_hash": HASH, "confidence": Decimal("0.9"), "relevance": Decimal("0.8"), "status": "CONFIRMED", "status_reason": "provider",
            "status_changed_at": T24 - timedelta(hours=2)})
        assert e is not None
        return e

    def review(self, selection: str, engine: str, *, evidence: list[int], pick: int | None) -> int:
        r = put(self.db, "ai.pick_reviews", {
            "reviewed_at": T24 - timedelta(minutes=30), "fixture_id": self.seed.fixture_id, "pick_id": pick, "market_key": "1X2",
            "selection": selection, "line": 0, "engine": engine, "engine_version": f"{engine}-review", "input_hash": HASH,
            "decision": "APPROVE", "confidence": Decimal("0.7"), "output": Jsonb({}), "mode": "shadow", "status": "ok",
            "evidence_ids": evidence, "cost_usd": Decimal("0.004")})
        assert r is not None
        return r

    def decision(self, selection: str, at: datetime, checkpoint: str, *, pick: int, review: int | None, evidence: list[int],
                 price_at: datetime | None) -> int:
        d = put(self.db, "intel.decisions", {
            "decision_version": DECISION_CORE, "known_at": at, "checkpoint": checkpoint, "fixture_id": self.seed.fixture_id, "kickoff_at": KO,
            "market_key": "1X2", "selection": selection, "line": 0, "pick_id": pick, "model_name": "dixon_coles",
            "model_version_id": self.seed.model_version_id, "odds": Decimal("2.10"), "bookmaker_id": self.seed.bookmaker_id, "price_at": price_at,
            "n_bookmakers": 6, "p_model": Decimal("0.52"), "p_market": Decimal("0.47"),
            "filters": Jsonb([{"n": 1, "key": "data", "ok": True, "why": "datos MODEL_READY"}, {"n": 10, "key": "final", "ok": False,
                                                                                               "why": "edge no validado", "effect": "INVESTIGACION"}]),
            "state": "INVESTIGACION", "reasons": ["edge no validado"], "context_status": "FULL", "review_id": review, "evidence_ids": evidence,
            "input_hash": f"{selection}{checkpoint}".ljust(32, "0")[:32], "code_version": "abc"})
        assert d is not None
        return d

    def settle(self, pick: int, decisions: list[int]) -> None:
        put(self.db, "picks.pick_results", {"pick_id": pick, "result_status": "win", "profit_units": Decimal("1.1"), "settled_at": KO + timedelta(hours=2),
                                            "settlement_basis": "regulation_90", "rule_version": "settle-v3"}, returning=False)
        for d in decisions:
            put(self.db, "intel.decision_outcomes", {"decision_id": d, "settled_at": KO + timedelta(hours=2), "result_status": "win",
                                                     "profit_flat": Decimal("1.1"), "profit_staked": Decimal(0), "version": OUTCOME_CORE,
                                                     "computed_at": KO + timedelta(hours=3), "clv": Decimal("0.02")}, returning=False)

    def publish(self, pick: int) -> None:
        set_id = put(self.db, "picks.daily_sets", {"day": DAY, "timezone": "America/Bogota", "source": "qualified", "rule_version": "daily-set-v7",
                                                   "status": "SETTLED", "created_at": T6, "updated_at": KO + timedelta(hours=2)})
        put(self.db, "picks.daily_set_items", {
            "set_id": set_id, "rank": 1, "pick_id": pick, "fixture_id": self.seed.fixture_id, "market_key": "1X2", "selection": "Home", "line": 0,
            "stage": "T-6h", "selected_at": T6, "odds": Decimal("2.10"), "bookmaker_id": self.seed.bookmaker_id, "price_at": PRICE_AT,
            "p_model": Decimal("0.52"), "p_low": Decimal("0.47"), "p_push": 0, "p_market": Decimal("0.47"), "ev": Decimal("0.09"),
            "model_version_id": self.seed.model_version_id, "inputs": Jsonb({}), "status": "WIN", "profit_units": Decimal("1.1"),
            "settled_at": KO + timedelta(hours=2)}, returning=False)


@pytest.fixture()
def world(db: psycopg.Connection[Any], seed: Seed) -> dict[str, Any]:
    w = World(db, seed)
    home_pick, home_prediction = w.pick("Home")
    w.consensus("Home", PRICE_AT)
    w.consensus("Home", SNAP_AT)
    w.snapshot("Home")
    evidence = w.evidence()
    combined = w.review("Home", "combined", evidence=[evidence], pick=home_pick)
    shadow = w.review("Home", "ma-v1", evidence=[], pick=None)
    d1 = w.decision("Home", T24, "T-24h", pick=home_pick, review=combined, evidence=[evidence], price_at=PRICE_AT - timedelta(hours=18))
    w.consensus("Home", PRICE_AT - timedelta(hours=18))
    d2 = w.decision("Home", T6, "T-6h", pick=home_pick, review=combined, evidence=[evidence], price_at=PRICE_AT)
    w.settle(home_pick, [d1, d2])
    w.publish(home_pick)
    run = put(db, "ai.agent_runs", run_values(seed, 7, started_at=T24 - timedelta(hours=1), finished_at=T24 - timedelta(minutes=59),
                                              known_at=T24 - timedelta(hours=2), latency_ms=1800))

    away_pick, _ = w.pick("Away", odds="3.40")
    w.snapshot("Away")
    w.consensus("Away", SNAP_AT)
    away = w.decision("Away", T6, "T-6h", pick=away_pick, review=987654321, evidence=[987654321], price_at=PRICE_AT)
    return {"home_pick": home_pick, "home_prediction": home_prediction, "evidence": evidence, "combined": combined, "shadow": shadow,
            "home_decisions": [d1, d2], "run": run, "away_pick": away_pick, "away_decision": away}


def kinds(t: tr.Trace, status: str) -> set[str]:
    return {s.kind for s in t.spans if s.status == status}


def test_a_complete_trace_follows_the_pick_from_the_data_to_its_outcome(db: psycopg.Connection[Any], seed: Seed, world: dict[str, Any]) -> None:
    t = tr.trace_of(db, pick_id=world["home_pick"])
    c = tr.completeness(t)
    assert c.complete, c
    assert set(c.present) == set(tr.MANDATORY) and c.not_applicable == ()
    assert t.trace_id == tr.selection_trace_id(seed.fixture_id, "1X2", "Home", 0) and t.match_trace_id == tr.match_trace_id(seed.fixture_id)

    decisions = t.of_kind("decision")
    assert [s.row_ids for s in decisions] == [(str(world["home_decisions"][0]),), (str(world["home_decisions"][1]),)]
    assert decisions[0].versions["decision"] == DECISION_CORE and decisions[0].versions["code"] == "abc"
    assert [f["key"] for f in decisions[1].payload["filters"]] == ["data", "final"]

    reviews = {s.row_ids[0]: s for s in t.of_kind("review")}
    assert reviews[str(world["combined"])].payload["cited_by"] and reviews[str(world["combined"])].payload["shadow"] is False
    assert reviews[str(world["shadow"])].payload["shadow"] is True and "cited_by" not in reviews[str(world["shadow"])].payload

    prices = t.of_kind("price")
    assert {s.source for s in prices} == {"market.market_consensus", "market.odds_snapshots"} and all(s.status == tr.PRESENT for s in prices)
    assert len([s for s in prices if s.source == "market.market_consensus"]) == 3, "two decision prices and the pick's consensus"

    (run,) = t.of_kind("agent_run")
    assert run.versions["prompt"] == "council-prompt-v1" and run.versions["model"] == "claude-sonnet-5-5"
    assert run.payload["input_tokens"] == 1200 and run.payload["cost_usd"] == pytest.approx(0.0123) and run.payload["latency_ms"] == 1800

    assert t.of_kind("forecast")[0].row_ids == (str(world["home_prediction"]),)
    assert t.of_kind("data_quality")[0].payload["class"] == "MODEL_READY"
    assert {s.source for s in t.of_kind("publication")} == {"picks.daily_set_items"}
    assert [s.row_ids for s in t.of_kind("outcome")] == [(str(d),) for d in world["home_decisions"]]
    assert kinds(t, tr.NOT_READ) == {"cycle", "postmortem", "attribution", "evidence"}
    (evidence,) = t.of_kind("evidence")
    assert evidence.row_ids == (str(world["evidence"]),)
    assert evidence.payload["cited_by"] == sorted([f"decision {d}" for d in world["home_decisions"]] + [f"review {world['combined']}"])
    assert [s.kind for s in t.spans] == sorted((s.kind for s in t.spans), key=tr.STAGES.index), "pipeline order"


def test_every_anchor_of_one_selection_is_the_same_trace(db: psycopg.Connection[Any], seed: Seed, world: dict[str, Any]) -> None:
    by_pick = tr.trace_of(db, pick_id=world["home_pick"])
    by_decision = tr.trace_of(db, decision_id=world["home_decisions"][0])
    by_key = tr.trace_of(db, fixture_id=seed.fixture_id, market_key="1X2", selection="Home", line="0.00")
    assert by_pick.trace_id == by_decision.trace_id == by_key.trace_id
    assert [s.row_ids for s in by_pick.spans] == [s.row_ids for s in by_decision.spans] == [s.row_ids for s in by_key.spans]


def test_a_trace_with_gaps_says_which_and_invents_none(db: psycopg.Connection[Any], seed: Seed, world: dict[str, Any]) -> None:
    t = tr.trace_of(db, pick_id=world["away_pick"])
    c = tr.completeness(t)
    assert not c.complete
    assert set(c.missing) == {"price", "review", "settlement"}
    assert c.not_applicable == ("outcome",), "no final result: no outcome is due"
    missing_review = [s for s in t.of_kind("review") if s.status == tr.MISSING]
    assert [s.row_ids for s in missing_review] == [("987654321",)] and "not found" in missing_review[0].note
    assert [(s.row_ids, s.status) for s in t.of_kind("evidence")] == [(("987654321",), tr.NOT_READ)], "listed, never said to resolve"
    missing_price = [s for s in t.of_kind("price") if s.status == tr.MISSING]
    assert [s.source for s in missing_price] == ["market.market_consensus"] and missing_price[0].at == PRICE_AT
    assert not [s for s in t.of_kind("review") if s.status == tr.PRESENT and s.row_ids == ("987654321",)]


def test_an_anchor_that_does_not_exist_is_missing_not_guessed(db: psycopg.Connection[Any]) -> None:
    t = tr.trace_of(db, pick_id=10**12)
    assert t.trace_id is None and not tr.completeness(t).complete
    assert t.of_kind("pick")[0].status == tr.MISSING and t.of_kind("pick")[0].note == "no such pick"
    assert tr.trace_of(db, decision_id=10**12).of_kind("decision")[0].status == tr.MISSING


def test_the_trace_of_the_match(db: psycopg.Connection[Any], seed: Seed, world: dict[str, Any]) -> None:
    t = tr.trace_of(db, fixture_id=seed.fixture_id)
    assert t.scope == "match" and t.trace_id == tr.match_trace_id(seed.fixture_id) and tr.completeness(t).complete
    assert len(t.of_kind("decision")) == 3
    assert {s.payload["selection_trace_id"] for s in t.of_kind("decision")} == {
        str(tr.selection_trace_id(seed.fixture_id, "1X2", sel, 0)) for sel in ("Home", "Away")}


def test_the_coverage_of_a_day(db: psycopg.Connection[Any], world: dict[str, Any]) -> None:
    cov = tr.coverage(db, DAY)
    assert (cov.selections.total, cov.selections.complete) == (2, 1) and cov.selections.share == pytest.approx(0.5)
    assert dict(cov.selections.missing) == {"price": 1, "review": 1, "settlement": 1}
    assert (cov.published.total, cov.published.complete) == (1, 1)
    before = tr.coverage(db, DAY - timedelta(days=1))
    assert (before.selections.total, before.selections.complete) == (1, 1), "only Home was decided on the 14th (T-24h)"
    assert tr.coverage(db, date(2026, 1, 1)).selections.share is None


def test_reading_a_trace_writes_nothing(db: psycopg.Connection[Any], world: dict[str, Any]) -> None:
    count = "SELECT (SELECT count(*) FROM picks.picks) + (SELECT count(*) FROM picks.pick_results) + (SELECT count(*) FROM market.market_consensus)"
    before = db.execute(count).fetchone()
    tr.trace_of(db, pick_id=world["home_pick"])
    tr.coverage(db, DAY)
    assert db.execute(count).fetchone() == before


# ── the registry ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

T0 = datetime(2026, 10, 1, 12, tzinfo=UTC)


@pytest.fixture()
def ledgers(db: psycopg.Connection[Any]) -> dict[str, Any]:
    def promo(at: datetime, entity: str, to_role: str, **kw: Any) -> int:
        values = {"at": at, "entity": entity, "to_role": to_role, "gate_version": "calib-gate-v1", "criteria": Jsonb({}),
                  "reason": "a reason the owner can read later", "decided_by": "system"} | kw
        out = put(db, "intel.promotions", values)
        assert out is not None
        return out

    ids = {
        "champion": promo(T0, "calibrator", "CHAMPION", market_key="1X2", model_name="dixon_coles", entity_id=10),
        "challenger": promo(T0 + timedelta(days=1), "calibrator", "CHALLENGER", market_key="1X2", model_name="dixon_coles", entity_id=11),
        "retired": promo(T0 + timedelta(days=5), "calibrator", "RETIRED", market_key="1X2", model_name="dixon_coles", entity_id=10,
                         from_role="CHAMPION"),
        "edge": promo(T0, "market_edge", "NOT_VALIDATED", market_key="1X2", model_name="dixon_coles", gate_version="edge-gate-v1"),
        "model": promo(T0, "model", "CHAMPION", gate_version=code_ledger.GATE_VERSION,
                       criteria=Jsonb({"model_code": code_ledger.LEDGER[0].fingerprint, "baseline": True})),
        "agent": promo(T0 + timedelta(days=2), "agent", "CHAMPION", market_key="1X2", model_name="match@match-v1", gate_version="ma-gate-v1",
                       decided_by="owner", criteria=Jsonb({"report_hash": HASH})),
    }
    session = put(db, "analytics.backtest_sessions", {
        "name": "trace test", "protocol": "holdout", "competition_ids": [1], "test_season": 2025, "test_from": date(2025, 8, 1),
        "test_to": date(2026, 5, 1), "primary_baseline": "market", "n_targets": 1, "dataset_hash": "x", "code_version": "abc",
        "status": "completed", "finished_at": T0})
    ids["spec"] = put_id(db, "analytics.promoted_forecast_spec", {
        "session_id": session, "promoted_at": T0 + timedelta(days=3), "promoted_by": "owner", "reason": "the goal spec, promoted",
        "spec": Jsonb({"version": "spec-v1", "competition_ids": [39], "history_days": 900, "goal": {}})})
    ids["neutral"] = put_id(db, "analytics.neutral_rule_promotion", {
        "promoted_at": T0 + timedelta(days=4), "promoted_by": "owner", "action": "retire", "reason": "switch the rule off"})
    ids["gate"] = put_id(db, "ai.feature_gates", {"gate": "batch", "at": T0, "passed": True, "evidence": Jsonb({"n": 1}), "evidence_hash": HASH,
                                               "decided_by": "script"})
    ids["switches"] = put_id(db, "ai.feature_gates", {"gate": "switches", "at": T0, "passed": True, "evidence": Jsonb({}), "evidence_hash": HASH,
                                                   "decided_by": "script"})
    return ids


def test_the_registry_puts_every_ledger_in_one_shape(db: psycopg.Connection[Any], ledgers: dict[str, Any]) -> None:
    rows = registry.all_promotions(db)
    sources = {(p.source_table, p.source_id) for p in rows}
    for name in ("champion", "challenger", "retired", "edge", "model", "agent"):
        assert ("intel.promotions", str(ledgers[name])) in sources, name
    assert ("analytics.promoted_forecast_spec", str(ledgers["spec"])) in sources
    assert ("analytics.neutral_rule_promotion", str(ledgers["neutral"])) in sources
    assert ("ai.feature_gates", str(ledgers["gate"])) in sources and ("ai.feature_gates", str(ledgers["switches"])) not in sources
    assert (registry.CODE_LEDGER_SOURCE, "0") in sources
    assert {p.entity_type for p in rows} >= {"calibrator", "market_edge", "model", "agent", "goal_spec", "neutral_rule", "ai_gate"}
    assert [p.at for p in rows] == sorted(p.at for p in rows)
    assert {p.entity_type for p in registry.all_promotions(db, entity_type="agent")} == {"agent"}


def test_current_and_history_as_of_a_moment(db: psycopg.Connection[Any], ledgers: dict[str, Any]) -> None:
    key = "1X2/dixon_coles"
    during = registry.current(db, "calibrator", key, at=T0 + timedelta(days=2))
    assert during is not None and during.version == "10" and during.in_force, "the challenger did not depose the champion"
    after = registry.current(db, "calibrator", key)
    assert after is not None and after.decision == "RETIRED" and after.in_force is False
    assert [p.source_id for p in registry.history(db, "calibrator", key)] == [str(ledgers[n]) for n in ("champion", "challenger", "retired")]
    assert registry.current(db, "calibrator", key, at=T0 - timedelta(seconds=1)) is None

    model = registry.current(db, "model", registry.MODEL_CODE_KEY)
    assert model is not None and model.source_table == "intel.promotions" and model.version == code_ledger.LEDGER[0].fingerprint
    agent = registry.current(db, "agent", "1X2")
    assert agent is not None and agent.version == "match@match-v1" and agent.decided_by == "owner"
    spec = registry.current(db, "goal_spec", registry.GOAL_SPEC_KEY)
    assert spec is not None and spec.version is not None and spec.version.startswith("spec-v1:")
    neutral = registry.current(db, "neutral_rule", registry.NEUTRAL_KEY)
    assert neutral is not None and neutral.decision == "RETIRED"
