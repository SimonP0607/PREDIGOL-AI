from __future__ import annotations

from typing import Literal

from fbi.api.contracts.common import Contract


class SearchHit(Contract):
    type: Literal["fixture", "team", "competition"]
    id: int
    label: str
    sublabel: str
