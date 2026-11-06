"""The structured reading of a match for the reader (plan UX, A9; section 26 of the plan): six sections - summary, context,
data, market, risks and PrediGol's conclusion - each a list of facts the platform already states, as a stable code with its
parameters and a reference to where it comes from. The web writes every fact in the reader's language from its own templates
(Spanish and English); nothing here is prose.

No AI is called and nothing new is estimated. The facts are read from the newest match packet PrediGol Intelligence stored
(``ai.match_packets``, read only: the module that writes it and the rules narrative of Intelligence are neither touched nor
imported) and from the forecast as a reader may see it (``fbi.api.services.forecast``: a probability with its label, no odds,
no edge, no pick). A match without a packet gets a shorter reading that says so.

What never leaves this module: the models' own probabilities and edges, the Elo, prices and bookmakers, the text of a news item
or a rumour (only how many there are, by status) and any word that reads as advice. The conclusion is the likely outcome of
each market with its probability, labelled when it is the model's own number (uncalibrated) - never "sure", never "value".

Three sections are derived from these six and added after them by the route, through ``fbi.api.services.reading_value`` (plan de
cierre UX, 2.1): key points, why a published pick has value, and the factors that stand out. They are not added here - this module
is loaded by the readers' AI, which must not reach the user layer the picks board lives in - so they are not part of
``reading_hash`` either, and the narrative never reads them.

``FBI_READING_USERS`` (on since A9; ``=0`` hides it again without a deploy, ``fbi.api.switches``) decides whether readers
see it; the Admin Console's preview does not depend on it.

THE NARRATIVE (plan UX, A11). The same reading written as prose in Spanish and English by PrediGol's AI - in the worker, never
here (``fbi.narrative.job``: this module only reads ``ai.user_narratives``, with no model client and no key). A narrative is
attached only while it was written from THIS reading: the same packet and the same facts (``reading_hash``), so it can never
tell a reader something the facts beside it no longer say; otherwise, or while the owner keeps it off, the reader gets the
facts. ``FBI_USER_NARRATIVE``: off (default) | ``shadow`` (only the Admin Console's preview shows it: the owner reviews a sample
first) | ``on``.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Final, Literal

import structlog
from pydantic import ValidationError

from fbi.api.contracts.forecast import ForecastMarket
from fbi.api.contracts.reading import (
    MatchReading,
    NarrativeSection,
    NarrativeSource,
    ReadingFact,
    ReadingNarrative,
    ReadingSection,
)
from fbi.api.envelope import DataStatus, Envelope, ok, unavailable
from fbi.api.problem import ApiError
from fbi.api.repositories import Conn, fetch_all, fetch_one
from fbi.api.services import forecast as forecast_service
from fbi.api.switches import ON, user_switch
from fbi.core.clock import now
from fbi.core.env import environment

log = structlog.get_logger(__name__)

VERSION: Final = "reading-v1"
USERS_SWITCH: Final = "FBI_READING_USERS"
"""Every signed-in account sees the structured reading: on since plan UX A9, ``FBI_READING_USERS=0`` hides it again without a
deploy. The Admin Console's preview does not depend on it. The API needs a restart to read it."""

NARRATIVE_VERSION: Final = "user-narrative-v2"
"""The prompt and the checks of the narrative (``fbi.narrative.job``): a narrative of another version is not shown. v2 (UX-025) is
the chronicle - the lead, a paragraph for each side, the head-to-head and the risks - tied to the story of the match
(``fbi.api.services.story``), not to the newest packet."""
NARRATIVE_SWITCH: Final = "FBI_USER_NARRATIVE"
NarrativeMode = Literal["off", "shadow", "on"]

