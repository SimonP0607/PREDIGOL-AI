"""REVIEW PREDIGOL (11 Oct 2026), B1/B4: the daily set (v5) on a built world (``test_daily_records``) - a price above
3.00 stops at the risk stage; at the context stage (context-v2) a match without the AI's first pass of its day stops,
and so does a selection PrediGol Intelligence never reviewed; the day's set waits for the AI to read the whole day;
what the AI read (its decision, the outside evidence by status, the day's pass, the web search) is frozen with each
item, and the admin's funnel says it all."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from fbi.api.services.selection import selection_funnel
from fbi.picks.daily import RULE_VERSION, build_daily_sets, day_ready, product_day

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
    for name in ("F1", "F2", "F5"):
        w.review(name)
    w.review("F3", day_pass=False)
    w.day_pass("F3", web=True)  # its first pass searched the web too
    w.day_pass("F4")  # read on its day, but its selection never reviewed
    w.review("F6", day_pass=False)  # reviewed, but its match never had the AI's pass of the day
    _evidence(db, w, "F3", "CONFIRMED")
    _evidence(db, w, "F3", "RUMOR")
    build_daily_sets(db, at=AT)
    qualified = _items(db, "qualified")
    assert set(qualified) == {w.fixtures["F3"]}, "F1 priced at 3.10 stops at the risk stage; F2 has no growth"
    item = qualified[w.fixtures["F3"]]
    assert item["rule_version"] == RULE_VERSION == "daily-set-v5"
    assert item["risk"] == {"version": "risk-v1", "max_odds": "3.00"} and item["context"] == "context-v2"
    assert item["ai"]["decision"] == "APPROVE" and item["ai"]["evidence"] == {"CONFIRMED": 1, "RUMOR": 1}
    assert item["ai"]["day_pass"] is True and item["ai"]["web_searched"] is True
    evaluation = _items(db, "evaluation")
    assert w.fixtures["F4"] not in evaluation, "never reviewed by PrediGol Intelligence: not a pick of the day"
    assert w.fixtures["F6"] not in evaluation, "no pass of the day (no news searched, no model read): not a pick"
    assert {w.fixtures["F3"], w.fixtures["F5"]} <= set(evaluation)
    assert evaluation[w.fixtures["F5"]]["ai"]["web_searched"] is False

    funnel = selection_funnel(db, source="evaluation", at=AT).data
    assert funnel is not None and funnel.rule_version == "daily-set-v5" and funnel.max_odds is not None
    assert funnel.context_version == "context-v2"
    stages = {s.key: s for s in funnel.stages}
    assert stages["risk"].reasons == {"odds_above_cap": 1}
    assert stages["context"].reasons == {"not_reviewed": 1, "no_day_pass": 1}
    assert stages["value"].reasons == {"no_pessimistic_growth": 1}
    assert stages["selection"].reasons == {"match_taken": stages["selection"].entered}, \
        "every match that passed is already in the day's set: nothing new to add"
    assert funnel.chosen == [] and funnel.in_set == {str(product_day(AT)): len(evaluation)}
    near = {(i.fixture_id, i.stage, i.reason) for i in funnel.near}
    assert (w.fixtures["F1"], "risk", "odds_above_cap") in near and (w.fixtures["F4"], "context", "not_reviewed") in near
    assert (w.fixtures["F6"], "context", "no_day_pass") in near
    f3 = next(i for i in funnel.near if i.fixture_id == w.fixtures["F3"])
    assert f3.evidence == {"CONFIRMED": 1, "RUMOR": 1} and f3.ai_decision == "APPROVE"
    assert f3.day_pass and f3.web_searched and funnel.days_ready == [product_day(AT)]
    f6 = next(i for i in funnel.near if i.fixture_id == w.fixtures["F6"])
    assert not f6.day_pass and not f6.web_searched


def test_the_days_set_waits_until_the_ai_has_read_the_day(db: psycopg.Connection[Any], seed: Seed,
                                                          monkeypatch: pytest.MonkeyPatch) -> None:
    """At 05:00 Bogotá a first pass is still due (F1 has a market and no pass): nothing of the day is chosen yet, so
    the five are the best of the day, not the first five read. Once F1's pass is over, the day is ready."""
    monkeypatch.setenv("FBI_AI_MODE", "shadow")
    w = World(db, seed)
    early = datetime(2032, 8, 1, 10, tzinfo=UTC)  # 05:00 Bogotá
    w.price("F1", "2.30", early - timedelta(hours=1))
    w.review("F1", at=early - timedelta(minutes=20), day_pass=False)
    assert not day_ready(db, at=datetime(2032, 8, 1, 5, 3, tzinfo=UTC)), "00:03 Bogotá: the AI's day is not open"
    assert not day_ready(db, at=early), "F1's first pass is still due"
    build_daily_sets(db, at=early)
    assert _items(db, "evaluation") == {}
    funnel = selection_funnel(db, source="evaluation", at=early).data
    assert funnel is not None and dict({s.key: s for s in funnel.stages}["context"].reasons) == {"day_not_ready": 1}
    assert funnel.days_ready == []
    w.day_pass("F1", at=early - timedelta(minutes=5))
    assert day_ready(db, at=early), "no first pass due any more: the day is read"
    build_daily_sets(db, at=early)
    assert set(_items(db, "evaluation")) == {w.fixtures["F1"]}
    assert day_ready(db, at=AT), "07:00 Bogotá: from 06:00 the day is chosen with what has been read"


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
