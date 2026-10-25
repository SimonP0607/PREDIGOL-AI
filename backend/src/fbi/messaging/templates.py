"""The e-mails PrediGol sends, in Spanish and English (plan UX, A5, section 33).

A template is a subject, a few paragraphs and at most one button, the same in both languages (a test checks the
parity: the same {placeholders}). The queue keeps only the template's name, the language and the template's own
parameters - short codes and dates, never a body, the reader's name, an address, a secret or a token - and the
message is rendered when it is sent: the parameters become words in the reader's language (``Template.values``), the
reader's name comes from their account at that moment (``ACCOUNT_FIELDS``), and the result is plain text plus
one-column HTML a phone's mail app reads well (a 44 px button, 16 px text, no image, no tracking pixel, no external
resource). Every value is escaped in the HTML.

The e-mails of an account (plan UX, A7) carry a one-use link: the queue keeps only the number of its row in
``auth.account_tokens`` (``grant``), and the link - with the moment it expires - is made in the transaction that
sends the e-mail (``fbi.auth.tokens.arm``), so it exists only in that e-mail (``SEND_FIELDS``). Times are said in the
reader's time zone, read from their account when the message leaves. A message whose moment has passed is not sent
(``stale_after``: a reset link asked for two hours ago, a sign-in notice from yesterday).
"""

from __future__ import annotations

import html
import os
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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
SEND_FIELDS = frozenset({"link", "until"})
"""Placeholders of a template with a one-use link, filled when the message leaves: the link (only in the button's
address) and the moment it expires. Never stored anywhere."""
PREVIEW_LINK = "preview-link-made-when-the-e-mail-leaves"
"""What the console's preview shows in place of a link: the preview never makes a real one."""

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


def zone_label(zone: str, locale: Locale) -> str:
    """The reader's time zone as a person says it: «hora de Bogota» / «Bogota time»; UTC as such."""
    if zone == "UTC" or "/" not in zone:
        return "hora UTC" if locale == "es" else "UTC"
    city = zone.rsplit("/", 1)[-1].replace("_", " ")
    return f"hora de {city}" if locale == "es" else f"{city} time"


def moment(value: str | datetime, locale: Locale, zone: str) -> str:
    """A moment as the reader says it, in their time zone: «25 de octubre de 2026, 13:05 (hora de Bogota)»."""
    try:
        at = value if isinstance(value, datetime) else datetime.fromisoformat(value)
    except ValueError:
        raise TemplateError(f"not a moment: {value!r}") from None
    if at.tzinfo is None:
        raise TemplateError(f"a moment without its time zone: {value!r}")
    try:
        tz = ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError):
        tz, zone = ZoneInfo("UTC"), "UTC"
    local = at.astimezone(tz)
    month = MONTHS[locale][local.month - 1]
    day = f"{local.day} de {month} de {local.year}" if locale == "es" else f"{local.day} {month} {local.year}"
    return f"{day}, {local:%H:%M} ({zone_label(zone, locale)})"


def day_in_zone(value: str, locale: Locale, zone: str) -> str:
    """The calendar day of a moment in the reader's time zone, as they say it: «7 de noviembre de 2026»."""
    try:
        at = datetime.fromisoformat(value)
    except ValueError:
        raise TemplateError(f"not a moment: {value!r}") from None
    if at.tzinfo is None:
        raise TemplateError(f"a moment without its time zone: {value!r}")
    try:
        tz = ZoneInfo(zone)
    except (ZoneInfoNotFoundError, ValueError):
        tz = ZoneInfo("UTC")
    return long_date(at.astimezone(tz).date().isoformat(), locale)


MEMBERSHIP_KINDS: dict[str, dict[Locale, str]] = {
    "trial": {"es": "Tu prueba de PrediGol", "en": "Your PrediGol trial"},
    "paid": {"es": "Tu membresía de PrediGol", "en": "Your PrediGol membership"},
    "courtesy": {"es": "Tu membresía de PrediGol", "en": "Your PrediGol membership"},
}
"""What ends, as the reader calls it: a trial, or the membership (paid or a courtesy)."""
GRACE_DAYS = 3


