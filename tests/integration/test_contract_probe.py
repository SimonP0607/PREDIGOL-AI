"""The contract probe asks for each endpoint form PrediGol never stored, with ids read from the database
(scripts.audit_api_contract --probe): never an invented id, nothing asked twice."""

from __future__ import annotations

import psycopg

from scripts.audit_api_contract import probes
from tests.integration.conftest import Seed


def test_the_probe_plan_uses_an_upcoming_tracked_match_and_its_people(db: psycopg.Connection, seed: Seed) -> None:
    assert probes(db) == [], "no upcoming tracked match: nothing to ask about"
    db.execute("UPDATE core.competitions SET is_tracked = true WHERE id = %s", (seed.competition_id,))
    db.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, "
               "kickoff_at) VALUES (5005, %s, %s, %s, now() + interval '1 day')",
               (seed.season_id, seed.home_team_id, seed.away_team_id))
    db.execute("UPDATE core.fixtures SET status_group = 'finished', status_short = 'FT', "
               "kickoff_at = now() - interval '3 days' WHERE id = %s", (seed.fixture_id,))
    db.execute("INSERT INTO core.fixture_player_stats (fixture_id, source, provider_player_id, team_side, payload_hash, "
               "fetched_at) VALUES (%(f)s, 'api-football', 909, 'home', %(h)s, now()), "
               "(%(f)s, 'api-football', 77, 'away', %(h)s, now())", {"f": seed.fixture_id, "h": seed.payload_hash})
    plan = probes(db)
    asked = {(e, tuple(sorted(p.items()))) for e, p in plan}
    assert ("/predictions", (("fixture", 5005),)) in asked
    assert ("/fixtures/rounds", (("dates", "true"), ("league", 39), ("season", 2025))) in asked
    assert ("/transfers", (("team", 33),)) in asked
    assert ("/fixtures/statistics", (("fixture", 1001), ("half", "true"))) in asked
    assert ("/sidelined", (("players", "77-909"),)) in asked and ("/trophies", (("player", 77),)) in asked
    assert len(asked) == len(plan), "each form once"
