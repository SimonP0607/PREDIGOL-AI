"""Who will start: the estimated starters of a match (IA-094, plan piece AD-D04, ``lineup-estimate-v1``), in SHADOW.

WHY. There is no «probable line-up» stored anywhere (Doc 1, production, 16 Nov 2026): what the plan calls the probable XI is a guess
nobody keeps. Before the official line-up (20 minutes before kick-off at the median, AD-D05) every model that depends on a player - his
shots, his goals, a team's goals without its striker (AD-B08, AD-D03) - needs the probability that he starts, from data and with sources.

THE ESTIMATE, per player of each side, as of a moment, with three inputs and nothing else:

1. **Recent minutes** (``player-engine-v1``, ``fbi.players.availability``): the recency-weighted share of the team's last covered
   matches he started, whether he started the last one and whether he is doubtful, calibrated walk-forward by the start model; his
   minutes if he starts and if he comes on. ``sample`` is the number of team matches behind the share.
2. **Confirmed absences** (``fbi.people.availability``, IA-091): the state that decides for him - ``baja`` or ``sancionado`` with an
   official, provider or two-origin basis is a confirmed absence and he does not start (``baja_confirmada``); ``duda``, or a ``baja``
   that only one outlet reports, is a doubt: a feature of the start model, never a rule. A rumour changes nothing.
3. **Facts «titular» with their source** (``ai.evidence``: a line-up item that says he starts): the highest rung among his facts moves
   the odds of a start by a fixed factor (``LIKELIHOOD``: official 9, two origins 4, one outlet 2, a rumour 1 - nothing). The factors are
   SETTINGS written down before any measurement, not fitted numbers: the measurement below says whether they help.

Once the official line-up is read by the moment, it replaces all of this: a starter is 1, the bench comes on at his rate, a man off the
sheet is 0 (``player-engine-v1``'s own rules).

THE SEAL. Each figure carries ``calibrada`` or ``sin_calibrar``. It is ``calibrada`` only for a competition in ``CALIBRATED``, which is
empty: a competition enters it when the owner signs a measurement that beats the baseline there with the preregistered sample
(``MIN_SIDES``). Until then every figure says ``sin_calibrar``.

THE MEASUREMENT (``Measure``, read-only): walk forward over played matches, estimate every side 90 minutes before kick-off (before the
official line-up) and compare with the official starters (``core.fixture_lineup_players``): Brier score and a reliability table, against
the baseline «the same XI as the team's previous match» (1 for who started it, 0 for the rest); the precision of the eleven most likely
(the same as their recall: both sides have eleven) and of the baseline's eleven; precision and recall at p >= 0.5. A starter the history
never saw is counted with p = 0 by both. By competition, with the number of sides.

Pure: rows in, estimates out - no database and no clock (``fbi.players.lineup_store`` reads and writes). No model of language computes,
corrects or chooses a figure. Health details never enter: an absence is one of four words with its basis (IA-091).
"""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final

from fbi.people import availability as people
from fbi.players import VERSION as MODEL_VERSION
from fbi.players import availability as av
from fbi.players import backtest as bt
from fbi.players.history import DOUBTFUL, Match, Observation, SheetLine, absences_at

VERSION: Final = "lineup-estimate-v1"
MODEL: Final = MODEL_VERSION
"""The start model underneath (``player-engine-v1``)."""

RUNGS: Final = ("oficial", "dos_origenes", "un_medio", "rumor")
LIKELIHOOD: Final[Mapping[str, float]] = {"oficial": 9.0, "dos_origenes": 4.0, "un_medio": 2.0, "rumor": 1.0}
"""How much a fact «titular» of each rung moves the odds of a start: SETTINGS fixed before measuring (a rumour moves nothing)."""
CONFIRMED_OUT: Final = frozenset({"oficial", "proveedor", "dos_origenes"})
"""The bases on which a ``baja`` or ``sancionado`` is a confirmed absence (one outlet alone is a doubt)."""
OUT_STATES: Final = frozenset({"baja", "sancionado"})

CALIBRADA: Final = "calibrada"
SIN_CALIBRAR: Final = "sin_calibrar"
CALIBRATED: Final[frozenset[int]] = frozenset()
"""The competitions whose figures are sealed ``calibrada``: none until the owner signs a measurement that beats the baseline there."""
MIN_SIDES: Final = 60
"""The preregistered sample of a competition's verdict (fixed on 17 Nov 2026, before the first measurement): sides with an official
line-up in the window - three rounds of a league of twenty, some 1.500 player-forecasts."""

