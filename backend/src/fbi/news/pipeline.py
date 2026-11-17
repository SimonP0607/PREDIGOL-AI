"""The news pipeline in shadow (IA-099 to IA-102, plan pieces AD-G02 to AD-G05): ``news-pipeline-v1``. One pass of the worker over
``news.items``: who each new article names, which story it belongs to, the story's category, language, country and level, the rules of
moderation, and - only with its own switch - PrediGol's own text of the stories whose sources allow it.

THE SWITCHES (both born ``off``; any word but ``shadow`` is ``off``):

* ``FBI_NEWS_STORIES`` - ``shadow``: every ``EVERY_MINUTES`` the worker runs ``run_pass``. Writes only ``news.item_entities``,
  ``news.stories``, ``news.item_story`` and ``news.moderation_log`` (all append-only). No model, no web, no key.
* ``FBI_NEWS_TEXT`` (``fbi.news.writer``) - ``shadow``: the same pass also asks the small model for the own text of the stories with at
  least one ELIGIBLE article (authorised and signed, not reserved, ``facts``/``summary``) and facts of it, paid by the LAB, at most
  ``writer.MAX_PER_PASS`` a pass and ``writer.PIECE_MONTHLY_USD`` a month. Writes ``news.story_texts``.

WHAT IT NEVER DOES: read an article's text (there is none in the store), send an outlet's title to a model, show anything (``FBI_NEWS_V2``
is off and the public C-06 is AD-G07's), change the current news page (``FBI_NEWS_FEED`` reads ``ai.evidence`` as before), a probability,
a threshold, a pick or what a reader sees.

INCREMENTAL. A pass takes the articles that are in no story yet (seen in the last ``NEW_SINCE``) and the members of the stories still
open (``grouping.WINDOW``); an article already in a story is never moved by it. A pass that stops half way leaves what it wrote; the next
one goes on from there (each story is its own transaction)."""

from __future__ import annotations

import os
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final, Literal

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fbi.ai import source_policy
from fbi.ai import source_select as ss
from fbi.ai.providers.base import JsonRequest
from fbi.ai.usage import CallOutcome
from fbi.news import anticopy, classify, entities, evidence_reads, grouping, readers, store, writer
from fbi.newsroom import moderation

VERSION: Final = "news-pipeline-v1"
SWITCH: Final = "FBI_NEWS_STORIES"
EVERY_MINUTES: Final = int(os.environ.get("FBI_NEWS_STORIES_MINUTES", "30") or 30)
NEW_SINCE: Final = timedelta(days=7)
MAX_NEW: Final = 1500
WORLD_BACK: Final = timedelta(days=3)
WORLD_AHEAD: Final = timedelta(days=7)

Mode = Literal["off", "shadow"]


def mode(env: Mapping[str, str] | None = None) -> Mode:
    raw = (os.environ if env is None else env).get(SWITCH, "")
    return "shadow" if raw.strip().lower() == "shadow" else "off"


# ── reading ─────────────────────────────────────────────────────────────────────────────────────────────────────────────────

COLUMNS: Final = ("i.id, i.url_sha256, i.content_sha256, i.canonical_url, i.source_domain, i.seen_at, i.published_at, i.source_title, "
                  "i.lang, i.simhash")
