"""The legal texts, a reader's consents, their export and their privacy requests (plan UX, A4)."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from fbi.api.contracts.common import Contract

Language = Literal["es", "en"]
LegalDocumentName = Literal["terms", "privacy", "responsible_gaming"]
ConsentKind = Literal["terms", "privacy", "age_18", "risk_notice", "marketing_email", "analytics"]
"""The four the gate asks for and the two optional ones: the weekly summary by e-mail (plan UX, B8), offered only while it
can reach the reader, and the usage statistics under a pseudonym (plan de cierre UX, 1.2), always offered."""
RequestKind = Literal["privacy_query", "privacy_claim", "privacy_deletion"]
TicketStatus = Literal["open", "answered", "closed"]


class LegalBlock(Contract):
    p: str | None = Field(default=None, description="A paragraph.")
    ul: list[str] | None = Field(default=None, description="A bulleted list.")


class LegalSection(Contract):
    id: str = Field(description="Stable across languages and versions: the page's anchor.")
    title: str
    blocks: list[LegalBlock]


class LegalVersion(Contract):
    version: str
    date: date
    draft: bool
    material: bool = Field(description="True: every reader had to accept this version again.")
    changes: str = Field(description="What changed, in the requested language.")
    sha256: str = Field(description="Of this version's text in the requested language.")


class LegalDocument(Contract):
    document: LegalDocumentName
    locale: Language
    version: str
    date: date
    draft: bool = Field(description="Pending the lawyer's written OK (P5): the page says it is not in force yet.")
    title: str
    summary: str
    sections: list[LegalSection]
    sha256: str = Field(description="sha256 of the canonical form of exactly this text (fbi.customer.legal).")
    history: list[LegalVersion] = Field(description="Every version, newest first.")


class ConsentPurpose(Contract):
    kind: ConsentKind
    document: LegalDocumentName
    version: str = Field(description="The current version of its document: the one a decision must name.")
    sha256: str
    statement: str = Field(description="The box's sentence, in the requested language.")
    required: bool
    withdrawable: bool
    changes: str | None = Field(default=None, description="When the reader accepted an older version a material "
                                                          "change replaced: what changed.")


class ConsentRecord(Contract):
    kind: str
    granted: bool
    document: str
    version: str
    sha256: str
    locale: str
    statement: str
    source: str
    at: datetime


class ConsentState(Contract):
    gate: bool = Field(description="Whether the consent gate is on for this account (off: switch off, drafts, or an "
                                   "exempt account).")
    due: list[ConsentKind] = Field(description="The purposes to accept before using PrediGol (when the gate is on).")
    purposes: list[ConsentPurpose]
    history: list[ConsentRecord] = Field(description="Every decision, newest first.")


class ConsentDecisionIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: ConsentKind
    granted: bool
    version: str = Field(min_length=10, max_length=34, description="The version of the text the reader was shown.")


class ConsentsIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decisions: list[ConsentDecisionIn] = Field(min_length=1, max_length=8)
    locale: Language
    source: Literal["gate", "profile", "activation"] = Field(
        default="gate", description="activation: the gate shown right after /activate (plan UX, A7) - recorded as "
                                    "such only within an hour of the account's activation, as gate otherwise.")


class ReauthIn(BaseModel):
    """The account's own password again, and its second factor's code when it has one."""

    model_config = ConfigDict(extra="forbid")
    password: str = Field(min_length=1, max_length=256)
    code: str | None = Field(default=None, max_length=12)


class PrivacyRequestIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: RequestKind
    message: str = Field(min_length=1, max_length=4000)
    password: str | None = Field(default=None, max_length=256, description="A deletion request only.")
    code: str | None = Field(default=None, max_length=12, description="A deletion request only, with MFA.")


class TicketMessage(Contract):
    author: Literal["customer", "owner", "system"]
    body: str
    at: datetime


class PrivacyRequest(Contract):
    id: int
    kind: RequestKind
    status: TicketStatus
    opened_at: datetime
    due_on: date | None
    extended_to: date | None
    deadline: date | None = Field(description="extended_to when the one extension was used, due_on otherwise.")
    closed_at: datetime | None
    messages: list[TicketMessage]


class AdminPrivacyRequest(PrivacyRequest):
    user_id: int
    email: str


class PrivacyAnswerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    body: str = Field(min_length=1, max_length=4000)
    status: TicketStatus = "answered"
    extend: bool = Field(default=False, description="Use the one extension the law allows (5 or 8 business days "
                                                    "more); the message must say why and until when.")


ExportDocument = dict[str, Any]
