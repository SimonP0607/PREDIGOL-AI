"""Migration 0145 and the search v2 (AD-I01/AD-I02; IA-078, IA-081): the two extensions, ``core.search_key``, the empty view
and its indexes - and nothing else; the three passes, the groups and the projection over a few fictitious names; the plan
uses the indexes; going back drops what was added. Run on a scratch database, the way production does (up to the revision under
0145, then 0145)."""

from __future__ import annotations

import os
from collections.abc import Iterator
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from fastapi.testclient import TestClient

from fbi.api.contracts.intelligence.projection import leaks, to_public
from fbi.api.contracts.intelligence.search import SearchV2, SearchV2Private
from fbi.api.repositories import search_v2 as repo
from fbi.api.services import search_v2 as service
from tests.integration.conftest import ADMIN_URL, REPO_ROOT, _dsn
from tests.integration.signed_in import SAME_SITE, principal

pytestmark = pytest.mark.integration
SCRATCH = "fbi_test_m0145"


def _cfg() -> Config:
    cfg = Config(os.path.join(REPO_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(REPO_ROOT, "migrations"))
    return cfg


def _parent() -> str:
    """The revision under 0145 (0141 today; whatever the merge re-chains it on)."""
    revision = ScriptDirectory.from_config(_cfg()).get_revision("0145")
    assert revision is not None and isinstance(revision.down_revision, str)
    return revision.down_revision


def _drop() -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s "
                      "AND pid <> pg_backend_pid()", (SCRATCH,))
        admin.execute(f'DROP DATABASE IF EXISTS "{SCRATCH}"')


def _shape(c: psycopg.Connection[Any]) -> list[tuple[Any, ...]]:
    return c.execute("SELECT table_schema, table_name, column_name, data_type, is_nullable, column_default "
                     "FROM information_schema.columns WHERE table_schema IN ('ai', 'core', 'market', 'models', 'picks', "
                     "'raw', 'customer') ORDER BY 1, 2, ordinal_position").fetchall()


def _seed(c: psycopg.Connection[Any]) -> dict[str, int]:
    def one(sql: str, *args: Any) -> int:
        row = c.execute(sql, args).fetchone()
        assert row
        return int(row[0])

    league = one("INSERT INTO core.competitions (provider_league_id, name, country, type, entity_scope, competition_type, "
                 "is_tracked) VALUES (9001, 'Liga Ficticia', 'Ejemplandia', 'league', 'club', 'domestic_league', true) "
                 "RETURNING id")
    season = one("INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, 2026) RETURNING id", league)
    venue = one("INSERT INTO core.venues (provider_venue_id, name, city, country) VALUES (9101, 'Estadio Nemesio Ejemplo', "
                "'Villaejemplo', 'Ejemplandia') RETURNING id")
    ids = {"league": league, "venue": venue}
    for key, (pid, name, national) in {"atletico": (9201, "Atlético Ejemplo", False),
                                       "deportivo": (9202, "Deportivo Ficticio", False),
                                       "national": (9203, "Ejemplandia", True)}.items():
        ids[key] = one("INSERT INTO core.teams (provider_team_id, name, country, is_national) VALUES (%s, %s, 'Ejemplandia', %s) "
                       "RETURNING id", pid, name, national)
    ids["fixture"] = one("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
                         "venue_id, kickoff_at) VALUES (9301, %s, %s, %s, %s, now() + interval '2 days') RETURNING id",
                         season, ids["atletico"], ids["deportivo"], venue)
    ids["player"] = one("INSERT INTO core.players (provider_player_id, name, firstname, lastname) VALUES "
                        "(9401, 'J. Rodríguez', 'Jaime David', 'Rodríguez Ficticio') RETURNING id")
    ids["cyrillic"] = one("INSERT INTO core.players (provider_player_id, name) VALUES (9402, 'Иван Примеров') RETURNING id")
    c.execute("INSERT INTO core.squad_members (team_id, provider_player_id, player_name, position, first_seen_at, "
              "last_seen_at, payload_hash) VALUES (%s, 9401, 'J. Rodríguez', 'Midfielder', now(), now(), 'h')",
              (ids["atletico"],))
    ids["coach"] = one("INSERT INTO core.coaches (provider_coach_id, name, firstname, lastname) VALUES "
                       "(9501, 'C. Entrenador', 'Carlo', 'Entrenador') RETURNING id")
    ids["referee"] = one("INSERT INTO core.referees (name, name_key, origin, version) VALUES ('Wilmar Árbitro', "
                         "'wilmar arbitro', 'manual', 'refid-v1') RETURNING id")
    return ids


