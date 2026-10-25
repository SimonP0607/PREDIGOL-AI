"""What a family learns from one decision, in a real database (plan F11, ``pm-fam-v1``): a decision is taken before the kick-off, the match is played, the
settlement writes its outcome and the post-mortem says what became of it and why.

The pure parts are in tests/unit/test_familydecisions_postmortem.py. Here: the decision that STOOD at the kick-off is studied once, with the count, the
price against the close, the verdict and the causes read from what the match left; the revisions that came before it are settled and not studied; a
rejection that came after a selection is the family's last word and nothing is studied; nothing is studied before the settlement; the pipeline's decisions
and the pipeline's post-mortem are neither read nor written; one decision that cannot be read, or that the database refuses, costs only itself; the step
does nothing while the switch is off."""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from psycopg.rows import dict_row

from fbi.core import decision_versions as dv
from fbi.familydecisions import decide as fd
from fbi.familydecisions import outcomes as fo
from fbi.familydecisions import postmortem as pm
from fbi.intel import postmortem as pipeline
from tests.integration.conftest import Seed

from .knowledge_world import World, card, goal
from .test_families_forecast import AT, catalogue, played, referees, run, upcoming, whistle
from .test_families_score import play
from .test_familydecisions_decide import KICKOFF, NOW, Market, scene
from .test_familydecisions_outcomes import LATER, decided
from .test_leak_audit_families import forged

pytestmark = pytest.mark.integration

AFTER = LATER + timedelta(hours=1)
"""A pass of the post-mortem: after the settlement of the decisions."""


@pytest.fixture()
def w(db: psycopg.Connection[Any], seed: Seed) -> World:
    return World(db, seed)


@pytest.fixture(autouse=True)
def small_window(monkeypatch: pytest.MonkeyPatch) -> None:
    from fbi.families import forecast

    monkeypatch.setattr(forecast, "MIN_DISPERSION_MATCHES", 40)


def stored(db: psycopg.Connection[Any]) -> list[dict[str, Any]]:
    with db.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM intel.family_postmortems ORDER BY id")
        return cur.fetchall()


def settled_and_studied(db: psycopg.Connection[Any], w: World, fid: int, **play_kw: Any) -> pm.StudyReport:
    play(w, fid, **play_kw)
    assert fo.settle(db, at=LATER).failed == 0
    return pm.study(db, at=AFTER)


def counts(db: psycopg.Connection[Any]) -> dict[str, int]:
    """How many rows the tables that the post-mortem must not write hold."""
    tables = ("intel.postmortems", "intel.entity_memory", "ai.memory_events", "models.match_forecasts", "intel.decisions", "intel.decision_outcomes")
    return {t: int(db.execute(f"SELECT count(*) FROM {t}").fetchall()[0][0]) for t in tables}


# ── the post-mortem of the decision that stood ───────────────────────────────────────────────────────────────────────

