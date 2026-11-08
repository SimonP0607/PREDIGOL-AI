"""A market family as a plug-in (``fbi.plugins``, ``family-plugin-v1``): the worked example (TEAM_TOTALS, from the sim-v1 joint) is
registered AT RUN TIME and flows through decision-v2, its replay and the portfolio's correlation provider with no change to any of them;
the registry checks an entry against every layer; and no family becomes ACTIVE without a CHAMPION calibrator and a validated edge."""

from __future__ import annotations

import ast
import dataclasses
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest

from fbi.core.version import MODEL_PACKAGES, model_code_fingerprint
from fbi.decision import engine, replay
from fbi.decision.families import (
    CAP_CODE,
    FAMILIES,
    GateStatus,
    MarketFamily,
    SettlementRule,
    gate_of,
)
from fbi.familydecisions import decide as fd
from fbi.intel import decision
from fbi.intel.calibration import CalibrationState, Calibrator
from fbi.market.rules import RULES_BY_KEY
from fbi.picks.count_settlement import settle_numbers
from fbi.picks.settlement import Status
from fbi.plugins import family as plug
from fbi.plugins import registry
from fbi.plugins._template import family as example
from fbi.portfolio import correlation
from fbi.portfolio.selection import Selection
from fbi.simulator import joint as jt
from fbi.simulator import markets as sim
from tests.unit.test_model_code_version import RUNNING_MODEL_CODE

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "fbi"
AT = datetime(2026, 11, 7, 15, 0, tzinfo=UTC)
FIXTURE = 4242
JOINT = jt.build(jt.split_full_time(1.7, 1.0), rho=-0.05, source="test")
OVER_15_HOME = sim.Selection("TT_HOME", "Over", 1.5)
P_HOME_OVER_15 = sim.probability(JOINT, OVER_15_HOME)


def fixture_fields() -> dict[str, Any]:
    return {"kickoff_at": AT + timedelta(hours=6), "status_short": "NS", "status_group": "scheduled", "home_team_id": 1, "away_team_id": 2,
            "competition_season_id": 10, "competition_id": 20, "competition_name": "Liga", "home_name": "A", "away_name": "B"}


def inputs(*, books: int = 5) -> example.Inputs:
    """One match, the books pricing the home side's over 1.5 at a price the model sees value in (and its under, fairly)."""
    m = example.Match(FIXTURE, fixture_fields(), JOINT, 77, AT - timedelta(hours=2))
    p = P_HOME_OVER_15
    priced = {(FIXTURE, "OU_HOME", Decimal("1.5"), "Over"): fd.Priced(p - 0.02, round(1.12 / p, 2), 3, books, 1.05, AT - timedelta(minutes=20)),
              (FIXTURE, "OU_HOME", Decimal("1.5"), "Under"): fd.Priced(1 - p + 0.02, round(0.9 / (1 - p), 2), 4, books, 1.05,
                                                                      AT - timedelta(minutes=20))}
    return example.Inputs({FIXTURE: m}, priced, {FIXTURE: AT - timedelta(minutes=15)})


def in_memory(found: example.Inputs) -> example.Source:
    def source(conn: Any, *, at: datetime, fixtures: Sequence[int] | None, horizon: timedelta) -> example.Inputs:
        assert conn is None, "the example reads nothing but what it is given here"
        return found
    return source


def world(*, champion: bool = False, edge: bool = False) -> decision.World:
    slots = {(m, example.MODEL): Calibrator(m, example.MODEL, "identity", {}, id=900 + i, role="CHAMPION")
             for i, m in enumerate(example.MARKET_KEYS)}
    cal = CalibrationState(champions=slots if champion else {}, best={}, wf={s: {"rule_clv": 0.01} for s in slots},
                           edge=dict.fromkeys(slots, edge))
    return decision.World(at=AT, cal=cal, quality={}, reviews={}, rules={}, evidence={}, passes={}, lineups={}, type_clv={}, previous={},
                          ai_mode="shadow")


def registered(found: example.Inputs | None = None) -> registry.Registry:
    reg = registry.Registry()
    reg.register(example.make_plugin(in_memory(found or inputs())))
    return reg


def team_totals(reg: registry.Registry) -> MarketFamily:
    return next(f for f in reg.decision_families() if f.name == example.NAME)


# -- one entry every layer reads -------------------------------------------------------------------------------------------------------

def test_the_example_is_shadow_never_active_and_not_installed() -> None:
    assert example.PLUGIN.status == plug.SHADOW and example.PLUGIN.activatable is False
    assert registry.INSTALLED == () and registry.installed().plugins() == ()
    with pytest.raises(plug.PromotionRefused):
        dataclasses.replace(example.PLUGIN, status=plug.ACTIVE)


