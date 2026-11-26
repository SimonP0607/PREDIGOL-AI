"""RP-8.4 (tranche 2) on a real database: the scan reads what the registry has in force, reads each calibrator's last 14 days, says which kinds are not watched, and
the command drafts a withdrawal once, for the owner, from a degrading version a reader covers."""

from __future__ import annotations

import argparse
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb
from scripts import ia_proposals

from fbi.governance import promotions as registry
from fbi.proposals import store
from fbi.proposals import surveillance as rule
from fbi.proposals import watch as surveillance

pytestmark = pytest.mark.integration

NOW = datetime(2026, 12, 20, 12, tzinfo=UTC)


def calibrator(db: psycopg.Connection[Any], *, model: str = "poisson", days: int = 1, n: int = 600, ll_cal: float = 0.60, ll_raw: float = 0.61, ece: float = 0.01) -> int:
    row = db.execute("INSERT INTO intel.calibrators (market_key, model_name, method, version, params, known_at, fitted_at, n_train, train_hash) "
                     "VALUES ('1X2', %s, 'logit2', 'cal-logit2-v1', '{}'::jsonb, %s, %s, 1000, 'h') RETURNING id", (model, NOW - timedelta(days=20), NOW - timedelta(days=20))).fetchone()
    assert row is not None
    cid = int(row[0])
    for d in range(days):
        db.execute("INSERT INTO intel.calibrator_evaluations (calibrator_id, day, evaluated_at, n, logloss_cal, logloss_raw, ece_cal) VALUES (%s, %s, %s, %s, %s, %s, %s)",
                   (cid, (NOW - timedelta(days=d + 1)).date(), NOW, n // days, ll_cal, ll_raw, ece))
    return cid


def champion(db: psycopg.Connection[Any], cid: int, model: str = "poisson", at: datetime = NOW - timedelta(days=15)) -> None:
    db.execute("INSERT INTO intel.promotions (at, entity, market_key, model_name, entity_id, from_role, to_role, gate_version, criteria, reason, decided_by) "
               "VALUES (%s, 'calibrator', '1X2', %s, %s, NULL, 'CHAMPION', 'calib-gate-v1', %s, 'first champion', 'system')", (at, model, cid, Jsonb({})))


def test_a_champion_calibrator_is_read_over_its_last_14_days_and_kept_when_not_worse(db: psycopg.Connection[Any]) -> None:
    champion(db, calibrator(db, days=5, n=600, ll_cal=0.59, ll_raw=0.61))
    report = surveillance.scan(db, at=NOW)
    (f,) = [x for x in report.findings if x.key == "1X2/poisson"]
    assert (f.entity_type, f.automatic, f.verdict.state) == ("calibrator", True, rule.KEEPS) and f.reading is not None and f.reading.n == 600


def test_a_small_sample_is_insufficient_and_a_degrading_calibrator_is_reported_but_not_proposed(db: psycopg.Connection[Any]) -> None:
    champion(db, calibrator(db, days=2, n=100, ll_cal=0.9, ll_raw=0.6))
    champion(db, calibrator(db, model="elo_ologit", days=3, n=900, ll_cal=0.70, ll_raw=0.60, ece=0.2), model="elo_ologit")
    report = surveillance.scan(db, at=NOW)
    states = {f.key: f.verdict.state for f in report.findings if f.entity_type == "calibrator"}
    assert states == {"1X2/poisson": rule.SHORT, "1X2/elo_ologit": rule.DEGRADES}
    assert [rule.withdrawal(f) for f in report.findings if f.entity_type == "calibrator"] == [None, None], "the calibration step withdraws these by itself"


def test_a_retired_calibrator_is_not_in_force_and_so_not_watched(db: psycopg.Connection[Any]) -> None:
    cid = calibrator(db, days=3, n=900, ll_cal=0.7, ll_raw=0.6)
    champion(db, cid)
    db.execute("INSERT INTO intel.promotions (at, entity, market_key, model_name, entity_id, from_role, to_role, gate_version, criteria, reason, decided_by) "
               "VALUES (%s, 'calibrator', '1X2', 'poisson', %s, 'CHAMPION', 'RETIRED', 'calib-gate-v1', %s, 'retired', 'system')", (NOW - timedelta(days=1), cid, Jsonb({})))
    assert [x for x in surveillance.scan(db, at=NOW).findings if x.entity_type == "calibrator"] == []


def test_the_kinds_without_a_reader_are_listed_as_not_watched_never_as_healthy(db: psycopg.Connection[Any]) -> None:
    db.execute("INSERT INTO intel.promotions (at, entity, market_key, model_name, entity_id, from_role, to_role, gate_version, criteria, reason, decided_by) "
               "VALUES (%s, 'selection_rule', '1X2', 'poisson', 7, NULL, 'CHAMPION', 'edge-gate-v1', %s, 'rule in force', 'system')", (NOW - timedelta(days=3), Jsonb({})))
    report = surveillance.scan(db, at=NOW)
    assert any(x["entity_type"] == "selection_rule" and x["key"] == "1X2/poisson" for x in report.not_watched)
    s = report.summary()
    assert s["in_force"] == s["watched"] + s["not_watched"] and s["not_watched"] >= 1


def test_the_command_drafts_one_withdrawal_for_a_degrading_version_a_reader_covers_and_registers_it_once(db: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch) -> None:
    db.execute("INSERT INTO intel.promotions (at, entity, market_key, model_name, entity_id, from_role, to_role, gate_version, criteria, reason, decided_by) "
               "VALUES (%s, 'selection_rule', '1X2', 'poisson', 6, NULL, 'CHAMPION', 'edge-gate-v1', %s, 'first rule', 'system'), "
               "(%s, 'selection_rule', '1X2', 'poisson', 7, 'CHAMPION', 'CHAMPION', 'edge-gate-v1', %s, 'second rule', 'system')",
               (NOW - timedelta(days=30), Jsonb({}), NOW - timedelta(days=10), Jsonb({})))
    monkeypatch.setitem(surveillance.READERS, "selection_rule", lambda conn, promotion, at: rule.Reading(900, 0.70, 0.60, None))
    monkeypatch.setattr(ia_proposals, "datetime", type("D", (), {"now": staticmethod(lambda tz=None: NOW)}))
    ns = argparse.Namespace(command="watch", write=False, proposal_id=None)
    plan, code = ia_proposals.run(db, ns)
    assert code == ia_proposals.OK and plan["written"] == [] and [p["target"] for p in plan["plan"]] == ["store:promotion/selection_rule/1X2/poisson"]
    ns.write = True
    done, _ = ia_proposals.run(db, ns)
    assert len([w for w in done["written"] if w is not None]) == 1
    again, _ = ia_proposals.run(db, ns)
    assert again["written"] == []
    (row,) = [r for r in store.rows(db) if r.proposal.kind == "retirada" and r.proposal.target.startswith("store:promotion/")]
    assert row.status == "pendiente_de_firma" and (row.proposal.current_version, row.proposal.proposed_version) == ("7", "6")
    assert store.summary(db)["applied_without_signature"] == 0 and registry.BY_VERSION  # nothing was applied or signed