BASE_CONFIRMED_OUT: Final = "baja_confirmada"
BASE_MINUTES: Final = "minutos_recientes"
BASE_FACT: Final = "con_hecho_titular"
BASES: Final = (av.CONFIRMED_STARTER, av.CONFIRMED_BENCH, av.NOT_IN_LINEUP, BASE_CONFIRMED_OUT, BASE_MINUTES, BASE_FACT)

LEAD: Final = bt.LEAD
"""The measurement estimates each side 90 minutes before kick-off: before the official line-up (20 min at the median, AD-D05)."""
HISTORY: Final = timedelta(days=180)
"""History read before a moment: the last ten covered matches of a team, the minutes and the start model's training samples."""
TRAIN: Final = timedelta(days=120)
"""The start model is fitted on the forecasts of the matches of the last ``TRAIN`` before the moment (walk-forward)."""
BINS: Final = 10
TOP: Final = 11


@dataclass(frozen=True, slots=True)
class StarterFact:
    """A fact that says a player starts this match, with its rung and when it was learned (``ai.evidence``)."""

    provider_player_id: int
    rung: str
    evidence_id: int
    known_at: datetime
    typed: bool = False
    """A claim of research v2 (``subject_type``), read only when the system reads them."""


def rung_of(status: str | None, tier: str | None) -> str:
    """The rung of a fact of the press: IA-091's basis (official, two origins, one outlet), else a rumour. Pure."""
    return people.press_basis(status, tier) or "rumor"


def facts_from_rows(rows: Iterable[Mapping[str, Any]], *, at: datetime) -> dict[int, list[StarterFact]]:
    """The facts «titular» of a match known by ``at`` (retrieved and published by then), by provider player id. Rows without a player,
    or that do not say he starts, are not facts. Pure."""
    out: dict[int, list[StarterFact]] = defaultdict(list)
    for r in rows:
        pid, known = r.get("provider_player_id"), r.get("retrieved_at")
        published = r.get("published_at")
        if not isinstance(pid, int) or pid <= 0 or not isinstance(known, datetime) or known > at:
            continue
        if isinstance(published, datetime) and published > at:
            continue
        starts = r.get("assertion") == "starts" or r.get("claim_type") == "STARTER"
        if not starts or r.get("origin") == "provider" or r.get("status") in ("OUTDATED", "CONTRADICTORY"):
            continue
        out[pid].append(StarterFact(pid, rung_of(r.get("status"), r.get("source_tier")), int(r["id"]), known,
                                    r.get("subject_type") is not None))
    return dict(out)


def best_rung(facts: Sequence[StarterFact]) -> str | None:
    return min((f.rung for f in facts), key=RUNGS.index) if facts else None


def with_fact(p: float, rung: str | None) -> float:
    """The probability of a start once a fact of ``rung`` says he starts: its odds times the rung's factor. Pure."""
    factor = LIKELIHOOD.get(rung or "rumor", 1.0)
    if factor == 1.0 or p >= 1.0:
        return p
    if p <= 0.0:
        return 0.0
    odds = p / (1.0 - p) * factor
    return odds / (1.0 + odds)


def is_confirmed_out(state: people.State | None) -> bool:
    return state is not None and state.status in OUT_STATES and state.basis in CONFIRMED_OUT


def is_doubtful(state: people.State | None) -> bool:
    return state is not None and (state.status == "duda" or (state.status in OUT_STATES and state.basis not in CONFIRMED_OUT))


def seal_of(competition_id: int | None) -> str:
    return CALIBRADA if competition_id in CALIBRATED else SIN_CALIBRAR


@dataclass(frozen=True, slots=True)
class Estimate:
    fixture_id: int
    team_id: int
    provider_player_id: int
    position: str
    p_start: float
    p_sub: float
    minutes_start: float
    minutes_sub: float
    basis: str
    sample: int
    """Team matches behind the share (0 when the official line-up decides)."""
    share: float | None
    started_last: bool | None
    absence_status: str | None
    absence_basis: str | None
    fact_rung: str | None
    fact_ids: tuple[int, ...]
    seal: str

    @property
    def p_play(self) -> float:
        return self.p_start + self.p_sub

    @property
    def expected_minutes(self) -> float:
        return self.p_start * self.minutes_start + self.p_sub * self.minutes_sub

    def as_json(self) -> dict[str, Any]:
        return {"provider_player_id": self.provider_player_id, "team_id": self.team_id, "position": self.position,
                "p_start": round(self.p_start, 4), "p_play": round(self.p_play, 4), "expected_minutes": round(self.expected_minutes, 1),
                "basis": self.basis, "sample": self.sample, "share": None if self.share is None else round(self.share, 4),
                "started_last": self.started_last, "absence": None if self.absence_status is None else
                {"status": self.absence_status, "basis": self.absence_basis}, "fact": None if self.fact_rung is None else
                {"rung": self.fact_rung, "ids": list(self.fact_ids)}, "seal": self.seal, "version": VERSION, "model": MODEL}


