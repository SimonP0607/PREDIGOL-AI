"""The news pipeline against PostgreSQL (IA-099 to IA-102): stories, classification, own text and moderation, in shadow.

* a wire story reprinted by five outlets = ONE story with five sources, and a second pass moves nothing (incremental);
* every story gets category, level, language and country;
* the own text: only facts of an authorised, signed source reach the model - a reserved source's claim never does - and the attempt is
  recorded; an injury text goes to the private queue;
* withdrawal end to end: hidden from the public projection, recorded, put back - nothing deleted, the tables refuse UPDATE and DELETE;
* a source whose rights are taken back leaves every public projection.

Each test runs in one transaction rolled back at the end (``commit=False``)."""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest

from fbi.ai import source_registry as registry
from fbi.ai.providers.base import JsonRequest, LlmResult, LlmUsage
from fbi.ai.source_policy import SourcePolicy
from fbi.ai.usage import CallOutcome
from fbi.news import pipeline, readers, store, writer
from fbi.newsroom import moderation
from tests.unit import news_world

pytestmark = pytest.mark.integration
AT = datetime(2027, 2, 10, 15, 0, tzinfo=UTC)
"""Far from the dates other suites commit rows at: a pass reads every article of the last seven days."""
ON = {"FBI_NEWS_STORIES": "shadow"}
TEXT_ON = {"FBI_NEWS_STORIES": "shadow", "FBI_NEWS_TEXT": "shadow"}
WIRE = "Convocatoria del Club Norte para la final: vuelve el capitán"
EXTRA = (news_world._source("ej-tv", "tv.ejemplo.invalid", "verificada_pendiente_derechos"),
         news_world._source("ej-diario", "diario.ejemplo.invalid", "verificada_pendiente_derechos"))
WORLD: tuple[dict[frozenset[str], set[int]], dict[int, str]] = ({frozenset({"norte"}): {11}}, {11: "Club Norte"})


OFICIAL = replace(news_world.SOURCES[0], authority={"convocatorias": {"level": "confirma"}, "lesiones": {"level": "confirma"},
                                                         "alineaciones": {"level": "confirma"}})


def pol(*, signed: tuple[str, ...] = ("ej-oficial",), rules: tuple[registry.DomainRule, ...] = news_world.RULES) -> SourcePolicy:
    return SourcePolicy((OFICIAL, *news_world.SOURCES[1:], *EXTRA), rules, signed, directory_version="dir-ejemplo-1", exclusion_version="excl-ejemplo-1",
                        origin="db")


@pytest.fixture
def conn(migrated_database: str) -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(migrated_database) as c:
        c.execute("SELECT 1")
        yield c
        c.rollback()


def put(c: psycopg.Connection[Any], domain: str, path: str, title: str, *, minutes: int = 0, p: SourcePolicy | None = None) -> int:
    w = store.write_item(c, store.Article(url=f"https://{domain}/{path}", source_name=domain.split(".")[0], fingerprint_text=title,
                                          seen_at=AT + timedelta(minutes=minutes), found_via="rss", written_by="signals-v1",
                                          source_title=title, lang="es", published_at=AT + timedelta(minutes=minutes - 3)), p or pol())
    assert w.wrote and w.id is not None, w
    return w.id


def scalar(c: psycopg.Connection[Any], sql: str, *args: Any) -> Any:
    row = c.execute(sql, args).fetchone()
    assert row is not None
    return row[0]


def story_of(c: psycopg.Connection[Any], item_id: int) -> str:
    return str(scalar(c, "SELECT story_key FROM news.item_story WHERE item_id = %s ORDER BY id DESC LIMIT 1", item_id))


def run(c: psycopg.Connection[Any], *, minutes: int = 30, env: dict[str, str] = ON, p: SourcePolicy | None = None,
        call: Any = None) -> pipeline.Report:
    return pipeline.run_pass(c, at=AT + timedelta(minutes=minutes), env=env, policy=p or pol(), linker_world=WORLD, call=call, typed=False,
                             commit=False)


def evidence(c: psycopg.Connection[Any], item_id: int, claim: str, *, domain: str, tier: str = "media", kind: str = "lineup") -> int:
    return int(scalar(c, "INSERT INTO ai.evidence (kind, claim, origin, source_name, source_url, source_domain, source_tier, published_at, "
                         "retrieved_at, story_key, content_hash, confidence, relevance, status, status_reason, status_changed_at, item_id) "
                         "VALUES (%s, %s, 'web', %s, %s, %s, %s, %s, %s, %s, %s, 0.8, 0.8, 'CONFIRMED', 'test', %s, %s) RETURNING id",
                      kind, claim, domain, f"https://{domain}/n/{item_id}", domain, tier, AT, AT, f"t:{item_id}", f"h:{item_id}:{claim[:8]}",
                      AT, item_id))


