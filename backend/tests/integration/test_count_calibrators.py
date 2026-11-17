"""IA-095 / IA-096 on a real database: migration 0152, the calibrators of the counts and the owner's signature, and the read-only
statements of the LAB and of the private evaluation.

* 0152 goes on top of 0149 and back without touching any other column;
* a fit is written once and never changed; a CHAMPION without VALIDADO is refused by the code AND by the database;
* a family has a champion only while its newest signature is a CHAMPION;
* the LAB's COPY statements, the referee read and the price read run on the schema as it is (read-only);
* the private evaluation, as a dry run on an empty day, writes nothing and admits nothing.
"""

from __future__ import annotations

import os
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config

from fbi.countcal import calibrator as cc
from fbi.countcal import lab, market, private, store
from fbi.research import protocol
from tests.integration.conftest import ADMIN_URL, REPO_ROOT, _dsn

pytestmark = pytest.mark.integration
SCRATCH = "fbi_test_m0152"
BELOW = "0151"
AT = datetime(2026, 11, 17, 12, tzinfo=UTC)


def _cfg() -> Config:
    cfg = Config(os.path.join(REPO_ROOT, "alembic.ini"))
    cfg.set_main_option("script_location", os.path.join(REPO_ROOT, "migrations"))
    return cfg


def _drop() -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()",
                      (SCRATCH,))
        admin.execute(f'DROP DATABASE IF EXISTS "{SCRATCH}"')


def _shape(c: psycopg.Connection[Any]) -> list[tuple[Any, ...]]:
    rows = c.execute("SELECT table_schema, table_name, column_name, data_type, is_nullable, column_default FROM "
                     "information_schema.columns WHERE table_schema IN ('ai', 'core', 'market', 'models', 'intel', 'picks') "
                     "ORDER BY 1, 2, ordinal_position").fetchall()
    return [r for r in rows if not (r[0] == "intel" and r[1] in ("count_calibrators", "count_calibrator_signatures"))]


def _save(c: psycopg.Connection[Any], family: str, verdict: str, known_at: datetime) -> int:
    return store.save(c, family=family, params=cc.Params(1.1, -0.05, 2400, 16800), known_at=known_at, fitted_at=known_at, verdict=verdict,
                      protocol=protocol.stamp("AD-B07"), report={"matches": 2400}, train_from=None, train_to=None, code_version="test")


def test_0152_the_calibrators_their_signature_and_the_reads(migrated_database: str) -> None:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop()
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    dsn = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = dsn.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), BELOW)
        with psycopg.connect(dsn, autocommit=True) as c:
            before = _shape(c)
        command.upgrade(_cfg(), "0152")
        with psycopg.connect(dsn) as c:
            assert _shape(c) == before, "not a column more or less anywhere else"
            good = _save(c, "corners_total", "VALIDADO", AT - timedelta(days=1))
            bad = _save(c, "cards_total", "NO VALIDADO", AT - timedelta(days=1))
            c.commit()
            assert store.latest_verdicts(c, at=AT) == {"corners_total": "VALIDADO", "cards_total": "NO VALIDADO"}
            assert store.champions(c, at=AT) == {}, "nothing is a champion until the owner signs"
            with pytest.raises(store.NotValidatedError):
                store.sign(c, calibrator_id=bad, role=store.CHAMPION, signed_by="Simon", signature="firmo el calibrador", at=AT)
            with pytest.raises(psycopg.errors.RaiseException):  # the database refuses it too, whoever writes the row
                c.execute("INSERT INTO intel.count_calibrator_signatures (calibrator_id, role, signed_by, signature, at) "
                          "VALUES (%s, 'CHAMPION', 'Simon', 'firmo el calibrador', %s)", (bad, AT))
            c.rollback()
            store.sign(c, calibrator_id=good, role=store.CHAMPION, signed_by="Simon", signature="firmo el calibrador", at=AT)
            c.commit()
            champs = store.champions(c, at=AT + timedelta(minutes=1))
            assert set(champs) == {"corners_total"} and champs["corners_total"].params.a == pytest.approx(1.1)
            assert store.champions(c, at=AT - timedelta(minutes=1)) == {}, "a signature counts from its moment"
            store.sign(c, calibrator_id=good, role=store.RETIRED, signed_by="Simon", signature="retiro el calibrador", at=AT + timedelta(hours=1))
            c.commit()
            assert store.champions(c, at=AT + timedelta(hours=2)) == {}
            for sql in ("UPDATE intel.count_calibrators SET verdict = 'VALIDADO'", "DELETE FROM intel.count_calibrator_signatures"):
                with pytest.raises(psycopg.errors.CheckViolation):
                    c.execute(sql)
                c.rollback()

            # the reads of the LAB and of the private evaluation run on the schema as it is, read-only
            c.read_only = True
            for name, statement in lab.statements().items():
                with c.cursor() as cur, cur.copy(statement) as copy:
                    out = b"".join(bytes(chunk) for chunk in copy).decode()
                assert out.splitlines()[0].split(",")[:2] in (["competition_id", "fixture_id"], ["fixture_id", "market_key"],
                                                              ["fixture_id", "referee_id"], ["family", "priced_finished"]), name
                c.rollback()
            assert market.referee_known(c, start=AT - timedelta(days=30), end=AT) == {}
            assert private.books(c, {1: AT}) == {}
            rep = private.run_pass(c, now=AT, dry_run=True)
            assert (rep.fixtures, rep.selections, rep.admitted, rep.appended) == (0, 0, 0, 0)
            c.rollback()
        command.downgrade(_cfg(), BELOW)
        with psycopg.connect(dsn, autocommit=True) as c:
            assert _shape(c) == before
            assert c.execute("SELECT to_regclass('intel.count_calibrators'), to_regclass('intel.count_calibrator_signatures')"
                             ).fetchone() == (None, None)
        command.upgrade(_cfg(), "head")
    finally:
        _drop()
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
