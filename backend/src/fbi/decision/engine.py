"""``decision-v2``: the shared stages of the one Decision & Risk Engine, in SHADOW (plan IA, P1, IA-012).

``decide(world, candidate)`` takes ONE candidate of any family (``fbi.decision.families``) through the stages below and returns a
``Decision2``: every stage's verdict and reason, the objects kept apart (prediction, price, value, context, risk), and a state of
``state-v2`` (``fbi.intel.state_v2``). ``decide_all`` does it for the candidates of one moment and adds the stage that needs them all
(correlation). Nothing here writes, stakes or publishes: the stake is the portfolio's.

THE STAGES (numbered as decision-v1's ten filters, whose thresholds are IMPORTED from ``fbi.intel.decision``, never copied):

     1 data         the match still to play, >= MIN_MINUTES away, its competition's data fit, not quarantined, the forecast not
                    older than the family's ``forecast_max_age``                                                      -> REJECTED
     2 model        the market's model gave a probability (with an interval where the family requires one)        -> REJECTED
                    (the pick's own probability - decision-v1's - or, in the replay's measurement, the common probability view
                    of the selection, ``PROBABILITY_SOURCES``, ``fbi.decision.view.judged``)
     3 market       a price from >= MIN_BOOKS books, not an outlier (MAX_PRICE_EDGE), not older than MAX_PRICE_AGE   -> REJECTED / WATCH
                    (the price the candidate carries: decision-v1's consensus of a capture, or the book's answer in force at the
                    moment - ``PRICE_SOURCES``, ``fbi.decision.book_price`` - with its age either way)
     4 calibration  a CHAMPION calibrator for (market, model); the best fit is shown, never approves                   -> ABSTAIN
                    (with the common view: the view's own seal - calibrated by a champion with a fresh price, or «Sin
                    calibrar» with its reason, and then no calibrated probability to judge the value with)
     5 value        calibrated EV >= EV_MIN and edge >= EDGE_MIN at the best price; no calibrated EV with a price      -> REJECTED / ABSTAIN
     6 context      hard rules (an unplayable or quarantined match; a key absence on the chosen side, confirmed by the
                    line-ups -> REJECTED, reported -> CAUTION), the review a decision-v1 reads (REJECT / DOWNGRADE ->
                    CAUTION), and the Council ONLY as a typed adjustment (ctx-adj-v1: BLOQUEA -> REJECTED, RESERVA ->
                    CAUTION, FALTA_INFO -> WATCH, CONFIRMA / SIN_COUNCIL -> nothing). Every effect only LOWERS.
     7 risk         odds above RISK_MAX_ODDS, calibrated p below RISK_MIN_P, interval wider than RISK_MAX_WIDTH, and the
                    market's signals when given (market-signals-v1: steam against the model -> CAUTION); a signal is an
                    input to risk, never to a probability                                                             -> CAUTION
     8 correlation  one RECOMMENDED per match among the families that correlate: the best score stays             -> CAUTION
     9 price        at a final checkpoint (FINAL_CHECKPOINTS) the price at most FINAL_FRESH old                       -> CAUTION
    10 final        RECOMMENDED only with the market's edge validated out of sample (edge-gate-v1) -> ABSTAIN; a family
                    not promoted is held at ABSTAIN (``families.CAP_CODE``). The labels (PICK_PREMIUM, CANDIDATO_PARLAY)
                    stay labels on RECOMMENDED.

THE STATE is the lowest effect (``RANK``: REJECTED < ABSTAIN < WATCH < CAUTION < RECOMMENDED), which is decision-v1's precedence
(RECHAZADO > INVESTIGACION > CAUTELA > APROBADO) with INVESTIGACION split as state-v2 splits it: the effect of each decision-v1 reason
code is read from ``state_v2`` (``CODE_STATE``), so a reason means here what it means there. Every effect can only lower.

WHERE IT DIFFERS FROM THE LAYERS IT REPLACES, on purpose (the replay attributes each to its stage):

* the edge gate (10) reads the state the selection has WITHOUT its context. decision-v1 gates only what is APROBADO after every filter,
  so a context that lowers a selection with no validated edge to CAUTELA (a key absence reported, a review REJECT or DOWNGRADE) lifts
  it from INVESTIGACION to CAUTELA - the context RAISES its state. Here it stays ABSTAIN. As in decision-v1, a risk (7) or a stale
  final price (9) is still a CAUTION whatever the edge;
* a family that is not promoted is held at ABSTAIN, where decision-fam-v1 holds it at INVESTIGACION: a stale price alone (WATCH in
  state-v2) is ABSTAIN here, because no fresh price makes a family in shadow recommendable;
* correlation ties break on the selection, not on the order the database returned the rows in, and a Council's adjustment never takes
  a selection out of the competition for its match (``Assessed.competes``).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import datetime
from typing import Any, Final

from fbi.decision.families import CAP_CODE, Candidate, FamilyParams, GateStatus
from fbi.intel import decision
from fbi.intel import score as scoring
from fbi.intel.context_adjustment import EFFECT as ADJ_EFFECT_V1
from fbi.intel.context_adjustment import AdjVerdict, ContextAdjustment
from fbi.intel.decision import Key
from fbi.intel.state_v2 import DIRECT, INVESTIGATION_RULES, REASON_EFFECT, StateV2

VERSION: Final = "decision-v2"

CONSENSUS: Final = "consensus"
BOOK: Final = "book"
PRICE_SOURCES: Final = (CONSENSUS, BOOK)
"""Where the price of a selection comes from (``Price.source``). ``consensus``: decision-v1's own, the newest Shin consensus of a capture
(the default, and the evidence of P1). ``book``: the answer in force in the odds book at the moment - a capture's or a book refresh's -
priced the same way (``fbi.decision.book_price``, plan INT-A06). The stages read either alike: only the price and its age can differ."""

OWN: Final = "own"
COMMON: Final = "common"
PROBABILITY_SOURCES: Final = (OWN, COMMON)
"""Which probability the stages judge (``Prediction.source``). ``own``: the pick's, calibrated by stage 4's calibrator - decision-v1's own (the
default, and the evidence of P1). ``common``: the common probability view of the selection (``fbi.forecasting.market_view``, ``forecast-v1``),
the number the Match Center states - the same model, a market that adds up to one, calibrated only by a champion with a fresh price and
otherwise «Sin calibrar» - set on the candidate by ``fbi.decision.view.judged`` (plan INT-A03). A selection the view does not cover is judged
with its own probability and says why (``Prediction.missing``)."""
VIEW_BASIS: Final[Mapping[str, str]] = {"no_champion": "sin calibrador campeón", "needs_price": "sin precio fresco",
                                         "not_applicable": "el calibrador no se pudo aplicar"}
"""Why the common view is «Sin calibrar» (``market_view.BASIS_*``; a test holds the keys to them)."""

STAGES: Final = ("data", "model", "market", "calibration", "value", "context", "risk", "correlation", "price", "final")
NUMBER: Final[Mapping[str, int]] = {s: i + 1 for i, s in enumerate(STAGES)}

RANK: Final[Mapping[StateV2, int]] = {"REJECTED": 0, "ABSTAIN": 1, "WATCH": 2, "CAUTION": 3, "RECOMMENDED": 4}
"""The order of the states, the most conservative first. ABSTAIN is below WATCH: a structural lack wins over a wait (state-v2)."""


def _code_state() -> dict[str, StateV2]:
    kind = {code: k for code, _, _, k in INVESTIGATION_RULES}
    return {code: (kind[code] if v1 == "INVESTIGACION" else DIRECT[v1]) for code, v1 in REASON_EFFECT.items()}


V1_STAGE: Final[Mapping[str, str]] = {"ev": "value"}
"""decision-v1's filter keys where this engine names the stage otherwise."""

