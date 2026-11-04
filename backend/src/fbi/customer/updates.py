"""Novedades as the server knows them (plan UX, B6 and B8): the entries of the web's page (web/src/product/updates/updates.ts)
with their titles in both languages, from ``updates.json`` beside this module - what the weekly summary by e-mail names
(fbi.messaging.digest). The web's test checks that both lists and their words are the same: an entry is added in both in
the same change. An entry's id is its date and a slug (fbi.customer.feedback.UPDATE_ID): the day readers could see it."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from functools import cache
from pathlib import Path
from typing import Literal

Locale = Literal["es", "en"]
CATALOG = Path(__file__).resolve().parent / "updates.json"


@dataclass(frozen=True, slots=True)
class Update:
    id: str
    key: str
    title_es: str
    title_en: str

    @property
    def day(self) -> date:
        return date.fromisoformat(self.id[:10])

    def title(self, locale: Locale) -> str:
        return self.title_es if locale == "es" else self.title_en


@cache
def catalog() -> tuple[Update, ...]:
    """Newest first, as the page lists them."""
    raw = json.loads(CATALOG.read_text(encoding="utf-8"))
    return tuple(Update(id=e["id"], key=e["key"], title_es=e["title"]["es"], title_en=e["title"]["en"])
                 for e in raw["entries"])


def by_id(update_id: str) -> Update | None:
    return next((u for u in catalog() if u.id == update_id), None)


def between(first: date, last: date) -> list[Update]:
    """The entries of these days (both included), newest first."""
    return [u for u in catalog() if first <= u.day <= last]
