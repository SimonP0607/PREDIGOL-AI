"""PM-13-03 (BE-065, second PR): the change-only insert of ``core.fixture_facts`` compares with the match's newest row through the primary
key (newest first, LIMIT 1), not through the view ``core.fixture_facts_latest``, which the planner sorted whole at every call (807,211 calls
at 171.9 ms on average from 9 to 20-nov-2026; 0.33 ms with the new form in EXPLAIN ANALYZE on the same match). The behaviour - one row per
change, never rewriting what a newer payload established - is the integration tests' (test_fixture_facts.py, test_detail_newest_wins.py)."""

from __future__ import annotations

import re

from fbi.ingestion import fixture_facts as ff


def flat(sql: str) -> str:
    return re.sub(r"\s+", " ", sql)


def test_the_facts_insert_reads_the_newest_row_by_the_primary_key() -> None:
    sql = flat(ff.FACTS_SQL)
    assert "fixture_facts_latest" not in sql
    assert "FROM core.fixture_facts n WHERE n.fixture_id = f.id ORDER BY n.observed_at DESC LIMIT 1" in sql
    for column in ("referee", "referee_country", "home_winner", "away_winner", "first_half_at", "second_half_at"):
        assert f"n.{column}" in sql and f"l.{column}" in sql, column


def test_the_extras_insert_keeps_its_view_whose_keys_are_parameters() -> None:
    sql = flat(ff.EXTRAS_SQL)
    assert "core.fixture_player_extras_latest l WHERE l.fixture_id = %(f)s AND l.provider_player_id = %(p)s" in sql
