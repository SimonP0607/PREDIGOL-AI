"""What a model writes for the owner to READ: plain prose. A model told to cite ``P:market`` and ``E:12`` in its
claims also drops those tags into its narratives ("P:market dio 33 %"), and the codes it is given (CONTEXT_ERROR,
DOWNGRADE, OUTDATED, "1X2 Home") into its sentences: they are turned back into words here, and an answer is read
leniently where reading it strictly would only lose a good text (an extra key, one lesson too many)."""

from __future__ import annotations

import re
from decimal import Decimal
from typing import Any

WORDS = {"market": "el mercado", "models": "los modelos", "model": "el modelo", "lineups": "las alineaciones",
         "absences": "las bajas", "standings": "la tabla", "form": "la forma", "schedule": "el calendario",
         "h2h": "los cruces directos", "stats": "las estadísticas", "quality": "la calidad de los datos",
         "stakes": "lo que está en juego", "candidate": "la selección", "cards": "la selección",
         "evidence": "la evidencia", "fixture": "el partido", "elo": "el Elo", "travel": "el viaje",
         "signals": "las señales", "previous": "la lectura anterior"}
TAG = re.compile(r"\(?\b([PE]):([a-z_][a-z_0-9]*|\d+)(?:\.[a-z_0-9]+)*\)?")
CLASS_ES = {"MODEL_ERROR": "error del modelo", "CONTEXT_ERROR": "error de contexto", "DATA_ERROR": "error de datos",
            "MARKET_ERROR": "el mercado sabía algo", "EXECUTION_ERROR": "error de ejecución",
            "NORMAL_VARIANCE": "varianza normal", "UNKNOWN": "sin datos para juzgar"}
"""A loss's class in the owner's words (the notes, and a code a model copied into its prose)."""
CODES = {**CLASS_ES, "UNKNOWN": "desconocido",
         "APPROVE": "aprobar", "DOWNGRADE": "cautela", "REJECT": "rechazar", "ABSTAIN": "abstenerse",
         "APROBAR": "aprobar", "CAUTELA": "cautela", "RECHAZAR": "rechazar", "ABSTENERSE": "abstenerse",
         "CONFIRMED": "confirmada", "PROBABLE": "probable", "RUMOR": "rumor", "OUTDATED": "desactualizada",
         "CONTRADICTORY": "contradictoria"}
"""The codes a model is given (classes, decisions, evidence statuses) and copies into prose: on 9 Oct 2026 the
narratives said "Coincido con la clase CONTEXT_ERROR", "la dejó en DOWNGRADE", "quedó en estado OUTDATED"."""
_ALT = "|".join(sorted(CODES, key=len, reverse=True))
CODE = re.compile(rf"\b({_ALT})\b")
PAREN_CODE = re.compile(rf"\s*\((?:{_ALT})\)")
SELECTION_WORDS = {"Home": "local", "Draw": "empate", "Away": "visitante", "Over": "más de", "Under": "menos de",
                   "Yes": "sí", "No": "no"}
SELECTION = re.compile(r"\b(1X2|DC|AH|OU|BTTS)\s+(Home|Draw|Away|Over|Under|Yes|No)\b")
CLAIM_LABEL = re.compile(r"^(?:-\s+)?(?:DATOS|DATA|NOTICIA|NEWS|INFERENCIA|INFERENCE|OPINIÓN|OPINION):\s*")
NOTE_REFS = (  # a lesson citing the notes it rests on by number - the numbers belong in note_refs, not in the text
    re.compile(r"\b[Ss]egún (?:la|las) notas? \d+(?:(?:, | y )\d+)*,\s*"),
    re.compile(r"\b(?:[Ll]a|[Ll]as) notas? \d+(?:(?:, | y )\d+)* (?:indica|indican|muestra|muestran|señala|señalan|"
               r"dice|dicen) que\s+"),
    re.compile(r"\b(?:[Ll]a|[Ll]as) notas? \d+(?:(?:, | y )\d+)* (?:muestra|muestran|señala|señalan|registra|registran)"
               r"\s+"),
    re.compile(r"\s*\((?:según )?(?:la |las )?notas? \d+(?:(?:, | y )\d+)*\)"),
)
SOURCE_LABEL = ((re.compile(r"^provider:"), "Proveedor de datos:"), (re.compile(r"\(provider\)"), "(proveedor de datos)"))
QUOTED_TIER = re.compile(r"'(official|competition|club|provider|journalist|media|aggregator|social|unknown)'")
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