CODE_STAGE: Final[dict[str, str]] = {
    "data": "data", "model": "model", "no_price": "market", "thin_market": "market", "price_outlier": "market", "price_stale": "market",
    "not_calibrated": "calibration", "ev_unknown": "value", "ev_cal_below": "value", "context_stop": "context",
    "key_absence_confirmed": "context", "key_absence_reported": "context", "ai_reject": "context", "ai_downgrade": "context", "risk": "risk",
    "correlated_same_match": "correlation", "price_not_fresh": "price", "edge_not_validated": "final"}
"""The stage that writes each reason code of decision-v1 (a test holds it to ``state_v2.REASON_EFFECT``)."""

ADJ_STATE: Final[Mapping[str, StateV2]] = {"RECHAZADO": "REJECTED", "CAUTELA": "CAUTION", "INVESTIGACION": "WATCH"}
"""ctx-adj-v1's effect (decision-v1's words) in state-v2: FALTA_INFO waits for information - WATCH, as the contract says."""
ADJ_EFFECT: Final[Mapping[AdjVerdict, StateV2 | None]] = {v: None if s is None else ADJ_STATE[s] for v, s in ADJ_EFFECT_V1.items()}


def council_code(verdict: str) -> str:
    return f"council_{verdict.lower()}"


MARKET_STEAM_AGAINST: Final = "market_steam_against"

CODE_STATE: Final[dict[str, StateV2]] = _code_state() | {
    CAP_CODE: "ABSTAIN", MARKET_STEAM_AGAINST: "CAUTION",
    **{council_code(v): s for v, s in ADJ_EFFECT.items() if s is not None}}
"""The state each reason code takes a selection down to: decision-v1's codes as state-v2 reads them, and the codes of this engine."""
CODE_STAGE.update({CAP_CODE: "final", MARKET_STEAM_AGAINST: "risk", **{council_code(v): "context" for v, s in ADJ_EFFECT.items() if s is not None}})


@dataclass(frozen=True, slots=True)
class MarketRisk:
    """What the market's signals (market-signals-v1) say of a selection, as RISK inputs: plain values, never a probability.
    Built from ``fbi.market.signals.MarketSignals`` by ``fbi.decision.market_inputs``."""

    status: str
    side: str | None
    """``toward`` / ``against`` / ``flat`` relative to the model's probability, None without one or without prices."""
    steam: bool
    movement_points: float | None
    stale: bool | None
    version: str = "market-signals-v1"

    @property
    def steam_against(self) -> bool:
        return self.steam and self.side == "against"


