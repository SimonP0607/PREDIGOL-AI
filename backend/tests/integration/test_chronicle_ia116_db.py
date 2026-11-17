"""IA-116..IA-119 in a real database (revision 0159 applied), with a model that answers what each test needs (no network).

The single chronicle is kept with the rule of repetitions measured (``shadow``: nothing dropped); after the official line-up (E3) one new
version of it is written by template - the paragraph, the chronicle's outdated sentence superseded, the why of each selection with its origin
- and the earlier version is untouched; after the match ``chronicle-review-v2`` judges it on its cited facts into ``ai.chronicle_reviews``,
once, beside v1; the table refuses a review that names no text, or the wrong one. The transaction is rolled back."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb

from fbi.ai.usage import UsageLedger, shared
from fbi.chronicle import plan as cp
from fbi.chronicle import repetition, retire, review, review_v2, update_job, v4_job
from tests.integration.conftest import Seed
from tests.integration.helpers import scalar
from tests.integration.test_chronicle_v4_db import empty, plan_of, rows
from tests.integration.test_match_forecast import KO, World, world  # noqa: F401  (the fixture and the data)
from tests.integration.test_user_narrative import MODEL, RUN_AT, SETTINGS, Model, frozen, match  # noqa: F401

pytestmark = pytest.mark.integration

E3_AT = KO - timedelta(minutes=60)


def answer(plan: cp.ContentPlan) -> dict[str, Any]:
    """Two sentences the plan supports: the home side's newest result and its key absence as the provider gives it."""
    result = plan.by_id()["P:results.home.1"].params
    out = next(f for f in plan.planned if f.kind == "absence.out")
    es, en = empty(), empty()
    es["como_llega"] = [{"text": f"El {result['team']} ganó {result['goals_for']}-{result['goals_against']} al {result['opponent']} en su "
                                 "último partido.", "facts": ["P:results.home.1"]}]
    en["como_llega"] = [{"text": f"{result['team']} beat {result['opponent']} {result['goals_for']}-{result['goals_against']} in their last "
                                 "match.", "facts": ["P:results.home.1"]}]
    es["jugadores"] = [{"text": f"{out.params['player']} es baja en el {out.params['team']}, según el proveedor de datos.", "facts": [out.id]}]
    en["jugadores"] = [{"text": f"{out.params['player']} is out for {out.params['team']}, according to the data provider.", "facts": [out.id]}]
    return {"es": es, "en": en}


def chronicle(db: psycopg.Connection[Any], world: World, seed: Seed) -> tuple[int, cp.ContentPlan]:  # noqa: F811
    fid, _packet, _ids = match(db, world, seed)
    plan = plan_of(db, fid)
    report = v4_job.run(db, SETTINGS, at=RUN_AT, mode_word="shadow", batch=False, provider=(Model(answer(plan)), MODEL),
                        ledger=UsageLedger(shared(db)), cap=Decimal("1.00"))
    assert report.counts["ok"] == 1, report.counts
    return fid, plan


def line_up(db: psycopg.Connection[Any], seed: Seed, fid: int, *, starts: str) -> int:
    for side, people in (("home", [(501, starts, True), (502, "Bernd Leno", True)]), ("away", [(601, "Jordan Pickford", True)])):
        db.execute("INSERT INTO core.fixture_lineups (fixture_id, team_side, source, payload_hash, fetched_at) "
                   "VALUES (%s, %s, 'api-football', %s, %s)", (fid, side, seed.payload_hash, E3_AT - timedelta(minutes=2)))
        for pid, name, starter in people:
            db.execute("INSERT INTO core.fixture_lineup_players (fixture_id, team_side, source, provider_player_id, player_name, is_starter) "
                       "VALUES (%s, %s, 'api-football', %s, %s, %s)", (fid, side, pid, name, starter))
    run_id = int(scalar(db.execute(
        "INSERT INTO intel.eval_runs (fixture_id, evaluation, evaluation_version, cause, cause_key, known_at, kickoff_at, trigger_at, "
        "finished_at, latency_ms, status, decided, lineup, summary, version) VALUES (%s, 'E3', 1, 'alineacion_oficial', 'sheet:501,502', "
        "%s, %s, %s, %s, 4000, 'completa', false, %s, '{}', 'eval-cycle-v1') RETURNING id",
        (fid, E3_AT, KO, E3_AT - timedelta(seconds=4), E3_AT, Jsonb({"sides": ["away", "home"]})))))
    db.execute("INSERT INTO intel.eval_verdicts (run_id, fixture_id, market_key, selection, line, evaluation, evaluation_version, known_at, "
               "kickoff_at, verdict, state, reason, cause, version) VALUES (%s, %s, '1X2', 'Home', 0, 'E3', 1, %s, %s, 'confirmada', "
               "'confirmada_sombra', 'cumple_todo', 'alineacion_confirma', 'eval-verdict-v1')", (run_id, fid, E3_AT, KO))
    return run_id


