"""The walk-forward engine and its evaluation (``player-engine-v1``): every match is forecast with what was known before it.

THE WALK. Matches are taken in kick-off order. For each, the moment is ``kickoff - LEAD`` (before the line-ups are out); the history
holds exactly the played matches known by then (``fbi.players.history``, ``available_at``), and the start model and the dispersions
were fitted on the forecasts of matches whose outcome was known by the last refit (every ``REFIT_EVERY``). Then:

* AVAILABILITY: every candidate of each covered side gets P(start) and expected minutes; the outcome is whether he started (the
  statistics). A man the provider listed as OUT by the moment is a rule (P = 0), counted apart, with the times he started anyway.
* PROPS: every man who started gets his props as a CONFIRMED starter (P(start) = 1, his minutes if he starts): that is when a prop
  would be priced (no prop is evaluated before the confirmed line-up; Plan Maestro IA, Player Agent). The outcome is his count; a NULL
  count is not an outcome. The naive baseline is the frequency of the event among the starters of his position in the history (Laplace).

THE REPORT per family and line: n (player-matches with the count), events, coverage (share of starters with the count), log-loss and
Brier of the model and of the baseline, the paired difference of log-loss with its standard error, and a reliability table. A family is
MODELABLE when it has at least ``MIN_PLAYER_MATCHES`` outcomes, ``MIN_EVENTS`` events on its main line and ``MIN_COVERAGE``; otherwise
NOT_MODELABLE, with the reason. MODELABLE says there is data to judge the model, not that the model is good: the difference says that.
Read-only and deterministic: the same matches give the same report.
"""

from __future__ import annotations

import heapq
import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final

from fbi.families import counts
from fbi.players import VERSION, props
from fbi.players import availability as av
from fbi.players import families as fam
from fbi.players import rates as rt
from fbi.players.history import History, Match, Observation, SheetLine, absences_at

LEAD: Final = timedelta(minutes=90)
WARMUP: Final = timedelta(days=365)
"""History read before the first match evaluated: the priors, the team factors and the players' records."""
TRAIN_LEAD: Final = timedelta(days=180)
"""Matches forecast before the window only to train the start model and the dispersions (not reported)."""
REFIT_EVERY: Final = timedelta(days=30)
MAX_SAMPLES: Final = 60_000
MIN_PHI_SAMPLES: Final = 500
MIN_PLAYER_MATCHES: Final = 2_000
MIN_EVENTS: Final = 200
MIN_COVERAGE: Final = 0.5
EPS: Final = 0.005
"""Probabilities are clipped to [EPS, 1 - EPS] for the log-loss (a rule's 0 that turns out wrong costs log(1/0.005), not infinity)."""
BINS: Final = 10

LINES_BY_STAT: Final = {f.stat: f.lines for f in fam.FAMILIES}


def log_loss(p: float, y: int) -> float:
    q = min(max(p, EPS), 1 - EPS)
    return -math.log(q if y else 1 - q)


def brier(p: float, y: int) -> float:
    return (p - y) ** 2


@dataclass(frozen=True, slots=True)
class Sample:
    at: datetime
    """When its outcome was known (the match's ``available_at``): it trains nothing before."""
    features: av.StartFeatures | None
    started: int
    stat: str | None = None
    y: int = 0
    mu: float = 0.0


@dataclass(slots=True)
class Scores:
    """Running sums of a binary forecast against its baseline (streamed: a window of every league is millions of forecasts)."""

    n: int = 0
    events: int = 0
    sum_p: float = 0.0
    ll: float = 0.0
    ll_base: float = 0.0
    br: float = 0.0
    br_base: float = 0.0
    d: float = 0.0
    d2: float = 0.0
    bins: list[list[float]] = field(default_factory=lambda: [[0.0, 0.0, 0.0] for _ in range(BINS)])
    """Per reliability bin: [n, sum of p, events]."""

    def add(self, p: float, base: float, y: int) -> None:
        a, b = log_loss(p, y), log_loss(base, y)
        self.n += 1
        self.events += y
        self.sum_p += p
        self.ll += a
        self.ll_base += b
        self.br += brier(p, y)
        self.br_base += brier(base, y)
        self.d += a - b
        self.d2 += (a - b) ** 2
        cell = self.bins[min(int(p * BINS), BINS - 1)]
        cell[0] += 1
        cell[1] += p
        cell[2] += y

    def summary(self) -> dict[str, Any]:
        n = self.n
        if n == 0:
            return {"n": 0}
        mean_d = self.d / n
        var = (self.d2 - n * mean_d * mean_d) / (n - 1) if n > 1 else 0.0
        bins = [{"bin": f"{b / BINS:.1f}-{(b + 1) / BINS:.1f}", "n": int(c[0]), "mean_p": round(c[1] / c[0], 4),
                 "freq": round(c[2] / c[0], 4)} for b, c in enumerate(self.bins) if c[0] > 0]
        return {"n": n, "events": self.events, "freq": round(self.events / n, 4), "mean_p": round(self.sum_p / n, 4),
                "log_loss": round(self.ll / n, 5), "log_loss_baseline": round(self.ll_base / n, 5),
                "brier": round(self.br / n, 5), "brier_baseline": round(self.br_base / n, 5),
                "log_loss_diff": round(mean_d, 5), "log_loss_diff_se": round(math.sqrt(max(var, 0.0) / n), 5),
                "reliability": bins}


