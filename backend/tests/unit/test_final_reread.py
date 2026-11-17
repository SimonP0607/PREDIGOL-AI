"""The last reading of a match before its last pass (IA-061, ``fbi.ai.final_reread``, ``reread-v1``) without a database: the verdict, its closed
reasons, the record the state keeps, and the case of 12 Nov 2026 (match 180277) replayed."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from fbi.ai import final_reread as fr
from fbi.core import match_state

PACKET_AT = datetime(2026, 11, 12, 19, 20, 51, tzinfo=UTC)
STATED = datetime(2026, 11, 12, 20, 0, tzinfo=UTC)
"""The kick-off the provider gave for Bonaire - Cuba until 13 Nov 10:57:29."""
REAL = datetime(2026, 11, 12, 19, 0, tzinfo=UTC)
"""The kick-off it really had (the provider corrected it the next day)."""
PASS_AT = datetime(2026, 11, 12, 19, 26, 51, tzinfo=UTC)
"""When the state of the final pass was written (``ai.match_runs`` 6912)."""


def reading(kickoff: datetime | None = STATED, status: str | None = "NS", in_play: datetime | None = None, at: datetime = PASS_AT) -> fr.Reading:
    return fr.Reading(fixture_id=180277, at=at, kickoff_at=kickoff, status=status, in_play_at=in_play)


# ── the verdict ─────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_match_still_to_be_played_at_the_packets_kickoff_goes_on() -> None:
    v = fr.judge(STATED, "NS", reading(), at=PASS_AT)
    assert v.ok and v.reason is None


def test_the_case_of_12_november_once_the_provider_has_corrected_the_kickoff_stops_the_pass() -> None:
    """The packet said 20:00 and NS; read at the moment of the pass with the kick-off the provider corrected, the match had started 26 minutes earlier."""
    v = fr.judge(STATED, "NS", reading(kickoff=REAL), at=PASS_AT)
    assert (v.ok, v.reason) == (False, "kickoff_passed")


def test_the_case_of_12_november_as_the_provider_still_said_it_at_the_time_is_not_seen_by_the_reading() -> None:
    """The honest limit: at 19:18, 19:29 and 19:40 the provider's own /fixtures still said NS at 20:00 (read in production). A reading of what is
    stored cannot see what nobody had said yet; the nightly audit is what tells the case (``leak-audit-v10``, ``final_started_explained``)."""
    assert fr.judge(STATED, "NS", reading(), at=PASS_AT).ok


def test_a_match_the_in_play_odds_feed_sees_playing_stops_the_pass_whatever_the_stored_state_says() -> None:
    v = fr.judge(STATED, "NS", reading(in_play=PASS_AT - timedelta(minutes=1)), at=PASS_AT)
    assert (v.ok, v.reason) == (False, "started")


@pytest.mark.parametrize("moved", [timedelta(minutes=-30), timedelta(minutes=10), timedelta(hours=2), timedelta(days=3)])
def test_a_kickoff_that_moved_since_the_packet_stops_the_pass_earlier_or_later(moved: timedelta) -> None:
    v = fr.judge(STATED, "NS", reading(kickoff=STATED + moved), at=PASS_AT)
    assert (v.ok, v.reason) == (False, "kickoff_moved")


def test_a_kickoff_that_is_now_at_or_before_the_reading_is_passed_even_if_it_is_the_packets() -> None:
    assert fr.judge(PASS_AT, "NS", reading(kickoff=PASS_AT), at=PASS_AT).reason == "kickoff_passed"
    assert fr.judge(PASS_AT - timedelta(seconds=1), "NS", reading(kickoff=PASS_AT - timedelta(seconds=1)), at=PASS_AT).reason == "kickoff_passed"


@pytest.mark.parametrize("status, reason", [
    ("TBD", "kickoff_unknown"), ("FT", "finished"), ("AET", "finished"), ("PEN", "finished"), ("CANC", "cancelled"), ("ABD", "cancelled"),
    ("AWD", "cancelled"), ("WO", "cancelled"), ("PST", "postponed"), ("SUSP", "suspended"), ("INT", "suspended"), ("1H", "started"),
    ("HT", "started"), ("2H", "started"), ("ET", "started"), ("BT", "started"), ("P", "started"), ("LIVE", "started"), ("XYZ", "status_unknown"),
    ("", "status_unknown"), (None, "status_unknown"), ("ns", None), (" NS ", None), ("pst", "postponed")])
def test_each_state_of_the_provider_has_its_reason(status: str | None, reason: str | None) -> None:
    assert fr.status_reason(status) == reason
    v = fr.judge(STATED, "NS", reading(status=status), at=PASS_AT)
    assert v.ok is (reason is None) and v.reason == reason


def test_every_code_the_provider_has_is_either_to_be_played_or_a_closed_reason() -> None:
    for status in match_state.KNOWN:
        why = fr.status_reason(status)
        assert (why is None) == (status == "NS") and (why is None or why in fr.REASONS)


def test_the_state_is_judged_before_the_clock_so_a_postponed_match_says_postponed_not_moved() -> None:
    assert fr.judge(STATED, "NS", reading(kickoff=STATED + timedelta(days=7), status="PST"), at=PASS_AT).reason == "postponed"


def test_nothing_to_compare_stops_the_pass() -> None:
    assert fr.judge(STATED, "NS", None, at=PASS_AT).reason == "fixture_missing"
    assert fr.judge(None, None, reading(), at=PASS_AT).reason == "packet_without_kickoff"
    assert fr.judge(STATED, "NS", reading(kickoff=None), at=PASS_AT).reason == "kickoff_unknown"


def test_every_reason_judge_can_give_is_in_the_closed_list() -> None:
    cases = [(STATED, reading(kickoff=k, status=s, in_play=p)) for k in (None, REAL, STATED, STATED + timedelta(hours=1))
             for s in (*sorted(match_state.KNOWN), "??", None) for p in (None, PASS_AT)]
    reasons = {fr.judge(pk, "NS", r, at=PASS_AT).reason for pk, r in cases} | {fr.judge(None, None, reading(), at=PASS_AT).reason,
                                                                                 fr.judge(STATED, None, None, at=PASS_AT).reason}
    assert reasons - {None} <= set(fr.REASONS)
    assert len(set(fr.REASONS)) == len(fr.REASONS)


# ── what the packet knew and what the state keeps ───────────────────────────────────────────────────────────────

def test_the_packets_kickoff_and_state_are_read_from_its_fixture_block() -> None:
    content = {"fixture": {"id": 180277, "kickoff_at": "2026-11-12T20:00:00+00:00", "status": "NS"}}
    assert fr.packet_fixture(content) == (STATED, "NS")
    assert fr.packet_fixture({}) == (None, None)
    assert fr.packet_fixture({"fixture": "not a block"}) == (None, None)
    assert fr.packet_fixture({"fixture": {"kickoff_at": "2026-11-12T20:00:00", "status": 3}}) == (None, None), "a moment with no zone is no moment"
    assert fr.packet_fixture({"fixture": {"kickoff_at": "tomorrow"}}) == (None, None)
    assert fr.parse_moment("2026-11-12T20:00:00Z") == STATED and fr.parse_moment(STATED) == STATED and fr.parse_moment(None) is None


def test_the_record_is_plain_json_with_every_moment_compared() -> None:
    v = fr.judge(STATED, "NS", reading(in_play=None), at=PASS_AT)
    rec = v.record()
    assert json.loads(json.dumps(rec)) == rec
    assert rec == {"version": fr.VERSION, "ok": True, "reason": None, "at": PASS_AT.isoformat(), "packet_kickoff_at": STATED.isoformat(),
                   "packet_status": "NS", "kickoff_at": STATED.isoformat(), "status": "NS", "in_play_at": None}
    stopped = fr.judge(STATED, "NS", None, at=PASS_AT).record()
    assert stopped["ok"] is False and stopped["reason"] == "fixture_missing" and stopped["kickoff_at"] is None and stopped["status"] is None


def test_only_the_last_pass_is_read_again() -> None:
    assert frozenset({"final"}) == fr.PASSES
    assert fr.VERSION == "reread-v1"


# ── the reading ─────────────────────────────────────────────────────────────────────────────────────────────────

class _Cursor:
    def __init__(self, conn: _Conn) -> None:
        self.conn = conn

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, sql: str, params: dict[str, Any]) -> None:
        self.conn.seen.append((sql, params))
        if self.conn.fail:
            raise psycopg.OperationalError("gone")

    def fetchone(self) -> dict[str, Any] | None:
        return self.conn.row


class _Conn:
    def __init__(self, row: dict[str, Any] | None, *, fail: bool = False) -> None:
        self.row, self.fail = row, fail
        self.seen: list[tuple[str, dict[str, Any]]] = []
        self.rolled = 0

    def cursor(self, **_: Any) -> _Cursor:
        return _Cursor(self)

    def rollback(self) -> None:
        self.rolled += 1


CONTENT = {"fixture": {"kickoff_at": STATED.isoformat(), "status": "NS"}}


def test_the_reading_reads_the_stored_match_and_the_in_play_feed_as_of_the_moment() -> None:
    conn = _Conn({"kickoff_at": REAL, "status_short": "NS", "in_play_at": None})
    v = fr.reread(conn, 180277, CONTENT, at=PASS_AT)  # type: ignore[arg-type]
    assert (v.ok, v.reason) == (False, "kickoff_passed") and v.reading is not None and v.reading.kickoff_at == REAL
    sql, params = conn.seen[0]
    assert params == {"fixture": 180277, "at": PASS_AT, "recent": fr.IN_PLAY_RECENT}
    assert "core.fixtures" in sql and "market.live_fixture_current" in sql and "is_finished" in sql
    assert "INSERT" not in sql.upper() and "UPDATE" not in sql.upper()


def test_a_match_that_is_not_there_and_a_reading_that_fails_stop_the_pass() -> None:
    assert fr.reread(_Conn(None), 1, CONTENT, at=PASS_AT).reason == "fixture_missing"  # type: ignore[arg-type]
    broken = _Conn(None, fail=True)
    v = fr.reread(broken, 1, CONTENT, at=PASS_AT)  # type: ignore[arg-type]
    assert (v.ok, v.reason, broken.rolled) == (False, "reread_failed", 1)
