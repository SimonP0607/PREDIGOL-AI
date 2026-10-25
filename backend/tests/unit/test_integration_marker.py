"""``pytest -m "not integration"`` is the unit suite and nothing else (plan UX, A0).

The tests under ``tests/integration`` need a live PostgreSQL. Their ``conftest.py`` marks every one of them ``integration``
at collection, so a run without a database can deselect them all by the mark, and the database suite can be run alone.
This collects that folder in a subprocess with the unit filter (collection only: no database is touched): every test must
be deselected and none left.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]


def test_every_test_of_the_integration_folder_carries_the_mark() -> None:
    done = subprocess.run([sys.executable, "-m", "pytest", "--collect-only", "-q", "-p", "no:cacheprovider",
                           "-m", "not integration", "tests/integration"],
                          cwd=BACKEND, capture_output=True, text=True, timeout=600, check=False)
    out = done.stdout + done.stderr
    assert "no tests collected" in out, out[-800:]
    deselected = re.search(r"(\d+) deselected", out)
    assert deselected and int(deselected.group(1)) > 1000, out[-800:]
