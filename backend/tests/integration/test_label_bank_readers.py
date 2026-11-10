"""The readers of the labelled bank (IA-030) in a real database: the web evidence an extractor wrote (never the provider's), the sentences of
the newest review of each chronicle, and the facts a sampled sentence cites. Read only; the transaction is rolled back."""

from __future__ import annotations

from datetime import timedelta
from typing import Any

import psycopg
import pytest
from psycopg.types.json import Jsonb
from scripts.ia_label_bank import story_facts

from fbi.ai import label_bank, label_bank_readers
from fbi.chronicle import review
from tests.integration.conftest import Seed
from tests.integration.helpers import scalar
from tests.integration.test_chronicle_review import KICKOFF, NOW, world

pytestmark = pytest.mark.integration


def web(db: psycopg.Connection[Any], fid: int, team: int, version: str, *, origin: str = "web", n: int) -> int:
    seen = KICKOFF - timedelta(hours=6)
    attributes = {"assertion": "out", "player_name": "Lisandro Martínez", "extract_version": version, "applies_to": "THIS_MATCH",
                  "result_title": "Parte médico"}
    return int(scalar(db.execute(
        "INSERT INTO ai.evidence (fixture_id, team_id, kind, claim, origin, source_name, source_url, source_domain, source_tier, retrieved_at, "
        "story_key, content_hash, confidence, relevance, attributes, status, status_reason, status_changed_at, provider_player_id, claim_type, "
        "subject_type, subject_id) VALUES (%s, %s, 'injury', 'Lisandro Martínez no jugará por lesión', %s, 'x.example', %s, 'x.example', "
        "'media', %s, %s, %s, 0.5, 0.6, %s, 'PROBABLE', 'test', %s, 10, %s, %s, %s) RETURNING id",
        (fid, team, origin, f"https://x.example/{n}", seen, f"lb:{n}", f"{n:064x}", Jsonb(attributes), seen,
         "OUT" if version != "extract-v1" else None, "PLAYER" if version != "extract-v1" else None, 10 if version != "extract-v1" else None))))


def test_the_readers_give_the_candidates_of_both_banks_and_the_facts_a_sentence_cites(db: psycopg.Connection[Any], seed: Seed) -> None:
    fid, _pk, nid = world(db, seed)
    assert review.run(db, at=NOW).written == 1
    v3 = web(db, fid, seed.home_team_id, "extract-v3", n=1)
    v1 = web(db, fid, seed.home_team_id, "extract-v1", n=2)
    web(db, fid, seed.home_team_id, "extract-v3", origin="provider", n=3)

    claims = label_bank_readers.claims(db, since=KICKOFF - timedelta(days=1), until=NOW + timedelta(hours=1))
    assert {c.id for c in claims} == {f"ev:{v3}", f"ev:{v1}"}, "only the web evidence an extractor wrote; the world's news carry no version"
    by = {c.id: c for c in claims}
    assert by[f"ev:{v3}"].stratum == "extract-v3|OUT" and by[f"ev:{v1}"].stratum == "extract-v1|OUT"
    assert by[f"ev:{v3}"].fields["match"] != "" and by[f"ev:{v3}"].fields["source_url"] == "https://x.example/1"
    only_v1 = label_bank_readers.claims(db, since=KICKOFF - timedelta(days=1), until=NOW + timedelta(hours=1), versions=["extract-v1"])
    assert [c.id for c in only_v1] == [f"ev:{v1}"]
    assert label_bank_readers.claims(db, since=NOW, until=NOW + timedelta(hours=1)) == [], "the window is the evidence's retrieval"

    sentences = label_bank_readers.sentences(db, since=NOW - timedelta(hours=1), until=NOW + timedelta(hours=1))
    assert len(sentences) == 5 and {c.stratum for c in sentences} == {review.NOT_EVALUABLE, review.CONTRADICTED, review.DID_NOT_PLAY, review.HELD}
    rows = label_bank.sample(sentences, quota=60)
    assert len(rows) == 5 and all(r["narrative_id"] == nid for r in rows)
    label_bank_readers.cite(db, rows, story_facts)
    out = {r["section"]: r for r in rows}
    [absence] = out["home.0"]["cited"]
    assert absence["ref"] == "P:absences.home.1" and absence["found"] and absence["code"] == "absence"
    news = out["home.2"]["cited"]
    assert news[0]["found"] and news[0]["claim"] == "Salah, sancionado." and news[0]["kind"] == "suspension"
    assert all(c["found"] for r in rows for c in r["cited"]), "every reference of this chronicle is in its packet or in the evidence"
