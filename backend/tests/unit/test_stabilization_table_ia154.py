"""IA-154 (PM-10-08): the stabilisation table measured in the LAB is informative only - nothing reads it, it carries its protocol
and its export, and it never proposes a minimum below the one in force."""

from __future__ import annotations

import ast
import json
from pathlib import Path

from fbi.research import protocol
from fbi.stats import team

BACKEND = Path(__file__).resolve().parents[2]
TABLE = BACKEND / "src" / "fbi" / "stats" / "stabilization_v1.json"


def test_the_table_carries_its_protocol_and_its_export() -> None:
    doc = json.loads(TABLE.read_text(encoding="utf-8"))
    assert doc["version"] == "stabilization-v1"
    assert doc["protocol"] == protocol.stamp("PM-10-08")
    assert doc["export"]["version"] == "lab-export-v2" and doc["export"]["folder"] == "20261121T050132Z"


def test_it_never_proposes_less_than_the_minimum_in_force() -> None:
    doc = json.loads(TABLE.read_text(encoding="utf-8"))
    assert doc["current_min_matches"] == team.MIN_MATCHES
    for name, row in doc["stats"].items():
        assert row["verdict"] in ("PASA", "NO PASA", "INSUFICIENTE"), name
        if row["verdict"] == "PASA" and "n50" in row:
            assert row["proposed_min_matches"] >= team.MIN_MATCHES and row["n70"] >= row["n50"], name
        else:
            assert "proposed_min_matches" not in row, name


def test_nothing_in_the_code_reads_it() -> None:
    for path in (BACKEND / "src" / "fbi").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "stabilization_v1" not in text, path
        ast.parse(text)
