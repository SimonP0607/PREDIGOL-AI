"""The pass of the evaluation after the match (IA-112, AD-K01), in the SHADOW: ``reads`` reads what each settled selection is made
of and ``store`` appends its ``eval-sel-v1`` evaluation to ``intel.selection_evaluations`` (``FBI_SELECTION_EVAL``, ``off`` by default).

Apart from ``fbi.evaluation`` (the pure evaluation, the board and the owner's views) because it reads the AI layer's gate and the
picks' settlement while the API layer reads ``fbi.evaluation``: together they would join the import cycle
(``tests/unit/test_architecture.py``). Only the worker's door and the owner's command import it
(``tests/unit/test_selection_evaluation_isolation.py``).
"""
