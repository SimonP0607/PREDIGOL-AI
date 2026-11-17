"""The player markets in private evaluation (IA-130, AD-E04), without a database: the prices of a player's shots and shots on target are
read from an answer with ``tax-v3``'s readers and the hidden types stay out; «una sola casa» is marked; a name is matched to one man of
the sheet or to none; the rule settles every case of minutes (a man who does not play is void, a missing figure is nothing, never a
loss); the families are off while E3 is not reliable, and no selection is ever confirmed without the official line-up or on fewer than
three houses; nothing that decides, publishes or serves imports the package."""

from __future__ import annotations

import ast
import itertools
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from fbi.picks.settlement import Status
from fbi.playermarkets import admission, lab, quotes, settle

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "fbi"
KO = datetime(2026, 11, 10, 20, tzinfo=UTC)


def bet(bet_id: int, name: str, values: list[tuple[str, str]]) -> dict[str, Any]:
    return {"id": bet_id, "name": name, "values": [{"value": v, "odd": o} for v, o in values]}


def answer(*books: tuple[int, list[dict[str, Any]]]) -> dict[str, Any]:
    return {"bookmakers": [{"id": b, "name": f"book {b}", "bets": bets} for b, bets in books]}


HOME_SHOTS = bet(240, "Home Player Shots", [("Mohamed Salah - 1", "1.20"), ("Mohamed Salah - 2", "1.80"), ("Cody Gakpo - 1", "1.50")])
AWAY_SHOTS = bet(241, "Away Player Shots", [("Bukayo Saka - 1", "1.30")])
HOME_ON = bet(269, "Home Player Shots On Target Total", [("Mohamed Salah - 1", "1.70")])
AWAY_ON = bet(275, "Away Player Shots On Target Total", [("Bukayo Saka", "6.00")])


def test_the_prices_are_read_by_player_and_line_and_the_hidden_types_stay_out() -> None:
    got = quotes.read(answer((8, [HOME_SHOTS, AWAY_SHOTS, HOME_ON, AWAY_ON]), (11, [bet(240, "Home Player Shots",
                                                                                       [("Mohamed Salah - 1", "1.22")])])))
    by = {(q.family, q.side, q.name, q.at_least): q for q in got.quotes}
    salah = by[("player_shots", "home", "Mohamed Salah", 1)]
    assert salah.books == 2 and not salah.single_house and salah.best == Decimal("1.22") and salah.line == Decimal("0.5")
    assert by[("player_shots", "home", "Mohamed Salah", 2)].line == Decimal("1.5")
    assert by[("player_shots", "home", "Mohamed Salah", 2)].single_house
    assert ("player_shots_on", "home", "Mohamed Salah", 1) in by and ("player_shots", "away", "Bukayo Saka", 1) in by
    assert not any(q.family == "player_shots_on" and q.side == "away" for q in got.quotes), "275 is hidden by the taxonomy"
    assert 275 in got.hidden and got.bookmakers == 2


def test_a_renamed_bet_is_not_read() -> None:
    got = quotes.read(answer((8, [bet(240, "Home Player Tackles", [("Mohamed Salah - 1", "1.20")])])))
    assert not got.quotes and 240 in got.hidden


def test_a_name_is_matched_to_one_man_of_the_sheet_or_to_none() -> None:
    sheet = [(306, "M. Salah"), (1100, "C. Gakpo"), (7, "Alisson Becker"), (8, "Ibrahima Konaté"), (9, "Ibrahima Konate")]
    assert quotes.resolve("Mohamed Salah", sheet) == 306
    assert quotes.resolve("Cody Gakpo", sheet) == 1100
    assert quotes.resolve("Alisson", sheet) is None, "a first name alone is a doubt (IA-071), counted unresolved"
    assert quotes.resolve("Ibrahima Konaté", [(8, "Ibrahima Konaté"), (9, "Ibrahima Konaté")]) is None, "two men fit: not guessed"
    assert quotes.resolve("Virgil van Dijk", sheet) is None


def outcome(*, at_least: int = 1, status: str = "FT", at: datetime = KO + timedelta(hours=3), has_stats: bool = True,
            line: settle.PlayerLine | None) -> settle.Outcome:
    return settle.settle(at_least=at_least, match_status=status, kickoff_at=KO, at=at, has_stats=has_stats, line=line)


