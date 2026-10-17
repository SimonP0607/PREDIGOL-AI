"""Parsing Football-Data.co.uk CSVs.

Column conventions from the source's notes.txt: a bookmaker prefix followed by
H/D/A for 1X2 pre-closing odds, with "C" inserted for closing odds (B365H vs
B365CH); Over/Under 2.5 as "B365>2.5" / "B365C>2.5". Pre-closing odds "for
weekend games are collected Friday afternoons, and on Tuesday afternoons for
midweek games" - there is no timestamp, and none is invented here.
"""

from __future__ import annotations

import csv
import io
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

BASE_URL = "https://www.football-data.co.uk/mmz4281"

# API-Football league id -> Football-Data division code.
DIVISIONS: dict[int, str] = {39: "E0", 140: "SP1", 78: "D1", 135: "I1", 61: "F1", 40: "E1", 88: "N1", 94: "P1"}

# Football-Data prefix -> readable bookmaker code kept in market.historical_odds.
BOOKMAKERS_1X2: dict[str, str] = {
    "B365": "bet365", "BW": "bwin", "IW": "interwetten", "PS": "pinnacle", "WH": "williamhill",
    "VC": "betvictor", "BF": "betfair_sb", "BFE": "betfair_exchange", "1XB": "1xbet",
    "Max": "MAX", "Avg": "AVG",
}
BOOKMAKERS_OU: dict[str, str] = {"B365": "bet365", "P": "pinnacle", "Max": "MAX", "Avg": "AVG", "BFE": "betfair_exchange"}


def season_code(season: int) -> str:
    """2023 (the 2023/24 season, as API-Football labels it) -> '2324'."""
    return f"{season % 100:02d}{(season + 1) % 100:02d}"


def csv_url(division: str, season: int) -> str:
    return f"{BASE_URL}/{season_code(season)}/{division}.csv"


@dataclass(frozen=True, slots=True)
class Price:
    bookmaker_code: str
    market_key: str
    selection: str
    line: Decimal
    price_kind: str  # 'closing' | 'pre_closing'
    odds: Decimal


# Match statistics columns (notes.txt): home/away shots, shots on target,
# corners, fouls committed, yellow and red cards.
STAT_COLUMNS: dict[str, tuple[str, str]] = {
    "shots": ("HS", "AS"),
    "shots_on_target": ("HST", "AST"),
    "corners": ("HC", "AC"),
    "fouls": ("HF", "AF"),
    "yellow_cards": ("HY", "AY"),
    "red_cards": ("HR", "AR"),
}


@dataclass(frozen=True, slots=True)
class FDRow:
    division: str
    match_date: date
    home: str
    away: str
    goals_home: int
    goals_away: int
    prices: tuple[Price, ...] = field(default_factory=tuple)
    home_stats: dict[str, int | None] = field(default_factory=dict, hash=False)
    away_stats: dict[str, int | None] = field(default_factory=dict, hash=False)
    """Only the columns the CSV has; a blank cell is None, never 0."""


def _count(text: str | None) -> int | None:
    if text is None or not text.strip():
        return None
    try:
        v = int(float(text.strip()))
    except ValueError:
        return None
    return v if v >= 0 else None


def decode(raw: bytes) -> str:
    for enc in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    raise ValueError("undecodable CSV")


def _date(text: str) -> date | None:
    for fmt in ("%d/%m/%Y", "%d/%m/%y"):
        try:
            return datetime.strptime(text.strip(), fmt).date()  # noqa: DTZ007 - a calendar date, no time zone
        except ValueError:
            continue
    return None


def _odds(text: str | None) -> Decimal | None:
    if text is None or not text.strip():
        return None
    try:
        d = Decimal(text.strip())
    except InvalidOperation:
        return None
    return d if Decimal("1.001") <= d <= Decimal("999") else None


def parse_csv(text: str) -> tuple[list[FDRow], list[str]]:
    """Rows with a date, both teams and a full-time score; and the reasons any
    row was skipped. A row without a score is skipped, not zero-filled."""
    reader = csv.DictReader(io.StringIO(text))
    rows: list[FDRow] = []
    skipped: list[str] = []
    for i, r in enumerate(reader, start=2):
        if not any((v or "").strip() for v in r.values()):
            continue
        d = _date(r.get("Date") or "")
        home, away = (r.get("HomeTeam") or "").strip(), (r.get("AwayTeam") or "").strip()
        try:
            gh, ga = int(r.get("FTHG") or ""), int(r.get("FTAG") or "")
        except ValueError:
            skipped.append(f"line {i}: no full-time score")
            continue
        if d is None or not home or not away:
            skipped.append(f"line {i}: missing date or team")
            continue
        prices: list[Price] = []
        for prefix, code in BOOKMAKERS_1X2.items():
            for kind, infix in (("pre_closing", ""), ("closing", "C")):
                trio = [_odds(r.get(f"{prefix}{infix}{s}")) for s in ("H", "D", "A")]
                if all(t is not None for t in trio):
                    for sel, val in zip(("Home", "Draw", "Away"), trio, strict=True):
                        assert val is not None
                        prices.append(Price(code, "1X2", sel, Decimal("0"), kind, val))
        for prefix, code in BOOKMAKERS_OU.items():
            for kind, infix in (("pre_closing", ""), ("closing", "C")):
                over, under = _odds(r.get(f"{prefix}{infix}>2.5")), _odds(r.get(f"{prefix}{infix}<2.5"))
                if over is not None and under is not None:
                    prices.append(Price(code, "OU", "Over", Decimal("2.5"), kind, over))
                    prices.append(Price(code, "OU", "Under", Decimal("2.5"), kind, under))
        home_stats = {k: _count(r.get(h)) for k, (h, _) in STAT_COLUMNS.items() if h in r}
        away_stats = {k: _count(r.get(a)) for k, (_, a) in STAT_COLUMNS.items() if a in r}
        rows.append(FDRow((r.get("Div") or "").strip(), d, home, away, gh, ga, tuple(prices), home_stats,
                          away_stats))
    return rows, skipped
