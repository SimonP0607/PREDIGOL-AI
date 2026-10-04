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


# ── 4 Oct 2026, second round: what the golden seasons taught ──────────────


def tables(*groups: list[dict[str, Any]]) -> dict[str, Any]:
    return {"response": [{"league": {"id": 239, "season": 2024, "standings": [list(g) for g in groups]}}]}


def test_a_label_the_provider_gives_two_tables_is_made_unique_per_table() -> None:
    from fbi.providers.api_football.details import iter_standings

    # Colombia 2024: the Clausura play-off groups, then the Apertura ones, both "Group A"
    b = tables([row(1, 6, 3, 1, 2, 9, 6, group="Group A"), row(2, 6, 2, 2, 2, 6, 5, group="Group A", rank=2)],
               [row(1, 19, 10, 4, 5, 25, 12, group="Primera A: Clausura")],
               [row(1, 6, 2, 2, 2, 6, 5, group="Group A"), row(3, 6, 4, 1, 1, 9, 4, group="Group A", rank=2)])
    assert st.repeated_labels(b) == {"Group A": 2}
    assert [(r.team, r.group) for r in st.api_rows(b)] == [
        (1, "Group A"), (2, "Group A"), (1, "Primera A: Clausura"), (1, "Group A #2"), (3, "Group A #2")]
    # the writer stores exactly the labels the audit compares: team 1 keeps both play-off rows
    assert [(r.provider_team_id, r.group) for r in iter_standings(b)] == [
        (r.team, r.group) for r in st.api_rows(b)]


def test_a_play_off_group_stage_inside_a_phase_is_not_counted_in_the_phase_table() -> None:
    # four teams play three match days, then 1 and 2 meet twice in the quadrangular
    games = [match(1, 1, 2, 1, 0, "Apertura - 1"), match(2, 3, 4, 0, 0, "Apertura - 1"),
             match(3, 1, 3, 2, 0, "Apertura - 2"), match(4, 2, 4, 1, 1, "Apertura - 2"),
             match(5, 1, 4, 0, 1, "Apertura - 3"), match(6, 2, 3, 3, 0, "Apertura - 3"),
             match(7, 1, 2, 0, 0, "Apertura - Quadrangular - 1"), match(8, 2, 1, 2, 1, "Apertura - Quadrangular - 2")]
    b = tables([row(1, 3, 2, 0, 1, 3, 1, group="Primera A: Apertura"),
                row(2, 3, 1, 1, 1, 4, 2, group="Primera A: Apertura", rank=2),
                row(3, 3, 0, 1, 2, 0, 5, group="Primera A: Apertura", rank=3),
                row(4, 3, 1, 2, 0, 2, 1, group="Primera A: Apertura", rank=4)],
               [row(2, 2, 1, 1, 0, 2, 1, group="Group A"), row(1, 2, 0, 1, 1, 1, 2, group="Group A", rank=2)])
    a = st.audit_season({**FACTS, "provider_league_id": 239}, b, st.api_rows(b), games, at=NOW)
    assert a.counts() == {"ok": 6}, a.rows
    assert a.recompute["Primera A: Apertura"].startswith("Apertura rounds only")
    assert a.recompute["Group A"].startswith("Apertura - Quadrangular rounds only")
    assert st.stage_of("Apertura - Quadrangular - 3") == "Apertura - Quadrangular"
    assert st.stage_of("Regular Season - 34") == "Regular Season"


def test_a_result_decided_off_the_pitch_is_counted_at_its_official_score() -> None:
    # Union Berlin 1-1 Bochum on the pitch (the provider's fixture), 0-2 by the DFB's sports court (its table)
    union, bochum = 182, 176
    b = body(row(bochum, 1, 1, 0, 0, 2, 0), row(union, 1, 0, 0, 1, 0, 2, rank=2))
    played = [match(1224099, union, bochum, 1, 1)]
    plain = st.audit_season(FACTS, b, st.api_rows(b), played, at=NOW)
    assert plain.verdict == "provider_inconsistent"
    decision = st.Official(st.Played(1224099, NOW - timedelta(days=1), "Regular Season - 1", union, bochum, 0, 2),
                           "DFB Sports Court 9 Jan 2025")
    a = st.audit_season(FACTS, b, st.api_rows(b), played, at=NOW, official=[decision])
    assert {r.verdict for r in a.rows} == {"awarded"} and a.verdict == "adjusted"
    assert "official 0-2, stored 1-1 (DFB Sports Court 9 Jan 2025)" in a.rows[0].notes[0]
    ev = st.evidence(a, None)
    assert ev[0].status == "MONITOR" and "DFB Sports Court" in ev[0].claim
    # an official decision the stored fixture already carries changes nothing
    same = st.Official(st.Played(1224099, NOW, "Regular Season - 1", union, bochum, 1, 1), "x")
    assert st.audit_season(FACTS, b, st.api_rows(b), played, at=NOW, official=[same]).verdict == "provider_inconsistent"


def test_decisions_are_read_from_the_official_file(tmp_path: Any) -> None:
    import json as _json

    f = tmp_path / "decisions.json"
    f.write_text(_json.dumps({"decisions": [{"fixture": 1224099, "league": 78, "season": 2024, "official": [0, 2],
                                             "played": [1, 1], "basis": "DFB", "sources": ["https://www.dfb.de/x"]},
                                            {"fixture": 1388000, "league": 61, "season": 2025, "official": [0, 0],
                                             "played": None, "basis": "LFP"}]}))
    d = st.load_decisions(f)
    assert d[1224099].official == (0, 2) and d[1224099].played == (1, 1) and d[1224099].sources == ("https://www.dfb.de/x",)
    assert d[1388000].played is None and st.load_decisions(None) == {}