def _renew_how(locale: Locale) -> str:
    """How to renew, read when the e-mail leaves: WhatsApp (FBI_SUPPORT_WHATSAPP, P7 of the plan) and answering the
    e-mail (FBI_EMAIL_REPLY_TO) when they exist; the profile otherwise."""
    digits = re.sub(r"[^0-9]", "", os.environ.get("FBI_SUPPORT_WHATSAPP", ""))
    phone = f"+{digits}" if 8 <= len(digits) <= 15 else None
    reply = bool(os.environ.get("FBI_EMAIL_REPLY_TO", "").strip())
    if locale == "es":
        ways = ([f"por WhatsApp al {phone}"] if phone else []) + (["respondiendo a este correo"] if reply else [])
        return f"Para renovar, escríbenos {' o '.join(ways)}." if ways else (
            "Para renovar, mira cómo hacerlo en tu perfil.")
    ways = ([f"on WhatsApp at {phone}"] if phone else []) + (["by answering this e-mail"] if reply else [])
    return f"To renew, write to us {' or '.join(ways)}." if ways else "To renew, see how in your profile."


def _membership(params: Mapping[str, str], locale: Locale, zone: str) -> dict[str, str]:
    kind = MEMBERSHIP_KINDS.get(params["kind"])
    if kind is None:
        raise TemplateError(f"a membership is a trial, paid or a courtesy, not {params['kind']!r}")
    ends = params["ends"]
    try:
        grace = (datetime.fromisoformat(ends) + timedelta(days=GRACE_DAYS)).isoformat()
    except ValueError:
        raise TemplateError(f"not a moment: {ends!r}") from None
    return {"what": kind[locale], "date": day_in_zone(ends, locale, zone),
            "grace": day_in_zone(grace, locale, zone), "how": _renew_how(locale)}


BROWSERS: dict[str, dict[Locale, str]] = {
    "chrome": {"es": "Chrome", "en": "Chrome"}, "edge": {"es": "Edge", "en": "Edge"},
    "firefox": {"es": "Firefox", "en": "Firefox"}, "safari": {"es": "Safari", "en": "Safari"},
    "opera": {"es": "Opera", "en": "Opera"}, "samsung": {"es": "Samsung Internet", "en": "Samsung Internet"},
    "other": {"es": "un navegador", "en": "a browser"},
}
"""The browser family of a new sign-in (fbi.auth.recovery.device_family): a closed list, never the user agent."""
SYSTEMS: dict[str, dict[Locale, str]] = {
    "android": {"es": "Android", "en": "Android"}, "ios": {"es": "iPhone o iPad", "en": "iPhone or iPad"},
    "windows": {"es": "Windows", "en": "Windows"}, "macos": {"es": "Mac", "en": "Mac"},
    "linux": {"es": "Linux", "en": "Linux"}, "chromeos": {"es": "ChromeOS", "en": "ChromeOS"},
    "other": {"es": "un sistema desconocido", "en": "an unknown system"},
}
CHANGES: dict[str, dict[Locale, str]] = {
    "password": {"es": "Se cambió la contraseña de tu cuenta", "en": "Your account's password was changed"},
    "password_reset": {"es": "Se eligió una contraseña nueva para tu cuenta con un enlace de recuperación",
                       "en": "A new password was chosen for your account with a recovery link"},
    "password_admin": {"es": "El administrador restableció la contraseña de tu cuenta con una temporal",
                       "en": "The administrator reset your account's password to a temporary one"},
    "mfa_on": {"es": "Se activó la verificación en dos pasos de tu cuenta",
               "en": "Two-step verification was turned on for your account"},
    "mfa_off": {"es": "Se desactivó la verificación en dos pasos de tu cuenta",
                "en": "Two-step verification was turned off for your account"},
    "mfa_reset": {"es": "El administrador quitó la verificación en dos pasos de tu cuenta",
                  "en": "The administrator removed two-step verification from your account"},
    "recovery_codes": {"es": ("Se generaron códigos de recuperación nuevos para tu cuenta (los anteriores ya no "
                              "sirven)"),
                       "en": "New recovery codes were made for your account (the previous ones no longer work)"},
}
"""A change of credentials an account is told about (plan UX, section 33)."""


