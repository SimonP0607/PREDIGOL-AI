"""C-13 served (plan EA, EA-007): the statistics documents the nightly pass wrote (``analytics.stat_documents``), validated back into
the contract and wrapped with the entity's competition seasons and scopes. Nothing is computed here.

``build_*`` answers the PRIVATE projection (with the audit of the calculation); ``public_*`` projects it and answers 404 while
``FBI_STATS_V2`` is off. The competition season, when not asked for, is the team's (player's) one with most matches among its
leagues, else among everything it played.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any, Final, cast

from fbi.api.contracts.intelligence.base import Freshness, Missing
from fbi.api.contracts.intelligence.projection import to_public
from fbi.api.contracts.intelligence.stats_profile import (
    CompetitionSeasonRef,
    EntityRole,
    MetricCoverage,
    PlayerBody,
    Ref,
    ScatterPoint,
    StatsAudit,
    StatsContext,
    StatsEntityPrivate,
    StatsProfile,
    StatsProfilePrivate,
    StatsScope,
    StatsSubject,
    TeamBody,
)
from fbi.api.envelope import Envelope, ok
from fbi.api.problem import ApiError
from fbi.api.repositories import Conn, Row, fetch_all, fetch_one
from fbi.api.switches import stats_v2_on
from fbi.core.clock import now

STALE_AFTER: Final = timedelta(hours=36)
SCOPE_ORDER: Final[tuple[StatsScope, ...]] = ("u5", "u10", "u20", "season")

DOCS_SQL: Final = """
SELECT d.competition_season_id, d.scope, d.context, d.sample, d.computed_at, d.calc_version,
       cs.season, c.id AS competition_id, c.name AS competition_name, c.country, c.competition_type
  FROM analytics.stat_documents d
  JOIN core.competition_seasons cs ON cs.id = d.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE d.kind = %(kind)s AND d.entity_id = %(entity)s
"""
DOC_SQL: Final = """
SELECT doc, computed_at, calc_version, sample FROM analytics.stat_documents
 WHERE kind = %(kind)s AND entity_id = %(entity)s AND competition_season_id = %(cs)s AND scope = %(scope)s AND context = %(context)s
"""
LEAGUE_SQL: Final = """
SELECT doc FROM analytics.stat_documents
 WHERE kind = 'league' AND entity_id = %(cs)s AND competition_season_id = %(cs)s AND scope = 'season' AND context = 'all'