def estimate(h: Any, model: av.StartModel, *, fixture_id: int, team_id: int, player_id: int, position: str, competition_id: int | None,
             state: people.State | None = None, facts: Sequence[StarterFact] = (), sheet: Mapping[int, SheetLine] | None = None) -> Estimate:
    """One player's estimate as of the moment the history ``h`` stands at (``fbi.players.history.History``). Pure."""
    m = av.minutes_profile(h, team_id, player_id, position)
    absence = None if state is None else state.status
    absence_basis = None if state is None else state.basis
    rung = best_rung(facts)
    ids = tuple(sorted(f.evidence_id for f in facts))
    seal = seal_of(competition_id)
    if sheet is not None:
        a = av.availability(h, model, team_id, player_id, position, sheet=sheet)
        return Estimate(fixture_id, team_id, player_id, position, a.p_start, a.p_sub, m.if_start, m.if_sub, a.basis, 0, None, None,
                        absence, absence_basis, rung, ids, seal)
    f = av.start_features(h, team_id, player_id, doubtful=is_doubtful(state))
    if is_confirmed_out(state):
        return Estimate(fixture_id, team_id, player_id, position, 0.0, 0.0, m.if_start, m.if_sub, BASE_CONFIRMED_OUT, f.matches, f.share,
                        f.started_last, absence, absence_basis, rung, ids, seal)
    a = av.availability(h, model, team_id, player_id, position, absence=DOUBTFUL if f.doubtful else None)
    p = with_fact(a.p_start, rung)
    basis = BASE_FACT if p != a.p_start else BASE_MINUTES
    return Estimate(fixture_id, team_id, player_id, position, p, (1.0 - p) * m.off_rate, m.if_start, m.if_sub, basis, f.matches, f.share,
                    f.started_last, absence, absence_basis, rung, ids, seal)


def estimate_side(h: Any, model: av.StartModel, *, fixture_id: int, team_id: int, competition_id: int | None,
                  states: Mapping[int, people.State], facts: Mapping[int, Sequence[StarterFact]],
                  sheet: Sequence[SheetLine] | None = None) -> list[Estimate]:
    """Every candidate of one side (the men of its recent sheets, or its confirmed sheet), most likely first. Pure."""
    lineup = None if sheet is None else {s.player_id: s for s in sheet}
    players = list(lineup) if lineup is not None else av.candidates(h, team_id)
    out = [estimate(h, model, fixture_id=fixture_id, team_id=team_id, player_id=pid,
                    position=h.position(pid, lineup[pid].position if lineup is not None else "?"), competition_id=competition_id,
                    state=states.get(pid), facts=facts.get(pid, ()), sheet=lineup) for pid in players]
    out.sort(key=lambda e: (-e.p_start, e.provider_player_id))
    return out


def provider_states(observations: Mapping[tuple[int, int], Sequence[Observation]], fixture_id: int, players: Iterable[int],
                    at: datetime) -> list[people.Report]:
    """The provider's listings of a match as of ``at`` as IA-091's reports (from ``history.absence_history``; the type decides, the
    reason is never read). Pure."""
    out: list[people.Report] = []
    for pid in players:
        seen: Observation | None = None
        for obs in observations.get((fixture_id, pid), ()):
            if obs[0] <= at:
                seen = obs
            else:
                break
        if seen is None or seen[1] != "LISTED":
            continue
        status = people.provider_status(seen[2], None)
        if status is not None:
            out.append(people.Report(pid, str(pid), status, "proveedor", people.PROVIDER_SOURCE, seen[0], fixture_id))
    return out


# -- the engine and the measurement ------------------------------------------------------------------------------------------------

