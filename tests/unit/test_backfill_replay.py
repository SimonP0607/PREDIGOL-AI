"""The RAW replay that fills core.fixture_facts / core.fixture_player_extras keeps a change-only history in
memory and drops a fixture's players once the last payload naming it is read (scripts.backfill_from_raw)."""

from __future__ import annotations

import gzip
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from scripts.backfill_from_raw import Replay, detail_ids

T0 = datetime(2026, 9, 15, 17, 0, tzinfo=UTC)


def entry(referee: str | None, offsides: int | None = None) -> dict[str, Any]:
    e: dict[str, Any] = {"fixture": {"id": 1001, "referee": referee, "periods": {"first": None, "second": None}},
                         "teams": {"home": {"id": 33, "winner": None}, "away": {"id": 40, "winner": None}}}
    if offsides is not None:
        e["players"] = [{"team": {"id": 33}, "players": [
            {"player": {"id": 7, "name": "A"}, "statistics": [{"games": {"position": "F"}, "offsides": offsides}]}]}]
    return {"response": [e]}


def test_detail_ids_reads_the_request() -> None:
    assert detail_ids({"ids": "1-22-333"}) == (1, 22, 333)
    assert detail_ids({"id": "5"}) == (5,)
    assert detail_ids({"league": "39", "season": "2026"}) == ()
    assert detail_ids(None) == ()


def test_the_replay_adds_a_row_per_change_only() -> None:
    r = Replay(fixtures={1001: (1, 33, 40)}, last_naming={1001: 3})
    r.feed(0, "h0", T0, entry(None), ())
    r.feed(1, "h1", T0 + timedelta(hours=1), entry("M. Oliver, England", offsides=0), (1001,))
    r.feed(2, "h2", T0 + timedelta(hours=2), entry("M. Oliver, England", offsides=0), (1001,))
    r.feed(3, "h3", T0 + timedelta(hours=3), entry("M. Oliver, England", offsides=2), (1001,))
    assert [(row[0], row[2], row[-2]) for row in r.facts_rows] == [(1, "M. Oliver", "h1")]
    assert [(row[1], row[5], row[-2]) for row in r.extras_rows] == [(7, 0, "h1"), (7, 2, "h3")]
    assert r.extras_state == {}, "the last payload naming the fixture drops its players from memory"


def test_an_instant_already_held_adds_nothing_and_unknown_fixtures_are_counted() -> None:
    r = Replay(fixtures={1001: (1, 33, 40)})
    r.feed(0, "a", T0, entry("A. Rojas"), ())
    r.feed(1, "b", T0, entry("B. Other"), ())
    assert [row[-2] for row in r.facts_rows] == ["a"], "same instant: the first in hash order is kept"
    other = Replay(fixtures={})
    other.feed(0, "a", T0, entry("A. Rojas"), ())
    assert other.facts_rows == [] and other.counts["unknown_fixtures"] == 1


def test_an_unreadable_payload_file_is_reported_not_fatal(tmp_path: Path) -> None:
    from scripts.backfill_from_raw import _body

    (tmp_path / "empty.json.gz").write_bytes(b"")
    good = gzip.compress(json.dumps({"endpoint": "/fixtures", "body": {"response": []}}).encode())
    (tmp_path / "good.json.gz").write_bytes(good)
    (tmp_path / "cut.json.gz").write_bytes(good[: len(good) // 2])
    assert _body(tmp_path, "good.json.gz") == ({"response": []}, None)
    for name in ("empty.json.gz", "cut.json.gz", "missing.json.gz"):
        body, why = _body(tmp_path, name)
        assert body is None and why, name
