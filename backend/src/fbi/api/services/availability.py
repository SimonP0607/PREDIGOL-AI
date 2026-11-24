"""C-16 served (plan PM, PM-02-05): the availability matrix and the seven states of a match. Read only.

* the directory and a competition: ``analytics.coverage_cells`` and ``analytics.market_availability`` (the nightly batch, PM-02-03), the
  summary and families by ``fbi.coverage.levels`` from the latest graded season;
* a match: ``fbi.coverage.resolve`` with Mi parlay's own policy (``market_probs.parlay_policy``: ``FBI_PARLAY_MARKETS_V2`` and the
  catalogue's state of each bet) and whether readers may see the forecast (``FBI_FORECAST_USERS``) - the same inputs C-14 reads;
* the private routes add what each recalculation measured, the changes of level and the shadow's discrepancies.

Every route answers 404 while ``FBI_AVAILABILITY`` is off. The public answers are kept 60 seconds (``fbi.api.cache.shared``).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any, Final, Literal, cast

from fbi.api.cache import shared
from fbi.api.contracts.intelligence.availability import (
    Availability,
    AvailabilityPrivate,
    BlockAvailability,
    CompetitionAvailabilityPrivate,
    Discrepancy,
    FamilyLevel,
    LevelCellPrivate,
    LevelChange,
    MarketAvailabilityPrivate,
    MarketCellPrivate,
    MatchAvailabilityPrivate,
    ModuleVerdict,
    PhaseAvailabilityPrivate,
    SeasonAvailabilityPrivate,
    SelectionVerdict,
)
from fbi.api.contracts.intelligence.base import Freshness, ItemList, Missing
from fbi.api.contracts.intelligence.projection import to_public
from fbi.api.envelope import Envelope, ok
from fbi.api.problem import ApiError
from fbi.api.repositories import Conn, fetch_all, fetch_one
from fbi.api.services.forecast import VERSION as PUBLISHED_FORECAST_VERSION
from fbi.api.services.forecast import users_may_see
from fbi.api.services.market_probs import parlay_policy
from fbi.api.switches import availability_on, availability_phases_on, prob_by_competition_on
from fbi.core.clock import now
from fbi.coverage import depth, levels
from fbi.coverage import resolve as resolver
from fbi.coverage.job import CUP_PHASES, PHASE_ALL

CACHE_SECONDS: Final = 60
HISTORY_DAYS: Final = 7
SEASONS_SHOWN: Final = 2
_NO_DATA: Final = Missing(missing_reason="sin_datos")

COMPETITIONS_SQL: Final = """
SELECT c.id, c.provider_league_id, c.name, c.country, c.tier FROM core.competitions c
 WHERE c.is_tracked AND (%(id)s::bigint IS NULL OR c.id = %(id)s)
   AND EXISTS (SELECT 1 FROM core.competition_seasons s JOIN analytics.coverage_cells x ON x.competition_season_id = s.id
                WHERE s.competition_id = c.id)
 ORDER BY c.tier NULLS LAST, c.name
"""
SEASONS_SQL: Final = """
SELECT s.id, s.competition_id, s.season FROM core.competition_seasons s
 WHERE s.competition_id = ANY(%(ids)s) AND EXISTS (SELECT 1 FROM analytics.coverage_cells x WHERE x.competition_season_id = s.id)
 ORDER BY s.competition_id, s.season DESC
"""
CELLS_SQL: Final = """
SELECT competition_season_id, datum, level, measured_level, missed, provisional, reason, n_finished, n_with_data, share, pooled_seasons,
       declared_flag, measured_at
  FROM analytics.coverage_cells WHERE competition_season_id = ANY(%(ids)s) AND phase_key = %(phase)s
"""
PHASE_CELLS_SQL: Final = """
SELECT competition_season_id, phase_key, datum, level, measured_level, missed, provisional, reason, n_finished, n_with_data, share,
       pooled_seasons, declared_flag, measured_at
  FROM analytics.coverage_cells WHERE competition_season_id = ANY(%(ids)s) AND phase_key = ANY(%(phases)s)
