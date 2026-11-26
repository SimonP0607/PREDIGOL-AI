"""RP-8.5 on a real database: the decisions as the fixed groups read them (reason, distance to the market, tier, search, line-ups, news), a decision that
cannot say a group is simply left out of it, the weekly step off by default and the command that reads without writing."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb
from scripts import decision_groups as cli

from fbi.research import decision_groups as dg

from .conftest import Seed
from .test_pattern_search import AT, KICK, START, Ground

pytestmark = pytest.mark.integration


@pytest.fixture()
def ground(db: psycopg.Connection[Any], seed: Seed) -> Ground:
    return Ground(db, seed)


def decide(db: psycopg.Connection[Any], fixture: int, selection: str, *, state: str, p_model: float, p_cal: float | None, reasons: list[str],
           p_market: float | None, context: dict[str, Any]) -> int:
    """A decision with what these groups read (decisions are append-only: it is written whole)."""
    known = KICK - timedelta(hours=3)
    row = db.execute(
        "INSERT INTO intel.decisions (decision_version, known_at, checkpoint, fixture_id, kickoff_at, market_key, selection, line, model_name, odds, p_model, "
        "p_cal, p_market, reasons, filters, state, stake_units, context_status, context, input_hash) VALUES ('decision-v1', %s, 'T-3h', %s, %s, '1X2', %s, 0, "
        "'dixon_coles', 2.2, %s, %s, %s, %s, %s, %s, 0, 'PENDING', %s, %s) RETURNING id",
        (known, fixture, KICK, selection, p_model, p_cal, p_market, reasons, Jsonb([]), state, Jsonb(context), f"{fixture}|{selection}|{state}")).fetchone()
    assert row is not None
    return int(row[0])


def test_a_decision_is_read_in_the_fixed_groups_and_one_that_cannot_say_a_group_is_left_out_of_it(db: psycopg.Connection[Any], ground: Ground) -> None:
    comp, season = ground.competition("Liga A", "domestic_league")
    db.execute("UPDATE core.competitions SET tier = 2 WHERE id = %s", (comp,))
    fid = ground.match(season=season)
    a = decide(db, fid, "Home", state="RECHAZADO", p_model=0.60, p_cal=0.56, reasons=["ev", "edge_not_validated"], p_market=0.5,
               context={"web_searched": True, "lineups_at": KICK.isoformat(), "evidence": {"web:CONFIRMED": 2, "provider:PROBABLE": 1}})
    b = decide(db, fid, "Away", state="CAUTELA", p_model=0.30, p_cal=None, reasons=[], p_market=None, context={})
    ground.settle(a, "win")
    ground.settle(b, "loss")
    rows, labels = dg.read(db, start=START, end=AT)
    tags = {r.tags["selection"][0]: r.tags for r in rows}
    assert tags["1X2 Home"]["reject_reason"] == ("ev",) and tags["1X2 Home"]["market_distance"] == ("sobre +5 puntos",)
    assert tags["1X2 Home"]["competition_tier"] == ("nivel 2",) and tags["1X2 Home"]["searched"] == ("yes",)
    assert tags["1X2 Home"]["lineups"] == ("yes",) and tags["1X2 Home"]["news"] == ("yes",)
    away = tags["1X2 Away"]
    assert away["reject_reason"] == ("ninguno",) and "market_distance" not in away and "searched" not in away and "news" not in away
    assert labels[("searched", "yes")] == "con búsqueda web"
    assert all("odds_band" in t and "market" in t for t in tags.values()), "the groups of the 12 dimensions are still there for the strata"


def test_the_weekly_step_is_off_by_default_and_the_command_reads_without_writing(db: psycopg.Connection[Any], ground: Ground, monkeypatch: pytest.MonkeyPatch,
                                                                                capsys: pytest.CaptureFixture[str]) -> None:
    monkeypatch.setattr(dg, "environment", lambda: {})
    assert dg.weekly(db, at=AT) == {"mode": "off"}
    monkeypatch.setattr(dg, "environment", lambda: {dg.SWITCH: "report"})
    out = dg.weekly(db, at=AT)
    assert out["mode"] == "report" and out["confirmed"] == [] and "proposed" not in out
    before = db.execute("SELECT count(*) FROM analytics.research_hypotheses").fetchone()
    text = dg.render(dg.columns(dg.run(db, at=AT)))
    assert "SE CONFIRMA (0)" in text
    assert db.execute("SELECT count(*) FROM analytics.research_hypotheses").fetchone() == before
    assert isinstance(AT - timedelta(days=1), datetime) and callable(cli.main)
