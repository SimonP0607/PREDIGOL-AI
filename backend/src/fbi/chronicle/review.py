"""What a match's chronicle said, against what the match showed (``chronicle-review-v1``, IA-022).

The chronicle (``ai.user_narratives``, written before the match by ``fbi.narrative.job``) tells the reader a match in sentences, each with
the references of the facts it rests on. After the match this module takes the newest chronicle a reader could have seen before the
kick-off and judges, reference by reference, what the match can say about it:

* an **absence or a doubt** (``P:absences.<side>.<n>``) against who played: a player the chronicle said was out and then played
  *contradicted* it; one who did not play *held*; one who was in doubt is told by whether he played or not;
* a **news item** (``E:<id>``) about a player (an injury, a suspension, a doubt) is judged the same way, by the player's provider id;
* everything else the chronicle tells - the form, the last results, the head-to-head, the stakes - is history or context: it describes the
  match, it does not anticipate anything a result can refute, and it is recorded as *not evaluable*, not as a hit.

What it does not do: it states no cause (a chronicle that "held" did not make the match go any way), it calls no model, it spends nothing,
it changes no model, no threshold and no pick, and it never invents: a name the line-ups cannot place is *not checkable*, a match without
line-ups or minutes is *pending* (the run tries again later; nothing is written until the data is there).

The facts a reference points to are read again from the packet the chronicle was written from (``ai.match_packets``, which never
changes), with the same functions the chronicle was written with (``fbi.api.services.story``), so a reference means what it meant to the
reader. The selections of the match are listed beside the review as the post-mortems judged them (``intel.postmortems``): the review
puts the two side by side and links none to the other.

Append-only (``ai.chronicle_reviews``, one row per chronicle and version). Nothing of Intelligence reads it.
"""

from __future__ import annotations

import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fbi.api.services import story as story_service
from fbi.observability.trace import match_trace_id

VERSION: Final = "chronicle-review-v1"
SETTLE: Final = timedelta(hours=26)
"""A match is reviewed this long after its kick-off: the line-ups and the minutes are in, and so are the post-mortems of its selections."""
LOOKBACK: Final = timedelta(days=7)
LIMIT: Final = 200

# the verdict of one reference
HELD: Final = "held"
CONTRADICTED: Final = "contradicted"
PLAYED: Final = "played"
DID_NOT_PLAY: Final = "did_not_play"
PENDING: Final = "pending"
NOT_CHECKABLE: Final = "not_checkable"
NOT_EVALUABLE: Final = "not_evaluable"
VERDICTS: Final = (CONTRADICTED, HELD, PLAYED, DID_NOT_PLAY, PENDING, NOT_CHECKABLE, NOT_EVALUABLE)
"""In the order a sentence takes its verdict from its references: the first that any of them has."""

PLAYER_KINDS: Final = frozenset({"injury", "suspension", "doubtful"})
"""The kinds of news item about whether a player will play."""

DUE_SQL: Final = """
SELECT n.id AS narrative_id, n.fixture_id, n.version AS narrative_version, n.packet_id, n.created_at, n.content,
       f.kickoff_at, f.home_team_id, f.away_team_id
  FROM (SELECT DISTINCT ON (x.fixture_id) x.id, x.fixture_id, x.version, x.packet_id, x.created_at, x.content
          FROM ai.user_narratives x JOIN core.fixtures g ON g.id = x.fixture_id
         WHERE x.status = 'ok' AND x.created_at < g.kickoff_at AND g.status_group = 'finished'
           AND g.kickoff_at >= %(since)s AND g.kickoff_at <= %(until)s
         ORDER BY x.fixture_id, x.created_at DESC, x.id DESC) n
  JOIN core.fixtures f ON f.id = n.fixture_id
 WHERE NOT EXISTS (SELECT 1 FROM ai.chronicle_reviews r WHERE r.narrative_id = n.id AND r.version = %(version)s)
 ORDER BY f.kickoff_at
 LIMIT %(limit)s
"""
"""The newest chronicle each finished match had before its kick-off, when it has not been reviewed under this version."""

RESULT_SQL: Final = """
SELECT reg_goals_home, reg_goals_away FROM core.fixture_results WHERE fixture_id = %(fixture)s
"""

PACKET_SQL: Final = """
SELECT content->'fixture' AS fixture, content->'absences' AS absences FROM ai.match_packets WHERE id = %(packet)s
"""

LINEUP_SQL: Final = """
SELECT team_side, provider_player_id, player_name, is_starter FROM core.fixture_lineup_players WHERE fixture_id = %(fixture)s
"""

STATS_SQL: Final = """
SELECT team_side, provider_player_id, player_name, minutes FROM core.fixture_player_stats WHERE fixture_id = %(fixture)s
"""

