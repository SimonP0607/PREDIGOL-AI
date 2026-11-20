"""The tables of a competition season that are not a phase's table - an annual or accumulated table, an average over several
seasons and the places they give - computed from the results and the competition's rules file (BE-075, plan PM, PM-09-01,
OP-20). Colombia first: the reclasificación (arts. 27-28), the relegation table by average (arts. 32-34) and the places in the
Libertadores and the Sudamericana (arts. 30-31), all from ``config/rules/239_primera_a_colombia/``.

WHY
---
In Colombia the year is decided by tables the provider does not give: the reclasificación (the provider's «Tabla Anual» is it,
but only for the current season), the average over three seasons with a window per club, and the places it allocates.
``fbi.competitions.scenarios`` skips both (``tabla_promedio_no_calculada``, ``tabla_con_eliminatorias``). This module computes
them, and nothing of them is fixed in code: which phases count, the earlier seasons and their round labels, the clubs whose
average counts fewer seasons, the scope of the tie-breakers and the order of the places are all in the rules file.

WHAT IT GUARANTEES
------------------
* Only what the results and the rules prove. A table is ``complete`` when every match of every phase it counts is decided; a
  zone is ``definitivo`` only then, and only when no tie the regulation leaves open (a play-off, lots) straddles its edge. A
  zone marked ``conditional`` in the rules is never ``definitivo``.
* A place is never guessed: a champion or a cup winner not known yet is ``pendiente`` and the places after it are
  ``provisional``; a club that would take two places is a case the regulation settles in a paragraph that is not coded, and
  the allocation stops there (``parrafo_sin_codificar``).
* Results changed off the pitch (an awarded match, a score replaced by a decision) are applied from the competition's
  ``decisions/<season>.yaml``, each with its evidence; one not verified by the owner is counted and said
  (``decisiones_sin_verificar``). A match decided off the pitch with no score and no decision is left out and said.
* The average is the exact quotient (``fractions.Fraction``); the order never depends on a rounding. Whether rounding to two or
  three decimals would change who is in a zone is measured and said (``redondeo``), because the regulation states none.

Pure: matches, rules and decisions in, a reading out. No database, no clock, no model, no network. Nothing here is shown to a
reader: the switch ``FBI_COMPETITION_TABLES`` is OFF and stays so until the owner signs the cotejo of the regulation (DOC-008)
and the publication (DM-14). ``scripts/competition_tables.py`` runs it in shadow against the database and the provider's tables.
"""

from __future__ import annotations

import fnmatch
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any, Final, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from fbi.competitions import ranking as rk
from fbi.competitions.rules import (
    RULES_DIR,
    CompetitionRules,
    Phase,
    RulesError,
    Table,
    Tournament,
    Zone,
)
from fbi.core.env import environment

VERSION: Final = "season-tables-v1"
SWITCH: Final = "FBI_COMPETITION_TABLES"
"""OFF while the line is absent: no reader sees a table of this module. Turned on only with the owner's signature (DOC-008 acta and
DM-14), with an audited kit, like every other switch of plan PM (PM-15-03)."""
DECISIONS_SCHEMA: Final = "competition-decisions/1"
DECISIONS_DIR: Final = "decisions"
DECIDED: Final = frozenset({"FT", "AET", "PEN", "AWD", "WO"})
"""Statuses of a match that counts: played to the end, or decided off the pitch (as ``fbi.competitions.tables.DECIDED``)."""
OFF_PITCH: Final = frozenset({"AWD", "WO"})
ROUNDINGS: Final = ((2, "half_up"), (3, "half_up"), (2, "down"), (3, "down"))
"""The roundings whose effect on the zones is measured: the regulation states none (art. 32: «Excel»), and the published tables
of 20-nov-2026 show three decimals cut, not rounded (204/116 shown 1.758)."""


def switch_on() -> bool:
    """Whether a reader may be shown these tables (``FBI_COMPETITION_TABLES``, off by default)."""
    return environment().get(SWITCH, "").strip().lower() in {"1", "on", "true", "yes"}


# ── the matches and the decisions ─────────────────────────────────────────────────────────────────────────────────────────────