def test_a_wire_story_by_five_outlets_is_one_story_with_five_sources_and_a_second_pass_moves_nothing(conn: psycopg.Connection[Any]) -> None:
    domains = ("oficial.ejemplo.invalid", "radio.ejemplo.invalid", "tv.ejemplo.invalid", "diario.ejemplo.invalid", "reservado.ejemplo.invalid")
    ids = [put(conn, d, f"n/{i}", WIRE, minutes=i) for i, d in enumerate(domains)]
    r = run(conn)
    assert r.new_items == 5 and r.stories_new == 1 and r.methods == {"new_story": 1, "huella": 4}, r.as_json()
    assert r.linked_entities == 5, "«Norte» names team 11 in every title"
    keys = {scalar(conn, "SELECT story_key FROM news.item_story WHERE item_id = %s ORDER BY id DESC LIMIT 1", i) for i in ids}
    assert len(keys) == 1
    key = keys.pop()
    view = readers.story_view(conn, key, public=False)
    assert view is not None and len(view.items) == 5 and len({i.source_domain for i in view.items}) == 5
    s = view.story
    assert s.category and s.level and s.lang == "es" and s.country, "the four fields, always"
    assert s.claim_type == "convocatorias" and s.level == "oficial", "the official source confirms call-ups (the directory)"
    links_before = scalar(conn, "SELECT count(*) FROM news.item_story")
    again = run(conn, minutes=40)
    assert again.skipped == "nothing_new" and scalar(conn, "SELECT count(*) FROM news.item_story") == links_before
    late = put(conn, "radio.ejemplo.invalid", "n/late", WIRE + ".", minutes=50)
    third = run(conn, minutes=60)
    assert third.new_items == 1 and third.stories_new == 0
    assert scalar(conn, "SELECT story_key FROM news.item_story WHERE item_id = %s", late) == key
    assert scalar(conn, "SELECT count(*) FROM news.item_story") == links_before + 1, "nothing already grouped is moved"
    assert scalar(conn, "SELECT count(*) FROM news.items GROUP BY content_sha256, url_sha256 ORDER BY 1 DESC LIMIT 1") == 1, \
        "0 exact duplicates in news.items"


def test_the_switch_off_does_nothing(conn: psycopg.Connection[Any]) -> None:
    one = put(conn, "oficial.ejemplo.invalid", "n/1", WIRE)
    r = pipeline.run_pass(conn, at=AT, env={}, policy=pol(), commit=False)
    assert r.skipped == "off" and scalar(conn, "SELECT count(*) FROM news.item_story WHERE item_id = %s", one) == 0


def fake(answer: dict[str, Any], seen: list[JsonRequest]) -> Any:
    def call(req: JsonRequest, inp: writer.StoryInput) -> CallOutcome:
        seen.append(req)
        return CallOutcome(LlmResult(answer, LlmUsage(500, 200), "fake", "small", 10), 77, "bulk", "fake", "small", Decimal("0.0012"))
    return call


def honest(fid: str) -> dict[str, Any]:
    return {"es": {"headline": {"text": "El Norte recupera a su capitán para la final", "facts": [fid]},
                   "summary": [{"text": "El capitán vuelve a la lista del Norte para la final, informó el club.", "facts": [fid]},
                               {"text": "La lista oficial del club lo incluye entre los convocados.", "facts": [fid]}]},
            "en": {"headline": {"text": "Norte get their captain back for the final", "facts": [fid]},
                   "summary": [{"text": "The captain returns to the Norte list for the final, the club said.", "facts": [fid]},
                               {"text": "The club's official list includes him among those called up.", "facts": [fid]}]}}


