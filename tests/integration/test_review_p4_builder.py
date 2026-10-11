"""REVIEW PREDIGOL (11 Oct 2026), point 15: the automatic parlay builder on a built world (``test_daily_records``) and
over HTTP. Without filters it is PrediGol's own daily parlay; the filters only narrow; a user builds from qualified
picks only, the owner's preview from shadow picks; nothing is stored."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from fbi.api.services.product import built_parlay
from fbi.core.clock import FrozenClock, SystemClock, set_clock
from fbi.core.config import reset_cache
from fbi.parlays.builder import Filters
from fbi.parlays.persist import build_parlays
from fbi.picks.daily import product_day

from .conftest import Seed
from .signed_in import SAME_SITE, signed_in
from .test_daily_records import AT, World


def _legs(db: psycopg.Connection[Any], source: str) -> list[int]:
    return [r[0] for r in db.execute(
        "SELECT l.pick_id FROM picks.parlay_legs l JOIN picks.parlays p ON p.id = l.parlay_id "
        "WHERE p.kind = 'daily' AND p.source = %s AND p.day = %s ORDER BY l.leg_no", (source, product_day(AT)))]


def test_without_filters_it_is_predigols_own_daily_parlay(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    w.review_all()
    build_parlays(db, at=AT)
    wide = Filters(hours=17, min_legs=2, max_legs=5)  # the product day's matches: F1-F6, not F7 (+30 h)
    for include_shadow, source in ((False, "qualified"), (True, "evaluation")):
        env = built_parlay(db, wide, include_shadow=include_shadow, at=AT)
        body = env.data
        assert body is not None and body.status == "ok", body
        assert [leg.pick_id for leg in body.legs] == _legs(db, source), f"{source}: the builder is the same rule"
        assert body.source == ("shadow_preview" if include_shadow else "qualified")
        assert body.parlay_rule == "parlay-v5" and body.rule_version == "builder-v2"
        assert body.combined_odds is not None and body.p_all_low is not None and body.expected_log_growth > 0
    user = built_parlay(db, wide, include_shadow=False, at=AT).data
    assert user is not None
    assert {leg.fixture_id for leg in user.legs} <= {w.fixtures["F1"], w.fixtures["F2"], w.fixtures["F3"]}, \
        "a user's parlay holds qualified picks only"
    leg = user.legs[0]
    assert leg.p_low <= leg.p_model and leg.n_bookmakers >= 3
    assert leg.fair_odds == (Decimal(1) / leg.p_market).quantize(Decimal("0.001"))
    assert leg.price_edge == (leg.odds * leg.p_market - 1).quantize(Decimal("0.0001"))
    assert user.funnel.passing == 3 and user.funnel.matches == 3, "F1-F3 pass the gate; the rule keeps two"
    assert [o.selections for o in user.competitions] == [3] and user.markets == ["1X2"]


def test_the_filters_narrow_and_an_empty_answer_says_why(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    w.review_all()
    owner = built_parlay(db, Filters(hours=24, min_legs=2, max_legs=5), include_shadow=True, at=AT).data
    assert owner is not None and len(owner.competitions) == 2
    league_b = next(o.competition.id for o in owner.competitions if o.competition.name == "Daily League B")
    only_b = built_parlay(db, Filters.of(hours=24, min_legs=2, max_legs=5, competitions=[league_b]),
                          include_shadow=True, at=AT).data
    assert only_b is not None and only_b.status == "ok"
    assert {leg.competition.id for leg in only_b.legs} == {league_b} and len(only_b.legs) == 2, \
        "two legs of one competition at most"
    user = built_parlay(db, Filters.of(hours=24, min_legs=2, max_legs=5, competitions=[league_b]),
                        include_shadow=False, at=AT).data
    assert user is not None and (user.status, user.reason, user.legs) == ("no_valid_parlay", "no_match", [])
    capped = built_parlay(db, Filters(hours=24, min_legs=2, max_legs=5, max_total_odds=Decimal("4")),
                          include_shadow=True, at=AT).data
    assert capped is not None and (capped.status, capped.reason) == ("no_valid_parlay", "total_odds_cap"), \
        "no two legs priced 2.10+ stay under 4.00"
    far = built_parlay(db, Filters(hours=24, min_legs=2, max_legs=5), include_shadow=False,
                       at=AT + timedelta(days=30)).data
    assert far is not None and far.reason == "no_candidates" and far.funnel.passing == 0
    assert db.execute("SELECT count(*) FROM picks.user_parlays").fetchone() == (0,), "nothing is stored"
    assert w.fixtures


@pytest.fixture()
def api(migrated_database: str) -> Iterator[None]:
    mp = pytest.MonkeyPatch()
    mp.setenv("FBI_DATABASE_URL", migrated_database.replace("postgresql://", "postgresql+psycopg://"))
    reset_cache()
    set_clock(FrozenClock(AT))
    yield
    set_clock(SystemClock())
    mp.undo()
    reset_cache()


def test_the_route_answers_and_checks_its_filters(api: None) -> None:
    from fbi.api.app import create_app

    user = TestClient(signed_in(create_app(), "USER"), headers=SAME_SITE)
    ok = user.get("/api/v1/parlays/build", params={"hours": 48, "min_legs": 2, "max_legs": 3,
                                                   "market": ["1X2", "OU"], "min_odds": "1.5"})
    assert ok.status_code == 200, ok.text
    body = ok.json()["data"]
    assert body["source"] == "qualified" and body["filters"]["markets"] == ["1X2", "OU"]
    assert body["filters"]["hours"] == 48 and body["status"] in ("ok", "no_valid_parlay")
    assert user.get("/api/v1/parlays/daily").status_code == 200, "the fixed parlays are still there"
    bad = user.get("/api/v1/parlays/build", params={"min_legs": 4, "max_legs": 3})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_filters"
    assert user.get("/api/v1/parlays/build", params={"market": "CORNERS"}).status_code == 422
    assert user.get("/api/v1/parlays/build", params={"hours": 100}).status_code == 422
    assert user.get("/api/v1/parlays/build", params={"min_odds": "3", "max_odds": "2"}).status_code == 422
    assert user.get("/api/v1/parlays/build", params={"preview": "shadow"}).status_code == 403
    owner = TestClient(signed_in(create_app(), "SUPER_ADMIN"), headers=SAME_SITE)
    preview = owner.get("/api/v1/parlays/build", params={"preview": "shadow"})
    assert preview.status_code == 200 and preview.json()["data"]["source"] == "shadow_preview"
