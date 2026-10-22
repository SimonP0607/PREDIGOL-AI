"""What the neutral-venue verdicts flow into, on a real database (plan F0, defect 1).

``test_neutral_venue_db`` holds the verdicts, the switch and what the database refuses. Here the verdict is followed
through the places that produce it and the places that read it: a payload stored by the ingestion carries its verdict
(and a classifier that fails costs the payload nothing), the AI packet and the real-time forecast change only while a
person has put the rule in force, the command an operator types does what it says (and nothing it does not), and the
before/after backtest reads the database the way the in-memory comparison reads its lists. Every test runs in a
transaction that is rolled back."""

from __future__ import annotations

import json
from datetime import datetime, timedelta
from functools import partial
from pathlib import Path
from typing import Any

import psycopg
import pytest
from scripts import neutral_rule

from fbi.ai.packet import PacketBuilder
from fbi.backtesting.neutral_ab import evaluate, run_ab
from fbi.catalog import neutral_store as ns
from fbi.features.data import MatchRecord
from fbi.ingestion import apply as ingestion_apply
from fbi.ingestion.apply import apply_fixtures_payload
from fbi.predictions.forecast import forecast_upcoming
from fbi.providers.api_football.normalize import iter_fixture_results, iter_fixtures
from tests.integration.neutral_world import (
    NOW,
    World,
    justified_run,
    make_world,
    one,
    read,
    verdicts,
)
from tests.integration.test_pick_pipeline import AT, league  # noqa: F401 (fixture)
from tests.neutral_synth import SCALED
from tests.neutral_synth import world as synthetic_world

pytestmark = pytest.mark.integration


@pytest.fixture()
def world(db: psycopg.Connection[Any]) -> World:
    return make_world(db)


# ------------------------------------------------------------------------------------------------------ the ingestion

CUP = (98_702, 2025)  # the provider's league id and season of the world's cup
LEAGUE = (98_701, 2025)
GREENS, YELLOWS, BLUES, REDS = (987_103, "Greens"), (987_104, "Yellows"), (987_101, "Blues"), (987_102, "Reds")
ARENA = (987_205, "Neutral Arena", "Birmingham")
GREENS_PARK = (987_203, "Greens Park", "Leeds")
KICKOFF = NOW + timedelta(days=5)
FETCHED = NOW + timedelta(days=1)


class Parsers:
    """The two pure parsing methods of the provider: all ``apply_fixtures_payload`` asks of it. No client, no network."""

    def parse_fixtures(self, body: dict[str, Any]) -> list[Any]:
        return list(iter_fixtures(body))

    def parse_results(self, body: dict[str, Any]) -> list[Any]:
        return list(iter_fixture_results(body))


def payload_entry(fid: int, *, competition: tuple[int, int], round_: str, home: tuple[int, str], away: tuple[int, str],
                  venue: tuple[int, str, str] | None) -> dict[str, Any]:
    blank = {"home": None, "away": None}
    return {
        "fixture": {"id": fid, "date": KICKOFF.isoformat(), "status": {"short": "NS"},
                    "venue": {} if venue is None else {"id": venue[0], "name": venue[1], "city": venue[2]}},
        "league": {"id": competition[0], "season": competition[1], "round": round_},
        "teams": {"home": {"id": home[0], "name": home[1]}, "away": {"id": away[0], "name": away[1]}},
        "goals": dict(blank),
        "score": {"halftime": dict(blank), "fulltime": dict(blank), "extratime": dict(blank), "penalty": dict(blank)},
    }


def payload(*entries: dict[str, Any]) -> dict[str, Any]:
    return {"response": list(entries), "errors": [], "paging": {"current": 1, "total": 1}}


def register(db: psycopg.Connection[Any], digest: str, fetched_at: datetime) -> None:
    """The payload as the ledger holds it: a fixture names the payload that wrote it, and that is a foreign key."""
    run = one(db, "INSERT INTO raw.ingestion_runs (job_name, job_type, status, finished_at) "
                  "VALUES ('t', 'neutral_flow_test', 'completed', now()) RETURNING id")
    db.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, endpoint, params, fetched_at, http_status, "
               "results_count, file_path, bytes) VALUES (%s, %s, '/fixtures', '{}'::jsonb, %s, 200, 1, %s, 1) "
               "ON CONFLICT (hash) DO NOTHING", (digest, run, fetched_at, f"test/{digest}.json.gz"))


def apply(db: psycopg.Connection[Any], world: World, body: dict[str, Any], *, digest: str,
          fetched_at: datetime = FETCHED) -> ingestion_apply.PayloadOutcome:
    register(db, digest, fetched_at)
    seasons = {CUP: world.cup_season, LEAGUE: world.league_season}
    return apply_fixtures_payload(db, Parsers(), body, payload_hash=digest, fetched_at=fetched_at,  # type: ignore[arg-type]
                                  season_ids=seasons)


def fixture_of(db: psycopg.Connection[Any], provider_id: int) -> int:
    return int(one(db, "SELECT id FROM core.fixtures WHERE provider_fixture_id = %s", (provider_id,)))


FINAL = 9_880_001


