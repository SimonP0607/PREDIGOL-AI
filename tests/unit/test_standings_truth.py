"""Standings truth: who is wrong, read from how the provider's table, ours and the fixtures agree."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fbi.truth.v2 import standings as st

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)


def row(team: int, played: int, w: int, d: int, lost: int, gf: int, ga: int, *, group: str | None = "L",
        rank: int = 1) -> dict[str, Any]:
    return {"rank": rank, "team": {"id": team, "name": f"T{team}"}, "points": 3 * w + d, "goalsDiff": gf - ga,
            "group": group, "form": None, "update": "2026-10-04T10:00:00+00:00",
            "all": {"played": played, "win": w, "draw": d, "lose": lost, "goals": {"for": gf, "against": ga}}}


def body(*rows: dict[str, Any]) -> dict[str, Any]:
    return {"response": [{"league": {"standings": [list(rows)]}}]}


def match(fid: int, home: int, away: int, gh: int, ga: int, rnd: str = "Regular Season - 1",
          ko: datetime = NOW - timedelta(days=1)) -> st.Played:
    return st.Played(fid, ko, rnd, home, away, gh, ga)


FACTS = {"provider_league_id": 39, "name": "Premier League", "season": 2026, "type": "league", "cs_id": 1,
         "is_tracked": True, "is_current": True, "snapshot_at": NOW - timedelta(days=2),
         "checked_at": NOW - timedelta(hours=1), "last_finished": NOW - timedelta(days=1), "product_season": 2026}


def as_db(b: dict[str, Any]) -> list[st.Row]:
    return st.api_rows(b)


def test_all_three_agree() -> None:
    b = body(row(1, 1, 1, 0, 0, 2, 0), row(2, 1, 0, 0, 1, 0, 2, rank=2))
    a = st.audit_season(FACTS, b, as_db(b), [match(10, 1, 2, 2, 0)], at=NOW)
    assert a.verdict == "ok"
    assert a.counts() == {"ok": 2}


def test_our_snapshot_behind_the_provider_is_our_fault() -> None:
    old = body(row(1, 1, 1, 0, 0, 2, 0), row(2, 1, 0, 0, 1, 0, 2, rank=2))
    new = body(row(1, 2, 2, 0, 0, 3, 0), row(2, 2, 0, 0, 2, 0, 3, rank=2))
    games = [match(10, 1, 2, 2, 0), match(11, 2, 1, 0, 1, "Regular Season - 2")]
    a = st.audit_season(FACTS, new, as_db(old), games, at=NOW)
    assert a.verdict == "predigol_behind"
    ev = st.evidence(a, {"endpoint": "/standings"})
    assert [e.issue_type for e in ev] == ["STANDINGS_MISMATCH"]
    assert ev[0].at_fault == "predigol"


def test_provider_missing_a_whole_match_day_is_provider_stale() -> None:
    table = body(row(1, 1, 1, 0, 0, 2, 0), row(2, 1, 0, 0, 1, 0, 2, rank=2))
    games = [match(10, 1, 2, 2, 0), match(11, 2, 1, 1, 1, "Regular Season - 2", ko=NOW - timedelta(hours=20))]
    a = st.audit_season({**FACTS, "last_finished": NOW - timedelta(hours=20)}, table, as_db(table), games, at=NOW)
    assert a.verdict == "provider_stale"
    assert {r.verdict for r in a.rows} == {"provider_behind"}
    assert st.evidence(a, None)[0].issue_type == "PROVIDER_STALE"


def test_a_match_that_just_ended_is_expected_lag() -> None:
    table = body(row(1, 1, 1, 0, 0, 2, 0), row(2, 1, 0, 0, 1, 0, 2, rank=2))
    games = [match(10, 1, 2, 2, 0), match(11, 2, 1, 1, 1, "Regular Season - 2", ko=NOW - timedelta(hours=3))]
    a = st.audit_season({**FACTS, "last_finished": NOW - timedelta(hours=3)}, table, as_db(table), games, at=NOW)
    assert a.verdict == "provider_lag_expected"
    assert st.evidence(a, None) == []


def test_points_off_the_results_with_the_same_games_is_an_adjustment() -> None:
    t = row(1, 1, 1, 0, 0, 2, 0)
    t["points"] = -7  # a ten-point deduction
    table = body(t, row(2, 1, 0, 0, 1, 0, 2, rank=2))
    a = st.audit_season(FACTS, table, as_db(table), [match(10, 1, 2, 2, 0)], at=NOW)
    assert a.verdict == "adjusted"
    ev = st.evidence(a, None)
    assert ev[0].status == "MONITOR" and ev[0].at_fault == "none"


def test_a_cup_with_a_table_outside_the_refresh_scope_names_the_cause() -> None:
    old = body(row(1, 1, 1, 0, 0, 2, 0), row(2, 1, 0, 0, 1, 0, 2, rank=2))
    new = body(row(1, 2, 2, 0, 0, 3, 0), row(2, 2, 0, 0, 2, 0, 3, rank=2))
    games = [match(10, 1, 2, 2, 0, "League Stage - 1"), match(11, 2, 1, 0, 1, "League Stage - 2")]
    a = st.audit_season({**FACTS, "type": "cup", "provider_league_id": 2}, new, as_db(old), games, at=NOW)
    assert not a.in_refresh_scope
    assert "c.type = 'league'" in (st.evidence(a, None)[0].root_cause or "")


def test_the_phase_named_by_the_group_is_the_one_recomputed() -> None:
    rows = st.api_rows(body(row(1, 1, 1, 0, 0, 1, 0, group="Primera A: Clausura"),
                            row(2, 1, 0, 0, 1, 0, 1, group="Primera A: Clausura", rank=2)))
    games = [match(10, 1, 2, 0, 3, "Apertura - 1"), match(11, 1, 2, 1, 0, "Clausura - 1")]
    rec = st.recompute_group(rows, games)
    assert rec.phase.startswith("Clausura") and rec.usable
    assert rec.by_team[1].points == 3


def test_knockout_rounds_never_count_in_a_table() -> None:
    rows = st.api_rows(body(row(1, 1, 1, 0, 0, 2, 0), row(2, 1, 0, 0, 1, 0, 2, rank=2)))
    games = [match(10, 1, 2, 2, 0, "League Stage - 1"), match(11, 1, 2, 0, 1, "Knockout Round Play-offs")]
    rec = st.recompute_group(rows, games)
    assert rec.by_team[1].played == 1


def test_a_team_in_our_table_but_not_the_providers_is_a_season_mix() -> None:
    table = body(row(1, 1, 1, 0, 0, 2, 0), row(2, 1, 0, 0, 1, 0, 2, rank=2))
    ours = body(row(1, 1, 1, 0, 0, 2, 0), row(2, 1, 0, 0, 1, 0, 2, rank=2), row(3, 1, 0, 0, 1, 0, 2, rank=3))
    a = st.audit_season(FACTS, table, as_db(ours), [match(10, 1, 2, 2, 0)], at=NOW)
    assert a.extra_db_teams == [3]
    assert "SEASON_MISMATCH" in {e.issue_type for e in st.evidence(a, None)}


def test_the_product_showing_an_older_season_is_wrong_season() -> None:
    table = body(row(1, 1, 1, 0, 0, 2, 0), row(2, 1, 0, 0, 1, 0, 2, rank=2))
    a = st.audit_season({**FACTS, "product_season": 2025}, table, [], [], at=NOW)
    assert a.verdict == "missing_in_db"
    assert {"STANDINGS_MISMATCH", "WRONG_SEASON"} <= {e.issue_type for e in st.evidence(a, None)}


def test_a_conference_table_counts_matches_against_the_other_conference() -> None:
    east = st.api_rows(body(row(1, 2, 2, 0, 0, 3, 0, group="East"), row(2, 2, 0, 0, 2, 0, 3, group="East", rank=2)))
    games = [match(10, 1, 2, 2, 0), match(11, 1, 3, 1, 0), match(12, 2, 4, 0, 1)]  # 3 and 4 are West
    rec = st.recompute_group(east, games, tables=2)
    assert rec.usable and rec.by_team[1].played == 2 and "any" in rec.phase


def test_period_tables_that_match_no_phase_are_left_unjudged() -> None:
    period = st.api_rows(body(row(1, 0, 0, 0, 0, 0, 0, group="Period 2"), row(2, 0, 0, 0, 0, 0, 0, group="Period 2")))
    rec = st.recompute_group(period, [match(10, 1, 2, 2, 0)], tables=5)
    assert not rec.usable


def test_a_legacy_snapshot_missing_second_tables_names_the_old_writer() -> None:
    table = {"response": [{"league": {"standings": [
        [row(1, 1, 1, 0, 0, 2, 0, group="Annual"), row(2, 1, 0, 0, 1, 0, 2, group="Annual", rank=2)],
        [row(1, 1, 1, 0, 0, 2, 0, group="Clausura"), row(2, 1, 0, 0, 1, 0, 2, group="Clausura", rank=2)]]}}]}
    ours = st.api_rows(table)[:2]  # only the first table was kept, no payload hash
    a = st.audit_season({**FACTS, "checked_at": None}, table, ours, [match(10, 1, 2, 2, 0)], at=NOW)
    assert a.legacy_snapshot and a.counts().get("missing_in_db") == 2
    cause = st.evidence(a, None)[0].root_cause or ""
    assert "migration 0048" in cause and "not been re-read" in cause


def test_a_match_awarded_off_the_pitch_explains_the_extra_game() -> None:
    table = body(row(1, 2, 2, 0, 0, 5, 0), row(2, 2, 0, 0, 2, 0, 5, rank=2))
    a = st.audit_season(FACTS, table, as_db(table), [match(10, 1, 2, 2, 0)], at=NOW, awarded_pairs=[(2, 1)])
    assert {r.verdict for r in a.rows} == {"awarded"} and a.verdict == "adjusted"


def test_a_table_and_fixtures_naming_two_ids_for_one_club_is_the_providers_identity_error() -> None:
    table = body(row(1, 1, 1, 0, 0, 2, 0, group="G"), row(2, 1, 0, 0, 1, 0, 2, group="G", rank=2),
                 row(5, 1, 0, 0, 1, 0, 2, group="H", rank=1), row(6, 1, 1, 0, 0, 2, 0, group="H", rank=2))
    games = [match(10, 1, 2, 2, 0, "Group Stage - 1"), match(11, 6, 9, 2, 0, "Group Stage - 1")]  # 9 plays as 5
    a = st.audit_season({**FACTS, "type": "cup"}, table, as_db(table), games, at=NOW)
    assert [r.verdict for r in a.rows if r.team == 5] == ["provider_identity"]
    assert any(e.issue_type == "IDENTITY_MAPPING_ERROR" and e.at_fault == "provider" for e in st.evidence(a, None))
