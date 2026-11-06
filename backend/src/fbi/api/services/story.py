"""THE STORY OF A MATCH (plan de cierre UX, UX-025, «la crónica»): the facts a match's chronicle is written from, and the
identity that says whether a chronicle written earlier still tells what the data say.

A chronicle is short, flowing prose - the lead, one paragraph for each side, the head-to-head and what could go wrong - told with
the facts PrediGol holds: who is out and why, the last results with their score, the run a side is on, the table, the meetings
between the two, the verified news. The words are written by the readers' AI in the worker (``fbi.narrative.job``); this module
holds what is shared with the API and is pure but for one read of the past results:

* ``story_facts``  the facts, from the packet PrediGol Intelligence stored (read only), the results settled by its moment and the
                   news keys. A fact is a code with its parameters and a reference - the model may tell nothing else.
* ``Story.caps``   how much each paragraph may say, from the facts it has (a side with a named absence, a streak and a news
                   item may take five sentences; one with only its results, two): the length follows the information, never
                   the competition's name, and nothing is invented to fill the space.
* ``Story.hash``   the identity of what the chronicle says. The data of a match are rebuilt every ten or twenty minutes (the
                   market and the forecast move all day), so a chronicle tied to the newest packet would vanish the moment it was
                   written; it is tied to THIS hash instead - the facts above, which only change when something about the story
                   does (a result, an absence, a piece of news). The market, the prices, the forecast and the line-ups are not
                   in it: the reader sees them beside the chronicle, from their own templates, never from the AI.

What never gets here: the models' probabilities, an edge, a price, a pick, the Elo, a reader. The chronicle does not know of a pick
(its «por qué hay valor» is the reading's own section, written from templates).
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from fbi.api.repositories import Conn, fetch_all
from fbi.api.services import reading as reading_service

STORY_VERSION: Final = "story-v1"
SIDES: Final = ("home", "away")
SECTIONS: Final = ("summary", "home", "away", "h2h", "risks")
"""What a chronicle has, in this order: the lead, one paragraph for each side, the head-to-head and the risks."""

READING_CODES: Final = frozenset({
    "match_intro", "match_kind", "first_leg", "tie_outlook", "stakes_zone", "stakes_gap_up", "stakes_gap_down",
    "stakes_pressure", "form", "venue_record", "xg", "streak_unbeaten", "streak_winless", "top_scorer", "key_absences", "h2h"})
"""The facts of the structured reading a chronicle may tell: the ones that only change when something happens to the story. Not the
market, the forecast, the rest in days (it drifts with the clock), the line-ups or the table after each result."""

RESULTS_PER_SIDE: Final = 5
ABSENCES_PER_SIDE: Final = 4
MEETINGS: Final = 3
MIN_RESULTS: Final = 2
"""A chronicle needs the last results of both sides: with fewer than two each, the match has no story to tell and the reader
keeps the structured reading."""
NEWS_STATUSES: Final = ("CONFIRMED", "PROBABLE", "CONTRADICTORY", "RUMOR")
TOLD_AS_NEWS: Final = ("CONFIRMED", "PROBABLE")
"""The news that make a paragraph richer: a rumour or a contradiction is told among the risks only."""
LEAD_CAP: Final = 2
RISKS_CAP: Final = 3
H2H_CAP: Final = 2
SIDE_BASE: Final = 2
SIDE_MAX: Final = 5

RESULTS_SQL: Final = """
SELECT f.id, f.kickoff_at, f.home_team_id, th.name AS home_name, ta.name AS away_name, r.reg_goals_home, r.reg_goals_away,
       c.name AS competition
  FROM core.fixtures f
  JOIN core.fixture_results r ON r.fixture_id = f.id
  JOIN core.teams th ON th.id = f.home_team_id
  JOIN core.teams ta ON ta.id = f.away_team_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE (f.home_team_id = %(team)s OR f.away_team_id = %(team)s) AND f.kickoff_at < %(kickoff)s
   AND f.kickoff_at >= %(kickoff)s - interval '400 days'
   AND r.settled_at <= %(at)s AND r.reg_goals_home IS NOT NULL AND r.reg_goals_away IS NOT NULL
 ORDER BY f.kickoff_at DESC
 LIMIT %(limit)s
