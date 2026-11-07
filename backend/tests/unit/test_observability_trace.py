"""The trace of a selection (``fbi.observability.trace``, trace-v1), without a database: the identifiers, the rules of completeness, the
order of the spans, the compact payloads, and that the module only ever reads."""

from __future__ import annotations

import ast
import re
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from scripts import ia_trace

from fbi.ai.config import PRODUCTION_ENGINES, SHADOW_ENGINES
from fbi.observability import trace as t

ROOT = Path(__file__).resolve().parents[2]
NOW = datetime(2026, 11, 5, 15, tzinfo=UTC)


def span(kind: str, status: str = t.PRESENT, at: datetime | None = None, ids: tuple[str, ...] = ()) -> t.Span:
    return t.Span(kind, status, "x", ids, at)


def trace_with(spans: list[t.Span], scope: str = "selection") -> t.Trace:
    return t.Trace(t.VERSION, "fixture:1", scope, uuid.uuid4(), uuid.uuid4(), 1, "OU", "Over", "2.50", "core", t.order(spans))


# ── identifiers ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_namespace_is_the_one_written_down_and_is_derived_as_documented() -> None:
    assert uuid.uuid5(uuid.NAMESPACE_URL, "https://predigolai.com/observability/trace-v1") == t.NAMESPACE
    assert t.VERSION == "trace-v1"


def test_the_ids_are_stable_values_not_just_stable_within_a_run() -> None:
    """Pinned: a change of namespace or spelling changes these, and that is a new method version, not an edit."""
    assert str(t.match_trace_id(1001)) == str(uuid.uuid5(t.NAMESPACE, "match:1001"))
    assert str(t.selection_trace_id(1001, "OU", "Over", 2.5)) == str(uuid.uuid5(t.NAMESPACE, "selection:1001:OU:Over:2.50"))
    assert t.selection_trace_id(1001, "OU", "Over", 2.5) == t.selection_trace_id(1001, "OU", "Over", 2.5)


@pytest.mark.parametrize("line", [2.5, "2.5", "2.50", Decimal("2.500"), Decimal("2.5")])
def test_one_line_spelled_any_way_is_one_selection(line: Any) -> None:
    assert t.selection_trace_id(7, "OU", "Over", line) == t.selection_trace_id(7, "OU", "Over", Decimal("2.50"))


def test_zero_none_and_minus_zero_are_the_same_line() -> None:
    ids = {t.selection_trace_id(7, "1X2", "Home", x) for x in (0, None, "0", Decimal("-0.00"), 0.0)}
    assert len(ids) == 1
    assert t.spell_line(Decimal("-0.25")) == "-0.25" and t.spell_line(None) == "0.00"


def test_the_ids_are_distinct_across_every_part_of_the_key() -> None:
    base = (7, "OU", "Over", "2.5")
    variants = [base, (8, "OU", "Over", "2.5"), (7, "BTTS", "Over", "2.5"), (7, "OU", "Under", "2.5"), (7, "OU", "Over", "3.5"),
                (7, "ou", "Over", "2.5")]
    ids = {t.selection_trace_id(*v) for v in variants}
    assert len(ids) == len(variants)
    assert t.match_trace_id(7) not in ids and t.match_trace_id(7) != t.match_trace_id(8)


# ── completeness ────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("statuses", "expected"), [
    ([t.PRESENT], t.PRESENT),
    ([t.PRESENT, t.MISSING], t.MISSING),
    ([t.NOT_APPLICABLE, t.PRESENT], t.PRESENT),
    ([t.NOT_APPLICABLE], t.NOT_APPLICABLE),
    ([t.NOT_APPLICABLE, t.NOT_APPLICABLE], t.NOT_APPLICABLE),
    ([], t.MISSING),
    ([t.NOT_READ], t.MISSING),
])
def test_the_status_of_a_kind(statuses: list[str], expected: str) -> None:
    assert t.kind_status(span("evidence", s) for s in statuses) == expected


def full() -> list[t.Span]:
    return [span(k) for k in t.MANDATORY]


def test_a_trace_with_every_mandatory_span_is_complete_and_optional_spans_do_not_matter() -> None:
    spans = [*full(), span("agent_run", t.MISSING), span("cycle", t.NOT_READ), span("match_postmortem", t.MISSING)]
    c = t.completeness(trace_with(spans))
    assert c.complete and c.missing == () and set(c.present) == set(t.MANDATORY)


def test_not_applicable_counts_as_complete_but_is_said() -> None:
    spans = [s for s in full() if s.kind not in ("settlement", "outcome")]
    spans += [span("settlement", t.NOT_APPLICABLE), span("outcome", t.NOT_APPLICABLE)]
    c = t.completeness(trace_with(spans))
    assert c.complete and c.not_applicable == ("settlement", "outcome")


def test_one_missing_review_among_found_ones_makes_the_trace_incomplete() -> None:
    spans = [*full(), span("review", t.MISSING, ids=("99",))]
    c = t.completeness(trace_with(spans))
    assert not c.complete and c.missing == ("review",)


