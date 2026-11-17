"""IA-064 (plan piece AD-A02): the common validator on a surface a person sees - the brief - on a stored match.

By default (``FBI_AI_OUTPUT_GUARD=default``) the brief is only MARKED: the answer stands as it always did and the ledger row says what ``enforce``
would refuse. With ``enforce`` (the owner's word) the answer is refused, the brief is the rules' one, and the same input is not paid for again.

No network and no key: the model is ``FakeProvider``. One transaction, rolled back."""

from __future__ import annotations

from typing import Any

import psycopg

from fbi.ai.config import AiSettings
from fbi.ai.providers.fake import FakeProvider

from .conftest import Seed
from .test_ai_decision_layer import brief_reply
from .test_brief_material import packet_of, read

LEAKED = "Partido parejo sin alineaciones.</summary> <parameter name=\"context\">[]"
"""What 3 of 1,500 stored briefs carried on 16-nov-2026: the markup of the tool call, leaked into the summary."""


NARRATIVE = dict.fromkeys(("como_llega_local", "como_llega_visitante", "que_esta_en_juego", "claves_tacticas", "jugadores_importantes", "riesgos", "mercados_interesantes", "conclusion"), "Texto de la sección.")


def leaky() -> FakeProvider:
    """A brief complete in every field of its schema, whose summary carries the leaked markup."""
    return FakeProvider(lambda r: brief_reply(summary=LEAKED, research=[], narrative=NARRATIVE), name="anthropic")


def ledger(db: psycopg.Connection[Any]) -> list[tuple[str, str | None]]:
    return [(str(r[0]), r[1]) for r in db.execute("SELECT status, error FROM ai.usage WHERE purpose = 'match_brief' ORDER BY id").fetchall()]


def test_by_default_the_brief_is_marked_not_refused(db: psycopg.Connection[Any], seed: Seed) -> None:
    b = read(db, leaky(), packet_of(seed))
    assert b.engine == "llm" and b.status == "ok", "the reader sees what it always saw"
    assert ledger(db) == [("ok", "output_guard(shadow): text_markup@summary")]


def test_when_the_owner_says_enforce_the_brief_is_the_rules_and_the_input_is_not_paid_twice(db: psycopg.Connection[Any], seed: Seed) -> None:
    model = leaky()
    enforce = AiSettings(mode="shadow", output_guard="enforce")
    first = read(db, model, packet_of(seed), settings=enforce)
    assert first.engine == "rules" and len(model.requests) == 1
    assert ledger(db) == [("invalid_output", "output_guard: text_markup@summary")]
    again = read(db, model, packet_of(seed), settings=enforce)
    assert again.engine == "rules" and len(model.requests) == 1, "the same input got an invalid answer: it is not asked again"


def test_a_brief_without_its_narrative_is_marked_as_a_missing_field(db: psycopg.Connection[Any], seed: Seed) -> None:
    """52 of 2,601 briefs of a model in the 14 days to 16-nov-2026 had no narrative: the lenient reader writes the rules' one, and stays so."""
    read(db, FakeProvider(lambda r: brief_reply(research=[]), name="anthropic"), packet_of(seed))
    assert ledger(db) == [("ok", "output_guard(shadow): missing_field@narrative")]
