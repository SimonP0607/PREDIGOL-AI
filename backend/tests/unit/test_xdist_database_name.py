"""CI-014 - each pytest-xdist worker has its own test database, and a plain run keeps the name it always had."""

from __future__ import annotations

import pytest

from tests.integration.conftest import database_name_for


@pytest.mark.parametrize(
    ("base", "worker", "expected"),
    [("fbi_test", None, "fbi_test"), ("fbi_test", "", "fbi_test"), ("fbi_test", "gw0", "fbi_test_gw0"), ("mine", "gw12", "mine_gw12")],
)
def test_database_name_per_xdist_worker(base: str, worker: str | None, expected: str) -> None:
    assert database_name_for(base, worker) == expected


def test_two_workers_never_share_a_database() -> None:
    names = {database_name_for("fbi_test", f"gw{n}") for n in range(8)}
    assert len(names) == 8 and "fbi_test" not in names
