"""PM-13-03 (BE-065): the comparison of ``FBI_PACKET_STORE_STABLE`` leaves out the age fields and nothing else, and the cycle's
cadence counts a reused packet as built - only with the switch on."""

from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest

import fbi.ai.packet as pk

AT = datetime(2026, 11, 20, 12, 0, tzinfo=UTC)


def content(age_home: float | None = 1.2, age_away: float | None = 3.4, rest: float = 4.0) -> dict[str, Any]:
    side = {"complete": True, "reason": None, "fetched_at": "2026-11-20T10:00:00+00:00"}
    return {"schedule": {"calendar": {"complete": True, "home": {**side, "age_hours": age_home}, "away": {**side, "age_hours": age_away}},
                         "home": {"rest_days": rest}, "away": {"rest_days": 6.0}},
            "market": {"selections": [{"market": "1X2", "selection": "Home", "p_fair": 0.41}]}}


@pytest.fixture(autouse=True)
def _clean(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pk, "_reused_at", {})


def test_two_packets_that_differ_only_in_how_old_a_read_was_have_one_stable_hash() -> None:
    a, b = content(1.2, 3.4), content(2.9, 5.0)
    assert pk.content_hash({"v": "packet-v8", "content": a, "missing": []}) != pk.content_hash({"v": "packet-v8", "content": b, "missing": []})
    assert pk.stable_hash("packet-v8", a, []) == pk.stable_hash("packet-v8", b, [])


@pytest.mark.parametrize("other", [
    content(rest=5.0),                                   # the match changed: a rest day
    {**content(), "market": {"selections": []}},         # a price
])
def test_anything_else_that_changes_is_a_new_packet(other: dict[str, Any]) -> None:
    assert pk.stable_hash("packet-v8", content(), []) != pk.stable_hash("packet-v8", other, [])


def test_the_version_and_what_is_missing_count() -> None:
    assert pk.stable_hash("packet-v8", content(), []) != pk.stable_hash("packet-v9", content(), [])
    assert pk.stable_hash("packet-v8", content(), []) != pk.stable_hash("packet-v8", content(), ["schedule"])
    assert pk.stable_hash("packet-v8", content(), ["b", "a"]) == pk.stable_hash("packet-v8", content(), ["a", "b"])


def test_the_comparison_never_changes_the_packet_and_tolerates_a_schedule_without_calendar() -> None:
    c = content()
    before = copy.deepcopy(c)
    pk.stable_hash("packet-v8", c, [])
    assert c == before, "the packet the pass reads is the one it built"
    odds: list[dict[str, Any]] = [{}, {"schedule": {"error": "OperationalError"}}, {"schedule": {"calendar": None}}, {"schedule": []}]
    for odd in odds:
        assert len(pk.stable_hash("packet-v8", odd, [])) == 64


@pytest.mark.parametrize("value", [None, "off", "0", "shadow", ""])
def test_off_by_default_the_cadence_reads_the_stored_moment(monkeypatch: pytest.MonkeyPatch, value: str | None) -> None:
    if value is None:
        monkeypatch.delenv(pk.STABLE_STORE_SWITCH, raising=False)
    else:
        monkeypatch.setenv(pk.STABLE_STORE_SWITCH, value)
    assert not pk.stable_store_enabled()
    pk._reused_at[7] = AT
    assert pk.last_built(7, AT - timedelta(hours=2)) == AT - timedelta(hours=2)
    assert pk.last_built(7, None) is None


def test_on_a_reused_packet_counts_as_built(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(pk.STABLE_STORE_SWITCH, "on")
    assert pk.stable_store_enabled()
    pk._note_reuse(7, AT)
    assert pk.last_built(7, AT - timedelta(hours=2)) == AT
    assert pk.last_built(7, None) == AT
    assert pk.last_built(7, AT + timedelta(minutes=5)) == AT + timedelta(minutes=5), "a newer stored packet wins"
    assert pk.last_built(8, AT - timedelta(hours=1)) == AT - timedelta(hours=1)


def test_the_memory_of_reuses_is_pruned_but_never_inside_a_cadence(monkeypatch: pytest.MonkeyPatch) -> None:
    for fid in range(6000):
        pk._reused_at[fid] = AT - timedelta(days=3)
    pk._reused_at[99999] = AT - timedelta(hours=3)
    pk._note_reuse(1, AT)
    assert set(pk._reused_at) == {1, 99999}
