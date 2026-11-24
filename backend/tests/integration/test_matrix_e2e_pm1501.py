"""PM-15-01 (Plan Maestro PM, CI-021): the availability matrix end to end, from the data of a match to what C-16 tells the page, with one
real competition per level - Primera A (A), NB I (B), K League 1 (C) and Primera B (D).

Unit tests grade a cell and draw a tab, each alone; nothing checked that a screen does not draw what the matrix denies. Here the data
of four competitions is seeded from annex B of the plan (measured in production on 19-nov-2026: the share of finished matches that
carry each datum, scaled to 40 matches), the nightly batch itself (``fbi.coverage.job``) grades them, and the real application answers
``/api/v1/matches/{id}/availability`` with ``FBI_AVAILABILITY`` on - only inside this test: production keeps it off until PM-15-03. The
four answers are kept, without the ids of this database, in ``web/src/product/match/fixtures/matriz_e2e.json``, which the web's own
test (``web/src/product/match/matrixE2E.test.tsx``) draws: the screen half of the same four cases. This test fails when the two drift
apart; ``PM1501_WRITE=1`` rewrites the file from what the batch and the API answer now (and the change is then reviewed in the PR).
"""

from __future__ import annotations

import json
import os
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest
from fastapi.testclient import TestClient

from fbi.api.app import create_app
from fbi.api.cache import clear as clear_cache
from fbi.api.deps import get_db
from fbi.coverage import job
from fbi.coverage.resolve import BLOCKS
from tests.integration.conftest import Seed
from tests.integration.signed_in import SAME_SITE, signed_in

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 22, 8, 0, tzinfo=UTC)  # a Sunday: the full pass
FIRST = datetime(2026, 10, 6, 19, 0, tzinfo=UTC)  # inside the odds window (``job.ODDS_WINDOW_START``, 5-oct-2026)
N = 40
FIXTURE = Path(__file__).resolve().parents[3] / "web" / "src" / "product" / "match" / "fixtures" / "matriz_e2e.json"
DATA = ("events", "lineups", "corners", "yellow_cards", "shots", "shots_on_target", "fouls", "xg", "player_stats", "referee")
TEAM_COLUMNS = {"corners": "corners", "yellow_cards": "yellow_cards", "shots": "shots", "shots_on_target": "shots_on_target",
                "fouls": "fouls", "xg": "expected_goals"}


@dataclass(frozen=True)
class Case:
    """One competition of the plan's fixed cases: its level, its id at API-Football, annex B's row for its 2026 season, the matches of
    the 40 seeded that carry each datum (annex B's share, rounded to the same level) and the houses that price its 1X2."""

    level: str
    league: int
    name: str
    annex_share: dict[str, float]
    annex_level: dict[str, str]
    carried: dict[str, int]
    books: int


