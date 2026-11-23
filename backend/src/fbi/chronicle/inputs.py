"""What the content plan of a match is made from, read from the database (IA-103): read-only SELECTs on the caller's connection.

    the story         ``fbi.api.services.reading.reading_basis`` and ``fbi.api.services.story.story_of`` - the very functions the readers'
                      chronicle is written from (the newest packet known by ``at``, the results settled by the packet's moment)
    the news          the packet's web evidence, BY REFERENCE: id, status, kind, side, outlet, its two moments and its content hash; whether
                      a model may read its source is the directory's word (``fbi.ai.source_policy.can_extract``: closed on failure)
    the scenarios     the newest ``scenarios-v2`` reading of the match's competition season computed by ``at`` and not older than
                      ``SCENARIOS_MAX_AGE`` (``intel.scenario_readings``, IA-082)
    the figures       the single figure ``forecast-v2`` as of ``at`` (``fbi.api.services.match_intelligence.read_figures``: the private
                      C-01's reader; a match the models do not cover has none)
    the previous plan the keys of the newest plan stored for the match (``ai.chronicles``): what it did not have is new
    the C-13 sheet    with ``FBI_CHRONICLE_STAT_SHEET`` on only (PM-11-07, ``fbi.chronicle.stat_sheet``): each side's statistics document of
                      the match's competition season, the figures its profile shows (``analytics.stat_documents``)
    the corpus        the recent chronicles of other matches and each team's previous one (``ai.chronicles``), for the rule of stock
                      phrases and repetitions (``fbi.chronicle.repetition``, IA-117)

``claims_for`` joins, for the writer only, PrediGol's own claim of each planned news item (``ai.evidence.claim``, by id AND content hash: an
item rewritten since is not told).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from datetime import datetime, timedelta
from typing import Any, Final

import psycopg
import structlog
from psycopg.rows import dict_row

from fbi.ai import source_policy
from fbi.ai.final_reread import parse_moment
from fbi.ai.gates import typed_visible
from fbi.api.services import reading as reading_service
from fbi.api.services import story as story_service
from fbi.chronicle import plan as cp
from fbi.chronicle import repetition, stat_sheet
from fbi.protosign import store as signatures

log = structlog.get_logger(__name__)

SCENARIOS_MAX_AGE: Final = timedelta(days=3)
"""The engine writes a reading every six hours in shadow: an older one is not «what is at stake now»."""
CLAIM_MAX: Final = 600

PACKET_NEWS_SQL: Final = """
SELECT (e->>'id')::bigint AS id, e->>'status' AS status, e->>'kind' AS kind, e->>'side' AS side, e->>'source' AS source,
       e->>'url' AS url, e->>'retrieved_at' AS retrieved_at, e->>'published_at' AS published_at
  FROM ai.match_packets p, jsonb_array_elements(CASE WHEN jsonb_typeof(p.content->'evidence') = 'array'
                                                     THEN p.content->'evidence' ELSE '[]'::jsonb END) e
 WHERE p.id = %(packet)s AND e->>'origin' = 'web' AND (e->>'id') ~ '^[0-9]+$'
"""
"""The packet's web news by reference (never the provider's reports or the owner's notes): one packet by its key."""

HASHES_SQL: Final = ("SELECT id, content_hash, fixture_id FROM ai.evidence WHERE id = ANY(%(ids)s) "
                     "AND (subject_type IS NULL OR %(typed)s)")
"""By id, the items the packet names - and a claim of research v2 only while it is ``on`` (``fbi.ai.gates.typed_visible``)."""

SEASON_SQL: Final = "SELECT competition_season_id FROM core.fixtures WHERE id = %(f)s"

SCENARIOS_SQL: Final = """
SELECT reading FROM intel.scenario_readings
 WHERE competition_season_id = %(cs)s AND computed_at <= %(at)s AND computed_at > %(since)s
 ORDER BY computed_at DESC, id DESC LIMIT 1
"""
"""Through ``intel_scenario_readings_season`` (competition season, id DESC)."""

PREVIOUS_SQL: Final = "SELECT plan FROM ai.chronicles WHERE fixture_id = %(f)s AND plan_at <= %(at)s ORDER BY id DESC LIMIT 1"

CLAIMS_SQL: Final = "SELECT id, claim, content_hash FROM ai.evidence WHERE id = ANY(%(ids)s) AND (subject_type IS NULL OR %(typed)s)"