SectionKey = Literal["summary", "context", "data", "market", "risks", "conclusion"]
SECTIONS: Final[tuple[SectionKey, ...]] = ("summary", "context", "data", "market", "risks", "conclusion")
SIDES: Final = ("home", "away")
ZONES: Final = frozenset({"title", "europe", "relegation", "promotion"})
PRESSURES: Final = frozenset({"title", "europe", "relegation", "promotion", "settled", "playoff"})
NOT_FIT: Final = frozenset({"PRODUCT_ONLY", "INSUFFICIENT"})
"""The competition data classes PrediGol does not model: a reading of them is description only."""
CHECKABLE: Final = ("form", "h2h", "stats", "absences", "lineups", "market", "schedule", "standings", "dossier", "phase")
"""The packet's blocks a reader can be told were not checked (``missing``); any other name stays out."""
OUTCOMES: Final = {("1X2", "Home"): "home", ("1X2", "Draw"): "draw", ("1X2", "Away"): "away", ("OU", "Over"): "over",
                   ("OU", "Under"): "under", ("BTTS", "Yes"): "yes", ("BTTS", "No"): "no"}
MOVE_MIN: Final = 0.02
"""A market's move worth telling: two percentage points of implied probability or more since the opening."""
STREAK_MIN: Final = 4
NEXT_MATCH_DAYS: Final = 7.0
MAX_PLAYERS: Final = 3

Param = str | int | float | bool | list[str] | None
Params = dict[str, Param]


@dataclass(frozen=True)
class Fact:
    code: str
    params: Params
    ref: str


@dataclass
class Reading:
    sections: dict[SectionKey, list[Fact]] = field(default_factory=lambda: {k: [] for k in SECTIONS})

    def add(self, section: SectionKey, code: str, ref: str, **params: Param) -> None:
        self.sections[section].append(Fact(code, params, ref))


# ── small readers of a JSON block: never trust a shape, never invent a value ─────────────────────────────────────────

def _obj(x: Any) -> Mapping[str, Any]:
    return x if isinstance(x, Mapping) else {}


def _num(x: Any, places: int = 2) -> float | None:
    if isinstance(x, bool) or x is None:
        return None
    try:
        return round(float(x), places)
    except (TypeError, ValueError):
        return None


def _int(x: Any) -> int | None:
    if isinstance(x, bool) or x is None:
        return None
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def _team(content: Mapping[str, Any], side: str) -> str | None:
    name = _obj(_obj(content.get("fixture")).get(side)).get("name")
    return str(name) if name else None


def _outcome_team(content: Mapping[str, Any], outcome: str) -> str | None:
    return _team(content, outcome) if outcome in SIDES else None


# ── the forecast, as the reader may see it ─────────────────────────────────────────────────────────────────────────

def _likely(m: ForecastMarket) -> tuple[str, float] | None:
    best = next((o for o in m.outcomes if o.likely), None)
    if best is None:
        return None
    outcome = OUTCOMES.get((m.market, best.selection))
    p = _num(best.probability, 3)
    return (outcome, p) if outcome is not None and p is not None else None


def _line(m: ForecastMarket) -> str | None:
    return f"{float(m.line):g}" if m.market == "OU" else None


# ── the sections ──────────────────────────────────────────────────────────────────────────────────────────────────

def summary(r: Reading, content: Mapping[str, Any], markets: Sequence[ForecastMarket], forecast_code: str | None) -> None:
    fixture = _obj(content.get("fixture"))
    if fixture.get("competition"):
        r.add("summary", "match_intro", "packet:fixture", competition=str(fixture["competition"]),
              round=str(fixture["round"]) if fixture.get("round") else None,
              neutral=bool(fixture.get("neutral")) or None)
    ctx = _obj(_obj(content.get("dossier")).get("context"))
    kind = ("final" if ctx.get("final") else "second_leg" if ctx.get("second_leg") else
            "knockout" if ctx.get("knockout") else "derby" if ctx.get("derby") else
            "friendly" if ctx.get("friendly") else None)
    if kind is not None:
        r.add("summary", "match_kind", "packet:dossier.context", kind=kind)
    result = next((m for m in markets if m.market == "1X2"), None)
    likely = _likely(result) if result is not None else None
    if result is not None and likely is not None:
        outcome, p = likely
        r.add("summary", "expected_result", "forecast:1X2", outcome=outcome, team=_outcome_team(content, outcome),
              probability=p, calibrated=result.calibration == "CALIBRATED")
    elif forecast_code is not None:
        r.add("summary", "forecast_missing", "forecast", reason=forecast_code)