# Annex B (``B_matriz_estadisticas_mercados.csv``, 19-nov-2026), 2026 seasons: pct_* and nivel_* of each datum.
CASES: tuple[Case, ...] = (
    Case("A", 239, "Primera A",
         {"events": 100.0, "lineups": 100.0, "corners": 99.2, "yellow_cards": 97.7, "shots": 99.5, "shots_on_target": 99.5,
          "fouls": 99.5, "xg": 79.9, "player_stats": 99.7, "referee": 100.0},
         {"events": "A", "lineups": "A", "corners": "A", "yellow_cards": "A", "shots": "A", "shots_on_target": "A", "fouls": "A",
          "xg": "C", "player_stats": "A", "referee": "A"},
         {"events": 40, "lineups": 40, "corners": 40, "yellow_cards": 39, "shots": 40, "shots_on_target": 40, "fouls": 40,
          "xg": 31, "player_stats": 40, "referee": 40}, books=10),
    Case("B", 271, "NB I",
         {"events": 100.0, "lineups": 100.0, "corners": 87.0, "yellow_cards": 87.0, "shots": 87.0, "shots_on_target": 87.0,
          "fouls": 87.0, "xg": 39.0, "player_stats": 90.9, "referee": 84.4},
         {"events": "A", "lineups": "A", "corners": "B", "yellow_cards": "B", "shots": "B", "shots_on_target": "B", "fouls": "B",
          "xg": "D", "player_stats": "B", "referee": "B"},
         {"events": 40, "lineups": 40, "corners": 35, "yellow_cards": 35, "shots": 35, "shots_on_target": 35, "fouls": 35,
          "xg": 16, "player_stats": 36, "referee": 34}, books=9),
    Case("C", 292, "K League 1",
         {"events": 100.0, "lineups": 100.0, "corners": 55.7, "yellow_cards": 55.7, "shots": 55.7, "shots_on_target": 55.7,
          "fouls": 0.0, "xg": 4.8, "player_stats": 55.7, "referee": 100.0},
         {"events": "A", "lineups": "A", "corners": "C", "yellow_cards": "C", "shots": "C", "shots_on_target": "C", "fouls": "D",
          "xg": "D", "player_stats": "C", "referee": "A"},
         {"events": 40, "lineups": 40, "corners": 22, "yellow_cards": 22, "shots": 22, "shots_on_target": 22, "fouls": 0,
          "xg": 2, "player_stats": 22, "referee": 40}, books=10),
    Case("D", 240, "Primera B",
         {"events": 100.0, "lineups": 100.0, "corners": 0.0, "yellow_cards": 0.0, "shots": 0.0, "shots_on_target": 0.0,
          "fouls": 0.0, "xg": 0.0, "player_stats": 0.0, "referee": 0.0},
         {"events": "A", "lineups": "A", "corners": "D", "yellow_cards": "D", "shots": "D", "shots_on_target": "D", "fouls": "D",
          "xg": "D", "player_stats": "D", "referee": "D"},
         {"events": 40, "lineups": 40, "corners": 0, "yellow_cards": 0, "shots": 0, "shots_on_target": 0, "fouls": 0, "xg": 0,
          "player_stats": 0, "referee": 0}, books=0),
)
RANK = {"A": 4, "B": 3, "C": 2, "D": 1, "MI": 0}


def one(c: psycopg.Connection, sql: str, params: tuple[object, ...] | None = None) -> int:
    row = c.execute(sql, params).fetchone()
    assert row is not None
    return int(row[0])


