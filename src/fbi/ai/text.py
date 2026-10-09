"""What a model writes for the owner to READ: plain prose. A model told to cite ``P:market`` and ``E:12`` in its
claims also drops those tags into its narratives ("P:market dio 33 %"): they are turned back into words here, and an
answer is read leniently where reading it strictly would only lose a good text (an extra key, one lesson too many)."""

from __future__ import annotations

import re
from typing import Any

WORDS = {"market": "el mercado", "models": "los modelos", "model": "el modelo", "lineups": "las alineaciones",
         "absences": "las bajas", "standings": "la tabla", "form": "la forma", "schedule": "el calendario",
         "h2h": "los cruces directos", "stats": "las estadísticas", "quality": "la calidad de los datos",
         "stakes": "lo que está en juego", "candidate": "la selección", "cards": "la selección",
         "evidence": "la evidencia", "fixture": "el partido", "elo": "el Elo", "travel": "el viaje",
         "signals": "las señales", "previous": "la lectura anterior"}
TAG = re.compile(r"\(?\b([PE]):([a-z_][a-z_0-9]*|\d+)(?:\.[a-z_0-9]+)*\)?")
CONTRACTIONS = ((r"\bde el\b", "del"), (r"\bDe el\b", "Del"), (r"\ba el\b", "al"), (r"\bA el\b", "Al"))
# phrases of older versions, in the owner's words when shown (the stored row keeps what was written)
LEGACY = {" (el revisor no comparte la clase del servidor)": " (la IA no coincide con la clasificación automática)"}
DISAGREES = LEGACY[" (el revisor no comparte la clase del servidor)"]


def plain(text: str) -> str:
    """The text without reference tags: ``P:market`` becomes "el mercado", ``(E:12)`` disappears."""
    def word(m: re.Match[str]) -> str:
        if m.group(1) == "E":
            return ""
        return WORDS.get(m.group(2), "")
    out = TAG.sub(word, text)
    out = re.sub(r"\s+([,.;:])", r"\1", out)
    for a, b in CONTRACTIONS:  # "de el mercado" -> "del mercado" once a tag became words
        out = re.sub(a, b, out)
    out = re.sub(r"\s{2,}", " ", out).strip()
    # a sentence that now starts with an inserted article starts with a capital
    return re.sub(r"(^(?:-\s+)?|[.!?]\s+)(el|la|los|las|lo)\b", lambda m: m.group(1) + m.group(2).capitalize(), out)


def shown(text: str | None) -> str | None:
    """A stored text as the owner reads it: reference tags turned into words line by line (texts stored before the
    tags were removed at the source too) and older internal phrases in plain words. Nothing stored is changed."""
    if text is None:
        return None
    for old, new in LEGACY.items():
        text = text.replace(old, new)
    return "\n".join(plain(line) if line.strip() else line for line in text.split("\n"))


def narrative_of(data: dict[str, Any], *, max_lessons: int, max_len: int = 900) -> tuple[str, bool, list[str]] | None:
    """(summary, agrees_with_class, lessons) from a narrative answer, or None when it has no summary to read. An extra
    key is ignored, a missing agreement counts as agreement, lessons beyond the maximum are dropped."""
    d = dict(data)
    if "summary" not in d and len(d) == 1 and isinstance(next(iter(d.values())), dict):
        d = dict(next(iter(d.values())))
    summary = d.get("summary")
    if not isinstance(summary, str) or len(summary.strip()) < 3:
        return None
    lessons = [plain(x)[:240] for x in (d.get("lessons") or []) if isinstance(x, str) and x.strip()][:max_lessons]
    agrees = d.get("agrees_with_class")
    return plain(summary)[:max_len], True if agrees is None else bool(agrees), lessons
