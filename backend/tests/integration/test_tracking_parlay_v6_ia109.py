"""IA-109 / IA-110 against a real PostgreSQL: the tracking of loose selections settles a chain of decision-v2's shadow on settle-v4 - En juego
-> Liquidada -> Evaluada, a correction as a new row, two passes without a double write, the derivation of the layer agreeing with what it
appended - and ``parlay-v6`` builds from the chains confirmed in the shadow (at most three legs), records a day without a parlay, settles
through its legs and changes nothing it reads (``picks.parlays`` and ``parlay-v5`` included).

The passes commit, so the file has its own scratch database (``<FBI_TEST_DB>_ia109``), migrated to head and dropped at the end."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from alembic import command
from psycopg.types.json import Jsonb

from fbi.lifecycle import derive
from fbi.lifecycle import store as lifecycle
from fbi.tracking import parlay_v6 as v6
from fbi.tracking import parlay_v6_shadow as v6_shadow
from fbi.tracking import selections as tracking
from tests.integration.conftest import ADMIN_URL, TEST_DB, _dsn
from tests.integration.test_migration_0111 import _cfg

pytestmark = pytest.mark.integration

SCRATCH = f"{TEST_DB}_ia109"
WRITER = "decision-v2-shadow-v1"
KO = datetime(2026, 9, 15, 19, 0, tzinfo=UTC)  # 14:00 in Bogotá
READ = ("intel.decisions", "picks.parlays", "picks.parlay_legs", "picks.picks", "picks.pick_results")


def _drop(name: str) -> None:
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute("SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = %s AND pid <> pg_backend_pid()", (name,))
        admin.execute(f'DROP DATABASE IF EXISTS "{name}"')


@pytest.fixture(scope="module")
def dsn() -> Iterator[str]:
    previous = os.environ.get("FBI_DATABASE_URL")
    _drop(SCRATCH)
    with psycopg.connect(ADMIN_URL, autocommit=True) as admin:
        admin.execute(f'CREATE DATABASE "{SCRATCH}"')
    url = _dsn(SCRATCH)
    os.environ["FBI_DATABASE_URL"] = url.replace("postgresql://", "postgresql+psycopg://")
    try:
        command.upgrade(_cfg(), "head")
        yield url
    finally:
        if previous is None:
            os.environ.pop("FBI_DATABASE_URL", None)
        else:
            os.environ["FBI_DATABASE_URL"] = previous
        _drop(SCRATCH)


@pytest.fixture(scope="module")
def world(dsn: str) -> dict[str, Any]:
    with psycopg.connect(dsn, autocommit=True) as c:
        comp = c.execute("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type) "
                         "VALUES (39, 'Premier League', 'league', 'club', 'domestic_league') RETURNING id").fetchone()
        assert comp is not None
        season = c.execute("INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, 2026) RETURNING id", (comp[0],)).fetchone()
        assert season is not None
        teams = [c.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (%s, %s) RETURNING id", (100 + n, f"T{n}")).fetchone()
                 for n in range(8)]
        fixtures = []
        for n in range(4):
            h, a = teams[2 * n], teams[2 * n + 1]
            assert h is not None and a is not None
            row = c.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at) "
                            "VALUES (%s, %s, %s, %s, %s) RETURNING id", (2000 + n, season[0], h[0], a[0], KO + timedelta(minutes=15 * n))).fetchone()
            assert row is not None
            fixtures.append(int(row[0]))
        return {"fixtures": fixtures, "competition": int(comp[0])}


def decide(c: psycopg.Connection[Any], fx: int, *, ko: datetime, before: timedelta, market: str, selection: str, line: float, state: str,
           reasons: list[str], odds: float, p: float, p_low: float, p_market: float, books: int = 5) -> int:
    row = c.execute(
        "INSERT INTO intel.decisions (decision_version, known_at, checkpoint, fixture_id, kickoff_at, market_key, selection, line, model_name, "
        "odds, n_bookmakers, p_model, p_low, p_cal, p_market, filters, state, reasons, context_status, input_hash) VALUES ('decision-v1', %s, "
        "'T-3h', %s, %s, %s, %s, %s, 'dixon_coles', %s, %s, %s, %s, %s, %s, %s, %s, %s, 'FULL', %s) RETURNING id",
        (ko - before, fx, ko, market, selection, line, odds, books, p, p_low, p, p_market, Jsonb([]), state, reasons,
         f"h{fx}{market}{selection}{line}{before}")).fetchone()
    assert row is not None
    return int(row[0])


def link(c: psycopg.Connection[Any], *, now: datetime) -> lifecycle.PassReport:
    """decision-v2's shadow hands its chains to the cycle (``shadow.link_lifecycle``); here its decisions are rows of intel.decisions."""
    rows = c.execute("SELECT id, fixture_id, market_key, selection, line, known_at, checkpoint, state, reasons, context_status, kickoff_at "
                     "FROM intel.decisions ORDER BY id").fetchall()
    found: dict[derive.Key, derive.History] = {}
    for i, fx, m, s, ln, known, cp, st, rs, ctx, ko in rows:
        k = derive.Key.of(fx, m, s, ln)
        found.setdefault(k, derive.History(k)).decisions.append(derive.Decision(int(i), "decision-v2", known, cp, st, tuple(rs), ctx, ko))
    fixtures = {int(r[0]): derive.Fixture(int(r[0]), r[1], r[2], r[3])
                for r in c.execute("SELECT id, kickoff_at, status_short, status_group FROM core.fixtures")}
    rep = lifecycle.extend(c, found, fixtures, now=now, writer=WRITER, source="intel.decisions")
    c.commit()
    return rep


