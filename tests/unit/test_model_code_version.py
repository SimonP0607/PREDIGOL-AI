"""A model version is keyed by the model code, not by the repository commit."""

from __future__ import annotations

from pathlib import Path

from fbi.core.version import MODEL_PACKAGES, model_code_fingerprint


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