def final_between_greens_and_yellows(venue: tuple[int, str, str] | None) -> dict[str, Any]:
    return payload(payload_entry(FINAL, competition=CUP, round_="Final", home=GREENS, away=YELLOWS, venue=venue))


def test_a_payload_stores_the_verdict_of_its_fixtures_with_them(db: psycopg.Connection[Any], world: World) -> None:
    out = apply(db, world, final_between_greens_and_yellows(ARENA), digest="h1")
    assert (out.ours, out.fixtures_inserted, out.venue_verdicts_written) == (1, 1, 1)
    fid = fixture_of(db, FINAL)
    assert verdicts(db)[fid] == (True, "decider_ground"), "a final at a ground that is neither side's"
    assert ns.rule_in_force(db) is None and read(db)[fid] is False, "stored, and read by no model until promoted"


def test_applying_the_same_payload_again_writes_no_verdict(db: psycopg.Connection[Any], world: World) -> None:
    body = final_between_greens_and_yellows(ARENA)
    apply(db, world, body, digest="h1")
    fid = fixture_of(db, FINAL)
    stamp = one(db, "SELECT classified_at FROM core.fixture_venue_class WHERE fixture_id = %s", (fid,))
    again = apply(db, world, body, digest="h1")
    assert again.fixtures_inserted == 0 and again.venue_verdicts_written == 0
    assert one(db, "SELECT classified_at FROM core.fixture_venue_class WHERE fixture_id = %s", (fid,)) == stamp, (
        "a replay does not touch a verdict it would not change")


def test_a_payload_that_corrects_the_ground_corrects_the_verdict(db: psycopg.Connection[Any], world: World) -> None:
    apply(db, world, final_between_greens_and_yellows(ARENA), digest="h1")
    fid = fixture_of(db, FINAL)
    assert verdicts(db)[fid][0] is True
    later = apply(db, world, final_between_greens_and_yellows(GREENS_PARK), digest="h2",
                  fetched_at=FETCHED + timedelta(hours=3))
    assert (later.fixtures_updated, later.venue_verdicts_written) == (1, 1)
    assert verdicts(db)[fid] == (False, "home_ground"), "the provider now says it is the home side's own ground"


def test_a_payload_with_no_ground_gets_a_verdict_that_says_so(db: psycopg.Connection[Any], world: World) -> None:
    apply(db, world, final_between_greens_and_yellows(None), digest="h1")
    assert verdicts(db)[fixture_of(db, FINAL)] == (False, "no_venue"), "not neutral, and not for lack of looking"


def test_a_league_fixture_in_a_payload_gets_no_verdict(db: psycopg.Connection[Any], world: World) -> None:
    body = payload(payload_entry(9_880_002, competition=LEAGUE, round_="Regular Season - 9", home=BLUES, away=REDS,
                                 venue=ARENA))
    out = apply(db, world, body, digest="h1")
    assert (out.fixtures_inserted, out.venue_verdicts_written) == (1, 0)
    assert fixture_of(db, 9_880_002) not in verdicts(db), "a league match is never neutral by rule"


