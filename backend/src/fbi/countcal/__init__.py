"""Corners and cards: the calibrator of the counts and the private evaluation of their selections (plan 2026, AD-B07 / AD-E03,
``IA-095`` / ``IA-096``). SHADOW: nothing here reaches a reader, a published pick or a model.

* ``calibrator``   ``count-cal-v1``: one logistic map of the probability of «over L» for every line of a count. Pure.
* ``walkforward``  the LAB of the preregistered protocol ``AD-B07``: family-v1 refitted block by block, its out-of-sample dispersion,
                   the calibrator, the league mean and the market; one verdict per family. Pure.
* ``market``       the books' probability without margin (3 complete books or more), as one read-only statement.
* ``admission``    which corners or cards selection may enter the private evaluation (IA-096). Pure.
* ``store``        the calibrators and the owner's signature (``intel.count_calibrators``, revision 0152), append-only.
* ``private``      the shadow pass of the private evaluation: the cycle of states of the admitted selections only.

It lives OUTSIDE the packages with a model fingerprint on purpose: ``fbi.core.version.MODEL_PACKAGES`` (the goal models) and
``fbi.families.versioning.fingerprint`` (``family-v1``). A file here renews the version of no model; ``family-v1`` keeps its rows.
"""
