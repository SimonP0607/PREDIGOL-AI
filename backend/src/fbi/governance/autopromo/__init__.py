"""Bounded automatic promotion under a policy the owner signs (``autopromo-v1``, architecture section 6, phase P3) - BUILT OFF.

Only a narrow class of routine changes may ever promote itself (``policy.ChangeClass``, a closed enum): the periodic refit of a calibrator
that is already promoted, with the same method; the Council weights of agents that already count, within a band; the credibility of the
sources; the validity windows of the cache. Everything else is refused by name or because it is not in the enum - a new model or market in
force, an agent starting to count, the decision rules, the stake policy, the budget are NEVER automatic.

A candidate is ELIGIBLE only when every condition holds (``evaluate.evaluate``, pure):

1. the owner signed a policy that authorises its class - a row the owner writes; nothing here writes one (``policy``);
2. its out-of-sample metric beats the champion's by the policy's margin, on at least the minimum sample;
3. it is reversible: there is a champion in force to roll back to;
4. the class has not used up its changes for the period;
5. the policy names how the owner is told of each promotion;
6. the global switch ``FBI_AUTOPROMO`` is ``on`` (default ``off``).

THIS VERSION HAS NO WRITER. Even with the switch on it only says what WOULD be eligible (``scripts/ia_autopromo.py check``): writing a
promotion stays the owner's, and ``intel.promotions`` is not written by any code of this package (``tests/unit/test_autopromo.py`` proves it).
"""
