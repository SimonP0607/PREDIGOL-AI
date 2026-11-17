"""The way back from an analysis to the news it read (IA-122, plan piece AD-G08, contract C-07): ``link-v1``.

* ``validate`` - the validator, pure: a fact links to an evaluation only with the entity by its id (a team of the match or a player of
  its two squads), a literal quote that names it (not a surname alone, never a homonym without a signal) and a date inside the match's
  window (after the team's previous match: a club's news is not hung from all its matches); then its level and its relation to the
  analysis (``a_favor``, ``en_contra``, ``contexto``, ``no_usada``) by code, from the line-up dependencies of the selections.
* ``store`` - what the evaluation cycle calls at the moment of each evaluation E1-E4, in the same transaction: reads what was known as of
  that moment, validates, writes ``intel.eval_source_lists`` and ``intel.eval_sources`` (revision 0160, append-only). A relation is never
  written afterwards: the database refuses it (``intel.eval_sources_at_decision``).
* ``views`` - the reads the API serves C-07 from (rows only: the contract is built in ``fbi.api.services.analysis_sources``).

No model of language, no web, no probability: the relation is a record of what the code saw, not a new figure. This package imports
nothing of ``fbi.ai``, ``fbi.news`` or ``fbi.evalcycle`` (the API reads it). The owner's guide: ``docs/owner/IA_120_NOTICIAS_C06_C07.md``.
"""

from __future__ import annotations

from typing import Final

VERSION: Final = "link-v1"
