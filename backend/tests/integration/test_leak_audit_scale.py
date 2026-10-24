"""The leak audit stays linear in the packets of the day (``leak-audit-v6``, rules ``h2h_known`` and ``tactics_known``).

The nightly run of 24 Oct 2026 audited the first day written with ``packet-v8`` (10,209 packets with tactics and head-to-head) and was
still reading them after more than an hour: for every packet, and every match that could have been cited, both rules asked "does the
packet cite it?" by looking through a materialised CTE of everything the whole day cited, so the work grew with the SQUARE of the packets
(the day before, with ~3,800 packets and none of these blocks, had taken 74 seconds). The rules now keep, per packet (and side), the list
of what it cites and the oldest kick-off among it, and look into that list. Two tests hold that:

* the equivalence: on a random world with every kind of dishonest packet, the old text (``leakage_reference``, word for word) and the rule
  of today return the same row for row (not only the same count), and the world has both honest and dishonest rows in every branch;
* the size: thousands of packets under a time limit that the old text, by its own growth, takes hours to meet.

The transaction is rolled back afterwards."""

from __future__ import annotations

import random
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb

from fbi.ai.calendar import day_bounds, local_day
from fbi.intel import h2h, leakage, tactics

from .conftest import Seed
from .helpers import scalar
from .leakage_reference import H2H_KNOWN, TACTICS_KNOWN

AT = datetime(2035, 5, 20, 12, tzinfo=UTC)
"""The moment the packets are as of; they are built in the six hours after it, all on the same Bogotá day."""

DAY = local_day(AT)
FINISHED = ("FT", "AET", "PEN")
LAST = "SELECT count(*) AS n"
"""Where the closing select of a rule starts (the same text in all of them): the test swaps it for one row per verdict."""

RULES_UNDER_TEST = {"h2h_known": H2H_KNOWN, "tactics_known": TACTICS_KNOWN}


@dataclass
class Fx:
    id: int
    home: int
    away: int
    kickoff: datetime
    status: str
    settled: datetime | None = None
    goals: tuple[int, int] = (0, 0)
    half_time: bool = False
    events: bool = False
    sheets: dict[str, bool] = field(default_factory=dict)
    """side -> whether the sheet was fetched before the packets' moment."""