"""
FIXTURE_SQL: Final = "SELECT id, home_team_id, away_team_id, competition_season_id FROM core.fixtures WHERE id = %(id)s"


def _missing(reason: str) -> Missing:
    return Missing.model_validate({"missing_reason": reason})


def _gate() -> None:
    if not stats_v2_on():
        raise ApiError(404, "not_found", "not found")


def _cs_ref(r: Row) -> CompetitionSeasonRef:
    return CompetitionSeasonRef(competition_season_id=int(r["competition_season_id"]),
                                competition=Ref(id=int(r["competition_id"]), name=str(r["competition_name"])),
                                season=int(r["season"]), country=r["country"] or _missing("sin_datos"))


def _choose_season(rows: list[Row], asked: int | None) -> int:
    seasons = {int(r["competition_season_id"]) for r in rows}
    if asked is not None:
        if asked not in seasons:
            raise ApiError(404, "not_found", "no statistics for that competition season")
        return asked
    full = [r for r in rows if r["scope"] == "season" and r["context"] == "all"]
    leagues = [r for r in full if r["competition_type"] == "domestic_league"] or full
    if not leagues:
        raise ApiError(404, "not_found", "no statistics yet")
    best = max(leagues, key=lambda r: (int(r["sample"]), r["computed_at"]))
    return int(best["competition_season_id"])


def _audit(conn: Conn, cs: int) -> StatsAudit:
    row = fetch_one(conn, LEAGUE_SQL, {"cs": cs})
    doc: dict[str, Any] = cast(dict[str, Any], row["doc"]) if row else {}
    return StatsAudit(run_id=doc["run_id"] if isinstance(doc.get("run_id"), int) else _missing("sin_datos"),
                      calc_version=str(doc.get("calc_version", "desconocida")), threshold=float(doc.get("threshold", 0.8)),
                      coverage=[MetricCoverage.model_validate(c) for c in doc.get("coverage", [])])


def _scatter(conn: Conn, cs: int, player: PlayerBody) -> list[ScatterPoint] | Missing:
    if isinstance(player.position, Missing):
        return _missing("sin_datos")
    row = fetch_one(conn, LEAGUE_SQL, {"cs": cs})
    points = (cast(dict[str, Any], row["doc"]).get("scatter", {}) if row else {}).get(player.position, [])
    return [ScatterPoint.model_validate(p) for p in points] if points else _missing("sin_datos")


def entity(conn: Conn, subject: StatsSubject, entity_id: int, *, role: EntityRole, season: int | None, scope: StatsScope,
           context: StatsContext, with_scatter: bool = False) -> StatsEntityPrivate:
    kind = "team" if subject == "equipo" else "player"
    rows = fetch_all(conn, DOCS_SQL, {"kind": kind, "entity": entity_id})
    if not rows:
        raise ApiError(404, "not_found", "no statistics for this entity yet")
    cs = _choose_season(rows, season)
    if subject == "jugador":
        scope, context = "season", "all"
    here = [r for r in rows if int(r["competition_season_id"]) == cs]
    scopes = sorted({cast(StatsScope, r["scope"]) for r in here if r["context"] == context}, key=SCOPE_ORDER.index)
    row = fetch_one(conn, DOC_SQL, {"kind": kind, "entity": entity_id, "cs": cs, "scope": scope, "context": context})
    if row is None:
        raise ApiError(404, "not_found", "no statistics for that scope and context")
    competitions: dict[int, CompetitionSeasonRef] = {}
    for r in sorted(rows, key=lambda r: -int(r["sample"])):
        competitions.setdefault(int(r["competition_season_id"]), _cs_ref(r))
    body: dict[str, Any] = cast(dict[str, Any], row["doc"])
    team = TeamBody.model_validate(body) if kind == "team" else _missing("sin_datos")
    player = PlayerBody.model_validate(body) if kind == "player" else _missing("sin_datos")
    matches = team.record.matches if isinstance(team, TeamBody) else cast(PlayerBody, player).appearances
    return StatsEntityPrivate(
        role=role, subject=subject, competition=competitions[cs], scope=scope, context=context, matches=matches,
        calc_version=str(row["calc_version"]), computed_at=row["computed_at"], available_scopes=scopes,
        available_competitions=list(competitions.values()), team=team, player=player,
        scatter=_scatter(conn, cs, player) if with_scatter and isinstance(player, PlayerBody) else _missing("sin_datos"),
        audit=_audit(conn, cs))


def _freshness(entities: list[StatsEntityPrivate], at: datetime) -> Freshness:
    oldest = min(e.computed_at for e in entities)
    stale = at - oldest > STALE_AFTER
    return Freshness(generated_at=at, stale=stale, stale_reason="calculo_atrasado" if stale else None)


def _answer(entities: list[StatsEntityPrivate], at: datetime | None) -> StatsProfilePrivate:
    return StatsProfilePrivate(entities=entities, freshness=_freshness(entities, at or now()))


def build_team(conn: Conn, team_id: int, *, season: int | None = None, scope: StatsScope = "season",
               context: StatsContext = "all", at: datetime | None = None) -> StatsProfilePrivate:
    return _answer([entity(conn, "equipo", team_id, role="perfil", season=season, scope=scope, context=context)], at)


def build_player(conn: Conn, player_id: int, *, season: int | None = None, at: datetime | None = None) -> StatsProfilePrivate:
    return _answer([entity(conn, "jugador", player_id, role="perfil", season=season, scope="season", context="all")], at)


def build_compare(conn: Conn, subject: StatsSubject, a: int, b: int, *, scope: StatsScope = "season",
                  context: StatsContext = "all", at: datetime | None = None) -> StatsProfilePrivate:
    if a == b:
        raise ApiError(422, "same_entity", "a comparison needs two different entities")
    return _answer([entity(conn, subject, a, role="a", season=None, scope=scope, context=context, with_scatter=True),
                    entity(conn, subject, b, role="b", season=None, scope=scope, context=context, with_scatter=True)], at)


def build_preview(conn: Conn, fixture_id: int, *, scope: StatsScope = "season", at: datetime | None = None) -> StatsProfilePrivate:
    """The two sides of a match, each in its own context (the home side at home, the away side away), in the match's competition
    season when it has documents there, else in its own."""
    fx = fetch_one(conn, FIXTURE_SQL, {"id": fixture_id})
    if fx is None:
        raise ApiError(404, "not_found", "not found")
    out = []
    for team_id, role, context in ((int(fx["home_team_id"]), "local", "home"), (int(fx["away_team_id"]), "visitante", "away")):
        rows = fetch_all(conn, DOCS_SQL, {"kind": "team", "entity": team_id})
        here = int(fx["competition_season_id"]) if any(int(r["competition_season_id"]) == int(fx["competition_season_id"])
                                                       for r in rows) else None
        chosen_scope = scope
        if here is not None and not any(int(r["competition_season_id"]) == here and r["scope"] == scope and r["context"] == context
                                        for r in rows):
            chosen_scope = "season"
        out.append(entity(conn, "equipo", team_id, role=cast(EntityRole, role), season=here, scope=chosen_scope,
                          context=cast(StatsContext, context)))
    return _answer(out, at)


def _public(answer: StatsProfilePrivate) -> Envelope[StatsProfile]:
    return ok(to_public(answer, StatsProfile))


def public_team(conn: Conn, team_id: int, **kw: Any) -> Envelope[StatsProfile]:
    _gate()
    return _public(build_team(conn, team_id, **kw))


def public_player(conn: Conn, player_id: int, **kw: Any) -> Envelope[StatsProfile]:
    _gate()
    return _public(build_player(conn, player_id, **kw))


def public_compare(conn: Conn, subject: StatsSubject, a: int, b: int, **kw: Any) -> Envelope[StatsProfile]:
    _gate()
    return _public(build_compare(conn, subject, a, b, **kw))


def public_preview(conn: Conn, fixture_id: int, **kw: Any) -> Envelope[StatsProfile]:
    _gate()
    return _public(build_preview(conn, fixture_id, **kw))


def private_team(conn: Conn, team_id: int, **kw: Any) -> Envelope[StatsProfilePrivate]:
    return ok(build_team(conn, team_id, **kw))


def private_player(conn: Conn, player_id: int, **kw: Any) -> Envelope[StatsProfilePrivate]:
    return ok(build_player(conn, player_id, **kw))