def test_a_classifier_that_fails_costs_the_payload_nothing_and_says_so(db: psycopg.Connection[Any], world: World,
                                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    class Recorder:
        def __init__(self) -> None:
            self.events: list[tuple[str, dict[str, Any]]] = []

        def exception(self, event: str, **kw: Any) -> None:
            self.events.append((event, kw))

    def breaks(conn: psycopg.Connection[Any], ids: Any, **kw: Any) -> ns.Counts:
        conn.execute("INSERT INTO core.fixture_venue_class (fixture_id, rule_version, neutral, basis) "
                     "VALUES (-1, 'x', false, 'x')")  # a statement the DATABASE refuses: the transaction is poisoned
        raise AssertionError("unreachable")

    recorder = Recorder()
    monkeypatch.setattr(ingestion_apply, "classify_provider_fixtures", breaks)
    monkeypatch.setattr(ingestion_apply, "log", recorder)
    out = apply(db, world, final_between_greens_and_yellows(ARENA), digest="h1")
    assert (out.fixtures_inserted, out.venue_verdicts_written) == (1, 0), "the fixture is stored; the verdict is not"
    fid = fixture_of(db, FINAL)
    assert fid not in verdicts(db)
    assert [e for e, _ in recorder.events] == ["neutral.classify_failed"], "an error is logged, not swallowed"
    assert recorder.events[0][1] == {"fixtures": 1, "payload_hash": "h1"}
    assert one(db, "SELECT 1") == 1, "and the payload's own transaction is still alive"
    # what the failure left undone is what the backfill is for
    monkeypatch.undo()
    assert fid in ns.unclassified_ids(db)
    assert ns.classify_everything(db, at=NOW).written >= 1 and verdicts(db)[fid] == (True, "decider_ground")


# ---------------------------------------------------------------------------------------------------------- the packet


def changed_paths(a: Any, b: Any, path: tuple[str, ...] = ()) -> set[tuple[str, ...]]:
    """Where two nested documents differ."""
    if isinstance(a, dict) and isinstance(b, dict):
        out: set[tuple[str, ...]] = set()
        for key in a.keys() | b.keys():
            out |= changed_paths(a.get(key), b.get(key), (*path, str(key)))
        return out
    return set() if a == b else {path}


def test_the_ai_packet_calls_a_match_neutral_only_while_the_rule_is_in_force(db: psycopg.Connection[Any],
                                                                             world: World) -> None:
    ns.classify_everything(db, at=NOW)
    at = NOW + timedelta(days=9)
    ahead, host = world.ids["ahead"], world.ids["host"]
    off = PacketBuilder(db).build(ahead, at=at)
    assert off is not None
    assert off.content["fixture"]["neutral"] is False and off.content["travel"]["neutral_venue"] is False

    run = justified_run(db)
    ns.promote(db, run.id, by="owner", reason="the backtest justified the rule: better, nowhere worse", who="simon")
    on = PacketBuilder(db).build(ahead, at=at)
    assert on is not None
    assert on.content["fixture"]["neutral"] is True and on.content["travel"]["neutral_venue"] is True
    assert changed_paths(off.content, on.content) <= {("fixture", "neutral"), ("travel", "neutral_venue")}, (
        "the verdict reaches the packet through those two statements and no other")
    other = PacketBuilder(db).build(host, at=at)
    assert other is not None and other.content["fixture"]["neutral"] is False, "a match the rule does not call neutral"

    ns.retire(db, by="owner", reason="a model got worse in production: back to the old reading", who="simon")
    back = PacketBuilder(db).build(ahead, at=at)
    assert back is not None and back.content == off.content, "retired: the packet is what it was before"


# ------------------------------------------------------------------------------------------------------- the forecast

GOAL_MODELS = ("poisson", "dixon_coles")


def forecast_of(db: psycopg.Connection[Any], fixture_id: int) -> dict[tuple[str, str, str, float], tuple[float, str, datetime]]:
    """The newest real-time forecast of each model for a fixture: (model, market, selection, line) -> (probability,
    hash of the inputs it was made from, cut-off)."""
    rows = db.execute(
        """
        SELECT m.name, p.market_key, p.selection, p.line, p.p_calibrated, p.feature_set_hash, p.data_cutoff_ts
          FROM models.predictions p
          JOIN models.model_versions v ON v.id = p.model_version_id
          JOIN models.model_registry m ON m.id = v.model_id
         WHERE p.fixture_id = %s AND p.backtest_session_id IS NULL
           AND p.data_cutoff_ts = (SELECT max(q.data_cutoff_ts) FROM models.predictions q
                                     JOIN models.model_versions w ON w.id = q.model_version_id
                                    WHERE q.fixture_id = p.fixture_id AND w.model_id = v.model_id
                                      AND q.backtest_session_id IS NULL)""", (fixture_id,)).fetchall()
    return {(str(n), str(mk), str(sel), float(line)): (float(p), str(h), ts) for n, mk, sel, line, p, h, ts in rows}


def test_a_forecast_of_a_neutral_match_changes_only_while_the_rule_is_in_force(
    db: psycopg.Connection[Any], league: dict[str, object]  # noqa: F811 (the fixture imported above)
) -> None:
    target = int(league["target"])  # type: ignore[call-overload]
    first = forecast_upcoming(db, at=AT, code_version="pipetest")
    assert first.predicted["poisson"] == 1 and first.predicted["dixon_coles"] == 1
    base = forecast_of(db, target)
    assert {k[0] for k in base} == set(GOAL_MODELS)

    # The rule has decided that this match is at a neutral ground. Nobody has put the rule in force: no forecast moves.
    db.execute("INSERT INTO core.fixture_venue_class (fixture_id, rule_version, neutral, basis, evidence) "
               "VALUES (%s, %s, true, 'decider_ground', '{}')", (target, ns.RULE_VERSION))
    quiet = forecast_upcoming(db, at=AT + timedelta(hours=1), code_version="pipetest")
    assert quiet.written == 0 and quiet.unchanged >= 2 and quiet.feature_sets_written == 0
    assert forecast_of(db, target) == base, "a stored verdict is not an input to any model until the switch is on"

    # In force: the goal models price it without a home advantage, from inputs that now say so.
    run = justified_run(db)
    ns.promote(db, run.id, by="owner", reason="the backtest justified the rule: better, nowhere worse", who="simon")
    on = forecast_upcoming(db, at=AT + timedelta(hours=2), code_version="pipetest")
    assert on.predicted["poisson"] == 1 and on.predicted["dixon_coles"] == 1 and on.written > 0
    assert on.feature_sets_written == 1, "the Elo vector of the match is stored again: its inputs changed"
    neutral = forecast_of(db, target)
    for kind in GOAL_MODELS:
        home, away = (kind, "1X2", "Home", 0.0), (kind, "1X2", "Away", 0.0)
        assert neutral[home][0] < base[home][0] and neutral[away][0] > base[away][0], (
            f"{kind}: without a home advantage the home side is less likely to win")
        assert neutral[home][1] != base[home][1], "and the forecast says it was made from other inputs"
        assert neutral[home][2] == AT + timedelta(hours=2)

    # Retired: back to the old reading, to the last probability, and nothing that was stored is gone.
    ns.retire(db, by="owner", reason="a model got worse in production: back to the old reading", who="simon")
    off = forecast_upcoming(db, at=AT + timedelta(hours=3), code_version="pipetest")
    assert off.predicted["poisson"] == 1 and off.predicted["dixon_coles"] == 1 and off.feature_sets_written == 1
    restored = forecast_of(db, target)
    assert {k: v[1] for k, v in restored.items()} == {k: v[1] for k, v in base.items()}, "the very same inputs as at first"
    assert {v[2] for v in restored.values()} == {AT + timedelta(hours=3)}
    for key, (p, _, _) in restored.items():
        # not bit for bit: the weight of each result in the fit decays with the age of the cut-off, and it is three hours later
        assert p == pytest.approx(base[key][0], abs=1e-4)
    shift = abs(neutral[(GOAL_MODELS[0], "1X2", "Home", 0.0)][0] - base[(GOAL_MODELS[0], "1X2", "Home", 0.0)][0])
    assert shift > 0.02, "and the neutral reading was a real move away from it"
    cutoffs = db.execute("SELECT count(DISTINCT data_cutoff_ts) FROM models.predictions WHERE fixture_id = %s "
                         "AND backtest_session_id IS NULL", (target,)).fetchone()
    assert cutoffs == (3,), "three readings of the same match, each as it was made; none rewritten"


# ------------------------------------------------------------------------------------------------------ the operator


class Session:
    """The test's connection as a command sees it. A command commits what it writes and rolls back a dry run, and neither
    may touch the test's world (which is rolled back at the end, and must not be committed): ``commit()`` here keeps what
    was written inside the test's own transaction and ``rollback()`` discards what the command wrote since the last commit."""

    def __init__(self, conn: psycopg.Connection[Any]) -> None:
        self._conn = conn
        self.commits = 0
        self.rollbacks = 0
        conn.execute("SAVEPOINT command")

    def commit(self) -> None:
        self.commits += 1
        self._conn.execute("RELEASE SAVEPOINT command")
        self._conn.execute("SAVEPOINT command")

    def rollback(self) -> None:
        self.rollbacks += 1
        self._conn.execute("ROLLBACK TO SAVEPOINT command")

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)

    def __enter__(self) -> Session:
        return self

    def __exit__(self, *exc: object) -> None:
        return None