UNLINKED_SQL: Final = f"""
SELECT {COLUMNS} FROM news.items i
 WHERE i.seen_at >= %(since)s AND NOT EXISTS (SELECT 1 FROM news.item_story s WHERE s.item_id = i.id)
 ORDER BY i.seen_at, i.id
 LIMIT %(limit)s
"""
"""The articles in no story yet (index ``news_items_seen``; ``news_item_story_item`` for the NOT EXISTS)."""
MEMBERS_SQL: Final = f"""
SELECT {COLUMNS}, l.story_key FROM news.items i
  JOIN LATERAL (SELECT s.story_key, s.active FROM news.item_story s WHERE s.item_id = i.id ORDER BY s.id DESC LIMIT 1) l ON l.active
 WHERE i.seen_at >= %(since)s
"""
"""The members of the stories that may still be open: articles seen in the last two windows, by their newest link."""
WORLD_SQL: Final = ss.CONTEXT_SELECT + """
 WHERE c.is_tracked AND f.kickoff_at BETWEEN %(since)s AND %(until)s
 ORDER BY f.kickoff_at LIMIT 2000
"""
TEAMS_SQL: Final = "SELECT id, name, country, is_national FROM core.teams WHERE id = ANY(%(ids)s)"
SPENT_SQL: Final = "SELECT coalesce(sum(cost_usd), 0) FROM news.story_texts WHERE at >= %(since)s"
SEEN_INPUT_SQL: Final = ("SELECT 1 FROM news.story_texts WHERE story_key = %(key)s AND input_hash = %(hash)s AND prompt_version = %(v)s "
                         "AND outcome IN ('accepted', 'rejected', 'invalid_output') LIMIT 1")
INSERT_TEXT: Final = """
INSERT INTO news.story_texts (story_id, story_key, at, mode, prompt_version, verify_version, anticopy_version, input_hash, fact_ids, outcome,
                              problems, metrics, headline_es, headline_en, summary_es, summary_en, model, usage_id, cost_usd, written_by)
VALUES (%(story_id)s, %(story_key)s, %(at)s, 'shadow', %(prompt)s, %(verify)s, %(anticopy)s, %(hash)s, %(facts)s, %(outcome)s, %(problems)s,
        %(metrics)s, %(headline_es)s, %(headline_en)s, %(summary_es)s, %(summary_en)s, %(model)s, %(usage)s, %(cost)s, %(by)s)
RETURNING id
"""
HEALTH_REASONS: Final = ("medical_detail_unattributed", "medical_detail_not_communicated", "duration_not_communicated")


def _signal(r: Mapping[str, Any], teams: frozenset[int] = frozenset(), players: frozenset[int] = frozenset(),
            claim: str | None = None) -> grouping.ItemSignal:
    return grouping.ItemSignal(int(r["id"]), str(r["url_sha256"]), str(r["content_sha256"]), str(r["source_domain"]), r["seen_at"],
                               r["published_at"], r["source_title"], r["lang"], claim, teams, players,
                               None if r["simhash"] is None else int(r["simhash"]))