@dataclass(frozen=True, slots=True)
class CommonView:
    """The probability view of a selection (``fbi.forecasting.market_view``, as of the decision's moment): what a reader of the Match Center
    would see, for the model it chose. SHADOW, a measurement: no stage reads it - the state is decided as before, from ``Prediction`` -
    and it is carried so that the replay can say, selection by selection, how far decision-v2's own number is from the common one.
    Built by ``fbi.decision.view``."""

    p: float
    """The probability of the selection in the view: its market adds up to one."""
    p_model: float
    model: str
    calibration: str
    """``CALIBRATED`` (a champion applied with a fresh price) or ``UNCALIBRATED`` (the model's own number: ``basis`` says why)."""
    basis: str
    calibrator_id: int | None
    low: float | None
    high: float | None
    cutoff: datetime
    """The data cut-off of the model's numbers."""
    market_as_of: datetime | None
    """When the price that calibrated it was captured (None for an uncalibrated view)."""
    version: str
    model_version_id: int | None = None
    """The version of the model whose numbers the view states."""

    def as_json(self) -> dict[str, Any]:
        return {"p": self.p, "p_model": self.p_model, "model": self.model, "calibration": self.calibration, "basis": self.basis,
                "calibrator_id": self.calibrator_id, "interval": None if self.low is None or self.high is None else [self.low, self.high],
                "cutoff": self.cutoff.isoformat(), "market_as_of": None if self.market_as_of is None else self.market_as_of.isoformat(),
                "version": self.version, "model_version_id": self.model_version_id}


@dataclass(frozen=True, slots=True)
class Verdict:
    """One stage's verdict: passed (True), lowered the state (False) or only recorded (None), why, and the codes with their effect."""

    stage: str
    ok: bool | None
    why: str
    effects: tuple[tuple[str, StateV2], ...] = ()
    data: Mapping[str, Any] = field(default_factory=dict)

    @property
    def n(self) -> int:
        return NUMBER[self.stage]

    def as_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"n": self.n, "stage": self.stage, "ok": self.ok, "why": self.why}
        if self.effects:
            out["effects"] = [{"code": c, "state": s} for c, s in self.effects]
        if self.data:
            out["data"] = dict(self.data)
        return out


def _v(stage: str, ok: bool | None, why: str, *effects: tuple[str, StateV2], **data: Any) -> Verdict:
    return Verdict(stage, ok, why, tuple(effects), data)


def _e(code: str) -> tuple[str, StateV2]:
    return code, CODE_STATE[code]


@dataclass(frozen=True, slots=True)
class Prediction:
    model: str
    model_version_id: int | None
    p_model: float
    p_push: float
    interval: tuple[float, float] | None
    p_cal: float | None
    calibrator_id: int | None
    calibrator_role: str | None
    source: str = OWN
    """``PROBABILITY_SOURCES``: the pick's own probability or the common view's."""
    calibration: str | None = None
    """With the common view, its seal: ``CALIBRATED`` or ``UNCALIBRATED`` («Sin calibrar»); None with the pick's own."""
    basis: str | None = None
    """With the common view, why it is (not) calibrated (``champion``, ``no_champion``, ``needs_price``, ``not_applicable``)."""
    version: str | None = None
    """With the common view, its version (``forecast-v1``)."""
    missing: str | None = None
    """Why a selection asked to be judged by the common view was judged by its own probability (``fbi.decision.view``: the view does not
    forecast its market, or had no reading of it at the moment); None otherwise."""


@dataclass(frozen=True, slots=True)
class _Number:
    """The probability the stages judge, read off the candidate's row: the pick's own, or the common view's that ``view.judged`` set."""

    source: str
    model: str
    model_version_id: int | None
    p_model: float
    low: float | None
    high: float | None
    cutoff: datetime | None
    p_common: float | None
    calibrated: bool
    calibration: str | None
    basis: str | None
    calibrator_id: int | None
    version: str | None
    missing: str | None


def _number(r: Mapping[str, Any], model: str) -> _Number:
    if r.get("probability_source") == COMMON and r.get("common_p") is not None:
        return _Number(COMMON, str(r["common_model"]), r.get("common_model_version_id"), float(r["common_p_model"]), _num(r.get("common_low")),
                       _num(r.get("common_high")), r.get("common_cutoff"), float(r["common_p"]), bool(r.get("common_calibrated")),
                       r.get("common_calibration"), r.get("common_basis"), r.get("common_calibrator_id"), r.get("common_version"), None)
    return _Number(OWN, model, r.get("model_version_id"), float(r["p_model"]), _num(r.get("p_low")), _num(r.get("p_high")), r.get("data_cutoff_ts"),
                   None, False, None, None, None, None, r.get("probability_missing"))


