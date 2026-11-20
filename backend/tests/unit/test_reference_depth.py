"""The depth of the reference by coverage level and editorial priority (plan PM, PM-04-04; BE-063): the rule, the priorities file and
the feeds each depth keeps. The selection per competition against a database is in tests/integration/test_reference_depth.py."""

from __future__ import annotations

from typing import Any

import pytest

import fbi.ingestion.reference as ref
from fbi.coverage import depth, levels


@pytest.mark.parametrize(
    ("level", "priority", "expected"),
    [
        ("A", "P3", "completa"), ("B", "P4", "completa"), ("C", "P2", "media"), ("D", "P2", "minima"), ("MI", "P3", "minima"),
        ("D", "P0", "completa"), ("MI", "P1", "completa"), ("C", "P1", "completa"),
        (None, "P2", "minima"), (None, "P0", "completa"), (None, None, "completa"),
        ("C", None, "media"), ("D", None, "minima"), ("A", None, "completa"),
    ],
)
def test_the_rule_of_the_task_card(level: Any, priority: Any, expected: str) -> None:
    assert depth.depth_for(level, priority) == expected


def test_deepest_and_reaches() -> None:
    assert depth.deepest(["minima", "media"]) == "media"
    assert depth.deepest(["minima", "completa", "media"]) == "completa"
    assert depth.deepest([]) == "completa", "nothing known, nothing lowered"
    assert depth.reaches("completa", "media") and depth.reaches("media", "media") and not depth.reaches("minima", "media")


def test_the_priorities_file() -> None:
    prio = depth.priorities()
    assert len(prio) == 226, "annex A: 237 competitions with a priority, 11 of them without an API-Football id"
    assert prio[239] == prio[240] == "P0" and prio[2] == "P1" and prio[39] == "P2" and prio[299] == "P3"
    assert set(prio.values()) == set(depth.PRIORITIES)


def test_each_depth_keeps_squad_and_coach() -> None:
    """Squads go through the backfill (``people.seed_people_refresh``), coaches through ``coachs``: no feed floor names them."""
    feeds = {f.name for f in ref.FEEDS}
    assert set(depth.FEED_FLOOR) <= feeds, "every floor names a real feed"
    assert "coachs" not in depth.FEED_FLOOR and "coachs_by_id" not in depth.FEED_FLOOR
    kept = {d: sorted(f for f in feeds if depth.reaches(d, depth.FEED_FLOOR.get(f, "minima"))) for d in depth.DEPTHS}
    assert set(kept["completa"]) == feeds
    assert {"transfers", "profiles_players"} <= set(kept["media"])
    assert not {"trophies_players", "sidelined_players", "players_teams"} & set(kept["media"])
    assert not {"transfers", "profiles_players", "trophies_players", "sidelined_players", "players_teams"} & set(kept["minima"])


def test_summary_of_takes_the_latest_season_with_a_sample() -> None:
    graded = tuple[dict[str, levels.Level], dict[str, levels.Level]]
    b: levels.Level = "B"
    d: levels.Level = "D"
    full: graded = (dict.fromkeys(levels.DATA, b), dict.fromkeys(levels.MARKETS, b))
    poor: graded = (dict.fromkeys(levels.DATA, d), dict.fromkeys(levels.MARKETS, d))
    partial: graded = ({"events": "A"}, {})
    assert depth.summary_of({2026: full, 2025: poor}) == "B"
    assert depth.summary_of({2026: partial, 2025: poor}) == "D", "a season graded only in part is MI: the one before decides"
    assert depth.summary_of({2026: partial}) == "MI"


def test_player_seasons_only_p0_to_p2_and_never_minima() -> None:
    m = depth.DepthMap(by_league={1: "completa", 2: "media", 3: "completa", 4: "minima", 5: "media"},
                       priority={1: "P0", 2: "P2", 3: "P3", 4: "P2", 5: None})
    assert [lg for lg in range(1, 6) if m.player_seasons(lg)] == [1, 2, 5]


def test_a_team_takes_its_deepest_tracked_competition() -> None:
    m = depth.DepthMap(by_league={10: "minima", 11: "media"})
    assert m.of([10]) == "minima" and m.of([10, 11]) == "media"
    assert m.of([10, 999]) == "minima", "an untracked competition (a friendly) does not count"
    assert m.of([999]) == m.of([]) == "completa"


def test_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ref.DEPTH_SWITCH, raising=False)
    assert ref.depth_on() is False
    for word, on in (("on", True), ("1", True), ("true", True), ("off", False), ("0", False), ("measure", False)):
        monkeypatch.setenv(ref.DEPTH_SWITCH, word)
        assert ref.depth_on() is on


def test_off_keeps_every_target(monkeypatch: pytest.MonkeyPatch) -> None:
    """Switched off there is no view: the source is never called (no read of the matrix) and the list stays as it was."""
    calls: list[int] = []

    def source(conn: Any, at: Any) -> depth.DepthMap:
        calls.append(1)
        return depth.DepthMap(by_league={1: "minima"})

    targets = [ref.Target("team:1", {"team": 1}, ref.WEEK, {"leagues": [1]}), ref.Target("-", {}, ref.WEEK, {})]
    monkeypatch.setenv(ref.DEPTH_SWITCH, "off")
    view = ref.depth_view(None, None, source)  # type: ignore[arg-type]
    assert view is None and not calls
    assert ref.within_depth(view, "transfers", targets) is targets
    monkeypatch.setenv(ref.DEPTH_SWITCH, "on")
    view = ref.depth_view(None, None, source)  # type: ignore[arg-type]
    assert calls == [1]
    assert [t.key for t in ref.within_depth(view, "transfers", targets)] == ["-"], "a target naming no competition is kept"
    assert [t.key for t in ref.within_depth(view, "coachs", targets)] == ["team:1", "-"]
    assert ref.depth_view(None, None, None) is None, "no source given: nothing lowered"  # type: ignore[arg-type]


def test_the_worker_passes_the_depths() -> None:
    """The worker hands ``fbi.coverage.depth.current`` to both callers (it is the only place that may import both packages)."""
    from pathlib import Path

    text = (Path(__file__).resolve().parents[2] / "apps" / "worker" / "scheduler.py").read_text(encoding="utf-8")
    assert text.count("depths=reference_depth.current") == 2
