"""Standings truth: the provider's table against ours, against the table the fixtures imply.

For one competition season three tables are compared row by row (team x group):

* **API** - ``/standings?league&season`` now (a new RAW payload);
* **DB** - our newest snapshot (``core.standings`` at ``max(snapshot_at)``), which is exactly
  what the product shows (``COMPETITION_TABLE``) when the season is the one it picks;
* **FIX** - recomputed here from our finished fixtures and their scores, for the phase the
  provider's group describes (3 points a win, 1 a draw).

Who is wrong is read from how the three agree:

=====================  ==========================================================  ==========
API = DB, FIX ahead    the provider's table misses a match our fixtures have ended  provider
API ahead of DB        the provider moved on, our snapshot did not                  PrediGol
API = DB = FIX         correct                                                      -
API = DB, FIX behind   our fixtures lack a result the provider's table counts       PrediGol
same games, pts differ a deduction or a corrected result - checked against the      ?
                       official table
=====================  ==========================================================  ==========

The provider updates tables hourly (``/standings`` docs, "Update Frequency"). A finished match
not in its table within ``PROVIDER_GRACE`` of its end is PROVIDER_STALE; within it, it is
expected lag (reported, not an issue).
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.truth.v2.ledger import Evidence

MATCH_LENGTH = timedelta(hours=2)
PROVIDER_GRACE = timedelta(hours=3)
"""Kick-off + 2 h (the match is over) + the provider's hourly update + slack."""
FIELDS = ("played", "win", "draw", "lose", "gf", "ga", "points")
KNOCKOUT = re.compile(r"final|play-?offs?|knockout|round of|quarter|semi|8th|16th|1/\d|qualifying|qualification|preliminary|"
                      r"promotion|relegation (?:play|deciding)|third place|super cup|repechage|elimination",
                      re.IGNORECASE)


@dataclass(frozen=True)
class Line:
    """Played, won, drawn, lost, goals for and against, points - one side of a table row."""

    played: int | None
    win: int | None
    draw: int | None
    lose: int | None
    gf: int | None
    ga: int | None
    points: int | None = None

    def get(self, name: str) -> int | None:
        return getattr(self, name)  # type: ignore[no-any-return]


@dataclass(frozen=True)
class Row:
    team: int
    name: str
    group: str | None
    rank: int | None
    total: Line
    gd: int | None = None
    form: str | None = None
    description: str | None = None
    update: datetime | None = None
    home: Line | None = None
    away: Line | None = None
    payload_hash: str | None = None


def _int(v: Any) -> int | None:
    if v is None or isinstance(v, bool):
        return None
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _d(v: Any) -> dict[str, Any]:
    return v if isinstance(v, dict) else {}


def _when(v: Any) -> datetime | None:
    if isinstance(v, datetime):
        return v
    if isinstance(v, str) and v:
        try:
            return datetime.fromisoformat(v.replace("Z", "+00:00"))
        except ValueError:
            return None
    return None


def _line(block: Any, points: Any = None) -> Line:
    b = _d(block)
    goals = _d(b.get("goals"))
    return Line(_int(b.get("played")), _int(b.get("win")), _int(b.get("draw")), _int(b.get("lose")),
                _int(goals.get("for")), _int(goals.get("against")), _int(points))


def api_rows(body: Mapping[str, Any]) -> list[Row]:
    """Every row of every table in a /standings answer."""
    out: list[Row] = []
    response = body.get("response")
    for entry in response if isinstance(response, list) else []:
        league = _d(_d(entry).get("league"))
        tables = league.get("standings")
        for table in tables if isinstance(tables, list) else []:
            for r in table if isinstance(table, list) else []:
                if not isinstance(r, dict):
                    continue
                team = _d(r.get("team"))
                tid = _int(team.get("id"))
                if tid is None:
                    continue
                out.append(Row(team=tid, name=str(team.get("name") or tid), group=_text(r.get("group")),
                               rank=_int(r.get("rank")), total=_line(r.get("all"), r.get("points")),
                               gd=_int(r.get("goalsDiff")), form=_text(r.get("form")),
                               description=_text(r.get("description")), update=_when(r.get("update")),
                               home=_line(r.get("home")), away=_line(r.get("away"))))
    return out


