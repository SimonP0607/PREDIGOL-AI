"""The worker's doors to the shadow engines that keep what they compute (IA-093 decision-v2, IA-094 the estimated starters).

A leaf: nothing of ours imports this package but the worker's scheduler (``apps/worker/scheduler.py``), so the engines it opens -
``fbi.decision`` and ``fbi.players`` - stay out of reach of what decides, publishes or serves a reader, and no package import loop
grows through it (``tests/unit/test_architecture.py``). Each module holds one switch (``off`` by default), its cadence and one pass.
"""
