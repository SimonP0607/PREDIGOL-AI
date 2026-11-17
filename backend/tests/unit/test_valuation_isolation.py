"""value-v2 and corr-v2 (``fbi.valuation``) are in SHADOW: nothing that decides for production, publishes, stakes or serves users imports
them - not decision-v1 (``fbi.intel``, protected), not the picks, not ``parlay-v5``, not the API. Their readers are listed; a new one fails
here until someone decides it may read (``parlay-v6``, AD-E06, reads it from the leaf package ``tracking/``, in the shadow). The package itself writes nothing and reaches no
serving layer."""

from __future__ import annotations

import re

from .test_decision_v2_isolation import ROOT, SRC, files, imported, rel

PACKAGE = "fbi.valuation"
ALLOWED = {
    "decision/engine.py": "decision-v2 (shadow) carries value-v2 as a measurement no stage reads",
    "decision/replay.py": "the replay of decision-v2 (read-only) reports value-v2",
    "portfolio/build.py": "the shadow portfolio reads corr-v2 beside portfolio-corr-v1 behind --correlation-v2 (read-only)",
    "scripts/ia_value_correlation.py": "the read-only measurement of value-v2 and of the three calculations of correlation",
    "tracking/parlay_v6.py": "parlay-v6 (AD-E06, IA-110, shadow): the joint of its legs by simulation with corr-v2's dependence",
    "tracking/parlay_v6_shadow.py": "parlay-v6's shadow pass reads the score matrices and the measured correlations for the builder",
}
SERVING = ("intel/", "picks/", "familydecisions/", "api/", "parlays/", "customer/", "notify/", "messaging/", "narrative/", "knowledge/",
           "apps/")


def importers() -> set[str]:
    return {rel(p) for p in files(SRC, ROOT / "scripts", ROOT / "apps") if not rel(p).startswith("valuation/")
            and any(n == PACKAGE or n.startswith(PACKAGE + ".") for n in imported(p))}


def test_only_the_listed_readers_import_it() -> None:
    found = importers()
    assert found == set(ALLOWED), f"unlisted: {sorted(found - set(ALLOWED))}; listed but gone: {sorted(set(ALLOWED) - found)}"


def test_nothing_that_decides_publishes_stakes_or_serves_imports_it() -> None:
    assert not [f for f in importers() if f.startswith(SERVING)]


def test_the_package_writes_nothing_and_reaches_no_serving_layer() -> None:
    own = files(SRC / "valuation")
    assert own
    writes = re.compile(r"\b(INSERT\s+INTO|UPDATE\s+\w+\.\w+\s+SET|DELETE\s+FROM|TRUNCATE|CREATE\s+TABLE)\b", re.IGNORECASE)
    assert not [rel(p) for p in own if writes.search(p.read_text(encoding="utf-8"))]
    for p in own:
        names = imported(p)
        bad = [n for n in names if n.startswith("fbi.") and n.split(".")[1] in ("api", "notify", "messaging", "customer", "narrative",
                                                                                 "picks", "decision", "portfolio", "familydecisions")]
        assert not bad, (rel(p), bad)
        # from the parlays only icc-v1's measurement (its reader and its Bahadur expansion), never the builder nor the records
        assert not [n for n in names if n.startswith("fbi.parlays") and not n.startswith("fbi.parlays.correlation")
                    and n != "fbi.parlays"], rel(p)
        # from decision-v1 only its constant of books, never a function that decides
        assert not [n for n in names if n.startswith("fbi.intel") and n not in ("fbi.intel.decision", "fbi.intel.decision.MIN_BOOKS")], rel(p)
