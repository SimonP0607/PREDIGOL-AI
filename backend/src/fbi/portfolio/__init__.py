"""``portfolio-v1``: the Portfolio Engine, in SHADOW (plan IA, P2, IA-013). Deterministic code, not an LLM.

It works on the day's RECOMMENDED selections (decision-v1's rows mapped through ``fbi.intel.state_v2``) and answers what a
portfolio would do with them together, where decision-v1 looks at one selection at a time:

    selection    the row of ``intel.decisions`` the day's selection rule reads, with its state-v2 (``selection``)
    correlation  a dependence estimate for every pair, always with the source it came from: the match's joint score
                 distribution when a provider gives one, the measured intra-class correlation of a competition's
                 matchday (``fbi.parlays.correlation``), otherwise shared-factor rules (``correlation``)
    exposure     limits per match, team, competition, market family and day, with the one that binds (``exposure``)
    stakes       stake-v1 (``fbi.intel.stake``: a quarter of Kelly on the calibrated probability, its caps) per
                 selection, then scaled DOWN for the correlated ones that share a budget, then held by the exposure
                 limits - never above stake-v1, never for a selection that is not RECOMMENDED (``stakes``)
    the day      the day set and the pick of the day by comp-priority-v1 and select_day's caps (``build``)
    parlays      only RECOMMENDED legs, through the parlays' own value gate and correlation guard (``build``)

``build.build_day`` reads; ``build.assemble`` is the pure part. A ``what_if`` mode lets CAUTION in as well, for
MEASUREMENT only: every number it adds is labelled hypothetical.

SHADOW. This package computes and reports. Nothing that decides, publishes, stakes for users or serves the API imports it
(``tests/unit/test_portfolio_isolation.py``): its only reader is its own read-only command,
``python -m scripts.ia_portfolio day --day YYYY-MM-DD``. It writes nothing.
"""

VERSION = "portfolio-v1"
