"""Which players hold up each selection, and its probability if they do not play (IA-108, plan piece AD-D03, ``lineup-dep-v1``). Pure.

WHY. When the official line-up arrives, 19 minutes before kick-off at the median (IA-105's measurement), there is no time to deliberate:
E3 must say in seconds what the line-up does to each selection. So E1 computes it beforehand - for every selection, the players it
depends on and the probability recomputed without each of them - and E3 reads the table.

THE THREE GROUPS (``group_of``):

    siempre          a player's own prop (shots, shots on target, goals, assists, cards of a player, a keeper's saves): it always
                     waits for the line-up - without it the selection is «Descartada: sin alineación», never confirmed blind
    si_dependencia   the goals markets of a team or the match (1X2, double chance, draw-no-bet, Asian and European handicap, totals,
                     both to score, a team's goals) and the cards: they wait only when a player they depend on is in doubt
    no_espera        the corners: the line-up does not move them in v1

THE NUMBERS. The goals markets come from ONE score matrix (``fbi.forecasting.score_matrix``) rebuilt from the goal model's own stored
rows. Each side's expected goals are shared among its men in proportion to their goal rate per 90 times their expected minutes
(``player-engine-v1``: ``fbi.players.rates`` and the estimated starters of ``lineup-estimate-v1``), the same share the player engine uses
for a goalscorer (``fbi.players.props.goal_scale``). A man who does not play leaves his expected minutes to a replacement at his
position's rate in his team (the position's prior: ``position_rate`` x ``team_factor``); a man who starts for sure plays his minutes as a
starter. So, for side ``s`` with expected goals ``lam`` and ``S = sum_j r_j E_j / 90``,

    without i:   lam' = lam x (S - (r_i - r_repl) E_i / 90) / S
    with i full: lam' = lam x (S + (r_i - r_repl) (m_start_i - E_i) / 90) / S

and the selection's probability is read off the matrix rebuilt with ``lam'``. The table keeps the SHIFT the matrix gives, added to the
figure the decision judged (``p_base``): ``p_without = p_base + (p_matrix_without - p_matrix)``, clipped to [0, 1]. A player is listed when
either shift is at least ``MATERIAL`` (2 points); he is in doubt when his start probability is between ``DOUBT_LOW`` and ``DOUBT_HIGH`` or
his availability says ``duda``. A selection of the second group waits when one of its players is in doubt.

v1 measures the attack only: the absence of a defender or of the goalkeeper does not move the other side's goals (no rate of «goals
prevented» exists in the player engine). The cards have no matrix: their rows say ``sin_matriz`` and never wait.

E3 consults the table (``apply``): with the official starters, ``p = p_base + sum(shift)`` over the listed players. ``recompute`` does it
from scratch - every listed player's minutes changed at once in the same matrix - and the test holds the two within ``TOLERANCE``, fixed
before any measurement.

Every number comes from the models; no model of language computes, corrects or chooses one.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Final

from fbi.forecasting import score_matrix as sm
from fbi.models.goals import InvalidCorrectionError

VERSION: Final = "lineup-dep-v1"
ALWAYS: Final = "siempre"
DECLARED: Final = "si_dependencia"
NEVER: Final = "no_espera"
GROUPS: Final = (ALWAYS, DECLARED, NEVER)

COMPUTED: Final = "calculada"
NO_MATRIX: Final = "sin_matriz"
NO_ESTIMATE: Final = "sin_estimacion"
NOT_APPLICABLE: Final = "no_aplica"
STATUSES: Final = (COMPUTED, NO_MATRIX, NO_ESTIMATE, NOT_APPLICABLE)

MATERIAL: Final = 0.02
"""A player is listed when he moves the selection's probability by at least 2 points (fixed 17 Nov 2026, before any measurement)."""
DOUBT_LOW: Final = 0.10
DOUBT_HIGH: Final = 0.90
"""A start probability strictly between these is a doubt (fixed 17 Nov 2026)."""
TOLERANCE: Final = 0.01
"""Consulting the table and recomputing from scratch agree within one point (preregistered, 17 Nov 2026)."""
LAM_FLOOR: Final = 0.05
MAX_PLAYERS: Final = 6
"""At most this many players listed per selection, the largest shifts first."""

MATRIX_MARKETS: Final = frozenset({"1X2", "DC", "DNB", "OU", "BTTS", "OU_HOME", "OU_AWAY", "AH", "EH"})
CARD_MARKETS: Final = frozenset({"CARDS", "YELLOW"})
NEVER_MARKETS: Final = frozenset({"CORNERS"})
PROP_PREFIXES: Final = ("player_", "keeper_")


