"""The words of a notice on a device, in the reader's language (plan UX, B7; section 34): a title and one line, built from
what the reader saved or follows and the match's public facts - never a stake, a price, an amount or a promise. The title
says what happened; the line where to look. ES and EN with the same keys (a test holds the parity)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Final, Literal
from zoneinfo import ZoneInfo

Locale = Literal["es", "en"]


@dataclass(frozen=True)
class Words:
    title: str
    body: str


def locale_of(language: str | None) -> Locale:
    return "en" if (language or "").lower().startswith("en") else "es"


RESULT_WORD: Final[dict[str, dict[Locale, str]]] = {
    "WIN": {"es": "Ganado", "en": "Won"},
    "HALF_WIN": {"es": "Medio ganado", "en": "Half won"},
    "LOSS": {"es": "Perdido", "en": "Lost"},
    "HALF_LOSS": {"es": "Medio perdido", "en": "Half lost"},
    "PUSH": {"es": "Devuelto", "en": "Pushed"},
    "VOID": {"es": "Anulado", "en": "Void"},
}
PARLAY_WORD: Final[dict[str, dict[Locale, str]]] = {
    "WON": {"es": "Ganado", "en": "Won"},
    "LOST": {"es": "Perdido", "en": "Lost"},
    "VOID": {"es": "Anulado", "en": "Void"},
    "PARTIAL_VOID": {"es": "Con patas anuladas", "en": "With void legs"},
}


def match_name(home: str, away: str) -> str:
    return f"{home}\u2013{away}"  # an en dash, as the page writes a match


def clock(at: datetime, zone: str | None) -> str:
    return at.astimezone(ZoneInfo(zone or "America/Bogota")).strftime("%H:%M")


def pick_result(status: str, home: str, away: str, locale: Locale) -> Words:
    word = RESULT_WORD.get(status, {"es": "Terminado", "en": "Settled"})[locale]
    if locale == "es":
        return Words(f"{word}: tu pick de {match_name(home, away)}", "Mira cómo terminó y por qué en el Postpartido.")
    return Words(f"{word}: your pick of {match_name(home, away)}", "See how it ended and why in After the match.")


def parlay_result(status: str, name: str | None, locale: Locale) -> Words:
    word = PARLAY_WORD.get(status, {"es": "Terminado", "en": "Settled"})[locale]
    label = (name or "").strip()[:60]
    if locale == "es":
        return Words(f"{word}: tu parlay{f' «{label}»' if label else ''}", "Míralo en Mis picks.")
    return Words(f"{word}: your parlay{f' “{label}”' if label else ''}", "See it in My picks.")


def lineups(home: str, away: str, kickoff: datetime, zone: str | None, locale: Locale) -> Words:
    if locale == "es":
        return Words(f"Ya hay alineaciones: {match_name(home, away)}", f"Empieza a las {clock(kickoff, zone)}.")
    return Words(f"Line-ups are out: {match_name(home, away)}", f"Kick-off at {clock(kickoff, zone)}.")


def reminder(minutes: int, home: str, away: str, locale: Locale) -> Words:
    if locale == "es":
        return Words(f"Empieza en {minutes} minutos", f"{match_name(home, away)}: lo pediste con la campana.")
    return Words(f"Starts in {minutes} minutes", f"{match_name(home, away)}: you asked with the bell.")


def digest(first_home: str, first_away: str, others: int, locale: Locale) -> Words:
    if locale == "es":
        more = "" if others == 0 else (" y 1 partido más" if others == 1 else f" y {others} partidos más")
        return Words("Hoy juegan tus equipos y tus ligas", f"{match_name(first_home, first_away)}{more}: mira su análisis.")
    more = "" if others == 0 else (" and 1 more match" if others == 1 else f" and {others} more matches")
    return Words("Your teams and leagues play today", f"{match_name(first_home, first_away)}{more}: see their analysis.")


def membership_tomorrow(locale: Locale) -> Words:
    if locale == "es":
        return Words("Tu membresía vence mañana", "Mira cómo renovarla en tu perfil.")
    return Words("Your membership ends tomorrow", "See how to renew it in your profile.")


def new_sign_in(device: str, locale: Locale) -> Words:
    if locale == "es":
        return Words("Nuevo inicio de sesión en tu cuenta", f"Desde {device}. ¿No fuiste tú? Revisa tu seguridad.")
    return Words("New sign-in to your account", f"From {device}. Not you? Review your security.")


def test_notice(locale: Locale) -> Words:
    if locale == "es":
        return Words("Así se verán tus avisos", "Este dispositivo recibe los avisos de PrediGol.")
    return Words("This is how your notices will look", "This device receives PrediGol's notices.")