def _word(table: dict[str, dict[Locale, str]], key: str, locale: Locale, what: str) -> str:
    words = table.get(key)
    if words is None:
        raise TemplateError(f"unknown {what} {key!r}")
    return words[locale]


def _request(params: Mapping[str, str], locale: Locale) -> str:
    kind = REQUESTS.get(params["request"])
    if kind is None:
        raise TemplateError(f"unknown request {params['request']!r}")
    ticket = params["ticket"]
    if not ticket.isdigit():
        raise TemplateError(f"a ticket is a number, not {ticket!r}")
    return f"{kind[locale]} (n.º {ticket})" if locale == "es" else f"{kind[locale]} (no. {ticket})"


def _request_received(params: Mapping[str, str], locale: Locale, _zone: str) -> dict[str, str]:
    return {"request": _request(params, locale), "deadline": long_date(params["deadline"], locale)}


def _request_answered(params: Mapping[str, str], locale: Locale, _zone: str) -> dict[str, str]:
    return {"request": _request(params, locale)}


def _legal_change(params: Mapping[str, str], locale: Locale, _zone: str) -> dict[str, str]:
    from fbi.customer import legal

    document = next((d for d in legal.DOCUMENTS if d == params["document"]), None)
    if document is None or document not in LEGAL_SLUGS:
        raise TemplateError(f"unknown legal text {params['document']!r}")
    version = next((v for v in legal.register()[document] if v.version == params["version"]), None)
    if version is None:
        raise TemplateError(f"{document} has no version {params['version']!r}")
    title = legal.load(document, locale).title
    return {"document": title, "changes": version.changes[locale], "document_slug": LEGAL_SLUGS[document]}


def _grant(params: Mapping[str, str], _locale: Locale, _zone: str) -> dict[str, str]:
    """A link's e-mail: its only parameter is the number of its token's row (the link is made when it leaves)."""
    if not params["grant"].isdigit():
        raise TemplateError(f"a grant is the number of a token's row, not {params['grant']!r}")
    return {}


def _new_sign_in(params: Mapping[str, str], locale: Locale, zone: str) -> dict[str, str]:
    browser = _word(BROWSERS, params["browser"], locale, "browser")
    system = _word(SYSTEMS, params["system"], locale, "system")
    device = f"{browser} en {system}" if locale == "es" else f"{browser} on {system}"
    return {"device": device, "moment": moment(params["when"], locale, zone)}


