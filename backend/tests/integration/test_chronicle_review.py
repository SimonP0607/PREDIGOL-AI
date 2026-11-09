"""The review of the chronicle after the match (IA-022) in a real database: the newest chronicle a reader could have seen before the kick-off is
judged once, 26 hours after the match, against who played; a match without line-ups or minutes waits; the row is append-only; the run
writes ``ai.chronicle_reviews`` and nothing else. The transaction is rolled back."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import count
from typing import Any

import psycopg
import pytest
from psycopg.errors import CheckViolation
from psycopg.types.json import Jsonb

from fbi.chronicle import review
from fbi.intel import postmortem
from fbi.observability.trace import match_trace_id
from tests.integration.conftest import Seed
from tests.integration.helpers import scalar
from tests.integration.test_news_api import evidence as add_evidence
from tests.integration.test_postmortem_v6 import LATE, Pm

pytestmark = pytest.mark.integration

KICKOFF = datetime(2034, 4, 12, 18, tzinfo=UTC)
NOW = KICKOFF + timedelta(hours=30)
_provider_ids = count(9_870_001)
_keys = count(1)

PACKET = {"fixture": {"home": {"name": "Casa"}, "away": {"name": "Fuera"}, "competition": "Liga"},
          "absences": {"home": {"players": [{"name": "Lisandro Martínez", "key": True, "type": "Missing Fixture", "reason": "Hamstring Injury"},
                                            {"name": "Tom Heaton", "key": False, "type": "Questionable", "reason": "Knock"}]},
                       "away": {"players": [{"name": "Mohamed Salah", "key": True, "type": "Missing Fixture", "reason": "Suspended"}]}}}


def s(text: str, *refs: str) -> dict[str, Any]:
    return {"text": text, "refs": list(refs)}


def match(db: psycopg.Connection[Any], seed: Seed, *, status: str = "finished", kickoff: datetime = KICKOFF) -> int:
    fid = int(scalar(db.execute(
        "INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at, status_group) "
        "VALUES (%s, %s, %s, %s, %s, %s) RETURNING id", (next(_provider_ids), seed.season_id, seed.home_team_id, seed.away_team_id, kickoff, status))))
    if status == "finished":
        db.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away, settled_at) VALUES (%s, 2, 1, %s)",
                   (fid, kickoff + timedelta(hours=2)))
    return fid


def packet(db: psycopg.Connection[Any], fid: int) -> int:
    return int(scalar(db.execute(
        "INSERT INTO ai.match_packets (fixture_id, packet_version, as_of, built_at, packet_hash, content, missing) "
        "VALUES (%s, 'packet-v8', %s, %s, %s, %s, %s) RETURNING id",
        (fid, KICKOFF - timedelta(hours=5), KICKOFF - timedelta(hours=5), "d" * 64, Jsonb(PACKET), []))))


def chronicle(db: psycopg.Connection[Any], fid: int, packet_id: int, ids: dict[str, int], *, at: datetime | None = None,
              status: str = "ok", n: int = 1) -> int:
    es = [{"key": "summary", "sentences": [s("Partido de la Liga.", "P:fixture")]},
          {"key": "home", "sentences": [s("Lisandro Martínez es baja por lesión.", "P:absences.home.1"),
                                         s("Tom Heaton es duda por un golpe.", "P:absences.home.2"),
                                         s("Según Marca, Mohamed Salah no estará.", f"E:{ids['salah']}", "P:absences.away.1")]},
          {"key": "risks", "sentences": [s("Hay un rumor sobre el portero.", f"E:{ids['rumour']}")]}]
    content = {"es": es, "en": es, "sources": []}
    return int(scalar(db.execute(
        "INSERT INTO ai.user_narratives (fixture_id, created_at, version, packet_id, data_at, reading_hash, input_hash, status, content) "
        "VALUES (%s, %s, 'user-narrative-v3', %s, %s, %s, %s, %s, %s) RETURNING id",
        (fid, at or KICKOFF - timedelta(hours=4, minutes=n), packet_id, KICKOFF - timedelta(hours=5), "a" * 64, f"{n:x}" * 64,
         status, Jsonb(content) if status == "ok" else None))))


def news(db: psycopg.Connection[Any], fid: int, seed: Seed) -> dict[str, int]:
    seen = KICKOFF - timedelta(hours=6)
    key = next(_keys)
    salah = int(scalar(db.execute(
        "INSERT INTO ai.evidence (fixture_id, team_id, kind, claim, origin, source_name, source_url, source_domain, source_tier, "
        "retrieved_at, story_key, content_hash, confidence, relevance, attributes, status, status_reason, status_changed_at, "
        "provider_player_id) VALUES (%s, %s, 'suspension', 'Salah, sancionado.', 'web', 'www.marca.com', 'https://www.marca.com/1', NULL, "
        "'media', %s, %s, %s, 0.5, 0.6, %s, 'CONFIRMED', 'test', %s, 501) RETURNING id",
        (fid, seed.away_team_id, seen, f"k{key}", f"{key:064x}", Jsonb({"assertion": "out", "player_name": "Mohamed Salah"}), seen))))
    rumour = add_evidence(db, fid, seed.home_team_id, status="RUMOR", kind="news", assertion="info", claim="Se dice que el portero no viaja.",
                          tier="unknown", source="rumours.example", url="https://rumours.example/1", retrieved=seen)
    return {"salah": salah, "rumour": rumour}


def squad(db: psycopg.Connection[Any], fid: int, seed: Seed, *, lineups: bool = True, minutes: bool = True) -> None:
    now = KICKOFF - timedelta(minutes=50)
    if lineups:
        for side in ("home", "away"):
            db.execute("INSERT INTO core.fixture_lineups (fixture_id, team_side, source, payload_hash, fetched_at) "
                       "VALUES (%s, %s, 'api-football', %s, %s)", (fid, side, seed.payload_hash, now))
        for side, pid, name, starter in (("home", 10, "Lisandro Martínez", True), ("home", 11, "Bruno Fernandes", True), ("home", 12, "Tom Heaton", False),
                                         ("away", 30, "Virgil van Dijk", True)):
            db.execute("INSERT INTO core.fixture_lineup_players (fixture_id, team_side, source, provider_player_id, player_name, is_starter) "
                       "VALUES (%s, %s, 'api-football', %s, %s, %s)", (fid, side, pid, name, starter))
    if minutes:
        for side, pid, name, mins in (("home", 10, "Lisandro Martínez", 90), ("home", 11, "Bruno Fernandes", 90), ("home", 12, "Tom Heaton", None),
                                      ("away", 30, "Virgil van Dijk", 90)):
            db.execute("INSERT INTO core.fixture_player_stats (fixture_id, source, provider_player_id, team_side, player_name, minutes, "
                       "payload_hash, fetched_at) VALUES (%s, 'api-football', %s, %s, %s, %s, %s, %s)",
                       (fid, pid, side, name, mins, seed.payload_hash, KICKOFF + timedelta(hours=3)))


def world(db: psycopg.Connection[Any], seed: Seed, **kw: Any) -> tuple[int, int, int]:
    fid = match(db, seed)
    ids = news(db, fid, seed)
    pk = packet(db, fid)
    nid = chronicle(db, fid, pk, ids)
    squad(db, fid, seed, **kw)
    return fid, pk, nid


def rows(db: psycopg.Connection[Any]) -> list[dict[str, Any]]:
    cur = db.execute("SELECT fixture_id, narrative_id, version, narrative_version, packet_id, trace_id::text, status, outcome, items, summary, picks "
                     "FROM ai.chronicle_reviews ORDER BY id")
    names = [d.name for d in cur.description or []]
    return [dict(zip(names, r, strict=True)) for r in cur.fetchall()]


def test_a_chronicle_is_judged_once_against_who_played(db: psycopg.Connection[Any], seed: Seed) -> None:
    fid, pk, nid = world(db, seed)
    report = review.run(db, at=NOW)
    assert (report.due, report.written, report.waiting) == (1, 1, 0)
    [row] = rows(db)
    assert (row["fixture_id"], row["narrative_id"], row["version"], row["narrative_version"], row["packet_id"], row["status"]) == (
        fid, nid, review.VERSION, "user-narrative-v3", pk, "reviewed")
    assert row["trace_id"] == str(match_trace_id(fid))
    assert row["outcome"] == {"home_goals": 2, "away_goals": 1, "players_with_minutes": 3, "line_ups": True, "minutes": True}
    by = {(i["section"], i["index"]): i for i in row["items"]}
    assert by[("summary", 0)]["verdict"] == review.NOT_EVALUABLE
    assert by[("home", 0)]["verdict"] == review.CONTRADICTED, "he was out in the chronicle and played 90 minutes"
    assert by[("home", 1)]["verdict"] == review.DID_NOT_PLAY, "in doubt, and no minutes"
    assert by[("home", 2)]["verdict"] == review.HELD, "the news item and the absence: Salah is in neither list"
    assert [c["verdict"] for c in by[("home", 2)]["checks"]] == [review.HELD, review.HELD]
    assert by[("risks", 0)]["verdict"] == review.NOT_EVALUABLE, "a rumour is not about a named player"
    summary = row["summary"]
    assert (summary["sentences"], summary["firm_claims"], summary["held"], summary["contradicted"]) == (5, 3, 2, 1)
    assert summary["by_sentence"] == {review.NOT_EVALUABLE: 2, review.CONTRADICTED: 1, review.DID_NOT_PLAY: 1, review.HELD: 1}


def test_the_run_is_idempotent_and_a_newer_chronicle_is_a_new_review_of_the_newest_one_only(db: psycopg.Connection[Any], seed: Seed) -> None:
    fid, pk, nid = world(db, seed)
    assert review.run(db, at=NOW).written == 1
    again = review.run(db, at=NOW)
    assert (again.due, again.written) == (0, 0), "the same chronicle and version is reviewed once"
    ids = {"salah": int(scalar(db.execute("SELECT id FROM ai.evidence WHERE fixture_id = %s AND kind = 'suspension'", (fid,)))),
           "rumour": int(scalar(db.execute("SELECT id FROM ai.evidence WHERE fixture_id = %s AND kind = 'news'", (fid,))))}
    newer = chronicle(db, fid, pk, ids, at=KICKOFF - timedelta(hours=1), n=2)
    later = chronicle(db, fid, pk, ids, at=KICKOFF + timedelta(minutes=5), n=3)  # written after the kick-off: no reader saw it before
    got = review.run(db, at=NOW)
    assert got.written == 1
    assert [r["narrative_id"] for r in rows(db)] == [nid, newer] and later not in {r["narrative_id"] for r in rows(db)}


def test_a_match_without_line_ups_and_minutes_waits_and_a_chronicle_that_was_not_shown_is_not_reviewed(db: psycopg.Connection[Any], seed: Seed) -> None:
    fid, _pk, _nid = world(db, seed, lineups=False, minutes=False)
    report = review.run(db, at=NOW)
    assert (report.due, report.written, report.waiting) == (1, 0, 1)
    assert rows(db) == []
    squad(db, fid, seed)
    assert review.run(db, at=NOW).written == 1, "the next run finds the data and writes"
    other = match(db, seed, kickoff=KICKOFF + timedelta(days=1))
    chronicle(db, other, packet(db, other), news(db, other, seed), status="rejected", at=KICKOFF + timedelta(hours=5))
    assert review.run(db, at=NOW + timedelta(days=1)).due == 0, "a rejected chronicle was never shown"


def test_a_match_is_reviewed_only_after_the_settling_time_and_inside_the_lookback(db: psycopg.Connection[Any], seed: Seed) -> None:
    world(db, seed)
    assert review.run(db, at=KICKOFF + timedelta(hours=25)).due == 0, "26 hours after the kick-off, not before"
    assert review.run(db, at=KICKOFF + timedelta(days=9)).due == 0, "older than the lookback"
    assert review.run(db, at=KICKOFF + timedelta(hours=27)).written == 1


def test_a_preview_judges_and_writes_nothing(db: psycopg.Connection[Any], seed: Seed) -> None:
    world(db, seed)
    report = review.run(db, at=NOW, apply=False)
    assert (report.due, report.written, report.contradicted) == (1, 1, 1)
    assert rows(db) == []


def test_the_selections_of_the_match_are_listed_beside_the_review_and_linked_to_nothing(db: psycopg.Connection[Any], seed: Seed) -> None:
    world(db, seed)
    assert review.run(db, at=NOW).written == 1
    [row] = rows(db)
    assert row["picks"] == [], "no selection of this match was judged by a post-mortem"


def test_the_review_is_append_only(db: psycopg.Connection[Any], seed: Seed) -> None:
    world(db, seed)
    review.run(db, at=NOW)
    with pytest.raises(CheckViolation):
        db.execute("UPDATE ai.chronicle_reviews SET status = 'facts_unavailable'")


def test_a_run_writes_the_reviews_and_nothing_else(db: psycopg.Connection[Any], seed: Seed) -> None:
    world(db, seed)
    tables = ("ai.user_narratives", "ai.evidence", "ai.match_packets", "core.fixtures", "core.fixture_lineup_players", "core.fixture_player_stats",
              "intel.postmortems", "intel.decisions", "picks.picks", "ai.usage", "ai.user_usage")
    before = {t: scalar(db.execute(f"SELECT count(*) FROM {t}")) for t in tables}
    review.run(db, at=NOW)
    assert {t: scalar(db.execute(f"SELECT count(*) FROM {t}")) for t in tables} == before
    assert scalar(db.execute("SELECT count(*) FROM ai.chronicle_reviews")) == 1


def test_a_chronicle_whose_packet_is_gone_is_reviewed_without_the_absences(db: psycopg.Connection[Any], seed: Seed) -> None:
    fid = match(db, seed)
    ids = news(db, fid, seed)
    chronicle(db, fid, 987_654_321, ids)
    squad(db, fid, seed)
    review.run(db, at=NOW)
    [row] = rows(db)
    assert row["status"] == "facts_unavailable"
    absent = [c for i in row["items"] for c in i["checks"] if c["code"] == "absence"]
    assert absent and {c["verdict"] for c in absent} == {review.NOT_CHECKABLE}


def test_the_post_mortems_of_the_selections_come_beside_the_review(db: psycopg.Connection[Any], seed: Seed) -> None:
    """The query the review runs for the selections of a match, on the world of the post-mortems (F4, F5 and F6 have the selection post-mortems of the decision layer)."""
    pm = Pm(db, seed)
    postmortem.study(db, at=LATE)
    got = db.execute(review.PICKS_SQL, {"fixture": pm.f["F4"]}).fetchall()
    assert got, "the match has a judged selection"
    assert ("OU", "Over") in {(r[2], r[3]) for r in got} and all(r[5] in ("won", "lost", "void", "push", "half_won", "half_lost") for r in got)
    assert len({(r[2], r[3], r[4]) for r in got}) == len(got), "one row per selection, the newest version"


def test_the_command_previews_one_match_or_what_is_due_and_run_needs_the_owner(db: psycopg.Connection[Any], seed: Seed,
                                                                                 capsys: pytest.CaptureFixture[str]) -> None:
    from scripts import ia_chronicle_review as cli

    fid, _pk, _nid = world(db, seed)
    got, code = cli.preview(db, fid)
    assert code == 0 and len(got) == 1 and got[0].summary["contradicted"] == 1
    text = cli.render(got[0])
    assert "[contradicted] home.0: Lisandro Martínez es baja por lesión." in text and "Partido de la Liga" not in text
    assert cli.preview(db, 424_242) == ([], 1), "a match with no chronicle"
    assert cli.main(["run"]) == 2 and "--confirm-owner" in capsys.readouterr().err
    assert scalar(db.execute("SELECT count(*) FROM ai.chronicle_reviews")) == 0


def test_the_scheduled_job_leaves_a_ledger_row_only_when_it_wrote(db: psycopg.Connection[Any], seed: Seed) -> None:
    from fbi.chronicle.job import JOB, run_job

    def runs() -> int:
        return int(scalar(db.execute("SELECT count(*) FROM raw.ingestion_runs WHERE job_type = %s", (JOB,))))

    assert run_job(db, at=NOW).due == 0 and runs() == 0, "a quiet pass leaves nothing"
    world(db, seed)
    assert run_job(db, at=NOW).written == 1 and runs() == 1
    assert run_job(db, at=NOW).written == 0 and runs() == 1, "the second pass finds it reviewed and leaves no new row"
    notes = str(scalar(db.execute("SELECT notes FROM raw.ingestion_runs WHERE job_type = %s", (JOB,))))
    assert '"written": 1' in notes and review.VERSION in notes
