"""What every bet type the provider ACTUALLY sends is, for the odds explorer: taxonomy ``tax-v3`` (plan Cuotas, phase 2).

``fbi.odds.quote_taxonomy`` (``tax-v2``) classifies the 338 pre-match bets of the catalogue and decides which 55 are structured
into ``market.odds_quotes``. In 14 days (26 Oct - 8 Nov 2026, 1,703 matches, 9,926 answers) only 137 of them arrived. This module
describes those 137 for the current-price book (``market.book_current``, ``fbi.odds.book``) and the explorer that will read it:

* a stable KEY, ``<domain>.<market>.<period>[.<home|away>]`` (``corners.total.ft``, ``goals.total.1h.home``,
  ``player.anytime_scorer.ft``); ``market`` (the key without period and team) is what the explorer's market chips group;
* the FAMILY (a key of ``market.market_families``), the PERIOD (FT, 1H, 2H or INTERVAL with its ``minutes``) and the SUBJECT
  (match, home, away, player, keeper);
* the READER: how a ``value`` string is turned into a selection and a line (``fbi.odds.book_parse``);
* ``fair_method`` (``shin``, ``proportional`` or ``none``), ``exhaustive`` (the selections cover every outcome) and ``parlay``
  (only the five markets of Mi Parlay);
* ``visible``: False when the type cannot be read safely. A hidden type never enters the book; its reason says why.

It is METADATA ONLY. Nothing here changes what the extractor does: ``tax-v2`` keeps deciding what is written to
``market.odds_quotes`` (its version, its 55 ``extract`` flags and its parser are untouched), and the five classic markets keep
their pipeline. The rows of ``market.market_definitions`` are still written by ``tax-v2``; the book looks them up by bet id.

HOW EVERY READER WAS VALIDATED (8 Nov 2026): the four real RAW ``/odds`` bodies of the audit (Premier League with player props,
Serie A, Colombia Primera A, Copa del Rey: 133 of the 137 types, 33 bookmakers' books) plus the contract fixture of the test suite
were read value by value; every value of every visible type is read, and for the 42 types ``tax-v2`` extracts the reading is the
extractor's, selection for selection (``tests/unit/test_book_taxonomy.py``). What the samples showed, and decided:

* Asian handicaps (4, 19, 104, and the parked 56 corners and 81 cards): the provider prints the HOME handicap on both rows of a
  pair. Read that way every pair of the samples is a believable two-way book (267/267, 141/141, 67/67, 81/81, 16/16, raw book
  in (1, 1.25]); read as a per-side handicap 12/136, 0/74, 0/38, 2/34 and 0/10 are. The away row is negated, as ``tax-v2`` does
  for 4, 19 and 104 (E1 of the plan, in the data model).
* European handicaps (9, 18, 181, 239, 79): three rows with the same printed number, the HOME handicap of a three-way market;
  every complete group is a three-way book between 1.034 and 1.268. The line of the group is that number.
* "more N" in the exact-goals markets (38, 40, 41, 42, 46) is "N or more": every bookmaker lists 0 .. N-1 and then "more N"
  (never N and "more N" together).
* "Draw" in Winning Margin (47) and First Goal Method (97) is 0-0: its price equals the 0:0 exact score of the same bookmaker in
  every answer of the samples that quotes them (17.00, 8.50, 12.00, 15.00). It is read as ``No goal``, the provider's own word
  in 14, 15 and 185.
* Total Corners (1st Half) (77) mixes two markets under one id: a bookmaker that quotes "Exactly 4" beside "Over 4" / "Under 4"
  prices a THREE-way line (exactly 4 loses), the others a two-way Asian line (exactly 4 is void). They are kept apart
  (``three_way = "when_exactly"``) and never compared.

Hidden, with the evidence:

* 78 "RTG_H1": an opaque name. Its six values read as first-half result and total ("Draw/Under 1.5" is priced exactly as the
  0:0 half-time score in the four answers that have it), but the provider never says so.
* 215 "Player Singles": filed under other sports; its values are, price for price, the union of Home and Away Player Shots
  (240 and 241: 203/203 and 200/200). A duplicate under an opaque name.
* 213 "Player Triples": filed under other sports; "Name - N" values whose prices match no other market of the samples.
* 275 "Away Player Shots On Target Total": its values are, price for price, the union of the two header-goal markets (228 and
  245: 44/44, 54/54, 42/42). The name and the values disagree.
* 276 "Away Player Shots Total": a player's name, but a team-sized Over/Under (14.5-16.5) with no player in the values.
* 299 "Cards over/under between 0 and 10 m": "Over" and "Under" with no line.
* 61, 224, 225, 298: in the 14-day inventory (cup ties) but in none of the samples: no reader could be validated.

A type the provider sends that is not listed here is not shown either: the book counts it and logs it (``unknown_bets``).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType

BOOK_TAXONOMY_VERSION = "tax-v3"

PERIODS = ("FT", "1H", "2H", "INTERVAL")
SUBJECTS = ("match", "home", "away", "player", "keeper")
FAIR_METHODS = ("shin", "proportional", "none")
READERS = (
    "plain",             # a closed vocabulary: Home / Draw / Away, Yes / No, 1X / 12 / X2, "1st Half", "1 by 2" ...
    "line",              # "Over 9.5", "Exactly 4", "Home 3" (a race): a word and an unsigned line
    "signed_line",       # Asian handicap: "Home -0.25" / "Away -0.25", the home handicap printed on both rows
    "signed_line_3way",  # European handicap: "Home -1" / "Draw -1" / "Away -1", the home handicap of a three-way market
    "exact_score",       # "2:1"
    "ht_ft",             # "Home/Draw": half-time result / full-time result
    "result_total",      # "Draw/Over 3.5": result and total goals
    "total_btts",        # "o/yes 2.5": total goals and both teams to score
    "count",             # 0, 1, 2 ... "more 6": an exact count, the last one "N or more"
    "range",             # "Under 6", "6 - 8", "Over 14", "2 or 3 goals": bands of a count
    "player",            # "Mohamed Salah" (and the outcomes a player market adds, such as "No Goalscorer")
    "player_count",      # "Mohamed Salah - 2": the player reaches at least N (shots, fouls, saves)
)
THREE_WAY = ("never", "always", "when_exactly")
PARLAY_BETS = frozenset({1, 4, 5, 8, 12})
"""The five markets of Mi Parlay (and of the pick pipeline). No other type can be added to a parlay."""

# ── vocabularies: the provider's words (case-folded, spaces collapsed) -> the token the book stores ────────────────────────
# The tokens of the shared words are the ones ``market.odds_snapshots`` and ``market.odds_quotes`` already use, so a price of the
# book can be compared with the extractor's word for word.


def _vocab(pairs: Mapping[str, str]) -> Mapping[str, str]:
    return MappingProxyType(dict(pairs))


HDA = _vocab({"home": "Home", "draw": "Draw", "away": "Away", "1": "Home", "x": "Draw", "2": "Away"})
HA = _vocab({"home": "Home", "away": "Away", "1": "Home", "2": "Away"})
YN = _vocab({"yes": "Yes", "no": "No"})
OE = _vocab({"odd": "Odd", "even": "Even"})
DC = _vocab({"home/draw": "1X", "home/away": "12", "draw/away": "X2", "1x": "1X", "12": "12", "x2": "X2"})
FIRST = _vocab({"home": "Home", "away": "Away", "no goal": "No goal"})
HALF = _vocab({"1st half": "1st Half", "2nd half": "2nd Half", "draw": "Draw"})
RESULT_BTTS = _vocab({f"{r}/{b}": f"{r.title()}/{b.title()}" for r in ("home", "draw", "away") for b in ("yes", "no")})
MARGIN = _vocab({**{f"{t} by {n}": f"{t} by {n}" for t in ("1", "2") for n in ("1", "2", "3", "4+")},
                 "score draw": "Score Draw", "draw": "No goal"})
METHOD = _vocab({"shot": "Shot", "header": "Header", "penalty": "Penalty", "freekick": "FreeKick", "owngoal": "OwnGoal",
                 "draw": "No goal"})
OU = _vocab({"over": "Over", "under": "Under"})
OU3 = _vocab({"over": "Over", "exactly": "Exactly", "under": "Under"})
RACE = _vocab({"home": "Home", "draw": "Draw", "away": "Away"})
EH = _vocab({"home": "Home", "draw": "Draw", "away": "Away"})
SCORER_OUTCOMES = _vocab({"no goalscorer": "No Goalscorer"})


@dataclass(frozen=True, slots=True)
class BookSpec:
    """One bet type of the provider as the book reads it."""

    bet_id: int
    name: str
    """The provider's name. A payload that sends this id under another name is refused for the book, as the extractor does."""
    key: str
    family: str
    period: str
    subject: str
    reader: str
    fair_method: str = "none"
    exhaustive: bool = False
    visible: bool = True
    hidden_reason: str | None = None
    vocabulary: Mapping[str, str] = field(default_factory=lambda: MappingProxyType({}))
    """``plain`` and ``line`` readers: provider word -> token. The ``player`` reader: the outcomes that are not players."""
    outcomes: tuple[str, ...] = ()
    """The tokens of a complete book, in the order they are shown (empty where the outcome set is open or per line)."""
    three_way: str = "never"
    """``line`` reader: whether a line is a three-way market (Over / Exactly / Under)."""
    integer_lines: bool = False
    minutes: tuple[int, int] | None = None
    """INTERVAL period: the minutes it covers (0-10, 0-15 ...)."""
    alias_of: int | None = None
    """Another provider id of the same market (307 is 339): same key, its own rows."""
    note: str | None = None

    @property
    def parlay(self) -> bool:
        return self.bet_id in PARLAY_BETS

    @property
    def market(self) -> str:
        """The key without its period and team: what the explorer's market chips group (``corners.total``)."""
        return ".".join(self.key.split(".")[:2])

    @property
    def has_line(self) -> bool:
        return self.reader in ("line", "signed_line", "signed_line_3way", "result_total", "total_btts", "player_count")

    @property
    def fair(self) -> bool:
        """Whether a fair price may be computed at all (it still needs three complete bookmakers in the answer)."""
        return self.visible and self.exhaustive and self.fair_method != "none"