@dataclass(frozen=True, slots=True)
class Match:
    season: int
    fixture: int
    """The provider's fixture id."""
    round: str | None
    status: str
    home: int
    away: int
    """Provider team ids."""
    home_goals: int | None
    away_goals: int | None
    pen_home: int | None = None
    pen_away: int | None = None
    decision: Literal["verified", "unverified"] | None = None
    """Set when the score is a decision's (``decisions/<season>.yaml``), not the stored one."""

    @property
    def decided(self) -> bool:
        return self.status in DECIDED

    @property
    def counts(self) -> bool:
        return self.decided and self.home_goals is not None and self.away_goals is not None

    def result(self) -> rk.Result:
        assert self.home_goals is not None and self.away_goals is not None
        return rk.Result(self.home, self.away, self.home_goals, self.away_goals)


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, populate_by_name=True)


class Score(_Model):
    home: int = Field(ge=0, le=30)
    away: int = Field(ge=0, le=30)


class Decision(_Model):
    fixture: int = Field(ge=1)
    round: str = Field(min_length=2, max_length=80)
    home: int = Field(ge=1)
    away: int = Field(ge=1)
    kind: Literal["awarded", "result_changed"]
    result: Score
    stored: Score | None = None
    """The score ``core.fixture_results`` keeps when it was read (None: no row, as for a match the provider marks AWD)."""
    evidence: str = Field(min_length=20, max_length=1200)
    verified: bool = False
    """True only when the owner read the competition's resolution (and the cotejo says so)."""


class Decisions(_Model):
    schema_: Literal["competition-decisions/1"] = Field(alias="schema")
    league_id: int = Field(ge=1)
    season: int = Field(ge=1990, le=2100)
    decisions: tuple[Decision, ...] = ()


def load_decisions(league_id: int, root: Path = RULES_DIR) -> dict[int, Decisions]:
    """``<root>/<league_id>_*/decisions/<season>.yaml`` by season (empty when the competition has none)."""
    out: dict[int, Decisions] = {}
    for path in sorted(root.glob(f"{league_id}_*/{DECISIONS_DIR}/*.yaml")):
        try:
            d = Decisions.model_validate(yaml.safe_load(path.read_bytes()))
        except (OSError, yaml.YAMLError, ValidationError) as exc:
            raise RulesError(f"{path.relative_to(root)}: {exc}") from exc
        if d.league_id != league_id or path.stem != str(d.season):
            raise RulesError(f"{path.relative_to(root)}: the file of league {d.league_id} season {d.season} is "
                             f"{d.league_id}_*/{DECISIONS_DIR}/{d.season}.yaml")
        if len({x.fixture for x in d.decisions}) != len(d.decisions):
            raise RulesError(f"{path.relative_to(root)}: a fixture is listed twice")
        out[d.season] = d
    return out


@dataclass(frozen=True, slots=True)
class Applied:
    matches: tuple[Match, ...]
    applied: tuple[dict[str, Any], ...]
    problems: tuple[str, ...]

    @property
    def unverified(self) -> int:
        return sum(1 for a in self.applied if not a["verified"])


def apply_decisions(matches: Sequence[Match], decisions: Mapping[int, Decisions]) -> Applied:
    """The matches with each decision's result in place of the stored score. A decision whose match is missing, whose teams
    differ, or whose stored score is no longer what the database keeps is not applied and is said (the data moved: re-read)."""
    by_fixture = {m.fixture: m for m in matches}
    changed: dict[int, Match] = {}
    applied: list[dict[str, Any]] = []
    problems: list[str] = []
    for season, d in sorted(decisions.items()):
        for x in d.decisions:
            m = by_fixture.get(x.fixture)
            if m is None:
                if any(mm.season == season for mm in matches):
                    problems.append(f"decision {season}/{x.fixture}: the match is not among the matches read")
                continue
            if (m.home, m.away, m.season) != (x.home, x.away, season):
                problems.append(f"decision {season}/{x.fixture}: the match is {m.home} v {m.away} ({m.season}), the decision says "
                                f"{x.home} v {x.away}: not applied")
                continue
            now = None if m.home_goals is None or m.away_goals is None else (m.home_goals, m.away_goals)
            then = None if x.stored is None else (x.stored.home, x.stored.away)
            if now != then:
                problems.append(f"decision {season}/{x.fixture}: the stored score is now {now}, the decision was written over "
                                f"{then}: not applied")
                continue
            changed[x.fixture] = replace(m, status="AWD" if x.kind == "awarded" else m.status, home_goals=x.result.home,
                                         away_goals=x.result.away, decision="verified" if x.verified else "unverified")
            applied.append({"season": season, "fixture": x.fixture, "round": x.round, "home": x.home, "away": x.away,
                            "kind": x.kind, "result": [x.result.home, x.result.away],
                            "stored": None if then is None else list(then),
                            "verified": x.verified})
    out = tuple(changed.get(m.fixture, m) for m in matches)
    for m in out:
        if m.decided and not m.counts:
            problems.append(f"match {m.season}/{m.fixture} ({m.round}, {m.home} v {m.away}) is {m.status} with no score and no "
                            "decision: left out of every table")
    return Applied(out, tuple(applied), tuple(problems))


