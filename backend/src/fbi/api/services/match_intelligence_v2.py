"""C-01 2.0.0, the match complete (AD-J02 delivery 2, IA-131), read for both projections. Reading only.

It composes, never recomputes. The blocks of 1.x come from ``fbi.api.services.match_intelligence`` exactly as 1.1.0 serves them (its
``read`` and its pure helpers); the new ones are read from the tables their pieces write, by fixture, up to the answer's moment:

    scenarios           ``intel.scenario_readings`` (scenarios-v2, IA-082): the newest reading of the season of the last 3 days
    the one chronicle   ``ai.chronicles`` (chronicle-v4, IA-104; its update after the line-up, IA-116): the newest verified version
    E1-E4               ``intel.eval_runs`` and ``intel.eval_verdicts`` (eval-cycle-v1, IA-105/106), with decision-v2's seal
    C-05 alerts         ``intel.private_alerts`` (IA-107), served item by item as C-05 serves them (``intelligence_alerts.item_of``)
    C-02 states         ``intel.selection_lifecycle`` (IA-068, the writer C-02 reads) and the decision's id (IA-114)
    C-07 sources        ``analysis_sources.build`` (IA-122: the function it left ready for this contract)
    availability        ``profiles`` (availability-v1, IA-091), only while ``FBI_PROFILES`` lets readers see it
    player-engine-v2    ``intel.player_forecasts`` (IA-129), private only
    the market states   ``market_status.load_catalogue`` (market-states-v1, IA-070)

It imports none of the packages that write them (``fbi.competitions.scenarios`` is pure and below the API; ``fbi.chronicle``,
``fbi.evalcycle``, ``fbi.players`` and ``fbi.shadowjobs`` are not imported: the import cycle does not grow). A table that does not
exist yet in the database says ``no_entregado`` with its piece; a table without a row of the match says ``sin_datos``.

THE PUBLIC ANSWER is ``to_public`` of the private one. A shadow block (scenarios, chronicle, evaluations) reaches it only when it is
in ``PUBLISHED_BLOCKS`` - the blocks the owner published, none today - and otherwise says ``pendiente_derechos``; its shadow tables are
not even read for it. The private answer (``require_admin``) always carries each one's shadow value.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final, cast, get_args

import psycopg
import structlog

from fbi.api.contracts.intelligence.alerts import AlertItem
from fbi.api.contracts.intelligence.base import ItemList, Missing, Probability, rounded_pct
from fbi.api.contracts.intelligence.match import (
    Citation,
    OutcomeFigurePrivate,
    SelectionPrivate,
    SingleFigure,
    TeamRef,
)
from fbi.api.contracts.intelligence.match_v2 import (
    SCENARIOS_ORIGIN,
    ChronicleSectionCode,
    MatchIntelligenceV2,
    MatchIntelligenceV2Private,
    MatchV2AfterResult,
    MatchV2Chronicle,
    MatchV2ChroniclePrivate,
    MatchV2ChronicleSection,
    MatchV2Decided,
    MatchV2DependsOn,
    MatchV2Evaluation,
    MatchV2EvaluationPrivate,
    MatchV2LineupUpdate,
    MatchV2MarketStatusPrivate,
    MatchV2Needs,
    MatchV2NewFact,
    MatchV2Objective,
    MatchV2PendingPrivate,
    MatchV2PlayerForecast,
    MatchV2Scenarios,
    MatchV2SelectionPrivate,
    MatchV2SelectionWhy,
    MatchV2SideAvailability,
    MatchV2SideScenario,
    MatchV2SupersededRef,
    MatchV2Verdict,
    MatchV2WhyPhrase,
    PendingWhat,
    WhyOrigin,
)
from fbi.api.contracts.intelligence.profiles import TeamAvailability
from fbi.api.contracts.intelligence.projection import to_public
from fbi.api.contracts.intelligence.sources import AnalysisSourcesPrivate
from fbi.api.contracts.intelligence.vocab import MarketState
from fbi.api.envelope import Envelope, ok
from fbi.api.problem import ApiError
from fbi.api.repositories import Conn, fetch_all, fetch_one
from fbi.api.services import analysis_sources, intelligence_alerts, market_status, profiles
from fbi.api.services import match_intelligence as mi
from fbi.api.switches import match_intelligence_on, profiles_on
from fbi.core.clock import now
from fbi.core.decision_versions import DECISION_CORE
from fbi.lifecycle.store import WRITER as LIFECYCLE_WRITER

log = structlog.get_logger(__name__)

PUBLISHED_BLOCKS: Final[frozenset[str]] = frozenset()
"""The shadow blocks the owner published to readers: NONE (17-nov-2026). Each one is ``scenarios``, ``chronicle`` or ``evaluations``;
adding one is a code change, reviewed in its own PR with the owner's signature, and it reaches readers only while
``FBI_MATCH_INTELLIGENCE`` is on."""
SHADOW_BLOCKS: Final = ("scenarios", "chronicle", "evaluations")

SCENARIOS_MAX_AGE: Final = timedelta(days=3)
"""As the content plan reads them (``fbi.chronicle.inputs.SCENARIOS_MAX_AGE``; a test holds the two equal): the engine writes every six
hours in the shadow, an older reading is not «what is at stake now»."""
NEW_WINDOW: Final = timedelta(hours=24)
ALERTS_SHOWN: Final = 100
PLAYERS_SHOWN: Final = 60
CHRONICLE_SECTIONS: Final[tuple[ChronicleSectionCode, ...]] = get_args(ChronicleSectionCode)
UPDATE_PREFIX: Final = "lineup-update:"
NO_SENTENCE: Final = "SIN_FRASES_VERIFICADAS"
"""A section the plan gave facts to and whose every sentence the verifier dropped."""

E1_FROM: Final = timedelta(hours=24)
E1_UNTIL: Final = timedelta(hours=12)
E4_FROM: Final = timedelta(minutes=20)
"""The windows of the evaluation cycle (``fbi.evalcycle.clock``; a test holds them equal - the API does not import the cycle)."""

NO_DATA: Final = mi.NO_DATA
KEPT: Final = mi.KEPT_FROM_READERS
RESULT_WORDS: Final = ("victoria", "empate", "derrota")

# ── what is read ─────────────────────────────────────────────────────────────────────────────────────────────────────

SEASON_SQL: Final = "SELECT competition_season_id FROM core.fixtures WHERE id = %(f)s"
SCENARIOS_SQL: Final = """
SELECT reading FROM intel.scenario_readings
 WHERE competition_season_id = %(cs)s AND computed_at <= %(at)s AND computed_at > %(since)s
 ORDER BY computed_at DESC, id DESC LIMIT 1