def test_the_registry_reads_every_layer_of_the_entry() -> None:
    reg = registry.Registry()
    assert registry.check(example.PLUGIN) == []
    reg.register(example.PLUGIN)
    [d] = reg.describe()
    assert [(t["bet_id"], t["status"], t["extract"]) for t in d["taxonomy"]] == [(16, "CANDIDATE", True), (17, "CANDIDATE", True)]
    assert d["markets"] == ["OU_AWAY", "OU_HOME"] and d["status"] == "SHADOW"
    assert d["model"] == {"name": "sim-v1:dixon_coles", "version": "sim-v1", "distribution": True}
    assert d["calibrators"] == [["OU_AWAY", example.MODEL], ["OU_HOME", example.MODEL]]
    assert d["settlement"]["rule"] == "goals_ft@v1" and d["settlement"]["function"] == "fbi.picks.count_settlement:settle_numbers"
    assert d["edge_gate"] == "edge-gate-v1" and d["decision"] == {"version": example.DECISION_VERSION, "judged": True, "promoted": False}
    assert [f.name for f in reg.decision_families()] == [*(f.name for f in FAMILIES), "TEAM_TOTALS"], "today's families first, untouched"


def test_the_settlement_rule_grades_a_team_total() -> None:
    rule = RULES_BY_KEY[example.RULE]
    two_nil = {"goals_ft_home": 2, "goals_ft_away": 0}
    assert settle_numbers(rule, "over_under", "home", "Over", Decimal("1.5"), two_nil) is Status.WIN
    assert settle_numbers(rule, "over_under", "away", "Over", Decimal("0.5"), two_nil) is Status.LOSS
    assert settle_numbers(rule, "over_under", "home", "Over", Decimal("1.5"), {"goals_ft_home": None, "goals_ft_away": 0}) is None


def test_the_model_is_a_sum_over_the_sim_v1_joint() -> None:
    model = example.TeamTotalsModel(inputs().matches)
    assert isinstance(model, plug.DistributionProvider)
    win, push = model.price(FIXTURE, "OU_HOME", "Over", Decimal("1.5")) or (None, None)
    assert win == pytest.approx(P_HOME_OVER_15) and push == 0.0
    over, under = (model.price(FIXTURE, "OU_AWAY", s, Decimal("0.5")) or (0.0, 0.0) for s in ("Over", "Under"))
    assert over[0] + under[0] == pytest.approx(1.0)
    assert model.price(FIXTURE, "OU", "Over", Decimal("2.5")) is None, "only the family's markets are priced"
    assert len(model.forecasts()) == 2 * len(sim.TEAM_LINES) * 2


# -- through the core, registered at run time --------------------------------------------------------------------------------------------

def test_the_example_goes_through_decision_v2_and_is_held_at_abstain() -> None:
    fam = team_totals(registered())
    cands = fam.candidates(None, at=AT)  # type: ignore[arg-type]
    [c] = cands
    assert c.family is fam and c.key == (FIXTURE, "OU_HOME", "Over", Decimal("1.50")) and c.model_hint == example.MODEL
    assert c.models[example.MODEL]["p_model"] == pytest.approx(P_HOME_OVER_15)
    [bare] = engine.decide_all(world(), cands)
    assert bare.family == "TEAM_TOTALS" and bare.state == "ABSTAIN" and bare.verdict("calibration").ok is False, "no calibrator: abstains"
    [d] = engine.decide_all(world(champion=True, edge=True), cands)
    assert d.verdict("calibration").ok is True and d.prediction.calibrator_id == 901, "its own (market, model) slot"
    assert d.state == "ABSTAIN" and CAP_CODE in d.codes, "calibrated and validated, but SHADOW: never more than ABSTAIN"


def test_the_governed_view_overrides_what_the_author_wrote() -> None:
    sneaky = dataclasses.replace(example.TeamTotalsFamily(in_memory(inputs())),
                                 params=dataclasses.replace(example.PARAMS, promoted=True, decision_version="decision-v1"))
    entry = dataclasses.replace(example.make_plugin(in_memory(inputs())), adapter=sneaky)
    fam = entry.decision_family()
    assert fam.params.promoted is False and fam.params.decision_version == example.DECISION_VERSION
    [d] = engine.decide_all(world(champion=True, edge=True), fam.candidates(None, at=AT))  # type: ignore[arg-type]
    assert d.state == "ABSTAIN" and CAP_CODE in d.codes
    assert fam.gate(world(champion=True, edge=True), "OU_HOME", "another-model").champion is None, "only its own slot"