# ── phases ───────────────────────────────────────────────────────────────────────────────────────────────────────────────────


def _refs(rules: CompetitionRules, counts: Iterable[str]) -> list[tuple[Tournament, Phase]]:
    out: list[tuple[Tournament, Phase]] = []
    for ref in counts:
        tk, _, pk = ref.partition(".")
        out.extend((t, p) for t, p in rules.phases() if t.key == tk and (pk == "*" or p.key == pk))
    return out


def _of_phase(phase: Phase, matches: Iterable[Match], season: int) -> list[Match]:
    return [m for m in matches if m.season == season and phase.covers(m.round)]


def phase_complete(phase: Phase, ms: Sequence[Match]) -> bool:
    """Every match of the phase is on the calendar and decided: a league or group phase by its size, a knock-out phase when it
    has matches, all decided, and every pairing has its legs."""
    if not ms or any(not m.counts for m in ms):
        return False
    if phase.format == "league" and phase.teams and phase.matches_per_team:
        return len(ms) == phase.teams * phase.matches_per_team // 2
    if phase.format == "groups" and phase.groups and phase.group_size and phase.matches_per_team:
        return len(ms) == phase.groups * phase.group_size * phase.matches_per_team // 2
    if phase.format == "knockout" and phase.knockout is not None:
        pairs: dict[frozenset[int], int] = {}
        for m in ms:
            pairs[frozenset((m.home, m.away))] = pairs.get(frozenset((m.home, m.away)), 0) + 1
        return all(n == phase.knockout.legs for n in pairs.values())
    return False


def _tie_winner(phase: Phase, ms: Sequence[Match]) -> tuple[int | None, str]:
    """The winner of the one pairing of a knock-out phase under its rules (``points_over_legs``, ``aggregate``, ``penalties``,
    in the regulation's order), or None with the reason."""
    assert phase.knockout is not None
    teams = {t for m in ms for t in (m.home, m.away)}
    if not teams:
        return None, "the phase has no match on the calendar yet"
    if len(teams) != 2:
        return None, "the phase is not a single pairing"
    if not phase_complete(phase, ms):
        return None, "the pairing is not decided yet"
    a, b = sorted(teams)
    for how in phase.knockout.level:
        if how == "points_over_legs":
            pa = pb = 0
            for m in ms:
                r = rk.rows_of([m.result()], rk.THREE_ONE_ZERO)
                pa, pb = pa + r[a].points, pb + r[b].points
            va, vb = pa, pb
        elif how == "aggregate":
            va = sum(((m.home_goals or 0) if m.home == a else (m.away_goals or 0)) for m in ms)
            vb = sum(((m.home_goals or 0) if m.home == b else (m.away_goals or 0)) for m in ms)
        elif how == "penalties":
            last = ms[-1]
            if last.pen_home is None or last.pen_away is None:
                return None, "level and no shoot-out stored"
            va, vb = (last.pen_home, last.pen_away) if last.home == a else (last.pen_away, last.pen_home)
        else:
            return None, f"{how} is not computed here"
        if va != vb:
            return (a if va > vb else b), how
    return None, "level after every criterion of the rules"


def champions(rules: CompetitionRules, season: int, matches: Sequence[Match]) -> dict[str, dict[str, Any]]:
    """The champion of each tournament whose last phase is a knock-out pairing, or why it is not known."""
    out: dict[str, dict[str, Any]] = {}
    for t in rules.tournaments:
        last = t.phases[-1]
        if last.format != "knockout":
            out[t.key] = {"team": None, "reason": "the tournament does not end in a knock-out phase"}
            continue
        ms = _of_phase(last, matches, season)
        team, how = _tie_winner(last, ms)
        out[t.key] = {"team": team, "decided_by": how if team is not None else None,
                      "reason": None if team is not None else how}
    return out


