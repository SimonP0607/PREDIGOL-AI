"""Match Knowledge, read from the database (plan F7): the inputs of the nine layers for a batch of finished matches, and the fingerprint
of those inputs that says whether a match has to be built again.

Two readings of the same sources:

* ``fingerprints`` answers "has anything the layers are made of changed?" with a few aggregate queries and no row transferred. It is a
  fingerprint of the CONTENT of what the layers read - the scores, the lines of the events, the statistics of the men, the closing price... -
  and not of the moments it was fetched: the provider re-reading a match and finding the same facts must change nothing, or every re-read
  would add a row that says what the last one said. Together with the versions of the rules (``layers.RULES``) it is the ``inputs_hash`` of
  a build. It is taken BEFORE the rows are read, so a change that lands in between is found by the next pass instead of lost (the other
  way round, a build would say it had read what it had not).
* ``read`` answers "what are they made of?" with the rows, mapped to ``layers.Inputs``.

Both are made from the same lists of columns (``*_FACTS``: facts, in the fingerprint; ``*_MOMENTS``: when it was fetched, only in the
layers' ``known_at``), so a column cannot be read without being fingerprinted; a test changes each one and sees the fingerprint move.
Sources that are append-only by trigger (the decisions, their outcomes, the post-mortems, the corrections of a result) are fingerprinted
by their count and newest id: that is exact for a table nobody edits. The market is fingerprinted by its newest consensus before kick-off:
what the market came to expect is the last price before the ball rolls, and nothing writes before that moment once the match is over. The
provider's last pre-match prices (``market.final_prematch_odds``, written once, after the match) are fingerprinted by what was quoted.

Nothing here writes, and nothing here reads the clock.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.knowledge import events as ev
from fbi.knowledge import layers
from fbi.people import sides

SOURCE: Final = "api-football"
"""The one provider of the events, the squad sheets and the statistics of the men."""
STATS_SOURCES: Final = ("api-football", "football-data.co.uk")
"""The providers of the statistics of the teams, the one to prefer first (``football-data.co.uk`` has only the basic columns)."""
CHUNK: Final = 200
"""Matches read at a time: a few thousand lines of events and players, small enough to be a quick query, large enough to be a few queries."""

FIXTURE_FACTS: Final = ("status_short", "home_team_id", "away_team_id", "is_neutral", "leg", "tie_id")
"""``kickoff_at`` is a fact too; as a moment of the clock it is fingerprinted as seconds, so that no session setting changes the text."""
RESULT_FACTS: Final = ("goals_home", "goals_away", "reg_goals_home", "reg_goals_away", "ht_goals_home", "ht_goals_away", "et_goals_home",
                       "et_goals_away", "pen_home", "pen_away")
RESULT_MOMENTS: Final = ("settled_at", "source_fetched_at")
TIE_FACTS: Final = ("id", "format", "status", "legs", "team_a_id", "team_b_id", "aggregate_a", "aggregate_b", "winner_team_id", "decided_by",
                    "shootout_a", "shootout_b", "winner_check")
TEAM_STAT_COLUMNS: Final = tuple(layers.TEAM_STAT_KEYS)
EVENT_FACTS: Final = ("seq", "minute", "extra_minute", "team_side", "provider_player_id", "player_name", "provider_assist_id", "assist_name",
                      "event_type", "detail", "comments")
PLAYER_FACTS: Final = ("provider_player_id", "team_side", "player_name", "minutes", "rating", "is_captain", "is_substitute", "goals", "assists")
LINEUP_FACTS: Final = ("team_side", "formation", "coach_id", "coach_name")
FINAL_FACTS: Final = ("market_key", "selection", "line", "odds_decimal")
"""The provider's last pre-match prices as the layer reads them: the bookmaker does not matter, only what was quoted (and how many quoted it).
``provider_update_at`` is a fact too (the layer says when), fingerprinted as seconds like ``kickoff_at``; ``fetched_at`` is a moment."""
FINAL_MOMENTS: Final = ("fetched_at",)


def _cols(alias: str, names: Iterable[str]) -> str:
    return ", ".join(f"{alias}.{name}" for name in names)


# ── the fingerprint ──────────────────────────────────────────────────────────────────────────────────────────────────────

_IDS = "%(ids)s::bigint[]"
_MARKETS = "%(markets)s::text[]"

CROSSED_SQL: Final = f"""
SELECT l.fixture_id, l.team_side, count(*) AS men, count(*) FILTER (WHERE s.team_side <> l.team_side) AS apart
  FROM core.fixture_lineup_players l
  JOIN core.fixture_player_stats s ON s.fixture_id = l.fixture_id AND s.source = l.source AND s.provider_player_id = l.provider_player_id
 WHERE l.provider_player_id > 0 AND l.fixture_id = ANY({_IDS})
 GROUP BY l.fixture_id, l.team_side