def _security_change(params: Mapping[str, str], locale: Locale, zone: str) -> dict[str, str]:
    return {"change": _word(CHANGES, params["change"], locale, "change"),
            "moment": moment(params["when"], locale, zone)}


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
    values: Callable[[Mapping[str, str], Locale, str], dict[str, str]]
    """The parameters in words, in a language and the reader's time zone: every placeholder but ``ACCOUNT_FIELDS``
    (and ``SEND_FIELDS``)."""
    sample: tuple[tuple[str, str], ...] = ()
    """Parameters that render (the tests and the console's preview use them)."""
    grant: str | None = None
    """The kind of one-use link the button carries (fbi.auth.tokens): the queue keeps the number of its row as the
    parameter ``grant`` and the link is made when the message leaves."""
    stale_after: timedelta | None = None
    """A message still queued this long after it was asked for is not sent any more."""
    stale_param: str | None = None
    """The parameter holding the moment (plus ``stale_grace``) past which a queued message is not sent any more: a
    membership's «ends on the 7th» after the 7th (plan UX, A8)."""
    stale_grace: timedelta = timedelta(0)

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
    # ── an account's e-mails (plan UX, A7) ──
    Template(
        "invitation", "account", ("grant",), "/activate#t={link}",
        es=Copy("Tu invitación a PrediGol",
                ("Hola, {name}.",
                 "Te invitamos a PrediGol: el análisis diario de los partidos de tus ligas, y picks solo cuando hay "
                 "una ventaja medida.",
                 "Para entrar, crea tu contraseña con el botón. El enlace sirve una sola vez y caduca el {until}.",
                 "Si no esperabas esta invitación, ignora este correo: la cuenta no se activa sin ti."),
                "Activar mi cuenta"),
        en=Copy("Your invitation to PrediGol",
                ("Hello, {name}.",
                 "You are invited to PrediGol: a daily analysis of the matches of your leagues, and picks only when "
                 "there is a measured edge.",
                 "To get in, create your password with the button. The link works once and expires on {until}.",
                 "If you did not expect this invitation, ignore this e-mail: the account is not activated without "
                 "you."),
                "Activate my account"),
        values=_grant, sample=(("grant", "1"),), grant="invite",
    ),
    Template(
        "password_reset", "security", ("grant",), "/reset-password#t={link}",
        es=Copy("Elige una contraseña nueva para PrediGol",
                ("Hola, {name}.",
                 "Pediste elegir una contraseña nueva. Hazlo con el botón: el enlace sirve una sola vez y caduca el "
                 "{until}.",
                 "Al cambiarla se cierran todas tus sesiones; tu verificación en dos pasos, si la usas, sigue igual.",
                 "Si no lo pediste, ignora este correo: tu contraseña no cambia."),
                "Elegir una contraseña nueva"),
        en=Copy("Choose a new password for PrediGol",
                ("Hello, {name}.",
                 "You asked to choose a new password. Do it with the button: the link works once and expires on "
                 "{until}.",
                 "Changing it signs you out everywhere; your two-step verification, if you use it, stays as it is.",
                 "If you did not ask for this, ignore this e-mail: your password does not change."),
                "Choose a new password"),
        values=_grant, sample=(("grant", "1"),), grant="reset", stale_after=timedelta(hours=1),
    ),
    Template(
        "account_unlock", "security", ("grant",), "/unlock#t={link}",
        es=Copy("Desbloquea tu cuenta de PrediGol",
                ("Hola, {name}.",
                 "Tu cuenta se bloqueó un tiempo tras varios intentos fallidos de entrar. Si fuiste tú, desbloquéala "
                 "con el botón: el enlace sirve una sola vez y caduca el {until}.",
                 "Si no fuiste tú, no hagas nada: el bloqueo te protege. Si crees que alguien conoce tu contraseña, "
                 "cámbiala con «¿Olvidaste tu contraseña?» en la pantalla de acceso."),
                "Desbloquear mi cuenta"),
        en=Copy("Unlock your PrediGol account",
                ("Hello, {name}.",
                 "Your account was locked for a while after several failed attempts to sign in. If it was you, "
                 "unlock it with the button: the link works once and expires on {until}.",
                 "If it was not you, do nothing: the lock protects you. If you think someone knows your password, "
                 "change it with “Forgot your password?” on the sign-in screen."),
                "Unlock my account"),
        values=_grant, sample=(("grant", "1"),), grant="unlock", stale_after=timedelta(hours=1),
    ),
    Template(
        "new_sign_in", "security", ("browser", "system", "when"), "/profile#security",
        es=Copy("Nuevo inicio de sesión en tu cuenta de PrediGol",
                ("Hola, {name}.",
                 "Alguien entró a tu cuenta desde {device} el {moment}.",
                 "Si fuiste tú, no hagas nada. Si no, cambia tu contraseña y cierra las sesiones que no reconozcas "
                 "desde tu perfil; si no puedes entrar, usa «¿Olvidaste tu contraseña?» en la pantalla de acceso."),
                "Revisar mi seguridad"),
        en=Copy("New sign-in to your PrediGol account",
                ("Hello, {name}.",
                 "Someone signed in to your account from {device} on {moment}.",
                 "If it was you, do nothing. If not, change your password and end the sessions you do not recognise "
                 "from your profile; if you cannot get in, use “Forgot your password?” on the sign-in screen."),
                "Review my security"),
        values=_new_sign_in,
        sample=(("browser", "firefox"), ("system", "android"), ("when", "2026-10-25T18:05:00+00:00")),
        stale_after=timedelta(hours=24),
    ),
    Template(
        "security_change", "security", ("change", "when"), "/profile#security",
        es=Copy("Cambio de seguridad en tu cuenta de PrediGol",
                ("Hola, {name}.",
                 "{change} el {moment}.",
                 "Si fuiste tú, no hagas nada. Si no reconoces este cambio, cambia tu contraseña y revisa tus "
                 "sesiones desde tu perfil."),
                "Revisar mi seguridad"),
        en=Copy("A security change in your PrediGol account",
                ("Hello, {name}.",
                 "{change} on {moment}.",
                 "If it was you, do nothing. If you do not recognise this change, change your password and review "
                 "your sessions from your profile."),
                "Review my security"),
        values=_security_change, sample=(("change", "password"), ("when", "2026-10-25T18:05:00+00:00")),
        stale_after=timedelta(hours=24),
    ),
    # The membership (plan UX, A8): 7 days before the end (3 in a trial) and at the end - a service notice, no
    # countdown, no offer, no alarm colours; the reader can switch the category off in the profile.
    Template(
        "membership_expiring", "membership", ("ends", "kind"), "/profile#membership",
        es=Copy("{what} termina el {date}",
                ("Hola, {name}.",
                 "{what} termina el {date}. {how}",
                 "Si renuevas antes, sigues sin cortes; si no, tienes 3 días de gracia con acceso completo."),
                "Ver mi membresía"),
        en=Copy("{what} ends on {date}",
                ("Hello, {name}.",
                 "{what} ends on {date}. {how}",
                 "Renew before and nothing stops; if not, you have 3 days of grace with full access."),
                "See my membership"),
        values=_membership, sample=(("ends", "2026-11-07T15:00:00+00:00"), ("kind", "paid")),
        stale_param="ends",
    ),
    Template(
        "membership_grace", "membership", ("ends", "kind"), "/profile#membership",
        es=Copy("{what} terminó: tienes 3 días de gracia",
                ("Hola, {name}.",
                 "{what} terminó el {date}. Hasta el {grace} sigues con acceso completo. {how}",
                 "Tus datos siguen aquí. Si no renuevas, después del {grace} podrás ver tu perfil, tus picks "
                 "guardados, la ayuda y tus datos; al renovar vuelve todo."),
                "Ver mi membresía"),
        en=Copy("{what} has ended: you have 3 days of grace",
                ("Hello, {name}.",
                 "{what} ended on {date}. Until {grace} you keep full access. {how}",
                 "Your data stays here. If you do not renew, after {grace} you can see your profile, your saved "
                 "picks, the help and your data; renewing brings everything back."),
                "See my membership"),
        values=_membership, sample=(("ends", "2026-11-07T15:00:00+00:00"), ("kind", "trial")),
        stale_param="ends", stale_grace=timedelta(days=GRACE_DAYS),
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
    sent = SEND_FIELDS if t.grant else frozenset()
    for locale in LOCALES:
        missing = placeholders(t, locale) - ACCOUNT_FIELDS - sent - set(t.values(clean, locale, "UTC"))
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


def render(name: str, locale: Locale, params: Mapping[str, str], account: Mapping[str, str], *, zone: str = "UTC",
           link: str | None = None, until: datetime | None = None) -> Rendered:
    """The message as it leaves: ``params`` from the queue, ``account`` the reader's fields and ``zone`` their time
    zone at this moment. A template with a one-use link takes ``link`` and ``until`` from fbi.auth.tokens.arm; the
    console's preview passes no link (it shows PREVIEW_LINK, never a real one)."""
    t = check_params(name, params)
    if locale not in LOCALES:
        raise TemplateError(f"no language {locale!r}")
    if set(account) != ACCOUNT_FIELDS:
        raise TemplateError(f"account fields {sorted(account)}, expected {sorted(ACCOUNT_FIELDS)}")
    values = {**t.values(params, locale, zone), **{k: str(v).strip() or "—" for k, v in account.items()}}
    if t.grant:
        if until is None:
            raise TemplateError(f"{name}: an e-mail with a one-use link needs the moment it expires")
        values["link"] = PREVIEW_LINK if link is None else link
        values["until"] = moment(until.astimezone(UTC), locale, zone)
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
