"""The evaluation after the match and the validation board (IA-112 / IA-113, plan pieces AD-K01 and AD-K02). In the SHADOW.

* ``selection`` - ``eval-sel-v1``: the ONE evaluation of a settled selection, by code (pure): what was anticipated against what
  happened, the value against the close, each fact the decision cited held, contradicted or not judgeable, the effect of the
  official line-up, and its parity with ``intel.decision_outcomes``.
* ``sources`` - what C-02 reads besides the evaluation: the sources a decision cited and when the line-up was seen (read only).
* the pass lives in ``fbi.evalpass``: ``reads`` (every statement that reads what an evaluation is made of, read only, under a
  statement timeout) and ``store`` (the shadow pass that appends the evaluations to ``intel.selection_evaluations``,
  ``FBI_SELECTION_EVAL``, ``off`` by default, and the dry run that computes them without writing). It is apart because it reads
  the AI layer's gate and the picks' settlement, and this package is read by the API layer: together they would join the import
  cycle (``tests/unit/test_architecture.py``).
* ``board`` - the validation board by layer, family and market (``board-v1`` under the preregistered protocol ``AD-K02``): a
  verdict VALIDADO / NO_VALIDADO / INSUFICIENTE that activates nothing.

Nothing that decides, stakes or publishes imports this package (``tests/unit/test_selection_evaluation_isolation.py``); the private
screens (C-02, C-03) read it. No language model gives a verdict here: every word is a rule of this code.
"""
