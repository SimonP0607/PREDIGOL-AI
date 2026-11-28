"""The one schema of a context fact in a real database (RP-4.1, migration 0180): a complete fact under the schema is stored, an incomplete one is
refused by the code and, if it got past it, by the database; the new words exist only under the schema; the old rows are what they were; the
content guard covers the new columns. The transaction is rolled back afterwards."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

import psycopg
import pytest

from fbi.ai import evidence, factor_counts, factor_schema, value_sheet_readers

from .conftest import Seed

pytestmark = pytest.mark.integration

NOW = datetime(2026, 11, 26, 12, tzinfo=UTC)


def item(seed: Seed, **over: Any) -> evidence.EvidenceIn:
    base: dict[str, Any] = {"fixture_id": seed.fixture_id, "team_id": None, "kind": "stakes", "claim": "El equipo se juega el ascenso en esta fecha",
                            "origin": "web", "source_name": "Marca", "retrieved_at": NOW, "story_key": "stakes-1", "source_url": "https://www.marca.com/x",
                            "source_tier": "media", "published_at": NOW - timedelta(hours=2), "claim_type": "OTHER", "subject_type": "MATCH",
                            "subject_id": seed.fixture_id, "fresh_until": NOW + timedelta(days=1), "side": "both", "fact_schema": factor_schema.VERSION}
    base.update(over)
    return evidence.EvidenceIn(**base)


def test_a_complete_fact_under_the_schema_is_stored_with_its_side_and_its_new_kind(db: psycopg.Connection[Any], seed: Seed) -> None:
    fid, created = evidence.store(db, item(seed), at=NOW)
    assert created
    row = db.execute("SELECT kind, side, fact_schema, fresh_until IS NOT NULL FROM ai.evidence WHERE id = %s", (fid,)).fetchone()
    assert row == ("stakes", "both", "context-fact-v1", True)


def test_an_incomplete_fact_is_refused_and_nothing_is_written(db: psycopg.Connection[Any], seed: Seed) -> None:
    before = db.execute("SELECT count(*) FROM ai.evidence").fetchone()
    for change, absent in (({"side": None}, ["relation"]), ({"fresh_until": None}, ["validity"]), ({"published_at": None}, ["source_date"]),
                           ({"subject_type": None, "subject_id": None}, ["entity"]), ({"source_name": " "}, ["source"])):
        with pytest.raises(factor_schema.IncompleteFactError) as err:
            evidence.store(db, item(seed, **change), at=NOW)
        assert err.value.absent == absent
    assert db.execute("SELECT count(*) FROM ai.evidence").fetchone() == before


def test_a_calculated_fact_is_stored_with_its_calculation(db: psycopg.Connection[Any], seed: Seed) -> None:
    calc = item(seed, kind="rotation", origin="own_calc", source_name="PrediGol", source_url=None, source_tier=None, story_key="rot-1",
                attributes={"calculation": "rotation-v1"})
    fid, _ = evidence.store(db, calc, at=NOW)
    assert db.execute("SELECT origin, source_tier FROM ai.evidence WHERE id = %s", (fid,)).fetchone() == ("own_calc", "provider")
    with pytest.raises(factor_schema.IncompleteFactError):
        evidence.store(db, item(seed, kind="rotation", origin="own_calc", source_name="PrediGol", source_url=None, story_key="rot-2"), at=NOW)


def test_the_database_refuses_what_the_code_would_have_refused_and_the_new_words_without_the_schema(db: psycopg.Connection[Any], seed: Seed) -> None:
    def raw(**over: Any) -> None:
        cols: dict[str, Any] = {"kind": "injury", "claim": "a claim about a player", "origin": "provider", "source_name": "provider",
                                "source_tier": "provider", "retrieved_at": NOW, "story_key": f"s-{len(over)}-{sorted(over)}", "content_hash": "h",
                                "confidence": 0.9, "relevance": 0.8, "status": "PROBABLE", "status_reason": "t", "status_changed_at": NOW, **over}
        db.execute(f"INSERT INTO ai.evidence ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})", tuple(cols.values()))

    raw()  # the row of before: no schema, no side, nothing new - accepted exactly as it was
    for over in ({"kind": "stakes"}, {"origin": "own_calc"}, {"fact_schema": "context-fact-v1"}, {"side": "nowhere"}, {"fact_schema": "other"}):
        with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
            raw(**over)
    raw(kind="referee", fact_schema="context-fact-v1", side="match", published_at=NOW, fresh_until=NOW, subject_type="MATCH", subject_id=1)


def test_the_new_columns_are_content_and_never_change_but_the_state_still_does(db: psycopg.Connection[Any], seed: Seed) -> None:
    fid, _ = evidence.store(db, item(seed), at=NOW)
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        db.execute("UPDATE ai.evidence SET side = 'home' WHERE id = %s", (fid,))
    with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
        db.execute("UPDATE ai.evidence SET fact_schema = NULL WHERE id = %s", (fid,))
    db.execute("UPDATE ai.evidence SET status = 'CONFIRMED', status_reason = 'two outlets', status_changed_at = %s WHERE id = %s", (NOW, fid))
    assert db.execute("SELECT status, jsonb_array_length(status_history) FROM ai.evidence WHERE id = %s", (fid,)).fetchone() == ("CONFIRMED", 1)


def test_what_was_written_before_keeps_its_hash_and_the_schema_changes_the_hash_of_the_same_words(seed: Seed) -> None:
    old = item(seed, side=None, fact_schema=None, kind="injury", subject_type=None, subject_id=None, fresh_until=None, claim_type=None)
    assert old.content_hash() == item(seed, side=None, fact_schema=None, kind="injury", subject_type=None, subject_id=None, fresh_until=None,
                                      claim_type=None).content_hash()
    assert "fact" not in old.content_hash()  # a digest: just make sure it is built without the schema's keys
    assert item(seed).content_hash() != item(seed, side="home").content_hash(), "whom it affects is part of the content"


def test_the_counts_read_the_window_and_split_the_new_facts_from_the_old(db: psycopg.Connection[Any], seed: Seed) -> None:
    evidence.store(db, item(seed), at=NOW)
    evidence.store(db, item(seed, fact_schema=None, side=None, kind="injury", story_key="old-1", claim="Un jugador está en duda para el partido"),
                   at=NOW)
    doc = factor_counts.report(value_sheet_readers.fact_rows(db, since=NOW - timedelta(days=1), until=NOW + timedelta(days=1), typed=True))
    assert doc["new"]["facts"] == 1 and doc["new"]["complete_share"] == 1.0 and doc["new"]["by_kind"] == {"stakes": 1}
    assert doc["before"]["facts"] >= 1


def first_path(seed: Seed, **over: Any) -> evidence.EvidenceIn:
    """A provider's report written under the schema as v1 always wrote it: no claim type, no subject type, the identifiers of the row are its entity."""
    base: dict[str, Any] = {"kind": "injury", "origin": "provider", "source_name": "api-football", "source_url": None, "source_tier": "provider",
                            "story_key": "inj-1", "claim": "Un jugador está lesionado y no jugará el partido", "team_id": seed.home_team_id,
                            "provider_player_id": 4242, "claim_type": None, "subject_type": None, "subject_id": None, "side": "home",
                            "attributes": {"reason": "knee"}}
    return item(seed, **{**base, **over})


