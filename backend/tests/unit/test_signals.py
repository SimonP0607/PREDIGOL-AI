"""The ingestion of signals (IA-085, AD-C03) without a database: the reader of feeds on recorded (synthetic) responses, the canonical URL
of what it stores, the plan by tranches, robots.txt, the Exa plan and its budget, the switch and the worker's wiring.

The feeds in ``tests/fixtures/signals`` are SYNTHETIC: built by hand in the shape of the real ones (WordPress RSS 2.0 of Dimayor and the
FCF, a Google News sitemap...). Both sources are pending of rights in the directory v2, so nothing was downloaded from them; no test here
makes a request."""

from __future__ import annotations

import ast
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

from fbi.ai import source_policy as sp
from fbi.ai import source_select as ss
from fbi.ai import untrusted
from fbi.news import canonical, feeds, signals
from fbi.ops.run_watchdog import timeout_for

FIX = Path(__file__).resolve().parents[1] / "fixtures" / "signals"
AT = datetime(2026, 11, 16, 15, tzinfo=UTC)


def read(name: str) -> bytes:
    return (FIX / name).read_bytes()


# ── the reader of feeds ───────────────────────────────────────────────────────────────────────────────────────────────────

def test_a_wordpress_rss_gives_its_entries_and_nothing_of_their_text() -> None:
    p = feeds.parse(read("dimayor_feed.xml"))
    assert p.kind == "rss" and len(p.entries) == 4
    first = p.entries[0]
    assert first.url == "https://dimayor.com.co/comunicado-programacion-fecha-19-ejemplo/"
    assert first.title == "Comunicado oficial: programación de la fecha 19 (ejemplo)" and first.author == "Prensa Ejemplo"
    assert first.published_at == datetime(2026, 11, 15, 22, 10, tzinfo=UTC) and first.structured and not first.day_only
    assert first.lang == "es"
    assert not any(f.name for f in feeds.Entry.__dataclass_fields__.values() if f.name in ("body", "description", "content", "image"))


def test_a_date_without_time_is_day_only_and_formats_are_read() -> None:
    fcf = feeds.parse(read("fcf_feed.xml")).entries
    assert fcf[2].day_only and fcf[2].published_at == datetime(2026, 11, 15, tzinfo=UTC)
    atom = feeds.parse(read("atom.xml"))
    assert atom.kind == "atom" and atom.entries[0].url == "https://atom.ejemplo.invalid/entrada-1"
    assert atom.entries[0].author == "Autora Ejemplo" and atom.entries[0].published_at == datetime(2026, 11, 16, 8, tzinfo=UTC)
    news = feeds.parse(read("news_sitemap.xml"))
    assert news.kind == "news_sitemap" and news.entries[0].title == "Atlético Nacional viaja a Bucaramanga con dos bajas (ejemplo)"
    assert news.entries[0].published_at == datetime(2026, 11, 16, 17, 30, tzinfo=UTC) and news.entries[1].title is None
    index = feeds.parse(read("sitemap_index.xml"))
    assert index.kind == "sitemap_index" and index.children[1] == "https://dimayor.com.co/post-sitemap2.xml"
    assert feeds.parse_date("no es una fecha") == (None, False) and feeds.parse_date(None) == (None, False)


@pytest.mark.parametrize(("data", "reason"), [(b"", "not_xml"), (b"<html><body>hola</body></html>", "unknown_root"),
                                              (b"x" * (feeds.MAX_BYTES + 1), "too_big")])
def test_what_is_not_a_feed_is_refused(data: bytes, reason: str) -> None:
    with pytest.raises(feeds.FeedError, match=reason):
        feeds.parse(data)


def test_a_document_that_declares_entities_is_refused_before_it_is_parsed() -> None:
    with pytest.raises(feeds.FeedError, match="doctype_or_entity"):
        feeds.parse(read("entity_bomb.xml"))


