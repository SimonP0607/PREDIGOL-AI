"""The evaluation cycle E1-E4 (IA-105..IA-108) against a real PostgreSQL, on the player engine's own scene (twelve played rounds of two
teams, a striker who scores in half of them) with decision-v2's candidates on the next match:

* the whole match E1 -> E2 -> E3 -> E4: E1 decides, lists the striker as the player the over depends on (in doubt: the selection waits for
  the line-up, it is not confirmed blind); a fact about him triggers ONE E2; the official line-up without him withdraws the selection at
  E3 by code, within two minutes of its first sighting, with a private alert «antes -> ahora»; decision-v2 decides for the last time at
  T-15 (before decision-v1's floor) and E4 at T-4 (IA-142) reads the match again and judges with that decision, deciding nothing; after
  kick-off the chain under ``eval-cycle-v1`` is legal and closes; decision-v1's table does not move and nothing reaches a reader;
* the line-up with the striker confirms; no line-up at all raises «sin alineación» at E4 and closes as «sin alineación a tiempo», with
  the price read again at T-4;
* a kick-off brought forward after E1 is an alert, once; nothing is evaluated after kick-off; the five tables refuse UPDATE and DELETE.

Every pass runs inside the test's transaction (``commit=False``), so nothing outlives the test."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import psycopg
import pytest

from fbi.api.services import intelligence_alerts as alerts_svc
from fbi.decision import engine, shadow
from fbi.evalcycle import chain, dependency, run
from fbi.intel import calibration
from fbi.intel.calibration import GateVerdict, WalkForward
from fbi.lifecycle import machine
from fbi.models.scoring import MARKET_ROWS, dc_tau, from_matrix, poisson_matrix
from fbi.shadowjobs import eval_cycle

from .conftest import Seed
from .test_intel import IntelWorld
from .test_players_cli import World

pytestmark = pytest.mark.integration

CONFIG = shadow.Config(price=engine.CONSENSUS)
"""The shadow's own ruleset and single figure, priced by the consensus (the book needs RAW bodies)."""
STRIKER_J = 9
LAM_HOME, LAM_AWAY, RHO = 1.85, 1.05, -0.05


def scalar(db: psycopg.Connection[Any], sql: str, *args: Any) -> Any:
    row = db.execute(sql, args).fetchone()
    assert row is not None
    return row[0]


def champion(db: psycopg.Connection[Any], market: str, known: datetime) -> None:
    cid = calibration.store_fit(db, market=market, model="dixon_coles", method="identity", params={}, known_at=known, fitted_at=known,
                                train=[], wf=WalkForward("identity"), verdict=GateVerdict(True, True, {}))
    calibration.promote(db, at=known, entity="calibrator", market=market, model="dixon_coles", entity_id=cid, from_role=None,
                        to_role="CHAMPION", gate_version=calibration.GATE_VERSION, criteria={}, reason="test champion for the cycle")
    calibration.promote(db, at=known, entity="market_edge", market=market, model="dixon_coles", entity_id=cid, from_role=None,
                        to_role="VALIDATED", gate_version=calibration.EDGE_GATE_VERSION, criteria={}, reason="test edge for the cycle")


