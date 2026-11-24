"""An answer of an earlier minor version still reads under the current one (AD-J01; the integration of the 1.1 contracts,
23-nov-2026: «un campo nuevo ausente sigue validando; el ejemplo anterior no cambia»).

When a contract gains a minor version, the examples it had are copied unchanged to
``tests/fixtures/contracts/intelligence/<contract>/anteriores/<version>/`` before the current ones are touched. Here every such
copy, read as it was (only its version head is left out, so that the current class fills it), validates against the current
model and comes back unchanged; its public copy is still what the server builds from its private one and leaks nothing. So an
additive change is proved additive on the very payloads the web already reads.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from fbi.api.contracts.intelligence.projection import leaks, to_public
from fbi.api.contracts.intelligence.registry import CONTRACTS, ContractSpec
from fbi.api.contracts.intelligence.versioning import parse

EXAMPLES = Path(__file__).resolve().parents[1] / "fixtures" / "contracts" / "intelligence"
EARLIER = "anteriores"


def earlier_cases() -> list[Any]:
    found = []
    for spec in CONTRACTS:
        folder = EXAMPLES / spec.examples_dir / EARLIER
        if spec.superseded or not folder.is_dir():
            continue
        for version_dir in sorted(p for p in folder.iterdir() if p.is_dir()):
            for case in sorted({p.name.split(".")[0] for p in version_dir.glob("*.json")}):
                found.append(pytest.param(spec, version_dir, case, id=f"{spec.key}/{version_dir.name}/{case}"))
    return found


CASES = earlier_cases()


def read(path: Path) -> dict[str, Any]:
    data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
    return data


def as_current(data: dict[str, Any], spec: ContractSpec) -> dict[str, Any]:
    return {**data, "contract_version": spec.version}


def test_there_are_earlier_examples() -> None:
    assert CASES, "C-10 keeps its 1.0.0 examples at least"


@pytest.mark.parametrize(("spec", "version_dir", "case"), CASES)
def test_an_earlier_example_reads_under_the_current_version(spec: ContractSpec, version_dir: Path, case: str) -> None:
    earlier, current = parse(version_dir.name), parse(spec.version)
    assert earlier[0] == current[0] and earlier < current, f"{version_dir.name} is not an earlier minor of {spec.version}"
    private_data = read(version_dir / f"{case}.private.json")
    assert private_data["contract_version"] == version_dir.name, "the copy is the example as it was"
    head_less = {k: v for k, v in private_data.items() if k != "contract_version"}
    answer = spec.private.model_validate(head_less)
    assert answer.model_dump(mode="json") == as_current(private_data, spec)
    if spec.public is None:
        return
    public_data = read(version_dir / f"{case}.public.json")
    assert public_data["contract_version"] == version_dir.name
    public = spec.public.model_validate({k: v for k, v in public_data.items() if k != "contract_version"})
    assert public.model_dump(mode="json") == as_current(public_data, spec)
    projected = to_public(answer, spec.public).model_dump(mode="json")
    assert projected == as_current(public_data, spec)
    assert leaks(projected, public_schema=spec.public.model_json_schema(mode="serialization"),
                 private_schema=spec.private.model_json_schema(mode="serialization")) == []
