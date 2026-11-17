"""IA-077 (owner's decision no. 10): batches 3 and 4 of config/expansion.yaml - Venezuela's Primera and Colombia's
Primera B, then Uruguay's Primera and Copa Colombia - with the measurement they were decided on, and the way back
(``scripts.expand_leagues --untrack``)."""

from __future__ import annotations

from collections import Counter
from typing import Any

import pytest
import yaml

from fbi.migration.config import EXPANSION_FILE, expansion_batches, load_migration_config

# As raw.league_coverage names them (newest season, refreshed 17 Nov 2026 00:28 UTC): the identity check of
# scripts.expand_leagues compares exactly these.
BATCH3 = {299: ("Primera División", "Venezuela"), 240: ("Primera B", "Colombia")}
BATCH4 = {268: ("Primera División", "Uruguay"), 241: ("Copa Colombia", "Colombia")}
SHARES = ("events", "lineups", "team_stats", "player_stats", "goals_match_events")
FLAGS = ("events", "lineups", "statistics_fixtures", "statistics_players", "standings", "injuries", "odds")
LINEUPS_BAR, GOALS_BAR = 0.80, 0.95
"""Batch 1's data rule (config/expansion.yaml): both line-ups of eleven in 80 %, goal events = score in 95 %."""


def _raw() -> dict[str, Any]:
    raw: dict[str, Any] = yaml.safe_load(EXPANSION_FILE.read_text(encoding="utf-8"))
    return raw


def _batches() -> dict[int, dict[str, Any]]:
    return {int(b["batch"]): b for b in expansion_batches(EXPANSION_FILE)}


@pytest.mark.parametrize(("number", "tier", "expected"), [(3, 7, BATCH3), (4, 8, BATCH4)])
def test_each_batch_holds_its_two_competitions_with_the_providers_names(
        number: int, tier: int, expected: dict[int, tuple[str, str]]) -> None:
    b = _batches()[number]
    assert b["tier"] == tier and b["leagues"] == list(expected)
    assert b["names"] == {lid: name for lid, (name, _) in expected.items()}
    assert b["countries"] == {lid: country for lid, (_, country) in expected.items()}
    assert b["decided"] == "2026-11-17" and "decision no. 10" in b["rule"]


def test_no_league_is_in_two_batches_and_every_one_is_a_candidate_with_a_country() -> None:
    raw = _raw()
    listed = Counter(int(lid) for b in raw["batches"] for lid in b["leagues"])
    assert [lid for lid, n in listed.items() if n > 1] == []
    candidates = {int(c["league_id"]): c for c in raw["candidates"]}
    assert set(listed) <= set(candidates), "a batch league outside the candidates would skip the identity check"
    assert all(candidates[lid].get("country") for lid in (*BATCH3, *BATCH4))
    ranks = [int(c["rank"]) for c in raw["candidates"]]
    assert len(ranks) == len(set(ranks))


def test_batches_3_and_4_are_migrated_as_their_own_tiers_after_the_selection() -> None:
    cfg = load_migration_config()
    selection = {c.league_id for c in cfg.competitions if c.tier <= 4}
    assert not selection & {*BATCH3, *BATCH4}, "none of the four is in the selector's tiers 1-4"
    assert cfg.tiers[7] == "P3 expansion - batch 3" and cfg.tiers[8] == "P3 expansion - batch 4"
    assert sorted(c.league_id for c in cfg.tier_competitions({7})) == sorted(BATCH3)
    assert sorted(c.league_id for c in cfg.tier_competitions({8})) == sorted(BATCH4)
    assert sorted(c.league_id for c in cfg.tier_competitions({5, 6})) == sorted(
        [252, 250, 244, 99, 100, 180, 183, 255, 506, 29, 33, 7]), "batches 1 and 2 are untouched"


@pytest.mark.parametrize("number", [3, 4])
def test_every_league_carries_its_measurement(number: int) -> None:
    b = _batches()[number]
    measured = {int(k): v for k, v in b["measured"].items()}
    assert sorted(measured) == sorted(b["leagues"])
    for lid, m in measured.items():
        assert m["season"] == 2026 and m["sampled"] == 20 and m["unresolved"] == 0, lid
        assert m["finished"] + m["ahead"] <= m["fixtures"], lid
        assert all(0.0 <= float(m[k]) <= 1.0 for k in SHARES), lid
        assert sorted(m["flags"]) == sorted(FLAGS) and all(isinstance(v, bool) for v in m["flags"].values()), lid
        assert m["bookmakers"] is None or float(m["bookmakers"]) > 0, "null means not measured, never 0"


def test_batch_3_passes_the_data_rule_and_batch_4_is_marked_below_it() -> None:
    batches = _batches()
    for m in batches[3]["measured"].values():
        assert m["events"] > 0 and m["lineups"] >= LINEUPS_BAR and m["goals_match_events"] >= GOALS_BAR
    four = batches[4]["measured"]
    assert all(m["lineups"] < LINEUPS_BAR for m in four.values()), "else it belongs in batch 3"
    assert "BELOW" in batches[4]["rule"], "the batch says it is tracked by decision, not because it passes"


def test_no_league_of_the_four_has_player_statistics() -> None:
    """Decision no. 7: no player market without player statistics. Nothing here may claim them."""
    for number in (3, 4):
        for m in _batches()[number]["measured"].values():
            assert m["player_stats"] == 0.0 and m["flags"]["statistics_players"] is False
        assert "player market" in _batches()[number]["notes"]


def test_the_season_ahead_is_why_their_value_starts_in_2027() -> None:
    """The calendar part of batch 1's rule (25 fixtures ahead or a season into 2027) fails for all four today."""
    for number in (3, 4):
        assert all(m["ahead"] < 25 for m in _batches()[number]["measured"].values())


class _Conn:
    def __enter__(self) -> _Conn:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


@pytest.mark.parametrize(("argv", "apply", "untrack", "said"), [
    (["--batch", "3"], False, False, "dry run (track)"),
    (["--batch", "3", "--untrack"], False, True, "dry run (untrack)"),
    (["--batch", "4", "--untrack", "--apply"], True, True, "untracked in run 7"),
    (["--batch", "4", "--apply"], True, False, "tracked in run 7"),
])
def test_untrack_is_a_dry_run_until_apply(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
                                          argv: list[str], apply: bool, untrack: bool, said: str) -> None:
    import psycopg
    import scripts.expand_leagues as el

    seen: dict[str, Any] = {}

    def fake_expand(conn: Any, batch: dict[str, Any], *, apply: bool, untrack: bool = False) -> dict[str, Any]:
        seen.update(batch=batch["batch"], apply=apply, untrack=untrack)
        out: dict[str, Any] = {"batch": batch["batch"], "tier": batch["tier"], "leagues": [], "missing": []}
        if apply:
            out.update(catalogue={"tracked": 1}, run_id=7)
        return out

    monkeypatch.setattr(psycopg, "connect", lambda *a, **k: _Conn())
    monkeypatch.setattr(el, "expand", fake_expand)
    assert el.main(argv) == 0
    assert seen == {"batch": int(argv[1]), "apply": apply, "untrack": untrack}
    assert said in capsys.readouterr().out
