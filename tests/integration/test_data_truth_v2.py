"""The data truth audit V2 against a real, migrated database."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import psycopg

from fbi.truth.baseline import TABLES, baseline, markdown
from tests.integration.conftest import Seed

NOW = datetime(2026, 10, 4, 12, 0, tzinfo=UTC)


def test_the_baseline_reads_every_table_it_names(migrated_database: str, seed: Seed) -> None:
    with psycopg.connect(migrated_database) as conn:
        conn.execute("SET default_transaction_read_only = on")
        b: dict[str, Any] = baseline(conn, at=NOW)
    assert [t["table"] for t in b["tables"]] == [s.table for s in TABLES]
    by_table = {t["table"]: t for t in b["tables"]}
    assert by_table["core.fixtures"]["rows"] >= 1
    assert by_table["core.fixtures"]["span_from"] is not None
    assert by_table["raw.ingestion_payloads"]["rows"] >= 1
    assert {e["endpoint"] for e in b["endpoints"]} >= {"/odds"}
    assert set(b["extra"]) == {"fixtures_by_status", "competitions", "current_seasons", "teams_national", "repairs",
                               "validation"}
    md = markdown(b)
    assert "| `core.fixtures` (fixtures) |" in md
    assert "| `/odds` |" in md


# ── the evidence ledger and the audit runs ─────────────────────────────────

import asyncio  # noqa: E402
from collections.abc import Iterator  # noqa: E402
from datetime import timedelta  # noqa: E402

import pytest  # noqa: E402

from fbi.truth.v2 import players as pl  # noqa: E402
from fbi.truth.v2 import standings as st  # noqa: E402
from fbi.truth.v2 import team_history as th  # noqa: E402
from fbi.truth.v2 import team_stats as ts  # noqa: E402
from fbi.truth.v2.ledger import Evidence, clear_unseen, mark, record  # noqa: E402
from fbi.truth.v2.runner import V2Run  # noqa: E402

LEAGUE, SEASON, TEAM_A, TEAM_B, PLAYER = 9902, 2026, 99021, 99022, 990001


def ev(key: str, claim: str = "x") -> Evidence:
    return Evidence(key=key, area="standings", issue_type="STANDINGS_MISMATCH", severity="high", at_fault="predigol",
                    claim=claim)


def test_the_ledger_numbers_once_refreshes_clears_and_reopens(migrated_database: str) -> None:
    with psycopg.connect(migrated_database, autocommit=True) as conn:
        code = record(conn, ev("test:ledger:a", "first"), at=NOW)
        assert code.startswith("E-")
        assert record(conn, ev("test:ledger:a", "second"), at=NOW + timedelta(hours=1)) == code
        row = conn.execute("SELECT claim, times_seen, first_seen_at, status FROM audit.evidence_ledger "
                           "WHERE code = %s", (code,)).fetchone()
        assert row is not None and row[0] == "second" and row[1] == 2 and row[2] == NOW and row[3] == "OPEN"
        assert clear_unseen(conn, area="standings", scope_prefix="test:ledger:", seen=[], at=NOW) == 1
        assert conn.execute("SELECT status FROM audit.evidence_ledger WHERE code = %s", (code,)).fetchone() == \
            ("CLEARED",)
        mark(conn, code, status="FIXED", fix="refresh cups")
        record(conn, ev("test:ledger:a"), at=NOW + timedelta(hours=2))  # seen again: the fix did not hold
        assert conn.execute("SELECT status, fix FROM audit.evidence_ledger WHERE code = %s", (code,)).fetchone() == \
            ("OPEN", "refresh cups")
        mark(conn, code, status="ACCEPTED")
        record(conn, ev("test:ledger:a"), at=NOW + timedelta(hours=3))
        assert conn.execute("SELECT status FROM audit.evidence_ledger WHERE code = %s", (code,)).fetchone() == \
            ("ACCEPTED",)
        conn.execute("DELETE FROM audit.evidence_ledger WHERE key LIKE 'test:ledger:%'")


@pytest.fixture
def v2_league(migrated_database: str, seed: Seed) -> Iterator[dict[str, int]]:
    with psycopg.connect(migrated_database, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type, "
                    "tier, is_tracked) VALUES (%s, 'V2 League', 'league', 'club', 'domestic_league', 1, true) "
                    "RETURNING id", (LEAGUE,))
        comp = cur.fetchone()[0]  # type: ignore[index]
        cur.execute("INSERT INTO core.competition_seasons (competition_id, season, is_current) VALUES (%s, %s, true) "
                    "RETURNING id", (comp, SEASON))
        cs = cur.fetchone()[0]  # type: ignore[index]
        ids = []
        for pid, name in ((TEAM_A, "V2 A"), (TEAM_B, "V2 B")):
            cur.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (%s, %s) RETURNING id", (pid, name))
            ids.append(cur.fetchone()[0])  # type: ignore[index]
        fixtures = []
        for pid, home, away, gh, ga, days in ((992001, 0, 1, 2, 0, 5), (992002, 1, 0, 1, 1, 2)):
            cur.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, "
                        "away_team_id, kickoff_at, round, status_short, status_group, source_payload_hash, "
                        "source_fetched_at) VALUES (%s,%s,%s,%s,%s,'Regular Season - 1','FT','finished',%s,%s) "
                        "RETURNING id",
                        (pid, cs, ids[home], ids[away], NOW - timedelta(days=days), seed.payload_hash, NOW))
            fid = cur.fetchone()[0]  # type: ignore[index]
            fixtures.append(fid)
            cur.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away) VALUES (%s,%s,%s)",
                        (fid, gh, ga))
        for fid, side, minutes, sub in ((fixtures[0], "home", 90, False), (fixtures[1], "away", None, True)):
            cur.execute("INSERT INTO core.fixture_player_stats (fixture_id, source, provider_player_id, team_side, "
                        "minutes, is_substitute, goals, assists, yellow_cards, red_cards, payload_hash, fetched_at) "
                        "VALUES (%s,'api-football',%s,%s,%s,%s,1,0,0,0,%s,%s)",
                        (fid, PLAYER, side, minutes, sub, seed.payload_hash, NOW))
        cur.execute("INSERT INTO core.standings (competition_season_id, team_id, snapshot_at, rank, points, played, "
                    "wins, draws, losses, goals_for, goals_against, \"group\") VALUES "
                    "(%s,%s,%s,1,3,1,1,0,0,2,0,'V2 League'), (%s,%s,%s,2,0,1,0,0,1,0,2,'V2 League')",
                    (cs, ids[0], NOW - timedelta(days=4), cs, ids[1], NOW - timedelta(days=4)))
    yield {"competition": comp, "cs": cs, "team_a": ids[0], "team_b": ids[1]}
    with psycopg.connect(migrated_database, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("DELETE FROM audit.evidence_ledger WHERE key LIKE %s", (f"standings:{LEAGUE}:%",))
        cur.execute("DELETE FROM audit.truth_v2_runs")
        cur.execute("DELETE FROM raw.ingestion_runs WHERE job_type LIKE 'truth_v2_%'")
        cur.execute("DELETE FROM core.standings WHERE competition_season_id = %s", (cs,))
        cur.execute("DELETE FROM core.fixture_player_stats WHERE provider_player_id = %s", (PLAYER,))
        cur.execute("DELETE FROM core.fixture_results WHERE fixture_id = ANY(%s)", (fixtures,))
        cur.execute("DELETE FROM core.fixtures WHERE competition_season_id = %s", (cs,))
        cur.execute("DELETE FROM core.teams WHERE provider_team_id IN (%s, %s)", (TEAM_A, TEAM_B))
        cur.execute("DELETE FROM core.competition_seasons WHERE id = %s", (cs,))
        cur.execute("DELETE FROM core.competitions WHERE id = %s", (comp,))


class TableClient:
    """Answers /standings with the table after both matches; the snapshot we hold has one."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    async def get(self, endpoint: str, params: dict[str, Any]) -> Any:
        from types import SimpleNamespace

        self.calls.append((endpoint, params))
        rows = [{"rank": 1, "team": {"id": TEAM_A, "name": "V2 A"}, "points": 4, "group": "V2 League",
                 "update": "2026-10-03T00:00:00+00:00",
                 "all": {"played": 2, "win": 1, "draw": 1, "lose": 0, "goals": {"for": 3, "against": 1}}},
                {"rank": 2, "team": {"id": TEAM_B, "name": "V2 B"}, "points": 1, "group": "V2 League",
                 "update": "2026-10-03T00:00:00+00:00",
                 "all": {"played": 2, "win": 0, "draw": 1, "lose": 1, "goals": {"for": 1, "against": 3}}}]
        body = {"response": [{"league": {"id": LEAGUE, "season": SEASON, "standings": [rows]}}]}
        return SimpleNamespace(body=body, params=params, fetched_at=NOW, http_status=200, results_count=1,
                               stored=None)


