"""``player-engine-v2`` (IA-129, plan piece AD-B08): every player market as expected minutes x rate per 90 (with its sample) x the
probability that he starts, taken from the estimated starters (``lineup-estimate-v1``, AD-D04), and kept. SHADOW.

WHAT CHANGES FROM v1. ``player-engine-v1`` priced a man with ITS OWN start model (``fbi.players.availability``) and kept nothing. v2
takes the start and bench probabilities and the minutes of ``lineup-estimate-v1`` (``fbi.players.lineup_estimate.Estimate``: recent
minutes, confirmed absences, facts «titular» with their rung, the official sheet once it was read by the moment) and keeps every
forecast with its moment (``known_at``), its versions, its minutes, its rate and the sample behind it, and its start probability
(``intel.player_forecasts``, revision 0163). The rates (``fbi.players.rates``), the count engine (NB2, ``fbi.families.counts``) and the
mixture over starting, coming on and not playing (``fbi.players.props``) are v1's, untouched.

THE RULE, never 90 sure minutes:

    P(count > L) = p_start x P_NB2(count > L | mean = r x m_start / 90) + p_sub x P_NB2(count > L | mean = r x m_sub / 90)

with ``r`` the rate per 90 (shrunk towards his position x his team, times the opponent's factor), ``m_start`` his recency-weighted
minutes when he starts (never assumed 90) and ``m_sub`` from the bench; the mass left (1 - p_start - p_sub) does not play and counts 0.
Doc 1's example: 1.0 shot on target per 90 is 63 % of at least one in 90 minutes; at 85 % of starting it is 53 %.
``p_over_if_plays`` is the same mixture without the no-play mass, renormalised: the price of a prop the house voids when he does not
play (``fbi.playermarkets.settle``). With p_start = 0 and p_sub = 0 every probability is 0 and ``p_over_if_plays`` is None; with the
official sheet read by the moment p_start is 0 or 1 (the estimate's own rule).

THE SAMPLE travels with each figure: ``nineties`` (the weighted 90-minute units of his own behind the rate), ``start_sample`` (the
team matches behind the start share; 0 when the sheet decides) and ``history_matches``. The seal is the estimate's
(``sin_calibrar`` until the owner signs a competition): v2 calibrates nothing.

THE EVALUATION (``V2Engine``, ``evaluate``): walk forward as v1 does, but forecast every candidate 90 minutes before kick-off
(before the line-up) with the estimate's start probability, and score the UNCONDITIONAL probability against the count (0 when he did
not play; a NULL count when he played is no outcome) and against the naive baseline of v1 made unconditional: the share of candidates
who started (in the training samples) x the frequency of the event among the starters of his position (Laplace). Per family and
line: n, events, log-loss and Brier of both, the paired difference with its standard error, and a verdict - ``MEJORA`` (the upper end
of the 95 % interval of the difference is below 0), ``NO_MEJORA`` (otherwise) or ``INSUFICIENTE`` (fewer than v1's
``MIN_PLAYER_MATCHES`` outcomes or ``MIN_EVENTS`` events on the main line). A verdict activates nothing: every family stays SHADOW.

Pure: no database and no clock (``fbi.shadowjobs.player_forecast`` reads and writes). No model of language computes a figure here.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final

from fbi.people import availability as people
from fbi.players import availability as av
from fbi.players import backtest as bt
from fbi.players import families as fam
from fbi.players import lineup_estimate as le
from fbi.players import props
from fbi.players import rates as rt
from fbi.players.history import Match, Observation

VERSION: Final = "player-engine-v2"
ESTIMATE_VERSION: Final = le.VERSION
"""Where the start probability comes from (``lineup-estimate-v1``, AD-D04)."""

MEJORA: Final = "MEJORA"
NO_MEJORA: Final = "NO_MEJORA"
INSUFICIENTE: Final = "INSUFICIENTE"
VERDICTS: Final = (MEJORA, NO_MEJORA, INSUFICIENTE)
Z95: Final = 1.959964
"""The two-sided 95 % normal quantile of the paired difference's interval."""


