"""A small world for the Match Knowledge tests (``fbi.knowledge``, plan F7): finished matches with the facts the nine layers read - the result and
its corrections, the statistics of the teams and of the men, the provider's list of events, the squad sheets, the consensus from the opening to
the close, the decisions, the picks and the post-mortems - and the ways those can differ from match to match.

``World.golden()`` is the match most tests start from (kick-off ``KICKOFF``, home T0 against away T1, 2-1, break 1-0):

     12'  home   goal (501)
     33'  away   yellow card (601)
     60'  home   yellow card and red card of the same man (502): a dismissal for two yellows, listed as two lines
     70'  away   penalty scored (602)
     80'  home   substitution (503 off, 504 on)
     85'  home   goal (505)
     88'  away   VAR: goal disallowed

with both sides' statistics (their cards agree with the list), six men a side, both squad sheets, the 1X2, Over/Under 2.5 and BTTS from a week
before to twenty minutes before the kick-off (and the provider's last prices of them, read after the match, from two to four
bookmakers), two decisions (one backed and won, one rejected) with their outcomes, a shadow pick that won and a
post-mortem of the decision. The transaction of the test is rolled back afterwards.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
from psycopg.types.json import Jsonb

from .conftest import Seed
from .helpers import scalar

KICKOFF = datetime(2034, 5, 2, 19, tzinfo=UTC)
FETCHED = KICKOFF + timedelta(hours=3)
SETTLED = KICKOFF + timedelta(hours=2)
NOW = KICKOFF + timedelta(days=2)
"""A moment when the golden match has been settled for a long time."""

PICK_COLS = (
    "candidate_id,fixture_id,market_key,selection,line,model_version_id,calibrator_id,"
    "feature_set_hash,data_cutoff_ts,decision_rule_version,code_version,bookmaker_id,"
    "market_odds,odds_captured_at,p_model,p_calibrated,p_calibrated_lo,p_calibrated_hi,"
    "p_market_fair,fair_odds,edge,price_edge,ev,ev_adjusted,kelly_fraction,stake_units,"
    "selection_reason,created_at"
)

Event = dict[str, Any]


def ev(seq: int, minute: int, side: str | None, kind: str, detail: str | None = None, *, extra: int | None = None, player: int | None = None,
       name: str | None = None, assist: int | None = None, assist_name: str | None = None, comments: str | None = None) -> Event:
    """One line of the provider's list of events."""
    return {"seq": seq, "minute": minute, "extra_minute": extra, "team_side": side, "provider_player_id": player, "player_name": name,
            "provider_assist_id": assist, "assist_name": assist_name, "event_type": kind, "detail": detail, "comments": comments}


def goal(seq: int, minute: int, side: str, player: int | None = None, detail: str = "Normal Goal", **kw: Any) -> Event:
    return ev(seq, minute, side, "Goal", detail, player=player, name=None if player is None else f"Man {player}", **kw)


def card(seq: int, minute: int, side: str, player: int, detail: str) -> Event:
    return ev(seq, minute, side, "Card", detail, player=player, name=f"Man {player}")


def sub(seq: int, minute: int, side: str, off: int, on: int) -> Event:
    return ev(seq, minute, side, "subst", "Substitution 1", player=off, name=f"Man {off}", assist=on, assist_name=f"Man {on}")


def var(seq: int, minute: int, side: str, detail: str) -> Event:
    return ev(seq, minute, side, "Var", detail)


GOLDEN_EVENTS = [
    goal(0, 12, "home", 501),
    card(1, 33, "away", 601, "Yellow Card"),
    card(2, 60, "home", 502, "Yellow Card"),
    card(3, 60, "home", 502, "Red Card"),
    goal(4, 70, "away", 602, "Penalty"),
    sub(5, 80, "home", 503, 504),
    goal(6, 85, "home", 505),
    var(7, 88, "away", "Goal Disallowed"),
]