def test_the_canonical_url_drops_tracking_mobile_and_amp() -> None:
    raw = feeds.parse(read("fcf_feed.xml")).entries[2].url
    assert canonical.canonical_url(raw) == "https://fcf.com.co/parte-medico-ejemplo"
    assert canonical.canonical_url("https://dimayor.com.co/resolucion/?utm_source=rss&utm_medium=rss") == "https://dimayor.com.co/resolucion"
    assert canonical.canonical_url("http://www.m.ejemplo.invalid/a?b=2&a=1&gclid=z#x") == "https://m.ejemplo.invalid/a?a=1&b=2"


# ── robots.txt ────────────────────────────────────────────────────────────────────────────────────────────────────────────

ROBOTS = """User-agent: *
Disallow: /wp-admin/
Allow: /wp-admin/admin-ajax.php
Disallow: /*?s=

User-agent: GPTBot
Disallow: /
"""


def test_robots_our_group_or_star_longest_rule_wins_and_a_tie_is_a_disallow() -> None:
    assert signals.robots_allows(ROBOTS, "https://x.invalid/feed/")
    assert not signals.robots_allows(ROBOTS, "https://x.invalid/wp-admin/x")
    assert signals.robots_allows(ROBOTS, "https://x.invalid/wp-admin/admin-ajax.php")
    assert not signals.robots_allows(ROBOTS, "https://x.invalid/buscar?s=nacional")
    assert not signals.robots_allows("User-agent: PrediGolSignals\nDisallow: /feed\n", "https://x.invalid/feed/")
    assert signals.robots_allows("User-agent: PrediGolSignals\nDisallow: /feed\nUser-agent: *\nDisallow: /\n", "https://x.invalid/a")
    assert not signals.robots_allows("User-agent: *\nAllow: /a\nDisallow: /a\n", "https://x.invalid/a")
    assert signals.robots_allows("", "https://x.invalid/a")


def test_robots_is_read_once_a_day_and_an_unreadable_one_forbids() -> None:
    signals.reset_robots_cache()
    asked: list[str] = []

    def fetch(url: str, headers: object) -> signals.Response:
        asked.append(url)
        return signals.Response(403 if "bloq" in url else 404, {}, b"", 1)

    counter = [0]
    assert signals.robots_verdict(fetch, "https://abierto.invalid/feed/", AT, counter) == (True, "robots_absent")
    assert signals.robots_verdict(fetch, "https://abierto.invalid/otro", AT + timedelta(hours=2), counter)[0]
    assert signals.robots_verdict(fetch, "https://bloq.invalid/feed/", AT, counter) == (False, "robots_unreadable:403")
    assert asked == ["https://abierto.invalid/robots.txt", "https://bloq.invalid/robots.txt"] and counter == [2]
    signals.robots_verdict(fetch, "https://abierto.invalid/feed/", AT + timedelta(hours=25), counter)
    assert asked[-1] == "https://abierto.invalid/robots.txt" and counter == [3]
    signals.reset_robots_cache()


# ── the plan ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

def test_the_tranches_and_the_backoff_of_a_failing_feed() -> None:
    assert signals.interval("le6h", official=True) == timedelta(minutes=30)
    assert signals.interval("le6h", official=False) == timedelta(minutes=60)
    assert signals.interval("6_36h", official=True) == timedelta(hours=2)
    assert signals.interval("36h_7d", official=False) == timedelta(hours=8)
    assert signals.interval("none", official=True) == timedelta(hours=24)
    assert signals.interval("le6h", official=True, failures=1) == timedelta(hours=1)
    assert signals.interval("le6h", official=True, failures=3) == timedelta(hours=4)
    assert signals.interval("none", official=False, failures=9) == timedelta(days=7), "a feed that fails is read less, at most weekly"
    state = signals.FeedState(AT, "read", None, None, None, 0, AT + timedelta(minutes=30), None)
    assert not signals.is_due(state, AT + timedelta(minutes=29)) and signals.is_due(state, AT + timedelta(minutes=30))
    assert signals.is_due(None, AT)


