"""Dataset versions: PRE_DATA_TRUTH_AUDIT stays LEGACY; a build records gates and is never MODEL_READY by itself;
only a person promotes a VALIDATED version, never while research is frozen; models refuse to train otherwise."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import psycopg
import pytest

from fbi.datasets import versions as dv

T0 = datetime(2026, 10, 4, 20, 0, tzinfo=UTC)


def test_the_legacy_dataset_is_kept_and_nothing_is_model_ready(db: psycopg.Connection) -> None:
    assert db.execute("SELECT status, model_ready FROM audit.dataset_versions WHERE name = 'PRE_DATA_TRUTH_AUDIT'"
                      ).fetchone() == ("LEGACY", False)
    with pytest.raises(dv.DatasetNotModelReadyError, match="PRE_DATA_TRUTH_AUDIT LEGACY"):
        dv.require_model_ready(db)
    with pytest.raises(ValueError, match="LEGACY"):
        dv.build(db, name="PRE_DATA_TRUTH_AUDIT", at=T0)


def test_a_build_without_audit_runs_is_a_candidate_with_failing_gates(db: psycopg.Connection) -> None:
    b = dv.build(db, at=T0)
    assert b.status == "CANDIDATE"
    failing = {g.key for g in b.gates if g.status == "fail"}
    assert {"phases", "standings", "field_coverage", "raw_integrity"} <= failing
    assert db.execute("SELECT status, model_ready FROM audit.dataset_versions WHERE name = 'DATASET_V2'").fetchone() \
        == ("CANDIDATE", False)


def test_promotion_is_a_persons_decision_on_a_validated_version_with_research_unfrozen(
        db: psycopg.Connection, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    import fbi.research.loop as loop

    db.execute("INSERT INTO audit.dataset_versions (name, status, model_ready, built_from) "
               "VALUES ('DATASET_T', 'CANDIDATE', false, 'test')")
    monkeypatch.setattr(loop, "FREEZE_FILE", tmp_path / "frozen")
    monkeypatch.delenv("FBI_RESEARCH_FROZEN", raising=False)
    with pytest.raises(ValueError, match="only a VALIDATED version"):
        dv.promote(db, "DATASET_T", by="owner", at=T0)
    db.execute("UPDATE audit.dataset_versions SET status = 'VALIDATED' WHERE name = 'DATASET_T'")
    (tmp_path / "frozen").write_text("data-truth audit in progress")
    with pytest.raises(ValueError, match="frozen"):
        dv.promote(db, "DATASET_T", by="owner", at=T0)
    (tmp_path / "frozen").unlink()
    dv.promote(db, "DATASET_T", by="owner", at=T0)
    assert dv.require_model_ready(db) == "DATASET_T"
