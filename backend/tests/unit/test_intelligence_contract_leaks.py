"""Nothing private reaches a reader, for every registered Intelligence contract (AD-J01, IA-057).

Generic: these tests go through ``fbi.api.contracts.intelligence.registry.CONTRACTS``, so a contract is covered the day it
is registered, with no test of its own needed for this.

* The conventions hold in each contract's models (the private class inherits from the public one and marks what it adds;
  nothing untyped), and every contract class under ``fbi`` is registered.
* Every example (``tests/fixtures/contracts/intelligence/<contract>/<case>.<projection>.json``) validates against its model
  and comes back unchanged; the public example is exactly the projection the server builds from the private one; and the
  public JSON carries no private field, no unknown key and no state other than publicada, en_juego or liquidada.
* The examples carry no real person or address.
* Every private route of a registered contract answers 403 to a reader's account, from the server.
* The check itself catches a leak (a public class with a private field, an unmarked addition, a private key in a payload).
"""

from __future__ import annotations

import importlib
import json
import pkgutil
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, ClassVar

import pytest
from fastapi.testclient import TestClient

import fbi.api.contracts.intelligence as package
from fbi.api.contracts.intelligence.base import (
    Freshness,
    IntelligenceContract,
    IntelligenceModel,
    ItemList,
    private,
)
from fbi.api.contracts.intelligence.projection import (
    ProjectionError,
    has_private,
    leaks,
    structure_problems,
    to_public,
)
from fbi.api.contracts.intelligence.registry import (
    CATALOGUE,
    CONTRACTS,
    ContractSpec,
    spec_problems,
)

EXAMPLES = Path(__file__).resolve().parents[1] / "fixtures" / "contracts" / "intelligence"
AT = datetime(2026, 11, 21, 16, 42, tzinfo=UTC)


def cases(spec: ContractSpec) -> list[str]:
    return sorted({p.name.split(".")[0] for p in (EXAMPLES / spec.examples_dir).glob("*.json")})