def group_of(market_key: str) -> str:
    """The group of a market (see the module's docstring). A market this table does not know waits only if a dependency is declared."""
    if market_key.startswith(PROP_PREFIXES):
        return ALWAYS
    if market_key in NEVER_MARKETS:
        return NEVER
    return DECLARED


@dataclass(frozen=True, slots=True)
class PlayerInput:
    """One man of a side as E1 knew him: the estimate of his start (``lineup-estimate-v1``) and his goal rate (``player-engine-v1``)."""

    provider_player_id: int
    side: str
    position: str
    p_start: float
    p_sub: float
    minutes_start: float
    minutes_sub: float
    goal_per90: float
    replacement_per90: float
    absence_status: str | None = None

    @property
    def expected_minutes(self) -> float:
        return self.p_start * self.minutes_start + self.p_sub * self.minutes_sub

    @property
    def doubtful(self) -> bool:
        return DOUBT_LOW < self.p_start < DOUBT_HIGH or self.absence_status == "duda"


@dataclass(frozen=True, slots=True)
class Matrix:
    """The goal model's parameters for the match (``score_matrix.invert`` of its seven stored rows)."""

    lam_home: float
    lam_away: float
    rho: float | None
    model: str
    residual: float = 0.0

    def as_json(self) -> dict[str, Any]:
        return {"lam_home": round(self.lam_home, 6), "lam_away": round(self.lam_away, 6),
                "rho": None if self.rho is None else round(self.rho, 6), "model": self.model, "residual": self.residual,
                "matrix_version": sm.VERSION}


Key = tuple[str, str, Decimal]
"""(market, selection, line) of the match."""


def _line(x: Decimal | float | str | int) -> Decimal:
    return Decimal(str(x)).quantize(Decimal("0.01"))


def matrix_p(m: Matrix, keys: Iterable[Key], *, lam_home: float | None = None, lam_away: float | None = None) -> dict[Key, float] | None:
    """The probability of winning each selection read off the matrix of ``m`` (with other expected goals when given); None when the
    correction is invalid for those expected goals. A selection the matrix does not price is left out."""
    try:
        built = sm.build(sm.Params(lam_home if lam_home is not None else m.lam_home, lam_away if lam_away is not None else m.lam_away,
                                   m.rho, m.model))
    except (InvalidCorrectionError, ValueError):
        return None
    wanted = list(keys)
    ou = sorted({_line(k[2]) for k in wanted if k[0] == "OU"})
    ah = sorted({_line(k[2]) if k[1] == "Home" else -_line(k[2]) for k in wanted if k[0] == "AH"})
    team = sorted({_line(k[2]) for k in wanted if k[0] in ("OU_HOME", "OU_AWAY")})
    eh = sorted({_line(k[2]) for k in wanted if k[0] == "EH" and _line(k[2]) == _line(k[2]).to_integral_value() and _line(k[2]) != 0})
    try:
        derived = sm.derive(built, ou_lines=ou, ah_lines=ah, team_lines=team, eh_lines=eh)
    except ValueError:
        return None
    prices = {(k[0], k[1], _line(k[2])): v for k, v in derived.items()}
    out: dict[Key, float] = {}
    for k in wanted:
        got = prices.get((k[0], k[1], _line(k[2])))
        if got is not None:
            out[k] = float(got.win)
    return out


def side_share(players: Sequence[PlayerInput], side: str) -> float:
    """``S``: the side's projected goals per its men's rates and expected minutes (the denominator of the goal share)."""
    return sum(p.goal_per90 * p.expected_minutes / 90.0 for p in players if p.side == side)


def _lam(lam: float, share: float, change: float) -> float:
    if share <= 0.0:
        return lam
    return max(LAM_FLOOR, lam * (share + change) / share)


def change_without(p: PlayerInput) -> float:
    """What ``S`` loses when he does not play: his expected minutes go to a replacement at his position's rate."""
    return -(p.goal_per90 - p.replacement_per90) * p.expected_minutes / 90.0


def change_full(p: PlayerInput) -> float:
    """What ``S`` gains when he starts for sure: his minutes as a starter instead of his expected ones."""
    return (p.goal_per90 - p.replacement_per90) * (p.minutes_start - p.expected_minutes) / 90.0