HAVING count(*) FILTER (WHERE s.team_side <> l.team_side) > 0
"""
"""``fbi.intel.tactics.CROSSED_SQL`` without the moment: the sheets that put men on the side the statistics put them against. A test holds the
two equal. Only the matches with at least one man apart come back; ``sides.is_crossed`` says which of them are crossed."""

PICKS_SQL: Final = f"""
SELECT p.fixture_id, p.market_key AS market, COALESCE(r.result_status, 'pending') AS result, count(*) AS n,
       COALESCE(sum(r.profit_units), 0) AS profit, max(r.settled_at) AS settled_at
  FROM picks.picks p LEFT JOIN picks.pick_results r ON r.pick_id = p.id
 WHERE p.fixture_id = ANY({_IDS})
 GROUP BY p.fixture_id, p.market_key, COALESCE(r.result_status, 'pending')
"""

FINGERPRINT_SQL: Final = f"""
SELECT f.id AS fixture_id, 'fixture' AS src,
       md5(ROW(extract(epoch FROM f.kickoff_at), {_cols('f', FIXTURE_FACTS)})::text) AS h
  FROM core.fixtures f WHERE f.id = ANY({_IDS})
UNION ALL
SELECT r.fixture_id, 'result', md5(ROW({_cols('r', RESULT_FACTS)})::text)
  FROM core.fixture_results r WHERE r.fixture_id = ANY({_IDS})
UNION ALL
SELECT v.fixture_id, 'revisions', count(*)::text || ':' || max(v.id)::text
  FROM core.fixture_result_revisions v WHERE v.fixture_id = ANY({_IDS}) GROUP BY v.fixture_id
UNION ALL
SELECT f.id, 'tie', md5(ROW({_cols('t', TIE_FACTS)})::text)
  FROM core.fixtures f JOIN core.ties t ON t.id = f.tie_id WHERE f.id = ANY({_IDS})
UNION ALL
SELECT s.fixture_id, 'team_stats',
       md5(string_agg(ROW(s.team_side, s.source, {_cols('s', TEAM_STAT_COLUMNS)})::text, E'\\n' ORDER BY s.team_side, s.source))
  FROM core.fixture_team_stats s WHERE s.fixture_id = ANY({_IDS}) GROUP BY s.fixture_id
UNION ALL
SELECT e.fixture_id, 'events', md5(string_agg(ROW({_cols('e', EVENT_FACTS)})::text, E'\\n' ORDER BY e.seq))
  FROM core.fixture_events e WHERE e.fixture_id = ANY({_IDS}) GROUP BY e.fixture_id
UNION ALL
SELECT p.fixture_id, 'players', md5(string_agg(ROW({_cols('p', PLAYER_FACTS)})::text, E'\\n' ORDER BY p.provider_player_id))
  FROM core.fixture_player_stats p WHERE p.fixture_id = ANY({_IDS}) GROUP BY p.fixture_id
UNION ALL
SELECT l.fixture_id, 'lineups', md5(string_agg(ROW({_cols('l', LINEUP_FACTS)})::text, E'\\n' ORDER BY l.team_side, l.source))
  FROM core.fixture_lineups l WHERE l.fixture_id = ANY({_IDS}) GROUP BY l.fixture_id