def _seed_case(c: psycopg.Connection, case: Case, k: int, seed: Seed) -> tuple[int, int, int]:
    """The competition (tracked), its 2026 season, ``N`` finished matches carrying the data of ``case.carried`` (the first ``carried``
    of them carry it, for both teams), its 1X2 priced by ``case.books`` houses, and one match to come. Returns (competition, season,
    match to come)."""
    comp = one(c, "INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type, is_tracked) "
                  "VALUES (%s, %s, 'league', 'club', 'domestic_league', true) RETURNING id", (case.league, case.name))
    cs = one(c, "INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, 2026) RETURNING id", (comp,))
    h = seed.payload_hash
    books = [one(c, "INSERT INTO market.bookmakers (provider_bookmaker_id, name) VALUES (%s, %s) ON CONFLICT (provider_bookmaker_id) "
                    "DO UPDATE SET name = EXCLUDED.name RETURNING id", (881_500 + b, f"Casa {b}")) for b in range(case.books)]
    for i in range(N):
        kickoff = FIRST + timedelta(days=i)
        fid = one(c, "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at, "
                     "status_short, status_group) VALUES (%s, %s, %s, %s, %s, 'FT', 'finished') RETURNING id",
                  (881_000_000 + k * 1000 + i, cs, seed.home_team_id, seed.away_team_id, kickoff))
        has = {d: i < case.carried[d] for d in DATA}
        c.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away, ht_goals_home, ht_goals_away) "
                  "VALUES (%s, 2, 1, 1, 0)", (fid,))
        if has["events"]:
            c.execute("INSERT INTO core.fixture_events (fixture_id, source, seq, minute, team_side, event_type, payload_hash, fetched_at) "
                      "VALUES (%s, 'api-football', 0, 23, 'home', 'Goal', %s, now())", (fid, h))
        if has["lineups"]:
            for side in ("home", "away"):
                c.execute("INSERT INTO core.fixture_lineups (fixture_id, team_side, source, payload_hash, fetched_at) "
                          "VALUES (%s, %s, 'api-football', %s, now())", (fid, side, h))
        stats = {col: (7 if has[d] else None) for d, col in TEAM_COLUMNS.items()}
        if any(v is not None for v in stats.values()):
            for side in ("home", "away"):
                c.execute("INSERT INTO core.fixture_team_stats (fixture_id, team_side, source, corners, yellow_cards, shots, "
                          "shots_on_target, fouls, expected_goals, payload_hash, fetched_at) "
                          "VALUES (%s, %s, 'api-football', %s, %s, %s, %s, %s, %s, %s, now())",
                          (fid, side, stats["corners"], stats["yellow_cards"], stats["shots"], stats["shots_on_target"],
                           stats["fouls"], None if stats["expected_goals"] is None else 1.2, h))
        if has["player_stats"]:
            for n, side in enumerate(("home", "away")):
                c.execute("INSERT INTO core.fixture_player_stats (fixture_id, team_side, source, provider_player_id, payload_hash, "
                          "fetched_at) VALUES (%s, %s, 'api-football', %s, %s, now())", (fid, side, 881_900 + n, h))
        if has["referee"]:
            c.execute("INSERT INTO core.fixture_facts (fixture_id, referee, normalizer_version, payload_hash, observed_at) "
                      "VALUES (%s, 'Árbitro de prueba', 'test-v1', %s, now())", (fid, h))
        for b in books:
            for sel in ("Home", "Draw", "Away"):
                c.execute("INSERT INTO market.final_prematch_odds (fixture_id, bookmaker_id, market_key, selection, line, odds_decimal, "
                          "provider_update_at, minutes_to_ko, fetched_at, payload_hash) VALUES (%s, %s, '1X2', %s, 0, 2.5, %s, 10, %s, %s)",
                          (fid, b, sel, kickoff - timedelta(hours=1), kickoff - timedelta(minutes=30), h))
    upcoming = one(c, "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at, "
                      "status_short, status_group) VALUES (%s, %s, %s, %s, %s, 'NS', 'scheduled') RETURNING id",
                   (881_000_000 + k * 1000 + 999, cs, seed.home_team_id, seed.away_team_id, NOW + timedelta(days=1)))
    return comp, cs, upcoming


@pytest.fixture(scope="module")
def graded(migrated_database: str, seed: Seed) -> Iterator[dict[str, tuple[int, int, int]]]:
    """The four competitions seeded and graded once by the nightly batch (a full pass, as on a Sunday). Committed: the module's
    database keeps them."""
    with psycopg.connect(migrated_database, autocommit=True) as c:
        c.execute("UPDATE core.competitions SET is_tracked = false")
        ids = {case.level: _seed_case(c, case, k, seed) for k, case in enumerate(CASES)}
    with psycopg.connect(migrated_database) as c:
        report = job.run_pass(c, now=NOW, full=True)
        assert report.stopped is None and report.graded == len(CASES), report.as_json()
    clear_cache()
    yield ids
    clear_cache()


def _client(db: psycopg.Connection) -> TestClient:
    app = signed_in(create_app(), "USER")
    app.dependency_overrides[get_db] = lambda: db
    return TestClient(app, headers=SAME_SITE)


def _normalise(match: dict[str, Any], case: Case) -> dict[str, Any]:
    """The C-16 answer without what belongs to this database (ids) or to the clock: what the web's test draws."""
    out = dict(match)
    out["fixture_id"] = 1_501_000 + RANK[case.level]
    out["competition_season_id"] = 1_501_100 + RANK[case.level]
    return out