def quiet(_message: str) -> None:
    return None


REASON = "the backtest justified the rule: better, nowhere worse"


def test_show_says_the_switch_is_off_and_what_is_missing(db: psycopg.Connection[Any], world: World) -> None:
    text = "\n".join(neutral_rule.show(db))
    assert "The switch is OFF: no model reads a neutral-venue verdict." in text
    assert "none stored yet" in text and "without a verdict of neutral-v1: 7" in text
    assert "python -m scripts.neutral_rule classify --apply" in text and "none yet" in text


def test_classify_is_a_dry_run_until_it_is_told_to_apply(db: psycopg.Connection[Any], world: World) -> None:
    session = Session(db)
    code, lines = neutral_rule.classify_command(session, everything=False, since=None, until=None, apply=False,  # type: ignore[arg-type]
                                                say=quiet)
    assert code == 0 and lines[0].startswith("DRY RUN") and "3 neutral" in lines[0] and "7 verdicts would be written" in lines[0]
    assert any("decider_ground" in line for line in lines) and lines[-1].startswith("Nothing was written")
    assert verdicts(db) == {} and (session.commits, session.rollbacks) == (0, 1), "decided, reported, and rolled back"

    code, lines = neutral_rule.classify_command(session, everything=False, since=None, until=None, apply=True,  # type: ignore[arg-type]
                                                say=quiet)
    assert code == 0 and lines[0].startswith("APPLIED") and "7 verdicts written" in lines[0]
    assert len(verdicts(db)) == 7 and session.commits >= 1

    code, lines = neutral_rule.classify_command(session, everything=False, since=None, until=None, apply=True,  # type: ignore[arg-type]
                                                say=quiet)
    assert (code, len(lines)) == (0, 1) and "nothing to do" in lines[0]
    code, lines = neutral_rule.classify_command(session, everything=True, since=None, until=None, apply=True,  # type: ignore[arg-type]
                                                say=quiet)
    assert "0 verdicts written" in lines[0] and "3 neutral" in lines[0], "all again: the same verdicts, nothing rewritten"


def test_classify_can_be_limited_to_a_range_of_kick_offs(db: psycopg.Connection[Any], world: World) -> None:
    session = Session(db)
    since, until = NOW - timedelta(days=45), NOW
    code, lines = neutral_rule.classify_command(session, everything=False, since=since, until=until, apply=True,  # type: ignore[arg-type]
                                                say=quiet)
    assert code == 0 and "over 3 non-league fixtures" in lines[0], "the final, the qualifier in Santiago and the one in Rio"
    assert set(verdicts(db)) == {world.ids["final"], world.ids["third"], world.ids["host"]}
    code, lines = neutral_rule.classify_command(session, everything=False, since=None, until=None, apply=False,  # type: ignore[arg-type]
                                                say=quiet)
    assert "over 4 non-league fixtures" in lines[0], "what the range left out is what is still missing"


