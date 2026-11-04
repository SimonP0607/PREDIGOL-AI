"""The readers' notices on their devices over HTTP (plan UX, B7; section 34). Mirrored by web/src/lib/api/v1/types_push.ts."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Family = Literal["chrome", "firefox", "safari", "edge", "other"]
System = Literal["android", "ios", "windows", "macos", "linux", "other"]


class PushDevice(BaseModel):
    """A browser the reader allowed (never the push service's address nor the keys)."""

    id: int
    family: Family
    system: System
    installed: bool = Field(description="Subscribed from the installed app (an iPhone needs it).")
    created_at: datetime
    last_ok_at: datetime | None = Field(description="The last notice its push service took.")


class PushCategories(BaseModel):
    result: bool = Field(description="The result of what the reader saved.")
    lineup: bool = Field(description="The line-ups of the teams the reader follows.")
    digest: bool = Field(description="The day's summary of their teams and leagues, once a day at most.")
    account: bool = Field(description="Their account: the membership's end, a new sign-in.")


class PushState(BaseModel):
    available: bool = Field(description="FBI_PUSH on and PrediGol's VAPID key set (P12): false hides every invitation.")
    public_key: str | None = Field(description="The application server key the browser subscribes with (base64url).")
    devices: list[PushDevice]
    categories: PushCategories
    quiet_start: str = Field(description="The quiet hours, in the reader's zone: what falls inside waits.")
    quiet_end: str
    daily_cap: int = Field(description="At most this many results, line-ups and summaries a day.")


class PushKeys(BaseModel):
    model_config = ConfigDict(extra="forbid")

    p256dh: str = Field(min_length=86, max_length=90)
    auth: str = Field(min_length=21, max_length=26)


class PushSubscribeIn(BaseModel):
    """``PushSubscription.toJSON()`` of the browser, with what the page knows of it."""

    model_config = ConfigDict(extra="forbid")

    endpoint: str = Field(min_length=12, max_length=1024)
    keys: PushKeys
    family: Family = "other"
    system: System = "other"
    installed: bool = False


class PushUnsubscribeIn(BaseModel):
    """This browser (its address) or another of the list (its id)."""

    model_config = ConfigDict(extra="forbid")

    endpoint: str | None = Field(default=None, max_length=1024)
    device_id: int | None = Field(default=None, ge=1)


class PushCategoriesIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result: bool | None = None
    lineup: bool | None = None
    digest: bool | None = None
    account: bool | None = None


class PushTestOut(BaseModel):
    id: int


class MatchAlert(BaseModel):
    """The bell of a match for this reader."""

    fixture_id: int
    on: bool
    minutes_before: int | None
    kickoff_at: datetime | None


class MatchAlertIn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    minutes_before: Literal[15, 30, 60] = 30


class PushFamilyCount(BaseModel):
    family: Family
    system: System
    devices: int


class PushCategoryCount(BaseModel):
    category: Literal["result", "lineup", "digest", "reminder", "account", "test"]
    sent: int
    dropped: int


class PushOverview(BaseModel):
    """The owner's view (/admin/product): live devices and the last 7 days of notices - counts, never who."""

    available: bool
    readers: int = Field(description="Readers with at least one live device.")
    devices: list[PushFamilyCount]
    notices: list[PushCategoryCount]
    gone: int = Field(description="Devices their push service dropped in the last 7 days (404/410).")