class Pool:
    """A random world: sides, matches with and without a result, with and without events and sheets, and the matches to come."""

    def __init__(self, db: psycopg.Connection[Any], seed: Seed, rng: random.Random, *, sides: int, past: int, ahead: int) -> None:
        self.db, self.rng, self.hash = db, rng, seed.payload_hash
        self.cur = db.cursor()
        self.cur.execute("INSERT INTO core.competitions (provider_league_id, name, country, type, entity_scope, competition_type, "
                         "is_tracked) VALUES (98951, 'Scale League', 'Colombia', 'league', 'club', 'domestic_league', true) RETURNING id")
        comp = scalar(self.cur)
        self.cur.execute("INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, 2035) RETURNING id", (comp,))
        self.season = int(scalar(self.cur))
        self.team: list[int] = []
        for i in range(sides):
            self.cur.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (%s, %s) RETURNING id", (989500 + i, f"Scale {i}"))
            self.team.append(int(scalar(self.cur)))
        self.fx: dict[int, Fx] = {}
        self.n = 0
        for _ in range(past):
            self.add(rng.choice((*FINISHED, "FT", "FT", "FT", "FT", "PST", "CANC", "NS")), AT - timedelta(days=rng.uniform(1, 470)))
        self.upcoming = [self.add("NS", AT + timedelta(hours=rng.uniform(20, 40))).id for _ in range(ahead)]

    def add(self, status: str, kickoff: datetime) -> Fx:
        rng = self.rng
        home, away = rng.sample(self.team, 2)
        self.n += 1
        group = "finished" if status in FINISHED else ("cancelled" if status == "CANC" else "scheduled")
        self.cur.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at, "
                         "status_short, status_group) VALUES (%s, %s, %s, %s, %s, %s, %s) RETURNING id",
                         (9895000 + self.n, self.season, home, away, kickoff, status, group))
        fx = Fx(int(scalar(self.cur)), home, away, kickoff, status)
        self.fx[fx.id] = fx
        if status in FINISHED and rng.random() < 0.93:
            fx.settled = kickoff + timedelta(hours=2) if rng.random() < 0.93 else kickoff + timedelta(days=rng.uniform(5, 40))
            fx.goals = (rng.randint(0, 4), rng.randint(0, 4))
            fx.half_time = rng.random() < 0.7
            self.cur.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away, ht_goals_home, ht_goals_away, "
                             "settled_at) VALUES (%s, %s, %s, %s, %s, %s)",
                             (fx.id, *fx.goals, *((rng.randint(0, 2), rng.randint(0, 2)) if fx.half_time else (None, None)), fx.settled))
            if rng.random() < 0.6:
                late = rng.random() < 0.05
                fx.events = not late
                for seq in range(rng.randint(1, 3)):
                    self.cur.execute("INSERT INTO core.fixture_events (fixture_id, source, seq, minute, team_side, event_type, detail, "
                                     "payload_hash, fetched_at) VALUES (%s, 'api-football', %s, %s, %s, 'Goal', 'Normal Goal', %s, %s)",
                                     (fx.id, seq, 10 + seq * 20, rng.choice(["home", "away"]), self.hash,
                                      AT + timedelta(hours=1) if late else kickoff + timedelta(hours=3)))
            for side in ("home", "away"):
                if rng.random() < 0.5:
                    fx.sheets[side] = rng.random() > 0.05
                    self.cur.execute("INSERT INTO core.fixture_lineups (fixture_id, team_side, source, payload_hash, fetched_at) "
                                     "VALUES (%s, %s, 'api-football', %s, %s)",
                                     (fx.id, side, self.hash, kickoff - timedelta(hours=1) if fx.sheets[side] else AT + timedelta(hours=1)))
        return fx

    def known(self, team: int, kickoff: datetime, *, against: int | None = None, days: int | None = None) -> list[Fx]:
        """The matches the rules think a side could cite as of ``AT``: played to a result, settled by then, newest first."""
        out = [f for f in self.fx.values()
               if f.status in FINISHED and f.settled is not None and f.settled <= AT and f.kickoff < kickoff
               and (team in (f.home, f.away) if against is None else {f.home, f.away} == {team, against})
               and (days is None or f.kickoff >= kickoff - timedelta(days=days))]
        return sorted(out, key=lambda f: f.kickoff, reverse=True)


def junk(rng: random.Random, ids: list[int]) -> Any:
    """A value that is not a match id the way the builder writes them (or is one written in another way)."""
    return rng.choice([None, "abc", "12x", "", 1.5, True, [], {}, str(rng.choice(ids)), -7, 10**16, "00123", rng.choice(ids) + 10**9])


def dishonest_meetings(rng: random.Random, meetings: list[Any], ids: list[int]) -> list[Any]:
    out = list(meetings)
    for _ in range(rng.randint(1, 3)):
        kind = rng.randrange(9)
        if kind == 0 and out:
            out.pop(rng.randrange(len(out)))
        elif kind == 1 and out and isinstance(out[0], dict):
            out[rng.randrange(len(out))] = {**out[0], "fixture_id": rng.choice([*ids, junk(rng, ids)])}
        elif kind == 2 and out and isinstance(out[0], dict):
            out[rng.randrange(len(out))] = {**out[0], "days_ago": rng.choice([out[0].get("days_ago", 0) + 1, "x", None, -1])}
        elif kind == 3 and out:
            out.append(out[rng.randrange(len(out))])
        elif kind == 4:
            out.insert(rng.randrange(len(out) + 1), rng.choice([None, 5, "x", [1], {"fixture_id": rng.choice(ids)}]))
        elif kind == 5 and out and isinstance(out[0], dict):
            out[rng.randrange(len(out))] = {k: v for k, v in out[0].items() if k != "fixture_id"}
        elif kind == 6:
            out = []
        elif kind == 7 and out and isinstance(out[0], dict):
            out[rng.randrange(len(out))] = {**out[0], "coach_changed": {"home": rng.random() < 0.5, "away": rng.choice([True, "no"])}}
        else:
            out.extend({"fixture_id": rng.choice(ids), "days_ago": rng.randint(0, 400)} for _ in range(rng.randint(1, 5)))
    return out