class EstimateEngine(bt.Engine):
    """``player-engine-v1``'s walk-forward state (history, start model refitted on what was known) without the props: what the estimate
    needs, at a fraction of the cost. While walking it can measure each side against its official line-up (``measure``)."""

    def __init__(self, matches: Iterable[Match], absences: Mapping[tuple[int, int], Sequence[Observation]] | None = None, *,
                 measure: Measure | None = None, official: Mapping[tuple[int, str], frozenset[int]] | None = None,
                 facts: Mapping[int, Sequence[Mapping[str, Any]]] | None = None,
                 press: Mapping[int, Sequence[Mapping[str, Any]]] | None = None) -> None:
        super().__init__(matches, absences)
        self.measure = measure
        self.official = official or {}
        self.fact_rows = facts or {}
        self.press_rows = press or {}

    def _forecast_match(self, m: Match, t: datetime, rec: bt.Recorder | None) -> None:
        for side in m.sides():
            team = m.team(side)
            actual = {p.player_id: p for p in m.lines if p.side == side}
            cands = av.candidates(self.h, team)
            out = absences_at(self.absences, m.fixture_id, set(cands) | set(actual), t)
            for pid in cands:
                line = actual.get(pid)
                y = 1 if line is not None and line.started else 0
                if out.get(pid) == "OUT":
                    continue
                f = av.start_features(self.h, team, pid, doubtful=pid in out)
                self._samples.append(bt.Sample(m.available_at, f, y))
            if rec is not None and self.measure is not None and (m.fixture_id, side) in self.official:
                self._measure_side(m, side, team, cands, t)

    def _measure_side(self, m: Match, side: str, team: int, cands: Sequence[int], t: datetime) -> None:
        assert self.measure is not None
        starters = self.official[(m.fixture_id, side)]
        reports = provider_states(self.absences, m.fixture_id, set(cands) | set(starters), t)
        reports += people.press_reports([r for r in self.press_rows.get(m.fixture_id, ())
                                         if isinstance(r.get("known_at"), datetime) and r["known_at"] <= t])
        states = people.resolve(reports)
        facts = facts_from_rows(self.fact_rows.get(m.fixture_id, ()), at=t)
        est = estimate_side(self.h, self.model, fixture_id=m.fixture_id, team_id=team, competition_id=m.competition_id, states=states,
                            facts=facts)
        plain = estimate_side(self.h, self.model, fixture_id=m.fixture_id, team_id=team, competition_id=m.competition_id, states={},
                              facts={})
        recent = self.h.recent_team(team, 1)
        previous = frozenset(p for p, line in recent[0].men.items() if line.started) if recent else frozenset()
        self.measure.add(m.competition_id, est, plain, starters, previous)


@dataclass(slots=True)
class Scores:
    """A forecast of who starts against the official starters, and its baseline (streamed)."""

    sides: int = 0
    n: int = 0
    events: int = 0
    sum_p: float = 0.0
    brier: float = 0.0
    brier_base: float = 0.0
    brier_plain: float = 0.0
    unseen_starters: int = 0
    top_hits: int = 0
    top_hits_base: int = 0
    top_n: int = 0
    base_n: int = 0
    tp: int = 0
    fp: int = 0
    fn: int = 0
    bins: list[list[float]] = field(default_factory=lambda: [[0.0, 0.0, 0.0] for _ in range(BINS)])

    def add(self, p: float, p_plain: float, base: float, y: int) -> None:
        self.n += 1
        self.events += y
        self.sum_p += p
        self.brier += (p - y) ** 2
        self.brier_plain += (p_plain - y) ** 2
        self.brier_base += (base - y) ** 2
        cell = self.bins[min(int(p * BINS), BINS - 1)]
        cell[0] += 1
        cell[1] += p
        cell[2] += y
        if p >= 0.5:
            self.tp += y
            self.fp += 1 - y
        elif y:
            self.fn += 1

    def summary(self) -> dict[str, Any]:
        if self.n == 0:
            return {"sides": self.sides, "n": 0}
        ece = sum(abs(c[1] - c[2]) for c in self.bins) / self.n
        return {"sides": self.sides, "n": self.n, "starters": self.events, "unseen_starters": self.unseen_starters,
                "mean_p": round(self.sum_p / self.n, 4), "freq": round(self.events / self.n, 4),
                "brier": round(self.brier / self.n, 5), "brier_baseline": round(self.brier_base / self.n, 5),
                "brier_without_absences_and_facts": round(self.brier_plain / self.n, 5),
                "beats_baseline": self.brier < self.brier_base, "ece": round(ece, 4),
                "top11_precision": None if not self.top_n else round(self.top_hits / self.top_n, 4),
                "baseline_xi_precision": None if not self.base_n else round(self.top_hits_base / self.base_n, 4),
                "at_0_5": {"precision": None if not self.tp + self.fp else round(self.tp / (self.tp + self.fp), 4),
                           "recall": None if not self.tp + self.fn else round(self.tp / (self.tp + self.fn), 4)},
                "reliability": [{"bin": f"{b / BINS:.1f}-{(b + 1) / BINS:.1f}", "n": int(c[0]), "mean_p": round(c[1] / c[0], 4),
                                 "freq": round(c[2] / c[0], 4)} for b, c in enumerate(self.bins) if c[0] > 0]}


