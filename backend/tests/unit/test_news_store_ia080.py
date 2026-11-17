"""IA-080 (AD-G01), without a database: the canonical URL and the fingerprint the store deduplicates on, the words of the store against
the CHECKs of migration 0146, and what ``write_item`` refuses before it ever reaches the database (the source policy decides first, and
without a registry nothing is stored)."""

from __future__ import annotations

import importlib.util
from datetime import timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from fbi.ai import source_policy
from fbi.news import canonical, readers, store, vocab
from tests.unit.news_world import AT, policy

BACKEND = Path(__file__).resolve().parents[2]


def migration() -> ModuleType:
    spec = importlib.util.spec_from_file_location("m0146", BACKEND / "migrations" / "versions" / "0146_news_schema.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


# ── canonical URL ─────────────────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("raw", "expected"), [
    ("http://www.Club-Norte.invalid/noticias/convocatoria/?utm_source=x&utm_medium=y#arriba",
     "https://club-norte.invalid/noticias/convocatoria"),
    ("https://m.club-norte.invalid/noticias/convocatoria/amp/", "https://club-norte.invalid/noticias/convocatoria"),
    ("https://amp.club-norte.invalid/noticias/convocatoria?outputType=amp&fbclid=abc", "https://club-norte.invalid/noticias/convocatoria"),
    ("https://club-norte.invalid:443/a//b/?b=2&a=1&gclid=z", "https://club-norte.invalid/a/b?a=1&b=2"),
    ("https://club-norte.invalid:8080/a", "https://club-norte.invalid:8080/a"),
    ("https://club-norte.invalid/", "https://club-norte.invalid/"),
    ("https://club-norte.invalid", "https://club-norte.invalid/"),
    ("https://club-norte.invalid/Noticia-Mayus?id=7&format=json", "https://club-norte.invalid/Noticia-Mayus?format=json&id=7"),
    ("https://m.invalid/a", "https://m.invalid/a"),
])
def test_one_address_per_article(raw: str, expected: str) -> None:
    assert canonical.canonical_url(raw) == expected
    assert canonical.canonical_url(expected) == expected, "canonical twice is canonical once"


@pytest.mark.parametrize("raw", ["", "ftp://club.invalid/a", "club.invalid/a", "https:///nohost", "javascript:alert(1)"])
def test_what_is_not_an_article_address_is_refused(raw: str) -> None:
    with pytest.raises(canonical.NotAnArticleUrlError):
        canonical.canonical_url(raw)


def test_the_fingerprint_reads_the_words_not_the_typography() -> None:
    a = canonical.fingerprint("Club Ejemplo Norte cita a sus dos atacantes — titulares.")
    b = canonical.fingerprint("  CLUB  ejemplo norte cita a sus dos atacantes, titulares ")
    c = canonical.fingerprint("Club Ejemplo Norté cita a sus dos atacantes titulares")
    assert a == b == c
    assert a != canonical.fingerprint("Club Ejemplo Norte cita a sus tres atacantes titulares")
    with pytest.raises(ValueError):
        canonical.fingerprint(" — ¡! ")
    assert canonical.url_sha256("http://www.club.invalid/a/") == canonical.sha256_hex("https://club.invalid/a")


# ── the words against the migration ───────────────────────────────────────────────────────────────────────────────────────

def test_the_words_of_the_code_are_the_checks_of_the_migration() -> None:
    m = migration()
    pairs: list[tuple[Any, Any]] = [
        (m.FEED_KINDS, vocab.FEED_KINDS), (m.FOUND_VIA, vocab.FOUND_VIA), (m.SOURCE_STATES, vocab.SOURCE_STATES),
        (m.STORE_LEVELS, vocab.STORE_LEVELS), (m.PUBLISH_LEVELS, vocab.PUBLISH_LEVELS), (m.CATEGORIES, vocab.CATEGORIES),
        (m.LEVELS, vocab.LEVELS), (m.CLAIM_TYPES, vocab.CLAIM_TYPES), (m.STATUSES, vocab.STATUSES),
        (m.GROUP_METHODS, vocab.GROUP_METHODS), (m.ENTITY_TYPES, vocab.ENTITY_TYPES), (m.ROLES, vocab.ROLES),
        (m.LINK_METHODS, vocab.LINK_METHODS), (m.DECIDERS, vocab.DECIDERS),
    ]
    for theirs, ours in pairs:
        assert tuple(theirs) == tuple(ours)
    assert set(vocab.PUBLISH_ORDER) == set(vocab.PUBLISH_LEVELS) and set(vocab.STORE_ORDER) == {*vocab.STORE_LEVELS, "none"}
    assert m.down_revision == "0145" and m.revision == "0146"
    assert set(m.TABLES) == {"feeds", "items", "stories", "item_story", "item_entities"}


def test_the_guard_of_the_evidence_keeps_every_column_of_0114_and_adds_item_id() -> None:
    m = migration()
    spec = importlib.util.spec_from_file_location("m0114", BACKEND / "migrations" / "versions" / "0114_ia_phase2_evidence_subject_fresh_scope.py")
    assert spec and spec.loader
    m0114 = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m0114)
    assert tuple(m.CONTENT) == (*m0114.CONTENT, *m0114.NEW_CONTENT)
    guard = m._guard((*m.CONTENT, "item_id"))
    assert "NEW.item_id" in guard and "OLD.item_id" in guard and "rows are never deleted" in guard


def test_no_column_could_hold_an_articles_text_or_picture() -> None:
    sql = Path(BACKEND / "migrations" / "versions" / "0146_news_schema.py").read_text(encoding="utf-8").lower()
    for word in ("body ", "body_", "full_text", "content_text", "image", "photo", "snippet", "html"):
        assert word not in sql.split("def upgrade")[1].split("def downgrade")[0], word


