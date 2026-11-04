"""What a family decides, and what became of it (plan F11): the decision of the families, its settlement and - the days that follow - what is
learned from it. Corners, cards and the goals of the halves go through the same filters as a market of the pipeline, in SHADOW, under versions of
their own (``fbi.core.decision_versions``), and switched OFF until the owner asks (``FBI_FAMILY_DECISIONS``).

WHY A PACKAGE OF ITS OWN. Not ``fbi.families``: the version of a family's model is keyed by the fingerprint of the sources of that package
(``fbi.families.versioning``), so a file added or edited there renews the version of every family and the prospective record they gather starts again,
and what a family DECIDES or what is LEARNED from it does not decide what a model predicts. Not ``fbi.intel``: the families sit above the decision
layer (they import its judge) and a package below may not import the one above (``tests/unit/test_architecture.py`` holds the import cycle at its
size). So this package sits above both, and nothing under ``src/fbi`` imports it: the clock (``apps/worker/scheduler.py``) hands its steps to the
intelligence jobs and the owner's commands (``scripts/families.py``) call it. ``tests/unit/test_decision_version_guard.py`` holds that list.
"""
