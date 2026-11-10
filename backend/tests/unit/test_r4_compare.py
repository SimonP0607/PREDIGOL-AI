"""The R4 comparison (IA-029): review-v2 beside the Council of the shadow, as pure arithmetic over rows - and it decides nothing."""

from __future__ import annotations

import inspect
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest

from fbi.ai import r4_compare as r4
from fbi.ai import r4_readers
from fbi.ai.config import PRODUCTION_ENGINES, SHADOW_ENGINES

KICK = datetime(2026, 11, 8, 20, 0, tzinfo=UTC)
_ids = iter(range(1, 10_000))


def rv(engine: str, decision: str, *, fixture: int = 1, selection: str = "Home", hours: float = 2, status: str = "ok", odds: str | None = "2.00",
       outcome: str | None = None, prof: float | None = None, clv: float | None = None, cost: str = "0.01", rid: int | None = None) -> r4.Review:
    return r4.Review(next(_ids) if rid is None else rid, engine, fixture, "1X2", selection, Decimal("0"), decision, status, KICK - timedelta(hours=hours),
                     KICK, None if odds is None else Decimal(odds), "m", Decimal(cost), outcome, prof, clv)


def test_the_newest_review_made_before_the_kick_off_is_the_one_compared() -> None:
    old, new = rv("llm", "APPROVE", hours=5), rv("llm", "REJECT", hours=1)
    late = rv("llm", "APPROVE", hours=-1)
    failed = rv("llm", "APPROVE", hours=0.5, status="invalid_output")
    by = r4.newest([new, old, late, failed])
    assert list(by["llm"].values()) == [new], "the newest before the kick-off; after it, or a review that judged nothing, never"
    tie_a, tie_b = rv("ma-v1", "APPROVE", hours=3, rid=500), rv("ma-v1", "REJECT", hours=3, rid=501)
    assert list(r4.newest([tie_b, tie_a])["ma-v1"].values()) == [tie_b], "a tie in time goes to the later row"
    assert rv("rules", "APPROVE", status="fallback").key == (1, "1X2", "Home", "0")


def test_the_line_is_one_key_however_it_is_written() -> None:
    a = r4.Review(1, "llm", 1, "OU", "Over", Decimal("2.50"), "APPROVE", "ok", KICK - timedelta(hours=1), KICK)
    b = r4.Review(2, "ma-v1", 1, "OU", "Over", Decimal("2.5"), "APPROVE", "ok", KICK - timedelta(hours=1), KICK)
    assert a.key == b.key == (1, "OU", "Over", "2.5")


def test_the_matrix_the_agreement_and_its_interval() -> None:
    rows = [rv("llm", "APPROVE", fixture=1), rv("ma-v1", "APPROVE", fixture=1),
            rv("llm", "REJECT", fixture=2), rv("ma-v1", "APPROVE", fixture=2, outcome="win", prof=1.0, clv=0.05),
            rv("llm", "DOWNGRADE", fixture=3), rv("ma-v1", "ABSTAIN", fixture=3),
            rv("llm", "APPROVE", fixture=4), rv("ma-v1", "REJECT", fixture=4, odds="3.00"),
            rv("llm", "APPROVE", fixture=5)]
    rows[6] = rv("llm", "APPROVE", fixture=4, outcome="loss", prof=-1.0, clv=-0.02)
    p = r4.agreement(r4.newest(rows), "llm", "ma-v1")
    assert p["common"] == 4 and p["only"] == {"llm": 1, "ma-v1": 0}
    assert p["matrix"] == {"APPROVE|APPROVE": 1, "APPROVE|REJECT": 1, "DOWNGRADE|ABSTAIN": 1, "REJECT|APPROVE": 1}
    assert (p["agree"]["counted"], p["agree"]["cases"], p["agree"]["pct"]) == (1, 4, "25.0") and p["agree"]["ci95_wilson_pct"] is not None
    assert (p["agree_on_reject_or_not"]["counted"], p["agree_on_reject_or_not"]["cases"]) == (2, 4)
    assert p["agree"]["decides"] is False


