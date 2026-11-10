"""``audit.deprecated_api_use`` (migration 0133, BE-033): a call of an endpoint on its way out is one more of the day for its kind
of caller and role; the table takes no user, refuses an unknown kind of caller and goes away on downgrade."""

from __future__ import annotations

import psycopg
import pytest

from fbi.api.services.deprecated import count_use

pytestmark = pytest.mark.integration


def test_calls_add_up_per_day_caller_and_role(db: psycopg.Connection) -> None:
    for _ in range(3):
        count_use(db, "/odds/best", "browser", "USER")
    count_use(db, "/odds/best", "testclient", "SUPER_ADMIN")
    rows = db.execute("SELECT caller, role, calls, first_at <= last_at FROM audit.deprecated_api_use "
                      "WHERE endpoint = '/odds/best' AND day = (now() AT TIME ZONE 'UTC')::date "
                      "ORDER BY caller").fetchall()
    assert rows == [("browser", "USER", 3, True), ("testclient", "SUPER_ADMIN", 1, True)]
    columns = {r[0] for r in db.execute("SELECT column_name FROM information_schema.columns WHERE table_schema = 'audit' "
                                        "AND table_name = 'deprecated_api_use'").fetchall()}
    assert columns == {"day", "endpoint", "caller", "role", "calls", "first_at", "last_at"}


def test_an_unknown_kind_of_caller_is_refused(db: psycopg.Connection) -> None:
    with pytest.raises(psycopg.errors.CheckViolation):
        count_use(db, "/odds/best", "robot", "USER")  # type: ignore[arg-type]
