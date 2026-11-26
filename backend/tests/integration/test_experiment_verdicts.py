"""RP-8.1 on a real database (migration 0183): a verdict is written only on a protocol registered before it; it is never edited; the newest of an experiment
supersedes the older; NaN is stored as no figure; the report reads it all. The transaction is rolled back afterwards."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
from scripts import research_cycle

from fbi.research import cycle_state, evolution, exp_protocol, verdicts
from fbi.research.protocol import fingerprint

pytestmark = pytest.mark.integration

NOW = datetime(2026, 12, 1, 12, tzinfo=UTC)
E1 = exp_protocol.EXPERIMENTS["EXP-E1"]


def decided(mean: float = -0.002) -> exp_protocol.Judgement:
    return exp_protocol.Judgement("exito", "por debajo del umbral, con intervalo y mismo signo en las dos mitades", mean, mean - 0.003, mean + 0.002, 1200, 0.01)


def insufficient() -> exp_protocol.Judgement:
    return exp_protocol.difference_verdict([0.0] * 5, [NOW.date()] * 5, success_below=0.005, n_required=1000, seed=1)


def test_a_verdict_on_a_registered_protocol_is_written_with_its_fingerprint_and_thresholds(db: psycopg.Connection[Any]) -> None:
    v = verdicts.record(db, "EXP-E1", decided(), claimed_fingerprint=fingerprint(E1), computed_at=NOW, population={"matches": 1200, "from": "2026-11-26"})
    assert (v.experiment, v.verdict, v.n, v.recorded_by) == ("EXP-E1", "exito", 1200, "system")
    assert v.protocol_fingerprint == fingerprint(E1) and v.protocol_version == E1.version
    assert v.thresholds == {"success_below": 0.005, "n_required": 1000}
    assert v.population["matches"] == 1200
    assert v.low is not None and v.mean is not None and v.high is not None and v.low < v.mean < v.high


def test_a_verdict_without_a_prior_protocol_is_refused_and_nothing_is_written(db: psycopg.Connection[Any]) -> None:
    before = db.execute("SELECT count(*) FROM analytics.experiment_verdicts").fetchone()
    with pytest.raises(exp_protocol.ProtocolRefusedError, match="no hay protocolo"):
        verdicts.record(db, "EXP-E9", decided(), claimed_fingerprint="0" * 64, computed_at=NOW)
    with pytest.raises(exp_protocol.ProtocolRefusedError, match="huella"):
        verdicts.record(db, "EXP-E1", decided(), claimed_fingerprint="f" * 64, computed_at=NOW)
    with pytest.raises(exp_protocol.ProtocolRefusedError, match="anterior a la firma"):
        verdicts.record(db, "EXP-E1", decided(), claimed_fingerprint=fingerprint(E1), computed_at=datetime(2026, 11, 1, tzinfo=UTC))
    assert db.execute("SELECT count(*) FROM analytics.experiment_verdicts").fetchone() == before


def test_the_code_refuses_what_the_table_would_refuse_before_the_database_says_it(db: psycopg.Connection[Any]) -> None:
    fp = fingerprint(E1)
    with pytest.raises(verdicts.VerdictRefusedError, match="media y su intervalo"):
        verdicts.record(db, "EXP-E1", exp_protocol.Judgement("exito", "una razón suficientemente larga", float("nan"), 0.0, 0.0, 1200), claimed_fingerprint=fp, computed_at=NOW)
    with pytest.raises(verdicts.VerdictRefusedError, match="motivo"):
        verdicts.record(db, "EXP-E1", exp_protocol.Judgement("insuficiente", "corto", float("nan"), float("nan"), float("nan"), 3), claimed_fingerprint=fp, computed_at=NOW)
    with pytest.raises(verdicts.VerdictRefusedError, match="zona horaria"):
        verdicts.record(db, "EXP-E1", decided(), claimed_fingerprint=fp, computed_at=NOW.replace(tzinfo=None))
    with pytest.raises(verdicts.VerdictRefusedError, match="quien registra"):
        verdicts.record(db, "EXP-E1", decided(), claimed_fingerprint=fp, computed_at=NOW, recorded_by="nobody")  # type: ignore[arg-type]


def test_the_table_itself_refuses_a_decided_verdict_without_its_figures_and_any_edit(db: psycopg.Connection[Any]) -> None:
    fp = fingerprint(E1)
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        db.execute("INSERT INTO analytics.experiment_verdicts (experiment, protocol_version, protocol_fingerprint, verdict, reason, n, computed_at, recorded_by) "
                   "VALUES ('EXP-E1', 'v', %s, 'abandono', 'sin cifras no hay veredicto', 10, now(), 'system')", (fp,))
    v = verdicts.record(db, "EXP-E1", decided(), claimed_fingerprint=fp, computed_at=NOW)
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        db.execute("UPDATE analytics.experiment_verdicts SET verdict = 'abandono' WHERE id = %s", (v.id,))
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        db.execute("DELETE FROM analytics.experiment_verdicts WHERE id = %s", (v.id,))


def test_nan_is_stored_as_no_figure_and_an_insufficient_verdict_needs_none(db: psycopg.Connection[Any]) -> None:
    v = verdicts.record(db, "EXP-E1", insufficient(), claimed_fingerprint=fingerprint(E1), computed_at=NOW)
    assert (v.verdict, v.n, v.mean, v.low, v.high) == ("insuficiente", 5, None, None, None)
    assert "muestra 5 de 1000" in v.reason


def test_the_newest_verdict_of_an_experiment_supersedes_the_older_and_the_older_stays(db: psycopg.Connection[Any]) -> None:
    fp = fingerprint(E1)
    first = verdicts.record(db, "EXP-E1", insufficient(), claimed_fingerprint=fp, computed_at=NOW)
    second = verdicts.record(db, "EXP-E1", decided(), claimed_fingerprint=fp, computed_at=NOW, recorded_by="owner")
    assert [v.id for v in verdicts.history(db, "EXP-E1")] == [second.id, first.id]
    now = {v.experiment: v for v in verdicts.latest(db)}
    assert now["EXP-E1"].id == second.id and now["EXP-E1"].verdict == "exito"
    assert "EXP-E1" not in verdicts.pending(db) and "EXP-E2" in verdicts.pending(db)


def test_an_insufficient_verdict_does_not_close_an_experiment(db: psycopg.Connection[Any]) -> None:
    verdicts.record(db, "EXP-E3", insufficient(), claimed_fingerprint=fingerprint(exp_protocol.EXPERIMENTS["EXP-E3"]), computed_at=NOW)
    assert "EXP-E3" in verdicts.pending(db)


def test_a_hypothesis_can_be_archived_by_the_database_and_nothing_else_is_accepted(db: psycopg.Connection[Any]) -> None:
    hid = evolution.propose(db, title="hipótesis de prueba", hypothesis="h", rationale="r", evidence={}, proposed_by="owner", at=NOW)
    assert hid is not None
    db.execute("UPDATE analytics.research_hypotheses SET status = 'ARCHIVED', decided_at = %s WHERE id = %s", (NOW, hid))
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        db.execute("UPDATE analytics.research_hypotheses SET status = 'LOST', decided_at = now() WHERE id = %s", (hid,))


def test_the_report_counts_every_state_of_the_graph_and_none_outside_it(db: psycopg.Connection[Any]) -> None:
    hid = evolution.propose(db, title="otra hipótesis de prueba", hypothesis="h", rationale="r", evidence={}, proposed_by="owner", at=NOW)
    assert hid is not None
    db.execute("UPDATE analytics.research_hypotheses SET status = 'ARCHIVED', decided_at = %s WHERE id = %s", (NOW, hid))
    verdicts.record(db, "EXP-E1", decided(), claimed_fingerprint=fingerprint(E1), computed_at=NOW)
    doc = research_cycle.report(db)
    assert [s["state"] for s in doc["states"]] == list(cycle_state.STATES)
    assert doc["outside_the_graph"] == {}
    assert next(s for s in doc["states"] if s["state"] == "ARCHIVED")["n"] >= 1
    assert [v["experiment"] for v in doc["verdicts"]] == ["EXP-E1"]
    text = "\n".join(research_cycle.lines(doc))
    assert "EXP-E1: exito" in text and "ARCHIVED" in text and "sin veredicto decidido: EXP-E2" in text
