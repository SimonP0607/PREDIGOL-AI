"""Which side of a match a man was on (plan F3, ``sides-v1``): the squad sheet, the statistics, and the sheets the provider crossed.

The provider tells us who played a match twice: in the SQUAD SHEETS (``core.fixture_lineup_players``: who started, who sat on the
bench) and in the PLAYER STATISTICS (``core.fixture_player_stats``: what each one did). Both name a side, ``home`` or ``away``. They
agree almost always. In 202 of the 137,400 matches that have both - mostly of 2025, almost none since the spring of 2026 - the
provider gave EACH TEAM THE OTHER'S SHEET: Nashville's eleven under Inter Miami and the other way round, while the statistics of the
same match have every man on his own side. (The raw answer shows it: the lineup of team 9569 lists the players of team 9568, with the
right coach beside them; the statistics blocks are right.) The mistake is the provider's, it is made by whole sheets and never by
single men: of the 274,813 sheets that share men with the statistics, 274,367 agree on every man, 404 (both sheets of those 202
matches) disagree on all but one - none in between - and the other 42 differ on a single man, listed in BOTH sheets of his match.

So the rule is the one a person would apply:

* **The statistics win.** A man the statistics place is on the side they say, whatever his sheet says. (Measured against the club he
  played for in the matches around it, they are right in 97.7 % of the disagreements; the sheet, in the rest.)
* **A sheet the statistics turn round is the other side's.** When at least ``MIN_MEN`` of its men are in the statistics and at least
  ``APART_PERCENT`` of them are placed on the other side, the sheet is crossed: every man of it who is NOT in the statistics (a
  substitute who never got on, the matches the statistics miss for one man) is on the other side too.
* **A man in both sheets and not in the statistics is nowhere**: nothing says which side is his, and a wrong guess puts him in a
  club he never played for. A sheet with few men in the statistics is not turned on so little evidence.
* **A match with no statistics keeps its sheet as it is**: nothing says otherwise, and about one in five recent matches has no
  statistics at all. That is the residue this rule cannot reach (``audit`` counts those matches); the repair is at the source
  (the ingestion could orient the sheets with the statistics of the same answer) and the owner decides it.

Pure: the reads of the database are in ``fbi.people.player_history``.
"""

from __future__ import annotations

from typing import Final

VERSION: Final = "sides-v1"

MIN_MEN: Final = 5
"""Men of a sheet that must be in the statistics before the statistics may say the sheet is the other side's."""
APART_PERCENT: Final = 80
"""Share (percent) of those men the statistics must place on the other side."""

HOME: Final = "home"
AWAY: Final = "away"
SIDES: Final = (HOME, AWAY)

_OTHER: Final = {HOME: AWAY, AWAY: HOME}


def other(side: str) -> str:
    """The other side of the match."""
    return _OTHER[side]


def is_crossed(men: int, apart: int) -> bool:
    """Is a squad sheet the other side's? ``men`` of its men are in the statistics of the match and ``apart`` of them are placed there
    on the other side."""
    return men >= MIN_MEN and apart * 100 >= men * APART_PERCENT