# ── the reading ──────────────────────────────────────────────────────────────────────────────────────────────────────────────


@dataclass(slots=True)
class TableReading:
    key: str
    name: str
    kind: str
    complete: bool
    rows: list[dict[str, Any]]
    zones: list[dict[str, Any]] = field(default_factory=list)
    places: list[dict[str, Any]] = field(default_factory=list)
    rounding: dict[str, str] = field(default_factory=dict)
    pending: int = 0
    """Matches of the phases counted that are on the calendar and not decided."""
    unverified_decisions: int = 0
    note: str | None = None

    def order(self) -> list[int]:
        return [int(r["team"]) for r in self.rows]

    def as_json(self) -> dict[str, Any]:
        out: dict[str, Any] = {"key": self.key, "name": self.name, "kind": self.kind, "complete": self.complete,
                               "pending_matches": self.pending, "decisiones_sin_verificar": self.unverified_decisions,
                               "rows": self.rows, "zones": self.zones}
        if self.places:
            out["places"] = self.places
        if self.rounding:
            out["redondeo"] = self.rounding
        if self.note:
            out["note"] = self.note
        return out


def _row_json(position: int, row: rk.Row, place: rk.Place | None) -> dict[str, Any]:
    return {"position": position, "team": row.team, "played": row.played, "wins": row.wins, "draws": row.draws,
            "losses": row.losses, "goals_for": row.goals_for, "goals_against": row.goals_against,
            "goal_difference": row.goal_difference, "points": row.points,
            "shared_with": [] if place is None else list(place.shared_with),
            "decided_by": None if place is None else place.decided_by, "open_on": None if place is None else place.open_on}


def _zone_states(zones: Sequence[Zone], rows: Sequence[dict[str, Any]], complete: bool) -> list[dict[str, Any]]:
    size = len(rows)
    out: list[dict[str, Any]] = []
    for z in zones:
        positions = list(z.positions(size))
        if not positions:
            continue
        inside = {rows[p - 1]["team"] for p in positions}
        straddles = any(set(rows[p - 1]["shared_with"]) - inside for p in positions)
        if z.conditional:
            state = "condicional"
        elif not complete:
            state = "provisional"
        elif straddles:
            state = "empate_abierto"
        else:
            state = "definitivo"
        out.append({"kind": z.kind, "target": z.target, "positions": positions,
                    "teams": [rows[p - 1]["team"] for p in positions], "state": state, "note": z.note})
    return out


def _count_pending(ms: Iterable[Match]) -> int:
    return sum(1 for m in ms if not m.decided)


def _unverified(ms: Iterable[Match]) -> int:
    return sum(1 for m in ms if m.decision == "unverified")


def _aggregate(rules: CompetitionRules, table: Table, season: int, matches: Sequence[Match]) -> TableReading:
    refs = _refs(rules, table.counts)
    counted = [m for _t, p in refs for m in _of_phase(p, matches, season)]
    complete = bool(refs) and all(phase_complete(p, _of_phase(p, matches, season)) for _t, p in refs)
    results = [m.result() for m in counted if m.counts]
    members = sorted({t for m in counted for t in (m.home, m.away)})
    ranked = rk.rank(results, table.ranking, points=rules.points, teams=members, complete=complete, zones=table.zones)
    rows = [_row_json(p.position, p.row, p) for p in ranked.places]
    return TableReading(table.key, table.name, table.kind, complete, rows, _zone_states(table.zones, rows, complete),
                        pending=_count_pending(counted),
                        unverified_decisions=_unverified(counted), note=table.note)


def _rounded(value: Fraction, digits: int, mode: str = "half_up") -> Decimal:
    exact = Decimal(value.numerator) / Decimal(value.denominator)
    return exact.quantize(Decimal(1).scaleb(-digits), rounding=ROUND_HALF_UP if mode == "half_up" else ROUND_DOWN)


def _order_by(values: Mapping[int, Any], scope: Sequence[rk.Result], table: Table, rules: CompetitionRules
              ) -> list[tuple[int, rk.Place | None]]:
    """Teams by ``values`` (higher first); a group level on it ranked among themselves on the tie scope's results with the
    table's tie-breakers."""
    order = sorted(values, key=lambda t: (-values[t], t))
    out: list[tuple[int, rk.Place | None]] = []
    i = 0
    while i < len(order):
        level = [t for t in order[i:] if values[t] == values[order[i]]]
        if len(level) == 1:
            out.append((level[0], None))
        else:
            sub = rk.rank(scope, table.ranking, points=rules.points, members=level, complete=True)
            out.extend((p.team, p) for p in sub.places)
        i += len(level)
    return out


