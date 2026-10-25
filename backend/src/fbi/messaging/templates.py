"""The e-mails PrediGol sends, in Spanish and English (plan UX, A5, section 33).

A template is a subject, a few paragraphs and at most one button, the same in both languages (a test checks the
parity: the same {placeholders}). The queue keeps only the template's name, the language and the template's own
parameters - short codes and dates, never a body, the reader's name, an address, a secret or a token - and the
message is rendered when it is sent: the parameters become words in the reader's language (``Template.values``), the
reader's name comes from their account at that moment (``ACCOUNT_FIELDS``), and the result is plain text plus
one-column HTML a phone's mail app reads well (a 44 px button, 16 px text, no image, no tracking pixel, no external
resource). Every value is escaped in the HTML.
"""

from __future__ import annotations

import html
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Literal

Locale = Literal["es", "en"]
Category = Literal["account", "security", "membership", "support", "privacy", "legal"]
LOCALES: tuple[Locale, ...] = ("es", "en")
CATEGORIES: tuple[Category, ...] = ("account", "security", "membership", "support", "privacy", "legal")

MANDATORY: frozenset[Category] = frozenset({"account", "security", "privacy", "legal"})
"""Categories a reader cannot switch off: what their account, its security, their own privacy requests and a material
change of the legal texts need them to know (plan UX, section 33). Membership and support notices are optional
(``OPTIONAL``; the database refuses any other in ``customer.preferences.email_off``)."""
OPTIONAL: tuple[Category, ...] = tuple(c for c in CATEGORIES if c not in MANDATORY)

ACCOUNT_FIELDS = frozenset({"name"})
"""Placeholders filled from the reader's account when the message is sent - never stored in the queue."""

FORBIDDEN_PARAMS = re.compile(r"(token|password|secret|passwd|pwd|code|otp|key|cookie|session|email|mail)",
                              re.IGNORECASE)
"""A parameter with a name like these is refused by the queue, whatever the template says."""
PLACEHOLDER = re.compile(r"\{([a-z_]+)\}")
MAX_PARAM = 200


class TemplateError(ValueError):
    """A template, a language or a parameter that does not exist: a bug in the caller, never a reader's input."""


# ── words for the parameters ──────────────────────────────────────────────────────────

MONTHS: dict[Locale, tuple[str, ...]] = {
    "es": ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre",
           "noviembre", "diciembre"),
    "en": ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
           "November", "December"),
}

REQUESTS: dict[str, dict[Locale, str]] = {
    "privacy_query": {"es": "consulta sobre tus datos", "en": "query about your data"},
    "privacy_claim": {"es": "reclamo para corregir o actualizar tus datos",
                      "en": "claim to correct or update your data"},
    "privacy_deletion": {"es": "solicitud para borrar tus datos", "en": "request to delete your data"},
}

LEGAL_SLUGS: dict[str, str] = {"terms": "terms", "privacy": "privacy", "responsible_gaming": "responsible-gaming"}
"""The address of each legal text (web/src/product/legal/links.ts)."""


def long_date(iso: str, locale: Locale) -> str:
    """A calendar day as the reader says it: «9 de noviembre de 2026» / «9 November 2026»."""
    try:
        day = date.fromisoformat(iso[:10])
    except ValueError:
        raise TemplateError(f"not a date: {iso!r}") from None
    month = MONTHS[locale][day.month - 1]
    return f"{day.day} de {month} de {day.year}" if locale == "es" else f"{day.day} {month} {day.year}"


def _request(params: Mapping[str, str], locale: Locale) -> str:
    kind = REQUESTS.get(params["request"])
    if kind is None:
        raise TemplateError(f"unknown request {params['request']!r}")
    ticket = params["ticket"]
    if not ticket.isdigit():
        raise TemplateError(f"a ticket is a number, not {ticket!r}")
    return f"{kind[locale]} (n.º {ticket})" if locale == "es" else f"{kind[locale]} (no. {ticket})"


def _request_received(params: Mapping[str, str], locale: Locale) -> dict[str, str]:
    return {"request": _request(params, locale), "deadline": long_date(params["deadline"], locale)}


def _request_answered(params: Mapping[str, str], locale: Locale) -> dict[str, str]:
    return {"request": _request(params, locale)}


