"""«Explícame» over HTTP (plan UX, B9), on B3's example picks in every state (``test_pick_states``) - a real database, the
transaction rolled back.

    no_pick   a match with a pick says so; one played without a pick says none was published; one still to be played says what
              stands in the way - its forecast, its prices, the decision layer's latest evaluation of each selection - and an
              evaluation pick is never named (S)
    pick      what can go wrong (its probability, the model's doubt, the reading's risks, the review's own only while it is
              applied) and «¿Por qué cautela?» for every state
    parlay    every leg must win: each leg's probability, their product, the related legs and the slip's own warning - the same
              numbers as POST /me/parlays/validate; a leg without a probability is «no tengo ese dato»; a broken rule is named
    the door  FBI_EXPLAIN=0 (404, and /auth/me says so), the preview (403 to a reader), the limit (30 a minute), a question
              that is not the place's (422), and not one call to the outside world
"""

from __future__ import annotations

import math
from collections.abc import Iterator
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from fbi.api.routers import explain as explain_router
from tests.integration.conftest import Seed
from tests.integration.helpers import scalar
from tests.integration.test_pick_states import NOW, World, client, world  # noqa: F401  (the fixture and the data)
from tests.integration.test_user_layer_guards import doors_shut  # noqa: F401  (the trap of the outside world)

pytestmark = pytest.mark.integration


@pytest.fixture(autouse=True)
def fresh_limit() -> Iterator[None]:
    explain_router.LIMIT.reset()
    yield
    explain_router.LIMIT.reset()


def ask(c: TestClient, entity: str, item: int, intent: str, **params: Any) -> dict[str, Any]:
    r = c.get("/api/v1/explain", params={"entity": entity, "id": item, "intent": intent, **params})
    assert r.status_code == 200, (entity, item, intent, r.status_code, r.text[:300])
    data: dict[str, Any] = r.json()["data"]
    assert data["version"] == "explain-v1" and (data["entity"], data["item_id"], data["intent"]) == (entity, item, intent)
    return data


def slip(c: TestClient, legs: list[dict[str, Any]]) -> dict[str, Any]:
    r = c.post("/api/v1/explain/parlay", json={"legs": legs})
    assert r.status_code == 200, (r.status_code, r.text[:300])
    data: dict[str, Any] = r.json()["data"]
    assert (data["entity"], data["item_id"], data["intent"]) == ("parlay", None, "probability")
    return data


def says(answer: dict[str, Any]) -> list[str]:
    return [line["say"] or f"fact:{line['fact']['code']}" for line in answer["lines"]]


def said(answer: dict[str, Any], code: str) -> dict[str, Any]:
    params: dict[str, Any] = next(line["params"] for line in answer["lines"] if line["say"] == code)
    return params


def every(answer: dict[str, Any], code: str) -> list[dict[str, Any]]:
    return [line["params"] for line in answer["lines"] if line["say"] == code]


def leg(world: World, name: str, selection: str = "Home", market: str = "1X2", line: str = "0") -> dict[str, Any]:  # noqa: F811
    return {"fixture_id": world.fixtures[name], "market_key": market, "selection": selection, "line": line}


def new_match(world: World, seed: Seed, n: int, hours: float) -> int:  # noqa: F811
    return int(scalar(world.db.execute(
        "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at) "
        "VALUES (%s, %s, %s, %s, %s) RETURNING id",
        (9_932_000 + n, seed.season_id, seed.home_team_id, seed.away_team_id, NOW + timedelta(hours=hours)))))


def forecast_of(world: World, seed: Seed, fid: int, selection: str = "Home") -> int:  # noqa: F811
    return int(scalar(world.db.execute(
        "INSERT INTO models.predictions (fixture_id, model_version_id, market_key, selection, p_raw, p_calibrated, p_lo, p_hi, "
        "feature_set_hash, data_cutoff_ts) VALUES (%s, %s, '1X2', %s, 0.40, 0.40, 0.35, 0.45, 'b9', %s) RETURNING id",
        (fid, seed.model_version_id, selection, NOW - timedelta(days=1)))))