@pytest.fixture(scope="module")
def scratch() -> Iterator[str]:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), _parent())
        yield dsn
    finally:
        _drop()
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous


def _groups(answer: SearchV2Private) -> dict[str, list[str]]:
    return {name: [h.label for h in getattr(answer.groups, name).items]
            for name in type(answer.groups).model_fields}


def test_0145_builds_nothing_then_the_search_finds_by_three_passes_and_goes_back_clean(scratch: str) -> None:
    with psycopg.connect(scratch, autocommit=True) as c:
        ids = _seed(c)
        before = _shape(c)
    command.upgrade(_cfg(), "0145")
    with psycopg.connect(scratch) as c:
        assert _shape(c) == before, "not a column more or less in any table"
        exts: dict[str, str] = dict(c.execute("SELECT extname, extversion FROM pg_extension WHERE extname IN ('unaccent', 'pg_trgm')"
                              ).fetchall())
        assert set(exts) == {"unaccent", "pg_trgm"}
        assert c.execute("SELECT core.search_key('  Atlético-Ejemplo, F.C. '), core.search_key('Иван Примеров'), "
                         "core.search_key('...')").fetchone() == ("atletico ejemplo f c", "иван примеров", None)
        assert c.execute("SELECT provolatile FROM pg_proc WHERE proname = 'search_key'").fetchone() == ("i",)
        assert c.execute("SELECT relispopulated FROM pg_class WHERE relname = 'search_entries'").fetchone() == (False,), \
            "the migration builds nothing"
        indexes = {r[0] for r in c.execute("SELECT indexname FROM pg_indexes WHERE tablename = 'search_entries'")}
        assert indexes == {"search_entries_key", "search_entries_prefix", "search_entries_words", "search_entries_trgm"}

        empty = service.build(c, "Atlético")
        assert empty.freshness.stale and empty.freshness.stale_reason == "indice_sin_construir"
        assert empty.groups.teams.missing_reason == "no_entregado" and empty.groups.teams.expected_piece == "AD-I01"
        assert empty.groups.news.expected_piece == "AD-G01"
        c.rollback()

        c.execute("REFRESH MATERIALIZED VIEW core.search_entries")
        c.commit()
        c.execute("REFRESH MATERIALIZED VIEW CONCURRENTLY core.search_entries")
        c.commit()

        accents = service.build(c, "atletico")
        assert _groups(accents)["teams"] == ["Atlético Ejemplo"]
        assert accents.groups.teams.items[0].match == "prefijo"
        assert [f.id for f in accents.groups.fixtures.items] == [ids["fixture"]]
        assert accents.groups.fixtures.items[0].label == "Atlético Ejemplo v Deportivo Ficticio"
        assert accents.groups.players.missing_reason == "sin_resultados"
        assert accents.groups.news.missing_reason == "no_entregado"

        words = service.build(c, "jai rod")
        assert words.groups.players.items[0].id == ids["player"]
        assert words.groups.players.items[0].match == "palabras"
        assert words.groups.players.items[0].matched == "Jaime David Rodríguez Ficticio"
        assert words.groups.players.items[0].sublabel == "Atlético Ejemplo", "a player shows his current team"

        typo = service.build(c, "deportvo ficticio")
        assert typo.groups.teams.items[0].label == "Deportivo Ficticio"
        assert typo.groups.teams.items[0].match == "trigramas"

        groups = _groups(service.build(c, "ejemplandia"))
        assert groups["national_teams"] == ["Ejemplandia"] and groups["teams"] == []
        assert _groups(service.build(c, "nemesio"))["venues"] == ["Estadio Nemesio Ejemplo"]
        assert _groups(service.build(c, "entrenador"))["coaches"] == ["C. Entrenador"]
        assert _groups(service.build(c, "wilmar arbitro"))["referees"] == ["Wilmar Árbitro"]
        assert _groups(service.build(c, "liga fict"))["competitions"] == ["Liga Ficticia"]
        assert _groups(service.build(c, "иван"))["players"] == ["Иван Примеров"]

        lost = service.build(c, "deportivx fictixio zzz")
        assert all(not getattr(lost.groups, g).items for g in ("teams", "players"))
        assert [s.text for s in lost.did_you_mean.items][:1] == ["Deportivo Ficticio"], "«¿Quisiste decir…?»"
        assert service.build(c, "atletico").did_you_mean.missing_reason == "sin_resultados"

        public = to_public(accents, SearchV2).model_dump(mode="json")
        assert "index" not in public and "score" not in public["groups"]["teams"]["items"][0]
        assert leaks(public, public_schema=SearchV2.model_json_schema(mode="serialization"),
                     private_schema=SearchV2Private.model_json_schema(mode="serialization")) == []

        # The plan reads the indexes, never the whole view (seqscan off so that a tiny table does not hide it).
        c.execute("SET enable_seqscan = off")
        key = "atletico"
        words_on, trigrams_on = repo.passes_for(key)
        plan = "\n".join(r[0] for r in c.execute(
            "EXPLAIN " + repo.ENTITIES_SQL, {"key": key, "prefix": repo.like_prefix(key), "words": words_on,
                                             "trigrams": trigrams_on, "threshold": 0.6, "per_group": 8,
                                             "pop_weight": repo.POPULARITY_WEIGHT}).fetchall())
        assert "search_entries_prefix" in plan and "search_entries_words" in plan and "search_entries_trgm" in plan
        assert "Seq Scan on search_entries" not in plan
        c.rollback()

    command.downgrade(_cfg(), _parent())
    with psycopg.connect(scratch, autocommit=True) as c:
        assert _shape(c) == before
        assert c.execute("SELECT count(*) FROM pg_class WHERE relname = 'search_entries'").fetchone() == (0,)
        assert c.execute("SELECT count(*) FROM pg_proc WHERE proname = 'search_key'").fetchone() == (0,)
        assert c.execute("SELECT count(*) FROM pg_extension WHERE extname IN ('unaccent', 'pg_trgm')").fetchone() == (0,)
    command.upgrade(_cfg(), "head")


