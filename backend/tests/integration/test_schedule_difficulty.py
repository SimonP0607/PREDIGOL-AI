"""PM-08-05: the difficulty of a team's coming matches on a real database, as of a moment - the newest Elo run computed by then (never a
later one), each rival's last rating and its recent movement, the home advantage, a fixture recorded later left out, and the
independent query of the owner's check giving the same index."""

from __future__ import annotations

import statistics
from datetime import UTC, datetime, timedelta
from itertools import count
from typing import Any

import psycopg
import pytest

from fbi.competitions import schedule_difficulty as sd
from tests.integration.helpers import scalar

pytestmark = pytest.mark.integration
AT = datetime(2026, 11, 20, 12, tzinfo=UTC)
_ids = count(97_000)


def team(db: psycopg.Connection[Any]) -> int:
    with db.cursor() as cur:
        cur.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (%s, 'T') RETURNING id", (next(_ids),))
        return scalar(cur)


def season(db: psycopg.Connection[Any]) -> int:
    with db.cursor() as cur:
        cur.execute("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type) "
                    "VALUES (%s, 'L', 'league', 'club', 'domestic_league') RETURNING id", (next(_ids),))
        comp = scalar(cur)
        cur.execute("INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, 2026) RETURNING id", (comp,))
        return scalar(cur)


def fixture(db: psycopg.Connection[Any], cs: int, home: int, away: int, ko: datetime, *, created: datetime = AT - timedelta(days=30),
            status: str = "scheduled", neutral: bool = False) -> int:
    with db.cursor() as cur:
        cur.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at, "
                    "status_short, status_group, created_at, is_neutral) VALUES (%s, %s, %s, %s, %s, 'NS', %s, %s, %s) RETURNING id",
                    (next(_ids), cs, home, away, ko, status, created, neutral))
        return scalar(cur)


def run(db: psycopg.Connection[Any], computed: datetime, ratings: dict[int, list[float]], cs: int) -> None:
    """One whole Elo run: for each team, its ratings (oldest first) over past matches against a dummy rival."""
    with db.cursor() as cur:
        cur.execute("INSERT INTO raw.ingestion_runs (job_name, job_type, status) VALUES ('elo', 'elo_refresh', 'completed') RETURNING id")
        run_id = scalar(cur)
        dummy = team(db)
        for t, values in ratings.items():
            for k, value in enumerate(values):
                ko = AT - timedelta(days=200 - 7 * k)
                fid = fixture(db, cs, t, dummy, ko, status="finished")
                cur.execute("INSERT INTO features.elo_ratings (elo_version, run_id, team_id, fixture_id, kickoff_at, rating_before, "
                            "rating_after, expected_score, actual_score, k_factor, margin_multiplier, computed_at) "
                            "VALUES ('elo-v2.0', %s, %s, %s, %s, %s, %s, 0.5, 0.5, 20, 1, %s)",
                            (run_id, t, fid, ko, value, value, computed))


def test_the_index_as_of_a_moment_and_the_independent_check(db: psycopg.Connection[Any]) -> None:
    cs = season(db)
    me, a, b, c, late = (team(db) for _ in range(5))
    hist = {a: [1600.0 + 2 * k for k in range(12)], b: [1450.0 - k for k in range(12)], c: [1700.0] * 3}
    run(db, AT - timedelta(days=1), hist, cs)
    # a newer run computed after the moment asked: never read
    run(db, AT + timedelta(hours=1), {a: [9999.0] * 12, b: [9999.0] * 12, c: [9999.0] * 12}, cs)
    fixture(db, cs, me, a, AT + timedelta(days=3))                      # at home: a gives up 65
    fixture(db, cs, b, me, AT + timedelta(days=10))                     # away: b has 65
    fixture(db, cs, me, c, AT + timedelta(days=17), neutral=True)       # neutral
    fixture(db, cs, me, late, AT + timedelta(days=24), created=AT + timedelta(hours=2))  # recorded later: not known yet
    got = sd.team_difficulty(db, me, at=AT)
    assert got.elo_run is not None and got.elo_run[0] == "elo-v2.0"
    assert [r.opponent_id for r in got.rivals] == [a, b, c]
    assert [r.venue for r in got.rivals] == ["home", "away", "neutral"]
    faced = [hist[a][-1] - 65, hist[b][-1] + 65, hist[c][-1]]
    assert got.difficulty.index == pytest.approx(sum(faced) / 3)
    assert got.difficulty.state == "incierto"  # c has three rated matches
    assert got.rivals[2].as_json()["flag"] == "pocas_partidas"
    assert got.rivals[0].sigma == pytest.approx(statistics.pstdev(hist[a][-10:]))
    assert got.as_json()["shadow"] is True

    from scripts.schedule_difficulty import INDEPENDENT_SQL

    row = db.execute(INDEPENDENT_SQL, {"team": me, "at": AT}).fetchone()
    assert row is not None and int(row[0]) == 3 and float(row[1]) == pytest.approx(got.difficulty.index)

    n, mean = sd.league_mean(db, cs, at=AT)
    assert n == 3 and mean == pytest.approx((hist[a][-1] + hist[b][-1] + hist[c][-1]) / 3)
