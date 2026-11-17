"""IA-062 and IA-063 on a real database: the registry loaded (idempotent, append-only, the counts of the directory), the owner's signature,
the policy read from the database, and the two research paths with a search that is a function and a model that is a spy:

* a page of a source that reserves its text from AI never reaches the model - with nothing else to read, the model is not called at all;
* a page of an excluded domain never reaches ``ai.evidence`` (a replay of Exa results of the kind production stored);
* what the strict policy would block is recorded in shadow and changes nothing of what is read;
* the text of a reserved or excluded page is not kept in the research cache."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from typing import Any
from urllib.parse import urlsplit

import psycopg
import pytest

from fbi.ai import collectors, source_policy, source_registry
from fbi.ai.config import AiSettings
from fbi.ai.providers.base import JsonRequest
from fbi.ai.providers.fake import FakeProvider
from fbi.ai.usage import UsageLedger, shared

from .conftest import Seed
from .test_ai_research_entities import AT, MODEL, Web, World, build, page, reader, run

pytestmark = pytest.mark.integration

RESERVED = page("https://www.espn.com/soccer/alfa", "Alfa FC: baja", "Delantero Uno no jugará ante Beta FC por lesión.")
BETTING = page("https://www.mediapronos.com/alfa-beta", "Pronostic Alfa Beta", "Delantero Uno no jugará ante Beta FC: misez sur Beta.")
SEARCH_ENGINE = page("https://exa.ai/search?q=alfa", "Alfa FC", "Extremo Dos es duda para el partido.")
HONEST = page("https://www.futbolred.com/beta-duda", "Beta FC: duda", "Extremo Dos es duda para el partido.")


@pytest.fixture()
def world(db: psycopg.Connection[Any], seed: Seed) -> Iterator[World]:
    source_policy.reset_cache()
    yield build(db, kickoff_a=AT + timedelta(hours=20))
    source_policy.reset_cache()


@pytest.fixture()
def loaded(world: World) -> World:
    source_registry.load_bundled(world.db, at=AT)
    return world


def test_the_loader_writes_the_directory_once_with_its_counts(world: World) -> None:
    first = source_registry.load_bundled(world.db, at=AT)
    assert [(r.kind, r.created, r.rows) for r in first] == [("directory", True, 2001), ("exclusion", True, 559)]
    again = source_registry.load_bundled(world.db, at=AT + timedelta(hours=1))
    assert [(r.created, r.rows) for r in again] == [(False, 0), (False, 0)], "idempotent: two loads, no new row"
    db = world.db
    assert db.execute("SELECT count(*) FROM ai.source_registry").fetchone() == (2001,)
    assert dict(db.execute("SELECT state, count(*) FROM ai.source_registry GROUP BY 1").fetchall()) == {
        "verificada_autorizada": 3, "verificada_pendiente_derechos": 1289, "solo_referencia": 71, "no_comprobada": 153, "bloqueada": 485}
    assert db.execute("SELECT count(*) FROM ai.domain_rules WHERE action = 'block'").fetchone() == (117,)
    assert db.execute("SELECT count(*) FROM ai.source_registry_versions").fetchone() == (2,)
    assert source_registry.current_versions(db) == (source_registry.DIRECTORY.version, source_registry.EXCLUSION.version)
    record = db.execute("SELECT record, authority FROM ai.source_registry WHERE source_id = 'reuters'").fetchone()
    assert record is not None and len(record[0]) == 52 and record[1]["rumores"] == {"level": "sin_autoridad"}


def test_the_registry_is_append_only(loaded: World) -> None:
    db = loaded.db
    for sql in ("UPDATE ai.source_registry SET state = 'verificada_autorizada' WHERE source_id = 'reuters'",
                "DELETE FROM ai.domain_rules WHERE domain = 'exa.ai'",
                "UPDATE ai.source_registry_versions SET rows = 0"):
        with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
            db.execute(sql)


def test_only_the_owner_moves_a_source_to_authorised(loaded: World) -> None:
    db = loaded.db
    v = source_registry.DIRECTORY.version
    url = "https://agenciabrasil.ebc.com.br/esportes/noticia"
    assert not source_policy.can_extract(source_policy.load(db).standing(url)).allowed, "authorised by the directory, not signed: pending"  # type: ignore[union-attr]
    with pytest.raises(source_registry.RegistryError, match="only a source"):
        source_registry.sign(db, source_ids=["reuters"], decision="authorize", version=v, at=AT, reason="prueba")
    assert source_registry.sign(db, source_ids=["bra-agencia-brasil-esportes"], decision="authorize", version=v, at=AT, reason="términos leídos") == 1
    assert source_policy.can_extract(source_policy.load(db).standing(url)).allowed  # type: ignore[union-attr]
    source_registry.sign(db, source_ids=["bra-agencia-brasil-esportes"], decision="revoke", version=v, at=AT + timedelta(minutes=1), reason="revisar")
    assert not source_policy.can_extract(source_policy.load(db).standing(url)).allowed, "the newest signature decides"  # type: ignore[union-attr]
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        db.execute("INSERT INTO ai.source_signoffs (source_id, decision, registry_version, decided_by, at, reason) "
                   "VALUES ('co-elnuevodia', 'authorize', %s, 'loader', now(), 'no soy el dueño')", (v,))


def test_the_policy_reads_the_database_and_the_image_before_the_loader_ran(world: World) -> None:
    before = source_policy.load(world.db)
    assert before is not None and before.origin == "bundled", "no version loaded yet: the pinned files of the image"
    source_registry.load_bundled(world.db, at=AT)
    after = source_policy.load(world.db)
    assert after is not None and after.origin == "db" and after.version == f"{source_registry.DIRECTORY.version}+{source_registry.EXCLUSION.version}"
    assert after.standing("https://www.espn.com/x").hard_reason == "ai_reserved"


def spy_v1() -> FakeProvider:
    """v1's extractor, scripted: one item for the first result it is given. Its ``requests`` are what it was shown."""

    def items(r: JsonRequest) -> dict[str, Any]:
        return {"items": [{"result_id": "R1", "side": "home", "player": "Delantero Uno", "kind": "injury", "assertion": "out",
                           "claim": "Delantero Uno no jugará por lesión.", "published_at": None}]}

    return FakeProvider(items, name="anthropic")


