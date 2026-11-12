"""``decision-v2``: ONE Decision & Risk Engine for every market, in SHADOW (plan IA, P1, IA-012).

The target architecture (capa 10) replaces ``decision-v1`` (``fbi.intel.decision``) and ``decision-fam-v1``
(``fbi.familydecisions.decide``) with one engine: each market FAMILY is a plug-in that brings its candidate predictions and
its settlement rule (``families``), and the filters are shared (``engine``). The flow keeps the objects apart - prediction,
price, value, context, risk, state - and stops there: the pick is frozen by the portfolio and the stake is the portfolio's,
so nothing here stakes. Models produce probabilities, the Council brings evidence only as a typed adjustment
(``fbi.intel.context_adjustment``) that can never raise a state, the market's signals (``fbi.market.signals``) are inputs to
risk and never to probability, and the state (``fbi.intel.state_v2``) is decided by deterministic code.

SHADOW. This package computes and reports. Nothing that decides, publishes, stakes or serves users imports it
(``tests/unit/test_decision_v2_isolation.py``): its only reader is its own command, ``python -m scripts.ia_decision_v2``,
whose ``replay`` recomputes a day's decisions and compares them with decision-v1 and decision-fam-v1 (``replay``) - the
evidence of the P1 gate. It writes nothing. The core's price is decision-v1's consensus of a capture by default; the replay
can price it instead as the odds book held it at each moment, with its age and the book's last price before kick-off
(``book_price``, plan INT-A06).
"""
