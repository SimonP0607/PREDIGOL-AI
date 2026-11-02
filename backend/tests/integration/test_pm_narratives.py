"""The narratives of the post-mortems (plan F8, ``fbi.ai.pm_narratives``): optional, paid for and apart from the post-mortem, which is built by
rules at no cost.

The world is the one of ``test_postmortem_v6`` (the post-mortem of every selection, once): of its selections three matter to a person - the
approved home win of F1 that lost (a pick of the day), the pick of the day of F4 nobody reviewed that lost, and the away win of F2 that the AI
rejected and would have won - and the others do not (a win, a push, a selection only the decision layer judged, INVESTIGACION). A narrative is
written for the three, the picks of the day with the intermediate model, once; a model that fails leaves the post-mortem whole; the admin reads
the narrative the new way and, for a selection studied before F8, the one the first post-mortem by selection wrote.
"""

from __future__ import annotations

import json
from datetime import timedelta
from typing import Any
from zoneinfo import ZoneInfo

import psycopg
import pytest

from fbi.ai import pm_narratives
from fbi.ai.config import AiSettings
from fbi.ai.providers.fake import FakeProvider
from fbi.ai.usage import UsageLedger, shared
from fbi.api.services import ai_layer, ai_v2
from fbi.intel import postmortem

from .conftest import Seed
from .helpers import scalar
from .test_postmortem_v6 import LATE, Pm

pytestmark = pytest.mark.integration

BOGOTA = ZoneInfo("America/Bogota")
SETTINGS = AiSettings(mode="shadow")
MODEL = "claude-haiku-5-5"
SUMMARY = "Perdió con una cuota justa: varianza."


def narrator(**kw: Any) -> FakeProvider:
    def answer(request: Any) -> dict[str, Any]:
        assert request.schema_name == "submit_postmortem"
        return {"summary": SUMMARY, "agrees_with_class": True, "lessons": ["Una lección.", "Otra lección.", "Una tercera."]}
    return FakeProvider(answer, name="anthropic", **kw)


def write(db: psycopg.Connection[Any], provider: FakeProvider | None, **kw: Any) -> pm_narratives.NarrativeReport:
    return pm_narratives.run_narratives(db, at=LATE, settings=SETTINGS, ledger=UsageLedger(shared(db)),
                                        provider=None if provider is None else (provider, MODEL), **kw)


@pytest.fixture()
def world(db: psycopg.Connection[Any], seed: Seed) -> Pm:
    pm = Pm(db, seed)
    postmortem.study(db, at=LATE)
    return pm


def narrated(db: psycopg.Connection[Any]) -> dict[tuple[str, str], str]:
    rows = db.execute("SELECT f.id, p.market_key, p.selection, n.narrative FROM ai.postmortem_narratives n "
                      "JOIN intel.postmortems p ON p.id = n.postmortem_id JOIN core.fixtures f ON f.id = p.fixture_id").fetchall()
    return {(f"{r[0]}", f"{r[1]} {r[2]}"): r[3] for r in rows}


def test_a_narrative_is_written_for_the_post_mortems_that_matter_and_for_no_other(db: psycopg.Connection[Any], world: Pm) -> None:
    provider = narrator()
    report = write(db, provider)
    f = world.f
    assert (report.due, report.written, report.strong, report.unavailable, report.errors) == (3, 3, 2, 0, [])
    assert set(narrated(db)) == {(str(f["F1"]), "1X2 Home"), (str(f["F4"]), "1X2 Home"), (str(f["F2"]), "1X2 Away")}, \
        "the loss the AI approved, the loss nobody reviewed, the win it rejected: not the win, the push, the decision layer's alone"
    text = narrated(db)[(str(f["F1"]), "1X2 Home")]
    assert text == SUMMARY + "\n- Una lección.\n- Otra lección.", "the summary and at most two lessons"
    tiers = sorted(r[0] for r in db.execute("SELECT tier FROM ai.usage WHERE purpose = 'postmortem'").fetchall())
    assert tiers == ["analysis", "analysis", "bulk"], "the picks of the day that lost with the intermediate model, the rest with the economical"
    assert len(provider.requests) == 3


def test_the_model_reads_the_ten_questions_the_class_and_what_the_review_said_not_the_decision_layers_own_answers(
        db: psycopg.Connection[Any], world: Pm) -> None:
    provider = narrator()
    write(db, provider)
    bodies = [json.loads(r.user) for r in provider.requests]
    a = next(b for b in bodies if "1X2 Home" in b["selection"] and b["verdict"] == "approved_lost")
    assert set(a) == {"selection", "verdict", "class", "answers", "review", "roles"}
    assert set(a["answers"]) <= set(pm_narratives.QUESTIONS) and "expected" in a["answers"] and "probabilidad" not in a["answers"]
    assert set(a["review"]) == set(pm_narratives.REVIEW_KEYS) and a["roles"] == sorted(a["roles"])
    assert a["class"] is not None, "the class of the loss"


def test_a_narrative_is_written_once_and_a_second_run_finds_nothing_due(db: psycopg.Connection[Any], world: Pm) -> None:
    write(db, narrator())
    again = write(db, narrator())
    assert (again.due, again.written) == (0, 0)
    assert scalar(db.execute("SELECT count(*) FROM ai.postmortem_narratives")) == 3
    assert scalar(db.execute("SELECT count(*) FROM ai.usage WHERE purpose = 'postmortem'")) == 3, "and nothing is paid twice"