"""
"""Through ``intel_scenario_readings_season`` (competition season, id DESC)."""

CHRONICLE_SQL: Final = """
SELECT id, created_at, plan_at, version, plan_version, verify_version, figure_version, status, plan, content, custom_id
  FROM ai.chronicles
 WHERE fixture_id = %(f)s AND created_at <= %(at)s AND status IN ('ok', 'partial')
 ORDER BY id DESC LIMIT 1
"""
"""The newest verified version (an update after the line-up carries the base's sections, its paragraph and the whys)."""
ATTEMPTS_SQL: Final = "SELECT count(*) AS n FROM ai.chronicles WHERE fixture_id = %(f)s AND created_at <= %(at)s"

RUNS_SQL: Final = """
SELECT id, evaluation, evaluation_version, cause, known_at, status, decided, latency_ms, error
  FROM intel.eval_runs WHERE fixture_id = %(f)s AND finished_at <= %(at)s
 ORDER BY known_at, id
"""
VERDICTS_SQL: Final = """
SELECT v.run_id, v.market_key, v.selection, v.line, v.verdict, v.state, v.reason, v.evaluation, v.evaluation_version, v.known_at,
       v.p_after, v.odds_after, v.price_state, v.decision_id, (d.p_cal IS NOT NULL) AS calibrated
  FROM intel.eval_verdicts v LEFT JOIN intel.decisions_v2 d ON d.id = v.decision_id
 WHERE v.fixture_id = %(f)s AND v.known_at <= %(at)s
 ORDER BY v.id
"""
ALERTS_SQL: Final = """
SELECT id, kind, fixture_id, market_key, selection, line, cause, before, after, price, decision_id, evaluation, evaluation_version,
       known_at, kickoff_at
  FROM intel.private_alerts WHERE fixture_id = %(f)s AND created_at <= %(at)s
 ORDER BY created_at DESC, id DESC LIMIT %(limit)s
"""
"""The columns ``intelligence_alerts.item_of`` reads, by fixture (``private_alerts_fixture``)."""
LIFECYCLE_SQL: Final = """
SELECT DISTINCT ON (chain_key) market_key, selection, line, state, reason
  FROM intel.selection_lifecycle WHERE fixture_id = %(f)s AND writer = %(w)s AND known_at <= %(at)s
 ORDER BY chain_key, id DESC
"""
"""The newest state of every chain of the match, of the writer C-02 reads (``lifecycle-shadow-v1``)."""
DECISION_IDS_SQL: Final = """
SELECT DISTINCT ON (market_key, selection, line) market_key, selection, line, id
  FROM intel.decisions WHERE fixture_id = %(f)s AND decision_version = %(v)s AND known_at <= %(at)s
 ORDER BY market_key, selection, line, known_at DESC, id DESC
"""
PLAYERS_SQL: Final = """
SELECT pf.team_id, t.name AS team_name, pf.provider_player_id, p.name AS player_name, pf.family, pf.line, pf.p_over, pf.seal,
       pf.p_start, pf.expected_minutes, pf.start_basis, pf.lineup_confirmed, pf.evaluation, pf.known_at, pf.version
  FROM intel.player_forecasts pf
  JOIN core.teams t ON t.id = pf.team_id
  LEFT JOIN core.players p ON p.provider_player_id = pf.provider_player_id
 WHERE pf.fixture_id = %(f)s AND pf.known_at = (SELECT max(known_at) FROM intel.player_forecasts
                                                 WHERE fixture_id = %(f)s AND known_at <= %(at)s)
 ORDER BY pf.family, pf.p_over DESC, pf.provider_player_id
 LIMIT %(limit)s
"""
"""The newest evaluation's lines of the match (``player_forecasts_fixture``)."""


def _not_yet(piece: str) -> Missing:
    return Missing(missing_reason="no_entregado", expected_piece=piece)


PIECE_OF: Final[dict[str, str]] = {"scenarios": "AD-B02", "chronicle": "AD-F02", "evaluations": "AD-D06", "alerts": "AD-D08",
                                   "players": "AD-B08", "lifecycle": "AD-D02", "sources": "AD-G08"}


def _rows(conn: Conn, sql: str, params: dict[str, Any]) -> list[dict[str, Any]] | None:
    """The rows, or None when the table does not exist in this database yet (a savepoint keeps the answer's transaction)."""
    try:
        with conn.transaction():
            return [dict(r) for r in fetch_all(conn, sql, params)]
    except psycopg.errors.UndefinedTable:
        return None


# ── the inputs ───────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Shadow:
    """What 2.0.0 adds to 1.x's inputs, as read. ``None`` for a table that does not exist yet; ``()`` for no row."""

    scenario: Mapping[str, Any] | None = None
    scenario_missing: Missing = field(default_factory=lambda: NO_DATA)
    chronicle: Mapping[str, Any] | None = None
    chronicle_missing: Missing = field(default_factory=lambda: NO_DATA)
    attempts: int = 0
    runs: Sequence[Mapping[str, Any]] | None = ()
    verdicts: Sequence[Mapping[str, Any]] = ()
    alerts: Sequence[Mapping[str, Any]] | None = ()
    lifecycle: Sequence[Mapping[str, Any]] | None = ()
    decision_ids: Sequence[Mapping[str, Any]] = ()
    sources: AnalysisSourcesPrivate | Missing = field(default_factory=lambda: NO_DATA)
    players: Sequence[Mapping[str, Any]] | None = ()
    read: bool = True
    """False: the shadow tables were not read (the public answer): every private block says ``sin_datos``."""


@dataclass(frozen=True)
class InputsV2:
    base: mi.Inputs
    shadow: Shadow = field(default_factory=Shadow)
    availability: Mapping[str, TeamAvailability | Missing] = field(default_factory=dict)
    availability_shown: bool = False
    published: frozenset[str] = PUBLISHED_BLOCKS


def read_scenario(conn: Conn, fixture_id: int, at: datetime) -> tuple[Mapping[str, Any] | None, Missing]:
    season = fetch_one(conn, SEASON_SQL, {"f": fixture_id})
    if season is None or season["competition_season_id"] is None:
        return None, NO_DATA
    rows = _rows(conn, SCENARIOS_SQL, {"cs": int(season["competition_season_id"]), "at": at, "since": at - SCENARIOS_MAX_AGE})
    if rows is None:
        return None, _not_yet(PIECE_OF["scenarios"])
    reading = rows[0]["reading"] if rows else None
    if not isinstance(reading, Mapping):
        return None, NO_DATA
    if reading.get("status") != "ok":
        return None, Missing(missing_reason="reglamento_no_codificado")
    return reading, NO_DATA


def read_chronicle(conn: Conn, fixture_id: int, at: datetime) -> tuple[Mapping[str, Any] | None, Missing, int]:
    rows = _rows(conn, CHRONICLE_SQL, {"f": fixture_id, "at": at})
    if rows is None:
        return None, _not_yet(PIECE_OF["chronicle"]), 0
    attempts = fetch_one(conn, ATTEMPTS_SQL, {"f": fixture_id, "at": at})
    return (rows[0] if rows else None), NO_DATA, int(attempts["n"]) if attempts else 0


def read_shadow(conn: Conn, fixture_id: int, at: datetime, *, private: bool, published: frozenset[str]) -> Shadow:
    """The shadow blocks: all of them for the private answer; for the public one only the published ones (none today)."""
    if not private and not published:
        return Shadow(read=False)
    scenario, scenario_missing = (read_scenario(conn, fixture_id, at) if private or "scenarios" in published else (None, NO_DATA))
    chronicle, chronicle_missing, attempts = (read_chronicle(conn, fixture_id, at) if private or "chronicle" in published
                                              else (None, NO_DATA, 0))
    runs = _rows(conn, RUNS_SQL, {"f": fixture_id, "at": at}) if private or "evaluations" in published else ()
    verdicts = (_rows(conn, VERDICTS_SQL, {"f": fixture_id, "at": at}) or []) if private and runs else []
    if not private:
        return Shadow(scenario=scenario, scenario_missing=scenario_missing, chronicle=chronicle, chronicle_missing=chronicle_missing,
                      attempts=attempts, runs=runs, read=False)
    try:
        sources: AnalysisSourcesPrivate | Missing = analysis_sources.build(conn, fixture_id, at=at)
    except (psycopg.Error, ValueError, KeyError):  # the rest of the private answer is still served; the block says it has nothing
        log.warning("match_intelligence_v2.sources_failed", fixture_id=fixture_id, exc_info=True)
        sources = NO_DATA
    return Shadow(
        scenario=scenario, scenario_missing=scenario_missing, chronicle=chronicle, chronicle_missing=chronicle_missing,
        attempts=attempts, runs=runs, verdicts=verdicts,
        alerts=_rows(conn, ALERTS_SQL, {"f": fixture_id, "at": at, "limit": ALERTS_SHOWN}),
        lifecycle=_rows(conn, LIFECYCLE_SQL, {"f": fixture_id, "w": LIFECYCLE_WRITER, "at": at}),
        decision_ids=fetch_all(conn, DECISION_IDS_SQL, {"f": fixture_id, "v": DECISION_CORE, "at": at}),
        sources=sources, players=_rows(conn, PLAYERS_SQL, {"f": fixture_id, "at": at, "limit": PLAYERS_SHOWN}))


def read_availability(conn: Conn, fx: Mapping[str, Any], at: datetime) -> dict[str, TeamAvailability | Missing]:
    """Each side's availability for THIS match, as C-09 reads it (``availability-v1``): only who may miss it."""
    match = {"fixture_id": int(fx["id"])}
    return {side: profiles._team_availability(conn, int(fx[f"{side}_team_id"]), match, [], at) for side in mi.SIDES}


def read(conn: Conn, fixture_id: int, *, at: datetime | None = None, private: bool = False,
         published: frozenset[str] = PUBLISHED_BLOCKS) -> InputsV2:
    """What one match's 2.0.0 answer is made of as of ``at``; 404 for an unknown match. Reading only."""
    moment = at or now()
    base = mi.read(conn, fixture_id, at=moment, shadow=private)
    shown = profiles_on()
    return InputsV2(base=base, shadow=read_shadow(conn, fixture_id, moment, private=private, published=published),
                    availability=read_availability(conn, base.fixture, moment) if shown else {},
                    availability_shown=shown, published=published)


# ── scenarios ────────────────────────────────────────────────────────────────────────────────────────────────────────

def _share(x: Any, at: datetime) -> Probability | Missing:
    if isinstance(x, bool) or not isinstance(x, int | float) or not 0 <= float(x) <= 1:
        return NO_DATA
    return Probability.of(round(float(x), 6), calibration="sin_calibrar", as_of=at, origin=SCENARIOS_ORIGIN, evaluation=NO_DATA,
                          evaluation_version=NO_DATA, interval=NO_DATA)


def _after(row: Mapping[str, Any] | None, at: datetime) -> list[MatchV2AfterResult]:
    if row is None:
        return []
    out = []
    for word in RESULT_WORDS:
        r = mi._obj(row.get(word))
        if r.get("estado") in ("conseguido", "descartado", "abierto"):
            out.append(MatchV2AfterResult(result=cast(Any, word), state=r["estado"], probability=_share(r.get("probabilidad"), at)))
    return out


def scenarios(reading: Mapping[str, Any] | None, fx: Mapping[str, Any], missing: Missing) -> MatchV2Scenarios | Missing:
    """Each side's objectives in every table of the reading, and what each result of this match does to them. Pure."""
    if reading is None:
        return missing
    at = datetime.fromisoformat(str(reading["at"]))
    fid = str(fx["id"])
    sides: list[MatchV2SideScenario] = []
    for side in mi.SIDES:
        team = int(fx[f"{side}_team_id"])
        objectives: list[MatchV2Objective] = []
        for table in reading.get("tables") or []:
            after = {(str(o.get("objetivo")), o.get("terminar_entre_los")): o
                     for o in mi._obj(mi._obj(mi._obj(table.get("matches")).get(fid)).get(side)).get("objetivos") or []}
            for row in table.get("teams") or []:
                if row.get("team") != team:
                    continue
                for o in row.get("objetivos") or []:
                    needs, depends, decided = mi._obj(o.get("necesita")), mi._obj(o.get("depende_de")), mi._obj(o.get("decidido"))
                    secure = mi._int(needs.get("puntos_que_lo_aseguran"))
                    objectives.append(MatchV2Objective(
                        table=str(table.get("key")), objective=str(o["objetivo"]), places=[int(p) for p in o.get("puestos") or []],
                        conditional=bool(o.get("condicional")), state=o["estado"],
                        decided=MatchV2Decided(value=bool(decided.get("valor")), proved=bool(decided.get("demostrado")),
                                               reasons=[str(r) for r in decided.get("motivos") or []]),
                        probability=_share(o.get("probabilidad"), at),
                        needs=MatchV2Needs(points=int(needs.get("puntos_actuales") or 0), max_points=int(needs.get("puntos_maximos") or 0),
                                           matches_left=int(needs.get("partidos_restantes") or 0),
                                           points_that_secure=NO_DATA if secure is None else secure),
                        depends_on=MatchV2DependsOn(kind=depends.get("tipo") or "de_otros",
                                                    rivals=[int(t) for t in depends.get("rivales") or []]),
                        after_result=mi._list(_after(after.get((str(o["objetivo"]), o.get("terminar_entre_los"))), at), NO_DATA)))
        fact = mi._obj(mi._obj(reading.get("teams")).get(str(team)))
        sides.append(MatchV2SideScenario(
            side=side, team=mi._team(fx, side), no_objective_proved=fact.get("demostrado") is True,
            no_objective_reasons=[str(r) for r in fact.get("motivos") or []], objectives=mi._list(objectives, NO_DATA)))
    rules = mi._obj(reading.get("rules"))
    version = mi._int(rules.get("version"))
    return MatchV2Scenarios(version=str(reading["version"]), computed_at=at, rules_version=NO_DATA if version is None else version,
                            contradictions=int(reading.get("contradicciones") or 0), sides=sides)


# ── the one chronicle ────────────────────────────────────────────────────────────────────────────────────────────────

def _texts(content: Mapping[str, Any], lang: str, code: str) -> list[str]:
    return [str(s["text"]) for s in mi._obj(content.get(lang)).get(code) or [] if isinstance(s, Mapping) and s.get("text")]


def _update(content: Mapping[str, Any], row: Mapping[str, Any]) -> MatchV2LineupUpdate | None:
    up = mi._obj(content.get("actualizacion"))
    es, en = [str(x) for x in up.get("es") or []], [str(x) for x in up.get("en") or []]
    if not es or not en:
        return None
    superseded = [MatchV2SupersededRef(section=s["section"], index=int(s["index"])) for s in up.get("superseded") or []
                  if isinstance(s, Mapping) and s.get("section") in CHRONICLE_SECTIONS]
    version = str(up.get("version") or "")
    return MatchV2LineupUpdate(version=version if version.startswith("lineup-update-v") else "lineup-update-v1",
                               chronicle_id=int(row["id"]), written_at=row["created_at"], es=es, en=en, superseded=superseded)


def _whys(content: Mapping[str, Any]) -> list[MatchV2SelectionWhy]:
    out = []
    for w in content.get("selecciones") or []:
        if not isinstance(w, Mapping):
            continue
        phrases = [MatchV2WhyPhrase(es=str(p["es"]), en=str(p["en"]), origin=cast(WhyOrigin, mi._obj(p.get("origin")).get("kind")))
                   for p in w.get("phrases") or []
                   if isinstance(p, Mapping) and p.get("es") and p.get("en")
                   and mi._obj(p.get("origin")).get("kind") in ("decision", "chronicle", "update")]
        if phrases:
            out.append(MatchV2SelectionWhy(market_key=str(w["market_key"]), selection=str(w["selection"]), line=str(w["line"]),
                                           verdict=w["verdict"], state=w["state"], reason=str(w["reason"]), phrases=phrases))
    return out


def chronicle(row: Mapping[str, Any] | None, attempts: int, fx: Mapping[str, Any], missing: Missing
              ) -> MatchV2ChroniclePrivate | Missing:
    """The newest verified version, by the plan's eight sections, with its update after the line-up. Pure."""
    if row is None:
        return missing
    content, plan = mi._obj(row.get("content")), mi._obj(row.get("plan"))
    abstentions = {str(s.get("code")): s.get("abstention") for s in plan.get("sections") or [] if isinstance(s, Mapping)}
    sections = []
    for code in CHRONICLE_SECTIONS:
        es, en = _texts(content, "es", code), _texts(content, "en", code)
        n = min(len(es), len(en))
        said = abstentions.get(code)
        sections.append(MatchV2ChronicleSection(
            code=code, es=es[:n], en=en[:n],
            abstention=NO_DATA if n else (str(said) if isinstance(said, str) and said else NO_SENTENCE)))
    update = _update(content, row) if str(row.get("custom_id") or "").startswith(UPDATE_PREFIX) else None
    lineup_missing: Missing = (Missing(missing_reason="aun_no_disponible", expected_at=fx["kickoff_at"] - mi.LINEUP_LEAD)
                               if mi.phase_of(str(fx["status_group"])) == "previo" else NO_DATA)
    figure = row.get("figure_version")
    return MatchV2ChroniclePrivate(
        version=str(row["version"]), chronicle_id=int(row["id"]), written_at=row["created_at"], plan_at=row["plan_at"],
        plan_version=str(row["plan_version"]), verify_version=str(row["verify_version"]),
        figure_version=str(figure) if figure else NO_DATA, status=row["status"], sections=sections,
        lineup_update=update if update is not None else lineup_missing,
        selection_whys=_whys(content), attempts=max(attempts, 1))


# ── E1-E4 ────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _line(x: Any) -> str:
    return str(Decimal(str(x)).quantize(Decimal("0.01")))


def verdict(v: Mapping[str, Any]) -> MatchV2Verdict:
    p = v.get("p_after")
    probability: Probability | Missing = NO_DATA
    if p is not None and v.get("decision_id") is not None:
        probability = Probability.of(float(p), calibration="calibrada" if v.get("calibrated") else "sin_calibrar", as_of=v["known_at"],
                                     origin="decision-v2", evaluation=v["evaluation"], evaluation_version=int(v["evaluation_version"]),
                                     interval=NO_DATA)
    odds = v.get("odds_after")
    return MatchV2Verdict(market_key=str(v["market_key"]), selection=str(v["selection"]), line=_line(v["line"]), verdict=v["verdict"],
                          state=v["state"], reason=str(v["reason"]), probability=probability,
                          odds=NO_DATA if odds is None else float(odds),
                          price_state=v["price_state"] if v.get("price_state") else NO_DATA)


def evaluations(runs: Sequence[Mapping[str, Any]] | None, verdicts: Sequence[Mapping[str, Any]]
                ) -> ItemList[MatchV2EvaluationPrivate] | Missing:
    """Every evaluation of the match, oldest first, each with what it made of each selection. Pure."""
    if runs is None:
        return _not_yet(PIECE_OF["evaluations"])
    by_run: dict[int, list[MatchV2Verdict]] = {}
    for v in verdicts:
        by_run.setdefault(int(v["run_id"]), []).append(verdict(v))
    out = [MatchV2EvaluationPrivate(
        evaluation=r["evaluation"], evaluation_version=int(r["evaluation_version"]), cause=r["cause"], known_at=r["known_at"],
        status=r["status"], decided=bool(r["decided"]),
        latency_ms=NO_DATA if r.get("latency_ms") is None else int(r["latency_ms"]),
        error=str(r["error"]) if r.get("error") else NO_DATA,
        verdicts=mi._list(by_run.get(int(r["id"]), []), NO_DATA)) for r in runs]
    return mi._list(out, NO_DATA)


# ── selections, markets, availability, what is new and what is pending ─────────────────────────────────────────────

def selections_v2(base: Sequence[SelectionPrivate], lifecycle: Sequence[Mapping[str, Any]] | None,
                  decision_ids: Sequence[Mapping[str, Any]], catalogue: market_status.MarketCatalogue) -> list[MatchV2SelectionPrivate]:
    """1.x's selections with C-02's state in the cycle, its decision and its market's state. Pure."""
    chains = {mi._key(r["market_key"], r["selection"], r["line"]): r for r in lifecycle or []}
    ids = {mi._key(r["market_key"], r["selection"], r["line"]): int(r["id"]) for r in decision_ids}
    out = []
    for s in base:
        k = mi._key(s.market, s.selection, s.line)
        chain = chains.get(k)
        missing_chain = _not_yet(PIECE_OF["lifecycle"]) if lifecycle is None else NO_DATA
        state = catalogue.status(s.market).state
        out.append(MatchV2SelectionPrivate(
            **{name: getattr(s, name) for name in type(s).model_fields if name != "lifecycle_state"},
            lifecycle_state=chain["state"] if chain else missing_chain,
            lifecycle_reason=str(chain["reason"]) if chain else missing_chain,
            decision_id=ids.get(k, NO_DATA),
            market_state=cast(MarketState, state) if state in get_args(MarketState) else NO_DATA))
    return out


def markets(figures: Sequence[OutcomeFigurePrivate], picks: Sequence[MatchV2SelectionPrivate], single: Sequence[SingleFigure],
            catalogue: market_status.MarketCatalogue) -> list[MatchV2MarketStatusPrivate]:
    """The state of every market the answer shows, in order of appearance; a reader sees those of the figures and of the published
    selections. Pure."""
    seen: dict[str, bool] = {}
    for key, readers in ([(f.market, f.readers_see) for f in figures] + [(p.market, p.public_state is not None) for p in picks]
                         + [(g.market, False) for g in single]):
        seen[key] = seen.get(key, False) or readers
    out = []
    for key, readers in seen.items():
        st = catalogue.status(key)
        if st.state in get_args(MarketState):
            out.append(MatchV2MarketStatusPrivate(market_key=key, state=cast(MarketState, st.state), reason=st.reason,
                                                  readers_see=readers))
    return out


def availability(found: Mapping[str, TeamAvailability | Missing], fx: Mapping[str, Any]) -> list[MatchV2SideAvailability]:
    out = []
    for side in mi.SIDES:
        a = found.get(side)
        if isinstance(a, TeamAvailability):
            out.append(MatchV2SideAvailability(side=side, team=mi._team(fx, side), report_checked_at=a.report_checked_at,
                                               unavailable=a.unavailable))
    return out


def _why_no_availability(found: Mapping[str, TeamAvailability | Missing]) -> Missing:
    reasons = {a.missing_reason for a in found.values() if isinstance(a, Missing)}
    return Missing(missing_reason="sin_cobertura") if reasons == {"sin_cobertura"} else NO_DATA


def new_since_yesterday(cited: Sequence[Citation], at: datetime) -> list[MatchV2NewFact]:
    return [MatchV2NewFact(n=c.n, known_at=c.known_at) for c in cited if at - c.known_at <= NEW_WINDOW]


def pending(fx: Mapping[str, Any], lineup_known: bool, runs: Sequence[Mapping[str, Any]] | None, at: datetime, *,
            shadow: bool) -> list[MatchV2PendingPrivate]:
    """What is not known yet and when it is expected: the official line-up (20 min before kick-off, the median) and, privately, the
    evaluations of the cycle still to come. Only before kick-off. Pure."""
    if mi.phase_of(str(fx["status_group"])) != "previo":
        return []
    ko: datetime = fx["kickoff_at"]
    out: list[MatchV2PendingPrivate] = []
    if not lineup_known:
        out.append(MatchV2PendingPrivate(what="alineacion_oficial", expected_at=ko - mi.LINEUP_LEAD, readers_see=True))
    if shadow and runs is not None:
        done = {str(r["evaluation"]) for r in runs if r.get("status") != "fallida"}
        steps: list[tuple[PendingWhat, str, datetime, bool]] = [
            ("evaluacion_e1", "E1", max(ko - E1_FROM, at), at < ko - E1_UNTIL),
            ("evaluacion_e3", "E3", ko - mi.LINEUP_LEAD, not lineup_known),
            ("evaluacion_e4", "E4", ko - E4_FROM, True)]
        out += [MatchV2PendingPrivate(what=what, expected_at=when, readers_see=False)
                for what, step, when, due in steps if due and step not in done]
    return sorted(out, key=lambda p: (p.expected_at, p.what))


def players(rows: Sequence[Mapping[str, Any]] | None) -> ItemList[MatchV2PlayerForecast] | Missing:
    if rows is None:
        return _not_yet(PIECE_OF["players"])
    out = [MatchV2PlayerForecast(
        team=TeamRef(id=int(r["team_id"]), name=str(r["team_name"])), provider_player_id=int(r["provider_player_id"]),
        name=mi._text(r.get("player_name")), family=str(r["family"]), line=float(r["line"]),
        pct_over=float(rounded_pct(float(r["p_over"]), 1)), calibration=r["seal"],
        p_start_pct=float(rounded_pct(float(r["p_start"]), 1)), expected_minutes=float(r["expected_minutes"]),
        start_basis=r["start_basis"], lineup_confirmed=bool(r["lineup_confirmed"]), evaluation=r["evaluation"], known_at=r["known_at"],
        version=str(r["version"])) for r in rows]
    return mi._list(out, NO_DATA)


# ── the answer ───────────────────────────────────────────────────────────────────────────────────────────────────────

def _unread[T](sh: Shadow, value: T) -> T | Missing:
    """A private block of an answer whose shadow was not read (the public one, before ``to_public`` drops it) says ``sin_datos``."""
    return value if sh.read else NO_DATA


def _published(block: str, x: InputsV2) -> bool:
    return block in x.published


def assemble(x: InputsV2, *, catalogue: market_status.MarketCatalogue | None = None) -> MatchIntelligenceV2Private:
    """The private answer of C-01 2.0.0 from what was read. Pure: the public one is ``to_public`` of it."""
    v1 = mi.assemble(x.base)
    fx, sh = x.base.fixture, x.shadow
    cat = catalogue or market_status.load_catalogue()
    picks = selections_v2(v1.selections.items, sh.lifecycle if sh.read else (), sh.decision_ids, cat)
    figures = list(v1.probabilities.items)
    states = markets(figures, picks, v1.single_figure.items, cat)
    scen = scenarios(sh.scenario, fx, sh.scenario_missing)
    chron = chronicle(sh.chronicle, sh.attempts, fx, sh.chronicle_missing)
    evals = evaluations(sh.runs, sh.verdicts)
    public_chron: MatchV2Chronicle | Missing = KEPT
    if _published("chronicle", x) and isinstance(chron, MatchV2ChroniclePrivate):
        public_chron = MatchV2Chronicle(**{n: getattr(chron, n) for n in MatchV2Chronicle.model_fields})
    elif _published("chronicle", x):
        public_chron = chron
    public_evals: ItemList[MatchV2Evaluation] | Missing = KEPT
    if _published("evaluations", x):
        public_evals = evals if isinstance(evals, Missing) else mi._list(
            [MatchV2Evaluation(**{n: getattr(e, n) for n in MatchV2Evaluation.model_fields}) for e in evals.items], NO_DATA)
    if x.availability_shown:
        sides = availability(x.availability, fx)
        avail = mi._list(sides, _why_no_availability(x.availability))
    else:
        avail = mi._list([], KEPT)
    cited = v1.citations.items
    lineup_known = not isinstance(v1.official_lineup, Missing)
    alerts: ItemList[AlertItem] | Missing = (_not_yet(PIECE_OF["alerts"]) if sh.alerts is None
                                                else mi._list([intelligence_alerts.item_of(dict(r)) for r in sh.alerts], NO_DATA))
    return MatchIntelligenceV2Private(
        freshness=v1.freshness, match=v1.match, probabilities=v1.probabilities,
        markets=mi._list(states, NO_DATA), context=v1.context, form=v1.form, official_lineup=v1.official_lineup,
        availability=avail, reader_chronicle=v1.reader_chronicle,
        selections=mi._list(picks, "sin_publicados"),
        citations=v1.citations if v1.citations.missing_reason is not None else mi._list(
            [c.model_copy(update={"relation": KEPT}) for c in cited], NO_DATA),
        new_since_yesterday=mi._list(new_since_yesterday(cited, x.base.at), KEPT if not x.base.news_shown else NO_DATA),
        pending_unknowns=mi._list(pending(fx, lineup_known, sh.runs if sh.read else None, x.base.at, shadow=sh.read), NO_DATA),
        scenarios=scen if _published("scenarios", x) else KEPT,
        chronicle=public_chron,
        evaluations=public_evals,
        scenarios_shadow=_unread(sh, scen),
        chronicle_shadow=_unread(sh, chron),
        evaluations_shadow=_unread(sh, evals),
        sources=_unread(sh, sh.sources),
        alerts=_unread(sh, alerts),
        player_forecasts=_unread(sh, players(sh.players)),
        single_figure=v1.single_figure, packet=v1.packet, brief=v1.brief, chronicle_preview=v1.chronicle_preview,
        evidence=v1.evidence,
    )


def build(conn: Conn, fixture_id: int, *, at: datetime | None = None, private: bool = False) -> MatchIntelligenceV2Private:
    return assemble(read(conn, fixture_id, at=at, private=private))


def _as_of(answer: MatchIntelligenceV2) -> datetime | None:
    moments = [f.probability.as_of for f in answer.probabilities.items] + [s.known_at for s in answer.context.items]
    return max(moments, default=None)


def public(conn: Conn, fixture_id: int, *, at: datetime | None = None) -> Envelope[MatchIntelligenceV2]:
    """The public projection: 404 while ``FBI_MATCH_INTELLIGENCE`` is off (the route does not exist for a reader)."""
    if not match_intelligence_on():
        raise ApiError(404, "not_found", "not found")
    answer = to_public(build(conn, fixture_id, at=at), MatchIntelligenceV2)
    return ok(answer, data_as_of=_as_of(answer))


def private(conn: Conn, fixture_id: int, *, at: datetime | None = None) -> Envelope[MatchIntelligenceV2Private]:
    """The private projection, for the Admin Console (``require_admin``): no switch; every shadow block."""
    answer = build(conn, fixture_id, at=at, private=True)
    return ok(answer, data_as_of=_as_of(answer))
