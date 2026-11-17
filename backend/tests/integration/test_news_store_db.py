"""The news store against PostgreSQL (IA-080, AD-G01): idempotent and deduplicated writes, the source policy copied into each item, the
versions that replace an UPDATE, and the contract test of the piece - C-06 «noticia individual» is served from ``news.items`` +
``news.item_entities`` (with its story), equal to ``tests/fixtures/contracts/news/C-06/noticia.public.json``.

Every test but the last runs in one transaction rolled back at the end; the last commits rows of its own (unique URLs): two workers
writing the same article at the same moment must leave one row."""

from __future__ import annotations

import json
import threading
import uuid
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest

from fbi.news import canonical, readers, store, vocab
from tests.unit.news_world import AT, policy

pytestmark = pytest.mark.integration
EXAMPLE = Path(__file__).resolve().parents[1] / "fixtures" / "contracts" / "news" / "C-06" / "noticia.public.json"
OFICIAL = "https://oficial.ejemplo.invalid/noticias/convocatoria"
RADIO = "https://radio.ejemplo.invalid/deportes/club-norte-atacantes"
RESERVADO = "https://reservado.ejemplo.invalid/futbol/convocatoria-club-norte"


@pytest.fixture
def conn(migrated_database: str) -> Iterator[psycopg.Connection[Any]]:
    with psycopg.connect(migrated_database) as c:
        c.execute("SELECT 1")  # a transaction in progress: every write of the store is then a savepoint inside it, rolled back below
        yield c
        c.rollback()


def article(url: str, text: str, *, seen: datetime, published: datetime | None = None, **kw: Any) -> store.Article:
    return store.Article(url=url, source_name=kw.pop("source_name", "Fuente Ejemplo"), fingerprint_text=text, seen_at=seen,
                         found_via=kw.pop("found_via", "rss"), written_by="ingest-v1", published_at=published,
                         published_structured=published is not None, lang="es", **kw)


def count(c: psycopg.Connection[Any], table: str) -> int:
    row = c.execute(f"SELECT count(*) FROM news.{table}").fetchone()
    assert row is not None
    return int(row[0])


def test_an_article_is_written_once_and_a_new_content_is_a_new_version(conn: psycopg.Connection[Any]) -> None:
    p = policy()
    first = store.write_item(conn, article(OFICIAL + "?utm_source=boletin#top", "Convocatoria oficial del Club Ejemplo Norte",
                                           seen=AT, published=AT - timedelta(minutes=6), source_title="Convocados para el sábado"), p)
    assert first.outcome == "created" and first.version == 1
    again = store.write_item(conn, article("http://www.oficial.ejemplo.invalid/noticias/convocatoria/",
                                           "CONVOCATORIA oficial del club ejemplo norte.", seen=AT + timedelta(hours=1)), p)
    assert again == store.Written("unchanged", first.id, 1), "another spelling of the same address and the same words: nothing written"
    changed = store.write_item(conn, article(OFICIAL, "Convocatoria oficial del Club Ejemplo Norte con dos novedades",
                                             seen=AT + timedelta(hours=2)), p)
    assert changed.outcome == "new_version" and changed.version == 2
    back = store.write_item(conn, article(OFICIAL, "Convocatoria oficial del Club Ejemplo Norte", seen=AT + timedelta(hours=3)), p)
    assert back == store.Written("unchanged", first.id, 1), "a content already stored for the URL is that row, never a third version"
    rows = conn.execute("SELECT version, previous_id, url_sha256, canonical_url, canon_version, fingerprint_version, store_level, "
                        "publish_level, source_state, source_id, ai_reserved, registry_version, policy_version, source_title "
                        "FROM news.items WHERE url_sha256 = %s ORDER BY version", (canonical.url_sha256(OFICIAL),)).fetchall()
    assert [r[:2] for r in rows] == [(1, None), (2, first.id)]
    assert rows[0][2:] == (canonical.sha256_hex(OFICIAL), OFICIAL, "canon-v1", "fp-v1", "facts", "summary", "verificada_autorizada",
                           "ej-oficial", False, "dir-ejemplo-1+excl-ejemplo-1", "source-policy-v1", "Convocados para el sábado")


