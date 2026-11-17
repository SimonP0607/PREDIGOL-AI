"""C-06 «Noticia» (IA-121, AD-G07) and C-07 «Fuentes del análisis» (IA-122, AD-G08) as the server builds them, without a database.

The generic tests of every contract (``test_intelligence_contract_*.py``) already validate the examples, project them and look for leaks;
here, what is particular to these two:

* every example is exactly what the services' pure builders give (``tests/unit/news_contract_world.py``);
* the public projection never carries an author, a withheld source, the moderation queue, a story in moderation, a selection or the facts
  the validator refused; PrediGol's own text waits for a source that allows a summary; the image is a monogram;
* a fact known after its evaluation, or a rumour «used», cannot be a C-07 answer;
* the public routes are 404 while their switches are off, and the routes of BE-040 are still there;
* the two packages the API reads import nothing of ``fbi.ai``, ``fbi.news``, ``fbi.evalcycle`` or ``fbi.api``, and ``fbi.factlinks``
  writes only its two tables, with INSERT.
"""

from __future__ import annotations

import ast
import json
import re
from collections.abc import Iterator
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any, get_args

import pytest
from fastapi.testclient import TestClient

from fbi.api.contracts.intelligence.base import Freshness, Missing
from fbi.api.contracts.intelligence.projection import to_public
from fbi.api.contracts.intelligence.sources import AnalysisSources, AnalysisSourcesPrivate
from fbi.api.contracts.intelligence.stories import Category, News, NewsPrivate
from fbi.api.services import news_v2
from fbi.factlinks.views import ItemUse
from fbi.news import vocab as news_vocab
from tests.unit import news_contract_world as world

SRC = Path(__file__).resolve().parents[2] / "src" / "fbi"
EXAMPLES = world.EXAMPLES


def load(contract: str, case: str, projection: str) -> dict[str, Any]:
    data: dict[str, Any] = json.loads((EXAMPLES / contract / f"{case}.{projection}.json").read_text(encoding="utf-8"))
    return data


@pytest.mark.parametrize("case", sorted(world.c06_cases()))
def test_each_c06_example_is_what_the_builders_give(case: str) -> None:
    answer = world.c06_cases()[case]
    assert world.dumped(answer) == load("C-06", case, "private")
    assert world.dumped(to_public(answer, News)) == load("C-06", case, "public")


@pytest.mark.parametrize("case", sorted(world.c07_cases()))
def test_each_c07_example_is_what_the_builders_give(case: str) -> None:
    answer = world.c07_cases()[case]
    assert world.dumped(answer) == load("C-07", case, "private")
    assert world.dumped(to_public(answer, AnalysisSources)) == load("C-07", case, "public")


def walk(x: Any, path: str = "$") -> Iterator[tuple[str, Any]]:
    if isinstance(x, dict):
        for k, v in x.items():
            yield f"{path}.{k}", v
            yield from walk(v, f"{path}.{k}")
    elif isinstance(x, list):
        for v in x:
            yield from walk(v, f"{path}[]")


@pytest.mark.parametrize("case", sorted(world.c06_cases()))
def test_nothing_of_a_third_party_or_of_the_moderation_reaches_a_reader(case: str) -> None:
    public = load("C-06", case, "public")
    for path, value in walk(public):
        key = path.rsplit(".", 1)[-1]
        assert key not in {"queue", "withheld_sources", "own_text", "status", "publish_level", "author_seen", "analyses", "story_status",
                           "source_title", "title", "text", "body", "photo", "selection", "selection_id"}, path
        if key == "author":
            assert value == {"missing_reason": "pendiente_derechos"}, path
        if key == "image":
            assert value == {"kind": "monograma"}, path
    text = json.dumps(public, ensure_ascii=False)
    assert "en_moderacion" not in text and "st-ej-lesion-en-cola" not in text, "a story in the queue is in no public list"


def test_the_own_text_waits_for_a_source_that_allows_a_summary() -> None:
    b = world.convocatoria()
    withdrawn_rights = replace(b, publish={i.id: "link" for i in b.items})
    card = news_v2.card(withdrawn_rights, world.AT)
    public = to_public(NewsPrivate(freshness=Freshness(generated_at=world.AT, stale=False), view="portada",
                                   front=news_v2.front_of([withdrawn_rights], [], at=world.AT, followed=None, upcoming={}),
                                   story_status=news_v2.NO_DATA), News)
    assert card.headline_es == Missing(missing_reason="pendiente_derechos") and card.own_text.headline_es == b.story.headline_es
    assert public.front is not None
    lead = public.front.lead_story
    assert not isinstance(lead, Missing) and lead.headline_es == Missing(missing_reason="pendiente_derechos")
    nothing = replace(b, publish={i.id: "none" for i in b.items})
    assert not news_v2.public_ok(nothing), "a story none of whose sources may be shown is not shown at all"


