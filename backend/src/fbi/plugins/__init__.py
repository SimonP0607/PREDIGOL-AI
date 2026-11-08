"""``family-plugin-v1``: a market family as ONE plug-in that every layer reads (plan IA, P3, IA-018; principle 6 of the target
architecture: "a market is a plug-in - model + calibrator + settlement rule + its own gate; adding a market does not touch the core").

A family is one ``FamilyPlugin`` (``family``): an entry that names, for each layer, the piece of that layer it is, by REFERENCE to what
the layer already has - nothing here re-implements a layer:

    taxonomy      the provider's bets it is priced on (``fbi.odds.quote_taxonomy``) and their catalogue keys (``fbi.market.catalogue``)
    status        NOT_MODELABLE / CANDIDATE / RESEARCH (the taxonomy's words), SHADOW (computed and reported, decides nothing),
                  ACTIVE (only through ``promote``: a CHAMPION calibrator and a validated edge for every one of its markets)
    model         the model name and version of its probabilities, and the distribution provider that gives them and the dependence
                  of two selections of one match (the portfolio's ``JointProvider`` shape, ``fbi.portfolio.correlation``)
    calibrator    the (market, model) slots of ``fbi.intel.calibration`` its probabilities are calibrated in
    settlement    the settlement rule (``fbi.market.rules``) and the function that grades it (``fbi.decision.families.SettlementRule``)
    edge gate     the out-of-sample gate its markets must pass (``edge-gate-v1``, ``fbi.intel.calibration.EDGE_GATE_VERSION``)
    decision      its decision-v2 adapter: a ``fbi.decision.families.MarketFamily``, governed by the plug-in (the status, not the
                  author, says whether it may be more than ABSTAIN)

The registry (``registry``) checks an entry against every layer before it is accepted and hands each consumer its view: the tuple of
families decision-v2 and its replay take, the correlation provider the portfolio takes. The core is never edited to add a family: the
families are passed to it (``engine.decide_all``, ``replay.replay_day(families=...)``, ``correlation.estimate(joint=...)``).

``_template`` is a worked, real but harmless example (team total goals from the ``sim-v1`` joint distribution, SHADOW, never ACTIVE):
copy it to add a family. The owner's checklist is ``docs/owner/IA_018_FAMILIA_PLUGIN.md``.

SHADOW. Nothing that decides, publishes, stakes or serves users imports this package, and no family is installed
(``registry.INSTALLED`` is empty): ``tests/unit/test_family_plugin_isolation.py``.
"""

from __future__ import annotations

from typing import Final

VERSION: Final = "family-plugin-v1"
