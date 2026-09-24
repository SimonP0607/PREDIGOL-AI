"""Comparing team names across sources - as evidence, never as the only evidence.

A name similarity alone would attach Real Madrid's odds to Real Mallorca on a
bad day. It is only ever used to choose between fixtures that already agree
on the competition, the date and the score.
"""

from __future__ import annotations

import re
import unicodedata
from difflib import SequenceMatcher

_NOISE = {"fc", "afc", "cf", "sc", "ac", "as", "ssc", "sv", "vfl", "vfb", "tsg", "rcd", "ud", "cd", "sd",
          "ca", "club", "de", "calcio", "1", "04", "05", "1899", "1846", "1848", "fk", "rc", "ogc", "stade",
          "the"}
_SPECIAL = {
    "man united": "manchester united", "man utd": "manchester united", "man city": "manchester city",
    "nott'm forest": "nottingham forest", "nottm forest": "nottingham forest", "wolves": "wolverhampton",
    "spurs": "tottenham", "sheffield weds": "sheffield wednesday", "west brom": "west bromwich",
    "ath madrid": "atletico madrid", "ath bilbao": "athletic bilbao", "sociedad": "real sociedad",
    "vallecano": "rayo vallecano", "espanol": "espanyol", "betis": "real betis", "celta": "celta vigo",
    "m'gladbach": "monchengladbach", "ein frankfurt": "eintracht frankfurt", "fc koln": "koln",
    "bayern munich": "bayern munchen", "paris sg": "paris saint germain", "st etienne": "saint etienne",
    "inter": "inter milan", "milan": "ac milan",
}


def normalise(name: str) -> str:
    text = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().lower().strip()
    text = _SPECIAL.get(text, text)
    text = re.sub(r"[^a-z0-9' ]+", " ", text)
    return " ".join(text.split())


def _tokens(name: str) -> set[str]:
    return {t for t in normalise(name).replace("'", "").split() if t not in _NOISE}


def similarity(a: str, b: str) -> float:
    """0..1. Token containment dominates ("Dortmund" is in "Borussia Dortmund");
    a character ratio breaks the rest."""
    na, nb = normalise(a), normalise(b)
    if na == nb:
        return 1.0
    ta, tb = _tokens(a), _tokens(b)
    token = len(ta & tb) / min(len(ta), len(tb)) if ta and tb else 0.0
    chars = SequenceMatcher(None, na, nb).ratio()
    return max(token, chars * 0.9)