def test_a_withdrawn_story_says_so_and_carries_nothing() -> None:
    assert load("C-06", "noticia_retirada", "public")["story"] == {"missing_reason": "retirado_por_derechos"}


def test_the_match_impact_is_public_only_for_a_published_analysis() -> None:
    uses = [ItemUse(11, world.FIXTURE, world.KICKOFF, "E2", 1, world.AT, "contexto", "J. Ejemplo", "player", "lineup",
                                "starts")]
    assert news_v2.impact_of(uses, {world.FIXTURE: False}, world.AT) == news_v2.NO_DATA
    shown = news_v2.impact_of(uses, {world.FIXTURE: True}, world.AT)
    assert not isinstance(shown, Missing) and shown.aspect_es == "J. Ejemplo: titular" and shown.analysis_published
    assert news_v2.impact_of(uses, {world.FIXTURE: True}, world.KICKOFF + timedelta(minutes=1)) == news_v2.NO_DATA, "a match played"


def test_c07_public_carries_no_selection_and_no_refused_fact() -> None:
    public = load("C-07", "publicada", "public")
    keys = {p.rsplit(".", 1)[-1] for p, _ in walk(public)}
    assert not keys & {"selections", "refused", "evaluations", "evidence_id", "named_as", "published_at_private", "rule_version"}
    assert [f["relation"] for f in public["facts"]["items"]] == ["en_contra", "contexto", "no_usada"]
    assert all(f["quote"] == {"missing_reason": "pendiente_derechos"} for f in public["facts"]["items"])
    assert public["summary"]["unused_rumours"] == 1


def test_c07_refuses_a_fact_known_after_its_evaluation_and_a_rumour_used() -> None:
    data = load("C-07", "publicada", "private")
    late = json.loads(json.dumps(data))
    late["facts"]["items"][0]["known_at"] = "2026-11-22T14:06:00Z"
    with pytest.raises(ValueError, match="known after the evaluation"):
        AnalysisSourcesPrivate.model_validate(late)
    used = json.loads(json.dumps(data))
    used["facts"]["items"][2]["relation"] = "a_favor"
    with pytest.raises(ValueError, match="a rumour is not used"):
        AnalysisSourcesPrivate.model_validate(used)


def test_the_fact_sentence_is_code_and_never_medical() -> None:
    from fbi.api.services.analysis_sources import fact_es

    assert fact_es("J. Ejemplo", "player", "injury", "out") == "J. Ejemplo: baja"
    assert fact_es("J. Ejemplo", "player", "suspension", "out") == "J. Ejemplo: sancionado"
    assert fact_es(None, "player", "injury", "doubtful") == "Un jugador: en duda"
    assert fact_es("Club Ejemplo Sur", "team", "weather", "info") == "Club Ejemplo Sur: clima"


def test_the_categories_are_the_news_store_s() -> None:
    assert get_args(Category) == news_vocab.CATEGORIES


def test_a_view_carries_its_body_and_nothing_else() -> None:
    data = load("C-06", "portada", "private")
    with pytest.raises(ValueError, match="carries front and nothing else"):
        NewsPrivate.model_validate({**data, "story": {"missing_reason": "retirado_por_derechos"}})


# ── the routes ───────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def reader() -> Iterator[TestClient]:
    from fbi.api.app import create_app
    from fbi.api.deps import get_db
    from fbi.api.security import current_principal
    from fbi.auth.roles import Permission, Role
    from fbi.auth.service import Principal

    principal = Principal(user_id=7, email="lector@ejemplo.invalid", display_name="Lector", role=Role.USER, language="es",
                          timezone="America/Bogota", session_id="s", session_expires_at=world.AT, permissions=frozenset({Permission.APP}))
    app = create_app()
    app.dependency_overrides[current_principal] = lambda: principal
    app.dependency_overrides[get_db] = lambda: None
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.mark.parametrize("path", ["/api/v1/news/v2", "/api/v1/news/v2?q=ejemplo", "/api/v1/news/st-ej-convocatoria-norte",
                                  "/api/v1/matches/1/news/v2", "/api/v1/matches/1/sources"])