def test_the_decision_that_stood_is_studied_with_the_count_the_price_the_verdict_and_what_the_match_left(db: psycopg.Connection[Any], w: World) -> None:
    fid, _, (over, under) = decided(db, w)
    w.events(fid, [goal(0, 9, "away", 601), card(1, 34, "home", 502, "Red Card")])
    competition = db.execute("SELECT competition_id FROM core.competition_seasons WHERE id = %s", (w.season,)).fetchall()[0][0]
    decision, forecast_id = db.execute(
        "SELECT id, jsonb_path_query_first(filters, '$[*] ? (@.key == \"model\").data.forecast_id') FROM intel.decisions").fetchall()[0]
    report = settled_and_studied(db, w, fid)  # 11 corners: the over of 10.5 won
    assert (report.open, report.written, report.unreadable, report.failed) == (1, 1, 0, 0), report
    assert report.by_verdict == {"SUERTE": 1} and report.by_family == {"CORNERS": 1}

    [r] = stored(db)
    assert r["version"] == pm.VERSION == "pm-fam-v1" and r["decision_id"] == decision and r["created_at"] == AFTER
    assert (r["fixture_id"], r["kickoff_at"], r["family"], r["model_name"], r["market_key"], r["selection"], r["line"]) == (
        fid, KICKOFF, "CORNERS", "family-corners_ft", "CORNERS_OU", "Over", Decimal("10.50"))
    assert r["competition_id"] == competition and r["referee_id"] is None, "the match has no referee the identity layer placed"
    assert (r["result"], r["profit_flat"]) == ("win", Decimal(str(over)) - 1)
    fair = (1 / over) / (1 / over + 1 / under)
    assert r["odds"] == Decimal(str(over)) and float(r["p_close"]) == pytest.approx(fair, abs=1e-6)
    assert float(r["clv"]) == pytest.approx(over * fair - 1, abs=2e-6) and r["quality"] == "BAD", "a 6 % margin that did not move is a price below fair value"
    assert r["verdict"] == "SUERTE", "won at a price worse than the close"
    assert (r["actual"], r["margin"]) == (Decimal("11.00"), Decimal("0.50"))
    assert float(r["p_model"]) == pytest.approx(float(db.execute("SELECT p_model FROM intel.decisions").fetchall()[0][0]), abs=1e-6)
    assert float(r["p_decision"]) == pytest.approx(fair, abs=1e-5), "the books' fair probability at the decision"
    assert [c["code"] for c in r["causes"]] == ["red_card", "early_goal"]

    assert r["answers"]["resumen"].startswith("córners · CORNERS_OU Over 10.5 a ") and r["answers"]["suerte_o_decision"] == "SUERTE"
    assert r["answers"]["probabilidad"]["calibracion"] == "UNCALIBRATED" and r["answers"]["aprendizaje"] == pm.LESSON["SUERTE"]
    assert r["evidence"]["forecast"]["id"] == forecast_id, "the forecast the decision cited, from the decision's own record"
    assert r["evidence"]["decision"]["checkpoint"] == "T-24h" and r["evidence"]["decision"]["revisions"] == 1
    assert r["evidence"]["outcome"]["version"] == fo.VERSION and r["evidence"]["match"]["counts"] == {"corners_ft_home": 7, "corners_ft_away": 4}


@pytest.mark.parametrize(("corners", "close", "verdict", "quality"), [
    ((7, 4), None, "SUERTE", "BAD"),  # won, and the price was the book's own with its margin in it
    ((3, 3), None, "ERROR", "BAD"),  # lost at that price
    ((7, 4), (1.70, 2.20), "MERECIDO", "GOOD"),  # won, and the market moved to the selection
    ((3, 3), (1.70, 2.20), "VARIANZA", "GOOD"),  # lost, and the price was better than the close
])
def test_luck_against_decision_on_a_real_match(db: psycopg.Connection[Any], w: World, corners: tuple[int, int], close: tuple[float, float] | None,
                                               verdict: str, quality: str) -> None:
    fid, market, _ = decided(db, w)
    if close is not None:
        for book in w.books(3):  # the books change their minds after the decision
            market.quote(book, close[0], close[1], KICKOFF - timedelta(hours=2))
        market.read(KICKOFF - timedelta(hours=1, minutes=50))
    report = settled_and_studied(db, w, fid, corners=corners)
    [r] = stored(db)
    assert (r["quality"], r["verdict"]) == (quality, verdict) and report.by_verdict == {verdict: 1}


def test_a_close_of_fewer_than_three_books_is_no_close_and_the_decision_cannot_be_judged(db: psycopg.Connection[Any], w: World) -> None:
    fid, market, _ = decided(db, w)
    [book] = w.books(1)
    market.quote(book, 20.0, 1.70, KICKOFF - timedelta(hours=1))  # a book whose margin is no longer believable: not a price
    settled_and_studied(db, w, fid)
    [r] = stored(db)
    assert (r["clv"], r["p_close"], r["quality"], r["verdict"]) == (None, None, "UNKNOWN", "SIN_DATOS")
    assert r["result"] == "win" and r["answers"]["precio"]["texto"] == "sin cierre para medir el precio"