def dishonest_side(rng: random.Random, block: dict[str, Any], ids: list[int]) -> dict[str, Any]:
    out = {**block}
    for _ in range(rng.randint(1, 3)):
        kind = rng.randrange(10)
        fixtures = list(out.get("fixtures", [])) if isinstance(out.get("fixtures"), list) else []
        if kind == 0 and fixtures:
            fixtures.pop(rng.randrange(len(fixtures)))
            out["fixtures"] = fixtures
        elif kind == 1:
            fixtures.insert(rng.randrange(len(fixtures) + 1), rng.choice([*ids, junk(rng, ids)]))
            out["fixtures"] = fixtures
        elif kind == 2 and fixtures:
            fixtures.append(fixtures[0])
            out["fixtures"] = fixtures
        elif kind == 3:
            out["goals"] = {"total_for": rng.choice([0, 1, 7, "x", None]), "total_against": rng.choice([0, 2, "3", None])}
        elif kind == 4:
            out["n"] = rng.choice([len(fixtures) + 1, "n", None, 0])
        elif kind == 5:
            out["read"] = {"events": rng.sample(ids, 3), "sheets": rng.sample(ids, 2)}
        elif kind == 6:
            out["with_the_score"] = {"half_time": {"n": rng.choice([0, 3, "x", None])}}
        elif kind == 7:
            out["fixtures"] = fixtures[: rng.randint(0, len(fixtures))]
        elif kind == 8:
            out["fixtures"] = [*fixtures, *rng.sample(ids, 11)]
        else:
            out.pop(rng.choice(["read", "goals", "with_the_score", "n"]), None)
    return out


def honest_side(pool: Pool, team: int, kickoff: datetime) -> dict[str, Any]:
    """The block of a side as an honest reader writes it: its last ``tactics.N`` matches, what was read from them, and the totals."""
    mine = pool.known(team, kickoff, days=tactics.WINDOW.days)[: tactics.N]
    events = [f for f in mine if f.events]
    sheets = [f for f in mine if f.sheets.get("home" if f.home == team else "away")]
    gf = sum(f.goals[0] if f.home == team else f.goals[1] for f in events)
    ga = sum(f.goals[1] if f.home == team else f.goals[0] for f in events)
    return {"team_id": team, "n": len(mine), "fixtures": [f.id for f in mine], "read": {"events": [f.id for f in events],
            "sheets": [f.id for f in sheets]}, "goals": {"total_for": gf, "total_against": ga},
            "with_the_score": {"half_time": {"n": sum(1 for f in mine if f.half_time)}}}


