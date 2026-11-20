"""PM-02-07 (BE-067) on a real database: a cup season's cells split by phase. A Champions-like cup whose qualifying rounds have no
corners: its league phase grades A on its own, the previous rounds D, and the season whole (``todas``) C - the 72 % of the plan
(«la Champions sale con 72 % de córners porque suma las rondas previas»). A cup match's blocks follow its own phase only with
``FBI_AVAILABILITY_PHASES`` (``by_phase``); a league is never split; a second pass changes nothing."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import psycopg
import pytest

import fbi.coverage.job as job
import fbi.coverage.resolve as resolve
from fbi.coverage import levels
from fbi.odds.quote_taxonomy import sync_definitions
from tests.integration.test_coverage_job import NOW, competition, match, one, payload, season

pytestmark = pytest.mark.integration
START = datetime(2025, 7, 8, 19, 0, tzinfo=UTC)


@pytest.fixture()
def conn(migrated_database: str) -> Iterator[psycopg.Connection]:
    """As in test_coverage_job: the matrix's tables empty and nothing else tracked."""
    with psycopg.connect(migrated_database) as c:
        for t in ("analytics.coverage_cells", "analytics.market_availability", "analytics.coverage_fixture_facts",
                  "analytics.coverage_changes"):
            c.execute(f"DELETE FROM {t}")
        c.execute("UPDATE core.competitions SET is_tracked = false")
        c.commit()
        yield c


def _cup(c: psycopg.Connection, league: int) -> tuple[int, int]:
    comp = competition(c, league, kind="continental")
    c.execute("UPDATE core.competitions SET type = 'cup' WHERE id = %s", (comp,))
    return comp, season(c, comp, 2025)


def _round(c: psycopg.Connection, fid: int, label: str) -> None:
    c.execute("UPDATE core.fixtures SET round = %s WHERE id = %s", (label, fid))


def _champions(c: psycopg.Connection, league: int = 990201) -> tuple[int, list[int], list[int]]:
    """16 qualifying matches without corners (four rounds, the last the play-offs) and 36 league-stage matches with them."""
    _, cs = _cup(c, league)
    h = payload(c)
    pre, lg = [], []
    for i, label in enumerate(["1st Qualifying Round", "2nd Qualifying Round", "3rd Qualifying Round", "Play-offs"]):
        for k in range(4):
            fid = match(c, cs, START + timedelta(days=14 * i, hours=k), corners=(None, None), h=h)
            _round(c, fid, label)
            pre.append(fid)
    for k in range(36):
        fid = match(c, cs, START + timedelta(days=70 + 3 * k), h=h)
        _round(c, fid, f"League Stage - {k // 4 + 1}")
        lg.append(fid)
    c.commit()
    return cs, pre, lg


def _cells(c: psycopg.Connection, cs: int, datum: str) -> dict[str, tuple[object, ...]]:
    rows = c.execute("SELECT phase_key, level, n_finished, n_with_data FROM analytics.coverage_cells "
                     "WHERE competition_season_id = %s AND datum = %s", (cs, datum)).fetchall()
    return {str(r[0]): tuple(r[1:]) for r in rows}


def test_the_league_phase_of_a_cup_has_its_own_level(conn: psycopg.Connection) -> None:
    c = conn
    sync_definitions(c)
    cs, _, _ = _champions(c)
    report = job.run_pass(c, now=NOW, full=True)
    corners = _cells(c, cs, "corners")
    assert corners["todas"] == ("C", 52, 36), "36 of 52: 69 %, the qualifying rounds pull the season down"
    assert corners[job.PHASE_LEAGUE] == ("A", 36, 36), "the league phase measured on its own"
    assert corners[job.PHASE_PRE] == ("D", 16, 0)
    assert job.PHASE_KNOCKOUT not in corners, "no knock-out match played yet: no cell"
    assert _cells(c, cs, "events")[job.PHASE_LEAGUE][0] == "A"
    assert report.phase_cells == 2 * len(levels.DATA)
    markets = c.execute("SELECT count(*) FROM analytics.market_availability WHERE competition_season_id = %s", (cs,)).fetchone()
    assert markets is not None and markets[0] == len(levels.MARKETS), "the markets stay on todas"
    changes = c.execute("SELECT phase_key, count(*) FROM analytics.coverage_changes WHERE competition_season_id = %s GROUP BY 1",
                        (cs,)).fetchall()
    assert dict(changes) == {"todas": len(levels.DATA) + len(levels.MARKETS), job.PHASE_PRE: len(levels.DATA),
                             job.PHASE_LEAGUE: len(levels.DATA)}, "the first measure of every phase cell is in the history"
    # idempotent: a second pass over the same data writes no change
    job.run_pass(c, now=NOW + timedelta(minutes=5), full=True)
    again = c.execute("SELECT count(*) FROM analytics.coverage_changes WHERE competition_season_id = %s", (cs,)).fetchone()
    assert again is not None and again[0] == sum(n for _, n in changes)
    assert _cells(c, cs, "corners") == corners