def test_the_example_flows_through_the_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    """A row as a shadow pass of the family would record it: the replay sorts it to the family, rebuilds its candidate through the
    registered adapter, decides it with the one engine and reports the family - none of the replay's code knows the family."""
    row = {"id": 1, "decision_version": example.DECISION_VERSION, "known_at": AT, "checkpoint": "early", "fixture_id": FIXTURE,
           "market_key": "OU_HOME", "selection": "Over", "line": Decimal("1.50"), "model_name": example.MODEL, "state": "INVESTIGACION",
           "reasons": ["not_calibrated"], "filters": [], "context_status": "AI_OFF"}
    asked: list[Sequence[str]] = []

    def read_rows(conn: Any, *, day: Any, versions: Sequence[str]) -> list[dict[str, Any]]:
        asked.append(versions)
        return [row]

    monkeypatch.setattr(replay, "read_rows", read_rows)
    monkeypatch.setattr(replay, "world_at", lambda conn, family, fixtures, *, at, rows: world())
    out = replay.replay_day(None, day=AT.date(), families=registered().decision_families())  # type: ignore[arg-type]
    assert example.DECISION_VERSION in asked[0]
    assert out["skipped"] == {"selection_copies": 0, "unclaimed": 0}
    tt = out["families"]["TEAM_TOTALS"]
    assert (tt["n"], tt["agree"], tt["unmatched"]) == (1, 1, 0) and tt["confusion"] == {"ABSTAIN": {"ABSTAIN": 1}}
    assert out["families"]["core"]["n"] == 0, "today's families are reported as before"


def test_the_example_is_the_portfolios_correlation_provider_for_its_markets() -> None:
    joint = registered().joint_provider(None, at=AT, fixtures=[FIXTURE])
    base: dict[str, Any] = {
        "fixture_id": FIXTURE, "kickoff_at": AT + timedelta(hours=6), "known_at": AT, "competition_id": 20, "provider_league_id": None,
        "home_team_id": 1, "away_team_id": 2, "odds": 2.0, "p_cal": 0.5, "p_push": 0.0, "p_low": None, "p_high": None, "p_market": 0.48,
        "n_bookmakers": 4, "price_at": AT, "score": 60.0, "premium": False, "parlay_eligible": False, "state_v1": "APROBADO",
        "state_v2": "RECOMMENDED", "reason": "approved", "label": None}
    tt = Selection(decision_id=1, market_key="OU_HOME", selection="Over", line=Decimal("1.5"), **base)
    ou = Selection(decision_id=2, market_key="OU", selection="Over", line=Decimal("2.5"), **base)
    away = Selection(decision_id=3, market_key="1X2", selection="Away", line=Decimal(0), **base)
    c = correlation.estimate(tt, ou, joint=joint)
    want = sim.pair(JOINT, OVER_15_HOME, sim.Selection("OU", "Over", 2.5)).correlation
    assert c.source == "joint_distribution" and c.rho == pytest.approx(want) and c.rho > 0.3
    assert correlation.estimate(tt, away, joint=joint).rho < 0, "the home side scoring twice and the away side winning pull apart"
    assert correlation.estimate(tt, ou).source == "same_match", "without the plug-in: the shared-factor rule"
    assert correlation.estimate(ou, away, joint=joint).source == "same_match", "a pair of the core's markets is not the family's to say"
    assert [p.source for p in correlation.pairs([tt, ou, away], joint=joint)] == ["joint_distribution"] * 2 + ["same_match"]


def test_no_core_module_knows_the_plugins_and_the_model_code_is_unchanged() -> None:
    """The proof that adding the family touched no core module: nothing outside ``fbi.plugins`` imports it or names the example,
    and the fingerprint every model version is keyed by is the running one."""
    for path in sorted(SRC.rglob("*.py")):
        if "__pycache__" in path.parts or (SRC / "plugins") in path.parents:
            continue
        text = path.read_text(encoding="utf-8")
        assert "TEAM_TOTALS" not in text and "fbi.plugins" not in text, path.relative_to(SRC).as_posix()
        for node in ast.walk(ast.parse(text)):
            if isinstance(node, ast.ImportFrom) and node.module == "fbi":
                assert "plugins" not in {a.name for a in node.names}, path.relative_to(SRC).as_posix()
    assert "plugins" not in MODEL_PACKAGES
    assert model_code_fingerprint() == RUNNING_MODEL_CODE


# -- no ACTIVE without a calibrator and an edge-gate promotion --------------------------------------------------------------------------

def gates(*, champion: bool, edge: bool) -> dict[str, GateStatus]:
    w = world(champion=champion, edge=edge)
    return {m: gate_of(w, m, example.MODEL) for m in example.MARKET_KEYS}


def promotable() -> plug.FamilyPlugin:
    """A copy of the template whose author allows promotion (the example itself never does)."""
    return dataclasses.replace(example.make_plugin(in_memory(inputs())), activatable=True)