def test_a_standings_run_finds_our_stale_table_and_writes_the_evidence(migrated_database: str,
                                                                        v2_league: dict[str, int]) -> None:
    from scripts.audit_standings import audit_one

    with psycopg.connect(migrated_database, autocommit=True) as conn:
        facts = st.season_facts(conn, "c.provider_league_id = %(l)s", {"l": LEAGUE})
        assert len(facts) == 1 and facts[0]["product_season"] == SEASON
        run = V2Run(conn, TableClient(), "standings", NOW)
        audit, evidence = asyncio.run(audit_one(run, conn, facts[0], no_api=False, externals={}))
        assert audit.verdict == "predigol_behind"
        assert audit.recompute == {"V2 League": "Regular Season: 2/2 rows agree on games played"}
        codes = {e.key: record(conn, e, at=NOW, run_id=run.run_id) for e in evidence}
        assert list(codes) == [f"standings:{LEAGUE}:{SEASON}:predigol_behind"]
        assert run.finish({"seasons": 1}) == "completed"
        assert conn.execute("SELECT status, requests FROM audit.truth_v2_runs WHERE id = %s",
                            (run.run_id,)).fetchone() == ("completed", 1)


def test_the_team_and_player_queries_read_the_real_schema(migrated_database: str, v2_league: dict[str, int]) -> None:
    with psycopg.connect(migrated_database, autocommit=True) as conn:
        rows = ts.our_fixtures(conn, league=LEAGUE, season=SEASON, team_id=v2_league["team_a"])
        figures = ts.recompute(rows)
        assert (figures.get("played"), figures.get("wins"), figures.get("draws")) == (2, 1, 1)
        assert ts.product_record(conn, v2_league["team_a"])["played"] == 2
        blocks = pl.our_blocks(conn, PLAYER, SEASON)
        assert len(blocks) == 1 and blocks[0]["appearances"] == 1 and blocks[0]["rows"] == 2
        product = pl.product_view(conn, PLAYER, NOW - timedelta(days=400))
        # the product's apps are matches played; the bench row is counted apart, never as an appearance
        assert (product["apps"], product["played_rows"], product["bench_rows"], product["rows"]) == (1, 1, 1, 2)
        assert product["team_id"] == v2_league["team_a"] and not product["team_is_national"]
        assert pl.team_detail_gaps(conn, LEAGUE, SEASON, TEAM_A) == {"finished": 2, "without_player_rows": 0,
                                                                      "never_fetched": 0, "empty_at_provider": 0}
        counts = {t["provider_team_id"]: t for t in th.team_counts(conn)}
        assert counts[TEAM_A]["fixtures"] == 2


