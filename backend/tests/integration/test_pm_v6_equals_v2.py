"""The ONE post-mortem (``pm-v6``) judges a selection only the AI looked at exactly as the first post-mortem by selection (``pm-v2``, now
frozen in ``fbi.ai.pick_postmortem``) did: the same class of a loss, the same verdict of the review, the same price, the same ten questions
answered the same way - over the same selections of the same world. The two writers share ``fbi.intel.pm_questions`` but read their facts
separately (``fbi.intel.pm_facts`` in batches, the frozen writer one selection at a time): this test is what holds those two readings together
until the frozen writer is deleted.

Eleven selections of six finished matches, one per class of a loss (all seven) and the wins around them. The transaction is rolled back
afterwards."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fbi.ai.config import AiSettings
from fbi.ai.pick_postmortem import run_pick_postmortems
from fbi.intel import postmortem

from .conftest import Seed
from .helpers import scalar
from .test_ai_decision_layer import Savepoints
from .test_daily_records import AT
from .test_postmortem_v6 import LATE, Pm

pytestmark = pytest.mark.integration

RESULTS = {"F1": (0, 2), "F2": (0, 1), "F3": (0, 1), "F4": (0, 1), "F5": (0, 1), "F6": (1, 0)}
Q = (("Home",), ("Draw",), ("Away",))


def lineup(pm: Pm, name: str, side: str, *, player: int, fetched_hours_after: float) -> None:
    pm.cur.execute("INSERT INTO core.fixture_lineups (fixture_id, team_side, source, formation, payload_hash, fetched_at) "
                   "VALUES (%s,%s,'api-football','4-3-3',%s,%s)",
                   (pm.f[name], side, pm.seed.payload_hash, AT + timedelta(hours=fetched_hours_after)))
    pm.cur.execute("INSERT INTO core.fixture_lineup_players (fixture_id, team_side, source, provider_player_id, player_name, shirt_number, "
                   "position, is_starter) VALUES (%s,%s,'api-football',%s,'Reported Out',9,'F',true)", (pm.f[name], side, player))


def report_out(pm: Pm, name: str, side: str, player: int) -> None:
    team = scalar(pm.db.execute(f"SELECT {side}_team_id FROM core.fixtures WHERE id = %s", (pm.f[name],)))
    pm.cur.execute(
        "INSERT INTO ai.evidence (fixture_id, team_id, provider_player_id, kind, claim, origin, source_name, source_tier, retrieved_at, "
        "story_key, content_hash, confidence, relevance, attributes, status, status_reason, status_changed_at) VALUES "
        "(%s,%s,%s,'injury','Reported Out: Missing Fixture','provider','Provider','official',%s,%s,%s,0.9,0.8,%s,'CONFIRMED','t',%s)",
        (pm.f[name], team, player, AT - timedelta(hours=1), f"story-{name}-{player}", f"hash-{name}-{player}", Jsonb({"assertion": "out"}),
         AT - timedelta(hours=1)))


def world(db: psycopg.Connection[Any], seed: Seed) -> Pm:
    pm = Pm(db, seed, results=RESULTS, scenarios=False)
    key_absence = pm.packet("F1", absences={"home": {"players": [{"key": True, "name": "Nine", "type": "Missing Fixture"}]}})
    unfit = pm.packet("F2", quality={"competition_score": {"class": "PRODUCT_ONLY"}})
    b, o = pm.book, pm.other
    changed = {"uncertainties": [{"code": "kickoff_changed"}]}
    noise = {"negative_evidence": [{"code": "edge_within_noise"}]}
    #            fixture market selection line  decision    odds   book p_model p_market packet        output
    plan = [("F1", "1X2", "Home", "0", "APPROVE", "2.40", o, "0.55", "0.46", key_absence, None),  # a known key absence, approved
            ("F2", "1X2", "Home", "0", "APPROVE", "2.30", b, "0.55", "0.46", unfit, None),  # data not fit for models
            ("F3", "1X2", "Home", "0", "APPROVE", "2.00", b, "0.50", "0.47", None, None),  # the same book's price moved against it
            ("F4", "1X2", "Home", "0", "APPROVE", "2.30", o, "0.60", "0.45", None, None),  # the model far above the close
            ("F5", "1X2", "Home", "0", "DOWNGRADE", "2.30", b, "0.45", "0.47", None, noise),  # a report that proved wrong
            ("F3", "1X2", "Draw", "0", "ABSTAIN", "3.40", b, "0.30", "0.28", None, None),  # a fair price that lost
            ("F6", "OU", "Over", "2.5", "REJECT", "1.90", b, "0.50", "0.50", None, None),  # no closing price at all
            ("F6", "1X2", "Away", "0", "APPROVE", "3.30", o, "0.30", "0.29", None, changed),  # the kick-off changed
            ("F1", "1X2", "Away", "0", "REJECT", "3.50", b, "0.30", "0.29", None, None),  # rejected, would have won
            ("F4", "1X2", "Away", "0", "APPROVE", "3.40", o, "0.35", "0.29", None, None),  # won, the model near the close
            ("F2", "OU", "Under", "2.5", "APPROVE", "1.80", b, "0.55", "0.52", None, None)]  # won, nothing to judge the price by
    for name, market, selection, line, decision, odds, book, p_model, p_market, packet, output in plan:
        pm.review(name, market, selection, line, decision=decision, odds=odds, book=book, p_model=p_model, p_market=p_market, packet=packet,
                  output=output)
        pm.w.day_pass(name, at=AT)
    pm.book_close("F3", b, "1X2", "Home", "0", "2.20")  # 2.00 against 2.20: -9 %
    lineup(pm, "F4", "home", player=401, fetched_hours_after=2)  # the line-ups came after the review
    lineup(pm, "F5", "away", player=501, fetched_hours_after=3)
    report_out(pm, "F5", "away", 501)  # reported out, started
    return pm


def rows(db: psycopg.Connection[Any], sql: str) -> dict[tuple[int, str, str, Decimal], dict[str, Any]]:
    with db.cursor(row_factory=dict_row) as cur:
        cur.execute(sql)
        return {(int(r["fixture_id"]), r["market_key"], r["selection"], Decimal(r["line"])): dict(r) for r in cur.fetchall()}


def test_the_one_post_mortem_judges_what_only_the_ai_looked_at_as_the_first_post_mortem_by_selection_did(db: psycopg.Connection[Any],
                                                                                                       seed: Seed) -> None:
    pm = world(db, seed)
    legacy = run_pick_postmortems(Savepoints(db), at=LATE, settings=AiSettings(mode="shadow"))  # type: ignore[arg-type]
    assert legacy.errors == [] and legacy.studied == 11
    study = postmortem.study(db, at=LATE)
    assert study.errors == [] and study.studied == 11 and study.by_source == {"ai": 11}

    old = rows(db, "SELECT * FROM ai.pick_postmortems")
    new = rows(db, "SELECT * FROM intel.postmortems WHERE market_key IS NOT NULL")
    assert set(old) == set(new) and len(new) == 11, "the same selections"
    classes = set()
    for key, was in old.items():
        now = new[key]
        label = f"{key}"
        assert now["loss_class"] == was["classification"], label
        assert now["review_verdict"] == was["verdict"], label
        assert (now["review_id"], now["review_decision"], sorted(now["roles"])) == (was["review_id"], was["decision"], sorted(was["roles"])), label
        assert (now["odds"], now["close_odds"], now["p_model"], now["p_market"]) == (was["odds"], was["close_odds"], was["p_model"],
                                                                                     was["p_market"]), label
        assert now["price_move"] == was["clv"], f"{label}: the old column holds the PRICE MOVE"
        assert {k: v for k, v in now["answers"].items() if k in was["answers"]} == was["answers"], f"{label}: the ten questions, answered alike"
        assert now["outcome"] == {"win": "won", "loss": "lost"}[was["settled"]], label
        if now["loss_class"] is not None:
            classes.add(now["loss_class"])
    assert classes == {"MODEL_ERROR", "CONTEXT_ERROR", "DATA_ERROR", "MARKET_ERROR", "EXECUTION_ERROR", "NORMAL_VARIANCE", "UNKNOWN"}, \
        "the world has one loss of every class: the test compares the whole classification"
    assert len(pm.f) == 7


def test_the_two_writers_leave_one_memory_event_per_selection_not_two(db: psycopg.Connection[Any], seed: Seed) -> None:
    world(db, seed)
    run_pick_postmortems(Savepoints(db), at=LATE, settings=AiSettings(mode="shadow"))  # type: ignore[arg-type]
    before = scalar(db.execute("SELECT count(*) FROM ai.memory_events WHERE kind = 'pick_postmortem'"))
    assert before == 11
    postmortem.study(db, at=LATE)
    assert scalar(db.execute("SELECT count(*) FROM ai.memory_events WHERE kind = 'pick_postmortem'")) == 11, \
        "pm-v6 writes its row and finds the memory event of the same selection already there: patterns count it once"