# ── what write_item refuses before the database ───────────────────────────────────────────────────────────────────────────

def article(url: str, **kw: Any) -> store.Article:
    base: dict[str, Any] = {"url": url, "source_name": "Fuente Ejemplo", "fingerprint_text": "Club Ejemplo Norte cita a sus atacantes",
                            "seen_at": AT, "found_via": "rss", "written_by": "ingest-v1"}
    return store.Article(**{**base, **kw})


class NoDatabase:
    """A connection that fails the test if it is used: a refusal never reaches the database."""

    def __getattr__(self, name: str) -> Any:
        raise AssertionError(f"the database was used: {name}")


@pytest.mark.parametrize(("url", "reason"), [
    ("https://bloqueado.ejemplo.invalid/a", "store:none:not_authorised:bloqueada"),
    ("https://apuestas.ejemplo.invalid/a", "store:none:excluded:apuestas_o_pronosticos"),
    ("https://cualquiera.ejemplo.invalid/a", "store:none:not_authorised:desconocida"),
])
def test_a_source_that_may_keep_nothing_is_never_stored(url: str, reason: str) -> None:
    written = store.write_item(NoDatabase(), article(url), policy())  # type: ignore[arg-type]
    assert written == store.Written("refused", reason=reason)


def test_without_a_registry_nothing_is_stored() -> None:
    written = store.write_item(NoDatabase(), article("https://oficial.ejemplo.invalid/a"), None)  # type: ignore[arg-type]
    assert written.outcome == "refused" and written.reason == "registry_unavailable"


@pytest.mark.parametrize(("kw", "reason"), [
    ({"published_at": AT + timedelta(minutes=1)}, "invalid:published_after_seen"),
    ({"published_structured": True}, "invalid:published_flags_without_date"),
    ({"event_at": AT, "valid_until": AT - timedelta(hours=1)}, "invalid:valid_until_before_event"),
    ({"found_via": "scraping"}, "invalid:found_via:scraping"),
    ({"source_name": "  "}, "invalid:source_name"),
    ({"url": "ftp://oficial.ejemplo.invalid/a"}, "invalid:NotAnArticleUrlError"),
    ({"fingerprint_text": "—"}, "invalid:ValueError"),
])
def test_what_the_database_would_refuse_is_refused_first(kw: dict[str, Any], reason: str) -> None:
    url = kw.pop("url", "https://oficial.ejemplo.invalid/a")
    written = store.write_item(NoDatabase(), article(url, **kw), policy())  # type: ignore[arg-type]
    assert written == store.Written("refused", reason=reason)


def test_a_naive_time_is_a_mistake_of_the_caller() -> None:
    with pytest.raises(ValueError):
        store.write_item(NoDatabase(), article("https://oficial.ejemplo.invalid/a", seen_at=AT.replace(tzinfo=None)), policy())  # type: ignore[arg-type]


def test_the_policy_copied_into_an_item_is_what_the_table_of_ia063_says() -> None:
    p = policy()
    expected = {"oficial": ("facts", "summary"), "sinfirma": ("link", "link"), "radio": ("link", "link"), "reservado": ("link", "link")}
    for name, (store_level, publish_level) in expected.items():
        st = p.standing(f"https://{name}.ejemplo.invalid/x")
        assert (source_policy.can_store(st), source_policy.can_publish(st).level) == (store_level, publish_level), name
        assert store_level in vocab.STORE_LEVELS


def test_the_stricter_of_the_copy_and_the_policy_in_force_decides() -> None:
    copy = readers.StoredItem(1, "0" * 64, 1, "https://oficial.ejemplo.invalid/a", "ej-oficial", "oficial.ejemplo.invalid", "Oficial",
                              "verificada_autorizada", "facts", "summary", False, None, None, "es", None, False, False, AT, None, None)
    assert readers.effective_publish(copy) == "summary"
    assert readers.effective_publish(copy, policy()) == "summary"
    assert readers.effective_publish(copy, policy(signed=())) == "link", "the owner took the signature back: only the link"
    radio = readers.StoredItem(**{**{f: getattr(copy, f) for f in readers.StoredItem.__dataclass_fields__},
                                  "canonical_url": "https://radio.ejemplo.invalid/a", "publish_level": "link"})
    assert readers.effective_publish(radio, policy(signed=("ej-oficial", "ej-radio"))) == "link", "a copy never gets more than it had"


def test_a_story_key_is_the_same_for_the_same_seed_and_the_database_accepts_it() -> None:
    key = store.story_key_for("a" * 64)
    assert key == store.story_key_for("a" * 64) and key != store.story_key_for("b" * 64)
    assert store.STORY_KEY_RE.match(key)


def test_a_story_is_withdrawn_only_by_the_owner_and_always_with_a_reason() -> None:
    base = store.Story(story_key="st-ejemplo-01", at=AT, first_seen_at=AT, written_by="moderation-v1")
    with pytest.raises(ValueError, match="owner"):
        store.write_story(NoDatabase(), store.Story(**{**_fields(base), "status": "retirada", "status_reason": "petición"}))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="why"):
        store.write_story(NoDatabase(), store.Story(**{**_fields(base), "status": "en_moderacion"}))  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="story key"):
        store.write_story(NoDatabase(), store.Story(**{**_fields(base), "story_key": "ST 1"}))  # type: ignore[arg-type]


def _fields(story: store.Story) -> dict[str, Any]:
    return {f: getattr(story, f) for f in store.Story.__dataclass_fields__}