def test_each_item_carries_the_permission_of_its_source_and_a_source_that_keeps_nothing_is_never_stored(
        conn: psycopg.Connection[Any]) -> None:
    p = policy()
    before = count(conn, "items")
    for url, expected in ((RADIO, ("link", "link", False, "verificada_pendiente_derechos")),
                          (RESERVADO, ("link", "link", True, "solo_referencia")),
                          ("https://sinfirma.ejemplo.invalid/a", ("link", "link", False, "verificada_autorizada"))):
        w = store.write_item(conn, article(url, f"texto leído de {url}", seen=AT), p)
        assert w.outcome == "created"
        assert conn.execute("SELECT store_level, publish_level, ai_reserved, source_state FROM news.items WHERE id = %s",
                            (w.id,)).fetchone() == expected
    for url in ("https://bloqueado.ejemplo.invalid/a", "https://apuestas.ejemplo.invalid/a", "https://otro.ejemplo.invalid/a"):
        assert store.write_item(conn, article(url, "algo", seen=AT), p).outcome == "refused"
    assert store.write_item(conn, article(OFICIAL, "algo", seen=AT), None).outcome == "refused"
    assert count(conn, "items") == before + 3


def test_feeds_are_versioned_and_a_feed_taken_out_is_a_new_version(conn: psycopg.Connection[Any]) -> None:
    feed = store.Feed(url="https://oficial.ejemplo.invalid/rss.xml", kind="rss", source_id="ej-oficial",
                      source_domain="oficial.ejemplo.invalid", at=AT, added_by="loader", lang="es", country="Colombia")
    first = store.write_feed(conn, feed)
    assert first.outcome == "created"
    assert store.write_feed(conn, feed) == store.Written("unchanged", first.id, 1)
    off = store.write_feed(conn, store.Feed(**{**{f: getattr(feed, f) for f in store.Feed.__dataclass_fields__}, "active": False,
                                               "reason": "el feed dejó de responder", "added_by": "owner"}))
    assert off.outcome == "new_version" and off.version == 2
    item = store.write_item(conn, article(OFICIAL, "con su feed", seen=AT, feed_id=off.id), policy())
    assert conn.execute("SELECT feed_id FROM news.items WHERE id = %s", (item.id,)).fetchone() == (off.id,)


def build_story(conn: psycopg.Connection[Any]) -> str:
    """The fictitious story of the contract example: an official call-up told by three sources (the club, a radio pending its rights,
    a medium that reserves its text from AI) and two players and a team named."""
    p = policy()
    seen = AT + timedelta(hours=1, minutes=44)  # 18:26
    a1 = store.write_item(conn, article(OFICIAL, "Convocatoria oficial del Club Ejemplo Norte", seen=seen - timedelta(minutes=30),
                                        published=seen - timedelta(minutes=36), source_name="Club Ejemplo Norte (oficial)"), p)
    a2 = store.write_item(conn, article(OFICIAL, "Convocatoria oficial del Club Ejemplo Norte con sus dos atacantes", seen=seen,
                                        published=seen - timedelta(minutes=6), source_name="Club Ejemplo Norte (oficial)"), p)
    b = store.write_item(conn, article(RADIO, "La radio cuenta la convocatoria", seen=seen + timedelta(minutes=14),
                                       published=seen + timedelta(minutes=9), source_name="Radio Ejemplo", author="R. Ejemplo"), p)
    c = store.write_item(conn, article(RESERVADO, "El medio cuenta la convocatoria", seen=seen + timedelta(minutes=20),
                                       source_name="Diario Reservado Ejemplo"), p)
    assert [w.outcome for w in (a1, a2, b, c)] == ["created", "new_version", "created", "created"]
    key = store.story_key_for(canonical.url_sha256(OFICIAL))
    created = store.write_story(conn, store.Story(story_key=key, at=seen - timedelta(minutes=30), first_seen_at=seen - timedelta(minutes=30),
                                                  written_by="grouper-v1", claim_type="convocatorias"))
    assert created.outcome == "created"
    methods: tuple[tuple[store.Written, vocab.GroupMethod], ...] = ((a1, "url"), (a2, "url"), (b, "entidades"), (c, "entidades"))
    for w, method in methods:
        assert w.id is not None
        assert store.link_item_story(conn, w.id, key, at=seen + timedelta(minutes=21), method=method, grouper_version="grouper-v1",
                                     score=0.9).wrote
    classified = store.revise_story(conn, key, at=seen + timedelta(minutes=22), written_by="classify-v1", category="selecciones",
                                    level="oficial", lang="es", country="Colombia")
    texted = store.revise_story(conn, key, at=seen + timedelta(minutes=23), written_by="writer-v1", text_version="writer-v1",
                                headline_es="Club Ejemplo Norte cita a sus dos atacantes titulares",
                                summary_es="La convocatoria oficial incluye a J. Ejemplo y A. Ejemplo. El club no informó bajas nuevas.")
    assert (classified.version, texted.version) == (2, 3)
    assert store.revise_story(conn, key, at=seen + timedelta(minutes=24), written_by="writer-v1",
                              headline_es="Club Ejemplo Norte cita a sus dos atacantes titulares").outcome == "unchanged"
    at = seen + timedelta(minutes=25)
    links = (
        (a2, store.EntityLink("player", 880009, "protagonista", "alias", 0.98, "linker-v1", at, "J. Ejemplo")),
        (a2, store.EntityLink("player", 880010, "protagonista", "alias", 0.95, "linker-v1", at, "A. Ejemplo")),
        (a2, store.EntityLink("team", 770001, "protagonista", "proveedor", 1, "linker-v1", at, "Club Ejemplo Norte")),
        (b, store.EntityLink("player", 880009, "mencionado", "alias", 0.9, "linker-v1", at, "J. Ejemplo")),
        (b, store.EntityLink("player", 880011, "mencionado", "alias", 0.6, "linker-v1", at, "Otro Ejemplo")),
    )
    for w, link in links:
        assert w.id is not None and store.link_entity(conn, w.id, link).outcome == "created"
    assert b.id is not None
    again = store.link_entity(conn, b.id, store.EntityLink("player", 880009, "mencionado", "alias", 0.9, "linker-v2", at, "J. Ejemplo"))
    assert again.outcome == "unchanged", "a new linker that agrees writes nothing"
    homonym = store.EntityLink("player", 880011, "mencionado", "alias", 0.6, "linker-v1", at + timedelta(minutes=1), "Otro Ejemplo",
                               active=False)
    assert store.link_entity(conn, b.id, homonym).outcome == "new_version", "a homonym taken back"
    assert store.link_entity(conn, b.id, homonym).outcome == "unchanged"
    return key


