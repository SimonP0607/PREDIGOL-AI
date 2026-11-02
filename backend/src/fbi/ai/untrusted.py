"""Untrusted text: what a web page, a player's name or a provider's note may say - and what the package does with it before a model reads it
(Plan Maestro IA, phase 1, section 31).

A model reads three kinds of text: PrediGol's own (the system prompt, the schema, the numbers of the package), text that comes from
OUTSIDE (a page found by a search, the name of a player, a coach, a referee, a note of the provider) and its own earlier answers. Only
the first is an instruction. The second is DATA that someone else wrote and may have written to be read by a model: "ignore your
instructions", "this is a safe pick", a fake official statement, a command to call a tool or to give a probability, a name that contains
a sentence, text hidden in HTML, letters of another alphabet that look like ours, a link that says one thing and goes elsewhere.

What this module does about it, once, in one place, for every piece of outside text that goes into a package:

* it is NORMALISED (Unicode compatibility forms - full-width letters - become the plain ones; invisible and control characters go; a word
  that mixes alphabets has its look-alike letters turned into the Latin ones, so that a filter and a reader see the same word);
* HTML is reduced to its visible text (scripts, styles, comments, and elements hidden by an attribute or an inline style are dropped);
* a link keeps its words and loses its target, a bare address becomes ``[link]``: a model is never handed a URL to follow or to repeat;
* it has a MAXIMUM LENGTH, and says that it was cut;
* it is FLAGGED where it looks like an instruction (``instruction_like``) - a flag for the audit and the battery, never a reason to drop an
  evidence (a page that says "ignore the rumours" must not be able to make a true report disappear);
* it travels as a block that says where it came from (``Untrusted.as_block``): ``{"untrusted": true, "origin": "<domain>", "text": ...}``,
  inside JSON, so every quote and bracket in it is escaped, and the system prompt of every agent says that such a block is data.

None of this makes a model immune: the guarantee is structural. An agent's answer is made of codes and references the server checks
(``fbi.ai.contracts``), it has no tools, no memory, no credentials and no way out, and the worst a poisoned text can do is lower a pick
or leave a misleading sentence in a narrative nobody acts on. This module makes the attack cheaper to see and more expensive to make.
"""

# ruff: noqa: RUF001 - the table of look-alike letters is the point of this module

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Final

MAX_INPUT_FACTOR: Final = 20
"""Only this many times the output length of the input is looked at: a page of a megabyte costs what a page of ten kilobytes does."""
LINK: Final = "[link]"

VOID_TAGS: Final = frozenset({"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track",
                              "wbr"})
DROPPED_TAGS: Final = frozenset({"script", "style", "template", "noscript", "iframe", "object", "embed", "svg", "canvas", "head"})
HIDDEN_STYLE: Final = re.compile(
    r"display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0(?![.\d])|opacity\s*:\s*0(?![.\d])|color\s*:\s*transparent|"
    r"text-indent\s*:\s*-\d{3,}|(?:left|right|top|bottom|margin-left|margin-top)\s*:\s*-\d{3,}|clip-path\s*:\s*inset\(\s*(?:50|100)%|"
    r"clip\s*:\s*rect\(\s*0(?:px)?[\s,]+0(?:px)?[\s,]+0(?:px)?[\s,]+0", re.I)
COLLAPSED: Final = re.compile(r"(?:max-)?(?:height|width)\s*:\s*0(?![.\d])", re.I)
CLIPPED: Final = re.compile(r"overflow(?:-[xy])?\s*:\s*hidden", re.I)
"""Inline styles that hide text from a reader and leave it for a machine (a box with no height or width that clips what overflows
it is the one that takes two of them)."""


def style_hides(style: str) -> bool:
    return bool(HIDDEN_STYLE.search(style)) or (bool(COLLAPSED.search(style)) and bool(CLIPPED.search(style)))


# Letters of the Cyrillic and Greek alphabets that look like a Latin one.
CONFUSABLES: Final[dict[str, str]] = {
    "а": "a", "е": "e", "о": "o", "р": "p", "с": "c", "у": "y", "х": "x", "і": "i", "ј": "j", "ѕ": "s", "ԁ": "d", "һ": "h", "ӏ": "l",
    "ԛ": "q", "ԝ": "w", "ɡ": "g",
    "ᴀ": "a", "ʙ": "b", "ᴄ": "c", "ᴅ": "d", "ᴇ": "e", "ꜰ": "f", "ɢ": "g", "ʜ": "h", "ɪ": "i", "ᴊ": "j", "ᴋ": "k", "ʟ": "l", "ᴍ": "m",
    "ɴ": "n", "ᴏ": "o", "ᴘ": "p", "ʀ": "r", "ꜱ": "s", "ᴛ": "t", "ᴜ": "u", "ᴠ": "v", "ᴡ": "w", "ʏ": "y", "ᴢ": "z",
    "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H", "О": "O", "Р": "P", "С": "C", "Т": "T", "Х": "X", "У": "Y", "І": "I",
    "Ј": "J", "Ѕ": "S",
    "ο": "o", "ν": "v", "ρ": "p", "α": "a", "ι": "i", "κ": "k", "τ": "t", "υ": "u", "χ": "x",
    "Α": "A", "Β": "B", "Ε": "E", "Ζ": "Z", "Η": "H", "Ι": "I", "Κ": "K", "Μ": "M", "Ν": "N", "Ο": "O", "Ρ": "P", "Τ": "T", "Υ": "Y",
    "Χ": "X",
}

