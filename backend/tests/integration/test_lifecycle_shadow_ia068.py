"""IA-068 (AD-D02): the shadow writer of the cycle against a real PostgreSQL - it reads decision-v1, decision-fam-v1, the reviews, the
settlements and the post-mortems, appends the chains, changes none of what it reads, says the same thing twice as nothing, closes at the
kick-off, settles and evaluates, skips a closed match, refuses to run twice at once, and the private reader counts every state.

The pass commits, so the file has its own scratch database (``<FBI_TEST_DB>_lc068``), migrated to head and dropped at the end."""

from __future__ import annotations

import os
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

import psycopg
import pytest
from alembic import command
from psycopg.types.json import Jsonb

from fbi.lifecycle import machine, reader, store
from fbi.lifecycle.derive import Key
from tests.integration.conftest import ADMIN_URL, TEST_DB, _dsn
from tests.integration.test_migration_0111 import _cfg

pytestmark = pytest.mark.integration

SCRATCH = f"{TEST_DB}_lc068"
KO = datetime(2026, 9, 15, 19, 0, tzinfo=UTC)
READ = ("intel.decisions", "intel.decision_outcomes", "intel.postmortems", "ai.pick_reviews", "picks.picks", "core.fixtures")


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
def world(dsn: str) -> dict[str, int]:
    with psycopg.connect(dsn, autocommit=True) as c:
        comp = c.execute("INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type) "
                         "VALUES (39, 'Premier League', 'league', 'club', 'domestic_league') RETURNING id").fetchone()
        assert comp is not None
        season = c.execute("INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, 2026) RETURNING id", (comp[0],)).fetchone()
        home = c.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (33, 'Local') RETURNING id").fetchone()
        away = c.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (40, 'Visitante') RETURNING id").fetchone()
        assert season is not None and home is not None and away is not None
        fx = c.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at) "
                       "VALUES (1001, %s, %s, %s, %s) RETURNING id", (season[0], home[0], away[0], KO)).fetchone()
        assert fx is not None
        return {"fixture": int(fx[0]), "competition": int(comp[0])}


def decide(c: psycopg.Connection[Any], fx: int, *, version: str, before: timedelta, checkpoint: str, market: str, selection: str,
           line: float, state: str, reasons: list[str], context: str = "FULL") -> int:
    row = c.execute(
        "INSERT INTO intel.decisions (decision_version, known_at, checkpoint, fixture_id, kickoff_at, market_key, selection, line, model_name, "
        "p_model, filters, state, reasons, context_status, input_hash) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, 'dixon_coles', 0.55, %s, %s, "
        "%s, %s, %s) RETURNING id",
        (version, KO - before, checkpoint, fx, KO, market, selection, line, Jsonb([]), state, reasons, context,
         f"h{version}{checkpoint}{market}{selection}")).fetchone()
    assert row is not None
    return int(row[0])


def fingerprint(c: psycopg.Connection[Any]) -> dict[str, str]:
    """Every table the writer reads, as a hash of its rows: what must not move."""
    out = {}
    for t in READ:
        rows = c.execute(f"SELECT md5(coalesce(string_agg(x::text, '|' ORDER BY x::text), '')) FROM {t} x").fetchone()
        assert rows is not None
        out[t] = str(rows[0])
    return out


def chains(c: psycopg.Connection[Any]) -> dict[str, list[tuple[str, str, str]]]:
    out: dict[str, list[tuple[str, str, str]]] = {}
    for key, state, reason, actor in c.execute("SELECT chain_key, state, reason, actor FROM intel.selection_lifecycle ORDER BY chain_key, id"):
        out.setdefault(str(key).split("|", 2)[2], []).append((str(state), str(reason), str(actor)))
    return out


