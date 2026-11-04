"""What Mis picks can be narrowed by (plan UX, B5, section 30): the result, the kind of bet, the league, the odds range, who
chose the selection (PrediGol or the reader) and the days its match is played - and a search of the teams and the league.

One filter for the list, its totals, its breakdown and its CSV (``fbi.api.services.records`` and ``.mypicks``): the four
always count exactly the same records of the same reader. The SQL is a fragment of conditions over a reader's saved picks
``u`` joined to the match ``f``, its teams ``th`` / ``ta`` and its competition ``c``; every value travels as a parameter.

The odds range is the price the reader counts - their own when they gave one, else the price shown when they saved it -,
the same price the recap and the history count (``fbi.userdata.records``); a record without any price is in no range. The
days are the reader's own (their time zone), as every list of Mis picks cuts them.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, fields
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from typing import Final, Literal, get_args
from zoneinfo import ZoneInfo

Result = Literal["pending", "won", "lost", "push", "void"]
Origin = Literal["predigol", "mine"]
Band = Literal["lt1.5", "1.5-2", "2-3", "3-5", "5+"]

RESULT_STATUSES: Final[dict[str, tuple[str, ...]]] = {
    "pending": ("PENDING",), "won": ("WIN", "HALF_WIN"), "lost": ("LOSS", "HALF_LOSS"), "push": ("PUSH",),
    "void": ("VOID",)}
"""A result as the reader picks it, and the settlement statuses it stands for (a half win is won, a half loss is lost, as in
every count of Mis picks)."""
ORIGINS: Final[dict[str, str]] = {"predigol": "predigol_pick", "mine": "market"}
BANDS: Final[dict[str, tuple[Decimal, Decimal | None]]] = {
    "lt1.5": (Decimal("1"), Decimal("1.5")), "1.5-2": (Decimal("1.5"), Decimal("2")), "2-3": (Decimal("2"), Decimal("3")),
    "3-5": (Decimal("3"), Decimal("5")), "5+": (Decimal("5"), None)}
"""The odds ranges, from (included) to (excluded): the recap's own (web ``recapData.ODDS_BUCKETS``)."""
BAND_ORDER: Final[tuple[Band, ...]] = get_args(Band)
MARKETS: Final = frozenset({"1X2", "OU", "BTTS", "AH", "DC"})
"""The kinds of bet a reader can save (``fbi.api.contracts.records.LegInBody``)."""
SEARCH_MAX: Final = 60
SPAN_MAX_DAYS: Final = 3660
"""The widest span of days a filter accepts (ten years): anything a reader has saved fits in it."""

ACCENTED: Final = "áéíóúüñàèìòùâêîôûãõçÁÉÍÓÚÜÑÀÈÌÒÙÂÊÎÔÛÃÕÇ"
PLAIN: Final = "aeiouunaeiouaeiouaocaeiouunaeiouaeiouaoc"
"""A search finds «Medellín» from «medellin» (plan UX: searches without accents): both sides are compared in lower case with
these letters made plain. The capitals are in the list too: a database whose ``lower()`` leaves them as they are (the C
collation lowers only ASCII) still compares them plain."""


class FilterError(ValueError):
    """A filter the list cannot apply: the message says which part."""


def plain(text: str) -> str:
    """Lower case, the accents of ACCENTED made plain and the spaces collapsed: how a search and a name are compared."""
    lowered = " ".join(text.lower().split())
    return lowered.translate(str.maketrans(ACCENTED, PLAIN))


def like_pattern(text: str) -> str:
    """A LIKE pattern that finds ``text`` anywhere, with ``%``, ``_`` and the escape character taken literally."""
    return "%" + re.sub(r"([\\%_])", r"\\\1", plain(text)) + "%"


