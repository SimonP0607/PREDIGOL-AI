"""REVIEW PREDIGOL (11 Oct 2026), B1/B4: daily-set-v4 on a built world (``test_daily_records``) - a price above 3.00
stops at the risk stage, a selection PrediGol Intelligence never reviewed stops at the context stage, what the AI read
(its decision and the outside evidence by status) is frozen with each item, and the admin's funnel says it all."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import psycopg
import pytest

from fbi.api.services.selection import selection_funnel
from fbi.picks.daily import RULE_VERSION, build_daily_sets, product_day

from .conftest import Seed
from .test_daily_records import AT, World


def _long_price(db: psycopg.Connection[Any], w: World, name: str) -> None:
    """A newer price of 3.10 for the match's home win, the market at 33 %: value, no outlier - above the risk cap."""
    for sel, p_fair, odds in (("Home", "0.33", "3.10"), ("Draw", "0.30", "3.20"), ("Away", "0.37", "2.60")):
        db.execute("INSERT INTO market.market_consensus (fixture_id,market_key,selection,line,as_of,devig_method,p_fair,"
                   "n_bookmakers,overround,best_odds,best_bookmaker_id) VALUES (%s,'1X2',%s,0,%s,'shin',%s,5,0.05,%s,%s)",
                   (w.fixtures[name], sel, AT - timedelta(minutes=5), p_fair, odds, w.seed.bookmaker_id))


def _evidence(db: psycopg.Connection[Any], w: World, name: str, status: str) -> None:
    db.execute(
        "INSERT INTO ai.evidence (fixture_id, kind, claim, origin, source_name, source_url, source_domain, source_tier, "
        "retrieved_at, story_key, content_hash, confidence, relevance, status, status_reason, status_changed_at) VALUES "
        "(%s, 'injury', 'El portero titular no juega por lesión.', 'web', 'Liga', 'https://dimayor.com.co/x', "
        "'dimayor.com.co', 'competition', %s, %s, %s, 0.9, 0.8, %s, 'test', %s)",
        (w.fixtures[name], AT - timedelta(hours=1), f"story-{name}-{status}", f"hash-{name}-{status}", status,
         AT - timedelta(hours=1)))


def _items(db: psycopg.Connection[Any], source: str) -> dict[int, dict[str, Any]]:
    return {r[0]: r[1] for r in db.execute(
        "SELECT i.fixture_id, i.inputs FROM picks.daily_set_items i JOIN picks.daily_sets s ON s.id = i.set_id "
        "WHERE s.source = %s AND s.day = %s", (source, product_day(AT))).fetchall()}


def test_risk_and_context_stages_and_what_is_frozen(db: psycopg.Connection[Any], seed: Seed,
                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FBI_AI_MODE", "shadow")
    w = World(db, seed)
    _long_price(db, w, "F1")
    for name in ("F1", "F2", "F3", "F5", "F6"):  # F4 is never reviewed
        w.review(name)
    _evidence(db, w, "F3", "CONFIRMED")
    _evidence(db, w, "F3", "RUMOR")
    build_daily_sets(db, at=AT)
    qualified = _items(db, "qualified")
    assert set(qualified) == {w.fixtures["F3"]}, "F1 priced at 3.10 stops at the risk stage; F2 has no growth"
    item = qualified[w.fixtures["F3"]]
    assert item["rule_version"] == RULE_VERSION == "daily-set-v4"
    assert item["risk"] == {"version": "risk-v1", "max_odds": "3.00"} and item["context"] == "context-v1"
    assert item["ai"]["decision"] == "APPROVE" and item["ai"]["evidence"] == {"CONFIRMED": 1, "RUMOR": 1}
    evaluation = _items(db, "evaluation")
    assert w.fixtures["F4"] not in evaluation, "never reviewed by PrediGol Intelligence: not a pick of the day"
    assert {w.fixtures["F3"], w.fixtures["F5"], w.fixtures["F6"]} <= set(evaluation)

    funnel = selection_funnel(db, source="evaluation", at=AT).data
    assert funnel is not None and funnel.rule_version == "daily-set-v4" and funnel.max_odds is not None
    stages = {s.key: s for s in funnel.stages}
    assert stages["risk"].reasons == {"odds_above_cap": 1}
    assert stages["context"].reasons == {"not_reviewed": 1}
    assert stages["value"].reasons == {"no_pessimistic_growth": 1}
    assert stages["selection"].reasons == {"match_taken": stages["selection"].entered}, \
        "every match that passed is already in the day's set: nothing new to add"
    assert funnel.chosen == [] and funnel.in_set == {str(product_day(AT)): len(evaluation)}
    near = {(i.fixture_id, i.stage, i.reason) for i in funnel.near}
    assert (w.fixtures["F1"], "risk", "odds_above_cap") in near and (w.fixtures["F4"], "context", "not_reviewed") in near
    f3 = next(i for i in funnel.near if i.fixture_id == w.fixtures["F3"])
    assert f3.evidence == {"CONFIRMED": 1, "RUMOR": 1} and f3.ai_decision == "APPROVE"


def test_with_the_ai_switched_off_there_is_no_review_to_require(db: psycopg.Connection[Any], seed: Seed,
                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FBI_AI_MODE", "off")
    w = World(db, seed)
    build_daily_sets(db, at=AT)
    qualified = _items(db, "qualified")
    assert set(qualified) == {w.fixtures["F1"], w.fixtures["F3"]}
    assert {i["context"] for i in qualified.values()} == {"ai_off"}, "the record says the context stage was off"
    funnel = selection_funnel(db, source="qualified", at=AT).data
    assert funnel is not None and funnel.context_version == "ai_off" and funnel.ai_mode == "off"


def test_the_admin_route_is_the_owners() -> None:
    from fastapi.testclient import TestClient

    from fbi.api.app import create_app

    from .signed_in import SAME_SITE, signed_in

    user = TestClient(signed_in(create_app(), "USER"), headers=SAME_SITE)
    assert user.get("/api/v1/admin/picks/funnel").status_code == 403
