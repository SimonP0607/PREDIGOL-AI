"""The API's refusal as a value: a status and a code the frontend translates (``fbi.api.errors`` turns it into the HTTP answer).

It lives apart from ``fbi.api.errors`` so that a module which only needs to refuse - a service the worker also reads, like the
structured reading the readers' narrative is written from (plan UX, A11) - loads neither the web framework's handlers nor the
accounts' code. ``fbi.api.errors`` re-exports it: ``from fbi.api.errors import ApiError`` is the same class.
"""

from __future__ import annotations


class ApiError(Exception):
    """A refusal the API means to give: a status and a code the frontend translates."""

    def __init__(self, status: int, code: str, message: str, *, headers: dict[str, str] | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.code = code
        self.message = message
        self.headers = headers or {}
