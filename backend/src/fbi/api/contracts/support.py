"""A reader's questions to PrediGol and the owner's inbox (plan UX, A14): what the page reads and sends. A ticket never
carries a password, a token, an address or what a form held; the reader's own address is on the owner's view only."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from fbi.api.contracts.common import Contract

SupportCategory = Literal["access", "account", "technical", "wrong_data", "suggestion", "complaint"]
TicketCategory = Literal["access", "account", "technical", "wrong_data", "suggestion", "complaint", "privacy"]
Priority = Literal["urgent", "high", "medium", "low"]
TicketStatus = Literal["open", "answered", "closed"]
Channel = Literal["web", "email", "whatsapp"]
Author = Literal["customer", "owner", "system"]
Device = Literal["phone", "tablet", "desktop"]
FirstAnswer = Literal["same_day", "24h", "48h", "week"]
InboxStatus = Literal["open", "waiting", "answered", "closed", "all"]


class SupportContext(Contract):
    route: str | None = Field(default=None, description="The screen's path, without its query.")
    request_id: str | None = Field(default=None, description="The request id of the last error the page met (plan UX, "
                                                             "A2): the server's log line of that error.")
    web_version: str | None = None
    device: Device | None = None
    pwa: bool | None = Field(default=None, description="True: the installed app; false: a browser tab.")
    match_id: int | None = Field(default=None, description="The match a «wrong data» report is about.")


class SupportContextIn(BaseModel):
    """What the page attaches; the server checks every key again (fbi.customer.support.clean_context)."""

    model_config = ConfigDict(extra="forbid")

    route: str | None = Field(default=None, max_length=200)
    request_id: str | None = Field(default=None, max_length=32)
    web_version: str | None = Field(default=None, max_length=40)
    device: Device | None = None
    pwa: bool | None = None
    match_id: int | None = Field(default=None, ge=1)


class SupportMessage(Contract):
    author: Author
    body: str
    at: datetime
    channel: Channel = Field(description="web: written in PrediGol; email / whatsapp: what the owner noted from a talk "
                                         "there.")


class SupportTicket(Contract):
    id: int
    category: SupportCategory
    priority: Priority
    status: TicketStatus = Field(description="open: waiting for PrediGol; answered: PrediGol answered; closed.")
    opened_at: datetime
    respond_by: datetime | None = Field(description="When the first answer is due (section 32); null once one came.")
    answered: bool = Field(description="PrediGol has answered at least once.")
    closed_at: datetime | None
    effort: int | None = Field(description="The reader's answer on how easy it was, 1 to 5; asked once it is closed.")
    messages: list[SupportMessage]


class SupportCategoryInfo(Contract):
    category: SupportCategory
    priority: Priority
    first_answer: FirstAnswer


class SupportContact(Contract):
    whatsapp: str | None = Field(description="The WhatsApp Business number, digits with the country code "
                                             "(FBI_SUPPORT_WHATSAPP, P7 of the plan); null until the owner gives it.")
    email: str | None = Field(description="The address a reader's e-mail reaches (FBI_EMAIL_REPLY_TO); null if none.")


class SupportState(Contract):
    enabled: bool = Field(description="FBI_SUPPORT: false - no new ticket or message; the help centre, the contact and "
                                      "the privacy requests stay, and the tickets already written can be read.")
    contact: SupportContact
    categories: list[SupportCategoryInfo] = Field(description="In the order the reader is offered them.")
    tickets: list[SupportTicket] = Field(description="The reader's own, open first, newest first.")
    max_text: int
    max_open: int


class TicketIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: SupportCategory
    text: str = Field(min_length=1, max_length=2000)
    context: SupportContextIn | None = None


class TicketReplyIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str = Field(min_length=1, max_length=2000)


class TicketCloseIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    effort: int | None = Field(default=None, ge=1, le=5)


class TicketEffortIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    effort: int = Field(ge=1, le=5)


# ── the owner ────────────────────────────────────────────────────────────────────────

class AdminTicket(Contract):
    id: int
    user_id: int
    email: str
    display_name: str
    account_status: str = Field(description="The account's state now (a deleted one: nobody is left to answer).")
    kind: str = Field(description="support, or the privacy request's kind (privacy_query / _claim / _deletion).")
    category: TicketCategory
    priority: Priority
    status: TicketStatus
    opened_at: datetime
    closed_at: datetime | None
    respond_by: datetime | None = Field(description="A support ticket's target for its first answer.")
    deadline: date | None = Field(description="A privacy request's legal deadline (with the one extension, if used).")
    extended: bool = Field(description="A privacy request's one extension was used.")
    first_answer_at: datetime | None
    waiting: bool = Field(description="Waiting for PrediGol (status open).")
    late: bool = Field(description="Past the target of its first answer with none yet, or past its legal deadline.")
    context: SupportContext | None
    effort: int | None
    messages: list[SupportMessage]


class SupportCounts(Contract):
    open: int = Field(description="Not closed.")
    waiting: int = Field(description="Waiting for PrediGol.")
    late: int
    urgent: int = Field(description="Urgent tickets waiting.")


class AdminInbox(Contract):
    counts: SupportCounts
    tickets: list[AdminTicket]


class TicketAnswerIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    body: str = Field(min_length=1, max_length=4000)
    status: TicketStatus = "answered"
    channel: Channel = Field(default="web", description="web: the reader is told by e-mail; email / whatsapp: a note of "
                                                        "what was said there (no e-mail).")