def _spec(bet_id: int, name: str, key: str, family: str, reader: str, *, period: str = "FT", subject: str = "match",
          fair: str = "none", exhaustive: bool = False, vocabulary: Mapping[str, str] | None = None,
          outcomes: tuple[str, ...] = (), three_way: str = "never", integer_lines: bool = False,
          minutes: tuple[int, int] | None = None, alias_of: int | None = None, note: str | None = None) -> BookSpec:
    return BookSpec(bet_id=bet_id, name=name, key=key, family=family, period=period, subject=subject, reader=reader,
                    fair_method=fair, exhaustive=exhaustive, vocabulary=vocabulary or MappingProxyType({}),
                    outcomes=outcomes, three_way=three_way, integer_lines=integer_lines, minutes=minutes, alias_of=alias_of,
                    note=note)


def _hidden(bet_id: int, name: str, key: str, family: str, reason: str, *, period: str = "FT", subject: str = "match",
            minutes: tuple[int, int] | None = None) -> BookSpec:
    return BookSpec(bet_id=bet_id, name=name, key=key, family=family, period=period, subject=subject, reader="plain",
                    visible=False, hidden_reason=reason, minutes=minutes)


# Short constructors for the shapes that repeat. ``fair`` is set where the outcomes are exclusive and exhaustive.
def _hda(bet_id: int, name: str, key: str, family: str, *, period: str = "FT", minutes: tuple[int, int] | None = None,
         note: str | None = None) -> BookSpec:
    return _spec(bet_id, name, key, family, "plain", vocabulary=HDA, outcomes=("Home", "Draw", "Away"), fair="shin",
                   exhaustive=True, period=period, minutes=minutes, note=note)


