"""RAW damage severity (scripts.audit_raw_integrity): HIGH when the fixed store let damage through; before the fix,
by what the rows naming the payload feed."""

from datetime import UTC, datetime, timedelta

from scripts.audit_raw_integrity import STORE_SYNCED_SINCE, evidence, severity_of


def test_damage_after_the_fix_is_high_and_open() -> None:
    later = STORE_SYNCED_SINCE + timedelta(minutes=1)
    assert severity_of(later, {"market.live_odds_snapshots": 3}) == "high"
    meta = {"h1": {"endpoint": "/odds/live", "params": "{}", "fetched_at": str(later), "fetched_at_dt": later,
                   "bytes": 10, "file_path": "x"}}
    [ev] = evidence([{"hash": "h1", "problem": "empty", "size": 0}], meta, {"h1": {"market.live_odds_snapshots": 3}})
    assert (ev.severity, ev.status) == ("high", "OPEN")


def test_damage_before_the_fix_follows_what_its_rows_feed() -> None:
    stop = datetime(2026, 10, 4, 2, 57, 16, tzinfo=UTC)
    assert severity_of(stop, {"market.live_odds_snapshots": 22, "market.live_fixture_states": 2}) == "low"
    assert severity_of(stop, {"core.fixture_live_states": 1}) == "low"
    assert severity_of(stop, {"market.odds_snapshots": 5}) == "medium", "a pre-match price a model may read"
    meta = {"h2": {"endpoint": "/odds/live", "params": "{}", "fetched_at": str(stop), "fetched_at_dt": stop,
                   "bytes": 13986, "file_path": "x"}}
    [ev] = evidence([{"hash": "h2", "problem": "empty", "size": 0}], meta, {"h2": {"market.live_odds_snapshots": 22}})
    assert (ev.severity, ev.status) == ("low", "MONITOR")
    assert "cause is fixed" in ev.claim and "no model reads" in ev.claim
