"""ctx-adj-v1 and state-v2 on a real database (plan IA, P0): rows of ``intel.decisions`` and of ``ai.pick_reviews`` written by hand, in the shapes
``fbi.intel.decision.store`` and ``fbi.ai.orchestrator.write_review`` write them, and the two reports read over them. Everything is rolled back; the
reports only read.

The world, one match at 22:00 UTC (17:00 in Bogotá) and its decisions at 12:00 UTC:

    1X2 Home  APROBADO          ma-v1 REJECT at 11:00 (BLOQUEA)        ma-v1-h not answered (SIN_COUNCIL)   + the same at T-90m, 17:00
    1X2 Away  CAUTELA           ma-v1 DOWNGRADE at 11:30, and an APPROVE at 12:30 - after the decision, never seen
    1X2 Draw  INVESTIGACION     ma-v1 APPROVE (CONFIRMA)                                   reason price_stale -> WATCH; an older RECHAZADO
    DC  1X    CANDIDATO_PARLAY  ma-v1 with a driver cd-v1 does not have (refused)
    DC  X2    APROBADO          ma-v1 ABSTAIN 16 h before the decision (out of the 12 h; FALTA_INFO with no limit)
    DC  12    INVESTIGACION     reasons nobody knows -> ABSTAIN unclassified
    OU  Over  INVESTIGACION     not_calibrated -> ABSTAIN
    a decision of the families (decision-fam-v1) on the same match: in neither report
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb
from scripts import ia_ctx_shadow, ia_state_v2

from fbi.ai import orchestrator
from fbi.core.decision_versions import DECISION_CORE, DECISION_FAMILIES
from fbi.intel import context_adjustment as ctx
from fbi.intel import state_v2

from .conftest import Seed

KICKOFF = datetime(2032, 11, 10, 22, 0, tzinfo=UTC)
AT = datetime(2032, 11, 10, 12, 0, tzinfo=UTC)
DAY = date(2032, 11, 10)

DECISION_SQL = (
    "INSERT INTO intel.decisions (decision_version, known_at, checkpoint, fixture_id, kickoff_at, market_key, selection, line, model_name, odds, "
    "p_model, p_cal, p_market, filters, state, reasons, context_status, input_hash, evidence_ids) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'dixon_coles', 2.05, 0.55, 0.55, 0.47, %s, %s, %s, 'PARTIAL', %s, '{}') RETURNING id")
REVIEW_SQL = (
    "INSERT INTO ai.pick_reviews (reviewed_at, fixture_id, market_key, selection, line, engine, engine_version, provider, model, input_hash, "
    "decision, confidence, output, mode, status, evidence_ids, error) "
    "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'shadow', %s, %s, %s) RETURNING id")


class World:
    def __init__(self, db: psycopg.Connection[Any], seed: Seed) -> None:
        self.db = db
        self.n = 0
        with db.cursor() as cur:
            cur.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at) "
                        "VALUES (990101, %s, %s, %s, %s) RETURNING id", (seed.season_id, seed.home_team_id, seed.away_team_id, KICKOFF))
            row = cur.fetchone()
        assert row is not None
        self.fixture = int(row[0])

    def decision(self, market: str, selection: str, state: str, *, at: datetime = AT, checkpoint: str = "T-12h",
                 reasons: tuple[str, ...] = (), filters: list[dict[str, Any]] | None = None, version: str = DECISION_CORE,
                 line: float = 0) -> int:
        self.n += 1
        with self.db.cursor() as cur:
            cur.execute(DECISION_SQL, (version, at, checkpoint, self.fixture, KICKOFF, market, selection, line, Jsonb(filters or []), state,
                                       list(reasons), f"h{self.n}"))
            row = cur.fetchone()
        assert row is not None
        return int(row[0])

    def review(self, market: str, selection: str, *, engine: str = "ma-v1", verdict: str = "APPROVE", at: datetime, status: str = "ok",
               drivers: tuple[str, ...] = ("FORM",), risks: tuple[str, ...] = ()) -> int:
        self.n += 1
        out: dict[str, Any] = {"version": orchestrator.VERSION, "engine": engine, "arm": engine, "contract": "cd-v1", "candidate": "c1", "round": 1,
                               "prompts": {"council": "council-v1"}, "contradictions": [], "fair_odds": 1.9, "minimum_playable_odds": 2.0,
                               "research_ask_ignored": 0, "assessment": {"match_evaluation": "SUPPORT"}}
        if status == "ok":
            out |= {"verdict": verdict, "confidence_level": "MEDIUM", "confidence": "0.60", "drivers": list(drivers), "risks": list(risks),
                    "refs": ["A:match_evaluation", "E:3"], "model": "claude-sonnet-5-5", "paths": []}
            conf, model, evidence, error = orchestrator.confidence_value("MEDIUM"), "claude-sonnet-5-5", [3], None
        else:
            out |= {"verdict": "ABSTAIN", "confidence": "0", "reason": "paused:budget", "status": status}
            conf, model, evidence, error = orchestrator.confidence_value(None), None, [], "paused:budget"
        with self.db.cursor() as cur:
            cur.execute(REVIEW_SQL, (at, self.fixture, market, selection, 0, engine, orchestrator.engine_version(engine, with_stats=False),
                                     "anthropic" if model else None, model, f"r{self.n}", verdict if status == "ok" else "ABSTAIN", conf, Jsonb(out),
                                     status, evidence, error))
            row = cur.fetchone()
        assert row is not None
        return int(row[0])


@pytest.fixture()
def world(db: psycopg.Connection[Any], seed: Seed) -> dict[str, Any]:
    w = World(db, seed)
    ids: dict[str, Any] = {"w": w}
    ids["home"] = w.decision("1X2", "Home", "APROBADO", reasons=())
    ids["home_t90"] = w.decision("1X2", "Home", "APROBADO", at=AT + timedelta(hours=5), checkpoint="T-90m")
    ids["away"] = w.decision("1X2", "Away", "CAUTELA", reasons=("risk",))
    w.decision("1X2", "Draw", "RECHAZADO", at=AT - timedelta(hours=1), reasons=("ev_cal_below",))
    ids["draw"] = w.decision("1X2", "Draw", "INVESTIGACION", reasons=("price_stale",),
                             filters=[{"n": 3, "key": "market", "ok": False, "why": "precio de hace 4.0 h", "effect": "INVESTIGACION"}])
    ids["dc1x"] = w.decision("DC", "1X", "CANDIDATO_PARLAY")
    ids["dcx2"] = w.decision("DC", "X2", "APROBADO")
    ids["dc12"] = w.decision("DC", "12", "INVESTIGACION", reasons=("a_reason_of_tomorrow",))
    ids["over"] = w.decision("OU", "Over", "INVESTIGACION", reasons=("not_calibrated", "ev_unknown"), line=2.5)
    w.decision("1X2", "Home", "INVESTIGACION", version=DECISION_FAMILIES, reasons=("family_research",))
    ids["r_home"] = w.review("1X2", "Home", verdict="REJECT", at=AT - timedelta(hours=1), risks=("KEY_ABSENCE_OPEN",))
    w.review("1X2", "Home", engine="ma-v1-h", at=AT - timedelta(hours=1), status="fallback")
    w.review("1X2", "Away", verdict="DOWNGRADE", at=AT - timedelta(minutes=30))
    w.review("1X2", "Away", verdict="APPROVE", at=AT + timedelta(minutes=30))
    w.review("1X2", "Draw", verdict="APPROVE", at=AT - timedelta(hours=2))
    ids["r_bad"] = w.review("DC", "1X", verdict="APPROVE", at=AT - timedelta(hours=1), drivers=("VIBES",))
    w.review("DC", "X2", verdict="ABSTAIN", at=AT - timedelta(hours=16))
    return ids


def test_the_as_of_reader_sees_nothing_reviewed_after_the_moment(db: psycopg.Connection[Any], world: dict[str, Any]) -> None:
    fixture = world["w"].fixture
    seen = ctx.adjustments_for(db, at=AT, fixture_ids=[fixture])
    away = seen.adjustments[((fixture, "1X2", "Away", ctx.LINE_Q * 0), "ma-v1")]
    assert away.verdict == "RESERVA" and away.known_at == AT - timedelta(minutes=30)
    later = ctx.adjustments_for(db, at=AT + timedelta(hours=1), fixture_ids=[fixture])
    assert later.adjustments[((fixture, "1X2", "Away", ctx.LINE_Q * 0), "ma-v1")].verdict == "CONFIRMA"
    assert [r.review_id for r in seen.refused] == [world["r_bad"]] and "drivers" in seen.refused[0].why
    assert ((fixture, "DC", "X2", ctx.LINE_Q * 0), "ma-v1") not in seen.adjustments, "16 h old: beyond filter 6's twelve hours"
    unlimited = ctx.adjustments_for(db, at=AT, fixture_ids=[fixture], max_age=None)
    assert unlimited.adjustments[((fixture, "DC", "X2", ctx.LINE_Q * 0), "ma-v1")].verdict == "FALTA_INFO"
    only_h = ctx.adjustments_for(db, at=AT, fixture_ids=[fixture], engines=("ma-v1-h",))
    assert {e for _, e in only_h.adjustments} == {"ma-v1-h"} and only_h.refused == ()
    assert ctx.adjustments_for(db, at=AT, fixture_ids=[]).adjustments == {}


def test_the_shadow_report_compares_decision_v1_with_the_proposed_effect(db: psycopg.Connection[Any], world: dict[str, Any]) -> None:
    doc, code = ia_ctx_shadow.run(db, first=DAY, last=DAY)
    assert code == ia_ctx_shadow.OK
    assert doc["decisions"] == 9, "the core layer only (the older RECHAZADO of the draw included): the family's decision is not read"
    m = doc["engines"]["ma-v1"]
    assert (m["rows"], m["refused"], m["judged"], m["with_review"]) == (9, 1, 8, 5)
    assert m["by_verdict"] == {"CONFIRMA": 2, "RESERVA": 1, "BLOQUEA": 2, "FALTA_INFO": 0, "SIN_COUNCIL": 3}
    assert m["agreement"] == {"n": 8, "agree": 6, "rate": 0.75}
    assert m["agreement_with_council"] == {"n": 5, "agree": 3, "rate": 0.6}
    assert m["confusion"]["APROBADO"] == {"APROBADO": 1, "RECHAZADO": 2}
    assert m["confusion"]["CAUTELA"] == {"CAUTELA": 1} and m["confusion"]["INVESTIGACION"] == {"INVESTIGACION": 3}
    assert m["confusion"]["RECHAZADO"] == {"RECHAZADO": 1}
    held = {(h["decision_id"], h["proposed"], h["verdict"]) for h in m["held_back"]}
    assert held == {(world["home"], "RECHAZADO", "BLOQUEA"), (world["home_t90"], "RECHAZADO", "BLOQUEA")}
    assert all(h["review_id"] == world["r_home"] and h["factor_codes"] == ["FORM", "KEY_ABSENCE_OPEN"] for h in m["held_back"])
    assert m["refused_rows"] == [{"decision_id": world["dc1x"], "review_id": world["r_bad"], "why": m["refused_rows"][0]["why"]}]
    h = doc["engines"]["ma-v1-h"]
    assert h["by_verdict"]["SIN_COUNCIL"] == 9 and h["with_review"] == 2 and h["held_back"] == [] and h["agreement"]["rate"] == 1.0
    text = ia_ctx_shadow.render(doc)
    assert "## ma-v1: 9 rows, 5 with a review, 1 refused" in text and "APROBADO -> RECHAZADO (BLOQUEA, bloqueante" in text


def test_without_an_age_limit_the_old_abstain_holds_an_approval_back(db: psycopg.Connection[Any], world: dict[str, Any]) -> None:
    doc, _ = ia_ctx_shadow.run(db, first=DAY, last=DAY, engines=("ma-v1",), max_age=None)
    m = doc["engines"]["ma-v1"]
    assert list(doc["engines"]) == ["ma-v1"] and doc["max_age_hours"] is None
    assert (world["dcx2"], "INVESTIGACION", "FALTA_INFO") in {(x["decision_id"], x["proposed"], x["verdict"]) for x in m["held_back"]}
    assert "no age limit" in ia_ctx_shadow.render(doc)


def test_the_shadow_report_of_a_bad_window_cannot_run(db: psycopg.Connection[Any]) -> None:
    doc, code = ia_ctx_shadow.run(db, first=DAY, last=DAY - timedelta(days=1))
    assert code == ia_ctx_shadow.CANNOT and "error" in doc


def test_the_state_v2_report_of_the_day(db: psycopg.Connection[Any], world: dict[str, Any]) -> None:
    doc, code = ia_state_v2.run(db, day=DAY)
    assert code == ia_state_v2.OK
    assert doc["rows"] == 8, "the newest per selection and checkpoint: the older RECHAZADO of the draw and the family's row are not read"
    assert doc["by_state"] == {"RECOMMENDED": 4, "CAUTION": 1, "WATCH": 1, "ABSTAIN": 2, "REJECTED": 0}
    assert doc["by_reason"]["ABSTAIN"] == {"not_calibrated": 1, "unclassified": 1}
    assert doc["by_reason"]["WATCH"] == {"price_stale": 1} and doc["by_reason"]["CAUTION"] == {"risk": 1}
    assert doc["labels"] == {"APROBADO": 3, "CANDIDATO_PARLAY": 1}
    assert doc["crosswalk"]["INVESTIGACION"] == {"ABSTAIN": 2, "WATCH": 1}
    assert doc["unclassified"] == 1 and doc["unclassified_rows"][0]["decision_id"] == world["dc12"]
    text = ia_state_v2.render(doc)
    assert "unclassified: 1" in text and "a_reason_of_tomorrow" in text
    other = state_v2.day_report(db, day=DAY + timedelta(days=1))
    assert other["rows"] == 0 and other["unclassified"] == 0


def test_the_commands_run_read_only_from_the_command_line(migrated_database: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert ia_state_v2.main(["report", "--day", "2032-11-10", "--json", "--dsn", migrated_database]) == 0
    assert '"version": "state-v2"' in capsys.readouterr().out
    assert ia_ctx_shadow.main(["report", "--from", "2032-11-10", "--to", "2032-11-10", "--engine", "ma-v1-h", "--dsn", migrated_database]) == 0
    assert "## ma-v1-h: 0 rows" in capsys.readouterr().out
    assert ia_ctx_shadow.main(["report", "--from", "2032-11-11", "--to", "2032-11-10", "--dsn", migrated_database]) == ia_ctx_shadow.CANNOT
