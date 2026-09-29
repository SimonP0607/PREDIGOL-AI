"""How far ahead the provider can be seen, measured on this account.

Two numbers, in one place, because three modules need them and a copy that drifts is
how a capture window gets lost: the fixtures sync decides how far ahead to look, the
worker decides how often, and the probe is what measured them in the first place.

Nothing here imports anything, so it is safe to read from module scope anywhere.
"""

from __future__ import annotations

MEASURED_FIRST_PRICE_DAYS: int = 19
"""How far before kick-off pre-match prices were observed to exist.

The provider documents about fourteen days. On 2026-09-29 this account had prices at
T-18.2 days and none at T-24.5, so the documented figure is a floor, not the range. 19
is that measurement rounded away from zero: assuming less would mean a fixture enters
the database only after its first prices already exist, and a pre-match window that
closes unobserved cannot be re-fetched.

Re-measure with ``python -m scripts.probe_windows``; a plan change can widen it.
"""

SYNC_INTERVAL_HOURS: int = 12
"""How often the fixtures sync runs by default. The horizon has to allow for a fixture
appearing just after one run, so this is margin, not decoration."""

DEFAULT_HORIZON_DAYS: int = MEASURED_FIRST_PRICE_DAYS + 2
"""Far enough ahead that a fixture is a row before its first prices exist.

Under the LEAGUE strategy widening this costs nothing at all: the horizon only changes
the from/to parameters of the one request per competition-season. Under DATE it is one
request per calendar day, which against the Ultra plan's 60,000-request guard is noise.
"""