def test_the_routes_answer_c10_public_and_private(scratch: str) -> None:
    from fbi.api.app import create_app
    from fbi.api.deps import get_db
    from fbi.api.security import optional_principal

    command.upgrade(_cfg(), "head")
    with psycopg.connect(scratch, autocommit=True) as c:
        if c.execute("SELECT count(*) FROM core.teams WHERE provider_team_id = 9201").fetchone() == (0,):
            _seed(c)
        c.execute("REFRESH MATERIALIZED VIEW core.search_entries")
    conn = psycopg.connect(scratch)
    app = create_app()
    app.dependency_overrides[optional_principal] = lambda: principal("SUPER_ADMIN")
    app.dependency_overrides[get_db] = lambda: conn
    try:
        with TestClient(app, headers=SAME_SITE) as client:
            public = client.get("/api/v1/search/v2", params={"q": "Atlético"})
            assert public.status_code == 200, public.text
            data = public.json()["data"]
            assert data["contract"] == "C-10" and data["projection"] == "public"
            assert data["groups"]["teams"]["items"][0]["label"] == "Atlético Ejemplo"
            assert "score" not in data["groups"]["teams"]["items"][0] and "index" not in data
            private = client.get("/api/v1/admin/search/v2", params={"q": "Atlético"})
            assert private.status_code == 200, private.text
            pdata = private.json()["data"]
            assert pdata["projection"] == "private" and pdata["index"]["built"] is True
            assert 0 < pdata["groups"]["teams"]["items"][0]["score"] <= 1
            assert client.get("/api/v1/search/v2", params={"q": "a"}).status_code == 422
            old = client.get("/api/v1/search", params={"q": "Atlético"})
            assert old.status_code == 200 and isinstance(old.json()["data"], list), "/search keeps its list"
    finally:
        conn.close()
