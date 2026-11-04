"""What PrediGol suggests to a reader in Colombia until they choose their own (plan UX: section 24, «arranque en frío», and A13):
one list for Home's suggested leagues (A9), Home's news (A10) and the favourites already ticked in the welcome (A13). A neutral
module - not the API's, not the customer's - so the code that reads it never loads more than this."""

from __future__ import annotations

from typing import Final

SUGGESTED_LEAGUES: Final = (239, 13, 2, 39, 140, 135, 78, 61)
"""The Liga BetPlay (Primera A), the Libertadores, the Champions League and the five big European leagues - by the provider's
league id."""
SUGGESTED_TEAM: Final = "Colombia"
"""And the national team (the senior side: ``is_national`` and this exact name)."""
