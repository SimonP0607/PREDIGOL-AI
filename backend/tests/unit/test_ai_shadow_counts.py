"""The report of the corners and the cards of the shadow (``fbi.ai.shadow.counts_report``, Plan Maestro IA phase 4): the figures the plan asks for - CLV of each
evaluation, abstentions, Brier and log loss against the market - derived from reviews and counts, with no database, and never a verdict of pass."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from fbi.ai import shadow
from fbi.ai.config import PRODUCTION_ENGINES, SHADOW_ENGINES
from fbi.families import score

KICKOFF = datetime(2026, 11, 1, 19, 0, tzinfo=UTC)


def row(fixture: int, market: str, selection: str, line: str, *, decision: str = "APPROVE", status: str = "ok", stance: str | None = "SUPPORT",
        p_model: str = "0.60", p_market: str | None = "0.50", odds: str = "2.00", p_close: str | None = "0.55", day: int = 0) -> dict[str, Any]:
    return {"fixture_id": fixture, "market_key": market, "selection": selection, "line": Decimal(line), "odds": Decimal(odds), "bookmaker_id": 1,
            "p_model": Decimal(p_model), "p_market": None if p_market is None else Decimal(p_market), "decision": decision, "status": status,
            "reviewed_at": KICKOFF - timedelta(hours=3), "kickoff_at": KICKOFF + timedelta(days=day), "stance": stance,
            "p_close": None if p_close is None else Decimal(p_close)}


COUNTS = {1: {"corners_ft_home": 6, "corners_ft_away": 5, "cards_lines_ft_home": 3, "cards_lines_ft_away": 3},
          2: {"corners_ft_home": 3, "corners_ft_away": 4, "cards_lines_ft_home": 1, "cards_lines_ft_away": 2},
          3: {"corners_ft_home": 5, "corners_ft_away": 5, "cards_lines_ft_home": 2, "cards_lines_ft_away": 2}}


def test_corners_and_cards_are_settled_on_the_counts_and_the_halves_never_are() -> None:
    rows = [row(1, "CORNERS_OU", "Over", "9.5"), row(1, "CORNERS_OU", "Under", "9.5"), row(1, "CARDS_OU", "Over", "5.5"), row(1, "CARDS_OU_HOME", "Over", "2.5"),
            row(1, "CORNERS_OU_1H", "Over", "4.5"), row(1, "CARDS_OU_2H", "Over", "1.5"), row(9, "CORNERS_OU", "Over", "9.5"), row(3, "CORNERS_OU", "Over", "10.0")]
    items, left = shadow.counts_of(rows, COUNTS, score)
    assert left == {"half": 2, "ungradable": 1, "unreadable": 0}, "a match with no counts is ungradable and never a zero; the halves are never graded"
    assert [(c.family, c.item.status) for c in items] == [("CORNERS", "win"), ("CORNERS", "loss"), ("CARDS", "win"), ("CARDS", "win"), ("CORNERS", "push")]
    assert all(c.stance == "SUPPORT" and c.answered for c in items)
    assert items[2].item.profit == pytest.approx(1.0) and items[4].item.profit == 0.0 and items[1].item.profit == pytest.approx(-1.0)


def test_a_key_nobody_can_read_is_left_out_not_raised() -> None:
    items, left = shadow.counts_of([row(1, "CORNERS_WHATEVER", "Over", "9.5")], COUNTS, score)
    assert items == [] and left["unreadable"] == 1


def test_the_arms_carry_clv_abstentions_and_the_model_against_the_market() -> None:
    rows = [row(1, "CORNERS_OU", "Over", "9.5", stance="SUPPORT"), row(1, "CARDS_OU", "Over", "5.5", stance="CONCERN", decision="DOWNGRADE", p_close="0.45"),
            row(2, "CORNERS_OU", "Under", "9.5", stance="NEUTRAL", decision="ABSTAIN", status="fallback", p_model="0.5", p_market="0.52"),
            row(2, "CARDS_OU", "Under", "5.5", stance=None, decision="REJECT", p_model="0.40", p_market="0.45", p_close=None)]
    items, _ = shadow.counts_of(rows, COUNTS, score)
    arms = shadow.counts_arms(items)
    assert arms["n"] == 4 and arms["abstentions"] == {"abstained": 1, "no_answer": 1, "rate": 0.25}
    assert set(arms["by_stance"]) == {"SUPPORT", "CONCERN", "NEUTRAL", "none"} and arms["by_stance"]["SUPPORT"]["n"] == 1
    assert arms["by_stance"]["SUPPORT"]["clv"] == pytest.approx(2.0 * 0.55 - 1) and arms["by_stance"]["CONCERN"]["clv"] == pytest.approx(2.0 * 0.45 - 1)
    assert arms["by_stance"]["none"]["clv"] is None and arms["by_stance"]["none"]["n_clv"] == 0, "no closing price, no CLV: never invented"
    assert arms["by_decision"]["abstained"]["n"] == 1 and arms["by_decision"]["rejected"]["n"] == 1 and arms["by_decision"]["kept"]["n"] == 3
    vs = arms["versus_market"]
    assert vs["n"] == 4 and set(vs) == {"n", "brier_model", "brier_market", "brier_gain", "logloss_model", "logloss_market", "logloss_gain"}
    assert vs["brier_gain"] == pytest.approx(vs["brier_market"] - vs["brier_model"], abs=1e-4)
    assert set(arms["by_family"]) == {"CORNERS", "CARDS"} and arms["by_family"]["CARDS"]["versus_market"]["n"] == 2


def test_with_nothing_settled_the_arms_say_so_and_invent_nothing() -> None:
    arms = shadow.counts_arms([])
    assert arms["n"] == 0 and arms["abstentions"]["rate"] is None and arms["versus_market"] == {"n": 0} and arms["all"] == {"n": 0}
    assert shadow.versus_market([]) == {"n": 0}


class NoDatabase:
    """A connection whose cursor yields no review: the report of an empty shadow."""

    def cursor(self, *args: Any, **kw: Any) -> Any:
        class Cur:
            def __enter__(self) -> Cur:
                return self

            def __exit__(self, *exc: Any) -> None:
                return None

            def execute(self, *a: Any, **k: Any) -> None:
                return None

            def fetchall(self) -> list[Any]:
                return []

        return Cur()


def test_the_report_never_says_pass_and_counts_the_days_it_rests_on() -> None:
    report = shadow.counts_report(NoDatabase(), score, at=KICKOFF)  # type: ignore[arg-type]
    assert report["version"] == "ai-counts-v1" and report["verdict"] == "not_judged" and "pass" not in report["verdict"].lower()
    assert report["evidence"] == {"days": 0, "need_days": 14, "enough_days": False}
    assert list(report["engines"]) == list(SHADOW_ENGINES) and all(e["n"] == 0 for e in report["engines"].values())
    assert set(report) == {"version", "at", "window", "verdict", "reason", "evidence", "engines"}


def test_the_counts_report_is_not_the_gate_and_adds_no_engine() -> None:
    assert shadow.VERSION == "ai-gate-v2" and shadow.COUNTS_VERSION != shadow.VERSION
    assert (*PRODUCTION_ENGINES, *SHADOW_ENGINES) == shadow.ENGINES, "the engines of the shadow are the three of phase 3: the Statistics Agent is no engine"
