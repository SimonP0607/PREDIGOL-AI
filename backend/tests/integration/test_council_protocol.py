"""``council-protocol-v1`` (IA-012, shadow) against the real schema, on a world of its OWN (not the session's shared seed): a match with a pass
of the shadow, the specialists' evaluations over its package, the Council's reviews, the prices captured, an owner-signed promotion and a
record of attributions on an earlier match. The deliberation reads them as of a moment, weighs, finds the contradictions, decides the
research round and compares its baseline with the judge - and writes nothing. The transaction is rolled back afterwards."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb
from scripts import ia_council_v2 as cli

from fbi.ai.calendar import local_day
from fbi.council import protocol

pytestmark = pytest.mark.integration

D = Decimal
H = timedelta(hours=1)
KO = datetime.fromisoformat("2026-11-06T20:00:00+00:00")
KNOWN = KO - 6 * H
CREATED = KNOWN + timedelta(minutes=10)
AT = CREATED + timedelta(minutes=5)
PACKAGE = hashlib.sha256(b"council-package").hexdigest()
PIPELINE = "council@council-v1+match-v2+stats-v2"


def one(cur: psycopg.Cursor[Any], sql: str, *args: Any) -> Any:
    row = cur.execute(sql, args).fetchone()
    assert row is not None
    return row[0]


def digest(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class World:
    """The match, built from nothing the other tests share."""

    def __init__(self, conn: psycopg.Connection[Any]) -> None:
        self.conn = conn
        cur = self.cur = conn.cursor()
        comp = one(cur, "INSERT INTO core.competitions (provider_league_id, name, type, entity_scope, competition_type) "
                        "VALUES (99012, 'Council League', 'league', 'club', 'domestic_league') RETURNING id")
        season = one(cur, "INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, 2026) RETURNING id", comp)
        home = one(cur, "INSERT INTO core.teams (provider_team_id, name) VALUES (99121, 'Council Home') RETURNING id")
        away = one(cur, "INSERT INTO core.teams (provider_team_id, name) VALUES (99122, 'Council Away') RETURNING id")
        self.fixture = one(cur, "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at) "
                                "VALUES (990121, %s, %s, %s, %s) RETURNING id", season, home, away, KO)
        self.past = one(cur, "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at) "
                             "VALUES (990122, %s, %s, %s, %s) RETURNING id", season, away, home, KO - timedelta(days=7))
        self.books = [one(cur, "INSERT INTO market.bookmakers (provider_bookmaker_id, name) VALUES (%s, %s) RETURNING id", 99800 + i, f"CB{i}")
                      for i in range(3)]
        self.run = one(cur, "INSERT INTO raw.ingestion_runs (job_name, job_type, status, finished_at) "
                            "VALUES ('council', 'test_council', 'completed', now()) RETURNING id")

    # -- the pass ------------------------------------------------------------------------------------------------------------------------
    def shadow_pass(self, *, known: datetime = KNOWN, created: datetime = CREATED, package: str = PACKAGE) -> int:
        candidates = [
            {"candidate": "c1", "family": "1X2", "market": "1X2", "selection": "Home", "line": "0", "odds": "2.40", "p_model": "0.56",
             "p_market": "0.50", "edge": "0.06", "ev": "0.10"},
            {"candidate": "c2", "family": "OU", "market": "OU", "selection": "Over", "line": "2.5", "odds": "1.90", "p_model": "0.55",
             "p_market": "0.52", "edge": "0.03", "ev": "0.045"},
            {"candidate": "c3", "family": "CORNERS", "market": "CORNERS_OU", "selection": "Over", "line": "9.5", "odds": "1.95",
             "p_model": "0.54", "p_market": "0.51", "edge": "0.03", "ev": "0.05"},
            {"candidate": None, "left_out": "beyond_the_limit", "market": "1X2", "selection": "Away", "line": "0"}]
        contradictions = [{"code": "C01", "subject": "player:7", "candidates": ["c1"], "refs": ["P:shared.absences.home"],
                           "requires": "cite_and_explain"}]
        agents = [{"agent": a, "version": v, "task": t, "status": "ok"} for a, v, t in
                  (("match", "match-v2", "evaluation"), ("stats", "stats-v2", "evaluation"), ("council", "council-v1", "council"))]
        return int(one(self.cur, "INSERT INTO ai.match_runs (fixture_id, run_kind, pass_kind, known_at, created_at, state_version, package_version, "
                                 "package_hash, agents, contradictions, candidates) VALUES (%s, 'shadow', 'pre', %s, %s, 'ms-v1', 'mcp-v1', %s, %s, %s, %s) "
                                 "RETURNING id", self.fixture, known, created, package, Jsonb(agents), Jsonb(contradictions), Jsonb(candidates)))

    def evaluation(self, agent: str, version: str, stances: list[tuple[str, str, list[str]]], *, package: str = PACKAGE,
                   finished: datetime = KNOWN + timedelta(minutes=6), tag: str = "") -> int:
        output = {"contract": "aa-v1", "agent": agent, "mode": "EVALUATION", "data_quality": "GOOD", "signals": [], "research": [],
                  "candidates": [{"candidate": c, "stance": s, "drivers": d, "risks": [], "refs": ["P:shared.absences.home", "E:41"]}
                                 for c, s, d in stances]}
        return int(one(self.cur, "INSERT INTO ai.agent_runs (run_kind, reason, task_kind, pass_kind, fixture_id, started_at, finished_at, known_at, "
                                 "model, agent, agent_version, prompt_version, schema_version, router_version, package_hash, idem_key, output, "
                                 "input_tokens, output_tokens, status) VALUES ('shadow', 'pre pass', 'evaluation', 'pre', %s, %s, %s, %s, "
                                 "'claude-haiku-5-5', %s, %s, 'assess-v1', 'aa-v1', 'router-v1', %s, %s, %s, 100, 20, 'ok') RETURNING id",
                       self.fixture, finished - timedelta(minutes=1), finished, KNOWN, agent, version, package,
                       digest(f"{agent}{version}{package}{finished}{tag}"), Jsonb(output)))

    def review(self, engine: str, verdict: str, *, status: str = "ok", at: datetime = CREATED, selection: str = "Home",
               market: str = "1X2", line: str = "0", candidate: str = "c1") -> int:
        output: dict[str, Any] = {"version": "ma-v1", "engine": engine, "contract": "cd-v1", "candidate": candidate, "verdict": verdict,
                                  "assessment": {"match_evaluation": "SUPPORT", "stats_evaluation": "CONCERN"}, "contradictions": ["C01"]}
        if status == "ok":
            output |= {"confidence_level": "MEDIUM", "drivers": ["ABSENCES"], "risks": [], "refs": ["P:market"]}
        return int(one(self.cur, "INSERT INTO ai.pick_reviews (reviewed_at, fixture_id, market_key, selection, line, engine, engine_version, "
                                 "input_hash, decision, confidence, output, mode, status) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 0.6, %s, "
                                 "'shadow', %s) RETURNING id",
                       at, self.fixture, market, selection, D(line), engine, f"{engine}+match-v2+council-v1+contra-v1+router-v1",
                       digest(f"{engine}{verdict}{at}{selection}"), verdict, Jsonb(output), status))

    def capture(self, before: timedelta, home: str, draw: str, away: str) -> None:
        at = KO - before
        h = f"council-{int(before.total_seconds())}"
        self.cur.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, fetched_at, http_status, file_path, bytes) "
                         "VALUES (%s, %s, '/odds', %s, 200, 'x', 1)", (h, self.run, at))
        for b in self.books:
            for selection, odds in (("Home", home), ("Draw", draw), ("Away", away)):
                self.cur.execute("INSERT INTO market.odds_snapshots (fixture_id, bookmaker_id, market_key, selection, line, odds_decimal, captured_at, "
                                 "minutes_to_ko, source, payload_hash) VALUES (%s, %s, '1X2', %s, 0, %s, %s, %s, 'prematch', %s)",
                                 (self.fixture, b, selection, D(odds), at, int(before.total_seconds() // 60), h))

    def promote(self, model_name: str = PIPELINE, *, family: str = "1X2", at: datetime = KO - timedelta(days=3)) -> None:
        self.cur.execute("INSERT INTO intel.promotions (at, entity, market_key, model_name, entity_id, from_role, to_role, gate_version, criteria, "
                         "reason, decided_by) VALUES (%s, 'agent', %s, %s, NULL, NULL, 'CHAMPION', 'ma-gate-v1', %s, "
                         "'passed the gate of the family with enough selections', 'owner')",
                         (at, family, model_name, Jsonb({"report_hash": "a" * 64})))

    def attribution(self, agent: str, version: str, outcome: str, *, n: int, engine: str = "ma-v1", start: int = 0,
                    computed: datetime = KO - timedelta(days=6)) -> None:
        for i in range(start, start + n):
            self.cur.execute(
                "INSERT INTO intel.agent_attributions (attribution_version, classified_by, fixture_id, market_key, selection, line, engine, agent, "
                "agent_version, signal, stance, outcome, error_class, settled, review_id, postmortem_id, source, computed_at) VALUES "
                "('attr-v1', 'code', %s, '1X2', 'Home', %s, %s, %s, %s, 'VERDICT', 'SUPPORT', %s, %s, %s, 1, 1, 'batch', %s)",
                (self.past, D(i) / 100, engine, agent, version, outcome, "MODEL_ERROR" if outcome == "MISS" else "NONE",
                 "win" if outcome == "HIT" else "loss", computed))

    def standard(self) -> None:
        self.shadow_pass()
        self.evaluation("match", "match-v2", [("c1", "SUPPORT", ["ABSENCES"]), ("c2", "CONCERN", ["FORM"])])
        self.evaluation("stats", "stats-v2", [("c1", "CONCERN", ["LINEUP"]), ("c3", "SUPPORT", ["RATE"])])
        self.review("ma-v1", "DOWNGRADE")
        self.review("ma-v1-h", "ABSTAIN", status="fallback")
        self.capture(26 * H, "2.00", "3.40", "3.80")
        self.capture(6 * H + timedelta(minutes=30), "2.40", "3.40", "3.00")  # before the pass: the market drifts away from Home
        self.promote()
        self.attribution("match", "match-v2", "HIT", n=8)
        self.attribution("match", "match-v2", "MISS", n=2, start=8)
        self.attribution("match", "match-v2", "HIT", n=10, engine="ma-v1-h")  # the same selections in the other arm: counted once
        self.attribution("match", "match-v2", "MISS", n=40, start=50, computed=AT + H)  # written after the moment: not known


@pytest.fixture()
def world(migrated_database: str) -> Iterator[World]:
    conn = psycopg.connect(migrated_database, options="-c TimeZone=UTC")
    try:
        yield World(conn)
    finally:
        conn.rollback()
        conn.close()


def selection(d: protocol.Deliberation, key: str) -> protocol.SelectionReport:
    return next(s for s in d.selections if s.selection.key == key)


def test_the_deliberation_of_a_match_as_of_a_moment(world: World, monkeypatch: pytest.MonkeyPatch) -> None:
    from fbi.ai import usage

    def no_model(*_: Any, **__: Any) -> Any:
        raise AssertionError("the protocol asked a model")

    monkeypatch.setattr(usage, "call_json", no_model)
    world.standard()
    d = protocol.deliberate(world.conn, world.fixture, at=AT)
    assert d.status == "ok" and d.problems == () and [s.selection.key for s in d.selections] == ["c1", "c2", "c3"]

    weights = {(x.agent, x.family): x for x in d.weights}
    assert weights[("match", "1X2")].weight == D("1.2000") and (weights[("match", "1X2")].hits, weights[("match", "1X2")].misses) == (8, 2)
    assert weights[("stats", "1X2")].weight == D("1.0000") and weights[("stats", "1X2")].promoted, "an upstream of the champion, no record"
    assert weights[("match", "OU")].weight == 0 and weights[("stats", "CORNERS")].weight == 0, "nobody is promoted in OU or CORNERS"

    c1 = selection(d, "c1")
    assert c1.market.readable and c1.market.fell, "the fair probability of Home fell by more than three points"
    assert sorted(f.code for f in c1.findings) == ["AA1", "AK1", "AM1", "KN2"]
    assert all(f.material for f in c1.findings if f.code in ("AA1", "AK1", "AM1"))
    aa = next(f for f in c1.findings if f.code == "AA1")
    runs = world.conn.execute("SELECT id FROM ai.agent_runs WHERE fixture_id = %s ORDER BY agent", (world.fixture,)).fetchall()
    assert aa.run_ids == tuple(sorted(int(r[0]) for r in runs)) and aa.refs == ("E:41", "P:shared.absences.home")
    assert c1.research.warranted and c1.selection.contra == ("C01",)
    assert d.round is not None and d.round.requested and d.round.candidates == ("c1",) and d.round.topics == ("availability", "confirmation")
    assert d.round.minutes_to_kickoff == 345
    assert c1.baseline.adjustment.verdict == "FALTA_INFO" and c1.baseline.word == "ABSTAIN", "(1.2 - 1.0) / 2.2: split, and a round to make"
    assert c1.judges["ma-v1"] is not None and c1.judges["ma-v1"].verdict == "RESERVA"
    assert [a.as_json() for a in c1.agreements] == [
        {"engine": "ma-v1", "status": "compared", "verdict_agrees": False, "effect_agrees": False},
        {"engine": "ma-v1-h", "status": "judge_sin_council", "verdict_agrees": None, "effect_agrees": None}]

    c2 = selection(d, "c2")
    assert sorted(f.code for f in c2.findings) == ["AM1", "KN1"] and not any(f.material for f in c2.findings), \
        "the model already reads form; and the match agent weighs nothing in OU"
    assert c2.baseline.adjustment.verdict == "SIN_COUNCIL" and c2.research.reasons == ("no_material_contradiction",)
    assert [a.status for a in c2.agreements] == ["no_judge", "no_judge"]
    c3 = selection(d, "c3")
    assert [f.code for f in c3.findings] == ["KN1"] and c3.market.status == "no_prices"

    doc = d.as_json()
    assert doc["shadow"] is True and doc["research_round"]["requested"] and doc["constants"]["weights"]["max_weight"] == "1.5"
    assert all("adjustment" in s["baseline"] for s in doc["selections"])


def test_the_deliberation_writes_nothing_and_runs_on_a_read_only_transaction(world: World) -> None:
    world.standard()
    tables = ("ai.match_runs", "ai.agent_runs", "ai.pick_reviews", "intel.agent_attributions", "intel.promotions", "intel.decisions")
    before = [world.conn.execute(f"SELECT count(*) FROM {t}").fetchone() for t in tables]
    world.conn.execute("SET LOCAL transaction_read_only = on")  # from here the transaction refuses any write
    d = protocol.deliberate(world.conn, world.fixture, at=AT)
    assert d.status == "ok" and d.round is not None and d.round.requested
    assert [world.conn.execute(f"SELECT count(*) FROM {t}").fetchone() for t in tables] == before


def test_what_is_known_after_the_moment_is_not_read(world: World) -> None:
    world.standard()
    early = protocol.deliberate(world.conn, world.fixture, at=KNOWN - timedelta(minutes=1))
    assert early.status == "no_shadow_pass" and early.selections == ()
    before_review = protocol.deliberate(world.conn, world.fixture, at=CREATED - timedelta(seconds=1))
    assert before_review.status == "no_shadow_pass", "the pass was written at CREATED"
    late_run = world.evaluation("match", "match-v2", [("c1", "REJECT_SIGNAL", ["ABSENCES"])], finished=AT + timedelta(minutes=5), tag="late")
    other = world.evaluation("stats", "stats-v2", [("c1", "REJECT_SIGNAL", ["NEWS"])], package=digest("another package"), tag="other")
    d = protocol.deliberate(world.conn, world.fixture, at=AT)
    used = {p.run_id for s in d.selections for p in s.positions}
    assert late_run not in used and other not in used, "a run finished after the moment, or over another package, is not this pass's"
    later = protocol.deliberate(world.conn, world.fixture, at=AT + timedelta(minutes=10))
    assert late_run in {p.run_id for s in later.selections for p in s.positions}


def test_without_a_promotion_no_voice_weighs_and_nothing_is_material(world: World) -> None:
    world.shadow_pass()
    world.evaluation("match", "match-v2", [("c1", "SUPPORT", ["ABSENCES"])])
    world.evaluation("stats", "stats-v2", [("c1", "REJECT_SIGNAL", ["LINEUP"])])
    world.attribution("match", "match-v2", "HIT", n=30)
    d = protocol.deliberate(world.conn, world.fixture, at=AT)
    assert all(x.weight == 0 and not x.promoted for x in d.weights)
    c1 = selection(d, "c1")
    assert "AA1" in {f.code for f in c1.findings} and not any(f.material for f in c1.findings)
    assert c1.baseline.adjustment.verdict == "SIN_COUNCIL" and d.round is not None and not d.round.requested


def test_an_unknown_fixture_and_an_unreadable_run(world: World) -> None:
    assert protocol.deliberate(world.conn, -5, at=AT).status == "unknown_fixture"
    doc, code = cli.show(world.conn, -5, at=AT)
    assert code == cli.CANNOT and "unknown" in doc["error"]
    world.shadow_pass()
    rid = int(one(world.cur, "INSERT INTO ai.agent_runs (run_kind, reason, task_kind, pass_kind, fixture_id, started_at, finished_at, known_at, "
                             "model, agent, agent_version, prompt_version, schema_version, router_version, package_hash, idem_key, output, "
                             "input_tokens, output_tokens, status) VALUES ('shadow', 'pre pass', 'evaluation', 'pre', %s, %s, %s, %s, "
                             "'claude-haiku-5-5', 'match', 'match-v2', 'assess-v1', 'aa-v1', 'router-v1', %s, %s, %s, 1, 1, 'ok') RETURNING id",
                  world.fixture, KNOWN + timedelta(minutes=1), KNOWN + timedelta(minutes=2), KNOWN, PACKAGE, digest("broken"),
                  Jsonb({"candidates": [{"candidate": "c1", "stance": "SUPPORT"}]})))
    d = protocol.deliberate(world.conn, world.fixture, at=AT)
    assert d.status == "ok" and d.problems == (f"run_unreadable:{rid}",) and all(not s.positions for s in d.selections)


def test_the_command_shows_a_match_and_counts_a_day(world: World) -> None:
    world.standard()
    doc, code = cli.show(world.conn, world.fixture, at=KO + timedelta(days=1))
    assert code == cli.OK and doc["status"] == "ok" and doc["at"] == (KO - timedelta(microseconds=1)).isoformat(), "never past the kick-off"
    assert "c1" in cli.render_show(doc)
    day, code = cli.day(world.conn, local_day(KO), at=KO + timedelta(days=1))
    assert code == cli.OK and day["fixtures"] == 1 and day["deliberated"] == 1 and day["selections"] == 3
    assert day["fixtures_detail"][0]["at"] == CREATED.isoformat(), "each match as of the moment its pass was written"
    assert day["contradictions"]["by_kind"] == {"agent_vs_agent": 1, "agent_vs_model": 2, "agent_vs_market": 1, "already_known": 3}
    assert day["contradictions"]["material_by_kind"] == {"agent_vs_agent": 1, "agent_vs_model": 1, "agent_vs_market": 1, "already_known": 0}
    assert day["research_rounds"]["requested"] == 1 and day["research_rounds"]["topics"] == {"availability": 1, "confirmation": 1}
    assert day["agreement"]["ma-v1"]["compared"] == 1 and day["agreement"]["ma-v1"]["verdict_agrees"] == 0
    assert day["agreement"]["ma-v1-h"]["judge_sin_council"] == 1 and day["baseline"]["SIN_COUNCIL"] == 2
    assert "agreement with ma-v1" in cli.render_day(day)
    empty, _ = cli.day(world.conn, local_day(KO) - timedelta(days=1), at=KO)
    assert empty["fixtures"] == 0 and empty["agreement"]["ma-v1"]["verdict_rate"] is None