def test_without_a_model_nothing_is_read_and_nothing_is_written(db: psycopg.Connection[Any], world: Pm) -> None:
    report = write(db, None)
    assert (report.due, report.written) == (0, 0) and not narrated(db)
    assert scalar(db.execute("SELECT count(*) FROM ai.usage")) == 0


def test_a_model_that_fails_leaves_the_post_mortem_whole_and_the_call_on_the_ledger(db: psycopg.Connection[Any], world: Pm) -> None:
    before = scalar(db.execute("SELECT count(*) FROM intel.postmortems"))
    report = write(db, narrator(fail="timeout"))
    assert (report.due, report.written, report.unavailable) == (3, 0, 3) and not narrated(db)
    assert scalar(db.execute("SELECT count(*) FROM intel.postmortems")) == before
    statuses = {r[0] for r in db.execute("SELECT status FROM ai.usage WHERE purpose = 'postmortem'").fetchall()}
    assert statuses == {"timeout"}, "what was asked and failed is recorded"
    # and the next run, with a model that answers, writes them
    assert write(db, narrator()).written == 3


def test_a_run_writes_at_most_what_its_limits_allow_and_the_picks_of_the_day_come_first(
        db: psycopg.Connection[Any], world: Pm, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(pm_narratives, "MAX_NARRATIVES", 2)
    report = write(db, narrator())
    assert (report.written, report.strong) == (2, 2)
    f = world.f
    assert set(narrated(db)) == {(str(f["F1"]), "1X2 Home"), (str(f["F4"]), "1X2 Home")}, "the two picks of the day, not the rejected one"
    monkeypatch.setattr(pm_narratives, "MAX_NARRATIVES", 12)
    monkeypatch.setattr(pm_narratives, "MAX_STRONG_NARRATIVES", 0)
    again = write(db, narrator())
    assert (again.written, again.strong) == (1, 0), "the one left is written with the economical model"
    assert sorted(r[0] for r in db.execute("SELECT tier FROM ai.usage").fetchall()) == ["analysis", "analysis", "bulk"]


def test_a_post_mortem_older_than_the_week_is_not_narrated(db: psycopg.Connection[Any], world: Pm) -> None:
    report = pm_narratives.run_narratives(db, at=LATE + timedelta(days=8), settings=SETTINGS, ledger=UsageLedger(shared(db)),
                                          provider=(narrator(), MODEL))
    assert (report.due, report.written) == (0, 0)


def test_the_admin_reads_the_new_narrative_and_for_an_older_selection_the_one_the_first_post_mortem_wrote(
        db: psycopg.Connection[Any], world: Pm) -> None:
    f = world.f
    old = ("INSERT INTO ai.pick_postmortems (fixture_id, market_key, selection, line, created_at, version, roles, settled, verdict, "
           "answers, narrative) VALUES (%s, '1X2', %s, 0, %s, 'pm-v2', '{daily_pick}', 'loss', 'approved_lost', '{}'::jsonb, %s)")
    db.execute(old, (f["F1"], "Home", LATE, "La narrativa de antes sobre F1."))
    day = world.kickoff("F1").astimezone(BOGOTA).date()  # the day the matches were played

    def read() -> dict[tuple[int, str], str | None]:
        return {(r.fixture_id, f"{r.market_key} {r.selection}"): r.narrative for r in ai_v2.postmortems(db, day=day).data}
    before = read()
    assert before[(f["F1"], "1X2 Home")] == "La narrativa de antes sobre F1.", "a selection studied before F8 keeps the narrative it had"
    assert before[(f["F4"], "1X2 Home")] is None and before[(f["F2"], "1X2 Away")] is None
    write(db, narrator())
    after = read()
    assert after[(f["F1"], "1X2 Home")] == SUMMARY + "\n- Una lección.\n- Otra lección.", "the new one wins over the old"
    assert after[(f["F4"], "1X2 Home")] is not None and after[(f["F2"], "1X2 Away")] is not None


def test_the_mistakes_of_the_ais_day_come_from_the_one_post_mortem_with_their_narrative(db: psycopg.Connection[Any], world: Pm) -> None:
    write(db, narrator())
    f = world.f
    written = LATE.astimezone(BOGOTA).date()  # the post-mortems were written at LATE: the dashboard of that day lists them
    dashboard = ai_layer.dashboard(db, day=written).data
    assert dashboard is not None
    rows = {(e["fixture_id"], e["market"], e["selection"]): e for e in dashboard.errors}
    assert set(rows) == {(f["F1"], "1X2", "Home"), (f["F2"], "1X2", "Away")}, "approved and lost, rejected and would have won"
    lost = rows[(f["F1"], "1X2", "Home")]
    assert (lost["decision"], lost["settled"], lost["score"], lost["line"]) == ("APPROVE", "loss", "0-2", 0.0)
    assert lost["narrative"] and SUMMARY[:20] in lost["narrative"]
    assert isinstance(lost["p_model"], float) and isinstance(lost["signals"], list)
