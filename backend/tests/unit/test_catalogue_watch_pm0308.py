"""PM-03-08 (Plan Maestro PM, DOC-010): the limitations of config/catalogue_watch.yaml and the watch that says when the provider
lists one of them - by identifier, never by name - tried on a simulated catalogue."""

from __future__ import annotations

from typing import Any

import pytest

from fbi.catalog import watch
from fbi.catalog.watch import Listed
from fbi.ingestion import catalogue_refresh

PRIORITY = {
    "Colombia", "World", "Argentina", "Brazil", "Chile", "Uruguay", "Mexico", "USA", "Panama", "England", "Scotland", "Spain",
    "Italy", "Germany", "France", "Portugal", "Belgium", "Denmark", "Austria", "Turkey", "Japan", "South-Korea", "India",
    "Saudi-Arabia", "Qatar", "United-Arab-Emirates", "Egypt", "Australia",
}
"""Colombia, the internationals and the 26 countries of section 3 of the plan, as the provider spells them."""


@pytest.fixture(scope="module")
def config() -> watch.WatchConfig:
    return watch.load()


def _baseline(config: watch.WatchConfig) -> list[Listed]:
    """The catalogue as it was on the baseline date: every known id, the waiting ones at their last season."""
    last = {w.league_id: w.last_season for w in config.waiting}
    return [Listed(lid, f"league {lid}", country, last.get(lid, 2026)) for country, ids in config.known.items() for lid in ids]


def test_the_file_holds_the_limitations_of_the_plan(config: watch.WatchConfig) -> None:
    assert set(config.known) == PRIORITY
    assert sum(len(v) for v in config.known.values()) == 702
    assert len(config.missing) == 11
    assert {m["country"] for m in config.missing} <= set(config.known)
    assert {w.league_id for w in config.waiting} == {264, 65, 1032, 808, 806, 35, 960, 858, 548, 1186}
    assert {w.league_id for w in config.waiting if w.kind == "descontinuada"} == {264, 65, 1032, 808}
    for w in config.waiting:
        assert w.league_id in config.known[w.country], w
    # ids that cannot be in two countries
    ids = [lid for v in config.known.values() for lid in v]
    assert len(ids) == len(set(ids))


def test_the_baseline_itself_has_nothing_new(config: watch.WatchConfig) -> None:
    assert watch.findings(_baseline(config), config) == []


def test_a_league_added_in_a_priority_country_is_reported(config: watch.WatchConfig) -> None:
    listed = [*_baseline(config), Listed(1300, "Copa Panamá", "Panama", 2027)]
    found = watch.findings(listed, config)
    assert [(f.kind, f.league_id, f.country, f.season) for f in found] == [("nueva", 1300, "Panama", 2027)]
    assert "Panama had 1 leagues" in found[0].detail


def test_a_league_added_elsewhere_is_not(config: watch.WatchConfig) -> None:
    assert watch.findings([*_baseline(config), Listed(1301, "Cup", "Norway", 2027)], config) == []


def test_a_renamed_competition_is_not_new(config: watch.WatchConfig) -> None:
    renamed = [Listed(r.league_id, "Liga Panameña (nuevo nombre)", r.country, r.newest_season) if r.league_id == 304 else r
               for r in _baseline(config)]
    assert watch.findings(renamed, config) == []


def test_the_country_is_compared_without_case_or_spaces(config: watch.WatchConfig) -> None:
    found = watch.findings([*_baseline(config), Listed(1302, "Super Cup", " south-korea ", 2027)], config)
    assert [f.league_id for f in found] == [1302]


def test_a_discontinued_or_cyclical_competition_coming_back_is_reported(config: watch.WatchConfig) -> None:
    listed = [Listed(r.league_id, r.name, r.country, 2027 if r.league_id in (264, 806) else r.newest_season)
              for r in _baseline(config)]
    found = watch.findings(listed, config)
    assert [(f.kind, f.league_id, f.season) for f in found] == [("edicion", 264, 2027), ("edicion", 806, 2027)]
    assert found[0].detail == "descontinuada: newest season was 2019"


def test_the_switch_is_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(watch.SWITCH, raising=False)
    assert watch.watch_on() is False
    for value in ("1", "on", "TRUE", "yes"):
        monkeypatch.setenv(watch.SWITCH, value)
        assert watch.watch_on() is True
    monkeypatch.setenv(watch.SWITCH, "off")
    assert watch.watch_on() is False


def test_notes_are_short() -> None:
    assert watch.notes([]) == "watch: nothing new"
    many = [watch.Finding("nueva", 2000 + i, "x", "Panama", 2027, "d") for i in range(12)]
    note = watch.notes(many, limit=2)
    assert note.startswith("watch: 12 finding(s): nueva 2000 x (Panama) 2027: d; nueva 2001")
    assert note.endswith("(+10 more)")


class _Conn:
    def __init__(self) -> None:
        self.rolled_back = False

    def rollback(self) -> None:
        self.rolled_back = True


def test_the_refresh_notes_the_findings(monkeypatch: pytest.MonkeyPatch) -> None:
    found = [watch.Finding("nueva", 1300, "Copa Panamá", "Panama", 2027, "d")]
    monkeypatch.setattr(watch, "check", lambda conn: found)
    assert catalogue_refresh.watch_catalogue(_Conn()) == "watch: 1 finding(s): nueva 1300 Copa Panamá (Panama) 2027: d"  # type: ignore[arg-type]


def test_a_failing_watch_never_fails_the_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    def boom(conn: Any) -> list[watch.Finding]:
        raise RuntimeError("no table")

    monkeypatch.setattr(watch, "check", boom)
    conn = _Conn()
    assert catalogue_refresh.watch_catalogue(conn) == "watch failed: RuntimeError"  # type: ignore[arg-type]
    assert conn.rolled_back
