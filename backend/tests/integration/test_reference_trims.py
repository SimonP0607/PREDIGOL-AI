"""The sweeps nobody reads, trimmed (plan PM, PM-04-03; BE-062), behind ``FBI_REFERENCE_TRIMS``: off, every feed is what it was;
on, /predictions once a match, /teams/statistics weekly, /players monthly on each competition's own day and the squad round spread
over the week."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import psycopg
import pytest

import fbi.ingestion.people as people
import fbi.ingestion.reference as ref
from tests.integration.conftest import Seed

MONDAY = datetime(2026, 11, 2, 9, 0, tzinfo=UTC)
"""A Monday; the seeded competition is provider league 39 (day 39 % 28 + 1 = 12 of the month), its teams 33 and 40 (33 % 7 =
40 % 7 = 5: Saturday)."""


@pytest.fixture()
def tracked(db: psycopg.Connection, seed: Seed) -> psycopg.Connection:
    db.execute("UPDATE core.competitions SET is_tracked = true WHERE id = %s", (seed.competition_id,))
    db.execute("UPDATE core.competition_seasons SET is_current = true WHERE id = %s", (seed.season_id,))
    return db


def test_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(ref.TRIMS_SWITCH, raising=False)
    assert ref.trims_on() is False
    for word, on in (("on", True), ("1", True), ("yes", True), ("off", False), ("0", False), ("enforce", False)):
        monkeypatch.setenv(ref.TRIMS_SWITCH, word)
        assert ref.trims_on() is on


def test_predictions_once_a_match_with_the_trims(tracked: psycopg.Connection, seed: Seed,
                                                 monkeypatch: pytest.MonkeyPatch) -> None:
    db = tracked
    db.execute("UPDATE core.fixtures SET kickoff_at = %s, status_group = 'scheduled' WHERE id = %s",
               (MONDAY + timedelta(hours=30), seed.fixture_id))
    monkeypatch.setenv(ref.TRIMS_SWITCH, "off")
    assert [t.key for t in ref.prediction_targets(db, MONDAY + timedelta(hours=28))] == ["fixture:1001:3h"]
    monkeypatch.setenv(ref.TRIMS_SWITCH, "on")
    keys = {t.key for at in (MONDAY, MONDAY + timedelta(hours=10), MONDAY + timedelta(hours=28))
            for t in ref.prediction_targets(db, at)}
    assert keys == {"fixture:1001:48h"}, "one key for the whole approach: asked once (the key of the first window of before)"
    late = MONDAY + timedelta(hours=29)  # a match first seen an hour before kick-off is still asked, once
    assert [t.key for t in ref.prediction_targets(db, late)] == ["fixture:1001:48h"]
    db.rollback()


def test_team_statistics_weekly_for_all_with_the_trims(tracked: psycopg.Connection, seed: Seed,
                                                       monkeypatch: pytest.MonkeyPatch) -> None:
    db = tracked
    db.execute("UPDATE core.fixtures SET kickoff_at = %s, status_group = 'scheduled' WHERE id = %s",
               (MONDAY + timedelta(hours=5), seed.fixture_id))
    monkeypatch.setenv(ref.TRIMS_SWITCH, "off")
    assert {t.every for t in ref.team_season_targets(db, MONDAY)} == {ref.DAY}, "playing within 24 h: daily"
    monkeypatch.setenv(ref.TRIMS_SWITCH, "on")
    assert {t.every for t in ref.team_season_targets(db, MONDAY)} == {ref.WEEK}
    db.rollback()


def test_players_monthly_on_the_competitions_own_day_with_the_trims(tracked: psycopg.Connection,
                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    """The seed commits (it is a worker step), so the test puts back what it changed."""
    db = tracked
    db.commit()
    monkeypatch.setenv(ref.TRIMS_SWITCH, "on")
    try:
        first_day = MONDAY.replace(day=1)
        assert people.seed_player_seasons(db, at=first_day) == 0, "league 39 sweeps from the 12th"
        assert people.seed_player_seasons(db, at=first_day.replace(day=11)) == 0
        assert people.seed_player_seasons(db, at=first_day.replace(day=12)) == 1
        assert people.seed_player_seasons(db, at=first_day.replace(day=19)) == 0, "the same month"
        december = datetime(2026, 12, 1, 9, 0, tzinfo=UTC)
        assert people.seed_player_seasons(db, at=december.replace(day=1)) == 0, "a new month, but before its day"
        assert people.seed_player_seasons(db, at=december.replace(day=12)) == 1
        keys = db.execute("SELECT batch_key FROM raw.backfill_tasks WHERE kind = 'players_season' ORDER BY 1").fetchall()
        assert keys == [("m202611",), ("m202612",)]
    finally:
        db.rollback()
        db.execute("DELETE FROM raw.backfill_tasks WHERE kind = 'players_season'")
        db.commit()


def test_a_monthly_sweep_never_follows_the_previous_one_within_twenty_days(tracked: psycopg.Connection,
                                                                           monkeypatch: pytest.MonkeyPatch) -> None:
    db = tracked
    db.commit()
    try:
        monkeypatch.setenv(ref.TRIMS_SWITCH, "off")
        assert people.seed_player_seasons(db, at=MONDAY.replace(day=9)) == 1, "the weekly sweep, on 9 Nov"
        monkeypatch.setenv(ref.TRIMS_SWITCH, "on")
        assert people.seed_player_seasons(db, at=MONDAY.replace(day=12)) == 0, "switched on: three days after a sweep"
        assert people.seed_player_seasons(db, at=MONDAY.replace(day=29, hour=10)) == 1, "twenty days on"
    finally:
        db.rollback()
        db.execute("DELETE FROM raw.backfill_tasks WHERE kind = 'players_season'")
        db.commit()


def test_the_squad_round_is_spread_over_the_week_with_the_trims(tracked: psycopg.Connection,
                                                                monkeypatch: pytest.MonkeyPatch) -> None:
    db = tracked
    db.commit()
    try:
        monkeypatch.setenv(ref.TRIMS_SWITCH, "on")
        assert people.seed_people_refresh(db, at=MONDAY).squad_units == 0, "teams 33 and 40 are Saturday's"
        assert people.seed_people_refresh(db, at=MONDAY + timedelta(days=4)).squad_units == 0
        assert people.seed_people_refresh(db, at=MONDAY + timedelta(days=5)).squad_units == 2
        assert people.seed_people_refresh(db, at=MONDAY + timedelta(days=6)).squad_units == 0, "the same week"
        monkeypatch.setenv(ref.TRIMS_SWITCH, "off")
        assert people.seed_people_refresh(db, at=MONDAY + timedelta(days=7)).squad_units == 2, "off: all on Monday"
    finally:
        db.rollback()
        db.execute("DELETE FROM raw.backfill_tasks WHERE kind IN ('player_profiles', 'team_squad')")
        db.commit()
