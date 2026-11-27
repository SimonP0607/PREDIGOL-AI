"""RP-11.3 against a real PostgreSQL: the owner's criterion for the joint, read by the shadow's own command (``scripts.ia_parlays_v6 acceptance``), over the real tables
of the parlays and in a read-only connection. With no parlays in the window every estimator says «pendiente» and the door stays shut."""

from __future__ import annotations

import json

import pytest
from scripts import ia_parlays_v6 as script

from fbi.parlays import acceptance

pytestmark = pytest.mark.integration


def test_the_command_reads_the_real_tables_and_an_empty_window_is_pending_for_every_estimator(migrated_database: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert script.main(["--dsn", migrated_database, "acceptance"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["version"] == acceptance.VERSION and out["protocol"] == "PARLAY-P1" and out["stated"] == "p_joint"
    assert set(out["estimators"]) == set(acceptance.ESTIMATORS) and out["opens_the_door"] is False
    assert {r["verdict"] for r in out["estimators"].values()} == {"pendiente"} and out["since"] == acceptance.FROZEN_ON.isoformat()


def test_a_window_cannot_start_before_the_signature_of_the_criterion(migrated_database: str, capsys: pytest.CaptureFixture[str]) -> None:
    assert script.main(["--dsn", migrated_database, "acceptance", "--from", "2026-09-01"]) == 0
    assert json.loads(capsys.readouterr().out)["since"] == acceptance.FROZEN_ON.isoformat(), "what was already looked at never counts"