def write_packets(pool: Pool, db: psycopg.Connection[Any], *, honest: float) -> int:
    rng = pool.rng
    ids = list(pool.fx)
    for i, fid in enumerate(pool.upcoming):
        fx = pool.fx[fid]
        meetings = [{"fixture_id": f.id, "days_ago": int((fx.kickoff - f.kickoff).total_seconds() // 86400),
                     **({"coach_changed": {"home": rng.random() < 0.5, "away": False}}
                        if any(f.sheets.values()) and rng.random() < 0.5 else {})}
                    for f in pool.known(fx.home, fx.kickoff, against=fx.away)[: h2h.N]]
        sides = {"home": honest_side(pool, fx.home, fx.kickoff), "away": honest_side(pool, fx.away, fx.kickoff)}
        content: dict[str, Any] = {"fixture": {"kickoff_at": fx.kickoff.isoformat(), "home": {"id": fx.home}, "away": {"id": fx.away}},
                                   "h2h": {"meetings": meetings}, "dossier": {"tactics": sides}}
        if rng.random() > honest:
            part = rng.randrange(5)
            if part in (0, 1):
                content["h2h"] = {"meetings": dishonest_meetings(rng, meetings, ids)}
            if part in (2, 3):
                side = rng.choice(["home", "away"])
                sides[side] = dishonest_side(rng, sides[side], ids)
            if part == 4:
                content["fixture"][rng.choice(["home", "away"])] = {"id": rng.choice(["x", None, 12])}
                if rng.random() < 0.5:
                    content["dossier"]["tactics"][rng.choice(["home", "away"])] = rng.choice([{}, {"fixtures": "none"}, None])
        built = AT + timedelta(minutes=i % 360)
        db.execute("INSERT INTO ai.match_packets (fixture_id, packet_version, as_of, built_at, packet_hash, content) "
                   "VALUES (%s, 'packet-v8', %s, %s, %s, %s)",
                   (fid, AT, built, f"{i:064x}", Jsonb(content)))
    return len(pool.upcoming)


def one_row_per_verdict(sql: str) -> str:
    """The rule with its closing select swapped for one row per verdict (the packet and whether it is bad)."""
    head, tail = sql[: sql.rindex(LAST)], " ".join(sql[sql.rindex(LAST):].split())
    assert tail == ("SELECT count(*) AS n, count(*) FILTER (WHERE c.bad) AS bad, (array_agg(DISTINCT c.packet_id) FILTER (WHERE c.bad))[1:5] "
                    "AS examples FROM c"), "the rule closes in another way: the test has to be read again"
    return head + "SELECT c.packet_id, c.bad FROM c"


def verdicts(db: psycopg.Connection[Any], sql: str) -> Counter[tuple[Any, ...]]:
    start, end = day_bounds(DAY)
    return Counter(db.execute(one_row_per_verdict(sql), {"start": start, "end": end}).fetchall())


def summary(db: psycopg.Connection[Any], sql: str) -> tuple[Any, ...]:
    start, end = day_bounds(DAY)
    row = db.execute(sql, {"start": start, "end": end}).fetchone()
    assert row is not None
    return tuple(row)


@pytest.mark.parametrize("rule", sorted(RULES_UNDER_TEST))
@pytest.mark.parametrize("run", [11, 12, 13, 14])
def test_the_linear_rule_gives_the_row_the_old_one_gave(db: psycopg.Connection[Any], seed: Seed, rule: str, run: int) -> None:
    pool = Pool(db, seed, random.Random(run * 1000 + len(rule)), sides=9, past=420, ahead=140)
    assert write_packets(pool, db, honest=0.35) == 140
    old, new = verdicts(db, RULES_UNDER_TEST[rule]), verdicts(db, leakage.RULES[rule])
    assert old == new, f"{rule}: {sum((old - new).values())} verdicts only in the old text, {sum((new - old).values())} only in the new"
    assert summary(db, RULES_UNDER_TEST[rule]) == summary(db, leakage.RULES[rule])
    good = sum(n for (_p, verdict), n in new.items() if verdict is False)
    bad = sum(n for (_p, verdict), n in new.items() if verdict)
    assert good >= 60 and bad >= 20, f"{rule}: the world does not have both kinds ({good} honest rows, {bad} dishonest)"


def test_the_honest_packets_of_the_world_pass_both_rules(db: psycopg.Connection[Any], seed: Seed) -> None:
    """The yardstick of the test: a world written by an honest reader has no violation (so the dishonest rows above are the ones edited)."""
    pool = Pool(db, seed, random.Random(5), sides=9, past=420, ahead=100)
    write_packets(pool, db, honest=2.0)
    audit = leakage.audit_day(db, day=DAY, at=AT + timedelta(hours=10))
    for rule in RULES_UNDER_TEST:
        assert audit[rule]["violations"] == 0 and audit[rule]["checked"] > 0, (rule, audit[rule])


def scale_world(db: psycopg.Connection[Any], seed: Seed, packets: int, sides: int = 12, past: int = 700, filler: int = 0) -> None:
    """``packets`` packets about matches among ``sides`` sides that have each played ~120 matches in the last year (every pair ~10 times),
    each citing, honestly, the last ten matches of each side and the last eight meetings, all written in SQL. The packets are about
    matches that are only in their own JSON (the rules read the sides and the kick-off from there), so all hang from the seed's fixture and
    the table of matches holds no unplayed ones to wade through. ``filler`` is the number of other matches of other sides in the table, so
    the planner meets a table as large as production's and not a toy."""
    cur = db.cursor()
    cur.execute("INSERT INTO core.competitions (provider_league_id, name, country, type, entity_scope, competition_type, is_tracked) "
                "VALUES (98952, 'Scale League 2', 'Colombia', 'league', 'club', 'domestic_league', true) RETURNING id")
    comp = scalar(cur)
    cur.execute("INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, 2035) RETURNING id", (comp,))
    season = scalar(cur)
    cur.execute("INSERT INTO core.teams (provider_team_id, name) SELECT 989600 + g, 'Scale ' || g FROM generate_series(1, %s) g", (sides,))
    pair = ("JOIN core.teams t1 ON t1.provider_team_id = 989600 + 1 + (g * 7) %% %(sides)s "
            "JOIN core.teams t2 ON t2.provider_team_id = 989600 + 1 + ((g * 7) %% %(sides)s + 1 + g %% (%(sides)s - 1)) %% %(sides)s")
    cur.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at, "
                "status_short, status_group) "
                "SELECT 9896000 + g, %(season)s, t1.id, t2.id, %(at)s - interval '1 minute' * (g::bigint * 400 * 1440 / %(past)s + 90), "
                "'FT', 'finished' FROM generate_series(1, %(past)s) g " + pair,
                {"season": season, "at": AT, "past": past, "sides": sides})
    cur.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away, ht_goals_home, ht_goals_away, settled_at) "
                "SELECT id, 1, 0, 0, 0, kickoff_at + interval '2 hours' FROM core.fixtures WHERE provider_fixture_id > 9896000")
    if filler:
        cur.execute("INSERT INTO core.teams (provider_team_id, name) SELECT 989700 + g, 'Filler ' || g FROM generate_series(1, 400) g")
        cur.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at, "
                    "status_short, status_group) "
                    "SELECT 9990000 + g, %(season)s, t1.id, t2.id, %(at)s - interval '1 hour' * (g %% 36000), 'FT', 'finished' "
                    "FROM generate_series(1, %(filler)s) g "
                    "JOIN core.teams t1 ON t1.provider_team_id = 989700 + 1 + g %% 400 "
                    "JOIN core.teams t2 ON t2.provider_team_id = 989700 + 1 + (g %% 400 + 1 + g %% 399) %% 400",
                    {"season": season, "at": AT, "filler": filler})
        cur.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away, ht_goals_home, ht_goals_away, settled_at) "
                    "SELECT id, 2, 1, 1, 0, kickoff_at + interval '2 hours' FROM core.fixtures WHERE provider_fixture_id >= 9990000")
    for table in ("core.fixtures", "core.fixture_results"):
        cur.execute(f"ANALYZE {table}")
    cur.execute("""
        WITH t AS (
            SELECT g, t1.id AS home, t2.id AS away, %(at)s + interval '1 second' * (g %% 80000) AS kickoff
              FROM generate_series(1, %(packets)s) g """ + pair + """)
        INSERT INTO ai.match_packets (fixture_id, packet_version, as_of, built_at, packet_hash, content)
        SELECT %(fixture)s, 'packet-v8', %(at)s, %(at)s + interval '1 second' * (t.g %% 21000), encode(sha256(convert_to(t.g::text, 'UTF8')), 'hex'),
               jsonb_build_object(
                 'fixture', jsonb_build_object('kickoff_at', t.kickoff, 'home', jsonb_build_object('id', t.home),
                                               'away', jsonb_build_object('id', t.away)),
                 'h2h', jsonb_build_object('meetings', mt.m),
                 'dossier', jsonb_build_object('tactics', jsonb_build_object(
                     'home', jsonb_build_object('team_id', t.home, 'n', hs.n, 'fixtures', hs.fx, 'read', jsonb_build_object(
                         'events', '[]'::jsonb, 'sheets', '[]'::jsonb), 'goals', jsonb_build_object('total_for', 0, 'total_against', 0),
                         'with_the_score', jsonb_build_object('half_time', jsonb_build_object('n', hs.n))),
                     'away', jsonb_build_object('team_id', t.away, 'n', aws.n, 'fixtures', aws.fx, 'read', jsonb_build_object(
                         'events', '[]'::jsonb, 'sheets', '[]'::jsonb), 'goals', jsonb_build_object('total_for', 0, 'total_against', 0),
                         'with_the_score', jsonb_build_object('half_time', jsonb_build_object('n', aws.n))))))
          FROM t
          CROSS JOIN LATERAL (SELECT COALESCE(jsonb_agg(jsonb_build_object('fixture_id', q.id,
                        'days_ago', floor(extract(epoch FROM (t.kickoff - q.kickoff_at)) / 86400)::int) ORDER BY q.kickoff_at DESC),
                        '[]'::jsonb) AS m
                 FROM (SELECT g.id, g.kickoff_at FROM core.fixtures g JOIN core.fixture_results r ON r.fixture_id = g.id
                        WHERE ((g.home_team_id = t.home AND g.away_team_id = t.away) OR (g.home_team_id = t.away AND g.away_team_id = t.home))
                          AND g.kickoff_at < t.kickoff AND r.settled_at <= %(at)s ORDER BY g.kickoff_at DESC LIMIT 8) q) mt
          CROSS JOIN LATERAL (SELECT COALESCE(jsonb_agg(q.id ORDER BY q.kickoff_at DESC), '[]'::jsonb) AS fx, count(*) AS n
                 FROM (SELECT g.id, g.kickoff_at FROM core.fixtures g JOIN core.fixture_results r ON r.fixture_id = g.id
                        WHERE (g.home_team_id = t.home OR g.away_team_id = t.home) AND g.kickoff_at < t.kickoff
                          AND g.kickoff_at >= t.kickoff - interval '400 days' AND r.settled_at <= %(at)s
                        ORDER BY g.kickoff_at DESC LIMIT 10) q) hs
          CROSS JOIN LATERAL (SELECT COALESCE(jsonb_agg(q.id ORDER BY q.kickoff_at DESC), '[]'::jsonb) AS fx, count(*) AS n
                 FROM (SELECT g.id, g.kickoff_at FROM core.fixtures g JOIN core.fixture_results r ON r.fixture_id = g.id
                        WHERE (g.home_team_id = t.away OR g.away_team_id = t.away) AND g.kickoff_at < t.kickoff
                          AND g.kickoff_at >= t.kickoff - interval '400 days' AND r.settled_at <= %(at)s
                        ORDER BY g.kickoff_at DESC LIMIT 10) q) aws""",
                {"at": AT, "packets": packets, "sides": sides, "fixture": seed.fixture_id})
    cur.execute("ANALYZE ai.match_packets")


@pytest.mark.parametrize("rule", sorted(RULES_UNDER_TEST))
def test_thousands_of_packets_are_audited_within_the_time_limit(db: psycopg.Connection[Any], seed: Seed, rule: str) -> None:
    """3,000 packets (6,000 sides, 60,000 matches cited by the tactics) in a few seconds: the old text needs hours for this (the cost of a
    row grows with all the rows of the day), the linear one a second or two. The limit is generous so a slow machine does not fail it."""
    scale_world(db, seed, packets=3000, filler=40000)
    start, end = day_bounds(DAY)
    db.execute("SET LOCAL statement_timeout = '45s'")
    row = db.execute(leakage.RULES[rule], {"start": start, "end": end}).fetchone()
    assert row is not None
    n, bad, examples = row
    assert n >= 3000 and bad == 0 and not examples, (rule, row)
