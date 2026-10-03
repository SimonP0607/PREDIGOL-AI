"""Roles and what they may do.

A role is a row in ``auth.roles``; what it may do is decided here, in code, so that no
permission can be granted by editing a row. A new role is a new row plus a new entry
in ``ROLE_PERMISSIONS`` - the two existing ones are never renamed.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum


class Role(StrEnum):
    SUPER_ADMIN = "SUPER_ADMIN"
    USER = "USER"


class Permission(StrEnum):
    APP = "app"
    """The product: home, matches, live, qualified picks, valid parlays, odds, profile."""
    ADMIN = "admin"
    """The Admin Console and every research, model and system endpoint behind it."""
    MANAGE_USERS = "admin.users"
    """List, create, enable, disable and change the role of accounts."""
    SHADOW_PREVIEW = "admin.shadow_preview"
    """See unqualified (shadow) picks laid out as the product would show them. Never a user's view."""


ROLE_PERMISSIONS: Mapping[Role, frozenset[Permission]] = {
    Role.SUPER_ADMIN: frozenset(Permission),
    Role.USER: frozenset({Permission.APP}),
}


def permissions_for(role: str) -> frozenset[Permission]:
    """Unknown roles get nothing: a role that exists in the database but not here is inert."""
    try:
        return ROLE_PERMISSIONS[Role(role)]
    except ValueError:
        return frozenset()


def is_role(value: str) -> bool:
    return value in Role.__members__.values()