def iso(value: datetime | None) -> str | None:
    return None if value is None else value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def c06_noticia(view: readers.StoryView) -> dict[str, Any]:
    """C-06 «noticia individual» (UX plan, screen 09) as AD-G07 will build it - here, only from what the readers return."""
    s = view.story
    return {
        "contract": "C-06", "contract_version": "1.0.0", "projection": "public",
        "id": s.story_key, "category": s.category, "level": s.level, "headline_es": s.headline_es, "essentials_es": s.summary_es,
        "sources": [{"name": i.source_name, "author": i.author, "published_at": iso(i.published_at), "known_at": iso(i.seen_at),
                     "url": i.canonical_url} for i in view.items],
        "entities": [{"type": e.entity_type, "id": e.entity_id, "name": e.name_seen, "role": e.role, "method": e.method,
                      "confidence": float(e.confidence)} for e in view.entities],
    }


def test_c06_is_served_from_news_items_and_news_item_entities(conn: psycopg.Connection[Any]) -> None:
    key = build_story(conn)
    view = readers.story_view(conn, key, policy=policy())
    assert view is not None and not view.hidden
    assert c06_noticia(view) == json.loads(EXAMPLE.read_text(encoding="utf-8"))
    assert [i.version for i in view.items if i.canonical_url == OFICIAL] == [2], "one source per article: its newest version"
    assert {e.entity_id for e in view.entities} == {880009, 880010, 770001}, "the homonym taken back is not there"

    by_player = readers.items_for_entity(conn, "player", 880009, since=AT)
    assert [i.canonical_url for i in by_player] == [RADIO, OFICIAL]
    assert [s.story_key for s in readers.recent_stories(conn, since=AT)][:1] == [key]


