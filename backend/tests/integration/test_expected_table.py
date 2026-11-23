"""PM-09-06: the expected table on a real database, as of a moment - the newest xG row of each side, a match without the xG of both
teams left out, a result recorded later not known yet, the gate of the matrix (rows only with xG B or better), and the owner's check
recomputing every team independently (SQL subqueries and SciPy's Skellam) with no difference."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import count
from typing import Any

import psycopg
import pytest
from scripts import expected_table as command

from fbi.stats import expected_table as xt
from tests.integration.helpers import scalar

pytestmark = pytest.mark.integration
AT = datetime(2026, 11, 20, 12, tzinfo=UTC)
_ids = count(96_000)


def setup(db: psycopg.Connection[Any], kind: str = "league") -> tuple[int, list[int], str]:
    with db.cursor() as cur:
        cur.execute("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type, is_tracked) "
                    "VALUES (%s, 'L', %s, 'club', 'domestic_league', true) RETURNING id", (next(_ids), kind))
        comp = scalar(cur)
        cur.execute("INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, 2026) RETURNING id", (comp,))
        cs = scalar(cur)
        teams = []
        for name in ("Alfa", "Beta", "Gamma"):
            cur.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (%s, %s) RETURNING id", (next(_ids), name))
            teams.append(scalar(cur))
        cur.execute("INSERT INTO raw.ingestion_runs (job_name, job_type, status) VALUES ('t', 'test_seed', 'completed') RETURNING id")
        run = scalar(cur)
        h = f"xt{next(_ids)}"
        cur.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, fetched_at, http_status, file_path, bytes) "
                    "VALUES (%s, %s, '/fixtures/statistics', now(), 200, 'x', 1)", (h, run))
    return cs, teams, h


def match(db: psycopg.Connection[Any], cs: int, home: int, away: int, score: tuple[int, int], xg: tuple[float | None, float | None],
          h: str, *, day: int, settled: datetime | None = None) -> int:
    ko = AT - timedelta(days=day)
    with db.cursor() as cur:
        cur.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at, "
                    "status_short, status_group) VALUES (%s, %s, %s, %s, %s, 'FT', 'finished') RETURNING id",
                    (next(_ids), cs, home, away, ko))
        fid = scalar(cur)
        cur.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away, settled_at) VALUES (%s, %s, %s, %s)",
                    (fid, score[0], score[1], settled or ko + timedelta(hours=2)))
        for side, value in zip(("home", "away"), xg, strict=True):
            cur.execute("INSERT INTO core.fixture_team_stats (fixture_id, team_side, source, expected_goals, payload_hash, fetched_at) "
                        "VALUES (%s, %s, 'api-football', %s, %s, %s)", (fid, side, value, h, ko + timedelta(hours=3)))
    return fid


def level(db: psycopg.Connection[Any], cs: int, value: str) -> None:
    db.execute("INSERT INTO analytics.coverage_cells (competition_season_id, phase_key, datum, n_finished, n_with_data, share, level, "
               "measured_level, rules_version, measured_at) VALUES (%s, 'todas', 'xg', 30, 30, 1, %s, %s, 'coverage-levels-v1', now())",
               (cs, value, value))


def test_the_table_as_of_a_moment_and_the_independent_check(db: psycopg.Connection[Any]) -> None:
    cs, (a, b, c), h = setup(db)
    match(db, cs, a, b, (2, 0), (1.8, 0.7), h, day=20)
    match(db, cs, b, c, (1, 1), (1.1, 1.3), h, day=13)
    match(db, cs, c, a, (0, 1), (2.2, 0.4), h, day=6)
    match(db, cs, a, c, (1, 1), (None, 0.9), h, day=5)                                        # no xG for the home side
    match(db, cs, b, a, (3, 0), (2.5, 0.2), h, day=1, settled=AT + timedelta(hours=1))        # its result recorded later
    got = xt.expected_table(db, cs, at=AT)
    assert got is not None and got.visibility == "sin_medir" and got.as_json()["rows"] == []
    assert got.matches == 3 and got.without_xg == 1
    by = {x.team_id: x for x in got.lines}
    assert by[a].matches == 2 and by[a].points == 6
    assert by[a].xpts == pytest.approx(xt.expected_points(1.8, 0.7)[0] + xt.expected_points(0.4, 2.2)[0])
    assert by[c].name == "Gamma" and by[c].points == 1

    level(db, cs, "C")
    assert xt.expected_table(db, cs, at=AT).visibility == "sin_cobertura"  # type: ignore[union-attr]
    db.execute("UPDATE analytics.coverage_cells SET level = 'B' WHERE competition_season_id = %s AND datum = 'xg'", (cs,))
    shown = xt.expected_table(db, cs, at=AT)
    assert shown is not None and shown.visibility == "visible"
    j = shown.as_json()
    assert j["exposed"] is False and j["label_es"] == "xG de API-Football" and len(j["rows"]) == 3
    assert [r["team_id"] for r in j["rows"]] == [x.team_id for x in shown.lines]
    assert any(r["league"] == shown.league and r["visibility"] == "visible" for r in xt.eligible(db))

    other = command.independent(db.execute(command.INDEPENDENT_SQL, {"cs": cs, "at": AT}).fetchall())
    assert set(other) == {a, b, c}
    for line in shown.lines:
        n, xpts, pts = other[line.team_id]
        assert (n, pts) == (line.matches, line.points) and xpts == pytest.approx(line.xpts, abs=1e-6)


def test_a_cup_never_has_an_expected_table(db: psycopg.Connection[Any]) -> None:
    cs, (a, b, _), h = setup(db, "cup")
    match(db, cs, a, b, (1, 0), (1.0, 0.5), h, day=3)
    level(db, cs, "A")
    got = xt.expected_table(db, cs, at=AT)
    assert got is not None and got.visibility == "no_es_liga" and got.as_json()["rows"] == []