EVIDENCE_SQL: Final = """
SELECT id, kind, status, team_id, provider_player_id, attributes->>'player_name' AS player_name
  FROM ai.evidence WHERE id = ANY(%(ids)s)
"""

PICKS_SQL: Final = """
SELECT DISTINCT ON (pm.market_key, pm.selection, pm.line) pm.decision_id, pm.version, pm.market_key, pm.selection, pm.line::text AS line,
       pm.outcome, pm.decision_quality, pm.verdict
  FROM intel.postmortems pm
 WHERE pm.fixture_id = %(fixture)s AND pm.market_key IS NOT NULL
 ORDER BY pm.market_key, pm.selection, pm.line, pm.created_at DESC, pm.id DESC
"""

INSERT_SQL: Final = """
INSERT INTO ai.chronicle_reviews (fixture_id, narrative_id, version, created_at, narrative_version, packet_id, trace_id, status,
                                  outcome, items, summary, picks)
VALUES (%(fixture)s, %(narrative)s, %(version)s, %(at)s, %(narrative_version)s, %(packet)s, %(trace)s, %(status)s,
        %(outcome)s, %(items)s, %(summary)s, %(picks)s)
ON CONFLICT (narrative_id, version) DO NOTHING
RETURNING id
"""


# ── who played ───────────────────────────────────────────────────────────────────────────────────────────────────

def fold(name: str) -> str:
    """A name as the line-ups and the chronicle can both write it: no accents, no case, no punctuation, single spaces."""
    plain = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", " ", plain.casefold()).strip()


@dataclass(frozen=True)
class Participant:
    side: str
    provider_id: int
    name: str
    starter: bool | None
    minutes: int | None


@dataclass(frozen=True)
class Squad:
    """Who the match's line-ups and minutes say took part, and whether there is anything to judge by."""

    people: tuple[Participant, ...]
    have_lineups: bool
    have_minutes: bool

    @property
    def ready(self) -> bool:
        return self.have_lineups or self.have_minutes

    def by_id(self, provider_id: int) -> Participant | None:
        return next((p for p in self.people if p.provider_id == provider_id), None)

    def by_name(self, side: str, name: str) -> tuple[Participant, ...] | None:
        """The people of ``side`` called ``name``; None when the name is not placed (nobody has it in full)."""
        wanted = fold(name)
        if not wanted:
            return None
        found = tuple(p for p in self.people if p.side == side and fold(p.name) == wanted)
        return found or None

    def resembles(self, side: str, name: str) -> bool:
        """Somebody of ``side`` has a word of ``name`` in his own name (a surname, a nickname): the name may be spelled differently."""
        words = {w for w in fold(name).split() if len(w) >= 4}
        return any(words & set(fold(p.name).split()) for p in self.people if p.side == side)


def squad_of(lineups: Iterable[Mapping[str, Any]], stats: Iterable[Mapping[str, Any]]) -> Squad:
    """Merges the line-ups (who started, who was on the bench) with the minutes (who played), by provider id."""
    people: dict[int, Participant] = {}
    have_lineups = have_minutes = False
    for row in lineups:
        have_lineups = True
        pid = int(row["provider_player_id"])
        people[pid] = Participant(str(row["team_side"]), pid, str(row.get("player_name") or ""), bool(row["is_starter"]), None)
    for row in stats:
        have_minutes = True
        pid = int(row["provider_player_id"])
        before = people.get(pid)
        minutes = None if row.get("minutes") is None else int(row["minutes"])
        people[pid] = Participant(str(row["team_side"]), pid, str(row.get("player_name") or (before.name if before else "")),
                                  before.starter if before else None, minutes)
    return Squad(tuple(people.values()), have_lineups, have_minutes)


def played(p: Participant, squad: Squad) -> bool | None:
    """Did he play? His minutes when the match has them; otherwise whether he started; None when a bench player's minutes are unknown."""
    if squad.have_minutes:
        return (p.minutes or 0) > 0
    if p.starter:
        return True
    return None


# ── one reference ────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class Check:
    ref: str
    code: str
    verdict: str
    detail: str | None = None

    def as_json(self) -> dict[str, Any]:
        return {"ref": self.ref, "code": self.code, "verdict": self.verdict, "detail": self.detail}


def judge_player(ref: str, code: str, *, said: str, participants: tuple[Participant, ...] | None, squad: Squad) -> Check:
    """What the match says of a player the chronicle said was out (``said='out'``) or in doubt (``said='doubtful'``), once he is placed."""
    if not squad.ready:
        return Check(ref, code, PENDING, "the match has neither line-ups nor minutes yet")
    if not participants:
        return Check(ref, code, NOT_CHECKABLE, "the player is not in the line-ups under that name")
    verdicts = {played(p, squad) for p in participants}
    if verdicts == {None}:
        return Check(ref, code, NOT_CHECKABLE, "on the bench, with no minutes recorded")
    took_part = True in verdicts
    detail = "played" if took_part else "did not play"
    if said == "out":
        return Check(ref, code, CONTRADICTED if took_part else HELD, detail)
    return Check(ref, code, PLAYED if took_part else DID_NOT_PLAY, detail)


