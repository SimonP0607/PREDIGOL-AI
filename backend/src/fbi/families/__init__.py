"""Specialised model families (plan F10): the goals of each half, the corners and the cards.

They live apart from ``fbi.models`` on purpose: a change in ``models``, ``features``, ``predictions``, ``backtesting`` or ``domain`` renews
the version of every model PrediGol runs (``tests/unit/test_model_code_version.py``), and a new family must not do that to the old ones. The
families borrow the fitting engine of ``fbi.models.goals`` and add what a count other than goals needs.
"""