def test_a_family_is_not_active_without_a_champion_calibrator_and_a_validated_edge() -> None:
    entry = promotable()
    with pytest.raises(plug.PromotionRefused) as none:
        plug.promote(entry, gates(champion=False, edge=True), by="owner", at=AT)
    assert any("no CHAMPION calibrator" in r for r in none.value.reasons) and not any("edge" in r for r in none.value.reasons)
    with pytest.raises(plug.PromotionRefused) as no_edge:
        plug.promote(entry, gates(champion=True, edge=False), by="owner", at=AT)
    assert all("edge not validated" in r for r in no_edge.value.reasons) and len(no_edge.value.reasons) == 2
    best_only = {m: dataclasses.replace(g, champion=None, best=g.champion) for m, g in gates(champion=True, edge=True).items()}
    with pytest.raises(plug.PromotionRefused):
        plug.promote(entry, best_only, by="owner", at=AT)
    with pytest.raises(plug.PromotionRefused):
        dataclasses.replace(entry, status=plug.ACTIVE), "an entry cannot just say ACTIVE"
    with pytest.raises(plug.PromotionRefused):
        plug.promote(example.make_plugin(in_memory(inputs())), gates(champion=True, edge=True), by="owner", at=AT)


def test_with_both_the_family_is_active_and_no_longer_capped() -> None:
    active = plug.promote(promotable(), gates(champion=True, edge=True), by="owner", at=AT)
    assert active.status == plug.ACTIVE and active.promotion is not None
    assert dict(active.promotion.calibrators) == {"OU_AWAY": 900, "OU_HOME": 901} and active.promotion.edge_validated == set(example.MARKET_KEYS)
    with pytest.raises(plug.PromotionRefused):
        plug.promote(active, gates(champion=True, edge=True), by="owner", at=AT)
    fam = active.decision_family()
    assert fam.params.promoted is True
    [d] = engine.decide_all(world(champion=True, edge=True), fam.candidates(None, at=AT))  # type: ignore[arg-type]
    assert CAP_CODE not in d.codes


# -- the registry refuses what a layer would not accept --------------------------------------------------------------------------------

@pytest.mark.parametrize(("change", "problem"), [
    ({"bets": (16, 99999)}, "bet 99999 is not in the taxonomy"),
    ({"bets": (5,), "market_keys": ("OU",)}, "OU already belongs to core"),
    ({"bets": (16,)}, "the catalogue derives ['OU_HOME']"),
    ({"rule": "goals_1h@v1"}, "is graded by goals_ft@v1, not by goals_1h@v1"),
    ({"bets": (45,), "market_keys": ("CORNERS_OU",), "rule": "corners_ft@v1"}, "CORNERS_OU already belongs to CORNERS"),
    ({"decision_version": "decision-v1"}, "belongs to a layer being replaced"),
    ({"name": "core"}, "must be upper case"),
    ({"settlement": SettlementRule("fbi.picks.count_settlement", "nowhere", "x")}, "does not exist"),
    ({"edge_gate": "edge-gate-v0"}, "is not one the calibration knows"),
    ({"model": ""}, "needs a model name and version"),
])
def test_the_registry_refuses_an_entry_a_layer_would_not_accept(change: dict[str, Any], problem: str) -> None:
    entry = dataclasses.replace(example.PLUGIN, **change)
    with pytest.raises(registry.RegistryError) as refused:
        registry.Registry().register(entry)
    assert any(problem in p for p in refused.value.problems), refused.value.problems


def test_a_bet_the_taxonomy_cannot_model_or_does_not_extract_backs_no_family_above_not_modelable() -> None:
    parked = dataclasses.replace(example.PLUGIN, bets=(164,), market_keys=())  # offsides: NOT_MODELABLE, not extracted
    problems = registry.check(parked)
    assert any("NOT_MODELABLE in the taxonomy" in p for p in problems) and any("not extracted" in p for p in problems)


def test_a_family_is_registered_once_and_its_markets_are_its_own() -> None:
    reg = registered()
    with pytest.raises(registry.RegistryError) as twice:
        reg.register(example.PLUGIN)
    assert any("another family is called TEAM_TOTALS" in p for p in twice.value.problems)
    assert any("OU_HOME already belongs to TEAM_TOTALS" in p for p in twice.value.problems)
    assert sum(f.owns("OU_HOME") for f in reg.decision_families()) == 1


def test_a_family_below_shadow_is_not_judged() -> None:
    research = dataclasses.replace(example.make_plugin(in_memory(inputs())), status=plug.RESEARCH)
    reg = registry.Registry()
    reg.register(research)
    assert [f.name for f in reg.decision_families()] == [f.name for f in FAMILIES]
    assert reg.joint_provider(None, at=AT, fixtures=[FIXTURE]).providers == ()
    with pytest.raises(ValueError, match="SHADOW and ACTIVE"):
        research.decision_family()