def _legal_change(params: Mapping[str, str], locale: Locale) -> dict[str, str]:
    from fbi.customer import legal

    document = next((d for d in legal.DOCUMENTS if d == params["document"]), None)
    if document is None or document not in LEGAL_SLUGS:
        raise TemplateError(f"unknown legal text {params['document']!r}")
    version = next((v for v in legal.register()[document] if v.version == params["version"]), None)
    if version is None:
        raise TemplateError(f"{document} has no version {params['version']!r}")
    title = legal.load(document, locale).title
    return {"document": title, "changes": version.changes[locale], "document_slug": LEGAL_SLUGS[document]}


# ── the templates ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Copy:
    subject: str
    paragraphs: tuple[str, ...]
    button: str | None = None


@dataclass(frozen=True, slots=True)
class Template:
    name: str
    category: Category
    params: tuple[str, ...]
    """What the queue keeps for this template: exactly these keys, short strings."""
    path: str | None
    """The address the button opens (relative to FBI_WEB_BASE_URL); None: no button."""
    es: Copy
    en: Copy
    values: Callable[[Mapping[str, str], Locale], dict[str, str]]
    """The parameters in words, in a language: every placeholder but ``ACCOUNT_FIELDS``."""
    sample: tuple[tuple[str, str], ...] = ()
    """Parameters that render (the tests and the console's preview use them)."""

    def copy(self, locale: Locale) -> Copy:
        return self.es if locale == "es" else self.en


TEMPLATES: dict[str, Template] = {t.name: t for t in (
    Template(
        "privacy_request_received", "privacy", ("request", "ticket", "deadline"), "/profile#privacy",
        es=Copy("Recibimos tu solicitud sobre tus datos",
                ("Hola, {name}.",
                 "Recibimos tu {request}. Te respondemos a más tardar el {deadline}, como manda la ley.",
                 "Puedes ver su estado y nuestra respuesta en tu perfil, en «Privacidad y datos»."),
                "Ver mi solicitud"),
        en=Copy("We received your request about your data",
                ("Hello, {name}.",
                 "We received your {request}. We will answer by {deadline} at the latest, as the law requires.",
                 "You can see its status and our answer in your profile, under “Privacy and data”."),
                "See my request"),
        values=_request_received,
        sample=(("request", "privacy_query"), ("ticket", "12"), ("deadline", "2026-11-09")),
    ),
    Template(
        "privacy_request_answered", "privacy", ("request", "ticket"), "/profile#privacy",
        es=Copy("Respondimos tu solicitud sobre tus datos",
                ("Hola, {name}.",
                 "Hay una respuesta nueva a tu {request}.",
                 "Léela en tu perfil, en «Privacidad y datos». Por tu seguridad no la copiamos en este correo."),
                "Leer la respuesta"),
        en=Copy("We answered your request about your data",
                ("Hello, {name}.",
                 "There is a new answer to your {request}.",
                 "Read it in your profile, under “Privacy and data”. For your security we do not copy it into this "
                 "e-mail."),
                "Read the answer"),
        values=_request_answered,
        sample=(("request", "privacy_claim"), ("ticket", "12")),
    ),
    Template(
        "legal_change", "legal", ("document", "version"), "/legal/{document_slug}",
        es=Copy("Actualizamos un texto legal de PrediGol",
                ("Hola, {name}.",
                 "Actualizamos «{document}». Qué cambió: {changes}",
                 "La próxima vez que entres te pediremos aceptarlo; hasta entonces no cambia nada de tu cuenta."),
                "Leer el texto"),
        en=Copy("We updated one of PrediGol's legal texts",
                ("Hello, {name}.",
                 "We updated “{document}”. What changed: {changes}",
                 "Next time you sign in we will ask you to accept it; until then nothing changes in your account."),
                "Read the text"),
        values=_legal_change,
        sample=(("document", "terms"), ("version", "2026-10-25-draft1")),
    ),
)}


def placeholders(t: Template, locale: Locale) -> set[str]:
    c = t.copy(locale)
    found = set(PLACEHOLDER.findall(c.subject))
    for p in c.paragraphs:
        found |= set(PLACEHOLDER.findall(p))
    if c.button:
        found |= set(PLACEHOLDER.findall(c.button))
    if t.path:
        found |= set(PLACEHOLDER.findall(t.path))
    return found