@dataclass(frozen=True, slots=True)
class PlayerForecast:
    """One player, one family, one line, as of ``known_at``: what ``intel.player_forecasts`` keeps."""

    fixture_id: int
    team_id: int
    opponent_id: int
    provider_player_id: int
    position: str
    family: str
    stat: str
    line: float
    known_at: datetime
    p_over: float
    p_over_if_plays: float | None
    mean: float
    p_start: float
    p_sub: float
    minutes_start: float
    minutes_sub: float
    per90: float
    player_per90: float
    prior_per90: float
    opponent_factor: float
    nineties: float
    phi: float
    start_basis: str
    start_sample: int
    lineup_confirmed: bool
    seal: str
    tail: float

    @property
    def p_play(self) -> float:
        return self.p_start + self.p_sub

    @property
    def expected_minutes(self) -> float:
        return self.p_start * self.minutes_start + self.p_sub * self.minutes_sub

    def as_row(self) -> dict[str, Any]:
        """The figures as stored (rounded as the columns hold them)."""
        return {"fixture_id": self.fixture_id, "team_id": self.team_id, "opponent_id": self.opponent_id,
                "provider_player_id": self.provider_player_id, "position": self.position, "family": self.family, "stat": self.stat,
                "line": self.line, "known_at": self.known_at.isoformat(), "p_over": round(self.p_over, 4),
                "p_over_if_plays": None if self.p_over_if_plays is None else round(self.p_over_if_plays, 4),
                "mean": round(self.mean, 4), "p_start": round(self.p_start, 4), "p_sub": round(self.p_sub, 4),
                "p_play": round(self.p_play, 4), "minutes_start": round(self.minutes_start, 1),
                "minutes_sub": round(self.minutes_sub, 1), "expected_minutes": round(self.expected_minutes, 1),
                "per90": round(self.per90, 4), "player_per90": round(self.player_per90, 4), "prior_per90": round(self.prior_per90, 4),
                "opponent_factor": round(self.opponent_factor, 3), "nineties": round(self.nineties, 2), "phi": round(self.phi, 4),
                "start_basis": self.start_basis, "start_sample": self.start_sample, "lineup_confirmed": self.lineup_confirmed,
                "seal": self.seal, "tail": round(self.tail, 6), "version": VERSION, "estimate_version": ESTIMATE_VERSION}

    def input_hash(self) -> str:
        return hashlib.sha256(json.dumps(self.as_row(), sort_keys=True).encode()).hexdigest()


def p_over(per90: float, phi: float, *, p_start: float, minutes_start: float, p_sub: float = 0.0, minutes_sub: float = 0.0,
           line: float = 0.5) -> float:
    """The rule in one number: P(count > line) over starting, coming on and not playing. Pure."""
    return props.p_over(props.mixture_pmf(per90, phi, [(p_start, minutes_start), (p_sub, minutes_sub)]), line)


def forecast_player(e: le.Estimate, rate: rt.Rate, family: fam.PropFamily, *, opponent_id: int, known_at: datetime, phi: float,
                    lineup_confirmed: bool) -> list[PlayerForecast]:
    """Every line of one family for one estimated man. Pure."""
    if not fam.applies(family, e.position):
        return []
    scenarios = [(e.p_start, e.minutes_start), (e.p_sub, e.minutes_sub)]
    pf = props.forecast(family.key, rate.per90, phi, scenarios, family.lines)
    out: list[PlayerForecast] = []
    for line in family.lines:
        cond = None if pf.over_if_plays is None else pf.over_if_plays[line]
        out.append(PlayerForecast(e.fixture_id, e.team_id, opponent_id, e.provider_player_id, e.position, family.key, family.stat, line,
                                  known_at, pf.over[line], cond, pf.mean, e.p_start, e.p_sub, e.minutes_start, e.minutes_sub,
                                  rate.per90, rate.player_per90, rate.prior_per90, rate.opponent_factor, rate.nineties, phi, e.basis,
                                  e.sample, lineup_confirmed, e.seal, pf.tail))
    return out


