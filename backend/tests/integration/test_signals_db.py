"""The ingestion of signals against PostgreSQL (IA-085, AD-C03): a pass in shadow over recorded (synthetic) feeds, with a fictitious
registry in which Dimayor and the FCF are authorised AND signed (in the real directory v2 both are pending of rights: nothing is read
from them). What it checks: what is written to ``news.items`` (titles, dates, links - never a body), the reading state in
``news.feed_reads`` (ETag, Last-Modified, the body's hash, failures, the next read), the conditional request, the incremental read,
the «habría leído» of a pending source (no request, a row of ``ai.source_policy_log``), robots.txt, a failing feed, the adversarial
title and the append-only table.

Every test runs in one transaction rolled back at the end (``commit=False``)."""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg
import pytest

from fbi.ai import source_policy as sp
from fbi.ai import source_registry as registry
from fbi.ai import source_select as ss
from fbi.news import canonical, signals

pytestmark = pytest.mark.integration
FIX = Path(__file__).resolve().parents[1] / "fixtures" / "signals"
AT = datetime(2026, 11, 16, 15, tzinfo=UTC)
ON = {signals.SWITCH: "shadow"}
DIMAYOR = "https://dimayor.com.co/feed/"
FCF = "https://fcf.com.co/feed/"
LAFM = "https://www.lafm.com.co/rss/deportes.xml"


def world() -> tuple[sp.SourcePolicy, ss.Catalog]:
    """Three sources of the directory v2: Dimayor and the FCF made authorised and signed (fictitious), La FM as it is (pending)."""
    by_id = {s.source_id: s for s in registry.bundled_directory().sources}
    authorised = [replace(by_id[i], state="verificada_autorizada", automated_access="permitido_robots",
                          record={**by_id[i].record, "estado_verificacion": "verificada_autorizada"}) for i in ("liga-dimayor", "fed-colombia")]
    sources = [*authorised, by_id["co-lafm"]]
    pol = sp.SourcePolicy(sources, (), ("liga-dimayor", "fed-colombia"), directory_version="dir-ficticio-1", exclusion_version="excl-1",
                          origin="db")
    return pol, ss.Catalog.of("dir-ficticio-1", sources)


class Server:
    """The recorded web: a response per URL (a list is served in order), and every request it was asked."""

    def __init__(self, routes: Mapping[str, Any]) -> None:
        self.routes = {k: (list(v) if isinstance(v, list) else [v]) for k, v in routes.items()}
        self.asked: list[tuple[str, dict[str, str]]] = []

    def __call__(self, url: str, headers: Mapping[str, str]) -> signals.Response:
        self.asked.append((url, dict(headers)))
        queue = self.routes.get(url)
        if not queue:
            return signals.Response(404, {}, b"", 1)
        r = queue.pop(0) if len(queue) > 1 else queue[0]
        assert isinstance(r, signals.Response)
        return r

    def urls(self) -> list[str]:
        return [u for u, _ in self.asked]


def ok(name: str, etag: str = '"v1"', modified: str = "Sun, 15 Nov 2026 22:10:00 GMT") -> signals.Response:
    return signals.Response(200, {"ETag": etag, "Last-Modified": modified}, (FIX / name).read_bytes(), 12)


ROBOTS_OK = signals.Response(200, {}, b"User-agent: *\nDisallow: /wp-admin/\n", 3)


@pytest.fixture
def conn(migrated_database: str) -> Iterator[psycopg.Connection[Any]]:
    signals.reset_robots_cache()
    with psycopg.connect(migrated_database) as c:
        c.execute("SELECT 1")
        yield c
        c.rollback()
    signals.reset_robots_cache()


def run(conn: psycopg.Connection[Any], server: Server, at: datetime = AT, **kw: Any) -> signals.Report:
    pol, cat = world()
    return signals.run_pass(conn, at=at, fetch=server, policy=pol, catalog=cat, contexts=kw.pop("contexts", []), commit=False,
                            env=ON, sleep=lambda s: None, **kw)


def reads(conn: psycopg.Connection[Any], url: str) -> list[dict[str, Any]]:
    from psycopg.rows import dict_row

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT * FROM news.feed_reads WHERE url_sha256 = %s ORDER BY at, id", (canonical.sha256_hex(url),))
        return list(cur.fetchall())


def items(conn: psycopg.Connection[Any], domain: str) -> list[tuple[Any, ...]]:
    return conn.execute("SELECT canonical_url, source_title, published_at, published_structured, found_via, store_level, publish_level, "
                        "source_state, feed_id, written_by FROM news.items WHERE source_domain = %s ORDER BY published_at DESC NULLS LAST",
                        (domain,)).fetchall()


