"""The Admin Console's review listing knows the shadow engines of plan IA phase 3 and keeps every production figure where it was.

Phase 3 writes rows of ``ai.pick_reviews`` with the engines ``ma-v1`` (MULTIAGENTE), ``ma-v1-h`` (MULTIAGENTE + COUNCIL HAIKU) and ``cs-v1``
(COUNCIL SOLO). They never reach the decision layer or a user, but the owner reads them in the Console, and ``GET /admin/ai/reviews`` used to
validate ``engine`` against a closed list of three: the day the shadow started, asking for one of them would have been a 422. This file keeps, with no
database:

* the router accepts exactly the six engines (production's three and the three of the shadow), defaults to ``combined`` and refuses anything else
  before the service is called;
* the service passes the engine through to an exact match in SQL, so a shadow row never shows in a production listing, and the detail of a shadow
  review opens whatever its output keeps under ``engines``;
* every statement under ``src/fbi/api`` that reads ``ai.pick_reviews`` names an engine or reads by id, so no figure of the Console counts a shadow row
  by accident (a code scan, in the manner of ``test_typed_evidence_guard.py``);
* the AI layer cannot write an engine the API would refuse to list.
"""

from __future__ import annotations

import ast
import functools
import inspect
import re
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, get_args, get_type_hints

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from fbi.ai import shadow
from fbi.ai.review import EngineResult
from fbi.api.contracts.ai_layer import ReviewDetail, ReviewRow
from fbi.api.deps import get_db
from fbi.api.envelope import Envelope, listing
from fbi.api.routers import ai_layer as router
from fbi.api.services import ai_layer as service

PRODUCTION = ("rules", "llm", "combined")
SHADOW = ("ma-v1", "ma-v1-h", "cs-v1")
BACKEND = Path(__file__).resolve().parents[2]
API_SOURCES = sorted((BACKEND / "src" / "fbi" / "api").rglob("*.py"))
BASE = "/api/v1/admin"
NO_DB: Any = None
"""The services under test reach the database only through ``fetch_one``/``fetch_all``, which these tests replace."""


# ── the router ───────────────────────────────────────────────────────────────────────────────────────────────────────

def review(i: int = 1, engine: str = "combined", **over: Any) -> dict[str, Any]:
    """A row as ``REVIEWS_SQL`` returns it."""
    return {"id": i, "reviewed_at": datetime(2026, 11, 3, 15, 0, tzinfo=UTC), "fixture_id": 77, "match": "Alpha - Beta",
            "kickoff_at": datetime(2026, 11, 3, 20, 0, tzinfo=UTC), "competition": "Liga", "market_key": "1x2", "selection": "home",
            "line": Decimal("0.00"), "odds": Decimal("2.100"), "p_model": Decimal("0.520000"), "p_market": Decimal("0.470000"),
            "edge": Decimal("0.050000"), "decision": "APPROVE", "confidence": Decimal("0.700"), "engine": engine,
            "engine_version": f"{engine}-v1", "model": None, "reason": "price above the fair one", "status": "ok", "mode": "shadow",
            "cost_usd": Decimal("0.000000")} | over


class Calls:
    """What the route handed to the service: nothing, when the route refused the request first."""

    def __init__(self) -> None:
        self.seen: list[dict[str, Any]] = []


@pytest.fixture()
def api(monkeypatch: pytest.MonkeyPatch) -> tuple[TestClient, Calls]:
    """``/admin/ai/reviews`` and its sisters without the database or the sign-in: the service is replaced by one that records what it was asked."""
    calls = Calls()

    def fake_reviews(conn: Any, **kw: Any) -> Envelope[list[ReviewRow]]:
        calls.seen.append(kw)
        return listing([ReviewRow.model_validate(review(1, kw["engine"]))], empty_reason="no_reviews")

    monkeypatch.setattr(service, "reviews", fake_reviews)  # the router calls it as ``ai_layer.reviews``
    app = FastAPI()
    app.include_router(router.admin_router, prefix=BASE)
    app.dependency_overrides[get_db] = lambda: None
    return TestClient(app), calls


def test_the_router_lists_the_three_production_engines_and_the_three_of_the_shadow_in_that_order() -> None:
    assert get_args(router.Engine) == (*PRODUCTION, *SHADOW)


def test_the_listing_still_defaults_to_the_combined_review() -> None:
    assert inspect.signature(router.get_reviews).parameters["engine"].default == "combined"