"""
"""A side's last results settled by the packet's moment, in 90 minutes (the packet's own cut: ``fbi.ai.packet.PAST_SQL``), with
the opponent and the competition. Regular time: a tie decided in extra time or on penalties shows its score after 90 minutes."""


@dataclass(frozen=True)
class Fact:
    """One thing the chronicle may tell: a code, its parameters and where it comes from (``P:<block>``)."""

    ref: str
    section: str
    code: str
    params: Mapping[str, Any]


@dataclass(frozen=True)
class Result:
    side: str
    team: str
    opponent: str
    venue: str
    goals_for: int
    goals_against: int
    competition: str


@dataclass(frozen=True)
class NewsKey:
    """What identifies a news item without its words: the API never sees a claim, only this."""

    id: int
    status: str
    kind: str
    side: str | None
    claim_md5: str


@dataclass(frozen=True)
class Story:
    facts: tuple[Fact, ...]
    caps: Mapping[str, int]
    """The sections to write and the most sentences each may have, from the facts it has. Empty: no story to tell."""
    richness: Mapping[str, int]
    news: tuple[NewsKey, ...]
    thin: bool
    """The match lacks the last results of a side: nothing is written."""

    @property
    def hash(self) -> str:
        body = {"v": STORY_VERSION,
                "facts": [[f.ref, f.section, f.code, dict(f.params)] for f in self.facts],
                "news": sorted([n.id, n.status, n.claim_md5] for n in self.news),
                "caps": dict(self.caps)}
        return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, default=str,
                                         separators=(",", ":")).encode()).hexdigest()


# ── small readers of a JSON block: never trust a shape, never invent a value ─────────────────────────────────────────

def _obj(x: Any) -> Mapping[str, Any]:
    return x if isinstance(x, Mapping) else {}


def _int(x: Any) -> int | None:
    if isinstance(x, bool) or x is None:
        return None
    try:
        return int(x)
    except (TypeError, ValueError):
        return None


def claim_md5(claim: str) -> str:
    return hashlib.md5(claim.encode(), usedforsecurity=False).hexdigest()


def news_keys(evidence: Any) -> tuple[NewsKey, ...]:
    """The web news of a packet's evidence the chronicle can tell (by status), as keys. ``evidence`` items carry either the
    claim (the worker reads the whole packet) or its md5 (the API's projection)."""
    out = []
    for e in evidence if isinstance(evidence, list) else []:
        if not isinstance(e, Mapping) or e.get("origin") != "web" or e.get("status") not in NEWS_STATUSES:
            continue
        ident = _int(e.get("id"))
        digest = e.get("claim_md5") or (claim_md5(str(e["claim"])) if e.get("claim") else None)
        if ident is None or not digest:
            continue
        out.append(NewsKey(ident, str(e["status"]), str(e.get("kind") or "other"),
                           e.get("side") if e.get("side") in SIDES else None, str(digest)))
    return tuple(sorted(out, key=lambda k: k.id))


# ── the facts ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def _ref(ref: str) -> str:
    kind, _, path = ref.partition(":")
    if kind == "forecast":
        return "P:forecast" + (f".{path}" if path else "")
    return "P:" + (path or "packet")


def _section_of(code: str, params: Mapping[str, Any]) -> str:
    if code == "h2h":
        return "h2h"
    side = params.get("side")
    return str(side) if side in SIDES else "summary"


def reading_facts(content: Mapping[str, Any]) -> list[Fact]:
    """The facts of the structured reading the chronicle may tell, in the reading's own order, with the counts the model cannot
    compute (a form's wins, draws and losses) and without the weights of the head-to-head."""
    built = reading_service.build(content, [], [], forecast_code=None, packet=True, pre_match=True)
    out: list[Fact] = []
    for section in reading_service.SECTIONS:
        if section not in ("summary", "context", "data"):
            continue
        for f in built.sections[section]:
            if f.code not in READING_CODES:
                continue
            params: dict[str, Any] = {k: v for k, v in f.params.items() if k != "n_effective"}
            if f.code == "form" and isinstance(params.get("sequence"), str):
                seq = str(params["sequence"])
                params |= {"wins": seq.count("W"), "draws": seq.count("D"), "losses": seq.count("L")}
            out.append(Fact(_ref(f.ref), _section_of(f.code, params), f.code, params))
    return out


def _reason_kind(reason: str) -> str:
    low = reason.lower()
    if any(w in low for w in ("injur", "knock", "strain", "sprain", "fracture", "ligament", "tendon")):
        return "injury"
    if any(w in low for w in ("card", "suspend", "ban")):
        return "suspension"
    if any(w in low for w in ("ill", "health", "virus", "flu", "covid")):
        return "illness"
    if "fitness" in low or "rest" in low:
        return "fitness"
    return "other"


def absence_facts(content: Mapping[str, Any]) -> list[Fact]:
    """Each side's named absences (the heaviest first): the player, whether he is out or in doubt and the provider's reason, short
    and stripped of anything but letters - the provider's words are data, never instructions."""
    block = _obj(content.get("absences"))
    fixture = _obj(content.get("fixture"))
    out: list[Fact] = []
    for side in SIDES:
        team = _obj(fixture.get(side)).get("name")
        listed = [p for p in _obj(block.get(side)).get("players") or [] if isinstance(p, Mapping) and p.get("name")]
        for i, p in enumerate(listed[:ABSENCES_PER_SIDE], start=1):
            reason = re.sub(r"[^A-Za-z .'-]", "", str(p.get("reason") or "")).strip()[:40]
            doubtful = str(p.get("type") or "").startswith("Quest")
            out.append(Fact(f"P:absences.{side}.{i}", side, "absence", {
                "side": side, "team": str(team) if team else None, "player": str(p["name"]),
                "status": "doubtful" if doubtful else "out", "reason": reason or None,
                "kind": _reason_kind(reason) if reason else "other", "key": bool(p.get("key"))}))
    return out


def meeting_facts(content: Mapping[str, Any]) -> list[Fact]:
    """The last meetings between the two with their score, newest first, from the head-to-head block of the packet."""
    h2h = _obj(content.get("h2h"))
    fixture = _obj(content.get("fixture"))
    home, away = _obj(fixture.get("home")).get("name"), _obj(fixture.get("away")).get("name")
    out: list[Fact] = []
    for i, m in enumerate([x for x in h2h.get("meetings") or [] if isinstance(x, Mapping)][:MEETINGS], start=1):
        gh, ga, days = _int(m.get("goals_home_side")), _int(m.get("goals_away_side")), _int(m.get("days_ago"))
        if gh is None or ga is None or days is None or not home or not away:
            continue
        out.append(Fact(f"P:h2h.meeting.{i}", "h2h", "h2h_meeting", {
            "home": str(home), "away": str(away), "goals_home": gh, "goals_away": ga,
            "winner": "home" if gh > ga else "away" if ga > gh else "draw",
            "home_was": m.get("home_side_was") if m.get("home_side_was") in SIDES else None,
            "months_ago": round(days / 30.4), "competition": str(m["competition"]) if m.get("competition") else None,
            "after_extra_time": bool(m.get("after_extra_time")) or None}))
    return out


def recent_results(conn: Conn, *, home_id: int, away_id: int, kickoff: datetime, at: datetime) -> list[Result]:
    """Each side's last results settled by ``at``, newest first."""
    out: list[Result] = []
    for side, team in (("home", home_id), ("away", away_id)):
        for r in fetch_all(conn, RESULTS_SQL, {"team": team, "kickoff": kickoff, "at": at, "limit": RESULTS_PER_SIDE}):
            at_home = int(r["home_team_id"]) == team
            gf, ga = (int(r["reg_goals_home"]), int(r["reg_goals_away"]))
            gf, ga = (gf, ga) if at_home else (ga, gf)
            out.append(Result(side, str(r["home_name"] if at_home else r["away_name"]),
                              str(r["away_name"] if at_home else r["home_name"]), "home" if at_home else "away", gf, ga,
                              str(r["competition"])))
    return out


def result_facts(results: Sequence[Result]) -> list[Fact]:
    out: list[Fact] = []
    seen = {"home": 0, "away": 0}
    for r in results:
        seen[r.side] += 1
        out.append(Fact(f"P:results.{r.side}.{seen[r.side]}", r.side, "result", {
            "side": r.side, "team": r.team, "opponent": r.opponent, "venue": r.venue, "goals_for": r.goals_for,
            "goals_against": r.goals_against, "outcome": "W" if r.goals_for > r.goals_against else
            "D" if r.goals_for == r.goals_against else "L", "competition": r.competition, "order": seen[r.side]}))
    return out


# ── how much there is to say ──────────────────────────────────────────────────────────────────────────────────────────

def _richness(side: str, facts: Sequence[Fact], news: Sequence[NewsKey]) -> int:
    """How many different things are known of a side beyond its results: a named absence (two at most), a streak, what it plays
    for, its top scorer, its record at the venue, its expected goals, a verified piece of news (two at most)."""
    mine = [f for f in facts if f.section == side]
    codes = {f.code for f in mine}
    stakes = any(f.code in ("stakes_zone", "stakes_gap_up", "stakes_gap_down")
                 or (f.code == "stakes_pressure" and f.params.get("pressure") != "settled") for f in mine)
    venue = any(f.code == "venue_record" and (_int(f.params.get("n")) or 0) >= 3 for f in mine)
    told = sum(1 for n in news if n.side == side and n.status in TOLD_AS_NEWS)
    points = (min(2, sum(1 for f in mine if f.code == "absence")) + min(2, told) + (1 if codes & {"streak_unbeaten",
              "streak_winless"} else 0) + (1 if stakes else 0) + (1 if "top_scorer" in codes else 0) + (1 if venue else 0)
              + (1 if "xg" in codes else 0))
    return points


def _risky(facts: Sequence[Fact], news: Sequence[NewsKey]) -> bool:
    """Whether the facts give something to say about what could go wrong: an absence, a side without a win in a while, or news
    that is a rumour, a contradiction or only probable."""
    return (any(f.code in ("absence", "streak_winless") for f in facts)
            or any(n.status in ("RUMOR", "CONTRADICTORY", "PROBABLE") for n in news))


def story_facts(content: Mapping[str, Any], results: Sequence[Result], news: Sequence[NewsKey]) -> Story:
    """The story of a match from its packet's blocks, the results settled by its moment and its news keys. Pure."""
    facts = [*reading_facts(content), *result_facts(results), *absence_facts(content), *meeting_facts(content)]
    have = {s: sum(1 for r in results if r.side == s) for s in SIDES}
    thin = any(have[s] < MIN_RESULTS for s in SIDES)
    richness = {s: _richness(s, facts, news) for s in SIDES}
    caps: dict[str, int] = {}
    if not thin:
        caps["summary"] = LEAD_CAP
        for s in SIDES:
            caps[s] = SIDE_BASE + min(SIDE_MAX - SIDE_BASE, richness[s])
        if any(f.code == "h2h_meeting" for f in facts):
            caps["h2h"] = H2H_CAP
        if _risky(facts, news):
            caps["risks"] = RISKS_CAP
    order = {s: i for i, s in enumerate(SECTIONS)}
    ordered = {s: caps[s] for s in sorted(caps, key=lambda k: order[k])}
    return Story(tuple(facts), ordered, richness, tuple(news), thin)


# ── the API's side: the identity of the story as it stands now ────────────────────────────────────────────────────────

def story_of(conn: Conn, *, content: Mapping[str, Any], home_id: int, away_id: int, kickoff: datetime,
             data_at: datetime) -> Story:
    """The story of a match as its newest packet (``content``, the blocks the reading reads) and the results settled by that
    packet's moment tell it - the same function the worker writes from, so the hash a chronicle was stored with is the hash it is
    compared against."""
    results = recent_results(conn, home_id=home_id, away_id=away_id, kickoff=kickoff, at=data_at)
    return story_facts(content, results, news_keys(content.get("evidence")))
