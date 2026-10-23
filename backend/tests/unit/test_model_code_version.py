"""A model version is keyed by the model code, not by the repository commit."""

from __future__ import annotations

from pathlib import Path

from fbi.core.version import MODEL_PACKAGES, model_code_fingerprint

SRC = Path(__file__).resolve().parents[2] / "src" / "fbi"
RUNNING_MODEL_CODE = "9a7bec97caec"
"""The model code every running model version is keyed by (``mc`` + its first ten characters), in force since F0 (22 Oct 2026)."""


def tree(root: Path, body: str = "x = 1\\n") -> Path:
    for package in MODEL_PACKAGES:
        (root / package).mkdir(parents=True, exist_ok=True)
        (root / package / "__init__.py").write_text("")
    (root / "models" / "goals.py").write_text(body)
    (root / "api").mkdir(exist_ok=True)
    (root / "api" / "page.py").write_text("title = 'a'\\n")
    return root


def test_a_change_outside_the_model_code_keeps_the_version(tmp_path: Path) -> None:
    root = tree(tmp_path)
    before = model_code_fingerprint(root)
    (root / "api" / "page.py").write_text("title = 'b'\\n")  # a page, an audit, a doc
    assert model_code_fingerprint(root) == before
    (root / "models" / "goals.py").write_text("x = 2\\n")  # the model itself
    assert model_code_fingerprint(root) != before


def test_the_running_code_has_a_fingerprint() -> None:
    fp = model_code_fingerprint()
    assert len(fp) == 12 and all(c in "0123456789abcdef" for c in fp)


def test_the_same_code_has_the_same_fingerprint_whatever_its_line_endings(tmp_path: Path) -> None:
    lf = tree(tmp_path / "lf", "x = 1\ny = 2\n")
    crlf = tree(tmp_path / "crlf", "x = 1\r\ny = 2\r\n")  # a file saved from Windows; git sees no change
    assert model_code_fingerprint(crlf) == model_code_fingerprint(lf)


def test_the_model_code_is_the_one_whose_versions_are_running() -> None:
    """A change in the model packages renews the version of EVERY model: a full re-forecast under new versions, a prospective record that
    starts again, a research run that becomes due. F5's first release did it by accident (a new file in fbi.predictions, 23 Oct 2026:
    92,937 forecasts written again). If the change is on purpose - a model, its features, its backtest - update RUNNING_MODEL_CODE in
    the same commit and say so in the release notes; if not, the file belongs outside the model packages."""
    assert model_code_fingerprint() == RUNNING_MODEL_CODE


def test_the_forecast_of_a_match_is_not_model_code() -> None:
    """It derives from what the models say and decides nothing about what they predict (plan F5)."""
    writer = SRC / "forecasting" / "match_forecast.py"
    assert writer.is_file() and "forecasting" not in MODEL_PACKAGES
    assert not any(writer.is_relative_to(SRC / package) for package in MODEL_PACKAGES)
    assert not (SRC / "predictions" / "match_forecast.py").exists(), "it was moved out of fbi.predictions on purpose"
