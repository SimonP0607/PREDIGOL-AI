"""PM-13-02 (BE-064): the switch, the pattern and the fallbacks of ``fbi.picks.feature_code``, without a database."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import psycopg
import pytest

from fbi.core.version import MODEL_PACKAGES
from fbi.picks import feature_code

SRC = Path(__file__).resolve().parents[2] / "src" / "fbi"


class _Broken:
    """A connection whose every read fails."""

    def transaction(self) -> Any:
        raise psycopg.OperationalError("down")


@pytest.mark.parametrize("value", [None, "", "off", "0", "no", "shadow", "nonsense"])
def test_off_by_default_and_for_anything_not_on(monkeypatch: pytest.MonkeyPatch, value: str | None) -> None:
    if value is None:
        monkeypatch.delenv(feature_code.SWITCH, raising=False)
    else:
        monkeypatch.setenv(feature_code.SWITCH, value)
    assert not feature_code.enabled()
    assert feature_code.forecast_code_version(_Broken(), "abc123") == "abc123"  # type: ignore[arg-type]


@pytest.mark.parametrize("value", ["on", "1", "true", "YES", " On "])
def test_on(monkeypatch: pytest.MonkeyPatch, value: str) -> None:
    monkeypatch.setenv(feature_code.SWITCH, value)
    assert feature_code.enabled()


def test_a_read_that_fails_keeps_the_current_commit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(feature_code.SWITCH, "on")
    assert feature_code.forecast_code_version(_Broken(), "abc123", model_code="mc0123456789") == "abc123"  # type: ignore[arg-type]


def test_the_pattern_names_the_versions_keyed_by_the_model_code_and_escapes_wildcards() -> None:
    assert feature_code._like("mc9a7bec97ca") == "%@mc9a7bec97ca"
    assert feature_code._like("mc_a%b") == "%@mc\\_a\\%b"


def test_the_choice_lives_outside_the_model_packages() -> None:
    """A file added or changed in a model package renews every model version (tests/unit/test_model_code_version.py)."""
    module = SRC / "picks" / "feature_code.py"
    assert module.is_file()
    assert not any(module.is_relative_to(SRC / package) for package in MODEL_PACKAGES)