def absent_from_squad(ref: str, code: str, *, said: str, squad: Squad, similar: bool) -> Check:
    """A player the chronicle named who is in neither list. Only a complete squad (line-ups and minutes) and a name nobody resembles can say
    he took no part: a player the squad spells differently would look the same."""
    if not squad.ready:
        return Check(ref, code, PENDING, "the match has neither line-ups nor minutes yet")
    if not (squad.have_lineups and squad.have_minutes):
        return Check(ref, code, NOT_CHECKABLE, "the match has only one of the line-ups and the minutes")
    if similar:
        return Check(ref, code, NOT_CHECKABLE, "no one has that name in full, but a similar name is in the squad")
    return Check(ref, code, HELD if said == "out" else DID_NOT_PLAY, "in neither the line-ups nor the minutes")


def side_of(team_id: int | None, home: int, away: int) -> str | None:
    if team_id is None:
        return None
    return "home" if team_id == home else "away" if team_id == away else None


def checks_of(refs: Sequence[str], *, absences: Mapping[str, story_service.Fact], evidence: Mapping[int, Mapping[str, Any]],
              squad: Squad, home: int, away: int) -> list[Check]:
    out: list[Check] = []
    for ref in refs:
        if ref.startswith("P:absences."):
            fact = absences.get(ref)
            if fact is None:
                out.append(Check(ref, "absence", NOT_CHECKABLE, "the packet has no such absence"))
                continue
            said = str(fact.params.get("status") or "out")
            side, name = str(fact.params.get("side")), str(fact.params.get("player") or "")
            participants = squad.by_name(side, name)
            out.append(judge_player(ref, "absence", said=said, participants=participants, squad=squad) if participants
                       else absent_from_squad(ref, "absence", said=said, squad=squad, similar=squad.resembles(side, name)))
        elif ref.startswith("E:"):
            try:
                item = evidence.get(int(ref[2:]))
            except ValueError:
                item = None
            if item is None:
                out.append(Check(ref, "news", NOT_CHECKABLE, "the news item is not in the evidence"))
            elif str(item["kind"]) not in PLAYER_KINDS or item["provider_player_id"] is None:
                out.append(Check(ref, "news", NOT_EVALUABLE, f"{item['kind']}: not about whether a named player plays"))
            else:
                participant = squad.by_id(int(item["provider_player_id"]))
                said = "doubtful" if str(item["kind"]) == "doubtful" else "out"
                if participant is None:
                    out.append(absent_from_squad(ref, "news", said=said, squad=squad, similar=False))
                else:
                    out.append(judge_player(ref, "news", said=said, participants=(participant,), squad=squad))
        else:
            out.append(Check(ref, "context", NOT_EVALUABLE, "history or context: it describes the match, it anticipates nothing"))
    return out


def verdict_of(checks: Sequence[Check]) -> str:
    present = {c.verdict for c in checks}
    return next((v for v in VERDICTS if v in present), NOT_EVALUABLE)


# ── one chronicle ────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass
class Review:
    fixture_id: int
    narrative_id: int
    narrative_version: str
    packet_id: int
    status: str
    outcome: dict[str, Any]
    items: list[dict[str, Any]]
    summary: dict[str, Any]
    picks: list[dict[str, Any]] = field(default_factory=list)


