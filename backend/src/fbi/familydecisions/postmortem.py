"""WHAT A FAMILY LEARNS FROM ONE DECISION (plan F11) - ``pm-fam-v1``: after the match, the decision a family left standing is asked what became of
it and why. The third step of the cycle of a family in shadow (decision, settlement, post-mortem, memory).

WHICH DECISION. The hourly passes revise a family's decision as the forecasts and the prices move: one match can hold several rows for the same
model and market (``intel.decisions`` is append-only, a revision is a new row). Every one of them is settled (``fbi.familydecisions.outcomes``: a
row is cheap and its outcome is a fact), but the post-mortem studies the one that STOOD - the last of each model, market and match - and only when
that last word was a selection (INVESTIGACION) and not a rejection by the filters. The revisions are the same bet seen again: studying each would
weigh a match by the number of times its price moved, and the memory that sums the post-mortems would read a match that was repriced six times as
six matches. How many revisions there were is in the row's evidence.

WHAT IT SAYS, with the pipeline's own definitions (``fbi.intel.postmortem``), not copies of them:

    quality    the price taken against the close, by the one closing-line value (``fbi.market.closing_value``, ``clv-v1``): above +1 % GOOD, below
               -1 % BAD, between NEUTRAL, no close UNKNOWN. The decision's quality, never the result's
    verdict    luck against decision, quality x result: won with a GOOD or NEUTRAL price MERECIDO, with a BAD one SUERTE; lost with a GOOD or NEUTRAL
               price VARIANZA, with a BAD one ERROR; push or void NULO; no close SIN_DATOS (``verdict_of``)
    causes     what happened in the match that the model could not see - a red card, a penalty, an early goal, an early substitution, the cards
               against what the referee usually shows (``causes_of``, from the events and the statistics of the match). The expected-goals reading
               of the pipeline is a reading of GOALS and is not applied to corners or cards
    count      the number the line was graded on (the corners of the match, the cards, the goals of a half) and by how much it passed the line,
               for the bets that compare ONE number with a line; none for a bet on two (the 1X2 of the corners, HT/FT)
    answers    the questions of the post-mortem, in Spanish, from stored numbers only: the probability the family stated (NOT calibrated) against
               the books' at the decision and at the close, the price, the count, what was not seen, luck or decision, what it teaches

It reads what is stored - the decision, the outcome that settled it, the events and the statistics of the match - and nothing else. In particular it
does not read the table of forecasts of the models: the forecast the decision cited is named in the decision's own record (its ``model`` filter),
and the row says which. Zero requests to the provider, zero AI. Written once per decision and version (``intel.family_postmortems`` is append-only: a rule that
changes is a new version, ``pm-fam-v2``, and the rows of this one stay as they were written).

WHERE IT STOPS. What a family learns is the future of the match it describes and it is derived: no forecast, decision, packet or pick reads it
(``tests/unit/test_postmortem_isolation.py``). It is kept apart from the pipeline's post-mortem on purpose - see revision 0094.
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final

import psycopg
import structlog
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fbi.core.decision_versions import POSTMORTEM_FAMILIES
from fbi.families import score
from fbi.familydecisions import decide as fd
from fbi.familydecisions import outcomes as fo
from fbi.intel import postmortem as pipeline
from fbi.market.rules import RULES_BY_MEASURE

log = structlog.get_logger(__name__)

VERSION: Final = POSTMORTEM_FAMILIES
"""The version of the post-mortems of the families: the ``version`` of their rows in ``intel.family_postmortems``."""
DECISION_VERSION: Final = fd.VERSION
OUTCOME_VERSION: Final = fo.VERSION
LOOKBACK: Final = fo.LOOKBACK
"""How far back the kick-offs of the decisions that are looked for go: the horizon of the settlement, so that what it settled is studied."""
BATCH: Final = 5000
"""The most decisions one pass studies (the rest wait for the next night)."""
CHUNK: Final = 100
"""Matches whose events and statistics are read at a time."""
ERRORS_KEPT: Final = 5
USUAL_MATCHES: Final = 5
"""Matches a referee needs before what he usually shows counts as usual (the pipeline's number)."""
COUNT_KINDS: Final = frozenset({"over_under", "odd_even"})
"""The bets that compare ONE count with a line (or its parity); the others compare two."""
COUNT_Q: Final = Decimal("0.01")
UNIT_Q: Final = Decimal("0.0001")

FAMILY_ES: Final = {"CORNERS": "córners", "CARDS": "tarjetas", "YELLOW": "amarillas", "GOALS_HALF": "goles por mitades"}
"""The family as the owner reads it. A family that is not here is written with its own name."""
RESULT_ES: Final = {"win": "ganó", "loss": "perdió", "push": "devuelta", "void": "anulada", "half_win": "ganó la mitad", "half_loss": "perdió la mitad"}
NOT_FOR: Final[Mapping[str, frozenset[str]]] = {
    "CORNERS": frozenset({"cards_above_referee", "cards_below_referee"}),
    "GOALS_HALF": frozenset({"cards_above_referee", "cards_below_referee"}),
}
"""Causes of the pipeline's list that say nothing of a family's count: the cards a referee shows do not explain the corners of a match."""
LESSON: Final = {
    "MERECIDO": "decisión y resultado alineados: se suma a la memoria de la familia, nada que cambiar",
    "VARIANZA": "decisión con precio bueno o neutro que perdió: varianza; no se toca el modelo",
    "SUERTE": "ganó con el precio peor que el cierre: no enseña nada a favor del modelo",
    "ERROR": "precio peor que el cierre y perdió: a revisar en el patrón del mercado de la familia, no por este partido",
    "NULO": "sin resultado que juzgar (devuelta o anulada)",
    "SIN_DATOS": "sin cierre para juzgar el precio de la decisión",
}

STOOD_SQL: Final = """
WITH seen AS (
    SELECT d.id, d.fixture_id, d.model_name, d.market_key, d.selection, d.line, d.kickoff_at, d.known_at, d.checkpoint, d.state, d.odds,
           d.bookmaker_id, d.price_at, d.n_bookmakers, d.p_model, d.p_market,
           jsonb_path_query_first(d.filters, '$[*] ? (@.key == "model").data') AS forecast,
           row_number() OVER (PARTITION BY d.fixture_id, d.model_name, d.market_key ORDER BY d.known_at DESC, d.id DESC) AS rn,
           count(*) OVER (PARTITION BY d.fixture_id, d.model_name, d.market_key) AS revisions
      FROM intel.decisions d
     WHERE d.decision_version = %(decision_version)s AND d.pick_id IS NULL AND d.odds IS NOT NULL
       AND d.known_at >= %(since)s - %(horizon)s::interval AND d.kickoff_at >= %(since)s
)
SELECT s.id, s.fixture_id, s.model_name, s.market_key, s.selection, s.line, s.kickoff_at, s.known_at, s.checkpoint, s.odds, s.bookmaker_id,
       s.price_at, s.n_bookmakers, s.p_model, s.p_market, s.forecast, s.revisions,
       o.result_status, o.profit_flat, o.close_p_fair, o.close_odds, o.close_as_of, o.close_minutes_to_ko, o.clv
  FROM seen s
  JOIN intel.decision_outcomes o ON o.decision_id = s.id AND o.version = %(outcome_version)s
  LEFT JOIN intel.family_postmortems p ON p.decision_id = s.id AND p.version = %(version)s
 WHERE s.rn = 1 AND s.state = 'INVESTIGACION' AND p.id IS NULL
 ORDER BY s.kickoff_at, s.id
 LIMIT %(limit)s
"""
"""The decisions that stood - the last of each model, market and match - that are selections, have an outcome and have no post-mortem yet. The last
word is taken over the revisions of every state: a rejection that followed a selection is the family's last word, and nothing is studied."""

MATCH_SQL: Final = """
SELECT f.id AS fixture_id, cs.competition_id, fr.referee_id
  FROM core.fixtures f
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  LEFT JOIN core.fixture_referees fr ON fr.fixture_id = f.id
 WHERE f.id = ANY(%(fixtures)s)
"""
"""The competition of each match and the referee the identity layer placed in it (none when it has not)."""

INSERT_SQL: Final = (
    "INSERT INTO intel.family_postmortems (decision_id, version, created_at, fixture_id, kickoff_at, family, model_name, market_key, selection, line, "
    "competition_id, referee_id, result, quality, verdict, odds, p_model, p_decision, p_close, clv, profit_flat, actual, margin, causes, answers, "
    "evidence) VALUES (%(decision_id)s, %(version)s, %(at)s, %(fixture_id)s, %(kickoff_at)s, %(family)s, %(model)s, %(key)s, %(selection)s, %(line)s, "
    "%(competition_id)s, %(referee_id)s, %(result)s, %(quality)s, %(verdict)s, %(odds)s, %(p_model)s, %(p_decision)s, %(p_close)s, %(clv)s, %(profit)s, "
    "%(actual)s, %(margin)s, %(causes)s, %(answers)s, %(evidence)s) ON CONFLICT (decision_id, version) DO NOTHING")


@dataclass(frozen=True, slots=True)
class Stood:
    """A decision that stood at the kick-off, with what settled it."""

    id: int
    fixture_id: int
    family: str | None
    model: str
    key: str
    selection: str
    line: Decimal
    kickoff_at: datetime
    known_at: datetime
    checkpoint: str
    odds: Decimal
    bookmaker_id: int | None
    price_at: datetime | None
    books: int | None
    p_model: Decimal
    p_market: Decimal | None
    revisions: int
    forecast: Mapping[str, Any]
    """What the ``model`` filter of the decision records of the forecast it used: which, when it was written, when its data was cut off."""
    result: str
    profit: Decimal
    p_close: Decimal | None
    close_odds: Decimal | None
    close_as_of: datetime | None
    close_minutes: int | None
    clv: Decimal | None


@dataclass(frozen=True, slots=True)
class Built:
    """A post-mortem, as ``intel.family_postmortems`` holds it (but for the match's own competition and referee, which the pass adds)."""

    decision_id: int
    family: str
    result: str
    quality: str
    verdict: str
    actual: Decimal | None
    margin: Decimal | None
    causes: list[dict[str, Any]]
    answers: dict[str, Any]
    evidence: dict[str, Any]


class UnreadableError(ValueError):
    """A decision the post-mortem cannot read: it does not say which family it is of."""


def plain(value: Decimal) -> str:
    """A Decimal as a person writes it: 10.50 is 10.5 and 11.00 is 11."""
    return format(value.normalize(), "f")


def number(value: Decimal | float | None, places: int = 6) -> float | None:
    """A number as JSON holds it (a Decimal or a date is not JSON)."""
    return None if value is None else round(float(value), places)


def stood_from(r: Mapping[str, Any]) -> Stood:
    forecast = r["forecast"] if isinstance(r["forecast"], dict) else {}
    family = forecast.get("family")
    return Stood(
        int(r["id"]), int(r["fixture_id"]), str(family) if isinstance(family, str) else None, str(r["model_name"]), str(r["market_key"]),
        str(r["selection"]), Decimal(r["line"]), r["kickoff_at"], r["known_at"], str(r["checkpoint"]), Decimal(r["odds"]),
        None if r["bookmaker_id"] is None else int(r["bookmaker_id"]), r["price_at"], None if r["n_bookmakers"] is None else int(r["n_bookmakers"]),
        Decimal(r["p_model"]), None if r["p_market"] is None else Decimal(r["p_market"]), int(r["revisions"]), forecast, str(r["result_status"]),
        Decimal(r["profit_flat"]), None if r["close_p_fair"] is None else Decimal(r["close_p_fair"]),
        None if r["close_odds"] is None else Decimal(r["close_odds"]), r["close_as_of"],
        None if r["close_minutes_to_ko"] is None else int(r["close_minutes_to_ko"]), None if r["clv"] is None else Decimal(r["clv"]))


# ── what it says (pure) ──────────────────────────────────────────────────────────────────────────────────────────────

def counted(key: str, line: Decimal, counts: Mapping[str, int] | None) -> tuple[Decimal | None, Decimal | None]:
    """The ONE count the bet was graded on and by how much it passed the line (positive: over it), for the bets that compare one number with a
    line; ``(count, None)`` for odd/even, which reads the count but has no line to pass; ``(None, None)`` when the bet reads two numbers (the 1X2 of
    the corners, HT/FT), when a count is unknown, or when the key is not one the rules read. An unknown count is never a zero."""
    if counts is None:
        return None, None
    try:
        kind, subject = score.key_shape(key)
        rule = RULES_BY_MEASURE[score.measure_of(key)]
    except (KeyError, ValueError):
        return None, None
    if kind not in COUNT_KINDS or len(rule.columns) != 2:
        return None, None
    home, away = (counts.get(column) for column in rule.columns)
    if home is None or away is None:
        return None, None
    actual = Decimal(home + away if subject == "match" else home if subject == "home" else away)
    return actual.quantize(COUNT_Q), (None if kind != "over_under" else (actual - line).quantize(COUNT_Q))


def causes_for(s: Stood, events: Sequence[dict[str, Any]], stats: dict[str, dict[str, Any]], usual: float | None) -> list[dict[str, Any]]:
    """What happened in the match that the model could not see: the pipeline's reading of the events and the statistics, for a bet on a count. The
    expected-goals comparison is a reading of goals and is left out (the bet is not on goals), the side a red card hurt is not read as for or
    against the selection (the selection is a count, not a side), and the cards a referee shows are left out of the families they explain nothing of."""
    wanted = pipeline.causes_of({"market_key": "COUNT", "selection": s.selection, "line": float(s.line)}, list(events), stats, None, usual)
    return [c for c in wanted if c["code"] not in NOT_FOR.get(s.family or "", frozenset())]


def log_loss(p: Decimal, result: str) -> float | None:
    """The log loss of the probability stated against what happened, for a bet that was won or lost outright (none for a half or a push)."""
    if result not in ("win", "loss"):
        return None
    clipped = min(max(float(p), 1e-4), 1 - 1e-4)
    return round(-math.log(clipped if result == "win" else 1 - clipped), 4)


def answers_for(s: Stood, *, quality: str, verdict: str, actual: Decimal | None, margin: Decimal | None, causes: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """The questions of the post-mortem of a family, answered only from stored numbers. Spanish, for the owner."""
    family = FAMILY_ES.get(s.family or "", s.family or s.key)
    bet = f"{s.key} {s.selection}" + (f" {plain(s.line)}" if s.line else "") + f" a {s.odds:.2f}"
    count = ("" if actual is None else f" con {plain(actual)}"
             + ("" if margin is None or margin == 0 else f" ({plain(abs(margin))} {'por encima' if margin > 0 else 'por debajo'} de la línea)"))
    price = ("sin cierre para medir el precio" if s.clv is None else f"precio {'mejor' if quality == 'GOOD' else 'peor' if quality == 'BAD' else 'en línea'}"
             f" que el cierre (CLV {float(s.clv):+.1%})")
    return {
        "resumen": f"{family} · {bet}: {RESULT_ES.get(s.result, s.result)}{count}; {price}: {verdict}",
        "probabilidad": {
            "p_familia": number(s.p_model), "calibracion": str(s.forecast.get("calibration") or "UNCALIBRATED"), "p_decision": number(s.p_market),
            "p_cierre": number(s.p_close), "log_loss": log_loss(s.p_model, s.result),
            "texto": (f"la familia dijo {float(s.p_model):.3f} (sin calibrar)" + ("" if s.p_market is None else f"; las casas {float(s.p_market):.3f} al decidir")
                      + ("" if s.p_close is None else f" y {float(s.p_close):.3f} al cierre"))},
        "precio": {"clv": number(s.clv), "calidad": quality, "cuota": number(s.odds, 3), "casas": s.books, "texto": price},
        "conteo": {"cuenta": number(actual, 2), "linea": number(s.line, 2), "margen": number(margin, 2),
                   "texto": "la apuesta compara dos cuentas: no hay una sola que mirar" if actual is None else f"{plain(actual)} frente a la línea {plain(s.line)}"},
        "no_visto": [c["text"] for c in causes] or ["nada fuera de lo normal en los eventos registrados"],
        "suerte_o_decision": verdict,
        "aprendizaje": LESSON[verdict],
        "cambiar_algo": "no por un solo partido: queda en la memoria de la familia; el paso a otra cosa que sombra es del dueño",
    }


def build(s: Stood, *, counts: Mapping[str, int] | None, events: Sequence[dict[str, Any]], stats: dict[str, dict[str, Any]],
          usual: float | None) -> Built:
    """The post-mortem of a decision from everything stored of it and of its match. Pure: the same inputs, the same row."""
    if s.family is None:
        raise UnreadableError("the decision does not say which family it is of")
    quality = pipeline.quality_of(None if s.clv is None else float(s.clv))
    verdict = pipeline.verdict_of(s.result, quality)
    actual, margin = counted(s.key, s.line, counts)
    causes = causes_for(s, events, stats, usual)
    evidence = {
        "forecast": {"id": s.forecast.get("forecast_id"), "known_at": s.forecast.get("forecast_known_at"),
                     "data_cut_off": s.forecast.get("forecast_cutoff"), "calibration": s.forecast.get("calibration")},
        "decision": {"checkpoint": s.checkpoint, "known_at": s.known_at.isoformat(), "revisions": s.revisions, "bookmaker_id": s.bookmaker_id,
                     "price_at": None if s.price_at is None else s.price_at.isoformat(), "books": s.books},
        "outcome": {"version": OUTCOME_VERSION, "close_odds": number(s.close_odds, 3),
                    "close_as_of": None if s.close_as_of is None else s.close_as_of.isoformat(), "close_minutes_to_ko": s.close_minutes},
        "match": {"kickoff_at": s.kickoff_at.isoformat(), "events": len(events), "stats": bool(stats), "counts": dict(counts or {}),
                  "referee_usual_cards": number(usual, 2)},
    }
    return Built(s.id, s.family, s.result, quality, verdict, actual, margin, causes,
                 answers_for(s, quality=quality, verdict=verdict, actual=actual, margin=margin, causes=causes), evidence)


# ── what is read ─────────────────────────────────────────────────────────────────────────────────────────────────────

def _rows(conn: psycopg.Connection[Any], sql: str, params: Mapping[str, Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def load_stood(conn: psycopg.Connection[Any], *, at: datetime, lookback: timedelta = LOOKBACK, limit: int = BATCH) -> list[Stood]:
    """The decisions that stood, settled and not yet studied, of the matches that kicked off in the last ``lookback``."""
    params = {"decision_version": DECISION_VERSION, "outcome_version": OUTCOME_VERSION, "version": VERSION, "since": at - lookback,
              "horizon": fd.HORIZON, "limit": limit}
    return [stood_from(r) for r in _rows(conn, STOOD_SQL, params)]


@dataclass
class Facts:
    """What the pass reads of the matches it studies, by match."""

    counts: Mapping[int, Mapping[str, int]]
    events: Mapping[int, list[dict[str, Any]]]
    stats: Mapping[int, dict[str, dict[str, Any]]]
    competition: Mapping[int, int | None]
    referee: Mapping[int, int | None]
    usual: Mapping[int, float]
    """What each referee usually shows (cards a match, over the 400 days before the earliest match studied), for the referees of five matches or more."""


def load_facts(conn: psycopg.Connection[Any], rows: Sequence[Stood]) -> Facts:
    fixtures = sorted({s.fixture_id for s in rows})
    measures = score.measures_to_read(s.key for s in rows if _readable(s.key))
    counts: Mapping[int, Mapping[str, int]] = (
        score.load_counts(conn, measures, since=min(s.kickoff_at for s in rows), until=max(s.kickoff_at for s in rows)) if measures else {})
    events: dict[int, list[dict[str, Any]]] = defaultdict(list)
    stats: dict[int, dict[str, dict[str, Any]]] = defaultdict(dict)
    competition: dict[int, int | None] = {}
    referee: dict[int, int | None] = {}
    for start in range(0, len(fixtures), CHUNK):
        chunk = fixtures[start:start + CHUNK]
        for r in _rows(conn, pipeline.EVENTS_SQL, {"fixtures": chunk}):
            events[int(r["fixture_id"])].append(r)
        for r in _rows(conn, pipeline.STATS_SQL, {"fixtures": chunk}):
            stats[int(r["fixture_id"])][str(r["team_side"])] = r
        for r in _rows(conn, MATCH_SQL, {"fixtures": chunk}):
            competition[int(r["fixture_id"])] = None if r["competition_id"] is None else int(r["competition_id"])
            referee[int(r["fixture_id"])] = None if r["referee_id"] is None else int(r["referee_id"])
    ids = sorted({i for i in referee.values() if i is not None})
    usual = ({int(r["referee_id"]): float(r["cards"]) for r in _rows(conn, pipeline.REFEREE_BY_ID_SQL, {"ids": ids, "before": min(s.kickoff_at for s in rows)})
              if int(r["n"]) >= USUAL_MATCHES} if ids else {})
    return Facts(counts, events, stats, competition, referee, usual)


def _readable(key: str) -> bool:
    try:
        score.key_shape(key)
        score.measure_of(key)
    except ValueError:
        return False
    return True


# ── a pass ───────────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass
class StudyReport:
    open: int = 0
    """Decisions that stood, are settled and had no post-mortem."""
    written: int = 0
    unreadable: int = 0
    """Decisions the post-mortem cannot read (they do not say which family they are of)."""
    failed: int = 0
    by_verdict: dict[str, int] = field(default_factory=dict)
    by_family: dict[str, int] = field(default_factory=dict)
    errors: list[str] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {"open": self.open, "written": self.written, "unreadable": self.unreadable, "failed": self.failed, "by_verdict": self.by_verdict,
                "by_family": self.by_family, "errors": self.errors[:ERRORS_KEPT]}


def study(conn: psycopg.Connection[Any], *, at: datetime, lookback: timedelta = LOOKBACK, limit: int = BATCH, write: bool = True) -> StudyReport:
    """Write the post-mortem of every decision that stood, was settled and has none under this version. Idempotent (a decision has one row per
    version); commits nothing itself. One the database refuses, or the pass cannot build, costs only itself. With ``write=False`` it reads and builds
    and writes nothing."""
    report = StudyReport()
    rows = load_stood(conn, at=at, lookback=lookback, limit=limit)
    report.open = len(rows)
    if not rows:
        return report
    facts = load_facts(conn, rows)
    for s in rows:
        try:
            built = build(s, counts=facts.counts.get(s.fixture_id), events=facts.events.get(s.fixture_id, []), stats=facts.stats.get(s.fixture_id, {}),
                          usual=_usual(facts, s.fixture_id))
        except UnreadableError as exc:  # a decision that does not say which family it is of: counted, never a reason to stop the pass
            report.unreadable += 1
            report.errors.append(f"{s.id}/{s.fixture_id}/{s.key}: {exc}"[:300])
            continue
        except Exception as exc:  # research: one decision that cannot be read never costs the others
            report.failed += 1
            report.errors.append(f"{s.id}/{s.fixture_id}/{s.key}: {type(exc).__name__}: {exc}"[:300])
            log.error("family_postmortems.decision_failed", decision=s.id, fixture=s.fixture_id, key=s.key, error=type(exc).__name__, detail=str(exc)[:300])
            continue
        if write:
            try:
                with conn.transaction():  # a savepoint: a row the database refuses costs that row, not the rest of the pass
                    wrote = _insert(conn, s, built, facts, at=at)
            except Exception as exc:
                report.failed += 1
                report.errors.append(f"{s.id}/{s.fixture_id}/{s.key}: {type(exc).__name__}: {exc}"[:300])
                log.error("family_postmortems.decision_failed", decision=s.id, fixture=s.fixture_id, key=s.key, error=type(exc).__name__, detail=str(exc)[:300])
                continue
            if not wrote:
                continue
        report.written += 1
        report.by_verdict[built.verdict] = report.by_verdict.get(built.verdict, 0) + 1
        report.by_family[built.family] = report.by_family.get(built.family, 0) + 1
    return report


def _usual(facts: Facts, fixture_id: int) -> float | None:
    referee = facts.referee.get(fixture_id)
    return None if referee is None else facts.usual.get(referee)


def _insert(conn: psycopg.Connection[Any], s: Stood, b: Built, facts: Facts, *, at: datetime) -> bool:
    params = {
        "decision_id": s.id, "version": VERSION, "at": at, "fixture_id": s.fixture_id, "kickoff_at": s.kickoff_at, "family": b.family, "model": s.model,
        "key": s.key, "selection": s.selection, "line": s.line, "competition_id": facts.competition.get(s.fixture_id),
        "referee_id": facts.referee.get(s.fixture_id), "result": b.result, "quality": b.quality, "verdict": b.verdict, "odds": s.odds,
        "p_model": s.p_model, "p_decision": s.p_market, "p_close": s.p_close, "clv": s.clv, "profit": s.profit.quantize(UNIT_Q), "actual": b.actual,
        "margin": b.margin, "causes": Jsonb(b.causes), "answers": Jsonb(b.answers), "evidence": Jsonb(b.evidence)}
    with conn.cursor() as cur:
        cur.execute(INSERT_SQL, params)
        return cur.rowcount > 0


def run_step(conn: psycopg.Connection[Any], *, at: datetime) -> dict[str, Any]:
    """The step of the nightly job: nothing while the switch of the families' decisions is ``off``; in ``shadow`` the post-mortem of the decisions
    that were settled. A step of its own in the job (``fbi.intel.cycle.run_nightly``): if it raises, the job writes it in its record and the others
    still run."""
    chosen = fd.mode()
    if chosen == "off":
        return {"mode": chosen}
    return {"mode": chosen, **study(conn, at=at).as_dict()}