class World:
    def __init__(self, db: psycopg.Connection[Any], seed: Seed) -> None:
        self.db, self.seed = db, seed
        self.cur = db.cursor()
        self.hash = seed.payload_hash
        self.n = 0
        self.bookmakers: list[int] = [seed.bookmaker_id]
        self.cur.execute("INSERT INTO core.competitions (provider_league_id, name, country, type, entity_scope, competition_type, is_tracked) "
                         "VALUES (98971, 'Knowledge League', 'Colombia', 'league', 'club', 'domestic_league', true) RETURNING id")
        comp = scalar(self.cur)
        self.cur.execute("INSERT INTO core.competition_seasons (competition_id, season, is_current) VALUES (%s, 2034, true) RETURNING id", (comp,))
        self.season = int(scalar(self.cur))
        self.team: list[int] = []
        for i in range(4):
            self.cur.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (%s, %s) RETURNING id", (989710 + i, f"Knowledge {i}"))
            self.team.append(int(scalar(self.cur)))
        self.cur.execute("INSERT INTO market.markets (key,name,n_outcomes,has_line,is_exclusive) VALUES "
                         "('OU','Goals Over/Under',2,true,true),('BTTS','Both Teams Score',2,false,true) ON CONFLICT (key) DO NOTHING")
        self.cur.execute(
            "INSERT INTO models.calibrators (model_version_id,market_key,scope,method,params,n_train,train_from,train_to,n_val,val_from,val_to,"
            "val_ece,val_mce,val_brier,val_logloss,reliability_weight) VALUES "
            "(%s,'1X2','global','isotonic','{}',1000,'2020-01-01','2024-06-30',500,'2024-07-01','2025-06-30',0.018,0.04,0.19,0.58,0.82) RETURNING id",
            (seed.model_version_id,))
        self.calibrator = int(scalar(self.cur))

    # ── the match ────────────────────────────────────────────────────────────────────────────────────────────────────────

    def match(self, kickoff: datetime = KICKOFF, home: int = 0, away: int = 1, goals: tuple[int, int] | None = (2, 1), *, status: str = "FT",
              ht: tuple[int, int] | None = (1, 0), ft: tuple[int, int] | None = None, et: tuple[int, int] | None = None,
              pen: tuple[int, int] | None = None, neutral: bool = False, settled: datetime | None = SETTLED,
              group: str = "finished") -> int:
        """A match and, if ``goals`` is given, its result. ``goals`` is the final score with extra time; ``ft`` the 90 minutes' (the goals
        when not said)."""
        self.n += 1
        self.cur.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at, "
                         "status_short, status_group, is_neutral) VALUES (%s, %s, %s, %s, %s, %s, %s, %s) RETURNING id",
                         (9897100 + self.n, self.season, self.team[home], self.team[away], kickoff, status, group, neutral))
        fid = int(scalar(self.cur))
        if goals is not None:
            self.result(fid, goals, ht=ht, ft=ft, et=et, pen=pen, settled=settled, kickoff=kickoff)
        return fid

    def result(self, fid: int, goals: tuple[int, int], *, ht: tuple[int, int] | None = (1, 0), ft: tuple[int, int] | None = None,
               et: tuple[int, int] | None = None, pen: tuple[int, int] | None = None, settled: datetime | None = SETTLED,
               kickoff: datetime = KICKOFF) -> None:
        """The result row of a match (``match`` writes it when it is given the goals; this is for the match whose result arrives later)."""
        regulation = ft if ft is not None else goals
        self.cur.execute(
            "INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away, ht_goals_home, ht_goals_away, ft_goals_home, ft_goals_away, "
            "et_goals_home, et_goals_away, pen_home, pen_away, settled_at, source_payload_hash, source_fetched_at) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
            (fid, goals[0], goals[1], ht[0] if ht else None, ht[1] if ht else None, regulation[0], regulation[1],
             et[0] if et else None, et[1] if et else None, pen[0] if pen else None, pen[1] if pen else None,
             settled or kickoff + timedelta(hours=2), self.hash, kickoff + timedelta(hours=2)))

    def events(self, fid: int, events: list[Event], fetched: datetime = FETCHED) -> None:
        for e in events:
            self.cur.execute("INSERT INTO core.fixture_events (fixture_id, source, seq, minute, extra_minute, team_side, provider_player_id, "
                             "player_name, provider_assist_id, assist_name, event_type, detail, comments, payload_hash, fetched_at) "
                             "VALUES (%(fixture_id)s, 'api-football', %(seq)s, %(minute)s, %(extra_minute)s, %(team_side)s, %(provider_player_id)s, "
                             "%(player_name)s, %(provider_assist_id)s, %(assist_name)s, %(event_type)s, %(detail)s, %(comments)s, %(hash)s, "
                             "%(fetched)s)", {**e, "fixture_id": fid, "hash": self.hash, "fetched": fetched})

    def team_stats(self, fid: int, side: str, source: str = "api-football", fetched: datetime = FETCHED, **columns: Any) -> None:
        names = ["fixture_id", "team_side", "source", "payload_hash", "fetched_at", *columns]
        values = [fid, side, source, self.hash, fetched, *columns.values()]
        self.cur.execute(f"INSERT INTO core.fixture_team_stats ({', '.join(names)}) VALUES ({', '.join(['%s'] * len(values))})", values)

    def men(self, fid: int, side: str, men: list[tuple[int, dict[str, Any]]], fetched: datetime = FETCHED) -> None:
        """The statistics of the men of a side: ``(provider id, {column: value})``."""
        for pid, columns in men:
            row = {"fixture_id": fid, "source": "api-football", "provider_player_id": pid, "team_side": side, "player_name": f"Man {pid}",
                   "payload_hash": self.hash, "fetched_at": fetched, **columns}
            self.cur.execute(f"INSERT INTO core.fixture_player_stats ({', '.join(row)}) VALUES ({', '.join(['%s'] * len(row))})", list(row.values()))

    def sheet(self, fid: int, side: str, formation: str | None, men: list[int], coach: str | None = None, fetched: datetime = FETCHED,
              coach_id: int | None = None) -> None:
        self.cur.execute("INSERT INTO core.fixture_lineups (fixture_id, team_side, source, formation, coach_name, coach_id, payload_hash, fetched_at) "
                         "VALUES (%s, %s, 'api-football', %s, %s, %s, %s, %s)", (fid, side, formation, coach, coach_id, self.hash, fetched))
        for pid in men:
            self.cur.execute("INSERT INTO core.fixture_lineup_players (fixture_id, team_side, source, provider_player_id, is_starter) "
                             "VALUES (%s, %s, 'api-football', %s, true)", (fid, side, pid))

    def quote(self, fid: int, market: str, selection: str, line: float, p: float, as_of: datetime, *, books: int = 10,
              method: str = "shin") -> None:
        self.cur.execute("INSERT INTO market.market_consensus (fixture_id,market_key,selection,line,as_of,devig_method,p_fair,n_bookmakers,"
                         "overround,best_odds,best_bookmaker_id) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,0.05,%s,%s)",
                         (fid, market, selection, line, as_of, method, p, books, round(1 / p, 3), self.seed.bookmaker_id))

    def books(self, n: int) -> list[int]:
        """The ids of ``n`` bookmakers: the seed's and, for more, others made here."""
        while len(self.bookmakers) < n:
            self.cur.execute("INSERT INTO market.bookmakers (provider_bookmaker_id, name) VALUES (%s, %s) RETURNING id",
                             (989800 + len(self.bookmakers), f"Knowledge book {len(self.bookmakers)}"))
            self.bookmakers.append(int(scalar(self.cur)))
        return self.bookmakers[:n]

    def final(self, fid: int, market: str, selection: str, line: float, prices: Sequence[float], *, kickoff: datetime = KICKOFF,
              minutes: int = 85, fetched: datetime | None = None) -> None:
        """The provider's last pre-match prices of a selection, read after the match: one per bookmaker (``prices[i]`` is the ``i``-th one's),
        stamped ``minutes`` before kick-off."""
        for book, price in zip(self.books(len(prices)), prices, strict=True):
            self.cur.execute("INSERT INTO market.final_prematch_odds (fixture_id, bookmaker_id, market_key, selection, line, odds_decimal, "
                             "provider_update_at, minutes_to_ko, fetched_at, payload_hash) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
                             (fid, book, market, selection, line, price, kickoff - timedelta(minutes=minutes), minutes,
                              fetched or kickoff + timedelta(hours=3), self.hash))

    def revision(self, fid: int, observed: datetime, kind: str = "score") -> None:
        self.cur.execute("INSERT INTO core.fixture_result_revisions (fixture_id, kind, observed_at, old_state, new_state, changed) "
                         "VALUES (%s, %s, %s, %s, %s, %s)",
                         (fid, kind, observed, Jsonb({"goals_home": 1}), Jsonb({"goals_home": 2}), ["goals_home"]))

    # ── what PrediGol did ────────────────────────────────────────────────────────────────────────────────────────────────

    def decision(self, fid: int, market: str, selection: str, line: float, state: str, *, odds: float | None = 2.1, kickoff: datetime = KICKOFF,
                 checkpoint: str = "T-3h", score: float = 71.5, stake: float = 1.0, known: datetime | None = None, pick: int | None = None) -> int:
        stake = stake if state not in ("RECHAZADO", "INVESTIGACION") else 0
        return int(scalar(self.cur.execute(
            "INSERT INTO intel.decisions (decision_version, known_at, checkpoint, fixture_id, kickoff_at, market_key, selection, line, pick_id, "
            "model_name, odds, p_model, p_cal, p_market, edge_cal, score, stake_units, filters, state, context_status, input_hash) VALUES "
            "('decision-v1', %s, %s, %s, %s, %s, %s, %s, %s, 'dixon_coles', %s, 0.55, 0.55, 0.50, 0.04, %s, %s, '[]', %s, 'PENDING', %s) "
            "RETURNING id", (known or kickoff - timedelta(hours=3), checkpoint, fid, kickoff, market, selection, line, pick, odds, score, stake,
                             state, f"{market}-{selection}-{line}-{checkpoint}-{self.n}-{state}-{odds}"))))

    def outcome(self, decision: int, result: str, profit: float, *, clv: float | None = 0.04, settled: datetime = SETTLED) -> None:
        self.cur.execute("INSERT INTO intel.decision_outcomes (decision_id, settled_at, result_status, profit_flat, profit_staked, close_p_fair, "
                         "close_odds, close_as_of, clv, version, computed_at) VALUES (%s, %s, %s, %s, %s, 0.5, 2.0, %s, %s, 'outcome-v1', %s)",
                         (decision, settled, result, profit, profit, KICKOFF - timedelta(minutes=20), clv, settled))

    def postmortem(self, decision: int, fid: int, *, verdict: str = "MERECIDO", quality: str = "GOOD", outcome: str = "won",
                   version: str = "pm-v5", causes: list[str] | None = None, created: datetime = SETTLED + timedelta(hours=10)) -> int:
        causes = ["red_card"] if causes is None else causes
        return int(scalar(self.cur.execute(
            "INSERT INTO intel.postmortems (decision_id, fixture_id, created_at, version, outcome, decision_quality, verdict, causes, answers) "
            "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, '{}'::jsonb) RETURNING id",
            (decision, fid, created, version, outcome, quality, verdict, Jsonb([{"code": c, "text": c} for c in causes])))))

    def pick(self, fid: int, market: str, selection: str, line: float, *, odds: float = 2.1, result: str | None = "win",
             profit: float = 1.1, settled: datetime = SETTLED, kickoff: datetime = KICKOFF) -> int:
        cur = self.cur
        created = kickoff - timedelta(hours=3)
        cutoff = created - timedelta(hours=2)
        cur.execute("INSERT INTO models.predictions (fixture_id,model_version_id,calibrator_id,market_key,selection,line,p_raw,p_calibrated,p_lo,p_hi,"
                    "feature_set_hash,data_cutoff_ts) VALUES (%s,%s,%s,%s,%s,%s,0.55,0.55,0.50,0.60,'fh',%s) RETURNING id",
                    (fid, self.seed.model_version_id, self.calibrator, market, selection, line, cutoff))
        prediction = scalar(cur)
        cur.execute("INSERT INTO picks.pick_candidates (run_id,fixture_id,prediction_id,market_key,selection,line,bookmaker_id,market_odds,"
                    "p_calibrated,p_market_fair,edge,price_edge,ev,ev_adjusted,decision) VALUES "
                    "(%s,%s,%s,%s,%s,%s,%s,%s,0.55,0.5,0.05,0.01,0.05,0.04,'selected') RETURNING id",
                    (self.seed.run_id, fid, prediction, market, selection, line, self.seed.bookmaker_id, odds))
        candidate = scalar(cur)
        cur.execute(f"INSERT INTO picks.picks ({PICK_COLS}) VALUES (%s,%s,%s,%s,%s,%s,%s,'fh',%s,'shadow-rule-v2','abc',%s,%s,%s,0.55,0.55,0.50,0.60,"
                    "0.5,2.0,0.05,0.01,0.05,0.04,0.01,1,'{}',%s) RETURNING id",
                    (candidate, fid, market, selection, line, self.seed.model_version_id, self.calibrator, cutoff, self.seed.bookmaker_id, odds,
                     created - timedelta(minutes=1), created))
        pick = int(scalar(cur))
        if result is not None:
            cur.execute("INSERT INTO picks.pick_results (pick_id,result_status,profit_units,settled_at,settlement_basis,rule_version) "
                        "VALUES (%s,%s,%s,%s,'regulation_90','settle-v3')", (pick, result, profit, settled))
        return pick

    # ── the whole match ──────────────────────────────────────────────────────────────────────────────────────────────────

    def golden(self, kickoff: datetime = KICKOFF) -> int:
        """The match of the module docstring, with everything."""
        fid = self.match(kickoff)
        self.events(fid, GOLDEN_EVENTS, fetched=kickoff + timedelta(hours=3))
        self.team_stats(fid, "home", shots=14, shots_on_target=6, corners=7, fouls=11, offsides=2, yellow_cards=1, red_cards=1, saves=3,
                        possession_pct=54.5, passes=480, passes_accurate=401, expected_goals=1.874)
        self.team_stats(fid, "away", shots=9, shots_on_target=3, corners=3, fouls=14, offsides=1, yellow_cards=1, red_cards=0, saves=4,
                        possession_pct=45.5, passes=399, passes_accurate=318, expected_goals=0.912)
        self.men(fid, "home", [(501, {"minutes": 90, "rating": 8.1, "is_captain": True, "is_substitute": False, "goals": 1, "assists": 0}),
                               (502, {"minutes": 60, "rating": 5.4, "is_captain": False, "is_substitute": False, "goals": 0, "assists": 0}),
                               (503, {"minutes": 80, "rating": 6.6, "is_captain": False, "is_substitute": False, "goals": 0, "assists": 1}),
                               (504, {"minutes": 10, "rating": 6.9, "is_captain": False, "is_substitute": True, "goals": 0, "assists": 0}),
                               (505, {"minutes": 90, "rating": 8.4, "is_captain": False, "is_substitute": False, "goals": 1, "assists": 0}),
                               (506, {"minutes": 0, "rating": None, "is_captain": False, "is_substitute": True, "goals": 0, "assists": 0})],
                 fetched=kickoff + timedelta(hours=3))
        self.men(fid, "away", [(601, {"minutes": 90, "rating": 6.2, "is_captain": True, "is_substitute": False, "goals": 0, "assists": 0}),
                               (602, {"minutes": 90, "rating": 7.4, "is_captain": False, "is_substitute": False, "goals": 1, "assists": 0}),
                               (603, {"minutes": 90, "rating": 6.0, "is_captain": False, "is_substitute": False, "goals": 0, "assists": 0}),
                               (604, {"minutes": 90, "rating": 6.8, "is_captain": False, "is_substitute": False, "goals": 0, "assists": 0}),
                               (605, {"minutes": 90, "rating": 6.5, "is_captain": False, "is_substitute": False, "goals": 0, "assists": 0}),
                               (606, {"minutes": 90, "rating": 7.0, "is_captain": False, "is_substitute": False, "goals": 0, "assists": 0})],
                 fetched=kickoff + timedelta(hours=3))
        self.sheet(fid, "home", "4-3-3", [501, 502, 503, 505], "Coach Home", kickoff - timedelta(minutes=50))
        self.sheet(fid, "away", "4-4-2", [601, 602, 603, 604, 605, 606], "Coach Away", kickoff - timedelta(minutes=50))
        opening, closing = kickoff - timedelta(days=6), kickoff - timedelta(minutes=20)
        for market, selection, line, p_open, p_close in (("1X2", "Home", 0, 0.45, 0.50), ("1X2", "Draw", 0, 0.27, 0.26), ("1X2", "Away", 0, 0.28, 0.24),
                                                         ("OU", "Over", 2.5, 0.52, 0.55), ("OU", "Under", 2.5, 0.48, 0.45),
                                                         ("BTTS", "Yes", 0, 0.55, 0.58), ("BTTS", "No", 0, 0.45, 0.42)):
            self.quote(fid, market, selection, line, p_open, opening)
            self.quote(fid, market, selection, line, p_close, closing)
        for market, selection, line, prices in (("1X2", "Home", 0, [1.80, 1.85, 1.90, 2.00]), ("1X2", "Draw", 0, [3.4, 3.5, 3.6, 3.8]),
                                                ("1X2", "Away", 0, [4.2, 4.4, 4.5, 5.0]), ("OU", "Over", 2.5, [1.90, 1.95, 2.00]),
                                                ("OU", "Under", 2.5, [1.80, 1.85, 1.90]), ("BTTS", "Yes", 0, [1.80, 1.85]), ("BTTS", "No", 0, [1.90, 1.95])):
            self.final(fid, market, selection, line, prices, kickoff=kickoff)
        pick = self.pick(fid, "1X2", "Home", 0, kickoff=kickoff, settled=kickoff + timedelta(hours=2))
        backed = self.decision(fid, "1X2", "Home", 0, "PICK_PREMIUM", kickoff=kickoff, pick=pick)
        self.outcome(backed, "win", 1.1)
        rejected = self.decision(fid, "OU", "Over", 2.5, "RECHAZADO", odds=1.9, kickoff=kickoff, score=40)
        self.outcome(rejected, "win", 0.9, clv=None)
        self.postmortem(backed, fid)
        return fid