class Scene:
    """The player engine's two teams and, on their next match, decision-v2's candidate «over 2.5», its goal model's seven rows and prices."""

    def __init__(self, db: psycopg.Connection[Any], seed: Seed) -> None:
        self.db, self.seed = db, seed
        self.w = World(db, seed)
        db.execute("UPDATE core.competitions SET is_tracked = true WHERE id = (SELECT competition_id FROM core.competition_seasons "
                   "WHERE id = %s)", (seed.season_id,))
        self.k = self.w.kickoff
        self.fid = self.w.target
        self.intel = IntelWorld(db, seed)
        champion(db, "OU", self.k - timedelta(days=3))
        made = self.k - timedelta(hours=16)
        m = dc_tau(poisson_matrix(LAM_HOME, LAM_AWAY), LAM_HOME, LAM_AWAY, RHO)
        rows = from_matrix(m, LAM_HOME, LAM_AWAY).as_rows()
        self.p_over = rows[3]
        self.intel.pick(self.fid, "OU", "Over", "2.5", p_model=self.p_over, p_market=0.50, odds=2.10, created=made)
        for (market, selection, line), p in zip(MARKET_ROWS, rows, strict=True):
            db.execute("INSERT INTO models.predictions (fixture_id, model_version_id, market_key, selection, line, p_raw, p_calibrated, "
                       "p_lo, p_hi, feature_set_hash, data_cutoff_ts) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'fh', %s)",
                       (self.fid, seed.model_version_id, market, selection, line, p, p, max(0.01, p - 0.05), min(0.99, p + 0.05),
                        made - timedelta(minutes=30)))
        # the AI layer's first pass read the match (decision-v1's context stage: not PENDING)
        db.execute("INSERT INTO ai.fixture_passes (fixture_id, day, pass, started_at, finished_at, kickoff_at, status, counts) "
                   "VALUES (%s, %s, 'first', %s, %s, %s, 'ok', '{}')", (self.fid, made.date(), made, made + timedelta(minutes=5), self.k))
        self.price(self.k - timedelta(hours=13, minutes=20))
        self.striker = self.w.man(self.w.home, STRIKER_J)
        self.w.absence(self.w.home, STRIKER_J, self.k - timedelta(days=1), kind="Questionable")

    def price(self, at: datetime, odds: float = 2.10) -> None:
        self.intel.consensus(self.fid, "OU", "Over", "2.5", p_fair=0.50, best=odds, as_of=at)
        self.intel.consensus(self.fid, "OU", "Under", "2.5", p_fair=0.50, best=1.80, as_of=at)

    def fact(self, at: datetime) -> int:
        return int(scalar(self.db, "INSERT INTO ai.evidence (fixture_id, provider_player_id, kind, claim, origin, source_name, source_tier, "
                          "retrieved_at, story_key, content_hash, confidence, relevance, status, status_reason, status_changed_at) VALUES "
                          "(%s, %s, 'injury', 'Molestias en el entrenamiento', 'provider', 'api-football', 'provider', %s, 'k1', 'h1', "
                          "0.8, 0.8, 'PROBABLE', 'test', %s) RETURNING id", self.fid, self.striker, at, at))

    def line_up(self, at: datetime, *, with_striker: bool) -> None:
        home = [0, 1, 2, 3, 4, 5, 6, 7, 8, STRIKER_J, 10] if with_striker else [0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 12]
        self.w.lineup("home", self.w.home, at, starters=home, bench=[j for j in range(13) if j not in home])
        self.w.lineup("away", self.w.away, at, starters=list(range(11)), bench=[11, 12])

    def main(self, at: datetime) -> run.Report:
        rep = run.run_pass(self.db, now=at, store=None, estimates=eval_cycle._estimates, config=CONFIG, code_version="test", commit=False)
        assert not [e for e in rep.errors if "input after the moment" not in e], rep.as_json()
        return rep

    def e3(self, at: datetime) -> run.Report:
        rep = run.run_line_ups(self.db, now=at, store=None, config=CONFIG, code_version="test", commit=False)
        assert not rep.errors, rep.as_json()
        return rep

    def rows(self, sql: str, *args: Any) -> list[dict[str, Any]]:
        cur = self.db.execute(sql, args)
        names = [c.name for c in cur.description or ()]
        return [dict(zip(names, r, strict=True)) for r in cur.fetchall()]

    def verdicts(self) -> list[dict[str, Any]]:
        return self.rows("SELECT * FROM intel.eval_verdicts WHERE fixture_id = %s ORDER BY id", self.fid)


@pytest.fixture()
def scene(db: psycopg.Connection[Any], seed: Seed) -> Scene:
    return Scene(db, seed)


