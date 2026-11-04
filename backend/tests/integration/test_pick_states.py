"""The visible state of a pick and «¿Por qué este pick?» over HTTP (plan UX, B3), on example picks in every state - a real database,
the transaction rolled back.

    A  +3h  published, value now          review APPROVE     in the day's set (frozen: DOWNGRADE, applied then)
    B  +4h  published, value now          review DOWNGRADE
    C  +5h  published, value now          review REJECT
    D  +6h  published, value now          no review          in the day's set (frozen: REJECT, not applied then)
    E  +7h  published, price 1.70         -> no value now
    S  +8h  shadow pick (its model has not beaten the market)  in the evaluation set
    K  -1h  published, its match already kicked off

«Criterio de terminado: cada estado visible equivale a uno interno ... todo pick publicado responde «¿por qué?»». The AI's review
changes a state only while it is applied: the owner's switch (FBI_AI_MODE=enforce) AND a passed shadow gate.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from fbi.api.app import create_app
from fbi.api.deps import get_db
from fbi.api.security import optional_principal
from fbi.api.services import reading as reading_service
from fbi.core.clock import FrozenClock, SystemClock, set_clock
from fbi.picks.daily import product_day
from tests.integration.conftest import Seed
from tests.integration.helpers import scalar
from tests.integration.signed_in import SAME_SITE, principal
from tests.integration.test_reading_api import CONTENT

pytestmark = pytest.mark.integration

NOW = datetime(2031, 6, 16, 12, 0, tzinfo=UTC)
PICK_COLS = (
    "candidate_id,fixture_id,market_key,selection,model_version_id,feature_set_hash,data_cutoff_ts,decision_rule_version,"
    "code_version,bookmaker_id,market_odds,odds_captured_at,p_model,p_calibrated,p_calibrated_lo,p_calibrated_hi,"
    "p_market_fair,fair_odds,edge,price_edge,ev,ev_adjusted,kelly_fraction,stake_units,selection_reason"
)
PLAN: dict[str, tuple[float, str, str, str | None]] = {
    # name: kickoff hours from NOW, pick status, best price now, the AI's newest review
    "A": (3, "qualified", "2.30", "APPROVE"),
    "B": (4, "qualified", "2.30", "DOWNGRADE"),
    "C": (5, "qualified", "2.30", "REJECT"),
    "D": (6, "qualified", "2.30", None),
    "E": (7, "qualified", "1.70", None),
    "S": (8, "shadow", "2.30", None),
    "K": (-1, "qualified", "2.30", None),
}


@dataclasses.dataclass
class World:
    db: psycopg.Connection[Any]
    fixtures: dict[str, int]
    picks: dict[str, int]

    def enforce(self, monkeypatch: pytest.MonkeyPatch, *, gate: str | None = "pass") -> None:
        """The owner's switch on and, unless ``gate`` is None, a shadow report whose gate says so."""
        monkeypatch.setenv("FBI_AI_MODE", "enforce")
        if gate is not None:
            self.db.execute("INSERT INTO ai.shadow_reports (created_at, window_from, window_to, engine, arms, gate, version) "
                            "VALUES (%s, %s, %s, 'combined', '{}', %s, 'ai-gate-v1')",
                            (NOW - timedelta(hours=2), (NOW - timedelta(days=60)).date(), NOW.date(), Jsonb({"verdict": gate})))