@pytest.mark.parametrize("engine", [*PRODUCTION, *SHADOW])
def test_every_engine_can_be_asked_for_and_reaches_the_service_unchanged(api: tuple[TestClient, Calls], engine: str) -> None:
    client, calls = api
    answer = client.get(f"{BASE}/ai/reviews", params={"engine": engine, "day": "2026-11-03"})
    assert answer.status_code == 200, answer.text
    assert [c["engine"] for c in calls.seen] == [engine]
    assert [row["engine"] for row in answer.json()["data"]] == [engine]


def test_without_an_engine_the_listing_is_the_combined_one_as_before(api: tuple[TestClient, Calls]) -> None:
    client, calls = api
    assert client.get(f"{BASE}/ai/reviews").status_code == 200
    assert [c["engine"] for c in calls.seen] == ["combined"]


@pytest.mark.parametrize("engine", ["magic", "MA-V1", "ma_v1", "ma-v2", "cs-v1-h", "council", "multiagent", "", " ma-v1",
                                    "combined,ma-v1", "all", "*", "ma-v1'; DROP TABLE ai.pick_reviews; --"])
def test_any_other_engine_is_refused_before_the_service_is_called(api: tuple[TestClient, Calls], engine: str) -> None:
    client, calls = api
    answer = client.get(f"{BASE}/ai/reviews", params={"engine": engine})
    assert answer.status_code == 422
    assert calls.seen == []


def test_the_open_api_document_names_the_six_engines_and_the_default(api: tuple[TestClient, Calls]) -> None:
    client, _ = api
    spec = client.get("/openapi.json").json()
    parameter = next(p for p in spec["paths"][f"{BASE}/ai/reviews"]["get"]["parameters"] if p["name"] == "engine")
    assert parameter["schema"]["enum"] == [*PRODUCTION, *SHADOW]
    assert parameter["schema"]["default"] == "combined"


def test_the_engine_of_a_row_is_a_free_text_in_the_contract_so_an_engine_it_does_not_know_never_breaks_a_listing() -> None:
    for engine in (*PRODUCTION, *SHADOW, "an-engine-of-the-future"):
        row = ReviewRow.model_validate(review(engine=engine))
        assert row.engine == engine and row.model_dump(mode="json")["engine"] == engine


def test_a_shadow_row_serializes_with_the_same_fields_as_a_production_one() -> None:
    production = ReviewRow.model_validate(review(engine="combined")).model_dump(mode="json")
    for engine in SHADOW:
        shadowed = ReviewRow.model_validate(review(engine=engine)).model_dump(mode="json")
        assert list(shadowed) == list(production)
        assert {k for k in shadowed if shadowed[k] != production[k]} == {"engine", "engine_version"}


def test_every_engine_the_ai_layer_can_write_can_be_listed_by_the_api() -> None:
    """The day ``fbi.ai`` writes an engine this list lacks, this test fails instead of the Console."""
    listed = set(get_args(router.Engine))
    assert set(get_args(get_type_hints(EngineResult)["engine"])) <= listed
    assert set(shadow.ENGINES) <= listed