def forecast_fixture(doc: Mapping[str, Any], *, at: datetime, phi: Mapping[str, float],
                     families: Sequence[fam.PropFamily] = fam.FAMILIES) -> list[PlayerForecast]:
    """Every estimated man of both sides of one match (``doc``: ``fbi.shadowjobs.lineup_estimate.estimate_fixture``'s answer, with the
    engine's history as of ``at``) and every family that applies to his position. Pure: the same doc gives the same rows."""
    h = doc["history"]
    fx = doc["fixture"]
    out: list[PlayerForecast] = []
    for side, opponent in (("home", fx.away_team_id), ("away", fx.home_team_id)):
        block = doc["sides"][side]
        team = int(block["team_id"])
        confirmed = bool(block["confirmed"])
        for e in block["estimates"]:
            mine = [f for f in families if fam.applies(f, e.position)]
            if not mine:
                continue
            rates = rt.player_rates(h, e.provider_player_id, at=at, team_id=team, opponent_id=opponent, position=e.position,
                                    stats=tuple(dict.fromkeys(f.stat for f in mine)))
            for family in mine:
                out.extend(forecast_player(e, rates[family.stat], family, opponent_id=opponent, known_at=at,
                                           phi=float(phi.get(family.stat, 0.0)), lineup_confirmed=confirmed))
    return out


# -- the evaluation (walk-forward, before the line-up) ----------------------------------------------------------------------------

@dataclass(slots=True)
class V2Recorder:
    """The unconditional forecasts of the candidates before the line-up, by (family, line), and what fed them."""

    fixtures: int = 0
    sides: int = 0
    candidates: int = 0
    unseen_players: int = 0
    """Men with a count who were no candidate (the history never saw them on this team): not forecast, counted."""
    lines: dict[tuple[str, float], bt.Scores] = field(default_factory=lambda: defaultdict(bt.Scores))
    if_played: dict[tuple[str, float], bt.Scores] = field(default_factory=lambda: defaultdict(bt.Scores))
    """The same men who played, with ``p_over_if_plays`` against the frequency among starters of his position."""


class V2Engine(bt.Engine):
    """v1's walk (history, start model and dispersions refitted on what was known) that forecasts with the estimated starters."""

    def __init__(self, matches: Iterable[Match], absences: Mapping[tuple[int, int], Sequence[Observation]] | None = None) -> None:
        super().__init__(matches, absences)
        self.v2: V2Recorder | None = None

    def _forecast_match(self, m: Match, t: datetime, rec: bt.Recorder | None) -> None:
        super()._forecast_match(m, t, rec)
        if rec is None or self.v2 is None:
            return
        self.v2.fixtures += 1
        for side in m.sides():
            team, opponent = m.team(side), m.team("away" if side == "home" else "home")
            actual = {p.player_id: p for p in m.lines if p.side == side}
            cands = av.candidates(self.h, team)
            reports = le.provider_states(self.absences, m.fixture_id, set(cands), t)
            states = people.resolve(reports)
            est = le.estimate_side(self.h, self.model, fixture_id=m.fixture_id, team_id=team, competition_id=m.competition_id,
                                   states=states, facts={})
            self.v2.sides += 1
            self.v2.unseen_players += sum(1 for pid, p in actual.items() if p.played and pid not in set(cands))
            for e in est:
                self.v2.candidates += 1
                line_of = actual.get(e.provider_player_id)
                mine = [f for f in fam.FAMILIES if fam.applies(f, e.position)]
                rates = rt.player_rates(self.h, e.provider_player_id, at=t, team_id=team, opponent_id=opponent, position=e.position,
                                        stats=tuple(dict.fromkeys(f.stat for f in mine)))
                for family in mine:
                    played = line_of is not None and line_of.played
                    count = line_of.count(family.stat) if played and line_of is not None else 0
                    if count is None:
                        continue
                    phi = self.phi[family.stat]
                    rate = rates[family.stat]
                    scen = [(e.p_start, e.minutes_start), (e.p_sub, e.minutes_sub)]
                    pmf = props.mixture_pmf(rate.per90, phi, scen)
                    cond = props.conditional_on_playing(rate.per90, phi, scen)
                    for ln in family.lines:
                        ev = self.h.pos_events.get((family.stat, e.position, ln), [0.0, 0.0])
                        pos_freq = (ev[0] + 1.0) / (ev[1] + 2.0)
                        y = 1 if count > ln else 0
                        self.v2.lines[(family.key, ln)].add(props.p_over(pmf, ln), self.start_base * pos_freq, y)
                        if played and cond is not None:
                            self.v2.if_played[(family.key, ln)].add(props.p_over(cond, ln), pos_freq, y)