def test_the_feeds_of_the_directory() -> None:
    cat = ss.bundled_catalog()
    targets = signals.targets(cat)
    by_url = {t.url: t for t in targets}
    assert by_url["https://dimayor.com.co/feed/"].source_id == "liga-dimayor" and by_url["https://dimayor.com.co/feed/"].official
    assert by_url["https://fcf.com.co/feed/"].kind == "rss"
    assert by_url["https://www.deportesrcn.com/sitemapnews"].kind == "news_sitemap"
    assert sum(1 for t in targets if t.kind == "rss") >= 100, "the directory v2 has 102 open and confirmed RSS feeds and more"
    assert len({t.url for t in targets}) == len(targets)


def test_today_no_feed_is_readable_and_reserved_or_blocked_ones_are_never_planned() -> None:
    pol = sp.load(None)
    assert pol is not None
    readable, never, would = 0, 0, 0
    for t in signals.targets(ss.bundled_catalog()):
        st = pol.standing(t.url)
        if signals.never_read(st, t):
            never += 1
            assert not sp.can_fetch(st).allowed
        elif sp.can_fetch(st).allowed:
            readable += 1
        else:
            would += 1
    assert readable == 0, "nobody has signed: nothing is read today"
    assert never > 0 and would > 100


def test_a_title_naming_a_team_with_a_match_soon_asks_for_its_body() -> None:
    ctx = ss.MatchContext(1, AT + timedelta(hours=20), "Primera A", "Colombia", ss.Team(1, "Bucaramanga", (), "Colombia"),
                          ss.Team(2, "Atletico Nacional", (), "Colombia"))
    keys = signals.followed_keys([ctx], AT)
    assert signals.wants_body("Atlético Nacional viaja a Bucaramanga con dos bajas", keys)
    assert not signals.wants_body("Millonarios presenta a su nuevo técnico", keys)
    assert not signals.followed_keys([ctx], AT, within=timedelta(hours=6))


def test_a_title_that_gives_an_order_is_flagged_and_changes_no_query() -> None:
    title = feeds.parse(read("fcf_feed.xml")).entries[1].title
    assert title is not None and untrusted.sanitize(title, origin="fcf.com.co", max_chars=300).instruction_like
    ctx = ss.MatchContext(1, AT + timedelta(hours=20), "Friendlies", "World", ss.Team(1, "Chile", (), "Chile", None, True),
                          ss.Team(2, "Colombia", (), "Colombia", None, True))
    pol = sp.load(None)
    before = signals.plan_exa([ctx], ss.bundled_catalog(), pol, at=AT, exa=ss.ExaAllowance.of(True, Decimal(1), Decimal(35)))
    assert "apuestas" not in repr(before) and "instrucciones" not in repr(before)
    assert signals.plan_exa.__code__.co_varnames[:6] == ("contexts", "catalog", "policy", "at", "exa", "claims"), \
        "the plan takes no text read from a feed"


# ── Exa only for gaps ─────────────────────────────────────────────────────────────────────────────────────────────────────

def _vanguardia_signed() -> sp.SourcePolicy:
    from dataclasses import replace

    pol = sp.load(None)
    assert pol is not None
    sources = [replace(s, state="verificada_autorizada", automated_access="permitido_robots") if s.source_id == "vanguardia" else s
               for s in pol.by_domain.values()]
    return sp.SourcePolicy(sources, list(pol.rules.values()), ["vanguardia"], directory_version="t", exclusion_version="t", origin="t")


def _buc(hours: float) -> ss.MatchContext:
    return ss.MatchContext(31688, AT + timedelta(hours=hours), "Primera A", "Colombia",
                           ss.Team(3905, "Bucaramanga", ("BUC",), "Colombia", "Bucaramanga"),
                           ss.Team(3911, "Atletico Nacional", ("NAC",), "Colombia", "Medellín"))