def check_params(name: str, params: Mapping[str, object]) -> Template:
    """What the queue may keep for a template: exactly its parameters, short strings, nothing that looks secret or
    personal, and values that render in both languages. Raises TemplateError."""
    t = TEMPLATES.get(name)
    if t is None:
        raise TemplateError(f"no template {name!r}")
    bad = sorted(k for k in params if FORBIDDEN_PARAMS.search(k) or k in ACCOUNT_FIELDS)
    if bad:
        raise TemplateError(f"{name}: parameters the queue never keeps: {bad}")
    if set(params) != set(t.params):
        raise TemplateError(f"{name}: parameters {sorted(params)}, expected {sorted(t.params)}")
    for k, v in params.items():
        if not isinstance(v, str) or not v or len(v) > MAX_PARAM:
            raise TemplateError(f"{name}: parameter {k} must be a string of 1 to {MAX_PARAM} characters")
    clean = {k: str(v) for k, v in params.items()}
    for locale in LOCALES:
        missing = placeholders(t, locale) - ACCOUNT_FIELDS - set(t.values(clean, locale))
        if missing:
            raise TemplateError(f"{name}/{locale}: no value for {sorted(missing)}")
    return t


@dataclass(frozen=True, slots=True)
class Rendered:
    subject: str
    text: str
    html: str
    link: str | None


def web_base() -> str:
    return os.environ.get("FBI_WEB_BASE_URL", "http://localhost:5173").rstrip("/")


FOOTER: dict[Locale, str] = {
    "es": ("PrediGol · información y análisis de fútbol; no garantiza resultados (+18). Recibes este correo por tu "
           "cuenta de PrediGol; puedes elegir qué avisos recibir en tu perfil."),
    "en": ("PrediGol · football information and analysis; it guarantees no result (18+). You receive this e-mail "
           "because of your PrediGol account; you can choose which notices you get in your profile."),
}


def render(name: str, locale: Locale, params: Mapping[str, str], account: Mapping[str, str]) -> Rendered:
    """The message as it leaves: ``params`` from the queue, ``account`` the reader's fields at this moment."""
    t = check_params(name, params)
    if locale not in LOCALES:
        raise TemplateError(f"no language {locale!r}")
    if set(account) != ACCOUNT_FIELDS:
        raise TemplateError(f"account fields {sorted(account)}, expected {sorted(ACCOUNT_FIELDS)}")
    values = {**t.values(params, locale), **{k: str(v).strip() or "—" for k, v in account.items()}}
    c = t.copy(locale)

    def fill(s: str, escape: bool) -> str:
        return PLACEHOLDER.sub(lambda m: html.escape(values[m.group(1)]) if escape else values[m.group(1)], s)

    link = f"{web_base()}{fill(t.path, False)}" if t.path else None
    text_parts = [fill(p, False) for p in c.paragraphs]
    if link and c.button:
        text_parts.append(f"{fill(c.button, False)}: {link}")
    text = "\n\n".join([*text_parts, "--", FOOTER[locale]]) + "\n"
    paragraphs = "".join(
        f'<p style="margin:0 0 16px;font-size:16px;line-height:24px;">{fill(p, True)}</p>' for p in c.paragraphs)
    button = (
        f'<p style="margin:24px 0;"><a href="{html.escape(link)}" style="display:inline-block;min-height:44px;'
        f'line-height:44px;padding:0 20px;border-radius:8px;background:#0f7a4a;color:#ffffff;font-size:16px;'
        f'font-weight:600;text-decoration:none;">{fill(c.button, True)}</a></p>'
    ) if link and c.button else ""
    subject = fill(c.subject, False)
    body = (
        f'<!doctype html><html lang="{locale}"><head><meta charset="utf-8">'
        f'<meta name="viewport" content="width=device-width,initial-scale=1"><title>{html.escape(subject)}</title>'
        f'</head><body style="margin:0;padding:0;background:#ffffff;color:#111111;'
        f'font-family:-apple-system,Segoe UI,Roboto,Helvetica,Arial,sans-serif;">'
        f'<div style="max-width:560px;margin:0 auto;padding:24px 16px;">{paragraphs}{button}'
        f'<p style="margin:32px 0 0;font-size:13px;line-height:20px;color:#555555;">{html.escape(FOOTER[locale])}</p>'
        f'</div></body></html>'
    )
    return Rendered(subject=subject, text=text, html=body, link=link)