def context(r: Reading, content: Mapping[str, Any]) -> None:
    stakes = _obj(content.get("stakes"))
    for side in SIDES:
        s = _obj(stakes.get(side))
        team, ref = _team(content, side), f"packet:stakes.{side}"
        rank = _int(s.get("rank"))
        if s.get("zone") in ZONES:
            r.add("context", "stakes_zone", ref, side=side, team=team, rank=rank, zone=str(s["zone"]))
        if (gap := _int(s.get("gap_up"))) is not None and s.get("zone_above") in ZONES:
            r.add("context", "stakes_gap_up", ref, side=side, team=team, gap=gap, zone=str(s["zone_above"]))
        if (gap := _int(s.get("gap_down"))) is not None and s.get("zone_below") in ZONES:
            r.add("context", "stakes_gap_down", ref, side=side, team=team, gap=gap, zone=str(s["zone_below"]))
        if s.get("pressure") in PRESSURES:
            r.add("context", "stakes_pressure", ref, side=side, team=team, pressure=str(s["pressure"]))
    second = _obj(_obj(_obj(content.get("dossier")).get("context")).get("second_leg"))
    first_home, first_away = _int(second.get("first_leg_score_home_side")), _int(second.get("first_leg_score_away_side"))
    if first_home is not None and first_away is not None:
        r.add("context", "first_leg", "packet:dossier.context.second_leg", home_goals=first_home, away_goals=first_away)
    outlook = _obj(_obj(_obj(content.get("phase")).get("tie")).get("outlook"))
    ahead, level = (_int(outlook.get("home_side_ahead_if_home_margin_at_least")),
                    _int(outlook.get("level_if_home_margin_is")))
    if outlook.get("kind") == "second_leg" and ahead is not None and level is not None:
        r.add("context", "tie_outlook", "packet:phase.tie.outlook", ahead_from=ahead, level_at=level,
              home=_team(content, "home"), away=_team(content, "away"))
    table = _obj(_obj(content.get("scenarios")).get("table"))
    after = _obj(table.get("after"))
    if after and not table.get("unavailable"):
        for result in ("home_win", "draw", "away_win"):
            entry = _obj(after.get(result))
            h, a = _obj(entry.get("home")), _obj(entry.get("away"))
            hp, ap = _int(h.get("points")), _int(a.get("points"))
            if hp is None or ap is None:
                continue
            r.add("context", "table_after", "packet:scenarios.table", result=result,
                  home=_team(content, "home"), home_points=hp, home_best=_int(h.get("rank_best")),
                  home_worst=_int(h.get("rank_worst")),
                  away=_team(content, "away"), away_points=ap, away_best=_int(a.get("rank_best")),
                  away_worst=_int(a.get("rank_worst")))
    schedule = _obj(content.get("schedule"))
    complete = bool(_obj(schedule.get("calendar")).get("complete"))
    for side in SIDES:
        s = _obj(schedule.get(side))
        team, ref = _team(content, side), f"packet:schedule.{side}"
        rest = _num(s.get("rest_days"), 1)
        if rest is not None:
            r.add("context", "rest_days", ref, side=side, team=team, days=rest,
                  matches_14d=_int(s.get("matches_last_14d")), at_most=not complete)
        nxt = _obj(s.get("next_match"))
        days = _num(nxt.get("days_after"), 1)
        if days is not None and days <= NEXT_MATCH_DAYS:
            r.add("context", "next_match", f"{ref}.next_match", side=side, team=team, days=days,
                  competition=str(nxt["competition"]) if nxt.get("competition") else None)