def test_a_disagreement_is_read_at_the_price_of_the_engine_that_kept_it() -> None:
    rows = [rv("llm", "REJECT", fixture=2, outcome="win", prof=1.0), rv("ma-v1", "APPROVE", fixture=2, odds="2.50", outcome="win", prof=1.5, clv=0.1),
            rv("llm", "APPROVE", fixture=4, outcome="loss", prof=-1.0, clv=-0.04), rv("ma-v1", "REJECT", fixture=4, outcome="loss", prof=-1.0),
            rv("llm", "REJECT", fixture=6), rv("ma-v1", "DOWNGRADE", fixture=6)]
    d = r4.agreement(r4.newest(rows), "llm", "ma-v1")["disagreements_on_reject"]
    llm_rejects, council_rejects = d["llm_rejects"], d["ma-v1_rejects"]
    assert (llm_rejects["selections"], llm_rejects["settled"], llm_rejects["won"], llm_rejects["lost"]) == (2, 1, 1, 0)
    assert llm_rejects["profit_flat_stake"] == 1.5 and llm_rejects["roi_pct"] == 150.0, "the Council kept it at 2.50: what following it did"
    assert llm_rejects["mean_clv_pct"] == 10.0 and llm_rejects["with_clv"] == 1 and llm_rejects["positive_clv"]["counted"] == 1
    assert (council_rejects["selections"], council_rejects["lost"], council_rejects["profit_flat_stake"]) == (1, 1, -1.0)
    assert council_rejects["won_of_decided"]["cases"] == 1 and council_rejects["mean_clv_pct"] == -4.0


def test_the_outcome_is_the_settlements_at_a_flat_stake() -> None:
    assert r4.settle("1X2", "Home", Decimal(0), 2, 1, Decimal("2.10")) == ("win", pytest.approx(1.1))
    assert r4.settle("1X2", "Home", Decimal(0), 0, 1, Decimal("2.10")) == ("loss", -1.0)
    assert r4.settle("1X2", "Home", Decimal(0), None, None, Decimal("2.10")) == (None, None), "not settled yet"
    assert r4.settle("1X2", "Home", Decimal(0), 2, 1, None) == (None, None), "no price, no profit"
    assert r4.settle("NO_SUCH_MARKET", "x", Decimal(0), 2, 1, Decimal(2)) == (None, None)
    assert r4.clv_of(Decimal("2.0"), Decimal("0.55")) == pytest.approx(0.10) and r4.clv_of(None, Decimal("0.5")) is None


def test_a_row_of_the_reader_becomes_a_review_with_its_outcome_and_clv() -> None:
    row: dict[str, Any] = {"id": 9, "engine": "llm", "fixture_id": 3, "market_key": "1X2", "selection": "Away", "line": Decimal("0.00"),
                           "odds": Decimal("3.000"), "decision": "APPROVE", "status": "ok", "reviewed_at": KICK - timedelta(hours=1), "kickoff_at": KICK,
                           "model": "claude-opus-5-5", "cost_usd": Decimal("0.090000"), "reg_goals_home": 0, "reg_goals_away": 2, "p_close": Decimal("0.40")}
    r = r4.review_of(row)
    assert (r.outcome, r.profit, r.key) == ("win", 2.0, (3, "1X2", "Away", "0")) and r.clv == pytest.approx(0.2) and r.settled
    pending = r4.review_of(row | {"reg_goals_home": None, "reg_goals_away": None, "p_close": None})
    assert (pending.outcome, pending.profit, pending.clv, pending.settled) == (None, None, None, False)


def test_kept_and_rejected_and_the_engine_summary() -> None:
    rows = {r.key: r for r in (rv("ma-v1", "APPROVE", fixture=1, outcome="win", prof=1.0, cost="0.02"),
                               rv("ma-v1", "REJECT", fixture=2, outcome="loss", prof=-1.0, cost="0.03"),
                               rv("ma-v1", "DOWNGRADE", fixture=3))}
    s = r4.engine_summary("ma-v1", rows)
    assert s["selections"] == 3 and s["decisions"] == {"APPROVE": 1, "DOWNGRADE": 1, "REJECT": 1} and s["fixtures"] == 3
    assert s["cost_usd_of_the_compared_reviews"] == "0.06" and (s["reject_rate"]["counted"], s["reject_rate"]["cases"]) == (1, 3)
    assert (s["kept"]["selections"], s["kept"]["settled"], s["kept"]["roi_pct"]) == (2, 1, 100.0)
    assert (s["rejected"]["selections"], s["rejected"]["lost"], s["kept"]["won_of_decided"]["cases"]) == (1, 1, 1)


