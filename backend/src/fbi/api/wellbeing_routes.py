"""The ONE table of what shows a price, a pick or a parlay (plan PM, PM-14-07): the single control point of «solo fútbol».

Every call a signed-in reader can make outside the Admin Console is in exactly one of three lists, and a test
(``tests/unit/test_wellbeing_routes.py``) walks the whole OpenAPI document and fails for a call in none of them - so a route added
tomorrow cannot slip a price past a reader who chose to see none without somebody deciding, here, which list it belongs to:

* ``BLOCKED`` - the route IS a price, a pick or a parlay (Cuotas, Picks, Mi parlay, Transparencia...): for a reader in the mode it
  answers 403 ``wellbeing_active`` (``fbi.api.security.wellbeing_required``) and nothing else changes.
* ``MIXED``   - a football route that also carries prices or picks among its fields (Inicio, Hoy, the Match Center...). The API still
  answers it - the football is the point of the mode - and the WEB hides what it draws from it (``useWellbeing``). Taking the fields
  out of the answer is the part that depends on the design of each screen (PM-14-04 gives the single reading of the matrix; the screens
  follow): listed here so that it is a decision, with an owner, and not an omission.
* ``OPEN``    - nothing in it is a price: the account, football facts, news, the law, support.

An entry is ``"METHOD /path/{template}"``; ``{x}`` matches one path segment, so the same table reads a template (the test) and a real
path (the guard).
"""

from __future__ import annotations

import re
from typing import Final

BLOCKED: Final[frozenset[str]] = frozenset({
    "GET /daily", "GET /picks", "GET /picks/started", "GET /picks/{pick_id}/explanation",
    "GET /parlays/build", "GET /parlays/{kind}", "POST /explain/parlay",
    "GET /odds", "GET /odds/board", "GET /odds/families", "GET /odds/fixtures/{fixture_id}",
    "GET /odds/fixtures/{fixture_id}/movement", "GET /odds/status",
    "GET /matches/{fixture_id}/markets", "GET /matches/{fixture_id}/markets/catalog", "GET /matches/{fixture_id}/odds-book",
    "GET /matches/{fixture_id}/market-probs",
    "GET /me/history", "GET /me/picks", "POST /me/picks", "GET /me/picks/export", "GET /me/picks/summary",
    "DELETE /me/picks/{record_id}", "PATCH /me/picks/{record_id}",
    "GET /me/parlays", "POST /me/parlays", "GET /me/parlays/export", "POST /me/parlays/validate", "DELETE /me/parlays/{record_id}",
    "GET /today/no-pick", "GET /transparency", "GET /transparency/export", "GET /transparency/picks",
})
MIXED: Final[frozenset[str]] = frozenset({
    "GET /home", "GET /today", "GET /me/today", "GET /live", "GET /matches", "GET /matches/{fixture_id}",
    "GET /matches/{fixture_id}/center", "GET /matches/{fixture_id}/analysis", "GET /matches/{fixture_id}/intelligence",
    "GET /matches/{fixture_id}/intelligence/v2", "GET /matches/{fixture_id}/reading", "GET /matches/{fixture_id}/postmatch",
    "GET /matches/{fixture_id}/knowledge", "GET /matches/{fixture_id}/forecast", "GET /matches/{fixture_id}/stats-preview",
    "GET /me/personal", "PUT /me/personal/markets", "POST /me/personal/suggestion/dismiss", "GET /explain",
    "GET /stats/compare/players", "GET /stats/compare/teams",
})
OPEN_PREFIXES: Final[tuple[str, ...]] = (
    "/announcements", "/auth/", "/availability/", "/competitions", "/email/", "/events", "/health", "/legal/", "/monitoring/",
    "/news", "/players", "/search", "/support/", "/teams", "/telegram/", "/today/news",
    "/me/account", "/me/calendar-feed", "/me/consents", "/me/export", "/me/favorites", "/me/feedback", "/me/guides", "/me/hints",
    "/me/inbox", "/me/match-alerts", "/me/membership", "/me/onboarding", "/me/payment-request", "/me/preferences",
    "/me/privacy-requests", "/me/push", "/me/support", "/me/updates", "/me/wellbeing",
)
"""Prefixes of the calls that carry no price: the account, the law, support, news, the football's own facts (teams, players,
competitions). A new ``/me/...`` or ``/matches/...`` call is in none of them until somebody puts it here, in ``MIXED`` or in ``BLOCKED``."""
OPEN_MATCH_PARTS: Final[frozenset[str]] = frozenset({"calendar", "availability", "news", "news/v2", "profile", "sources"})


def _regex(entry: str) -> re.Pattern[str]:
    return re.compile(re.sub(r"\\\{[^}]+\\\}", "[^/]+", re.escape(entry)))


_BLOCKED = [_regex(e) for e in sorted(BLOCKED)]
_MIXED = [_regex(e) for e in sorted(MIXED)]
_OPEN_MATCH = re.compile(r"[A-Z]+ /matches/[^/]+/(" + "|".join(re.escape(p) for p in sorted(OPEN_MATCH_PARTS)) + ")")


def blocked(method: str, path: str) -> bool:
    """Whether this call is a price, a pick or a parlay itself (``path`` without ``/api/v1``; a template or a real path)."""
    call = f"{method} {path}"
    return any(p.fullmatch(call) for p in _BLOCKED)


def mixed(method: str, path: str) -> bool:
    call = f"{method} {path}"
    return any(p.fullmatch(call) for p in _MIXED)


def open_(method: str, path: str) -> bool:
    return _OPEN_MATCH.fullmatch(f"{method} {path}") is not None or any(path.startswith(p) for p in OPEN_PREFIXES)