def data(r: Reading, content: Mapping[str, Any]) -> None:
    form = _obj(content.get("form"))
    teams = _obj(_obj(content.get("dossier")).get("teams"))
    for side in SIDES:
        team = _team(content, side)
        f = _obj(form.get(side))
        n = _int(f.get("n"))
        if n and f.get("sequence"):
            r.add("data", "form", f"packet:form.{side}", side=side, team=team, sequence=str(f["sequence"])[-6:], n=n,
                  ppg=_num(f.get("ppg")), goals_for=_num(f.get("gf_pg")), goals_against=_num(f.get("ga_pg")))
        d = _obj(teams.get(side))
        venue = _obj(d.get(side))
        vn = _int(venue.get("n"))
        if vn:
            r.add("data", "venue_record", f"packet:dossier.teams.{side}", side=side, team=team, n=vn,
                  wins=_int(venue.get("wins")) or 0, draws=_int(venue.get("draws")) or 0,
                  losses=_int(venue.get("losses")) or 0)
        everything = _obj(d.get("all"))
        xg_for, xg_against = _num(everything.get("xg_for")), _num(everything.get("xg_against"))
        if xg_for is not None and xg_against is not None:
            r.add("data", "xg", f"packet:dossier.teams.{side}", side=side, team=team, xg_for=xg_for,
                  xg_against=xg_against, n=_int(everything.get("n_stats")))
        streaks = _obj(d.get("streaks"))
        if (unbeaten := _int(streaks.get("unbeaten")) or 0) >= STREAK_MIN:
            r.add("data", "streak_unbeaten", f"packet:dossier.teams.{side}", side=side, team=team, n=unbeaten)
        elif (winless := _int(streaks.get("winless")) or 0) >= STREAK_MIN:
            r.add("data", "streak_winless", f"packet:dossier.teams.{side}", side=side, team=team, n=winless)
    h2h = _obj(content.get("h2h"))
    record = _obj(h2h.get("record"))
    meetings = _int(record.get("n"))
    if meetings:
        r.add("data", "h2h", "packet:h2h", n=meetings, n_effective=_num(h2h.get("n_effective"), 1),
              home=_team(content, "home"), home_wins=_int(record.get("home_side_wins")) or 0,
              draws=_int(record.get("draws")) or 0, away=_team(content, "away"),
              away_wins=_int(record.get("away_side_wins")) or 0)
    players = _obj(_obj(content.get("dossier")).get("players"))
    absences = _obj(content.get("absences"))
    for side in SIDES:
        team = _team(content, side)
        top = next((p for p in players.get(side) or [] if isinstance(p, Mapping) and (_int(p.get("goals")) or 0) > 0),
                   None)
        if top is not None and top.get("name"):
            r.add("data", "top_scorer", f"packet:dossier.players.{side}", side=side, team=team, player=str(top["name"]),
                  goals=_int(top.get("goals")) or 0, minutes=_int(top.get("minutes")))
        listed = [p for p in _obj(absences.get(side)).get("players") or [] if isinstance(p, Mapping)]
        key = [str(p["name"]) for p in listed if p.get("key") and p.get("name")]
        if key:
            r.add("data", "key_absences", f"packet:absences.{side}", side=side, team=team, count=len(key),
                  players=key[:MAX_PLAYERS])


def market(r: Reading, content: Mapping[str, Any]) -> None:
    block = _obj(content.get("market"))
    selections = [s for s in block.get("selections") or [] if isinstance(s, Mapping)]
    if not block.get("observed") or not selections:
        r.add("market", "market_unpriced", "packet:market")
        return
    result = [(s, OUTCOMES.get(("1X2", str(s.get("selection"))))) for s in selections if s.get("market") == "1X2"]
    priced = [(s, o, p) for s, o in result if o is not None and (p := _num(s.get("p_fair"), 3)) is not None]
    if priced:
        s, outcome, p = max(priced, key=lambda x: x[2])
        r.add("market", "market_favourite", "packet:market.1X2", outcome=outcome, team=_outcome_team(content, outcome),
              probability=p, bookmakers=_int(s.get("n_bookmakers")))
        moves = [(o, opening, p) for s, o, p in priced
                 if (opening := _num(s.get("opening_p_fair"), 3)) is not None and abs(p - opening) >= MOVE_MIN]
        if moves:
            outcome, opening, now = max(moves, key=lambda x: abs(x[2] - x[1]))
            r.add("market", "market_moved", "packet:market.1X2", outcome=outcome, team=_outcome_team(content, outcome),
                  opening=opening, now=now)
    totals = [(s, o, p) for s in selections
              if s.get("market") == "OU" and _num(s.get("line"), 2) == 2.5
              and (o := OUTCOMES.get(("OU", str(s.get("selection"))))) is not None
              and (p := _num(s.get("p_fair"), 3)) is not None]
    if totals:
        _, outcome, p = max(totals, key=lambda x: x[2])
        r.add("market", "market_total", "packet:market.OU", outcome=outcome, line="2.5", probability=p)