def prices_of(world: World, seed: Seed, fid: int) -> None:  # noqa: F811
    for sel, p_fair, odds in (("Home", "0.43", "2.20"), ("Draw", "0.28", "3.40"), ("Away", "0.29", "3.30")):
        world.db.execute("INSERT INTO market.market_consensus (fixture_id, market_key, selection, line, as_of, devig_method, "
                         "p_fair, n_bookmakers, overround, best_odds, best_bookmaker_id) VALUES (%s, '1X2', %s, 0, %s, 'shin', "
                         "%s, 5, 0.05, %s, %s)", (fid, sel, NOW - timedelta(hours=1), p_fair, odds, seed.bookmaker_id))


def evaluated(world: World, seed: Seed, fid: int, prediction: int, selection: str, market: str,  # noqa: F811
              decision: str, reason: str | None, hours_ago: float) -> None:
    world.db.execute(
        "INSERT INTO picks.pick_candidates (run_id, fixture_id, prediction_id, market_key, selection, bookmaker_id, market_odds, "
        "p_calibrated, p_market_fair, edge, price_edge, ev, ev_adjusted, decision, rejection_reason, evaluated_at) VALUES "
        "(%s, %s, %s, %s, %s, %s, 2.20, 0.40, 0.43, -0.03, -0.02, -0.12, -0.15, %s, %s, %s)",
        (seed.run_id, fid, prediction, market, selection, seed.bookmaker_id, decision, reason,
         NOW - timedelta(hours=hours_ago)))


# ── «¿Por qué no hay pick?» ───────────────────────────────────────────────────────────────────────────────────────────


def test_a_match_with_a_pick_says_so_and_opens_it(world: World) -> None:  # noqa: F811
    c = client(world.db)
    a = ask(c, "match", world.fixtures["A"], "no_pick")
    assert says(a) == ["has_pick"] and said(a, "has_pick") == {"count": 1}
    assert a["answered"] is True and a["links"] == ["why_pick"] and a["terms"] == ["pick"]
    started = ask(c, "match", world.fixtures["K"], "no_pick")
    assert said(started, "has_pick") == {"count": 1}, "a pick published before kick-off is still the match's pick"


def test_a_match_whose_only_pick_is_an_evaluation_one_never_names_it(world: World) -> None:  # noqa: F811
    s = ask(client(world.db), "match", world.fixtures["S"], "no_pick")
    assert says(s) == ["no_pick_not_published", "pick_rule", "no_pick_may_change"]
    assert said(s, "no_pick_not_published") == {"evaluated": 1}, "counted among the selections, never named"
    assert s["answered"] is True and s["links"] == ["transparency"]
    text = str(s).lower()
    for never in ("shadow", "evaluation", "evaluación", "pick_id"):
        assert never not in text, never