def test_the_chronicle_is_kept_with_the_rule_of_repetitions_measured(db: psycopg.Connection[Any], world: World, seed: Seed,  # noqa: F811
                                                                    frozen: None) -> None:  # noqa: F811
    fid, _plan = chronicle(db, world, seed)
    [row] = rows(db, fid)
    rep = row["metrics"]["repetition"]
    assert rep["version"] == repetition.VERSION and rep["mode"] == "shadow" and rep["dropped"] == 0 and rep["corpus"] == 0
    assert len(rep["templates"]) == row["metrics"]["kept"] == 2
    assert scalar(db.execute("SELECT verify_version FROM ai.chronicles WHERE fixture_id = %s", (fid,))) == "chronicle-verify-v1"
    assert repetition.corpus_of([]).size == 0


def test_after_the_line_up_one_new_version_corrects_the_chronicle_and_explains_each_selection(
        db: psycopg.Connection[Any], world: World, seed: Seed, frozen: None) -> None:  # noqa: F811
    fid, plan = chronicle(db, world, seed)
    out = next(f for f in plan.planned if f.kind == "absence.out")
    run_id = line_up(db, seed, fid, starts=str(out.params["player"]))
    assert update_job.run(db, at=E3_AT, mode_word="off").counts == {}
    report = update_job.run(db, at=E3_AT + timedelta(minutes=1), mode_word="shadow")
    assert report.counts["written"] == 1 and report.counts["errors"] == 0, report.counts
    first, new = rows(db, fid)
    assert new["route"] == "none" and new["cost_usd"] == 0 and new["usage_id"] is None and new["plan_hash"] == first["plan_hash"]
    assert new["content"]["es"] == first["content"]["es"], "the earlier sections are carried as they were"
    block = new["content"]["actualizacion"]
    assert block["version"] == "lineup-update-v1" and block["e3_run_id"] == run_id and {"section": "jugadores", "index": 0} in block["superseded"]
    assert any("figura como titular" in s for s in block["es"])
    [why] = new["content"]["selecciones"]
    assert why["version"] == "selection-why-v1" and why["phrases"][0]["origin"]["kind"] == "decision"
    assert all(p["origin"]["kind"] in ("decision", "chronicle", "update") for p in why["phrases"])
    assert new["metrics"]["without_origin"] == 0 and new["metrics"]["latency_from_lineup_ms"] < 120_000
    custom = scalar(db.execute("SELECT custom_id FROM ai.chronicles WHERE id = (SELECT max(id) FROM ai.chronicles WHERE fixture_id = %s)", (fid,)))
    assert custom == f"lineup-update:{run_id}"
    assert update_job.run(db, at=E3_AT + timedelta(minutes=3), mode_word="shadow").counts["due"] == 0, "never twice"
    again = v4_job.run(db, SETTINGS, at=RUN_AT, mode_word="shadow", batch=False, provider=(Model(), MODEL),
                       ledger=UsageLedger(shared(db)), cap=Decimal("1.00"))
    assert again.counts["already_answered"] == 1, "an update is no reason to pay for the chronicle again"