def load(spec: ContractSpec, case: str, projection: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((EXAMPLES / spec.examples_dir / f"{case}.{projection}.json").read_text(encoding="utf-8"))
    return data


def example_ids() -> Iterator[Any]:
    for spec in CONTRACTS:
        for case in cases(spec):
            yield pytest.param(spec, case, id=f"{spec.key}/{case}")


def dumped(model: IntelligenceContract) -> dict[str, Any]:
    data: dict[str, Any] = model.model_dump(mode="json")
    return data


# ── the conventions in the models ────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("spec", CONTRACTS, ids=lambda s: s.key)
def test_each_contract_follows_the_conventions(spec: ContractSpec) -> None:
    assert spec_problems(spec) == []


def test_every_contract_class_is_registered_once() -> None:
    for info in pkgutil.walk_packages(package.__path__, f"{package.__name__}."):
        importlib.import_module(info.name)
    todo, found = list(IntelligenceContract.__subclasses__()), set()
    while todo:
        cls = todo.pop()
        found.add(cls)
        todo.extend(cls.__subclasses__())
    ours = {c for c in found if c.__module__.startswith("fbi.")}
    registered = {spec.private for spec in CONTRACTS} | {spec.public for spec in CONTRACTS if spec.public}
    assert ours == registered, f"not registered: {sorted(c.__name__ for c in ours - registered)}"
    keys = [spec.key for spec in CONTRACTS]
    assert len(keys) == len(set(keys)) and {spec.id for spec in CONTRACTS} <= set(CATALOGUE)
    current = [spec.id for spec in CONTRACTS if not spec.superseded]
    assert len(current) == len(set(current)), "one current version per contract; an earlier major one is superseded"


def test_the_catalogue_keeps_private_routes_under_admin() -> None:
    assert len(CATALOGUE) == 15  # C-00, the twelve of the plan, C-13 and C-14 of plan EA
    for contract, planned in CATALOGUE.items():
        assert all(r.startswith("/api/v1/admin/") for r in planned.private), contract
        assert all(r.startswith("/api/v1/") and not r.startswith("/api/v1/admin/") for r in planned.public), contract


# ── the examples ─────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("spec", CONTRACTS, ids=lambda s: s.key)
def test_each_contract_has_examples_of_both_projections(spec: ContractSpec) -> None:
    assert cases(spec), f"{spec.key} has no example in {EXAMPLES / spec.examples_dir}"
    for case in cases(spec):
        names = {p.name for p in (EXAMPLES / spec.examples_dir).glob(f"{case}.*.json")}
        expected = {f"{case}.private.json"} | ({f"{case}.public.json"} if spec.public else set())
        assert names == expected, f"{spec.id}/{case}: {sorted(names)}"


@pytest.mark.parametrize(("spec", "case"), list(example_ids()))
def test_an_example_validates_and_comes_back_unchanged(spec: ContractSpec, case: str) -> None:
    private_data = load(spec, case, "private")
    answer = spec.private.model_validate(private_data)
    assert dumped(answer) == private_data
    assert answer.projection == "private"
    if spec.public is not None:
        public_data = load(spec, case, "public")
        assert dumped(spec.public.model_validate(public_data)) == public_data


@pytest.mark.parametrize(("spec", "case"), list(example_ids()))
def test_the_public_example_is_the_servers_projection_and_leaks_nothing(spec: ContractSpec, case: str) -> None:
    if spec.public is None:
        pytest.skip(f"{spec.id} has no public projection")
    projected = dumped(to_public(spec.private.model_validate(load(spec, case, "private")), spec.public))
    assert projected == load(spec, case, "public"), "the public example is not what the server would serve"
    found = leaks(projected, public_schema=spec.public.model_json_schema(mode="serialization"),
                  private_schema=spec.private.model_json_schema(mode="serialization"))
    assert found == []


EMAIL = re.compile(r"[\w.+-]+@([\w-]+\.[\w.-]+)")
"""An address has a dotted domain: a settlement rule's key (``goals_ft@v1``) is not one."""
PHONE = re.compile(r"\+\d[\d ]{6,}\d")
URL = re.compile(r"https?://([^/\"\s]+)")


def test_the_examples_carry_no_real_person_or_address() -> None:
    files = sorted(EXAMPLES.rglob("*.json"))
    assert files
    for path in files:
        text = path.read_text(encoding="utf-8")
        assert not PHONE.search(text), f"{path.name}: looks like a phone number"
        hosts = URL.findall(text) + EMAIL.findall(text)
        assert all(h.endswith(".invalid") for h in hosts), f"{path.name}: a link or an address outside .invalid {hosts}"


# ── the private routes answer 403 to a reader ────────────────────────────────────────────────────────────────────────

WITNESS = "/api/v1/admin/intelligence/matches/{fixture_id}/dossier"
"""A private route that exists today: it proves the check below works before any contract has a route of its own."""


@pytest.fixture(scope="module")
def reader_client() -> Iterator[TestClient]:
    from fbi.api.app import create_app
    from fbi.api.deps import get_db
    from fbi.api.security import current_principal
    from fbi.auth.roles import Permission, Role
    from fbi.auth.service import Principal

    reader = Principal(user_id=7, email="lector@ejemplo.invalid", display_name="Lector", role=Role.USER, language="es",
                       timezone="America/Bogota", session_id="s", session_expires_at=AT,
                       permissions=frozenset({Permission.APP}))
    app = create_app()
    app.dependency_overrides[current_principal] = lambda: reader
    app.dependency_overrides[get_db] = lambda: None
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


def mounted(client: TestClient) -> set[str]:
    return set(client.app.openapi()["paths"])  # type: ignore[attr-defined]


def concrete(route: str) -> str:
    return re.sub(r"\{[^}]+\}", "1", route)


@pytest.mark.parametrize("route", sorted({WITNESS} | {r for s in CONTRACTS for r in s.private_routes}))
def test_a_private_route_answers_403_to_a_reader(reader_client: TestClient, route: str) -> None:
    assert route in mounted(reader_client), f"{route} is registered for a contract but not mounted"
    answer = reader_client.get(concrete(route))
    assert answer.status_code == 403
    assert answer.json()["error"]["code"] == "forbidden"


@pytest.mark.parametrize("route", sorted({r for s in CONTRACTS for r in s.public_routes}) or ["(none yet)"])
def test_a_public_route_of_a_contract_is_mounted(reader_client: TestClient, route: str) -> None:
    if route == "(none yet)":
        pytest.skip("no contract has a public route yet")
    assert route in mounted(reader_client)


# ── the check catches a leak ─────────────────────────────────────────────────────────────────────────────────────────

class Item(IntelligenceModel):
    name: str


class ItemPrivate(Item):
    score: float = private(description="private")
    shown: bool = private(description="private")

    def shown_in_public(self) -> bool:
        return self.shown


class Answer(IntelligenceContract):
    CONTRACT_ID: ClassVar[str] = "C-01"
    CONTRACT_VERSION: ClassVar[str] = "1.0.0"

    items: ItemList[Item]


class AnswerPrivate(Answer):
    items: ItemList[ItemPrivate]  # type: ignore[assignment]
    cost_usd: float = private(description="private")


class Leaky(IntelligenceContract):
    CONTRACT_ID: ClassVar[str] = "C-01"
    CONTRACT_VERSION: ClassVar[str] = "1.0.0"

    cost_usd: float = private(description="private")


class Unmarked(Answer):
    items: ItemList[ItemPrivate]  # type: ignore[assignment]
    cost_usd: float


class Untyped(Answer):
    extra: dict[str, Any] = private(description="private")


FRESH = Freshness(generated_at=AT, stale=False)


def private_answer(*shown: bool) -> AnswerPrivate:
    return AnswerPrivate(freshness=FRESH, cost_usd=0.12, items=ItemList[ItemPrivate](
        items=[ItemPrivate(name=f"s{i}", score=0.5, shown=s) for i, s in enumerate(shown)]))


def test_the_projection_copies_only_public_fields_and_leaves_out_what_is_not_shown() -> None:
    public = to_public(private_answer(True, False), Answer)
    assert type(public) is Answer and type(public.items.items[0]) is Item
    assert dumped(public) == {"contract": "C-01", "contract_version": "1.0.0", "projection": "public",
                              "freshness": FRESH.model_dump(mode="json"),
                              "items": {"items": [{"name": "s0"}]}}
    nothing_shown = to_public(private_answer(False, False), Answer)
    assert dumped(nothing_shown)["items"] == {"items": [], "missing_reason": "sin_publicados"}


def test_the_projection_refuses_what_is_not_a_projection() -> None:
    with pytest.raises(ProjectionError, match="does not derive from"):
        to_public(Answer(freshness=FRESH, items=ItemList[Item](items=[Item(name="a")])), Leaky)
    with pytest.raises(ProjectionError, match="carries private fields"):
        to_public(Leaky(freshness=FRESH, cost_usd=1.0), Leaky)


def test_a_public_class_with_a_private_field_is_refused() -> None:
    assert has_private(Leaky)
    spec = ContractSpec(private=Leaky, public=Leaky)
    assert any("cannot be the public projection" in p for p in spec_problems(spec))
    assert Leaky(freshness=FRESH, cost_usd=1.0).projection == "private"


def test_an_addition_that_is_not_marked_private_is_refused() -> None:
    problems = structure_problems(Unmarked)
    assert problems == ["Unmarked.cost_usd is added to Answer without being marked private"]
    assert any("untyped" in p for p in structure_problems(Untyped))


def test_a_private_key_or_state_in_a_public_payload_is_found() -> None:
    schemas = {"public_schema": Answer.model_json_schema(mode="serialization"),
               "private_schema": AnswerPrivate.model_json_schema(mode="serialization")}
    assert leaks(dumped(to_public(private_answer(True), Answer)), **schemas) == []
    leaked = dumped(private_answer(True)) | {"projection": "public"}
    assert sorted(leaks(leaked, **schemas)) == [
        "$.cost_usd: a private field in the public projection",
        "$.items.items[].score: a private field in the public projection",
        "$.items.items[].shown: a private field in the public projection"]
    odd = dumped(to_public(private_answer(True), Answer))
    odd["items"]["items"][0] |= {"name": "en_evaluacion", "public_state": "confirmada_sombra"}
    assert sorted(leaks(odd, **schemas)) == [
        "$.items.items[].name: the state 'en_evaluacion' is not public",
        "$.items.items[].public_state: 'confirmada_sombra' is not publicada, en_juego or liquidada",
        "$.items.items[].public_state: not in the public schema",
        "$.items.items[].public_state: the state 'confirmada_sombra' is not public"]
    assert leaks(dumped(private_answer(True)) | {"cost_usd": 0}, **schemas)[-1].startswith("$.projection")
