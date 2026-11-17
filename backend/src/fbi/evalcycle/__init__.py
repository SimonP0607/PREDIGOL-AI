"""The evaluation cycle ``eval-cycle-v1`` (IA-105..IA-108, plan pieces AD-D06, AD-D07, AD-D08, AD-D03), in SHADOW.

Four evaluations of every tracked match, tied to the football clock instead of the three passes ``first``, ``pre`` and ``final``
(``fbi.ai.day.PASSES``, which keep running untouched until the owner signs their retirement):

    E1  once, 24 to 12 hours before kick-off: decision-v2 decides, the estimated starters are read and every selection gets the
        players it depends on and its probability without each of them (``dependency``, AD-D03)
    E2  for each new fact of the match (``ai.evidence``), between E1 and E4: recalculated only when the fact touches a variable of the
        model or a declared dependency, otherwise only noted - a fact never triggers two E2
    E3  when the official line-up arrives (``core.fixture_lineup_arrivals``, IA-069), code only, under two minutes: the official
        starters against the estimated, the dependencies applied, the price read again; confirmed, unchanged, withdrawn
        (``reevaluate``, AD-D07)
    E4  20 to 10 minutes before kick-off: the match read again (kick-off, state, venue: ``fbi.ai.final_reread``, IA-061) and the
        last decision. decision-v1's floor (``fbi.intel.decision.MIN_MINUTES``: under 10 minutes it rejects every selection) is never
        lowered, so E4 is kept between T-20 and T-10, as decision-v2's kept shadow does (IA-093) - not at T-5.

Each evaluation keeps what it did (``intel.eval_runs``, ``intel.eval_verdicts``, revision 0156), its decision as a new version of
decision-v2 (``intel.decisions_v2``, IA-093) and its moves in the cycle of states under the writer ``eval-cycle-v1``
(``intel.selection_lifecycle``, through the cycle's API); a withdrawal, a line-up that did not arrive in time and a change of kick-off
or conditions become a private alert «antes -> ahora» for the owner (``alerts``, AD-D08), never a notice to a reader.

The pure modules (``clock``, ``dependency``, ``reevaluate``, ``alerts``, ``chain``) read no database and no clock; ``run`` reads and
writes. No model of language computes, raises or lowers anything here. Off by default: the worker schedules it only while
``FBI_EVAL_CYCLE`` is ``shadow`` (``fbi.shadowjobs.eval_cycle``).
"""

from __future__ import annotations

from typing import Final

VERSION: Final = "eval-cycle-v1"
