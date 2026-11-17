"""IA-071: the command line of ``scripts.entity_identity`` - every command parses, writing ones are dry runs by default."""

from __future__ import annotations

from pathlib import Path

import pytest
from scripts.entity_identity import build_parser


@pytest.mark.parametrize("argv", [
    ["fetch", "--dir", "/x"], ["verify", "--dir", "/x"], ["load", "--dir", "/x"], ["sync-core"], ["player-keys"],
    ["status"], ["audit"], ["queue", "--kind", "name_mismatch"], ["decide", "3", "accept"],
    ["link", "player", "1", "reep", "", "rp_x", "reject"], ["undo", "--queue", "3"], ["retire", "4", "--note", "bad"],
])
def test_every_command_parses(argv: list[str]) -> None:
    assert build_parser().parse_args(argv).command == argv[0]


def test_writing_is_a_dry_run_unless_asked() -> None:
    p = build_parser()
    for argv in (["load", "--dir", "/x"], ["sync-core"], ["player-keys"], ["decide", "3", "accept"],
                 ["retire", "4", "--note", "n"]):
        assert p.parse_args(argv).apply is False
    assert p.parse_args(["load", "--dir", "/x"]).dir == Path("/x")
    assert p.parse_args(["load", "--dir", "/x"]).release == "2026-10-19.1"
