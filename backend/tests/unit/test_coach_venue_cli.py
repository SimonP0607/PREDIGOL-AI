"""IA-075 / IA-076: the command lines parse, and every command that writes is a dry run unless asked."""

from __future__ import annotations

import pytest
from scripts.coach_current import build_parser as coach_parser
from scripts.venue_geo import build_parser as venue_parser


@pytest.mark.parametrize("argv", [["show", "1", "2"], ["audit"], ["counts"], ["close"], ["close", "--team", "5"],
                                  ["retract", "3", "--note", "n"]])
def test_coach_commands_parse(argv: list[str]) -> None:
    assert coach_parser().parse_args(argv).command == argv[0]


@pytest.mark.parametrize("argv", [["fetch", "--out", "/x.json"], ["load", "--snapshot", "/x", "--sha256", "a"],
                                  ["link"], ["queue", "--kind", "venue_qid"], ["decide", "4", "accept", "--chosen", "7"],
                                  ["retire", "2", "--note", "n"], ["status"]])
def test_venue_commands_parse(argv: list[str]) -> None:
    assert venue_parser().parse_args(argv).command == argv[0]


def test_writing_is_a_dry_run_unless_asked() -> None:
    assert coach_parser().parse_args(["close"]).apply is False
    assert coach_parser().parse_args(["retract", "3", "--note", "n"]).apply is False
    vp = venue_parser()
    for argv in (["load", "--snapshot", "/x", "--sha256", "a"], ["link"], ["decide", "4", "reject"],
                 ["retire", "2", "--note", "n"]):
        assert vp.parse_args(argv).apply is False
    assert vp.parse_args(["load", "--snapshot", "/x", "--sha256", "a"]).dem is False
