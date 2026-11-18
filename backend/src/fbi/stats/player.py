"""The statistics documents of the players of one competition season (plan EA, EA-005). Pure.

A player's position is the one of his sheets weighted by minutes (G, D, M, F), or his profile's when no sheet says it. His figures are
the template of that position (``TEMPLATES``), each a rate per 90 over the appearances whose sheet reports it (a NULL leaves the
appearance and its minutes out: a league that does not record tackles lowers nobody's tackles) or a proportion. A percentile is taken
among the players of the same position with at least ``MIN_NINETIES`` noventas, and needs ``MIN_PLAYERS`` of them; the distribution
(p10-p90) is theirs. A metric the competition season reports in less than ``COVERAGE`` of its appearances is ``sin_cobertura``.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Final, cast

from fbi.statmath import formulas as fx
from fbi.stats.data import PlayerLine, SeasonData
from fbi.stats.doc import (
    Doc,
    MinutesItem,
    PlayerBody,
    Quantiles,
    Ref,
    StatFigure,
    StripItem,
    StripValue,
    is_missing,
    missing,
)

CALC_VERSION: Final = "player-agg-v1"
MIN_NINETIES: Final = 5.0
MIN_PLAYERS: Final = 10
COVERAGE: Final = 0.8
STRIP: Final = 5

GROUP: Final[dict[str, str]] = {"G": "portero", "D": "defensa", "M": "medio", "F": "delantero"}
PROFILE_GROUP: Final[dict[str, str]] = {"goalkeeper": "G", "defender": "D", "midfielder": "M", "attacker": "F", "forward": "F"}


@dataclass(frozen=True, slots=True)
class Metric:
    key: str
    unit: str
    better: str
    column: str | None
    """The count summed per 90; None for a proportion (``ratio``)."""
    ratio: Callable[[Sequence[PlayerLine]], tuple[float | None, int]] | None = None
    strip: bool = True


def _ratio(num: str, den: str, *, extra_den: str | None = None) -> Callable[[Sequence[PlayerLine]], tuple[float | None, int]]:
    def read(lines: Sequence[PlayerLine]) -> tuple[float | None, int]:
        n = d = 0.0
        used = 0
        for line in lines:
            a, b = line.counts.get(num), line.counts.get(den)
            c = line.counts.get(extra_den) if extra_den else 0.0
            if a is None or b is None or c is None:
                continue
            used += 1
            n += a
            d += b + (c if extra_den else 0.0)
        return (100.0 * n / d if d > 0 else None), used
    return read


def _weighted_accuracy(lines: Sequence[PlayerLine]) -> tuple[float | None, int]:
    n = d = 0.0
    used = 0
    for line in lines:
        acc, passes = line.counts.get("passes_accuracy_pct"), line.counts.get("passes_total")
        if acc is None or passes is None or passes <= 0:
            continue
        # API-Football fills ``passes.accuracy`` with the COUNT of accurate passes (measured in production on 18-nov-2026: 86 % of
        # the sheets with 20+ passes have it at or below the passes); a value above the passes and at most 100 is a percentage
        if acc <= passes:
            accurate = acc
        elif acc <= 100:
            accurate = acc / 100.0 * passes
        else:
            continue
        used += 1
        n += accurate
        d += passes
    return (100.0 * n / d if d > 0 else None), used


METRICS: Final[dict[str, Metric]] = {m.key: m for m in (
    Metric("goals", "por_90", "mas", "goals"),
    Metric("assists", "por_90", "mas", "assists"),
    Metric("shots", "por_90", "mas", "shots_total"),
    Metric("shots_on_target", "por_90", "mas", "shots_on"),
    Metric("key_passes", "por_90", "mas", "passes_key"),
    Metric("passes", "por_90", "mas", "passes_total"),
    Metric("pass_accuracy", "porcentaje", "mas", None, _weighted_accuracy, strip=False),
    Metric("tackles", "por_90", "mas", "tackles"),
    Metric("interceptions", "por_90", "mas", "interceptions"),
    Metric("blocks", "por_90", "mas", "blocks"),
    Metric("duels_won_pct", "porcentaje", "mas", None, _ratio("duels_won", "duels_total"), strip=False),
    Metric("dribbles", "por_90", "mas", "dribbles_success"),
    Metric("fouls_committed", "por_90", "menos", "fouls_committed"),
    Metric("fouls_drawn", "por_90", "mas", "fouls_drawn"),
    Metric("yellow_cards", "por_90", "menos", "yellow_cards"),
    Metric("saves", "por_90", "mas", "saves"),
    Metric("goals_conceded", "por_90", "menos", "goals_conceded"),
    Metric("save_pct", "porcentaje", "mas", None, _ratio("saves", "saves", extra_den="goals_conceded"), strip=False),
)}

TEMPLATES: Final[dict[str, tuple[str, ...]]] = {
    "G": ("saves", "save_pct", "goals_conceded", "passes", "pass_accuracy"),
    "D": ("tackles", "interceptions", "blocks", "duels_won_pct", "fouls_committed", "yellow_cards", "passes", "pass_accuracy",
          "goals"),
    "M": ("passes", "pass_accuracy", "key_passes", "tackles", "interceptions", "dribbles", "fouls_committed", "goals", "assists",
          "shots"),
    "F": ("goals", "assists", "shots", "shots_on_target", "key_passes", "dribbles", "fouls_drawn", "duels_won_pct"),
}
"""The figures of each position, in the order the page shows them (V2·2)."""


@dataclass(frozen=True, slots=True)
class Value:
    value: float | None
    used: int
    """Appearances that report it."""


def value_of(metric: Metric, lines: Sequence[PlayerLine]) -> Value:
    if metric.ratio is not None:
        v, used = metric.ratio(lines)
        return Value(v, used)
    col = cast(str, metric.column)
    count = minutes = 0.0
    used = 0
    for line in lines:
        c = line.counts.get(col)
        if c is None:
            continue
        used += 1
        count += c
        minutes += line.minutes
    if used == 0 or minutes <= 0:
        return Value(None, used)
    return Value(count * 90.0 / minutes, used)


def position_of(lines: Sequence[PlayerLine]) -> str | None:
    weights: Counter[str] = Counter()
    for line in lines:
        if line.position:
            weights[line.position] += line.minutes
    if weights:
        return weights.most_common(1)[0][0]
    prof = (lines[0].profile_position or "").strip().lower() if lines else ""
    return PROFILE_GROUP.get(prof)


def coverage(lines: Sequence[PlayerLine]) -> dict[str, float]:
    if not lines:
        return {}
    out = {}
    for key, metric in METRICS.items():
        cols = [metric.column] if metric.column else {
            "pass_accuracy": ["passes_accuracy_pct", "passes_total"], "duels_won_pct": ["duels_won", "duels_total"],
            "save_pct": ["saves", "goals_conceded"]}[key]
        have = sum(1 for line in lines if all(line.counts.get(c) is not None for c in cols))
        out[key] = fx.half_up(have / len(lines), 4)
    return out


@dataclass(slots=True)
class PlayerDoc:
    player_id: int
    team_id: int | None
    body: Doc
    sample: int


def season_documents(data: SeasonData) -> list[PlayerDoc]:
    by_player: dict[int, list[PlayerLine]] = defaultdict(list)
    for line in data.players:
        by_player[line.player_id].append(line)
    cover = coverage(data.players)
    side_team = {}
    for m in data.matches:
        side_team[(m.fixture_id, "home")] = (m.home_id, m.home_name, m.away_id, m.away_name)
        side_team[(m.fixture_id, "away")] = (m.away_id, m.away_name, m.home_id, m.home_name)
    positions = {pid: position_of(lines) for pid, lines in by_player.items()}
    minutes = {pid: sum(line.minutes for line in lines) for pid, lines in by_player.items()}
    values = {pid: {k: value_of(m, lines) for k, m in METRICS.items()} for pid, lines in by_player.items()}
    population: dict[tuple[str, str], list[float]] = defaultdict(list)
    for pid, pos in positions.items():
        if pos is None or minutes[pid] < MIN_NINETIES * 90:
            continue
        for key in METRICS:
            measured = values[pid][key].value
            if measured is not None:
                population[(pos, key)].append(measured)
    docs = []
    for pid, lines in by_player.items():
        lines.sort(key=lambda x: (x.kickoff_at, x.fixture_id))
        pos = positions[pid]
        last = lines[-1]
        team = side_team.get((last.fixture_id, last.team_side))
        figures = []
        for key in TEMPLATES.get(pos or "", ()):
            metric = METRICS[key]
            v = values[pid][key]
            value: float | Doc
            if v.value is None:
                value = missing("sin_datos")
            elif cover.get(key, 0.0) < COVERAGE:
                value = missing("sin_cobertura")
            else:
                value = fx.half_up(v.value, 3)
            pop = population.get((cast(str, pos), key), [])
            pct: int | Doc
            dist: Doc
            if len(pop) < MIN_PLAYERS:
                pct = dist = missing("muestra_insuficiente", sample=len(pop), min_sample=MIN_PLAYERS)
            else:
                q = fx.quantiles(pop)
                dist = Quantiles(p10=q[0], p25=q[1], p50=q[2], p75=q[3], p90=q[4], entities=len(pop))
                if is_missing(value):
                    pct = missing("sin_datos")
                elif minutes[pid] < MIN_NINETIES * 90:
                    pct = missing("muestra_insuficiente", sample=minutes[pid], min_sample=int(MIN_NINETIES * 90))
                else:
                    pct = fx.percentile(cast(float, v.value), pop)
            league: float | Doc = dist["p50"] if not is_missing(dist) else missing("sin_datos")
            figures.append(StatFigure(key=key, unit=metric.unit, better=metric.better, value=value, matches_with_data=v.used,
                                      percentile=pct, league_value=league, distribution=dist))
        strip_keys = [k for k in TEMPLATES.get(pos or "", ()) if METRICS[k].strip]
        strip = []
        for line in lines[-STRIP:]:
            t = side_team.get((line.fixture_id, line.team_side))
            vals = []
            for k in strip_keys:
                c = line.counts.get(cast(str, METRICS[k].column))
                vals.append(StripValue(key=k, value=int(c) if c is not None else missing("sin_datos")))
            strip.append(StripItem(fixture_id=line.fixture_id, kickoff_at=line.kickoff_at,
                                   opponent=Ref(id=t[2], name=t[3]) if t else Ref(id=0, name="—"), minutes=line.minutes,
                                   starter=line.starter, values=vals))
        total = minutes[pid]
        body = PlayerBody(
            player=Ref(id=pid, name=last.player_name), team=Ref(id=team[0], name=team[1]) if team else missing("sin_datos"),
            position=GROUP[pos] if pos else missing("sin_datos"), appearances=len(lines),
            starts=sum(1 for line in lines if line.starter), minutes=total, nineties=fx.half_up(total / 90.0, 1),
            min_nineties=MIN_NINETIES, figures=figures, last5=strip,
            recent_minutes=[MinutesItem(fixture_id=line.fixture_id, minutes=line.minutes, starter=line.starter) for line in lines[-10:]])
        docs.append(PlayerDoc(pid, team[0] if team else None, body, len(lines)))
    return docs


def scatter(data: SeasonData) -> dict[str, list[dict[str, float]]]:
    """V2·4's background, per position: every player with at least ``MIN_NINETIES`` noventas, shots per 90 and the share on target."""
    by_player: dict[int, list[PlayerLine]] = defaultdict(list)
    for line in data.players:
        by_player[line.player_id].append(line)
    out: dict[str, list[dict[str, float]]] = defaultdict(list)
    for pid, lines in by_player.items():
        pos = position_of(lines)
        if pos is None or sum(line.minutes for line in lines) < MIN_NINETIES * 90:
            continue
        shots = value_of(METRICS["shots"], lines).value
        on = value_of(METRICS["shots_on_target"], lines).value
        if shots is None or on is None or shots <= 0:
            continue
        out[GROUP[pos]].append({"player_id": pid, "shots_per90": fx.half_up(shots, 3),
                                "on_target_pct": fx.half_up(min(100.0, 100.0 * on / shots), 1)})
    return dict(out)