def test_the_post_mortem_is_due_only_once_settled_studied_and_after_a_step() -> None:
    step = NOW + timedelta(hours=5)
    assert t.postmortem_reason(final=True, step_at=step, studied=True) is None
    assert "no final result" in str(t.postmortem_reason(final=False, step_at=step, studied=True))
    assert "no post-mortem step" in str(t.postmortem_reason(final=True, step_at=None, studied=True))
    assert "not a selection the post-mortem studies" in str(t.postmortem_reason(final=True, step_at=step, studied=False))


def test_the_window_and_bounds_of_a_post_mortem_step_are_the_ones_study_uses() -> None:
    from fbi.intel import postmortem as pm

    kickoff = datetime(2026, 11, 5, 20, tzinfo=UTC)  # 15:00 in Bogotá, 5 Nov
    after, before = t.postmortem_window(kickoff)
    assert after == kickoff + pm.SETTLE_DELAY
    assert before == datetime(2026, 11, 6, 5, tzinfo=UTC) + pm.LOOKBACK, "until the start of the day after, Bogotá time, plus the look-back"
    since, until = t.study_bounds(kickoff, kickoff + timedelta(hours=4))
    assert since == datetime(2026, 11, 5, 5, tzinfo=UTC) and until == kickoff + timedelta(hours=4) - pm.SETTLE_DELAY
    assert t.study_bounds(kickoff, kickoff + timedelta(days=2))[1] == datetime(2026, 11, 6, 5, tzinfo=UTC), "the day whole once it is over"


def test_the_attribution_step_covers_its_day_and_the_day_before() -> None:
    kickoff = datetime(2026, 11, 5, 20, tzinfo=UTC)
    assert t.attribution_step_covers(kickoff, [datetime(2026, 11, 5, 23, tzinfo=UTC)])
    assert t.attribution_step_covers(kickoff, [datetime(2026, 11, 6, 12, tzinfo=UTC)])
    assert not t.attribution_step_covers(kickoff, [datetime(2026, 11, 7, 12, tzinfo=UTC)]), "two days later it attributes other days"
    assert not t.attribution_step_covers(kickoff, [])
    assert t.attribution_reason(postmortem=True, shadow_reviewed=True, step_covers=True) is None
    assert "no post-mortem" in str(t.attribution_reason(postmortem=False, shadow_reviewed=True, step_covers=True))
    assert "no shadow engine" in str(t.attribution_reason(postmortem=True, shadow_reviewed=False, step_covers=True))
    assert "has not run" in str(t.attribution_reason(postmortem=True, shadow_reviewed=True, step_covers=False))
    assert {"evidence", "postmortem", "attribution"} <= set(t.MANDATORY) and set(t.NOT_READ_SPANS) == {"cycle"}


def test_a_mandatory_kind_nobody_mentioned_is_missing() -> None:
    spans = [s for s in full() if s.kind != "price"]
    assert t.completeness(trace_with(spans)).missing == ("price",)


def test_the_match_scope_asks_less_and_an_unknown_scope_is_refused() -> None:
    c = t.completeness(trace_with([span("fixture"), span("data_quality")], scope="match"))
    assert c.complete and c.required == t.MANDATORY_MATCH
    with pytest.raises(ValueError):
        t.required_kinds("league")


def test_the_spans_not_read_are_not_mandatory_and_say_why() -> None:
    assert not set(t.NOT_READ_SPANS) & set(t.MANDATORY)
    assert set(t.MANDATORY) <= set(t.STAGES) and set(t.NOT_READ_SPANS) <= set(t.STAGES)
    for source, why in t.NOT_READ_SPANS.values():
        assert source and len(why.split()) >= 8


@pytest.mark.parametrize(("status", "expected"), [("finished", True), ("scheduled", False), ("live", False), ("cancelled", False),
                                                  ("postponed", False), (None, False)])
def test_a_settlement_is_expected_once_the_match_is_finished(status: str | None, expected: bool) -> None:
    assert t.settlement_expected(status) is expected


@pytest.mark.parametrize(("result", "expected"), [("win", True), ("void", True), ("half_loss", True), ("pending", False), (None, False)])
def test_an_outcome_is_expected_once_the_pick_has_a_final_result(result: str | None, expected: bool) -> None:
    assert t.outcome_expected(result) is expected


# ── order and payloads ──────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_spans_are_in_pipeline_order_then_by_time_with_timeless_ones_last() -> None:
    spans = [span("settlement", at=NOW), span("decision", at=NOW), span("decision", at=NOW - timedelta(hours=3)), span("fixture"),
             span("decision"), span("price", at=NOW)]
    ordered = t.order(spans)
    assert [s.kind for s in ordered] == ["fixture", "price", "decision", "decision", "decision", "settlement"]
    decisions = [s.at for s in ordered if s.kind == "decision"]
    assert decisions == [NOW - timedelta(hours=3), NOW, None]


