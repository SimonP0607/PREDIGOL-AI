"""RP-8.2 on a real database: the proposal reads only what is waiting; applying needs the owner, his fingerprint and every hypothesis still waiting; it approves,
archives with the rule and the merge, notes the ones kept (so they stop counting as waiting), and a plan that no longer matches is refused whole."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import psycopg
import pytest

from fbi.research import evolution
from fbi.research import triage as tr

pytestmark = pytest.mark.integration

NOW = datetime(2026, 12, 1, 12, tzinfo=UTC)


def propose(db: psycopg.Connection[Any], title: str, n: int | None = None, key: str | None = None) -> int:
    hid = evolution.propose(db, title=title, hypothesis="h", rationale="r", evidence={} if n is None else {"n_matches": n}, proposed_by="owner", at=NOW, key=key)
    assert hid is not None
    return hid


def owner(db: psycopg.Connection[Any]) -> int:
    row = db.execute("INSERT INTO auth.users (email, display_name, password_hash) VALUES ('triage-owner@test.local', 'Owner', '$argon2id$x') RETURNING id").fetchone()
    assert row is not None
    return int(row[0])


def waiting(db: psycopg.Connection[Any]) -> list[tr.Item]:
    return [i for i in tr.read(db) if i.title.startswith("T·")]


def test_the_proposal_reads_only_what_is_waiting_with_its_matches(db: psycopg.Connection[Any]) -> None:
    a = propose(db, "T· Sobreestimación de empate en 1X2", 900)
    b = propose(db, "T· Calibrar empate frente al cierre", 100)
    done = propose(db, "T· Empate ya decidido")
    db.execute("UPDATE analytics.research_hypotheses SET status = 'REJECTED', decided_at = now() WHERE id = %s", (done,))
    items = {i.id: i for i in waiting(db)}
    assert set(items) == {a, b} and items[a].n_matches == 900 and items[b].n_matches == 100


def test_applying_approves_archives_with_its_reason_and_notes_the_ones_kept(db: psycopg.Connection[Any]) -> None:
    uid = owner(db)
    rep = propose(db, "T· Sobreestimación de empate en 1X2", 900)
    dup = propose(db, "T· Calibrar empate frente al cierre", 100)
    weather = propose(db, "T· El clima como feature de goles")
    odd = propose(db, "T· Algo que ninguna regla lee")
    before = tr.untriaged(db)
    decisions = [d for d in tr.propose(waiting(db)) if d.id in (rep, dup, weather, odd)]
    assert {d.id: d.destination for d in decisions} == {rep: "experiment", dup: "archive", weather: "archive", odd: "keep"}
    done = tr.apply(db, decisions, claimed_fingerprint=tr.plan_fingerprint(decisions), user_id=uid, at=NOW, confirmed_by_owner=True)
    assert done == {"experiment": 1, "keep": 1, "archive": 2}
    rows = {r[0]: r[1:] for r in db.execute("SELECT id, status, decided_by, decision_note, stage_history FROM analytics.research_hypotheses WHERE id = ANY(%s)",
                                            ([rep, dup, weather, odd],)).fetchall()}
    assert rows[rep][0] == "ACCEPTED" and rows[rep][1] == uid
    assert rows[dup][0] == "ARCHIVED" and f"#{rep}" in rows[dup][2]
    assert rows[dup][3][-1]["triage"]["merged_into"] == rep and rows[dup][3][-1]["triage"]["rule"] == "duplicada"
    assert rows[weather][0] == "ARCHIVED" and rows[weather][3][-1]["triage"]["rule"] == "no_comprobable"
    assert rows[odd][0] == "PROPOSED" and rows[odd][3][-1]["triage"]["destination"] == "keep"
    assert before == 4 and tr.untriaged(db) == 0, "the three decided ones leave the count and the one kept carries its triage"


def test_a_plan_without_the_owner_or_with_another_fingerprint_writes_nothing(db: psycopg.Connection[Any]) -> None:
    uid = owner(db)
    a = propose(db, "T· Sobreestimación de empate en 1X2", 10)
    decisions = [d for d in tr.propose(waiting(db)) if d.id == a]
    with pytest.raises(tr.PlanRefusedError, match="dueño"):
        tr.apply(db, decisions, claimed_fingerprint=tr.plan_fingerprint(decisions), user_id=uid, at=NOW, confirmed_by_owner=False)
    with pytest.raises(tr.PlanRefusedError, match="huella"):
        tr.apply(db, decisions, claimed_fingerprint="0" * 64, user_id=uid, at=NOW, confirmed_by_owner=True)
    assert db.execute("SELECT status FROM analytics.research_hypotheses WHERE id = %s", (a,)).fetchone() == ("PROPOSED",)


def test_a_plan_whose_hypothesis_is_no_longer_waiting_is_refused_whole(db: psycopg.Connection[Any]) -> None:
    uid = owner(db)
    a = propose(db, "T· Sobreestimación de empate en 1X2", 10)
    b = propose(db, "T· Cuotas altas: encoger p_model hacia el mercado", 20)
    decisions = [d for d in tr.propose(waiting(db)) if d.id in (a, b)]
    db.execute("UPDATE analytics.research_hypotheses SET status = 'REJECTED', decided_at = now() WHERE id = %s", (b,))
    with pytest.raises(tr.PlanRefusedError, match="ya no está en espera"):
        tr.apply(db, decisions, claimed_fingerprint=tr.plan_fingerprint(decisions), user_id=uid, at=NOW, confirmed_by_owner=True)
    assert db.execute("SELECT status FROM analytics.research_hypotheses WHERE id = %s", (a,)).fetchone() == ("PROPOSED",), "all or nothing"


def test_an_archived_hypothesis_keeps_its_line_and_can_be_reopened_by_the_graph(db: psycopg.Connection[Any]) -> None:
    from fbi.research import cycle_state

    uid = owner(db)
    a = propose(db, "T· El clima como feature de goles")
    decisions = [d for d in tr.propose(waiting(db)) if d.id == a]
    tr.apply(db, decisions, claimed_fingerprint=tr.plan_fingerprint(decisions), user_id=uid, at=NOW, confirmed_by_owner=True)
    assert db.execute("SELECT title, evidence FROM analytics.research_hypotheses WHERE id = %s", (a,)).fetchone() is not None
    assert cycle_state.check("ARCHIVED", "PROPOSED", by="owner").target == "PROPOSED"
