"""What follows the shadow's selections after they are confirmed (plan 2026, bloque E), in SHADOW.

* ``selections`` - the tracking of loose selections (IA-109, AD-E05): En juego -> Liquidada -> Evaluada on ``settle-v4``.
* ``parlay_v6`` - the ``parlay-v6`` rule (IA-110, AD-E06), pure: legs confirmed by themselves, at most three, the joint by simulation.
* ``parlay_v6_shadow`` - its pass: build, keep, record the days without one, read the results.

A LEAF: nothing of ``fbi`` imports this package - only the worker's door (``fbi.shadowjobs.selection_settle``) and the owner's command
(``scripts/ia_parlays_v6.py``) - so the packages it reads (the cycle of states, the settlement, ``corr-v2``) stay out of each other's
import loop (``tests/unit/test_architecture.py``), and nothing that decides, publishes or serves a reader can reach it. ``parlay-v5``
(``fbi.parlays``) and ``settle-v4`` (``fbi.picks.settlement``) are not touched.
"""