def test_the_referee_the_identity_layer_placed_is_in_the_row_and_what_he_usually_shows_in_the_evidence(db: psycopg.Connection[Any], w: World) -> None:
    catalogue(db)
    strict, other = referees(db, "Strict", "Other")
    played(w, refs=((strict, 1.0), (other, 1.0)))
    fid = upcoming(w)
    whistle(db, fid, strict, AT)
    run(db, [fid])
    market = Market(db, w, fid)
    market.pays(0.10)
    market.read(AT + timedelta(minutes=30))
    assert fd.decide_families(db, at=NOW)[0].written == 1
    settled_and_studied(db, w, fid)
    [r] = stored(db)
    [(expected,)] = db.execute("SELECT referee_id FROM core.referee_aliases WHERE id = %s", (strict,)).fetchall()
    assert r["referee_id"] == expected
    assert r["evidence"]["match"]["referee_usual_cards"] is not None and r["evidence"]["match"]["referee_usual_cards"] > 0
    assert "cards_above_referee" not in [c["code"] for c in r["causes"]] and "cards_below_referee" not in [c["code"] for c in r["causes"]], \
        "what a referee shows in cards says nothing of the corners of a match"


# ── which decision, and when ─────────────────────────────────────────────────────────────────────────────────────────

def test_a_second_pass_writes_nothing_and_a_row_is_never_rewritten(db: psycopg.Connection[Any], w: World) -> None:
    fid, _, _ = decided(db, w)
    settled_and_studied(db, w, fid)
    [first] = stored(db)
    again = pm.study(db, at=AFTER + timedelta(hours=1))
    assert (again.open, again.written) == (0, 0), "a decision with a post-mortem is not looked at again"
    assert stored(db) == [first]


def test_nothing_is_studied_before_the_decision_is_settled(db: psycopg.Connection[Any], w: World) -> None:
    fid, _, _ = decided(db, w)
    play(w, fid)
    assert pm.study(db, at=LATER).open == 0, "the match is over and the decision has no outcome yet: its settlement waits 30 hours"
    assert stored(db) == []
    assert fo.settle(db, at=LATER).settled == 1
    assert pm.study(db, at=LATER).written == 1


def test_the_revisions_are_settled_and_only_the_decision_that_stood_is_studied(db: psycopg.Connection[Any], w: World) -> None:
    fid, market, (over, _) = scene(db, w)
    assert fd.decide_families(db, at=NOW)[0].written == 1
    for book in w.books(3):  # the books pay 8 % more for the over
        market.quote(book, round(over * 1.08, 2), 1.50, AT + timedelta(hours=2))
    market.read(AT + timedelta(hours=2, minutes=5))
    assert fd.decide_families(db, at=AT + timedelta(hours=3))[0].written == 1
    assert fd.decide_families(db, at=KICKOFF - timedelta(hours=11))[0].written == 1  # and another checkpoint (T-12h)
    ids = [r[0] for r in db.execute("SELECT id FROM intel.decisions ORDER BY known_at, id").fetchall()]
    assert len(ids) == 3

    report = settled_and_studied(db, w, fid)
    assert db.execute("SELECT count(*) FROM intel.decision_outcomes").fetchone() == (3,), "every revision is settled"
    assert (report.open, report.written) == (1, 1), "and one of them is studied"
    [r] = stored(db)
    assert r["decision_id"] == ids[-1] and r["evidence"]["decision"]["checkpoint"] == "T-12h" and r["evidence"]["decision"]["revisions"] == 3


def test_each_model_and_each_market_of_a_match_has_its_own_decision_that_stood(db: psycopg.Connection[Any], w: World) -> None:
    """The last word is the last of a model AND a market AND a match: another model's decision on the same market, or the same model's on another market,
    is not a revision of this one - it is another bet, and it is studied, with one revision of its own."""
    fid, _, _ = decided(db, w)
    [(source,)] = db.execute("SELECT id FROM intel.decisions").fetchall()
    other_model = forged(db, source, model_name="family-corners_ft-b", known_at=NOW + timedelta(minutes=1))
    other_market = forged(db, source, market_key="CORNERS_OU_HOME", line=Decimal("6.5"), known_at=NOW + timedelta(minutes=2))
    report = settled_and_studied(db, w, fid)
    assert (report.open, report.written) == (3, 3), report
    rows = stored(db)
    assert {r["decision_id"] for r in rows} == {source, other_model, other_market}
    assert [r["evidence"]["decision"]["revisions"] for r in rows] == [1, 1, 1], "the others are not counted as revisions of each"
    assert {(r["model_name"], r["market_key"]) for r in rows} == {("family-corners_ft", "CORNERS_OU"), ("family-corners_ft-b", "CORNERS_OU"),
                                                                  ("family-corners_ft", "CORNERS_OU_HOME")}


