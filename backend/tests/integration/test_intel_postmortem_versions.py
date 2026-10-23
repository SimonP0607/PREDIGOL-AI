"""Plan F0, defect 6, on a real database: pm-v4 (and so pm-v5) does not read a penalty shoot-out as a penalty of the match, and
the readers of the post-mortems count a decision once when it has been judged under two versions.

The transaction is rolled back afterwards."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fbi.intel import memory, postmortem, report

from .conftest import Seed
from .helpers import scalar

KICKOFF = datetime(2032, 9, 20, 18, tzinfo=UTC)
AFTER = KICKOFF + timedelta(hours=6)


def _world(db: psycopg.Connection[Any], seed: Seed) -> tuple[int, int]:
    """One finished match that went to a shoot-out, one decision on it, its outcome. Returns (fixture, decision)."""
    teams = [scalar(db.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (%s, %s) RETURNING id",
                               (989000 + n, f"Shootout {n}"))) for n in (1, 2)]
    fid = int(scalar(db.execute(
        "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at, "
        "status_short, status_group) VALUES (9890001, %s, %s, %s, %s, 'PEN', 'finished') RETURNING id",
        (seed.season_id, teams[0], teams[1], KICKOFF))))
    # 1-1 after extra time, then a shoot-out: the regulation score is what is settled
    db.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away, ft_goals_home, ft_goals_away) "
               "VALUES (%s, 1, 1, 1, 1)", (fid,))
    events = [
        (1, 55, "home", "Goal", "Penalty", None),                      # a penalty of the match: scored
        (2, 120, "home", "Goal", "Penalty", "Penalty Shootout"),       # shoot-out kicks: not part of the match
        (3, 120, "away", "Goal", "Missed Penalty", "Penalty Shootout"),
        (4, 120, "away", "Goal", "Penalty", "Penalty Shootout"),
    ]
    for seq, minute, side, kind, detail, comments in events:
        db.execute("INSERT INTO core.fixture_events (fixture_id, source, seq, minute, team_side, event_type, detail, "
                   "comments, payload_hash, fetched_at) VALUES (%s, 'api-football', %s, %s, %s, %s, %s, %s, %s, %s)",
                   (fid, seq, minute, side, kind, detail, comments, seed.payload_hash, AFTER))
    decision = int(scalar(db.execute(
        "INSERT INTO intel.decisions (decision_version, known_at, checkpoint, fixture_id, kickoff_at, market_key, "
        "selection, line, model_name, odds, p_model, p_cal, p_market, filters, state, context_status, input_hash) "
        "VALUES ('decision-v1', %s, 'T-3h', %s, %s, '1X2', 'Draw', 0, 'dixon_coles', 3.40, 0.30, 0.30, 0.28, '[]', "
        "'CAUTELA', 'PENDING', 'shootout') RETURNING id", (KICKOFF - timedelta(hours=3), fid, KICKOFF))))
    db.execute("INSERT INTO intel.decision_outcomes (decision_id, settled_at, result_status, profit_flat, profit_staked, "
               "close_p_fair, close_odds, close_as_of, clv, version, computed_at) VALUES (%s, %s, 'win', 2.4, 0, 0.28, "
               "3.30, %s, 0.02, 'outcome-v1', %s)", (decision, AFTER - timedelta(hours=1), KICKOFF, AFTER))
    return fid, decision


def _causes(db: psycopg.Connection[Any], decision: int, version: str) -> list[dict[str, Any]]:
    row = db.execute("SELECT causes FROM intel.postmortems WHERE decision_id = %s AND version = %s",
                     (decision, version)).fetchone()
    assert row is not None
    return list(row[0])


def test_a_shootout_kick_is_not_a_penalty_of_the_match() -> None:
    d = {"market_key": "1X2", "selection": "Draw", "line": 0}
    kicks = [
        {"minute": 120, "event_type": "Goal", "detail": "Penalty", "team_side": "home", "comments": "Penalty Shootout"},
        {"minute": 120, "event_type": "Goal", "detail": "Missed Penalty", "team_side": "away",
         "comments": "Penalty Shootout"},
    ]
    assert postmortem.causes_of(d, kicks, {}, {"gh": 1, "ga": 1}, None) == [], "a 0-0 that goes to penalties has no causes"
    penalty = {"minute": 55, "event_type": "Goal", "detail": "Penalty", "team_side": "home", "comments": None}
    with_penalty = [*kicks, penalty]
    codes = [c["code"] for c in postmortem.causes_of(d, with_penalty, {}, {"gh": 1, "ga": 1}, None)]
    assert codes == ["penalty_scored"], "the penalty of the match is still a cause; the kicks of the shoot-out are not"


def test_the_current_post_mortem_judges_a_shootout_match_without_its_kicks_and_the_readers_take_the_newest(
        db: psycopg.Connection[Any], seed: Seed) -> None:
    fid, decision = _world(db, seed)
    stale = Jsonb([{"code": "penalty_scored", "minute": 120, "side": "home", "effect": "neutral",
                    "text": "Penalti convertido (home) en el 120'"}])
    db.execute("INSERT INTO intel.postmortems (decision_id, fixture_id, created_at, version, outcome, decision_quality, "
               "verdict, causes, answers) VALUES (%s, %s, %s, 'pm-v3', 'won', 'GOOD', 'ERROR', %s, '{}')",
               (decision, fid, AFTER - timedelta(hours=2), stale))

    assert postmortem.VERSION == "pm-v6"
    assert postmortem.run_postmortems(db, at=AFTER) == 1, "v3 does not stop the decision being judged under v6"

    current = _causes(db, decision, postmortem.VERSION)
    assert [(c["code"], c["minute"]) for c in current if c["code"].startswith("penalty")] == [("penalty_scored", 55)]
    assert "penalty_missed" not in {c["code"] for c in current}
    assert [c["minute"] for c in _causes(db, decision, "pm-v3")] == [120], "the v3 row is history: it stays as written"
    assert postmortem.run_postmortems(db, at=AFTER) == 0, "judged once per version"

    start, end = KICKOFF - timedelta(days=1), KICKOFF + timedelta(days=1)
    with db.cursor(row_factory=dict_row) as cur:
        cur.execute(report.LAST_SQL, {"start": start, "end": end})
        rows = [r for r in cur.fetchall() if r["id"] == decision]
        assert len(rows) == 1, "a decision judged under two versions is counted once"
        assert rows[0]["verdict"] != "ERROR", "and by its newest post-mortem"
        cur.execute(memory.DECISIONS_SQL, {"start": start, "end": end})
        mem = [r for r in cur.fetchall() if r["id"] == decision]
        assert len(mem) == 1 and mem[0]["verdict"] != "ERROR"