def fingerprint(c: psycopg.Connection[Any]) -> dict[str, str]:
    out = {}
    for t in READ:
        row = c.execute(f"SELECT md5(coalesce(string_agg(x::text, '|' ORDER BY x::text), '')) FROM {t} x").fetchone()
        assert row is not None
        out[t] = str(row[0])
    return out


def states(c: psycopg.Connection[Any], fx: int, market: str = "1X2") -> list[tuple[str, str]]:
    return [(str(s), str(r)) for s, r in c.execute("SELECT state, reason FROM intel.selection_lifecycle WHERE fixture_id = %s AND writer = %s "
                                                   "AND market_key = %s ORDER BY id", (fx, WRITER, market))]


def test_the_migration_keeps_three_append_only_tables(dsn: str) -> None:
    with psycopg.connect(dsn) as c:
        for t in ("selection_settlements", "parlays_v6", "parlay_v6_legs"):
            got = c.execute("SELECT count(*) FROM pg_trigger WHERE tgrelid = %s::regclass AND tgname = %s",
                            (f"intel.{t}", f"{t}_append_only")).fetchone()
            assert got == (1,), t
        with pytest.raises(psycopg.errors.CheckViolation):
            c.execute("INSERT INTO intel.parlays_v6 (writer, rule_version, kind, day, outcome, none_reason, max_legs, n_legs, n_candidates, "
                      "window_from, window_to, known_at) VALUES ('w-test', 'parlay-v6', 'daily', '2026-09-15', 'none', 'sin_candidatos', 4, 0, "
                      "0, now(), now() + interval '1 day', now())")
        c.rollback()


