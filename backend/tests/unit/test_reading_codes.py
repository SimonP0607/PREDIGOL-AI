"""The structured reading's codes (plan UX, A9): every code the API can send is one the web has a template for, and the other
way round - ``web/src/product/reading/codes.json`` is the list both sides are held to (the web's own test holds its templates
to it). A code the web does not know is left out on the page; this test makes sure none is."""

from __future__ import annotations

import ast
import json
from pathlib import Path

from fbi.api.services import reading

WEB_CODES = Path(__file__).resolve().parents[3] / "web" / "src" / "product" / "reading" / "codes.json"


def emitted() -> list[str]:
    """The codes ``fbi.api.services.reading`` adds (``r.add(<section>, <code>, ...)``), in source order."""
    tree = ast.parse(Path(reading.__file__).read_text(encoding="utf-8"))
    codes: list[str] = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == "add"
                and len(node.args) >= 2):
            continue
        first, second = node.args[0], node.args[1]
        if isinstance(first, ast.Constant) and isinstance(second, ast.Constant):
            assert first.value in reading.SECTIONS, first.value
            if second.value not in codes:
                codes.append(str(second.value))
    return codes


def test_the_api_and_the_web_know_the_same_codes() -> None:
    assert WEB_CODES.is_file(), "the web's list of the reading's codes"
    web = json.loads(WEB_CODES.read_text(encoding="utf-8"))
    assert sorted(emitted()) == sorted(web)
    assert len(web) == len(set(web))


def test_every_code_is_a_plain_name() -> None:
    assert all(code.isidentifier() and code == code.lower() for code in emitted())
