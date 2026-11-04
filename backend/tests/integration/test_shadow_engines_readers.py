"""The shadow of phase 3 beside the readers of production (plan IA, phase 3, A4), on a real database.

Migration 0119 lets ``ai.pick_reviews`` carry the engines ``ma-v1``, ``ma-v1-h`` and ``cs-v1``. Every reader below measured, before the shadow existed,
something the shadow must not move: the candidates and the coverage of Gate A, the reviews and the matches of the costs, the claims the reviews cite for
the gate of research v2, the matches the post-mortems study, the context that filter 6 of the decision layer reads, the reports that open the gate of
enforcement. Each test builds the same world twice - once with the rows of production only, once with the rows of the three shadow engines added
(on the same selections, on selections only they reviewed, on matches only they reviewed, newer and hostile) - and says that the figure is the same.
``tests/unit/test_engine_filter_guard.py`` is the same promise read from the code.

The figures are written by hand into a transaction that is rolled back and the readers only read them: a test of what each reader counts, not evidence
of anything about the agents."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import psycopg
import pytest
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fbi.ai import costs, gate_a, gate_research, gating, postmortem, shadow
from fbi.ai.calendar import local_day
from fbi.ai.config import PRODUCTION_ENGINES, SHADOW_ENGINES, AiSettings
from fbi.ai.evidence import EvidenceIn, store
from fbi.api.services import ai_v2
from fbi.intel import decision, match_review

from .conftest import Seed
from .test_intel import IntelWorld

AT = datetime(2032, 11, 10, 17, 0, tzinfo=UTC)  # 12:00 in Bogotá
D = Decimal


class Reviews:
    """A little world of matches and of reviews of them: ``fixture`` makes a match (finished with a score, or not), ``put`` writes one review."""

    def __init__(self, db: psycopg.Connection[Any], seed: Seed) -> None:
        self.db, self.seed, self.n = db, seed, 0

    def fixture(self, kickoff: datetime, *, score: tuple[int, int] | None = None) -> int:
        self.n += 1
        row = self.db.execute(
            "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at) "
            "VALUES (%s, %s, %s, %s, %s) RETURNING id",
            (9_960_000 + self.n, self.seed.season_id, self.seed.home_team_id, self.seed.away_team_id, kickoff)).fetchone()
        assert row is not None
        fixture_id = int(row[0])
        if score is not None:
            self.db.execute("UPDATE core.fixtures SET status_short = 'FT', status_group = 'finished' WHERE id = %s", (fixture_id,))
            self.db.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away) VALUES (%s, %s, %s)", (fixture_id, *score))
        return fixture_id

    def put(self, fixture_id: int, engine: str, *, at: datetime, selection: str = "Home", market: str = "1X2", line: str = "0",
            decision: str = "APPROVE", status: str = "ok", version: str = "r-v1", output: dict[str, Any] | None = None,
            evidence_ids: list[int] | None = None, priced: bool = False) -> int:
        row = self.db.execute(
            "INSERT INTO ai.pick_reviews (reviewed_at, fixture_id, market_key, selection, line, odds, p_model, p_market, engine, engine_version, "
            "input_hash, decision, confidence, output, evidence_ids, mode, status) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, 'h', %s, 0.6, %s, %s, "
            "'shadow', %s) RETURNING id",
            (at, fixture_id, market, selection, line, D("2.10") if priced else None, D("0.55") if priced else None, D("0.46") if priced else None,
             engine, version, decision, Jsonb({} if output is None else output), evidence_ids or [], status)).fetchone()
        assert row is not None
        return int(row[0])


@pytest.fixture()
def world(db: psycopg.Connection[Any], seed: Seed) -> Reviews:
    return Reviews(db, seed)


def rows(db: psycopg.Connection[Any], sql: str, **params: Any) -> list[dict[str, Any]]:
    with db.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


# ── Gate A: the candidates of production ──────────────────────────────────────────────────────────────────────────

def test_the_candidates_of_gate_a_are_the_selections_production_reviewed(world: Reviews) -> None:
    f1, f2 = world.fixture(AT + timedelta(hours=6)), world.fixture(AT + timedelta(hours=7))
    for engine in PRODUCTION_ENGINES:
        world.put(f1, engine, selection="s1", at=AT)
    world.put(f2, "rules", selection="s2", at=AT)
    day = local_day(AT)
    before = gate_a.coverage(world.db, day, day)
    assert (before.selections, before.selections_llm) == (2, 1), "s1 was reviewed by the model, s2 by the rules alone"

    for engine in SHADOW_ENGINES:
        world.put(f1, engine, selection="s1", at=AT)  # the same selection
        world.put(f2, engine, selection="s2", at=AT)  # one production reviewed without a model
        world.put(f2, engine, selection=f"only-{engine}", at=AT)  # one nobody else reviewed
        world.put(f1, engine, selection=f"newer-{engine}", at=AT + timedelta(minutes=5), decision="REJECT")
    after = gate_a.coverage(world.db, day, day)
    assert after == before, "the shadow is not a candidate, and no model review of the shadow is the model review of production"
    assert after.rates["candidates_reviewed"] == before.rates["candidates_reviewed"] == D("0.5")


def test_the_candidates_of_gate_a_are_still_counted_when_only_production_reviewed_them(world: Reviews) -> None:
    """The control: the filter takes nothing from production."""
    f = world.fixture(AT + timedelta(hours=6))
    for k in range(5):
        world.put(f, "rules", selection=f"s{k}", at=AT)
    world.put(f, "llm", selection="s0", at=AT)
    world.put(f, "combined", selection="s7", at=AT)
    day = local_day(AT)
    got = gate_a.coverage(world.db, day, day)
    assert (got.selections, got.selections_llm) == (6, 1)


# ── the costs: the reviews of production ──────────────────────────────────────────────────────────────────────────

def figures(world: Reviews) -> dict[str, int]:
    [row] = rows(world.db, costs.REVIEWS_SQL, since=AT - timedelta(hours=12), until=AT + timedelta(hours=1))
    return {k: int(v) for k, v in row.items()}


def test_the_reviews_the_costs_count_are_those_of_production_and_so_are_the_matches_they_were_for(world: Reviews) -> None:
    f1 = world.fixture(AT + timedelta(hours=6))
    only_shadow = world.fixture(AT + timedelta(hours=7))
    world.put(f1, "rules", at=AT)
    world.put(f1, "llm", at=AT)
    world.put(f1, "combined", at=AT, version="rules-review-v1+review-v1")
    world.put(f1, "combined", selection="Away", at=AT, version="rules-review-v1+none")
    before = figures(world)
    assert before == {"llm_reviews": 1, "reviews": 2, "approved_with_llm": 1, "fixtures_reviewed": 1}

    for engine in SHADOW_ENGINES:
        world.put(f1, engine, at=AT, version="ma-v1+x")
        world.put(only_shadow, engine, at=AT, version="ma-v1+x")  # a match only the shadow reviewed is not a match reviewed
    assert figures(world) == before


def test_the_summary_of_the_costs_does_not_move_for_the_shadow(world: Reviews) -> None:
    f = world.fixture(AT + timedelta(hours=6))
    world.put(f, "llm", at=AT)
    world.put(f, "combined", at=AT, version="rules-review-v1+review-v1")
    settings = AiSettings(mode="shadow")

    def periods() -> dict[str, dict[str, Any]]:
        return {name: {k: v for k, v in p.items() if k in ("reviews", "llm_reviews", "approved_with_llm", "cost_per_review", "cost_per_approved")}
                for name, p in costs.summary(world.db, at=AT, settings=settings)["periods"].items()}

    before = periods()
    assert before["today"] == {"reviews": 1, "llm_reviews": 1, "approved_with_llm": 1, "cost_per_review": 0.0, "cost_per_approved": 0.0}
    for engine in SHADOW_ENGINES:
        world.put(f, engine, at=AT, version="ma-v1+x")
    assert periods() == before


# ── the gate of research v2: the reviews that cite a claim of it ──────────────────────────────────────────────────

def typed_claim(world: Reviews, fixture_id: int) -> int:
    when = AT - timedelta(hours=2)
    item = EvidenceIn(fixture_id=fixture_id, team_id=world.seed.home_team_id, kind="injury", claim="Delantero: out", origin="web", source_name="Marca",
                      retrieved_at=when, story_key=f"v2:{fixture_id}:home:delantero:injury:out", assertion="out", source_tier="media",
                      source_url=f"https://www.marca.com/futbol/{fixture_id}.html", published_at=when - timedelta(hours=1),
                      attributes={"player_name": "Delantero"}, claim_type="OUT", subject_type="PLAYER", subject_id=77,
                      fresh_until=when + timedelta(hours=24))
    evidence_id, created = store(world.db, item, at=when)
    assert created
    return evidence_id


def test_a_review_of_the_shadow_that_cites_a_claim_of_research_v2_does_not_fail_the_gate_that_says_no_review_does(world: Reviews) -> None:
    f = world.fixture(AT + timedelta(hours=6))
    claim = typed_claim(world, f)
    day = local_day(AT)
    for engine in SHADOW_ENGINES:
        world.put(f, engine, selection=f"s-{engine}", at=AT, evidence_ids=[claim])
    check = gate_research.check_invisible(world.db, day, day)
    assert check.ok is True and check.detail == {"reviews_citing": 0, "decisions_citing": 0}

    world.put(f, "llm", selection="s-llm", at=AT, evidence_ids=[claim])  # the control: a review of production that cites it is still one
    world.put(f, "combined", selection="s-llm", at=AT, evidence_ids=[claim])
    check = gate_research.check_invisible(world.db, day, day)
    assert check.ok is False and check.detail == {"reviews_citing": 2, "decisions_citing": 0}


# ── the post-mortems: the matches with something to study ─────────────────────────────────────────────────────────

KICKOFF = AT - timedelta(days=1)


def due(world: Reviews, sql: str, version: str) -> set[int]:
    window = {"since": AT - timedelta(days=7), "until": AT - timedelta(hours=3), "version": version, "limit": 100}
    return {int(r["id"]) for r in rows(world.db, sql, **window)}


def test_a_match_only_the_shadow_reviewed_has_nothing_to_study_for_either_post_mortem(world: Reviews) -> None:
    only_shadow = world.fixture(KICKOFF, score=(2, 1))
    produced = world.fixture(KICKOFF + timedelta(hours=1), score=(1, 1))
    both = world.fixture(KICKOFF + timedelta(hours=2), score=(0, 1))
    for engine in SHADOW_ENGINES:
        world.put(only_shadow, engine, at=KICKOFF - timedelta(hours=3))
        world.put(both, engine, at=KICKOFF - timedelta(hours=3))
    world.put(produced, "rules", at=KICKOFF - timedelta(hours=3))
    world.put(both, "combined", at=KICKOFF - timedelta(hours=3))
    assert due(world, postmortem.DUE_SQL, postmortem.VERSION) == {produced, both}
    assert due(world, match_review.DUE_SQL, match_review.VERSION) == {produced, both}


@pytest.mark.parametrize("engine", ["rules", "llm", "combined"])
def test_each_engine_of_production_makes_a_match_due(world: Reviews, engine: str) -> None:
    f = world.fixture(KICKOFF, score=(2, 1))
    world.put(f, engine, at=KICKOFF - timedelta(hours=3))
    assert due(world, postmortem.DUE_SQL, postmortem.VERSION) == {f} == due(world, match_review.DUE_SQL, match_review.VERSION)


def test_the_post_mortems_study_nothing_and_remember_nothing_of_a_match_only_the_shadow_reviewed(world: Reviews) -> None:
    f = world.fixture(KICKOFF, score=(2, 1))
    for engine in SHADOW_ENGINES:
        world.put(f, engine, at=KICKOFF - timedelta(hours=3), priced=True)
    report = postmortem.run_postmortems(world.db, at=AT, settings=AiSettings(mode="shadow"))
    assert (report.fixtures, report.memory_events, report.narratives, report.errors) == (0, 0, 0, [])
    reviewed = match_review.review_matches(world.db, at=AT)
    assert (reviewed.matches, reviewed.memory_events, reviewed.errors) == (0, 0, [])
    for table in ("ai.postmortems", "ai.memory_events", "intel.match_postmortems"):
        assert world.db.execute(f"SELECT count(*) FROM {table}").fetchone() == (0,), table


# ── filter 6 of the decision layer ────────────────────────────────────────────────────────────────────────────────

def judged(db: psycopg.Connection[Any], fixture_id: int) -> tuple[decision.World, dict[decision.Key, dict[str, Any]]]:
    """What the decision layer reads at ``AT`` and what it concludes of each selection: the state, the reasons, every filter and the context."""
    read = decision.read_world(db, [fixture_id], at=AT)
    out: dict[decision.Key, dict[str, Any]] = {}
    for key, models in decision.load_candidates(db, at=AT).items():
        e = decision.evaluate(read, key, models)
        out[key] = {"state": e.state, "reasons": e.reasons, "filters": e.filters, "context": e.context.as_json()}
    return read, out


def context_filter(verdict: dict[str, Any]) -> dict[str, Any]:
    [f] = [f for f in verdict["filters"] if f["key"] == "context"]
    return f


def hostile(engine: str) -> dict[str, Any]:
    return {"reason": f"{engine} says no", "decision": "REJECT", "negative_evidence": [{"code": "fixture_not_playable", "severity": "hard"}],
            "uncertainties": [{"code": "shadow_only_code", "severity": "soft"}]}


def priced_selections(db: psycopg.Connection[Any], seed: Seed) -> tuple[int, dict[str, decision.Key]]:
    """A match five hours away with three priced picks: ``A`` (Over 2.5), ``B`` (Over 3.5) and ``C`` (both teams score)."""
    intel = IntelWorld(db, seed)
    fid = intel.fixture(AT + timedelta(hours=5))
    for market, selection, line, p_model, p_market, odds in (("OU", "Over", "2.5", 0.66, 0.50, 2.10), ("OU", "Over", "3.5", 0.50, 0.38, 2.40),
                                                             ("BTTS", "Yes", "0", 0.66, 0.52, 2.05)):
        intel.pick(fid, market, selection, line, p_model=p_model, p_market=p_market, odds=odds, created=AT - timedelta(minutes=30))
        intel.consensus(fid, market, selection, line, p_fair=p_market, best=odds, as_of=AT - timedelta(minutes=10))
    return fid, {"A": (fid, "OU", "Over", D("2.50")), "B": (fid, "OU", "Over", D("3.50")), "C": (fid, "BTTS", "Yes", D("0.00"))}


def test_filter_6_of_the_decision_layer_never_reads_an_engine_of_the_shadow(db: psycopg.Connection[Any], seed: Seed) -> None:
    fid, keys = priced_selections(db, seed)
    reviews = Reviews(db, seed)
    where = {"A": ("OU", "Over", "2.5"), "B": ("OU", "Over", "3.5"), "C": ("BTTS", "Yes", "0")}
    before = AT - timedelta(minutes=20)
    # production: A has a combined review and the rules' findings, B only a combined review (no findings of the rules), C nothing at all
    combined_a = reviews.put(fid, "combined", market="OU", selection="Over", line="2.5", at=before, output={"reason": "nothing against it"})
    rules_a = reviews.put(fid, "rules", market="OU", selection="Over", line="2.5", at=before,
                          output={"uncertainties": [{"code": "thin_market_note", "severity": "soft"}]})
    combined_b = reviews.put(fid, "combined", market="OU", selection="Over", line="3.5", at=before)
    read0, judged0 = judged(db, fid)
    assert set(judged0) == set(keys.values())
    assert set(read0.reviews) == {keys["A"], keys["B"]} and set(read0.rules) == {keys["A"]}
    assert read0.reviews[keys["A"]]["id"] == combined_a and read0.rules[keys["A"]]["id"] == rules_a and read0.reviews[keys["B"]]["id"] == combined_b
    assert judged0[keys["A"]]["context"]["signals"] == {"thin_market_note": "soft"} and judged0[keys["B"]]["context"]["signals"] == {}
    assert judged0[keys["C"]]["context"]["review"] is None and judged0[keys["C"]]["context"]["status"] == "PENDING"
    assert all(context_filter(v)["ok"] is True for v in judged0.values())

    # the shadow, hostile and NEWER than everything production wrote: three engines, on all three selections, a REJECT and a hard stop code each
    shadow_ids = [reviews.put(fid, engine, market=m, selection=sel, line=line, at=AT - timedelta(minutes=5), decision="REJECT", output=hostile(engine))
                  for engine in SHADOW_ENGINES for m, sel, line in where.values()]
    assert len(shadow_ids) == 9
    read1, judged1 = judged(db, fid)
    assert read1.reviews == read0.reviews and read1.rules == read0.rules, "the world the layer reads has no row of the shadow"
    assert not {int(r["id"]) for r in [*read1.reviews.values(), *read1.rules.values()]} & set(shadow_ids)
    assert judged1 == judged0, "and what it concludes - every filter, the context, the state - is what it concluded without them"
    assert judged1[keys["C"]]["context"]["review"] is None, "a selection only the shadow reviewed is a selection nobody has read"
    assert all("shadow_only_code" not in v["context"]["signals"] for v in judged1.values())


def test_the_control_of_filter_6_a_newer_review_of_production_does_move_it(db: psycopg.Connection[Any], seed: Seed) -> None:
    """Without this one the test above could pass because nothing a review says reaches filter 6 at all."""
    intel = IntelWorld(db, seed)
    fid = intel.fixture(AT + timedelta(hours=5))
    intel.pick(fid, "OU", "Over", "2.5", p_model=0.66, p_market=0.50, odds=2.10, created=AT - timedelta(minutes=30))
    intel.consensus(fid, "OU", "Over", "2.5", p_fair=0.50, best=2.10, as_of=AT - timedelta(minutes=10))
    reviews = Reviews(db, seed)
    key = (fid, "OU", "Over", D("2.50"))
    reviews.put(fid, "combined", market="OU", selection="Over", line="2.5", at=AT - timedelta(minutes=20))
    _, before = judged(db, fid)
    assert context_filter(before[key])["ok"] is True

    rejected = reviews.put(fid, "combined", market="OU", selection="Over", line="2.5", at=AT - timedelta(minutes=5), decision="REJECT",
                           output={"reason": "baja del portero"})
    after_world, after = judged(db, fid)
    assert after_world.reviews[key]["id"] == rejected
    assert context_filter(after[key]) | {"why": ""} == {"n": 6, "key": "context", "ok": False, "why": "", "effect": "CAUTELA"}
    assert "ai_reject" in after[key]["reasons"]

    reviews.put(fid, "rules", market="OU", selection="Over", line="2.5", at=AT - timedelta(minutes=4),
                output={"negative_evidence": [{"code": "fixture_not_playable", "severity": "hard"}]})
    _, stopped = judged(db, fid)
    assert context_filter(stopped[key])["effect"] == "RECHAZADO" and "context_stop" in stopped[key]["reasons"], "the rules' findings do reach it"


# ── the reports: the gate of enforcement and the comparison of the console ────────────────────────────────────────

def report(db: psycopg.Connection[Any], engine: str, verdict: str, *, created: datetime) -> None:
    db.execute("INSERT INTO ai.shadow_reports (created_at, window_from, window_to, engine, arms, gate, version) VALUES (%s, %s, %s, %s, %s, %s, 'ai-gate-v2')",
               (created, (created - timedelta(days=60)).date(), created.date(), engine, Jsonb({"model": {"n": 1}, "model_ai": {"n": 1}}),
                Jsonb({"verdict": verdict, "checks": {}})))


def test_the_gate_of_enforcement_is_the_report_of_combined_and_of_no_shadow_engine(db: psycopg.Connection[Any]) -> None:
    enforce = AiSettings(mode="enforce")
    assert gating.enforcement(db, enforce).reason == "no_shadow_report"
    for k, engine in enumerate(SHADOW_ENGINES):
        report(db, engine, "pass", created=AT - timedelta(hours=k))
    got = gating.enforcement(db, enforce)
    assert (got.enforced, got.reason) == (False, "no_shadow_report"), "three reports that passed, none of them the one that counts"

    report(db, "combined", "fail", created=AT - timedelta(days=3))
    got = gating.enforcement(db, enforce)
    assert (got.enforced, got.reason) == (False, "shadow_gate_not_passed")
    report(db, "combined", "pass", created=AT - timedelta(days=2))
    assert gating.enforcement(db, enforce).enforced is True
    for k, engine in enumerate(SHADOW_ENGINES):
        report(db, engine, "fail", created=AT - timedelta(hours=k))  # newer, and failing: they do not switch the enforcement off either
    got = gating.enforcement(db, enforce)
    assert (got.enforced, got.reason) == (True, "enforced")
    assert gating.enforcement(db, AiSettings(mode="shadow")).reason == "mode_shadow"


def settle(world: Reviews, engines: tuple[str, ...], *, days: int = 4, decisions: tuple[str, ...] = ("APPROVE", "REJECT")) -> None:
    """``days`` finished matches (2-1) each reviewed before kick-off by every engine of ``engines``, with a price: settled selections for the report."""
    for k in range(days):
        kickoff = AT - timedelta(days=2 + k)
        f = world.fixture(kickoff, score=(2, 1))
        for engine in engines:
            world.put(f, engine, at=kickoff - timedelta(hours=3), decision=decisions[k % len(decisions)], priced=True)


def test_a_report_is_written_for_an_engine_of_the_shadow_only_once_it_has_settled_selections(world: Reviews) -> None:
    db = world.db
    nothing = shadow.run_shadow(db, at=AT)
    assert sorted(nothing.reports) == ["combined", "rules"], "as ever when nothing has settled: llm waits for a model, the shadow for its first match"
    assert db.execute("SELECT count(*) FROM ai.shadow_reports").fetchone() == (2,)

    settle(world, PRODUCTION_ENGINES)
    f_open = world.fixture(AT + timedelta(hours=5))  # the shadow reviewed a match that has not been played: nothing to judge yet
    for engine in SHADOW_ENGINES:
        world.put(f_open, engine, at=AT, priced=True)
    production_only = shadow.run_shadow(db, at=AT, store=False)
    assert sorted(production_only.reports) == ["combined", "llm", "rules"]

    settle(world, ("ma-v1", "cs-v1"), days=3)
    got = shadow.run_shadow(db, at=AT)
    assert sorted(got.reports) == ["combined", "cs-v1", "llm", "ma-v1", "rules"], "no report for ma-v1-h: it has no settled selection"
    for engine in PRODUCTION_ENGINES:
        assert got.reports[engine] == production_only.reports[engine], f"{engine}: its arms and its gate are what they were"
    assert got.reports["ma-v1"]["arms"]["model"]["n"] == 3 == got.reports["cs-v1"]["arms"]["model"]["n"]
    assert got.reports["rules"]["arms"]["model"]["n"] == 4 == got.reports["combined"]["arms"]["model"]["n"]
    assert got.reports["ma-v1"]["gate"]["verdict"] == "insufficient"
    stored = {r[0] for r in db.execute("SELECT DISTINCT engine FROM ai.shadow_reports WHERE created_at = %s", (AT,))}
    assert stored == {"combined", "cs-v1", "llm", "ma-v1", "rules"}


def test_the_listing_of_the_reports_shows_the_shadow_and_the_comparison_of_the_console_does_not(world: Reviews) -> None:
    db = world.db
    settle(world, PRODUCTION_ENGINES)
    shadow.run_shadow(db, at=AT)
    before = ai_v2.comparison(db).data.model_dump(mode="json")
    assert [row["n"] for row in before["rows"]] == [4, 2, 2, 4], "the model alone, with the rules, with the AI, the market: over the same four matches"
    assert {r["engine"] for r in shadow.latest(db)} == {"rules", "llm", "combined"}

    settle(world, SHADOW_ENGINES, days=5)
    shadow.run_shadow(db, at=AT)
    assert {r["engine"] for r in shadow.latest(db)} == {"rules", "llm", "combined", *SHADOW_ENGINES}, "the reports are in the listing (the console shows them)"
    assert ai_v2.comparison(db).data.model_dump(mode="json") == before, "and not in the comparison of MODELO SOLO / REGLAS / IA / MERCADO"


def test_each_engine_is_evaluated_over_its_own_selections(world: Reviews) -> None:
    settle(world, ("ma-v1",), days=2)
    settle(world, ("ma-v1-h",), days=3)
    settle(world, ("rules",), days=1)
    since, until = AT - timedelta(days=60), AT
    sizes = {engine: len(shadow.load(world.db, engine=engine, since=since, until=until)) for engine in shadow.ENGINES}
    assert sizes == {"rules": 1, "llm": 0, "combined": 0, "ma-v1": 2, "ma-v1-h": 3, "cs-v1": 0}
