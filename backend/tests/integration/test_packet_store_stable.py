"""PM-13-03 (BE-065): with ``FBI_PACKET_STORE_STABLE=on`` a packet that differs from its fixture's newest stored one only in the age
of a calendar read reuses that row; any other difference, or the switch off, stores a new row. Nothing stored is changed."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

import fbi.ai.packet as pk
from tests.integration.conftest import Seed
from tests.integration.helpers import scalar

AT = datetime(2026, 9, 14, 12, 0, tzinfo=UTC)


def _content(age: float, rest: float = 4.0) -> dict[str, Any]:
    side = {"complete": True, "reason": None, "fetched_at": "2026-09-14T10:00:00+00:00", "age_hours": age}
    return {"schedule": {"calendar": {"complete": True, "home": dict(side), "away": dict(side)}, "home": {"rest_days": rest}}}


def _packet(seed: Seed, at: datetime, age: float, rest: float = 4.0) -> pk.Packet:
    return pk.Packet(seed.fixture_id, at, _content(age, rest), sources=[{"block": "schedule", "as_of": at.isoformat()}])


def _rows(db: psycopg.Connection, seed: Seed) -> int:
    return int(scalar(db.execute("SELECT count(*) FROM ai.match_packets WHERE fixture_id = %s", (seed.fixture_id,))))


def test_only_the_age_of_a_read_is_left_out(db: psycopg.Connection, seed: Seed, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pk, "_reused_at", {})
    monkeypatch.setenv(pk.STABLE_STORE_SWITCH, "off")
    first = pk.store_packet(db, _packet(seed, AT, 2.0), built_at=AT)
    off = pk.store_packet(db, _packet(seed, AT + timedelta(minutes=15), 2.3), built_at=AT + timedelta(minutes=15))
    assert off != first and _rows(db, seed) == 2, "off: as before, the age alone is a new row"

    monkeypatch.setenv(pk.STABLE_STORE_SWITCH, "on")
    later = AT + timedelta(minutes=30)
    same = pk.store_packet(db, _packet(seed, later, 2.5), built_at=later)
    assert same == off and _rows(db, seed) == 2, "on: only the age changed, the newest row is reused"
    assert pk.last_built(seed.fixture_id, AT + timedelta(minutes=15)) == later, "and the cycle's cadence counts it as built"
    stored = pk.load_packet(db, same)
    assert stored is not None and stored.content["schedule"]["calendar"]["home"]["age_hours"] == 2.3, "nothing stored is rewritten"

    changed = pk.store_packet(db, _packet(seed, AT + timedelta(minutes=45), 2.8, rest=5.0), built_at=AT + timedelta(minutes=45))
    assert changed not in (first, off) and _rows(db, seed) == 3, "anything else that changes is a new row"
    back = pk.store_packet(db, _packet(seed, AT + timedelta(hours=1), 3.0), built_at=AT + timedelta(hours=1))
    assert back not in (first, off, changed) and _rows(db, seed) == 4, (
        "compared with the NEWEST row only: an earlier content that comes back is stored again, so the newest row is the current context")
    db.rollback()
