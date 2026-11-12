"""The switches that decide what a reader is shown (plan UX, A9): one rule for all of them.

``FBI_FORECAST_USERS``, ``FBI_CALENDAR_USERS``, ``FBI_KNOWLEDGE_USERS`` and ``FBI_READING_USERS`` are ON when the line is
absent - the owner approved showing PrediGol's forecast, the calendar, the base of the post-match and the structured reading
with phase A9 - and a line in ``/etc/predigol/app.env`` turns any of them off again without a deploy (``=0`` and the API
recreated). A value that reads as neither on nor off counts as off: when the owner wrote something to that line, showing less
is the safer reading of it. The Admin Console's preview never depends on them.
"""

from __future__ import annotations

from typing import Final

from fbi.core.env import environment

ON: Final = frozenset({"1", "on", "true", "yes"})


TRANSPARENCY: Final = "FBI_TRANSPARENCY"
"""«Cómo le va a PrediGol» (plan UX, A12): OFF while the line is absent - the page is published only after the owner reviewed
it in QA (P9) - and ``=1`` opens it to every signed-in reader (the API recreated). The Admin Console's preview
(``preview=shadow``) shows it either way."""


EXPLAIN: Final = "FBI_EXPLAIN"
"""«Explícame» (plan UX, B9): ON while the line is absent - it reads what PrediGol already keeps, calls no AI and costs
nothing - and ``=0`` takes the buttons and their routes away (the API recreated)."""


ODDS_EXPLORER: Final = "FBI_ODDS_EXPLORER"
"""The new Cuotas explorer (plan Cuotas, BE-011 exposes it, UX-068 reads it): OFF while the line is absent - the explorer is
deployed off and switched on once it is verified in production (decision 8 of the plan) - and ``=1`` shows it instead of the
current Cuotas page (the API recreated). The explorer's endpoints answer either way: the switch decides what the page shows."""


ODDS_STATUS: Final = "FBI_ODDS_STATUS"
"""«Estado de los precios» (plan maestro UX/UI 2026, decision 4; BE-038): OFF while the line is absent - ``GET /odds/status``
does not exist (404) and the page shows no way to it - and ``=1`` opens it to every signed-in reader (the API recreated). It
reads what the capture already stored: it asks the provider nothing and changes no price."""


def user_switch(name: str, *, default: bool) -> bool:
    """Whether the switch ``name`` is on: ``default`` while the line is absent or empty, off for a value it cannot read."""
    raw = environment().get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ON


def transparency_open() -> bool:
    """Whether readers see «Cómo le va a PrediGol» (``FBI_TRANSPARENCY``, off by default)."""
    return user_switch(TRANSPARENCY, default=False)


def explain_on() -> bool:
    """Whether readers get «Explícame» (``FBI_EXPLAIN``, on by default)."""
    return user_switch(EXPLAIN, default=True)


def odds_explorer_on() -> bool:
    """Whether the page shows the new Cuotas explorer (``FBI_ODDS_EXPLORER``, off by default)."""
    return user_switch(ODDS_EXPLORER, default=False)


def odds_status_on() -> bool:
    """Whether readers get «Estado de los precios» (``FBI_ODDS_STATUS``, off by default)."""
    return user_switch(ODDS_STATUS, default=False)