def test_a_backtest_refuses_to_run_over_part_of_the_labels(db: psycopg.Connection[Any], world: World) -> None:
    code, lines = neutral_rule.backtest_command(db, apply=False, allow_dirty=False, out=None, say=quiet)
    assert code == 3 and "refused: 7 non-league fixtures have no verdict" in lines[0]
    assert ns.runs(db) == []


def test_a_run_is_not_stored_from_code_nobody_can_reproduce(db: psycopg.Connection[Any], world: World,
                                                            monkeypatch: pytest.MonkeyPatch) -> None:
    ns.classify_everything(db, at=NOW)
    monkeypatch.setattr(neutral_rule, "dirty_tree", lambda: [" M src/fbi/features/engine.py"])
    code, lines = neutral_rule.backtest_command(db, apply=True, allow_dirty=False, out=None, say=quiet)
    assert code == 3 and "uncommitted changes" in lines[0] and " M src/fbi/features/engine.py" in lines
    assert ns.runs(db) == []


def test_promoting_asks_before_it_writes_and_says_what_it_would_change(db: psycopg.Connection[Any],
                                                                      world: World) -> None:
    ns.classify_everything(db, at=NOW)
    run = justified_run(db)
    code, lines = neutral_rule.promote_command(db, run_id=run.id, reason=REASON, by=None, confirm=False)
    text = "\n".join(lines)
    assert code == 0 and text.startswith("DRY RUN") and "Putting it in force would change" in text
    assert "3 fixtures are read as neutral from then on: 2 played" in text and "1 still to play" in text
    assert "python -m scripts.build_features --elo-only --apply" in text and "Nothing was written" in text
    assert ns.promoted(db) is None

    code, lines = neutral_rule.promote_command(db, run_id=run.id, reason=REASON, by=None, confirm=True)
    assert code == 2 and "--confirm needs --by" in lines[0] and ns.promoted(db) is None, "a person decides, and is named"

    code, lines = neutral_rule.promote_command(db, run_id=run.id, reason=REASON, by="simon", confirm=True)
    assert code == 0 and "Rule neutral-v1 is in force" in lines[0] and "by simon" in lines[0]
    assert ns.rule_in_force(db) == ns.RULE_VERSION

    code, lines = neutral_rule.promote_command(db, run_id=run.id, reason=REASON, by="simon", confirm=True)
    assert code == 0 and "already in force: nothing written" in lines[0]
    code, lines = neutral_rule.promote_command(db, run_id=run.id, reason=REASON, by=None, confirm=False)
    assert code == 0 and "already in force: nothing would change" in lines[-1]
    assert len(ns.history(db)) == 1


def test_the_dry_run_counts_the_logit_forecasts_that_will_outlive_the_switch(db: psycopg.Connection[Any],
                                                                            world: World) -> None:
    """The ordered logit cannot price a neutral match, so once the rule is in force it writes no newer forecast of one; a
    forecast it made before stays the newest of that model. The person who decides is told how many there are."""
    ns.classify_everything(db, at=NOW)
    run = justified_run(db)
    _, lines = neutral_rule.promote_command(db, run_id=run.id, reason=REASON, by=None, confirm=False)
    assert "ordered logit" not in "\n".join(lines), "none yet"

    model = one(db, "INSERT INTO models.model_registry (name, family, description) VALUES ('elo_ologit', 'rating', "
                    "'test') ON CONFLICT (name) DO UPDATE SET description = EXCLUDED.description RETURNING id")
    version = one(db, "INSERT INTO models.model_versions (model_id, version, train_from, train_to, n_train, "
                      "code_version) VALUES (%s, 'v-neutral-flow-test', '2020-01-01', '2026-09-30', 1000, 'abc') "
                      "RETURNING id", (model,))
    for name in ("ahead", "host"):  # the match still to play, and one that is over (and so not a forecast to outlive)
        db.execute("INSERT INTO models.predictions (fixture_id, model_version_id, market_key, selection, line, p_raw, "
                   "p_calibrated, feature_set_hash, data_cutoff_ts) VALUES (%s, %s, '1X2', 'Home', 0, 0.5, 0.5, 'h', %s)",
                   (world.ids[name], version, NOW))
    _, lines = neutral_rule.promote_command(db, run_id=run.id, reason=REASON, by=None, confirm=False)
    text = "\n".join(lines)
    assert "1 of the matches still to play already hold a forecast of the ordered logit" in text
    assert "remains that model's newest forecast of the match until kick-off" in text

    neutral_rule.promote_command(db, run_id=run.id, reason=REASON, by="simon", confirm=True)
    _, lines = neutral_rule.retire_command(db, reason="a model got worse in production", by=None, confirm=False)
    assert "ordered logit" not in "\n".join(lines), "going back has no such forecast to leave behind"


