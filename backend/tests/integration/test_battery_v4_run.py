"""IA-065 (plan piece AD-A03): ``battery-v4`` in the LAB - the owner's signature, what is refused without it, a measurement of the quarantined
extractor's target with the Message Batches API simulated, and the rows of ``battery-v3`` untouched.

No network and no key. One transaction, rolled back."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest

from fbi.ai import gates
from fbi.ai.battery import quarantine as qworld
from fbi.ai.battery import v4, v4_run
from fbi.ai.providers.fake import FakeBatches
from fbi.ai.usage import UsageLedger, shared

from .conftest import Seed  # noqa: F401
from .test_ai_decision_layer import Savepoints
from .test_lab import AT, cfg

LATER = AT + timedelta(hours=2)
V3_ROW = {"battery": "battery-v3", "corpus_hash": "0c75b248", "targets": {"stats": {"assessment": {"verdict": "NO PASA"}}}}


def faithful(req: Any) -> dict[str, Any]:
    return qworld.faithful(req, None)  # type: ignore[arg-type]


def battery_rows(db: psycopg.Connection[Any]) -> list[tuple[int, bool, str, dict[str, Any]]]:
    return [(int(r[0]), bool(r[1]), str(r[2]), dict(r[3])) for r in
            db.execute("SELECT id, passed, decided_by, evidence FROM ai.feature_gates WHERE gate = 'battery' ORDER BY id").fetchall()]


@pytest.fixture()
def conn(db: psycopg.Connection[Any]) -> Any:
    gates.record_gate(db, gate="battery", passed=False, evidence=V3_ROW, at=AT - timedelta(days=1))  # a row of battery-v3, like row 18
    return Savepoints(db)


def test_the_signature_is_the_owners_and_nothing_is_written_without_it(db: psycopg.Connection[Any], conn: Any) -> None:
    before = battery_rows(db)
    preview = v4_run.sign(conn, invalid_max=0.0, reason="firmo battery-v4", confirm_owner=False, at=AT)
    assert preview["preview"] is True and preview["written"] is None and battery_rows(db) == before
    assert v4_run.sign(conn, invalid_max=0.05, reason="x", confirm_owner=True, at=AT)["error"].startswith("invalid_max must be")
    assert v4_run.sign(conn, invalid_max=0.0, reason=" ", confirm_owner=True, at=AT)["error"].startswith("sign needs --reason")
    assert battery_rows(db) == before and v4_run.signature(conn) is None
    signed = v4_run.sign(conn, invalid_max=0.03, reason="el dueño firma el 3 %", confirm_owner=True, at=AT)
    rows = battery_rows(db)
    assert rows[:-1] == before, "the rows of battery-v3 are as they were"
    row_id, passed, decided_by, evidence = rows[-1]
    assert row_id == signed["written"] and passed is False and decided_by == "owner"
    assert evidence["kind"] == "protocol-signature" and evidence["params"]["invalid_max"] == 0.03
    sig = v4_run.signature(conn)
    assert sig is not None and sig.params.invalid_max == 0.03 and sig.problems() == []


def test_a_round_is_refused_without_a_signature_and_above_the_ceiling(db: psycopg.Connection[Any], conn: Any) -> None:
    fake = FakeBatches(faithful, name="anthropic")
    ledger = UsageLedger(shared(db))
    unsigned = v4_run.submit(conn, cfg(), at=AT, targets=["deep"], ledger=ledger, client=fake)
    assert unsigned["submitted"] == 0 and any("has not been signed" in b for b in unsigned["blockers"])
    plan = v4_run.submit(conn, cfg(), at=AT, ledger=ledger, client=fake, dry_run=True)
    assert plan["dry_run"] is True and plan["asks"] == sum(len(v4.first_round(t)) for t in v4.TARGETS)
    assert any("has not been signed" in b for b in plan["would_stop"])
    v4_run.sign(conn, invalid_max=0.0, reason="firmo", confirm_owner=True, at=AT)
    capped = v4_run.submit(conn, cfg(), at=AT, targets=["deep"], max_usd=Decimal("0.0001"), ledger=ledger, client=fake)
    assert capped["submitted"] == 0 and any("above the ceiling" in b for b in capped["blockers"])
    assert fake.created == [] and db.execute("SELECT count(*) FROM ai.batch_items").fetchone() == (0,)


def test_a_measurement_of_the_quarantine_target_is_judged_and_recorded_only_with_every_target(db: psycopg.Connection[Any], conn: Any) -> None:
    fake = FakeBatches(faithful, name="anthropic")
    ledger = UsageLedger(shared(db))
    v4_run.sign(conn, invalid_max=0.0, reason="firmo", confirm_owner=True, at=AT)
    sent = v4_run.submit(conn, cfg(), at=AT, targets=["deep"], ledger=ledger, client=fake)
    assert sent["submitted"] == 16 * 15 + 64 * 10 and sent.get("blockers") is None, sent
    items = db.execute("SELECT DISTINCT prompt_version, context ->> 'lab' FROM ai.batch_items").fetchall()
    assert items == [("battery-v4", "battery-v4")]
    fake.end()
    got = v4_run.collect(conn, cfg(), at=LATER, targets=["deep"], ledger=ledger, client=fake)
    assert got["state"] == "ended" and got["verdict"] == "PASA", got["targets"]["deep"]["reasons"]
    assert "gate_id" not in got, "a measurement of part of the battery is never a row of the gate"
    again = v4_run.submit(conn, cfg(), at=LATER, targets=["deep"], ledger=ledger, client=fake)
    assert again["submitted"] == 0 and again.get("nothing_due") is True, "asking again pays nothing twice"
    assert [r[3].get("battery") for r in battery_rows(db)] == ["battery-v3", "battery-v4"], "battery-v3's row is untouched"