@dataclass(slots=True)
class Recorder:
    start: Scores = field(default_factory=Scores)
    start_raw: Scores = field(default_factory=Scores)
    minutes_n: int = 0
    minutes_abs: float = 0.0
    minutes_abs_naive: float = 0.0
    ruled_out: int = 0
    ruled_out_started: int = 0
    fixtures: int = 0
    sides: int = 0
    lines: dict[tuple[str, float], Scores] = field(default_factory=lambda: defaultdict(Scores))
    starters: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    with_count: dict[str, int] = field(default_factory=lambda: defaultdict(int))


class Engine:
    """The walk-forward state: a history, the start model and the dispersions, refitted on what was known."""

    def __init__(self, matches: Iterable[Match], absences: Mapping[tuple[int, int], Sequence[Observation]] | None = None) -> None:
        self.matches = sorted(matches, key=lambda m: (m.kickoff, m.fixture_id))
        self.absences: Mapping[tuple[int, int], Sequence[Observation]] = absences or {}
        self.h = History()
        self.model = av.StartModel()
        self.phi: dict[str, float] = dict.fromkeys(fam.STATS, 0.0)
        self.start_base = 0.5
        self._pending: list[tuple[datetime, int, int]] = []
        self._samples: list[Sample] = []
        self._next = 0
        self._last_refit: datetime | None = None
        self.refits = 0

    # ── time ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

    def advance(self, t: datetime) -> None:
        """Add to the history every walked match known by ``t``."""
        while self._pending and self._pending[0][0] <= t:
            _, _, i = heapq.heappop(self._pending)
            self.h.add(self.matches[i], LINES_BY_STAT)

    def refit(self, t: datetime, *, force: bool = False) -> None:
        if not force and self._last_refit is not None and t - self._last_refit < REFIT_EVERY:
            return
        self._last_refit = t
        known = [s for s in self._samples if s.at <= t]
        kept: list[Sample] = []
        starts = [s for s in known if s.features is not None][-MAX_SAMPLES:]
        if starts:
            self.model = av.StartModel.fit([s.features for s in starts if s.features is not None], [s.started for s in starts])
            self.start_base = (sum(s.started for s in starts) + 1.0) / (len(starts) + 2.0)
        for stat in fam.STATS:
            pairs = [s for s in known if s.stat == stat][-MAX_SAMPLES:]
            if len(pairs) >= MIN_PHI_SAMPLES:
                self.phi[stat] = counts.fit_dispersion([s.y for s in pairs], [s.mu for s in pairs])
            kept.extend(pairs)
        # what a later refit can still use: the newest known samples of each kind, and every one not known yet
        self._samples = sorted([*starts, *kept, *(s for s in self._samples if s.at > t)], key=lambda s: s.at)
        self.refits += 1

    # ── the walk ─────────────────────────────────────────────────────────────────────────────────────────────────────────

    def walk(self, until: datetime, *, record_from: datetime, train_from: datetime, recorder: Recorder | None = None) -> Recorder:
        rec = recorder or Recorder()
        while self._next < len(self.matches) and self.matches[self._next].kickoff < until:
            i = self._next
            m = self.matches[i]
            self._next += 1
            t = m.kickoff - LEAD
            self.advance(t)
            self.refit(t)
            if m.kickoff >= train_from:
                self._forecast_match(m, t, rec if m.kickoff >= record_from else None)
            heapq.heappush(self._pending, (m.available_at, m.fixture_id, i))
        return rec

    def _forecast_match(self, m: Match, t: datetime, rec: Recorder | None) -> None:
        if rec is not None:
            rec.fixtures += 1
        for side in m.sides():
            team, opponent = m.team(side), m.team("away" if side == "home" else "home")
            actual = {p.player_id: p for p in m.lines if p.side == side}
            cands = av.candidates(self.h, team)
            out = absences_at(self.absences, m.fixture_id, set(cands) | set(actual), t)
            if rec is not None:
                rec.sides += 1
            recent = self.h.recent_team(team, av.RECENT_MATCHES)
            for pid in cands:
                line = actual.get(pid)
                y = 1 if line is not None and line.started else 0
                position = self.h.position(pid)
                a = av.availability(self.h, self.model, team, pid, position, absence=out.get(pid))
                if a.basis == av.RULED_OUT:
                    if rec is not None:
                        rec.ruled_out += 1
                        rec.ruled_out_started += y
                    continue
                f = av.start_features(self.h, team, pid, doubtful=a.absence is not None)
                self._samples.append(Sample(m.available_at, f, y))
                if rec is not None:
                    rec.start.add(a.p_start, self.start_base, y)
                    rec.start_raw.add(f.share, self.start_base, y)
                    played = float(line.minutes) if line is not None else 0.0
                    naive = sum(float(tm.men[pid].minutes) if pid in tm.men else 0.0 for tm in recent) / max(1, len(recent))
                    rec.minutes_n += 1
                    rec.minutes_abs += abs(a.expected_minutes - played)
                    rec.minutes_abs_naive += abs(naive - played)
            starters = {pid: SheetLine(pid, None, p.position, True) for pid, p in actual.items() if p.started}
            for pid, line in actual.items():
                if not line.started:
                    continue
                position = self.h.position(pid, line.position)
                a = av.availability(self.h, self.model, team, pid, position, sheet=starters)
                mine = [f for f in fam.FAMILIES if fam.applies(f, position)]
                reported = [f.stat for f in mine if line.count(f.stat) is not None]
                rates = rt.player_rates(self.h, pid, at=t, team_id=team, opponent_id=opponent, position=position, stats=reported)
                for family in mine:
                    if rec is not None:
                        rec.starters[family.key] += 1
                    count = line.count(family.stat)
                    if count is None:
                        continue
                    rate = rates[family.stat]
                    mu = rate.per90 * a.minutes_start / 90.0
                    self._samples.append(Sample(m.available_at, None, 0, family.stat, count, mu))
                    if rec is None:
                        continue
                    rec.with_count[family.key] += 1
                    pmf = props.mixture_pmf(rate.per90, self.phi[family.stat], a.scenarios())
                    for ln in family.lines:
                        ev = self.h.pos_events.get((family.stat, position, ln), [0.0, 0.0])
                        base = (ev[0] + 1.0) / (ev[1] + 2.0)
                        rec.lines[(family.key, ln)].add(props.p_over(pmf, ln), base, 1 if count > ln else 0)

    # ── a match to come ──────────────────────────────────────────────────────────────────────────────────────────────────

    def forecast_side(self, *, at: datetime, team_id: int, opponent_id: int, sheet: Sequence[SheetLine] | None,
                      absences: Mapping[int, str], team_xg: float | None = None) -> dict[str, Any]:
        """Every candidate of one side as of ``at`` (call ``prepare(at)`` first): availability, rates and props."""
        lineup = None if sheet is None else {s.player_id: s for s in sheet}
        players = list(lineup) if lineup is not None else av.candidates(self.h, team_id)
        rows: list[dict[str, Any]] = []
        for pid in players:
            hint = lineup[pid].position if lineup is not None else "?"
            position = self.h.position(pid, hint)
            a = av.availability(self.h, self.model, team_id, pid, position, absence=absences.get(pid), sheet=lineup)
            rates = rt.player_rates(self.h, pid, at=at, team_id=team_id, opponent_id=opponent_id, position=position)
            rows.append({"player_id": pid, "name": lineup[pid].name if lineup is not None else None, "position": position,
                         "availability": a, "rates": dict(rates)})
        scale = None
        if team_xg is not None and rows:
            goal_rates = {r["player_id"]: r["rates"]["goals"].per90 for r in rows if r["position"] != "G"}
            minutes = {r["player_id"]: r["availability"].expected_minutes for r in rows}
            try:
                scale = props.goal_scale(goal_rates, minutes, team_xg)
            except ValueError:
                scale = None
        out: list[dict[str, Any]] = []
        for r in rows:
            a = r["availability"]
            fams: list[dict[str, Any]] = []
            for family in fam.FAMILIES:
                if not fam.applies(family, r["position"]):
                    continue
                per90 = r["rates"][family.stat].per90
                if family.stat == "goals" and scale is not None:
                    per90 *= scale
                pf = props.forecast(family.key, per90, self.phi[family.stat], a.scenarios(), family.lines)
                fams.append(pf.as_json() | {"status": family.status, "per90": round(per90, 4)})
            out.append({"player_id": r["player_id"], "name": r["name"], "position": r["position"], "availability": a.as_json(),
                        "rates": {k: v.as_json() for k, v in r["rates"].items()}, "props": fams})
        out.sort(key=lambda d: (-d["availability"]["p_play"], d["player_id"]))
        return {"team_xg": team_xg, "goal_scale": None if scale is None else round(scale, 4), "players": out}

    def prepare(self, at: datetime) -> None:
        """Bring the history and the fitted parts to ``at`` (after the walk over the matches before it)."""
        self.advance(at)
        self.refit(at, force=True)


