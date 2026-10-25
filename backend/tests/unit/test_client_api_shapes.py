"""What the six client routes answer does not change unseen (plan UX, A0 and section 4: "instantáneas de forma").

The user layer consumes PrediGol Intelligence and never alters it, and that includes what the API already answers:
``/home``, ``/picks``, ``/daily``, ``/odds/best``, ``/me/history`` and ``/matches/{id}/center``. Their parameters and the
JSON Schema of their 200 answers (with every schema they refer to) are kept in ``tests/snapshots/client_api_shapes.json``.
A deliberate change rewrites it with ``python -m scripts.api_shapes write --reason "..."``, which appends the date and the
reason to the file; this test only says whether the code and the file agree.
"""

from __future__ import annotations

import json
from typing import Any

import pytest
from scripts import api_shapes


@pytest.fixture(scope="module")
def now() -> dict[str, Any]:
    return api_shapes.current()


def test_the_six_client_routes_answer_the_shape_kept_in_the_snapshot(now: dict[str, Any]) -> None:
    diff = api_shapes.differences(api_shapes.stored()["routes"], now)
    assert not diff, (
        "the shape of a client route changed. If it is meant, rewrite the snapshot with its reason:\n"
        '  python -m scripts.api_shapes write --reason "<phase>: <what changes and why>"\n' + "\n".join(diff))


def test_the_snapshot_covers_exactly_the_routes_the_plan_names(now: dict[str, Any]) -> None:
    assert set(now) == {f"{m.upper()} {p}" for m, p in api_shapes.ROUTES}
    assert len(api_shapes.ROUTES) == 6


def test_every_change_of_the_snapshot_carries_a_date_and_a_reason() -> None:
    changes = api_shapes.stored()["changes"]
    assert changes, "the snapshot has no history: it was written without the tool"
    for change in changes:
        assert set(change) == {"date", "reason"} and len(change["reason"].strip()) >= 10, change


def test_a_changed_field_is_reported_by_route_and_by_schema(now: dict[str, Any]) -> None:
    """The comparison would see a change: a field removed from one schema of one route shows up in words."""
    altered = json.loads(json.dumps(now))
    route = "GET /api/v1/home"
    name, schema = next((n, s) for n, s in altered[route]["schemas"].items() if s.get("properties"))
    schema["properties"].pop(next(iter(schema["properties"])))
    diff = api_shapes.differences(now, altered)
    assert diff and all(line.startswith(f"{route}: schema {name} changed") for line in diff), diff


def test_a_new_parameter_is_reported() -> None:
    old = {"GET /x": {"parameters": [], "answer": {}, "schemas": {}}}
    new = {"GET /x": {"parameters": [{"name": "q", "in": "query", "required": False, "schema": {}}], "answer": {},
                      "schemas": {}}}
    assert api_shapes.differences(old, new) == [
        "GET /x: parameters changed: [] -> [{'name': 'q', 'in': 'query', 'required': False, 'schema': {}}]"]


@pytest.fixture()
def scratch_copy(tmp_path: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """The tool pointed at a copy of the snapshot: a test never rewrites the real file, whatever it finds."""
    copy = tmp_path / "client_api_shapes.json"
    copy.write_text(api_shapes.SNAPSHOT.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(api_shapes, "SNAPSHOT", copy)
    return copy


def test_the_tool_refuses_to_write_without_a_reason(scratch_copy: Any, capsys: pytest.CaptureFixture[str]) -> None:
    before = scratch_copy.read_text(encoding="utf-8")
    assert api_shapes.main(["write", "--reason", "short"]) == 2
    assert "reason" in capsys.readouterr().err
    assert scratch_copy.read_text(encoding="utf-8") == before


def test_the_tool_refuses_to_rewrite_a_snapshot_that_is_already_current(
        scratch_copy: Any, capsys: pytest.CaptureFixture[str]) -> None:
    before = scratch_copy.read_text(encoding="utf-8")
    assert api_shapes.main(["write", "--reason", "nothing changed in this run of the tests"]) == 2
    assert "nothing changed" in capsys.readouterr().err
    assert scratch_copy.read_text(encoding="utf-8") == before


def test_a_deliberate_change_is_written_with_its_date_and_reason(scratch_copy: Any) -> None:
    document = json.loads(scratch_copy.read_text(encoding="utf-8"))
    document["routes"]["GET /api/v1/picks"]["parameters"] = []          # the stored copy is now out of date
    scratch_copy.write_text(json.dumps(document), encoding="utf-8")
    assert api_shapes.main(["write", "--reason", "a test of the history of the snapshot"]) == 0
    written = json.loads(scratch_copy.read_text(encoding="utf-8"))
    assert written["routes"] == api_shapes.current()
    assert written["changes"][-1]["reason"] == "a test of the history of the snapshot"
    assert len(written["changes"]) == len(document["changes"]) + 1
