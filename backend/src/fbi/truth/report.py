"""The truth audit as a document a person reads: the matrix first, then the evidence."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

SEVERITIES = ("critical", "high", "medium", "low", "info")


def _cell(value: Any) -> str:
    text = "" if value is None else str(value)
    return text.replace("|", "\\|").replace("\n", " ")


def render_markdown(summary: dict[str, Any], findings: Sequence[dict[str, Any]]) -> str:
    lines = [
        f"# Data truth audit {summary['run_id']}",
        "",
        f"Started {summary['started_at']} · {summary['requests']} provider requests"
        + (f" · **stopped early: {summary['stopped']}**" if summary.get("stopped") else "")
        + (f" · {len(summary['failures'])} failed requests" if summary.get("failures") else ""),
        "",
        "## Matrix",
        "",
        "| Dataset | API | DB | Difference | Freshness | Model safe? |",
        "|---|---|---|---|---|---|",
    ]
    for row in summary["matrix"]:
        diff = row["difference"]
        if row["checked"]:
            diff = f"{row['matched']:,}/{row['checked']:,} agree; {diff}"
        lines.append(f"| {_cell(row['dataset'])} | {_cell(row['api'])} | {_cell(row['db'])} | {_cell(diff)} | "
                     f"{_cell(row['freshness'])} | {_cell(row['model_safe'])} |")
    lines += ["", "## Freshness (service levels)", "",
              "| Dataset | Status | Share | Rule |", "|---|---|---|---|"]
    for f in summary["freshness"]:
        lines.append(f"| {f['dataset']} | {f['status']} | {_cell(f['label'])} | {_cell(f['sla'])} |")
    gate = summary.get("gate") or {}
    if gate:
        lines += ["", f"## MODEL_DATA_GATE (upcoming {gate.get('horizon_hours')} h, {gate.get('fixtures')} fixtures)",
                  "", "| Model | Pass | Blocked | Blocked by |", "|---|---:|---:|---|"]
        for model, g in (gate.get("by_model") or {}).items():
            by = ", ".join(f"{k} {v}" for k, v in (g.get("blocked_by") or {}).items()) or "-"
            lines.append(f"| {model} | {g['pass']} | {g['blocked']} | {_cell(by)} |")
    lines += ["", "## Findings by dataset", ""]
    for name, d in summary["datasets"].items():
        if not d["findings"]:
            continue
        sev = ", ".join(f"{d['by_severity'][s]} {s}" for s in SEVERITIES if d["by_severity"].get(s))
        lines += [f"### {name}", "", f"{d['checked']:,} checked, {d['matched']:,} agree, {d['findings']:,} findings "
                  f"({sev}).", ""]
        lines += ["| Field | Kind | Severity | Count |", "|---|---|---|---:|"]
        for b in d["by_field"][:20]:
            lines.append(f"| {_cell(b['field'])} | {b['kind']} | {b['severity']} | {b['n']:,} |")
        examples = [f for f in findings if f["dataset"] == name][:12]
        if examples:
            lines += ["", "Examples:", ""]
            for f in examples:
                lines.append(f"* **{f['severity']}** {_cell(f['entity'])} · {f['field']} · {f['kind']}: "
                             f"API `{_cell(f['api'])}` / DB `{_cell(f['db'])}`" + (f" - {_cell(f['note'])}"
                                                                                 if f.get("note") else ""))
        if d.get("notes"):
            lines += ["", "Notes: " + "; ".join(_cell(n) for n in d["notes"][:10])]
        lines.append("")
    return "\n".join(lines) + "\n"
