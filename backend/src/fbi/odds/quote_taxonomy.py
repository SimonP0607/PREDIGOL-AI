"""What every pre-match bet of the provider IS, and whether its prices are structured (plan F1, the price clock).

API-Football sends 333 bet types in every ``/odds`` answer. The live pipeline reads five of them
(``providers.api_football.normalize.PREMATCH_BETS``); the other 333 stayed in the gzipped RAW payloads, which is a
record but not something that can be asked a question. This module is the registry that says, for each bet id:

* the FAMILY it belongs to (result, goals, goals by half, corners, cards, team shots, ...), the PERIOD it covers
  (full time, a half, an interval), and the SUBJECT it is about (the match, one team, a player, a goalkeeper);
* how its ``value`` strings are read (the SCHEMA, see ``fbi.odds.quote_parse``) and whether it carries a line;
* its STATUS: ACTIVE (the live pipeline picks on it), RESEARCH (the plan's priority families, under study),
  CANDIDATE (could be studied later), NOT_MODELABLE (no data to settle it, or no value in it);
* whether its prices are EXTRACTED into ``market.odds_quotes``.

Extracting is a cost (rows, disk), not-extracting is not a loss: every price stays in RAW, which is never deleted, and
flipping ``extract`` and replaying RAW structures it afterwards. So the extracted set is the plan's families and
nothing else: the five markets the pipeline already reads (so the new tables can be checked against ``odds_snapshots``
price for price), goals by half, corners, cards and team shots. Players, goalkeepers, timing and the other sports stay in
RAW.

The extracted bets carry their provider name. The extractor compares it with the name in the payload and refuses the bet
on a mismatch, exactly as the live parser does (a provider renumbering must refuse prices, never relabel them).
Parked bets take their name from ``market.provider_markets`` (the catalogue), and a bet the taxonomy has never seen is
registered as ``unclassified`` with ``extract = false``: visible in the coverage view, never silently dropped.

Handicap-shaped bets (Asian handicap and its relatives) repeat the HOME handicap on both rows of a pair, so the away row
is negated before it is stored (``away_line_negated``). That convention was MEASURED for bet 4 (a pair devigs to 1.090 under
it and to an impossible 0.47 under the other) and, on 22 Oct 2026, on the prices of its two relatives, the first-half (19) and
second-half (104) handicaps (see the bets below): both are extracted with it (``tax-v2``). A relative of bet 4 is only
extracted once the same measurement has been made on its own prices, so any other one stays parked.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

import psycopg
import structlog
from psycopg.rows import tuple_row

log = structlog.get_logger(__name__)

TAXONOMY_VERSION = "tax-v2"
SCOPE = "prematch"
PROVIDER = "api-football"

STATUSES = ("ACTIVE", "RESEARCH", "CANDIDATE", "NOT_MODELABLE")
PERIODS = ("FT", "1H", "2H", "INTERVAL", "OTHER")
SUBJECTS = ("match", "home", "away", "player", "keeper")


@dataclass(frozen=True, slots=True)
class BetSpec:
    bet_id: int
    name: str
    family: str
    period: str = "FT"
    subject: str = "match"
    kind: str = "unspecified"
    schema: str = "text"
    has_line: bool = False
    line_is_signed: bool = False
    away_line_negated: bool = False
    status: str = "CANDIDATE"
    extract: bool = False
    market_key: str | None = None


def _s(bet_id: int, name: str, family: str, period: str, subject: str, kind: str, schema: str, *,
       line: bool = False, signed: bool = False, away_negated: bool = False, status: str = "RESEARCH",
       market_key: str | None = None) -> BetSpec:
    """An EXTRACTED bet: every field stated, because the extractor trusts them."""
    return BetSpec(bet_id=bet_id, name=name, family=family, period=period, subject=subject, kind=kind,
                   schema=schema, has_line=line, line_is_signed=signed, away_line_negated=away_negated,
                   status=status, extract=True, market_key=market_key)


# ── the bets whose prices are structured ─────────────────────────────────────────────────────────────────────────
# The first five are the markets the live pipeline reads: same ids, same names, and the extractor reads them with the
# very functions the pipeline uses (``normalize._selection``), so the two series cannot disagree about a selection.
_LEGACY: tuple[BetSpec, ...] = (
    _s(1, "Match Winner", "result", "FT", "match", "one_x_two", "legacy", status="ACTIVE", market_key="1X2"),
    _s(4, "Asian Handicap", "result", "FT", "match", "asian_handicap", "legacy", line=True, signed=True,
       away_negated=True, status="RESEARCH", market_key="AH"),
    _s(5, "Goals Over/Under", "goals", "FT", "match", "over_under", "legacy", line=True, status="ACTIVE",
       market_key="OU"),
    _s(8, "Both Teams Score", "goals", "FT", "match", "both_teams_score", "legacy", status="ACTIVE",
       market_key="BTTS"),
    _s(12, "Double Chance", "result", "FT", "match", "double_chance", "legacy", status="RESEARCH",
       market_key="DC"),
)

# Draw no bet, team totals: full-time markets around the five.
_RESULT_GOALS: tuple[BetSpec, ...] = (
    _s(2, "Home/Away", "result", "FT", "match", "draw_no_bet", "ha"),
    _s(16, "Total - Home", "goals", "FT", "home", "over_under", "ou", line=True, status="CANDIDATE"),
    _s(17, "Total - Away", "goals", "FT", "away", "over_under", "ou", line=True, status="CANDIDATE"),
)

# Goals by half: the plan's first priority after the five (the football-data matrix says "POR INVESTIGAR - alta":
# the result of a half is known for 97.9 % of finished matches).
_GOALS_HALF: tuple[BetSpec, ...] = (
    _s(6, "Goals Over/Under First Half", "goals_half", "1H", "match", "over_under", "ou", line=True),
    _s(26, "Goals Over/Under - Second Half", "goals_half", "2H", "match", "over_under", "ou", line=True),
    _s(13, "First Half Winner", "goals_half", "1H", "match", "one_x_two", "hda"),
    _s(3, "Second Half Winner", "goals_half", "2H", "match", "one_x_two", "hda"),
    _s(34, "Both Teams Score - First Half", "goals_half", "1H", "match", "both_teams_score", "yn"),
    _s(35, "Both Teams To Score - Second Half", "goals_half", "2H", "match", "both_teams_score", "yn"),
    _s(7, "HT/FT Double", "goals_half", "FT", "match", "half_time_full_time", "text"),
    _s(105, "Home Team Total Goals(1st Half)", "goals_half", "1H", "home", "over_under", "ou", line=True),
    _s(106, "Away Team Total Goals(1st Half)", "goals_half", "1H", "away", "over_under", "ou", line=True),
    _s(107, "Home Team Total Goals(2nd Half)", "goals_half", "2H", "home", "over_under", "ou", line=True),
    _s(108, "Away Team Total Goals(2nd Half)", "goals_half", "2H", "away", "over_under", "ou", line=True),
    _s(109, "Draw No Bet (1st Half)", "goals_half", "1H", "match", "draw_no_bet", "ha"),
    _s(182, "Draw No Bet (2nd Half)", "goals_half", "2H", "match", "draw_no_bet", "ha"),
    _s(20, "Double Chance - First Half", "goals_half", "1H", "match", "double_chance", "dc"),
    _s(33, "Double Chance - Second Half", "goals_half", "2H", "match", "double_chance", "dc"),
    _s(11, "Highest Scoring Half", "goals_half", "FT", "match", "highest_scoring_half", "text"),
    _s(192, "Home Highest Scoring Half", "goals_half", "FT", "home", "highest_scoring_half", "text"),
    _s(193, "Away Highest Scoring Half", "goals_half", "FT", "away", "highest_scoring_half", "text"),
    # Asian handicap by half. MEASURED on the server on 22 Oct 2026 (400 newest /odds bodies: 2,126 first-half and 779 second-half
    # bookmaker groups): like bet 4, both rows of a pair repeat the HOME handicap - the pair adds up to 1.085 / 1.094 (median)
    # that way and to anything between 0.28 and 1.9 the other way, and the away price RISES with the printed number in 1,833 of
    # 2,126 and 770 of 779 groups (never falls) - so the away row is negated.
    _s(19, "Asian Handicap First Half", "goals_half", "1H", "match", "asian_handicap", "ah", line=True, signed=True,
       away_negated=True, status="CANDIDATE"),
    _s(104, "Asian Handicap (2nd Half)", "goals_half", "2H", "match", "asian_handicap", "ah", line=True, signed=True,
       away_negated=True, status="CANDIDATE"),
    _s(22, "Odd/Even - First Half", "goals_half", "1H", "match", "odd_even", "oe", status="CANDIDATE"),
    _s(63, "Odd/Even - Second Half", "goals_half", "2H", "match", "odd_even", "oe", status="CANDIDATE"),
)

# Corners: full-time only. Half-time corners are priced but the provider gives no corners by half, so a price on them could
# never be graded (the matrix says NO VIABLE); they are parked below, not lost.
_CORNERS: tuple[BetSpec, ...] = (
    _s(45, "Corners Over Under", "corners", "FT", "match", "over_under", "ou", line=True),
    _s(55, "Corners 1x2", "corners", "FT", "match", "one_x_two", "hda"),
    _s(57, "Home Corners Over/Under", "corners", "FT", "home", "over_under", "ou", line=True,
       status="CANDIDATE"),
    _s(58, "Away Corners Over/Under", "corners", "FT", "away", "over_under", "ou", line=True,
       status="CANDIDATE"),
    _s(307, "Corners. Double Chance", "corners", "FT", "match", "double_chance", "dc", status="CANDIDATE"),
    _s(339, "Corners. Double Chance", "corners", "FT", "match", "double_chance", "dc", status="CANDIDATE"),
)

# Cards: a card total is graded from the events (90 % of matches have them), a half's total too.
_CARDS: tuple[BetSpec, ...] = (
    _s(80, "Cards Over/Under", "cards", "FT", "match", "over_under", "ou", line=True),
    _s(82, "Home Team Total Cards", "cards", "FT", "home", "over_under", "ou", line=True, status="CANDIDATE"),
    _s(83, "Away Team Total Cards", "cards", "FT", "away", "over_under", "ou", line=True, status="CANDIDATE"),
    _s(150, "Home Team Yellow Cards", "cards", "FT", "home", "over_under", "ou", line=True, status="CANDIDATE"),
    _s(151, "Away Team Yellow Cards", "cards", "FT", "away", "over_under", "ou", line=True, status="CANDIDATE"),
    _s(153, "Yellow Over/Under", "cards", "FT", "match", "over_under", "ou", line=True, status="CANDIDATE"),
    _s(154, "Yellow Double Chance", "cards", "FT", "match", "double_chance", "dc", status="CANDIDATE"),
    _s(155, "Yellow Over/Under (1st Half)", "cards", "1H", "match", "over_under", "ou", line=True,
       status="CANDIDATE"),
    _s(156, "Yellow Over/Under (2nd Half)", "cards", "2H", "match", "over_under", "ou", line=True,
       status="CANDIDATE"),
    _s(158, "Yellow Cards 1x2", "cards", "FT", "match", "one_x_two", "hda", status="CANDIDATE"),
    _s(335, "Red Cards Over/Under", "cards", "FT", "match", "over_under", "ou", line=True, status="CANDIDATE"),
)

# Team shots: the team's own shots, never a player's.
_SHOTS: tuple[BetSpec, ...] = (
    _s(87, "Total ShotOnGoal", "shots", "FT", "match", "over_under", "ou", line=True, status="CANDIDATE"),
    _s(88, "Home Total ShotOnGoal", "shots", "FT", "home", "over_under", "ou", line=True, status="CANDIDATE"),
    _s(89, "Away Total ShotOnGoal", "shots", "FT", "away", "over_under", "ou", line=True, status="CANDIDATE"),
    _s(211, "Total Shots", "shots", "FT", "match", "over_under", "ou", line=True, status="CANDIDATE"),
    _s(221, "Shots. Home Total", "shots", "FT", "home", "over_under", "ou", line=True, status="CANDIDATE"),
    _s(220, "Shots. Away Total", "shots", "FT", "away", "over_under", "ou", line=True, status="CANDIDATE"),
    _s(176, "ShotOnTarget 1x2", "shots", "FT", "match", "one_x_two", "hda", status="CANDIDATE"),
    _s(340, "Shots.1x2", "shots", "FT", "match", "one_x_two", "hda", status="CANDIDATE"),
)

EXTRACTED: tuple[BetSpec, ...] = (*_LEGACY, *_RESULT_GOALS, *_GOALS_HALF, *_CORNERS, *_CARDS, *_SHOTS)

# ── the bets that stay in RAW (extract = false) ──────────────────────────────────────────────────────────────────
# (family, status, bet ids). Period, subject and a name come from the catalogue text when the row is written.
_PARKED: tuple[tuple[str, str, tuple[int, ...]], ...] = (
    # Handicaps and goal-market relatives whose sign convention has not been measured on their own prices yet, combos that
    # the goal distribution already contains, and markets whose value is not informative (odd/even, exact score).
    ("result", "CANDIDATE", (9, 206, 207)),
    ("advance", "NOT_MODELABLE", (61, 189)),
    ("goals", "CANDIDATE", (
        10, 21, 23, 24, 25, 27, 28, 29, 30, 36, 38, 40, 41, 43, 44, 47, 49, 50, 60, 91, 110, 118, 119, 120, 121,
        183, 186, 188, 195, 196, 223, 282, 330, 331, 332, 333, 336, 349)),
    ("goals_half", "CANDIDATE", (
        18, 31, 32, 37, 39, 42, 46, 48, 51, 52, 53, 62, 72, 73, 111, 112, 113, 114, 115, 116, 117, 122, 123,
        181, 184, 187, 190, 191, 194, 199, 200, 201, 202, 283, 284)),
    ("corners", "NOT_MODELABLE", (
        56, 77, 84, 85, 125, 126, 127, 128, 130, 131, 132, 133, 134, 135, 239, 295, 338)),
    ("cards", "CANDIDATE", (
        79, 81, 86, 152, 157, 159, 160, 161, 162, 203, 204, 250, 252, 299, 300, 309, 310, 342)),
    ("shots", "CANDIDATE", (78, 177, 178, 243, 244)),
    ("fouls", "CANDIDATE", (170, 171, 172, 173, 174, 175, 314, 343)),
    ("tackles", "CANDIDATE", (281, 301, 302)),
    ("offsides", "NOT_MODELABLE", (164, 165, 166, 167, 168, 169, 313)),
    ("saves", "NOT_MODELABLE", (267, 268, 274, 315, 316, 317, 318, 319, 320, 323)),
    ("timing", "NOT_MODELABLE", (
        14, 15, 54, 74, 75, 76, 136, 137, 138, 139, 140, 141, 142, 143, 144, 145, 146, 147, 148, 149, 179, 180, 185, 197,
        198, 205, 208, 247, 248, 253, 260, 261, 262, 263, 280, 291, 292, 293, 294, 296, 297, 303, 304, 305, 306, 308,
        311, 312, 324, 325, 326, 327, 328, 329, 334)),
    ("special", "NOT_MODELABLE", (
        59, 97, 124, 129, 163, 209, 210, 222, 224, 225, 227, 228, 229, 230, 245, 246, 249, 254, 285, 298, 321, 322)),
    ("players", "NOT_MODELABLE", (
        92, 93, 94, 95, 96, 99, 100, 102, 103, 218, 219, 226, 231, 232, 233, 234, 235, 236, 237, 238, 240, 241, 242,
        251, 255, 256, 257, 258, 259, 264, 265, 266, 269, 270, 271, 272, 273, 275, 276, 277, 278, 279, 286, 287,
        288, 289, 290)),
    ("other_sport", "NOT_MODELABLE", (212, 213, 214, 215, 216, 217, 337, 344, 345, 346, 347, 348)),
    ("unclassified", "NOT_MODELABLE", (341,)),
)

_FIRST_HALF = re.compile(r"(first half|1st half|\(1st|half-time|halftime|1st set)", re.IGNORECASE)
_SECOND_HALF = re.compile(r"(second half|2nd half|\(2nd)", re.IGNORECASE)
_INTERVAL = re.compile(r"(\d+\s*-\s*\d+\s*min|between\s+\d+|minutes?\b|\bmin\b|\d+m\b)", re.IGNORECASE)


def _infer_period(name: str) -> str:
    if _FIRST_HALF.search(name):
        return "1H"
    if _SECOND_HALF.search(name):
        return "2H"
    if _INTERVAL.search(name):
        return "INTERVAL"
    return "FT"


def _infer_subject(name: str, family: str) -> str:
    low = name.lower()
    if family == "players" or "player" in low or "scorer" in low:
        return "player"
    if "goalkeeper" in low or family == "saves":
        return "keeper"
    if re.search(r"\bhome\b", low):
        return "home"
    if re.search(r"\baway\b", low):
        return "away"
    return "match"


def _parked_spec(bet_id: int, name: str, family: str, status: str) -> BetSpec:
    return BetSpec(bet_id=bet_id, name=name, family=family, period=_infer_period(name),
                   subject=_infer_subject(name, family), kind="unspecified", schema="text", status=status,
                   extract=False)


def _build_index() -> dict[int, tuple[str, str]]:
    index: dict[int, tuple[str, str]] = {}
    for family, status, ids in _PARKED:
        for bet_id in ids:
            if bet_id in index:
                raise RuntimeError(f"bet {bet_id} is parked twice ({index[bet_id][0]} and {family})")
            index[bet_id] = (family, status)
    overlap = sorted(set(index) & {s.bet_id for s in EXTRACTED})
    if overlap:
        raise RuntimeError(f"bets both extracted and parked: {overlap}")
    return index


_PARKED_INDEX = _build_index()
_EXTRACTED_BY_ID: dict[int, BetSpec] = {}
for _spec in EXTRACTED:
    if _spec.bet_id in _EXTRACTED_BY_ID:
        raise RuntimeError(f"bet {_spec.bet_id} is extracted twice")
    _EXTRACTED_BY_ID[_spec.bet_id] = _spec


def extracted_specs() -> tuple[BetSpec, ...]:
    return EXTRACTED


def known_bet_ids() -> frozenset[int]:
    return frozenset(_EXTRACTED_BY_ID) | frozenset(_PARKED_INDEX)


def spec_for(bet_id: int, name: str = "") -> BetSpec:
    """The classification of one bet. A bet the taxonomy has never seen is ``unclassified`` and not extracted."""
    spec = _EXTRACTED_BY_ID.get(bet_id)
    if spec is not None:
        return spec
    parked = _PARKED_INDEX.get(bet_id)
    if parked is not None:
        return _parked_spec(bet_id, name, parked[0], parked[1])
    return BetSpec(bet_id=bet_id, name=name, family="unclassified", period=_infer_period(name),
                   subject=_infer_subject(name, "unclassified"), status="NOT_MODELABLE", extract=False)


def same_name(a: str, b: str) -> bool:
    return " ".join(a.split()).casefold() == " ".join(b.split()).casefold()


def sync_definitions(conn: psycopg.Connection, *, names: Mapping[int, str] | None = None,
                     observed: Iterable[tuple[int, str]] = ()) -> dict[int, int]:
    """Make ``market.market_definitions`` say what this module says. Idempotent; returns bet id -> definition id.

    ``names`` are the catalogue names of the bets (default: ``market.provider_markets``, scope prematch); ``observed`` are
    (bet id, name) pairs seen inside real payloads, for bets neither the taxonomy nor the catalogue knew. Nothing is deleted:
    a definition that is no longer in the taxonomy keeps its row (prices captured under it happened).

    A row is rewritten only when the taxonomy changed it (``taxonomy_version``): editing a definition by hand in the
    database survives until the version moves, which is the owner's lever for switching one bet on before a release.
    """
    with conn.cursor(row_factory=tuple_row) as cur:
        if names is None:
            cur.execute("SELECT provider_bet_id, name FROM market.provider_markets WHERE provider = %s AND scope = %s",
                        (PROVIDER, SCOPE))
            names = {int(b): str(n) for b, n in cur.fetchall()}
        all_names: dict[int, str] = dict(names)
        for bet_id, name in observed:
            all_names.setdefault(int(bet_id), name)
        wanted = set(all_names) | set(_EXTRACTED_BY_ID) | set(_PARKED_INDEX)
        cur.execute("SELECT provider_bet_id FROM market.market_definitions "
                    "WHERE provider = %s AND scope = %s AND taxonomy_version = %s", (PROVIDER, SCOPE, TAXONOMY_VERSION))
        current = {int(b) for (b,) in cur.fetchall()}
        for bet_id in sorted(wanted - current):
            spec = spec_for(bet_id, _EXTRACTED_BY_ID[bet_id].name if bet_id in _EXTRACTED_BY_ID
                            else all_names.get(bet_id, ""))
            cur.execute(
                "INSERT INTO market.market_definitions (provider, scope, provider_bet_id, name, family, period, "
                " subject, kind, schema, has_line, line_is_signed, away_line_negated, status, extract, market_key, "
                " taxonomy_version) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (provider, scope, provider_bet_id) DO UPDATE SET "
                " name = EXCLUDED.name, family = EXCLUDED.family, period = EXCLUDED.period, "
                " subject = EXCLUDED.subject, kind = EXCLUDED.kind, schema = EXCLUDED.schema, "
                " has_line = EXCLUDED.has_line, line_is_signed = EXCLUDED.line_is_signed, "
                " away_line_negated = EXCLUDED.away_line_negated, status = EXCLUDED.status, "
                " extract = EXCLUDED.extract, market_key = EXCLUDED.market_key, "
                " taxonomy_version = EXCLUDED.taxonomy_version, classified_at = now() "
                "WHERE market.market_definitions.taxonomy_version IS DISTINCT FROM EXCLUDED.taxonomy_version",
                (PROVIDER, SCOPE, spec.bet_id, spec.name or all_names.get(bet_id, "") or f"bet {bet_id}",
                 spec.family, spec.period, spec.subject, spec.kind, spec.schema, spec.has_line,
                 spec.line_is_signed, spec.away_line_negated, spec.status, spec.extract, spec.market_key,
                 TAXONOMY_VERSION),
            )
        cur.execute("SELECT provider_bet_id, id FROM market.market_definitions WHERE provider = %s AND scope = %s",
                    (PROVIDER, SCOPE))
        return {int(b): int(i) for b, i in cur.fetchall()}
