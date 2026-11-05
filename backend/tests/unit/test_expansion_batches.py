"""BE-002: batch 2 of config/expansion.yaml (World Cup qualifiers Africa and Oceania, AFC Asian Cup), the identity
check of scripts.expand_leagues, and the refusal of a mass untracking by ``manage_competitions apply``."""

from __future__ import annotations

from argparse import Namespace
from pathlib import Path
from typing import Any

import pytest

from fbi.catalog import activation
from fbi.catalog.activation import ActivationDiff, mass_disable_refusal
from fbi.migration.config import (
    EXPANSION_FILE,
    expansion_batches,
    load_migration_config,
)

BATCH2 = {29: "World Cup - Qualification Africa", 33: "World Cup - Qualification Oceania", 7: "Asian Cup"}


def test_batch_2_holds_exactly_the_three_competitions_the_owner_asked_for() -> None:
    batches = {int(b["batch"]): b for b in expansion_batches(EXPANSION_FILE)}
    assert sorted(batches) == [1, 2]
    b2 = batches[2]
    assert b2["tier"] == 6 and b2["leagues"] == [29, 33, 7]
    assert b2["names"] == BATCH2
    assert b2["countries"] == {29: "World", 33: "World", 7: "World"}
    assert batches[1]["leagues"] == [252, 250, 244, 99, 100, 180, 183, 255, 506], "batch 1 is untouched"


def test_batch_2_is_migrated_as_its_own_tier_and_is_new_to_the_selection() -> None:
    cfg = load_migration_config()
    selection = {c.league_id for c in cfg.competitions if c.tier <= 4}
    assert not selection & set(BATCH2), "none of the three was already in tiers 1-4"
    assert {30, 31, 32, 34, 37} <= selection, "the other confederations' qualifiers are in the selection"
    assert cfg.tiers[6] == "P3 expansion - batch 2"
    assert sorted((c.league_id, c.name) for c in cfg.tier_competitions({6})) == sorted(BATCH2.items())


def test_batch_2_is_listed_for_the_probe_as_well() -> None:
    from scripts.probe_leagues import candidates

    listed = {int(c["league_id"]): c for c in candidates()}
    assert {lid: listed[lid]["name"] for lid in BATCH2} == BATCH2
    ranks = [int(c["rank"]) for c in candidates()]
    assert len(ranks) == len(set(ranks)), "ranks are unique"


def _state(lid: int, name: str | None, country: str | None, seasons: int = 2) -> dict[str, Any]:
    return {"provider_league_id": lid, "provider_name": name, "provider_country": country, "seasons_listed": seasons}


def test_identity_check_compares_name_and_country_with_the_provider() -> None:
    from scripts.expand_leagues import identity_mismatches

    batch = {"names": {29: "World Cup - Qualification Africa", 7: "Asian Cup", 5: "5"},
             "countries": {29: "World", 7: "World"}}
    ok = [_state(29, "World Cup -  Qualification AFRICA", "World"), _state(7, "Asian Cup", "world"),
          _state(5, "Whatever the provider says", "Anywhere")]
    assert identity_mismatches(batch, ok) == [], "case and spacing do not matter; a non-candidate is not checked"
    wrong = [_state(29, "Africa Cup of Nations", "World"), _state(7, "Asian Cup", "Qatar"),
             _state(33, None, None, seasons=0)]
    assert identity_mismatches(batch, wrong) == [
        "29: provider calls it 'Africa Cup of Nations', config says 'World Cup - Qualification Africa'",
        "7: provider country 'Qatar', config says 'World'",
    ]


def _diff(disabled: int) -> ActivationDiff:
    return ActivationDiff(enabled=[], disabled=list(range(1, disabled + 1)), unknown=[], unchanged=0)


def test_mass_disable_is_refused_above_the_limit() -> None:
    assert mass_disable_refusal(_diff(0)) is None
    assert mass_disable_refusal(_diff(activation.MAX_DISABLE_WITHOUT_CONFIRMATION)) is None
    refusal = mass_disable_refusal(_diff(131))
    assert refusal is not None and "131 competitions" in refusal and "--allow-mass-disable" in refusal


class _Conn:
    def __enter__(self) -> _Conn:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def commit(self) -> None:
        raise AssertionError("nothing may be committed")


@pytest.mark.parametrize("allow", [False, True])
def test_manage_competitions_apply_with_the_stale_pilot_file_writes_nothing_unless_forced(
        monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str], allow: bool) -> None:
    """The real config/competitions.yaml against a production-like catalogue of 131 tracked competitions."""
    import scripts.manage_competitions as mc

    calls: list[bool] = []

    def fake_apply(conn: Any, toggles: Any, *, dry_run: bool) -> ActivationDiff:
        calls.append(dry_run)
        if not dry_run:
            raise RuntimeError("written")
        return _diff(131)

    monkeypatch.setattr(mc, "_connect", _Conn)
    monkeypatch.setattr(mc.activation, "apply", fake_apply)
    monkeypatch.setattr(mc.activation, "active_league_ids", lambda conn: [])
    args = Namespace(config=str(Path(mc.DEFAULT_CONFIG)), dry_run=False, allow_mass_disable=allow)
    if allow:
        with pytest.raises(RuntimeError, match="written"):
            mc.cmd_apply(args)
        assert calls == [False], "an explicit --allow-mass-disable goes straight to the write"
    else:
        assert mc.cmd_apply(args) == 1
        assert calls == [True], "only the dry run ran"
        assert "REFUSED, nothing written" in capsys.readouterr().out


def test_manage_competitions_dry_run_still_shows_the_diff(monkeypatch: pytest.MonkeyPatch) -> None:
    import scripts.manage_competitions as mc

    calls: list[bool] = []

    def fake_apply(conn: Any, toggles: Any, *, dry_run: bool) -> ActivationDiff:
        calls.append(dry_run)
        return _diff(131)

    monkeypatch.setattr(mc, "_connect", _Conn)
    monkeypatch.setattr(mc.activation, "apply", fake_apply)
    monkeypatch.setattr(mc.activation, "active_league_ids", lambda conn: [])
    args = Namespace(config=str(mc.DEFAULT_CONFIG), dry_run=True, allow_mass_disable=False)
    assert mc.cmd_apply(args) == 0 and calls == [True]