def risks(r: Reading, content: Mapping[str, Any], missing: Sequence[str], markets: Sequence[ForecastMarket], *,
          packet: bool, pre_match: bool) -> None:
    if not packet:
        r.add("risks", "no_context_yet", "packet")
    else:
        if pre_match and not _obj(content.get("lineups")).get("confirmed"):
            r.add("risks", "lineups_unconfirmed", "packet:lineups")
        flags = [str(f) for f in _obj(content.get("schedule")).get("flags") or []]
        for side in SIDES:
            if f"{side}_short_rest" in flags:
                r.add("risks", "short_rest", "packet:schedule.flags", side=side, team=_team(content, side))
            if f"{side}_rest_disadvantage" in flags:
                r.add("risks", "rest_disadvantage", "packet:schedule.flags", side=side, team=_team(content, side))
        evidence = [e for e in content.get("evidence") or [] if isinstance(e, Mapping)]
        contradictory = sum(1 for e in evidence if e.get("status") == "CONTRADICTORY")
        rumours = sum(1 for e in evidence if e.get("status") == "RUMOR")
        if contradictory:
            r.add("risks", "contradictory_news", "packet:evidence", count=contradictory)
        if rumours:
            r.add("risks", "rumours", "packet:evidence", count=rumours)
        if not evidence:
            r.add("risks", "no_external_info", "packet:evidence")
        h2h = _obj(content.get("h2h"))
        meetings = _int(_obj(h2h.get("record")).get("n")) or _int(h2h.get("n")) or 0
        if meetings and h2h.get("relevance") in ("nula", "baja"):
            r.add("risks", "h2h_weak", "packet:h2h", n=meetings, n_effective=_num(h2h.get("n_effective"), 1))
        quality = _obj(_obj(content.get("quality")).get("competition_score")).get("class")
        if quality in NOT_FIT:
            r.add("risks", "data_not_fit", "packet:quality")
        unchecked: list[str] = [b for b in CHECKABLE if b in set(missing)]
        if unchecked:
            r.add("risks", "not_checked", "packet:missing", blocks=unchecked)
    uncalibrated: list[str] = [m.market for m in markets if m.calibration == "UNCALIBRATED"]
    if uncalibrated:
        r.add("risks", "uncalibrated", "forecast", markets=uncalibrated)
    if not r.sections["risks"]:
        # never empty (plan, section 26): when nothing stands out, say what the reading could not see
        r.add("risks", "none_found", "packet")


def conclusion(r: Reading, content: Mapping[str, Any], markets: Sequence[ForecastMarket], forecast_code: str | None) -> None:
    quality = _obj(_obj(content.get("quality")).get("competition_score")).get("class")
    if quality in NOT_FIT or forecast_code == "data_not_fit":
        r.add("conclusion", "description_only", "packet:quality")
    for m in markets:
        likely = _likely(m)
        if likely is None:
            continue
        outcome, p = likely
        r.add("conclusion", "likely", f"forecast:{m.market}", market=m.market, outcome=outcome,
              team=_outcome_team(content, outcome), line=_line(m), probability=p,
              calibrated=m.calibration == "CALIBRATED")
    if not markets and forecast_code not in (None, "data_not_fit", "hidden"):  # hidden by the owner: not "there is none"
        r.add("conclusion", "no_forecast", "forecast", reason=forecast_code)


def build(content: Mapping[str, Any], missing: Sequence[str], markets: Sequence[ForecastMarket], *,
          forecast_code: str | None, packet: bool, pre_match: bool) -> Reading:
    """The reading of one match from its packet's ``content`` (empty when there is no packet) and the forecast a reader may
    see. Pure: every fact is a value the inputs already hold."""
    r = Reading()
    summary(r, content, markets, forecast_code)
    if packet:
        context(r, content)
        data(r, content)
        market(r, content)
    risks(r, content, missing, markets, packet=packet, pre_match=pre_match)
    conclusion(r, content, markets, forecast_code)
    return r