def test_identity_and_fixture_sample_queries_read_the_real_schema(migrated_database: str,
                                                                  v2_league: dict[str, int]) -> None:
    from fbi.truth.v2 import fixtures as fx
    from fbi.truth.v2 import identity as idn
    from fbi.truth.v2 import leagues as lg

    with psycopg.connect(migrated_database, autocommit=True) as conn:
        checks = idn.db_checks(conn)
        assert set(checks) == set(idn.CHECKS)
        assert checks["squads"][0]["teams"] == 0
        strata = fx.sample_ids(conn, at=NOW)
        assert 992001 in strata["FT"] or 992002 in strata["FT"]
        assert fx.current_seasons(conn)
        comps, seasons = lg.ours(conn)
        assert LEAGUE in {int(c["provider_league_id"]) for c in comps}
        assert seasons[LEAGUE][0]["fixtures"] == 2
        ids = idn.sample(conn, n=4)
        assert set(ids) == {"teams", "players", "coaches", "venues"}


def test_a_player_is_shown_with_his_club_not_his_national_side_and_bench_rows_are_not_apps(
        migrated_database: str, v2_league: dict[str, int], seed: Seed) -> None:
    """Data truth audit V2: 'latest team' was Spain/Norway/England after an international window, and an
    unused substitute counted as an appearance."""
    from fbi.api.services import center as svc

    with psycopg.connect(migrated_database, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO core.players (provider_player_id, name, lastname) VALUES (%s, 'V2 Player', 'Player') "
                    "RETURNING id", (PLAYER,))
        player_id = cur.fetchone()[0]  # type: ignore[index]
        cur.execute("INSERT INTO core.teams (provider_team_id, name, is_national) VALUES (99029, 'V2 Nation', true) "
                    "RETURNING id")
        nation = cur.fetchone()[0]  # type: ignore[index]
        cur.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, "
                    "away_team_id, kickoff_at, round, status_short, status_group, source_payload_hash, "
                    "source_fetched_at) VALUES (992009, %s, %s, %s, %s, 'Friendly', 'FT', 'finished', %s, %s) "
                    "RETURNING id", (v2_league["cs"], nation, v2_league["team_b"], NOW - timedelta(days=1),
                                     seed.payload_hash, NOW))
        fid = cur.fetchone()[0]  # type: ignore[index]
        cur.execute("INSERT INTO core.fixture_player_stats (fixture_id, source, provider_player_id, team_side, minutes, "
                    "is_substitute, goals, payload_hash, fetched_at) VALUES (%s,'api-football',%s,'home',30,true,0,%s,%s)",
                    (fid, PLAYER, seed.payload_hash, NOW))
        cur.execute("UPDATE core.teams SET squad_checked_at = %s WHERE id = %s", (NOW, v2_league["team_a"]))
        cur.execute("INSERT INTO core.squad_members (team_id, provider_player_id, player_name, first_seen_at, "
                    "last_seen_at, payload_hash) VALUES (%s, %s, 'V2 Player', %s, %s, %s)",
                    (v2_league["team_a"], PLAYER, NOW, NOW, seed.payload_hash))
        try:
            detail = svc.player(conn, player_id, at=NOW).data
            assert detail is not None
            p = detail.player
            assert (p.team, p.club_source, p.national_team, p.last_team) == ("V2 A", "squad", "V2 Nation", "V2 Nation")
            assert p.apps == 2  # the 90 minutes for the club and the 30 for the nation; the bench row is not one
            seasons = detail.seasons.data or []
            assert {(s.team, s.apps) for s in seasons} == {("V2 A", 1), ("V2 Nation", 1)}
            listed = svc.players(conn, q="V2 Player", team_id=None, limit=5, offset=0, at=NOW).data or []
            assert listed and listed[0].team == "V2 A" and listed[0].apps == 2
            active = svc.players(conn, q=None, team_id=None, limit=50, offset=0, at=NOW).data or []
            mine = [x for x in active if x.provider_player_id == PLAYER]
            assert mine and mine[0].team == "V2 A" and mine[0].last_team == "V2 Nation"
        finally:
            cur.execute("DELETE FROM core.squad_members WHERE provider_player_id = %s", (PLAYER,))
            cur.execute("DELETE FROM core.fixture_player_stats WHERE fixture_id = %s", (fid,))
            cur.execute("DELETE FROM core.fixtures WHERE id = %s", (fid,))
            cur.execute("DELETE FROM core.teams WHERE id = %s", (nation,))
            cur.execute("DELETE FROM core.players WHERE id = %s", (player_id,))