def _yn(bet_id: int, name: str, key: str, family: str, *, period: str = "FT", subject: str = "match") -> BookSpec:
    return _spec(bet_id, name, key, family, "plain", vocabulary=YN, outcomes=("Yes", "No"), fair="shin",
                   exhaustive=True, period=period, subject=subject)


def _oe(bet_id: int, name: str, key: str, family: str, *, period: str = "FT", subject: str = "match") -> BookSpec:
    return _spec(bet_id, name, key, family, "plain", vocabulary=OE, outcomes=("Odd", "Even"), fair="shin",
                   exhaustive=True, period=period, subject=subject)


def _dc(bet_id: int, name: str, key: str, family: str, *, period: str = "FT", alias_of: int | None = None,
        note: str | None = None) -> BookSpec:
    """Double chance: each selection covers two outcomes, so a fair book sums to 2; its fair price is computed through the
    1X2 book its three prices imply (``fbi.market.consensus``)."""
    return _spec(bet_id, name, key, family, "plain", vocabulary=DC, outcomes=("1X", "12", "X2"), fair="shin",
                   exhaustive=True, period=period, alias_of=alias_of, note=note)


def _dnb(bet_id: int, name: str, key: str, family: str, *, period: str = "FT") -> BookSpec:
    """Draw no bet: Home / Away, void on a draw - the fair price is conditional on the bet being settled, like an Asian line."""
    return _spec(bet_id, name, key, family, "plain", vocabulary=HA, outcomes=("Home", "Away"), fair="shin",
                   exhaustive=True, period=period)


def _either(bet_id: int, name: str, key: str, family: str, *, note: str | None = None) -> BookSpec:
    """Home / Away where neither can happen too (win to nil, win both halves ...): two one-sided bets, no fair price."""
    return _spec(bet_id, name, key, family, "plain", vocabulary=HA, outcomes=("Home", "Away"), note=note)