@dataclass(frozen=True, slots=True)
class Price:
    odds: float | None
    p_market: float | None
    n_bookmakers: int | None
    price_at: datetime | None
    """When the price was last confirmed: the capture of the consensus, or the ask whose answer the book has in force."""
    age_minutes: float | None
    source: str = CONSENSUS
    """``PRICE_SOURCES``: which reading of the market the candidate was priced with."""
    confirmed_by: str | None = None
    """``capture`` or ``refresh``: the kind of ask that confirmed the price; None without a price."""
    provider_update_at: datetime | None = None
    """The provider's own stamp of the answer (when it last moved its prices), where the source reads it (``book``)."""
    missing: str | None = None
    """Why there is no price, where the source says it (``book``: the answer was withdrawn, never asked, unreadable, or does not quote the
    selection); None with a price."""


@dataclass(frozen=True, slots=True)
class Close:
    """The last price the book held of a selection before kick-off: what the closing-line value of a decision is measured against
    (``fbi.market.closing_value.clv``), with how near kick-off it was confirmed and how near kick-off the provider last moved it. Built by
    ``fbi.decision.book_price``. A MEASUREMENT carried along, in shadow: it did not exist at the moment of the decision and no stage reads it.
    For a match not played yet it is the newest answer so far, and its distance says so."""

    odds: float
    p_fair: float
    n_bookmakers: int
    checked_at: datetime
    """The ask whose answer was in force at kick-off."""
    minutes_to_kickoff: float
    confirmed_by: str
    provider_update_at: datetime | None
    provider_minutes_to_kickoff: float | None
    """How long before kick-off the provider last moved the prices of that answer (its own stamp), None without a stamp."""
    version: str

    def as_json(self) -> dict[str, Any]:
        return {"odds": self.odds, "p_fair": self.p_fair, "n_bookmakers": self.n_bookmakers, "checked_at": self.checked_at.isoformat(),
                "minutes_to_kickoff": self.minutes_to_kickoff, "confirmed_by": self.confirmed_by,
                "provider_update_at": None if self.provider_update_at is None else self.provider_update_at.isoformat(),
                "provider_minutes_to_kickoff": self.provider_minutes_to_kickoff, "version": self.version}


@dataclass(frozen=True, slots=True)
class Value:
    ev_raw: float | None
    edge_raw: float | None
    ev_cal: float | None
    edge_cal: float | None


@dataclass(frozen=True, slots=True)
class Decision2:
    """A decision of decision-v2: the state, why, every stage, and the objects it was made from. No stake: that is the portfolio's."""

    family: str
    key: Key
    model_hint: str | None
    checkpoint: str
    state: StateV2
    reason: str
    """The first code (in stage order) whose effect is the state; ``approved`` for a RECOMMENDED."""
    codes: tuple[str, ...]
    verdicts: tuple[Verdict, ...]
    label: str | None
    """PICK_PREMIUM or CANDIDATO_PARLAY on a RECOMMENDED (a label, not a state), None otherwise."""
    prediction: Prediction
    price: Price
    value: Value
    context_status: str
    adjustment: str | None
    """The ctx-adj-v1 verdict the context stage was given, None when none was."""
    market: MarketRisk | None
    score: float | None
    version: str = VERSION
    common: CommonView | None = None
    """The common probability view of the selection (a measurement in shadow; see ``CommonView``), None when none was given."""
    close: Close | None = None
    """The last price the book held of the selection before kick-off (a measurement in shadow; see ``Close``), None when none was given."""

    @property
    def ident(self) -> tuple[str, Key, str | None]:
        return self.family, self.key, self.model_hint

    def verdict(self, stage: str) -> Verdict:
        return next(v for v in self.verdicts if v.stage == stage)

    def as_json(self) -> dict[str, Any]:
        p, pr, va = self.prediction, self.price, self.value
        return {
            "version": self.version, "family": self.family, "fixture_id": self.key[0], "market_key": self.key[1], "selection": self.key[2],
            "line": str(self.key[3]), "model": p.model, "checkpoint": self.checkpoint, "state": self.state, "reason": self.reason,
            "codes": list(self.codes), "label": self.label, "score": self.score,
            "prediction": {"p_model": p.p_model, "p_push": p.p_push, "interval": None if p.interval is None else list(p.interval),
                           "p_cal": p.p_cal, "calibrator_id": p.calibrator_id, "calibrator_role": p.calibrator_role, "source": p.source,
                           "calibration": p.calibration, "basis": p.basis, "version": p.version, "missing": p.missing},
            "price": {"odds": pr.odds, "p_market": pr.p_market, "n_bookmakers": pr.n_bookmakers,
                      "price_at": None if pr.price_at is None else pr.price_at.isoformat(), "age_minutes": pr.age_minutes,
                      "source": pr.source, "confirmed_by": pr.confirmed_by,
                      "provider_update_at": None if pr.provider_update_at is None else pr.provider_update_at.isoformat(),
                      "missing": pr.missing},
            "value": {"ev_raw": va.ev_raw, "edge_raw": va.edge_raw, "ev_cal": va.ev_cal, "edge_cal": va.edge_cal},
            "context": {"status": self.context_status, "adjustment": self.adjustment},
            "market": None if self.market is None else {"status": self.market.status, "side": self.market.side, "steam": self.market.steam,
                                                        "movement_points": self.market.movement_points, "stale": self.market.stale},
            "common": None if self.common is None else self.common.as_json(),
            "close": None if self.close is None else self.close.as_json(),
            "stages": [v.as_json() for v in self.verdicts]}


