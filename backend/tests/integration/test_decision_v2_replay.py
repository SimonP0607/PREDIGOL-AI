"""decision-v2 replayed against decision-v1 and decision-fam-v1 in a real database (``fbi.decision.replay``), on rows built the way the
layers build them: the layers decide (``decision.decide``, ``decision.select_day``, ``fd.decide_families``) and write their rows, then the
replay recomputes every one as of its moment and must agree - row by row, read-only, and the same twice.

Every test builds its own matches (``IntelWorld`` of tests/integration/test_intel.py, the scene of tests/integration/test_familydecisions_decide.py):
nothing here reads or moves the session's shared seed match."""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any

import psycopg
import pytest

from fbi.ai.calendar import local_day
from fbi.decision import replay
from fbi.families import forecast
from fbi.familydecisions import decide as fd
from fbi.intel import calibration, decision
from fbi.intel.calibration import GateVerdict, WalkForward
from tests.integration.conftest import Seed

from .knowledge_world import World
from .test_families_forecast import AT as FAMILY_AT
from .test_familydecisions_decide import NOW, scene
from .test_intel import AT, IntelWorld

pytestmark = pytest.mark.integration

WRITES_SQL = "SELECT COALESCE(sum(n_tup_ins + n_tup_upd + n_tup_del), 0) FROM pg_stat_xact_user_tables"
"""What this transaction has written so far, by every table: a read-only replay leaves it as it was."""