"""
"""A cup season's phases (PM-02-07), read only while ``FBI_AVAILABILITY_PHASES`` is on."""
MARKETS_SQL: Final = """
SELECT competition_season_id, market_key, level, measured_level, missed, provisional, reason, n_window, n_priced, priced_share,
       median_books, settle_share, catalogue_state, measured_at
  FROM analytics.market_availability WHERE competition_season_id = ANY(%(ids)s)
"""
CHANGES_SQL: Final = """
SELECT competition_season_id, phase_key, kind, subject, old_level, new_level, reason, n_finished, changed_at
  FROM analytics.coverage_changes WHERE changed_at >= %(since)s ORDER BY changed_at DESC, id DESC LIMIT 2000
"""
DISCREPANCIES_SQL: Final = """
SELECT day, fixture_id, module, subject, shown, matrix, reason, observed_at
  FROM analytics.availability_discrepancies WHERE day >= %(since)s ORDER BY day DESC, id DESC LIMIT 2000
"""

_CELL_REASONS: Final = frozenset({"heredado", "muestra_insuficiente", "menos_de_3_casas", "menos_de_5_casas", "no_entregado",
                                  "sin_ventana"})


def _pct(share: Any) -> float | Missing:
    return _NO_DATA if share is None else round(float(share) * 100, 1)


def _reason(value: str | None) -> Any:
    return value if value in _CELL_REASONS else "ninguno"


def _declared(flag: bool | None) -> Literal["si", "no", "sin_bandera"]:
    return "sin_bandera" if flag is None else "si" if flag else "no"


def _cell(r: dict[str, Any]) -> LevelCellPrivate:
    return LevelCellPrivate(key=r["datum"], level=r["level"], n=r["n_finished"], with_data=r["n_with_data"], pct=_pct(r["share"]),
                            provisional=r["provisional"], reason=_reason(r["reason"]), measured_at=r["measured_at"],
                            measured_level=r["measured_level"], missed=r["missed"], pooled_seasons=r["pooled_seasons"],
                            declared=_declared(r["declared_flag"]))


def _market_cell(r: dict[str, Any]) -> MarketCellPrivate:
    return MarketCellPrivate(
        key=r["market_key"], level=r["level"], n=r["n_window"], with_data=r["n_priced"], pct=_pct(r["priced_share"]),
        provisional=r["provisional"], reason=_reason(r["reason"]), measured_at=r["measured_at"],
        median_books=_NO_DATA if r["median_books"] is None else float(r["median_books"]), settle_pct=_pct(r["settle_share"]),
        measured_level=r["measured_level"], missed=r["missed"], pooled_seasons=1, declared="sin_bandera",
        catalogue_state=r["catalogue_state"] if r["catalogue_state"] else _NO_DATA)


def _season(sid: int, season: int, data: list[LevelCellPrivate], markets: list[MarketCellPrivate],
            phases: dict[str, list[LevelCellPrivate]] | None = None) -> SeasonAvailabilityPrivate:
    by_datum: dict[str, levels.Level] = {c.key: c.level for c in data}
    by_market: dict[str, levels.Level] = {c.key: c.level for c in markets}
    if set(levels.DATA) <= set(by_datum) and set(levels.MARKETS) <= set(by_market):
        families = levels.family_levels(by_datum, by_market)
        summary = levels.summary_level(by_datum, by_market)
        level, label = summary.level, summary.label
    else:  # a season graded by an older pass, or partly: said as it is, never guessed
        families, level, label = {}, "MI", "MI"
    order = {d: i for i, d in enumerate((*levels.DATA, *levels.MARKETS))}
    return SeasonAvailabilityPrivate(
        competition_season_id=sid, season=season, phase=PHASE_ALL, summary=level, summary_label=label,
        families=[FamilyLevel(family=cast(Any, f), level=lv) for f, lv in families.items()],
        data=sorted(data, key=lambda c: order.get(c.key, 99)), markets=sorted(markets, key=lambda c: order.get(c.key, 99)),
        phases=[PhaseAvailabilityPrivate(phase=cast(Any, p), data=sorted(cells, key=lambda c: order.get(c.key, 99)))
                for p in CUP_PHASES if (cells := (phases or {}).get(p))])


