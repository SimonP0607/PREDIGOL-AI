"""C-01, the match's contract, read for both projections (AD-J02, IA-066). Reading only.

One builder makes the PRIVATE answer; the public one is ``to_public`` of it (``fbi.api.contracts.intelligence.projection``):
it copies only the fields the public classes declare, and leaves out of a list every item that is not shown - a selection
that is not published, a figure the owner keeps from readers. Nothing private is hidden afterwards: it is never copied.

What the PUBLIC fields carry is, by construction, what a reader is already shown elsewhere and under the same switches:

* the figures - the Match Center's forecast (``fbi.api.services.forecast``: the newest set of each market, ``forecast-v1``),
  shown while ``FBI_FORECAST_USERS`` is on;
* the context and the form - the match packet's blocks the structured reading tells (``fbi.api.services.reading``), while
  ``FBI_READING_USERS`` is on;
* the reader's chronicle - ``reading.narrative_for`` exactly, so only with ``FBI_USER_NARRATIVE=on`` and only while it tells
  the story the data tell now;
* the selections - the ``qualified`` daily set (the only set a reader is shown; empty in the whole history on 16-nov-2026);
* the citations - the stories of the match's news (``fbi.api.services.news``: the web's items, no provider or owner notes,
  research v2 only while it is on), while ``FBI_NEWS_USERS`` is on.

The PRIVATE fields add the decision layer's shadow (``decision-v1``, read, never called: ``fbi.intel.decision`` is not
imported), the model's own numbers, the AI's latest brief, the chronicle whatever the switch, and every web item of the match
whatever its status or language. No model is called, no probability is computed - a percentage is only rounded, once, by ``Probability.of``.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final, cast, get_args

from fbi.api.contracts.intelligence.base import (
    Freshness,
    ItemList,
    Missing,
    Probability,
    Source,
    rounded_pct,
)
from fbi.api.contracts.intelligence.match import (
    DECISION_ORIGIN,
    FORECAST_ORIGIN,
    Brief,
    ChronicleSection,
    Citation,
    CompetitionRef,
    DecisionState,
    EvidenceRecord,
    ForecastBasis,
    MatchInfo,
    MatchIntelligence,
    MatchIntelligencePrivate,
    MatchPhase,
    OfficialLineup,
    OutcomeCode,
    OutcomeFigurePrivate,
    PacketRef,
    Pressure,
    ReaderChronicle,
    SelectionPrivate,
    SideForm,
    SideLineup,
    SideStakes,
    TeamRef,
    Zone,
    ZoneGap,
)
from fbi.api.contracts.intelligence.projection import to_public
from fbi.api.contracts.intelligence.vocab import ConfirmationLevel, PublicState, StoryWarning
from fbi.api.contracts.reading import ReadingNarrative
from fbi.api.envelope import Envelope, ok
from fbi.api.problem import ApiError
from fbi.api.repositories import Conn, fetch_all, fetch_one
from fbi.api.services import forecast as forecast_service
from fbi.api.services import news as news_service
from fbi.api.services import reading as reading_service
from fbi.api.switches import match_intelligence_on
from fbi.core.clock import now
from fbi.core.decision_versions import DECISION_CORE

SIDES: Final = ("home", "away")
PHASES: Final[dict[str, MatchPhase]] = {"scheduled": "previo", "live": "en_juego", "finished": "terminado",
                                        "postponed": "aplazado", "cancelled": "cancelado"}
OUTCOMES: Final[dict[tuple[str, str], OutcomeCode]] = cast(dict[tuple[str, str], OutcomeCode], reading_service.OUTCOMES)
"""The provider's selection of each forecast market and its code (the structured reading's own table)."""

STALE_AFTER: Final = timedelta(hours=6)
STALE_WINDOW: Final = timedelta(hours=24)
"""A match that kicks off within 24 h and whose newest packet is older than 6 h is said to be stale. Measured in production
on 17-nov-2026 00:21 UTC: of the 43 matches kicking off in the next 24 h, all 43 had a packet, the newest 0.30 h old at the
median, 0.96 h at the 90th percentile and 1.21 h at most - so 6 h only fires when the worker stopped building packets."""

LINEUP_LEAD: Final = timedelta(minutes=20)
"""When the official line-up is expected: 20 minutes before kick-off, the median measured over 30 days (n = 3,401 matches;
it arrives for 76 % of them) in the plan of the definitive architecture (Doc 3)."""

EVIDENCE_SHOWN: Final = 60
CONFIRMED_OFFICIAL_TIERS: Final = frozenset({"official", "competition", "club"})
STATUS_ORDER: Final = ("CONFIRMED", "PROBABLE", "CONTRADICTORY", "RUMOR", "OUTDATED")

NOT_YET: Final = {
    "scenarios": "AD-B02", "chronicle": "AD-F02", "evaluations": "AD-D06", "new_since_yesterday": "AD-C07",
    "pending_unknowns": "AD-D05", "keys": "AD-F01", "risks": "AD-F01", "players_to_watch": "AD-H07",
}
"""The blocks of C-01 that no piece computes yet, and the piece that will."""


def _not_yet(piece: str) -> Missing:
    return Missing(missing_reason="no_entregado", expected_piece=piece)


NO_EVALUATION: Final = _not_yet("AD-D06")
NO_PRICE: Final = _not_yet("AD-B06")
NO_DATA: Final = Missing(missing_reason="sin_datos")
KEPT_FROM_READERS: Final = Missing(missing_reason="pendiente_derechos")

# ── what is read ─────────────────────────────────────────────────────────────────────────────────────────────────────

FIXTURE_SQL = """
SELECT f.id, f.kickoff_at, f.status_short, f.status_group, f.round, f.venue_name,
       f.home_team_id, th.name AS home_name, f.away_team_id, ta.name AS away_name,
       c.id AS competition_id, c.name AS competition, c.country
  FROM core.fixtures f
  JOIN core.teams th ON th.id = f.home_team_id
  JOIN core.teams ta ON ta.id = f.away_team_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE f.id = %(f)s
