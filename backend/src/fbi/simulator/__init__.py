"""The joint match simulator (``sim-v1``, IA-013, P2), in SHADOW.

One joint distribution per match over the goals of each side in each half, ``(home_1H, away_1H, home_2H, away_2H)``, built from the
fitted models in force (Poisson / Dixon-Coles in ``fbi.models.goals``; the half fits of ``fbi.families`` where they are given). Every
result and goals market of the match is a SUM over that one distribution (``markets``), so the markets of a match are coherent with
each other by construction and the dependence between any two selections can be measured (the correlation provider the Portfolio
Engine will plug in). ``consistency`` compares what it derives with what the models in force stored, and lists any incoherence in
those stored numbers.

Shadow means: it computes and reports. It replaces no model, writes nothing, and nothing that decides, picks, publishes a forecast or
serves the API imports it (``tests/unit/test_simulator_isolation.py``). It lives outside the model packages on purpose: a file in
``fbi.models``, ``features``, ``predictions``, ``backtesting`` or ``domain`` would renew the version of every model
(``fbi.core.version.MODEL_PACKAGES``). No heuristic mapping and no language model: every number is a sum over the distribution.
"""

from __future__ import annotations

from typing import Final

VERSION: Final = "sim-v1"