def summarise(items: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    sentences = Counter(str(i["verdict"]) for i in items)
    references = Counter(str(c["verdict"]) for i in items for c in i["checks"])
    firm = references[HELD] + references[CONTRADICTED]
    return {"sentences": len(items), "by_sentence": dict(sentences), "by_reference": dict(references),
            "firm_claims": firm, "held": references[HELD], "contradicted": references[CONTRADICTED],
            "note": "counts of what could be checked; a claim that held did not cause the result, and most of a chronicle is history"}


def review_items(content: Mapping[str, Any], *, absences: Mapping[str, story_service.Fact], evidence: Mapping[int, Mapping[str, Any]],
                 squad: Squad, home: int, away: int) -> list[dict[str, Any]]:
    """The sentences of the Spanish chronicle (the English one says the same, sentence by sentence) with each reference judged."""
    items: list[dict[str, Any]] = []
    for section in content.get("es") or []:
        for index, sentence in enumerate(section.get("sentences") or []):
            refs = [str(r) for r in sentence.get("refs") or []]
            checks = checks_of(refs, absences=absences, evidence=evidence, squad=squad, home=home, away=away)
            items.append({"section": section.get("key"), "index": index, "text": sentence.get("text"), "refs": refs,
                          "verdict": verdict_of(checks), "checks": [c.as_json() for c in checks]})
    return items


def rows_of(conn: psycopg.Connection[Any], sql: str, params: Mapping[str, Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return list(cur.fetchall())


def news_ids(content: Mapping[str, Any]) -> list[int]:
    ids: set[int] = set()
    for section in content.get("es") or []:
        for sentence in section.get("sentences") or []:
            for ref in sentence.get("refs") or []:
                if isinstance(ref, str) and ref.startswith("E:") and ref[2:].isdigit():
                    ids.add(int(ref[2:]))
    return sorted(ids)


def review_one(conn: psycopg.Connection[Any], due: Mapping[str, Any]) -> Review | None:
    """The review of one chronicle, or None while the match has nothing to judge it by (no line-ups and no minutes yet)."""
    fixture = int(due["fixture_id"])
    result = rows_of(conn, RESULT_SQL, {"fixture": fixture})
    if not result or result[0]["reg_goals_home"] is None or result[0]["reg_goals_away"] is None:
        return None
    squad = squad_of(rows_of(conn, LINEUP_SQL, {"fixture": fixture}), rows_of(conn, STATS_SQL, {"fixture": fixture}))
    if not squad.ready:
        return None
    content: Mapping[str, Any] = due["content"]
    packet = rows_of(conn, PACKET_SQL, {"packet": int(due["packet_id"])})
    absences: dict[str, story_service.Fact] = {}
    status = "facts_unavailable"
    if packet:
        block = {"fixture": packet[0]["fixture"] or {}, "absences": packet[0]["absences"] or {}}
        absences = {f.ref: f for f in story_service.absence_facts(block)}
        status = "reviewed"
    evidence = {int(r["id"]): r for r in rows_of(conn, EVIDENCE_SQL, {"ids": news_ids(content)})}
    items = review_items(content, absences=absences, evidence=evidence, squad=squad, home=int(due["home_team_id"]),
                         away=int(due["away_team_id"]))
    picks = [{"decision_id": int(r["decision_id"]), "postmortem_version": r["version"], "market": r["market_key"],
              "selection": r["selection"], "line": r["line"], "outcome": r["outcome"], "decision_quality": r["decision_quality"],
              "verdict": r["verdict"]} for r in rows_of(conn, PICKS_SQL, {"fixture": fixture})]
    return Review(fixture, int(due["narrative_id"]), str(due["narrative_version"]), int(due["packet_id"]), status,
                  {"home_goals": int(result[0]["reg_goals_home"]), "away_goals": int(result[0]["reg_goals_away"]),
                   "players_with_minutes": sum(1 for p in squad.people if (p.minutes or 0) > 0), "line_ups": squad.have_lineups,
                   "minutes": squad.have_minutes},
                  items, summarise(items), picks)


def store(conn: psycopg.Connection[Any], review: Review, *, at: datetime) -> int | None:
    with conn.cursor() as cur:
        cur.execute(INSERT_SQL, {
            "fixture": review.fixture_id, "narrative": review.narrative_id, "version": VERSION, "at": at,
            "narrative_version": review.narrative_version, "packet": review.packet_id,
            "trace": str(match_trace_id(review.fixture_id)), "status": review.status, "outcome": Jsonb(review.outcome),
            "items": Jsonb(review.items), "summary": Jsonb(review.summary), "picks": Jsonb(review.picks)})
        row = cur.fetchone()
    return None if row is None else int(row[0])


@dataclass
class RunReport:
    due: int = 0
    written: int = 0
    waiting: int = 0
    firm: int = 0
    contradicted: int = 0
    ids: list[int] = field(default_factory=list)


def run(conn: psycopg.Connection[Any], *, at: datetime, apply: bool = True, lookback: timedelta = LOOKBACK,
        limit: int = LIMIT) -> RunReport:
    """Reviews the chronicles of the matches that finished at least ``SETTLE`` ago and have not been reviewed under this version.

    ``apply=False`` reads and judges but writes nothing (the command line's preview)."""
    report = RunReport()
    due = rows_of(conn, DUE_SQL, {"since": at - lookback - SETTLE, "until": at - SETTLE, "version": VERSION, "limit": limit})
    report.due = len(due)
    for row in due:
        review = review_one(conn, row)
        if review is None:
            report.waiting += 1
            continue
        report.firm += int(review.summary["firm_claims"])
        report.contradicted += int(review.summary["contradicted"])
        if apply:
            stored = store(conn, review, at=at)
            if stored is not None:
                report.written += 1
                report.ids.append(stored)
        else:
            report.written += 1
    return report
