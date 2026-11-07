"""Plan F0, defect 8: only the latest /injuries answer AS OF a moment counts.

``core.player_absences`` keeps the last thing said about each (match, player) and every answer overwrites it. Read with
``fetched_at <= at`` it failed in both directions: a player the newest answer no longer names kept his old row (the AI
packet then reported a recovered key player as out, and the decision rule turned that into CAUTELA or RECHAZADO), and a
row refreshed after ``at`` vanished from a read as of ``at`` although it had been known then.

``core.player_availability_obs`` (migration 0078, written by ``fbi.ingestion.availability``) records each answer as the
changes it makes; ``fbi.ai.absences`` reads the state at a moment from it. These tests build a world, feed it answers
the way ``context_refresh`` does (the latest table, the history, the context check) and ask the packet, the evidence
collector and the dossier what they know at different moments. The transaction is rolled back afterwards."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from fbi.ai.absences import absences_as_of, checked_at_as_of
from fbi.ai.collectors import collect_provider
from fbi.ai.packet import PacketBuilder
from fbi.ingestion.availability import AnswerReport, record_answer
from fbi.ingestion.context_refresh import record_check
from fbi.ingestion.details import apply_injuries
from fbi.providers.api_football.details import AbsenceRef
from fbi.providers.base import RawResponse
from fbi.quality.detect import payload_dated_relations

from .conftest import Seed
from .helpers import scalar

H = timedelta(hours=1)
T1 = datetime(2032, 10, 5, 6, tzinfo=UTC)
T2 = T1 + 4 * H
T3 = T1 + 8 * H
T4 = T1 + 12 * H
KICKOFF = T1 + timedelta(days=1)
KNEE = ("Missing Fixture", "Knee Injury")
DOUBT = ("Questionable", "Muscle Injury")


@dataclass(frozen=True)
class World:
    season: int
    fixture: int
    provider_fixture: int
    home_team: int
    away_team: int
    home_provider: int
    away_provider: int


def _world(db: psycopg.Connection[Any]) -> World:
    cur = db.cursor()
    cur.execute("INSERT INTO core.competitions (provider_league_id, name, country, type, entity_scope, "
                "competition_type, is_tracked) VALUES (98930, 'Availability League', 'Colombia', 'league', 'club', "
                "'domestic_league', true) RETURNING id")
    comp = scalar(cur)
    cur.execute("INSERT INTO core.competition_seasons (competition_id, season, is_current) VALUES (%s, 2032, true) "
                "RETURNING id", (comp,))
    season = scalar(cur)
    teams = []
    for i in range(2):
        cur.execute("INSERT INTO core.teams (provider_team_id, name) VALUES (%s, %s) RETURNING id",
                    (989310 + i, f"Availability {i}"))
        teams.append(scalar(cur))
    cur.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
                "kickoff_at, status_short, status_group) VALUES (9893100, %s, %s, %s, %s, 'NS', 'scheduled') "
                "RETURNING id", (season, teams[0], teams[1], KICKOFF))
    return World(int(season), int(scalar(cur)), 9893100, int(teams[0]), int(teams[1]), 989310, 989311)


def _ref(w: World, player: int, what: tuple[str, str] = KNEE, *, away: bool = False) -> AbsenceRef:
    return AbsenceRef(w.provider_fixture, player, w.away_provider if away else w.home_provider, f"Player {player}",
                      what[0], what[1])


def _payload(db: psycopg.Connection[Any], seed: Seed, key: str, at: datetime) -> str:
    h = f"avail-{key}"
    db.execute("INSERT INTO raw.ingestion_payloads (hash, run_id, provider, endpoint, params, fetched_at, http_status, "
               "results_count, file_path, bytes) VALUES (%s, %s, 'api_football', '/injuries', '{}'::jsonb, %s, 200, 1, "
               "'x', 1) ON CONFLICT DO NOTHING", (h, seed.run_id, at))
    return h


def _answer(db: psycopg.Connection[Any], seed: Seed, w: World, at: datetime, refs: list[AbsenceRef], *,
            key: str | None = None) -> AnswerReport:
    """One /injuries answer, written the way ``fbi.ingestion.context_refresh`` writes it: the latest table, the history,
    and the check that the season's list was asked for."""
    h = _payload(db, seed, key or at.strftime("%d%H"), at)
    apply_injuries(db, refs, payload_hash=h, fetched_at=at)
    report = record_answer(db, refs, payload_hash=h, competition_season_id=w.season, requested_at=at)
    record_check(db, competition_season_id=w.season, dataset="injuries", checked_at=at, payload_hash=h,
                 rows_seen=len(refs))
    return report