def test_a_whole_match_e1_to_e4_where_the_line_up_withdraws_the_selection(scene: Scene) -> None:
    db, k = scene.db, scene.k
    v1_before = scalar(db, "SELECT count(*) FROM intel.decisions")

    # E1, T-13 h: decided, dependent on the striker (in doubt), waiting for the line-up
    rep = scene.main(k - timedelta(hours=13))
    assert rep.runs == {"E1": 1} and not rep.failed, rep.as_json()
    dep = scene.rows("SELECT * FROM intel.lineup_dependencies WHERE fixture_id = %s", scene.fid)
    assert len(dep) == 1 and dep[0]["market_key"] == "OU" and dep[0]["market_group"] == dependency.DECLARED
    assert dep[0]["status"] == dependency.COMPUTED and dep[0]["waits"] and dep[0]["matrix"]["model"] == "dixon_coles"
    listed = {p["provider_player_id"]: p for p in dep[0]["players"]}
    assert scene.striker in listed and listed[scene.striker]["doubtful"], listed
    assert listed[scene.striker]["shift_without"] <= -dependency.MATERIAL
    assert abs(dep[0]["matrix"]["lam_home"] - LAM_HOME) < 1e-3, "the matrix is the goal model's own, inverted from its seven rows"
    (e1,) = scene.verdicts()
    assert (e1["evaluation"], e1["verdict"], e1["state"], e1["reason"]) == ("E1", "lectura", "pendiente_alineaciones",
                                                                           "depende_de_alineacion"), e1
    assert e1["detail"]["decision_state"] == "confirmada_sombra", "decision-v2 approves it: only the line-up keeps it waiting"
    assert scene.main(k - timedelta(hours=12, minutes=30)).runs == {}, "E1 is kept once"

    # E2: a fact about the striker -> one E2, recalculated; the same fact never a second one
    fact = scene.fact(k - timedelta(hours=6))
    scene.price(k - timedelta(hours=5, minutes=10))
    rep = scene.main(k - timedelta(hours=5))
    assert rep.runs == {"E2": 1} and rep.facts == {"recalcula": 1}, rep.as_json()
    e2 = scene.verdicts()[-1]
    assert (e2["evaluation"], e2["verdict"], e2["state"]) == ("E2", "lectura", "pendiente_alineaciones"), e2
    (looked,) = scene.rows("SELECT * FROM intel.eval_facts WHERE fixture_id = %s", scene.fid)
    assert (looked["evidence_id"], looked["action"], looked["reason"]) == (fact, "recalcula", "dependencia_declarada")
    assert scene.main(k - timedelta(hours=4)).runs == {}, "a fact never triggers two E2"

    # E3: the official line-up without the striker, first seen at T-19; the minute pass reads it 60 s later
    scene.price(k - timedelta(minutes=25))
    seen = k - timedelta(minutes=19)
    scene.line_up(seen, with_striker=False)
    rep = scene.e3(seen + timedelta(seconds=60))
    assert rep.runs == {"E3": 1} and rep.alerts == {"retirada": 1}, rep.as_json()
    assert rep.latency_ms and max(rep.latency_ms) < 120_000, "E3 ends within two minutes of the line-up's first sighting"
    (e3_run,) = scene.rows("SELECT * FROM intel.eval_runs WHERE fixture_id = %s AND evaluation = 'E3'", scene.fid)
    assert e3_run["cause"] == "alineacion_oficial" and e3_run["trigger_at"] == seen and e3_run["decided"]
    assert e3_run["lineup"]["source"] == {"home": "sheet", "away": "sheet"}
    e3 = scene.verdicts()[-1]
    assert (e3["evaluation"], e3["verdict"], e3["state"], e3["reason"], e3["cause"]) == (
        "E3", "retirada", "retirada", "alineacion_en_contra", "alineacion"), e3
    assert e3["lineup"]["missing"] == [scene.striker] and float(e3["p_after"]) < float(e3["p_before"])
    (alert,) = scene.rows("SELECT * FROM intel.private_alerts WHERE fixture_id = %s", scene.fid)
    assert (alert["kind"], alert["cause"], alert["evaluation"]) == ("retirada", "alineacion_en_contra", "E3")
    assert alert["before"]["state"] == "pendiente_alineaciones" and alert["after"]["state"] == "retirada"
    assert alert["after"]["players_out"] == [scene.striker] and alert["decision_id"] == e3["decision_id"]
    assert scene.e3(seen + timedelta(seconds=120)).runs == {}, "the same line-up is judged once"
    served = alerts_svc.build(db, at=seen + timedelta(minutes=3), hours=720)
    (item,) = served.alerts.items
    assert served.projection == "private" and served.contract == "C-05" and item.kind == "retirada" and not item.notifies_reader
    assert item.before.shape == item.now.shape == "seleccion" and item.now.players_out == [scene.striker]
    v2 = scene.rows("SELECT trigger, evaluation, evaluation_version FROM intel.decision_v2_moments WHERE fixture_id = %s ORDER BY id",
                    scene.fid)
    assert [(r["trigger"], r["evaluation"]) for r in v2] == [("E1", "E1"), ("E2", "E2"), ("E3", "E3")], "a version per evaluation"

    # T-15: decision-v2's last decision before decision-v1's floor - kept in its tables, no evaluation of the cycle yet
    rep = scene.main(k - timedelta(minutes=15))
    assert rep.runs == {} and rep.last_decisions == 1, rep.as_json()
    assert scene.main(k - timedelta(minutes=12)).last_decisions == 0, "the last decision is kept once"
    (last,) = scene.rows("SELECT id, known_at FROM intel.decision_v2_moments WHERE fixture_id = %s AND trigger = 'E4'", scene.fid)
    assert last["known_at"] == k - timedelta(minutes=15)

    # E4, T-4 (IA-142): the match read again; nothing decides; judged with the last decision; the selection stays withdrawn
    moments = scalar(db, "SELECT count(*) FROM intel.decision_v2_moments WHERE fixture_id = %s", scene.fid)
    assert scene.main(k - timedelta(minutes=8)).runs == {}, "no E4 before T-5"
    rep = scene.main(k - timedelta(minutes=4))
    assert rep.runs == {"E4": 1} and not rep.alerts and rep.last_decisions == 0, rep.as_json()
    (e4_run,) = scene.rows("SELECT * FROM intel.eval_runs WHERE fixture_id = %s AND evaluation = 'E4'", scene.fid)
    assert e4_run["conditions"]["reread"]["ok"] is True and e4_run["known_at"] == k - timedelta(minutes=4)
    assert not e4_run["decided"] and e4_run["decision_moment_id"] == last["id"], "E4 decides nothing: it adopts the last decision"
    assert e4_run["summary"]["decision"]["trigger"] == "E4" and e4_run["summary"]["clock"] == "eval-clock-v2"
    assert e4_run["summary"]["price"] == "releido"
    assert scalar(db, "SELECT count(*) FROM intel.decision_v2_moments WHERE fixture_id = %s", scene.fid) == moments, "nothing at T-5"
    assert scene.verdicts()[-1]["state"] == "retirada"

    # after kick-off: nothing evaluated; the chain closes, legal, under its own writer
    db.execute("UPDATE core.fixtures SET status_short = 'FT', status_group = 'finished' WHERE id = %s", (scene.fid,))
    rep = scene.main(k + timedelta(hours=2))
    assert rep.runs == {} and rep.lifecycle["illegal"] == 0 and rep.lifecycle["divergent"] == 0, rep.as_json()
    steps = [machine.Step(r["state"], r["reason"]) for r in scene.rows(
        "SELECT state, reason FROM intel.selection_lifecycle WHERE writer = %s AND fixture_id = %s ORDER BY id", chain.WRITER, scene.fid)]
    machine.check_chain(steps)
    assert [(s.state, s.reason) for s in steps] == [("detectado", "candidato_nuevo"), ("pendiente_alineaciones", "depende_de_alineacion"),
                                                     ("retirada", "alineacion_en_contra"), ("descartada", "retirada_al_saque")]
    assert scene.main(k + timedelta(hours=3)).lifecycle["appended"] == 0, "the chain is written once"
    assert scalar(db, "SELECT count(*) FROM intel.decisions") == v1_before, "decision-v1's table does not move"
    assert scalar(db, "SELECT count(*) FROM intel.selection_lifecycle WHERE writer = %s AND reason = 'autorizada_por_dueno'",
                  chain.WRITER) == 0, "nothing is ever public: the shadow never authorises"
    for table in ("eval_runs", "eval_facts", "lineup_dependencies", "eval_verdicts", "private_alerts"):
        for sql in (f"UPDATE intel.{table} SET id = id", f"DELETE FROM intel.{table}"):
            with pytest.raises(psycopg.Error), db.transaction():
                db.execute(sql)


