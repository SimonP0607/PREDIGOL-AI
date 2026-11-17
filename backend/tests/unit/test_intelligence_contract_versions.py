"""A change of an Intelligence contract's shape carries the version it needs (AD-J01, IA-057).

``tests/snapshots/intelligence_contracts.json`` keeps each registered contract's version and the facts of its two JSON
Schemas. A change that only adds (a field, a closed value) needs a new minor version; one that removes, retypes, makes a
field optional or opens a union needs a new major one - and goes with the web in the same PR. A deliberate change rewrites
the file with ``python -m scripts.intelligence_contracts write --reason "..."``; this test only says whether the code and
the file agree, and which version a change needs.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, ClassVar, Literal

import pytest
from scripts import intelligence_contracts as tool

from fbi.api.contracts.intelligence.base import IntelligenceContract, IntelligenceModel, Missing
from fbi.api.contracts.intelligence.versioning import required_bump, schema_facts, version_problem


def test_every_registered_contract_has_the_shape_and_version_kept_in_the_snapshot() -> None:
    kept, now = tool.stored()["contracts"], tool.current()
    found = tool.problems(kept, now)
    assert not found, "\n".join(found)
    diff = tool.differences(kept, now)
    assert not diff, ("an Intelligence contract changed. Raise its CONTRACT_VERSION as the change needs and rewrite the "
                      'snapshot:\n  python -m scripts.intelligence_contracts write --reason "IA-0NN: ..."\n'
                      + "\n".join(diff[:60]))


def test_every_change_of_the_snapshot_carries_a_date_and_a_reason() -> None:
    changes = tool.stored()["changes"]
    assert changes
    for change in changes:
        assert set(change) == {"date", "reason"} and len(change["reason"].strip()) >= 10, change


# ── what is additive and what breaks ─────────────────────────────────────────────────────────────────────────────────

class V1(IntelligenceModel):
    name: str
    state: Literal["a", "b"]
    count: int


class AddsAField(V1):
    note: str | None = None


class AddsAValue(IntelligenceModel):
    name: str
    state: Literal["a", "b", "c"]
    count: int


class RemovesAField(IntelligenceModel):
    name: str
    state: Literal["a", "b"]


class RemovesAValue(IntelligenceModel):
    name: str
    state: Literal["a"]
    count: int


class Retypes(IntelligenceModel):
    name: str
    state: Literal["a", "b"]
    count: float


class MayBeMissing(IntelligenceModel):
    name: str
    state: Literal["a", "b"]
    count: int | Missing


class MayBeAbsent(IntelligenceModel):
    name: str
    state: Literal["a", "b"]
    count: int = 0


def facts(model: type[IntelligenceModel]) -> frozenset[str]:
    return schema_facts(model.model_json_schema(mode="serialization"))


@pytest.mark.parametrize(("model", "bump"), [
    (V1, "none"), (AddsAField, "minor"), (AddsAValue, "minor"), (RemovesAField, "major"), (RemovesAValue, "major"),
    (Retypes, "major"), (MayBeMissing, "major"),
])
def test_what_each_change_needs(model: type[IntelligenceModel], bump: str) -> None:
    assert required_bump(facts(V1), facts(model)) == bump


def test_a_field_that_may_be_absent_in_the_answer_breaks() -> None:
    # In the answer as served, a field with a default is still always there; a field that could be left out is not.
    assert required_bump(facts(V1), facts(MayBeAbsent)) == "none"
    assert required_bump(facts(AddsAField), facts(V1)) == "major"


@pytest.mark.parametrize(("old", "new", "bump", "ok"), [
    ("1.0.0", "1.0.0", "none", True), ("1.0.0", "1.0.1", "none", True), ("1.0.0", "1.1.0", "minor", True),
    ("1.0.0", "1.0.1", "minor", False), ("1.0.0", "1.0.0", "minor", False), ("1.4.2", "2.0.0", "major", True),
    ("1.4.2", "1.5.0", "major", False), ("1.4.2", "1.4.2", "major", False), ("1.4.2", "1.3.9", "none", False),
])
def test_the_version_a_change_needs(old: str, new: str, bump: Any, ok: bool) -> None:
    assert (version_problem(old, new, bump) is None) is ok


class Kept(IntelligenceContract):
    CONTRACT_ID: ClassVar[str] = "C-77"
    CONTRACT_VERSION: ClassVar[str] = "1.0.0"
    count: int


def entry(model: type[IntelligenceContract], version: str) -> dict[str, Any]:
    return {"version": version, "public": sorted(facts(model)), "private": sorted(facts(model))}


def test_a_change_that_breaks_without_a_new_major_version_fails() -> None:
    class Changed(IntelligenceContract):
        CONTRACT_ID: ClassVar[str] = "C-77"
        CONTRACT_VERSION: ClassVar[str] = "1.1.0"
        count: float

    kept = {"C-77": entry(Kept, "1.0.0")}
    assert tool.problems(kept, {"C-77": entry(Changed, "1.0.0")}) == [
        "C-77: a change that breaks the contract needs a new major version (2.0.0), not 1.0.0"]
    assert tool.problems(kept, {"C-77": entry(Changed, "1.1.0")}) == [
        "C-77: a change that breaks the contract needs a new major version (2.0.0), not 1.1.0"]
    assert tool.problems(kept, {"C-77": entry(Changed, "2.0.0")}) == []
    assert tool.problems(kept, {}) == [
        "C-77: kept in the snapshot but no longer registered - a contract is never removed silently"]
    without_public = entry(Kept, "1.0.0") | {"public": None}
    assert tool.problems(kept, {"C-77": without_public})[0].startswith("C-77: a change that breaks")


# ── the tool ─────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture()
def scratch(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    copy = tmp_path / "intelligence_contracts.json"
    copy.write_text(tool.SNAPSHOT.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(tool, "SNAPSHOT", copy)
    return copy


def test_the_tool_refuses_to_write_without_a_reason_or_without_a_change(scratch: Path) -> None:
    before = scratch.read_text(encoding="utf-8")
    assert tool.main(["write", "--reason", "short"]) == 2
    assert tool.main(["write", "--reason", "nothing changed in this run of the tests"]) == 2
    assert tool.main(["check"]) == 0
    assert scratch.read_text(encoding="utf-8") == before


def test_the_tool_refuses_to_write_a_change_with_the_wrong_version(scratch: Path) -> None:
    data = json.loads(scratch.read_text(encoding="utf-8"))
    data["contracts"]["C-00"]["public"].append("$.a_field_that_was_removed")
    scratch.write_text(json.dumps(data), encoding="utf-8")
    assert tool.main(["check"]) == 1
    assert tool.main(["write", "--reason", "a test that must not be able to write this"]) == 2