def headline(content: Mapping[str, Any]) -> Fact | None:
    """One line of the reading for a list of matches (Home, plan section 24): what the match is about - a final, a second leg,
    a knockout, what a side is fighting for - or nothing when the packet says none of it."""
    r = Reading()
    summary(r, content, [], None)
    kind = next((f for f in r.sections["summary"] if f.code == "match_kind"), None)
    if kind is not None:
        return kind
    context(r, content)
    return next((f for f in r.sections["context"] if f.code == "stakes_pressure" and f.params.get("pressure") != "settled"),
                None)


GLANCE_CONTEXT: Final = ("stakes_pressure", "first_leg", "tie_outlook", "stakes_zone", "stakes_gap_up", "stakes_gap_down",
                         "rest_days", "next_match")
"""What Home's «Contexto» tells of a match (plan section 24, block 5: what is at stake - the table or the tie -, the rest and
the next match), in this order. The table after each result (three long lines) stays in the match's own reading."""


@dataclass(frozen=True)
class Glance:
    """A match in a list (Home): its one line and the facts of its context."""

    headline: Fact | None
    context: list[Fact]


def glance(content: Mapping[str, Any]) -> Glance:
    r = Reading()
    context(r, content)
    facts = sorted((f for f in r.sections["context"] if f.code in GLANCE_CONTEXT), key=lambda f: GLANCE_CONTEXT.index(f.code))
    return Glance(headline(content), facts)


# ── reading it from the database ──────────────────────────────────────────────────────────────────────────────────

FIXTURE_SQL = """
SELECT f.id, f.kickoff_at, f.status_group, f.home_team_id, f.away_team_id, th.name AS home_name, ta.name AS away_name,
       c.name AS competition
  FROM core.fixtures f
  JOIN core.teams th ON th.id = f.home_team_id
  JOIN core.teams ta ON ta.id = f.away_team_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE f.id = %(f)s
"""

PACKET_BLOCKS: Final = ("fixture", "phase", "stakes", "scenarios", "form", "schedule", "h2h", "absences", "lineups", "market",
                        "quality")
PACKET_SQL = (
    "SELECT p.id AS packet_id, p.as_of, p.missing, "
    + ", ".join(f"p.content->'{b}' AS {b}" for b in PACKET_BLOCKS)
    + """,
       jsonb_build_object('teams', p.content->'dossier'->'teams', 'players', p.content->'dossier'->'players',
                          'context', p.content->'dossier'->'context') AS dossier,
       CASE WHEN jsonb_typeof(p.content->'evidence') = 'array'
            THEN (SELECT coalesce(jsonb_agg(jsonb_build_object('status', e->'status', 'id', e->'id', 'kind', e->'kind',
                                                               'side', e->'side', 'origin', e->'origin',
                                                               'claim_md5', md5(e->>'claim'))), '[]'::jsonb)
                    FROM jsonb_array_elements(p.content->'evidence') e)
            ELSE '[]'::jsonb END AS evidence
  FROM ai.match_packets p
 WHERE p.fixture_id = %(f)s AND p.as_of <= %(at)s
 ORDER BY p.as_of DESC, p.id DESC LIMIT 1
""")
"""The newest packet of the match, only the blocks a reading uses: of the outside evidence, its status, its id, its kind, its
side, its origin and the md5 of its claim (what tells one item from another) and nothing else - no claim, no source, no link
reaches this process."""


def users_may_see() -> bool:
    return user_switch(USERS_SWITCH, default=True)


GLANCES_SQL = """
SELECT w.id AS fixture_id, p.fixture, p.stakes, p.phase, p.schedule, p.dossier
  FROM unnest(%(ids)s::bigint[]) AS w(id)
  CROSS JOIN LATERAL (
    SELECT p.content->'fixture' AS fixture, p.content->'stakes' AS stakes, p.content->'phase' AS phase,
           p.content->'schedule' AS schedule, jsonb_build_object('context', p.content->'dossier'->'context') AS dossier
      FROM ai.match_packets p
     WHERE p.fixture_id = w.id AND p.as_of <= %(at)s
     ORDER BY p.as_of DESC, p.id DESC
     LIMIT 1) p
"""
"""The newest packet of each match, one per match through its index (``fixture_id, as_of DESC, id DESC``): packets are kept
as they are rebuilt - about 50 per match in production on 26 Oct 2026, 29,713 (299 MB) for the 600 matches of Home's window -
and a DISTINCT ON over all of them took longer than the API's 10 s (UX A13's baseline)."""
GLANCE_BLOCKS: Final = ("fixture", "stakes", "phase", "schedule", "dossier")


