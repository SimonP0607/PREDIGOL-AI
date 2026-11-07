"""IA-014: the Statistics Agent is asked about the corners and the cards the FAMILIES decided (``decision-fam-v1``), as of the moment of the pass.

The defect, measured in production on 7 Nov 2026: with ``FBI_AI_AGENTS=match,council,stats`` the agent ran 0 times, every pass writing
``model_status.stats.note = 'no_count_to_assess'``, because the pass named its candidates from the reviews of production alone (``ai.pick_reviews`` of
``rules``: the picks of goals and result), and no corner or card is ever there. The families' decisions are where those candidates live. What is
shown here, on a match production reviewed on goals and result only (its own decisions, written by the test, inside the test's transaction):

* the old derivation names no count, and the pass now asks the agent about the full-time counts of the families, by the names after goals and result;
* strictly as of the pass: a decision written after the moment of the package, a decision of the pipeline's layer, a half, the yellow cards and the
  goals of a half are never candidates; the newest decision of each market is the one read;
* the names of goals and result, and every request and key of the Match Agent, are those of a pass with no family decision at all;
* the leak rules of the shadow stay clean, and the state of the pass says which decisions it read, so that what was asked is derived again;
* nothing of production moves: decisions, picks and the reviews of production are as they were."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb

from fbi.ai import contra, orchestrator, orchestrator_store, prompts
from fbi.ai import package as mcp_package
from fbi.ai.agents import match, stats
from fbi.ai.agents.common import name_with_counts
from fbi.ai.contracts.assessment import CANDIDATES_MAX
from fbi.core.decision_versions import DECISION_CORE, DECISION_FAMILIES
from fbi.core.version import model_code_version
from fbi.intel import leakage
from tests.integration.conftest import Seed
from tests.integration.orchestrator_world import RUN, Gear, World, assign, provider, settings, world
from tests.integration.test_orchestrator import go, reviews_of, rows
from tests.integration.test_slice_leak_audit import AT

pytestmark = pytest.mark.integration

D = Decimal
H = timedelta(hours=1)
ON = ("match", "council", "stats")
ENGINES = ("ma-v1", "ma-v1-h", "cs-v1")


@pytest.fixture(autouse=True)
def clean_memory() -> None:
    orchestrator._failed.clear()


def on(**over: Any) -> Any:
    return settings(agents=ON, **over)


def decide(db: psycopg.Connection[Any], seed: Seed, fixture: int, market: str, selection: str, line: str, p: str, odds: str, *,
           known_at: datetime, version: str = DECISION_FAMILIES, state: str = "INVESTIGACION", model: str = "family-corners_ft") -> int:
    """A decision as ``fbi.familydecisions.decide`` writes one (the columns the orchestrator reads), with a price captured by its moment."""
    kickoff = db.execute("SELECT kickoff_at FROM core.fixtures WHERE id = %s", (fixture,)).fetchone()
    assert kickoff is not None
    p_market = D(p) - D("0.06")
    row = db.execute(
        "INSERT INTO intel.decisions (decision_version, known_at, checkpoint, fixture_id, kickoff_at, market_key, selection, line, model_name, odds, "
        "bookmaker_id, price_at, n_bookmakers, p_model, p_low, p_high, p_push, p_market, ev_raw, filters, state, reasons, context_status, input_hash) "
        "VALUES (%s, %s, 'T-24', %s, %s, %s, %s, %s, %s, %s, %s, %s, 3, %s, NULL, NULL, 0, %s, %s, %s, %s, %s, 'LIMITED', %s) RETURNING id",
        (version, known_at, fixture, kickoff[0], market, selection, D(line), model, D(odds), seed.bookmaker_id, known_at - timedelta(minutes=5),
         D(p), p_market, (D(p) * D(odds) - 1).quantize(D("0.000001")), Jsonb([]), state, ["family_research"],
         f"t-{market}-{selection}-{line}-{known_at.isoformat()}-{version}"),
    ).fetchone()
    assert row is not None
    return int(row[0])


def counted(db: psycopg.Connection[Any], seed: Seed) -> tuple[World, list[int]]:
    """Goals and result reviewed by production; the corners (total and who has more) and the cards decided by the families before the pass."""
    w = world(db, seed)
    assign(db, w.fixture)
    ids = [
        decide(db, seed, w.fixture, "CORNERS_OU", "Over", "9.5", "0.58", "1.90", known_at=AT - 2 * H),
        decide(db, seed, w.fixture, "CORNERS_1X2", "Home", "0", "0.52", "2.10", known_at=AT - 3 * H),
        decide(db, seed, w.fixture, "CARDS_OU", "Over", "4.5", "0.55", "1.95", known_at=AT - H, model="family-cards_lines_ft"),
    ]
    return w, ids


def stats_requests(pv: Any) -> list[Any]:
    return [r for r in pv.requests if r.system == prompts.STATS_ASSESS_SYSTEM]


def asked_of(request: Any) -> dict[str, Any]:
    return dict(json.loads(request.user.split("\n")[1]))


def shadow_state(db: psycopg.Connection[Any], fixture: int) -> dict[str, Any]:
    [state] = rows(db, "SELECT * FROM ai.match_runs WHERE fixture_id = %s AND run_kind = 'shadow'", fixture)
    return state


def work_of(w: World) -> orchestrator_store.Work:
    [x] = rows(db_of(w), "SELECT fixture_id, pass AS pass_kind, packet_id, finished_at FROM ai.fixture_passes WHERE fixture_id = %s", w.fixture)
    kickoff = rows(db_of(w), "SELECT kickoff_at FROM core.fixtures WHERE id = %s", w.fixture)[0]["kickoff_at"]
    return orchestrator_store.Work(w.fixture, x["pass_kind"], int(x["packet_id"]), AT, kickoff, x["finished_at"])


def db_of(w: World) -> psycopg.Connection[Any]:
    return w.db


def production(db: psycopg.Connection[Any], fixture: int) -> dict[str, Any]:
    return {
        "decisions": rows(db, "SELECT id, state, known_at FROM intel.decisions WHERE fixture_id = %s ORDER BY id", fixture),
        "picks": rows(db, "SELECT count(*) AS n FROM picks.picks")[0]["n"],
        "rules": rows(db, "SELECT id, decision FROM ai.pick_reviews WHERE fixture_id = %s AND engine = 'rules' ORDER BY id", fixture),
    }


# ── the defect, and the fix ─────────────────────────────────────────────────────────────────────────────────────

def test_the_counts_of_the_families_reach_the_agent_that_production_reviews_never_had(db: psycopg.Connection[Any], seed: Seed) -> None:
    w, ids = counted(db, seed)
    before = production(db, w.fixture)

    old = name_with_counts(orchestrator_store.reviewed(db, work_of(w)).candidates)
    assert stats.asked_keys(old) == (), "the defect: named from the reviews of production alone, there is no count to ask about"

    pv = provider()
    report = go(db, Gear(db), pv, on())
    assert (report.ran, report.invalid, report.failed_open, report.not_run) == (1, 0, 0, 0)

    [request] = stats_requests(pv)
    ask = asked_of(request)
    got = [(c["candidate"], c["market"], c["selection"], c["line"]) for c in ask["candidates"]]
    assert got == [("c4", "CORNERS_1X2", "Home", "0"), ("c5", "CORNERS_OU", "Over", "9.5"), ("c6", "CARDS_OU", "Over", "4.5")]
    assert ask["settlement"] == {"CARDS": "cards_lines_ft@v1", "CORNERS": "corners_ft@v1"}
    corners = next(c for c in ask["candidates"] if c["candidate"] == "c5")
    assert (corners["p_model"], corners["odds"], corners["n_bookmakers"], corners["model"]) == ("0.58", "1.9", 3, "family-corners_ft")

    [task] = rows(db, "SELECT * FROM ai.agent_tasks WHERE fixture_id = %s AND agent = 'stats'", w.fixture)
    assert task["candidates"] == ["c4", "c5", "c6"] and task["state"] == "done"
    status = shadow_state(db, w.fixture)["model_status"]["stats"]
    assert status["asked"] == ["c4", "c5", "c6"] and status["note"] is None and status["naming"] == "cand-names-v2"
    assert status["counts"] == {"source": "fam-counts-v1", "decisions": sorted(ids)}

    shadow = reviews_of(db, w.fixture)
    assert len(shadow) == 6 * len(ENGINES)
    by_decision = {int(r["output"]["decision_id"]): r for r in shadow if r["engine"] == "ma-v1" and "decision_id" in r["output"]}
    assert set(by_decision) == set(ids)
    [corners_row] = [r for r in by_decision.values() if r["market_key"] == "CORNERS_OU"]
    assert corners_row["pick_id"] is None and corners_row["p_model"] == D("0.58") and corners_row["odds"] == D("1.9")
    assert all("decision_id" not in r["output"] for r in shadow if r["market_key"] in ("1X2", "OU")), "a selection production reviewed names no decision"

    assert production(db, w.fixture) == before, "the decisions, the picks and the reviews of production are as they were"


def test_only_what_was_decided_by_the_moment_of_the_pass_is_a_candidate(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, seed)
    assign(db, w.fixture)
    older = decide(db, seed, w.fixture, "CORNERS_OU", "Over", "8.5", "0.62", "1.70", known_at=AT - 5 * H)
    newest = decide(db, seed, w.fixture, "CORNERS_OU", "Over", "9.5", "0.58", "1.90", known_at=AT - 2 * H)
    edge = decide(db, seed, w.fixture, "CARDS_OU", "Over", "4.5", "0.55", "1.95", known_at=AT, model="family-cards_lines_ft")
    decide(db, seed, w.fixture, "CORNERS_OU", "Over", "10.5", "0.50", "2.30", known_at=AT + timedelta(seconds=1))
    decide(db, seed, w.fixture, "CARDS_1X2", "Away", "0", "0.40", "2.80", known_at=AT + H, model="family-cards_lines_ft")
    decide(db, seed, w.fixture, "CORNERS_OU", "Under", "11.5", "0.60", "1.90", known_at=AT - H, version=DECISION_CORE)
    decide(db, seed, w.fixture, "CORNERS_OU_1H", "Over", "4.5", "0.55", "1.95", known_at=AT - H)
    decide(db, seed, w.fixture, "YELLOW_OU", "Over", "3.5", "0.55", "1.95", known_at=AT - H, model="family-yellow_ft")
    decide(db, seed, w.fixture, "OU_1H", "Over", "0.5", "0.70", "1.50", known_at=AT - H, model="family-goals_halves")

    read = orchestrator_store.family_counts(db, w.fixture, at=AT)
    assert read.decision_ids == (edge, newest) and [(c.market_key, c.line) for c in read.candidates] == [("CARDS_OU", D("4.5")), ("CORNERS_OU", D("9.5"))]
    assert older not in read.decision_ids, "the newest decision of a market is the line the family stands on"
    assert all(c.pick_id is None and c.price_at is not None and c.price_at <= AT for c in read.candidates)

    pv = provider()
    go(db, Gear(db), pv, on())
    [request] = stats_requests(pv)
    lines = {(c["market"], c["line"]) for c in asked_of(request)["candidates"]}
    assert lines == {("CORNERS_OU", "9.5"), ("CARDS_OU", "4.5")}
    for later in ("10.5", "CARDS_1X2", "CORNERS_OU_1H", "YELLOW_OU", "OU_1H", "11.5"):
        assert later not in request.user.split("\n")[1], later


def test_the_names_of_goals_and_result_and_the_match_agent_do_not_move(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, seed)
    assign(db, w.fixture)

    def one(cfg: Any) -> tuple[dict[tuple[str, str], str], list[str], dict[tuple[str, str, str], str]]:
        db.execute("SAVEPOINT once")
        orchestrator._failed.clear()
        pv = provider()
        go(db, Gear(db), pv, cfg)
        keys = {(t["agent"], t["task_kind"]): t["idem_key"] for t in rows(db, "SELECT * FROM ai.agent_tasks WHERE fixture_id = %s AND agent = 'match'", w.fixture)}
        users = [r.user for r in pv.requests if r.system in match.SYSTEM.values()]
        names = {(r["engine"], r["market_key"], r["selection"]): r["output"]["candidate"] for r in reviews_of(db, w.fixture) if r["market_key"] in ("1X2", "OU")}
        db.execute("ROLLBACK TO SAVEPOINT once")
        return keys, users, names

    off = one(settings())
    without_decisions = one(on())
    for market, selection, line, model in (("CORNERS_OU", "Over", "9.5", "family-corners_ft"), ("CARDS_OU", "Over", "4.5", "family-cards_lines_ft")):
        decide(db, seed, w.fixture, market, selection, line, "0.58", "1.90", known_at=AT - H, model=model)
    with_counts = one(on())
    assert without_decisions == off and with_counts == off, "the Match Agent is asked the same, under the same keys, and c1..c3 are the same selections"
    assert one(settings()) == off


def test_the_counts_take_only_the_places_goals_and_result_leave(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, seed)
    assign(db, w.fixture)
    markets = sorted(orchestrator_store.COUNT_MARKETS)
    for i, market in enumerate(markets):
        for model, side, line in (("family-a", "Home", "4.5"), ("family-b", "Away", "5.5")):
            three_way = market.endswith("1X2")
            decide(db, seed, w.fixture, market, side if three_way else "Over", "0" if three_way else line, f"0.{50 + i}", "2.00", known_at=AT - H,
                   model=model)
    pv = provider()
    go(db, Gear(db), pv, on())
    state = shadow_state(db, w.fixture)
    named = [c for c in state["candidates"] if c.get("candidate")]
    assert len(named) == CANDIDATES_MAX and [c["candidate"] for c in named[:3]] == ["c1", "c2", "c3"]
    assert {c["market"] for c in named[:3]} == {"1X2", "OU"}
    left = [c for c in state["candidates"] if c.get("left_out")]
    assert {c["left_out"] for c in left} == {"beyond_the_limit"} and all("decision_id" in c for c in left)
    assert len(left) == 2 * len(markets) - (CANDIDATES_MAX - 3) and len(state["model_status"]["stats"]["counts"]["decisions"]) == 2 * len(markets)


# ── the audit ───────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_leak_rules_stay_clean_and_what_was_asked_is_derived_again(db: psycopg.Connection[Any], seed: Seed) -> None:
    w, ids = counted(db, seed)
    pv = provider()
    go(db, Gear(db), pv, on())
    start, end = RUN - timedelta(days=1), RUN + timedelta(days=1)
    for rule in (leakage.agent_known, leakage.shadow_review_known, leakage.slice_known):
        n, bad, examples = rule(db, start, end)
        assert n >= 1 and (bad, examples) == (0, []), rule.__name__

    state = shadow_state(db, w.fixture)
    [run] = rows(db, "SELECT r.* FROM ai.agent_runs r JOIN ai.agent_tasks t ON t.last_run_id = r.id WHERE t.fixture_id = %s AND t.agent = 'stats'", w.fixture)
    assert run["known_at"] == state["known_at"] == AT

    # A decision written after the pass changes nothing of what the pass is derived again with.
    decide(db, seed, w.fixture, "CORNERS_OU", "Over", "10.5", "0.50", "2.30", known_at=AT + 2 * H)
    again = orchestrator_store.family_counts(db, w.fixture, at=state["known_at"])
    assert sorted(again.decision_ids) == state["model_status"]["stats"]["counts"]["decisions"] == sorted(ids)
    known = rows(db, "SELECT known_at FROM intel.decisions WHERE id = ANY(%s)", list(again.decision_ids))
    assert all(r["known_at"] <= run["known_at"] for r in known), "no decision read was known after the moment of the pass"

    package = mcp_package.derive(db, state["packet_id"], pass_kind=state["pass_kind"], model_code=model_code_version())
    assert package is not None and package.hash == state["package_hash"]
    naming = name_with_counts((*orchestrator_store.reviewed(db, work_of(w)).candidates, *again.candidates))
    assert list(stats.asked_keys(naming)) == state["model_status"]["stats"]["asked"] == run["candidates"]
    contra0 = contra.detect(package.document, naming=naming, assessments=(), at=state["known_at"])
    rebuilt = stats.evaluation_request(mcp_package.slices_of(package)["stats"], naming, at=state["known_at"], contradictions=contra0)
    [sent] = stats_requests(pv)
    assert rebuilt.user == sent.user, "the question the agent was asked is derived again, byte for byte, from what is stored"