def _average(rules: CompetitionRules, table: Table, season: int, matches: Sequence[Match]) -> TableReading:
    refs = _refs(rules, table.counts)
    current = [m for _t, p in refs for m in _of_phase(p, matches, season)]
    complete = bool(refs) and all(phase_complete(p, _of_phase(p, matches, season)) for _t, p in refs)
    members = sorted({t for m in current for t in (m.home, m.away)})
    seasons_all = [p.season for p in table.past] + [season]
    window = {w.team: set(w.seasons) for w in table.windows}
    past_rounds = {p.season: p.rounds for p in table.past}

    def counted_in(m: Match) -> bool:
        if m.season == season:
            return any(p.covers(m.round) for _t, p in refs)
        pats = past_rounds.get(m.season, ())
        return bool(m.round) and any(fnmatch.fnmatchcase(str(m.round), pat) for pat in pats)

    pts: dict[int, int] = dict.fromkeys(members, 0)
    played: dict[int, int] = dict.fromkeys(members, 0)
    by_season: dict[int, dict[int, list[int]]] = {t: {s: [0, 0] for s in seasons_all} for t in members}
    unverified = 0
    for m in matches:
        if not m.counts or m.season not in seasons_all or not counted_in(m):
            continue
        r = rk.rows_of([m.result()], rules.points)
        touched = False
        for t in (m.home, m.away):
            if t in pts and m.season in window.get(t, set(seasons_all)):
                pts[t] += r[t].points
                played[t] += 1
                by_season[t][m.season][0] += 1
                by_season[t][m.season][1] += r[t].points
                touched = True
        unverified += int(touched and m.decision == "unverified")
    average = {t: Fraction(pts[t], played[t]) if played[t] else Fraction(0) for t in members}
    ties_refs = _refs(rules, table.ties_on) if table.ties_on else refs
    scope = [m.result() for _t, p in ties_refs for m in _of_phase(p, matches, season) if m.counts]
    scope_rows = rk.rows_of(scope, rules.points, teams=members)

    ordered = _order_by(average, scope, table, rules)
    rows: list[dict[str, Any]] = []
    for pos, (t, place) in enumerate(ordered, start=1):
        rows.append({"position": pos, "team": t, "points": pts[t], "played": played[t],
                     "average": f"{average[t].numerator}/{average[t].denominator}",
                     "average_3": str(_rounded(average[t], 3)),
                     "average_3_cut": str(_rounded(average[t], 3, "down")),
                     "seasons": {str(s): {"played": v[0], "points": v[1]} for s, v in by_season[t].items() if v[0]},
                     "window": sorted(window.get(t, set(seasons_all))),
                     "tie_scope": {"points": scope_rows[t].points, "goal_difference": scope_rows[t].goal_difference,
                                   "goals_for": scope_rows[t].goals_for, "wins": scope_rows[t].wins},
                     "shared_with": [] if place is None else list(place.shared_with),
                     "decided_by": None if place is None else (place.decided_by or "points"),
                     "open_on": None if place is None else place.open_on})
    zones = _zone_states(table.zones, rows, complete)
    rounding: dict[str, str] = {}
    for digits, mode in ROUNDINGS:
        alt = [t for t, _p in _order_by({t: _rounded(a, digits, mode) for t, a in average.items()}, scope, table, rules)]
        changes = any({alt[p - 1] for p in z["positions"]} != set(z["teams"]) for z in zones)
        rounding[f"{digits}_{mode}"] = "cambia_una_zona" if changes else "igual"
    return TableReading(table.key, table.name, table.kind, complete, rows, zones, rounding=rounding,
                        pending=_count_pending(current), unverified_decisions=unverified, note=table.note)