@dataclass(frozen=True)
class PickFilter:
    result: Result | None = None
    market: str | None = None
    competition: int | None = None
    origin: Origin | None = None
    band: Band | None = None
    since: date | None = None
    until: date | None = None
    search: str | None = None

    def __post_init__(self) -> None:
        if self.result is not None and self.result not in RESULT_STATUSES:
            raise FilterError("result: one of " + ", ".join(RESULT_STATUSES))
        if self.market is not None and self.market not in MARKETS:
            raise FilterError("market: one of " + ", ".join(sorted(MARKETS)))
        if self.competition is not None and self.competition < 1:
            raise FilterError("competition: a competition's id")
        if self.origin is not None and self.origin not in ORIGINS:
            raise FilterError("origin: predigol or mine")
        if self.band is not None and self.band not in BANDS:
            raise FilterError("band: one of " + ", ".join(BAND_ORDER))
        if self.since is not None and self.until is not None:
            if self.since > self.until:
                raise FilterError("since: on or before until")
            if (self.until - self.since).days > SPAN_MAX_DAYS:
                raise FilterError(f"since..until: at most {SPAN_MAX_DAYS} days")
        if self.search is not None and (not self.search.strip() or len(self.search) > SEARCH_MAX):
            raise FilterError(f"search: 1 to {SEARCH_MAX} characters")

    @classmethod
    def of(cls, *, result: str | None = None, market: str | None = None, competition: int | None = None,
           origin: str | None = None, band: str | None = None, since: date | None = None, until: date | None = None,
           search: str | None = None) -> PickFilter:
        """From a request's query: an empty search is no search."""
        text = (search or "").strip() or None
        return cls(result=result, market=market, competition=competition, origin=origin, band=band,  # type: ignore[arg-type]
                   since=since, until=until, search=text)

    @property
    def active(self) -> int:
        """How many parts are set (the «Filtros» button says it)."""
        return sum(1 for f in fields(self) if getattr(self, f.name) is not None)

    def params(self, tz: str) -> dict[str, object]:
        """The values of SQL, for a reader in time zone ``tz``."""
        zone = ZoneInfo(tz)
        low, high = BANDS[self.band] if self.band is not None else (None, None)
        return {
            "f_statuses": list(RESULT_STATUSES[self.result]) if self.result is not None else None,
            "f_market": self.market,
            "f_competition": self.competition,
            "f_origin": ORIGINS[self.origin] if self.origin is not None else None,
            "f_odds_min": low,
            "f_odds_max": high,
            "f_from": datetime.combine(self.since, time(), zone) if self.since is not None else None,
            "f_to": datetime.combine(self.until + timedelta(days=1), time(), zone) if self.until is not None else None,
            "f_search": like_pattern(self.search) if self.search is not None else None,
            "f_accented": ACCENTED,
            "f_plain": PLAIN,
        }


NONE: Final = PickFilter()

SQL: Final = r"""
   AND (%(f_statuses)s::text[] IS NULL OR u.status = ANY(%(f_statuses)s::text[]))
   AND (%(f_market)s::text IS NULL OR u.market_key = %(f_market)s::text)
   AND (%(f_competition)s::bigint IS NULL OR c.id = %(f_competition)s::bigint)
   AND (%(f_origin)s::text IS NULL OR u.origin = %(f_origin)s::text)
   AND (%(f_odds_min)s::numeric IS NULL OR COALESCE(u.user_odds, u.odds) >= %(f_odds_min)s::numeric)
   AND (%(f_odds_max)s::numeric IS NULL OR COALESCE(u.user_odds, u.odds) < %(f_odds_max)s::numeric)
   AND (%(f_from)s::timestamptz IS NULL OR f.kickoff_at >= %(f_from)s::timestamptz)
   AND (%(f_to)s::timestamptz IS NULL OR f.kickoff_at < %(f_to)s::timestamptz)
   AND (%(f_search)s::text IS NULL
        OR translate(lower(th.name || ' ' || ta.name || ' ' || c.name), %(f_accented)s::text, %(f_plain)s::text)
           LIKE %(f_search)s::text ESCAPE '\')
"""
"""The conditions, after ``WHERE u.user_id = ...``: a reader's saved picks ``u``, the match ``f``, its teams ``th`` and ``ta``
and its competition ``c``."""

JOINS: Final = """
  JOIN core.fixtures f ON f.id = u.fixture_id
  JOIN core.teams th ON th.id = f.home_team_id
  JOIN core.teams ta ON ta.id = f.away_team_id
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
"""
"""What SQL needs joined to a reader's saved picks ``u`` when nothing else of the match is read."""

CLOSE_JOIN: Final = """
  LEFT JOIN LATERAL (
      SELECT m.p_fair, m.as_of FROM market.market_consensus m
       WHERE m.fixture_id = u.fixture_id AND m.market_key = u.market_key AND m.selection = u.selection
         AND m.line = u.line AND m.devig_method = 'shin' AND m.as_of < f.kickoff_at AND f.kickoff_at <= %(now)s
       ORDER BY m.as_of DESC LIMIT 1) pc ON true
"""
"""The reference a saved pick's price is set against once its match has started (``clv-v1``, ``fbi.market.closing_value``):
the de-vigged (Shin) consensus of the last capture before kick-off - ``pc.p_fair``, ``pc.as_of``. Before kick-off there is
none: the close is not known yet."""
