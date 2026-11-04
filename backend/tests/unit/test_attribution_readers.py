"""Who reads the attribution (plan IA, phase 5). The table is new and the production does not know it: no pick, filter, decision, gate or promotion may read
it. The modules allowed to touch ``intel.agent_attributions`` are named here; a new reader is a decision, and this test is where it is made.

Pure: it reads the source, and the helpers of the page that shows the table (shares of counts, the ids a hypothesis cites).
"""

from __future__ import annotations

import re
from pathlib import Path

from fbi.api.services import ai_attribution

ROOT = Path(__file__).resolve().parents[2]
TOUCH = re.compile(r"\b(FROM|JOIN|INTO|UPDATE)\s+intel\.agent_attributions\b", flags=re.IGNORECASE)
ALLOWED = {
    "src/fbi/ai/agents/attribution.py",  # the rule writes it and reads it back for the coverage and the scoreboard
    "src/fbi/ai/agents/pmr.py",  # the reviewer reads the rows the code left UNKNOWN and writes its refinement beside them
    "src/fbi/ai/agents/analyst.py",  # the analyst reads the rows it cites
    "src/fbi/api/services/ai_attribution.py",  # the page of the Admin Console: reading only
}


def test_only_the_modules_of_the_phase_touch_the_attribution() -> None:
    found = {
        str(path.relative_to(ROOT))
        for base in (ROOT / "src", ROOT / "scripts")
        for path in base.rglob("*.py")
        if TOUCH.search(path.read_text(encoding="utf-8"))
    }
    assert found <= ALLOWED, sorted(found - ALLOWED)
    assert "src/fbi/ai/agents/attribution.py" in found


def test_the_page_only_reads() -> None:
    source = (ROOT / "src/fbi/api/services/ai_attribution.py").read_text(encoding="utf-8")
    assert not re.search(r"\b(INSERT\s+INTO|UPDATE\s+[\w.]+\s+SET|DELETE\s+FROM|TRUNCATE)\b", source, flags=re.IGNORECASE)
    assert "commit" not in source


def test_zero_of_zero_is_not_one_hundred_percent() -> None:
    assert ai_attribution.share(0, 0) is None
    assert ai_attribution.share(0, 3) == 0.0
    assert ai_attribution.share(19, 20) == 0.95
    assert ai_attribution.share(1, 3) == 0.3333


def test_the_ids_a_hypothesis_cites_are_read_as_integers_and_nothing_else() -> None:
    assert ai_attribution.ids_of({"attribution_ids": [1, 2, 3]}) == [1, 2, 3]
    assert ai_attribution.ids_of({"attribution_ids": [1, "2", True, 2.5, None, 7]}) == [1, 7]
    assert ai_attribution.ids_of({"attribution_ids": "1,2"}) == []
    assert ai_attribution.ids_of({}) == [] and ai_attribution.ids_of(None) == [] and ai_attribution.ids_of([1]) == []