"""
"""The match, with the names the structured reading expects (``reading.FIXTURE_SQL``'s columns are a subset)."""

DECISIONS_SQL = """
SELECT DISTINCT ON (market_key, selection, line) market_key, selection, line, known_at, state, odds, p_model, p_cal,
       calibrator_id, ev_cal, reasons
  FROM intel.decisions WHERE fixture_id = %(f)s AND decision_version = %(v)s AND known_at <= %(at)s
 ORDER BY market_key, selection, line, known_at DESC, id DESC
"""
"""The newest decision of every selection of the match, of the pipeline's layer only (the families' rows are research)."""

SET_ITEMS_SQL = """
SELECT s.source, i.market_key, i.selection, i.line, i.selected_at, i.settled_at
  FROM picks.daily_set_items i JOIN picks.daily_sets s ON s.id = i.set_id
 WHERE i.fixture_id = %(f)s AND i.selected_at <= %(at)s
"""
"""The match's items of the day's sets: ``qualified`` is what a reader is shown; ``evaluation`` is the owner's preview."""

BRIEF_SQL = """
SELECT created_at, pass, version, engine, model, status, escalate, reasons, uncertainty, data_quality,
       content->>'summary' AS summary
  FROM ai.match_briefs WHERE fixture_id = %(f)s AND created_at <= %(at)s ORDER BY created_at DESC, id DESC LIMIT 1
"""

PACKET_SQL = """
SELECT id, packet_version AS version, as_of, missing FROM ai.match_packets
 WHERE fixture_id = %(f)s AND as_of <= %(at)s ORDER BY as_of DESC, id DESC LIMIT 1
"""

LINEUPS_SQL = """
SELECT team_side, formation, coach_name, fetched_at FROM core.fixture_lineups WHERE fixture_id = %(f)s
"""


# ── small readers: never trust a shape, never invent a value ─────────────────────────────────────────────────────────

def _obj(x: Any) -> Mapping[str, Any]:
    return x if isinstance(x, Mapping) else {}


def _int(x: Any) -> int | None:
    if isinstance(x, bool) or x is None:
        return None
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def _float(x: Any) -> float | Missing:
    if isinstance(x, bool) or x is None:
        return NO_DATA
    try:
        return float(x)
    except (TypeError, ValueError):
        return NO_DATA


def _text(x: Any) -> str | Missing:
    return str(x).strip() if x is not None and str(x).strip() else NO_DATA


def _when(x: Any) -> datetime | Missing:
    return x if isinstance(x, datetime) else NO_DATA


def _pct_band(p: float, lo: Any, hi: Any) -> tuple[int, int] | Missing:
    """The interval in whole points, or ``sin_datos`` when the model gave none (or one that does not hold the figure)."""
    if lo is None or hi is None or not float(lo) <= p <= float(hi):
        return NO_DATA
    return int(rounded_pct(float(lo))), int(rounded_pct(float(hi)))


# ── the match ────────────────────────────────────────────────────────────────────────────────────────────────────────

def phase_of(status_group: str) -> MatchPhase:
    return PHASES.get(status_group, "otro")


def match_info(fx: Mapping[str, Any]) -> MatchInfo:
    return MatchInfo(
        id=int(fx["id"]),
        home=TeamRef(id=int(fx["home_team_id"]), name=str(fx["home_name"])),
        away=TeamRef(id=int(fx["away_team_id"]), name=str(fx["away_name"])),
        competition=CompetitionRef(id=int(fx["competition_id"]), name=str(fx["competition"]),
                                   country=_text(fx.get("country"))),
        kickoff_at=fx["kickoff_at"], round=_text(fx.get("round")), venue=_text(fx.get("venue_name")),
        status=str(fx["status_short"] or "?"), phase=phase_of(str(fx["status_group"])))


def _team(fx: Mapping[str, Any], side: str) -> TeamRef:
    return TeamRef(id=int(fx[f"{side}_team_id"]), name=str(fx[f"{side}_name"]))


# ── one figure per outcome ───────────────────────────────────────────────────────────────────────────────────────────

def figures(rows: Sequence[Mapping[str, Any]], *, readers_see: bool) -> list[OutcomeFigurePrivate]:
    """The newest set of each market as the Match Center shows it (rows of ``forecast.FORECAST_SQL``), each outcome with
    its one figure (0 decimals) and, privately, the model's own number (1 decimal: 78.5 %). Pure."""
    out: list[OutcomeFigurePrivate] = []
    for r in rows:
        code = OUTCOMES.get((str(r["market_key"]), str(r["selection"])))
        if code is None:
            continue
        calibrated = r["calibration"] == "CALIBRATED"
        p, p_model = float(r["p"]), float(r["p_model"])
        basis = str(r["basis"])
        out.append(OutcomeFigurePrivate(
            market=cast(Any, str(r["market_key"])), line=float(r["line"]), outcome=code,
            probability=Probability.of(
                p, calibration="calibrada" if calibrated else "sin_calibrar", as_of=r["known_at"], origin=FORECAST_ORIGIN,
                evaluation=NO_EVALUATION, evaluation_version=NO_EVALUATION, interval=_pct_band(p, r["p_lo"], r["p_hi"])),
            price=NO_PRICE,
            raw_probability=Probability.of(
                p_model, calibration="sin_calibrar", as_of=r["known_at"], origin=FORECAST_ORIGIN, evaluation=NO_EVALUATION,
                evaluation_version=NO_EVALUATION, interval=NO_DATA, decimals=1),
            model=str(r["model_name"]),
            basis=cast(ForecastBasis, basis if basis in get_args(ForecastBasis) else "not_applicable"),
            fair_odds=float((Decimal(1) / Decimal(str(r["p"]))).quantize(Decimal("0.01"))),
            readers_see=readers_see))
    order = {"1X2": 0, "OU": 1, "BTTS": 2}
    return sorted(out, key=lambda f: (order[f.market], f.line))


def _why_no_figure(fixture: Mapping[str, Any] | None) -> Missing:
    if fixture is not None and fixture.get("data_class") in forecast_service.NOT_FIT:
        return Missing(missing_reason="sin_cobertura")
    return NO_DATA


# ── context and form ─────────────────────────────────────────────────────────────────────────────────────────────────

def _zone(x: Any) -> Zone:
    return cast(Zone, x) if x in get_args(Zone) else ("none" if x is None else "other")


def stakes(content: Mapping[str, Any], fx: Mapping[str, Any], known_at: datetime) -> list[SideStakes]:
    """Each side's stakes from the packet's ``stakes`` block (``fbi.ai.context.Stakes.as_json``). Pure."""
    block = _obj(content.get("stakes"))
    out: list[SideStakes] = []
    for side in SIDES:
        s = _obj(block.get(side))
        rank, rule = _int(s.get("rank")), s.get("rule")
        if rank is None or rank < 1 or not isinstance(rule, str) or not rule.startswith("stakes-v"):
            continue
        pressure = s.get("pressure")
        up, down = _int(s.get("gap_up")), _int(s.get("gap_down"))
        settled = s.get("settled")
        remaining = _int(s.get("remaining"))
        out.append(SideStakes(
            side=side, team=_team(fx, side), rank=rank, zone=_zone(s.get("zone")),
            pressure=cast(Pressure, pressure if pressure in get_args(Pressure) else "unknown"),
            above=NO_DATA if up is None else ZoneGap(zone=_zone(s.get("zone_above")), points=up),
            below=NO_DATA if down is None else ZoneGap(zone=_zone(s.get("zone_below")), points=down),
            remaining=NO_DATA if remaining is None else remaining,
            settled=settled if isinstance(settled, bool) else NO_DATA, rule=rule, known_at=known_at))
    return out


def form(content: Mapping[str, Any], fx: Mapping[str, Any], known_at: datetime) -> list[SideForm]:
    """Each side's last results from the packet's ``form`` block, as the structured reading tells them. Pure."""
    block = _obj(content.get("form"))
    out: list[SideForm] = []
    for side in SIDES:
        f = _obj(block.get(side))
        n, sequence = _int(f.get("n")), str(f.get("sequence") or "")
        if not n or n < 1 or not sequence or set(sequence) - set("WDL"):
            continue
        out.append(SideForm(side=side, team=_team(fx, side), matches=n, sequence=sequence[-10:],
                            points_per_game=_float(f.get("ppg")), goals_for_per_game=_float(f.get("gf_pg")),
                            goals_against_per_game=_float(f.get("ga_pg")), known_at=known_at))
    return out


def lineup(rows: Sequence[Mapping[str, Any]], fx: Mapping[str, Any]) -> OfficialLineup | Missing:
    """Both sides' official line-up, or when it is expected (before kick-off), or that there is none. Pure."""
    by_side = {str(r["team_side"]): r for r in rows}
    if set(SIDES) <= by_side.keys():
        return OfficialLineup(
            home=SideLineup(formation=_text(by_side["home"]["formation"]), coach=_text(by_side["home"]["coach_name"])),
            away=SideLineup(formation=_text(by_side["away"]["formation"]), coach=_text(by_side["away"]["coach_name"])),
            known_at=max(by_side[s]["fetched_at"] for s in SIDES))
    if phase_of(str(fx["status_group"])) == "previo":
        return Missing(missing_reason="aun_no_disponible", expected_at=fx["kickoff_at"] - LINEUP_LEAD)
    return NO_DATA


# ── the chronicle and the brief ──────────────────────────────────────────────────────────────────────────────────────

def chronicle_of(narrative: ReadingNarrative | None) -> ReaderChronicle | Missing:
    if narrative is None:
        return NO_DATA

    def sections(xs: Sequence[Any]) -> list[ChronicleSection]:
        return [ChronicleSection(key=x.key, sentences=[s.text for s in x.sentences]) for x in xs if x.sentences]

    return ReaderChronicle(version=narrative.version, written_at=narrative.written_at, data_at=narrative.data_at,
                           es=sections(narrative.es), en=sections(narrative.en),
                           sources=[s.name for s in narrative.sources])


def brief_of(row: Mapping[str, Any] | None) -> Brief | Missing:
    if row is None:
        return NO_DATA
    return Brief(created_at=row["created_at"], pass_name=str(row["pass"]), version=str(row["version"]),
                 engine=str(row["engine"]), model=_text(row["model"]), status=str(row["status"]),
                 summary=_text(row["summary"]), escalate=bool(row["escalate"]),
                 reasons=[str(x) for x in row["reasons"] or []], uncertainty=_text(row["uncertainty"]),
                 data_quality=_text(row["data_quality"]))


# ── selections ───────────────────────────────────────────────────────────────────────────────────────────────────────

Key = tuple[str, str, Decimal]


def _key(market: Any, selection: Any, line: Any) -> Key:
    return str(market), str(selection), Decimal(str(line)).quantize(Decimal("0.01"))


def public_state(item: Mapping[str, Any] | None, phase: MatchPhase) -> PublicState | None:
    """What a reader sees of a published pick: settled, the match under way or over, or published before kick-off. Pure."""
    if item is None:
        return None
    if item.get("settled_at") is not None:
        return "liquidada"
    return "en_juego" if phase in ("en_juego", "terminado") else "publicada"


def _decision_figure(p: Any, *, calibrated: bool, at: datetime, decimals: int = 0) -> Probability | Missing:
    if p is None:
        return NO_DATA
    return Probability.of(float(p), calibration="calibrada" if calibrated else "sin_calibrar", as_of=at,
                          origin=DECISION_ORIGIN, evaluation=NO_EVALUATION, evaluation_version=NO_EVALUATION,
                          interval=NO_DATA, decimals=decimals)


def selections(decisions: Sequence[Mapping[str, Any]], set_items: Sequence[Mapping[str, Any]],
               outcome_figures: Sequence[OutcomeFigurePrivate], phase: MatchPhase) -> list[SelectionPrivate]:
    """Every selection of the decision layer and of the day's sets, with the outcome's one figure when the one figure
    covers it. Pure."""
    by_key: dict[Key, dict[str, Any]] = defaultdict(dict)
    for d in decisions:
        by_key[_key(d["market_key"], d["selection"], d["line"])]["decision"] = d
    for i in set_items:
        slot = by_key[_key(i["market_key"], i["selection"], i["line"])]
        if i["source"] == "qualified":
            slot["qualified"] = i
        else:
            slot["evaluation"] = i
    figure = {_key(f.market, sel, f.line): f for f in outcome_figures
              for (m, sel), code in OUTCOMES.items() if m == f.market and code == f.outcome}
    out: list[SelectionPrivate] = []
    for (market, selection, line), found in sorted(by_key.items()):
        dec = found.get("decision")
        f = figure.get((market, selection, line))
        if f is None:
            probability: Probability | Missing = _not_yet("AD-B05")
        else:
            probability = f.probability if f.readers_see else KEPT_FROM_READERS
        state = public_state(found.get("qualified"), phase)
        out.append(SelectionPrivate(
            market=market, selection=selection, line=float(line), public_state=state, probability=probability,
            published=state is not None, in_evaluation_set="evaluation" in found,
            lifecycle_state=_not_yet("AD-D02"),
            decision_state=NO_DATA if dec is None or dec["state"] not in get_args(DecisionState) else dec["state"],
            decision_probability=NO_DATA if dec is None else _decision_figure(
                dec["p_cal"], calibrated=dec["calibrator_id"] is not None, at=dec["known_at"]),
            decision_raw_probability=NO_DATA if dec is None else _decision_figure(
                dec["p_model"], calibrated=False, at=dec["known_at"], decimals=1),
            odds=NO_DATA if dec is None else _float(dec["odds"]),
            expected_value=NO_DATA if dec is None else _float(dec["ev_cal"]),
            decided_at=NO_DATA if dec is None else dec["known_at"],
            reasons=[] if dec is None else [str(x) for x in dec["reasons"] or []]))
    return out


# ── citations and evidence ───────────────────────────────────────────────────────────────────────────────────────────

def confirmation(status: str, tiers: Sequence[str], outlets: int) -> tuple[ConfirmationLevel | Missing, list[StoryWarning]]:
    """Today's status of a story in the closed vocabulary (agreed with UX, 16-nov-2026): CONFIRMED by an official source ->
    oficial, by two outlets -> dos_origenes; PROBABLE -> un_medio; RUMOR -> rumor; a contradiction and an outdated item are
    warnings, with no level until AD-C07. Pure."""
    if status == "CONFIRMED":
        if any(t in CONFIRMED_OFFICIAL_TIERS for t in tiers):
            return "oficial", []
        return ("dos_origenes" if outlets >= 2 else "un_medio"), []
    if status == "PROBABLE":
        return "un_medio", []
    if status == "RUMOR":
        return "rumor", []
    warning: StoryWarning = "contradiccion" if status == "CONTRADICTORY" else "desactualizada"
    return _not_yet("AD-C07"), [warning]


def citations(rows: Sequence[news_service.Row]) -> list[Citation]:
    """One citation per story of the match's news (the stories its cards are made of), in the news' order: status, then
    newest. ``known_at`` is when PrediGol first read the story. A story whose summary does not read as PrediGol's own
    Spanish sentence is left out (the news card words it from its kind; a citation needs words). Pure."""
    by_story: dict[str, list[news_service.Row]] = defaultdict(list)
    for r in rows:
        by_story[r.story_key].append(r)
    stories = [news_service.Story(tuple(rs)) for rs in by_story.values()]
    order = {s: i for i, s in enumerate(STATUS_ORDER)}
    stories.sort(key=lambda s: (order.get(s.status, len(order)), -s.newest.when.timestamp(), s.newest.id))
    out: list[Citation] = []
    for story in stories:
        claim = story.claim()
        if not claim.text or not claim.sources:
            continue
        first = claim.sources[0]
        level, warnings = confirmation(story.status, [s.tier for s in claim.sources],
                                       len({news_service.outlet_key(s) for s in claim.sources}))
        out.append(Citation(
            n=len(out) + 1, kind=story.newest.kind, text=claim.text, confirmation=level, warnings=warnings,
            relation=_not_yet("AD-G08"), source=Source(name=first.name, url=first.url or NO_DATA),
            published_at=first.published_at or NO_DATA,
            published_day_only=first.published_at is not None and first.published_day_only,
            known_at=min(r.retrieved_at for r in story.chosen), fact_at=NO_DATA, valid_until=NO_DATA))
    return out


def evidence(rows: Sequence[news_service.Row]) -> list[EvidenceRecord]:
    """The web's items of the match as its news read them, newest first, whatever their status or language. Pure."""
    newest = sorted(rows, key=lambda r: (r.retrieved_at, r.id), reverse=True)[:EVIDENCE_SHOWN]
    return [EvidenceRecord(
        id=r.id, kind=r.kind, status=r.status, story_key=r.story_key, claim=r.claim, source_name=r.source_name,
        source_tier=r.tier, source_url=_text(r.source_url), published_at=_when(r.published_at), known_at=r.retrieved_at,
        last_seen_at=_when(r.last_seen_at)) for r in newest]


# ── the answer ───────────────────────────────────────────────────────────────────────────────────────────────────────

def _list[T](items: list[T], empty: Missing | str) -> ItemList[T]:
    """A list, or an empty one that says why (a ``Missing``'s reason, or a reason only a list gives: ``sin_publicados``)."""
    if items:
        return ItemList[T](items=items)
    if isinstance(empty, str):
        return ItemList[T].model_validate({"items": [], "missing_reason": empty})
    return ItemList[T].model_validate({"items": [], **empty.model_dump(mode="json", exclude_none=True)})


def freshness(fx: Mapping[str, Any], packet_at: datetime | None, at: datetime) -> Freshness:
    """Stale only for a match about to be played whose packet stopped being rebuilt (``STALE_AFTER``). Pure."""
    soon = phase_of(str(fx["status_group"])) == "previo" and fx["kickoff_at"] - at <= STALE_WINDOW
    if soon and packet_at is not None and at - packet_at > STALE_AFTER:
        return Freshness(generated_at=at, stale=True, stale_reason="paquete_antiguo")
    return Freshness(generated_at=at, stale=False)


@dataclass(frozen=True)
class Inputs:
    """Everything one answer is made of, as read (``read``): the assembly from it is pure (``assemble``)."""

    at: datetime
    fixture: Mapping[str, Any]
    forecast_rows: Sequence[Mapping[str, Any]] = ()
    forecast_fixture: Mapping[str, Any] | None = None
    packet: Mapping[str, Any] | None = None
    content: Mapping[str, Any] = field(default_factory=dict)
    narrative: ReadingNarrative | None = None
    decisions: Sequence[Mapping[str, Any]] = ()
    set_items: Sequence[Mapping[str, Any]] = ()
    news_rows: Sequence[news_service.Row] = ()
    lineups: Sequence[Mapping[str, Any]] = ()
    brief: Mapping[str, Any] | None = None
    forecast_shown: bool = True
    reading_shown: bool = True
    narrative_shown: bool = False
    news_shown: bool = True


def read(conn: Conn, fixture_id: int, *, at: datetime | None = None) -> Inputs:
    """What one match's answer is made of as of ``at`` (now by default), and the switches that decide what a reader is
    shown; 404 for an unknown match. Reading only."""
    fx = fetch_one(conn, FIXTURE_SQL, {"f": fixture_id})
    if fx is None:
        raise ApiError(404, "not_found", "no such fixture")
    moment = at or now()
    rows = fetch_all(conn, forecast_service.FORECAST_SQL,
                     {"f": fixture_id, "version": forecast_service.VERSION, "at": moment})
    basis = reading_service.reading_basis(conn, fixture_id, at=moment, fixture=fx)
    return Inputs(
        at=moment, fixture=fx, forecast_rows=rows,
        forecast_fixture=None if rows else fetch_one(conn, forecast_service.FIXTURE_SQL, {"f": fixture_id}),
        packet=fetch_one(conn, PACKET_SQL, {"f": fixture_id, "at": moment}), content=basis.content,
        narrative=reading_service.narrative_for(conn, basis, preview=True),
        decisions=fetch_all(conn, DECISIONS_SQL, {"f": fixture_id, "v": DECISION_CORE, "at": moment}),
        set_items=fetch_all(conn, SET_ITEMS_SQL, {"f": fixture_id, "at": moment}),
        news_rows=news_service.stored_items(conn, fixture_id, at=moment),
        lineups=fetch_all(conn, LINEUPS_SQL, {"f": fixture_id}),
        brief=fetch_one(conn, BRIEF_SQL, {"f": fixture_id, "at": moment}),
        forecast_shown=forecast_service.users_may_see(), reading_shown=reading_service.users_may_see(),
        narrative_shown=reading_service.narrative_mode() == "on", news_shown=news_service.users_may_see())


def assemble(x: Inputs) -> MatchIntelligencePrivate:
    """The private answer of C-01 from what was read. Pure: the public one is ``to_public`` of it."""
    fx = x.fixture
    outcome_figures = figures(x.forecast_rows, readers_see=x.forecast_shown)
    packet_at: datetime | None = x.packet["as_of"] if x.packet else None
    if not x.reading_shown:
        context: ItemList[SideStakes] = _list([], KEPT_FROM_READERS)
        arrive: ItemList[SideForm] = _list([], KEPT_FROM_READERS)
    elif packet_at is None:
        context, arrive = _list([], NO_DATA), _list([], NO_DATA)
    else:
        context = _list(stakes(x.content, fx, packet_at), NO_DATA)
        arrive = _list(form(x.content, fx, packet_at), NO_DATA)
    # While the owner keeps the chronicle from readers the public field says so whether or not one was written: its
    # reason must not tell a reader that a chronicle exists in the shadow.
    reader_chronicle = chronicle_of(x.narrative) if x.narrative_shown else KEPT_FROM_READERS
    picks = selections(x.decisions, x.set_items, outcome_figures, phase_of(str(fx["status_group"])))
    cited = _list(citations(x.news_rows), NO_DATA) if x.news_shown else _list([], KEPT_FROM_READERS)
    return MatchIntelligencePrivate(
        freshness=freshness(fx, packet_at, x.at),
        match=match_info(fx),
        probabilities=_list(outcome_figures,
                            _why_no_figure(x.forecast_fixture) if x.forecast_shown else KEPT_FROM_READERS),
        context=context, form=arrive,
        official_lineup=lineup(x.lineups, fx),
        reader_chronicle=reader_chronicle,
        selections=_list(picks, "sin_publicados"),
        citations=cited,
        scenarios=_not_yet(NOT_YET["scenarios"]), chronicle=_not_yet(NOT_YET["chronicle"]),
        evaluations=_not_yet(NOT_YET["evaluations"]), new_since_yesterday=_not_yet(NOT_YET["new_since_yesterday"]),
        pending_unknowns=_not_yet(NOT_YET["pending_unknowns"]), keys=_not_yet(NOT_YET["keys"]),
        risks=_not_yet(NOT_YET["risks"]), players_to_watch=_not_yet(NOT_YET["players_to_watch"]),
        packet=NO_DATA if x.packet is None else PacketRef(
            id=int(x.packet["id"]), version=str(x.packet["version"]), as_of=x.packet["as_of"],
            missing=[str(m) for m in x.packet["missing"] or []]),
        brief=brief_of(x.brief),
        chronicle_preview=chronicle_of(x.narrative),
        evidence=_list(evidence(x.news_rows), NO_DATA),
    )


def build(conn: Conn, fixture_id: int, *, at: datetime | None = None) -> MatchIntelligencePrivate:
    """The private answer of C-01 for one match as of ``at``."""
    return assemble(read(conn, fixture_id, at=at))


def _as_of(answer: MatchIntelligence) -> datetime | None:
    moments = [f.probability.as_of for f in answer.probabilities.items]
    moments += [s.known_at for s in answer.context.items]
    return max(moments, default=None)


def public(conn: Conn, fixture_id: int, *, at: datetime | None = None) -> Envelope[MatchIntelligence]:
    """The public projection: 404 while ``FBI_MATCH_INTELLIGENCE`` is off (the route does not exist for a reader)."""
    if not match_intelligence_on():
        raise ApiError(404, "not_found", "not found")
    answer = to_public(build(conn, fixture_id, at=at), MatchIntelligence)
    return ok(answer, data_as_of=_as_of(answer))


def private(conn: Conn, fixture_id: int, *, at: datetime | None = None) -> Envelope[MatchIntelligencePrivate]:
    """The private projection, for the Admin Console (``require_admin``): no switch."""
    answer = build(conn, fixture_id, at=at)
    return ok(answer, data_as_of=_as_of(answer))