@pytest.fixture(autouse=True)
def small_window(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(forecast, "MIN_DISPERSION_MATCHES", 40)


def champion(db: psycopg.Connection[Any], market: str, *, edge: bool) -> None:
    """A champion identity calibrator for (market, dixon_coles) and the market's edge verdict, a day before the moment."""
    known = AT - timedelta(days=1)
    cid = calibration.store_fit(db, market=market, model="dixon_coles", method="identity", params={}, known_at=known, fitted_at=known,
                                train=[], wf=WalkForward("identity"), verdict=GateVerdict(True, edge, {}))
    calibration.promote(db, at=known, entity="calibrator", market=market, model="dixon_coles", entity_id=cid, from_role=None,
                        to_role="CHAMPION", gate_version=calibration.GATE_VERSION, criteria={}, reason="test champion for the replay")
    calibration.promote(db, at=known, entity="market_edge", market=market, model="dixon_coles", entity_id=cid, from_role=None,
                        to_role="VALIDATED" if edge else "NOT_VALIDATED", gate_version=calibration.EDGE_GATE_VERSION, criteria={},
                        reason="test edge verdict for the replay")


def core_scene(db: psycopg.Connection[Any], seed: Seed) -> tuple[IntelWorld, int, int]:
    """Two matches with the pipeline's picks, priced: approvals that correlate, a market with no calibrator, a value below the floor, a
    market whose edge is not validated and a stale price."""
    w = IntelWorld(db, seed)
    champion(db, "OU", edge=True)
    champion(db, "1X2", edge=False)
    a, b = w.fixture(AT + timedelta(hours=5)), w.fixture(AT + timedelta(hours=8))
    made = AT - timedelta(hours=1)
    for fid, market, selection, line, p, fair, odds, as_of in (
            (a, "OU", "Over", "2.5", 0.60, 0.48, 2.05, AT - timedelta(minutes=20)),     # approved, a parlay candidate
            (a, "OU", "Under", "3.5", 0.585, 0.565, 1.76, AT - timedelta(minutes=20)),  # approved too, with less value: the lower score
            (a, "BTTS", "Yes", "0", 0.58, 0.50, 2.02, AT - timedelta(minutes=20)),      # no calibrator: abstain
            (a, "OU", "Over", "3.5", 0.30, 0.38, 2.50, AT - timedelta(minutes=20)),     # below the value floor: rejected
            (b, "1X2", "Home", "0", 0.55, 0.45, 2.15, AT - timedelta(minutes=20)),      # no validated edge: abstain
            (b, "OU", "Over", "2.5", 0.60, 0.48, 2.05, AT - timedelta(hours=4))):       # a price of four hours ago: watch
        w.pick(fid, market, selection, line, p_model=p, p_market=fair, odds=odds, created=made)
        w.consensus(fid, market, selection, line, p_fair=fair, best=odds, as_of=as_of)
    return w, a, b


def writes(db: psycopg.Connection[Any]) -> int:
    row = db.execute(WRITES_SQL).fetchone()
    assert row is not None
    return int(row[0])


def test_decision_v2_agrees_with_decision_v1_on_every_row_of_the_day(db: psycopg.Connection[Any], seed: Seed) -> None:
    w, a, b = core_scene(db, seed)
    _, first = decision.decide(db, at=AT)
    scores = {e.key[1:3]: e.score.total for e in first if e.key[0] == a and e.score is not None and e.state in decision.APPROVED | {"CAUTELA"}}
    assert scores[("OU", "Over")] > scores[("OU", "Under")], (
        "the two approvals of the match must not tie: decision-v1 breaks a tie on the order of its rows, which no query fixes")
    assert {(e.key[0], e.key[1], e.key[2], str(e.key[3])): e.state for e in first} == {
        (a, "OU", "Over", "2.50"): "CANDIDATO_PARLAY", (a, "OU", "Under", "3.50"): "CAUTELA", (a, "BTTS", "Yes", "0.00"): "INVESTIGACION",
        (a, "OU", "Over", "3.50"): "RECHAZADO", (b, "1X2", "Home", "0.00"): "INVESTIGACION", (b, "OU", "Over", "2.50"): "INVESTIGACION"}
    later = AT + timedelta(minutes=30)
    w.consensus(a, "OU", "Over", "2.5", p_fair=0.48, best=2.15, as_of=later - timedelta(minutes=5))  # the price moved: a new row
    decision.decide(db, at=later)
    decision.select_day(db, at=later, ready=True)

    before = writes(db)
    out = replay.replay_day(db, day=local_day(AT))
    again = replay.replay_day(db, day=local_day(AT))
    assert writes(db) == before, "the replay wrote nothing"
    assert json.dumps(out, default=str, sort_keys=True) == json.dumps(again, default=str, sort_keys=True), "and it is deterministic"

    v1_rows = db.execute("SELECT count(*) FROM intel.decisions WHERE decision_version = %s AND checkpoint <> 'selection'",
                         (decision.VERSION,)).fetchone()
    assert v1_rows is not None and out["agreement"] == {"n": v1_rows[0], "agree": v1_rows[0], "rate": 1.0, "unmatched": 0,
                                                     "correlation_ties": 0}, out["disagreements"]
    assert out["moments"] == 2 and out["skipped"]["selection_copies"] >= 1, "the picks of the day are labels, not decisions"
    core = out["families"]["core"]
    assert core["rate"] == 1.0 and core["unmatched"] == 0 and not out["disagreements"]
    assert set(core["confusion"]) == {"RECOMMENDED", "CAUTION", "ABSTAIN", "REJECTED", "WATCH"}, core["confusion"]
    assert core["labels"]["n"] >= 1 and core["labels"]["agree"] == core["labels"]["n"]
    assert core["checkpoints"]["agree"] == core["checkpoints"]["n"]
    assert all(out["families"][f]["n"] == 0 for f in ("CORNERS", "CARDS", "YELLOW", "GOALS_HALF"))


def test_the_new_inputs_change_nothing_when_there_is_nothing_to_say(db: psycopg.Connection[Any], seed: Seed) -> None:
    """With no Council verdict stored and no captured series, the Council's adjustment and the market's signals leave every state as it was."""
    core_scene(db, seed)
    decision.decide(db, at=AT)
    plain = replay.replay_day(db, day=local_day(AT))
    with_inputs = replay.replay_day(db, day=local_day(AT), council="ma-v1", signals=True)
    assert with_inputs["inputs"]["council"] == "ma-v1" and with_inputs["inputs"]["signals"] is True
    assert with_inputs["agreement"] == plain["agreement"] and plain["agreement"]["rate"] == 1.0
    with pytest.raises(ValueError, match="council"):
        replay.replay_day(db, day=local_day(AT), council="cs-v1")


def test_measuring_against_the_common_view_changes_no_decision_and_writes_nothing(db: psycopg.Connection[Any], seed: Seed) -> None:
    """``view=True`` only adds a measurement (plan PICKS, F3): the agreement is what it was, the report says how many rows had a reading, and the
    database is as it was."""
    core_scene(db, seed)
    decision.decide(db, at=AT)
    plain = replay.replay_day(db, day=local_day(AT))
    before = writes(db)
    measured = replay.replay_day(db, day=local_day(AT), view=True)
    assert writes(db) == before
    assert "common_view" not in plain and measured["inputs"]["view"] is True
    assert measured["agreement"] == plain["agreement"] and measured["disagreements"] == plain["disagreements"]
    c = measured["common_view"]
    assert c["rows"] == measured["rows"] - measured["skipped"]["selection_copies"] - measured["skipped"]["unclaimed"]
    assert c["with_view"] <= c["rows"] and c["with_v1_probability"] <= c["with_view"] and c["within_tolerance"] <= c["with_v1_probability"]
    assert set(c["causes"]) == set(replay.CAUSES)


def test_decision_v2_agrees_with_decision_fam_v1_on_a_familys_rows(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = World(db, seed)
    fid, market, (over, _) = scene(db, w)
    assert fd.decide_families(db, at=NOW)[0].written == 1
    [book] = w.books(4)[3:]
    market.quote(book, 9.00, 1.10, FAMILY_AT + timedelta(hours=2))  # a fourth book with an absurd price, an hour later
    market.read(FAMILY_AT + timedelta(hours=2, minutes=5))
    assert fd.decide_families(db, at=FAMILY_AT + timedelta(hours=3))[0].written == 1
    states = [r[0] for r in db.execute("SELECT state FROM intel.decisions WHERE fixture_id = %s ORDER BY known_at", (fid,)).fetchall()]
    assert states == ["INVESTIGACION", "RECHAZADO"]

    before = writes(db)
    out = replay.replay_day(db, day=local_day(NOW))
    assert writes(db) == before
    corners = out["families"]["CORNERS"]
    assert (corners["n"], corners["agree"], corners["unmatched"]) == (2, 2, 0), out["disagreements"] or out["unmatched"]
    assert corners["confusion"] == {"ABSTAIN": {"ABSTAIN": 1}, "REJECTED": {"REJECTED": 1}}
    assert out["families"]["core"]["n"] == 0 and out["moments"] == 2
    assert json.dumps(out, default=str, sort_keys=True) == json.dumps(replay.replay_day(db, day=local_day(NOW)), default=str, sort_keys=True)
    _ = over
