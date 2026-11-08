"""``autopromo-v1`` on the real schema: the dry run reads a champion calibrator and its refit, writes nothing, and no policy can exist yet -
the entity check of ``intel.promotions`` refuses an ``autopromo_policy`` row, even the owner's. The transaction is rolled back afterwards."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb
from scripts import ia_autopromo

from fbi.governance.autopromo import policy as pol

AT = datetime(2026, 10, 20, 12, tzinfo=UTC)
TABLES = ("intel.promotions", "intel.calibrators", "analytics.promoted_forecast_spec", "analytics.neutral_rule_promotion", "ai.feature_gates")


def count(db: psycopg.Connection[Any], table: str) -> int:
    row = db.execute(f"SELECT count(*) FROM {table}").fetchone()
    assert row is not None
    return int(row[0])


def calibrator(db: psycopg.Connection[Any], method: str, known_at: datetime, logloss: float) -> int:
    row = db.execute(
        "INSERT INTO intel.calibrators (market_key, model_name, method, version, params, known_at, fitted_at, n_train, train_hash, wf, gate) "
        "VALUES ('OU', 'autopromo_test', %s, 'test', '{}'::jsonb, %s, %s, 600, 'h', %s, '{}'::jsonb) RETURNING id",
        (method, known_at, known_at, Jsonb({"logloss_cal": logloss, "n": 2000}))).fetchone()
    assert row is not None
    return int(row[0])


@pytest.mark.integration
def test_the_dry_run_reads_the_real_schema_and_writes_nothing(db: psycopg.Connection[Any]) -> None:
    champion = calibrator(db, "logit2", AT - timedelta(days=8), 0.665)
    db.execute("INSERT INTO intel.promotions (at, entity, market_key, model_name, entity_id, to_role, gate_version, criteria, reason, decided_by) "
               "VALUES (%s, 'calibrator', 'OU', 'autopromo_test', %s, 'CHAMPION', 'calib-gate-v1', '{}'::jsonb, 'test champion', 'system')",
               (AT - timedelta(days=8), champion))
    refit = calibrator(db, "logit2", AT, 0.660)
    before = {t: count(db, t) for t in TABLES}
    out, code = ia_autopromo.run(ia_autopromo.build_parser().parse_args(["check", "--json"]), db, {"FBI_AUTOPROMO": "on"})
    assert code == ia_autopromo.OK and isinstance(out, dict)
    assert {t: count(db, t) for t in TABLES} == before
    mine = [c for c in out["candidates"] if c["candidate"]["key"] == "OU/autopromo_test"]
    assert [(c["candidate"]["version"], c["candidate"]["champion_version"], c["verdict"]) for c in mine] == [
        (str(refit), str(champion), "NOT_ELIGIBLE")]
    assert mine[0]["reasons"] == ["no_signed_policy"]


@pytest.mark.integration
def test_no_policy_can_be_signed_until_the_owner_adds_its_entity(db: psycopg.Connection[Any]) -> None:
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        db.execute("INSERT INTO intel.promotions (at, entity, market_key, to_role, gate_version, criteria, reason, decided_by) "
                   "VALUES (now(), %s, 'calibrator_refit', 'VALIDATED', %s, %s, 'the owner authorises this class', 'owner')",
                   (pol.POLICY_ENTITY, pol.VERSION, Jsonb({"version": pol.VERSION})))
    assert not pol.read_policies(db).by_class