def worst(effects: Sequence[tuple[str, StateV2]], *, start: StateV2 = "RECOMMENDED") -> StateV2:
    """The most conservative of ``start`` and the effects' states: an effect can only lower."""
    out = start
    for _, s in effects:
        if RANK[s] < RANK[out]:
            out = s
    return out


def _num(x: Any) -> float | None:
    try:
        return None if x is None else float(x)
    except (TypeError, ValueError):
        return None


# -- the per-candidate stages ------------------------------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Assessed:
    """A candidate through every stage but correlation: what ``decide_all`` needs to compare the candidates of one match."""

    candidate: Candidate
    checkpoint: str
    verdicts: tuple[Verdict, ...]
    """Stages 1-7, 9 and 10, without 8."""
    gated: StateV2
    """The state before correlation."""
    competes: bool
    """Whether it competes for its match in correlation: a family that correlates, RECOMMENDED before correlation leaving the Council's
    adjustment out - so that a Council that holds one selection back never lifts another of the same match."""
    label: str | None
    prediction: Prediction
    price: Price
    value: Value
    context_status: str
    adjustment: str | None
    market: MarketRisk | None
    score: float | None


def assess(world: decision.World, candidate: Candidate, *, adjustment: ContextAdjustment | None = None,
           market: MarketRisk | None = None) -> Assessed:
    """Every stage of one candidate but correlation (8). Pure: it reads ``world`` and the candidate, nothing else."""
    at = world.at
    params: FamilyParams = candidate.family.params
    key, models = candidate.key, candidate.models
    mkt = key[1]
    names = sorted(models)
    own = world.cal.primary_model(mkt, names) or names[0]
    r = models[own]
    number = _number(r, own)
    model = number.model
    kickoff: datetime = r["kickoff_at"]
    minutes = (kickoff - at).total_seconds() / 60
    prev = world.previous.get(key)
    important = prev is not None and prev["state"] in decision.APPROVED
    lineups_seen = key[0] in world.lineups
    cp = decision.checkpoint_of(minutes, important=important, lineups=lineups_seen)
    ctx = decision.build_context(world, key, lineups_seen=lineups_seen)
    out: list[Verdict] = []

    # 1 data
    q = world.quality.get(key[0]) or {}
    data_class = q.get("data_class")
    cutoff = number.cutoff
    forecast_age = at - cutoff if cutoff is not None else None
    problems = []
    if (r.get("status_short") or "") in decision.BAD_STATUS or r.get("status_group") not in (None, "scheduled"):
        problems.append(f"estado {r.get('status_short')}")
    if minutes < decision.MIN_MINUTES:
        problems.append(f"menos de {decision.MIN_MINUTES} min al saque")
    if data_class in decision.NOT_FIT:
        problems.append(f"datos de la competición {data_class}")
    if q.get("quarantined"):
        problems.append("partido en cuarentena")
    if params.forecast_max_age is not None and forecast_age is not None and forecast_age > params.forecast_max_age:
        problems.append(f"pronóstico de hace {forecast_age.total_seconds() / 3600:.0f} h")
    out.append(_v("data", not problems, "; ".join(problems) or f"datos {data_class or 'sin evaluar'}",
                  *((_e("data"),) if problems else ()), forecast_age_checked=params.forecast_max_age is not None))

    # 2 model (the pick's own probability, or the common view's: ``number``)
    p_model = number.p_model
    p_push = float(r.get("p_push") or 0)
    has_interval = number.low is not None and number.high is not None
    model_ok = (has_interval or not params.interval_required) and 0 < p_model < 1
    common = number.source == COMMON
    out.append(_v("model", model_ok, f"{model}: p {p_model:.3f}" + (f" (cifra única {number.version})" if common else "") + ("" if has_interval else
                  " sin intervalo" + ("" if params.interval_required else " (la familia no lo guarda: no se juzga su ancho)")),
                  *((_e("model"),) if not model_ok else ()), model=model, model_version_id=number.model_version_id,
                  **({"probability": COMMON} if common else {})))
    width = (number.high - number.low) if number.high is not None and number.low is not None else None

    # 3 market (the price)
    odds = _num(r.get("best_odds"))
    p_mkt = _num(r.get("p_fair"))
    price_at: datetime | None = r.get("price_at")
    n_books = None if r.get("n_bookmakers") is None else int(r["n_bookmakers"])
    price_age = None if price_at is None else at - price_at
    price_edge = None if odds is None or p_mkt is None else odds * p_mkt - 1
    source = str(r.get("price_source") or CONSENSUS)
    missing = None if odds is not None and p_mkt is not None else r.get("price_missing")
    if odds is None or p_mkt is None:
        out.append(_v("market", False, "sin precio de mercado observado" if missing is None else f"sin precio vigente en el libro ({missing})",
                      _e("no_price")))
    elif (n_books or 0) < decision.MIN_BOOKS:
        out.append(_v("market", False, f"solo {n_books} casas", _e("thin_market"), n_bookmakers=n_books))
    elif price_edge is not None and price_edge > decision.MAX_PRICE_EDGE:
        out.append(_v("market", False, f"precio atípico ({price_edge:+.0%} sobre el consenso)", _e("price_outlier")))
    elif price_age is not None and price_age > decision.MAX_PRICE_AGE:
        out.append(_v("market", False, f"precio de hace {price_age.total_seconds() / 3600:.1f} h", _e("price_stale")))
    else:
        out.append(_v("market", True, f"{n_books} casas, cuota {odds:.2f}", odds=odds, p_market=p_mkt, n_bookmakers=n_books))

    # 4 calibration
    gate: GateStatus = candidate.family.gate(world, mkt, model)
    calibrator = gate.calibrator
    p_cal = None if calibrator is None else calibrator.apply(p_model, p_mkt)
    calibrator_id = None if calibrator is None else calibrator.id
    calibrator_role = None if calibrator is None else calibrator.role
    if common:
        # the view's own seal: a champion applied with a fresh price, the market scaled to one - or «Sin calibrar», and no calibrated number
        p_cal = number.p_common if number.calibrated else None
        calibrator_id = number.calibrator_id if number.calibrated else None
        calibrator_role = "CHAMPION" if number.calibrated else None
        if number.calibrated:
            out.append(_v("calibration", True, f"cifra única calibrada: calibrador #{number.calibrator_id} (champion), {number.version}",
                          calibrator_id=number.calibrator_id, basis=number.basis))
        else:
            out.append(_v("calibration", False, f"cifra única «Sin calibrar» ({VIEW_BASIS.get(str(number.basis), number.basis)}): no aprueba",
                          _e("not_calibrated"), calibrator_id=None, basis=number.basis))
    elif gate.champion is not None and p_cal is not None:
        out.append(_v("calibration", True, f"calibrador {gate.champion.method} #{gate.champion.id} (champion)",
                      calibrator_id=gate.champion.id))
    else:
        out.append(_v("calibration", False, "sin calibrador validado: se muestra el mejor ajuste, no aprueba" if calibrator is not None
                      else "sin calibrador para este mercado y modelo", _e("not_calibrated"),
                      calibrator_id=None if calibrator is None else calibrator.id))

    # 5 value (at the current best price)
    ev_raw = None if odds is None else decision.ev_of(p_model, odds, p_push)
    edge_raw = None if p_mkt is None else p_model - p_mkt
    ev_cal = None if odds is None or p_cal is None else decision.ev_of(p_cal, odds, p_push)
    edge_cal = None if p_mkt is None or p_cal is None else p_cal - p_mkt
    if ev_cal is None:
        out.append(_v("value", None if odds is None else False, "sin probabilidad calibrada o sin precio: EV no evaluable",
                      *((_e("ev_unknown"),) if odds is not None else ()), ev_raw=ev_raw))
    elif ev_cal >= decision.EV_MIN and (edge_cal or 0) >= decision.EDGE_MIN:
        out.append(_v("value", True, f"EV calibrado {ev_cal:+.1%}, edge {edge_cal:+.3f}", ev_cal=ev_cal, edge_cal=edge_cal))
    else:
        out.append(_v("value", False, f"EV calibrado {ev_cal:+.1%} / edge {edge_cal:+.3f} bajo el mínimo", _e("ev_cal_below"),
                      ev_cal=ev_cal, edge_cal=edge_cal))

    # 6 context: hard rules, the review decision-v1 reads, the Council's typed adjustment - each only lowers
    hard = [c for c, s in ctx.rules_codes.items() if s == "hard"]
    soft = [c for c, s in ctx.rules_codes.items() if s == "soft"]
    review_decision = None if ctx.review is None else str(ctx.review["decision"])
    effects: list[tuple[str, StateV2]] = []
    whys: list[str] = []
    if any(c in decision.STOP_CODES for c in hard):
        effects.append(_e("context_stop"))
        whys.append("el contexto impide jugarlo: " + ", ".join(c for c in hard if c in decision.STOP_CODES))
    elif "key_absences_pick_side" in hard and lineups_seen:
        effects.append(_e("key_absence_confirmed"))
        whys.append("baja clave confirmada en el lado elegido (alineaciones)")
    elif "key_absences_pick_side" in hard:
        effects.append(_e("key_absence_reported"))
        whys.append("baja clave reportada en el lado elegido (sin confirmar)")
    elif review_decision in ("REJECT", "DOWNGRADE"):
        effects.append(_e(f"ai_{review_decision.lower()}"))
        whys.append(f"revisión de PrediGol Intelligence: {review_decision}")
    else:
        whys.append(f"contexto {ctx.status}" + (f"; revisión {review_decision}" if review_decision else ""))
    adj_verdict = None
    if adjustment is not None:
        adj_verdict = adjustment.verdict
        target = ADJ_EFFECT[adjustment.verdict]
        if target is not None:
            effects.append(_e(council_code(adjustment.verdict)))
        whys.append(f"Council {adjustment.verdict} ({adjustment.severity})")
    out.append(_v("context", not effects, "; ".join(whys), *effects, context_status=ctx.status, adjustment=adj_verdict))

    # 7 risk (the market's signals are risk inputs, never a probability)
    risks: list[str] = []
    if odds is not None and odds > decision.RISK_MAX_ODDS:
        risks.append(f"cuota {odds:.2f} > {decision.RISK_MAX_ODDS:.2f}")
    if p_cal is not None and p_cal < decision.RISK_MIN_P:
        risks.append(f"p calibrada {p_cal:.2f} < {decision.RISK_MIN_P:.2f}")
    if width is not None and width > decision.RISK_MAX_WIDTH:
        risks.append(f"intervalo {width * 100:.0f} pts")
    risk_effects = [_e("risk")] if risks else []
    if market is not None and market.steam_against:
        risks.append("el mercado se movió en contra del modelo, con steam")
        risk_effects.append(_e(MARKET_STEAM_AGAINST))
    out.append(_v("risk", not risks, "; ".join(risks) or "sin riesgo cuantitativo", *risk_effects,
                  market=None if market is None else {"side": market.side, "steam": market.steam, "movement_points": market.movement_points}))

    # 9 price freshness at the end
    if cp in decision.FINAL_CHECKPOINTS and price_age is not None and price_age > decision.FINAL_FRESH:
        out.append(_v("price", False, f"precio de hace {price_age.total_seconds() / 60:.0f} min en {cp}", _e("price_not_fresh")))
    else:
        out.append(_v("price", True if odds is not None else None, "mejor precio vigente" if odds is not None else "sin precio"))

    # the score: what correlation compares (decision-v1's own, from the same inputs)
    sc = _score(world, key, models, model, mkt, p_mkt, odds, p_cal, ev_cal, edge_cal, gate, data_class, q, price_age, n_books, r,
                ctx.status, width, review_decision, hard, soft)

    # 10 final: the edge gate, the labels, the cap of a family not promoted. The gate reads the state WITHOUT the context: decision-v1
    # gates only an APROBADO, so a context that lowers a selection to CAUTELA lifts it past the gate (INVESTIGACION -> CAUTELA), and a
    # context must never raise a state (see the module's note on where this differs from decision-v1).
    every = [e for v in out for e in v.effects]
    council = {council_code(v) for v in ADJ_EFFECT}
    non_context = worst([e for v in out if v.stage != "context" for e in v.effects])
    final_effects: list[tuple[str, StateV2]] = []
    if non_context == "RECOMMENDED" and not gate.edge_validated:
        final_effects.append(_e("edge_not_validated"))
    if not params.promoted and RANK[worst(every + final_effects)] > RANK["ABSTAIN"]:
        final_effects.append(_e(CAP_CODE))
    state = worst(every + final_effects)
    competes = params.correlate and worst([e for e in every + final_effects if e[0] not in council]) == "RECOMMENDED"
    label = None
    if state == "RECOMMENDED":
        tc = world.type_clv.get((mkt, key[2], decision.odds_band(odds or 0)))
        premium = bool(sc is not None and sc >= decision.PREMIUM_SCORE and (_num(gate.wf.get("rule_clv")) or 0) > 0
                       and tc is not None and tc[0] > 0)
        parlay = odds is not None and decision.PARLAY_ODDS[0] <= odds <= decision.PARLAY_ODDS[1] and (p_cal or 0) >= decision.PARLAY_MIN_P
        label = "PICK_PREMIUM" if premium else "CANDIDATO_PARLAY" if parlay else None
    out.append(_v("final", not final_effects, f"{state}" + (f" ({label})" if label else ""), *final_effects,
                  edge_validated=gate.edge_validated, promoted=params.promoted))
    out.sort(key=lambda v: v.n)
    return Assessed(candidate, cp, tuple(out), state, competes, label,
                    Prediction(model, number.model_version_id, p_model, p_push,
                               (number.low, number.high) if number.low is not None and number.high is not None else None, p_cal,
                               calibrator_id, calibrator_role, number.source, number.calibration, number.basis, number.version,
                               None if number.missing is None else str(number.missing)),
                    Price(odds, p_mkt, n_books, price_at, None if price_age is None else round(price_age.total_seconds() / 60, 2), source,
                          None if price_at is None else (r.get("price_confirmed_by") or "capture"), r.get("provider_update_at"),
                          None if missing is None else str(missing)),
                    Value(ev_raw, edge_raw, ev_cal, edge_cal), ctx.status, adj_verdict, market, sc)