def test_the_public_routes_do_not_exist_while_their_switches_are_off(reader: TestClient, path: str,
                                                                     monkeypatch: pytest.MonkeyPatch) -> None:
    import fbi.api.switches as switches

    monkeypatch.setattr(switches, "environment", lambda: {})
    assert reader.get(path).status_code == 404


def test_news_v2_needs_both_switches(reader: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    import fbi.api.switches as switches

    monkeypatch.setattr(switches, "environment", lambda: {"FBI_NEWS_FEED": "1"})
    assert reader.get("/api/v1/news/v2").status_code == 404, "FBI_NEWS_FEED alone (today's production) does not open C-06"


def test_the_routes_of_be040_are_still_mounted_and_a_story_key_is_checked(reader: TestClient) -> None:
    paths = set(reader.app.openapi()["paths"])  # type: ignore[attr-defined]
    assert {"/api/v1/news", "/api/v1/today/news", "/api/v1/matches/{fixture_id}/news"} <= paths
    assert reader.get("/api/v1/news/not-a-story-key").status_code in (404, 422)


# ── isolation ────────────────────────────────────────────────────────────────────────────────────────────────────────

def imports(path: Path) -> set[str]:
    out: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            out.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            out.add(node.module)
    return out


@pytest.mark.parametrize("package", ["factlinks", "newsdesk"])
def test_what_the_api_reads_imports_nothing_that_would_grow_the_cycle(package: str) -> None:
    for p in (SRC / package).glob("*.py"):
        bad = {n for n in imports(p) if n.startswith(("fbi.ai", "fbi.news", "fbi.evalcycle", "fbi.api", "fbi.picks", "fbi.intel",
                                                       "anthropic", "httpx"))}
        assert not bad, f"{p.name}: {bad}"
    assert "fbi.news" not in {n.split(".")[0] + "." + n.split(".")[1] for n in imports(SRC / "api" / "services" / "news_v2.py")
                              if n.count(".") >= 1}


WRITE = re.compile(r"\b(INSERT\s+INTO|UPDATE|DELETE\s+FROM|TRUNCATE)\s+([a-z_]+\.[a-z_0-9]+)", re.IGNORECASE)


def test_factlinks_writes_only_its_two_tables_with_insert_and_the_rest_writes_nothing() -> None:
    writes = {(p.parent.name, p.name, m.group(1).upper().split()[0], m.group(2)) for pkg in ("factlinks", "newsdesk")
              for p in (SRC / pkg).glob("*.py") for m in WRITE.finditer(p.read_text(encoding="utf-8"))}
    assert writes == {("factlinks", "store.py", "INSERT", "intel.eval_source_lists"), ("factlinks", "store.py", "INSERT", "intel.eval_sources")}
    for name in ("news_v2.py", "analysis_sources.py"):
        assert not WRITE.search((SRC / "api" / "services" / name).read_text(encoding="utf-8")), name


def test_an_active_story_none_of_whose_sources_may_be_shown_waits_in_the_queue_and_the_front_page_still_answers() -> None:
    """A story of the window whose every article is ``none`` now: not on the reader's page, in the owner's queue with 0 sources shown
    (the private card allows 0; the public one always carries at least one); the front page does not fail on it."""
    s = world.story("st-sinfuentesvisibles0000", level="un_medio", category="convocatorias", at=world.AT - timedelta(hours=2))
    hidden = world.bundle(s, [world.item(990, s.key, "Medio retenido", "https://medio.example/a", seen=world.AT - timedelta(hours=2),
                                         published=world.AT - timedelta(hours=3))], [], publish={990: "none"})
    body = news_v2.front_of([world.convocatoria(), hidden], [], at=world.AT, followed=None, upcoming=world.UPCOMING)
    queued = [c for c in body.queue.items if c.id == s.key]
    assert queued and queued[0].sources_count == 0 and queued[0].sources == []
    page = NewsPrivate(freshness=Freshness(generated_at=world.AT, stale=False), view="portada", front=body, story_status=news_v2.NO_DATA)
    public = to_public(page, News)
    assert s.key not in json.dumps(public.model_dump(mode="json"))