def lambdas(m: Matrix, players: Sequence[PlayerInput], changes: Mapping[int, float]) -> tuple[float, float]:
    """The two sides' expected goals once the share ``S`` of each side changes by the players' ``changes`` (pid -> change of ``S``)."""
    out = []
    for side, lam in (("home", m.lam_home), ("away", m.lam_away)):
        share = side_share(players, side)
        delta = sum(c for pid, c in changes.items() for p in players if p.provider_player_id == pid and p.side == side)
        out.append(_lam(lam, share, delta))
    return out[0], out[1]


def _clip(x: float) -> float:
    return min(1.0, max(0.0, x))


@dataclass(frozen=True, slots=True)
class PlayerDependency:
    provider_player_id: int
    side: str
    position: str
    p_start: float
    expected_minutes: float
    minutes_start: float
    goal_per90: float
    replacement_per90: float
    doubtful: bool
    p_without: float
    """The selection's probability if he does not play (the decision's figure plus the matrix's shift)."""
    p_full: float
    """... if he starts for sure."""
    shift_without: float
    shift_full: float
    absence_status: str | None = None

    def as_json(self) -> dict[str, Any]:
        return {"provider_player_id": self.provider_player_id, "side": self.side, "position": self.position,
                "p_start": round(self.p_start, 4), "expected_minutes": round(self.expected_minutes, 1),
                "minutes_start": round(self.minutes_start, 1), "goal_per90": round(self.goal_per90, 4),
                "replacement_per90": round(self.replacement_per90, 4), "doubtful": self.doubtful, "absence_status": self.absence_status,
                "p_without": round(self.p_without, 6), "p_full": round(self.p_full, 6), "shift_without": round(self.shift_without, 6),
                "shift_full": round(self.shift_full, 6)}

    @staticmethod
    def from_json(d: Mapping[str, Any]) -> PlayerDependency:
        return PlayerDependency(int(d["provider_player_id"]), str(d["side"]), str(d["position"]), float(d["p_start"]),
                                float(d["expected_minutes"]), float(d["minutes_start"]), float(d["goal_per90"]),
                                float(d["replacement_per90"]), bool(d["doubtful"]), float(d["p_without"]), float(d["p_full"]),
                                float(d["shift_without"]), float(d["shift_full"]), d.get("absence_status"))


@dataclass(frozen=True, slots=True)
class Dependency:
    """One selection's row of ``intel.lineup_dependencies``."""

    key: Key
    group: str
    status: str
    waits: bool
    p_base: float | None
    p_matrix: float | None
    matrix: Matrix | None
    players: tuple[PlayerDependency, ...] = field(default_factory=tuple)

    @property
    def dependents(self) -> frozenset[int]:
        return frozenset(p.provider_player_id for p in self.players)

    def players_json(self) -> list[dict[str, Any]]:
        return [p.as_json() for p in self.players]


def selection_dependency(key: Key, p_base: float | None, m: Matrix | None, players: Sequence[PlayerInput]) -> Dependency:
    """The dependency of one selection (``dependencies`` for one). Pure."""
    return dependencies([(key, p_base)], m, players)[0]


def _shifted(m: Matrix, keys: Sequence[Key], players: Sequence[PlayerInput], changes: Mapping[int, float]) -> dict[Key, float] | None:
    lh, la = lambdas(m, players, changes)
    return matrix_p(m, keys, lam_home=lh, lam_away=la)


