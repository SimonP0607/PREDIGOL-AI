"""PM-08-02: the block «Árbitro designado» (``fbi.people.referee_block``) - the intervals checked against an independent computation, the
gate of the matrix (B or better), the short samples, the contract, and nothing exposed (DM-08)."""

from __future__ import annotations

import math
from datetime import UTC, datetime
from pathlib import Path

import pytest
from scipy import stats

from fbi.api.contracts.referees import RefereeBlockOut
from fbi.people import referee_block as rb


@pytest.mark.parametrize(("hits", "n"), [(0, 12), (3, 20), (7, 31), (15, 40), (40, 40), (1, 1)])
def test_the_wilson_interval_against_an_independent_computation(hits: int, n: int) -> None:
    f = rb.share("penalty_share", hits, n, 30, 200)
    z = stats.norm.ppf(0.975)
    p = hits / n
    centre, half = (p + z * z / (2 * n)) / (1 + z * z / n), z / (1 + z * z / n) * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n))
    assert f.low == pytest.approx(max(0.0, centre - half), abs=1e-9) and f.high == pytest.approx(min(1.0, centre + half), abs=1e-9)
    assert f.league_value == pytest.approx(30 / 200)


@pytest.mark.parametrize(("total", "n"), [(0, 10), (47, 12), (120, 25), (310, 61)])
def test_the_poisson_score_interval_solves_its_own_equation(total: int, n: int) -> None:
    low, high = rb.poisson_score(total, n)
    z = stats.norm.ppf(0.975)
    # the score interval is the set of rates lambda with |x - n*lambda| <= z*sqrt(n*lambda): its ends solve the equality
    for lam in (low, high):
        if lam > 0:
            assert abs(total - n * lam) == pytest.approx(z * math.sqrt(n * lam), rel=1e-6)
    assert low <= total / n <= high
    # and it is close to the exact (Garwood) interval for a count this size
    if total >= 40:
        exact_low, exact_high = stats.chi2.ppf(0.025, 2 * total) / 2 / n, stats.chi2.ppf(0.975, 2 * total + 2) / 2 / n
        assert low == pytest.approx(exact_low, rel=0.03) and high == pytest.approx(exact_high, rel=0.03)


def test_a_short_sample_and_no_sample_say_so() -> None:
    assert rb.rate("cards_per_match", 20, 4, 900, 200).state == "muestra_corta"
    assert rb.rate("cards_per_match", 50, 10, 900, 200).state == "medido"
    empty = rb.share("red_card_share", 0, 0, 10, 200)
    assert (empty.state, empty.value, empty.low, empty.n) == ("sin_datos", None, None, 0)


def test_the_block_appears_only_with_b_or_better() -> None:
    assert rb.gate({"referee": "A", "yellow_cards": "B", "events": "A"}) == dict.fromkeys(rb.NEEDS, "visible")
    got = rb.gate({"referee": "B", "yellow_cards": "C", "events": "A"})
    assert got == {"cards_per_match": "sin_cobertura", "red_card_share": "sin_cobertura", "penalty_share": "visible"}
    assert rb.gate({"referee": "D", "yellow_cards": "A", "events": "A"}) == dict.fromkeys(rb.NEEDS, "sin_cobertura")
    assert rb.gate({"referee": None, "yellow_cards": "A", "events": "A"}) == dict.fromkeys(rb.NEEDS, "sin_medir")


def test_the_block_fits_the_reader_contract_and_is_never_exposed() -> None:
    block = rb.RefereeBlock(1, datetime(2026, 11, 20, tzinfo=UTC), "construido", 7, "Wilmar Roldán", "Colombia", 31,
                            [rb.rate("cards_per_match", 140, 30, 4000, 900), rb.share("red_card_share", 4, 30, 80, 900),
                             rb.share("penalty_share", 9, 31, 250, 950)],
                            rb.gate({"referee": "A", "yellow_cards": "A", "events": "A"}),
                            {"referee": "A", "yellow_cards": "A", "events": "A"})
    out = RefereeBlockOut.model_validate(block.as_json())
    assert out.exposed is False and out.version == rb.VERSION and len(out.figures) == 3
    assert all(f.interval95 is not None and f.interval95[0] <= (f.value or 0) <= f.interval95[1] for f in out.figures)


def test_the_constants_and_the_switch() -> None:
    from fbi.intel.dossier import REFEREE_WINDOW

    assert rb.WINDOW == REFEREE_WINDOW
    assert rb.mode({}) == "off" and rb.mode({rb.SWITCH: "1"}) == "on"
    assert "sin cruces con equipos" in rb.RULE


def test_no_route_page_or_packet_reads_the_block() -> None:
    src = Path(rb.__file__).resolve().parents[1]
    readers = sorted(str(p.relative_to(src)) for p in src.rglob("*.py")
                     if ("referee_block" in p.read_text(encoding="utf-8") or "RefereeBlockOut" in p.read_text(encoding="utf-8"))
                     and p.name not in ("referee_block.py", "referees.py"))
    assert readers == [], readers
    routers = (src / "api" / "routers").rglob("*.py")
    assert not [p for p in routers if "RefereeBlockOut" in p.read_text(encoding="utf-8")]


def test_no_crossing_of_a_referee_with_a_team() -> None:
    sql = (rb.REFEREE_SQL + rb.LEAGUE_SQL).lower()
    assert "home_team_id" not in sql and "away_team_id" not in sql and "team_id =" not in sql
