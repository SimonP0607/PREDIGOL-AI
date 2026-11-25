"""Who is signed in, their preferences and security, and the accounts the Admin Console manages."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from fbi.api.contracts.common import Contract
from fbi.api.contracts.customer import ConsentPurpose
from fbi.api.contracts.guides import GuideState
from fbi.api.contracts.membership import MembershipSummary
from fbi.api.contracts.wellbeing import WellbeingState

Language = Literal["es", "en"]
Stage = Literal["mfa", "enroll", "password", "full"]


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=256)


MatrixMode = Literal["off", "show", "on"]


class MatrixModules(BaseModel):
    """What each module does with C-16 (plan PM, PM-14-04): ``off`` decides as it always did, ``show`` reads the matrix and only says
    what it says, ``on`` lets it replace the module's own check. Always ``off`` while ``FBI_AVAILABILITY`` is off."""

    odds: MatrixMode = "off"
    picks: MatrixMode = "off"
    news: MatrixMode = "off"
    parlay: MatrixMode = "off"


class DisplayPrefs(BaseModel):
    """How the reader wants PrediGol shown (plan maestro UX/UI 2026, decision 8). Presentation only."""

    time_format: Literal["24h", "12h"] = "24h"
    odds_format: Literal["decimal", "american", "fractional"] = Field(
        default="decimal", description="How a price is written. What is stored, computed and sent stays decimal.")
    reduce_motion: bool = Field(default=False, description="Fewer animations whatever the device says.")
    home_default: Literal["mine", "all"] | None = Field(
        default=None, description="The view Inicio opens on; null: «Para ti» for a reader who follows something.")


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
    welcome_due: bool = Field(default=False, description="The account still owes its welcome (plan UX, A13; FBI_ONBOARDING): "
                                                         "the page opens /welcome after the consents. Readers only, once.")
    welcome_steps: list[str] = Field(default_factory=list, description="football (the favourites) and, for a new account, "
                                                                       "about («Qué es PrediGol»).")
    hints_seen: list[str] = Field(default_factory=list, description="The first-visit hints the reader dismissed (picks, match, "
                                                                    "parlay, my_picks): never shown again.")
    guides: list[GuideState] = Field(default_factory=list, description="What the reader has seen of the welcome tour and of "
                                                                       "the guides of each screen (UX-032): one entry per "
                                                                       "guide they have a row for.")
    guides_on: bool = Field(default=True, description="FBI_GUIDES: the page shows guides (on unless the owner turned it off).")
    guides_auto: bool = Field(default=True, description="The reader's own switch: the guide of each screen on the first visit.")
    transparency: bool = Field(default=False, description="«Cómo le va a PrediGol» is open to readers (plan UX, A12; "
                                                          "FBI_TRANSPARENCY, off until the owner reviewed it): the page "
                                                          "links to it only then.")
    support: bool = Field(default=False, description="A reader can write to PrediGol from the page (plan UX, A14; "
                                                     "FBI_SUPPORT, on unless the owner turned it off): «Reportar un "
                                                     "problema» in Ayuda, in an error and in a match.")
    explain: bool = Field(default=False, description="«Explícame» answers the frequent questions of a match, a pick and "
                                                     "the parlay being built (plan UX, B9; FBI_EXPLAIN, on unless the "
                                                     "owner turned it off): the page shows its buttons only then.")
    odds_explorer: bool = Field(default=False, description="The new Cuotas explorer (plan Cuotas, BE-011/UX-068; "
                                                           "FBI_ODDS_EXPLORER, off until the owner verified it): the page "
                                                           "shows it only then, and the current Cuotas page otherwise.")
    odds_status: bool = Field(default=False, description="«Estado de los precios» is open to readers (plan maestro UX/UI "
                                                         "2026, decision 4; FBI_ODDS_STATUS, off by default): the page "
                                                         "links to it only then.")
    news_feed: bool = Field(default=False, description="The Noticias section is open to readers (plan maestro UX/UI "
                                                       "2026, decision 2; FBI_NEWS_FEED, off by default, and the "
                                                       "news shown to users): the page links to it only then.")
    inbox: bool = Field(default=False, description="«Avisos», the reader's inbox, is open (plan maestro UX/UI 2026, "
                                                   "decision 1; FBI_INBOX, off by default): the page shows its bell "
                                                   "only then.")
    odds_by_match: bool = Field(default=False, description="Cuotas opens on the view by match (plan maestro unificado, "
                                                           "UX-141; FBI_ODDS_BY_MATCH, off by default).")
    nav_v2: bool = Field(default=False, description="The bars of the unified plan (UX-152, decisions D-01 and D-02; "
                                                    "FBI_NAV_V2, off by default).")
    search: bool = Field(default=False, description="The readers' global search in the top bar (UX-153; FBI_SEARCH, off "
                                                    "by default).")
    profiles: bool = Field(default=False, description="The pages of a club, a national team and a player, and «Equipos» "
                                                      "(UX-154 to UX-157; FBI_PROFILES, off by default).")
    news_v2: bool = Field(default=False, description="Noticias as maquetas 08-10 draw it (UX-158 to UX-160; FBI_NEWS_V2, "
                                                     "off by default, and only with the Noticias section open).")
    match_intelligence: bool = Field(default=False, description="A match's «Intelligence» tab for readers (UX-162 to "
                                                                "UX-166; FBI_MATCH_INTELLIGENCE, off by default).")
    stats_v2: bool = Field(default=False, description="The advanced statistics: profiles, comparisons and the Match Center's "
                                                      "statistics (plan EA, C-13; FBI_STATS_V2, off by default).")
    market_probs: bool = Field(default=False, description="The probabilities by market of a match (plan EA, C-14; "
                                                          "FBI_MARKET_PROBS, off by default).")
    parlay_markets_v2: bool = Field(default=False, description="Mi parlay accepts every market the catalogue settles (plan EA, "
                                                               "EA-501; FBI_PARLAY_MARKETS_V2, off by default).")
    player_markets: bool = Field(default=False, description="The players' markets of a match (plan EA, C-15; "
                                                            "FBI_PLAYER_MARKETS, off by default).")
    match_shot_funnel: bool = Field(default=False, description="The Match Center's shot funnel and its two shot zones (plan PM, "
                                                               "PM-10-01, lámina I01; FBI_MATCH_SHOT_FUNNEL, off by default).")
    match_balance: bool = Field(default=False, description="The Match Center's balance and strip of the score's state (plan PM, "
                                                           "PM-10-02, lámina I01; FBI_MATCH_BALANCE, off by default).")
    lineup_layers: bool = Field(default=False, description="The data layers of the line-up pitch (plan PM, PM-10-04, lámina I02; "
                                                           "FBI_LINEUP_LAYERS, off by default).")
    match_coverage: bool = Field(default=False, description="The Match Center adapted to the coverage levels of C-16: tabs and "
                                                            "blocks by level (plan PM, PM-14-02; FBI_MATCH_COVERAGE, off by "
                                                            "default; it reads C-16, so FBI_AVAILABILITY too).")
    prob_icons: bool = Field(default=False, description="The result forecast also in 100 icons, with «Mito o dato» (plan PM, "
                                                        "PM-10-07, lámina I09; FBI_PROB_ICONS, off by default).")
    availability: bool = Field(default=False, description="What PrediGol has per competition, datum and market (plan PM, C-16; "
                                                          "FBI_AVAILABILITY, off by default): the states «información no "
                                                          "disponible» and the owner's console of the matrix only then.")
    usage_console: bool = Field(default=False, description="The owner's console of the provider's requests by lane, endpoint and "
                                                           "competition (plan PM, PM-04-05; FBI_USAGE_CONSOLE, off by default).")
    competition_page: bool = Field(default=False, description="A competition's page: tables, calendar, leaders and coverage "
                                                              "(plan PM, PM-09-04; FBI_COMPETITION_PAGE, off by default).")
    competition_tables: bool = Field(default=False, description="The season tables computed from the regulation on a "
                                                                "competition's page (plan PM, PM-09-01; FBI_COMPETITION_TABLES, "
                                                                "off until the owner signs DOC-008 and DM-14).")
    competition_directory: bool = Field(default=False, description="The world directory of competitions with level and priority "
                                                                   "(plan PM, PM-09-05; FBI_COMPETITION_DIRECTORY, off by default).")
    player_profile_extras: bool = Field(default=False, description="The player's profile with the new data, the goalkeeper's "
                                                                   "included (plan PM, PM-08-06; FBI_PLAYER_PROFILE_EXTRAS, off "
                                                                   "by default).")
    what_if: bool = Field(default=False, description="The calculator «¿Qué pasa si…?» of a competition's tables (plan PM, "
                                                     "PM-09-03; FBI_WHAT_IF, off until the owner signs DM-14).")
    home_unified: bool = Field(default=False, description="One Inicio for everyone, with the «Tus favoritos» strip (plan de correcciones UX, AP-I01, decision D1) (FBI_HOME_UNIFIED, off by default).")
    match_halves: bool = Field(default=False, description="A match's statistics by half in the Match Center (plan PM, PM-10-03) (FBI_MATCH_HALVES, off by default).")
    markets_v3: bool = Field(default=False, description="A match's markets as a bookmaker lays them out (plan de correcciones UX, AP-P08, decision D6) (FBI_MARKETS_V3, off by default).")
    day_highlights: bool = Field(default=False, description="«Lo más interesante de hoy» on days without picks (plan de correcciones UX, AP-K04, decision D2) (FBI_DAY_HIGHLIGHTS, off by default).")
    my_books: bool = Field(default=False, description="«Mis casas»: the bookmakers the reader plays at, in Perfil, Mercados and Cuotas (plan de correcciones UX, AP-P10, decision D5) (FBI_MY_BOOKS, off by default).")
    stakes: bool = Field(default=False, description="Variable units on picks, parlays, Mis picks and Transparencia (plan de correcciones UX, AP-K07, decision D3) (FBI_STAKES, off by default).")
    trend_builder: bool = Field(default=False, description="The parlay builder «Por tendencias» (plan de correcciones UX, AP-L02, decision D7) (FBI_TREND_BUILDER, off by default).")
    transparency_export: bool = Field(default=False, description="The download of the published picks (CSV and JSON, with the calibration and its uncertainty) in «Cómo le va a PrediGol» (plan PM, PM-14-08; FBI_TRANSPARENCY_EXPORT, off by default; it needs the page open).")
    matrix_modules: MatrixModules = Field(default_factory=MatrixModules, description=(
        "What Cuotas, Picks, Noticias and Mi parlay do with C-16 (plan PM, PM-14-04; FBI_MATRIX_ODDS, FBI_MATRIX_PICKS, FBI_MATRIX_NEWS, "
        "FBI_MATRIX_PARLAY: off by default; show: they read the matrix and only say what it says; on: it replaces their own check)."))
    wellbeing: WellbeingState = Field(default_factory=WellbeingState, description="What the reader chose about seeing prices (plan PM, PM-14-07; FBI_WELLBEING, off by default): «solo fútbol» and the voluntary pause; ``available`` False while the choice is not open.")
    display: DisplayPrefs = Field(default_factory=DisplayPrefs, description="The reader's settings of presentation "
                                                                            "(decision 8): clock, price format, "
                                                                            "motion and Inicio's view.")


class PreferencesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    language: Language | None = None
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    display_name: str | None = Field(default=None, min_length=1, max_length=80)
    guides_auto: bool | None = Field(default=None, description="Show the guide of each screen on the first visit (UX-032).")
    time_format: Literal["24h", "12h"] | None = None
    odds_format: Literal["decimal", "american", "fractional"] | None = None
    reduce_motion: bool | None = None
    home_default: Literal["mine", "all", "auto"] | None = Field(
        default=None, description="mine or all; auto goes back to the rule (mine for a reader who follows something).")


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
    status: Literal["active", "disabled", "invited", "deleted", "pending"] = Field(
        description="pending: registered by the person, the address not yet confirmed (UX-038); invited: created by an invitation, not activated yet; deleted: anonymised at the reader's "
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
    signup: bool = Field(default=False, description="A person may create their own account (FBI_SIGNUP on and every "
                                                    "lock behind it closed): the sign-in page offers «Crear cuenta».")


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


class SignupConsentIn(BaseModel):
    """One consent ticked on the registration form, with the version of the text the person was shown."""

    model_config = ConfigDict(extra="forbid")
    kind: Literal["terms", "privacy", "age_18", "risk_notice", "marketing_email", "analytics"]
    granted: bool
    version: str = Field(min_length=10, max_length=34)


class SignupConsents(Contract):
    """The boxes of the registration form: the required consents with their exact sentences and current versions."""

    purposes: list[ConsentPurpose]


class SignupIn(BaseModel):
    """The registration form (tramo 1, UX-038). The four required consents travel with it, each with its version."""

    model_config = ConfigDict(extra="forbid")
    first_name: str = Field(max_length=120)
    last_name: str = Field(max_length=120)
    email: str = Field(min_length=1, max_length=254)
    phone: str = Field(max_length=40, description="A mobile number; without a country code, Colombian.")
    nickname: str = Field(max_length=60, description="Unique, 3 to 24 characters.")
    password: str = Field(min_length=1, max_length=256)
    language: str = Field(max_length=8, description="es or en: refused with invalid_language otherwise.")
    timezone: str = Field(default="America/Bogota", max_length=64)
    consents: list[SignupConsentIn] = Field(max_length=6)


class VerifyInfo(Contract):
    email: str
    display_name: str
    language: Language


class VerifyIn(TokenIn):
    """The confirmation link's token and the password the person chose when registering - or, with
    ``replace_password``, a NEW one that replaces it (the person no longer remembers the first)."""

    password: str = Field(min_length=1, max_length=256)
    replace_password: bool = False


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
    trial_days: int | None = Field(default=None, ge=7, le=20, description="The trial this account gets when it is "
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