def _ou(bet_id: int, name: str, key: str, family: str, *, period: str = "FT", subject: str = "match",
        minutes: tuple[int, int] | None = None, note: str | None = None) -> BookSpec:
    return _spec(bet_id, name, key, family, "line", vocabulary=OU, outcomes=("Over", "Under"), fair="shin",
                   exhaustive=True, period=period, subject=subject, minutes=minutes, note=note)


def _ah(bet_id: int, name: str, key: str, family: str, *, period: str = "FT", note: str | None = None) -> BookSpec:
    return _spec(bet_id, name, key, family, "signed_line", vocabulary=HA, outcomes=("Home", "Away"), fair="shin",
                   exhaustive=True, period=period, note=note)


def _eh(bet_id: int, name: str, key: str, family: str, *, period: str = "FT") -> BookSpec:
    return _spec(bet_id, name, key, family, "signed_line_3way", vocabulary=EH, outcomes=("Home", "Draw", "Away"),
                   fair="shin", exhaustive=True, integer_lines=True, period=period)


def _count(bet_id: int, name: str, key: str, family: str, *, period: str = "FT", subject: str = "match") -> BookSpec:
    """An exact count whose last value is "N or more": the outcome lists differ between bookmakers (0-5 and 6+, 0-6 and 7+), so
    each book is de-vigged in proportion, which keeps every outcome's ratio to its neighbours whatever the cut."""
    return _spec(bet_id, name, key, family, "count", fair="proportional", exhaustive=True, period=period, subject=subject)


def _player(bet_id: int, name: str, key: str, family: str = "players", *,
            vocabulary: Mapping[str, str] | None = None) -> BookSpec:
    return _spec(bet_id, name, key, family, "player", subject="player", vocabulary=vocabulary)


def _player_count(bet_id: int, name: str, key: str, family: str = "players", *, subject: str = "player") -> BookSpec:
    return _spec(bet_id, name, key, family, "player_count", subject=subject)


_NOT_SAMPLED = "in the 14-day inventory but in none of the validation samples: its values were never read"