def test_only_the_authorised_sources_facts_reach_the_model_and_the_attempt_is_recorded(conn: psycopg.Connection[Any]) -> None:
    ok = put(conn, "oficial.ejemplo.invalid", "n/1", WIRE)
    reserved = put(conn, "reservado.ejemplo.invalid", "n/2", WIRE, minutes=2)
    pending = put(conn, "radio.ejemplo.invalid", "n/3", WIRE, minutes=3)
    e_ok = evidence(conn, ok, "El Club Norte publicó la lista de convocados para la final con el regreso del capitán",
                    domain="oficial.ejemplo.invalid", tier="club")
    evidence(conn, reserved, "SECRETO DEL MEDIO RESERVADO: texto que nunca debe llegar al modelo", domain="reservado.ejemplo.invalid")
    evidence(conn, pending, "TEXTO DE LA RADIO PENDIENTE: tampoco llega al modelo", domain="radio.ejemplo.invalid")
    seen: list[JsonRequest] = []
    r = run(conn, env=TEXT_ON, call=fake(honest(f"N{e_ok}"), seen))
    assert r.with_eligible == 1 and r.text == {"accepted": 1}, conn.execute("SELECT problems, metrics FROM news.story_texts").fetchall()
    assert len(seen) == 1
    sent = json.loads(seen[0].user)
    assert [f["id"] for f in sent["facts"]] == [f"N{e_ok}"]
    assert "RESERVADO" not in seen[0].user and "RADIO PENDIENTE" not in seen[0].user and WIRE not in seen[0].user, \
        "no reserved or pending text, and no outlet's title, reaches the model"
    row = conn.execute("SELECT outcome, fact_ids, cost_usd, usage_id, headline_es FROM news.story_texts").fetchone()
    assert row is not None and row[0] == "accepted" and row[1] == [f"N{e_ok}"] and row[2] == Decimal("0.0012") and row[3] == 77
    key = scalar(conn, "SELECT story_key FROM news.story_texts")
    s = readers.story(conn, key)
    assert s is not None and s.headline_es == row[4]
    assert scalar(conn, "SELECT text_version FROM news.stories WHERE story_key = %s ORDER BY version DESC LIMIT 1", key) == \
        writer.PROMPT_VERSION
    public = readers.story_view(conn, key, public=True, policy=pol())
    assert public is not None and public.story.headline_es is not None
    assert {i.source_domain for i in public.items} == {"oficial.ejemplo.invalid", "reservado.ejemplo.invalid", "radio.ejemplo.invalid"}, \
        "the reserved and the pending appear only as links"
    again = run(conn, minutes=45, env=TEXT_ON, call=fake(honest(f"N{e_ok}"), seen))
    assert again.skipped == "nothing_new" and len(seen) == 1, "nothing new: nothing asked again"


def test_with_no_authorised_source_nothing_is_asked_and_it_is_counted(conn: psycopg.Connection[Any]) -> None:
    pending = put(conn, "radio.ejemplo.invalid", "n/1", WIRE)
    evidence(conn, pending, "La radio dice que vuelve el capitán del Norte", domain="radio.ejemplo.invalid")
    seen: list[JsonRequest] = []
    r = run(conn, env=TEXT_ON, call=fake(honest("N1"), seen))
    assert seen == [] and r.text == {"no_eligible_source": 1} and r.with_eligible == 0


def test_an_injury_text_goes_to_the_private_queue_and_a_medical_detail_is_refused(conn: psycopg.Connection[Any]) -> None:
    title = "Lesión: el capitán del Norte es baja para la final"
    ok = put(conn, "oficial.ejemplo.invalid", "n/1", title)
    e = evidence(conn, ok, "El Club Norte informó que su capitán es baja para la final por una lesión", domain="oficial.ejemplo.invalid",
                 tier="club", kind="injury")
    good = {"es": {"headline": {"text": "Norte pierde a su capitán para la final", "facts": [f"N{e}"]},
                   "summary": [{"text": "El capitán es baja para la final, según informó el club.", "facts": [f"N{e}"]},
                               {"text": "El Norte confirmó su ausencia en un comunicado.", "facts": [f"N{e}"]}]},
            "en": {"headline": {"text": "Norte captain out of the final", "facts": [f"N{e}"]},
                   "summary": [{"text": "The captain is out of the final, the club said.", "facts": [f"N{e}"]},
                               {"text": "Norte confirmed his absence in a statement.", "facts": [f"N{e}"]}]}}
    r = run(conn, env=TEXT_ON, call=fake(good, []))
    assert r.text == {"accepted": 1} and r.flags == {"texto_lesion": 1}, conn.execute("SELECT problems FROM news.story_texts").fetchall()
    key = scalar(conn, "SELECT story_key FROM news.story_texts")
    assert readers.story(conn, key).status == "en_moderacion"  # type: ignore[union-attr]
    public = readers.story_view(conn, key, public=True, policy=pol())
    assert public is not None and public.hidden and public.items == [] and public.story.headline_es is None
    queue = moderation.queue(conn, since=AT - timedelta(days=1))
    assert [q["story_key"] for q in queue] == [key] and queue[0]["log"][0].rule == "texto_lesion"

    other = put(conn, "oficial.ejemplo.invalid", "n/2", "Lesión: el lateral del Norte, otra baja para el clásico", minutes=200)
    e2 = evidence(conn, other, "El Club Norte informó que el lateral es baja por lesión", domain="oficial.ejemplo.invalid", tier="club",
                  kind="injury")
    bad = json.loads(json.dumps(good, ensure_ascii=False).replace(f"N{e}", f"N{e2}").replace(
        "El capitán es baja para la final, según informó el club.", "El lateral sufrió una rotura de ligamento y estará seis meses fuera."))
    r2 = run(conn, minutes=230, env=TEXT_ON, call=fake(bad, []))
    assert r2.text.get("rejected") == 1 and r2.flags.get("salud_rechazado") == 1, r2.as_json()
    problems = scalar(conn, "SELECT problems FROM news.story_texts WHERE outcome = 'rejected'")
    assert any("medical_detail" in p for p in problems)
    assert scalar(conn, "SELECT headline_es FROM news.story_texts WHERE outcome = 'rejected'") is None, "a refused text is not kept"