UNION ALL
SELECT c.fixture_id, 'crossed', md5(string_agg(ROW(c.team_side, c.men, c.apart)::text, E'\\n' ORDER BY c.team_side))
  FROM ({CROSSED_SQL}) c GROUP BY c.fixture_id
UNION ALL
SELECT f.id, 'market', extract(epoch FROM max(m.as_of))::text
  FROM core.fixtures f
  JOIN market.market_consensus m ON m.fixture_id = f.id AND m.devig_method = 'shin' AND m.as_of < f.kickoff_at
 WHERE f.id = ANY({_IDS}) GROUP BY f.id
UNION ALL
SELECT o.fixture_id, 'final',
       md5(string_agg(ROW({_cols('o', FINAL_FACTS)}, extract(epoch FROM o.provider_update_at))::text, E'\\n'
                      ORDER BY {_cols('o', FINAL_FACTS)}, o.provider_update_at))
  FROM market.final_prematch_odds o WHERE o.fixture_id = ANY({_IDS}) AND o.market_key = ANY({_MARKETS}) GROUP BY o.fixture_id
UNION ALL
SELECT d.fixture_id, 'decisions', count(*)::text || ':' || max(d.id)::text
  FROM intel.decisions d WHERE d.fixture_id = ANY({_IDS}) GROUP BY d.fixture_id
UNION ALL
SELECT d.fixture_id, 'outcomes', count(*)::text || ':' || max(o.decision_id)::text
  FROM intel.decision_outcomes o JOIN intel.decisions d ON d.id = o.decision_id WHERE d.fixture_id = ANY({_IDS}) GROUP BY d.fixture_id
UNION ALL
SELECT k.fixture_id, 'picks', md5(string_agg(ROW(k.market, k.result, k.n, k.profit)::text, E'\\n' ORDER BY k.market, k.result))
  FROM ({PICKS_SQL}) k GROUP BY k.fixture_id
UNION ALL
SELECT pm.fixture_id, 'postmortems', count(*)::text || ':' || max(pm.id)::text
  FROM intel.postmortems pm WHERE pm.fixture_id = ANY({_IDS}) GROUP BY pm.fixture_id
"""

SOURCES: Final = ("fixture", "result", "revisions", "tie", "team_stats", "events", "players", "lineups", "crossed", "market", "final",
                  "decisions", "outcomes", "picks", "postmortems")
"""The sources of the fingerprint, in the order of ``FINGERPRINT_SQL``: a source that has no row for a match says ``None``, so that a row
appearing or disappearing is a change."""


def _rows(conn: psycopg.Connection[Any], sql: str, params: Mapping[str, Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def fingerprints(conn: psycopg.Connection[Any], fixture_ids: Sequence[int]) -> dict[int, dict[str, Any]]:
    """What the layers of each match are made of, as a fingerprint per source (``None`` for a source with nothing), with the versions of
    the rules. Every id asked for comes back, also one that is not a match."""
    ids = [int(i) for i in fixture_ids]
    if not ids:
        return {}
    seen: dict[int, dict[str, Any]] = {i: {} for i in ids}
    for row in _rows(conn, FINGERPRINT_SQL, {"ids": ids, "markets": list(layers.MARKETS)}):
        seen[int(row["fixture_id"])][str(row["src"])] = row["h"]
    return {i: {"rules": dict(layers.RULES), **{src: found.get(src) for src in SOURCES}} for i, found in seen.items()}


def signatures(conn: psycopg.Connection[Any], fixture_ids: Sequence[int]) -> dict[int, str]:
    """The ``inputs_hash`` of each match: its fingerprint, canonical and hashed."""
    return {i: layers.signature_hash(fp) for i, fp in fingerprints(conn, fixture_ids).items()}


# ── the rows ─────────────────────────────────────────────────────────────────────────────────────────────────────────────

FIXTURE_SQL: Final = f"""
SELECT f.id AS fixture_id, f.kickoff_at, {_cols('f', FIXTURE_FACTS)} FROM core.fixtures f WHERE f.id = ANY({_IDS})
"""
RESULT_SQL: Final = f"""
SELECT r.fixture_id, {_cols('r', RESULT_FACTS)}, {_cols('r', RESULT_MOMENTS)} FROM core.fixture_results r WHERE r.fixture_id = ANY({_IDS})
"""
REVISIONS_SQL: Final = f"""
SELECT v.fixture_id, v.kind, v.observed_at, v.changed FROM core.fixture_result_revisions v
 WHERE v.fixture_id = ANY({_IDS}) ORDER BY v.fixture_id, v.observed_at, v.id