def test_the_line_up_with_the_striker_confirms(scene: Scene) -> None:
    k = scene.k
    scene.main(k - timedelta(hours=13))
    scene.price(k - timedelta(minutes=25))
    scene.line_up(k - timedelta(minutes=19), with_striker=True)
    rep = scene.e3(k - timedelta(minutes=18))
    assert rep.runs == {"E3": 1} and not rep.alerts, rep.as_json()
    e3 = scene.verdicts()[-1]
    assert (e3["verdict"], e3["state"], e3["cause"]) == ("confirmada", "confirmada_sombra", "alineacion_confirma"), e3
    assert scene.striker in e3["lineup"]["starting"] and not e3["lineup"]["missing"], e3["lineup"]
    # the striker plays: his own shift is up, but the scene's other listed starters rate below their replacement, so the sum of the
    # table's shifts is small either way; what the E3 must hold is that the figure did not move materially (it confirms)
    assert abs(float(e3["p_after"]) - float(e3["p_before"])) < 0.02, e3


def test_no_line_up_raises_sin_alineacion_at_e4_and_closes_without_it(scene: Scene) -> None:
    k = scene.k
    scene.main(k - timedelta(hours=13))
    scene.price(k - timedelta(minutes=25))
    assert scene.e3(k - timedelta(minutes=16)).runs == {}, "no line-up, no E3"
    rep = scene.main(k - timedelta(minutes=15))
    assert rep.runs == {} and rep.last_decisions == 1, rep.as_json()
    scene.price(k - timedelta(minutes=6), odds=2.30)
    rep = scene.main(k - timedelta(minutes=4))
    assert rep.runs == {"E4": 1} and rep.alerts == {"sin_alineacion": 1}, rep.as_json()
    (alert,) = scene.rows("SELECT * FROM intel.private_alerts WHERE fixture_id = %s", scene.fid)
    assert alert["after"]["line_up"] == "sin_alineacion_oficial" and alert["after"]["sides_missing"] == ["away", "home"]
    assert alert["after"]["minutes_to_kickoff"] == 4.0
    verdict = scene.verdicts()[-1]
    assert verdict["verdict"] == "pendiente", "never confirmed blind"
    (kept,) = scene.rows("SELECT d.id FROM intel.decisions_v2 d JOIN intel.decision_v2_moments m ON m.id = d.moment_id "
                         "WHERE m.fixture_id = %s AND m.trigger = 'E4' AND d.market_key = 'OU' AND d.selection = 'Over'", scene.fid)
    assert verdict["decision_id"] == kept["id"], "judged with decision-v2's last decision"
    assert float(verdict["odds_after"]) == 2.30, "at the price read again at T-4, not the one it was decided at"
    scene.db.execute("UPDATE core.fixtures SET status_short = 'FT', status_group = 'finished' WHERE id = %s", (scene.fid,))
    scene.main(k + timedelta(hours=2))
    last = scene.rows("SELECT state, reason FROM intel.selection_lifecycle WHERE writer = %s AND fixture_id = %s ORDER BY id DESC LIMIT 1",
                      chain.WRITER, scene.fid)
    assert last == [{"state": "descartada", "reason": "sin_alineacion_a_tiempo"}]