def world(conn: psycopg.Connection[Any], at: datetime) -> tuple[dict[frozenset[str], set[int]], dict[int, str]]:
    """The closed world of the linker: the teams of the tracked matches from three days back to seven ahead, with their names."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(WORLD_SQL, {"since": at - WORLD_BACK, "until": at + WORLD_AHEAD})
        rows = cur.fetchall()
    ids = sorted({int(r["home_id"]) for r in rows} | {int(r["away_id"]) for r in rows})
    aliases = ss.team_aliases(conn, ids) if ids else {}
    teams: dict[int, ss.Team] = {}
    for r in rows:
        ctx = ss.context_from_row(r, aliases)
        for t in (ctx.home, ctx.away):
            if t.team_id is not None:
                teams[t.team_id] = t
    return entities.catalogue(teams.values()), {i: t.name for i, t in teams.items()}


def team_facts(conn: psycopg.Connection[Any], ids: Sequence[int]) -> dict[int, classify.TeamFacts]:
    if not ids:
        return {}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(TEAMS_SQL, {"ids": sorted(set(ids))})
        return {int(r["id"]): classify.TeamFacts(r["country"], bool(r["is_national"]), str(r["name"] or "")) for r in cur.fetchall()}


def claim_types(conn: psycopg.Connection[Any], item_ids: Sequence[int], *, typed: bool) -> dict[int, str]:
    """The type of claim of each article from its claims, when it has any (``fbi.news.evidence_reads``)."""
    return evidence_reads.claim_types(conn, item_ids, typed=typed)


# ── the report ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass
class Report:
    mode: str
    at: datetime
    skipped: str | None = None
    new_items: int = 0
    open_members: int = 0
    linked_entities: int = 0
    methods: Counter[str] = field(default_factory=Counter)
    stories_new: int = 0
    stories_revised: int = 0
    stories_unchanged: int = 0
    categories: Counter[str] = field(default_factory=Counter)
    levels: Counter[str] = field(default_factory=Counter)
    touched: int = 0
    with_eligible: int = 0
    text: Counter[str] = field(default_factory=Counter)
    flags: Counter[str] = field(default_factory=Counter)
    cost_usd: Decimal = Decimal(0)
    errors: list[str] = field(default_factory=list)

    def as_json(self) -> dict[str, Any]:
        return {"version": VERSION, "grouper": grouping.VERSION, "classifier": classify.VERSION, "mode": self.mode,
                "at": self.at.isoformat(), "skipped": self.skipped, "new_items": self.new_items, "open_members": self.open_members,
                "linked_entities": self.linked_entities, "methods": dict(sorted(self.methods.items())), "stories_new": self.stories_new,
                "stories_revised": self.stories_revised, "stories_unchanged": self.stories_unchanged, "touched": self.touched,
                "with_eligible_source": self.with_eligible, "categories": dict(sorted(self.categories.items())),
                "levels": dict(sorted(self.levels.items())), "text": dict(sorted(self.text.items())), "flags": dict(sorted(self.flags.items())),
                "cost_usd": str(self.cost_usd), "errors": self.errors[:10]}


# ── the text (FBI_NEWS_TEXT) ────────────────────────────────────────────────────────────────────────────────────────────────

Caller = writer.Caller


def lab_caller(conn: psycopg.Connection[Any], *, at: datetime, settings: Any = None) -> Caller:
    """``call_json`` for the own texts: the small model (tier ``bulk``), the LAB's key and envelope (``lab=True``: nothing is asked when
    the LAB's month does not allow it), the prompt version, the hash of the input."""
    from fbi.ai.config import AiSettings
    from fbi.ai.usage import call_json

    cfg = settings if settings is not None else AiSettings.from_env()

    def call(req: JsonRequest, inp: writer.StoryInput) -> CallOutcome:
        return call_json(conn, cfg, tier="bulk", purpose="other", request=req, at=at, prompt_version=writer.PROMPT_VERSION,
                         input_hash=inp.hash, lab=True, agent="news_text")
    return call


def _month_start(at: datetime) -> datetime:
    return at.replace(day=1, hour=0, minute=0, second=0, microsecond=0)


def spent_this_month(conn: psycopg.Connection[Any], at: datetime) -> Decimal:
    with conn.cursor() as cur:
        cur.execute(SPENT_SQL, {"since": _month_start(at)})
        row = cur.fetchone()
    return Decimal(str(row[0])) if row else Decimal(0)


def record_text(conn: psycopg.Connection[Any], inp: writer.StoryInput, w: writer.Written, *, at: datetime) -> int:
    v = w.verdict
    text = (v.text if v is not None and v.status == "accepted" else None) or {}
    outcome = w.status if w.status in ("accepted", "rejected", "invalid_output", "over_budget", "not_configured", "failed", "timeout",
                                       "refused", "unavailable", "rate_limited", "piece_cap") else "failed"
    with conn.cursor() as cur:
        cur.execute(INSERT_TEXT, {"story_id": inp.story_id, "story_key": inp.story_key, "at": at, "prompt": writer.PROMPT_VERSION,
                                  "verify": writer.VERIFY_VERSION, "anticopy": anticopy.VERSION, "hash": inp.hash,
                                  "facts": Jsonb([] if v is None else v.cited), "outcome": outcome,
                                  "problems": Jsonb([] if v is None else v.problems[:40]), "metrics": Jsonb({} if v is None else v.metrics),
                                  "headline_es": text.get("headline_es"), "headline_en": text.get("headline_en"),
                                  "summary_es": text.get("summary_es"), "summary_en": text.get("summary_en"),
                                  "model": (w.model or None) and str(w.model)[:100], "usage": w.usage_id, "cost": w.cost,
                                  "by": writer.VERIFY_VERSION})
        row = cur.fetchone()
    assert row is not None
    return int(row[0])


