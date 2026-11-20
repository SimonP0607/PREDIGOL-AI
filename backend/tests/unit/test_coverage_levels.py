"""The rules coverage-levels-v1 (PM-02-01, DM-04): the thresholds are the ones the code already decides with, the borders fall
where the plan says, and the module gives back the levels of annex B of the plan (measured on 19-nov-2026) for a sample of its
rows (``fixtures/coverage_levels_annex_b_sample.csv``: aggregate shares of public competitions, nothing else)."""

from __future__ import annotations

import csv
from pathlib import Path

import pytest

from fbi.api.services import market_status
from fbi.coverage import levels as lv
from fbi.coverage.levels import Grade, Level, Step, Summary
from fbi.market import coverage as market_coverage
from fbi.market import eligibility, settle_coverage
from fbi.market.settle_coverage import Coverage
from fbi.odds.quote_taxonomy import known_bet_ids, spec_for
from fbi.stats import team

SAMPLE = Path(__file__).resolve().parents[1] / "fixtures" / "coverage_levels_annex_b_sample.csv"

# ── thresholds: imported, never copied ───────────────────────────────────────────────────────────────────────────────


def test_the_thresholds_are_the_ones_the_code_already_decides_with() -> None:
    """A change of one of them upstream fails here: the matrix then needs a new rules version."""
    assert lv.B_SHARE is settle_coverage.MIN_SHARE
    assert lv.MIN_SAMPLE is settle_coverage.MIN_MATCHES
    # fbi.coverage may not import fbi.api (test_architecture): these two are written there and held equal here
    assert lv.C_SHARE == market_status.NO_SETTLEMENT
    assert lv.A_SAMPLE == market_status.MIN_SETTLE_SAMPLE
    assert lv.MIN_BOOKS is eligibility.MIN_BOOKS
    # the other copies of the same thresholds in the code still agree with them
    assert team.COVERAGE == market_coverage.COVERED_SHARE == lv.B_SHARE
    assert market_status.MIN_BOOKS == lv.MIN_BOOKS


def test_the_thresholds_of_coverage_levels_v1_are_the_ones_dm04_approved() -> None:
    """A change of any of them is a new rules version (``RULES_VERSION``), not an edit: this test then fails on purpose."""
    assert lv.RULES_VERSION == "coverage-levels-v1"
    assert (lv.A_SHARE, lv.B_SHARE, lv.C_SHARE) == (0.95, 0.80, 0.50)
    assert (lv.MIN_SAMPLE, lv.A_SAMPLE) == (10, 30)
    assert (lv.MIN_BOOKS, lv.A_BOOKS) == (3, 5)


def test_the_markets_are_keys_and_families_of_the_catalogue() -> None:
    families = {spec_for(b).family for b in known_bet_ids()}
    for key in lv.MARKETS:
        assert key in eligibility.CORE or key in families, key
    for keys in lv.MARKET_FAMILIES.values():
        assert set(keys) <= set(lv.MARKETS)
    for keys in lv.DATA_FAMILIES.values():
        assert set(keys) <= set(lv.DATA)
    assert tuple(sorted(lv.RANK, key=lv.RANK.__getitem__, reverse=True)) == lv.LEVELS


# ── borders of a datum ───────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("share", "n", "level"), [
    (0.95, 30, "A"), (0.949, 30, "B"), (0.95, 29, "B"), (1.0, 29, "B"), (0.95, 31, "A"),
    (0.80, 10, "B"), (0.799, 10, "C"), (0.80, 9, "MI"), (1.0, 9, "MI"),
    (0.50, 10, "C"), (0.499, 10, "D"), (0.0, 10, "D"), (0.0, 500, "D"),
    (None, 30, "MI"), (0.95, 0, "MI"),
])
def test_datum_level_borders(share: float | None, n: int, level: Level) -> None:
    assert lv.datum_level(share, n) == level


@pytest.mark.parametrize(("finished", "with_data", "level"), [
    (20, 19, "B"),     # exactly 95 % but n < 30
    (40, 38, "A"),     # exactly 95 % with n >= 30
    (1000, 949, "B"),  # 94.9 %
    (1000, 950, "A"),  # 95.0 %
    (1000, 799, "C"),  # 79.9 %
    (1000, 800, "B"),  # 80.0 %
    (10, 8, "B"),
    (10, 5, "C"),
    (10, 4, "D"),
    (9, 9, "MI"),
])
def test_exact_shares_from_counts(finished: int, with_data: int, level: Level) -> None:
    assert lv.grade_datum(Coverage(finished, with_data)).level == level


def test_no_finished_match_is_insufficient_sample_never_a_zero() -> None:
    assert lv.grade_datum(Coverage(0, 0)) == Grade("MI", False, "muestra_insuficiente")
    assert lv.grade_market(Coverage(0, 0), None) == Grade("MI", False, "muestra_insuficiente")