def test_a_kick_off_brought_forward_is_an_alert_once_and_nothing_runs_after_kick_off(scene: Scene) -> None:
    k = scene.k
    scene.main(k - timedelta(hours=13))
    scene.db.execute("UPDATE core.fixtures SET kickoff_at = %s WHERE id = %s", (k - timedelta(hours=2), scene.fid))
    rep = scene.main(k - timedelta(hours=8))
    assert rep.alerts == {"cambio_horario": 1}, rep.as_json()
    (alert,) = scene.rows("SELECT * FROM intel.private_alerts WHERE fixture_id = %s", scene.fid)
    assert alert["cause"] == "saque_adelantado" and alert["before"] == {"kickoff_at": k.isoformat()}
    assert alert["after"] == {"kickoff_at": (k - timedelta(hours=2)).isoformat()} and alert["market_key"] is None
    assert scene.main(k - timedelta(hours=7)).alerts == {}, "an alert is written once"
    (item,) = alerts_svc.build(scene.db, at=k - timedelta(hours=7), hours=720).alerts.items
    assert item.kind == "cambio_horario" and item.cause == "saque_adelantado" and item.before.shape == "saque"
    scene.line_up(k - timedelta(hours=2, minutes=20), with_striker=False)
    assert scene.e3(k - timedelta(hours=1)).runs == {}, "after the (new) kick-off nothing is evaluated"
    assert scene.main(k - timedelta(hours=1)).runs == {}