def test_the_admin_reads_the_ledger_and_records_a_verdict(migrated_database: str, seed: Seed) -> None:
    from fbi.core.config import reset_cache
    from tests.integration.helpers import scalar
    from tests.integration.test_records_api import client_for

    with psycopg.connect(migrated_database, autocommit=True) as conn, conn.cursor() as cur:
        cur.execute("INSERT INTO auth.users (email, display_name, password_hash) VALUES "
                    "('owner-truth-v2@test.local', 'Owner', '$argon2id$x') RETURNING id")
        user = scalar(cur)
        code = record(conn, ev("test:api:a", "a table five days behind"), at=NOW)
        run = V2Run(conn, None, "standings", NOW)
        run.finish({"seasons": 3, "verdicts": {"ok": 3}, "by_season": [{"x": 1}]})
    mp = pytest.MonkeyPatch()
    mp.setenv("FBI_DATABASE_URL", migrated_database.replace("postgresql://", "postgresql+psycopg://"))
    reset_cache()
    try:
        owner = client_for(user, role="SUPER_ADMIN")
        body = owner.get("/api/v1/admin/truth/v2").json()
        assert body["status"] == "ok"
        assert any(r["kind"] == "standings" and "by_season" not in r["summary"] for r in body["data"]["runs"])
        assert any(e["code"] == code and e["status"] == "OPEN" for e in body["data"]["ledger"])
        res = owner.post(f"/api/v1/admin/truth/v2/ledger/{code}", json={"status": "ACCEPTED", "note": "provider rule"})
        assert res.status_code == 200 and res.json()["data"]["status"] == "ACCEPTED"
        assert owner.post("/api/v1/admin/truth/v2/ledger/E-99999", json={"status": "FIXED"}).json()["status"] == "empty"
        user_client = client_for(user, role="USER")
        assert user_client.get("/api/v1/admin/truth/v2").status_code == 403
    finally:
        mp.undo()
        reset_cache()
        with psycopg.connect(migrated_database, autocommit=True) as conn, conn.cursor() as cur:
            cur.execute("DELETE FROM audit.evidence_ledger WHERE key LIKE 'test:api:%'")
            cur.execute("DELETE FROM audit.truth_v2_runs")
            cur.execute("DELETE FROM raw.ingestion_runs WHERE job_type LIKE 'truth_v2_%'")
            cur.execute("DELETE FROM auth.users WHERE id = %s", (user,))


