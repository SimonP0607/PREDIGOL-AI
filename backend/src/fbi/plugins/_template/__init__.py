"""The template of a plug-in family, with a worked example that is real but harmless: TEAM_TOTALS (``family``).

TO ADD A FAMILY, copy this package to ``fbi/plugins/<name>/`` and change, in order (the owner's checklist is
``docs/owner/IA_018_FAMILIA_PLUGIN.md``):

    1 data         ``BETS``: the provider's bets (``fbi.odds.quote_taxonomy``), extracted; ``MARKET_KEYS``: their catalogue keys;
                   ``RULE``: the settlement rule that grades them (``fbi.market.rules``)
    2 model        ``MODEL`` / ``MODEL_VERSION`` and the reading of its probabilities as of a moment (``read_inputs``); the
                   distribution provider (``TeamTotalsModel``: its probabilities and the dependence of two selections of one match)
    3 calibration  nothing to write: the calibrator slots are (market key, ``MODEL``) of ``fbi.intel.calibration``
    4 evaluation   the adapter (``TeamTotalsFamily``) decision-v2 judges in SHADOW; the replay and the portfolio take the family
                   from the registry, at run time (``tests/unit/test_family_plugin.py`` shows how)
    5 gate         ``STATUS`` stays SHADOW. ACTIVE only through ``fbi.plugins.family.promote``: a CHAMPION calibrator and a validated
                   edge for every market, by the owner. This example forbids it (``activatable=False``)

The example is not installed (``fbi.plugins.registry.INSTALLED`` is empty) and nothing that decides imports it.
"""
