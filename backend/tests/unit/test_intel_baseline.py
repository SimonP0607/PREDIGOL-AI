"""RP-0.1: the frozen baseline of 22 indicators is built from a run, hashed, and repeatable."""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts.intel_baseline_report import (
    INDICATORS,
    LIVE_SECTIONS,
    build,
    repeatable,
    section_hash,
    split_sections,
    summarize_latency,
)

SQL = Path(__file__).resolve().parents[2] / "scripts" / "intel_baseline.sql"


def _run(extra: str = "", *, drop: str | None = None, count: str = "5") -> str:
    parts = ["### run\nstarted_utc,host\n2026-11-26T03:10:03Z,h",
             "### meta\ncut_utc,migration\n2026-11-26 03:30:00,0177"]
    for name in sorted({s for _, _, s in INDICATORS if s != "i22_latency"}):
        if name != drop:
            parts.append(f"### {name}\nn\n{count}")
    parts.append("### i20b_jobs_outside_ledger_live\njobs\n46")
    return "\n".join(parts) + extra + "\n"


def test_sql_has_a_section_for_every_indicator_and_only_reads() -> None:
    text = SQL.read_text()
    for _, _, section in INDICATORS:
        assert f"\\echo ### {section}" in text, section
    body = "\n".join(line for line in text.splitlines() if not line.lstrip().startswith("--"))
    for word in ("INSERT ", "UPDATE ", "DELETE ", "DROP ", "ALTER ", "CREATE ", "TRUNCATE "):
        assert word not in body.upper(), word
    assert "BEGIN READ ONLY" in text and text.rstrip().endswith("ROLLBACK;")


def test_every_figure_is_bounded_by_the_cut() -> None:
    text = SQL.read_text()
    assert text.count(":cut::timestamptz") >= 40
    assert "now()" in text and text.count("now()") == 1  # only the live heartbeat window


def test_sections_are_split_and_psql_noise_dropped() -> None:
    got = split_sections("BEGIN\nSET\n### a\nx,y\n1,2\nNull display is \"\".\n### b\nz\n9\nROLLBACK\n")
    assert got == {"a": "x,y\n1,2", "b": "z\n9"}


def test_build_hashes_every_section_and_marks_live_ones() -> None:
    doc = build(_run(), code_version="abc")
    assert doc["definition_version"] == "intel-baseline-v1"
    assert len(doc["indicators"]) == 22
    assert doc["sections"]["i07_close_minutes"]["sha256"] == section_hash("n\n5")
    assert doc["sections"]["i20b_jobs_outside_ledger_live"]["live"] is True
    assert {name for name, s in doc["sections"].items() if s["live"] and name != "i22_latency"} <= LIVE_SECTIONS


def test_two_runs_with_the_same_cut_have_the_same_hash_and_a_change_is_seen() -> None:
    first = build(_run(), code_version="abc")
    again = build(_run().replace("46", "47"), code_version="abc")  # only the live section moved
    assert repeatable(first, again) == []
    changed = build(_run(count="6"), code_version="abc")
    assert "i07_close_minutes" in repeatable(first, changed)


def test_a_missing_section_or_a_psql_error_does_not_freeze_a_baseline() -> None:
    with pytest.raises(ValueError, match="missing"):
        build(_run(drop="i13_complete_texts"), code_version="abc")
    with pytest.raises(ValueError, match="ERROR"):
        build(_run("ERROR:  relation does not exist\n"), code_version="abc")


def test_latency_summary_uses_the_intelligence_and_ops_routes() -> None:
    manifest = {"timings_ms": {"intel__console": 400, "admin__ops__jobs": 100, "home": 9999, "intel__x": 200}}
    got = summarize_latency(manifest)
    assert got["routes"] == 3 and got["max_ms"] == 400 and got["slowest"][0] == "intel__console"
    assert summarize_latency({}) == {"routes": 0}


def test_the_committed_document_is_what_the_frozen_baseline_renders() -> None:
    """BASELINE.md is generated from baseline-v1.json: editing either by hand makes this fail."""
    import json
    from pathlib import Path

    from scripts.intel_baseline_report import render_markdown

    root = Path(__file__).resolve().parents[3] / "docs" / "intelligence"
    doc = json.loads((root / "baseline" / "baseline-v1.json").read_text())
    assert (root / "BASELINE.md").read_text(encoding="utf-8") == render_markdown(doc)
    assert len(doc["indicators"]) == 22
