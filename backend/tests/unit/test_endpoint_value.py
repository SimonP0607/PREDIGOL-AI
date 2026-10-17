"""Every documented endpoint has a use (what we do) and a value (what it is worth); the matrix is generated."""

from __future__ import annotations

from scripts.endpoint_matrix import matrix

from fbi.providers.api_football.contract import endpoints
from fbi.providers.api_football.integration import USES
from fbi.providers.api_football.value import VALUES


def test_every_documented_endpoint_has_a_use_and_a_value() -> None:
    documented = {e.path for e in endpoints()}
    assert set(USES) == set(VALUES)
    assert documented <= set(USES), f"documented but unclassified: {sorted(documented - set(USES))}"


def test_the_matrix_lists_every_endpoint_once() -> None:
    text = matrix()
    assert all(text.count(f"| `{e}` |") == 1 for e in USES)
    assert "Endpoints revisados: 38" in text