def _competitions(conn: Conn, competition_id: int | None, *, with_seasons: bool) -> list[CompetitionAvailabilityPrivate]:
    comps = fetch_all(conn, COMPETITIONS_SQL, {"id": competition_id})
    if not comps:
        return []
    seasons = fetch_all(conn, SEASONS_SQL, {"ids": [c["id"] for c in comps]})
    per_comp: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for s in seasons:
        if competition_id is not None or len(per_comp[s["competition_id"]]) < SEASONS_SHOWN:
            per_comp[s["competition_id"]].append(s)
    ids = [s["id"] for ss in per_comp.values() for s in ss]
    cells: dict[int, list[LevelCellPrivate]] = defaultdict(list)
    for r in fetch_all(conn, CELLS_SQL, {"ids": ids, "phase": PHASE_ALL}):
        cells[r["competition_season_id"]].append(_cell(r))
    markets: dict[int, list[MarketCellPrivate]] = defaultdict(list)
    for r in fetch_all(conn, MARKETS_SQL, {"ids": ids}):
        markets[r["competition_season_id"]].append(_market_cell(r))
    phases: dict[int, dict[str, list[LevelCellPrivate]]] = defaultdict(lambda: defaultdict(list))
    if with_seasons and availability_phases_on():
        for r in fetch_all(conn, PHASE_CELLS_SQL, {"ids": ids, "phases": list(CUP_PHASES)}):
            phases[r["competition_season_id"]][r["phase_key"]].append(_cell(r))
    out: list[CompetitionAvailabilityPrivate] = []
    prio = depth.priorities()
    for c in comps:
        graded = [_season(s["id"], s["season"], cells[s["id"]], markets[s["id"]], phases.get(s["id"], {}))
                  for s in per_comp.get(c["id"], [])]
        if not graded:
            continue
        head = next((g for g in graded if g.summary != "MI"), graded[0])  # the latest season with a sample decides the directory
        out.append(CompetitionAvailabilityPrivate(
            competition_id=c["id"], name=c["name"], country=c["country"] or _NO_DATA,
            tier=_NO_DATA if c["tier"] is None else int(c["tier"]),
            priority=prio.get(int(c["provider_league_id"]), _NO_DATA) if c.get("provider_league_id") is not None else _NO_DATA,
            summary=head.summary, summary_label=head.summary_label,
            families=head.families, seasons=graded if with_seasons else []))
    return out


def parlay_rules() -> resolver.ParlayRules:
    """Mi parlay's own checks of a leg (``fbi.userdata.records``), handed to the resolver (the domain may not import them)."""
    from fbi.picks.count_settlement import settle_numbers
    from fbi.userdata import records

    return resolver.ParlayRules(core_markets=records.CORE_MARKETS, lookback=records.SNAPSHOT_LOOKBACK,
                                valid_selection=records.valid_selection, quarter_line=records.quarter_line,
                                outlier_price=records.outlier_price, grade=settle_numbers)


def _match(conn: Conn, fixture_id: int, at: datetime) -> MatchAvailabilityPrivate:
    policy = parlay_policy()
    found = resolver.availability(conn, fixture_id, at=at, rules=parlay_rules(), parlay_on=policy.enabled, state_of=policy.state_of,
                                  forecast_users=users_may_see(), by_phase=availability_phases_on(),
                                  by_competition=prob_by_competition_on(), published_versions=(PUBLISHED_FORECAST_VERSION,))
    if found is None:
        raise ApiError(404, "not_found", "match not found")
    inputs_cs = fetch_one(conn, "SELECT competition_season_id, kickoff_at FROM core.fixtures WHERE id = %(id)s", {"id": fixture_id})
    assert inputs_cs is not None
    blocks = [BlockAvailability(key=k, exists=b.exists, level=b.level if b.level else _NO_DATA, n=b.n, provisional=b.provisional,
                                reason=_reason(b.reason) if b.reason != "sin_medir" else "sin_medir")
              for k, b in found.blocks.items()]
    markets: list[MarketAvailabilityPrivate] = []
    for m in found.markets:
        state = m.catalogue_state  # Mi parlay's policy: the catalogue's state of the bet, as C-14 reads it
        markets.append(MarketAvailabilityPrivate(
            key=m.key, matrix_market=m.matrix_market or _NO_DATA, exists=m.exists,
            coverage_ok=_NO_DATA if m.coverage_ok is None else m.coverage_ok, level=m.level or _NO_DATA,
            price_in_force=m.price_in_force, prob_computed=m.prob_computed, prob_authorised=m.prob_authorised, settleable=m.settleable,
            reason=cast(Any, m.reason or "ninguno"),
            modules=[ModuleVerdict(module=cast(Any, name), ok=v.ok, reason=cast(Any, "ok" if v.ok else (v.reason or "market_not_priced")))
                     for name, v in m.modules.items()],
            catalogue_state=cast(Any, state) if state else _NO_DATA,
            selections=[SelectionVerdict(selection=s.selection, line=float(s.line), books=s.books, mi_parlay=cast(Any, list(s.mi_parlay)))
                        for s in m.selections]))
    return MatchAvailabilityPrivate(
        fixture_id=fixture_id, kickoff_at=inputs_cs["kickoff_at"],
        competition_season_id=_NO_DATA if inputs_cs["competition_season_id"] is None else int(inputs_cs["competition_season_id"]),
        phase=cast(Any, found.phase), blocks=blocks, markets=markets, notes=cast(Any, list(found.notes)))