def test_a_story_in_moderation_or_withdrawn_shows_nothing_and_comes_back_with_a_new_version(conn: psycopg.Connection[Any]) -> None:
    key = build_story(conn)
    later = AT + timedelta(hours=3)
    assert store.revise_story(conn, key, at=later, written_by="moderation-v1", status="en_moderacion",
                              status_reason="cola de moderación").outcome == "new_version"
    hidden = readers.story_view(conn, key)
    assert hidden is not None and hidden.hidden and hidden.items == [] and hidden.entities == []
    assert hidden.story.headline_es is None and hidden.story.status == "en_moderacion"
    private = readers.story_view(conn, key, public=False)
    assert private is not None and not private.hidden and private.story.headline_es and len(private.items) == 3
    assert key not in [s.story_key for s in readers.recent_stories(conn, since=AT)]
    withdrawn = store.revise_story(conn, key, at=later + timedelta(minutes=1), written_by="moderation-v1", decided_by="owner",
                                   status="retirada", status_reason="petición del medio")
    restored = store.revise_story(conn, key, at=later + timedelta(minutes=2), written_by="moderation-v1", decided_by="owner",
                                  status="activa", status_reason=None)
    assert (withdrawn.version, restored.version) == (5, 6)
    view = readers.story_view(conn, key)
    assert view is not None and not view.hidden
    history = conn.execute("SELECT version, status FROM news.stories WHERE story_key = %s ORDER BY version", (key,)).fetchall()
    assert [s for _, s in history] == ["activa", "activa", "activa", "en_moderacion", "retirada", "activa"], "nothing was rewritten"


def test_without_a_source_that_allows_it_the_own_text_is_not_shown_only_the_links(conn: psycopg.Connection[Any]) -> None:
    key = build_story(conn)
    view = readers.story_view(conn, key, policy=policy(signed=()))
    assert view is not None and view.story.headline_es is None and view.story.summary_es is None
    assert [readers.effective_publish(i, policy(signed=())) for i in view.items] == ["link", "link", "link"]


def test_an_item_moves_between_stories_with_a_new_row(conn: psycopg.Connection[Any]) -> None:
    key = build_story(conn)
    other = store.story_key_for("otra-historia")
    store.write_story(conn, store.Story(story_key=other, at=AT + timedelta(hours=2), first_seen_at=AT + timedelta(hours=2),
                                        written_by="grouper-v1"))
    radio = readers.newest_item(conn, canonical.url_sha256(RADIO))
    assert radio is not None
    moved = store.link_item_story(conn, radio.id, other, at=AT + timedelta(hours=2), method="manual", grouper_version="grouper-v1",
                                  decided_by="owner")
    assert moved.outcome == "new_version"
    assert [i.canonical_url for i in readers.story_items(conn, key)] == [RESERVADO, OFICIAL]
    assert [i.canonical_url for i in readers.story_items(conn, other)] == [RADIO]
    assert store.link_item_story(conn, radio.id, "st-no-existe", at=AT, method="manual", grouper_version="g-1").reason == "no_such_story"


def test_a_claim_written_with_its_article_keeps_it(conn: psycopg.Connection[Any]) -> None:
    item = store.write_item(conn, article(OFICIAL, "convocatoria", seen=AT), policy())
    row = conn.execute(
        "INSERT INTO ai.evidence (kind, claim, origin, source_name, source_url, source_tier, retrieved_at, story_key, content_hash, "
        "confidence, relevance, status, status_reason, status_changed_at, item_id) VALUES ('lineup', 'El club convoca a sus atacantes', "
        "'web', 'Club Ejemplo Norte', %s, 'club', %s, 'k-ia080', 'h-ia080', 0.9, 0.9, 'CONFIRMED', 'official', %s, %s) RETURNING item_id",
        (OFICIAL, AT, AT, item.id)).fetchone()
    assert row == (item.id,)


def test_two_workers_writing_the_same_article_at_once_leave_one_row(migrated_database: str) -> None:
    url = f"https://oficial.ejemplo.invalid/noticias/{uuid.uuid4().hex}"
    results: list[store.Written] = []
    barrier = threading.Barrier(4)

    def worker() -> None:
        with psycopg.connect(migrated_database, autocommit=True) as c:
            barrier.wait()
            results.append(store.write_item(c, article(url, "la misma noticia", seen=AT), policy()))

    threads = [threading.Thread(target=worker) for _ in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert sorted(r.outcome for r in results) == ["created", "unchanged", "unchanged", "unchanged"]
    assert len({r.id for r in results}) == 1
    with psycopg.connect(migrated_database) as c:
        assert c.execute("SELECT count(*) FROM news.items WHERE url_sha256 = %s", (canonical.url_sha256(url),)).fetchone() == (1,)
