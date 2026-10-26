"""The disguises of the battery's attacks, written with code points so that no look-alike letter is typed into a source file (and so that
what disguises a text is independent of the table that undoes it: ``fbi.ai.untrusted``).

Each function takes plain text and returns the same words dressed up: letters of another alphabet that look like ours, the full-width
forms, characters that cannot be seen, text written in the invisible block of «tags»."""

from __future__ import annotations

from typing import Final

CYRILLIC: Final[dict[str, int]] = {"a": 0x0430, "e": 0x0435, "o": 0x043E, "p": 0x0440, "c": 0x0441, "y": 0x0443, "x": 0x0445, "i": 0x0456}
"""Lower-case Latin letters and the Cyrillic letter that looks like each."""
SMALL_CAPS: Final[dict[str, int]] = {
    "a": 0x1D00, "b": 0x0299, "c": 0x1D04, "d": 0x1D05, "e": 0x1D07, "f": 0xA730, "g": 0x0262, "h": 0x029C, "i": 0x026A, "j": 0x1D0A,
    "k": 0x1D0B, "l": 0x029F, "m": 0x1D0D, "n": 0x0274, "o": 0x1D0F, "p": 0x1D18, "r": 0x0280, "s": 0xA731, "t": 0x1D1B, "u": 0x1D1C,
    "v": 0x1D20, "w": 0x1D21, "y": 0x028F, "z": 0x1D22}
ZERO_WIDTH_SPACE: Final = chr(0x200B)
TAG_BASE: Final = 0xE0000


def lookalike(text: str, table: dict[str, int] = CYRILLIC, *, every: int = 2) -> str:
    """Every ``every``-th letter that has a look-alike in ``table`` becomes it: the word is still read the same and is no longer spelled
    with one alphabet (a word that is wholly of the other alphabet is a word of another language, and is not what this does)."""
    eligible = 0
    out: list[str] = []
    for ch in text:
        if ch in table:
            eligible += 1
            if (eligible - 1) % every == 0:
                out.append(chr(table[ch]))
                continue
        out.append(ch)
    return "".join(out)


def fullwidth(text: str) -> str:
    """The printable ASCII of ``text`` in its full-width forms (U+FF01 to U+FF5E), the space in the ideographic space."""
    return "".join(chr(ord(ch) + 0xFEE0) if "!" <= ch <= "~" else chr(0x3000) if ch == " " else ch for ch in text)


def zero_width(text: str) -> str:
    """A zero-width space between every two letters of every word: no filter that looks for the word finds it."""
    return " ".join(ZERO_WIDTH_SPACE.join(word) for word in text.split(" "))


def small_caps(text: str) -> str:
    """The letters that have a small capital in Unicode written as it (a, b, c ... but not q or x)."""
    return "".join(chr(SMALL_CAPS[ch]) if ch in SMALL_CAPS else ch for ch in text)


def tags(text: str) -> str:
    """The ASCII of ``text`` in the invisible block of tag characters (U+E0000 + the code): a line that no reader sees and that a
    program that reads code points can read back (the «ASCII smuggling» of 2024)."""
    return "".join(chr(TAG_BASE + ord(ch)) for ch in text if ord(ch) < 0x80)
