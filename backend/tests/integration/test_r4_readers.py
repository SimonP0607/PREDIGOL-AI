"""The readers of the R4 comparison (IA-029) on a real database: the newest pre-match review of each selection by each engine, production's and the
shadow's read apart, with the regulation score - written by hand into a transaction that is rolled back."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from fbi.ai import r4_compare, r4_readers

from .conftest import Seed
from .test_shadow_engines_readers import Reviews

pytestmark = pytest.mark.integration

KICK = datetime(2032, 11, 10, 20, 0, tzinfo=UTC)


def test_the_readers_pair_the_newest_pre_match_review_of_each_engine(db: psycopg.Connection[Any], seed: Seed) -> None:
    w = Reviews(db, seed)
    played = w.fixture(KICK, score=(2, 1))
    open_ = w.fixture(KICK + timedelta(days=1))
    w.put(played, "llm", at=KICK - timedelta(hours=6), decision="APPROVE", priced=True)
    w.put(played, "llm", at=KICK - timedelta(hours=2), decision="REJECT", priced=True)  # the newest before the kick-off
    w.put(played, "llm", at=KICK + timedelta(minutes=5), decision="APPROVE", priced=True)  # after the kick-off: never compared
    w.put(played, "llm", at=KICK - timedelta(hours=1), decision="APPROVE", status="failed", priced=True)  # judged nothing
    w.put(played, "ma-v1", at=KICK - timedelta(hours=3), decision="APPROVE", priced=True)
    w.put(played, "cs-v1", at=KICK - timedelta(hours=3), decision="REJECT", priced=True)
    w.put(played, "combined", at=KICK - timedelta(hours=3), decision="APPROVE", priced=True)  # not an engine of the comparison
    w.put(open_, "ma-v1", at=KICK, decision="DOWNGRADE")

    got = r4_readers.reviews(db, since=KICK - timedelta(days=2), until=KICK + timedelta(days=2))
    by = r4_compare.newest(got)
    assert {e: len(v) for e, v in by.items()} == {"llm": 1, "ma-v1": 2, "cs-v1": 1}
    [llm] = by["llm"].values()
    assert (llm.decision, llm.outcome) == ("REJECT", "win") and llm.profit == pytest.approx(1.1), "Home won 2-1 at 2.10"
    rep = r4_compare.report(got, r4_readers.usage(db, since=KICK - timedelta(days=2), until=KICK + timedelta(days=2)))
    pair = rep["pairs"]["llm_vs_ma-v1"]
    assert pair["common"] == 1 and pair["matrix"] == {"REJECT|APPROVE": 1}
    kept = pair["disagreements_on_reject"]["llm_rejects"]
    assert (kept["selections"], kept["settled"], kept["won"], kept["profit_flat_stake"]) == (1, 1, 1, 1.1)
    assert rep["pairs"]["llm_vs_cs-v1"]["agree"]["counted"] == 1 and rep["decides"] is False
    assert not r4_readers.reviews(db, since=KICK + timedelta(days=3), until=KICK + timedelta(days=4)), "the window is the caller's"
