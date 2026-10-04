"""Every entry point that trains or stores a model asks for a MODEL_READY dataset first (fbi.datasets.versions)."""

from __future__ import annotations

from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def test_training_entry_points_require_a_model_ready_dataset() -> None:
    for name in ("research_v2.py", "run_backtest.py"):
        text = (SCRIPTS / name).read_text(encoding="utf-8")
        guard = text.index("require_model_ready(")
        assert "DatasetNotModelReadyError" in text, name
        store = text.index("record_v2(" if name == "research_v2.py" else "ledger.open(\"backtest\"")
        assert guard < store, f"{name}: the guard must come before anything is stored"