def _players(db: psycopg.Connection[Any], w: World, at: datetime) -> list[int]:
    return sorted(int(r["provider_player_id"]) for r in absences_as_of(db, w.fixture, at))


def _rows(db: psycopg.Connection[Any], w: World, player: int) -> list[tuple[str, datetime, str | None, str | None]]:
    return [(str(r[0]), r[1], r[2], r[3]) for r in db.execute(
        "SELECT status, observed_at, absence_type, reason FROM core.player_availability_obs "
        "WHERE fixture_id = %s AND provider_player_id = %s ORDER BY observed_at", (w.fixture, player)).fetchall()]


# ── the state at a moment is the latest answer at or before it ───────────────────────────────────────────────────

def test_a_player_the_newest_answer_no_longer_names_is_not_absent(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = _world(db)
    _answer(db, seed, w, T1, [_ref(w, 9001), _ref(w, 9002, DOUBT)])
    assert _players(db, w, T1 + H) == [9001, 9002]
    report = _answer(db, seed, w, T2, [_ref(w, 9002, DOUBT)])  # 9001 has recovered
    assert (report.listed, report.cleared, report.unchanged) == (0, 1, 1)
    assert _players(db, w, T2 + H) == [9002], "a recovered player is not an absence"
    assert _rows(db, w, 9001) == [("LISTED", T1, *KNEE), ("CLEARED", T2, *KNEE)], (
        "the row that clears him says what was cleared")


def test_a_read_as_of_a_moment_sees_what_was_known_at_it_whatever_came_after(db: psycopg.Connection[Any],
                                                                              seed: Seed) -> None:
    w = _world(db)
    _answer(db, seed, w, T1, [_ref(w, 9001), _ref(w, 9002, DOUBT)])
    _answer(db, seed, w, T2, [_ref(w, 9002, DOUBT)])
    _answer(db, seed, w, T3, [_ref(w, 9002, KNEE), _ref(w, 9003, away=True)])  # 9002 is now out; 9003 (away) appears
    assert _players(db, w, T1 - H) == [], "before anything was recorded nothing was known"
    assert _players(db, w, T1 + H) == [9001, 9002]
    assert _players(db, w, T2 + H) == [9002]
    assert _players(db, w, T3 + H) == [9002, 9003]
    by_player = {int(r["provider_player_id"]): r["absence_type"] for r in absences_as_of(db, w.fixture, T2 + H)}
    assert by_player == {9002: "Questionable"}, "9002 was a doubt at T2, whatever it is now"
    by_player = {int(r["provider_player_id"]): r["absence_type"] for r in absences_as_of(db, w.fixture, T3 + H)}
    assert by_player == {9002: "Missing Fixture", 9003: "Missing Fixture"}


def test_the_latest_table_cannot_answer_either_question(db: psycopg.Connection[Any], seed: Seed) -> None:
    """Why the history exists: ``core.player_absences`` is the latest answer per player, kept as it is for the Match
    Center and the audits - but read as of a moment it is wrong in both directions."""
    w = _world(db)
    _answer(db, seed, w, T1, [_ref(w, 9001), _ref(w, 9002, DOUBT)])
    _answer(db, seed, w, T2, [_ref(w, 9002, DOUBT)])
    legacy = "SELECT provider_player_id FROM core.player_absences WHERE fixture_id = %s AND fetched_at <= %s"

    def old_read(at: datetime) -> list[int]:
        return sorted(int(r[0]) for r in db.execute(legacy, (w.fixture, at)).fetchall())

    assert old_read(T2 + H) == [9001, 9002], "9001 recovered, yet his row stands"
    assert old_read(T1 + H) == [9001], "9002 was known at T1; its refresh at T2 took it out of a read as of T1"
    assert _players(db, w, T2 + H) == [9002] and _players(db, w, T1 + H) == [9001, 9002]


# ── what an answer writes ────────────────────────────────────────────────────────────────────────────────────────

def test_an_unchanged_answer_and_a_replayed_one_write_nothing(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = _world(db)
    refs = [_ref(w, 9001), _ref(w, 9002, DOUBT)]
    first = _answer(db, seed, w, T1, refs)
    assert (first.listed, first.cleared, first.unchanged) == (2, 0, 0)
    again = _answer(db, seed, w, T1, refs)  # the same answer applied twice
    assert (again.listed, again.cleared, again.unchanged, again.stale) == (0, 0, 2, False)
    later = _answer(db, seed, w, T2, refs, key="same-content-later")  # asked again, nothing changed
    assert later.changes == 0 and later.unchanged == 2
    rows = db.execute("SELECT count(*) FROM core.player_availability_obs WHERE fixture_id = %s", (w.fixture,))
    assert rows.fetchone() == (2,), "two players listed once; asking again wrote nothing"
    assert _players(db, w, T3) == [9001, 9002]


def test_a_changed_type_or_reason_is_a_new_row_not_an_overwrite(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = _world(db)
    _answer(db, seed, w, T1, [_ref(w, 9002, DOUBT)])
    report = _answer(db, seed, w, T2, [_ref(w, 9002, KNEE)])
    assert (report.listed, report.cleared) == (1, 0)
    assert _rows(db, w, 9002) == [("LISTED", T1, *DOUBT), ("LISTED", T2, *KNEE)]
    assert [r["absence_type"] for r in absences_as_of(db, w.fixture, T1 + H)] == ["Questionable"]
    assert [r["absence_type"] for r in absences_as_of(db, w.fixture, T2 + H)] == ["Missing Fixture"]


def test_a_cleared_player_can_come_back(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = _world(db)
    _answer(db, seed, w, T1, [_ref(w, 9001)])
    _answer(db, seed, w, T2, [])  # recovered; the season has nobody listed at all
    _answer(db, seed, w, T3, [_ref(w, 9001, DOUBT)])  # a relapse
    assert [s for s, *_ in _rows(db, w, 9001)] == ["LISTED", "CLEARED", "LISTED"]
    assert (_players(db, w, T1 + H), _players(db, w, T2 + H), _players(db, w, T3 + H)) == ([9001], [], [9001])


def test_a_match_that_has_started_keeps_who_was_missing(db: psycopg.Connection[Any], seed: Seed) -> None:
    """Who was missing is what happened: an answer after kick-off that no longer names a player is the provider tidying
    up, not the player recovering."""
    w = _world(db)
    _answer(db, seed, w, T1, [_ref(w, 9001), _ref(w, 9002, DOUBT)])
    after_kickoff = KICKOFF + 3 * H
    report = _answer(db, seed, w, after_kickoff, [_ref(w, 9002, DOUBT)])
    assert report.cleared == 0
    assert _players(db, w, after_kickoff + H) == [9001, 9002]

    db.execute("UPDATE core.fixtures SET status_short = 'FT', status_group = 'finished' WHERE id = %s", (w.fixture,))
    on_time = _answer(db, seed, w, T3, [])  # before kick-off by the clock, but the match is over by its status
    assert on_time.cleared == 0 and _players(db, w, T3 + H) == [9001, 9002]


def test_an_answer_older_than_one_already_recorded_changes_nothing(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = _world(db)
    _answer(db, seed, w, T3, [_ref(w, 9002, DOUBT)])
    late = record_answer(db, [_ref(w, 9001), _ref(w, 9002, DOUBT)], payload_hash=_payload(db, seed, "late", T1),
                         competition_season_id=w.season, requested_at=T1)
    assert late.stale and late.changes == 0
    assert _players(db, w, T3 + H) == [9002], "the older answer does not bring 9001 back"
    assert _rows(db, w, 9001) == []


def test_the_history_alone_also_knows_which_answer_is_newer(db: psycopg.Connection[Any], seed: Seed) -> None:
    """The backfill writes no context check: the history itself must refuse an answer older than one it holds."""
    w = _world(db)
    h = _payload(db, seed, "bf", T3)
    record_answer(db, [_ref(w, 9002)], payload_hash=h, competition_season_id=w.season, requested_at=T3)
    late = record_answer(db, [_ref(w, 9001)], payload_hash=_payload(db, seed, "bf-old", T1),
                         competition_season_id=w.season, requested_at=T1)
    assert late.stale and _rows(db, w, 9001) == []


def test_an_answer_that_goes_back_to_an_earlier_content_still_wins(db: psycopg.Connection[Any], seed: Seed) -> None:
    """The raw store keeps identical bodies once, at the first fetch: content A, then B, then A again carries A's index
    time. The history is dated by when WE asked, so the third answer is the newest."""
    w = _world(db)
    _answer(db, seed, w, T1, [_ref(w, 9001)], key="content-a")
    _answer(db, seed, w, T2, [_ref(w, 9001), _ref(w, 9002)], key="content-b")
    back = _answer(db, seed, w, T3, [_ref(w, 9001)], key="content-a")
    assert (back.listed, back.cleared) == (0, 1)
    assert _players(db, w, T2 + H) == [9001, 9002] and _players(db, w, T3 + H) == [9001]


def test_entries_for_a_match_we_do_not_hold_are_counted_not_recorded(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = _world(db)
    stranger = AbsenceRef(999999999, 9001, w.home_provider, "Player 9001", *KNEE)
    report = _answer(db, seed, w, T1, [stranger, _ref(w, 9002)])
    assert (report.unknown_fixture, report.listed) == (1, 1)
    row = db.execute("SELECT count(*) FROM core.player_availability_obs WHERE provider_player_id = 9001").fetchone()
    assert row == (0,)


def test_the_last_entry_of_a_player_in_one_answer_wins(db: psycopg.Connection[Any], seed: Seed) -> None:
    """What ``core.player_absences`` keeps too: one row per (match, player)."""
    w = _world(db)
    _answer(db, seed, w, T1, [_ref(w, 9001, DOUBT), _ref(w, 9001, KNEE)])
    assert [r["absence_type"] for r in absences_as_of(db, w.fixture, T1 + H)] == ["Missing Fixture"]


def test_the_history_is_not_a_payload_dated_relation(db: psycopg.Connection[Any]) -> None:
    """Its time is when WE asked, which can be later than the index time of a body the store keeps once; the lineage
    check forbids that for derived copies (``fetched_at``). Renaming the column would make valid rows offenders."""
    assert "player_availability_obs" not in payload_dated_relations(db)
    assert "player_absences" in payload_dated_relations(db)


# ── "was the list asked for by then?" ────────────────────────────────────────────────────────────────────────────

def test_whether_the_list_had_been_asked_for_does_not_depend_on_the_latest_check(db: psycopg.Connection[Any],
                                                                                   seed: Seed) -> None:
    w = _world(db)
    assert checked_at_as_of(db, w.season, T1) is None, "nothing recorded: no evidence it was ever asked for"
    _answer(db, seed, w, T1, [_ref(w, 9001)])
    _answer(db, seed, w, T3, [])
    # core.context_checks keeps only the latest check (T3): it knows nothing of T1 or T2
    assert checked_at_as_of(db, w.season, T1 + H) == T1
    assert checked_at_as_of(db, w.season, T2 + H) == T1
    assert checked_at_as_of(db, w.season, T3 + H) == T3
    assert checked_at_as_of(db, w.season, T1 - H) is None


# ── the packet, the collector and the dossier read the same answer ───────────────────────────────────────────────

def test_the_packet_lists_only_the_players_the_latest_answer_names(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = _world(db)
    _answer(db, seed, w, T1, [_ref(w, 9001), _ref(w, 9002, DOUBT), _ref(w, 9003, away=True)])
    _answer(db, seed, w, T2, [_ref(w, 9002, DOUBT), _ref(w, 9003, away=True)])  # 9001 has recovered

    now = PacketBuilder(db).build(w.fixture, at=T2 + H)
    assert now is not None
    absences = now.content["absences"]
    assert absences["checked"] is True
    assert [p["player_id"] for p in absences["home"]["players"]] == [9002], "9001 recovered: he is not in the packet"
    assert [p["player_id"] for p in absences["away"]["players"]] == [9003]
    assert "absences" not in now.missing
    source = next(s for s in now.sources if s["block"] == "absences")
    assert source["table"] == "core.player_availability_obs"
    assert source["as_of"] == T1.isoformat(), "the newest change that still stands: 9002 and 9003 were named at T1"

    then = PacketBuilder(db).build(w.fixture, at=T1 + H)
    assert then is not None
    assert sorted(p["player_id"] for p in then.content["absences"]["home"]["players"]) == [9001, 9002], (
        "built for T1 the packet is what a reviewer knew at T1, although two refreshes followed")
    assert then.hash != now.hash


def test_a_packet_with_nobody_listed_says_so_instead_of_saying_nothing_is_known(db: psycopg.Connection[Any],
                                                                                 seed: Seed) -> None:
    w = _world(db)
    _answer(db, seed, w, T1, [_ref(w, 9001)])
    _answer(db, seed, w, T2, [])
    packet = PacketBuilder(db).build(w.fixture, at=T2 + H)
    assert packet is not None
    assert packet.content["absences"]["checked"] is True and packet.content["absences"]["home"]["players"] == []
    assert "absences" not in packet.missing, "everybody recovered is an answer, not a gap"
    never = PacketBuilder(db).build(w.fixture, at=T1 - H)
    assert never is not None and "absences" in never.missing, "before any answer nothing is known"


def test_the_collector_turns_only_the_current_list_into_evidence(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = _world(db)
    _answer(db, seed, w, T1, [_ref(w, 9001), _ref(w, 9002, DOUBT)])
    _answer(db, seed, w, T2, [_ref(w, 9002, DOUBT)])
    out = collect_provider(db, w.fixture, at=T2 + H)
    assert out.seen == 1 and out.created == 1
    stories = [r[0] for r in db.execute("SELECT story_key FROM ai.evidence WHERE fixture_id = %s ORDER BY 1",
                                        (w.fixture,)).fetchall()]
    assert stories == [f"absence:{w.fixture}:9002"], "9001 recovered: no evidence that he is out"
    status = db.execute("SELECT status, status_reason, retrieved_at FROM ai.evidence WHERE fixture_id = %s", (w.fixture,)).fetchone()
    assert status is not None and status[2] == T1, "the item is dated by the first time he was listed: the unchanged answer wrote nothing"
    assert (status[0], status[1]) == ("PROBABLE", "the data provider's report"), (
        "IA-015: 9002 is still on the list re-read at T2, so his absence stands although it was first listed 4 h before")


def test_an_item_of_the_report_stands_while_listed_and_goes_when_cleared(db: psycopg.Connection[Any], seed: Seed) -> None:
    """IA-015, through the collector: the list is re-read every 4 h and an unchanged answer writes nothing, so the items of the provider keep
    the date they were first listed. What the latest answer lists decides whether they stand, not how old they are."""
    w = _world(db)
    _answer(db, seed, w, T1, [_ref(w, 9001), _ref(w, 9002, DOUBT)])
    collect_provider(db, w.fixture, at=T1 + H)
    _answer(db, seed, w, T2, [_ref(w, 9001), _ref(w, 9002, DOUBT)], key="unchanged")  # nothing changed: nothing written
    _answer(db, seed, w, T3, [_ref(w, 9001), _ref(w, 9002, DOUBT)], key="unchanged-again")

    def statuses() -> dict[int, tuple[str, str]]:
        return {int(r[0]): (str(r[1]), str(r[2])) for r in db.execute(
            "SELECT provider_player_id, status, status_reason FROM ai.evidence WHERE fixture_id = %s AND origin = 'provider'",
            (w.fixture,)).fetchall()}

    collect_provider(db, w.fixture, at=T3 + timedelta(minutes=10))  # listed 8 h ago, the list re-read 10 min ago
    assert {p: s for p, (s, _) in statuses().items()} == {9001: "PROBABLE", 9002: "PROBABLE"}, "both still on the list"

    _answer(db, seed, w, T4, [_ref(w, 9002, DOUBT)])  # 9001 has recovered
    collect_provider(db, w.fixture, at=T4 + H)
    now = statuses()
    assert now[9001] == ("OUTDATED", "no longer in the provider's latest injury report")
    assert now[9002][0] == "PROBABLE"
    packet = PacketBuilder(db).build(w.fixture, at=T4 + H)
    assert packet is not None
    shown = sorted(int(e["player_id"]) for e in packet.content["evidence"] if e["origin"] == "provider")
    assert shown == [9002], "the packet carries the absence that stands, not the cleared one"


def test_the_dossier_flags_a_key_player_only_while_the_latest_answer_lists_him(db: psycopg.Connection[Any],
                                                                                seed: Seed) -> None:
    w = _world(db)
    cur = db.cursor()
    cur.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
                "kickoff_at, status_short, status_group) VALUES (9893000, %s, %s, %s, %s, 'FT', 'finished') "
                "RETURNING id", (w.season, w.home_team, w.away_team, T1 - timedelta(days=7)))
    played = int(scalar(cur))
    cur.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away, settled_at) VALUES (%s, 2, 1, %s)",
                (played, T1 - timedelta(days=7) + 2 * H))
    cur.execute("INSERT INTO core.fixture_player_stats (fixture_id, source, provider_player_id, team_side, player_name, "
                "minutes, is_substitute, goals, assists, shots_total, payload_hash, fetched_at) "
                "VALUES (%s, 'api-football', 9001, 'home', 'Player 9001', 90, false, 2, 0, 4, %s, %s)",
                (played, seed.payload_hash, T1 - timedelta(days=7) + 3 * H))
    _answer(db, seed, w, T1, [_ref(w, 9001)])
    _answer(db, seed, w, T2, [])

    def star(at: datetime) -> Any:
        packet = PacketBuilder(db).build(w.fixture, at=at)
        assert packet is not None
        players = packet.content["dossier"]["players"]["home"]
        assert [p["id"] for p in players] == [9001]
        return players[0]["reported_out"]

    assert star(T1 + H) == "Missing Fixture"
    assert star(T2 + H) is None, "he recovered: the dossier does not call him out"


# ── the readers all go through the same function ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("module", ["fbi.ai.packet", "fbi.ai.collectors", "fbi.intel.dossier"])
def test_the_readers_use_the_history_not_the_latest_table(module: str) -> None:
    import importlib

    mod = importlib.import_module(module)
    assert mod.absences_as_of.__module__ == "fbi.ai.absences"


# ── the writers that call it ─────────────────────────────────────────────────────────────────────────────────────

class _Ledger:
    """Just enough of the run ledger for one task: the test indexes the payload itself."""

    def record_payloads(self, run_id: int, raws: list[Any]) -> int:
        return len(raws)

    def indexed_at(self, payload_hash: str) -> datetime | None:
        return None


class _Provider:
    def __init__(self, refs: list[AbsenceRef], at: datetime, payload_hash: str) -> None:
        self.refs, self.at, self.hash = refs, at, payload_hash

    async def fetch_injuries(self, *, league_id: int, season: int) -> Any:
        raw = RawResponse(endpoint="/injuries", params={}, fetched_at=self.at, http_status=200,
                          results_count=len(self.refs), payload_hash=self.hash, file_path="x", bytes_written=1, body={})
        return self.refs, raw


async def test_the_backfill_of_a_seasons_injuries_enters_the_history_too(db: psycopg.Connection[Any],
                                                                          seed: Seed) -> None:
    from fbi.ingestion.backfill import Task, _execute
    from fbi.ingestion.ledger import RunCounters

    w = _world(db)
    provider = _Provider([_ref(w, 9001), _ref(w, 9002, DOUBT)], T1, _payload(db, seed, "backfill", T1))
    task = Task(1, "injuries_season", 98930, 2032, None, None, {}, 1, None, 300)
    outcome = await _execute(db, provider, _Ledger(), seed.run_id, task, RunCounters())  # type: ignore[arg-type]
    assert outcome.rows == 2
    assert _players(db, w, T1 + H) == [9001, 9002]
    assert [r[0] for r in db.execute(
        "SELECT status FROM core.player_availability_obs WHERE fixture_id = %s ORDER BY provider_player_id",
        (w.fixture,)).fetchall()] == ["LISTED", "LISTED"]
    legacy = db.execute("SELECT count(*) FROM core.player_absences WHERE fixture_id = %s", (w.fixture,)).fetchone()
    assert legacy == (2,), "the latest table is written as before"
