"""RP-12.2 on a stored match: with ``FBI_AI_REVIEW_PREFILTER`` on, a selection the rules reject is not sent to the model (a control share is);
off, today's path is exactly the same. No network: the provider is fake. One transaction, rolled back."""

from __future__ import annotations

from dataclasses import replace
from typing import Any

import pytest

from fbi.ai import review_prefilter as rp
from fbi.ai.providers.fake import FakeProvider
from fbi.ai.review import Reviewed, review_candidate

from .test_ai_decision_layer import review_reply
from .test_batch import AT, SETTINGS, Env, candidate, env  # noqa: F401  (the fixture)

ON = replace(SETTINGS, review_prefilter=True)


def ask(e: Env, settings_: Any, *, status: str) -> tuple[Reviewed, int]:
    """The review of the same candidate; ``status`` is the match's state in the packet (a postponed match is a hard stop of the rules)."""
    e.packet.content["fixture"]["status"] = status
    calls: list[int] = []

    def answer(request: Any) -> Any:
        calls.append(1)
        return review_reply("APPROVE")

    provider = FakeProvider(answer, name="anthropic")
    got = review_candidate(e.conn, settings_, candidate(e.seed), e.packet, e.packet_id, at=AT, use_llm=True, tier="analysis",
                           ledger=e.ledger, provider=(provider, "anthropic"))
    return got, len(calls)


def test_off_the_model_is_asked_even_when_the_rules_rejected(env: Env) -> None:  # noqa: F811
    got, calls = ask(env, SETTINGS, status="PST")
    assert got.rules.decision == "REJECT" and calls == 1 and got.llm is not None
    assert got.decision == "REJECT", "the combined review is the most conservative: the model cannot lift a REJECT"


def test_on_a_rules_reject_outside_the_control_is_not_sent_and_stays_reject(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    monkeypatch.setattr(rp, "in_control", lambda *a: False)
    got, calls = ask(env, ON, status="PST")
    assert got.rules.decision == "REJECT" and calls == 0 and got.llm is None and got.decision == "REJECT"
    stored = env.db.execute("SELECT engine, decision FROM ai.pick_reviews ORDER BY id").fetchall()
    assert [r[0] for r in stored] == ["rules", "combined"] and stored[-1][1] == "REJECT"


def test_on_the_control_is_still_asked_and_the_outcome_is_the_same(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    monkeypatch.setattr(rp, "in_control", lambda *a: True)
    got, calls = ask(env, ON, status="PST")
    assert calls == 1 and got.llm is not None and got.decision == "REJECT"


def test_on_a_selection_the_rules_do_not_reject_is_asked_as_always(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    monkeypatch.setattr(rp, "in_control", lambda *a: False)
    got, calls = ask(env, ON, status="NS")
    assert got.rules.decision != "REJECT" and calls == 1 and got.llm is not None


def test_the_history_reads_the_pair_of_each_model_review_and_the_replay_changes_nothing(env: Env, monkeypatch: pytest.MonkeyPatch) -> None:  # noqa: F811
    from datetime import timedelta

    got, _ = ask(env, SETTINGS, status="PST")
    assert got.llm is not None
    rows = rp.read(env.db, since=AT - timedelta(hours=1), until=AT + timedelta(hours=1))
    assert len(rows) == 1 and rows[0]["rules"] == "REJECT" and rows[0]["llm"] is not None and rows[0]["combined"] == "REJECT"
    monkeypatch.setattr(rp, "in_control", lambda *a: False)
    p = rp.replay(rows, window_days=1)
    assert (p.skipped, p.combined_approvals_changed) == (1, 0) and p.skipped_cost == p.cost > 0