def test_parlay_v6_and_the_tracking_follow_the_shadow_to_the_result(dsn: str, world: dict[str, Any]) -> None:
    f1, f2, f3, f4 = world["fixtures"]
    with psycopg.connect(dsn) as c:
        for fx, n in ((f1, 0), (f2, 1), (f3, 2), (f4, 3)):
            decide(c, fx, ko=KO + timedelta(minutes=15 * n), before=timedelta(hours=5), market="1X2", selection="Home", line=0,
                   state="INVESTIGACION", reasons=["edge_not_validated"], odds=2.6, p=0.5, p_low=0.47, p_market=0.38)
        decide(c, f1, ko=KO, before=timedelta(hours=5), market="OU", selection="Over", line=2.0, state="INVESTIGACION",
               reasons=["edge_not_validated"], odds=2.0, p=0.6, p_low=0.55, p_market=0.48)  # a line that can push: never a leg
        c.commit()
        seen = fingerprint(c)
        at = KO - timedelta(hours=4)
        assert link(c, now=at).new_chains == 5

        rep = v6_shadow.run_pass(c, now=at)
        assert rep.errors == [] and rep.built == 1, rep.as_json()
        assert rep.by_kind["multiday"] == "none:ninguna_combinacion_cumple", "one product day: no multi-day parlay yet"
        parlays = c.execute("SELECT kind, n_legs, max_legs, p_joint, p_joint_low, p_product, combined_odds FROM intel.parlays_v6 "
                            "WHERE outcome = 'built' ORDER BY kind").fetchall()
        assert c.execute("SELECT count(*) FROM intel.parlays_v6 WHERE outcome = 'none' AND day < %s", (KO.date(),)).fetchone() == (6,), \
            "the three days before, without a parlay of either kind, are recorded as such"
        assert [(k, n) for k, n, *_ in parlays] == [("daily", 3)], "four confirmed legs, three at most"
        for _, n, cap, pj, low, prod, odds in parlays:
            assert 2 <= n <= cap <= 3 and low <= pj <= 0.5 and float(odds) > 1 and abs(float(pj) - float(prod)) < 0.01
        legs = c.execute("SELECT DISTINCT market_key FROM intel.parlay_v6_legs").fetchall()
        assert legs == [("1X2",)], "the line that can push is never a leg"
        again = v6_shadow.run_pass(c, now=at + timedelta(minutes=15))
        assert again.built == 0 and again.by_kind.get("daily") == "kept"

        # kick-off and the result; the daily parlay's legs: three home wins of 1-0, 0-0 and 2-1 ...
        for fx, score in ((f1, (1, 0)), (f2, (0, 0)), (f3, (2, 1)), (f4, (3, 3))):
            c.execute("UPDATE core.fixtures SET status_short = 'FT', status_group = 'finished' WHERE id = %s", (fx,))
            c.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away, ft_goals_home, ft_goals_away) "
                      "VALUES (%s, %s, %s, %s, %s)", (fx, *score, *score))
        c.commit()
        after = KO + timedelta(hours=3)
        link(c, now=after)
        assert states(c, f1)[-1] == ("en_juego", "saque")

        dry = tracking.run_pass(c, now=after, dry_run=True)
        assert dry.settled == 5 and c.execute("SELECT count(*) FROM intel.selection_settlements").fetchone() == (0,)
        first = tracking.run_pass(c, now=after)
        assert first.errors == [] and (first.settled, first.appended) == (5, 5), first.as_json()
        assert states(c, f1)[-2:] == [("en_juego", "saque"), ("liquidada", "resultado")]
        results: dict[str, str] = dict(c.execute("SELECT market_key || fixture_id, result FROM intel.selection_settlements").fetchall())
        assert results[f"1X2{f1}"] == "win" and results[f"1X2{f2}"] == "loss" and results[f"OU{f1}"] == "loss"
        second = tracking.run_pass(c, now=after + timedelta(minutes=15))
        assert (second.settled, second.corrected, second.appended) == (0, 0, 0), "a second pass writes nothing"
        assert link(c, now=after + timedelta(minutes=20)).divergent == 0, "the layer's derivation agrees with what the tracking appended"

        # the provider corrects match 2 to 1-0: a new row naming the one it supersedes; the chain does not move
        c.execute("UPDATE core.fixture_results SET goals_home = 1, ft_goals_home = 1 WHERE fixture_id = %s", (f2,))
        c.commit()
        fixed = tracking.run_pass(c, now=after + timedelta(hours=5))
        assert (fixed.corrected, fixed.appended) == (1, 0)
        trail = c.execute("SELECT kind, result, supersedes_id IS NOT NULL FROM intel.selection_settlements WHERE fixture_id = %s "
                          "AND market_key = '1X2' ORDER BY id", (f2,)).fetchall()
        assert trail == [("primera", "loss", False), ("correccion", "win", True)]

        # seven days later: the firm evaluation, with the value against the close; Evaluada
        late = KO + tracking.FIRM_AFTER + timedelta(hours=2)
        firm = tracking.run_pass(c, now=late)
        assert firm.firm == 5 and firm.appended == 5
        assert states(c, f1)[-1] == ("evaluada", "evaluacion_posterior")
        assert c.execute("SELECT count(*) FROM intel.selection_settlements WHERE kind = 'firme' AND odds_taken IS NOT NULL").fetchone() == (5,)

        read = v6_shadow.read(c, start=KO.date(), end=KO.date())
        daily = next(p for p in read if p["kind"] == "daily")
        assert daily["status"] in ("WON", "LOST") and all(leg["result"] in ("win", "loss") for leg in daily["legs"])
        cal = v6_shadow.calibration(read)
        assert cal["settled"] >= 1 and cal["note"]

        one = tracking.tracking(c, writer=WRITER, fixture_id=f2, market_key="1X2", selection="Home", line=0)
        assert one["result"] == "win" and one["corrected"] and one["state"] == "evaluada" and "local gana" in one["how_it_settles"]
        parity = tracking.parity(c, start=KO, end=late + timedelta(days=1))
        assert parity["settled"] == 5 and parity["without_pick"] == 5
        assert fingerprint(c) == seen, "nothing it reads was changed: decision-v1, parlay-v5, the picks"


