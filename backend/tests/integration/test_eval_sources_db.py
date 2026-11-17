"""The facts each evaluation used (IA-122, AD-G08, contract C-07) against PostgreSQL, on the evaluation cycle's own scene (a striker an
«over 2.5» depends on):

* E1 writes its list in its own transaction: the striker's start, quoted by name, dated after the previous match, links ``a_favor`` of the over;
  the same news by surname alone is a homonym (another player of the match shares it); a club's news of the week before is out of the
  window; a rumour is listed as not used; a model's summary is not a literal quote; a fact seen after E1 is not in E1's list - and every
  row says it was known before the decision;
* the next E2 lists the new fact, and C-07's private answer reads the newest list; the public one does not exist (switch off, and nothing
  published);
* the database refuses a list or a fact written after its evaluation (another transaction), for a failed evaluation, with another moment, or
  with a fact known after the decision; both tables are append-only;
* revision 0160 goes up on 0159 and back down clean.

Every pass runs inside the test's transaction (``commit=False``), so nothing outlives it - except the migration's scratch database."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from psycopg.types.json import Jsonb

from fbi.api.problem import ApiError
from fbi.api.services import analysis_sources
from fbi.factlinks import views

from .conftest import ADMIN_URL, REPO_ROOT, TEST_DB, Seed, _dsn
from .test_eval_cycle_shadow import Scene, scalar

pytestmark = pytest.mark.integration


def web(db: psycopg.Connection[Any], scene: Scene, *, claim: str, at: datetime, published: datetime | None, player: int | None = None,
        team: int | None = None, status: str = "CONFIRMED", tier: str = "club", kind: str = "injury", assertion: str = "out",
        literal: bool = True, key: str) -> int:
    attributes = {"assertion": assertion, **({"quote_checked": True} if literal else {})}
    return int(scalar(db, "INSERT INTO ai.evidence (fixture_id, team_id, provider_player_id, kind, claim, origin, source_name, source_url, "
                      "source_tier, published_at, retrieved_at, story_key, content_hash, confidence, relevance, attributes, status, "
                      "status_reason, status_changed_at) VALUES (%s, %s, %s, %s, %s, 'web', 'Fuente Ejemplo', %s, %s, %s, %s, %s, %s, 0.5, 0.6, "
                      "%s, %s, 'test', %s) RETURNING id", scene.fid, team, player, kind, claim, f"https://fuente.ejemplo.invalid/{key}", tier,
                      published, at, f"web:{scene.fid}:{key}", key, Jsonb(attributes), status, at))


def sources(scene: Scene, evaluation: str) -> dict[int, dict[str, Any]]:
    rows = scene.rows("SELECT s.* FROM intel.eval_sources s JOIN intel.eval_runs r ON r.id = s.run_id "
                      "WHERE s.fixture_id = %s AND r.evaluation = %s", scene.fid, evaluation)
    return {int(r["evidence_id"]): r for r in rows}


@pytest.fixture()
def scene(db: psycopg.Connection[Any], seed: Seed) -> Scene:
    s = Scene(db, seed)
    db.execute("INSERT INTO core.players (provider_player_id, name) VALUES (%s, 'Marco Ejemplo'), (%s, 'Rui Ejemplo')",
               (s.striker, s.w.man(s.w.away, 9)))
    return s


def test_each_evaluation_writes_its_facts_with_it_and_c07_reads_them(scene: Scene, db: psycopg.Connection[Any]) -> None:
    k = scene.k
    e1_at = k - timedelta(hours=13)
    linked = web(db, scene, claim="Marco Ejemplo será titular ante el Liverpool", at=e1_at - timedelta(hours=1),
                 published=e1_at - timedelta(hours=2), player=scene.striker, team=scene.w.home, kind="lineup", assertion="starts",
                 key="titular")
    homonym = web(db, scene, claim="Ejemplo, baja para el partido", at=e1_at - timedelta(hours=1), published=e1_at - timedelta(hours=2),
                  player=scene.striker, team=scene.w.home, key="apellido")
    old = web(db, scene, claim="El Manchester United presenta su nueva equipación", at=e1_at - timedelta(hours=1),
              published=k - timedelta(days=10), team=scene.w.home, kind="news", assertion="info", key="semana-pasada")
    rumour = web(db, scene, claim="El Liverpool ficharía un extremo", at=e1_at - timedelta(hours=1), published=e1_at - timedelta(hours=3),
                 team=scene.w.away, status="RUMOR", tier="media", kind="transfer", assertion="info", key="rumor")
    summary = web(db, scene, claim="Según la prensa, Marco Ejemplo es baja", at=e1_at - timedelta(hours=1),
                  published=e1_at - timedelta(hours=2), player=scene.striker, team=scene.w.home, literal=False, key="resumen")
    later = web(db, scene, claim="Marco Ejemplo entrenó aparte", at=e1_at + timedelta(minutes=10), published=e1_at + timedelta(minutes=5),
                player=scene.striker, team=scene.w.home, status="PROBABLE", tier="media", assertion="doubtful", key="despues")

    rep = scene.main(e1_at)
    assert rep.runs == {"E1": 1} and rep.sources == {"lists": 1, "linked": 2, "refused": 3}, rep.as_json()
    (lst,) = scene.rows("SELECT * FROM intel.eval_source_lists WHERE fixture_id = %s", scene.fid)
    assert (lst["evaluation"], lst["candidates"], lst["linked"], lst["rejected"], lst["version"]) == ("E1", 5, 2, 3, "link-v1")
    (dep,) = scene.rows("SELECT players FROM intel.lineup_dependencies WHERE fixture_id = %s", scene.fid)
    (striker,) = [p for p in dep["players"] if p["provider_player_id"] == scene.striker]
    assert striker["shift_full"] >= 0.02, striker
    assert lst["by_relation"] == {"a_favor": 1, "no_usada": 1}
    e1 = sources(scene, "E1")
    assert later not in e1, "a fact seen after the moment of E1 does not exist for it"
    assert (e1[linked]["relation"], e1[linked]["level"], e1[linked]["entity_type"], e1[linked]["named_as"]) == (
        "a_favor", "oficial", "player", "marco ejemplo")
    assert e1[linked]["selections"] == [{"market_key": "OU", "selection": "Over", "line": "2.50", "relation": "a_favor",
                                         "shift": round(striker["shift_full"], 4)}], "his start raises the over he holds up"
    assert e1[homonym]["rejection"] == "homonimo" and e1[homonym]["relation"] is None
    assert e1[old]["rejection"] == "fuera_de_ventana", "a club's news of the week before is not this match's"
    assert (e1[rumour]["relation"], e1[rumour]["level"]) == ("no_usada", "rumor")
    assert e1[summary]["rejection"] == "sin_cita_literal"
    assert all(r["fact_known_at"] <= r["decided_at"] == e1_at for r in e1.values())

    # the next E2 lists the new fact; C-07's private answer reads the newest list
    rep = scene.main(k - timedelta(hours=5))
    assert rep.runs == {"E2": 1} and rep.sources["lists"] == 1, rep.as_json()
    e2 = sources(scene, "E2")
    expected = "en_contra" if striker["shift_without"] <= -0.02 else "contexto"
    assert later in e2 and (e2[later]["relation"], e2[later]["level"], e2[later]["e2_action"]) == (expected, "un_medio", "recalcula")
    answer = analysis_sources.build(db, scene.fid, at=k - timedelta(hours=4))
    assert answer.evaluation == "E2" and [e.evaluation for e in answer.evaluations.items] == ["E2", "E1"]
    assert {f.evidence_id for f in answer.facts.items} == {linked, rumour, later}
    assert {r.evidence_id: r.rejection for r in answer.refused.items} == {homonym: "homonimo", old: "fuera_de_ventana",
                                                                          summary: "sin_cita_literal"}
    assert next(f for f in answer.facts.items if f.evidence_id == linked).fact_es == "Marco Ejemplo: titular"
    assert all(f.known_at <= answer.evaluated_at for f in answer.facts.items)  # type: ignore[operator]
    with pytest.raises(ApiError) as off:
        analysis_sources.public(db, scene.fid, at=k - timedelta(hours=4))
    assert off.value.status == 404, "FBI_MATCH_INTELLIGENCE is off (and nothing is published)"
    coverage = views.lists(db, scene.fid, until=k)
    assert len(coverage) == 2


def test_the_database_refuses_a_relation_written_after_its_evaluation(scene: Scene, db: psycopg.Connection[Any]) -> None:
    k = scene.k
    run_id = int(scalar(db, "INSERT INTO intel.eval_runs (fixture_id, evaluation, evaluation_version, cause, cause_key, known_at, kickoff_at, "
                        "finished_at, status, decided, conditions, version, created_at) VALUES (%s, 'E1', 1, 'ventana', 'ventana', %s, %s, %s, "
                        "'completa', false, '{}', 'eval-cycle-v1', now() - interval '1 second') RETURNING id",
                        scene.fid, k - timedelta(hours=13), k, k - timedelta(hours=13)))
    lst = ("INSERT INTO intel.eval_source_lists (run_id, fixture_id, evaluation, evaluation_version, known_at, candidates, linked, rejected, "
           "version) VALUES (%s, %s, %s, 1, %s, 0, 0, 0, 'link-v1') RETURNING id")
    with pytest.raises(psycopg.errors.CheckViolation, match="never afterwards"), db.transaction():
        db.execute(lst, (run_id, scene.fid, "E1", k - timedelta(hours=13)))

    now_run = int(scalar(db, "INSERT INTO intel.eval_runs (fixture_id, evaluation, evaluation_version, cause, cause_key, known_at, kickoff_at, "
                         "finished_at, status, decided, conditions, version) VALUES (%s, 'E1', 1, 'ventana', 'prueba-2', %s, %s, %s, 'completa', "
                         "false, '{}', 'eval-cycle-v1') RETURNING id", scene.fid, k - timedelta(hours=12), k, k - timedelta(hours=12)))
    with pytest.raises(psycopg.errors.CheckViolation, match="another moment"), db.transaction():
        db.execute(lst, (now_run, scene.fid, "E1", k - timedelta(hours=11)))
    with pytest.raises(psycopg.errors.CheckViolation, match="another moment"), db.transaction():
        db.execute(lst, (now_run, scene.fid, "E2", k - timedelta(hours=12)))
    list_id = int(scalar(db, lst, now_run, scene.fid, "E1", k - timedelta(hours=12)))
    fact = ("INSERT INTO intel.eval_sources (list_id, run_id, fixture_id, evidence_id, linked, relation, level, entity_type, entity_id, "
            "named_as, kind, source_name, source_tier, source_type, fact_at, fact_known_at, decided_at, version) VALUES "
            "(%s, %s, %s, 1, true, 'contexto', 'un_medio', 'team', %s, 'manchester united', 'news', 'Fuente', 'media', 'prensa', %s, %s, %s, "
            "'link-v1')")
    decided = k - timedelta(hours=12)
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        db.execute(fact, (list_id, now_run, scene.fid, scene.w.home, decided, decided + timedelta(minutes=1), decided))
    with pytest.raises(psycopg.errors.CheckViolation, match="decided_at"), db.transaction():
        db.execute(fact, (list_id, now_run, scene.fid, scene.w.home, decided - timedelta(hours=1), decided - timedelta(hours=1),
                          decided + timedelta(minutes=1)))
    with pytest.raises(psycopg.errors.CheckViolation, match="a_rumour_is_not_used"), db.transaction():
        db.execute(fact.replace("'un_medio'", "'rumor'"), (list_id, now_run, scene.fid, scene.w.home, decided - timedelta(hours=1),
                                                           decided - timedelta(hours=1), decided))
    db.execute(fact, (list_id, now_run, scene.fid, scene.w.home, decided - timedelta(hours=1), decided - timedelta(hours=1), decided))
    for sql in ("UPDATE intel.eval_sources SET relation = 'a_favor'", "DELETE FROM intel.eval_sources",
                "UPDATE intel.eval_source_lists SET linked = 1", "DELETE FROM intel.eval_source_lists"):
        with pytest.raises(psycopg.Error), db.transaction():
            db.execute(sql)

    failed = int(scalar(db, "INSERT INTO intel.eval_runs (fixture_id, evaluation, evaluation_version, cause, cause_key, known_at, kickoff_at, "
                        "finished_at, status, decided, conditions, error, version) VALUES (%s, 'E4', 1, 'ventana', 'ventana', %s, %s, %s, "
                        "'fallida', false, '{}', 'LookupError', 'eval-cycle-v1') RETURNING id",
                        scene.fid, k - timedelta(minutes=15), k, k - timedelta(minutes=15)))
    with pytest.raises(psycopg.errors.CheckViolation, match="failed evaluation"), db.transaction():
        db.execute(lst, (failed, scene.fid, "E4", k - timedelta(minutes=15)))


# ── the migration ────────────────────────────────────────────────────────────────────────────────────────────────────

SCRATCH = f"{TEST_DB}_m0160"


def _cfg() -> Config:
    cfg = Config(os.path.join(REPO_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(REPO_ROOT, "migrations"))
    return cfg


def _drop() -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()", (SCRATCH,))
        admin.execute(f'DROP DATABASE IF EXISTS "{SCRATCH}"')


@contextmanager
def scratch() -> Iterator[str]:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), "0159")
        yield dsn
    finally:
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
        _drop()


def tables(c: psycopg.Connection[Any]) -> set[str]:
    return {r[0] for r in c.execute("SELECT table_name FROM information_schema.tables WHERE table_schema = 'intel'").fetchall()}


def test_0160_goes_up_on_0159_with_two_append_only_tables_and_back_down_clean() -> None:
    with scratch() as dsn:
        with psycopg.connect(dsn) as c:
            before = tables(c)
        command.upgrade(_cfg(), "0160")
        with psycopg.connect(dsn) as c:
            assert tables(c) - before == {"eval_source_lists", "eval_sources"}
            triggers = {r[0] for r in c.execute("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal AND tgrelid IN "
                                                "('intel.eval_sources'::regclass, 'intel.eval_source_lists'::regclass)").fetchall()}
            assert triggers == {"eval_sources_at_decision", "eval_sources_append_only", "eval_source_lists_at_decision",
                                "eval_source_lists_append_only"}
        command.downgrade(_cfg(), "0159")
        with psycopg.connect(dsn) as c:
            assert tables(c) == before
            assert c.execute("SELECT to_regprocedure('intel.eval_sources_at_decision()')").fetchone() == (None,)
