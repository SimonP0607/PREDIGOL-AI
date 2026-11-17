"""Two pure calculations that every output that judges or combines a selection shares (plan 2026, bloque E), in SHADOW.

``value`` (``value-v2``, AD-E02, IA-097) .......... the expected value of one selection WITH its interval, its fair price, the age of its price
                                                    and how many bookmakers priced it; «una sola casa» (fewer than three) never confirms.
``dependence`` (``corr-v2``, AD-E07, IA-098) ...... the dependence of two selections, from ONE place: the same match from its score matrix
                                                    (``fbi.forecasting.score_matrix``, IA-074), across matches from the correlation measured on
                                                    settled results (``icc-v1``) with its uncertainty, and always which source said so.

Neither reads a clock nor writes anything; ``dependence.read_measured`` is the one read (``ai.correlation_estimates``, read-only). No
language model computes, corrects or chooses any of these numbers. Their readers today are decision-v2 (``fbi.decision``, shadow) and the
shadow portfolio (``fbi.portfolio``, behind ``--correlation corr-v2``); the parlays (``parlay-v5``) and decision-v1 do not read them: what
production publishes is unchanged (``tests/unit/test_valuation_isolation.py``).
"""
