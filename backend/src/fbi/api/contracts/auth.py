"""Who is signed in, their preferences and security, and the accounts the Admin Console manages."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from fbi.api.contracts.common import Contract
from fbi.api.contracts.membership import MembershipSummary

Language = Literal["es", "en"]
Stage = Literal["mfa", "enroll", "password", "full"]


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


class Me(Contract):
    id: int
    email: str
    display_name: str
    role: str
    permissions: list[str]
    language: Language
    timezone: str = Field(description="IANA time zone every time on screen is shown in. Stored data stays UTC.")
    session_expires_at: datetime
    session_idle_hours: int = Field(default=0, description="A session not used for this long ends: every use gives it "
                                                            "this long again, never past session_expires_at (7 days "
                                                            "for a user, 8 hours for the owner's console).")
    stage: Stage = Field(default="full", description="full: signed in. mfa / enroll / password: a step of signing "
                                                     "in is still owed, and nothing else is reachable until it is done.")
    mfa_enabled: bool = False
    mfa_required: bool = Field(default=False, description="This account must use a second factor (its role or the "
                                                          "owner's choice): it cannot be turned off.")
    must_change_password: bool = False
    recovery_codes_left: int = 0
    observability_id: str | None = Field(default=None, description="The pseudonym this account's errors carry to "
                                                                    "Sentry: an HMAC of its id under the server's "
                                                                    "key, never the id or the email (plan UX, A2). "
                                                                    "Null when the server has no key.")
    consents_due: list[str] = Field(default_factory=list, description="The consents the reader must accept before "
                                                                      "using the product (plan UX, A4): empty while "
                                                                      "the gate is off or nothing is owed. Filled by "
                                                                      "GET /auth/me; a 403 consent_required elsewhere "
                                                                      "means: ask /auth/me again.")
    membership: MembershipSummary | None = Field(default=None, description="The account's membership now (plan UX, "
                                                                           "A8), filled by GET /auth/me: None for "
                                                                           "the owner's accounts (no membership).")
    transparency: bool = Field(default=False, description="«Cómo le va a PrediGol» is open to readers (plan UX, A12; "
                                                          "FBI_TRANSPARENCY, off until the owner reviewed it): the page "
                                                          "links to it only then.")


class PreferencesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: Language | None = None
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    display_name: str | None = Field(default=None, min_length=1, max_length=80)


class PasswordChangeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str = Field(min_length=1, max_length=256)
    new_password: str = Field(min_length=1, max_length=256)


class RequiredPasswordIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    new_password: str = Field(min_length=1, max_length=256)


class MfaVerifyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str | None = Field(default=None, max_length=12)
    recovery_code: str | None = Field(default=None, max_length=24)


class MfaStartIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str | None = Field(default=None, max_length=256,
                                 description="Asked again when enrolling from a signed-in session.")


class MfaCodeIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(min_length=6, max_length=12)


class MfaGuardedIn(BaseModel):
    """Turning the second factor off, or renewing the recovery codes: the password and a current code."""

    model_config = ConfigDict(extra="forbid")

    password: str = Field(min_length=1, max_length=256)
    code: str | None = Field(default=None, max_length=12)


class MfaEnrollment(Contract):
    secret: str = Field(description="Base32, in groups of four - for an app that cannot scan.")
    otpauth_uri: str
    qr_svg: str = Field(description="The same URI as a QR code (an SVG data URI), drawn on the server.")
    issuer: str
    account: str


class MfaEnrolled(Contract):
    me: Me
    recovery_codes: list[str] = Field(description="Shown once. Each works once, in place of a code.")


class RecoveryCodes(Contract):
    recovery_codes: list[str]


class SessionInfo(Contract):
    id: str = Field(description="The first 16 hex characters of the session's hash: enough to name it, never usable.")
    created_at: datetime
    last_seen_at: datetime
    expires_at: datetime
    ip: str | None
    user_agent: str | None
    stage: Stage
    mfa_verified: bool
    current: bool


class AccessEvent(Contract):
    at: datetime
    action: str
    ip: str | None
    user_agent: str | None
    reason: str | None


class AdminUser(Contract):
    id: int
    email: str
    display_name: str
    role: str
    status: Literal["active", "disabled", "invited", "deleted"] = Field(
        description="invited: created by an invitation, not activated yet; deleted: anonymised at the reader's "
                    "request (plan UX, A7) - its address is masked and nothing about it changes any more.")
    language: Language
    timezone: str
    created_at: datetime
    last_login_at: datetime | None
    active_sessions: int
    mfa_enabled: bool = False
    mfa_required: bool = False
    must_change_password: bool = False
    locked_until: datetime | None = None
    failed_logins: int = 0
    recovery_codes_left: int = 0
    membership: MembershipSummary | None = Field(default=None, description="The membership now (plan UX, A8): read "
                                                                           "by the list; None for the owner's "
                                                                           "accounts and in the answer to an action "
                                                                           "(the console reads the list again).")


class AdminUserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=254)
    display_name: str | None = Field(default=None, max_length=80)
    role: str = Field(default="USER", max_length=32)
    password: str = Field(min_length=1, max_length=256)
    language: Language = "es"
    timezone: str = Field(default="UTC", max_length=64)
    must_change_password: bool = Field(default=True, description="The account chooses its own password at its "
                                                                 "first sign-in.")
    mfa_required: bool = False


class AdminUserPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str | None = Field(default=None, max_length=32)
    status: Literal["active", "disabled"] | None = None
    mfa_required: bool | None = None


class AdminPasswordReset(BaseModel):
    model_config = ConfigDict(extra="forbid")

    password: str | None = Field(default=None, max_length=256,
                                 description="Empty: a temporary password is generated and returned once.")


class AdminPasswordResult(Contract):
    user: AdminUser
    temporary_password: str | None = Field(description="Only when it was generated: shown once, never stored.")


class AuditEvent(Contract):
    id: int
    at: datetime
    action: str
    actor_email: str | None
    target_email: str | None
    email: str | None = Field(description="The address that was tried, for sign-ins of unknown accounts.")
    ip: str | None
    detail: dict[str, Any]


# ── account and access (plan UX, A7) ──────────────────────────────────────────────────

class AccountOptions(Contract):
    self_service: bool = Field(description="Invitations, password recovery and unlocking by e-mail are on "
                                           "(FBI_SELF_SERVICE). Off, the owner gives accounts a temporary password.")


class TokenIn(BaseModel):
    """A one-use link's token, as the page read it from the link's fragment (#t=...): never in a URL the server
    sees."""

    model_config = ConfigDict(extra="forbid")

    token: str = Field(min_length=1, max_length=128)


class ActivationInfo(Contract):
    email: str
    display_name: str
    language: Language
    timezone: str


class ActivateIn(TokenIn):
    password: str = Field(min_length=1, max_length=256)
    language: Language
    timezone: str = Field(min_length=1, max_length=64)


class EmailIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=1, max_length=254)


class ResetInfo(Contract):
    email: str
    mfa: bool = Field(description="The account has a second factor: a code from its app (or a recovery code) is "
                                  "asked with the new password (R25 of the security plan).")


class ResetIn(TokenIn):
    password: str = Field(min_length=1, max_length=256)
    code: str | None = Field(default=None, max_length=12)
    recovery_code: str | None = Field(default=None, max_length=24)


class IdentityIn(BaseModel):
    """Ending another session of one's own account: the password, or a code of the second factor (ASVS 7.5.2; R25 of
    the security plan) - either is enough. Not needed to end the session in use (that is signing out)."""

    model_config = ConfigDict(extra="forbid")

    password: str | None = Field(default=None, max_length=256)
    code: str | None = Field(default=None, max_length=12)


class Accepted(Contract):
    status: Literal["accepted"] = Field(default="accepted", description="Always the same answer: whether or not the "
                                                                        "address has an account, whether or not an "
                                                                        "e-mail leaves.")


class AdminInviteIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=254)
    display_name: str | None = Field(default=None, max_length=80)
    language: Language = "es"
    timezone: str = Field(default="America/Bogota", max_length=64)
    trial_days: int | None = Field(default=None, ge=7, le=14, description="The trial this account gets when it is "
                                                                          "activated (plan UX, A8); FBI_TRIAL_DAYS "
                                                                          "by default.")


class AdminAnonymiseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirm: str = Field(min_length=3, max_length=254, description="The account's address, typed again.")


class AdminAnonymised(Contract):
    user: AdminUser
    picks: int
    parlays: int
    sessions: int
    messages_dropped: int = Field(description="Messages still queued for the reader that will not be sent.")
    trail_rows: int = Field(description="Rows of the sign-in trail whose typed address was masked.")


class SelfServiceState(Contract):
    self_service: bool
    email_sending: bool = Field(description="FBI_EMAIL_SEND: off, invitations wait in the queue.")