@dataclass(slots=True)
class Measure:
    """The estimate against the official line-ups, overall and by competition (``EstimateEngine`` feeds it)."""

    total: Scores = field(default_factory=Scores)
    by_competition: dict[int, Scores] = field(default_factory=lambda: defaultdict(Scores))
    bases: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    facts: dict[str, int] = field(default_factory=lambda: defaultdict(int))

    def add(self, competition_id: int, est: Sequence[Estimate], plain: Sequence[Estimate], starters: frozenset[int],
            previous: frozenset[int]) -> None:
        plain_p = {e.provider_player_id: e.p_start for e in plain}
        for acc in (self.total, self.by_competition[competition_id]):
            acc.sides += 1
            for e in est:
                acc.add(e.p_start, plain_p.get(e.provider_player_id, e.p_start), 1.0 if e.provider_player_id in previous else 0.0,
                        1 if e.provider_player_id in starters else 0)
            seen = {e.provider_player_id for e in est}
            for pid in sorted(starters - seen):  # a starter the history never saw: p = 0 for the estimate and the baseline
                acc.unseen_starters += 1
                acc.add(0.0, 0.0, 1.0 if pid in previous else 0.0, 1)
            top = {e.provider_player_id for e in est[:TOP]}
            acc.top_hits += len(top & starters)
            acc.top_n += min(TOP, len(starters))
            if previous:
                acc.top_hits_base += len(previous & starters)
                acc.base_n += min(len(previous), len(starters))
        for e in est:
            self.bases[e.basis] += 1
            if e.fact_rung is not None:
                self.facts[f"{e.fact_rung}:{'titular' if e.provider_player_id in starters else 'no_titular'}"] += 1

    def report(self) -> dict[str, Any]:
        comps = {c: s.summary() for c, s in sorted(self.by_competition.items())}
        enough = {c: s for c, s in comps.items() if s.get("sides", 0) >= MIN_SIDES}
        return {"version": VERSION, "model": MODEL, "lead_minutes": LEAD.total_seconds() / 60,
                "baseline": "el mismo once que el partido anterior del equipo (1 titular, 0 el resto)",
                "total": self.total.summary(), "bases": dict(sorted(self.bases.items())), "facts": dict(sorted(self.facts.items())),
                "competitions": {"n": len(comps), "with_sample": len(enough), "min_sides": MIN_SIDES,
                                 "beating_baseline": sorted(c for c, s in enough.items() if s.get("beats_baseline")),
                                 "not_beating_baseline": sorted(c for c, s in enough.items() if not s.get("beats_baseline")),
                                 "detail": comps}}


def measure(matches: Sequence[Match], absences: Mapping[tuple[int, int], Sequence[Observation]], *, start: datetime, end: datetime,
            official: Mapping[tuple[int, str], frozenset[int]], facts: Mapping[int, Sequence[Mapping[str, Any]]] | None = None,
            press: Mapping[int, Sequence[Mapping[str, Any]]] | None = None) -> dict[str, Any]:
    """The estimate of every side of the matches that kicked off in ``[start, end)`` with an official line-up, 90 minutes before kick-off,
    against the official starters (``matches``: the played matches from ``start - HISTORY``). Pure and deterministic."""
    m = Measure()
    engine = EstimateEngine(matches, absences, measure=m, official=official, facts=facts, press=press)
    engine.walk(end, record_from=start, train_from=start - TRAIN)
    doc = m.report()
    doc |= {"window": [start.isoformat(), end.isoformat()], "matches": sum(1 for x in matches if start <= x.kickoff < end),
            "start_model": {"fitted": engine.model.coef is not None, "samples": engine.model.samples, "refits": engine.refits}}
    return doc


def brier_gain(doc: Mapping[str, Any]) -> float | None:
    """How much the estimate's Brier is below the baseline's (positive: better), from a ``measure`` report. Pure."""
    t = doc.get("total") or {}
    if not t.get("n"):
        return None
    return round(float(t["brier_baseline"]) - float(t["brier"]), 5) if math.isfinite(float(t["brier"])) else None