SPECS: tuple[BookSpec, ...] = (
    # ── result ───────────────────────────────────────────────────────────────────────────────────────────────────────
    _hda(1, "Match Winner", "result.1x2.ft", "result"),
    _dnb(2, "Home/Away", "result.draw_no_bet.ft", "result"),
    _ah(4, "Asian Handicap", "result.asian_handicap.ft", "result"),
    _eh(9, "Handicap Result", "result.european_handicap.ft", "result"),
    _dc(12, "Double Chance", "result.double_chance.ft", "result"),
    _hidden(61, "To Qualify", "advance.to_qualify.ft", "advance", _NOT_SAMPLED),
    # ── goals ────────────────────────────────────────────────────────────────────────────────────────────────────────
    _ou(5, "Goals Over/Under", "goals.total.ft", "goals"),
    _yn(8, "Both Teams Score", "goals.btts.ft", "goals"),
    _spec(10, "Exact Score", "goals.correct_score.ft", "goals", "exact_score",
          note="No 'any other score' value: the listed scores never cover every outcome."),
    _ou(16, "Total - Home", "goals.total.ft.home", "goals", subject="home"),
    _ou(17, "Total - Away", "goals.total.ft.away", "goals", subject="away"),
    _oe(21, "Odd/Even", "goals.odd_even.ft", "goals"),
    _oe(23, "Home Odd/Even", "goals.odd_even.ft.home", "goals", subject="home"),
    _oe(60, "Away Odd/Even", "goals.odd_even.ft.away", "goals", subject="away"),
    _spec(24, "Results/Both Teams Score", "goals.result_btts.ft", "goals", "plain", vocabulary=RESULT_BTTS,
          outcomes=tuple(RESULT_BTTS.values()), fair="shin", exhaustive=True),
    _spec(25, "Result/Total Goals", "goals.result_total.ft", "goals", "result_total", fair="shin", exhaustive=True,
          outcomes=("Home/Over", "Home/Under", "Draw/Over", "Draw/Under", "Away/Over", "Away/Under")),
    _yn(27, "Clean Sheet - Home", "goals.clean_sheet.ft.home", "goals", subject="home"),
    _yn(28, "Clean Sheet - Away", "goals.clean_sheet.ft.away", "goals", subject="away"),
    _yn(29, "Win to Nil - Home", "goals.win_to_nil.ft.home", "goals", subject="home"),
    _yn(30, "Win to Nil - Away", "goals.win_to_nil.ft.away", "goals", subject="away"),
    _either(36, "Win To Nil", "goals.win_to_nil.ft", "goals"),
    _count(38, "Exact Goals Number", "goals.exact_total.ft", "goals"),
    _count(40, "Home Team Exact Goals Number", "goals.exact_total.ft.home", "goals", subject="home"),
    _count(41, "Away Team Exact Goals Number", "goals.exact_total.ft.away", "goals", subject="away"),
    _yn(43, "Home Team Score a Goal", "goals.team_scores.ft.home", "goals", subject="home"),
    _yn(44, "Away Team Score a Goal", "goals.team_scores.ft.away", "goals", subject="away"),
    _spec(47, "Winning Margin", "goals.winning_margin.ft", "goals", "plain", vocabulary=MARGIN,
          outcomes=tuple(dict.fromkeys(MARGIN.values())), fair="shin", exhaustive=True,
          note="'1 by N' is the home team by N, '2 by N' the away team; 'Draw' is read 'No goal' (0-0): its price equals the "
               "0:0 exact score of the same bookmaker in every answer of the samples."),
    _spec(49, "Total Goals/Both Teams To Score", "goals.total_btts.ft", "goals", "total_btts", fair="shin",
          exhaustive=True, outcomes=("Over/Yes", "Over/No", "Under/Yes", "Under/No")),
    _ou(50, "Goal Line", "goals.goal_line.ft", "goals"),
    _yn(110, "Scoring Draw", "goals.score_draw.ft", "goals"),
    _spec(349, "Number Of Goals In Match", "goals.total_bands.ft", "goals", "range", fair="proportional",
          exhaustive=True),
    _spec(14, "Team To Score First", "goals.first_team_to_score.ft", "timing", "plain", vocabulary=FIRST,
          outcomes=("Home", "No goal", "Away"), fair="shin", exhaustive=True),
    _spec(15, "Team To Score Last", "goals.last_team_to_score.ft", "timing", "plain", vocabulary=FIRST,
          outcomes=("Home", "No goal", "Away"), fair="shin", exhaustive=True),
    _spec(185, "First Team to Score (3 way) 1st Half", "goals.first_team_to_score.1h", "timing", "plain",
          vocabulary=FIRST, outcomes=("Home", "No goal", "Away"), fair="shin", exhaustive=True, period="1H"),
    # ── halves ───────────────────────────────────────────────────────────────────────────────────────────────────────
    _hda(3, "Second Half Winner", "result.1x2.2h", "goals_half", period="2H"),
    _ou(6, "Goals Over/Under First Half", "goals.total.1h", "goals_half", period="1H"),
    _spec(7, "HT/FT Double", "halves.ht_ft.ft", "goals_half", "ht_ft", fair="shin", exhaustive=True,
          outcomes=tuple(f"{a}/{b}" for a in ("Home", "Draw", "Away") for b in ("Home", "Draw", "Away"))),
    _spec(11, "Highest Scoring Half", "halves.highest_scoring.ft", "goals_half", "plain", vocabulary=HALF,
          outcomes=("1st Half", "Draw", "2nd Half"), fair="shin", exhaustive=True),
    _hda(13, "First Half Winner", "result.1x2.1h", "goals_half", period="1H"),
    _eh(18, "Handicap Result - First Half", "result.european_handicap.1h", "goals_half", period="1H"),
    _ah(19, "Asian Handicap First Half", "result.asian_handicap.1h", "goals_half", period="1H"),
    _dc(20, "Double Chance - First Half", "result.double_chance.1h", "goals_half", period="1H"),
    _oe(22, "Odd/Even - First Half", "goals.odd_even.1h", "goals_half", period="1H"),
    _ou(26, "Goals Over/Under - Second Half", "goals.total.2h", "goals_half", period="2H"),
    _spec(31, "Correct Score - First Half", "goals.correct_score.1h", "goals_half", "exact_score", period="1H"),
    _either(32, "Win Both Halves", "halves.win_both.ft", "goals_half"),
    _dc(33, "Double Chance - Second Half", "result.double_chance.2h", "goals_half", period="2H"),
    _yn(34, "Both Teams Score - First Half", "goals.btts.1h", "goals_half", period="1H"),
    _yn(35, "Both Teams To Score - Second Half", "goals.btts.2h", "goals_half", period="2H"),
    _yn(37, "Home win both halves", "halves.win_both.ft.home", "goals_half", subject="home"),
    _either(39, "To Win Either Half", "halves.win_either.ft", "goals_half"),
    _count(42, "Second Half Exact Goals Number", "goals.exact_total.2h", "goals_half", period="2H"),
    _count(46, "Exact Goals Number - First Half", "goals.exact_total.1h", "goals_half", period="1H"),
    _either(48, "To Score In Both Halves By Teams", "halves.score_both.ft", "goals_half"),
    _yn(53, "Away win both halves", "halves.win_both.ft.away", "goals_half", subject="away"),
    _spec(62, "Correct Score - Second Half", "goals.correct_score.2h", "goals_half", "exact_score", period="2H"),
    _oe(63, "Odd/Even - Second Half", "goals.odd_even.2h", "goals_half", period="2H"),
    _ou(72, "Goal Line (1st Half)", "goals.goal_line.1h", "goals_half", period="1H"),
    _ah(104, "Asian Handicap (2nd Half)", "result.asian_handicap.2h", "goals_half", period="2H"),
    _ou(105, "Home Team Total Goals(1st Half)", "goals.total.1h.home", "goals_half", period="1H", subject="home"),
    _ou(106, "Away Team Total Goals(1st Half)", "goals.total.1h.away", "goals_half", period="1H", subject="away"),
    _ou(107, "Home Team Total Goals(2nd Half)", "goals.total.2h.home", "goals_half", period="2H", subject="home"),
    _ou(108, "Away Team Total Goals(2nd Half)", "goals.total.2h.away", "goals_half", period="2H", subject="away"),
    _dnb(109, "Draw No Bet (1st Half)", "result.draw_no_bet.1h", "goals_half", period="1H"),
    _yn(111, "Home team will score in both halves", "halves.score_both.ft.home", "goals_half", subject="home"),
    _yn(112, "Away team will score in both halves", "halves.score_both.ft.away", "goals_half", subject="away"),
    _yn(113, "Both Teams To Score in Both Halves", "halves.btts_both.ft", "goals_half"),
    _eh(181, "European Handicap (2nd Half)", "result.european_handicap.2h", "goals_half", period="2H"),
    _dnb(182, "Draw No Bet (2nd Half)", "result.draw_no_bet.2h", "goals_half", period="2H"),
    _yn(184, "To Score in Both Halves", "halves.goal_both.ft", "goals_half"),
    _spec(192, "Home Highest Scoring Half", "halves.highest_scoring.ft.home", "goals_half", "plain", vocabulary=HALF,
          outcomes=("1st Half", "Draw", "2nd Half"), fair="shin", exhaustive=True, subject="home"),
    _spec(193, "Away Highest Scoring Half", "halves.highest_scoring.ft.away", "goals_half", "plain", vocabulary=HALF,
          outcomes=("1st Half", "Draw", "2nd Half"), fair="shin", exhaustive=True, subject="away"),
    _hidden(78, "RTG_H1", "goals.result_total.1h", "goals_half",
            "opaque provider name; the values read as first-half result and total ('Draw/Under 1.5' is priced exactly as the "
            "0:0 half-time score in the four answers that have it) but the provider never says so", period="1H"),
    # ── corners ──────────────────────────────────────────────────────────────────────────────────────────────────────
    _ou(45, "Corners Over Under", "corners.total.ft", "corners"),
    _hda(55, "Corners 1x2", "corners.1x2.ft", "corners"),
    _ah(56, "Corners Asian Handicap", "corners.asian_handicap.ft", "corners",
        note="Home handicap printed on both rows, like bet 4: 81/81 pairs of the samples are believable read that way."),
    _ou(57, "Home Corners Over/Under", "corners.total.ft.home", "corners", subject="home"),
    _ou(58, "Away Corners Over/Under", "corners.total.ft.away", "corners", subject="away"),
    _spec(77, "Total Corners (1st Half)", "corners.total.1h", "corners", "line", vocabulary=OU3, fair="shin",
          exhaustive=True, three_way="when_exactly", period="1H",
          note="A bookmaker that quotes 'Exactly L' prices a three-way line L; the others a two-way Asian line."),
    _spec(85, "Total Corners (3 way)", "corners.total_3way.ft", "corners", "line", vocabulary=OU3, fair="shin",
          exhaustive=True, three_way="always", integer_lines=True),
    _eh(239, "Corners. European Handicap", "corners.european_handicap.ft", "corners"),
    _spec(295, "Corners. Total (Range)", "corners.total_bands.ft", "corners", "range", fair="proportional",
          exhaustive=True),
    _oe(338, "Corners. Odd/Even", "corners.odd_even.ft", "corners"),
    _dc(339, "Corners. Double Chance", "corners.double_chance.ft", "corners"),
    _dc(307, "Corners. Double Chance", "corners.double_chance.ft", "corners", alias_of=339,
        note="Not in the 14-day inventory: the second provider id of 339 (tax-v2 extracts both), read with 339's reader."),
    _ou(249, "Multicorners", "corners.multicorners.ft", "corners",
        note="Bet365's corners of the first half times corners of the second half; tax-v2 files it under specials."),
    _ou(297, "Corners. total between 0 and 10m", "corners.total.m0_10", "timing", period="INTERVAL", minutes=(0, 10)),
    _spec(247, "Corners Race To", "corners.race.ft", "timing", "line", vocabulary=RACE, outcomes=("Home", "Draw", "Away"),
          fair="shin", exhaustive=True, three_way="always", integer_lines=True,
          note="'Home N': the home team reaches N corners first; 'Draw N': neither reaches N."),
    # ── cards ────────────────────────────────────────────────────────────────────────────────────────────────────────
    _ou(80, "Cards Over/Under", "cards.total.ft", "cards"),
    _ah(81, "Cards Asian Handicap", "cards.asian_handicap.ft", "cards",
        note="Home handicap printed on both rows, like bet 4: 16/16 pairs of the samples are believable read that way."),
    _ou(82, "Home Team Total Cards", "cards.total.ft.home", "cards", subject="home"),
    _ou(83, "Away Team Total Cards", "cards.total.ft.away", "cards", subject="away"),
    _eh(79, "Cards European Handicap", "cards.european_handicap.ft", "cards"),
    _hda(250, "First Card Received (3 way)", "cards.first_card.ft", "cards",
         note="'Draw': neither team receives the first card on its own (no card); label it neutrally."),
    _hidden(299, "Cards over/under between 0 and 10 m", "cards.total.m0_10", "cards",
            "'Over' and 'Under' with no line: what is over or under is not said", period="INTERVAL", minutes=(0, 10)),
    # ── team shots ───────────────────────────────────────────────────────────────────────────────────────────────────
    _ou(87, "Total ShotOnGoal", "shots.on_target.ft", "shots"),
    _ou(211, "Total Shots", "shots.total.ft", "shots"),
    _hda(176, "ShotOnTarget 1x2", "shots.on_target_1x2.ft", "shots"),
    _hda(340, "Shots.1x2", "shots.1x2.ft", "shots"),
    # ── offsides, tackles, goalkeepers ───────────────────────────────────────────────────────────────────────────────
    _ou(164, "Offsides Total", "offsides.total.ft", "offsides"),
    _ou(167, "Offsides Home Total", "offsides.total.ft.home", "offsides", subject="home"),
    _ou(168, "Offsides Away Total", "offsides.total.ft.away", "offsides", subject="away"),
    _ou(281, "Total Tackles", "tackles.total.ft", "tackles"),
    _player_count(267, "Goalkeeper Saves", "keeper.saves.ft", "saves", subject="keeper"),
    # ── players ──────────────────────────────────────────────────────────────────────────────────────────────────────
    _player(92, "Anytime Goal Scorer", "player.anytime_scorer.ft"),
    _player(93, "First Goal Scorer", "player.first_scorer.ft", vocabulary=SCORER_OUTCOMES),
    _player(94, "Last Goal Scorer", "player.last_scorer.ft", vocabulary=SCORER_OUTCOMES),
    _player(218, "Away Anytime Goal Scorer", "player.anytime_scorer.ft.away"),
    _player(219, "Away First Goal Scorer", "player.first_scorer.ft.away", vocabulary=SCORER_OUTCOMES),
    _player(226, "Away Last Goal Scorer", "player.last_scorer.ft.away", vocabulary=SCORER_OUTCOMES),
    _player(231, "Home Anytime Goal Scorer", "player.anytime_scorer.ft.home"),
    _player(232, "Home First Goal Scorer", "player.first_scorer.ft.home", vocabulary=SCORER_OUTCOMES),
    _player(233, "Home Last Goal Scorer", "player.last_scorer.ft.home", vocabulary=SCORER_OUTCOMES),
    _player(257, "Player to Score or Assist", "player.score_or_assist.ft"),
    _player_count(240, "Home Player Shots", "player.shots.ft.home"),
    _player_count(241, "Away Player Shots", "player.shots.ft.away"),
    _player_count(266, "Player Fouls Committed", "player.fouls.ft"),
    _player_count(269, "Home Player Shots On Target Total", "player.shots_on_target.ft.home"),
    _player(228, "Home Goal Method Header", "player.header_goal.ft.home", "special"),
    _player(245, "Away Goal Method Header", "player.header_goal.ft.away", "special"),
    _player(229, "Goal Method Outside the Box", "player.outside_box_goal.ft", "special"),
    _hidden(275, "Away Player Shots On Target Total", "player.shots_on_target.ft.away", "players",
            "the values are, price for price, the two header-goal markets 228 and 245 (44/44, 54/54, 42/42): the name and "
            "the values disagree", subject="player"),
    _hidden(276, "Away Player Shots Total", "player.shots_total.ft.away", "players",
            "a player's name but a team-sized Over/Under (14.5-16.5) with no player in the values", subject="player"),
    _hidden(213, "Player Triples", "other.player_triples.ft", "other_sport",
            "filed under other sports; 'Name - N' values whose prices match no other market of the samples",
            subject="player"),
    _hidden(215, "Player Singles", "other.player_singles.ft", "other_sport",
            "filed under other sports; price for price the union of Home and Away Player Shots (240 and 241: 203/203, "
            "200/200), a duplicate under an opaque name", subject="player"),
    # ── specials ─────────────────────────────────────────────────────────────────────────────────────────────────────
    _yn(59, "Own Goal", "special.own_goal.ft", "special"),
    _spec(97, "First Goal Method", "special.first_goal_method.ft", "special", "plain", vocabulary=METHOD,
          outcomes=("Shot", "Header", "Penalty", "FreeKick", "OwnGoal", "No goal"), fair="shin", exhaustive=True,
          note="'Draw' is read 'No goal': its price equals the 0:0 exact score of the same bookmaker in every answer of the "
               "samples."),
    _either(99, "To Score A Penalty", "special.penalty_scored.ft", "special",
            note="tax-v2 files it under players; its values are the teams."),
    _either(100, "To Miss A Penalty", "special.penalty_missed.ft", "special",
            note="tax-v2 files it under players; its values are the teams."),
    _either(222, "To Win From Behind", "special.win_from_behind.ft", "special"),
    _hidden(224, "Game Decided After Penalties", "special.decided_by_penalties.ft", "special", _NOT_SAMPLED),
    _hidden(225, "Game Decided in Extra Time", "special.decided_in_extra_time.ft", "special", _NOT_SAMPLED),
    _hidden(298, "Method of Victory", "special.method_of_victory.ft", "special", _NOT_SAMPLED),
    # ── result at a minute ───────────────────────────────────────────────────────────────────────────────────────────
    _hda(54, "First 10 min Winner", "result.1x2.m0_10", "timing", period="INTERVAL", minutes=(0, 10)),
    _hda(136, "1x2 - 15 minutes", "result.1x2.m0_15", "timing", period="INTERVAL", minutes=(0, 15)),
    _hda(139, "1x2 - 30 minutes", "result.1x2.m0_30", "timing", period="INTERVAL", minutes=(0, 30)),
    _hda(137, "1x2 - 60 minutes", "result.1x2.m0_60", "timing", period="INTERVAL", minutes=(0, 60)),
    _hda(138, "1x2 - 75 minutes", "result.1x2.m0_75", "timing", period="INTERVAL", minutes=(0, 75)),
)