def test_a_first_pass_reads_the_signed_feeds_and_only_records_what_it_would_read_of_the_pending_one(
        conn: psycopg.Connection[Any]) -> None:
    server = Server({"https://dimayor.com.co/robots.txt": ROBOTS_OK, DIMAYOR: ok("dimayor_feed.xml"),
                     "https://fcf.com.co/robots.txt": ROBOTS_OK, FCF: ok("fcf_feed.xml", etag='"f1"')})
    r = run(conn, server)
    assert r.skipped is None and r.readable == 2 and r.would_read == 1 and r.outcomes == {"read": 2, "would_read": 1}
    assert LAFM not in server.urls() and not any("lafm" in u for u in server.urls()), "a pending source is never asked"
    rows = items(conn, "dimayor.com.co")
    assert [x[0] for x in rows] == ["https://dimayor.com.co/comunicado-programacion-fecha-19-ejemplo",
                                    "https://dimayor.com.co/resolucion-disciplinaria-fecha-18-ejemplo",
                                    "https://dimayor.com.co/designacion-arbitral-bucaramanga-nacional-ejemplo"]
    assert rows[0][1:7] == ("Comunicado oficial: programación de la fecha 19 (ejemplo)", datetime(2026, 11, 15, 22, 10, tzinfo=UTC),
                                True, "rss", "facts", "summary")
    assert rows[0][7] == "verificada_autorizada" and rows[0][8] is not None and rows[0][9] == "signals-v1"
    assert r.foreign == 1, "the entry of another site is not stored under Dimayor"
    body = conn.execute("SELECT count(*) FROM information_schema.columns WHERE table_schema = 'news' AND table_name = 'items' "
                        "AND column_name ~ '^(body|text|content|description|image|picture|excerpt|summary)$'").fetchone()
    assert body is not None and body[0] == 0, "there is nowhere to keep a body or a picture"
    d = reads(conn, DIMAYOR)
    assert len(d) == 1 and d[0]["outcome"] == "read" and d[0]["etag"] == '"v1"' and d[0]["created"] == 3 and d[0]["entries"] == 4
    assert d[0]["next_due_at"] == AT + timedelta(hours=24) and d[0]["band"] == "none" and d[0]["failures"] == 0
    lafm = reads(conn, LAFM)
    assert [x["outcome"] for x in lafm] == ["would_read"] and lafm[0]["reason"] == "not_authorised:verificada_pendiente_derechos"
    assert lafm[0]["http_status"] is None and lafm[0]["entries"] == 0
    log = conn.execute("SELECT path, action, outcome, hard, source_id FROM ai.source_policy_log WHERE url = %s", (LAFM,)).fetchall()
    assert log == [("ingest", "fetch", "would_block", False, "co-lafm")]
    assert r.exa["executed"] == 0


def test_the_next_read_is_conditional_and_a_304_or_the_same_body_writes_no_item(conn: psycopg.Connection[Any]) -> None:
    server = Server({"https://dimayor.com.co/robots.txt": ROBOTS_OK, "https://fcf.com.co/robots.txt": ROBOTS_OK,
                     DIMAYOR: [ok("dimayor_feed.xml"), signals.Response(304, {}, b"", 5), ok("dimayor_feed.xml", etag='"v1b"')],
                     FCF: ok("fcf_feed.xml")})
    run(conn, server)
    before = len(items(conn, "dimayor.com.co"))
    assert run(conn, server, AT + timedelta(hours=1)).due == 0, "not due again before its interval"
    run(conn, server, AT + timedelta(hours=25))
    conditional = [h for u, h in server.asked if u == DIMAYOR][1]
    assert conditional == {"If-None-Match": '"v1"', "If-Modified-Since": "Sun, 15 Nov 2026 22:10:00 GMT"}
    run(conn, server, AT + timedelta(hours=50))
    outcomes = [x["outcome"] for x in reads(conn, DIMAYOR)]
    assert outcomes == ["read", "not_modified", "unchanged"], "the same body (another ETag) is not parsed again"
    assert len(items(conn, "dimayor.com.co")) == before
    last = reads(conn, DIMAYOR)[-1]
    assert last["etag"] == '"v1b"' and last["body_sha256"] == reads(conn, DIMAYOR)[0]["body_sha256"]


def test_a_new_body_writes_only_what_is_new(conn: psycopg.Connection[Any]) -> None:
    server = Server({"https://dimayor.com.co/robots.txt": ROBOTS_OK, "https://fcf.com.co/robots.txt": ROBOTS_OK,
                     DIMAYOR: [ok("dimayor_feed.xml"), ok("dimayor_feed_v2.xml", etag='"v2"')], FCF: ok("fcf_feed.xml")})
    run(conn, server)
    r = run(conn, server, AT + timedelta(hours=25))
    last = reads(conn, DIMAYOR)[-1]
    assert (last["outcome"], last["created"], last["unchanged"], last["entries"]) == ("read", 1, 1, 5)
    assert last["newest_published_at"] == datetime(2026, 11, 16, 14, tzinfo=UTC)
    assert r.older == 2, "entries older than the newest one already seen are not written again"
    assert len(items(conn, "dimayor.com.co")) == 4