def verdict_of(s: Mapping[str, Any], *, events_main: int) -> tuple[str, list[str]]:
    """``MEJORA``, ``NO_MEJORA`` or ``INSUFICIENTE`` from a ``Scores.summary()`` (``events_main``: events of the family's main line)."""
    n = int(s.get("n", 0))
    reasons: list[str] = []
    if n < bt.MIN_PLAYER_MATCHES:
        reasons.append(f"{n} pronósticos con resultado < {bt.MIN_PLAYER_MATCHES}")
    if events_main < bt.MIN_EVENTS:
        reasons.append(f"{events_main} eventos en la línea principal < {bt.MIN_EVENTS}")
    if reasons:
        return INSUFICIENTE, reasons
    upper = float(s["log_loss_diff"]) + Z95 * float(s["log_loss_diff_se"])
    if upper < 0:
        return MEJORA, [f"diferencia de log loss {s['log_loss_diff']} (IC95 superior {upper:.5f} < 0)"]
    return NO_MEJORA, [f"diferencia de log loss {s['log_loss_diff']} (IC95 superior {upper:.5f} >= 0)"]


def report(v2: V2Recorder, engine: bt.Engine, *, start: datetime, end: datetime) -> dict[str, Any]:
    families: list[dict[str, Any]] = []
    for family in fam.FAMILIES:
        main = v2.lines.get((family.key, family.lines[0]))
        events_main = main.events if main is not None else 0
        lines: dict[str, Any] = {}
        for ln in family.lines:
            if (family.key, ln) not in v2.lines:
                continue
            s = v2.lines[(family.key, ln)].summary()
            verdict, why = verdict_of(s, events_main=events_main)
            cond = v2.if_played[(family.key, ln)].summary() if (family.key, ln) in v2.if_played else {"n": 0}
            lines[str(ln)] = {"verdict": verdict, "reasons": why, "unconditional": s, "if_played": cond}
        main_verdict = lines.get(str(family.lines[0]), {}).get("verdict", INSUFICIENTE)
        families.append({"family": family.key, "subject": family.subject, "status": family.status, "verdict": main_verdict,
                         "lines": lines})
    return {"version": VERSION, "estimate_version": ESTIMATE_VERSION, "shadow": True, "from": start.isoformat(), "to": end.isoformat(),
            "lead_minutes": bt.LEAD.total_seconds() / 60, "matches_loaded": len(engine.matches), "fixtures_evaluated": v2.fixtures,
            "sides_evaluated": v2.sides, "candidates": v2.candidates, "unseen_players_who_played": v2.unseen_players,
            "start_model": {"fitted": engine.model.coef is not None, "samples": engine.model.samples},
            "dispersion": {k: round(v, 4) for k, v in engine.phi.items()},
            "baseline": "proporción de candidatos que fueron titulares (muestras de entrenamiento) x frecuencia del evento entre los "
                        "titulares de su puesto (Laplace); condicionada: solo la frecuencia del puesto",
            "verdicts": {f["family"]: f["verdict"] for f in families}, "families": families}


def evaluate(matches: Sequence[Match], absences: Mapping[tuple[int, int], Sequence[Observation]], *, start: datetime,
             end: datetime) -> dict[str, Any]:
    """Walk the matches (read from ``start - WARMUP``) and report v2 on those that kicked off in ``[start, end)``. Deterministic."""
    engine = V2Engine(matches, absences)
    engine.v2 = V2Recorder()
    engine.walk(end, record_from=start, train_from=start - bt.TRAIN_LEAD)
    return report(engine.v2, engine, start=start, end=end)


def rule_example() -> tuple[float, float]:
    """Doc 1's example, computed: (P(at least one in 90'), the same at 85 % of starting) for 1.0 per 90 (Poisson). Pure."""
    full = p_over(1.0, 0.0, p_start=1.0, minutes_start=90.0)
    return full, p_over(1.0, 0.0, p_start=0.85, minutes_start=90.0)