OBSERVED_14D: frozenset[int] = frozenset({
    1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33,
    34, 35, 36, 37, 38, 39, 40, 41, 42, 43, 44, 45, 46, 47, 48, 49, 50, 53, 54, 55, 56, 57, 58, 59, 60, 61, 62, 63, 72, 77, 78,
    79, 80, 81, 82, 83, 85, 87, 92, 93, 94, 97, 99, 100, 104, 105, 106, 107, 108, 109, 110, 111, 112, 113, 136, 137, 138, 139,
    164, 167, 168, 176, 181, 182, 184, 185, 192, 193, 211, 213, 215, 218, 219, 222, 224, 225, 226, 228, 229, 231, 232, 233, 239,
    240, 241, 245, 247, 249, 250, 257, 266, 267, 269, 275, 276, 281, 295, 297, 298, 299, 338, 339, 340, 349,
})
"""The 137 bet ids that arrived in the 14 days of the audit (``fbi_scratch/cuotas_auditoria/inventario_137_tipos_14d.txt``)."""


def _index() -> dict[int, BookSpec]:
    by_id: dict[int, BookSpec] = {}
    keys: dict[str, int] = {}
    for spec in SPECS:
        if spec.bet_id in by_id:
            raise RuntimeError(f"bet {spec.bet_id} is described twice in {BOOK_TAXONOMY_VERSION}")
        held = keys.get(spec.key)
        if held is not None and spec.alias_of != held and by_id[held].alias_of != spec.bet_id:
            raise RuntimeError(f"key {spec.key} is used by bets {held} and {spec.bet_id}")
        keys.setdefault(spec.key, spec.bet_id)
        by_id[spec.bet_id] = spec
    return by_id


_BY_ID = _index()


def book_spec(bet_id: int) -> BookSpec | None:
    """The ``tax-v3`` description of a bet, or None when the provider sends a bet this taxonomy has never seen."""
    return _BY_ID.get(bet_id)


def book_specs() -> tuple[BookSpec, ...]:
    return SPECS


def visible_bet_ids() -> frozenset[int]:
    return frozenset(s.bet_id for s in SPECS if s.visible)