def test_a_day_without_a_parlay_is_a_record(dsn: str, world: dict[str, Any]) -> None:
    with psycopg.connect(dsn) as c:
        later = KO + timedelta(days=2)
        rep = v6_shadow.run_pass(c, now=later)
        assert rep.errors == [] and rep.days_without >= 2
        rows: dict[str, str] = dict(c.execute("SELECT kind || day::text, none_reason FROM intel.parlays_v6 WHERE outcome = 'none'").fetchall())
        assert rows and set(rows.values()) <= {"sin_candidatos", "un_solo_candidato", "ninguna_combinacion_cumple"}
        assert rows[f"multiday{KO.date().isoformat()}"] == "ninguna_combinacion_cumple", "four chains confirmed, none over two days"
        assert v6_shadow.run_pass(c, now=later).days_without == 0, "recorded once"


def test_two_passes_never_write_at_once(dsn: str, world: dict[str, Any]) -> None:
    with psycopg.connect(dsn, autocommit=True) as holder, psycopg.connect(dsn) as c:
        for lock, run in ((tracking.LOCK, lambda: tracking.run_pass(c, now=KO + timedelta(days=1))),
                          (v6_shadow.LOCK, lambda: v6_shadow.run_pass(c, now=KO + timedelta(days=1)))):
            holder.execute("SELECT pg_advisory_lock(%s)", (lock,))
            try:
                rep = run()
            finally:
                holder.execute("SELECT pg_advisory_unlock(%s)", (lock,))
            assert rep.errors == ["another pass holds the lock"]


def test_the_rule_never_lets_four_legs_in(dsn: str) -> None:
    assert v6.MAX_LEGS == 3
    with psycopg.connect(dsn) as c:
        assert c.execute("SELECT count(*) FROM intel.parlays_v6 WHERE n_legs > 3 OR max_legs > 3").fetchone() == (0,)
        assert c.execute("SELECT count(*) FROM intel.parlay_v6_legs l JOIN intel.selection_lifecycle s ON s.id = l.confirmed_id "
                         "WHERE s.state <> 'confirmada_sombra'").fetchone() == (0,), "every leg is a confirmation"