def test_the_shadow_writer_appends_the_cycle_and_changes_nothing_it_reads(dsn: str, world: dict[str, int]) -> None:
    fx = world["fixture"]
    with psycopg.connect(dsn) as c:
        decide(c, fx, version="decision-v1", before=timedelta(hours=24), checkpoint="T-24h", market="OU", selection="over", line=2.5,
               state="CAUTELA", reasons=["risk"], context="PENDING")
        confirmed = decide(c, fx, version="decision-v1", before=timedelta(hours=3), checkpoint="T-3h", market="OU", selection="over",
                           line=2.5, state="INVESTIGACION", reasons=["edge_not_validated"])
        decide(c, fx, version="decision-v1", before=timedelta(minutes=8), checkpoint="lineups", market="OU", selection="over", line=2.5,
               state="RECHAZADO", reasons=["data", "price_not_fresh"])
        decide(c, fx, version="decision-fam-v1", before=timedelta(hours=6), checkpoint="T-6h", market="CORNERS_OU", selection="over",
               line=9.5, state="INVESTIGACION", reasons=["ev_unknown", "family_research", "not_calibrated"])
        c.commit()
        seen = fingerprint(c)

        before_ko = store.run_pass(c, now=KO - timedelta(hours=1))
        assert (before_ko.selections, before_ko.new_chains, before_ko.appended, before_ko.divergent, before_ko.illegal) == (2, 2, 5, 0, 0)
        assert chains(c) == {
            "CORNERS_OU|over|9.50": [("detectado", "candidato_nuevo", "code"), ("en_evaluacion", "sin_calibrar", "code")],
            "OU|over|2.50": [("detectado", "candidato_nuevo", "code"), ("en_investigacion", "contexto_pendiente", "code"),
                             ("confirmada_sombra", "cumple_salvo_validacion", "code")]}
        layers: dict[str, str] = dict(c.execute("SELECT market_key, min(layer) FROM intel.selection_lifecycle GROUP BY 1").fetchall())
        assert layers == {"CORNERS_OU": "decision-fam-v1", "OU": "decision-v1"}

        again = store.run_pass(c, now=KO - timedelta(hours=1))
        assert (again.appended, again.unchanged) == (0, 2), "the same layers say the same: nothing new"

        c.execute("UPDATE core.fixtures SET status_short = 'FT', status_group = 'finished' WHERE id = %s", (fx,))
        c.execute("INSERT INTO intel.decision_outcomes (decision_id, settled_at, result_status, profit_flat, profit_staked, version, computed_at) "
                  "VALUES (%s, %s, 'win', 0.9, 0, 'outcome-v1', %s)", (confirmed, KO + timedelta(hours=40), KO + timedelta(hours=40)))
        c.execute("INSERT INTO intel.postmortems (decision_id, fixture_id, created_at, version, outcome, decision_quality, verdict, answers) "
                  "VALUES (%s, %s, %s, 'pm-v4', 'won', 'GOOD', 'MERECIDO', '{}'::jsonb)", (confirmed, fx, KO + timedelta(hours=44)))
        c.commit()
        seen = fingerprint(c)

        dry = store.run_pass(c, now=KO + timedelta(days=3), dry_run=True)
        assert dry.appended == 4 and c.execute("SELECT count(*) FROM intel.selection_lifecycle").fetchone() == (5,), "a dry run writes nothing"

        after = store.run_pass(c, now=KO + timedelta(days=3))
        assert (after.extended, after.appended, after.divergent) == (2, 4, 0)
        got = chains(c)
        assert got["OU|over|2.50"][-3:] == [("en_juego", "saque", "code"), ("liquidada", "resultado", "code"),
                                            ("evaluada", "evaluacion_posterior", "code")], "the last ten minutes did not withdraw it"
        assert got["CORNERS_OU|over|9.50"][-1] == ("descartada", "sin_calibrar", "code")
        assert c.execute("SELECT settlement_result FROM intel.selection_lifecycle WHERE state = 'liquidada'").fetchone() == ("win",)
        assert fingerprint(c) == seen, "the writer changed a table it reads"

        closed = store.run_pass(c, now=KO + timedelta(days=4))
        assert (closed.skipped_closed, closed.selections, closed.appended) == (1, 0, 0), "a played match whose chains are closed is skipped"

        page = reader.tracking(c, date_from=date(2026, 9, 15), date_to=date(2026, 9, 15))
        assert page["counts_by_state"] == {s: (1 if s in ("evaluada", "descartada") else 0) for s in page["counts_by_state"]}
        assert list(page["counts_by_state"]) == list(machine.STATES)
        assert {i["state"] for i in page["items"]} == {"evaluada", "descartada"} and page["next_cursor"] is None
        assert all(i["public_state"] is None for i in page["items"]), "nothing the shadow wrote is public"
        ou = next(i for i in page["items"] if i["selection"]["market"] == "OU")
        assert (ou["outcome"], ou["moves"], ou["selection"]["family"]) == ("win", 6, "core")
        corners = reader.tracking(c, date_from=date(2026, 9, 15), date_to=date(2026, 9, 15), family="corners")
        assert corners["period"]["total"] == 1 and corners["items"][0]["state"] == "descartada"
        first = reader.tracking(c, date_from=date(2026, 9, 15), date_to=date(2026, 9, 15), limit=1)
        assert len(first["items"]) == 1 and first["next_cursor"] is not None
        rest = reader.tracking(c, date_from=date(2026, 9, 15), date_to=date(2026, 9, 15), limit=1, cursor=first["next_cursor"])
        assert {first["items"][0]["state"], rest["items"][0]["state"]} == {"evaluada", "descartada"} and rest["next_cursor"] is None
        with pytest.raises(ValueError):
            reader.tracking(c, date_from=date(2026, 9, 1), date_to=date(2026, 10, 15))


def test_two_passes_never_write_at_once(dsn: str, world: dict[str, int]) -> None:
    with psycopg.connect(dsn, autocommit=True) as holder, psycopg.connect(dsn) as c:
        holder.execute("SELECT pg_advisory_lock(%s)", (store.LOCK,))
        try:
            rep = store.run_pass(c, now=KO + timedelta(days=3))
        finally:
            holder.execute("SELECT pg_advisory_unlock(%s)", (store.LOCK,))
        assert rep.errors == ["another pass holds the lock"] and rep.appended == 0


def test_the_measurement_reads_without_writing(dsn: str, world: dict[str, int]) -> None:
    with psycopg.connect(dsn, options="-c default_transaction_read_only=on") as c:
        start = KO - timedelta(hours=12)
        m = store.measure(c, start=start, end=start + timedelta(days=1), now=KO + timedelta(days=3))
        assert (m["fixtures"], m["selections"], m["illegal"], m["unknown_reason_rows"]) == (1, 2, 0, 0)
        assert m["rows"] == 9 and m["by_layer"] == {"decision-fam-v1": 1, "decision-v1": 1}
        dry = store.run_pass(c, now=KO + timedelta(days=3), dry_run=True)
        assert dry.errors == [] and dry.appended == 0


def test_the_chain_key_the_code_writes_is_the_one_the_table_checks(dsn: str, world: dict[str, int]) -> None:
    with psycopg.connect(dsn) as c:
        keys = [r[0] for r in c.execute("SELECT DISTINCT chain_key FROM intel.selection_lifecycle ORDER BY 1")]
        assert keys == sorted(store.chain_key(store.WRITER, Key.of(world["fixture"], m, s, ln))
                              for m, s, ln in (("CORNERS_OU", "over", "9.5"), ("OU", "over", "2.5")))
