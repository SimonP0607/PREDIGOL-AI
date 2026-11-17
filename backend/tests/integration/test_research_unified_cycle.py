"""The cycle with the unified research in shadow (IA-087, ``FBI_AI_RESEARCH_UNIFIED``): ``off`` (the default) is the cycle of before; ``shadow``
runs the road after v1 and research v2 in the same pass, on the pages they found, and changes nothing they wrote, asked or answered.

The world and the scripted model are ``test_research_v2_cycle``'s (F6 on 1 Aug 2032; one page of marca.com, a source the directory v2 lists as
pending rights: the road may read its text for the windows and the links but never sends it to a model)."""

from __future__ import annotations

from typing import Any

import pytest

from .test_research_v2_cycle import (
    Setting,
    asked,
    evidence,
    model,
    pass_counts,
    run,
    setting,
    without_ids,
)

pytestmark = pytest.mark.integration
__all__ = ["setting"]


def rows(s: Setting) -> dict[str, Any]:
    return {"v1": without_ids(evidence(s.db, typed=False)), "v2": without_ids(evidence(s.db, typed=True))}


def test_off_by_default_the_cycle_does_not_know_the_road(setting: Setting) -> None:
    ai = model()
    report = run(setting, "shadow", ai)
    assert report.status == "ok", report.errors
    assert not [k for k in pass_counts(setting.db, setting.f6) if k.startswith("xu_")]


def test_in_shadow_the_road_reads_the_pass_pages_and_changes_nothing_v1_or_v2_wrote(setting: Setting) -> None:
    db = setting.db
    db.execute("SAVEPOINT baseline")
    base_ai = model()
    run(setting, "shadow", base_ai)
    before = rows(setting), asked(base_ai)
    db.execute("ROLLBACK TO SAVEPOINT baseline")

    ai = model()
    report = run(setting, "shadow", ai, research_unified="shadow")
    assert report.status == "ok", report.errors
    assert (rows(setting), asked(ai)) == before, "v1's and v2's rows and calls, as without the road"
    counts = pass_counts(db, setting.f6)
    assert counts["xu_pages"] == 1 and counts["xu_page_not_authorised"] == 1, counts
    assert "xu_calls" not in counts, "a source pending rights never reaches a model"
    assert counts["xu_v1_players"] == 1 and counts["xu_v1_windows"] == 1, "the v1 player is in the window the road would send"