def test_promoting_refuses_what_the_backtest_did_not_justify(db: psycopg.Connection[Any], world: World) -> None:
    ns.classify_everything(db, at=NOW)
    for verdict in ("inconclusive", "not_justified"):
        run = justified_run(db, verdict=verdict)
        for confirm in (False, True):
            code, lines = neutral_rule.promote_command(db, run_id=run.id, reason=REASON, by="simon", confirm=confirm)
            assert code == 3 and lines[0].startswith("refused:") and f"says '{verdict}'" in lines[0]
    code, lines = neutral_rule.promote_command(db, run_id=999_999, reason=REASON, by="simon", confirm=True)
    assert code == 3 and "no backtest run" in lines[0]
    code, lines = neutral_rule.promote_command(db, run_id=1, reason="short", by="simon", confirm=True)
    assert code == 3 and "at least 10 characters" in lines[0]
    stale = justified_run(db)
    db.execute("UPDATE core.fixtures SET venue_name = 'Blues Park', venue_city = 'London' WHERE id = %s",
               (world.ids["final"],))  # the final is now at the home side's own ground: one label turns
    ns.classify_fixtures(db, [world.ids["final"]], at=NOW + timedelta(hours=1))
    code, lines = neutral_rule.promote_command(db, run_id=stale.id, reason=REASON, by=None, confirm=False)
    assert code == 3 and "verdicts changed since" in lines[0], "even the dry run says the run is about other verdicts"
    assert ns.promoted(db) is None


def test_retiring_asks_before_it_writes_and_leaves_the_verdicts(db: psycopg.Connection[Any], world: World) -> None:
    ns.classify_everything(db, at=NOW)
    code, lines = neutral_rule.retire_command(db, reason=REASON, by="simon", confirm=True)
    assert code == 3 and "nothing to retire" in lines[0]
    run = justified_run(db)
    neutral_rule.promote_command(db, run_id=run.id, reason=REASON, by="simon", confirm=True)

    code, lines = neutral_rule.retire_command(db, reason="a model got worse in production", by=None, confirm=False)
    text = "\n".join(lines)
    assert code == 0 and text.startswith("DRY RUN - retiring neutral-v1") and "no match is neutral" in text
    assert "The verdicts stay stored" in text and ns.rule_in_force(db) == ns.RULE_VERSION
    code, lines = neutral_rule.retire_command(db, reason="a model got worse in production", by=None, confirm=True)
    assert code == 2 and ns.rule_in_force(db) == ns.RULE_VERSION

    code, lines = neutral_rule.retire_command(db, reason="a model got worse in production", by="simon", confirm=True)
    assert code == 0 and "The rule is retired" in lines[0] and ns.rule_in_force(db) is None
    assert len(verdicts(db)) == 7 and not any(read(db).values())
    assert [p.action for p in ns.history(db)] == ["retire", "promote"]


def test_show_tells_the_story_of_the_switch(db: psycopg.Connection[Any], world: World) -> None:
    ns.classify_everything(db, at=NOW)
    run = justified_run(db)
    neutral_rule.promote_command(db, run_id=run.id, reason=REASON, by="simon", confirm=True)
    on = "\n".join(neutral_rule.show(db))
    assert "The switch is ON since" in on and f"rule neutral-v1, backtest run #{run.id}, put in force by simon" in on
    assert "neutral-v1: 7 fixtures, 3 neutral" in on and "without a verdict of neutral-v1: 0" in on
    assert f"* run #{run.id}" in on and "JUSTIFIED (labels unchanged" in on

    neutral_rule.retire_command(db, reason="a model got worse in production", by="simon", confirm=True)
    off = "\n".join(neutral_rule.show(db))
    assert "The switch is OFF since" in off and "retired by owner" in off and "a model got worse in production" in off
    assert "EARLIER:" in off and f"promote rule neutral-v1 (run #{run.id}), by simon" in off

    db.execute("UPDATE core.fixtures SET venue_name = 'Blues Park', venue_city = 'London' WHERE id = %s",
               (world.ids["final"],))  # the final is now at the home side's own ground: one label turns
    ns.classify_fixtures(db, [world.ids["final"]], at=NOW + timedelta(hours=1))
    assert "LABELS CHANGED since: not promotable" in "\n".join(neutral_rule.show(db))


def run_main(session: Session, monkeypatch: pytest.MonkeyPatch, *argv: str) -> int:
    monkeypatch.setattr(neutral_rule.psycopg, "connect", lambda *_a, **_k: session)
    return neutral_rule.main(list(argv))