def test_b_below_30_matches_is_provisional_and_a_is_not() -> None:
    assert lv.grade_datum(Coverage(29, 29)) == Grade("B", True)
    assert lv.grade_datum(Coverage(30, 30)) == Grade("A", False)
    assert lv.grade_datum(Coverage(30, 25)) == Grade("B", False)
    assert lv.grade_datum(Coverage(10, 6)) == Grade("C", False)


def test_a_season_short_of_sample_takes_the_season_before_provisional() -> None:
    assert lv.grade_datum(Coverage(9, 9), previous="A") == Grade("A", True, "heredado")
    assert lv.grade_datum(Coverage(0, 0), previous="D") == Grade("D", True, "heredado")
    assert lv.grade_datum(Coverage(9, 9), previous="MI") == Grade("MI", False, "muestra_insuficiente")
    # with sample the season before does not count
    assert lv.grade_datum(Coverage(10, 1), previous="A") == Grade("D", False)


# ── borders of a market ──────────────────────────────────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(("books", "level"), [
    (5, "A"), (5.5, "A"), (4.5, "B"), (4, "B"), (3, "B"), (2.5, "C"), (2, "C"), (0, "C"), (None, "C"),
])
def test_market_houses_cap_the_level(books: float | None, level: Level) -> None:
    assert lv.market_level(1.0, 40, books) == level


def test_market_houses_never_raise_a_level_nor_lift_d_or_mi() -> None:
    assert lv.market_level(0.85, 40, 10) == "B"
    assert lv.market_level(0.60, 40, 10) == "C"
    assert lv.market_level(0.40, 40, 10) == "D"
    assert lv.market_level(0.40, 40, 1) == "D"
    assert lv.market_level(1.0, 9, 10) == "MI"
    assert lv.market_level(1.0, 29, 5) == "B"


def test_market_grade_says_what_capped_it() -> None:
    assert lv.grade_market(Coverage(40, 40), 4) == Grade("B", False, "menos_de_5_casas")
    assert lv.grade_market(Coverage(40, 40), 2) == Grade("C", False, "menos_de_3_casas")
    assert lv.grade_market(Coverage(20, 20), 2) == Grade("C", False, "menos_de_3_casas")
    assert lv.grade_market(Coverage(20, 20), 3) == Grade("B", True)
    assert lv.grade_market(Coverage(40, 22), 2) == Grade("C", False)  # 55 %: C without the cap
    assert lv.grade_market(Coverage(5, 5), 10, previous="B") == Grade("B", True, "heredado")


# ── phases and editions ──────────────────────────────────────────────────────────────────────────────────────────────


def test_phases_are_graded_apart_and_the_season_on_summed_counts() -> None:
    """The Champions case of section 4: the qualifying rounds drag the season down; split by phase, the league phase keeps A."""
    league_phase = Coverage(144, 144)
    qualifying = Coverage(160, 72)
    assert lv.grade_datum(league_phase).level == "A"
    assert lv.grade_datum(qualifying).level == "D"
    season = lv.combine([league_phase, qualifying])
    assert season == Coverage(304, 216)
    assert lv.grade_datum(season).level == "C"


def test_a_short_phase_is_short_of_sample_even_in_a_full_season() -> None:
    final = Coverage(1, 1)
    assert lv.grade_datum(final).level == "MI"
    editions = lv.combine([final] * 5)
    assert lv.grade_datum(editions).level == "MI"
    assert lv.grade_datum(lv.combine([Coverage(2, 2)] * 5)).level == "B"
    assert lv.combine([]) == Coverage(0, 0)


# ── families and summary ─────────────────────────────────────────────────────────────────────────────────────────────


def _all(level: Level) -> tuple[dict[str, Level], dict[str, Level]]:
    return dict.fromkeys(lv.DATA, level), dict.fromkeys(lv.MARKETS, level)


def test_a_family_is_its_worst_datum_and_mi_is_the_worst() -> None:
    assert lv.worst(["A", "B", "C"]) == "C"
    assert lv.worst(["A", "MI", "D"]) == "MI"
    data, markets = _all("A")
    data["shots"] = "D"
    markets["cards"] = "MI"
    fam = lv.family_levels(data, markets)
    assert fam["team_stats"] == "D"
    assert fam["stat_odds"] == "MI"
    assert fam["base"] == fam["main_odds"] == "A"
    assert set(fam) == set(lv.FAMILIES)
    with pytest.raises(ValueError, match="no level"):
        lv.worst([])


def test_a_family_needs_every_datum() -> None:
    data, markets = _all("A")
    del data["lineups"]
    with pytest.raises(KeyError):
        lv.family_levels(data, markets)


def test_summary_rules() -> None:
    data, markets = _all("A")
    assert lv.summary_level(data, markets) == Summary("A")
    markets["corners"] = "C"
    assert lv.summary_level(data, markets) == Summary("B")
    data, markets = _all("A")
    data["player_stats"] = "C"
    assert lv.summary_level(data, markets) == Summary("B")
    data, markets = _all("B")
    assert lv.summary_level(data, markets) == Summary("B")
    data["corners"] = "C"
    assert lv.summary_level(data, markets) == Summary("C")
    markets["1X2"] = "D"
    assert lv.summary_level(data, markets) == Summary("D")