def glances(conn: Conn, fixture_ids: list[int], *, at: datetime | None = None) -> dict[int, Glance]:
    """For a list of matches (Home): which have a reading with context (a key per match with a packet), its one line
    (``headline``; None when the packet says nothing that stands out) and its context. Empty while readers do not see the
    reading."""
    if not fixture_ids or not users_may_see():
        return {}
    return {int(r["fixture_id"]): glance({k: r[k] for k in GLANCE_BLOCKS if r.get(k) is not None})
            for r in fetch_all(conn, GLANCES_SQL, {"ids": fixture_ids, "at": at or now()})}


def _forecast(conn: Conn, fixture_id: int, at: datetime | None) -> tuple[list[ForecastMarket], str | None, datetime | None]:
    """The forecast as a reader may see it (never the preview): its markets, or why there are none, and when it was said."""
    env = forecast_service.match_forecast(conn, fixture_id, preview=False, at=at)
    if env.status is not DataStatus.OK or env.data is None:
        return [], "hidden", None
    section = env.data.forecast
    if section.status is not DataStatus.OK:
        return [], section.code or "no_forecast_yet", None
    return list(section.data), None, max((m.known_at for m in section.data), default=None)


def _sections(r: Reading) -> list[ReadingSection]:
    return [ReadingSection(key=k, facts=[ReadingFact(code=f.code, params=f.params, ref=f.ref) for f in r.sections[k]])
            for k in SECTIONS if r.sections[k]]


@dataclass(frozen=True)
class Basis:
    """A match's reading at a moment and what it was built from: the packet (its id, its moment, the blocks read) and the
    forecast a reader may see. The narrative is written from it (``fbi.ai.user_narrative``) and shown against it."""

    fixture: Mapping[str, Any]
    packet_id: int | None
    data_at: datetime | None
    forecast_at: datetime | None
    content: dict[str, Any]
    missing: list[str]
    sections: list[ReadingSection]

    @property
    def hash(self) -> str:
        return reading_hash(self.sections)


def reading_hash(sections: Sequence[ReadingSection]) -> str:
    """The identity of a reading's facts: the same codes, parameters and references in the same order give the same hash. A
    narrative carries the hash of the facts it was written from."""
    body = {"v": VERSION, "sections": [s.model_dump(mode="json") for s in sections]}
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                                     default=str).encode()).hexdigest()


def reading_basis(conn: Conn, fixture_id: int, *, at: datetime | None = None,
                  fixture: Mapping[str, Any] | None = None) -> Basis:
    """The reading of a match as a reader gets it at ``at`` (now by default), whatever the switches say; 404 for an unknown
    match. ``fixture``: its row of ``FIXTURE_SQL`` when the caller has read it already."""
    fixture = fixture if fixture is not None else fetch_one(conn, FIXTURE_SQL, {"f": fixture_id})
    if fixture is None:
        raise ApiError(404, "not_found", "no such fixture")
    moment = at or now()
    row = fetch_one(conn, PACKET_SQL, {"f": fixture_id, "at": moment})
    content: dict[str, Any] = {}
    missing: list[str] = []
    if row is not None:
        content = {b: row[b] for b in (*PACKET_BLOCKS, "dossier", "evidence") if row.get(b) is not None}
        missing = [str(m) for m in row.get("missing") or []]
    # the names a reader knows, even without a packet
    fx = dict(_obj(content.get("fixture")))
    fx.setdefault("competition", fixture["competition"])
    fx.setdefault("home", {"name": fixture["home_name"]})
    fx.setdefault("away", {"name": fixture["away_name"]})
    content["fixture"] = fx
    markets, code, forecast_at = _forecast(conn, fixture_id, at)
    reading = build(content, missing, markets, forecast_code=code, packet=row is not None,
                    pre_match=fixture["status_group"] == "scheduled")
    return Basis(fixture=fixture, packet_id=None if row is None else int(row["packet_id"]),
                 data_at=None if row is None else row["as_of"], forecast_at=forecast_at, content=content, missing=missing,
                 sections=_sections(reading))