def test_a_rejection_that_came_after_a_selection_is_the_last_word_and_nothing_is_studied(db: psycopg.Connection[Any], w: World) -> None:
    fid, market, _ = scene(db, w)
    assert fd.decide_families(db, at=NOW)[0].written == 1
    [fourth] = w.books(4)[3:]
    market.quote(fourth, 9.00, 1.10, AT + timedelta(hours=2))  # an absurd price: the filters refuse it
    market.read(AT + timedelta(hours=2, minutes=5))
    assert fd.decide_families(db, at=AT + timedelta(hours=3))[0].written == 1
    assert [r[0] for r in db.execute("SELECT state FROM intel.decisions ORDER BY known_at, id").fetchall()] == ["INVESTIGACION", "RECHAZADO"]
    report = settled_and_studied(db, w, fid)
    assert (report.open, report.written) == (0, 0) and stored(db) == [], "the family's last word was no"
    assert db.execute("SELECT count(*) FROM intel.decision_outcomes").fetchone() == (2,), "both rows are settled all the same"


def test_an_outcome_of_another_version_is_not_the_one_this_post_mortem_studies(db: psycopg.Connection[Any], w: World) -> None:
    fid, _, _ = decided(db, w)
    play(w, fid)
    fo.settle(db, at=LATER)
    db.execute("SET LOCAL fbi.intel_maintenance = 'on'")  # an outcome is append-only: a later version of the settlement is simulated by lifting the guard
    db.execute("UPDATE intel.decision_outcomes SET version = 'outcome-fam-v2'")
    db.execute("SET LOCAL fbi.intel_maintenance = 'off'")
    assert pm.study(db, at=AFTER).open == 0, "pm-fam-v1 studies what outcome-fam-v1 settled"
    assert stored(db) == []


def test_a_decision_that_became_a_pick_is_not_a_decision_of_research(db: psycopg.Connection[Any], w: World) -> None:
    fid, _, _ = decided(db, w)
    pick = w.pick(fid, "CORNERS_OU", "Over", 10.5)
    db.execute("SET LOCAL fbi.intel_maintenance = 'on'")  # a family never has a pick: the day one does is the day its decisions are the pipeline's
    db.execute("UPDATE intel.decisions SET pick_id = %s", (pick,))
    db.execute("SET LOCAL fbi.intel_maintenance = 'off'")
    play(w, fid)
    assert fo.settle(db, at=LATER).open == 0, "the settlement leaves it to the pipeline's"
    db.execute("SET LOCAL fbi.intel_maintenance = 'on'")
    db.execute("INSERT INTO intel.decision_outcomes (decision_id, settled_at, result_status, profit_flat, profit_staked, version, computed_at) "
               "SELECT id, %s, 'win', 1.1, 0, %s, %s FROM intel.decisions", (LATER, dv.OUTCOME_FAMILIES, LATER))
    db.execute("SET LOCAL fbi.intel_maintenance = 'off'")
    assert pm.study(db, at=AFTER).open == 0 and stored(db) == []


def test_a_match_older_than_the_window_is_not_looked_at(db: psycopg.Connection[Any], w: World) -> None:
    fid, _, _ = decided(db, w)
    play(w, fid)
    assert fo.settle(db, at=LATER).settled == 1
    assert pm.study(db, at=LATER, lookback=timedelta(hours=1), write=False).open == 0
    assert pm.study(db, at=LATER, lookback=timedelta(hours=19), write=False).open == 0, \
        "kicked off 31 hours ago: the decision was taken within the horizon of the window, the match was not"
    assert pm.study(db, at=LATER, lookback=timedelta(hours=32), write=False).open == 1
    assert pm.study(db, at=LATER).written == 1


