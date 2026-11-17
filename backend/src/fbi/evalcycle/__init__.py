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
    E4  at T-5 (the owner's decision of 17-nov-2026, IA-142): the match read again (kick-off, state, venue: ``fbi.ai.final_reread``,
        IA-061) and every selection judged with decision-v2's last kept decision and the price read again. decision-v1's floor
        (``fbi.intel.decision.MIN_MINUTES``: under 10 minutes it rejects every selection) is never lowered, so nothing decides at T-5:
        decision-v2 decides for the last time from T-20 to T-10, as its kept shadow does (IA-093), and E4 adopts that moment.

Each evaluation keeps what it did (``intel.eval_runs``, ``intel.eval_verdicts``, revision 0156), its decision as a new version of
decision-v2 (``intel.decisions_v2``, IA-093) and its moves in the cycle of states under the writer ``eval-cycle-v1``
(``intel.selection_lifecycle``, through the cycle's API); a withdrawal, a line-up that did not arrive in time and a change of kick-off
or conditions become a private alert «antes -> ahora» for the owner (``alerts``, AD-D08), never a notice to a reader. And each evaluation
writes, in its own transaction, the list of the facts it looked at with their relation to the analysis (``fbi.factlinks``, ``link-v1``,
AD-G08, revision 0160): contract C-07 is read from that list, never rebuilt afterwards.

The pure modules (``clock``, ``dependency``, ``reevaluate``, ``alerts``, ``chain``) read no database and no clock; ``run`` reads and
writes. No model of language computes, raises or lowers anything here. Off by default: the worker schedules it only while
``FBI_EVAL_CYCLE`` is ``shadow`` (``fbi.shadowjobs.eval_cycle``).
"""

from __future__ import annotations

from typing import Final

VERSION: Final = "eval-cycle-v1"
