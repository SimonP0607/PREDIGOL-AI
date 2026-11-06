"""The e-mails of the closing plan's task 4.1, word by word (plan de cierre UX, 4.1: «instantánea de cada plantilla»).

Seven templates were added - the welcome, the only reminder to an invitation nobody used, the trial the owner started, a
payment recorded, a scheduled maintenance, an incident resolved and an important change - each in Spanish and English.
What a reader is told is part of the product: the subject, every paragraph and the button of each, as the reader sees them
(name "Ana", the time zone of Bogotá), are kept in ``tests/snapshots/email_templates_ux017.json`` and a change of a word
fails here until it is written down on purpose:

    FBI_WRITE_SNAPSHOTS=1 PYTHONPATH=src python -m pytest tests/unit/test_email_templates_snapshot.py

The same test says what an e-mail must never carry: no amount, no price, no card, no promise of results (PrediGol is
analysis, not a bookmaker) and no address of the reader.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from fbi.messaging.templates import TEMPLATES, render

SNAPSHOT = Path(__file__).resolve().parents[1] / "snapshots" / "email_templates_ux017.json"
NEW = ("welcome", "activation_reminder", "trial_started", "payment_recorded", "maintenance_scheduled",
       "incident_resolved", "important_change")
TOKEN = "abcdefghijklmnopqrstuvwxyz0123456789"
LINK = f"https://predigol.example/activate#t={TOKEN}"
UNTIL = datetime(2026, 11, 12, 15, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def web_address(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FBI_WEB_BASE_URL", "https://predigol.example")


def rendered(name: str, locale: str) -> dict[str, Any]:
    t = TEMPLATES[name]
    out = render(name, locale, dict(t.sample), {"name": "Ana"}, zone="America/Bogota",  # type: ignore[arg-type]
                 link=TOKEN if t.grant else None, until=UNTIL if t.grant else None)
    return {"subject": out.subject, "text": out.text, "link": out.link}


def current() -> dict[str, dict[str, Any]]:
    return {f"{name}/{locale}": rendered(name, locale) for name in NEW for locale in ("es", "en")}


def test_the_seven_new_templates_are_the_ones_the_plan_names() -> None:
    for name in NEW:
        assert name in TEMPLATES
    assert {n for n, t in TEMPLATES.items() if t.category == "service"} == {
        "maintenance_scheduled", "incident_resolved", "important_change", "critical_notice"}
    # the two that reach everyone: an important change (4.1) and the owner's critical communiqué (4.3)
    assert {n for n, t in TEMPLATES.items() if t.critical} == {"important_change", "critical_notice"}


def test_each_template_says_what_it_said_when_it_was_written() -> None:
    now = current()
    if os.environ.get("FBI_WRITE_SNAPSHOTS") == "1":
        SNAPSHOT.write_text(json.dumps(now, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    saved = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    assert set(saved) == set(now), "a template was added or removed without writing the snapshot down"
    for key in sorted(now):
        assert now[key] == saved[key], f"{key} changed: write the snapshot down on purpose (see this file's head)"


@pytest.mark.parametrize("name", NEW)
@pytest.mark.parametrize("locale", ["es", "en"])
def test_no_amount_no_promise_and_the_reader_is_addressed_by_name(name: str, locale: str) -> None:
    out = rendered(name, locale)
    raw = out["subject"] + "\n" + out["text"]
    assert "Ana" in out["text"]
    for word in ("COP", "USD", "$", "tarjeta de crédito", "credit card", "garantizamos", "we guarantee"):
        assert word not in raw, f"{name}/{locale} mentions {word!r}"
    assert "@" not in raw, "an e-mail never prints the reader's address"


def test_the_reminder_carries_the_invitations_own_link_and_says_it_is_the_only_one() -> None:
    es, en = rendered("activation_reminder", "es"), rendered("activation_reminder", "en")
    assert es["link"] == en["link"] == LINK
    assert "único recordatorio" in es["text"] and "only reminder" in en["text"]
    assert "12 de noviembre de 2026, 10:00" in es["text"] and "12 November 2026, 10:00" in en["text"]


def test_the_welcome_and_the_payment_tell_the_day_in_the_readers_zone() -> None:
    # 2026-11-25T15:00Z is the 25th in Bogotá (UTC-5) and so is 2026-12-25T15:00Z the 25th
    assert "25 de noviembre" in rendered("welcome", "es")["text"]
    assert "25 de diciembre" in rendered("payment_recorded", "es")["text"]
    assert "25 de noviembre" in rendered("trial_started", "es")["text"]