def test_a_match_still_to_be_played_says_what_stands_in_the_way(world: World, seed: Seed) -> None:  # noqa: F811
    c = client(world.db)
    bare = new_match(world, seed, 1, 30)
    assert says(ask(c, "match", bare, "no_pick")) == ["no_pick_no_forecast", "pick_rule", "no_pick_may_change"]

    no_prices = new_match(world, seed, 2, 30)
    forecast_of(world, seed, no_prices)
    assert says(ask(c, "match", no_prices, "no_pick"))[0] == "no_pick_no_prices"

    not_compared = new_match(world, seed, 3, 30)
    forecast_of(world, seed, not_compared)
    prices_of(world, seed, not_compared)
    assert says(ask(c, "match", not_compared, "no_pick"))[0] == "no_pick_not_compared"

    rejected = new_match(world, seed, 4, 30)
    prediction = forecast_of(world, seed, rejected)
    prices_of(world, seed, rejected)
    # Home was chosen two hours ago and refused an hour ago: its LATEST evaluation is what counts
    evaluated(world, seed, rejected, prediction, "Home", "1X2", "selected", None, 2)
    evaluated(world, seed, rejected, prediction, "Home", "1X2", "rejected", "expected value below 0.02 (observed -0.1200)", 1)
    evaluated(world, seed, rejected, prediction, "Draw", "1X2", "rejected", "probability edge below 0.03 (observed +0.0100)", 1)
    evaluated(world, seed, rejected, prediction, "Away", "1X2", "rejected", "odds outside [1.5, 4.0] (observed 5.200)", 1)
    evaluated(world, seed, rejected, prediction, "Yes", "BTTS", "rejected", "market BTTS is not covered by shadow-rule-v2", 1)
    a = ask(c, "match", rejected, "no_pick")
    assert says(a) == ["no_pick_no_value", "pick_rule", "no_pick_may_change"]
    assert said(a, "no_pick_no_value") == {"evaluated": 4, "no_value": 2, "odds": 1, "market": 1, "other": 0}
    assert a["answered"] is True and set(a["terms"]) == {"pick", "value", "forecast", "odds"}

    played = new_match(world, seed, 5, -2)
    p = ask(c, "match", played, "no_pick")
    assert says(p) == ["no_pick_published", "pick_rule", "no_pick_past"] and p["links"] == ["transparency"]
    assert c.get("/api/v1/explain", params={"entity": "match", "id": 999_999_999, "intent": "no_pick"}).status_code == 404


# ── a pick ────────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_what_can_go_wrong_with_a_pick(world: World, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    c = client(world.db)
    a = ask(c, "pick", world.picks["A"], "risks")
    assert says(a)[:2] == ["pick_probability", "pick_interval"] and says(a)[-1] == "risks_incomplete"
    assert said(a, "pick_probability") == {"p": 0.5} and said(a, "pick_interval") == {"low": 0.45, "high": 0.55}
    assert "fact:no_context_yet" in says(a), "the reading's risks, as the pick's explanation gives them"
    assert "pick_review_risks" not in says(a), "the review is not applied: nothing it said is shown"
    assert a["links"] == ["why_pick"] and set(a["terms"]) == {"probability", "range", "pick"}
    assert says(ask(c, "pick", world.picks["K"], "risks"))[-1] == "pick_started"
    world.enforce(monkeypatch)
    rejected = ask(client(world.db), "pick", world.picks["C"], "risks")
    assert said(rejected, "pick_review_risks") == {"risks": ["En contra (REJECT)"]}, "applied: the review's own risks"