def _score(world: decision.World, key: Key, models: Mapping[str, Mapping[str, Any]], model: str, mkt: str, p_mkt: float | None,
           odds: float | None, p_cal: float | None, ev_cal: float | None, edge_cal: float | None, gate: GateStatus, data_class: Any,
           q: Mapping[str, Any], price_age: Any, n_books: int | None, r: Mapping[str, Any], context_status: str, width: float | None,
           review_decision: str | None, hard: list[str], soft: list[str]) -> float | None:
    """The PrediGol Pick Score decision-v1 computes (``fbi.intel.score``), with the consensus of the other models: only when there is
    something to score."""
    if odds is None or p_cal is None:
        return None
    votes: list[bool] = []
    for name, orow in sorted(models.items()):
        if name == model or orow.get("p_model") is None:
            continue
        oc = world.cal.for_model(mkt, name)
        po = float(orow["p_model"])
        pc = oc.apply(po, p_mkt) if oc is not None else po
        if pc is not None and p_mkt is not None:
            votes.append(pc > p_mkt)
    share = (sum(1 for v in votes if v) / len(votes)) if votes else None
    tc = world.type_clv.get((mkt, key[2], decision.odds_band(odds)))
    return scoring.score(scoring.ScoreInputs(
        ev_cal=ev_cal, edge_cal=edge_cal, ece=_num(gate.wf.get("ece_cal")), rule_clv=_num(gate.wf.get("rule_clv")), data_class=data_class,
        quarantined=bool(q.get("quarantined")), price_age_min=None if price_age is None else price_age.total_seconds() / 60,
        n_bookmakers=n_books, overround=_num(r.get("overround")), context_status=context_status, consensus=share, width=width,
        review_decision=review_decision, hard_signals=len(hard), soft_signals=len(soft),
        type_clv=None if tc is None or tc[1] < 50 else tc[0])).total


