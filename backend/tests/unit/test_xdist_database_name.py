"""CI-014 - each pytest-xdist worker has its own test database, and a plain run keeps the name it always had."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.integration.conftest import SERIAL_FILES, database_name_for


@pytest.mark.parametrize(
    ("base", "worker", "expected"),
    [("fbi_test", None, "fbi_test"), ("fbi_test", "", "fbi_test"), ("fbi_test", "gw0", "fbi_test_gw0"), ("mine", "gw12", "mine_gw12")],
)
def test_database_name_per_xdist_worker(base: str, worker: str | None, expected: str) -> None:
    assert database_name_for(base, worker) == expected


def test_two_workers_never_share_a_database() -> None:
    names = {database_name_for("fbi_test", f"gw{n}") for n in range(8)}
    assert len(names) == 8 and "fbi_test" not in names


def test_every_serial_file_exists_so_a_rename_cannot_silently_send_it_to_the_parallel_run() -> None:
    folder = Path(__file__).resolve().parents[1] / "integration"
    assert SERIAL_FILES and all((folder / name).is_file() for name in SERIAL_FILES)


def test_a_database_per_test_file_has_a_name_postgresql_keeps_whole() -> None:
    from tests.integration.conftest import module_database_name

    long_a = "tests.integration." + "a" * 80
    long_b = "tests.integration." + "a" * 79 + "b"
    names = {module_database_name("fbi_test_gw0", m) for m in (long_a, long_b, "tests.integration.test_x", "tests.integration.test_y")}
    assert len(names) == 4 and all(len(n) <= 63 for n in names) and all(n.startswith("fbi_test_gw0_") for n in names)
    assert module_database_name("fbi_test_gw0", "tests.integration.test_x") == module_database_name("fbi_test_gw0", "tests.integration.test_x")
