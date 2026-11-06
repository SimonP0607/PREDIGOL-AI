"""Why a published pick has value, the factors and the key points, over HTTP in a real database (plan de cierre UX, 2.1), on the
example picks of ``test_pick_states`` (A, B, C, D published with value now; E without value at the best price; S a shadow pick;
K published, its match already kicked off). The transaction is rolled back.

«Solo verde» (UX-002) holds here too: a reader is told why there is value for a RECOMMENDED pick and for no other - not for a
caution, a rejected or a priceless one, and never for an evaluation pick, not even in the owner's preview.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from fbi.api.services import reading as reading_service
from tests.integration.test_pick_states import PLAN, World, client, data, world  # noqa: F401  (the fixture and the data)

pytestmark = pytest.mark.integration

SIX = ("summary", "context", "data", "market", "risks", "conclusion")
DERIVED = ("key_points", "value", "factors")


def reading(c: TestClient, fixture_id: int, **params: Any) -> dict[str, list[dict[str, Any]]]:
    body = data(c, f"/api/v1/matches/{fixture_id}/reading", **params)
    return {s["key"]: s["facts"] for s in body["sections"]}


def test_a_green_pick_says_why_there_is_value_with_its_own_numbers(world: World) -> None:  # noqa: F811
    got = reading(client(world.db), world.fixtures["A"])
    assert [f["code"] for f in got["value"]] == ["value_pick", "value_price"]
    pick, price = (f["params"] for f in got["value"])
    assert {f["ref"] for f in got["value"]} == {f"pick:{world.picks['A']}"}
    assert (pick["p_model"], pick["p_market"]) == (0.5, 0.43), "PrediGol's probability against the market's"
    assert (pick["market"], pick["selection"]) == ("1X2", "Home")
    assert (price["odds"], price["fair_market"], price["fair_model"], price["taken"]) == (2.3, 2.33, 2.0, False)
    assert "value_pick" in [f["code"] for f in got["key_points"]], "the point that matters most after what is expected"
    assert "value_price" not in [f["code"] for f in got["key_points"]]


def test_the_six_sections_come_first_and_the_derived_ones_after_them(world: World) -> None:  # noqa: F811
    keys = [s["key"] for s in data(client(world.db), f"/api/v1/matches/{world.fixtures['A']}/reading")["sections"]]
    assert {"key_points", "value"} <= set(keys), "no packet here, so no factor stands out: that section is left out"
    last_six = max(keys.index(k) for k in SIX if k in keys)
    assert all(keys.index(k) > last_six for k in DERIVED if k in keys)


def test_a_reader_is_told_no_value_for_a_pick_that_is_not_green(world: World, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    world.enforce(monkeypatch)  # B is downgraded, C rejected: the reader's board holds neither
    for name in ("B", "C", "E"):
        got = reading(client(world.db), world.fixtures[name])
        assert "value" not in got, f"{name}: no value section for a pick a reader is not shown"
        assert not [f for f in got.get("key_points", []) if f["code"].startswith("value")], name
    assert "value" in reading(client(world.db), world.fixtures["A"])


def test_an_evaluation_pick_never_gets_a_value_section_not_even_in_the_owners_preview(world: World) -> None:  # noqa: F811
    for c, params in ((client(world.db), {}), (client(world.db, "SUPER_ADMIN"), {"preview": "shadow"})):
        got = reading(c, world.fixtures["S"], **params)
        assert "value" not in got
        assert not [f for f in got.get("key_points", []) if f["code"].startswith("value")]


def test_after_kick_off_the_pick_is_told_as_it_was_taken(world: World) -> None:  # noqa: F811
    got = reading(client(world.db), world.fixtures["K"])
    price = next(f["params"] for f in got["value"] if f["code"] == "value_price")
    assert price["taken"] is True and price["odds"] == 2.3, "the price it was taken at, never re-priced"


def test_the_ai_narrative_reads_and_is_hashed_from_the_six_only(world: World) -> None:  # noqa: F811
    basis = reading_service.reading_basis(world.db, world.fixtures["A"])
    assert {s.key for s in basis.sections} <= set(SIX)
    first = basis.hash
    again = reading_service.reading_basis(world.db, world.fixtures["A"])
    assert again.hash == first, "a pick appearing or its price moving never invalidates a narrative"


def test_the_derived_sections_follow_the_readings_switch(world: World, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    monkeypatch.setenv(reading_service.USERS_SWITCH, "0")
    body = client(world.db).get(f"/api/v1/matches/{world.fixtures['A']}/reading").json()
    assert body["status"] == "not_available" and body["data"] is None
    owner = reading(client(world.db, "SUPER_ADMIN"), world.fixtures["A"], preview="shadow")
    assert "value" in owner, "the owner's preview does not depend on the switch"


def test_every_match_of_the_plan_answers_with_key_points_that_say_what_is_missing(world: World) -> None:  # noqa: F811
    for name in PLAN:
        got = reading(client(world.db), world.fixtures[name])
        points = got["key_points"]
        assert 1 <= len(points) <= 5, name
        assert any(f["code"] in ("forecast_missing", "expected_result") for f in points), \
            f"{name}: what PrediGol expects, or that it has no forecast yet"