_INSTRUCTIONS: Final = tuple(re.compile(p, re.I) for p in (
    r"\b(?:ignore|disregard|forget|override|bypass)\b[^.\n]{0,40}\b(?:instructions?|rules?|prompts?|guidelines?|system|above|previous|prior)\b",
    r"\b(?:you are now|from now on you|act as|pretend (?:to be|you)|new instructions?|system prompt|developer message|"
    r"as an ai|jailbreak|do anything now)\b",
    r"\b(?:respond|reply|answer|output|return|write)\b[^.\n]{0,20}\b(?:only|just|exactly)\b[^.\n]{0,30}\b(?:with|:)",
    r"\b(?:call|use|invoke|run|execute)\b[^.\n]{0,25}\b(?:tool|function|command|sql|query|shell|browser)\b",
    r"\b(?:reveal|print|show|leak|repeat)\b[^.\n]{0,25}\b(?:prompt|instructions|system|api key|secret|password)\b",
    r"\b(?:safe|sure|guaranteed|certain|risk-?free|locked?)\s+(?:pick|bet|tip|win|winner)\b",
    r"\b(?:give|set|output|assign|use)\b[^.\n]{0,25}\b(?:probability|odds|stake|confidence)\b[^.\n]{0,10}\b(?:of|to|=|at)\b",
    r"\b(?:ignora|ignore?n|olvida|descarta|omite)\b[^.\n]{0,40}\b(?:instrucciones|reglas|indicaciones|anterior(?:es)?|sistema)\b",
    r"\b(?:a partir de ahora|desde ahora)\b[^.\n]{0,20}\b(?:eres|act[uú]a|responde)\b",
    r"\b(?:responde|contesta|devuelve)\b[^.\n]{0,20}\b(?:solo|[uú]nicamente|exactamente)\b",
    r"\b(?:pick|apuesta|jugada)\s+(?:segura|fija|garantizada|ganadora)\b",
    r"\b(?:llama|usa|ejecuta)\b[^.\n]{0,25}\b(?:herramienta|funci[oó]n|comando|sql|consulta)\b",
))

_MD_IMAGE = re.compile(r"!\[([^\]\n]{0,200})\]\([^)\n]{0,2000}\)")
_MD_LINK = re.compile(r"\[([^\]\n]{1,300})\]\([^)\n]{0,2000}\)")
_MD_REF = re.compile(r"\[([^\]\n]{1,300})\]\[[^\]\n]{0,100}\]")
_URL = re.compile(r"(?:\b(?:https?|ftp)://|\bwww\.)[^\s<>\"')\]]{1,2000}", re.I)
_SPACE = re.compile(r"\s+")