def test_e3_reads_an_arrival_of_the_watch_from_its_raw_answer_when_no_sheet_was_stored(scene: Scene, tmp_path: Any) -> None:
    """In the shadow the line-up watch (IA-069) records arrivals and writes no sheet: E3 reads the starters from the RAW answer."""
    from fbi.storage.payload_store import PayloadStore

    db, k = scene.db, scene.k
    scene.main(k - timedelta(hours=13))
    scene.price(k - timedelta(minutes=25))
    pf, home_p, away_p = (scalar(db, "SELECT provider_fixture_id FROM core.fixtures WHERE id = %s", scene.fid),
                          scalar(db, "SELECT provider_team_id FROM core.teams WHERE id = %s", scene.w.home),
                          scalar(db, "SELECT provider_team_id FROM core.teams WHERE id = %s", scene.w.away))
    home = [0, 1, 2, 3, 4, 5, 6, 7, 8, 10, 12]

    def xi(team: int, js: list[int]) -> list[dict[str, Any]]:
        return [{"player": {"id": scene.w.man(team, j), "name": f"P{j}", "number": j, "pos": "M", "grid": None}} for j in js]

    body = {"response": [{"fixture": {"id": pf}, "lineups": [
        {"team": {"id": home_p}, "formation": "4-4-2", "coach": {"id": 1, "name": "C"}, "startXI": xi(scene.w.home, home),
         "substitutes": xi(scene.w.home, [9])},
        {"team": {"id": away_p}, "formation": "4-4-2", "coach": {"id": 2, "name": "D"}, "startXI": xi(scene.w.away, list(range(11))),
         "substitutes": []}]}]}
    seen = k - timedelta(minutes=19)
    store = PayloadStore(tmp_path)
    stored = store.store(endpoint="/fixtures", params={"ids": str(pf)}, fetched_at=seen, http_status=200, body=body)
    db.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, fetched_at, http_status, file_path, bytes) "
               "VALUES (%s, %s, '/fixtures', %s, 200, %s, 1) ON CONFLICT DO NOTHING", (stored.hash, scene.seed.run_id, seen, stored.file_path))
    for side in ("home", "away"):
        db.execute("INSERT INTO core.fixture_lineup_arrivals (fixture_id, team_side, source, observed_at, kickoff_at, content_hash, "
                   "starters_hash, starters, players, formation, channel, payload_hash) VALUES (%s, %s, 'api-football', %s, %s, %s, %s, 11, "
                   "12, '4-4-2', 'lineup_watch', %s)", (scene.fid, side, seen, k, ("a" if side == "home" else "b") * 64, ("c" if side == "home" else "d") * 64, stored.hash))
    rep = run.run_line_ups(db, now=seen + timedelta(seconds=45), store=store, config=CONFIG, commit=False)
    assert rep.runs == {"E3": 1} and rep.alerts == {"retirada": 1} and not rep.errors, rep.as_json()
    (e3_run,) = scene.rows("SELECT lineup, trigger_at, latency_ms FROM intel.eval_runs WHERE fixture_id = %s AND evaluation = 'E3'",
                           scene.fid)
    assert e3_run["lineup"]["source"] == {"home": "raw", "away": "raw"} and e3_run["trigger_at"] == seen
    assert e3_run["latency_ms"] < 120_000 and len(e3_run["lineup"]["arrivals"]) == 2
    assert scene.verdicts()[-1]["reason"] == "alineacion_en_contra"