def test_a_snapshot_that_merged_two_tables_labelled_alike_is_rebuilt_beside_it(
        migrated_database: str, seed: Seed, v2_league: dict[str, int], tmp_path: Any) -> None:
    """Colombia 2024: the Clausura and the Apertura play-off groups are both "Group A". The old writer
    kept team A's first "Group A" row and dropped its second; the repair writes a NEW snapshot from the
    same payload and leaves the damaged one as it was."""
    from dataclasses import replace

    from psycopg.types.json import Json

    from fbi.ingestion.details import apply_standings_outcome
    from fbi.ingestion.payload_store import PayloadStore
    from fbi.ingestion.standings_repair import RULE, find_collisions, rebuild
    from fbi.providers.api_football.details import iter_standings

    def line(team: int, group: str, played: int, rank: int) -> dict[str, Any]:
        return {"rank": rank, "team": {"id": team, "name": str(team)}, "points": played, "group": group,
                "all": {"played": played, "win": 0, "draw": played, "lose": 0, "goals": {"for": 0, "against": 0}}}

    body = {"response": [{"league": {"id": LEAGUE, "season": SEASON, "standings": [
        [line(TEAM_A, "Group A", 6, 1), line(TEAM_B, "Group A", 6, 2)],
        [line(TEAM_A, "V2 League", 2, 1), line(TEAM_B, "V2 League", 2, 2)],
        [line(TEAM_A, "Group A", 4, 1)]]}}]}
    t0 = NOW - timedelta(days=1)
    store = PayloadStore(tmp_path)
    stored = store.store(endpoint="/standings", params={"league": LEAGUE, "season": SEASON}, fetched_at=t0,
                         http_status=200, body=body)
    cs = v2_league["cs"]
    with psycopg.connect(migrated_database) as conn:
        conn.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, params, fetched_at, http_status, "
                     "results_count, file_path, bytes) VALUES (%s,%s,'/standings',%s,%s,200,1,%s,%s)",
                     (stored.hash, seed.run_id, Json({"league": str(LEAGUE), "season": str(SEASON)}), t0,
                      stored.file_path, stored.bytes_written))
        # the old writer: bare labels, ON CONFLICT DO NOTHING - team A's second "Group A" row is lost
        old = [replace(r, group=(r.group or "").split(" #")[0]) for r in iter_standings(body)]
        assert apply_standings_outcome(conn, old, fetched_at=t0, payload_hash=stored.hash).written == 4
        conn.commit()
        try:
            cases = find_collisions(conn, store, seasons=[cs])
            assert [(c.league, c.season, c.rows_before, c.rows_expected, c.missing) for c in cases] == [
                (LEAGUE, SEASON, 4, 5, [f"{TEAM_A}|Group A #2"])]
            written = rebuild(conn, cases[0], store, at=NOW)
            assert written == 5
            snaps = conn.execute("SELECT snapshot_at, count(*) FROM core.standings WHERE competition_season_id = %s "
                                 "GROUP BY 1 ORDER BY 1", (cs,)).fetchall()
            assert [n for _, n in snaps][-2:] == [4, 5]  # the damaged snapshot kept, the rebuilt one beside it
            assert conn.execute("SELECT played FROM core.standings WHERE competition_season_id = %s AND "
                                "snapshot_at = %s AND \"group\" = 'Group A #2'", (cs, NOW)).fetchone() == (4,)
            repair = conn.execute("SELECT before_value, after_value, evidence FROM audit.data_repairs WHERE rule = %s "
                                  "AND entity_id = %s", (RULE, cs)).fetchone()
            assert repair is not None and repair[0].startswith("4 rows") and repair[1].startswith("5 rows")
            assert stored.hash in repair[2]
            assert find_collisions(conn, store, seasons=[cs]) == []  # the newest snapshot is whole now
        finally:
            conn.execute("DELETE FROM audit.data_repairs WHERE rule = %s AND entity_id = %s", (RULE, cs))
            conn.execute("DELETE FROM core.standings WHERE competition_season_id = %s AND snapshot_at IN (%s, %s)",
                         (cs, t0, NOW))
            conn.execute("DELETE FROM raw.ingestion_payloads WHERE hash = %s", (stored.hash,))
            conn.commit()


