"""Plan F12.4 in a real database: the register writes the proposals once, as the system, in PROPOSED - and leaves alone what the owner has decided.

The proposals themselves (their texts, limits and figures) are tied to their guide in tests/unit; here the database: the dry run writes nothing, a
confirmed run writes each proposal as the card reads it, a second run adds nothing, and a decision of the owner survives a third."""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest
from scripts import hypotheses as cli

from fbi.research import evolution, hypotheses
from fbi.research.hypotheses import REGISTER
from tests.integration.conftest import Seed

pytestmark = pytest.mark.integration

AT = datetime(2035, 3, 1, 12, tzinfo=UTC)
LATER = datetime(2035, 3, 2, 12, tzinfo=UTC)
KEYS = [p.key for p in REGISTER]


@pytest.fixture(autouse=True)
def clean(migrated_database: str) -> Iterator[None]:
    """The command line commits what it writes: the keys of the register are removed around each test, so none sees what another left."""
    def wipe() -> None:
        with psycopg.connect(migrated_database, autocommit=True) as conn:
            conn.execute("DELETE FROM analytics.research_hypotheses WHERE dedup_key = ANY(%s)", (KEYS,))
    wipe()
    yield
    wipe()


def rows(db: psycopg.Connection[Any]) -> list[tuple[Any, ...]]:
    return db.execute("SELECT dedup_key, proposed_by, status, target, title, hypothesis, rationale, evidence, created_at "
                      "FROM analytics.research_hypotheses WHERE dedup_key = ANY(%s) ORDER BY id", (KEYS,)).fetchall()


def total(db: psycopg.Connection[Any]) -> int:
    row = db.execute("SELECT count(*) FROM analytics.research_hypotheses").fetchone()
    assert row is not None
    return int(row[0])


def test_a_dry_run_writes_nothing_and_says_what_it_would(db: psycopg.Connection[Any], seed: Seed) -> None:
    before = total(db)
    lines = hypotheses.register(db, at=AT, confirm=False)
    assert len(lines) == len(REGISTER) and all(line.startswith("WOULD REGISTER") for line in lines)
    assert [key in line for key, line in zip(KEYS, lines, strict=True)] == [True] * len(KEYS)
    assert hypotheses.registered(db) == {} and total(db) == before and rows(db) == []


def test_a_confirmed_run_writes_each_proposal_as_the_card_reads_it(db: psycopg.Connection[Any], seed: Seed) -> None:
    lines = hypotheses.register(db, at=AT, confirm=True)
    assert len(lines) == len(REGISTER) and all(line.startswith("REGISTERED") for line in lines)
    written = rows(db)
    assert [r[0] for r in written] == KEYS, "in the order of the register: the one another depends on first"
    for p, (key, by, status, target, title, hypothesis, rationale, evidence, created) in zip(REGISTER, written, strict=True):
        assert (key, by, status, target) == (p.key, "system", "PROPOSED", p.target)
        assert (title, hypothesis, rationale) == (p.title, p.hypothesis, p.rationale), "nothing was cut on the way in"
        assert evidence == p.evidence and created == AT
    have = hypotheses.registered(db)
    assert set(have) == set(KEYS) and {status for _, status in have.values()} == {"PROPOSED"}
    row = db.execute("SELECT stage_history, decided_by, experiment_ids FROM analytics.research_hypotheses WHERE dedup_key = %s", (KEYS[0],)).fetchone()
    assert row is not None and row[0] == [] and row[1] is None and not row[2], "proposed, nobody has decided anything"


def test_the_card_the_owner_sees_has_the_proposal_whole(db: psycopg.Connection[Any], seed: Seed) -> None:
    """The page that lists the proposals reads them as the AI layer's own do: title, hypothesis, reason, matches, impact, cost and the rest of
    the evidence."""
    from fbi.api.services import ai_v2

    hypotheses.register(db, at=AT, confirm=True)
    cards = {c.title: c for c in ai_v2.proposals(db)}
    assert set(cards) >= {p.title for p in REGISTER}
    for p in REGISTER:
        card = cards[p.title]
        assert (card.hypothesis, card.rationale, card.target, card.proposed_by, card.status) == (p.hypothesis, p.rationale, p.target, "system",
                                                                                                 "PROPOSED")
        assert card.n_matches == p.evidence["n_matches"] and card.impact == p.evidence["impact"]
        assert card.investigation_cost == p.evidence["investigation_cost"]
        assert card.evidence == p.evidence