# ── the service ──────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_listing_asks_the_database_for_one_engine_exactly(monkeypatch: pytest.MonkeyPatch) -> None:
    asked: list[tuple[str, dict[str, Any]]] = []

    def fetch_all(conn: Any, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        asked.append((sql, params or {}))
        return [review(7, str((params or {})["engine"]))]

    monkeypatch.setattr(service, "fetch_all", fetch_all)
    for engine in (*PRODUCTION, *SHADOW):
        answer = service.reviews(NO_DB, day=date(2026, 11, 3), engine=engine, decision=None, fixture_id=None, limit=50)
        assert [r.engine for r in answer.data] == [engine]
    assert all(sql is service.REVIEWS_SQL for sql, _ in asked)
    assert [p["engine"] for _, p in asked] == [*PRODUCTION, *SHADOW]
    assert re.search(r"\br\.engine\s*=\s*%\(engine\)s", service.REVIEWS_SQL), "an exact match: never LIKE, IN or NOT IN"


def reports() -> list[dict[str, Any]]:
    """What ``fbi.ai.shadow.latest`` returns: the newest evaluation of each engine."""
    day = date(2026, 11, 1)
    return [{"engine": e, "created_at": datetime(2026, 11, 2, 7, 35, tzinfo=UTC), "window_from": day, "window_to": day,
             "arms": {"model": {"n": 10 + i}}, "gate": {"verdict": "insufficient", "checks": {"selections": {"ok": False}}},
             "version": "ai-gate-v2"} for i, e in enumerate((*PRODUCTION, *SHADOW))]


def test_the_shadow_report_lists_the_shadow_engines_beside_the_production_ones_without_touching_them(monkeypatch: pytest.MonkeyPatch) -> None:
    both = reports()
    monkeypatch.setattr(shadow, "latest", lambda conn: both)
    with_shadow = service.shadow_reports(NO_DB).data
    monkeypatch.setattr(shadow, "latest", lambda conn: [r for r in both if r["engine"] in PRODUCTION])
    without = service.shadow_reports(NO_DB).data
    assert [r["engine"] for r in with_shadow] == [*PRODUCTION, *SHADOW]
    assert with_shadow[: len(PRODUCTION)] == without


class Scripted:
    """The statements of ``review_detail`` answered from dicts: no database."""

    def __init__(self, outputs: dict[int, dict[str, Any]], usage: dict[int, list[int]] | None = None) -> None:
        self.outputs = outputs
        self.usage = usage or {}
        self.asked: list[int] = []

    def engine_of(self, i: int) -> str:
        return {1: "ma-v1", 2: "cs-v1", 3: "combined", 11: "rules", 12: "llm"}.get(i, "combined")

    def fetch_one(self, conn: Any, sql: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
        i = int((params or {})["id"])
        if "SELECT r.id, r.reviewed_at" in sql:
            self.asked.append(i)
            return review(i, self.engine_of(i)) if i in self.outputs else None
        if sql.startswith("SELECT output, sources, evidence_ids"):
            return {"output": self.outputs[i], "sources": [], "evidence_ids": [], "packet_id": None,
                    "usage_ids": self.usage.get(i, []), "input_hash": f"hash-{i}"}
        if sql.startswith("SELECT usage_ids FROM ai.pick_reviews"):
            return {"usage_ids": self.usage.get(i, [])}
        raise AssertionError(sql)

    def fetch_all(self, conn: Any, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        if "FROM ai.evidence" in sql:
            return []
        if "FROM ai.usage" in sql:
            ids = (params or {})["ids"]
            return [{"id": u, "at": datetime(2026, 11, 3, 15, 1, tzinfo=UTC), "purpose": "pick_review", "tier": "analysis",
                     "provider": "anthropic", "model": "claude-haiku-5-5", "prompt_version": "review-v2", "input_tokens": 100,
                     "output_tokens": 20, "cached_tokens": 0, "searches": 0, "cost_usd": Decimal("0.001"), "latency_ms": 800,
                     "status": "ok", "error": None} for u in ids]
        raise AssertionError(sql)

    def install(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(service, "fetch_one", self.fetch_one)
        monkeypatch.setattr(service, "fetch_all", self.fetch_all)


ODD_ENGINES = [
    {"engines": ["match", "council"]},
    {"engines": [{"agent": "council", "decision": "APPROVE"}, {"review_id": None}, {"review_id": 0}, {"review_id": "x"},
                 {"review_id": True}, {"review_id": 2.5}, {"review_id": [4]}, None, 7, "ma-v1"]},
    {"engines": {"match": 5, "council": 6}},
    {"engines": None},
    {"engines": "none"},
    {"engines": 5},
    {},
]


@pytest.mark.parametrize("output", ODD_ENGINES)
def test_the_detail_of_a_shadow_review_opens_whatever_its_output_keeps_under_engines(
        monkeypatch: pytest.MonkeyPatch, output: dict[str, Any]) -> None:
    script = Scripted({1: {"reason": "x", "confidence": "MEDIUM"} | output})
    script.install(monkeypatch)
    detail = service.review_detail(NO_DB, 1).data
    assert isinstance(detail, ReviewDetail)
    assert detail.review.engine == "ma-v1" and detail.components == [] and detail.input_hash == "hash-1"
    assert script.asked == [1], "no component was looked up"


def test_the_detail_of_a_combined_review_still_lists_its_components_and_their_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    combined = {"reason": "both agree", "engines": [{"engine": "rules", "decision": "APPROVE", "review_id": 11, "status": "ok"},
                                                    {"engine": "llm", "decision": "APPROVE", "review_id": "12", "status": "ok"},
                                                    {"engine": "llm", "decision": "ABSTAIN", "review_id": None, "status": "failed"}]}
    script = Scripted({3: combined, 11: {}, 12: {}}, usage={3: [30], 11: [], 12: [21, 30]})
    script.install(monkeypatch)
    detail = service.review_detail(NO_DB, 3).data
    assert [c.engine for c in detail.components] == ["rules", "llm"] and [c.id for c in detail.components] == [11, 12]
    assert [u.id for u in detail.usage] == [21, 30], "the calls of the components too, once each, in order"
    assert detail.review.engine == "combined"


def test_a_review_that_does_not_exist_is_a_404_whatever_its_engine(monkeypatch: pytest.MonkeyPatch) -> None:
    from fbi.api.errors import ApiError

    Scripted({}).install(monkeypatch)
    with pytest.raises(ApiError) as caught:
        service.review_detail(NO_DB, 99)
    assert caught.value.status == 404


@pytest.mark.parametrize(("output", "ids"), [
    ({"engines": [{"review_id": 5}, {"review_id": 9}]}, [5, 9]),
    ({"engines": [{"review_id": "7"}, {"review_id": 8}]}, [7, 8]),
    ({"engines": [{"review_id": None}, {"review_id": 0}, {"review_id": ""}, {"review_id": "x"}, {"review_id": True}]}, []),
    ({"engines": [{"review_id": 2.5}, {"review_id": [4]}, {"review_id": {"id": 4}}, "11", 11, None, ["review_id"]]}, []),
    ({"engines": []}, []),
    ({"engines": {"review_id": 5}}, []),
    ({"engines": None}, []),
    ({}, []),
])
def test_component_ids_keeps_only_the_entries_that_carry_an_id(output: dict[str, Any], ids: list[int]) -> None:
    assert service.component_ids(output) == ids


# ── the code: no reader of the reviews counts a shadow row by accident ──────────────────────────────────────────────────

READS = re.compile(r"\b(?:FROM|JOIN)\s+ai\.pick_reviews\b", re.IGNORECASE)
"""A statement reads the table when it names it after FROM or JOIN (a write says INSERT INTO)."""
ENGINES = "|".join(re.escape(e) for e in (*PRODUCTION, *SHADOW))
NAMES_AN_ENGINE = re.compile(rf"\bengine\s*(?:=\s*(?:'(?:{ENGINES})'|%\(engine\)s)|IN\s*\(\s*'(?:{ENGINES})'(?:\s*,\s*'(?:{ENGINES})')*\s*\))",
                             re.IGNORECASE)
"""``engine = 'combined'``, ``engine IN ('combined', 'rules')`` or ``engine = %(engine)s`` (the listing: its value is the router's ``Engine``)."""
BY_ID = re.compile(r"\bid\s*=\s*(?:%\(\w+\)s|ANY\(\s*%\(\w+\)s\s*\))", re.IGNORECASE)
"""A lookup of the reviews something else already pointed at (``WHERE id = %(id)s``, ``r.id = ANY(%(ids)s)``): it returns what was asked for."""


class Strings(ast.NodeVisitor):
    """Every string of a module that could be SQL: a constant, or an f-string as one text (its constant parts together)."""

    def __init__(self) -> None:
        self.found: list[tuple[int, str]] = []

    def visit_Constant(self, node: ast.Constant) -> None:
        if isinstance(node.value, str):
            self.found.append((node.lineno, node.value))

    def visit_JoinedStr(self, node: ast.JoinedStr) -> None:
        self.found.append((node.lineno, "".join(v.value for v in node.values if isinstance(v, ast.Constant) and isinstance(v.value, str))))
        for part in node.values:
            if isinstance(part, ast.FormattedValue):
                self.visit(part.value)


def readings(text: str) -> list[str]:
    """The part of a statement that belongs to each read of the table: from its ``FROM``/``JOIN`` up to the next read (or the end)."""
    starts = [m.start() for m in READS.finditer(text)]
    ends = [*starts[1:], len(text)]
    return [text[a:b] for a, b in zip(starts, ends, strict=False)]


def unguarded(text: str) -> list[str]:
    """The reads of a statement that neither name an engine nor look a review up by its id."""
    return [r for r in readings(text) if not NAMES_AN_ENGINE.search(r) and not BY_ID.search(r)]


@functools.cache
def statements() -> list[tuple[str, int, str]]:
    found: list[tuple[str, int, str]] = []
    for path in API_SOURCES:
        visitor = Strings()
        visitor.visit(ast.parse(path.read_text()))
        found += [(str(path.relative_to(BACKEND)), line, text) for line, text in visitor.found if READS.search(text)]
    return found


def test_the_guard_tells_a_read_that_counts_every_engine_from_one_that_names_its_own() -> None:
    assert unguarded("SELECT count(*) FROM ai.pick_reviews WHERE reviewed_at >= %(since)s")
    assert unguarded("SELECT 1 FROM ai.pick_reviews r JOIN core.fixtures f ON f.id = r.fixture_id WHERE r.fixture_id = %(fixture)s")
    assert unguarded("SELECT 1 FROM ai.pick_reviews WHERE engine <> 'combined'"), "a negation counts the shadow engines"
    assert unguarded("SELECT 1 FROM ai.pick_reviews WHERE engine NOT IN ('rules', 'llm')"), "the same"
    assert unguarded("SELECT 1 FROM ai.pick_reviews WHERE engine LIKE 'ma%'")
    assert unguarded("SELECT 1 FROM ai.pick_reviews WHERE engine = 'a-new-engine'"), "an engine the guard does not know"
    assert not unguarded("SELECT 1 FROM ai.pick_reviews WHERE engine = 'combined' AND reviewed_at >= %(since)s")
    assert not unguarded("SELECT 1 FROM ai.pick_reviews r WHERE r.engine = 'ma-v1'"), "a reader of a shadow engine names it on purpose"
    assert not unguarded("SELECT 1 FROM ai.pick_reviews r WHERE r.engine = %(engine)s")
    assert not unguarded("SELECT 1 FROM ai.pick_reviews WHERE engine IN ('combined', 'rules')")
    assert not unguarded("SELECT output FROM ai.pick_reviews WHERE id = %(id)s")
    assert not unguarded("SELECT id, output FROM ai.pick_reviews WHERE id = ANY(%(ids)s)")
    assert not unguarded("INSERT INTO ai.pick_reviews (engine) VALUES ('combined')"), "writing is not reading"
    two = ("SELECT (SELECT count(*) FROM ai.pick_reviews WHERE engine = 'combined') AS a, "
           "(SELECT count(*) FROM ai.pick_reviews WHERE reviewed_at > %(at)s) AS b")
    assert len(readings(two)) == 2 and len(unguarded(two)) == 1, "the engine of the first read does not cover the second"
    assert unguarded("SELECT 1 FROM ai.pick_reviews WHERE fixture_id = %(fixture)s"), "``fixture_id = ...`` is not a lookup by id"


def test_the_guard_reads_a_good_part_of_the_api() -> None:
    found = statements()
    files = {f for f, _, _ in found}
    assert sum(len(readings(t)) for _, _, t in found) >= 15, "the scan finds the readers of the table (a regex that matches nothing guards nothing)"
    assert {"src/fbi/api/services/ai_layer.py", "src/fbi/api/services/ai_v2.py", "src/fbi/api/services/records.py",
            "src/fbi/api/services/match_memory.py", "src/fbi/api/services/intelligence.py"} <= files


def test_every_statement_of_the_api_that_reads_the_reviews_names_an_engine_or_looks_a_review_up_by_its_id() -> None:
    bad = [f"{file}:{line}: {' '.join(part.split())[:160]}" for file, line, text in statements() for part in unguarded(text)]
    assert bad == [], "these statements of the API read ai.pick_reviews without naming an engine (a shadow row would count in them):\n" + "\n".join(bad)


SHADOW_READERS: dict[str, str] = {
    "src/fbi/api/services/ai_shadow.py": "the Console's views of the shadow of phase 3 (the arms, the contradictions, the file of a match): they read the shadow "
    "engines by name on purpose, never in the same statement as a production engine, and count only the shadow's own rows",
}
"""The files of the API that read a shadow engine on purpose, with the reason. Besides them, the Console reads the shadow rows only through the listing,
by the name the owner asks for, and through the detail of one review, by its id."""


def test_no_figure_of_the_api_counts_a_shadow_engine_and_only_the_listing_takes_its_engine_from_the_caller() -> None:
    for file, _line, text in statements():
        for part in readings(text):
            named = {m.group(1) for m in re.finditer(rf"\bengine\s*=\s*'({ENGINES})'", part, re.IGNORECASE)}
            assert not (named & set(SHADOW)) or file in SHADOW_READERS, f"{file} reads a shadow engine for a figure: {part[:120]!r}"
            if "%(engine)s" in part:
                assert file == "src/fbi/api/services/ai_layer.py" and "r.engine = %(engine)s" in part, f"{file}: an engine from the caller outside the listing"