"""
TIE_SQL: Final = f"""
SELECT f.id AS fixture_id, {_cols('t', TIE_FACTS)} FROM core.fixtures f JOIN core.ties t ON t.id = f.tie_id WHERE f.id = ANY({_IDS})
"""
TEAM_STATS_SQL: Final = f"""
SELECT s.fixture_id, s.team_side, s.source, {_cols('s', TEAM_STAT_COLUMNS)}, s.fetched_at
  FROM core.fixture_team_stats s WHERE s.fixture_id = ANY({_IDS})
"""
EVENTS_SQL: Final = f"""
SELECT e.fixture_id, {_cols('e', EVENT_FACTS)}, e.fetched_at FROM core.fixture_events e WHERE e.fixture_id = ANY({_IDS}) ORDER BY e.fixture_id, e.seq
"""
PLAYERS_SQL: Final = f"""
SELECT p.fixture_id, {_cols('p', PLAYER_FACTS)}, p.fetched_at FROM core.fixture_player_stats p WHERE p.fixture_id = ANY({_IDS})
"""
LINEUPS_SQL: Final = f"""
SELECT l.fixture_id, {_cols('l', LINEUP_FACTS)}, l.fetched_at FROM core.fixture_lineups l WHERE l.fixture_id = ANY({_IDS})
"""
CLOSING_SQL: Final = f"""
SELECT DISTINCT ON (m.fixture_id, m.market_key, m.selection, m.line)
       m.fixture_id, m.market_key, m.selection, m.line, m.p_fair, m.n_bookmakers, m.as_of
  FROM market.market_consensus m JOIN core.fixtures f ON f.id = m.fixture_id
 WHERE m.fixture_id = ANY({_IDS}) AND m.devig_method = 'shin' AND m.market_key = ANY(%(markets)s::text[]) AND m.as_of < f.kickoff_at
 ORDER BY m.fixture_id, m.market_key, m.selection, m.line, m.as_of DESC
"""
OPENING_SQL: Final = f"""
SELECT DISTINCT ON (m.fixture_id, m.market_key, m.selection, m.line)
       m.fixture_id, m.market_key, m.selection, m.line, m.p_fair, m.n_bookmakers, m.as_of
  FROM market.market_consensus m JOIN core.fixtures f ON f.id = m.fixture_id
 WHERE m.fixture_id = ANY({_IDS}) AND m.devig_method = 'shin' AND m.market_key = ANY(%(markets)s::text[]) AND m.as_of < f.kickoff_at
   AND m.as_of >= f.kickoff_at - make_interval(days => %(lookback)s)
 ORDER BY m.fixture_id, m.market_key, m.selection, m.line, m.as_of
"""
FINAL_SQL: Final = f"""
SELECT o.fixture_id, o.market_key, o.selection, o.line, percentile_disc(0.5) WITHIN GROUP (ORDER BY o.odds_decimal) AS odds,
       count(*) AS books, max(o.provider_update_at) AS as_of, {", ".join(f"max(o.{c}) AS {c}" for c in FINAL_MOMENTS)}
  FROM market.final_prematch_odds o WHERE o.fixture_id = ANY({_IDS}) AND o.market_key = ANY({_MARKETS})
 GROUP BY o.fixture_id, o.market_key, o.selection, o.line