def test_a_failing_feed_is_read_less_and_never_by_another_route(conn: psycopg.Connection[Any]) -> None:
    server = Server({"https://dimayor.com.co/robots.txt": ROBOTS_OK, "https://fcf.com.co/robots.txt": ROBOTS_OK,
                     DIMAYOR: signals.Response(403, {}, b"", 4), FCF: signals.Response(429, {"Retry-After": "86400"}, b"", 4)})
    run(conn, server)
    d, f = reads(conn, DIMAYOR)[-1], reads(conn, FCF)[-1]
    assert (d["outcome"], d["http_status"], d["failures"], d["reason"]) == ("failed", 403, 1, "http_403")
    assert d["next_due_at"] == AT + timedelta(hours=48), "one failure doubles the interval"
    assert f["next_due_at"] == AT + timedelta(hours=48) and f["failures"] == 1
    assert [u for u in server.urls() if "dimayor" in u] == ["https://dimayor.com.co/robots.txt", DIMAYOR], "no retry, no other route"


def test_robots_that_forbid_the_feed_mean_it_is_not_asked(conn: psycopg.Connection[Any]) -> None:
    server = Server({"https://dimayor.com.co/robots.txt": signals.Response(200, {}, b"User-agent: *\nDisallow: /feed/\n", 2),
                     "https://fcf.com.co/robots.txt": signals.Response(500, {}, b"", 2), DIMAYOR: ok("dimayor_feed.xml"),
                     FCF: ok("fcf_feed.xml")})
    run(conn, server)
    assert DIMAYOR not in server.urls() and FCF not in server.urls()
    assert reads(conn, DIMAYOR)[-1]["reason"] == "robots_disallows" and reads(conn, FCF)[-1]["reason"] == "robots_unreadable:500"
    assert {reads(conn, u)[-1]["outcome"] for u in (DIMAYOR, FCF)} == {"robots"}


def test_an_adversarial_title_is_data_flagged_and_changes_nothing_the_pass_plans(conn: psycopg.Connection[Any]) -> None:
    ctx = ss.MatchContext(1, AT + timedelta(hours=20), "Friendlies", "World", ss.Team(1, "Chile", (), "Chile", None, True),
                          ss.Team(2, "Colombia", (), "Colombia", None, True))
    pol, cat = world()
    expected = signals.plan_exa([ctx], cat, pol, at=AT).as_json()
    server = Server({"https://fcf.com.co/robots.txt": ROBOTS_OK, "https://dimayor.com.co/robots.txt": ROBOTS_OK,
                     DIMAYOR: ok("dimayor_feed.xml"), FCF: ok("fcf_feed.xml")})
    r = run(conn, server, contexts=[ctx])
    assert r.instruction_like == 1 and r.exa == expected
    stored = conn.execute("SELECT source_title FROM news.items WHERE canonical_url = 'https://fcf.com.co/nota-adversaria-ejemplo'").fetchone()
    assert stored is not None and "instrucciones" in stored[0], "kept as data, as it came"
    assert not any("apuestas" in u or "exa" in u for u in server.urls()), "no request follows from a title"
    assert r.body_candidates >= 1, "the call-up of Colombia names a team with a match in 36 h"


def test_without_a_registry_nothing_is_read(conn: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sp, "load", lambda c: None)
    server = Server({})
    r = signals.run_pass(conn, at=AT, fetch=server, contexts=[], commit=False, env=ON)
    assert r.skipped == "registry_unavailable" and server.asked == []


def test_feed_reads_is_append_only(conn: psycopg.Connection[Any]) -> None:
    run(conn, Server({"https://dimayor.com.co/robots.txt": ROBOTS_OK, DIMAYOR: ok("dimayor_feed.xml")}))
    with pytest.raises(psycopg.Error), conn.transaction():
        conn.execute("UPDATE news.feed_reads SET failures = 9")
    with pytest.raises(psycopg.Error), conn.transaction():
        conn.execute("DELETE FROM news.feed_reads")
    with pytest.raises(psycopg.errors.CheckViolation), conn.transaction():
        conn.execute("INSERT INTO news.feed_reads (feed_id, url_sha256, source_id, at, mode, outcome, band, next_due_at, reader_version, "
                     "registry_version, http_status) SELECT id, url_sha256, 'x', now(), 'shadow', 'would_read', 'none', now() + interval '1 h', "
                     "'signals-v1', 'r', 200 FROM news.feeds LIMIT 1")


def test_upcoming_contexts_read_the_tracked_matches(conn: psycopg.Connection[Any]) -> None:
    assert signals.upcoming_contexts(conn, AT) == [] or all(isinstance(c, ss.MatchContext) for c in signals.upcoming_contexts(conn, AT))
    assert signals.latest_states(conn) == {}