def test_a_dry_run_builds_and_writes_nothing(db: psycopg.Connection[Any], w: World) -> None:
    fid, _, _ = decided(db, w)
    play(w, fid)
    fo.settle(db, at=LATER)
    report = pm.study(db, at=AFTER, write=False)
    assert (report.open, report.written) == (1, 1) and report.by_verdict == {"SUERTE": 1}
    assert stored(db) == []


# ── what it reads and what it writes ─────────────────────────────────────────────────────────────────────────────────

def test_it_writes_only_its_own_table_and_the_pipelines_post_mortem_sees_nothing_of_it(db: psycopg.Connection[Any], w: World) -> None:
    fid, _, _ = decided(db, w)
    play(w, fid)
    fo.settle(db, at=LATER)
    before = counts(db)
    assert pm.study(db, at=AFTER).written == 1
    assert counts(db) == before, "no decision, outcome, forecast, post-mortem or memory of the pipeline was written"
    seen = pipeline.study(db, at=AFTER)
    assert seen.candidates == 0 and seen.studied == 0, "the pipeline's post-mortem reads the decisions of its own layer"
    assert counts(db) == before and len(stored(db)) == 1


def test_the_decisions_of_the_pipeline_are_not_studied_here(db: psycopg.Connection[Any], w: World) -> None:
    fid, _, _ = decided(db, w)
    db.execute("INSERT INTO intel.decisions (decision_version, known_at, checkpoint, fixture_id, kickoff_at, market_key, selection, line, pick_id, "
               "model_name, model_version_id, odds, bookmaker_id, price_at, n_bookmakers, p_model, p_low, p_high, p_push, p_cal, calibrator_id, "
               "calibrator_role, p_market, ev_raw, edge_raw, ev_cal, edge_cal, filters, state, reasons, premium, parlay_eligible, score, score_version, "
               "score_components, stake_units, stake_version, stake_components, context_status, context, review_id, evidence_ids, input_hash, "
               "code_version) SELECT %s, known_at, checkpoint, fixture_id, kickoff_at, market_key, selection, line, pick_id, model_name, "
               "model_version_id, odds, bookmaker_id, price_at, n_bookmakers, p_model, p_low, p_high, p_push, p_cal, calibrator_id, calibrator_role, "
               "p_market, ev_raw, edge_raw, ev_cal, edge_cal, filters, state, reasons, premium, parlay_eligible, score, score_version, "
               "score_components, stake_units, stake_version, stake_components, context_status, context, review_id, evidence_ids, 'pipeline', code_version "
               "FROM intel.decisions WHERE fixture_id = %s", (dv.DECISION_CORE, fid))
    [(core,)] = db.execute("SELECT id FROM intel.decisions WHERE decision_version = %s", (dv.DECISION_CORE,)).fetchall()
    db.execute("INSERT INTO intel.decision_outcomes (decision_id, settled_at, result_status, profit_flat, profit_staked, version, computed_at) "
               "VALUES (%s, %s, 'win', 1.1, 0, %s, %s)", (core, LATER, dv.OUTCOME_CORE, LATER))
    settled_and_studied(db, w, fid)
    [r] = stored(db)
    assert db.execute("SELECT decision_version FROM intel.decisions WHERE id = %s", (r["decision_id"],)).fetchone() == (dv.DECISION_FAMILIES,)
    assert len(stored(db)) == 1


def test_a_decision_that_does_not_say_its_family_is_counted_and_costs_the_others_nothing(db: psycopg.Connection[Any], w: World) -> None:
    catalogue(db)
    played(w)
    first, second = upcoming(w, 0, 1), upcoming(w, 2, 3)
    run(db, [first, second])
    one = Market(db, w, first)
    one.pays(0.10)
    one.read(AT + timedelta(minutes=30))
    two = Market(db, w, second, like=one)
    two.pays(0.10)
    two.read(AT + timedelta(minutes=30))
    assert fd.decide_families(db, at=NOW)[0].written == 2
    db.execute("SET LOCAL fbi.intel_maintenance = 'on'")  # the record of a decision is append-only: a faulty writer is simulated by lifting the guard
    db.execute("UPDATE intel.decisions SET filters = (SELECT jsonb_agg(CASE WHEN f->>'key' = 'model' THEN jsonb_set(f, '{data}', (f->'data') - 'family') "
               "ELSE f END) FROM jsonb_array_elements(filters) f) WHERE fixture_id = %s", (second,))
    db.execute("SET LOCAL fbi.intel_maintenance = 'off'")
    play(w, first)
    play(w, second)
    assert fo.settle(db, at=LATER).settled == 2
    report = pm.study(db, at=AFTER)
    assert (report.open, report.written, report.unreadable, report.failed) == (2, 1, 1, 0), report
    assert "which family" in report.errors[0] and str(second) in report.errors[0]
    assert [r["fixture_id"] for r in stored(db)] == [first], "the other match was studied"
    assert pm.study(db, at=AFTER + timedelta(hours=1)).unreadable == 1, "and the one that cannot be read is told again, never guessed"


