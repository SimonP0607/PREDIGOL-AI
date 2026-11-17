"""Injuries are a STATE, not a medical report (IA-102, plan piece AD-G05): ``health-filter-v1``. Pure.

A news text of PrediGol says of a player only whether he is out, doubtful, suspended or available, the source and the date. A health
datum is sensitive (Colombia, Ley 1581 de 2012, art. 5): a diagnosis, a part of the body, a treatment, a test or a time off are MEDICAL
DETAIL, and a text of ours carries one only when the club or the player communicated it AND the sentence says so («según informó el club»).
A time off (``plazo``) is never estimated and never inferred: it is said only when a communication of the club or the player that the text
cites gives that very time, attributed. Everything else is refused - the text is not written (``fbi.news.writer``) and the story goes to the
private moderation queue (``fbi.news.moderation``).

``details(text)`` finds the medical words in a text (Spanish, English, Portuguese; on the folded text); ``durations(text)`` the times off;
``check(sentence, cited)`` decides one sentence against the facts it cites. A word of STATE (baja, duda, lesionado, sancionado, out,
doubtful, injured, suspended, available) is not a detail."""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Final

from fbi.core.fingerprint import folded

VERSION: Final = "health-filter-v1"

DIAGNOSIS: Final = re.compile(
    r"\b(?:rotur\w*|desgarr\w*|distension\w*|esguince\w*|fractur\w*|fisur\w*|luxacion\w*|contusion\w*|tendin\w*|tendon\w*|ligament\w*|"
    r"menisc\w*|cartilag\w*|sobrecarga|elongacion|edema|hernia\w*|pubalgia|fascitis|conmocion|commotion|concussion|"
    r"tear|torn|sprain\w*|strain\w*|fracture\w*|rupture\w*|ruptured|acl|mcl|lca|lcp|grado (?:i|ii|iii|1|2|3)|grade (?:i|ii|iii|1|2|3)|"
    r"lesao muscular|estiramento|entorse|virus|covid\w*|gripe|enfermedad|illness|infeccion\w*|infection)\b")
BODY: Final = re.compile(
    r"\b(?:rodilla\w*|tobillo\w*|muslo\w*|isquio\w*|isquiotibial\w*|gemel\w*|pantorrilla\w*|aductor\w*|cuadricep\w*|hombro\w*|espalda|"
    r"cadera|ingle|tibia|perone|clavicula|muneca|codo|costilla\w*|craneo|nariz|mandibula|abductor\w*|soleo|"
    r"knee\w*|ankle\w*|thigh\w*|hamstring\w*|calf|calves|groin|shoulder\w*|hip|foot|toe|wrist|elbow|ribs?|"
    r"joelho|tornozelo|coxa|panturrilha|ombro|virilha)\b")
TREATMENT: Final = re.compile(
    r"\b(?:cirugi\w*|operad\w*|operacion|intervencion quirurgica|quirofano|infiltracion\w*|resonancia\w*|ecografi\w*|radiografi\w*|"
    r"surgery|operation|operated|scan\w*|mri|x ray|cirurgia|operado|exames?|parte medico|medical report|rehabilitacion|rehab)\b")
DURATION: Final = re.compile(
    r"\b(?:\d+|un|una|dos|tres|cuatro|cinco|seis|siete|ocho|nueve|diez|doce|quince|veinte|one|two|three|four|five|six|seven|eight|nine|"
    r"ten|twelve|um|uma|duas|tres)\s+(?:a\s+\w+\s+)?(?:dias?|semanas?|mes|meses|days?|weeks?|months?|jornadas?|partidos?|games?|matches?)\b"
    r"|\b(?:resto de la temporada|rest of the season|toda la temporada|varias semanas|several weeks|largo plazo|long term|"
    r"plazo de recuperacion|tiempo de baja|recovery time|baja de larga duracion|out until|hasta (?:enero|febrero|marzo|abril|mayo|junio|"
    r"julio|agosto|septiembre|octubre|noviembre|diciembre))\b")
ATTRIBUTION: Final = re.compile(
    r"\b(?:segun (?:el|su|la) (?:club|equipo|jugador|cuerpo medico|servicio medico|departamento medico)|informo el club|comunico el club|"
    r"anuncio el club|confirmo el club|el club (?:informo|comunico|anuncio|confirmo|explico)|el jugador (?:informo|comunico|anuncio|"
    r"confirmo|explico)|according to (?:the|his) club|the club (?:said|announced|confirmed|reported)|(?:the|said the) player (?:said|"
    r"confirmed|announced)|segundo o clube|o clube (?:informou|confirmou|anunciou))\b")
COMMUNICATORS: Final = frozenset({"club", "player"})


def _text(text: str) -> str:
    return " ".join(folded(text).split())


def details(text: str) -> list[str]:
    """The medical words of a text (diagnoses, parts of the body, treatments and tests), once each, in order."""
    t = _text(text)
    found: list[str] = []
    for pattern in (DIAGNOSIS, BODY, TREATMENT):
        for m in pattern.finditer(t):
            if m.group(0) not in found:
                found.append(m.group(0))
    return found


def durations(text: str) -> list[str]:
    t = _text(text)
    return list(dict.fromkeys(m.group(0) for m in DURATION.finditer(t)))


@dataclass(frozen=True, slots=True)
class Communicated:
    """What a cited fact says, and who said it: ``club`` or ``player`` when the club or the player communicated it (their own source or
    their own statement), else ``press``."""

    text: str
    by: str = "press"


def check(sentence: str, cited: Sequence[Communicated], *, injury: bool) -> str | None:
    """Why a sentence of an own text may not carry what it says of a player's health, or None. ``injury``: the sentence is about an
    injury or availability (a story of ``lesiones`` or a fact of that type) - then every medical word and every time off is checked; in any
    other sentence a medical word is refused too (a transfer text has no business saying a diagnosis)."""
    found = details(sentence)
    times = durations(sentence) if injury else []
    if not found and not times:
        return None
    attributed = ATTRIBUTION.search(_text(sentence)) is not None
    official = [c for c in cited if c.by in COMMUNICATORS]
    if found:
        if not official or not attributed:
            return "medical_detail_unattributed"
        said = " ".join(_text(c.text) for c in official)
        missing = [w for w in found if w not in said]
        if missing:
            return "medical_detail_not_communicated"
    if times:
        said = " ".join(_text(c.text) for c in official)
        if not official or not attributed or any(t not in said for t in times):
            return "duration_not_communicated"
    return None


__all__ = ["VERSION", "Communicated", "check", "details", "durations"]