def test_a_second_run_adds_nothing_and_a_decision_of_the_owner_is_left_alone(db: psycopg.Connection[Any], seed: Seed) -> None:
    owner = db.execute("INSERT INTO auth.users (email, display_name, password_hash) VALUES ('hypotheses-owner@test.local', 'Owner', '$argon2id$x') "
                       "RETURNING id").fetchone()
    assert owner is not None
    hypotheses.register(db, at=AT, confirm=True)
    first = rows(db)
    again = hypotheses.register(db, at=LATER, confirm=True)
    assert all(line.startswith("already registered") for line in again) and len(again) == len(REGISTER)
    assert rows(db) == first, "the same rows, with the date of the first time"
    # the owner decides one; running again neither registers it anew nor changes what he said
    hid = hypotheses.registered(db)[KEYS[0]][0]
    assert evolution.decide(db, hid, decision="reject", user_id=owner[0], note="no por ahora", at=LATER) == "REJECTED"
    after = hypotheses.register(db, at=LATER, confirm=True)
    assert any(f"{KEYS[0]} as #{hid} (REJECTED)" in line for line in after) and all(line.startswith("already registered") for line in after)
    status = {key: s for key, (_, s) in hypotheses.registered(db).items()}
    assert status == {KEYS[0]: "REJECTED", KEYS[1]: "PROPOSED"}
    assert len(rows(db)) == len(REGISTER), "a rejected proposal is not proposed again"


def test_a_proposal_registered_by_hand_is_not_registered_twice(db: psycopg.Connection[Any], seed: Seed) -> None:
    """The key is what makes a proposal one: if a row with it is already there - however it got there - the register leaves it."""
    p = REGISTER[0]
    hid = evolution.propose(db, key=p.key, title="Escrita a mano", hypothesis="h" * 10, rationale="r" * 10, evidence={}, proposed_by="owner", at=AT)
    assert hid is not None
    lines = hypotheses.register(db, at=AT, confirm=True)
    assert lines[0] == f"already registered: {p.key} as #{hid} (PROPOSED)" and lines[1].startswith("REGISTERED")
    only = db.execute("SELECT title FROM analytics.research_hypotheses WHERE dedup_key = %s", (p.key,)).fetchall()
    assert only == [("Escrita a mano",)]


def test_the_command_reads_without_writing_and_the_dry_run_rolls_back(capsys: pytest.CaptureFixture[str]) -> None:
    """``show`` goes through a connection that cannot write; ``register`` without ``--confirm`` writes nothing and says how to."""
    assert cli.main(["show"]) == 0
    shown = capsys.readouterr().out
    assert all(f"{key}  [models]  not registered" in shown for key in KEYS) and "hypothesis:" not in shown
    assert cli.main(["show", "--full"]) == 0
    full = capsys.readouterr().out
    assert all(p.rationale in full for p in REGISTER)
    assert cli.main(["register"]) == 0
    dry = capsys.readouterr().out
    assert dry.count("WOULD REGISTER") == len(REGISTER) and "Nothing was written. Add --confirm to register these proposals." in dry
    assert cli.main(["show"]) == 0 and "not registered" in capsys.readouterr().out, "the dry run left no trace"


def test_the_command_writes_with_confirm_and_what_it_writes_stays(capsys: pytest.CaptureFixture[str]) -> None:
    """``register --confirm`` commits: a later look from another connection finds the proposals as PROPOSED, and a second run finds them there."""
    assert cli.main(["register", "--confirm"]) == 0
    out = capsys.readouterr().out
    assert out.count("REGISTERED") == len(REGISTER) and "Nothing was written" not in out
    assert cli.main(["show"]) == 0
    shown = capsys.readouterr().out
    assert all(f"{key}  [models]  registered as #" in shown and "(PROPOSED)" in shown for key in KEYS)
    assert "all registered." in shown
    assert cli.main(["register", "--confirm"]) == 0
    again = capsys.readouterr().out
    assert again.count("already registered") == len(REGISTER) and "REGISTERED" not in again.replace("already registered", "")


def test_the_listing_goes_through_a_connection_that_cannot_write(monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]) -> None:
    seen: list[dict[str, Any]] = []
    real = psycopg.connect

    def spy(*args: Any, **kwargs: Any) -> psycopg.Connection[Any]:
        seen.append(kwargs)
        return real(*args, **kwargs)

    monkeypatch.setattr(psycopg, "connect", spy)
    assert cli.main(["show"]) == 0 and len(seen) == 1
    capsys.readouterr()
    assert "default_transaction_read_only=on" in seen[0].get("options", "")


def test_the_register_only_ever_writes_hypotheses(db: psycopg.Connection[Any], seed: Seed) -> None:
    """Registering decides nothing: no experiment, no model version, no promotion, no memory is created beside the rows of the proposals."""
    tables = ("analytics.experiments", "models.model_versions", "analytics.research_memory", "intel.promotions")
    before = {t: db.execute(f"SELECT count(*) FROM {t}").fetchone() for t in tables}
    hypotheses.register(db, at=AT, confirm=True)
    assert {t: db.execute(f"SELECT count(*) FROM {t}").fetchone() for t in tables} == before