def test_a_report_of_the_first_path_is_stored_under_the_schema_and_stays_on_the_path_v1_reads(db: psycopg.Connection[Any], seed: Seed) -> None:
    fid, created = evidence.store(db, first_path(seed), at=NOW)
    assert created
    assert db.execute("SELECT fact_schema, side, subject_type, claim_type, fresh_until IS NOT NULL FROM ai.evidence WHERE id = %s", (fid,)).fetchone() == (
        "context-fact-v1", "home", None, None, True)
    v1 = {r[0] for r in db.execute(evidence.LOAD_SQL, {"fixture": seed.fixture_id, "at": NOW + timedelta(hours=1)}).fetchall()}
    typed = {r[0] for r in db.execute(evidence.TYPED_SQL, {"fixture": seed.fixture_id, "teams": [seed.home_team_id], "at": NOW + timedelta(hours=1),
                                                          "since": NOW - timedelta(days=30)}).fetchall()}
    assert fid in v1 and fid not in typed, "the schema moves a fact to a better record, never to the road of the claims of research v2"


def test_the_database_asks_the_first_path_for_an_identifier_and_nothing_else_loosely(db: psycopg.Connection[Any], seed: Seed) -> None:
    def raw(**over: Any) -> None:
        cols: dict[str, Any] = {"kind": "injury", "claim": "a claim about a player", "origin": "provider", "source_name": "provider", "source_tier": "provider",
                                "retrieved_at": NOW, "story_key": f"r-{sorted(over)}", "content_hash": "h", "confidence": 0.9, "relevance": 0.8, "status": "PROBABLE",
                                "status_reason": "t", "status_changed_at": NOW, "fact_schema": "context-fact-v1", "side": "home", "published_at": NOW,
                                "fresh_until": NOW, "team_id": seed.home_team_id, **over}
        db.execute(f"INSERT INTO ai.evidence ({', '.join(cols)}) VALUES ({', '.join(['%s'] * len(cols))})", tuple(cols.values()))

    raw()  # the first path: an origin of v1, no claim type, no subject, an identifier
    raw(story_key="by-player", team_id=None, provider_player_id=7)
    for over in ({"team_id": None}, {"claim_type": "INJURY"}, {"origin": "own_calc"}, {"side": None}, {"fresh_until": None}, {"published_at": None},
                 {"source_name": " "}, {"subject_id": 3}):
        with pytest.raises(psycopg.errors.CheckViolation), db.transaction():
            raw(**over)