def test_a_decision_the_database_refuses_costs_that_decision_and_nothing_else(db: psycopg.Connection[Any], w: World, monkeypatch: pytest.MonkeyPatch) -> None:
    catalogue(db)
    played(w)
    first, second = upcoming(w, 0, 1), upcoming(w, 2, 3)
    run(db, [first, second])
    one = Market(db, w, first)
    one.pays(0.10)
    one.read(AT + timedelta(minutes=30))
    two = Market(db, w, second, like=one)
    two.pays(0.10)
    two.read(AT + timedelta(minutes=30))
    assert fd.decide_families(db, at=NOW)[0].written == 2
    play(w, first)
    play(w, second)
    assert fo.settle(db, at=LATER).settled == 2

    real, calls = pm._insert, []

    def flaky(conn: psycopg.Connection[Any], s: pm.Stood, b: pm.Built, facts: pm.Facts, *, at: datetime) -> bool:
        calls.append(s.id)
        if len(calls) == 1:
            raise psycopg.errors.CheckViolation("the database refuses this one")
        return real(conn, s, b, facts, at=at)

    monkeypatch.setattr(pm, "_insert", flaky)
    report = pm.study(db, at=AFTER)
    assert (report.open, report.written, report.failed) == (2, 1, 1), report
    assert len(report.errors) == 1 and "CheckViolation" in report.errors[0]
    assert [r["decision_id"] for r in stored(db)] == [calls[1]], "the other decision was written"
    monkeypatch.setattr(pm, "_insert", real)
    assert pm.study(db, at=AFTER + timedelta(hours=1)).written == 1, "and the one refused is tried again on the next pass"
    assert len(stored(db)) == 2


def test_the_database_itself_refuses_a_row_that_contradicts_the_rule(db: psycopg.Connection[Any], w: World, monkeypatch: pytest.MonkeyPatch) -> None:
    """If the code ever put a verdict the rule does not give, the table would refuse the row: the constraint is the last line, not the first."""
    fid, _, _ = decided(db, w)
    play(w, fid)
    fo.settle(db, at=LATER)
    monkeypatch.setattr(pipeline, "verdict_of", lambda result, quality: "MERECIDO")
    report = pm.study(db, at=AFTER)
    assert (report.written, report.failed) == (0, 1) and "family_postmortems_verdict_follows_the_rule" in report.errors[0]
    assert stored(db) == []


# ── the step of the job ──────────────────────────────────────────────────────────────────────────────────────────────

def test_the_step_does_nothing_while_the_switch_is_off_and_studies_in_shadow(db: psycopg.Connection[Any], w: World, monkeypatch: pytest.MonkeyPatch) -> None:
    fid, _, _ = decided(db, w)
    play(w, fid)
    fo.settle(db, at=LATER)
    monkeypatch.setattr(fd, "environment", lambda: {})
    assert pm.run_step(db, at=AFTER) == {"mode": "off"} and stored(db) == []
    monkeypatch.setattr(fd, "environment", lambda: {fd.SWITCH: "shadow"})
    out = pm.run_step(db, at=AFTER)
    assert out["mode"] == "shadow" and (out["open"], out["written"], out["unreadable"], out["failed"]) == (1, 1, 0, 0)
    assert out["by_verdict"] == {"SUERTE": 1} and out["by_family"] == {"CORNERS": 1}
    assert len(stored(db)) == 1
