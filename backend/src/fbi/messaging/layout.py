"""The look of PrediGol's e-mails (plan de correcciones UX, AP-M01, decision D13; behind ``FBI_EMAIL_V2``, born off).

One base layout and eight tones. The words, the placeholders, the queue and the sender do not change - only the HTML a reader
sees: a header with the brand in the colours of «Noche de partido» (the deep pitch, a gold rule), a white card, the tone's
small label, a 44 px button, the legal footer and a dark version for the mail apps that ask for one. No script, no external
style sheet, no remote image and no tracking pixel; the styles are inline (a ``<style>`` block only for the dark version and
the narrow screens, which a client may ignore without losing anything). The e-mail reads the same with images blocked: it has
none, and AP-M03 adds at most one light decorative image per tone, always with its alternative text.
"""

from __future__ import annotations

import html
import os
from typing import Literal

Locale = Literal["es", "en"]
SWITCH = "FBI_EMAIL_V2"
TONES: tuple[str, ...] = ("welcome", "verification", "security", "membership", "support", "announcement", "digest", "results")
"""The eight tones of the plan: welcome, e-mail verification, security, membership, support, announcement (a notice of the
service or of the legal texts), the weekly summary and the results."""

EYEBROW: dict[str, dict[Locale, str]] = {
    "welcome": {"es": "Bienvenida", "en": "Welcome"},
    "verification": {"es": "Verifica tu correo", "en": "Verify your e-mail"},
    "security": {"es": "Seguridad de tu cuenta", "en": "Your account's security"},
    "membership": {"es": "Tu membresía", "en": "Your membership"},
    "support": {"es": "Soporte", "en": "Support"},
    "announcement": {"es": "Aviso de PrediGol", "en": "PrediGol notice"},
    "digest": {"es": "Tu resumen de la semana", "en": "Your weekly summary"},
    "results": {"es": "Tus resultados", "en": "Your results"},
}
ACCENT: dict[str, str] = {
    "welcome": "#0f7a4a", "verification": "#0f7a4a", "security": "#8a5a00", "membership": "#0f7a4a",
    "support": "#2b6f8f", "announcement": "#8a5a00", "digest": "#0f7a4a", "results": "#0f7a4a",
}
"""The tone's rule above the label: green for what is the reader's own, amber for what asks for attention."""

_BY_NAME: dict[str, str] = {
    "welcome": "welcome", "invitation": "welcome", "activation_reminder": "welcome",
    "email_verification": "verification", "account_exists": "verification",
    "weekly_digest": "digest",
    "payment_request_received": "membership", "payment_request_rejected": "membership",
}
_BY_CATEGORY: dict[str, str] = {
    "security": "security", "membership": "membership", "support": "support", "privacy": "support",
    "legal": "announcement", "service": "announcement", "account": "announcement", "marketing": "digest",
}


def switch_on() -> bool:
    """FBI_EMAIL_V2: any of 1, true, on, yes. Anything else - or nothing - keeps the plain layout."""
    return os.environ.get(SWITCH, "").strip().lower() in {"1", "true", "on", "yes"}


def tone_of(name: str, category: str) -> str:
    """The tone of a template: by its name when it has one of its own, else by its category."""
    return _BY_NAME.get(name) or _BY_CATEGORY.get(category, "announcement")


def page(*, locale: Locale, subject: str, tone: str, paragraphs: list[str], button: tuple[str, str] | None,
         footer: str) -> str:
    """The whole HTML. ``paragraphs`` and ``footer`` arrive already escaped; ``button`` is (address, label) with the label
    already escaped; ``subject`` is plain text and is escaped here."""
    eyebrow = html.escape(EYEBROW[tone][locale])
    accent = ACCENT[tone]
    preheader = html.escape(subject)
    body = "".join(f'<p class="fg" style="margin:0 0 16px;font-size:16px;line-height:24px;color:#111111;">{p}</p>'
                   for p in paragraphs)
    action = (
        f'<table role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin:24px 0 8px;"><tr>'
        f'<td style="border-radius:8px;background:#0f7a4a;"><a href="{html.escape(button[0])}" '
        f'style="display:inline-block;min-height:44px;line-height:44px;padding:0 24px;border-radius:8px;'
        f'background:#0f7a4a;color:#ffffff;font-size:16px;font-weight:600;text-decoration:none;">{button[1]}</a>'
        f'</td></tr></table>'
    ) if button else ""
    return (
        f'<!doctype html><html lang="{locale}"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1">'
        f'<meta name="color-scheme" content="light dark"><meta name="supported-color-schemes" content="light dark">'
        f'<title>{html.escape(subject)}</title>'
        f'<style>@media (prefers-color-scheme: dark){{.bg{{background:#0a110e !important;}}'
        f'.card{{background:#111916 !important;}}.fg{{color:#f2f5f3 !important;}}.soft{{color:#98a29e !important;}}}}'
        f'@media (max-width:480px){{.pad{{padding:20px 16px !important;}}}}</style>'
        f'</head><body class="bg" style="margin:0;padding:0;background:#eef2f0;'
        f'font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;">'
        f'<div style="display:none;max-height:0;overflow:hidden;opacity:0;">{preheader}</div>'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" class="bg" '
        f'style="background:#eef2f0;"><tr><td align="center" style="padding:24px 12px;">'
        f'<table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" '
        f'style="max-width:560px;">'
        f'<tr><td style="background:#0e2318;border-radius:12px 12px 0 0;padding:20px 24px;">'
        f'<span style="font-size:22px;line-height:28px;font-weight:700;letter-spacing:0.2px;color:#f2f5f3;">'
        f'Predi<span style="color:#eeb747;">Gol</span></span></td></tr>'
        f'<tr><td style="height:3px;line-height:3px;font-size:0;background:#eeb747;">&nbsp;</td></tr>'
        f'<tr><td class="card pad" style="background:#ffffff;padding:28px 24px;border-radius:0 0 12px 12px;">'
        f'<p style="margin:0 0 12px;font-size:12px;line-height:16px;font-weight:700;letter-spacing:0.8px;'
        f'text-transform:uppercase;color:{accent};">{eyebrow}</p>'
        f'{body}{action}</td></tr>'
        f'<tr><td style="padding:16px 8px 0;"><p class="soft" style="margin:0;font-size:13px;line-height:20px;'
        f'color:#555555;">{footer}</p></td></tr>'
        f'</table></td></tr></table></body></html>'
    )