def test_a_past_season_is_never_the_wrong_season_of_the_product() -> None:
    table = body(row(1, 1, 1, 0, 0, 2, 0), row(2, 1, 0, 0, 1, 0, 2, rank=2))
    past = {**FACTS, "season": 2024, "is_current": False, "product_season": 2026}
    a = st.audit_season(past, table, as_db(table), [match(10, 1, 2, 2, 0)], at=NOW)
    assert "WRONG_SEASON" not in {e.issue_type for e in st.evidence(a, None)}


def test_the_provider_awarded_score_is_read_from_its_fixture_list() -> None:
    from fbi.truth.v2.golden import provider_awards

    items = [{"fixture": {"id": 1388000, "date": "2026-05-17T19:00:00+00:00", "status": {"short": "AWD"}},
              "league": {"round": "Regular Season - 34"}, "teams": {"home": {"id": 83}, "away": {"id": 96}},
              "goals": {"home": 0, "away": 0}},
             {"fixture": {"id": 1, "date": "2026-05-17T19:00:00+00:00", "status": {"short": "FT"}},
              "league": {"round": "Regular Season - 34"}, "teams": {"home": {"id": 1}, "away": {"id": 2}},
              "goals": {"home": 2, "away": 1}},
             {"fixture": {"id": 2, "date": "2026-05-17T19:00:00+00:00", "status": {"short": "AWD"}},
              "league": {"round": "x"}, "teams": {"home": {"id": 1}, "away": {"id": 2}},
              "goals": {"home": None, "away": None}}]
    got = provider_awards(items)
    assert [(o.match.fixture, o.match.home, o.match.away, o.match.gh, o.match.ga) for o in got] == [
        (1388000, 83, 96, 0, 0)]


def test_two_reports_in_the_same_second_never_overwrite_each_other(tmp_path: Any) -> None:
    from fbi.truth.v2.runner import write_report

    a = write_report(tmp_path, "standings", NOW, {"n": 1}, "# one")
    b = write_report(tmp_path, "standings", NOW, {"n": 2}, "# two")
    assert a != b and b.name.endswith("-standings-2")
    assert (a / "standings.md").read_text() == "# one" and (b / "standings.md").read_text() == "# two"


def test_a_provider_table_missing_an_official_result_is_the_providers_stale_table() -> None:
    # Ligue 1 2025/26: Nantes v Toulouse abandoned, 0-0 homologated by the LFP; the provider's final table
    # still shows both on 33 games (the official one: 34)
    nantes, toulouse = 83, 96
    b = body(row(nantes, 1, 1, 0, 0, 2, 0), row(toulouse, 1, 0, 0, 1, 0, 2, rank=2))
    played = [match(1, nantes, toulouse, 2, 0, ko=NOW - timedelta(days=30))]
    decided = st.Official(st.Played(1388000, NOW - timedelta(days=20), "Regular Season - 2", nantes, toulouse, 0, 0),
                          "LFP disciplinary commission, 28 May 2026")
    facts = {**FACTS, "is_current": False, "last_finished": NOW - timedelta(days=30)}
    a = st.audit_season(facts, b, st.api_rows(b), played, at=NOW, official=[decided])
    assert a.verdict == "provider_stale" and a.counts() == {"provider_behind": 2}
    assert "does not count fixture 1388000" in a.rows[0].notes[0]
    ev = st.evidence(a, None)
    assert ev[0].issue_type == "PROVIDER_STALE" and "LFP disciplinary commission" in ev[0].claim


def test_a_golden_season_failing_on_the_table_alone_names_the_table() -> None:
    from fbi.truth.v2.golden import GoldenSeason, evidence

    g = GoldenSeason(61, 2025, "Ligue 1", fixtures_api=308, fixtures_db=308, fixtures_checked=308,
                     fixtures_matched=308, results_checked=307, results_matched=307, table_rows=18, table_ok=16,
                     table_verdict="provider_stale", external_rows=306, external_matched=306,
                     external_score_disagree=0, external_other=0)
    assert g.verdict == "NEEDS_REVIEW"
    ev = evidence([g])
    assert [(e.issue_type, e.at_fault) for e in ev] == [("STANDINGS_MISMATCH", "provider")]


def test_our_table_one_hourly_check_behind_after_todays_matches_is_expected_lag() -> None:
    old = body(row(1, 1, 1, 0, 0, 2, 0), row(2, 1, 0, 0, 1, 0, 2, rank=2))
    new = body(row(1, 2, 2, 0, 0, 3, 0), row(2, 2, 0, 0, 2, 0, 3, rank=2))
    games = [match(10, 1, 2, 2, 0), match(11, 2, 1, 0, 1, "Regular Season - 2", ko=NOW - timedelta(hours=3))]
    recent = {**FACTS, "checked_at": NOW - timedelta(minutes=40), "last_finished": NOW - timedelta(hours=3)}
    a = st.audit_season(recent, new, as_db(old), games, at=NOW)
    assert a.verdict == "predigol_lag_expected" and st.evidence(a, None) == []
    # not re-read for hours after the match: our fault
    stale = {**recent, "checked_at": NOW - timedelta(hours=3)}
    assert st.audit_season(stale, new, as_db(old), games, at=NOW).verdict == "predigol_behind"
