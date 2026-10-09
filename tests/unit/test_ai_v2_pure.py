"""PrediGol AI V2's pure parts: when a match escalates, what a brief may say, the rules' brief, the budget's states
and the passes' shares, the search's language, the watch candidate, what counts as a material change, the class of
a loss and its ten answers, the day's notes and the patterns of losses. No database, no model, no network."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from fbi.ai.brief import BriefOut, escalation, lenient, line_text, rules_brief, validate
from fbi.ai.collectors import query_for
from fbi.ai.cycle import needs_llm, watch_candidate
from fbi.ai.learning import notes_for
from fbi.ai.patterns import loss_classes
from fbi.ai.pick_postmortem import Facts, answers, classify, verdict_of
from fbi.ai.prompts import REVIEW_VERSION
from fbi.ai.review import Candidate
from fbi.ai.usage import Budget, state_of

from .test_ai_decisions import AT, KO, home, packet


def cards() -> list[dict[str, Any]]:
    return [{"market": "1X2", "selection": "Home", "line": "0", "kind": "value", "p_model": "0.5200",
             "p_market": "0.4500", "ai": None}]


# ── escalation and the brief ─────────────────────────────────────────────────

def test_a_quiet_match_does_not_escalate_and_each_reason_is_the_servers() -> None:
    assert escalation(packet().content, candidates=0) == []
    assert escalation(packet().content, candidates=2) == ["candidate"]
    gap = packet(models__dixon_coles__selections=[{"market": "1X2", "selection": "Home", "line": "0", "p": 0.70,
                                                   "edge_vs_market": 0.25}])
    assert "model_market_gap" in escalation(gap.content, candidates=0)
    small = packet(models__dixon_coles__selections=[{"market": "OU", "selection": "Over", "line": "2.5", "p": 0.70,
                                                     "edge_vs_market": 0.25}])
    assert "model_market_gap" not in escalation(small.content, candidates=0), "the 1X2 gap only"
    p = packet()
    p.content["market"]["selections"][0]["movement"] = -0.05
    assert "market_move" in escalation(p.content, candidates=0)
    p = packet()
    p.content["absences"]["home"]["key_out"] = 2
    assert "important_news" in escalation(p.content, candidates=0)
    p = packet()
    p.content["evidence"] = [{"id": 7, "status": "CONTRADICTORY", "kind": "injury", "origin": "web", "side": "home",
                              "claim": "x"}]
    assert "contradiction" in escalation(p.content, candidates=0)
    p = packet(quality={"competition_score": None})
    assert escalation(p.content, candidates=0) == [], "an unknown quality is the same for every match: no reason"
    p = packet(quality={"competition_score": {"class": "INSUFFICIENT"}})
    assert "high_uncertainty" in escalation(p.content, candidates=0)
    p = packet()
    p.content["models"]["poisson"]["selections"][0]["p"] = 0.35
    assert "high_uncertainty" in escalation(p.content, candidates=0), "the models disagree by 17 points"


def test_a_brief_keeps_only_claims_it_can_back_and_only_the_given_cards() -> None:
    p = packet()
    p.content["evidence"] = [{"id": 42, "status": "PROBABLE", "kind": "injury", "origin": "web", "side": "away",
                              "claim": "El 9 visitante no juega"}]
    out = BriefOut.model_validate({
        "summary": "Local favorito por el modelo.", "data_quality": "good", "uncertainty": "medium",
        "contradiction": False, "escalate": True,
        "context": [{"text": "El mercado da 45 % al local.", "type": "DATA", "refs": ["P:market"]},
                    {"text": "El modelo da 99 % al local.", "type": "DATA", "refs": ["P:models"]},
                    {"text": "Se lesionó el 9 visitante.", "type": "NEWS", "refs": ["E:999"]}],
        "injuries": [{"side": "away", "player": "El 9", "status": "out", "refs": ["E:42"]},
                     {"side": "home", "player": "Inventado", "status": "out", "refs": []}],
        "changes": [],
        "cards": [{"market": "1X2", "selection": "Home", "line": "0.00",
                   "why": [{"text": "Modelo 52 % frente a 45 % del mercado.", "type": "DATA",
                            "refs": ["P:models", "P:market"]}], "risks": []},
                  {"market": "BTTS", "selection": "Yes", "line": "0", "why": [], "risks": []}]})
    content, rejected = validate(out, p, cards())
    assert [c["text"] for c in content["context"]] == ["El mercado da 45 % al local."]
    whys = {r["why"] for r in rejected}
    assert any("numbers not in the packet" in w for w in whys) and any("evidence not given" in w for w in whys)
    assert [i["player"] for i in content["injuries"]] == ["El 9"], "an injury needs a valid reference"
    assert [(n["market"], n["line"]) for n in content["cards"]] == [("1X2", "0")], "only the cards given"
    assert line_text("0.00") == "0" and line_text("2.50") == "2.5" and line_text(Decimal("-1.25")) == "-1.25"


def test_the_rules_brief_says_the_numbers_and_never_more() -> None:
    p = packet()
    p.content["absences"]["home"]["players"] = [{"name": "Portero Uno", "key": True, "type": "Missing Fixture"}]
    b = rules_brief(p, cards(), ["candidate"])
    assert "Home FC vs Away FC" in b["summary"] and "local 45 %" in b["summary"] and "Portero Uno" in b["summary"]
    assert b["escalate"] is True and b["uncertainty"] == "medium"
    assert b["cards"][0]["why"][0]["refs"] == ["P:models", "P:market"]
    assert b["injuries"] == [{"side": "home", "player": "Portero Uno", "status": "out", "refs": ["P:absences.home"]}]


# ── the budget ───────────────────────────────────────────────────────────────

def test_the_states_follow_the_days_budget_and_the_months_cap() -> None:
    def st(today: str, month: str = "10") -> str:
        return state_of(spent_today=Decimal(today), daily=Decimal("5"), cap=Decimal("7.5"),
                        spent_month=Decimal(month), monthly=Decimal("150"))
    assert st("0") == "NORMAL" and st("4.99") == "NORMAL"
    assert st("5") == "REDUCED", "past the day's budget: no strong model"
    assert st("6.25") == "CHEAP_ONLY" and st("7.49") == "CHEAP_ONLY"
    assert st("7.5") == "EXHAUSTED", "the day's ceiling"
    assert st("0", "150") == "EXHAUSTED", "the month's cap"


def test_each_pass_keeps_money_for_the_next_one() -> None:
    def b(spent: str) -> Budget:
        return Budget("NORMAL", Decimal(spent), Decimal(spent), Decimal("5"), Decimal("150"), Decimal("7.5"))
    assert b("2.70").pass_allows("first") and not b("2.80").pass_allows("first"), "55 % for the first pass"
    assert b("3.70").pass_allows("pre") and not b("3.80").pass_allows("pre"), "75 % by the second"
    assert b("4.90").pass_allows("final"), "the line-ups always have money left"
    assert not Budget("EXHAUSTED", Decimal(0), Decimal(0), Decimal(5), Decimal(150)).pass_allows("final")


# ── the web, the watch, what is material ─────────────────────────────────────

def test_the_search_speaks_the_competitions_language() -> None:
    assert "noticias" in query_for("Millonarios", "Nacional", KO, "Colombia")
    assert "escalação" in query_for("Flamengo", "Palmeiras", KO, "Brazil")
    assert "team news" in query_for("Arsenal", "Chelsea", KO, "England")
    assert KO.strftime("%Y-%m-%d") in query_for("A", "B", KO, None)


def test_the_watch_candidate_is_the_main_selection_nearest_to_value() -> None:
    c = watch_candidate(packet())
    assert c is not None and (c.market_key, c.selection) == ("1X2", "Home"), "52 % against 45 % at 2.40"
    p = packet()
    for s in p.content["market"]["selections"]:
        s["best_odds"] = 1.5
    assert watch_candidate(p) is None, "nothing near value at these prices"


def _last(**over: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"status": "ok", "engine_version": REVIEW_VERSION, "odds": Decimal("2.40"),
                            "reviewed_at": AT, "evidence_ids": [], "output": {"seen_evidence": [1, 2],
                                                                              "lineups_seen": False}}
    return base | over


def test_only_a_material_change_buys_a_new_review() -> None:
    c: Candidate = home()
    assert needs_llm(None, c, evidence_ids=set(), lineups_confirmed=False)
    assert not needs_llm(_last(), c, evidence_ids={1, 2}, lineups_confirmed=False), "nothing changed"
    assert needs_llm(_last(), home(odds=Decimal("2.50")), evidence_ids={1, 2}, lineups_confirmed=False), "price +4 %"
    assert not needs_llm(_last(), home(odds=Decimal("2.45")), evidence_ids={1, 2}, lineups_confirmed=False)
    assert needs_llm(_last(), c, evidence_ids={1, 2, 3}, lineups_confirmed=False), "evidence it had not seen"
    assert needs_llm(_last(), c, evidence_ids={1, 2}, lineups_confirmed=True), "the line-ups arrived"
    seen = _last(output={"seen_evidence": [1, 2], "lineups_seen": True})
    assert not needs_llm(seen, c, evidence_ids={1, 2}, lineups_confirmed=True)
    assert needs_llm(_last(engine_version="review-v1"), c, evidence_ids={1, 2}, lineups_confirmed=False)
    assert needs_llm(_last(status="invalid_output"), c, evidence_ids={1, 2}, lineups_confirmed=False)
    assert not needs_llm(_last(reviewed_at=AT - timedelta(hours=20)), c, evidence_ids={1, 2},
                         lineups_confirmed=False), "age alone is not a change"


# ── the post-mortem of a selection ───────────────────────────────────────────

def facts(**over: Any) -> Facts:
    base: dict[str, Any] = {"settled": "loss", "decision": "APPROVE", "p_model": 0.52, "p_market": 0.45,
                            "p_close": 0.47, "odds": 2.40, "close_odds": 2.30}
    return Facts(**(base | over))


def test_the_class_of_a_loss_is_the_first_that_applies() -> None:
    assert classify(facts(settled="win")) is None
    assert classify(facts(data_unfit=True, stale_price=True)) == "DATA_ERROR"
    assert classify(facts(stale_price=True, information_failed=True)) == "EXECUTION_ERROR"
    assert classify(facts(kickoff_changed=True)) == "EXECUTION_ERROR"
    assert classify(facts(information_failed=True, close_odds=3.0)) == "CONTEXT_ERROR"
    assert classify(facts(key_absence=["El 9 (local)"])) == "CONTEXT_ERROR", "a known key absence let through"
    assert classify(facts(key_absence=["El 9 (local)"], decision="DOWNGRADE")) != "CONTEXT_ERROR"
    assert classify(facts(close_odds=2.60)) == "MARKET_ERROR", "the price drifted 8 % against"
    assert classify(facts(p_model=0.60, p_close=0.47)) == "MODEL_ERROR"
    assert classify(facts()) == "NORMAL_VARIANCE", "a fair price that lost"
    assert classify(facts(p_close=None, close_odds=None)) == "UNKNOWN"


def test_the_verdicts_and_the_ten_answers() -> None:
    assert verdict_of(facts()) == "approved_lost" and verdict_of(facts(settled="win")) == "approved_won"
    assert verdict_of(facts(decision="REJECT", settled="win")) == "rejected_would_have_won"
    assert verdict_of(facts(decision="REJECT")) == "rejected_correctly"
    assert verdict_of(facts(decision=None)) == "unreviewed_lost" and verdict_of(facts(settled="push")) == "push"
    a = answers(facts(ignored=["market_against"]), "NORMAL_VARIANCE", score=(0, 1), label="A - B · 1X2 Home")
    assert set(a) == {"expected", "happened", "model", "information", "ignored_signal", "odds_moved", "key_absence",
                      "lineup_changed", "uncertainty", "variance"}
    assert a["ignored_signal"]["answer"] == "sí" and a["variance"]["answer"] == "sí"
    assert a["odds_moved"]["answer"] == "a favor" and a["model"]["answer"] == "no", "2.40 taken, 2.30 at the close"


# ── the day's notes and the patterns of losses ───────────────────────────────

def pm(i: int, verdict: str, cls: str | None = None, **over: Any) -> dict[str, Any]:
    base = {"id": i, "fixture_id": i, "market_key": "1X2", "selection": "Home", "line": Decimal(0), "roles": [],
            "decision": {"approved": "APPROVE", "caution": "DOWNGRADE", "rejected": "REJECT"}.get(verdict.split("_")[0]),
            "settled": "loss" if verdict.endswith(("lost", "correctly")) else "win", "verdict": verdict,
            "classification": cls, "odds": Decimal("2.0"), "close_odds": None, "clv": None, "p_model": 0.5,
            "p_market": 0.45, "answers": {"model": {"data": {"p_close": 0.46}}}, "evidence": {}, "match": f"M{i}"}
    return base | over


def test_the_days_notes_count_and_cite_their_post_mortems() -> None:
    rows = [pm(1, "approved_won"), pm(2, "approved_lost", "MARKET_ERROR", clv=Decimal("-0.05")),
            pm(3, "rejected_would_have_won"), pm(4, "rejected_correctly", "MODEL_ERROR")]
    notes = {n.kind: n for n in notes_for(rows, [], [])}
    assert notes["summary"].n == 4 and "Aprobadas 2 (1 ganadas, 1 perdidas)" in notes["summary"].body
    assert notes["approved"].evidence["classes"] == {"MARKET_ERROR": 1}
    assert notes["rejected"].evidence == {"postmortems": [3, 4], "would_have_won": 1, "rejected_correctly": 1}
    assert "market" in notes and "model" in notes
    assert notes_for([], [], []) == []


def test_a_class_of_losses_becomes_a_hypothesis_only_with_a_sample() -> None:
    def ev(i: int, cls: str) -> dict[str, Any]:
        return {"id": i, "kind": "pick_postmortem", "result": cls, "evidence": {}, "created_at": AT}
    few = [ev(i, "MARKET_ERROR") for i in range(10)]
    assert loss_classes(few) == [], "ten losses are not a sample"
    many = [ev(i, "MARKET_ERROR") for i in range(12)] + [ev(100 + i, "MODEL_ERROR") for i in range(4)] + \
        [ev(200 + i, "NORMAL_VARIANCE") for i in range(10)] + [ev(300 + i, "CONTEXT_ERROR") for i in range(4)]
    found = loss_classes(many)
    assert [f.key for f in found] == ["pattern:loss:MARKET_ERROR"], "12 of 20 classified losses"
    assert found[0].target == "pick_engine" and found[0].evidence["n_matches"] == 20
    assert "investigation_cost" in found[0].evidence and "impact" in found[0].evidence


def test_nothing_here_moves_a_probability() -> None:
    # the brief's schema has no probability and the post-mortem only reads
    from fbi.ai.prompts import BRIEF_SCHEMA

    def keys(node: Any) -> set[str]:
        if isinstance(node, dict):
            return set(node) | {k for v in node.values() for k in keys(v)}
        if isinstance(node, list):
            return {k for v in node for k in keys(v)}
        return set()
    assert not {k for k in keys(BRIEF_SCHEMA) if k.startswith("p_") or "probab" in k or "stake" in k}
    assert datetime.now(UTC) > AT - timedelta(days=36500)


def test_an_incomplete_brief_is_repaired_only_where_nothing_is_invented() -> None:
    wrapped = {"brief": {"summary": "Partido parejo.", "context": "[]", "cards": "no es json", "extra": 1}}
    d = lenient(wrapped)
    assert d["summary"] == "Partido parejo." and d["context"] == [] and d["cards"] == [] and "extra" not in d
    assert (d["data_quality"], d["uncertainty"], d["contradiction"], d["escalate"]) == ("fair", "medium", False, False)
    assert BriefOut.model_validate(d).summary == "Partido parejo."
    assert "summary" not in lenient({"context": []}), "a missing summary stays missing: the answer is invalid"
    as_text = lenient({"payload": '{"summary": "Texto.", "uncertainty": "low"}'})
    assert as_text["summary"] == "Texto." and as_text["uncertainty"] == "low"


def test_a_block_with_a_digit_can_be_cited() -> None:
    from fbi.ai.claims import ClaimOut, refused

    ok = ClaimOut(text="Ganó los dos últimos cruces.", type="DATA", refs=["P:h2h"])
    assert refused(ok, stored=set(), evidence_status={}) is None
    bad = ClaimOut(text="Otro dato.", type="DATA", refs=["P:2h"])
    assert refused(bad, stored=set(), evidence_status={}) is not None
