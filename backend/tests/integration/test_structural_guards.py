"""Structural guards that are not tied to a single legacy defect."""

from __future__ import annotations

import psycopg

from tests.integration.conftest import Seed
from tests.integration.helpers import must_be_accepted, must_be_rejected, scalar


def test_a_team_cannot_play_itself(db: psycopg.Connection, seed: Seed) -> None:
    with must_be_rejected(db, "home_team_id = away_team_id") as cur:
        cur.execute(
            "INSERT INTO core.fixtures "
            "(provider_fixture_id,competition_season_id,home_team_id,away_team_id,kickoff_at) "
            "VALUES (9999,%s,%s,%s,'2026-09-20 19:00Z')",
            (seed.season_id, seed.home_team_id, seed.home_team_id),
        )


def test_a_model_can_have_only_one_champion_version(db: psycopg.Connection, seed: Seed) -> None:
    """A partial unique index. Two champions means nobody knows which model
    produced a given pick."""
    with must_be_rejected(db, "two champion versions of one model") as cur:
        cur.execute("SELECT model_id FROM models.model_versions WHERE id = %s", (seed.model_version_id,))
        model_id = scalar(cur)
        for version in ("v9a", "v9b"):
            cur.execute(
                "INSERT INTO models.model_versions "
                "(model_id,version,train_from,train_to,n_train,code_version,status) "
                "VALUES (%s,%s,'2020-01-01','2024-06-30',5000,'abc','champion')",
                (model_id, version),
            )


def test_result_columns_are_derived_not_typed_in(db: psycopg.Connection, seed: Seed) -> None:
    """outcome_1x2 / total_goals / btts are GENERATED ALWAYS. They cannot drift
    away from the score the way hand-maintained columns do."""
    with must_be_accepted(db) as cur:
        cur.execute(
            "INSERT INTO core.fixture_results (fixture_id,goals_home,goals_away) "
            "VALUES (%s,2,2) RETURNING outcome_1x2, total_goals, btts",
            (seed.fixture_id,),
        )
        assert cur.fetchone() == ("Draw", 4, True)


def test_a_generated_result_column_cannot_be_written_to(db: psycopg.Connection, seed: Seed) -> None:
    with db.transaction(force_rollback=True), db.cursor() as cur:
        try:
            cur.execute(
                "INSERT INTO core.fixture_results (fixture_id,goals_home,goals_away,outcome_1x2) "
                "VALUES (%s,2,2,'Home')",
                (seed.fixture_id,),
            )
        except psycopg.errors.GeneratedAlways:
            return
        raise AssertionError("outcome_1x2 accepted a hand-written value")


def test_a_negative_score_is_rejected(db: psycopg.Connection, seed: Seed) -> None:
    with must_be_rejected(db, "goals_home = -1") as cur:
        cur.execute(
            "INSERT INTO core.fixture_results (fixture_id,goals_home,goals_away) VALUES (%s,-1,0)",
            (seed.fixture_id,),
        )


def test_a_blocked_feature_must_say_why(db: psycopg.Connection) -> None:
    """8 of the legacy's 32 declared features depended on ROI/CLV that never
    existed, and nothing anywhere recorded that."""
    with must_be_rejected(db, "blocked feature with no blocked_reason") as cur:
        cur.execute(
            "INSERT INTO features.feature_registry "
            "(name,feature_group,entity_type,value_type,description,status) "
            "VALUES ('team_clv_last10','market','team','numeric','x','blocked')"
        )
    with must_be_accepted(db) as cur:
        cur.execute(
            "INSERT INTO features.feature_registry "
            "(name,feature_group,entity_type,value_type,description,status,blocked_reason) "
            "VALUES ('team_lv_last10','market','team','numeric','x','blocked',"
            "'no hay historico de cuotas suficiente para calcularla') RETURNING status"
        )
        assert scalar(cur) == "blocked"


def test_every_migration_is_reversible_and_leaves_nothing_behind() -> None:
    """Guards the downgrade path, which is the one nobody exercises until the
    night they need it."""
    import os

    from alembic import command
    from alembic.config import Config

    from tests.integration.conftest import ADMIN_URL

    repo_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    admin_url = ADMIN_URL  # derived from the configured database when not set explicitly
    head, _, _ = admin_url.rpartition("/")
    db_name = "fbi_migration_roundtrip"

    with psycopg.connect(admin_url, autocommit=True) as conn:
        conn.execute(f'DROP DATABASE IF EXISTS "{db_name}"')
        conn.execute(f'CREATE DATABASE "{db_name}"')

    cfg = Config(os.path.join(repo_root, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(repo_root, "migrations"))
    previous = os.environ.get("FBI_DATABASE_URL")
    os.environ["FBI_DATABASE_URL"] = f"{head}/{db_name}".replace(
        "postgresql://", "postgresql+psycopg://"
    )
    try:
        command.upgrade(cfg, "head")
        command.downgrade(cfg, "base")
        with psycopg.connect(f"{head}/{db_name}") as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM information_schema.schemata WHERE schema_name IN "
                "('raw','core','market','features','models','picks','analytics','audit')"
            )
            assert scalar(cur) == 0, "downgrade left schemas behind"
        command.upgrade(cfg, "head")
        with psycopg.connect(f"{head}/{db_name}") as conn, conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM information_schema.tables WHERE table_schema IN "
                "('raw','core','market','features','models','picks','analytics','audit')"
            )
            assert scalar(cur) > 30, "re-upgrade did not rebuild the schema"
    finally:
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
        with psycopg.connect(admin_url, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{db_name}"')


def test_only_the_factory_builds_a_provider_client() -> None:
    """The hole BLOQUE 2.5 closed started as three scripts each constructing
    their own ApiFootballClient; two of them let the quota default to the
    in-memory one and spent against a budget that reset every invocation.

    Source-level guard rather than a runtime one, because the mistake is made
    at author time and a runtime check would only fire on the code path that
    was already wrong.
    """
    import pathlib

    root = pathlib.Path(__file__).parents[2]
    offenders: list[str] = []
    for path in [*(root / "scripts").rglob("*.py"), *(root / "apps").rglob("*.py")]:
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            if "ApiFootballClient(" in line and "build_client" not in line:
                offenders.append(f"{path.relative_to(root)}:{number}: {line.strip()}")
    assert not offenders, (
        "construct the client through fbi.providers.api_football.build.build_client, "
        "which is what attaches the persistent daily budget:\n  " + "\n  ".join(offenders)
    )