def test_the_command_line_is_wired_to_those_commands(db: psycopg.Connection[Any], world: World,
                                                     monkeypatch: pytest.MonkeyPatch,
                                                     capsys: pytest.CaptureFixture[str]) -> None:
    session = Session(db)
    assert run_main(session, monkeypatch, "show") == 0
    assert "The switch is OFF" in capsys.readouterr().out

    assert run_main(session, monkeypatch, "classify") == 0
    seen = capsys.readouterr()
    assert "DRY RUN" in seen.out and "decided" in seen.err, "the result on stdout, the progress on stderr"
    assert verdicts(db) == {}

    assert run_main(session, monkeypatch, "classify", "--apply", "--since", "2026-07-01", "--until", "2026-10-02") == 0
    assert "over 6 non-league fixtures" in capsys.readouterr().out and len(verdicts(db)) == 6
    assert run_main(session, monkeypatch, "classify", "--apply") == 0
    assert "over 1 non-league fixtures" in capsys.readouterr().out and len(verdicts(db)) == 7

    run = justified_run(db)
    stale = justified_run(db, verdict="inconclusive")
    assert run_main(session, monkeypatch, "promote", "--run", str(run.id), "--reason", REASON) == 0
    assert "DRY RUN" in capsys.readouterr().out and ns.promoted(db) is None
    before = session.rollbacks
    assert run_main(session, monkeypatch, "promote", "--run", str(stale.id), "--reason", REASON, "--by", "simon",
                    "--confirm") == 3
    refused = capsys.readouterr()
    assert "refused:" in refused.err and refused.out == "", "a refusal goes to stderr and leaves no trace"
    assert session.rollbacks == before + 1 and ns.promoted(db) is None
    assert run_main(session, monkeypatch, "promote", "--run", str(run.id), "--reason", REASON, "--by", "simon",
                    "--confirm") == 0
    assert "is in force" in capsys.readouterr().out and ns.rule_in_force(db) == ns.RULE_VERSION

    assert run_main(session, monkeypatch, "promote", "--reason", REASON) == 2
    assert "promote needs --run ID and --reason TEXT" in capsys.readouterr().err
    assert run_main(session, monkeypatch, "retire") == 2
    assert run_main(session, monkeypatch, "retire", "--reason", "a model got worse in production", "--by", "simon",
                    "--confirm") == 0
    assert "retired" in capsys.readouterr().out and ns.rule_in_force(db) is None


# ---------------------------------------------------------------------------- the backtest, from the database to the switch


def write_synthetic(db: psycopg.Connection[Any], before: list[MatchRecord], after: list[MatchRecord]) -> None:
    """A synthetic world (``tests.neutral_synth``) as rows: every match as a fixture with its result, in one league, and a
    verdict of the rule for each match the ``after`` arm calls neutral. Inserted in the order the matches were made, so the
    ids keep their order."""
    competition = one(db, "INSERT INTO core.competitions (provider_league_id, name, country, type, entity_scope, "
                          "competition_type) VALUES (98790, 'Synthetic League', 'Nowhere', 'league', 'club', "
                          "'domestic_league') RETURNING id")
    seasons = {year: one(db, "INSERT INTO core.competition_seasons (competition_id, season) VALUES (%s, %s) RETURNING id",
                         (competition, year)) for year in sorted({m.season for m in before})}
    teams = {t: one(db, "INSERT INTO core.teams (provider_team_id, name, country) VALUES (%s, %s, 'Nowhere') "
                        "RETURNING id", (9_790_000 + t, f"Synthetic {t}"))
             for t in sorted({m.home_team_id for m in before} | {m.away_team_id for m in before})}
    with db.cursor() as cur:
        cur.executemany(
            "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
            "kickoff_at, status_short, status_group) VALUES (%s, %s, %s, %s, %s, 'FT', 'finished')",
            [(9_791_000 + m.fixture_id, seasons[m.season], teams[m.home_team_id], teams[m.away_team_id], m.kickoff_at)
             for m in before])
        cur.execute("SELECT provider_fixture_id - 9791000, id FROM core.fixtures "
                    "WHERE provider_fixture_id > 9791000 AND provider_fixture_id <= %s", (9_791_000 + len(before),))
        ids = {int(a): int(b) for a, b in cur.fetchall()}
        assert len(ids) == len(before)
        cur.executemany("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away) VALUES (%s, %s, %s)",
                        [(ids[m.fixture_id], m.goals_home, m.goals_away) for m in before])
        cur.executemany("INSERT INTO core.fixture_venue_class (fixture_id, rule_version, neutral, basis, evidence) "
                        "VALUES (%s, %s, true, 'third_country', '{}')",
                        [(ids[m.fixture_id], ns.RULE_VERSION) for m in after if m.is_neutral])


def add_match_still_to_play(db: psycopg.Connection[Any], before: list[MatchRecord]) -> int:
    """A match after the last result, between two of the synthetic sides, that the rule has already called neutral: the
    ingestion decides tomorrow's matches today."""
    last = db.execute("SELECT f.competition_season_id, f.home_team_id, f.away_team_id FROM core.fixtures f "
                      "WHERE f.provider_fixture_id = %s", (9_791_000 + before[-1].fixture_id,)).fetchone()
    assert last is not None
    fid = one(db, "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
                  "kickoff_at, status_short, status_group) VALUES (9799999, %s, %s, %s, %s, 'NS', 'scheduled') "
                  "RETURNING id", (*last, max(m.kickoff_at for m in before) + timedelta(days=3)))
    db.execute("INSERT INTO core.fixture_venue_class (fixture_id, rule_version, neutral, basis, evidence) "
               "VALUES (%s, %s, true, 'third_country', '{}')", (fid, ns.RULE_VERSION))
    return int(fid)