# -- the end ----------------------------------------------------------------------------------------------------------------------------

def finish(a: Assessed, correlation: Verdict) -> Decision2:
    """The decision: the assessment with its correlation verdict, the lowest effect as the state, its first code as the reason."""
    verdicts = tuple(sorted((*a.verdicts, correlation), key=lambda v: v.n))
    state = worst(list(correlation.effects), start=a.gated)
    label = None if correlation.effects else a.label
    codes = tuple(c for v in verdicts for c, _ in v.effects)
    reason = "approved" if state == "RECOMMENDED" else next(c for v in verdicts for c, s in v.effects if s == state)
    c = a.candidate
    return Decision2(c.family.name, c.key, c.model_hint, a.checkpoint, state, reason, codes, verdicts, label, a.prediction, a.price, a.value,
                     a.context_status, a.adjustment, a.market, a.score)


def alone(a: Assessed) -> Verdict:
    """The correlation verdict of a candidate judged without the others of its match."""
    if not a.candidate.family.params.correlate:
        return _v("correlation", None, "no se aplica: la familia no compite por el partido")
    return _v("correlation", True, "única selección juzgada")


def decide(world: decision.World, candidate: Candidate, *, adjustment: ContextAdjustment | None = None,
           market: MarketRisk | None = None) -> Decision2:
    """ONE candidate through the shared stages (correlation judged alone). Pure and deterministic."""
    a = assess(world, candidate, adjustment=adjustment, market=market)
    return finish(a, alone(a))