def test_payloads_are_json_ready_and_long_texts_are_cut() -> None:
    value = t.plain({"p": Decimal("0.5123"), "at": NOW, "why": "x" * 500, "ids": (1, 2), "nested": {"d": Decimal(2)}})
    assert value["p"] == 0.5123 and value["at"] == NOW.isoformat() and len(value["why"]) == t.TEXT_CUT and value["ids"] == [1, 2]
    assert value["nested"] == {"d": 2.0}


def test_the_filters_keep_their_verdict_and_why_and_drop_their_data() -> None:
    filters = [{"n": 1, "key": "data", "ok": True, "why": "datos MODEL_READY", "data": {"big": [1] * 50}},
               {"n": 5, "key": "ev", "ok": False, "why": "EV 1 %", "effect": "RECHAZADO"}, "not a filter"]
    assert t.compact_filters(filters) == [{"n": 1, "key": "data", "ok": True, "why": "datos MODEL_READY"},
                                          {"n": 5, "key": "ev", "ok": False, "effect": "RECHAZADO", "why": "EV 1 %"}]
    assert t.compact_filters(None) == []


def test_the_coverage_of_a_population() -> None:
    complete = trace_with(full())
    lacking = trace_with([s for s in full() if s.kind not in ("price", "review")])
    lacking_price = trace_with([s for s in full() if s.kind != "price"])
    unit = t.unit_of("selections", [complete, lacking, lacking_price])
    assert (unit.total, unit.complete) == (3, 1) and unit.share == pytest.approx(1 / 3)
    assert unit.missing == (("price", 2), ("review", 1))
    assert set(unit.incomplete) == {str(lacking.trace_id), str(lacking_price.trace_id)}
    assert t.unit_of("published", []).share is None, "zero of zero is not 100 %"


def test_a_trace_serialises_with_its_completeness() -> None:
    doc = trace_with(full()).as_json()
    assert doc["version"] == "trace-v1" and doc["completeness"]["complete"] is True and len(doc["spans"]) == len(t.MANDATORY)


# ── what the module reads, and that it only reads ───────────────────────────────────────────────────────────────────────────────────────

def sql_constants() -> dict[str, str]:
    return {k: v for k, v in vars(t).items() if k.endswith("_SQL") and isinstance(v, str)}


def test_every_statement_is_a_select() -> None:
    writes = re.compile(r"\b(INSERT\s+INTO|UPDATE\s+[\w.]+\s+SET|DELETE\s+FROM|TRUNCATE|ALTER|DROP|CREATE|GRANT|COPY)\b", re.IGNORECASE)
    for name, sql in sql_constants().items():
        assert sql.lstrip().upper().startswith("SELECT"), name
        assert not writes.search(sql), name
    for path in (ROOT / "src/fbi/observability/trace.py", ROOT / "scripts/ia_trace.py"):
        source = path.read_text(encoding="utf-8")
        assert ".commit(" not in source and "Jsonb" not in source, path


def test_the_engines_named_are_the_engines_of_the_config() -> None:
    assert frozenset(PRODUCTION_ENGINES) == t.PRODUCTION_ENGINE_NAMES and frozenset(SHADOW_ENGINES) == t.SHADOW_ENGINE_NAMES
    names = lambda sql: set(re.findall(r"'([^']+)'", sql.split("r.engine IN", 1)[1]))  # noqa: E731
    assert names(t.PRODUCTION_REVIEWS_SQL) == t.PRODUCTION_ENGINE_NAMES
    assert names(t.SHADOW_REVIEWS_SQL) == t.SHADOW_ENGINE_NAMES


def test_nothing_that_decides_imports_the_trace() -> None:
    """The trace observes production; production must not come to depend on it."""
    importers = []
    readers = {
        "src/fbi/narrator/job.py",  # the Narrator (narrator-v1, IA-017) explains a pick AFTER its decision from its trace; it decides nothing
    }
    for path in (ROOT / "src/fbi").rglob("*.py"):
        if "observability" in path.parts or str(path.relative_to(ROOT)) in readers:
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if (isinstance(node, ast.ImportFrom) and node.module and node.module.startswith("fbi.observability")) or (isinstance(node, ast.Import) and any(a.name.startswith("fbi.observability") for a in node.names)):
                importers.append(str(path))
    assert importers == []


# ── the command ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("argv", [["show"], ["show", "--pick", "1", "--decision", "2"], ["show", "--fixture", "1", "--market", "OU"],
                                  ["show", "--fixture", "1", "--line", "2.5"], ["coverage"], ["coverage", "--day", "5 Nov"]])
def test_the_command_refuses_what_it_cannot_answer_before_reading_anything(argv: list[str]) -> None:
    args = ia_trace.build_parser().parse_args(argv)
    out, code = ia_trace.run(args, conn=None)  # type: ignore[arg-type]
    assert code == ia_trace.CANNOT and isinstance(out, dict) and "error" in out


def test_the_rendering_marks_the_missing_spans() -> None:
    text = ia_trace.render(trace_with([*full(), span("review", t.MISSING, ids=("99",))]))
    assert "INCOMPLETE" in text and "missing review" in text and "! review" in text
