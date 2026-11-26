"""Observations for the registry test: the same function as the unit test's, in a module of its own."""

from __future__ import annotations

import random
from datetime import date, timedelta

from fbi.intel import factor_residual as fr


def observations() -> list[fr.Obs]:
    rng = random.Random(11)
    return [fr.Obs(date(2026, 1, 1) + timedelta(days=d), "g", 1.0 if rng.random() < 0.45 else 0.0, 0.45) for d in range(150) for _ in range(20)]