@pytest.fixture()
def world(db: psycopg.Connection[Any], seed: Seed, monkeypatch: pytest.MonkeyPatch) -> Iterator[World]:
    monkeypatch.delenv("FBI_AI_MODE", raising=False)
    monkeypatch.setenv(reading_service.USERS_SWITCH, "1")
    monkeypatch.delenv("FBI_USER_NARRATIVE", raising=False)
    fixtures: dict[str, int] = {}
    picks: dict[str, int] = {}
    cutoff = NOW - timedelta(days=1)
    for n, (name, (hours, status, price, review)) in enumerate(PLAN.items()):
        ko = NOW + timedelta(hours=hours)
        fid = scalar(db.execute(
            "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (9_931_000 + n, seed.season_id, seed.home_team_id, seed.away_team_id, ko)))
        fixtures[name] = fid
        prediction = scalar(db.execute(
            "INSERT INTO models.predictions (fixture_id, model_version_id, market_key, selection, p_raw, p_calibrated, p_lo, "
            "p_hi, feature_set_hash, data_cutoff_ts) VALUES (%s, %s, '1X2', 'Home', 0.50, 0.50, 0.45, 0.55, 'b3', %s) "
            "RETURNING id", (fid, seed.model_version_id, cutoff)))
        candidate = scalar(db.execute(
            "INSERT INTO picks.pick_candidates (run_id, fixture_id, prediction_id, market_key, selection, bookmaker_id, "
            "market_odds, p_calibrated, p_market_fair, edge, price_edge, ev, ev_adjusted, decision) VALUES (%s, %s, %s, '1X2', "
            "'Home', %s, 2.30, 0.50, 0.43, 0.07, 0.08, 0.15, 0.10, 'selected') RETURNING id",
            (seed.run_id, fid, prediction, seed.bookmaker_id)))
        taken = min(cutoff + timedelta(minutes=5), ko - timedelta(hours=3))
        pick = scalar(db.execute(
            f"INSERT INTO picks.picks ({PICK_COLS}) VALUES (%s, %s, '1X2', 'Home', %s, 'b3', %s, 'shadow-rule-v2', 'b3', %s, "
            "2.30, %s, 0.50, 0.50, 0.45, 0.55, 0.43, 2.0, 0.07, 0.08, 0.15, 0.10, 0.11, 1, '{}') RETURNING id",
            (candidate, fid, seed.model_version_id, cutoff, seed.bookmaker_id, taken)))
        picks[name] = pick
        if status != "shadow":
            db.execute("UPDATE picks.picks SET status = %s, qualification = '{\"qualified\": true}'::jsonb WHERE id = %s",
                       (status, pick))
        as_of = min(NOW, ko) - timedelta(minutes=30)
        for sel, p_fair, odds in (("Home", "0.43", price), ("Draw", "0.28", "3.40"), ("Away", "0.29", "3.30")):
            db.execute("INSERT INTO market.market_consensus (fixture_id, market_key, selection, line, as_of, devig_method, "
                       "p_fair, n_bookmakers, overround, best_odds, best_bookmaker_id) VALUES (%s, '1X2', %s, 0, %s, 'shin', "
                       "%s, 5, 0.05, %s, %s)", (fid, sel, as_of, p_fair, odds, seed.bookmaker_id))
        if review is not None:
            db.execute(
                "INSERT INTO ai.pick_reviews (reviewed_at, fixture_id, pick_id, market_key, selection, line, engine, "
                "engine_version, input_hash, decision, confidence, output, mode, status) VALUES (%s, %s, %s, '1X2', 'Home', 0, "
                "'combined', 'rules-review-v1+none', 'b3', %s, 0.6, %s, 'shadow', 'ok')",
                (NOW - timedelta(minutes=40), fid, pick, review, Jsonb({
                    "reason": "revisión de prueba", "positive_evidence": [{"text": f"A favor ({review})"}],
                    "negative_evidence": [{"text": f"En contra ({review})"}]})))
    day = product_day(NOW)
    for source, items in (("qualified", (("A", {"decision": "DOWNGRADE", "enforced": True, "mode": "enforce"}, "2.20"),
                                         ("D", {"decision": "REJECT", "enforced": False, "mode": "shadow"}, "2.25"))),
                          ("evaluation", (("S", {"decision": None, "enforced": False, "mode": "shadow"}, "2.30"),))):
        set_id = scalar(db.execute(
            "INSERT INTO picks.daily_sets (day, timezone, source, rule_version, status, created_at, updated_at) VALUES "
            "(%s, 'America/Bogota', %s, 'daily-set-v5', 'COMPLETE', %s, %s) RETURNING id",
            (day, source, NOW - timedelta(hours=3), NOW - timedelta(hours=3))))
        for rank, (name, ai, odds) in enumerate(items, start=1):
            db.execute(
                "INSERT INTO picks.daily_set_items (set_id, rank, pick_id, fixture_id, market_key, selection, line, stage, "
                "selected_at, odds, bookmaker_id, price_at, p_model, p_low, p_push, p_market, ev, model_version_id, inputs) "
                "VALUES (%s, %s, %s, %s, '1X2', 'Home', 0, 'T-6h', %s, %s, %s, %s, 0.50, 0.45, 0, 0.43, 0.10, %s, %s)",
                (set_id, rank, picks[name], fixtures[name], NOW - timedelta(hours=3), Decimal(odds), seed.bookmaker_id,
                 NOW - timedelta(hours=3), seed.model_version_id, Jsonb({"ai": ai})))
    set_clock(FrozenClock(NOW))
    yield World(db, fixtures, picks)
    set_clock(SystemClock())


def client(db: psycopg.Connection[Any], role: str = "USER", user_id: int = 1) -> TestClient:
    app = create_app()
    who = principal(role, user_id=user_id)
    app.dependency_overrides[optional_principal] = lambda: who
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app, headers=SAME_SITE)


def data(c: TestClient, path: str, **params: Any) -> Any:
    r = c.get(path, params=params)
    assert r.status_code == 200, (path, r.status_code, r.text[:300])
    return r.json()["data"]


def states(cards: list[dict[str, Any]], picks: dict[str, int]) -> dict[str, tuple[str, str, bool]]:
    names = {v: k for k, v in picks.items()}
    return {names[c["pick_id"]]: (c["user_status"], c["status_reason"], c["context_pending"]) for c in cards}


# ── the list of picks ──────────────────────────────────────────────────────────────────────────────────────────────────


def test_in_shadow_every_published_pick_with_value_is_recommended_and_says_its_review_is_pending(world: World) -> None:
    board = data(client(world.db), "/api/v1/picks")
    assert states(board["picks"], world.picks) == dict.fromkeys("ABCD", ("RECOMMENDED", "value", True)), \
        "a review that is not applied changes nothing - not even C's REJECT"
    assert board["withheld"] == 1, "E has no value at the best price now: on its match, never in the list"
    preview = data(client(world.db, "SUPER_ADMIN"), "/api/v1/picks", preview="shadow")
    got = states(preview["picks"], world.picks)
    assert got["S"] == ("EVALUATION", "evaluation", False), "a shadow pick is never a recommendation, not even in the preview"
    assert got["E"] == ("NOT_RECOMMENDED", "no_value_now", False) and preview["withheld"] == 0


def test_with_the_review_applied_the_states_follow_it(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    world.enforce(monkeypatch)
    board = data(client(world.db), "/api/v1/picks")
    assert states(board["picks"], world.picks) == {
        "A": ("RECOMMENDED", "approved", False),
        "D": ("RECOMMENDED", "not_reviewed", True),
        "B": ("CAUTION", "downgraded", False)}
    order = [{v: k for k, v in world.picks.items()}[c["pick_id"]] for c in board["picks"]]
    assert order.index("B") > max(order.index("A"), order.index("D")), "the downgraded ones after the rest"
    assert board["withheld"] == 2, "C (rejected) and E (no value) stay on their match"
    match = data(client(world.db), "/api/v1/picks", fixture_id=world.fixtures["C"], hours=168)
    assert states(match["picks"], world.picks) == {"C": ("NOT_RECOMMENDED", "rejected", False)}
    assert match["top"] == [] and match["withheld"] == 0, "its match shows it, with its state - never ranked"


def test_a_list_that_keeps_every_pick_on_its_match_says_why_truthfully(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    only_e = data(client(world.db), "/api/v1/picks", max_odds="1.80")
    assert (only_e["picks"], only_e["withheld"], only_e["reason"]) == ([], 1, "no_value_now")
    world.enforce(monkeypatch)
    for name in "ABD":
        world.db.execute(
            "INSERT INTO ai.pick_reviews (reviewed_at, fixture_id, pick_id, market_key, selection, line, engine, engine_version, "
            "input_hash, decision, confidence, output, mode, status) VALUES (%s, %s, %s, '1X2', 'Home', 0, 'combined', "
            "'rules-review-v1+none', 'b3-all', 'REJECT', 0.7, '{}', 'shadow', 'ok')",
            (NOW - timedelta(minutes=20), world.fixtures[name], world.picks[name]))
    board = data(client(world.db), "/api/v1/picks")
    assert (board["picks"], board["top"], board["withheld"]) == ([], [], 5)
    assert board["reason"] == "none_recommended", "rejected ones are not «without value at the price now»"


def test_the_switch_alone_applies_nothing_without_a_passed_gate(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    for gate in (None, "fail"):
        world.enforce(monkeypatch, gate=gate)
        board = data(client(world.db), "/api/v1/picks")
        assert states(board["picks"], world.picks) == dict.fromkeys("ABCD", ("RECOMMENDED", "value", True)), gate


def test_the_days_set_shows_each_pick_as_it_entered(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    items = data(client(world.db), "/api/v1/daily")["set"]["items"]
    assert states(items, world.picks) == {"A": ("CAUTION", "downgraded", False), "D": ("RECOMMENDED", "value", True)}, \
        "A's review was applied when it entered the set; D's REJECT was not, so it changed nothing"
    world.enforce(monkeypatch)
    assert states(data(client(world.db), "/api/v1/daily")["set"]["items"], world.picks)["D"] == (
        "RECOMMENDED", "value", True), "a record keeps the state it entered with"
    preview = data(client(world.db, "SUPER_ADMIN"), "/api/v1/daily", preview="shadow")["set"]["items"]
    assert states(preview, world.picks) == {"S": ("EVALUATION", "evaluation", False)}


# ── a match's analysis ────────────────────────────────────────────────────────────────────────────────────────────────


def analysis_card(market: str, selection: str, kind: str, verdict: str, *, qualified: bool, pick_id: int | None,
                  decision: str | None) -> dict[str, Any]:
    return {"market": market, "selection": selection, "line": "0", "kind": kind, "odds": "2.300", "bookmaker": "BK",
            "p_model": "0.5000", "p_low": "0.4500", "p_market": "0.4300", "fair_odds": "2.00", "minimum_odds": "2.33",
            "edge": "0.0700", "ev": "0.1500", "model": "dixon_coles", "pick_id": pick_id, "qualified": qualified,
            "verdict": verdict, "verdict_reason": "context_caution" if decision == "DOWNGRADE" else "value",
            "ai": None if decision is None else {"decision": decision, "review_id": None, "confidence": 0.6, "reason": "x",
                                                 "positives": [], "risks": [], "engines": ["rules"]}}


def test_a_matchs_analysis_says_each_cards_state(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    fid = world.fixtures["B"]
    world.db.execute(
        "INSERT INTO ai.match_analyses (fixture_id, built_at, rule_version, input_hash, market_observed, cards, engines) "
        "VALUES (%s, %s, 'match-analysis-v1', 'b3', true, %s, '{rules}')",
        (fid, NOW - timedelta(minutes=20), Jsonb([
            analysis_card("1X2", "Home", "value", "caution", qualified=True, pick_id=world.picks["B"], decision="DOWNGRADE"),
            analysis_card("OU", "Over", "value", "recommended", qualified=False, pick_id=None, decision=None),
            analysis_card("BTTS", "Yes", "evaluated", "not_recommended", qualified=False, pick_id=None, decision=None)])))
    url = f"/api/v1/matches/{fid}/analysis"
    shadow = data(client(world.db), url)
    [card] = shadow["cards"]
    assert (card["user_status"], card["status_reason"], card["context_pending"]) == ("RECOMMENDED", "value", True)
    assert card["verdict"] == "recommended" and card["ai"] is None and card["pick_id"] == world.picks["B"]
    world.enforce(monkeypatch)
    [card] = data(client(world.db), url)["cards"]
    assert (card["user_status"], card["status_reason"], card["verdict"]) == ("CAUTION", "downgraded", "caution")
    owner = data(client(world.db, "SUPER_ADMIN"), url, preview="shadow")["cards"]
    assert [(c["kind"], c["user_status"]) for c in owner] == [
        ("value", "CAUTION"), ("value", "EVALUATION"), ("evaluated", "NOT_RECOMMENDED")]
    verdict_of = {"RECOMMENDED": "recommended", "CAUTION": "caution", "NOT_RECOMMENDED": "not_recommended"}
    for c in (card, *shadow["cards"]):
        assert verdict_of[c["user_status"]] == c["verdict"], "what a reader is shown agrees with the card's own verdict"


# ── «¿Por qué este pick?» ─────────────────────────────────────────────────────────────────────────────────────────────


def explanation(c: TestClient, pick: int, **params: Any) -> Any:
    return data(c, f"/api/v1/picks/{pick}/explanation", **params)


def test_every_published_pick_answers_why_in_five_layers(world: World) -> None:
    e = explanation(client(world.db), world.picks["A"])
    assert e["version"] == "pick-explanation-v1" and e["started"] is False
    assert (e["user_status"], e["status_reason"], e["context_pending"]) == ("RECOMMENDED", "value", True)
    assert e["market_key"] == "1X2" and e["selection"] == "Home" and e["match"]["fixture_id"] == world.fixtures["A"]
    day = e["day"]
    assert day["rank"] == 1 and day["stage"] == "T-6h" and Decimal(day["odds"]) == Decimal("2.20")
    assert (day["user_status"], day["status_reason"]) == ("CAUTION", "downgraded"), "as it entered the set, as its card says"
    m = e["market"]
    assert Decimal(m["p_model"]) == Decimal("0.50") and Decimal(m["p_market"]) == Decimal("0.43")
    assert Decimal(m["published_odds"]) == Decimal("2.20"), "a pick of the day: the set's own price"
    assert Decimal(m["odds_now"]) == Decimal("2.30") and m["value_now"] is True and m["bookmaker_now"]
    assert e["reading_shown"] is True and e["reading_complete"] is False and e["context"] == []
    assert next(f["code"] for f in e["risks"]) == "no_context_yet", "without a packet the risks say so"
    assert e["review"] is None and e["narrative"] is None, "the review is not applied: nothing it decided is shown"
    every = {n: explanation(client(world.db), world.picks[n]) for n in "BCDE"}
    assert {n: x["user_status"] for n, x in every.items()} == {
        "B": "RECOMMENDED", "C": "RECOMMENDED", "D": "RECOMMENDED", "E": "NOT_RECOMMENDED"}
    assert every["B"]["day"] is None and Decimal(every["B"]["market"]["published_odds"]) == Decimal("2.30")
    assert every["E"]["market"]["value_now"] is False and every["E"]["status_reason"] == "no_value_now"


def test_with_the_review_applied_the_explanation_carries_it(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    world.enforce(monkeypatch)
    e = explanation(client(world.db), world.picks["C"])
    assert (e["user_status"], e["status_reason"]) == ("NOT_RECOMMENDED", "rejected")
    assert e["review"] == {"decision": "REJECT", "positives": ["A favor (REJECT)"], "risks": ["En contra (REJECT)"]}
    assert explanation(client(world.db), world.picks["D"])["review"] is None, "no review, nothing invented"


def test_who_may_ask_why(world: World) -> None:
    user, owner = client(world.db), client(world.db, "SUPER_ADMIN")
    shadow = world.picks["S"]
    assert user.get(f"/api/v1/picks/{shadow}/explanation").status_code == 404, "a reader never learns a shadow pick exists"
    assert owner.get(f"/api/v1/picks/{shadow}/explanation").status_code == 404, "without the preview, a reader's answer"
    e = explanation(owner, shadow, preview="shadow")
    assert (e["user_status"], e["status_reason"]) == ("EVALUATION", "evaluation") and e["day"]["user_status"] == "EVALUATION"
    assert user.get(f"/api/v1/picks/{shadow}/explanation", params={"preview": "shadow"}).status_code == 403
    assert user.get("/api/v1/picks/999999999999/explanation").status_code == 404
    k = explanation(user, world.picks["K"])
    assert k["started"] is True and k["market"]["odds_now"] is None and k["market"]["value_now"] is None
    assert Decimal(k["market"]["p_market"]) == Decimal("0.43") and Decimal(k["market"]["published_odds"]) == Decimal("2.30")
    assert k["user_status"] == "RECOMMENDED", "as it was taken: never re-priced after kick-off"


def test_the_context_layer_is_the_readings_and_its_switch_is_respected(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    fid = world.fixtures["A"]
    world.db.execute("INSERT INTO ai.match_packets (fixture_id, packet_version, as_of, built_at, packet_hash, content, missing) "
                     "VALUES (%s, 'packet-v8', %s, %s, %s, %s, %s)",
                     (fid, NOW - timedelta(minutes=10), NOW - timedelta(minutes=9), "b" * 64, Jsonb(CONTENT), ["stats"]))
    e = explanation(client(world.db), world.picks["A"])
    codes = [f["code"] for f in e["context"]]
    assert e["reading_complete"] is True and e["reading_at"] is not None
    assert {"stakes_zone", "rest_days", "form", "key_absences"} <= set(codes)
    assert all(f["ref"].startswith(("packet", "forecast")) for f in e["context"] + e["risks"]), "every fact with its reference"
    assert {"lineups_unconfirmed", "rumours"} <= {f["code"] for f in e["risks"]}
    text = str(e).lower()
    for never in ("se dice que el portero", "rumours.example", "dixon", "1810"):
        assert never not in text, never
    monkeypatch.setenv(reading_service.USERS_SWITCH, "0")
    hidden = explanation(client(world.db), world.picks["A"])
    assert hidden["reading_shown"] is False and hidden["context"] == [] and hidden["risks"] == []
    preview = explanation(client(world.db, "SUPER_ADMIN"), world.picks["A"], preview="shadow")
    assert preview["reading_shown"] is True and preview["context"], "the owner's preview does not depend on the switch"


def test_every_reader_gets_the_same_states_and_the_same_explanation(world: World) -> None:
    one, two = client(world.db, user_id=1), client(world.db, user_id=2)
    assert data(one, "/api/v1/picks") == data(two, "/api/v1/picks")
    assert explanation(one, world.picks["A"]) == explanation(two, world.picks["A"])
    assert data(one, "/api/v1/daily") == data(two, "/api/v1/daily")