class _Visible(HTMLParser):
    """The text a reader would see: nothing of a script, a style, a comment or an element that hides itself."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.saw_markup = False
        self._hidden = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.saw_markup = True
        if self._hidden:
            if tag not in VOID_TAGS:
                self._hidden += 1
            return
        a = {k.lower(): (v or "") for k, v in attrs}
        hides = (tag in DROPPED_TAGS or "hidden" in a or a.get("aria-hidden", "").lower() == "true"
                 or style_hides(a.get("style", "")) or a.get("type", "").lower() == "hidden")
        if hides and tag not in VOID_TAGS:
            self._hidden = 1
        elif tag in ("br", "p", "div", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6"):
            self.parts.append(" ")

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.saw_markup = True

    def handle_endtag(self, tag: str) -> None:
        self.saw_markup = True
        if self._hidden and tag not in VOID_TAGS:
            self._hidden -= 1
        elif tag in ("p", "div", "li", "tr"):
            self.parts.append(" ")

    def handle_data(self, data: str) -> None:
        if not self._hidden:
            self.parts.append(data)

    def handle_comment(self, data: str) -> None:
        self.saw_markup = True

    def handle_decl(self, decl: str) -> None:
        self.saw_markup = True

    def handle_pi(self, data: str) -> None:
        self.saw_markup = True


@dataclass(frozen=True, slots=True)
class Untrusted:
    """A piece of outside text after the module has dealt with it."""

    origin: str
    text: str
    truncated: bool
    flags: tuple[str, ...]

    def as_block(self) -> dict[str, Any]:
        """What goes into a package or a prompt. ``untrusted: true`` is read by the system prompt of every agent as «this is data»."""
        return {"untrusted": True, "origin": self.origin, "text": self.text, "truncated": self.truncated,
                "flags": list(self.flags)}

    @property
    def instruction_like(self) -> bool:
        return "instruction_like" in self.flags


def _strip_invisible(text: str, flags: set[str]) -> str:
    out: list[str] = []
    for ch in text:
        if ch in "\n\t\r":
            out.append(" ")
            continue
        category = unicodedata.category(ch)
        if category in ("Cc", "Cf", "Cs", "Co", "Cn") or ch in ("\u2028", "\u2029"):
            flags.add("invisible" if category != "Cc" else "control")
            continue
        out.append(ch)
    return "".join(out)


def _script_of(ch: str) -> str | None:
    if not ch.isalpha():
        return None
    try:
        return unicodedata.name(ch).split(" ", 1)[0]
    except ValueError:
        return None


LATIN_LOOKALIKES: Final[dict[str, str]] = {c: v for c, v in CONFUSABLES.items() if (_script_of(c) or "") == "LATIN"}
"""The look-alikes that are Latin letters themselves (the small capitals, the script g): no word of any language this product reads has
one, so they are written as the plain letter wherever they are. NFKC does not do it: they have no compatibility form."""


def _resolve_homoglyphs(text: str, flags: set[str]) -> str:
    """A word that mixes Latin letters with Cyrillic or Greek ones gets the look-alikes written as Latin; one that is wholly Cyrillic or
    Greek is left (it is a word of another language). A word with a Latin look-alike (small capitals) gets those written as the plain
    letter. Both the filter and the reader then see the word the attacker meant."""
    words = text.split(" ")
    changed = False
    for i, word in enumerate(words):
        scripts = {s for s in map(_script_of, word) if s}
        if "LATIN" in scripts and scripts & {"CYRILLIC", "GREEK"}:
            words[i] = "".join(CONFUSABLES.get(c, c) for c in word)
            changed = True
        elif any(c in LATIN_LOOKALIKES for c in word):
            words[i] = "".join(LATIN_LOOKALIKES.get(c, c) for c in word)
            changed = True
    if changed:
        flags.add("mixed_script")
    return " ".join(words)


def _visible(text: str, flags: set[str]) -> str:
    if "<" not in text and "&" not in text:
        return text
    parser = _Visible()
    try:
        parser.feed(text)
        parser.close()
    except Exception:  # broken markup is text to an HTML reader, and is read as such
        flags.add("html_unreadable")
        return re.sub(r"<[^>]{0,2000}>", " ", text)
    if parser.saw_markup:
        flags.add("html")
    return "".join(parser.parts)


def sanitize(text: object, *, origin: str, max_chars: int) -> Untrusted:
    """``text`` as a model may read it. Never raises: whatever is not text is nothing. ``origin`` is the domain or the name of the
    provider it came from - a label for the reader and the audit, not a claim the text can make for itself."""
    if not isinstance(text, str) or not text or max_chars < 1:
        return Untrusted(origin, "", False, ())
    flags: set[str] = set()
    text = text[: max_chars * MAX_INPUT_FACTOR]
    text = unicodedata.normalize("NFKC", text)
    text = _visible(_strip_invisible(text, flags), flags)
    text = _strip_invisible(text, flags)
    text = _SPACE.sub(" ", text).strip()
    text = _resolve_homoglyphs(text, flags)
    before = text
    text = _MD_IMAGE.sub(r"\1", text)
    text = _MD_LINK.sub(r"\1", text)
    text = _MD_REF.sub(r"\1", text)
    text = _URL.sub(LINK, text)
    if text != before:
        flags.add("link")
    text = _SPACE.sub(" ", text).strip()
    if any(p.search(text) for p in _INSTRUCTIONS):
        flags.add("instruction_like")
    truncated = len(text) > max_chars
    if truncated:
        cut = text[: max_chars - 1]
        text = (cut.rsplit(" ", 1)[0] if " " in cut[max_chars // 2:] else cut).rstrip() + "…"
        flags.add("truncated")
    return Untrusted(origin or "unknown", text, truncated, tuple(sorted(flags)))


def instruction_like(text: str) -> bool:
    """Whether the text, once normalised the way the package normalises it, reads like an order to a model."""
    return sanitize(text, origin="check", max_chars=max(len(text), 1)).instruction_like