def test_a_league_is_never_split(conn: psycopg.Connection) -> None:
    c = conn
    sync_definitions(c)
    comp = competition(c, 990202)
    cs = season(c, comp, 2025)
    h = payload(c)
    for k, label in enumerate(["1st Qualifying Round", "Regular Season - 1", "Regular Season - 2", "Final"]):
        _round(c, match(c, cs, START + timedelta(days=10 * k), h=h), label)
    c.commit()
    job.run_pass(c, now=NOW, full=True)
    assert set(_cells(c, cs, "corners")) == {"todas"}


def test_a_cup_match_reads_its_phase_only_when_asked(conn: psycopg.Connection) -> None:
    from fbi.api.services.availability import parlay_rules

    c = conn
    sync_definitions(c)
    _, pre, lg = _champions(c, 990203)
    job.run_pass(c, now=NOW, full=True)
    at = START + timedelta(days=200)
    off = resolve.load(c, lg[-1], at=at, rules=parlay_rules())
    on = resolve.load(c, lg[-1], at=at, rules=parlay_rules(), by_phase=True)
    early = resolve.load(c, pre[0], at=at, rules=parlay_rules(), by_phase=True)
    assert off is not None and on is not None and early is not None
    assert off.phase == "todas" and off.cells["corners"].level == "C"
    assert on.phase == job.PHASE_LEAGUE and on.cells["corners"].level == "A"
    assert early.phase == job.PHASE_PRE and early.cells["corners"].level == "D"
    assert resolve.resolve(on).phase == job.PHASE_LEAGUE
    assert resolve.resolve(on).blocks["team_stats"].level != resolve.resolve(off).blocks["team_stats"].level
    c.rollback()
    one(c, "SELECT 1")


def test_c16_shows_the_phases_only_with_the_switch(conn: psycopg.Connection, monkeypatch: pytest.MonkeyPatch) -> None:
    from fbi.api.services import availability as service

    c = conn
    sync_definitions(c)
    cs, _, lg = _champions(c, 990204)
    job.run_pass(c, now=NOW, full=True)
    comp = one(c, "SELECT competition_id FROM core.competition_seasons WHERE id = %s", (cs,))
    monkeypatch.delenv("FBI_AVAILABILITY_PHASES", raising=False)
    off = service.build(c, "competicion", competition_id=comp, at=NOW)
    assert off.competitions[0].seasons[0].phases == []
    match_off = service.build(c, "partido", fixture_id=lg[0], at=NOW)
    assert not isinstance(match_off.match, dict) and getattr(match_off.match, "phase", None) == "todas"
    monkeypatch.setenv("FBI_AVAILABILITY_PHASES", "1")
    on = service.build(c, "competicion", competition_id=comp, at=NOW)
    phases = {p.phase: {d.key: d.level for d in p.data} for p in on.competitions[0].seasons[0].phases}
    assert set(phases) == {"previa", "liga_o_grupos"}
    assert phases["liga_o_grupos"]["corners"] == "A" and phases["previa"]["corners"] == "D"
    assert getattr(service.build(c, "partido", fixture_id=lg[0], at=NOW).match, "phase", None) == "liga_o_grupos"
    c.rollback()