def _text_for(conn: psycopg.Connection[Any], key: str, *, at: datetime, policy: source_policy.SourcePolicy | None, typed: bool,
              titles: Sequence[str], names: Sequence[str], call: Caller | None, budget_left: list[int], report: Report,
              text_on: bool) -> None:
    """Moderation rules and - with ``FBI_NEWS_TEXT=shadow`` - the own text of one story."""
    current = readers.story(conn, key)
    if current is None:
        return
    items = readers.story_items(conn, key, public=False)
    ok = [i for i in items if writer.eligible(i, policy)]
    report.with_eligible += int(bool(ok))
    if current.headline_es and not ok:
        if moderation.flag(conn, key, "derechos_retirados", at=at):
            report.flags["derechos_retirados"] += 1
        return
    if not ok:
        report.text["no_eligible_source"] += 1
        return
    if not text_on or call is None:
        report.text["text_off"] += 1
        return
    if current.status != "activa":
        report.text["not_active"] += 1
        return
    facts = writer.facts_of(conn, [i.id for i in ok], typed=typed)
    if not facts:
        report.text["no_facts"] += 1
        return
    inp = writer.StoryInput(key, current.id, current.level or "rumor", current.category or "internacional", current.claim_type or "contexto",
                            tuple(dict.fromkeys(names))[:12], tuple(facts), tuple(t for t in titles if t))
    with conn.cursor() as cur:
        cur.execute(SEEN_INPUT_SQL, {"key": key, "hash": inp.hash, "v": writer.PROMPT_VERSION})
        if cur.fetchone() is not None:
            report.text["same_input"] += 1
            return
    if budget_left[0] <= 0:
        report.text["pass_cap"] += 1
        return
    if spent_this_month(conn, at) >= writer.PIECE_MONTHLY_USD:
        report.text["piece_cap"] += 1
        return
    budget_left[0] -= 1
    w = writer.write(inp, call=call)
    report.cost_usd += w.cost
    report.text[w.status] += 1
    with conn.transaction():
        record_text(conn, inp, w, at=at)
        if w.status == "accepted" and w.verdict is not None and w.verdict.text is not None:
            changes: dict[str, Any] = dict(w.verdict.text)
            store.revise_story(conn, key, at=at, written_by=writer.VERIFY_VERSION, text_version=writer.PROMPT_VERSION, **changes)
            if inp.claim_type in writer.INJURY_TYPES and moderation.flag(conn, key, "texto_lesion", at=at):
                report.flags["texto_lesion"] += 1
        elif w.verdict is not None and any(p.endswith(HEALTH_REASONS) for p in w.verdict.problems) \
                and moderation.flag(conn, key, "salud_rechazado", at=at):
            report.flags["salud_rechazado"] += 1


# ── one pass ────────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _typed(conn: psycopg.Connection[Any]) -> bool:
    try:
        from fbi.ai import gates

        with conn.transaction():
            return gates.typed_visible(conn)
    except Exception:  # a database without the gates' tables: research v2's claims stay hidden, as everywhere
        return False