def v1(w: World, web: Web, model: FakeProvider) -> collectors.Collected:
    return collectors.collect_web(w.db, AiSettings(mode="shadow"), w.a, at=AT, ledger=UsageLedger(shared(w.db)), search=web,
                                  provider=(model, MODEL), levels=1)


def log_rows(db: psycopg.Connection[Any]) -> list[tuple[Any, ...]]:
    return db.execute("SELECT path, outcome, hard, reason, domain FROM ai.source_policy_log ORDER BY id").fetchall()


@pytest.mark.parametrize("path", ["v1", "v2"])
def test_a_reserved_page_alone_never_reaches_the_model(loaded: World, path: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(source_policy.POLICY_ENV, "shadow")
    model = spy_v1() if path == "v1" else reader()
    got = v1(loaded, Web([RESERVED]), model) if path == "v1" else run(loaded, Web([RESERVED]), model)
    assert model.requests == [], "the spy: zero calls"
    assert got.created == 0
    assert log_rows(loaded.db) == [(path, "blocked", True, "ai_reserved", "espn.com")]
    cached = loaded.db.execute("SELECT payload FROM ai.research_cache WHERE scope = 'search'").fetchone()
    assert cached is not None and all(r["snippet"] == "" for r in cached[0]["results"]), "the text of a reserved page is not kept"


@pytest.mark.parametrize("path", ["v1", "v2"])
def test_no_excluded_domain_reaches_the_evidence_and_shadow_reads_the_rest(loaded: World, path: str) -> None:
    """A replay of Exa results of the kind production stored: a betting site, the search engine's own page, a reserved outlet and an
    honest one. Only the honest one is read; the strict policy, in shadow, records that it would have kept it away too."""
    web = Web([BETTING, SEARCH_ENGINE, RESERVED, HONEST])
    model = spy_v1() if path == "v1" else reader()
    got = v1(loaded, web, model) if path == "v1" else run(loaded, web, model)
    assert len(model.requests) == 1
    sent = model.requests[0].user
    for absent in ("mediapronos", "exa.ai", "espn.com", "misez"):
        assert absent not in sent, absent
    assert "Extremo Dos es duda para el partido." in sent
    urls = [r[0] for r in loaded.db.execute("SELECT source_url FROM ai.evidence WHERE origin = 'web'").fetchall()]
    assert urls and all(urlsplit(u).hostname == "www.futbolred.com" for u in urls), urls
    assert got.created >= 1
    rows = log_rows(loaded.db)
    assert sorted((r[1], r[3]) for r in rows) == sorted([
        ("blocked", "excluded:apuestas_o_pronosticos"), ("blocked", "excluded:no_futbol_u_otro"), ("blocked", "ai_reserved"),
        ("would_block", "not_authorised:verificada_pendiente_derechos")]), rows
    assert {r[0] for r in rows} == {path}


def test_enforce_reads_only_what_is_authorised_and_signed(loaded: World, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(source_policy.POLICY_ENV, "enforce")
    model = spy_v1()
    got = v1(loaded, Web([HONEST]), model)
    assert model.requests == [] and got.created == 0, "a pending source is not read once the owner switches enforce on"
    assert log_rows(loaded.db) == [("v1", "blocked", False, "not_authorised:verificada_pendiente_derechos", "futbolred.com")]
    cached = loaded.db.execute("SELECT payload FROM ai.research_cache WHERE scope = 'search'").fetchone()
    assert cached is not None and [r["snippet"] for r in cached[0]["results"]] == [""], "enforce: only the link of a pending source"


def test_the_log_is_best_effort_and_never_breaks_the_callers_transaction(loaded: World) -> None:
    db = loaded.db
    screened = source_policy.screen(source_policy.load(db), [RESERVED])
    assert source_policy.record(db, screened, at=AT, path="v1") == 1
    assert db.execute("SELECT 1").fetchone() == (1,)
    ro = psycopg.connect(db.info.dsn, autocommit=False, options="-c default_transaction_read_only=on")
    try:
        assert source_policy.record(ro, screened, at=AT, path="analyst") == 0, "a connection that may not write: no row, no error"
        assert ro.execute("SELECT 1").fetchone() == (1,), "and the transaction goes on"
    finally:
        ro.close()


def test_the_shadow_report_reads_the_log(loaded: World) -> None:
    v1(loaded, Web([RESERVED, HONEST]), spy_v1())
    from scripts import ia_sources_load

    class Args:
        days = 14

    out, code = ia_sources_load.cmd_shadow(loaded.db, Args(), AT + timedelta(minutes=5))  # type: ignore[arg-type]
    assert code == 0 and {g["reason"] for g in out["groups"]} == {"ai_reserved", "not_authorised"}