def test_the_batch_grades_each_case_as_annex_b(graded: dict[str, tuple[int, int, int]], db: psycopg.Connection) -> None:
    """Step 1 (the data): the cells the nightly batch writes are annex B's levels, datum by datum."""
    for case in CASES:
        _, cs, _ = graded[case.level]
        rows: dict[str, str] = dict(db.execute("SELECT datum, level FROM analytics.coverage_cells WHERE competition_season_id = %s "
                               "AND phase_key = 'todas'", (cs,)).fetchall())
        assert rows == case.annex_level, (case.name, rows)
        # the seeded share is annex B's, to the level (never across a threshold)
        for d in DATA:
            assert abs(100 * case.carried[d] / N - case.annex_share[d]) <= 5.0, (case.name, d)
        market = db.execute("SELECT level FROM analytics.market_availability WHERE competition_season_id = %s AND market_key = '1X2'",
                            (cs,)).fetchone()
        assert market is not None
        assert market[0] == ("D" if case.books == 0 else "A"), (case.name, market[0])


def test_c16_tells_the_page_what_the_matrix_says(graded: dict[str, tuple[int, int, int]], db: psycopg.Connection,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    """Steps 2 and 3 (the contract and the page): with FBI_AVAILABILITY on in this test only, the match to come of each competition
    gets the blocks of its cells - a block is the worst of its data - and they are exactly the ones the web's test draws."""
    monkeypatch.setenv("FBI_AVAILABILITY", "1")
    reader = _client(db)
    answers: dict[str, Any] = {}
    for case in CASES:
        _, _, upcoming = graded[case.level]
        answer = reader.get(f"/api/v1/matches/{upcoming}/availability")
        assert answer.status_code == 200, answer.text
        body = answer.json()["data"]
        assert (body["contract"], body["projection"], body["scope"]) == ("C-16", "public", "partido")
        match = body["match"]
        blocks = {b["key"]: b for b in match["blocks"]}
        for key, data in BLOCKS.items():
            expected = min((case.annex_level[d] for d in data), key=RANK.__getitem__)
            assert blocks[key]["level"] == expected, (case.name, key, blocks[key])
            # «exists»: some finished match carries every datum of the block (a D with a few is still D: the page reads the level)
            assert blocks[key]["exists"] is all(case.carried[d] > 0 for d in data), (case.name, key)
            assert blocks[key]["n"] == N
        result = next(m for m in match["markets"] if m["key"] == "1X2")
        assert result["level"] == ("D" if case.books == 0 else "A")
        assert result["prob_computed"] is False  # no model ran: PrediGol's reading is never claimed
        answers[case.level] = {"league": case.league, "competition": case.name, "season": 2026,
                               "annex_b": case.annex_level, "match": _normalise(match, case)}
    document = {"_": "PM-15-01 (CI-021): generado por backend/tests/integration/test_matrix_e2e_pm1501.py; no editar a mano "
                     "(PM1501_WRITE=1 lo reescribe).", "cases": answers}
    text = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if os.environ.get("PM1501_WRITE") == "1":
        FIXTURE.parent.mkdir(parents=True, exist_ok=True)
        FIXTURE.write_text(text, encoding="utf-8")
    assert FIXTURE.exists(), f"{FIXTURE} falta: PM1501_WRITE=1 lo escribe"
    kept = json.loads(FIXTURE.read_text(encoding="utf-8"))
    assert kept == json.loads(text), (
        "la web dibuja otros casos que los que el lote y C-16 dan hoy: revisa el cambio y reescribe el archivo con PM1501_WRITE=1")


def test_off_the_page_reads_nothing(graded: dict[str, tuple[int, int, int]], db: psycopg.Connection,
                                    monkeypatch: pytest.MonkeyPatch) -> None:
    """As in production today: with FBI_AVAILABILITY off the same routes answer 404 and the page falls back to the match's own data."""
    monkeypatch.delenv("FBI_AVAILABILITY", raising=False)
    reader = _client(db)
    for case in CASES:
        _, _, upcoming = graded[case.level]
        assert reader.get(f"/api/v1/matches/{upcoming}/availability").status_code == 404
