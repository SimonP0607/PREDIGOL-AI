"""The line of why under each leg of a published parlay (plan de Inicio, 2.4b): a fact of the match's reading - known before the
match started - or no line. Every test runs in a transaction that is rolled back."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import pytest
from psycopg.types.json import Jsonb

from fbi.api.services import reading as reading_service
from tests.integration.helpers import scalar
from tests.integration.test_pick_states import NOW, World, client, data, stored_parlay
from tests.integration.test_pick_states import world as world

GREEN = {"decision": None, "enforced": False, "mode": "shadow"}


def packet(world: World, name: str, *, as_of: datetime | None = None, unbeaten: int = 6) -> None:
    as_of = as_of or NOW - timedelta(hours=1)
    content = {"fixture": {"home": {"name": "Home FC"}, "away": {"name": "Away FC"}},
               "dossier": {"teams": {"home": {"streaks": {"unbeaten": unbeaten}}}}}
    world.db.execute("INSERT INTO ai.match_packets (fixture_id, packet_version, as_of, built_at, packet_hash, content, missing) "
                     "VALUES (%s, 'packet-v8', %s, %s, %s, %s, %s)",
                     (world.fixtures[name], as_of, as_of + timedelta(minutes=1), "a" * 64, Jsonb(content), []))


def legs(world: World) -> list[dict[str, Any]]:
    board = data(client(world.db), "/api/v1/daily")
    return list(board["daily_parlay"]["legs"])


def test_a_leg_carries_the_fact_of_its_matchs_reading(world: World) -> None:
    packet(world, "D")
    stored_parlay(world, "daily", {"D": GREEN, "E": GREEN})
    first, second = legs(world)
    assert first["why"]["code"] == "streak_unbeaten"
    assert first["why"]["params"]["n"] == 6 and first["why"]["ref"].startswith("packet:")
    assert second["why"] is None, "no packet, no line"


def test_a_packet_built_after_the_match_started_is_not_used(world: World) -> None:
    """K kicked off an hour ago: its packet was rebuilt 15 minutes after the start - what the leg was explained with was not it."""
    kickoff = scalar(world.db.execute("SELECT kickoff_at FROM core.fixtures WHERE id = %s", (world.fixtures["K"],)))
    packet(world, "K", as_of=kickoff + timedelta(minutes=15))
    stored_parlay(world, "daily", {"K": GREEN, "E": GREEN})
    assert [leg["why"] for leg in legs(world)] == [None, None]
    packet(world, "K", as_of=kickoff - timedelta(minutes=30), unbeaten=7)
    assert legs(world)[0]["why"]["params"]["n"] == 7


def test_the_newest_packet_before_kick_off_is_the_one(world: World) -> None:
    packet(world, "D", as_of=NOW - timedelta(hours=5), unbeaten=5)
    packet(world, "D", as_of=NOW - timedelta(minutes=30), unbeaten=8)
    stored_parlay(world, "daily", {"D": GREEN, "E": GREEN})
    assert legs(world)[0]["why"]["params"]["n"] == 8


def test_without_the_reading_for_readers_there_is_no_line(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    packet(world, "D")
    stored_parlay(world, "daily", {"D": GREEN, "E": GREEN})
    monkeypatch.setenv(reading_service.USERS_SWITCH, "0")
    assert [leg["why"] for leg in legs(world)] == [None, None]
