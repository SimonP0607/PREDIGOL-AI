"""PM-08-02: the block «Árbitro designado» on a real database, as of a moment - his matches under every spelling, the cards from the
team statistics and the penalties from the events (the shoot-out excluded), the league's figure in the same window, the matrix's gate,
a match without a referee named, and the owner's command validating the reader contract."""

from __future__ import annotations

from datetime import timedelta

import pytest

from fbi.api.contracts.referees import RefereeBlockOut
from fbi.people import referee_block as rb
from fbi.people import referees as store
from tests.integration import test_referee_identity_store as identity_store
from tests.integration.test_referee_identity_store import T0, World

pytestmark = pytest.mark.integration
world = identity_store.world
"""The fixture of the referees' tests (three domestic competitions and a continental cup)."""


def played(w: World, fixture_id: int, *, cards: tuple[int, int, int, int], penalties: int = 0, shootout: int = 0) -> None:
    """A result, both teams' cards (home yellow, home red, away yellow, away red) and the penalties (events)."""
    ko = w.db.execute("SELECT kickoff_at FROM core.fixtures WHERE id = %s", (fixture_id,)).fetchone()
    assert ko is not None
    w.db.execute("UPDATE core.fixtures SET status_short = 'FT', status_group = 'finished' WHERE id = %s", (fixture_id,))
    w.db.execute("INSERT INTO core.fixture_results (fixture_id, goals_home, goals_away, settled_at) VALUES (%s, 1, 1, %s)",
                 (fixture_id, ko[0] + timedelta(hours=2)))
    for side, (y, r) in (("home", cards[:2]), ("away", cards[2:])):
        w.db.execute("INSERT INTO core.fixture_team_stats (fixture_id, team_side, source, yellow_cards, red_cards, payload_hash, "
                     "fetched_at) VALUES (%s, %s, 'api-football', %s, %s, %s, %s)", (fixture_id, side, y, r, w.seed.payload_hash,
                                                                                    ko[0] + timedelta(hours=3)))
    seq = 0
    for kind, n in (("Penalty", penalties), ("Shootout", shootout)):
        for _ in range(n):
            w.db.execute("INSERT INTO core.fixture_events (fixture_id, source, seq, minute, team_side, event_type, detail, comments, "
                         "payload_hash, fetched_at) VALUES (%s, 'api-football', %s, 50, 'home', 'Goal', 'Penalty', %s, %s, %s)",
                         (fixture_id, seq, "Penalty Shootout" if kind == "Shootout" else None, w.seed.payload_hash,
                          ko[0] + timedelta(hours=3)))
            seq += 1
    if seq == 0:
        w.db.execute("INSERT INTO core.fixture_events (fixture_id, source, seq, minute, team_side, event_type, detail, payload_hash, "
                     "fetched_at) VALUES (%s, 'api-football', 0, 10, 'home', 'Card', 'Yellow Card', %s, %s)",
                     (fixture_id, w.seed.payload_hash, ko[0] + timedelta(hours=3)))


def levels(w: World, cs: int, **lv: str) -> None:
    for datum, level in lv.items():
        w.db.execute("INSERT INTO analytics.coverage_cells (competition_season_id, phase_key, datum, n_finished, n_with_data, share, "
                     "level, measured_level, rules_version, measured_at) VALUES (%s, 'todas', %s, 100, 100, 1, %s, %s, "
                     "'coverage-levels-v1', now()) ON CONFLICT DO NOTHING", (cs, datum, level, level))


def test_the_block_of_a_referee_against_his_league(world: World) -> None:
    w = world
    mine = [w.match("England", d, "Michael Oliver" if d % 2 else "M. Oliver", "England" if d % 2 else None) for d in range(1, 13)]
    others = [w.match("England", d, "Anthony Taylor", "England", hour=18) for d in range(1, 9)]
    for k, fid in enumerate(mine):
        played(w, fid, cards=(2, 0, 2, 1 if k == 0 else 0), penalties=1 if k < 3 else 0, shootout=2 if k == 5 else 0)
    for fid in others:
        played(w, fid, cards=(1, 0, 1, 0))
    target = w.match("England", 40, "Michael Oliver", "England")
    store.build(w.db, apply=True)
    levels(w, w.seasons["England"], referee="A", yellow_cards="A", events="B")
    at = T0 + timedelta(days=39)

    block = rb.block_of(w.db, target, at=at)
    assert block is not None and block.state == "construido" and block.name == "Michael Oliver"
    assert block.matches == 12
    f = {x.key: x for x in block.figures}
    assert f["cards_per_match"].n == 12 and f["cards_per_match"].value == pytest.approx(49 / 12)
    assert f["red_card_share"].n == 12 and f["red_card_share"].value == pytest.approx(1 / 12)
    assert f["penalty_share"].n == 12 and f["penalty_share"].value == pytest.approx(3 / 12)  # the shoot-out is not a penalty awarded
    assert f["cards_per_match"].league_n == 20 and f["cards_per_match"].league_value == pytest.approx((49 + 16) / 20)
    assert all(x.state == "medido" for x in block.figures)
    assert block.visibility == dict.fromkeys(rb.NEEDS, "visible")
    out = RefereeBlockOut.model_validate(block.as_json())
    assert out.exposed is False

    # before his last matches were played (and before their results were recorded), they are not his yet
    early = rb.block_of(w.db, target, at=T0 + timedelta(days=6, hours=6))
    assert early is not None and early.matches == 6


def test_no_referee_named_and_a_league_short_of_b(world: World) -> None:
    w = world
    fid = w.fixture("Spain", 3)
    block = rb.block_of(w.db, fid, at=T0 + timedelta(days=2))
    assert block is not None and block.state == "sin_arbitro" and block.figures == []
    assert block.visibility == dict.fromkeys(rb.NEEDS, "sin_medir")
    levels(w, w.seasons["Spain"], referee="C", yellow_cards="A", events="A")
    later = rb.block_of(w.db, fid, at=T0 + timedelta(days=2))
    assert later is not None and later.visibility == dict.fromkeys(rb.NEEDS, "sin_cobertura")
    assert rb.block_of(w.db, -5, at=T0) is None