def run_pass(conn: psycopg.Connection[Any], *, at: datetime, env: Mapping[str, str] | None = None,
             policy: source_policy.SourcePolicy | None = None, linker_world: tuple[dict[frozenset[str], set[int]], dict[int, str]] | None = None,
             call: Caller | None = None, typed: bool | None = None, commit: bool = True) -> Report:
    """One pass (see the module). Does nothing unless ``FBI_NEWS_STORIES=shadow``."""
    report = Report(mode(env), at)
    if report.mode != "shadow":
        report.skipped = "off"
        return report
    pol = policy if policy is not None else source_policy.load(conn)
    seen_typed = _typed(conn) if typed is None else typed
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(UNLINKED_SQL, {"since": at - NEW_SINCE, "limit": MAX_NEW})
        new_rows = cur.fetchall()
        cur.execute(MEMBERS_SQL, {"since": at - 2 * grouping.WINDOW})
        member_rows = cur.fetchall()
    report.new_items, report.open_members = len(new_rows), len(member_rows)
    if not new_rows:
        report.skipped = "nothing_new"
        return report
    ids = [int(r["id"]) for r in new_rows] + [int(r["id"]) for r in member_rows]
    named = readers.item_entities(conn, ids)
    catalogue, team_names = linker_world if linker_world is not None else world(conn, at)
    for r in new_rows:
        iid = int(r["id"])
        if named.get(iid):
            continue
        for n in entities.teams_named(r["source_title"], catalogue, team_names):
            link = store.EntityLink("team", n.team_id, "protagonista", "alias", n.confidence, entities.VERSION, at, n.name_seen)
            if store.link_entity(conn, iid, link).wrote:
                report.linked_entities += 1
            named.setdefault(iid, []).append(readers.Entity("team", n.team_id, "protagonista", "alias", Decimal(str(n.confidence)),
                                                            n.name_seen))
    if commit:
        conn.commit()
    kinds = claim_types(conn, ids, typed=seen_typed)

    def signal(r: Mapping[str, Any]) -> grouping.ItemSignal:
        iid = int(r["id"])
        es = named.get(iid, [])
        return _signal(r, frozenset(e.entity_id for e in es if e.entity_type == "team"),
                       frozenset(e.entity_id for e in es if e.entity_type == "player"), kinds.get(iid))

    members: dict[str, list[grouping.ItemSignal]] = defaultdict(list)
    for r in member_rows:
        members[str(r["story_key"])].append(signal(r))
    open_stories = [grouping.OpenStory(k, list(v)) for k, v in members.items()]
    new = [signal(r) for r in new_rows]
    found = grouping.group(new, open_stories)
    by_id = {s.item_id: s for s in new}
    touched: dict[str, list[grouping.Assignment]] = defaultdict(list)
    for a in found:
        touched[a.story_key].append(a)
        report.methods["new_story" if a.new_story else a.method] += 1
        members[a.story_key].append(by_id[a.item_id])
    report.touched = len(touched)
    facts = team_facts(conn, sorted({t for k in touched for i in members[k] for t in i.teams}))
    text_on = writer.mode(env) == "shadow" and pol is not None
    text_call = call if call is not None else (lab_caller(conn, at=at) if text_on else None)
    budget_left = [writer.MAX_PER_PASS]
    for key, assigned in touched.items():
        items = members[key]
        try:
            cls = classify.classify(items, policy=pol, teams=facts, story_key=key, at=at)
            report.categories[cls.category] += 1
            report.levels[cls.level] += 1
            with conn.transaction():
                if any(a.new_story for a in assigned):
                    first = min(i.seen_at for i in items)
                    w = store.write_story(conn, store.Story(story_key=key, at=at, first_seen_at=min(first, at), written_by=VERSION,
                                                            claim_type=cls.claim_type, category=cls.category, level=cls.level,
                                                            lang=cls.lang, country=cls.country))
                else:
                    w = store.revise_story(conn, key, at=at, written_by=classify.VERSION, **cls.fields())
                report.stories_new += int(w.outcome == "created")
                report.stories_revised += int(w.outcome == "new_version")
                report.stories_unchanged += int(w.outcome == "unchanged")
                for a in assigned:
                    store.link_item_story(conn, a.item_id, key, at=at, method=a.method, grouper_version=grouping.VERSION,  # type: ignore[arg-type]
                                          score=Decimal(str(a.score)))
            names = [facts[t].name for i in items for t in i.teams if t in facts and facts[t].name]
            _text_for(conn, key, at=at, policy=pol, typed=seen_typed, titles=[i.title or "" for i in items], names=names, call=text_call,
                      budget_left=budget_left, report=report, text_on=text_on)
            if commit:
                conn.commit()
        except (psycopg.Error, ValueError) as exc:
            report.errors.append(f"{key}:{type(exc).__name__}:{str(exc)[:120]}")
            if commit:
                conn.rollback()
    return report


__all__ = ["EVERY_MINUTES", "SWITCH", "VERSION", "Report", "claim_types", "lab_caller", "mode", "record_text", "run_pass", "spent_this_month",
           "team_facts", "world"]
