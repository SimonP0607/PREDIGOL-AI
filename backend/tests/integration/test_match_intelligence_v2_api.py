"""C-01 2.0.0 (AD-J02 delivery 2, IA-131) against a real database: the statements of every block run on the pieces' own tables (revisions
0147, 0155, 0156, 0160, 0163), the owner reads each shadow block, a reader gets none of it, and the 1.x routes answer as before."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb

from fbi.api.contracts.intelligence.match_v2 import MatchIntelligenceV2, MatchIntelligenceV2Private
from fbi.api.contracts.intelligence.projection import leaks
from fbi.api.switches import MATCH_INTELLIGENCE
from tests.integration.test_match_forecast import AT, KO, World, world  # noqa: F401  (the fixture and the data)
from tests.integration.test_match_intelligence_api import client, stored_match

pytestmark = pytest.mark.integration


def shadow_rows(db: psycopg.Connection[Any], fid: int) -> None:
    """One scenarios reading of the match's season, one verified chronicle and one E1."""
    row = db.execute("SELECT f.competition_season_id, f.home_team_id, cs.season, c.provider_league_id FROM core.fixtures f "
                     "JOIN core.competition_seasons cs ON cs.id = f.competition_season_id "
                     "JOIN core.competitions c ON c.id = cs.competition_id WHERE f.id = %s", (fid,)).fetchone()
    assert row is not None
    cs, home, season, league = row
    fresh = datetime.now(UTC) - timedelta(hours=1)  # the answer is read now: a reading older than 3 days is not «what is at stake now»
    reading = {"version": "scenarios-v2", "at": fresh.isoformat(), "status": "ok", "rules": {"version": 1},
               "contradicciones": 0, "teams": {},
               "tables": [{"key": "liga", "teams": [{"team": home, "objetivos": [{
                   "objetivo": "titulo", "puestos": [1, 1], "terminar_entre_los": 1, "condicional": False, "estado": "abierto",
                   "decidido": {"valor": False, "demostrado": False, "motivos": []}, "probabilidad": 0.25,
                   "necesita": {"puntos_actuales": 20, "puntos_maximos": 35, "partidos_restantes": 5, "puntos_que_lo_aseguran": None},
                   "depende_de": {"tipo": "de_otros", "rivales": []}}]}], "matches": {}}]}
    db.execute("INSERT INTO intel.scenario_readings (computed_at, league_id, season, competition_season_id, status, engine_version, "
               "rules_version, rules_sha256, model, sims, seed, input_hash, reading) VALUES (%s, %s, %s, %s, 'ok', 'scenarios-v2', 1, "
               "%s, 'dixon_coles:x', 2000, 1, %s, %s)",
               (fresh, league or 1, season if 1990 <= season <= 2100 else 2026, cs, "a" * 64,
                hashlib.sha256(b"r").hexdigest(), Jsonb(reading)))
    content = {"es": {"que_se_juega": [{"text": "El local pelea por el título.", "facts": ["S:home"]}]},
               "en": {"que_se_juega": [{"text": "The hosts are in the title race.", "facts": ["S:home"]}]}}
    db.execute("INSERT INTO ai.chronicles (fixture_id, created_at, plan_at, version, plan_version, classes_version, verify_version, "
               "plan_hash, plan, status, content, route) VALUES (%s, %s, %s, 'chronicle-v4', 'content-plan-v1', 'claim-classes-v1', "
               "'chronicle-verify-v1', %s, %s, 'partial', %s, 'batch')",
               (fid, AT - timedelta(minutes=20), AT - timedelta(minutes=30), "b" * 64,
                Jsonb({"sections": [{"code": "riesgos", "abstention": "SIN_RIESGOS"}]}), Jsonb(content)))
    db.execute("INSERT INTO intel.eval_runs (fixture_id, evaluation, evaluation_version, cause, cause_key, known_at, kickoff_at, "
               "finished_at, status, decided, version) VALUES (%s, 'E1', 1, 'ventana', 'E1:ventana', %s, %s, %s, 'completa', true, "
               "'eval-cycle-v1')", (fid, AT - timedelta(minutes=15), KO, AT - timedelta(minutes=15)))


def test_the_owner_reads_every_block_and_a_reader_none_of_the_shadow(
        db: psycopg.Connection[Any], world: World, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    fid = stored_match(db, world)
    shadow_rows(db, fid)
    monkeypatch.setenv(MATCH_INTELLIGENCE, "1")
    owner = client(db, "SUPER_ADMIN").get(f"/api/v1/admin/intelligence/matches/{fid}/intelligence/v2")
    assert owner.status_code == 200, owner.text
    data = MatchIntelligenceV2Private.model_validate(owner.json()["data"])
    assert data.contract_version == "2.1.0" and data.projection == "private"
    assert data.scenarios == data.chronicle == data.evaluations
    assert data.scenarios_shadow.sides[0].objectives.items[0].objective == "titulo"  # type: ignore[union-attr]
    chron = data.chronicle_shadow
    assert chron.sections[0].es == ["El local pelea por el título."]  # type: ignore[union-attr]
    assert [e.evaluation for e in data.evaluations_shadow.items] == ["E1"]  # type: ignore[union-attr]
    assert data.alerts.missing_reason == "sin_datos" and data.sources.contract == "C-07"  # type: ignore[union-attr]
    assert data.player_forecasts.missing_reason == "sin_datos"  # type: ignore[union-attr, unused-ignore]
    reader = client(db, "USER")
    public = reader.get(f"/api/v1/matches/{fid}/intelligence/v2")
    assert public.status_code == 200, public.text
    body = public.json()["data"]
    assert leaks(body, public_schema=MatchIntelligenceV2.model_json_schema(mode="serialization"),
                 private_schema=MatchIntelligenceV2Private.model_json_schema(mode="serialization")) == []
    assert body["scenarios"] == body["chronicle"] == body["evaluations"] == {"missing_reason": "pendiente_derechos"}
    assert "pelea por el título" not in public.text and "RECHAZADO" not in public.text
    assert reader.get(f"/api/v1/admin/intelligence/matches/{fid}/intelligence/v2").status_code == 403
    v1 = reader.get(f"/api/v1/matches/{fid}/intelligence")
    assert v1.status_code == 200 and v1.json()["data"]["contract_version"] == "1.1.0"