"""
"""One row per selection and line: the price in the middle of the bookmakers' (``percentile_disc`` takes one of the prices quoted, the lower
one of the two in the middle when they are an even number) and how many quoted it - the primary key allows one price per bookmaker."""
DECISIONS_SQL: Final = f"""
SELECT d.fixture_id, d.id, d.checkpoint, d.market_key, d.selection, d.line, d.state, d.known_at, d.score, d.odds, d.p_cal, d.edge_cal,
       d.stake_units, o.result_status, o.profit_flat, o.clv, o.settled_at
  FROM intel.decisions d LEFT JOIN intel.decision_outcomes o ON o.decision_id = d.id
 WHERE d.fixture_id = ANY({_IDS}) ORDER BY d.fixture_id, d.id
"""
POSTMORTEMS_SQL: Final = f"""
SELECT pm.fixture_id, pm.id, pm.decision_id, pm.version, pm.outcome, pm.decision_quality, pm.verdict, pm.created_at, pm.causes
  FROM intel.postmortems pm WHERE pm.fixture_id = ANY({_IDS}) ORDER BY pm.fixture_id, pm.id
"""


@dataclass(frozen=True, slots=True)
class Read:
    """What was read for one match: the inputs of the layers, and when each line of its events was fetched (the table of what each line
    IS keeps that moment: a line whose ``event_fetched_at`` is not the provider's is stale)."""

    inputs: layers.Inputs
    event_stamps: Mapping[int, datetime]


def _float(value: Any) -> float | None:
    return None if value is None else float(value)


def _number(value: Any) -> float | int | None:
    if value is None:
        return None
    return value if isinstance(value, int) and not isinstance(value, bool) else float(value)


def _int(value: Any) -> int | None:
    return None if value is None else int(value)


def pick_team_stats(rows: Sequence[Mapping[str, Any]]) -> list[layers.TeamStats]:
    """One row per side: from the provider that has BOTH sides (the most complete), api-football before the older dataset. Mixing a side
    from one provider with the other side from another would compare what is not comparable."""
    by_source: dict[str, dict[str, Mapping[str, Any]]] = defaultdict(dict)
    for row in rows:
        by_source[str(row["source"])][str(row["team_side"])] = row
    if not by_source:
        return []

    def rank(source: str) -> tuple[int, int, str]:
        order = STATS_SOURCES.index(source) if source in STATS_SOURCES else len(STATS_SOURCES)
        return -len(by_source[source]), order, source

    chosen = by_source[min(by_source, key=rank)]
    return [layers.TeamStats(side=side, values={c: _number(chosen[side][c]) for c in TEAM_STAT_COLUMNS}, fetched_at=chosen[side]["fetched_at"])
            for side in sides.SIDES if side in chosen]


def read(conn: psycopg.Connection[Any], fixture_ids: Sequence[int]) -> dict[int, Read]:
    """The inputs of the layers of each match asked for that exists. Absent things are empty: nothing is invented."""
    ids = [int(i) for i in fixture_ids]
    if not ids:
        return {}
    fixtures = {int(r["fixture_id"]): r for r in _rows(conn, FIXTURE_SQL, {"ids": ids})}
    if not fixtures:
        return {}
    ids = [i for i in ids if i in fixtures]
    results = {int(r["fixture_id"]): r for r in _rows(conn, RESULT_SQL, {"ids": ids})}
    revisions: dict[int, list[layers.Revision]] = defaultdict(list)
    for r in _rows(conn, REVISIONS_SQL, {"ids": ids}):
        revisions[int(r["fixture_id"])].append(layers.Revision(observed_at=r["observed_at"], kind=str(r["kind"]), changed=tuple(r["changed"])))
    ties = {int(r["fixture_id"]): r for r in _rows(conn, TIE_SQL, {"ids": ids})}
    stats: dict[int, list[Mapping[str, Any]]] = defaultdict(list)
    for r in _rows(conn, TEAM_STATS_SQL, {"ids": ids}):
        stats[int(r["fixture_id"])].append(r)
    raw: dict[int, list[ev.RawEvent]] = defaultdict(list)
    stamps: dict[int, dict[int, datetime]] = defaultdict(dict)
    for r in _rows(conn, EVENTS_SQL, {"ids": ids}):
        fid = int(r["fixture_id"])
        raw[fid].append(ev.RawEvent(
            seq=int(r["seq"]), minute=int(r["minute"]), extra_minute=_int(r["extra_minute"]), side=r["team_side"], event_type=str(r["event_type"]),
            detail=r["detail"], comments=r["comments"], player_id=_int(r["provider_player_id"]), player_name=r["player_name"],
            assist_id=_int(r["provider_assist_id"]), assist_name=r["assist_name"]))
        stamps[fid][int(r["seq"])] = r["fetched_at"]
    players: dict[int, list[layers.PlayerStat]] = defaultdict(list)
    for r in _rows(conn, PLAYERS_SQL, {"ids": ids}):
        players[int(r["fixture_id"])].append(layers.PlayerStat(
            player_id=int(r["provider_player_id"]), side=str(r["team_side"]), name=r["player_name"], minutes=_int(r["minutes"]),
            rating=_float(r["rating"]), captain=bool(r["is_captain"]), substitute=bool(r["is_substitute"]), goals=_int(r["goals"]),
            assists=_int(r["assists"]), fetched_at=r["fetched_at"]))
    lineups: dict[int, list[layers.Lineup]] = defaultdict(list)
    for r in _rows(conn, LINEUPS_SQL, {"ids": ids}):
        lineups[int(r["fixture_id"])].append(layers.Lineup(
            side=str(r["team_side"]), formation=r["formation"], coach_id=_int(r["coach_id"]), coach_name=r["coach_name"], fetched_at=r["fetched_at"]))
    men: dict[int, list[tuple[int, int]]] = defaultdict(list)
    for r in _rows(conn, CROSSED_SQL, {"ids": ids}):
        men[int(r["fixture_id"])].append((int(r["men"]), int(r["apart"])))
    market = {"ids": ids, "markets": list(layers.MARKETS), "lookback": layers.OPENING_LOOKBACK_DAYS}
    closing: dict[int, list[layers.Quote]] = defaultdict(list)
    opening: dict[int, list[layers.Quote]] = defaultdict(list)
    for sql, into in ((CLOSING_SQL, closing), (OPENING_SQL, opening)):
        for r in _rows(conn, sql, market):
            into[int(r["fixture_id"])].append(layers.Quote(
                market=str(r["market_key"]), selection=str(r["selection"]), line=Decimal(r["line"]), p_fair=float(r["p_fair"]),
                books=int(r["n_bookmakers"]), as_of=r["as_of"]))
    final: dict[int, list[layers.FinalQuote]] = defaultdict(list)
    for r in _rows(conn, FINAL_SQL, market):
        final[int(r["fixture_id"])].append(layers.FinalQuote(
            market=str(r["market_key"]), selection=str(r["selection"]), line=Decimal(r["line"]), odds=float(r["odds"]), books=int(r["books"]),
            as_of=r["as_of"], fetched_at=r["fetched_at"]))
    decisions: dict[int, list[layers.Decision]] = defaultdict(list)
    for r in _rows(conn, DECISIONS_SQL, {"ids": ids}):
        decisions[int(r["fixture_id"])].append(layers.Decision(
            id=int(r["id"]), checkpoint=str(r["checkpoint"]), market=str(r["market_key"]), selection=str(r["selection"]), line=Decimal(r["line"]),
            state=str(r["state"]), known_at=r["known_at"], score=_float(r["score"]), odds=_float(r["odds"]), p_cal=_float(r["p_cal"]),
            edge_cal=_float(r["edge_cal"]), stake=float(r["stake_units"]), result=r["result_status"], profit=_float(r["profit_flat"]),
            clv=_float(r["clv"]), outcome_at=r["settled_at"]))
    picks: dict[int, list[layers.PickTally]] = defaultdict(list)
    for r in _rows(conn, PICKS_SQL, {"ids": ids}):
        picks[int(r["fixture_id"])].append(layers.PickTally(
            market=str(r["market"]), result=str(r["result"]), n=int(r["n"]), profit=float(r["profit"]), settled_at=r["settled_at"]))
    postmortems: dict[int, list[layers.Postmortem]] = defaultdict(list)
    for r in _rows(conn, POSTMORTEMS_SQL, {"ids": ids}):
        postmortems[int(r["fixture_id"])].append(layers.Postmortem(
            id=int(r["id"]), decision_id=int(r["decision_id"]), version=str(r["version"]), outcome=str(r["outcome"]),
            quality=str(r["decision_quality"]), verdict=str(r["verdict"]), created_at=r["created_at"],
            causes=_cause_codes(r["causes"])))

    out: dict[int, Read] = {}
    for fid in ids:
        f = fixtures[fid]
        res = results.get(fid)
        tie = ties.get(fid)
        lines = raw.get(fid, [])
        inputs = layers.Inputs(
            fixture=layers.Fixture(id=fid, kickoff_at=f["kickoff_at"], status=str(f["status_short"]), home_team_id=int(f["home_team_id"]),
                                   away_team_id=int(f["away_team_id"]), neutral=bool(f["is_neutral"]), leg=_int(f["leg"]), tie_id=_int(f["tie_id"])),
            result=None if res is None else layers.Result(
                goals_home=int(res["goals_home"]), goals_away=int(res["goals_away"]), reg_home=int(res["reg_goals_home"]), reg_away=int(res["reg_goals_away"]),
                settled_at=res["settled_at"], ht_home=_int(res["ht_goals_home"]), ht_away=_int(res["ht_goals_away"]), et_home=_int(res["et_goals_home"]),
                et_away=_int(res["et_goals_away"]), pen_home=_int(res["pen_home"]), pen_away=_int(res["pen_away"]), fetched_at=res["source_fetched_at"]),
            revisions=tuple(revisions.get(fid, ())),
            tie=None if tie is None else layers.Tie(
                id=int(tie["id"]), format=str(tie["format"]), status=str(tie["status"]), legs=int(tie["legs"]), team_a_id=int(tie["team_a_id"]),
                team_b_id=int(tie["team_b_id"]), aggregate_a=_int(tie["aggregate_a"]), aggregate_b=_int(tie["aggregate_b"]),
                winner_team_id=_int(tie["winner_team_id"]), decided_by=tie["decided_by"], shootout_a=_int(tie["shootout_a"]),
                shootout_b=_int(tie["shootout_b"]), winner_check=tie["winner_check"]),
            team_stats=tuple(pick_team_stats(stats.get(fid, ()))),
            events=tuple(lines), events_fetched_at=max(stamps[fid].values()) if fid in stamps else None,
            players=tuple(players.get(fid, ())), lineups=tuple(lineups.get(fid, ())),
            sheets_crossed=any(sides.is_crossed(n, apart) for n, apart in men.get(fid, ())),
            open_quotes=tuple(opening.get(fid, ())), close_quotes=tuple(closing.get(fid, ())), final_quotes=tuple(final.get(fid, ())),
            decisions=tuple(decisions.get(fid, ())), picks=tuple(picks.get(fid, ())), postmortems=tuple(postmortems.get(fid, ())))
        out[fid] = Read(inputs, stamps.get(fid, {}))
    return out


def _cause_codes(causes: Any) -> tuple[str, ...]:
    """The codes of the causes a post-mortem found (``[{"code": "red_card", ...}, ...]``), each once, in the order the post-mortem gave them."""
    if not isinstance(causes, list):
        return ()
    seen: dict[str, None] = {}
    for cause in causes:
        if isinstance(cause, dict) and isinstance(cause.get("code"), str):
            seen.setdefault(cause["code"], None)
    return tuple(seen)