def test_withdrawal_end_to_end_hides_records_and_puts_back_nothing_deleted(conn: psycopg.Connection[Any]) -> None:
    one = put(conn, "oficial.ejemplo.invalid", "n/1", WIRE)
    run(conn)
    key = story_of(conn, one)
    with pytest.raises(moderation.ModerationError):
        moderation.restore(conn, key, at=AT + timedelta(hours=1), reason="no estaba retirada")
    moderation.request(conn, key, at=AT + timedelta(hours=1), reason="El club pide retirar la noticia", requested_by="club",
                       reference="correo 2026-11-17 #12", actor_user_id=1)
    assert readers.story_view(conn, key, public=True).hidden  # type: ignore[union-attr]
    moderation.withdraw(conn, key, at=AT + timedelta(hours=2), reason="Retirada a petición del club", requested_by="club", actor_user_id=1)
    view = readers.story_view(conn, key, public=True)
    assert view is not None and view.hidden and view.story.status == "retirada"
    newest = readers.story(conn, key)
    assert newest is not None and newest.status == "retirada"
    moderation.restore(conn, key, at=AT + timedelta(hours=3), reason="El club retiró su petición", actor_user_id=1)
    assert not readers.story_view(conn, key, public=True).hidden  # type: ignore[union-attr]
    acts = [a.action for a in moderation.log_of(conn, [key])]
    assert acts == ["restore", "withdraw", "request"]
    versions = [r[0] for r in conn.execute("SELECT status FROM news.stories WHERE story_key = %s ORDER BY version", (key,)).fetchall()]
    assert versions == ["activa", "en_moderacion", "retirada", "activa"], "every version stays"
    for sql in ("UPDATE news.moderation_log SET reason = 'x'", "DELETE FROM news.moderation_log", "DELETE FROM news.stories"):
        with pytest.raises(psycopg.Error), conn.transaction():
            conn.execute(sql)


def test_a_source_whose_rights_are_taken_back_leaves_every_public_projection(conn: psycopg.Connection[Any]) -> None:
    one = put(conn, "oficial.ejemplo.invalid", "n/1", WIRE)
    put(conn, "radio.ejemplo.invalid", "n/2", WIRE, minutes=1)
    run(conn)
    key = story_of(conn, one)
    store.revise_story(conn, key, at=AT + timedelta(hours=1), written_by="test-text", text_version="news-text-v1",
                       headline_es="Titular propio de prueba", summary_es="Resumen propio de prueba, atribuido.")
    blocked = pol(rules=(*news_world.RULES, registry.DomainRule("oficial.ejemplo.invalid", "dudoso", "block")))
    view = readers.story_view(conn, key, public=True, policy=blocked)
    assert view is not None and [i.source_domain for i in view.items] == ["radio.ejemplo.invalid"], "the blocked source is left out"
    assert view.story.headline_es is None, "no source left that allows a summary: only the links"
    unsigned = readers.story_view(conn, key, public=True, policy=pol(signed=()))
    assert unsigned is not None and unsigned.story.headline_es is None and len(unsigned.items) == 2
    r = run(conn, minutes=200, p=pol(signed=()))
    assert r.skipped == "nothing_new"
    put(conn, "radio.ejemplo.invalid", "n/3", WIRE + "!", minutes=210)
    r = run(conn, minutes=220, p=pol(signed=()))
    assert r.flags == {"derechos_retirados": 1} and readers.story(conn, key).status == "en_moderacion"  # type: ignore[union-attr]


def test_the_owners_script_reports_and_replays_read_only(conn: psycopg.Connection[Any]) -> None:
    from scripts import ia_news_stories as script

    one = put(conn, "oficial.ejemplo.invalid", "n/1", WIRE)
    run(conn)
    for n in range(3):
        evidence(conn, one, f"Hecho {n} del Club Norte en su web oficial", domain="oficial.ejemplo.invalid")
    got = script.report(conn)
    assert got["items"] >= 1 and got["stories"] >= 1
    r = script.replay(conn, days=100000, at=AT + timedelta(days=1))
    assert r["addresses"] >= 1 and r["items"] == r["canonical_urls"] and r["version"] == "stories-v1"