def dependencies(selections: Sequence[tuple[Key, float | None]], m: Matrix | None, players: Sequence[PlayerInput]) -> list[Dependency]:
    """The dependency of every selection of one match, in the order given: each player's two matrices (without him, with him starting)
    are built once for all the selections. Pure."""
    priced = [k for k, p in selections if group_of(k[0]) == DECLARED and k[0] in MATRIX_MARKETS and p is not None]
    base = matrix_p(m, priced) if m is not None and priced else {}
    moved: list[tuple[PlayerInput, dict[Key, float], dict[Key, float]]] = []
    if m is not None and base:
        for p in players:
            if p.expected_minutes <= 0.0 and p.minutes_start <= 0.0:
                continue
            wo = _shifted(m, priced, players, {p.provider_player_id: change_without(p)})
            full = _shifted(m, priced, players, {p.provider_player_id: change_full(p)})
            if wo is not None and full is not None:
                moved.append((p, wo, full))
    out: list[Dependency] = []
    for key, p_base in selections:
        group = group_of(key[0])
        if group == ALWAYS:
            out.append(Dependency(key, group, NOT_APPLICABLE, True, p_base, None, m))
            continue
        if group == NEVER:
            out.append(Dependency(key, group, NOT_APPLICABLE, False, p_base, None, m))
            continue
        if base is None or key not in base or p_base is None:
            out.append(Dependency(key, group, NO_MATRIX, False, p_base, None, m))
            continue
        if not players:
            out.append(Dependency(key, group, NO_ESTIMATE, False, p_base, base[key], m))
            continue
        found: list[PlayerDependency] = []
        for p, wo, full in moved:
            if key not in wo or key not in full:
                continue
            s_wo, s_full = wo[key] - base[key], full[key] - base[key]
            if abs(s_wo) < MATERIAL and abs(s_full) < MATERIAL:
                continue
            found.append(PlayerDependency(p.provider_player_id, p.side, p.position, p.p_start, p.expected_minutes, p.minutes_start,
                                          p.goal_per90, p.replacement_per90, p.doubtful, _clip(p_base + s_wo), _clip(p_base + s_full),
                                          s_wo, s_full, p.absence_status))
        found.sort(key=lambda d: (-max(abs(d.shift_without), abs(d.shift_full)), d.provider_player_id))
        kept = tuple(found[:MAX_PLAYERS])
        out.append(Dependency(key, group, COMPUTED, any(d.doubtful for d in kept), p_base, base[key], m, kept))
    return out


# -- E3: the table consulted, and the same from scratch --------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Applied:
    p: float | None
    """The selection's probability with the official starters (``p_base`` when nothing listed changes)."""
    missing: tuple[int, ...]
    """Listed players whose side is known and who do not start."""
    starting: tuple[int, ...]
    unseen: tuple[int, ...]
    """Listed players whose side's line-up is not known yet."""


def apply(dep: Dependency, starters: Mapping[str, frozenset[int]]) -> Applied:
    """The table consulted (E3): the shift of every listed player whose side's starters are known, added to ``p_base``."""
    if dep.p_base is None:
        return Applied(None, (), (), tuple(p.provider_player_id for p in dep.players))
    total = 0.0
    missing: list[int] = []
    starting: list[int] = []
    unseen: list[int] = []
    for p in dep.players:
        xi = starters.get(p.side)
        if xi is None:
            unseen.append(p.provider_player_id)
        elif p.provider_player_id in xi:
            starting.append(p.provider_player_id)
            total += p.shift_full
        else:
            missing.append(p.provider_player_id)
            total += p.shift_without
    return Applied(_clip(dep.p_base + total), tuple(missing), tuple(starting), tuple(unseen))


def recompute(dep: Dependency, players: Sequence[PlayerInput], starters: Mapping[str, frozenset[int]]) -> float | None:
    """The same as ``apply`` from scratch: every listed player of a known side changed at once in one matrix. None without a matrix."""
    if dep.matrix is None or dep.p_base is None or dep.p_matrix is None:
        return None
    by_pid = {p.provider_player_id: p for p in players}
    changes: dict[int, float] = {}
    for d in dep.players:
        xi = starters.get(d.side)
        p = by_pid.get(d.provider_player_id)
        if xi is None or p is None:
            continue
        changes[d.provider_player_id] = change_full(p) if d.provider_player_id in xi else change_without(p)
    lh, la = lambdas(dep.matrix, players, changes)
    got = matrix_p(dep.matrix, [dep.key], lam_home=lh, lam_away=la)
    if not got or dep.key not in got:
        return None
    return _clip(dep.p_base + got[dep.key] - dep.p_matrix)


def input_hash(key: Key, p_base: float | None, m: Matrix | None, players: Sequence[PlayerInput]) -> str:
    doc = {"key": [key[0], key[1], str(_line(key[2]))], "p_base": None if p_base is None else round(p_base, 6),
           "matrix": None if m is None else m.as_json(),
           "players": [{"pid": p.provider_player_id, "side": p.side, "pos": p.position, "p_start": round(p.p_start, 4),
                        "p_sub": round(p.p_sub, 4), "m_start": round(p.minutes_start, 2), "m_sub": round(p.minutes_sub, 2),
                        "r": round(p.goal_per90, 6), "rr": round(p.replacement_per90, 6), "absence": p.absence_status}
                       for p in sorted(players, key=lambda x: (x.side, x.provider_player_id))],
           "version": VERSION}
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