def test_after_the_match_the_chronicle_is_judged_on_its_cited_facts_once(db: psycopg.Connection[Any], world: World,  # noqa: F811
                                                                         seed: Seed, frozen: None) -> None:  # noqa: F811
    fid, plan = chronicle(db, world, seed)
    out = next(f for f in plan.planned if f.kind == "absence.out")
    line_up(db, seed, fid, starts=str(out.params["player"]))
    update_job.run(db, at=E3_AT + timedelta(minutes=1), mode_word="shadow")
    db.execute("UPDATE core.fixtures SET status_short = 'FT', status_group = 'finished' WHERE id = %s", (fid,))
    db.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away, settled_at) VALUES (%s, 2, 1, %s)",
               (fid, KO + timedelta(hours=2)))
    for pid, side, name in ((501, "home", str(out.params["player"])), (502, "home", "Bernd Leno"), (601, "away", "Jordan Pickford")):
        db.execute("INSERT INTO core.fixture_player_stats (fixture_id, source, provider_player_id, team_side, player_name, minutes, "
                   "is_substitute, shots_total, goals, payload_hash, fetched_at) VALUES (%s, 'api-football', %s, %s, %s, 90, false, 0, 0, "
                   "%s, %s)", (fid, pid, side, name, seed.payload_hash, KO + timedelta(hours=3)))
    at = KO + review_v2.SETTLE + timedelta(hours=1)
    report = review_v2.run(db, at=at)
    assert report.written == 1 and report.failed == 0 and report.unsupported == 0, report
    r = db.execute("SELECT narrative_id, chronicle_id, narrative_version, version, summary, items FROM ai.chronicle_reviews "
                   "WHERE fixture_id = %s", (fid,)).fetchone()
    assert r is not None
    narrative_id, chronicle_id, chronicle_version, version, summary, items = r
    assert narrative_id is None and chronicle_id is not None and chronicle_version == "chronicle-v4" and version == review_v2.VERSION
    assert summary["version"] == review_v2.METRICS_VERSION and summary["unsupported"] == 0 and summary["contradicted"] >= 1
    said = next(i for i in items if i["part"] == "chronicle" and i["section"] == "jugadores")
    assert said["verdict"] == review.CONTRADICTED and said["superseded"]
    assert review_v2.run(db, at=at).written == 0, "once per chronicle and version"
    assert review.run(db, at=at).due == 0, "v1 reviews the readers' chronicle only"
    matches, found = retire.rows_for(db, since=KO - timedelta(days=1), until=KO + timedelta(days=1))
    assert fid in matches and any(x["fixture_id"] == fid for x in found[retire.CHRONICLE])
    assert all(not str(x.get("custom_id") or "").startswith("lineup-update:") for x in found[retire.CHRONICLE])


def test_the_table_takes_exactly_one_text_and_the_right_one(db: psycopg.Connection[Any], world: World, seed: Seed,  # noqa: F811
                                                            frozen: None) -> None:  # noqa: F811
    fid, _plan = chronicle(db, world, seed)
    sql = ("INSERT INTO ai.chronicle_reviews (fixture_id, narrative_id, chronicle_id, version, created_at, narrative_version, packet_id, "
           "trace_id, status, outcome, items, summary) VALUES (%s, %s, %s, %s, now(), %s, 1, gen_random_uuid(), 'reviewed', '{}', '[]', '{}')")
    for narrative, chronicle_id, version, text in ((None, None, "chronicle-review-v2", "chronicle-v4"),
                                                   (5, 7, "chronicle-review-v2", "chronicle-v4"),
                                                   (5, None, "chronicle-review-v2", "chronicle-v4"),
                                                   (None, 7, "chronicle-review-v2", "user-narrative-v3")):
        with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
            db.execute(sql, (fid, narrative, chronicle_id, version, text))
    with db.transaction():
        db.execute(sql, (fid, 5, None, "chronicle-review-v1", "user-narrative-v3"))
        db.execute(sql, (fid, None, 7, "chronicle-review-v2", "chronicle-v4"))
    with pytest.raises(psycopg.Error, match="append-only"), db.transaction():
        db.execute("DELETE FROM ai.chronicle_reviews WHERE fixture_id = %s", (fid,))