def test_the_spend_of_the_window_by_prompt_and_model() -> None:
    inv = r4.usage_inventory([{"purpose": "pick_review", "prompt_version": "review-v2", "model": "claude-opus-5-5", "calls": 3, "usd": Decimal("1.5")},
                              {"purpose": "pick_review", "prompt_version": "council-v1", "model": "claude-sonnet-5-5", "calls": 5, "usd": Decimal("0.5")}])
    assert inv["total_usd"] == "2.00" and inv["calls"] == 8
    assert [(i["prompt_version"], i["usd"], i["share_pct"]) for i in inv["lines"]] == [("review-v2", "1.50", "75.0"), ("council-v1", "0.50", "25.0")]
    assert r4.usage_inventory([]) == {"total_usd": "0.00", "calls": 0, "lines": []}


def test_an_empty_window_is_a_report_of_zeros_and_decides_nothing() -> None:
    rep = r4.report([], [])
    assert rep["version"] == r4.R4_VERSION == "r4-compare-v1" and rep["decides"] is False
    assert set(rep["engines"]) == set(r4.ENGINES) and set(rep["pairs"]) == {f"{a}_vs_{b}" for a, b in r4.PAIRS}
    assert all(p["common"] == 0 and p["agree"]["interval_vs_threshold"] == "no_cases" for p in rep["pairs"].values())
    text = r4.lines(rep)
    assert text[0].startswith("Comparación r4-compare-v1 (informa, no decide)") and any("0 casos" in t for t in text)


def test_every_rate_carries_its_interval_and_none_a_threshold() -> None:
    rows = [rv("llm", "APPROVE", fixture=f) for f in range(1, 6)] + [rv("ma-v1", "APPROVE" if f % 2 else "REJECT", fixture=f) for f in range(1, 6)]
    rep = r4.report(rows, [], since=KICK - timedelta(days=7), until=KICK)

    def proportions(node: Any) -> list[dict[str, Any]]:
        if isinstance(node, dict):
            found = [node] if "interval_vs_threshold" in node else []
            return found + [p for v in node.values() for p in proportions(v)]
        if isinstance(node, list):
            return [p for v in node for p in proportions(v)]
        return []

    found = proportions(rep)
    assert found and all(p["decides"] is False and p["threshold_pct"] is None for p in found)
    assert rep["pairs"]["llm_vs_ma-v1"]["agree"]["counted"] == 3 and any("llm_vs_ma-v1: 5 en común" in t for t in r4.lines(rep))


def test_the_readers_name_their_engines_one_list_of_production_and_one_of_the_shadow() -> None:
    assert set(r4.PRODUCTION) <= set(PRODUCTION_ENGINES) and set(r4.SHADOW) <= set(SHADOW_ENGINES)
    assert "r.engine IN ('llm', 'rules')" in r4_readers.PRODUCTION_SQL and "'ma-v1'" not in r4_readers.PRODUCTION_SQL
    assert "r.engine IN ('ma-v1', 'ma-v1-h', 'cs-v1')" in r4_readers.SHADOW_SQL and "'llm'" not in r4_readers.SHADOW_SQL
    for sql in (r4_readers.PRODUCTION_SQL, r4_readers.SHADOW_SQL):
        assert "r.reviewed_at < f.kickoff_at" in sql and "r.status IN ('ok', 'fallback')" in sql and "devig_method = 'shin'" in sql
    for sql in (r4_readers.PRODUCTION_SQL, r4_readers.SHADOW_SQL, r4_readers.USAGE_SQL):
        assert not any(w in sql.upper() for w in ("INSERT", "UPDATE ", "DELETE", "CREATE", "ALTER")), "it reads only"


def test_the_script_opens_the_database_read_only_and_writes_nothing() -> None:
    from scripts import ia_r4_compare as script

    source = inspect.getsource(script)
    assert "default_transaction_read_only=on" in source and "conn.read_only = True" in source and ".commit(" not in source
    start, end = script.window(script.DEFAULT_SINCE, None, now=KICK)
    assert start == datetime(2026, 10, 26, tzinfo=UTC) and end == KICK
    with pytest.raises(ValueError):
        script.window(KICK.date(), KICK.date(), now=KICK)
    assert script.main(["--since", "2026-11-10", "--until", "2026-11-09"]) == script.CANNOT