def test_an_official_decision_is_read_against_the_real_schema(migrated_database: str,
                                                               v2_league: dict[str, int]) -> None:
    from fbi.truth.v2.golden import official_variants

    with psycopg.connect(migrated_database) as conn:
        decisions = {992002: st.Decision(992002, LEAGUE, SEASON, (0, 2), (1, 1), "a sports court")}
        got = st.decided(conn, v2_league["cs"], decisions)
        assert [(o.match.fixture, o.match.home, o.match.away, o.match.gh, o.match.ga) for o in got] == [
            (992002, TEAM_B, TEAM_A, 0, 2)]
        variants = official_variants(conn, got)
        assert [(v.home, v.away, v.goals_home, v.goals_away) for v in variants] == [("V2 B", "V2 A", 0, 2)]


def test_a_player_block_is_settled_by_re_reading_its_matches(migrated_database: str,
                                                            v2_league: dict[str, int]) -> None:
    from types import SimpleNamespace

    class MatchesClient:
        def __init__(self, goals_first: int) -> None:
            self.goals_first = goals_first
            self.asked: list[str] = []

        async def get(self, endpoint: str, params: dict[str, Any]) -> Any:
            self.asked.append(params["ids"])
            items = [{"fixture": {"id": fid}, "players": [{"team": {"id": TEAM_A}, "players": [
                {"player": {"id": PLAYER}, "statistics": [{"games": {"minutes": minutes, "substitute": sub},
                                                           "goals": {"total": goals, "assists": 0},
                                                           "cards": {"yellow": 0, "red": 0}}]}]}]}
                     for fid, minutes, sub, goals in ((992001, 90, False, self.goals_first),
                                                      (992002, None, True, 1))]
            return SimpleNamespace(body={"response": items}, params=params, fetched_at=NOW, http_status=200,
                                   results_count=len(items), stored=None)

    def block() -> pl.BlockVerdict:
        return pl.BlockVerdict(TEAM_A, "V2 A", LEAGUE, "V2 League", SEASON, "stats_mismatch", {"goals": 3},
                               {"goals": 2}, differences={"goals": (3, 2)})

    with psycopg.connect(migrated_database, autocommit=True) as conn:
        same = MatchesClient(goals_first=1)
        v = asyncio.run(pl.recheck(V2Run(conn, same, "player_stats", NOW), conn, PLAYER, block()))
        assert same.asked == ["992001-992002"]
        assert v.verdict == "provider_aggregate_differs" and v.recheck["our_match_rows"]["goals"] == 2
        changed = MatchesClient(goals_first=2)
        assert asyncio.run(pl.recheck(V2Run(conn, changed, "player_stats", NOW), conn, PLAYER,
                                      block())).verdict == "ours_stale"
