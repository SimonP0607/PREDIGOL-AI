"""IA-126 / IA-127 / IA-128 on a database: credibility-v2's snapshot appended once, the gate of the extraction signed by the owner before any
verdict (row 17 untouched), and the provider's facts read back from what the ingestion stored. One transaction, rolled back."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from fbi.ai import (
    extract_protocol,
    page_bank,
    provider_facts,
    provider_facts_reads,
    unified_readers,
)
from fbi.ai.evidence import EvidenceIn, store
from fbi.ai.gates import gate_state
from fbi.shadowjobs import source_credibility

from .conftest import Seed

pytestmark = pytest.mark.integration
NOW = datetime(2026, 11, 17, 12, tzinfo=UTC)


def _fixture(db: psycopg.Connection[Any], seed: Seed, n: int, kickoff: datetime) -> int:
    row = db.execute("INSERT INTO core.fixtures (provider_fixture_id, competition_season_id, home_team_id, away_team_id, kickoff_at) "
                     "VALUES (%s, %s, %s, %s, %s) RETURNING id", (50000 + n, seed.season_id, seed.home_team_id, seed.away_team_id, kickoff)).fetchone()
    assert row is not None
    return int(row[0])


def _lineup(db: psycopg.Connection[Any], seed: Seed, fixture: int, starters: list[int], bench: list[int], at: datetime) -> None:
    db.execute("INSERT INTO core.fixture_lineups (fixture_id, team_side, source, formation, payload_hash, fetched_at) "
               "VALUES (%s, 'home', 'api-football', '4-3-3', %s, %s)", (fixture, seed.payload_hash, at))
    for pid in starters + bench:
        db.execute("INSERT INTO core.fixture_lineup_players (fixture_id, team_side, source, provider_player_id, player_name, is_starter) "
                   "VALUES (%s, 'home', 'api-football', %s, %s, %s)", (fixture, pid, f"P{pid}", pid in starters))


def test_credibility_v2_is_learned_from_what_the_line_ups_resolved_and_kept_once(db: psycopg.Connection[Any], seed: Seed) -> None:
    for i in range(3):
        kickoff = NOW - timedelta(days=10 - i)
        fx = _fixture(db, seed, i, kickoff)
        _lineup(db, seed, fx, [7000 + i], [], kickoff - timedelta(hours=1))
        for pid in (7000 + i, 8000 + i):  # out: wrong for the first (he started), right for the second (not in the sheet)
            store(db, EvidenceIn(fx, seed.home_team_id, "injury", f"{pid} no jugará", "web", "Diario", kickoff - timedelta(days=1),
                                 f"t:{fx}:{pid}", assertion="out", provider_player_id=pid, source_url="https://diario.example/x",
                                 source_tier="media"), at=kickoff - timedelta(days=1))
    out = source_credibility.run(db, now=NOW, code_version="test", typed=False, record=True)
    assert out["written"] == out["rows"] >= 1 and out["claims"] == 6
    rows = db.execute("SELECT fact_type, resolved, corroborated, sufficient FROM ai.source_credibility WHERE outlet = 'diario.example'").fetchall()
    assert rows == [("baja", 6, 3, False)]
    again = source_credibility.run(db, now=NOW, code_version="test", typed=False, record=True)
    assert again["written"] == 0, "the same moment is kept once"
    status = db.execute("SELECT count(*) FROM ai.evidence WHERE status_changed_at > %s", (NOW,)).fetchone()
    assert status == (0,), "no status was changed"


def test_the_extraction_gate_needs_the_owners_signature_and_leaves_row_17_alone(db: psycopg.Connection[Any], seed: Seed) -> None:
    db.execute("INSERT INTO ai.feature_gates (gate, at, passed, evidence, evidence_hash, decided_by) "
               "VALUES ('research_v2', %s, false, '{\"row\": 17}', repeat('b', 64), 'script')", (NOW - timedelta(days=5),))
    before = gate_state(db, "research_v2")
    report = page_bank.score([], {}, {})
    with pytest.raises(PermissionError):
        extract_protocol.record(db, report, at=NOW)
    preview = extract_protocol.sign(db, reason="firmo", confirm_owner=False, at=NOW)
    assert preview["written"] is False and extract_protocol.signature(db) is None
    signed = extract_protocol.sign(db, reason="firmo antes de mirar", confirm_owner=True, at=NOW)
    assert signed["written"] and extract_protocol.signature(db)["valid"] is True  # type: ignore[index]
    rec = extract_protocol.record(db, report, at=NOW + timedelta(minutes=1))
    assert rec["passed"] is False and set(rec["verdicts"].values()) == {"INSUFICIENTE"}
    st = extract_protocol.status(db)
    assert st["newest"]["kind"] == "measurement" and st["signature"]["valid"]
    assert gate_state(db, "research_v2") == before, "row 17 is what research_mode still reads"
    with pytest.raises(psycopg.Error):
        db.execute("DELETE FROM ai.feature_gates WHERE gate = 'extract_protocol'")


def test_the_provider_facts_are_read_back_from_what_the_ingestion_stored(db: psycopg.Connection[Any], seed: Seed) -> None:
    kickoff = NOW + timedelta(hours=3)
    fx = _fixture(db, seed, 9, kickoff)
    _lineup(db, seed, fx, [100, 101], [102], kickoff - timedelta(hours=1))
    db.execute("INSERT INTO core.player_availability_obs (fixture_id, source, provider_player_id, observed_at, status, provider_fixture_id, "
               "provider_team_id, player_name, absence_type, reason, payload_hash, origin, normalizer_version) "
               "VALUES (%s, 'api-football', 555, %s, 'LISTED', 50009, 33, 'Uno', 'Missing Fixture', 'Knee Injury', %s, 'answer', 'v1')",
               (fx, NOW - timedelta(hours=5), seed.payload_hash))
    made, coverage = provider_facts_reads.facts_for(db, [fx])
    types = sorted(f.assertion.claim_type for f in made.facts)
    assert types == ["AVAILABLE", "OUT", "STARTER", "STARTER"]
    line = next(f for f in made.facts if f.origin == "lineup")
    assert line.known_from in ("first_seen_at", "fetched_at") and line.assertion.team_id == seed.home_team_id
    assert "Knee" not in str([f.as_json() for f in made.facts])
    assert coverage[fx]["coverage"]["injuries"]["state"] == "desconocida"
    word, _ = provider_facts.availability_word(coverage[fx]["coverage"], checked_at=NOW, listed=0)
    assert word == "sin_dato"
    early = provider_facts.as_of(made.facts, NOW - timedelta(hours=6))
    assert early == []
    rep = unified_readers.provider_replay(db, since=NOW - timedelta(days=1), until=NOW + timedelta(days=1))
    assert rep["matches"] == 0 and rep["decides"] is False
