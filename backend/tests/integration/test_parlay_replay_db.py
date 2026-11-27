"""RP-11.1 against a real PostgreSQL: the script's reading of the shadow's confirmed selections and their settlements is valid SQL over the real tables,
reads nothing it should not and writes nothing (``scripts.ia_parlay_replay``)."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from scripts import ia_parlay_replay as script

from fbi.parlays import replay

pytestmark = pytest.mark.integration


def test_the_reading_runs_over_the_real_tables_and_an_empty_history_says_so(db: psycopg.Connection[Any]) -> None:
    legs = script.read_legs(db, at=datetime(2026, 11, 27, 12, tzinfo=UTC), days=60)
    assert legs == []
    out = replay.report(legs)
    assert out["combinations"] == 0 and out["enough"] is False and out["within_bound"] is None
    text = script.render({**out, "days_back": 60})
    assert "NO se alcanza" in text and "0 combinaciones" in text


def _chain(c: psycopg.Connection[Any], fixture_id: int, ko: datetime, *, selection: str, p: float, settle: str | None) -> str:
    """One chain of decision-v2's shadow as the tracking leaves it: confirmed before kick-off and, when ``settle`` is given, played, settled and evaluated
    (so the chain's NEWEST row is no longer the confirmation), with its settlement row."""
    row = c.execute(
        "INSERT INTO intel.decisions (decision_version, known_at, checkpoint, fixture_id, kickoff_at, market_key, selection, line, model_name, odds, "
        "n_bookmakers, p_model, p_low, p_cal, p_market, filters, state, reasons, context_status, input_hash) VALUES ('decision-v1', %s, 'T-3h', %s, %s, "
        "'1X2', %s, 0, 'dixon_coles', 2.0, 5, %s, %s, %s, 0.5, '[]'::jsonb, 'INVESTIGACION', '{}', 'FULL', %s) RETURNING id",
        (ko - timedelta(hours=3), fixture_id, ko, selection, p, p - 0.05, p, f"rp-{fixture_id}-{selection}")).fetchone()
    assert row is not None
    chain = f"{script.WRITER}|{fixture_id}|1X2|{selection}|0.00"
    ids: list[int] = []

    def move(state: str, reason: str, at: datetime, *, source: str, source_id: int | None, result: str | None = None) -> None:
        prev = ids[-1] if ids else None
        got = c.execute(
            "INSERT INTO intel.selection_lifecycle (chain_key, writer, fixture_id, market_key, selection, line, layer, previous_id, from_state, state, reason, "
            "actor, settlement_result, known_at, source, source_id, machine_version) VALUES (%s, %s, %s, '1X2', %s, 0, 'decision-v2', %s, %s, %s, %s, 'code', "
            "%s, %s, %s, %s, 'lifecycle-v1') RETURNING id",
            (chain, script.WRITER, fixture_id, selection, prev, None if prev is None else states[-1], state, reason, result, at, source, source_id)).fetchone()
        assert got is not None
        ids.append(int(got[0]))
        states.append(state)

    states: list[str] = []
    move("detectado", "candidato_nuevo", ko - timedelta(hours=4), source="intel.decisions", source_id=int(row[0]))
    move("confirmada_sombra", "cumple_todo", ko - timedelta(hours=3), source="intel.decisions", source_id=int(row[0]))
    if settle is not None:
        move("en_juego", "saque", ko, source="core.fixtures", source_id=fixture_id)
        move("liquidada", "resultado", ko + timedelta(hours=3), source="core.fixtures", source_id=fixture_id, result=settle)
        move("evaluada", "evaluacion_posterior", ko + timedelta(days=1), source="core.fixtures", source_id=fixture_id)
        c.execute(
            "INSERT INTO intel.selection_settlements (chain_key, writer, fixture_id, market_key, selection, line, kind, result, rule_version, known_at, "
            "tracker_version) VALUES (%s, %s, %s, '1X2', %s, 0, 'primera', %s, 'settle-v4', %s, 'selection-settle-v1')",
            (chain, script.WRITER, fixture_id, selection, settle, ko + timedelta(hours=3)))
    return chain


def test_settled_chains_are_read_with_their_confirmation_and_their_result(db: psycopg.Connection[Any], seed: Any) -> None:
    """The history the replay needs is the settled one: a chain whose newest row is ``evaluada`` still gives its confirmation (the probability of the
    decision it was confirmed on) and its settlement; one still waiting for its match has no result."""
    ko = datetime(2026, 11, 20, 19, 0, tzinfo=UTC)
    fixtures = []
    for n in range(3):
        row = db.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at) "
                         "VALUES (%s, %s, %s, %s, %s) RETURNING id",
                         (990_000 + n, seed.season_id, seed.home_team_id, seed.away_team_id, ko + timedelta(days=n))).fetchone()
        assert row is not None
        fixtures.append(int(row[0]))
    won = _chain(db, fixtures[0], ko, selection="Home", p=0.6, settle="win")
    lost = _chain(db, fixtures[1], ko + timedelta(days=1), selection="Home", p=0.55, settle="loss")
    waiting = _chain(db, fixtures[2], ko + timedelta(days=2), selection="Home", p=0.5, settle=None)
    legs = script.read_legs(db, at=datetime(2026, 11, 27, 12, tzinfo=UTC), days=60)
    by = {leg.chain_key: leg for leg in legs}
    assert set(by) == {won, lost, waiting}
    assert by[won].p == pytest.approx(0.6) and by[won].p_market == pytest.approx(0.5)
    assert by[won].result == "win" and by[lost].result == "loss" and by[waiting].result is None
