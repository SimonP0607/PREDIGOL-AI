"""Per-90 rates of a player (``player-engine-v1``): goals, assists, shots, shots on target, fouls committed, cards, goalkeeper saves.

THE ESTIMATE is gamma-Poisson shrinkage (the posterior mean of a rate with a gamma prior):

    rate = (sum_i w_i y_i + strength x prior) / (sum_i w_i m_i / 90 + strength)

over his last ``APPEARANCES`` appearances with minutes and the count reported (a NULL count is left out with its minutes), with
recency weights ``w_i = 0.5 ** (days ago / HALF_LIFE_DAYS)``. ``strength`` is in 90-minute units (``PRIOR_90S``): a man with fewer
minutes than that is closer to the prior than to himself. These strengths are SETTINGS of v1, not estimates; the evaluation measures
whether the player term beats the naive baseline (``fbi.players.backtest``).

THE PRIOR is the per-90 rate of his position in the history (everyone of that position, all teams) times his TEAM's factor: what the
team's players of every position produced in its last ``TEAM_MATCHES`` covered matches, over what their minutes at position rates would
give, shrunk to 1 with ``TEAM_PSEUDO_MATCHES`` matches' worth of an average team.

THE OPPONENT factor is the same ratio for what the opponent ALLOWED: the counts of the men who played against it (their shots, their
fouls, the saves of the keepers who faced it), over what their minutes at position rates would give, shrunk to 1 the same way. The
final rate is the player's rate times the opponent's factor. Home and away are not distinguished in v1.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from fbi.players.families import STATS
from fbi.players.history import History, TeamMatch

HALF_LIFE_DAYS: Final = 180.0
APPEARANCES: Final = 40
TEAM_MATCHES: Final = 20
TEAM_PSEUDO_MATCHES: Final = 5.0
PRIOR_90S: Final = {"goals": 6.0, "assists": 6.0, "shots": 3.0, "shots_on": 4.0, "fouls": 4.0, "cards": 10.0, "saves": 3.0}
FLOOR_RATE: Final = 1e-4
"""Per-90 floor of a prior: a count no man of the position has ever recorded is still not impossible."""


def shrunk_rate(counts: Sequence[float], minutes: Sequence[float], weights: Sequence[float], prior: float, strength: float) -> float:
    """The gamma-Poisson posterior mean of a per-90 rate."""
    if not (len(counts) == len(minutes) == len(weights)):
        raise ValueError("one count, one minutes and one weight per appearance")
    if strength <= 0 or prior < 0:
        raise ValueError("the prior must be non-negative and its strength positive")
    num = sum(w * y for w, y in zip(weights, counts, strict=True)) + strength * prior
    den = sum(w * m / 90.0 for w, m in zip(weights, minutes, strict=True)) + strength
    return num / den


def recency_weight(at: datetime, when: datetime, half_life_days: float = HALF_LIFE_DAYS) -> float:
    days = max(0.0, (at - when).total_seconds() / 86400.0)
    return float(0.5 ** (days / half_life_days))


def position_rate(h: History, stat: str, position: str) -> float:
    """Per 90 of the position in the history; the whole history when the position has no minutes (an unknown position)."""
    key = ("pos", stat, position)
    if key not in h.memo:
        h.memo[key] = _position_rate(h, stat, position)
    return h.memo[key]


def _position_rate(h: History, stat: str, position: str) -> float:
    y, m = h.pos_y.get(stat, {}), h.pos_min90.get(stat, {})
    if m.get(position, 0.0) > 0.0:
        return max(FLOOR_RATE, y.get(position, 0.0) / m[position])
    total_m = sum(m.values())
    return max(FLOOR_RATE, sum(y.values()) / total_m) if total_m > 0 else FLOOR_RATE


def _factor(h: History, matches: Sequence[TeamMatch], stat: str, *, against: bool) -> float:
    y = expected = 0.0
    for tm in matches:
        counts, minutes = (tm.against_y, tm.against_min90) if against else (tm.for_y, tm.for_min90)
        y += counts.get(stat, 0)
        expected += sum(m90 * position_rate(h, stat, pos) for pos, m90 in minutes.get(stat, {}).items())
    if not matches or expected <= 0.0:
        return 1.0
    per_match = expected / len(matches)
    return (y + TEAM_PSEUDO_MATCHES * per_match) / (expected + TEAM_PSEUDO_MATCHES * per_match)


def _memo_factor(h: History, team_id: int, stat: str, *, against: bool) -> float:
    key = ("against" if against else "for", team_id, stat)
    if key not in h.memo:
        h.memo[key] = _factor(h, h.recent_team(team_id, TEAM_MATCHES), stat, against=against)
    return h.memo[key]


def team_factor(h: History, team_id: int, stat: str) -> float:
    """What the team's men produced over what their minutes at position rates give, shrunk to 1."""
    return _memo_factor(h, team_id, stat, against=False)


def opponent_factor(h: History, opponent_id: int, stat: str) -> float:
    """What the opponent allowed (the counts of the men who played against it) over what their minutes give, shrunk to 1."""
    return _memo_factor(h, opponent_id, stat, against=True)


@dataclass(frozen=True, slots=True)
class Rate:
    stat: str
    per90: float
    """The rate for this match: the player's shrunk rate times the opponent's factor."""
    player_per90: float
    prior_per90: float
    position_per90: float
    team_factor: float
    opponent_factor: float
    nineties: float
    """Weighted 90-minute units of his own behind the estimate."""

    def as_json(self) -> dict[str, float | str]:
        return {"stat": self.stat, "per90": round(self.per90, 4), "player_per90": round(self.player_per90, 4),
                "prior_per90": round(self.prior_per90, 4), "position_per90": round(self.position_per90, 4),
                "team_factor": round(self.team_factor, 3), "opponent_factor": round(self.opponent_factor, 3),
                "nineties": round(self.nineties, 2)}


def player_rate(h: History, player_id: int, stat: str, *, at: datetime, team_id: int, opponent_id: int | None, position: str) -> Rate:
    return player_rates(h, player_id, at=at, team_id=team_id, opponent_id=opponent_id, position=position, stats=(stat,))[stat]


def player_rates(h: History, player_id: int, *, at: datetime, team_id: int, opponent_id: int | None, position: str,
                 stats: Sequence[str] = STATS) -> Mapping[str, Rate]:
    """His rates of these counts for a match against ``opponent_id`` (None: no opponent adjustment) as of ``at``."""
    apps = [(a.line, recency_weight(at, a.kickoff)) for a in h.recent_apps(player_id, APPEARANCES) if a.line.played]
    out: dict[str, Rate] = {}
    for stat in stats:
        pos_rate = position_rate(h, stat, position)
        tf = team_factor(h, team_id, stat)
        prior = pos_rate * tf
        ys: list[float] = []
        ms: list[float] = []
        ws: list[float] = []
        for line, w in apps:
            v = line.count(stat)
            if v is not None:
                ys.append(float(v))
                ms.append(float(line.minutes))
                ws.append(w)
        own = shrunk_rate(ys, ms, ws, prior, PRIOR_90S[stat])
        of = 1.0 if opponent_id is None else opponent_factor(h, opponent_id, stat)
        nineties = sum(w * m / 90.0 for w, m in zip(ws, ms, strict=True))
        out[stat] = Rate(stat, max(FLOOR_RATE, own * of), own, prior, pos_rate, tf, of, nineties)
    return out