def test_exa_is_planned_only_for_matches_of_the_next_36_hours_at_most_one_per_match_and_never_run() -> None:
    pol = _vanguardia_signed()
    exa = ss.ExaAllowance.of(True, Decimal("12.92"), Decimal(35))
    plan = signals.plan_exa([_buc(20), _buc(100)], ss.bundled_catalog(), pol, at=AT, exa=exa)
    assert plan.matches == 1 and len(plan.queries) == 1 <= signals.MAX_EXA_PER_MATCH
    fid, q = plan.queries[0]
    assert fid == 31688 and q.include_domains == ("vanguardia.com",)
    j = plan.as_json()
    assert j["executed"] == 0 and j["per_match"] == 1.0 < j["baseline_per_match"] and j["usd"] == "0.015"


def test_exa_is_not_planned_at_95_percent_of_its_envelope_nor_today() -> None:
    cut = signals.plan_exa([_buc(20)], ss.bundled_catalog(), _vanguardia_signed(), at=AT,
                           exa=ss.ExaAllowance.of(True, Decimal("33.25"), Decimal(35)))
    assert cut.queries == () and cut.allowance == "cut_at_95"
    today = signals.plan_exa([_buc(20)], ss.bundled_catalog(), sp.load(None), at=AT,
                             exa=ss.ExaAllowance.of(True, Decimal(1), Decimal(35)))
    assert today.queries == () and today.would_if_signed > 0


# ── the switch and the worker ─────────────────────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(("raw", "mode"), [("", "off"), ("off", "off"), ("on", "off"), ("1", "off"), ("shadow", "shadow"),
                                           (" Shadow ", "shadow")])
def test_only_the_word_shadow_switches_it_on(raw: str, mode: str) -> None:
    assert signals.mode({signals.SWITCH: raw}) == mode
    assert signals.mode({}) == "off"


def test_a_pass_while_off_touches_nothing() -> None:
    class NoConn:
        def __getattr__(self, name: str) -> object:
            raise AssertionError("no database while off")

    r = signals.run_pass(NoConn(), at=AT, env={})  # type: ignore[arg-type]
    assert r.skipped == "off" and r.requests == 0


def test_the_worker_schedules_it_only_in_shadow_with_a_deadline_and_never_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    from apps.worker import scheduler

    tree = ast.parse(Path(scheduler.__file__).read_text())
    found = [(str(n.args[0].value), str(n.args[1].value)) for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "_deadline"
             and isinstance(n.args[0], ast.Constant) and isinstance(n.args[1], ast.Constant)]
    assert ("signals_ingest", "signals_ingest") in found
    assert timeout_for("signals_ingest") == timedelta(minutes=20)
    assert "signals_ingest" in scheduler.WORKER_JOB_TYPES
    guarded = False
    for node in ast.walk(tree):
        if isinstance(node, ast.If) and isinstance(node.test, ast.Compare) and isinstance(node.test.left, ast.Call) \
                and isinstance(node.test.left.func, ast.Attribute) and node.test.left.func.attr == "mode" \
                and isinstance(node.test.left.func.value, ast.Name) and node.test.left.func.value.id == "signals":
            body = ast.Module(body=node.body, type_ignores=[])
            guarded = guarded or any(isinstance(n, ast.Constant) and n.value == "signals_ingest" for n in ast.walk(body))
    assert guarded, "the job is registered only while FBI_SIGNALS is shadow"
    monkeypatch.delenv(signals.SWITCH, raising=False)
    monkeypatch.setattr(scheduler, "_connect", lambda: (_ for _ in ()).throw(AssertionError("no connection while off")))
    scheduler._signals_now()
    monkeypatch.setenv(signals.SWITCH, "shadow")
    monkeypatch.setattr(scheduler, "_connect", lambda: (_ for _ in ()).throw(RuntimeError("database down")))
    scheduler._signals_now()  # logged, never raised


def test_nothing_in_the_ingestion_calls_a_model_or_exa() -> None:
    src = (Path(signals.__file__).read_text() + Path(feeds.__file__).read_text() + Path(ss.__file__).read_text())
    for word in ("fbi.ai.providers", "call_json", "LlmProvider", "fbi.analyst.search", "exa_search", "anthropic"):
        assert word not in src, word
