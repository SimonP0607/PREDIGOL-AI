"""The reader's account centre in one read (plan UX, B1; section 21): what each of the profile's eight blocks says while
it is folded - Cuenta, Fútbol, Idioma y zona, Notificaciones, Privacidad, Seguridad, Membresía and Ayuda. Each block's
own page part reads its details when it opens; this answer only summarises, and only the reader's own account.

Never an internal word (a role, a shadow state, a set's name): the page says the account's state in words from these
fields.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import Field

from fbi.api.contracts.common import Contract
from fbi.api.contracts.membership import MembershipSummary
from fbi.api.contracts.messaging import EmailStatus


class AccountBlock(Contract):
    display_name: str = Field(description="The alias the reader chose (PATCH /auth/me/preferences changes it).")
    email: str
    created_at: datetime | None = Field(description="When the account was made: «En PrediGol desde …» (None only for a "
                                                 "session whose account row cannot be read).")
    admin: bool = Field(description="The owner's account: the page says «Administrador», never a role's code.")


class RegionBlock(Contract):
    language: str
    timezone: str = Field(description="IANA name; the page writes it in words.")


class FootballBlock(Contract):
    leagues: int = Field(description="Leagues followed: the reader's own, or the suggested ones while none is chosen.")
    teams: int
    suggested: bool = Field(description="Nothing chosen yet: these are the suggested ones for Colombia (A13).")


class NotificationsBlock(Contract):
    email_on: int = Field(description="E-mail categories on, the mandatory ones included.")
    email_total: int
    email_status: EmailStatus = Field(description="ok, or why e-mail stopped for this address (a hard bounce, a "
                                                  "complaint).")
    sending: bool = Field(description="Whether PrediGol sends e-mail at all now (FBI_EMAIL_SEND): off, the page says "
                                      "the messages wait.")


class PrivacyBlock(Contract):
    consents_due: list[str] = Field(description="Purposes owed while the consent gate is on; empty otherwise.")
    consents_at: datetime | None = Field(description="The reader's latest consent decision.")
    open_requests: int = Field(description="Privacy requests still open (a copy, a correction, a deletion…).")
    next_deadline: date | None = Field(description="The nearest legal deadline among the open requests.")


class SecurityBlock(Contract):
    mfa_enabled: bool
    sessions: int = Field(description="Sessions open now, this one included.")
    last_sign_in_at: datetime | None
    password_changed_at: datetime | None


class HelpBlock(Contract):
    waiting: int = Field(description="The reader's messages waiting for PrediGol's answer.")
    answered: int = Field(description="Messages PrediGol answered that the reader has not closed.")
    whatsapp: bool = Field(description="Whether Ayuda shows a WhatsApp number (P7).")
    support: bool = Field(description="Whether the reader can write to PrediGol (FBI_SUPPORT).")


class AccountSummary(Contract):
    account: AccountBlock
    region: RegionBlock
    football: FootballBlock
    notifications: NotificationsBlock
    privacy: PrivacyBlock
    security: SecurityBlock
    membership: MembershipSummary | None = Field(description="None for the owner's accounts (no membership).")
    help: HelpBlock