def verdicts(rec: Recorder) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for family in fam.FAMILIES:
        n = rec.with_count.get(family.key, 0)
        total = rec.starters.get(family.key, 0)
        coverage = n / total if total else 0.0
        main = rec.lines.get((family.key, family.lines[0]))
        events = main.events if main is not None else 0
        reasons: list[str] = []
        if n < MIN_PLAYER_MATCHES:
            reasons.append(f"{n} player-matches with the count < {MIN_PLAYER_MATCHES}")
        if events < MIN_EVENTS:
            reasons.append(f"{events} events over {family.lines[0]} < {MIN_EVENTS}")
        if coverage < MIN_COVERAGE:
            reasons.append(f"coverage {coverage:.0%} < {MIN_COVERAGE:.0%}")
        lines = {str(ln): rec.lines[(family.key, ln)].summary() for ln in family.lines if (family.key, ln) in rec.lines}
        out.append({"family": family.key, "subject": family.subject, "status": family.status,
                    "verdict": fam.NOT_MODELABLE if reasons else fam.MODELABLE, "reasons": reasons, "starters": total,
                    "player_matches": n, "coverage": round(coverage, 4), "lines": lines})
    return out


def report(rec: Recorder, engine: Engine, *, start: datetime, end: datetime) -> dict[str, Any]:
    mae = rec.minutes_abs / rec.minutes_n if rec.minutes_n else None
    mae_naive = rec.minutes_abs_naive / rec.minutes_n if rec.minutes_n else None
    return {
        "version": VERSION, "shadow": True, "from": start.isoformat(), "to": end.isoformat(),
        "matches_loaded": len(engine.matches), "fixtures_evaluated": rec.fixtures, "sides_evaluated": rec.sides,
        "refits": engine.refits, "start_model": {"fitted": engine.model.coef is not None, "samples": engine.model.samples,
                                                 "coef": None if engine.model.coef is None else [round(c, 4) for c in engine.model.coef]},
        "dispersion": {k: round(v, 4) for k, v in engine.phi.items()},
        "availability": {"start": rec.start.summary(), "start_uncalibrated_share": rec.start_raw.summary(),
                         "baseline": "the share of candidates who started, in the training samples known at the refit",
                         "ruled_out": rec.ruled_out, "ruled_out_but_started": rec.ruled_out_started,
                         "minutes_mae": None if mae is None else round(mae, 2),
                         "minutes_mae_naive": None if mae_naive is None else round(mae_naive, 2),
                         "minutes_naive": "his mean minutes over the team's last covered matches (0 when absent)"},
        "props_basis": "confirmed starters (P(start) = 1); baseline: frequency among starters of his position in the history (Laplace)",
        "families": verdicts(rec),
    }


def evaluate(matches: Sequence[Match], absences: Mapping[tuple[int, int], Sequence[Observation]], *, start: datetime,
             end: datetime) -> dict[str, Any]:
    """Walk the matches (read from ``start - WARMUP``) and report on those that kicked off in ``[start, end)``."""
    engine = Engine(matches, absences)
    rec = engine.walk(end, record_from=start, train_from=start - TRAIN_LEAD)
    return report(rec, engine, start=start, end=end)

