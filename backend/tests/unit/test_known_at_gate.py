"""The moment of knowledge of every fact an agent reads (IA-061, ``fbi.ai.known_at``, ``known-at-v1``) without a database."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

from fbi.ai import known_at as ka

CUT = datetime(2032, 10, 5, 12, 0, tzinfo=UTC)
FIXTURE = 77
H = timedelta(hours=1)


def row(retrieved: datetime = CUT - H, published: datetime | None = None, fixture: int | None = FIXTURE) -> ka.Row:
    return ka.Row(fixture_id=fixture, retrieved_at=retrieved, published_at=published)


def same(r: ka.Row) -> ka.Copy:
    return ka.Copy(r.retrieved_at, r.published_at)


def test_a_fact_retrieved_and_published_by_the_cutoff_and_copied_as_it_is_is_known() -> None:
    rows = {1: row(), 2: row(published=CUT - 2 * H), 3: row(retrieved=CUT, published=CUT, fixture=None)}
    assert ka.fact_problems(FIXTURE, CUT, [1, 2, 3], {i: same(r) for i, r in rows.items()}, rows) == {}


def test_a_fact_with_no_row_cannot_be_proved_known() -> None:
    assert ka.fact_problems(FIXTURE, CUT, [9], {9: ka.Copy(CUT - H, None)}, {}) == {9: ["fact_missing"]}


def test_a_fact_retrieved_or_published_after_the_cutoff_is_refused() -> None:
    rows = {1: row(retrieved=CUT + timedelta(seconds=1)), 2: row(published=CUT + H)}
    got = ka.fact_problems(FIXTURE, CUT, [1, 2], {i: same(r) for i, r in rows.items()}, rows)
    assert got == {1: ["fact_after_cutoff"], 2: ["fact_after_cutoff"]}


def test_a_copy_that_moved_a_moment_or_lost_it_is_refused_even_when_the_row_is_in_time() -> None:
    rows = {1: row(), 2: row(published=CUT - 2 * H), 3: row()}
    copies = {1: ka.Copy(CUT - 2 * H, None), 2: ka.Copy(CUT - H, None)}  # 1: retrieved moved earlier, 2: published dropped, 3: no copy at all
    assert ka.fact_problems(FIXTURE, CUT, [1, 2, 3], copies, rows) == {1: ["fact_stamp_differs"], 2: ["fact_stamp_differs"],
                                                                       3: ["fact_stamp_differs"]}


def test_a_fact_of_another_match_is_refused_and_a_teams_fact_is_not() -> None:
    rows = {1: row(fixture=FIXTURE + 1), 2: row(fixture=None)}
    assert ka.fact_problems(FIXTURE, CUT, [1, 2], {i: same(r) for i, r in rows.items()}, rows) == {1: ["fact_other_match"]}


def test_every_code_is_in_the_closed_list() -> None:
    rows = {1: row(retrieved=CUT + H, fixture=FIXTURE + 1)}
    found = ka.fact_problems(FIXTURE, CUT, [1, 2], {1: ka.Copy(None, None)}, rows)
    assert {c for cs in found.values() for c in cs} == set(ka.CODES)


def test_the_facts_of_a_package_are_its_evidence_index_and_the_copies_are_the_packets() -> None:
    document: dict[str, Any] = {"evidence": [{"id": 5}, {"id": 3}, {"id": "7"}, {"id": True}, "junk"], "shared": {"x": 1}}
    assert ka.package_facts(document) == [5, 3]
    assert ka.package_facts({}) == []
    content = {"evidence": [{"id": 5, "retrieved_at": (CUT - H).isoformat(), "published_at": None},
                            {"id": 3, "retrieved_at": "not a moment", "published_at": "2032-10-05T10:00:00+00:00"}, {"id": False}]}
    assert ka.packet_copies(content) == {5: ka.Copy(CUT - H, None), 3: ka.Copy(None, CUT - 2 * H)}


def test_the_check_says_ok_codes_and_ids_in_plain_json() -> None:
    good = ka.Check(facts=4, problems={})
    assert good.ok and good.codes == [] and good.record() == {"version": ka.VERSION, "facts": 4, "ok": True, "codes": [], "ids": []}
    bad = ka.Check(facts=4, problems={9: ["fact_missing"], 2: ["fact_after_cutoff", "fact_stamp_differs"]})
    rec = bad.record()
    assert not bad.ok and json.loads(json.dumps(rec)) == rec
    assert rec["codes"] == ["fact_after_cutoff", "fact_missing", "fact_stamp_differs"] and rec["ids"] == [2, 9]


class _Conn:
    def __init__(self, rows: list[tuple[Any, ...]]) -> None:
        self.rows = rows
        self.asked: list[tuple[str, dict[str, Any]]] = []

    def cursor(self) -> _Conn:
        return self

    def __enter__(self) -> _Conn:
        return self

    def __exit__(self, *_: object) -> None:
        return None

    def execute(self, sql: str, params: dict[str, Any]) -> None:
        self.asked.append((sql, params))

    def fetchall(self) -> list[tuple[Any, ...]]:
        return self.rows


def test_the_rows_are_read_by_id_once_and_nothing_is_read_for_a_package_without_facts() -> None:
    conn = _Conn([(5, FIXTURE, CUT - H, None)])
    check = ka.check(conn, fixture_id=FIXTURE, cutoff=CUT, document={"evidence": [{"id": 5}, {"id": 6}]},  # type: ignore[arg-type]
                     content={"evidence": [{"id": 5, "retrieved_at": (CUT - H).isoformat()}, {"id": 6, "retrieved_at": (CUT - H).isoformat()}]})
    assert conn.asked == [(ka.ROWS_SQL, {"ids": [5, 6]})] and "ai.evidence" in ka.ROWS_SQL
    assert check.facts == 2 and check.problems == {6: ["fact_missing"]}
    empty = _Conn([])
    assert ka.check(empty, fixture_id=FIXTURE, cutoff=CUT, document={}, content={}).ok and empty.asked == []  # type: ignore[arg-type]