def test_why_caution_answers_every_state(world: World, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    c = client(world.db)
    pending = ask(c, "pick", world.picks["A"], "caution")
    assert says(pending) == ["caution_none_pending", "caution_what"]
    assert said(pending, "caution_none_pending") == {"status": "RECOMMENDED"}
    assert says(ask(c, "pick", world.picks["E"], "caution"))[0] == "caution_no_value"
    world.enforce(monkeypatch)
    c = client(world.db)
    first = {name: says(ask(c, "pick", world.picks[name], "caution"))[0] for name in "ACD"}
    assert first == {"A": "caution_none_approved", "C": "caution_rejected", "D": "caution_none_not_reviewed"}
    downgraded = ask(c, "pick", world.picks["B"], "caution")
    assert says(downgraded) == ["caution_downgraded", "pick_review_risks", "caution_what"]
    assert said(downgraded, "caution_downgraded") == {"status": "CAUTION"}
    assert said(downgraded, "pick_review_risks") == {"risks": ["En contra (DOWNGRADE)"]}


def test_an_evaluation_pick_is_the_owners_preview_only(world: World) -> None:  # noqa: F811
    shadow = world.picks["S"]
    user, owner = client(world.db), client(world.db, "SUPER_ADMIN")
    params = {"entity": "pick", "id": shadow, "intent": "caution"}
    assert user.get("/api/v1/explain", params=params).status_code == 404, "a reader never learns it exists"
    assert owner.get("/api/v1/explain", params=params).status_code == 404, "without the preview, a reader's answer"
    assert user.get("/api/v1/explain", params={**params, "preview": "shadow"}).status_code == 403
    preview = ask(owner, "pick", shadow, "caution", preview="shadow")
    assert says(preview) == ["caution_evaluation", "caution_what"]


# ── «¿Por qué baja la probabilidad de mi parlay?» ─────────────────────────────────────────────────────────────────────


def test_every_leg_must_win_and_the_numbers_are_the_slips_own(world: World) -> None:  # noqa: F811
    c = client(world.db)
    one = slip(c, [leg(world, "A")])
    assert says(one) == ["parlay_single", "parlay_leg"] and one["answered"] is True
    first = said(one, "parlay_leg")
    assert {k: first[k] for k in ("leg", "market", "selection", "line", "p", "source")} == {
        "leg": 1, "market": "1X2", "selection": "Home", "line": 0.0, "p": 0.5, "source": "model"}
    assert first["home"] and first["away"]

    legs = [leg(world, name) for name in "ABCDE"]
    five = slip(c, legs)
    assert says(five) == ["parlay_all_win", *["parlay_leg"] * 5, "parlay_product", "parlay_related", "parlay_shrinks",
                          "parlay_very_unlikely"]
    assert said(five, "parlay_all_win") == {"legs": 5}
    product = said(five, "parlay_product")
    assert product["probabilities"] == [0.5] * 5 and product["p"] == round(math.prod(product["probabilities"]), 6)
    related = said(five, "parlay_related")
    assert related["level"] == "high" and set(related["reasons"]) == {"shared_team", "same_competition_day"}, \
        "related legs, and no measure of how much: the estimate is the product, said so"
    check = c.post("/api/v1/me/parlays/validate", json={"legs": legs}).json()["data"]
    assert [float(x["p_used"]) for x in check["legs"]] == product["probabilities"], "the slip's own probabilities"
    assert float(check["estimated_probability"]) == product["p"]
    assert said(five, "parlay_very_unlikely") == {"p": float(check["fair_probability"])}, "the slip's warning, its number"


def test_legs_whose_dependence_was_measured_adjust_the_estimate(world: World) -> None:  # noqa: F811
    world.db.execute("INSERT INTO ai.correlation_estimates (estimated_at, scope, market, rho, se, n_groups, n_matches, "
                     "window_from, window_to, version) VALUES (%s, 'same_competition_day', 'home_win', 0.12, 0.03, 50, 120, "
                     "%s, %s, 'corr-test')", (NOW - timedelta(days=1), (NOW - timedelta(days=90)).date(), NOW.date()))
    legs = [leg(world, "A"), leg(world, "B")]
    c = client(world.db)
    answer = slip(c, legs)
    assert "parlay_related" not in says(answer)
    dependency = said(answer, "parlay_dependency")
    check = c.post("/api/v1/me/parlays/validate", json={"legs": legs}).json()["data"]
    assert dependency["p"] == float(check["estimated_probability"]) != said(answer, "parlay_product")["p"]
    assert dependency["level"] == "high" and "measured_dependence" in dependency["reasons"]


def test_a_leg_without_a_probability_and_a_broken_rule_are_said_never_guessed(world: World) -> None:  # noqa: F811
    c = client(world.db)
    missing = slip(c, [leg(world, "A"), leg(world, "B", "Over", "OU", "2.5")])
    assert missing["answered"] is False and says(missing)[-1] == "parlay_leg_missing"
    assert said(missing, "parlay_leg_missing") == {"legs": ["2"]}
    assert [x["p"] for x in every(missing, "parlay_leg")] == [0.5, None]
    assert "parlay_product" not in says(missing), "no product without every leg's probability"

    same = slip(c, [leg(world, "A"), leg(world, "A", "Draw")])
    assert same["answered"] is False and says(same) == ["parlay_invalid", "parlay_issue"]
    assert said(same, "parlay_issue") == {"code": "same_fixture", "leg": 2, "with": 1}
    started = slip(c, [leg(world, "K"), leg(world, "A")])
    assert said(started, "parlay_issue") == {"code": "started", "leg": 1, "with": None}
    assert c.post("/api/v1/explain/parlay", json={"legs": []}).status_code == 422
    assert c.post("/api/v1/explain/parlay", json={"legs": [leg(world, "A")], "name": "x"}).status_code == 422


# ── the door ──────────────────────────────────────────────────────────────────────────────────────────────────────────


def test_the_switch_the_questions_of_each_place_and_the_limit(world: World, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    c = client(world.db)
    assert c.get("/api/v1/auth/me").json()["explain"] is True, "on while the line is absent"
    monkeypatch.setenv("FBI_EXPLAIN", "0")
    off = c.get("/api/v1/explain", params={"entity": "match", "id": world.fixtures["A"], "intent": "no_pick"})
    assert off.status_code == 404 and off.json()["error"]["code"] == "explain_off"
    assert c.post("/api/v1/explain/parlay", json={"legs": [leg(world, "A")]}).status_code == 404
    assert c.get("/api/v1/auth/me").json()["explain"] is False
    monkeypatch.setenv("FBI_EXPLAIN", "maybe")
    assert c.get("/api/v1/auth/me").json()["explain"] is False, "a value it cannot read is off"
    monkeypatch.delenv("FBI_EXPLAIN")

    wrong = c.get("/api/v1/explain", params={"entity": "pick", "id": world.picks["A"], "intent": "forecast"})
    assert wrong.status_code == 422 and wrong.json()["error"]["code"] == "unknown_question"
    assert c.get("/api/v1/explain", params={"entity": "match", "id": 1, "intent": "anything"}).status_code == 422
    assert c.get("/api/v1/explain", params={"entity": "parlay", "id": 1, "intent": "probability"}).status_code == 422

    explain_router.LIMIT.reset()
    for _ in range(30):
        assert c.get("/api/v1/explain", params={"entity": "pick", "id": world.picks["A"], "intent": "caution"}).status_code == 200
    stopped = c.get("/api/v1/explain", params={"entity": "pick", "id": world.picks["A"], "intent": "caution"})
    assert stopped.status_code == 429 and stopped.json()["error"]["code"] == "rate_limited"
    assert stopped.headers["retry-after"] == "30"
    assert client(world.db, user_id=2).get(
        "/api/v1/explain", params={"entity": "pick", "id": world.picks["A"], "intent": "caution"}).status_code == 200, \
        "the limit is each account's"


def test_no_answer_reaches_the_outside_world(world: World, doors_shut: list[str]) -> None:  # noqa: F811
    c = client(world.db)
    for entity, name, intent in (("match", "A", "no_pick"), ("match", "S", "no_pick"), ("match", "A", "forecast"),
                                 ("match", "A", "risks"), ("pick", "A", "risks"), ("pick", "B", "caution")):
        item = world.fixtures[name] if entity == "match" else world.picks[name]
        ask(c, entity, item, intent)
    slip(c, [leg(world, name) for name in "ABC"])
    assert doors_shut == []


def test_nothing_is_written(world: World) -> None:  # noqa: F811
    def counts() -> tuple[int, ...]:
        return tuple(int(scalar(world.db.execute(f"SELECT count(*) FROM {table}"))) for table in (
            "picks.picks", "picks.pick_events", "picks.pick_candidates", "picks.daily_sets", "picks.daily_set_items",
            "ai.pick_reviews", "picks.user_picks", "picks.user_parlays", "customer.product_events", "customer.feedback"))

    before = counts()
    c = client(world.db)
    ask(c, "match", world.fixtures["S"], "no_pick")
    ask(c, "pick", world.picks["B"], "caution")
    slip(c, [leg(world, name) for name in "ABCDE"])
    assert counts() == before
    assert Decimal(str(said(ask(c, "pick", world.picks["A"], "risks"), "pick_probability")["p"])) == Decimal("0.5")