def _rows(conn: psycopg.Connection[Any], sql: str, params: Mapping[str, Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def news_of(conn: psycopg.Connection[Any], packet_id: int, fixture_id: int) -> tuple[cp.NewsIn, ...]:
    rows = _rows(conn, PACKET_NEWS_SQL, {"packet": packet_id})
    if not rows:
        return ()
    stored = {int(r["id"]): r for r in _rows(conn, HASHES_SQL, {"ids": [int(r["id"]) for r in rows], "typed": typed_visible(conn)})}
    try:
        policy = source_policy.load(conn)
    except Exception:  # the directory cannot be read: no source may reach a model (closed on failure)
        log.warning("chronicle_v4.policy_unreadable", exc_info=True)
        policy = None
    out = []
    for r in rows:
        row = stored.get(int(r["id"]))
        if row is None or (row["fixture_id"] is not None and int(row["fixture_id"]) != fixture_id):
            continue  # not in ai.evidence any more, or about another match: never cited
        may = policy is not None and source_policy.can_extract(policy.standing(r["url"])).allowed
        out.append(cp.NewsIn(int(r["id"]), str(r["status"] or ""), str(r["kind"] or "other"), r["side"] if r["side"] in ("home", "away")
                             else None, " ".join(str(r["source"]).split())[:60] if r["source"] else None, parse_moment(r["retrieved_at"]),
                             parse_moment(r["published_at"]), str(row["content_hash"]) if row["content_hash"] else None, may))
    return tuple(out)


def scenarios_of(conn: psycopg.Connection[Any], fixture_id: int, at: datetime) -> Mapping[str, Any] | None:
    season = _rows(conn, SEASON_SQL, {"f": fixture_id})
    if not season or season[0]["competition_season_id"] is None:
        return None
    found = _rows(conn, SCENARIOS_SQL, {"cs": int(season[0]["competition_season_id"]), "at": at, "since": at - SCENARIOS_MAX_AGE})
    reading = found[0]["reading"] if found else None
    return reading if isinstance(reading, Mapping) else None


def figures_of(conn: psycopg.Connection[Any], fixture_id: int, at: datetime) -> tuple[cp.FigureIn, ...]:
    from fbi.api.services.match_intelligence import read_figures

    found, _missing = read_figures(conn, fixture_id, at=at)
    if found is None:
        return ()
    out = []
    for g in found.figures.values():
        out.append(cp.FigureIn(g.reading_id, g.market_key, g.selection, float(g.line), float(g.p), str(g.label), g.version))
    return tuple(out)


def previous_keys(conn: psycopg.Connection[Any], fixture_id: int, at: datetime, current: frozenset[str]) -> frozenset[str]:
    """``plan.previous_for`` the newest plan stored for the match by ``at``."""
    rows = _rows(conn, PREVIOUS_SQL, {"f": fixture_id, "at": at})
    return cp.previous_for(current, rows[0]["plan"] if rows and isinstance(rows[0]["plan"], Mapping) else None)


def sheet_of(conn: psycopg.Connection[Any], fixture_id: int, *, home_id: int, away_id: int,
             sheet: bool | None = None) -> dict[str, stat_sheet.SideSheet] | None:
    """PM-11-07: the C-13 sheet of both sides while ``FBI_CHRONICLE_STAT_SHEET`` is on (``sheet`` forces it either way), else None."""
    wanted = stat_sheet.mode() == "on" if sheet is None else sheet
    return stat_sheet.read(conn, fixture_id, home_id=home_id, away_id=away_id) if wanted else None


def plan_input(conn: psycopg.Connection[Any], fixture_id: int, *, at: datetime, figures: bool = True,
               sheet: bool | None = None) -> cp.PlanInput | str:
    """Everything the plan of a match at ``at`` is made from, or why there is nothing (a code): ``no_packet``. ``sheet``: the C-13 sheet
    forced on or off (None: ``FBI_CHRONICLE_STAT_SHEET`` decides)."""
    basis = reading_service.reading_basis(conn, fixture_id, at=at)
    if basis.packet_id is None or basis.data_at is None:
        return "no_packet"
    fx = basis.fixture
    told = story_service.story_of(conn, content=basis.content, home_id=int(fx["home_team_id"]), away_id=int(fx["away_team_id"]),
                                  kickoff=fx["kickoff_at"], data_at=basis.data_at)
    block = basis.content.get("fixture") if isinstance(basis.content.get("fixture"), Mapping) else {}
    home = str((block.get("home") or {}).get("name") or fx["home_name"]) if isinstance(block, Mapping) else str(fx["home_name"])
    away = str((block.get("away") or {}).get("name") or fx["away_name"]) if isinstance(block, Mapping) else str(fx["away_name"])
    competition = str(block.get("competition") or fx["competition"]) if isinstance(block, Mapping) else str(fx["competition"])
    lineups = basis.content.get("lineups")
    first = cp.PlanInput(
        fixture_id=fixture_id, at=at, home=home, away=away, competition=competition, home_team_id=int(fx["home_team_id"]),
        away_team_id=int(fx["away_team_id"]), packet_id=basis.packet_id, data_at=basis.data_at, story=told.facts, thin=told.thin,
        news=news_of(conn, basis.packet_id, fixture_id),
        lineups_confirmed=bool(lineups.get("confirmed")) if isinstance(lineups, Mapping) else None,
        scenarios=scenarios_of(conn, fixture_id, at), figures=figures_of(conn, fixture_id, at) if figures else (),
        sheet=sheet_of(conn, fixture_id, home_id=int(fx["home_team_id"]), away_id=int(fx["away_team_id"]), sheet=sheet))
    return replace(first, previous=previous_keys(conn, fixture_id, at, cp.keys(cp.build(first))))


RECENT_SQL: Final = """
SELECT DISTINCT ON (c.fixture_id) c.id, c.metrics
  FROM ai.chronicles c
 WHERE c.created_at > %(since)s AND c.created_at <= %(at)s AND c.fixture_id <> %(f)s AND c.status IN ('ok', 'partial')
   AND c.route <> 'none'
 ORDER BY c.fixture_id, c.id DESC
 LIMIT %(limit)s
"""
"""The newest chronicle of each OTHER match of the window (``ai_chronicles_created``; a line-up update, ``route = 'none'``, is no new text)."""
TEAM_SQL: Final = """
SELECT c.id, c.metrics
  FROM ai.chronicles c
 WHERE c.created_at > %(since)s AND c.created_at <= %(at)s AND c.fixture_id <> %(f)s AND c.status IN ('ok', 'partial')
   AND c.route <> 'none' AND (c.plan->'match'->>'home' = %(team)s OR c.plan->'match'->>'away' = %(team)s)
 ORDER BY c.created_at DESC, c.id DESC
 LIMIT 1
"""
"""The previous chronicle of one team (by the name its plan carries), in another match."""


def repetition_corpus(conn: psycopg.Connection[Any], plan: cp.ContentPlan, *, at: datetime) -> repetition.Corpus:
    """What ``fbi.chronicle.repetition`` compares a chronicle with: the recent chronicles of other matches and each team's previous one."""
    since = at - timedelta(days=repetition.WINDOW_DAYS)
    recent = _rows(conn, RECENT_SQL, {"since": since, "at": at, "f": plan.fixture_id, "limit": repetition.CORPUS_LIMIT})
    previous: dict[str, Mapping[str, Any]] = {}
    for side, team in (("home", plan.home), ("away", plan.away)):
        found = _rows(conn, TEAM_SQL, {"since": since, "at": at, "f": plan.fixture_id, "team": team})
        if found:
            previous[side] = found[0]
    return replace(repetition.corpus_of(recent, previous), signed=signatures.is_signed(conn, repetition.KEY))


def claims_for(conn: psycopg.Connection[Any], plan: cp.ContentPlan) -> dict[str, str]:
    """The claim of each planned news item, by fact id - only when its row still has the content hash the plan saw."""
    news = {int(f.params["evidence_id"]): f for f in plan.planned if f.kind.startswith("news.") and "evidence_id" in f.params}
    if not news:
        return {}
    out: dict[str, str] = {}
    for r in _rows(conn, CLAIMS_SQL, {"ids": sorted(news), "typed": typed_visible(conn)}):
        f = news[int(r["id"])]
        if r["claim"] and str(r["content_hash"] or "") == str(f.params.get("content_hash") or ""):
            out[f.id] = " ".join(str(r["claim"]).split())[:CLAIM_MAX]
    return out


__all__ = ["SCENARIOS_MAX_AGE", "claims_for", "figures_of", "news_of", "plan_input", "previous_keys", "repetition_corpus", "scenarios_of", "sheet_of"]