def test_the_rule_settles_every_case_of_minutes() -> None:
    assert outcome(line=settle.PlayerLine(True, 90, 2)) == settle.Outcome(Status.WIN, settle.SETTLED)
    assert outcome(at_least=3, line=settle.PlayerLine(True, 90, 2)).status == Status.LOSS
    assert outcome(line=settle.PlayerLine(True, 1, 1)).status == Status.WIN, "one minute is playing"
    assert outcome(line=settle.PlayerLine(True, 12, 0)).status == Status.LOSS, "from the bench he plays: it settles"
    assert outcome(line=settle.PlayerLine(True, 0, 0)) == settle.Outcome(Status.VOID, settle.NOT_PLAYED)
    assert outcome(line=settle.PlayerLine(True, None, None)).status == Status.VOID
    assert outcome(line=None) == settle.Outcome(Status.VOID, settle.NOT_PLAYED)
    assert outcome(line=settle.PlayerLine(True, 70, None)) == settle.Outcome(None, settle.NO_FIGURE), "a missing figure is no loss"
    assert outcome(has_stats=False, line=None) == settle.Outcome(None, settle.NO_STATS)
    assert outcome(status="AET", line=settle.PlayerLine(True, 120, 3)) == settle.Outcome(None, settle.EXTRA)
    assert outcome(status="CANC", line=None) == settle.Outcome(Status.VOID, settle.MATCH_VOID)
    assert outcome(status="PST", line=None) == settle.Outcome(None, settle.WAITING)
    assert outcome(status="PST", at=KO + timedelta(hours=73), line=None).status == Status.VOID


def test_the_families_are_off_while_e3_is_not_reliable() -> None:
    from fbi.api.services.market_status import LINEUP_EVALUATION_RELIABLE

    assert admission.E3_RELIABLE is LINEUP_EVALUATION_RELIABLE is False
    assert admission.mode({}) == "off"
    assert admission.mode({admission.SWITCH: "shadow"}) == "off", "the switch alone opens nothing"
    assert admission.mode({admission.SWITCH: "shadow"}, e3_reliable=True) == "shadow"
    assert admission.mode({admission.SWITCH: "on"}, e3_reliable=True) == "off"
    f = admission.Facts("player_shots", True, 5, official_lineup=True, starts=True, kicked_off=False)
    assert admission.state(f, mode_now=admission.mode({})) == admission.OFF


def test_no_selection_is_ever_confirmed_without_the_official_line_up_nor_on_fewer_than_three_houses() -> None:
    seen: set[str] = set()
    for family, res, books, official, starts, kicked in itertools.product(
            ("player_shots", "player_shots_on", "player_goals"), (True, False), range(5), (True, False), (True, False, None),
            (True, False)):
        f = admission.Facts(family, res, books, official_lineup=official, starts=starts if official else None, kicked_off=kicked)
        s = admission.state(f, mode_now="shadow")
        seen.add(s)
        assert s in admission.STATES
        if s == admission.EVALUABLE:
            assert official and starts and books >= quotes.MIN_BOOKS and res and family in settle.STATS
        if not official:
            assert s != admission.EVALUABLE and (s in (admission.WAITING, admission.DISCARDED) or s in (
                admission.NO_RULE, admission.UNRESOLVED, admission.NO_PRICE))
        if official and starts and res and family in settle.STATS and books == 1:
            assert s == admission.SINGLE
    assert seen == set(admission.STATES) - {admission.OFF}


def test_the_lab_tallies_prices_houses_names_settlement_and_states() -> None:
    t = lab.Tally()
    sheet = {"home": [(306, "M. Salah", True), (1100, "C. Gakpo", False)], "away": [(22, "B. Saka", True)]}
    stats = {306: ("home", 90, 3, 1), 1100: ("home", 0, None, None), 22: ("away", 80, 0, 0)}
    lab.tally(t, answer((8, [HOME_SHOTS, AWAY_SHOTS, HOME_ON, AWAY_ON])), sheet=sheet, stats=stats, status="FT", kickoff_at=KO,
              at=KO + timedelta(days=1))
    doc = t.as_json()
    assert doc["fixtures"] == 1 and doc["fixtures_with_player_shot_prices"] == 1
    assert doc["selections"] == 5 and doc["single_house"] == 5 and doc["single_house_share"] == 1.0
    assert doc["names_resolved"] == 5 and doc["names_unresolved"] == 0
    assert doc["settlement"] == {"loss": 1, "void": 1, "win": 3}
    assert doc["states_if_on"] == {admission.NOT_PLAYING: 1, admission.SINGLE: 4} and doc["evaluable"] == 0
    assert doc["gate"] == {"e3_reliable": False, "mode": "off"} and doc["rule"] == "player_count_ft@v1"


def _imports(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            found.add(node.module)
    return found


def test_nothing_that_decides_publishes_or_serves_imports_the_player_markets() -> None:
    files = [p for root in (SRC, ROOT / "apps", ROOT / "scripts") for p in root.rglob("*.py") if "__pycache__" not in p.parts]
    importers = {p.relative_to(ROOT).as_posix() for p in files if "playermarkets" not in p.parts
                 and any(n == "fbi.playermarkets" or n.startswith("fbi.playermarkets.") for n in _imports(p))}
    assert importers == {"scripts/ia_player_markets.py"}, importers
    for p in (SRC / "playermarkets").glob("*.py"):
        assert not {n for n in _imports(p) if n.startswith(("fbi.decision", "fbi.intel", "fbi.api", "fbi.ai", "fbi.notify",
                                                                "fbi.parlays", "fbi.models"))}, p.name