def test_summary_without_odds_window() -> None:
    data, markets = _all("A")
    markets = dict.fromkeys(lv.MARKETS, "MI")
    assert lv.summary_level(data, markets) == Summary("B", without_odds=True)
    assert lv.summary_level(data, markets).label == "B*"
    data["yellow_cards"] = "D"
    assert lv.summary_level(data, markets).label == "C*"
    data["events"] = "C"
    assert lv.summary_level(data, markets) == Summary("D")
    data, markets = _all("MI")
    assert lv.summary_level(data, markets) == Summary("MI")
    assert Summary("C").label == "C"


# ── recalculation ────────────────────────────────────────────────────────────────────────────────────────────────────


def test_up_at_once_down_after_two_misses_in_a_row() -> None:
    assert lv.step(None, "C", missed_before=False) == Step("C")
    assert lv.step("B", "A", missed_before=False) == Step("A")
    assert lv.step("B", "A", missed_before=True) == Step("A")
    assert lv.step("B", "B", missed_before=True) == Step("B")
    first = lv.step("A", "B", missed_before=False)
    assert first == Step("A", missed=True)
    assert lv.step(first.level, "C", missed_before=first.missed) == Step("C")
    # a recalculation that meets the level again forgives the miss
    again = lv.step("A", "A", missed_before=True)
    assert lv.step(again.level, "B", missed_before=again.missed) == Step("A", missed=True)


# ── annex B of the plan, row by row ──────────────────────────────────────────────────────────────────────────────────

ANNEX_DATA: dict[str, str] = {
    "events": "eventos", "lineups": "alineaciones", "corners": "corners", "yellow_cards": "tarjetas_amarillas", "shots": "tiros",
    "shots_on_target": "tiros_puerta", "fouls": "faltas", "xg": "xg", "player_stats": "est_jugador", "referee": "arbitro",
}
ANNEX_MARKETS: dict[str, tuple[str, str | None]] = {
    # market -> (annex column, the annex column of the houses that price it; None: the annex does not measure them)
    "1X2": ("1x2", "1x2"), "OU": ("mas_menos", "mas_menos"), "BTTS": ("ambos_marcan", "1x2"), "AH": ("handicap", "1x2"),
    "goals_half": ("goles_por_mitad", "1x2"), "corners": ("corners", "corners"), "cards": ("tarjetas", "tarjetas"),
    "shots": ("tiros", "tiros"), "players": ("jugador", None),
}
ANNEX_FAMILIES: dict[str, str] = {
    "base": "familia_base", "team_stats": "familia_estadisticas_equipo", "xg": "familia_xg",
    "player_stats": "familia_estadisticas_jugador", "referee": "familia_arbitro", "main_odds": "familia_cuotas_principales",
    "stat_odds": "familia_cuotas_estadisticas",
}
NO_WINDOW = "sin ventana"


def _share(pct: str) -> float | None:
    return float(pct) / 100 if pct else None


def _books(value: str) -> float | None:
    return float(value) if value else None


def annex_row(row: dict[str, str]) -> dict[str, str]:
    """The annex's level columns as this module computes them from the row's measured columns. With no match in the odds window
    the annex writes «sin ventana» where the module says ``MI``."""
    n, window = int(row["n_terminados"]), int(row["n_terminados_ventana_cuotas"] or 0)
    data: dict[str, Level] = {d: lv.datum_level(_share(row[f"pct_{c}"]), n) for d, c in ANNEX_DATA.items()}
    markets: dict[str, Level] = {}
    for key, (col, books_col) in ANNEX_MARKETS.items():
        books = _books(row[f"mediana_casas_{books_col}"]) if books_col else None
        share = _share(row[f"pct_cuotas_{col}"])
        markets[key] = lv.market_level(share, window, books) if books_col else lv.datum_level(share, window)
    out: dict[str, str] = {f"nivel_{ANNEX_DATA[d]}": level for d, level in data.items()}
    for key, (col, _) in ANNEX_MARKETS.items():
        out[f"nivel_cuotas_{col}"] = NO_WINDOW if window == 0 else markets[key]
    for fam, level in lv.family_levels(data, markets).items():
        out[ANNEX_FAMILIES[fam]] = NO_WINDOW if window == 0 and fam in lv.MARKET_FAMILIES else level
    out["nivel_global_resumen"] = lv.summary_level(data, markets).label
    return out


def _rows() -> list[dict[str, str]]:
    with SAMPLE.open(encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def test_the_sample_covers_every_summary_and_the_borders() -> None:
    rows = _rows()
    assert len(rows) >= 40
    assert {r["nivel_global_resumen"] for r in rows} == {"A", "B", "C", "D", "MI", "B*", "C*"}
    assert {r["reglas"] for r in rows} == {lv.RULES_VERSION}


@pytest.mark.parametrize("row", _rows(), ids=lambda r: f"{r['liga_id']}-{r['temporada']}")
def test_reproduces_annex_b(row: dict[str, str]) -> None:
    got = annex_row(row)
    assert got == {k: row[k] for k in got}
