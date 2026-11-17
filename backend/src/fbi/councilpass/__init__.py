"""The pass of the reduced Council (IA-124, AD-D10), in the SHADOW: ``store`` deliberates every pass of the shadow with the protocol
(``fbi.council.protocol``), reduces it (``fbi.council.reduced``: the rules by default, the judge only on a material contradiction) and
appends one row per selection to ``ai.council_reduced`` (``FBI_COUNCIL_REDUCED``, ``off`` by default).

Apart from ``fbi.council`` because that package writes nothing (``tests/unit/test_council_isolation.py``). Only the worker's door imports it.
"""