TIER_ES = {"official": "fuentes oficiales", "competition": "la competición", "club": "los clubes",
           "provider": "el proveedor de datos", "journalist": "periodistas", "media": "medios",
           "aggregator": "agregadores", "social": "redes sociales", "unknown": "fuentes sin identificar"}
"""Where a report came from, in the owner's words (``ai.evidence.source_tier``)."""


def selection_es(market: str, selection: str, line: Any = None) -> str:
    """A selection as the owner says it: "1X2 local", "OU más de 2.5" (the provider's names are English)."""
    word = SELECTION_WORDS.get(selection, selection)
    if market not in ("OU", "AH") or line is None:
        return f"{market} {word}"
    t = format(line, "f") if isinstance(line, (Decimal, float)) else str(line)
    return f"{market} {word} {t.rstrip('0').rstrip('.') if '.' in t else t}"


def words(text: str) -> str:
    """Codes and English selection names a model copied into its prose, in the owner's words; references to the
    notes by number dropped; a claim-type label at the start of a line ("DATOS:") removed."""
    out = SELECTION.sub(lambda m: f"{m.group(1)} {SELECTION_WORDS[m.group(2)]}", text)
    out = PAREN_CODE.sub("", out)
    out = CODE.sub(lambda m: f"«{CODES[m.group(1)]}»", out)
    out = CLAIM_LABEL.sub("", out)
    for rx, label in SOURCE_LABEL:
        out = rx.sub(label, out)
    out = QUOTED_TIER.sub(lambda m: f"«{TIER_ES[m.group(1)]}»", out)
    cut = out
    for rx in NOTE_REFS:
        cut = rx.sub("", cut)
    if cut != out:  # a sentence that now starts lower-case starts with a capital
        cut = re.sub(r"(^(?:-\s+)?|[.!?]\s+)([a-záéíóúñ])", lambda m: m.group(1) + m.group(2).upper(), cut)
        out = re.sub(r"\s{2,}", " ", cut).strip()
    return out


def fit(text: str, limit: int) -> str:
    """A text longer than its field, cut at the last sentence (or word) that fits: what is kept is the model's own,
    nothing is added but an ellipsis. (A narrative cut at 900 characters ended "me inclino por varianza normal, co",
    9 Oct 2026.)"""
    if len(text) <= limit:
        return text
    head = text[:limit]
    end = max(head.rfind(". "), head.rfind("; "), head.rfind(".\n"))
    if end >= limit // 2:
        return head[:end + 1]
    cut = head[:limit - 1].rsplit(" ", 1)[0].rstrip(" ,;:")
    return cut + "…"


def shown(text: str | None) -> str | None:
    """A stored text as the owner reads it: reference tags turned into words line by line (texts stored before the
    tags were removed at the source too) and older internal phrases in plain words. Nothing stored is changed."""
    if text is None:
        return None
    for old, new in LEGACY.items():
        text = text.replace(old, new)
    return "\n".join(words(plain(_mended(line))) if line.strip() else line for line in text.split("\n"))


OLD_CUT = 900
"""Until 9 Oct 2026 a narrative's summary was cut at exactly this many characters, often mid-word."""


def _mended(line: str) -> str:
    """A summary stored cut mid-word at OLD_CUT characters ("me inclino por varianza normal, co") shown up to its
    last whole word, with an ellipsis. Any other line is left as it is."""
    body, marker = (line[:-len(DISAGREES)], DISAGREES) if line.endswith(DISAGREES) else (line, "")
    if len(body) == OLD_CUT and not body.rstrip().endswith((".", "!", "?", "…", ")", "»", '"')):
        body = body.rsplit(" ", 1)[0].rstrip(" ,;:") + "…"
    return body + marker


def narrative_of(data: dict[str, Any], *, max_lessons: int, max_len: int = 900) -> tuple[str, bool, list[str]] | None:
    """(summary, agrees_with_class, lessons) from a narrative answer, or None when it has no summary to read. An extra
    key is ignored, a missing agreement counts as agreement, lessons beyond the maximum are dropped."""
    d = dict(data)
    if "summary" not in d and len(d) == 1 and isinstance(next(iter(d.values())), dict):
        d = dict(next(iter(d.values())))
    summary = d.get("summary")
    if not isinstance(summary, str) or len(summary.strip()) < 3:
        return None
    lessons = [fit(words(plain(x)), 240) for x in (d.get("lessons") or []) if isinstance(x, str) and x.strip()]
    agrees = d.get("agrees_with_class")
    return fit(words(plain(summary)), max_len), True if agrees is None else bool(agrees), lessons[:max_lessons]