def test_the_backtest_reads_the_database_the_way_the_comparison_reads_its_lists(db: psycopg.Connection[Any]) -> None:
    before, after = synthetic_world(2, share=0.3, really_neutral=True)
    write_synthetic(db, before, after)
    add_match_still_to_play(db, before)
    stored = run_ab(db, rule=ns.RULE_VERSION, protocol=SCALED)
    direct = evaluate(before, after, {m.fixture_id: "third_country" for m in after if m.is_neutral}, SCALED,
                      labels=stored.labels)
    assert stored.decision.verdict == direct.decision.verdict == "justified"
    assert stored.primary is not None and direct.primary is not None
    for mine, theirs in ((stored.primary, direct.primary), (stored.control, direct.control),
                         (stored.guards["poisson"], direct.guards["poisson"])):
        assert mine is not None and theirs is not None and mine.n == theirs.n
        for field in ("diff", "lo", "hi", "loss_a", "loss_b", "brier_a", "brier_b", "ece_a", "ece_b"):
            assert getattr(mine, field) == pytest.approx(getattr(theirs, field), abs=1e-9), field
    assert stored.counts["labelled_in_window"] == direct.counts["labelled_in_window"] > SCALED.min_primary
    assert stored.counts["played"] == direct.counts["played"] == len(before), "every match, once"
    assert stored.labels == ns.label_state(db, ns.RULE_VERSION, through=ns.labels_through(stored.labels))
    assert stored.labels["neutral"] == sum(m.is_neutral for m in after)
    assert stored.labels["through"] == stored.window["through"] == direct.window["through"], (
        "the labels are those of the matches the run could see: up to the last result it priced")
    assert ns.label_state(db, ns.RULE_VERSION)["neutral"] == stored.labels["neutral"] + 1, (
        "a match still to play, decided since, is a label too - but not one this run measured")
    assert set(stored.as_dict()["bases"]) == {"third_country"}, "and each label is attributed to the evidence that made it"


def run_the_command(db: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> tuple[Session, ns.Run]:
    """``backtest --apply`` over the database as it is, with the protocol scaled to the small synthetic world."""
    session = Session(db)
    monkeypatch.setattr(neutral_rule, "run_ab", partial(run_ab, protocol=SCALED))
    monkeypatch.setattr(neutral_rule, "dirty_tree", lambda: [])
    code, lines = neutral_rule.backtest_command(session, apply=True, allow_dirty=False, out=tmp_path / "result.json",  # type: ignore[arg-type]
                                                say=quiet)
    assert code == 0, lines
    stored = ns.runs(db, limit=1)
    assert len(stored) == 1 and f"Stored as run #{stored[0].id}" in "\n".join(lines)
    assert lines[0].startswith(f"VERDICT: {stored[0].verdict.upper()}") and "WHY:" in lines, "and it is said in words"
    assert any("labelled matches, pooled Elo + ordered logit: " in line and "Log loss" in line for line in lines)
    assert any("production poisson goal model" in line for line in lines) and any("(control)" in line for line in lines)
    assert json.loads((tmp_path / "result.json").read_text())["verdict"] == stored[0].verdict
    return session, stored[0]


def test_labels_that_are_right_go_from_the_backtest_to_the_models_and_back(db: psycopg.Connection[Any],
                                                                          monkeypatch: pytest.MonkeyPatch,
                                                                          tmp_path: Path) -> None:
    before, after = synthetic_world(2, share=0.3, really_neutral=True)
    write_synthetic(db, before, after)
    session, run = run_the_command(db, monkeypatch, tmp_path)
    assert run.verdict == "justified" and run.protocol == neutral_rule.PROTOCOL
    assert run.params["control_margin"] == SCALED.control_margin and run.result["verdict"] == "justified"
    assert run.labels == ns.label_state(db, ns.RULE_VERSION, through=ns.labels_through(run.labels))
    assert ns.promoted(db) is None and not any(read(db).values()), "a backtest changes no model"

    code, lines = neutral_rule.promote_command(session, run_id=run.id, reason=REASON, by="simon", confirm=True)  # type: ignore[arg-type]
    assert code == 0, lines
    flagged = {fid for fid, flag in read(db).items() if flag}
    assert len(flagged) == sum(m.is_neutral for m in after) == run.labels["neutral"], "the models now read the labels"
    code, lines = neutral_rule.retire_command(session, reason="a model got worse in production", by="simon",  # type: ignore[arg-type]
                                              confirm=True)
    assert code == 0 and not any(read(db).values())


def test_labels_that_are_wrong_cannot_reach_the_models(db: psycopg.Connection[Any], monkeypatch: pytest.MonkeyPatch,
                                                       tmp_path: Path) -> None:
    before, after = synthetic_world(1, share=0.3, really_neutral=False)  # the matches DO have a home advantage
    write_synthetic(db, before, after)
    session, run = run_the_command(db, monkeypatch, tmp_path)
    assert run.verdict == "not_justified" and "poisson" in " ".join(run.result["reasons"])
    code, lines = neutral_rule.promote_command(session, run_id=run.id, reason=REASON, by="simon", confirm=True)  # type: ignore[arg-type]
    assert code == 3 and "says 'not_justified'" in lines[0]
    assert ns.promoted(db) is None and not any(read(db).values()), "the verdicts are stored, the models do not read them"
    with pytest.raises(PermissionError, match="says 'not_justified'"):
        ns.promote(db, run.id, by="owner", reason=REASON)
