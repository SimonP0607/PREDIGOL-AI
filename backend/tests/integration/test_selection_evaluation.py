"""AD-K01/K02/J03/J04 (IA-112 to IA-115) against a real database: the evaluation after the match written once and the same on a second
pass, its parity with ``intel.decision_outcomes``, the facts judged against the provider's line-up, the board over what was kept, and the
two private routes (C-02 inside the decision's page, C-03) answering the owner and refusing a reader."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient
from psycopg.types.json import Jsonb

from fbi.ai.gates import typed_visible
from fbi.api.app import create_app
from fbi.api.contracts.intelligence.selection import EvaluationSummary, SelectionIntelligencePrivate
from fbi.api.contracts.intelligence.tracking import Tracking
from fbi.api.deps import get_db
from fbi.evalpass import store
from fbi.evaluation import sources, views
from fbi.evaluation.selection import VERSION
from tests.integration.conftest import Seed
from tests.integration.signed_in import SAME_SITE, signed_in

pytestmark = pytest.mark.integration


def client(db: psycopg.Connection[Any], role: str) -> TestClient:
    app = signed_in(create_app(), role)
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app, headers=SAME_SITE, raise_server_exceptions=False)


def played(db: psycopg.Connection[Any], seed: Seed, *, provider: int, home: int, away: int) -> tuple[int, Any]:
    ko = db.execute("SELECT now() - interval '1 day'").fetchone()[0]  # type: ignore[index]
    fid = int(db.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at, "
                         "status_short) VALUES (%s, %s, %s, %s, %s, 'FT') RETURNING id",
                         (provider, seed.season_id, seed.home_team_id, seed.away_team_id, ko)).fetchone()[0])  # type: ignore[index]
    db.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away) VALUES (%s, %s, %s)", (fid, home, away))
    return fid, ko


def decide(db: psycopg.Connection[Any], fid: int, ko: Any, market: str, selection: str, line: float, *, hours: float, state: str,
           p_cal: float | None, odds: float, evidence: list[int] | None = None, reasons: list[str] | None = None,
           version: str = "decision-v1") -> int:
    return int(db.execute(
        "INSERT INTO intel.decisions (decision_version, known_at, checkpoint, fixture_id, kickoff_at, market_key, selection, line, "
        "model_name, odds, n_bookmakers, price_at, p_model, p_cal, p_market, filters, state, reasons, context_status, evidence_ids, "
        "input_hash) VALUES (%s, %s, 'T-3h', %s, %s, %s, %s, %s, 'dixon_coles', %s, 6, %s, 0.56, %s, 0.50, '[]', %s, %s, 'FULL', %s, %s) "
        "RETURNING id",
        (version, ko - timedelta(hours=hours), fid, ko, market, selection, line, odds, ko - timedelta(hours=hours, minutes=20), p_cal,
         state, reasons or [], evidence or [], f"k01-{fid}-{market}-{selection}-{line}-{hours}")).fetchone()[0])  # type: ignore[index]


def settle(db: psycopg.Connection[Any], decision_id: int, ko: Any, result: str, *, p_close: float, odds: float) -> None:
    db.execute("INSERT INTO intel.decision_outcomes (decision_id, settled_at, result_status, profit_flat, profit_staked, close_p_fair, "
               "close_odds, close_as_of, close_minutes_to_ko, clv, version, computed_at) VALUES (%s, %s, %s, 0, 0, %s, 1.9, %s, 170, %s, "
               "'outcome-v1', %s)", (decision_id, ko + timedelta(hours=2), result, p_close, ko - timedelta(hours=3),
                                     round(odds * p_close - 1, 6), ko + timedelta(hours=2)))


def world(db: psycopg.Connection[Any], seed: Seed) -> dict[str, Any]:
    fid, ko = played(db, seed, provider=880101, home=2, away=1)
    db.execute("INSERT INTO core.fixture_lineups (fixture_id, team_side, source, payload_hash, fetched_at) "
               "VALUES (%s, 'home', 'api-football', %s, %s)", (fid, seed.payload_hash, ko + timedelta(hours=3)))
    db.execute("INSERT INTO core.fixture_lineup_players (fixture_id, team_side, source, provider_player_id, player_name, is_starter) "
               "VALUES (%s, 'home', 'api-football', 5101, 'A. Ejemplo', true), (%s, 'home', 'api-football', 5102, 'B. Ejemplo', false)",
               (fid, fid))
    ev = [int(db.execute("INSERT INTO ai.evidence (fixture_id, kind, claim, origin, source_name, source_url, source_tier, retrieved_at, "
                         "story_key, content_hash, confidence, relevance, status, status_reason, status_changed_at, provider_player_id, "
                         "attributes) VALUES (%s, %s, 'texto de prueba', 'provider', 'proveedor.invalid', 'https://proveedor.invalid/x', "
                         "'provider', %s, %s, %s, 0.9, 0.9, 'CONFIRMED', 'test', %s, %s, %s) RETURNING id",
                         (fid, kind, ko - timedelta(hours=6), f"s-{kind}-{pid}", f"{pid:064d}", ko - timedelta(hours=6), pid,
                          Jsonb({"assertion": assertion}))).fetchone()[0])  # type: ignore[index]
          for kind, pid, assertion in (("injury", 5101, "out"), ("lineup", 5101, "starts"), ("injury", 5199, "out"))]
    early = decide(db, fid, ko, "OU", "Over", 2.5, hours=12, state="CAUTELA", p_cal=0.55, odds=2.05)
    over = decide(db, fid, ko, "OU", "Over", 2.5, hours=3, state="CAUTELA", p_cal=0.57, odds=2.05, evidence=ev,
                  reasons=["ev_cal_below"])
    late = decide(db, fid, ko, "OU", "Over", 2.5, hours=0.1, state="RECHAZADO", p_cal=0.57, odds=2.05)  # 6 minutes: not the standing one
    home = decide(db, fid, ko, "1X2", "Home", 0, hours=3, state="INVESTIGACION", p_cal=None, odds=1.80, reasons=["edge_not_validated"])
    settle(db, over, ko, "win", p_close=0.50, odds=2.05)
    settle(db, home, ko, "loss", p_close=0.58, odds=1.80)  # the stored result disagrees with the score: a provider's correction
    return {"fixture": fid, "ko": ko, "over": over, "home": home, "early": early, "late": late, "evidence": ev}


def test_the_evaluation_is_written_once_and_the_same_on_a_second_pass(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, seed)
    rep = store.Report()
    evs = store.evaluations(db, [w["fixture"]], rep)
    assert len(evs) == 2 and rep.skipped == {}
    by = {e.row["market_key"]: e for e in evs}
    over, home = by["OU"], by["1X2"]
    assert over.row["decision_id"] == w["over"] and over.row["verdict"] == "MERECIDO" and over.row["parity"] == "igual"
    assert over.row["clv"] is not None and over.row["seal"] == "calibrada" and over.row["taken"] is False
    assert [(i["id"], i["status"], i["why"]) for i in over.detail["evidence"]["items"]] == [
        (w["evidence"][0], "contradicho", "jugo"), (w["evidence"][1], "sostenido", "fue_titular"),
        (w["evidence"][2], "sostenido", "no_jugo")]
    assert home.row["parity"] == "difiere" and home.detail["parity"]["differences"][0] == {"what": "resultado", "stored": "loss",
                                                                                         "settle_v4": "win"}
    assert home.row["taken"] is True and home.row["seal"] == "sin_calibrar"
    assert store.write(db, evs, code_version="test") == (2, 0)
    again = store.evaluations(db, [w["fixture"]])
    assert [e.row["input_hash"] for e in again] == [e.row["input_hash"] for e in evs]
    assert store.write(db, again, code_version="test") == (0, 2)
    assert db.execute("SELECT count(*) FROM intel.selection_evaluations WHERE fixture_id = %s", (w["fixture"],)).fetchone()[0] == 2  # type: ignore[index]
    db.execute("SAVEPOINT s")
    with pytest.raises(psycopg.Error):
        db.execute("UPDATE intel.selection_evaluations SET verdict = 'ERROR' WHERE fixture_id = %s", (w["fixture"],))
    db.execute("ROLLBACK TO SAVEPOINT s")


def test_the_board_reads_what_was_kept_and_judges_only_what_the_layer_would_take(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, seed)
    store.write(db, store.evaluations(db, [w["fixture"]]), code_version="test")
    b = views.board(db, start=w["ko"] - timedelta(days=1), end=w["ko"] + timedelta(days=1))
    assert b is not None and b["counts"]["VALIDADO"] == 0
    cells = {(c["layer"], c["market"]): c for c in b["cells"]}
    assert cells[("decision-v1", "OU")]["candidates"] == 1 and cells[("decision-v1", "OU")]["sample"] == 0
    assert cells[("decision-v1", "1X2")]["sample"] == 1  # taken, with a full result, the market and a close: 1 of the needed 300
    assert cells[("decision-v1", "1X2")]["verdict"] == "INSUFICIENTE"
    one = views.evaluation_of(db, "intel.decisions", w["over"])
    assert one is not None and one["version"] == VERSION and one["verdict"] == "MERECIDO"


def test_the_sources_of_c02_are_read_with_the_question_every_reader_asks(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, seed)
    got = sources.sources(db, w["evidence"], typed=typed_visible(db))
    assert [r["id"] for r in got] == sorted(w["evidence"]) and set(got[0]) == {"id", "kind", "source_name", "source_url", "retrieved_at"}
    assert sources.sources(db, [], typed=False) == []


def test_the_owner_gets_c02_inside_the_decision_and_c03_and_a_reader_gets_403(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = world(db, seed)
    store.write(db, store.evaluations(db, [w["fixture"]]), code_version="test")
    owner, reader = client(db, "SUPER_ADMIN"), client(db, "USER")
    for path in (f"/api/v1/admin/intelligence/decisions/{w['over']}", "/api/v1/admin/intelligence/tracking"):
        assert reader.get(path).status_code == 403
    page = owner.get(f"/api/v1/admin/intelligence/decisions/{w['over']}")
    assert page.status_code == 200, page.text
    data = page.json()["data"]
    assert {"decision", "pick", "outcome", "history", "cost", "intelligence"} <= set(data)
    c02 = SelectionIntelligencePrivate.model_validate(data["intelligence"])
    assert c02.contract == "C-02" and c02.projection == "private" and c02.public_state is None
    assert isinstance(c02.evaluation, EvaluationSummary) and c02.decision_state == "CAUTELA"
    assert [v.checkpoint for v in c02.versions.items] == ["T-3h", "T-3h", "T-3h"]
    assert [s.id for s in c02.sources.items] == sorted(w["evidence"])
    assert [r.code for r in c02.reasons_against.items] == ["ev_cal_below"]
    day = (w["ko"] - timedelta(hours=5)).date().isoformat()
    t = owner.get("/api/v1/admin/intelligence/tracking", params={"from": day, "to": day})
    assert t.status_code == 200, t.text
    c03 = Tracking.model_validate(t.json()["data"])
    assert c03.contract == "C-03" and c03.projection == "private"
    assert owner.get("/api/v1/admin/intelligence/tracking", params={"state": "nada"}).status_code == 422
    assert owner.get("/api/v1/admin/intelligence/tracking", params={"from": "2026-01-01", "to": "2026-03-01"}).status_code == 422
