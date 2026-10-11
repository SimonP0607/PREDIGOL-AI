"""REVIEW PREDIGOL (11 Oct 2026), points 8 and 10: the Cronología says what really happened, with a code a page can
translate - a window the provider answered empty is not "missed", a catch-up capture is listed, near-close capture
is off by design (not a failure), kick-off is confirmed by evidence, and a missing result names its owner."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from fbi.api.services.matches import timeline

KO = datetime(2026, 10, 10, 12, 0, tzinfo=UTC)


def _row(**over: object) -> dict[str, object]:
    row: dict[str, object] = {"kickoff_at": KO, "created_at": KO - timedelta(days=10), "provider_fixture_id": 1570410,
                              "status_short": "NS", "status_group": "scheduled", "goals_home": None,
                              "goals_away": None, "result_fetched_at": None, "source_fetched_at": None}
    row.update(over)
    return row


def _by(events: list, key: str):  # type: ignore[no-untyped-def]
    return next(e for e in events if e.key == key)


def test_a_window_answered_empty_is_not_missed_and_a_catch_up_is_listed() -> None:
    at = KO - timedelta(minutes=30)
    captures = [{"captured_at": KO - timedelta(minutes=200), "minutes_to_ko": 200, "source": "prematch", "quotes": 405}]
    asks = [{"asked_at": KO - timedelta(minutes=170), "minutes_to_ko": 170, "window_minutes": 180, "results": 0,
             "quotes": 0}]
    ev = timeline(_row(), captures, at, asks=asks)
    w3 = _by(ev, "odds_180")
    assert (w3.state, w3.code) == ("skipped", "window_provider_empty")
    w6 = _by(ev, "odds_360")
    assert (w6.state, w6.code) == ("skipped", "window_missed")
    extra = _by(ev, "extra_200")
    assert (extra.state, extra.code, extra.vars["quotes"]) == ("done", "extra_capture", "405")


def test_near_close_off_by_design_is_not_a_failure() -> None:
    ev = timeline(_row(), [], KO + timedelta(hours=5))
    nc = _by(ev, "near_close")
    assert (nc.state, nc.code) == ("skipped", "near_close_off")


def test_kickoff_needs_evidence_and_a_missing_result_names_its_owner() -> None:
    later = KO + timedelta(hours=17)
    ev = timeline(_row(status_short="INT", status_group="live"), [], later, first_live=KO + timedelta(minutes=2),
                  wait="provider_pending")
    assert (_by(ev, "kickoff").code, _by(ev, "kickoff").state) == ("kickoff_seen", "done")
    res = _by(ev, "result")
    assert (res.state, res.code, res.vars["status"]) == ("pending", "result_provider_pending", "INT")
    silent = timeline(_row(), [], later, wait="provider_silent")
    assert (_by(silent, "kickoff").code, _by(silent, "kickoff").state) == ("kickoff_unconfirmed", "pending")
    assert _by(silent, "result").code == "result_provider_silent"
    assert _by(timeline(_row(), [], later, wait="jobs_stalled"), "result").state == "failed"


def test_a_result_and_the_final_prematch_prices_are_recorded() -> None:
    final = {"checked_at": KO + timedelta(hours=3), "outcome": "stored", "provider_update_at": KO,
             "bookmakers": 10, "quotes": 520}
    ev = timeline(_row(status_short="FT", status_group="finished", goals_home=3, goals_away=0,
                       result_fetched_at=KO + timedelta(hours=2)), [], KO + timedelta(hours=4), final=final)
    assert (_by(ev, "result").code, _by(ev, "result").vars["score"]) == ("result_recorded", "3-0")
    assert (_by(ev, "kickoff").code) == "kickoff_by_result"
    fp = _by(ev, "final_prematch")
    assert (fp.state, fp.code, fp.vars["quotes"]) == ("done", "final_prematch", "520")


def test_a_postponed_match_has_no_kickoff_and_no_result() -> None:
    ev = timeline(_row(status_short="PST", status_group="postponed"), [], KO + timedelta(hours=5))
    assert _by(ev, "kickoff").code == "kickoff_not_played" and _by(ev, "result").code == "result_not_played"
