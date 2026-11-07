"""The rules of the guides that need no database (UX-032): the closed lists and the contract that carries them."""

from __future__ import annotations

import pytest

from fbi.api.contracts.guides import GuideIn, GuideState
from fbi.customer import guides
from fbi.customer.db import CustomerError


def test_the_ten_guides_and_their_steps() -> None:
    assert guides.GUIDES == ("general", "home", "matches", "live", "match", "picks", "parlays", "odds", "my_picks",
                             "profile")
    assert set(guides.STEPS) == set(guides.GUIDES)
    assert guides.STEPS["general"] == 6 and guides.STEPS["profile"] == 6
    assert {guides.STEPS[g] for g in guides.GUIDES if g not in ("general", "profile")} == {3}
    assert frozenset({"profile"}) == guides.MANDATORY


def test_the_status_order_never_goes_down() -> None:
    assert sorted(guides.RANK, key=guides.RANK.__getitem__) == ["pending", "in_progress", "skipped", "completed"]


@pytest.mark.parametrize(("guide", "version", "status", "step", "code"), [
    ("nothing", 1, "pending", 0, "unknown_guide"),
    ("picks", 0, "pending", 0, "invalid_version"),
    ("picks", 100, "pending", 0, "invalid_version"),
    ("picks", 1, "seen", 0, "invalid_status"),
    ("picks", 1, "pending", 3, "invalid_step"),
    ("picks", 1, "pending", -1, "invalid_step"),
    ("profile", 1, "pending", 6, "invalid_step"),
])
def test_what_the_closed_lists_refuse(guide: str, version: int, status: str, step: int, code: str) -> None:
    with pytest.raises(CustomerError) as raised:
        guides.check(guide, version, status, step)
    assert (raised.value.status, raised.value.code) == (422, code)


def test_what_they_accept() -> None:
    guides.check("profile", 99, "completed", 5)
    guides.check("general", 1, "skipped", 5)


def test_the_contract_and_the_lists_say_the_same() -> None:
    assert set(GuideState.model_fields["guide"].annotation.__args__) == set(guides.GUIDES)  # type: ignore[union-attr]
    assert GuideIn(version=1, status="pending").step == 0
    with pytest.raises(ValueError):
        GuideIn(version=1, status="pending", extra=1)  # type: ignore[call-arg]


def test_the_switch_is_on_unless_it_is_zero(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(guides.SWITCH, raising=False)
    assert guides.guides_on() is True
    for value, expected in (("1", True), ("0", False), ("off", False), ("", True)):
        monkeypatch.setenv(guides.SWITCH, value)
        assert guides.guides_on() is expected, value