Ident = tuple[str, Key, str | None]


def decide_all(world: decision.World, candidates: Sequence[Candidate], *, adjustments: Mapping[Key, ContextAdjustment] | None = None,
               markets: Mapping[Ident, MarketRisk] | None = None, views: Mapping[Key, CommonView] | None = None,
               closes: Mapping[Key, Close] | None = None) -> list[Decision2]:
    """The candidates of one moment: each through the stages, then correlation (8) - among the selections of a match that compete
    (``Assessed.competes``), the best score stays and the others are CAUTION. Ties break on (market, selection, line, family, model), never on the order
    of the rows, and the verdicts say so (``tie``): decision-v1 breaks them on the order the database returns its candidates in, which no
    query fixes, so a tie is where the two may disagree with neither being wrong. Returned in the order of ``candidates``. ``views`` (selection -> its common view) and ``closes`` (selection -> the book's last price before kick-off) are only carried onto the decisions, as measurements."""
    assessed = [assess(world, c, adjustment=(adjustments or {}).get(c.key), market=(markets or {}).get(c.ident)) for c in candidates]
    by_fixture: dict[int, list[int]] = defaultdict(list)
    for i, a in enumerate(assessed):
        if a.competes:
            by_fixture[a.candidate.key[0]].append(i)
    verdicts: dict[int, Verdict] = {}
    for idx in by_fixture.values():
        if len(idx) < 2:
            continue
        idx.sort(key=lambda i: (-(assessed[i].score or 0.0), assessed[i].candidate.key[1:], assessed[i].candidate.family.name,
                                assessed[i].candidate.model_hint or ""))
        best = assessed[idx[0]].candidate
        top = assessed[idx[0]].score or 0.0
        tied = [i for i in idx[1:] if (assessed[i].score or 0.0) == top]
        verdicts[idx[0]] = _v("correlation", True, "la mejor selección aprobable del partido", tie=bool(tied))
        for i in idx[1:]:
            verdicts[i] = _v("correlation", False, f"otra selección del mismo partido tiene mejor score ({best.key[1]} {best.key[2]})"
                             + (" (empate de score: decide la selección)" if i in tied else ""),
                             _e("correlated_same_match"), best=[best.key[1], best.key[2], str(best.key[3])], tie=i in tied)
    decided = [finish(a, verdicts.get(i) or alone(a)) for i, a in enumerate(assessed)]
    if not views and not closes:
        return decided
    # measurements carried along: nothing above read them
    return [replace(d, common=(views or {}).get(d.key), close=(closes or {}).get(d.key)) for d in decided]

