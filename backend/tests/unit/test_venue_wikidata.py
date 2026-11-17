"""IA-076 (AD-H04): the Wikidata snapshot - the query, the batching at one request a minute, the pinned file, the parsing."""

from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from fbi.venues.wikidata import (
    QUERY_VERSION,
    SnapshotError,
    TransientError,
    build_query,
    fetch_snapshot,
    read_snapshot,
    sha256_of,
)

ANSWER = {"results": {"bindings": [{
    "team": {"value": "http://www.wikidata.org/entity/Q8682"},
    "venue": {"value": "http://www.wikidata.org/entity/Q164027"},
    "rank": {"value": "http://wikiba.se/ontology#NormalRank"},
    "coords": {"value": "Point(-3.68835 40.45306)"},
    "caps": {"value": "83186\u001f81044"}, "elevs": {"value": "657"},
    "names": {"value": "Estadio Santiago Bernabéu\u001fBernabeu"}, "places": {"value": "Madrid\u001fChamartín"},
    "countries": {"value": "Spain"},
}, {
    "team": {"value": "http://www.wikidata.org/entity/Q8682"},
    "venue": {"value": "http://www.wikidata.org/entity/Q9999"},
    "rank": {"value": "http://wikiba.se/ontology#DeprecatedRank"},
    "end": {"value": "1947-12-14T00:00:00Z"},
}]}}


def test_the_query_names_only_items_and_asks_the_home_venue_facts() -> None:
    q = build_query(["Q8682", "Q18656"])
    assert "wd:Q8682 wd:Q18656" in q and "P115" in q and "P625" in q and "P2044" in q and "P1083" in q
    with pytest.raises(ValueError):
        build_query(["Q1 } DELETE {"])


def test_fetch_batches_one_request_a_minute_and_the_file_is_pinned(tmp_path: Path) -> None:
    asked: list[str] = []
    slept: list[float] = []

    def post(query: str) -> Mapping[str, Any]:
        asked.append(query)
        return ANSWER

    out = tmp_path / "wd.json"
    digest = fetch_snapshot([f"Q{i}" for i in range(1, 6)] + ["Q3"], out, post=post, batch=2, sleep=slept.append)
    assert len(asked) == 3 and slept == [65.0, 65.0]
    assert digest == sha256_of(out)
    snap = read_snapshot(out, digest)
    assert snap.query_version == QUERY_VERSION and snap.teams_asked == {"Q1", "Q2", "Q3", "Q4", "Q5"}
    v = snap.venues["Q164027"]
    assert v.coords == {(40.45306, -3.68835)} and v.capacities == {83186, 81044} and v.elevations == {657.0}
    assert "Bernabeu" in v.names and "Madrid" in v.places and v.countries == {"Spain"}
    ranks = {h.venue_qid: h.rank for h in snap.homes["Q8682"]}
    assert ranks == {"Q164027": "normal", "Q9999": "deprecated"}
    with pytest.raises(SnapshotError):
        read_snapshot(out, "0" * 64)


def test_a_snapshot_of_another_query_version_is_refused(tmp_path: Path) -> None:
    out = tmp_path / "old.json"
    out.write_text(json.dumps({"query_version": "venue-wd-v0", "fetched_at": "2026-11-17T00:00:00+00:00",
                               "batches": []}))
    with pytest.raises(SnapshotError):
        read_snapshot(out, sha256_of(out))


def test_an_overloaded_endpoint_is_asked_again_after_a_longer_pause_and_nothing_is_written_if_it_never_answers(
        tmp_path: Path) -> None:
    calls: list[int] = []
    slept: list[float] = []

    def flaky(query: str) -> Mapping[str, Any]:
        calls.append(1)
        if len(calls) < 3:
            raise TransientError("HTTP 502")
        return ANSWER

    out = tmp_path / "wd.json"
    fetch_snapshot(["Q1"], out, post=flaky, sleep=slept.append)
    assert len(calls) == 3 and slept == [65.0, 130.0] and out.exists()

    def down(query: str) -> Mapping[str, Any]:
        raise TransientError("HTTP 502")

    never = tmp_path / "never.json"
    with pytest.raises(TransientError):
        fetch_snapshot(["Q1"], never, post=down, sleep=slept.append, retries=2)
    assert not never.exists()