def _history(conn: Conn, at: datetime) -> tuple[ItemList[LevelChange], ItemList[Discrepancy]]:
    since = at - timedelta(days=HISTORY_DAYS)
    changes = [LevelChange(competition_season_id=r["competition_season_id"], phase=r["phase_key"], kind=r["kind"], key=r["subject"],
                           old_level=r["old_level"] or _NO_DATA, new_level=r["new_level"], reason=r["reason"],
                           n=_NO_DATA if r["n_finished"] is None else r["n_finished"], changed_at=r["changed_at"])
               for r in fetch_all(conn, CHANGES_SQL, {"since": since})]
    found = [Discrepancy(day=r["day"].isoformat(), fixture_id=r["fixture_id"], module=r["module"], key=r["subject"], shown=r["shown"],
                         matrix=r["matrix"], reason=r["reason"], observed_at=r["observed_at"])
             for r in fetch_all(conn, DISCREPANCIES_SQL, {"since": since.date()})]
    return (ItemList[LevelChange](items=changes) if changes else ItemList[LevelChange](items=[], missing_reason="sin_datos"),
            ItemList[Discrepancy](items=found) if found else ItemList[Discrepancy](items=[], missing_reason="sin_datos"))


def build(conn: Conn, scope: str, *, competition_id: int | None = None, fixture_id: int | None = None,
          at: datetime | None = None) -> AvailabilityPrivate:
    """The private answer of one route (the public one is its projection)."""
    moment = at or now()
    competitions: list[CompetitionAvailabilityPrivate] = []
    match: MatchAvailabilityPrivate | Missing = _NO_DATA
    if scope in ("directorio", "matriz"):
        competitions = _competitions(conn, None, with_seasons=scope == "matriz")
    elif scope == "competicion":
        competitions = _competitions(conn, competition_id, with_seasons=True)
        if not competitions:
            raise ApiError(404, "not_found", "competition not graded")
    elif scope == "partido":
        assert fixture_id is not None
        match = _match(conn, fixture_id, moment)
    empty_changes = ItemList[LevelChange](items=[], missing_reason="sin_datos")
    empty_found = ItemList[Discrepancy](items=[], missing_reason="sin_datos")
    changes, found = _history(conn, moment) if scope in ("matriz", "cambios") else (empty_changes, empty_found)
    return AvailabilityPrivate(rules_version=levels.RULES_VERSION, scope=cast(Any, scope), competitions=competitions, match=match,
                               changes=changes, discrepancies=found, freshness=Freshness(generated_at=moment, stale=False))


def _guard() -> None:
    if not availability_on():
        raise ApiError(404, "not_found", "not found")


@shared(CACHE_SECONDS)
def _public_cached(conn: Conn, scope: str, competition_id: int | None, fixture_id: int | None) -> Envelope[Availability]:
    return ok(to_public(build(conn, scope, competition_id=competition_id, fixture_id=fixture_id), Availability))


def directory(conn: Conn) -> Envelope[Availability]:
    _guard()
    return _public_cached(conn, "directorio", None, None)


def competition(conn: Conn, competition_id: int) -> Envelope[Availability]:
    _guard()
    return _public_cached(conn, "competicion", competition_id, None)


def match(conn: Conn, fixture_id: int) -> Envelope[Availability]:
    _guard()
    return _public_cached(conn, "partido", None, fixture_id)


def matrix(conn: Conn) -> Envelope[AvailabilityPrivate]:
    _guard()
    return ok(build(conn, "matriz"))


def changes(conn: Conn) -> Envelope[AvailabilityPrivate]:
    _guard()
    return ok(build(conn, "cambios"))
