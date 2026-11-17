"""Migration 0166 (IA-143, AD-K07): the owner's signatures of protocols, append-only, on a scratch database at the revision below it.

The database refuses a signature that is not the owner's, a fingerprint that is not a sha256, a reason that is not the owner's words, an
unknown framework, a second row for the same fingerprint, and any UPDATE or DELETE. The register (``fbi.protosign.store``) counts only the
signature of the fingerprint in force: a row of an earlier fingerprint stays and does not sign the protocol. The owner's command previews
without ``--confirm-owner`` (exit 3), signs once (exit 0) and never writes twice; the board (C-03/C-08) and the console (C-11) read the
signature. The migration goes back clean."""

from __future__ import annotations

import os
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
from alembic import command
from alembic.config import Config
from scripts import ia_protocols as cli

from fbi import protosign
from fbi.api.contracts.intelligence.console import ConsoleProtocols
from fbi.api.services import intelligence_console as console
from fbi.evaluation import views
from fbi.protosign import store as register
from tests.integration.conftest import ADMIN_URL, REPO_ROOT, TEST_DB, _dsn

pytestmark = pytest.mark.integration
SCRATCH = f"{TEST_DB}_m0166"
BELOW = "0165"
REASON = "Firmo el protocolo del tablero antes de mirar los datos"


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
        command.upgrade(_cfg(), BELOW)
        yield dsn
    finally:
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
        _drop()


def shape(c: psycopg.Connection[Any]) -> list[Any]:
    return c.execute("SELECT table_schema, table_name, column_name, data_type FROM information_schema.columns "
                     "WHERE table_schema IN ('ai', 'intel') ORDER BY 1, 2, 3").fetchall()


RAW = ("INSERT INTO ai.protocol_signatures (protocol_key, protocol_version, framework, fingerprint, reason, decided_by) "
       "VALUES (%s, %s, %s, %s, %s, %s)")


def test_0166_keeps_one_signature_per_fingerprint_counts_only_the_one_in_force_and_goes_back_clean(
        capsys: pytest.CaptureFixture[str]) -> None:
    k02 = protosign.current("AD-K02")
    with scratch() as dsn:
        with psycopg.connect(dsn) as c:
            before = shape(c)
            assert register.exists(c) is False and register.is_signed(c, "AD-K02") is False, "behind the code: not signed, no error"
            assert console.protocols(c) == console.NO_DATA
        command.upgrade(_cfg(), "0166")
        with psycopg.connect(dsn) as c:
            added = {(r[0], r[1]) for r in sorted(set(shape(c)) - set(before))}
            assert added == {("ai", "protocol_signatures")}
            good = ("AD-K02", k02.version, "lab-protocol-v1", "1" * 64, REASON, "owner")
            for bad in (("AD-K02", k02.version, "lab-protocol-v1", "1" * 64, REASON, "system"),     # not the owner
                        ("AD-K02", k02.version, "lab-protocol-v1", "XYZ", REASON, "owner"),         # not a sha256
                        ("AD-K02", k02.version, "lab-protocol-v1", "1" * 64, "  ok ", "owner"),     # not the owner's words
                        ("AD-K02", k02.version, "trust-me-v1", "1" * 64, REASON, "owner"),          # an unknown framework
                        ("k02", k02.version, "lab-protocol-v1", "1" * 64, REASON, "owner")):        # not a key
                with pytest.raises(psycopg.errors.CheckViolation):
                    c.execute(RAW, bad)
                c.rollback()
            c.execute(RAW, good)  # an earlier fingerprint of the protocol: kept, and it does not count
            c.commit()
            with pytest.raises(psycopg.errors.UniqueViolation):
                c.execute(RAW, good)
            c.rollback()
            assert register.is_signed(c, "AD-K02") is False and len(register.signatures(c, ["AD-K02"])) == 1
            with pytest.raises(ValueError, match="no es la vigente"):
                register.sign(c, "AD-K02", fingerprint="1" * 64, reason=REASON)
            c.rollback()

        dsn_args = ["--dsn", dsn]
        sign = ["sign", "--key", "AD-K02", "--fingerprint", k02.fingerprint, "--reason", REASON, *dsn_args]
        assert cli.main(sign) == cli.PREVIEW and '"written": false' in capsys.readouterr().out
        with psycopg.connect(dsn) as c:
            assert register.is_signed(c, "AD-K02") is False, "a preview writes nothing"
        assert cli.main(["sign", "--key", "AD-K02", "--fingerprint", "2" * 64, "--reason", REASON, "--confirm-owner", *dsn_args]) == cli.REFUSED
        assert cli.main([*sign, "--confirm-owner"]) == cli.OK and '"written": true' in capsys.readouterr().out
        assert cli.main([*sign, "--confirm-owner"]) == cli.OK and '"written": false' in capsys.readouterr().out
        assert cli.main(["show", "--key", "AD-K02", *dsn_args]) == cli.OK
        shown = capsys.readouterr().out
        assert '"signed_by_owner": true' in shown and k02.fingerprint in shown
        assert cli.main(["list", *dsn_args]) == cli.OK and '"signed": 1' in capsys.readouterr().out

        with psycopg.connect(dsn) as c:
            found = register.in_force(c, "AD-K02")
            assert found is not None and found["fingerprint"] == k02.fingerprint and found["decided_by"] == "owner"
            assert found["code_version"] and len(register.signatures(c, ["AD-K02"])) == 2
            assert register.is_signed(c, "AD-K03") is False and register.is_signed(c, "AD-F06") is False
            at = datetime(2026, 11, 18, tzinfo=UTC)
            b = views.board(c, start=at.replace(month=10), end=at)
            assert b is not None and b["signed_by_owner"] is True and b["cells"] == [], "the board reports the signature and nothing more"
            block = console.protocols(c)
            assert isinstance(block, ConsoleProtocols) and block.signed == 1
            assert {p.key for p in block.items if p.signed_by_owner} == {"AD-K02"}
            assert next(p for p in block.items if p.key == "AD-K02").other_fingerprints == 1
            for sql in ("UPDATE ai.protocol_signatures SET reason = reason || '.'", "DELETE FROM ai.protocol_signatures"):
                with pytest.raises(psycopg.Error):
                    c.execute(sql)
                c.rollback()
        command.downgrade(_cfg(), BELOW)
        with psycopg.connect(dsn) as c:
            assert shape(c) == before