def narrative_mode() -> NarrativeMode:
    """``FBI_USER_NARRATIVE``: ``on`` (or 1, true, yes) - readers see the narrative; ``shadow`` - the job writes it and only the
    Admin Console's preview shows it; anything else, the line absent included - off."""
    raw = (environment().get(NARRATIVE_SWITCH) or "").strip().lower()
    if raw == "shadow":
        return "shadow"
    return "on" if raw in ON else "off"


NARRATIVE_SQL = """
SELECT id, created_at, data_at, version, content FROM ai.user_narratives
 WHERE fixture_id = %(f)s AND status = 'ok' AND version = %(version)s AND reading_hash = %(hash)s
 ORDER BY created_at DESC, id DESC LIMIT 1
"""
"""The newest chronicle written from THIS story: ``reading_hash`` holds the hash of the story it was written from
(``fbi.api.services.story``), whatever packet it was written from - the data of a match are rebuilt every few minutes and the
story is not."""


def story_hash(conn: Conn, basis: Basis) -> str | None:
    """The identity of the story the newest packet tells now, or None while there is no packet or the match has no story to tell
    (a side without its last results). Lazy: the story module reads this one."""
    from fbi.api.services import story

    if basis.packet_id is None or basis.data_at is None:
        return None
    told = story.story_of(conn, content=basis.content, home_id=int(basis.fixture["home_team_id"]),
                          away_id=int(basis.fixture["away_team_id"]), kickoff=basis.fixture["kickoff_at"],
                          data_at=basis.data_at)
    return None if told.thin or not told.caps else told.hash


def narrative_for(conn: Conn, basis: Basis, *, preview: bool) -> ReadingNarrative | None:
    """The validated chronicle of this very story, when the reader may see it: readers only with the switch ``on``, the Admin
    Console's preview whenever one exists. A stored narrative that does not read as the contract says is not shown (logged). It
    is shown only while the story it was written from is the story the data tell now - a new absence, a new result or a new
    piece of news makes the reader keep the facts until it is written again."""
    if basis.packet_id is None or not (preview or narrative_mode() == "on"):
        return None
    told = story_hash(conn, basis)
    if told is None:
        return None
    row = fetch_one(conn, NARRATIVE_SQL, {"f": int(basis.fixture["id"]), "version": NARRATIVE_VERSION, "hash": told})
    if row is None:
        return None
    content = row["content"] if isinstance(row["content"], Mapping) else {}
    try:
        return ReadingNarrative(
            version=str(row["version"]), written_at=row["created_at"], data_at=row["data_at"],
            es=[NarrativeSection.model_validate(x) for x in content.get("es") or []],
            en=[NarrativeSection.model_validate(x) for x in content.get("en") or []],
            sources=[NarrativeSource.model_validate(x) for x in content.get("sources") or []])
    except ValidationError as exc:
        log.error("reading.narrative_unreadable", narrative_id=row["id"], errors=len(exc.errors()))
        return None


def match_reading(conn: Conn, fixture_id: int, *, preview: bool, at: datetime | None = None
                  ) -> Envelope[MatchReading | None]:
    fixture = fetch_one(conn, FIXTURE_SQL, {"f": fixture_id})
    if fixture is None:
        raise ApiError(404, "not_found", "no such fixture")
    if not preview and not users_may_see():
        return unavailable(None, "The structured reading is not shown to users yet.")
    basis = reading_basis(conn, fixture_id, at=at, fixture=fixture)
    body = MatchReading(fixture_id=int(basis.fixture["id"]), version=VERSION, complete=basis.packet_id is not None,
                        data_at=basis.data_at, forecast_at=basis.forecast_at, sections=basis.sections,
                        narrative=narrative_for(conn, basis, preview=preview))
    newest = max((t for t in (basis.data_at, basis.forecast_at) if t is not None), default=None)
    return ok(body, data_as_of=newest)
