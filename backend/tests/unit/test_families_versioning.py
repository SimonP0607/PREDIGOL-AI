"""The code version of the families (plan F10): a fingerprint of the sources that decide what they predict, read the way git stores them."""

from __future__ import annotations

from pathlib import Path

from fbi.families import versioning


def _tree(root: Path, *, families: str = "X = 1\n", goals: str = "G = 1\n") -> Path:
    (root / "families").mkdir(parents=True)
    (root / "models").mkdir()
    (root / "families" / "fit.py").write_text(families, encoding="utf-8")
    (root / "models" / "goals.py").write_text(goals, encoding="utf-8")
    (root / "models" / "other.py").write_text("O = 1\n", encoding="utf-8")
    return root


def test_the_fingerprint_is_the_same_for_the_same_sources_and_changes_with_either_file(tmp_path: Path) -> None:
    a = versioning.fingerprint(_tree(tmp_path / "a"))
    assert a == versioning.fingerprint(_tree(tmp_path / "same"))
    assert len(a) == 10
    assert a != versioning.fingerprint(_tree(tmp_path / "f", families="X = 2\n")), "a change in a family is a new version"
    assert a != versioning.fingerprint(_tree(tmp_path / "g", goals="G = 2\n")), "so is a change in the fit it reuses"


def test_a_file_that_is_not_the_families_or_the_reused_fit_does_not_move_it(tmp_path: Path) -> None:
    root = _tree(tmp_path / "t")
    before = versioning.fingerprint(root)
    (root / "models" / "other.py").write_text("O = 2\n", encoding="utf-8")
    (root / "families" / "__pycache__").mkdir()
    (root / "families" / "__pycache__" / "junk.py").write_text("J = 1\n", encoding="utf-8")
    assert versioning.fingerprint(root) == before


def test_windows_line_endings_do_not_make_another_version(tmp_path: Path) -> None:
    lf = versioning.fingerprint(_tree(tmp_path / "lf", families="X = 1\nY = 2\n"))
    crlf = versioning.fingerprint(_tree(tmp_path / "crlf", families="X = 1\r\nY = 2\r\n"))
    assert lf == crlf, "the same commit must have the same fingerprint on every machine"


def test_a_new_module_of_the_families_is_a_new_version(tmp_path: Path) -> None:
    root = _tree(tmp_path / "t")
    before = versioning.fingerprint(root)
    (root / "families" / "extra.py").write_text("E = 1\n", encoding="utf-8")
    assert versioning.fingerprint(root) != before


def test_the_version_string_says_the_spec_and_the_code() -> None:
    assert versioning.version_string("corners_ft:xi=0.0019,penalty=2", "fcabc1234567") == "1.0.0/corners_ft:xi=0.0019,penalty=2@fcabc1234567"
    assert versioning.code_version().startswith("fc") and len(versioning.code_version()) == 12


def test_the_real_tree_has_a_fingerprint_that_covers_this_module() -> None:
    first = versioning.fingerprint()
    assert first == versioning.fingerprint(), "reading twice gives one answer"
    assert (Path(versioning.__file__).parent.parent / "models" / "goals.py").exists(), "the reused fit is where the fingerprint looks"
