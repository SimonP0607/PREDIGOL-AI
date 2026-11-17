"""The one cycle of states of a selection (IA-068, plan piece AD-D02), append-only and in SHADOW.

Ten states - detected, under investigation, under evaluation, waiting for the line-ups, confirmed in the shadow, withdrawn,
discarded, in play, settled, evaluated - kept as a chain of rows that is never rewritten (``intel.selection_lifecycle``,
revision 0142). Today five layers say where a selection stands (``decision-v1`` and ``decision-fam-v1`` in
``intel.decisions``, the combined review in ``ai.pick_reviews``, ``state-v2``, ``user-status-v2`` and the stages of the day's
set); this package reads them and writes ONE chain per selection beside them, without changing any of them.

* ``machine`` - the states, the closed reasons, the legal transitions and who may make each (pure).
* ``derive`` - the map from the current layers to the cycle, ``lifecycle-map-v1`` (pure).
* ``store`` - the shadow pass: read the layers, append what is missing (switch ``FBI_SELECTION_LIFECYCLE``, ``off`` by default).
* ``reader`` - the private reading for C-03 (counts by state and the selections with their state).

Nothing here is imported by the decision layer, the picks, the parlays or a page a reader can open, and nothing here imports
``fbi.decision`` (decision-v2 stays in its own sandbox).
"""
