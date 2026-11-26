"""RP-8.4 on a real database: the command reads the newest verdict of each experiment, drafts a proposal for each success, registers it once, and the indicator
«successes without a proposal» goes to 0. Nothing is signed or applied."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
from scripts import ia_proposals

from fbi.proposals import store
from fbi.research import exp_protocol, verdicts
from fbi.research.protocol import fingerprint

pytestmark = pytest.mark.integration

NOW = datetime(2026, 12, 20, 12, tzinfo=UTC)


def args(command: str, *, write: bool) -> argparse.Namespace:
    return argparse.Namespace(command=command, write=write, proposal_id=None)


def test_a_success_is_drafted_registered_once_and_waits_for_the_owner(db: psycopg.Connection[Any]) -> None:
    e1 = exp_protocol.EXPERIMENTS["EXP-E1"]
    verdicts.record(db, "EXP-E1", exp_protocol.Judgement("exito", "por debajo del umbral, con intervalo y mismo signo", -0.002, -0.005, 0.001, 1200), claimed_fingerprint=fingerprint(e1),
                    computed_at=NOW, population={"matches": 1200})
    verdicts.record(db, "EXP-E3", exp_protocol.Judgement("abandono", "el intervalo queda entero por encima del umbral", 0.02, 0.01, 0.03, 1500),
                    claimed_fingerprint=fingerprint(exp_protocol.EXPERIMENTS["EXP-E3"]), computed_at=NOW)
    plan, code = ia_proposals.run(db, args("verdicts", write=False))
    assert code == ia_proposals.OK and [p["target"] for p in plan["plan"]] == ["capability:exp-e1"] and plan["written"] == []
    assert plan["successes_without_a_proposal"] == 1
    done, code = ia_proposals.run(db, args("verdicts", write=True))
    assert code == ia_proposals.OK and len([w for w in done["written"] if w is not None]) == 1
    again, _ = ia_proposals.run(db, args("verdicts", write=True))
    assert again["written"] == [None] and again["successes_without_a_proposal"] == 0
    (row,) = [r for r in store.rows(db) if r.proposal.target == "capability:exp-e1"]
    assert row.status == "pendiente_de_firma" and row.applied == ()
    assert store.summary(db)["applied_without_signature"] == 0


def test_a_newer_verdict_that_is_no_longer_a_success_drafts_nothing(db: psycopg.Connection[Any]) -> None:
    e1 = exp_protocol.EXPERIMENTS["EXP-E1"]
    verdicts.record(db, "EXP-E1", exp_protocol.Judgement("exito", "por debajo del umbral, con intervalo y mismo signo", -0.002, -0.005, 0.001, 1200), claimed_fingerprint=fingerprint(e1),
                    computed_at=NOW)
    verdicts.record(db, "EXP-E1", exp_protocol.Judgement("abandono", "el intervalo queda entero por encima del umbral", 0.02, 0.01, 0.03, 1500), claimed_fingerprint=fingerprint(e1),
                    computed_at=NOW)
    plan, _ = ia_proposals.run(db, args("verdicts", write=False))
    assert plan["plan"] == []