def _text(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


# ── our side ────────────────────────────────────────────────────────────────

SEASON_SQL = """
SELECT cs.id AS cs_id, c.id AS competition_id, c.provider_league_id, c.name, c.type, c.country, cs.season,
       cs.is_current, c.is_tracked,
       (SELECT max(s.snapshot_at) FROM core.standings s WHERE s.competition_season_id = cs.id) AS snapshot_at,
       (SELECT k.checked_at FROM core.context_checks k WHERE k.competition_season_id = cs.id
           AND k.dataset = 'standings') AS checked_at,
       (SELECT k.changed_at FROM core.context_checks k WHERE k.competition_season_id = cs.id
           AND k.dataset = 'standings') AS changed_at,
       (SELECT max(f.kickoff_at) FROM core.fixtures f WHERE f.competition_season_id = cs.id
           AND f.status_group = 'finished') AS last_finished,
       (SELECT cs2.season FROM core.competition_seasons cs2 WHERE cs2.competition_id = c.id
           AND EXISTS (SELECT 1 FROM core.standings s2 WHERE s2.competition_season_id = cs2.id)
         ORDER BY cs2.season DESC LIMIT 1) AS product_season
  FROM core.competition_seasons cs JOIN core.competitions c ON c.id = cs.competition_id
"""

SNAPSHOT_SQL = """
SELECT t.provider_team_id, t.name, s.* FROM core.standings s JOIN core.teams t ON t.id = s.team_id
 WHERE s.competition_season_id = %(cs)s
   AND s.snapshot_at = (SELECT max(snapshot_at) FROM core.standings WHERE competition_season_id = %(cs)s)
"""

FINISHED_SQL = """
SELECT f.provider_fixture_id, f.kickoff_at, f.round, f.status_short, th.provider_team_id AS home,
       ta.provider_team_id AS away, r.goals_home, r.goals_away, r.et_goals_home, r.et_goals_away
  FROM core.fixtures f
  JOIN core.teams th ON th.id = f.home_team_id
  JOIN core.teams ta ON ta.id = f.away_team_id
  JOIN core.fixture_results r ON r.fixture_id = f.id
 WHERE f.competition_season_id = %(cs)s AND f.status_group = 'finished'
   AND r.goals_home IS NOT NULL AND r.goals_away IS NOT NULL
"""


def season_facts(conn: psycopg.Connection[Any], where: str, params: Mapping[str, Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(SEASON_SQL + " WHERE " + where + " ORDER BY c.provider_league_id, cs.season", params)
        return [dict(r) for r in cur.fetchall()]


def _db_line(r: Mapping[str, Any], prefix: str = "") -> Line:
    if prefix:
        return Line(_int(r.get(f"{prefix}_played")), _int(r.get(f"{prefix}_wins")), _int(r.get(f"{prefix}_draws")),
                    _int(r.get(f"{prefix}_losses")), _int(r.get(f"{prefix}_goals_for")),
                    _int(r.get(f"{prefix}_goals_against")))
    return Line(_int(r.get("played")), _int(r.get("wins")), _int(r.get("draws")), _int(r.get("losses")),
                _int(r.get("goals_for")), _int(r.get("goals_against")), _int(r.get("points")))


def db_rows(conn: psycopg.Connection[Any], cs_id: int) -> list[Row]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(SNAPSHOT_SQL, {"cs": cs_id})
        rows = cur.fetchall()
    return [Row(team=int(r["provider_team_id"]), name=str(r["name"]), group=_text(r.get("group")),
                rank=_int(r.get("rank")), total=_db_line(r), gd=_int(r.get("goals_diff")), form=_text(r.get("form")),
                description=_text(r.get("description")), update=r.get("provider_updated_at"),
                home=_db_line(r, "home") if r.get("home_played") is not None else None,
                away=_db_line(r, "away") if r.get("away_played") is not None else None,
                payload_hash=r.get("payload_hash")) for r in rows]


@dataclass(frozen=True)
class Played:
    fixture: int
    kickoff: datetime
    round: str
    home: int
    away: int
    gh: int
    ga: int


def finished(conn: psycopg.Connection[Any], cs_id: int) -> list[Played]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(FINISHED_SQL, {"cs": cs_id})
        rows = cur.fetchall()
    out = []
    for r in rows:
        gh, ga = int(r["goals_home"]), int(r["goals_away"])
        out.append(Played(int(r["provider_fixture_id"]), r["kickoff_at"], str(r["round"] or ""), int(r["home"]),
                          int(r["away"]), gh, ga))
    return out


AWARDED_SQL = """
SELECT th.provider_team_id AS home, ta.provider_team_id AS away
  FROM core.fixtures f JOIN core.teams th ON th.id = f.home_team_id JOIN core.teams ta ON ta.id = f.away_team_id
 WHERE f.competition_season_id = %(cs)s AND f.status_short IN ('AWD', 'WO')
"""


def awarded(conn: psycopg.Connection[Any], cs_id: int) -> list[tuple[int, int]]:
    """(home, away) of the season's matches decided off the pitch (technical loss, walkover): a table
    counts them, our match data has no on-field score for them."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(AWARDED_SQL, {"cs": cs_id})
        return [(int(r["home"]), int(r["away"])) for r in cur.fetchall()]


# ── the table the fixtures imply ───────────────────────────────────────────


def tally(matches: Iterable[Played]) -> dict[int, Line]:
    acc: dict[int, list[int]] = {}
    for m in matches:
        for team, gf, ga in ((m.home, m.gh, m.ga), (m.away, m.ga, m.gh)):
            a = acc.setdefault(team, [0, 0, 0, 0, 0, 0])
            a[0] += 1
            a[1 if gf > ga else 2 if gf == ga else 3] += 1
            a[4] += gf
            a[5] += ga
    return {t: Line(a[0], a[1], a[2], a[3], a[4], a[5], 3 * a[1] + a[2]) for t, a in acc.items()}


def _fold(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s.lower()) if not unicodedata.combining(c))


def phase_of(round_label: str) -> str:
    return round_label.split(" - ")[0].strip()


@dataclass
class Recompute:
    by_team: dict[int, Line]
    phase: str
    agree: int
    rows: int
    single_phase: bool = False
    """Only one phase was played among these teams: the fixtures ARE the table, whatever the
    provider's counts say (a provider behind on a whole match day disagrees on every row)."""

    @property
    def usable(self) -> bool:
        return self.rows > 0 and (self.single_phase or self.agree * 2 >= self.rows)


def recompute_group(rows: Sequence[Row], matches: Sequence[Played], *, tables: int = 1) -> Recompute:
    """The table the fixtures imply for the teams of one provider table.

    Candidates, each with and without the phase filter (the part of the round label before
    " - ", e.g. "Apertura", "League Stage"): the non-knockout matches between two of the table's
    teams ("within": groups, a split season), and those with at least one of its teams ("any":
    a conference, whose teams also meet the other conference). The candidate whose games-played
    agree with the provider's on the most rows wins; a phase named in the group label, then
    "within", wins ties.

    When the season has ONE table and its matches ONE phase, the fixtures are the table whatever
    the provider says (``single_phase``): a provider behind on a whole match day disagrees on
    every row and must still be caught. Otherwise the phase is only trusted when at least half
    of the rows agree (period tables, cumulative tables and play-off groups are left unjudged).
    """
    teams = {r.team for r in rows}
    league = [m for m in matches if not KNOCKOUT.search(m.round)]
    within = [m for m in league if m.home in teams and m.away in teams]
    anywhere = [m for m in league if m.home in teams or m.away in teams]
    group_label = _fold(" ".join(r.group or "" for r in rows[:1]))
    phases = sorted({phase_of(m.round) for m in within})
    zero = Line(0, 0, 0, 0, 0, 0, 0)

    def agree(table: dict[int, Line]) -> int:
        return sum(1 for r in rows if (table.get(r.team) or zero).played == r.total.played)

    if tables == 1 and len(phases) <= 1:
        table = tally(within)
        return Recompute(table, phases[0] if phases else "none", agree(table), len(rows), single_phase=bool(phases))
    candidates: list[tuple[str, bool, list[Played]]] = []
    for scope, subset in (("within", within), ("any", anywhere)):
        candidates.append((f"all non-knockout ({scope})", False, subset))
        for phase in sorted({phase_of(m.round) for m in subset}):
            candidates.append((f"{phase} ({scope})", _fold(phase) in group_label,
                               [m for m in subset if phase_of(m.round) == phase]))
    best: tuple[int, bool, Recompute] | None = None
    for name, named, subset in candidates:
        table = tally(subset)
        cand = Recompute(table, name, agree(table), len(rows))
        if best is None or cand.agree > best[0] or (cand.agree == best[0] and named and not best[1]):
            best = (cand.agree, named, cand)
    assert best is not None
    return best[2]


# ── comparison ─────────────────────────────────────────────────────────────


def diff(a: Line, b: Line) -> dict[str, tuple[int | None, int | None]]:
    return {f: (a.get(f), b.get(f)) for f in FIELDS if a.get(f) != b.get(f)}


@dataclass
class RowVerdict:
    team: int
    name: str
    group: str | None
    verdict: str
    """ok | predigol_behind | provider_behind | fixtures_missing | adjusted | awarded | provider_identity |
    db_ahead | missing_in_db | provider_inconsistent"""
    api: dict[str, int | None]
    db: dict[str, int | None] | None
    fix: dict[str, int | None] | None
    notes: list[str] = field(default_factory=list)


def _as(line: Line | None) -> dict[str, int | None] | None:
    return None if line is None else {f: line.get(f) for f in FIELDS}


def judge_row(api: Row, db: Row | None, fix: Line | None) -> RowVerdict:
    """Who is wrong for one team's row (see the module table)."""
    v = RowVerdict(api.team, api.name, api.group, "ok", _as(api.total) or {}, _as(db.total) if db else None,
                   _as(fix))
    if db is None:
        v.verdict = "missing_in_db"
        return v
    a, d = api.total, db.total
    api_db = diff(a, d)
    if api_db:
        if (a.played or 0) > (d.played or 0):
            v.verdict = "predigol_behind"
        elif (a.played or 0) < (d.played or 0):
            v.verdict = "db_ahead"
        else:
            v.verdict = "predigol_behind"  # same games, the provider corrected something since our snapshot
            v.notes.append("same games played; " + ", ".join(f"{k} {x}->{y}" for k, (x, y) in api_db.items()))
        return v
    if fix is None:
        return v
    api_fix = diff(a, fix)
    if not api_fix:
        if api.rank is not None and db.rank is not None and api.rank != db.rank:
            v.verdict = "predigol_behind"
            v.notes.append(f"rank {api.rank} vs ours {db.rank}")
        return v
    if (fix.played or 0) > (a.played or 0):
        v.verdict = "provider_behind"
    elif (fix.played or 0) < (a.played or 0):
        v.verdict = "fixtures_missing"
    elif set(api_fix) == {"points"}:
        v.verdict = "adjusted"
        v.notes.append(f"points {a.points} vs {fix.points} from the results: a deduction or an award")
    else:
        v.verdict = "provider_inconsistent"
        v.notes.append(", ".join(f"{k} {x} vs fixtures {y}" for k, (x, y) in api_fix.items()))
    return v


@dataclass
class SeasonAudit:
    league: int
    name: str
    season: int
    type: str
    cs_id: int | None
    api_rows: int = 0
    db_rows: int = 0
    api_groups: list[str] = field(default_factory=list)
    db_groups: list[str] = field(default_factory=list)
    api_update: datetime | None = None
    snapshot_at: datetime | None = None
    checked_at: datetime | None = None
    last_finished: datetime | None = None
    product_season: int | None = None
    in_refresh_scope: bool = False
    recompute: dict[str, str] = field(default_factory=dict)
    rows: list[RowVerdict] = field(default_factory=list)
    extra_db_teams: list[int] = field(default_factory=list)
    legacy_snapshot: bool = False
    """Our newest snapshot has no payload hash: written before migration 0048 by the writer that kept
    one row per team (a team's second table - Apertura/Clausura, a third-place ranking - dropped)."""
    payload_hash: str | None = None
    fetched_at: datetime | None = None
    verdict: str = "ok"
    notes: list[str] = field(default_factory=list)

    def counts(self) -> dict[str, int]:
        return dict(Counter(r.verdict for r in self.rows))

    def summary(self) -> dict[str, Any]:
        return {"league": self.league, "name": self.name, "season": self.season, "type": self.type,
                "verdict": self.verdict, "rows": self.counts(), "api_rows": self.api_rows, "db_rows": self.db_rows,
                "api_groups": self.api_groups, "db_groups": self.db_groups, "api_update": self.api_update,
                "snapshot_at": self.snapshot_at, "checked_at": self.checked_at, "last_finished": self.last_finished,
                "product_season": self.product_season, "in_refresh_scope": self.in_refresh_scope,
                "recompute": self.recompute, "extra_db_teams": self.extra_db_teams, "notes": self.notes,
                "legacy_snapshot": self.legacy_snapshot,
                "payload_hash": self.payload_hash}


def audit_season(facts: Mapping[str, Any], body: Mapping[str, Any] | None, db: Sequence[Row],
                 matches: Sequence[Played], *, at: datetime, payload_hash: str | None = None,
                 fetched_at: datetime | None = None,
                 awarded_pairs: Sequence[tuple[int, int]] = ()) -> SeasonAudit:
    """Compare one competition season's three tables and give the season its verdict."""
    s = SeasonAudit(int(facts["provider_league_id"]), str(facts["name"]), int(facts["season"]), str(facts["type"]),
                    facts.get("cs_id"), payload_hash=payload_hash, fetched_at=fetched_at)
    s.snapshot_at, s.checked_at = facts.get("snapshot_at"), facts.get("checked_at")
    s.last_finished, s.product_season = facts.get("last_finished"), facts.get("product_season")
    s.in_refresh_scope = bool(facts.get("is_tracked") and facts.get("is_current") and facts.get("type") == "league")
    api = api_rows(body or {})
    s.api_rows, s.db_rows = len(api), len(db)
    s.legacy_snapshot = bool(db) and all(r.payload_hash is None for r in db)
    s.api_groups = sorted({r.group or "" for r in api})
    s.db_groups = sorted({r.group or "" for r in db})
    updates = [r.update for r in api if r.update]
    s.api_update = max(updates) if updates else None
    if body is None:
        s.verdict = "not_asked"
        return s
    if not api:
        s.verdict = "no_api_table" if db else "no_table"
        return s
    by_group: dict[str | None, list[Row]] = {}
    for r in api:
        by_group.setdefault(r.group, []).append(r)
    db_by_key = {(r.team, r.group): r for r in db}
    db_by_team: dict[int, list[Row]] = {}
    for r in db:
        db_by_team.setdefault(r.team, []).append(r)
    for group, rows in by_group.items():
        rec = recompute_group(rows, matches, tables=len(by_group)) if matches else None
        if rec is not None:
            s.recompute[group or ""] = f"{rec.phase}: {rec.agree}/{rec.rows} rows agree on games played"
        for r in rows:
            mine = db_by_key.get((r.team, r.group))
            if mine is None and len(db_by_team.get(r.team, [])) == 1 and sum(1 for x in api if x.team == r.team) == 1:
                mine = db_by_team[r.team][0]
            fix = rec.by_team.get(r.team, Line(0, 0, 0, 0, 0, 0, 0)) if rec is not None and rec.usable else None
            s.rows.append(judge_row(r, mine, fix))
    api_teams = {r.team for r in api}
    s.extra_db_teams = sorted({r.team for r in db} - api_teams)
    explain_missing_games(s, api, matches, awarded_pairs)
    s.verdict = season_verdict(s, at=at)
    return s


def explain_missing_games(s: SeasonAudit, api: Sequence[Row], matches: Sequence[Played],
                          awarded_pairs: Sequence[tuple[int, int]]) -> None:
    """A table row with more games than our finished fixtures is not always a missing fixture:

    * ``awarded`` - the difference is exactly the team's matches decided off the pitch (AWD/WO): the
      table counts them, our match data rightly holds no on-field score;
    * ``provider_identity`` - our fixtures never name this team, but a team absent from every table played
      exactly its games: the provider's table and its fixtures use two different team ids for one club.
    """
    by_api = {r.team: r for r in api}
    table_teams = set(by_api)
    league = [m for m in matches if not KNOCKOUT.search(m.round)]
    orphan_games: dict[int, int] = {}
    for m in league:
        for t in (m.home, m.away):
            if t not in table_teams:
                orphan_games[t] = orphan_games.get(t, 0) + 1
    for v in s.rows:
        if v.verdict != "fixtures_missing" or v.fix is None:
            continue
        missing = int(v.api.get("played") or 0) - int(v.fix.get("played") or 0)
        off_pitch = sum(1 for h, a in awarded_pairs if v.team in (h, a))
        if missing > 0 and off_pitch == missing:
            v.verdict = "awarded"
            v.notes.append(f"{off_pitch} match(es) decided off the pitch (AWD/WO) counted by the table")
            continue
        if not v.fix.get("played"):
            twins = [t for t, n in orphan_games.items() if n == int(v.api.get("played") or 0)]
            if twins:
                v.verdict = "provider_identity"
                v.notes.append(f"the provider's table names team {v.team}; its fixtures name team(s) {twins} "
                               "for the same games")


def season_verdict(s: SeasonAudit, *, at: datetime) -> str:
    c = s.counts()
    if not s.db_rows:
        return "missing_in_db"
    if s.extra_db_teams:
        s.notes.append(f"{len(s.extra_db_teams)} team(s) in our table are not in the provider's: season or group mixed")
    if c.get("predigol_behind") or c.get("db_ahead") or c.get("missing_in_db"):
        return "predigol_behind" if c.get("predigol_behind") else "mismatch"
    if c.get("provider_behind"):
        if s.last_finished and at - (s.last_finished + MATCH_LENGTH) < PROVIDER_GRACE:
            s.notes.append("the provider has not yet counted a match that ended under 3 h ago (hourly update)")
            return "provider_lag_expected"
        return "provider_stale"
    if c.get("fixtures_missing"):
        return "fixtures_missing"
    if c.get("provider_identity"):
        return "provider_identity"
    if c.get("provider_inconsistent"):
        return "provider_inconsistent"
    if c.get("adjusted") or c.get("awarded"):
        return "adjusted"
    if s.extra_db_teams:
        return "mismatch"
    return "ok"


# ── evidence ───────────────────────────────────────────────────────────────

ROOT_LEGACY = ("NORMALIZER_BUG fixed 4 Oct 06:46 UTC (migration 0048): the old writer keyed a table row by team "
               "without its group, so a team's second table of the same season (Apertura/Clausura/annual, a "
               "third-place ranking) was dropped - this snapshot was written by it")

ROOT_SCOPE = ("our refresh reads tables only for tracked, current, league-type seasons "
              "(context_refresh: c.type = 'league'); this competition is a cup with a table "
              "(league phase / groups), so its table is never refreshed after the first load")


def evidence(s: SeasonAudit, api_ref: Mapping[str, Any] | None) -> list[Evidence]:
    """The ledger entries one season audit establishes (one per issue, rows summarised)."""
    out: list[Evidence] = []
    key = f"standings:{s.league}:{s.season}"
    label = f"{s.name} {s.season} ({s.league})"
    bad = [r for r in s.rows if r.verdict not in ("ok",)]
    examples = [{"team": r.team, "name": r.name, "group": r.group, "verdict": r.verdict, "api": r.api, "db": r.db,
                 "fixtures": r.fix, "notes": r.notes} for r in bad[:5]]
    db_ev = {"snapshot_at": s.snapshot_at, "last_checked": s.checked_at, "rows": s.db_rows, "groups": s.db_groups,
             "last_finished_kickoff": s.last_finished, "product_season": s.product_season,
             "in_refresh_scope": s.in_refresh_scope}
    api_ev = {**(dict(api_ref) if api_ref else {}), "rows": s.api_rows, "groups": s.api_groups,
              "provider_update": s.api_update}
    counts = s.counts()
    if s.verdict in ("predigol_behind", "mismatch", "missing_in_db"):
        if not s.in_refresh_scope and s.type == "cup":
            cause = ROOT_SCOPE
        elif s.legacy_snapshot and counts.get("missing_in_db"):
            cause = (ROOT_LEGACY + ("" if s.checked_at else "; the season has not been re-read since the fix "
                                    "(no core.context_checks row)"))
        else:
            cause = ("our newest snapshot predates the provider's update: the due-refresh did not re-read this "
                     "table after the provider changed it (see core.context_checks)")
        out.append(Evidence(
            key=f"{key}:predigol_behind", area="standings", issue_type="STANDINGS_MISMATCH", severity="high",
            at_fault="predigol", entity=label,
            claim=f"{label}: our table is behind the provider's - {counts.get('predigol_behind', 0)} rows behind, "
                  f"{counts.get('missing_in_db', 0)} missing, {counts.get('db_ahead', 0)} ahead",
            api={**api_ev, "examples": examples}, db=db_ev, root_cause=cause,
            fix="refresh tables for every tracked current season whose coverage has standings (cups included), "
                "hourly while matches end; product labels a table older than its last finished match as stale"))
    if s.verdict == "provider_stale":
        out.append(Evidence(
            key=f"{key}:provider_stale", area="standings", issue_type="PROVIDER_STALE", severity="medium",
            at_fault="provider", entity=label,
            claim=f"{label}: the provider's table does not count {counts.get('provider_behind', 0)} team-matches "
                  f"our fixtures have finished (last finished kick-off {s.last_finished})",
            api={**api_ev, "examples": examples}, db=db_ev,
            root_cause="provider table lags its own fixtures beyond its hourly update",
            fix="show the table with its provider update time and a 'pending results' note; never call it current"))
    if s.verdict == "fixtures_missing":
        out.append(Evidence(
            key=f"{key}:fixtures_missing", area="standings", issue_type="MISSING_BACKFILL", severity="high",
            at_fault="predigol", entity=label,
            claim=f"{label}: the provider's table counts games our finished fixtures do not have "
                  f"({counts.get('fixtures_missing', 0)} rows)",
            api={**api_ev, "examples": examples}, db=db_ev,
            root_cause="finished fixtures or their results missing in core.fixtures / core.fixture_results",
            fix="re-sync the season's fixtures (full season list) from the provider"))
    if counts.get("provider_identity"):
        ids = [r for r in s.rows if r.verdict == "provider_identity"]
        out.append(Evidence(
            key=f"{key}:provider_identity", area="standings", issue_type="IDENTITY_MAPPING_ERROR", severity="medium",
            at_fault="provider", entity=label,
            claim=f"{label}: the provider's table and its own fixtures name different teams for the same games "
                  f"({'; '.join(n for r in ids for n in r.notes)})",
            api={**api_ev, "examples": examples}, db=db_ev,
            root_cause="provider identity: /standings and /fixtures disagree on the team id",
            fix="report to the provider; keep both ids, never merge them silently; the product shows the fixtures' "
                "team and marks the table row"))
    if s.verdict == "provider_inconsistent":
        out.append(Evidence(
            key=f"{key}:provider_inconsistent", area="standings", issue_type="STANDINGS_MISMATCH", severity="medium",
            at_fault="undetermined", entity=label,
            claim=f"{label}: same games played, but goals or results differ between the provider's table and the "
                  f"fixtures ({counts.get('provider_inconsistent', 0)} rows)",
            api={**api_ev, "examples": examples}, db=db_ev,
            root_cause="a result differs between /standings and /fixtures, or the table uses another phase"))
    if s.verdict == "adjusted":
        out.append(Evidence(
            key=f"{key}:adjusted", area="standings", issue_type="STANDINGS_MISMATCH", severity="low",
            at_fault="none", entity=label,
            claim=f"{label}: points differ from the results for {counts.get('adjusted', 0)} team(s) - a deduction "
                  "or an award; to confirm with the official table",
            api={**api_ev, "examples": examples}, db=db_ev, status="MONITOR"))
    if s.extra_db_teams:
        out.append(Evidence(
            key=f"{key}:extra_teams", area="standings", issue_type="SEASON_MISMATCH", severity="high",
            at_fault="predigol", entity=label,
            claim=f"{label}: {len(s.extra_db_teams)} team(s) in our newest table are not in the provider's",
            api=api_ev, db={**db_ev, "extra_teams": s.extra_db_teams}))
    if s.product_season is not None and s.product_season != s.season and s.api_rows:
        out.append(Evidence(
            key=f"{key}:product_season", area="standings", issue_type="WRONG_SEASON", severity="high",
            at_fault="predigol", entity=label,
            claim=f"{label}: the product shows the {s.product_season} table while the current season "
                  f"{s.season} has one at the provider",
            api=api_ev, db=db_ev,
            root_cause="COMPETITION_TABLE picks the newest season WITH stored standings; the current season's "
                       "table was never stored"))
    return out