def _places(table: Table, reading: TableReading, champs: Mapping[str, dict[str, Any]],
            cup_winners: Mapping[str, int]) -> list[dict[str, Any]]:
    order = reading.order()
    shared = {int(r["team"]): bool(r["shared_with"]) for r in reading.rows}
    placed: set[int] = set()
    out: list[dict[str, Any]] = []
    certain = reading.complete
    stop: str | None = None
    for comp in table.places:
        for s in comp.slots:
            entry: dict[str, Any] = {"competition": comp.competition, "article": comp.article, "slot": s.slot,
                                     "source": s.source, "team": None}
            if stop is not None:
                out.append({**entry, "state": "no_calculado", "reason": stop})
                continue
            team: int | None
            if s.source in ("champion", "cup_winner"):
                assert s.of is not None
                team = champs.get(s.of, {}).get("team") if s.source == "champion" else cup_winners.get(s.of)
                if team is None:
                    certain = False
                    out.append({**entry, "of": s.of, "state": "pendiente",
                                "reason": f"{'the champion of' if s.source == 'champion' else 'the winner of'} {s.of} is not known"})
                    continue
                if team in placed:
                    stop = (f"{team} already has a place: the regulation settles it in a paragraph that is not coded "
                            "(parrafo_sin_codificar)")
                    out.append({**entry, "of": s.of, "team": team, "state": "no_calculado", "reason": stop})
                    continue
                placed.add(team)
                out.append({**entry, "of": s.of, "team": team, "state": "calculado"})
                continue
            team = next((t for t in order if t not in placed), None)
            if team is None:
                out.append({**entry, "state": "no_calculado", "reason": "no team left in the table"})
                continue
            placed.add(team)
            ok = certain and not shared.get(team, False)
            out.append({**entry, "team": team, "position": order.index(team) + 1,
                        "state": "calculado" if ok else "provisional",
                        "reason": None if ok else ("the table is not complete or an earlier place is pending"
                                                   if not certain else "the team shares its place (tie open)")})
    return out


@dataclass(frozen=True, slots=True)
class Reading:
    league_id: int
    season: int
    rules_version: int
    tables: tuple[TableReading, ...]
    phases: tuple[TableReading, ...]
    champions: dict[str, dict[str, Any]]
    decisions: Applied
    version: str = VERSION

    def table(self, key: str) -> TableReading:
        return next(t for t in (*self.tables, *self.phases) if t.key == key)

    def as_json(self) -> dict[str, Any]:
        return {"version": self.version, "league_id": self.league_id, "season": self.season,
                "rules_version": self.rules_version, "champions": self.champions,
                "tables": [t.as_json() for t in self.tables], "phases": [t.as_json() for t in self.phases],
                "decisions": {"applied": list(self.decisions.applied), "sin_verificar": self.decisions.unverified},
                "problems": list(self.decisions.problems)}


def compute(rules: CompetitionRules, season: int, matches: Sequence[Match], *,
            decisions: Mapping[int, Decisions] | None = None, cup_winners: Mapping[str, int] | None = None) -> Reading:
    """Every table of the rules file (``tables``) and every single-table league phase of ``season``, from ``matches`` (the season's
    and, for an average, the earlier seasons it names) with the decisions applied. ``cup_winners``: the winner of another
    competition a place names (``Copa BetPlay DIMAYOR 2026``), when known."""
    if season not in rules.seasons:
        raise ValueError(f"the rules of league {rules.league_id} version {rules.version} do not cover season {season}")
    applied = apply_decisions(matches, decisions or {})
    ms = applied.matches
    champs = champions(rules, season, ms)
    tables: list[TableReading] = []
    for table in rules.tables:
        reading = _average(rules, table, season, ms) if table.kind == "average" else _aggregate(rules, table, season, ms)
        if table.places:
            reading.places = _places(table, reading, champs, cup_winners or {})
        tables.append(reading)
    phases: list[TableReading] = []
    for t, p in rules.phases():
        if p.format != "league" or p.ranking is None:
            continue
        own = _of_phase(p, ms, season)
        if not own:
            continue
        complete = phase_complete(p, own)
        ranked = rk.rank([m.result() for m in own if m.counts], p.ranking, points=rules.points,
                         teams=sorted({x for m in own for x in (m.home, m.away)}), complete=complete,
                         legs=p.legs_between_pair, zones=p.zones, size=p.teams)
        rows = [_row_json(pl.position, pl.row, pl) for pl in ranked.places]
        phases.append(TableReading(f"{t.key}.{p.key}", f"{t.name} · {p.name}", "phase", complete, rows,
                                   _zone_states(p.zones, rows, complete), pending=_count_pending(own),
                                   unverified_decisions=_unverified(own)))
    return Reading(rules.league_id, season, rules.version, tuple(tables), tuple(phases), champs, applied)
