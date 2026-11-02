"""Plan F12.7 - the release guard for the code of the models (scripts/model_code_guard.py, owner decision 19).

The ledger test (test_model_code_ledger.py) runs in the gate of whoever builds the release and not on the server. The guard asks the same question of
the two trees a release moves between - the one production runs and the one the package carries - where the release passes through: UNCHANGED, COVERED
(the code changes and the ledger of the new tree puts exactly that code in force) or UNCOVERED (it changes and the ledger does not); it informs by default
and stops (exit status 4) only when asked to. A tree it cannot read is never a green light (exit status 2).

The trees here are built in a temporary folder out of the REAL ``version.py`` and ``promotions.py`` (the ledger of the tree is then replaced by the one
the case needs), so the guard is tested against the shape of the files it reads in production, and the fingerprint it names is compared with what
``fbi.core.version.model_code_fingerprint`` itself says of the same folder."""

from __future__ import annotations

import ast
import json
import shutil
import subprocess
import sys
import tempfile
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import pytest
from scripts import model_code_guard as guard

from fbi.core.version import MODEL_PACKAGES, model_code_fingerprint, model_code_version
from fbi.research import promotions

BACKEND = Path(__file__).resolve().parents[2]
SRC = BACKEND / "src" / "fbi"
SCRIPT = BACKEND / "scripts" / "model_code_guard.py"
OLD = "mc1111111111"
REASON = "the neutral-venue rule, after the before-and-after backtest the owner asked for and approved"
AT_NOON = "datetime(2026, 10, 30, 12, 0, tzinfo=UTC)"


def make_tree(root: Path, *, change: str = "", elsewhere: str = "", version: str | None = None) -> Path:
    """A backend folder: the real ``version.py`` (or ``version``), one small file in each of the five model packages (``change`` is added to the one
    in ``models``) and one outside them (``elsewhere``). It has no ledger yet."""
    base = root / "src" / "fbi"
    (base / "core").mkdir(parents=True)
    (base / "core" / "version.py").write_text(version if version is not None else (SRC / "core" / "version.py").read_text())
    for package in MODEL_PACKAGES:
        (base / package).mkdir()
        (base / package / "a.py").write_text(f"NAME = {package!r}\n" + (change if package == "models" else ""))
    (base / "api").mkdir()
    (base / "api" / "routes.py").write_text("ROUTES = 1\n" + elsewhere)
    return root


def name(tree: Path) -> str:
    """The name of the code of the tree, from the function the project itself uses."""
    return f"mc{model_code_fingerprint(tree / 'src' / 'fbi')[:10]}"


def entry(fingerprint: str, *, by: str = "owner", phase: str = "F99", reason: str = REASON, baseline: bool = False, at: str = AT_NOON) -> str:
    return (f"    CodePromotion(fingerprint={fingerprint!r}, decided_at={at}, decided_by={by!r}, phase={phase!r}, reason={reason!r}, "
            f"baseline={baseline!r}),\n")


def set_ledger(tree: Path, entries: list[str] | None) -> Path:
    """Give the tree the real ``promotions.py`` with its ``LEDGER`` replaced by ``entries``; None: the tree has no ledger at all."""
    path = tree / "src" / "fbi" / "research" / "promotions.py"
    if entries is None:
        path.unlink(missing_ok=True)
        return tree
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text((SRC / "research" / "promotions.py").read_text() + "\nimport datetime as _dt\n\nLEDGER = (\n" + "".join(entries) + ")\n")
    return tree


@pytest.fixture()
def cli(capsys: pytest.CaptureFixture[str]) -> Any:
    """Run ``main`` and give back its status, what it printed and what it said on the error output."""
    def call(*argv: str) -> tuple[int, str, str]:
        status = guard.main(list(argv))
        out = capsys.readouterr()
        return status, out.out, out.err
    return call


def test_the_names_the_options_and_the_exit_statuses_are_those_the_guide_and_the_scripts_rely_on() -> None:
    assert guard.MODES == ("inform", "stop") and guard.DEFAULT_MODE == "inform"
    assert guard.STATUSES == ("UNCHANGED", "COVERED", "UNCOVERED")
    assert (guard.EXIT_GO, guard.EXIT_CANNOT_CHECK, guard.EXIT_STOP) == (0, 2, 4)
    assert guard.REASON_CHARS == 160 and guard.MIN_PYTHON == (3, 11, 4)
    assert (guard.SOURCE, guard.VERSION_FILE, guard.LEDGER_FILE) == ("src/fbi", "src/fbi/core/version.py", "src/fbi/research/promotions.py")
    assert guard.LABEL.fullmatch("mc9a7bec97ca") and not guard.LABEL.fullmatch("mc9a7bec97c") and not guard.LABEL.fullmatch("mc9a7bec97caa")
    assert not guard.LABEL.fullmatch("MC9a7bec97ca") and not guard.LABEL.fullmatch("mc9a7bec97cg") and not guard.LABEL.fullmatch("xmc9a7bec97ca")
    assert not guard.LABEL.fullmatch("mc9a7bec97cA") and not guard.LABEL.fullmatch("mcAAAAAAAAAA"), "the hex digits of a name are lower case"
    assert not guard.LABEL.fullmatch("mc9a7bec97ca\n"), "not even a newline after it"
    assert guard.FINGERPRINT.fullmatch("9a7bec97caec") and not guard.FINGERPRINT.fullmatch("9a7bec97cae")
    assert not guard.FINGERPRINT.fullmatch("9a7bec97caecd") and not guard.FINGERPRINT.fullmatch("9A7bec97caec") and not guard.FINGERPRINT.fullmatch("9a7bec97caeg")
    assert not guard.FINGERPRINT.fullmatch("9a7bec97caec\n")


# ----------------------------------------------------------------------------------------------------------------------------------------------
# The name of the code of a tree
# ----------------------------------------------------------------------------------------------------------------------------------------------

def test_the_name_of_the_code_of_the_real_tree_is_the_one_a_model_version_carries(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FBI_MODEL_CODE_VERSION", raising=False)
    label = guard.label_of(BACKEND)
    assert label == model_code_version.__wrapped__() == promotions.label_of(model_code_fingerprint()), "the same name as ...@mc9a7bec97ca"
    assert label == promotions.in_force().fingerprint, "and, since the ledger test passes, the one the ledger has in force"


def test_the_name_of_a_tree_is_that_of_the_function_of_the_project_applied_to_its_own_folder(tmp_path: Path) -> None:
    tree = make_tree(tmp_path / "t")
    assert guard.label_of(tree) == name(tree)
    assert guard.label_of(tree) != guard.label_of(BACKEND)
    assert guard.label_of(tree) == guard.label_of(make_tree(tmp_path / "same")), "the same files, the same name wherever the folder is"


@pytest.mark.parametrize("package", MODEL_PACKAGES)
def test_a_change_in_any_model_package_changes_the_name_and_one_outside_them_does_not(tmp_path: Path, package: str) -> None:
    tree = make_tree(tmp_path / "t")
    before = guard.label_of(tree)
    (tree / "src" / "fbi" / package / "a.py").write_text("NAME = 'changed'\n")
    assert guard.label_of(tree) != before
    other = make_tree(tmp_path / "o")
    (other / "src" / "fbi" / "api" / "routes.py").write_text("ROUTES = 2\n")
    assert guard.label_of(other) == before, "a page, an audit, a doc: not model code"


def test_the_tree_decides_which_packages_are_the_models_not_the_guard(tmp_path: Path) -> None:
    text = (SRC / "core" / "version.py").read_text()
    assert '"backtesting", "domain")' in text, "the list of packages of the real version.py, which the next line widens"
    wider = text.replace('"backtesting", "domain")', '"backtesting", "domain", "extra")')
    plain = make_tree(tmp_path / "plain", version=wider)
    with_extra = make_tree(tmp_path / "with_extra", version=wider)
    for tree in (plain, with_extra):
        (tree / "src" / "fbi" / "extra").mkdir()
        (tree / "src" / "fbi" / "extra" / "a.py").write_text("X = 1\n")
    (with_extra / "src" / "fbi" / "extra" / "a.py").write_text("X = 2\n")
    assert guard.label_of(plain) != guard.label_of(with_extra), "a sixth package named by the tree's own version.py counts"
    assert guard.label_of(plain) != name(plain), "and it is not what the project's own five-package function says of the same folder"


def test_loading_a_tree_leaves_nothing_registered_whether_it_loads_or_not(tmp_path: Path) -> None:
    tree = set_ledger(make_tree(tmp_path / "t"), [entry(OLD, baseline=True)])
    guard.assess(OLD, tree)
    broken = make_tree(tmp_path / "broken", version="raise RuntimeError('boom')\n")
    with pytest.raises(guard.CannotCheckError):
        guard.label_of(broken)
    assert not [m for m in sys.modules if m.startswith("model_code_guard_")]


def test_reading_a_tree_writes_nothing_into_it_and_leaves_the_interpreter_as_it_was(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    tree = set_ledger(make_tree(tmp_path / "t"), [entry(OLD, by="system", phase="F0", baseline=True)])
    monkeypatch.setattr(sys, "dont_write_bytecode", False)
    guard.assess(OLD, tree)
    assert list(tree.rglob("__pycache__")) == [] and list(tree.rglob("*.pyc")) == [], "no bytecode of the version file or of the ledger"
    assert sys.dont_write_bytecode is False
    (tree / "src" / "fbi" / "research" / "promotions.py").write_text("raise RuntimeError('boom')\n")
    with pytest.raises(guard.CannotCheckError):
        guard.assess(OLD, tree)
    assert sys.dont_write_bytecode is False and list(tree.rglob("__pycache__")) == []
    monkeypatch.setattr(sys, "dont_write_bytecode", True)
    guard.label_of(tree)
    assert sys.dont_write_bytecode is True, "it gives back what it found, not what it set"


@pytest.mark.parametrize(("version", "message"), [
    ("raise RuntimeError('boom')\n", "does not load: RuntimeError: boom"),
    ("MODEL_PACKAGES = ('models',)\n", "does not give a fingerprint: AttributeError"),
    ("MODEL_PACKAGES = 3\n\ndef model_code_fingerprint():\n    return 'a' * 12\n", "does not give a fingerprint: TypeError"),
    ("MODEL_PACKAGES = ('models',)\n\ndef model_code_fingerprint():\n    return 'xyz'\n", "gave 'xyz', not 12 hex digits"),
    ("MODEL_PACKAGES = ('models',)\n\ndef model_code_fingerprint():\n    return 12\n", "gave 12, not 12 hex digits"),
    ("MODEL_PACKAGES = ('models',)\n\ndef model_code_fingerprint():\n    return 123456789012\n", "gave 123456789012, not 12 hex digits"),
    ("MODEL_PACKAGES = ('models',)\n\ndef model_code_fingerprint():\n    return 'a' * 13\n", "not 12 hex digits"),
    ("MODEL_PACKAGES = ('models',)\n\ndef model_code_fingerprint():\n    raise ValueError('not today')\n", "does not give a fingerprint: ValueError: not today"),
    ("MODEL_PACKAGES = ('models',)\n\ndef model_code_fingerprint():\n    return 'A' * 12\n", "not 12 hex digits"),
])
def test_a_version_file_that_does_not_give_a_name_is_refused_and_says_why(tmp_path: Path, version: str, message: str) -> None:
    tree = make_tree(tmp_path / "t", version=version)
    with pytest.raises(guard.CannotCheckError, match=message) as refused:
        guard.label_of(tree)
    assert str(refused.value).startswith(str(tree / "src" / "fbi" / "core" / "version.py")), "and the message says which file it is about"


def test_a_fingerprint_of_twelve_hex_digits_is_accepted_whatever_function_gives_it(tmp_path: Path) -> None:
    version = "MODEL_PACKAGES = ('models',)\n\ndef model_code_fingerprint():\n    return '0123456789ab'\n"
    assert guard.label_of(make_tree(tmp_path / "t", version=version)) == "mc0123456789"


def test_a_model_package_without_python_source_is_refused_because_it_would_fingerprint_as_nothing(tmp_path: Path) -> None:
    tree = make_tree(tmp_path / "t")
    (tree / "src" / "fbi" / "features" / "a.py").unlink()
    with pytest.raises(guard.CannotCheckError, match="no Python source in the model package 'features'"):
        guard.label_of(tree)
    shutil.rmtree(tree / "src" / "fbi" / "domain")
    (tree / "src" / "fbi" / "features" / "a.py").write_text("X = 1\n")
    with pytest.raises(guard.CannotCheckError, match="no Python source in the model package 'domain'"):
        guard.label_of(tree)


def test_a_model_package_with_only_files_that_are_not_python_has_no_source(tmp_path: Path) -> None:
    tree = make_tree(tmp_path / "t")
    (tree / "src" / "fbi" / "features" / "a.py").unlink()
    (tree / "src" / "fbi" / "features" / "notes.txt").write_text("not source\n")
    (tree / "src" / "fbi" / "features" / "__pycache__").mkdir()
    (tree / "src" / "fbi" / "features" / "__pycache__" / "a.cpython-312.pyc").write_bytes(b"\0")
    with pytest.raises(guard.CannotCheckError, match="no Python source in the model package 'features'"):
        guard.label_of(tree)


def test_a_source_in_a_subfolder_of_a_model_package_counts_as_source(tmp_path: Path) -> None:
    tree = make_tree(tmp_path / "t")
    (tree / "src" / "fbi" / "models" / "a.py").unlink()
    (tree / "src" / "fbi" / "models" / "deep" / "er").mkdir(parents=True)
    (tree / "src" / "fbi" / "models" / "deep" / "er" / "b.py").write_text("X = 1\n")
    assert guard.label_of(tree) == name(tree)


def test_a_file_that_is_not_there_or_not_python_cannot_be_loaded(tmp_path: Path) -> None:
    with pytest.raises(guard.CannotCheckError, match="is not a Python file that can be loaded"):
        guard.load(tmp_path / "missing.py", "model_code_guard_x")
    with pytest.raises(guard.CannotCheckError, match="is not a Python file that can be loaded"):
        guard.label_of(tmp_path)


# ----------------------------------------------------------------------------------------------------------------------------------------------
# The ledger of a tree
# ----------------------------------------------------------------------------------------------------------------------------------------------

def test_the_ledger_is_read_as_the_project_reads_it() -> None:
    read = guard.ledger_of(BACKEND)
    assert read is not None and len(read) == len(promotions.LEDGER) >= 1
    for got, want in zip(read, promotions.LEDGER, strict=True):
        assert got == guard.Entry(want.fingerprint, want.decided_at, want.decided_by, want.phase, want.baseline, want.reason)
        assert got.decided_at.tzinfo is not None


def test_the_ledger_of_a_synthetic_tree_is_what_was_written_in_the_order_it_was_written(tmp_path: Path) -> None:
    tree = set_ledger(make_tree(tmp_path / "t"), [entry(OLD, by="system", phase="F0", baseline=True, at="datetime(2026, 10, 22, 13, 0, tzinfo=UTC)"),
                                                 entry("mc2222222222", by="owner", phase="F13", reason="a second reason " * 4)])
    read = guard.ledger_of(tree)
    assert read == (guard.Entry(OLD, datetime(2026, 10, 22, 13, 0, tzinfo=UTC), "system", "F0", True, REASON),
                    guard.Entry("mc2222222222", datetime(2026, 10, 30, 12, 0, tzinfo=UTC), "owner", "F13", False, "a second reason " * 4))


def test_a_tree_without_a_ledger_has_none_and_an_empty_ledger_has_no_entries(tmp_path: Path) -> None:
    assert guard.ledger_of(make_tree(tmp_path / "none")) is None, "older than plan F12"
    assert guard.ledger_of(set_ledger(make_tree(tmp_path / "empty"), [])) == ()


@pytest.mark.parametrize(("body", "message"), [
    ("raise RuntimeError('boom')\n", "does not load: RuntimeError: boom"),
    ("X = 1\n", "has a ledger the guard cannot read: AttributeError"),
    ("LEDGER = 5\n", "has a ledger the guard cannot read: TypeError"),
    ("LEDGER = (1,)\n", "has a ledger the guard cannot read: AttributeError"),
    ("class Bad:\n    def __iter__(self):\n        raise ValueError('not today')\n\nLEDGER = Bad()\n", "cannot read: ValueError: not today"),
])
def test_a_ledger_that_does_not_load_or_is_not_a_ledger_is_refused_and_says_why(tmp_path: Path, body: str, message: str) -> None:
    tree = make_tree(tmp_path / "t")
    (tree / "src" / "fbi" / "research").mkdir()
    (tree / "src" / "fbi" / "research" / "promotions.py").write_text(body)
    with pytest.raises(guard.CannotCheckError, match=message) as refused:
        guard.ledger_of(tree)
    assert str(refused.value).startswith(str(tree / "src" / "fbi" / "research" / "promotions.py")), "and the message says which file it is about"


# ----------------------------------------------------------------------------------------------------------------------------------------------
# The verdict
# ----------------------------------------------------------------------------------------------------------------------------------------------

def changed_tree(tmp_path: Path, entries: list[str] | None) -> tuple[Path, str]:
    """A tree whose code is not OLD, with the ledger the case needs; ``@NEW@`` in an entry stands for the name of that code."""
    tree = make_tree(tmp_path / "t", change="X = 2\n")
    code = name(tree)
    set_ledger(tree, None if entries is None else [e.replace("@NEW@", code) for e in entries])
    return tree, code


def test_the_same_code_as_production_is_unchanged_in_both_modes_and_never_stops(tmp_path: Path) -> None:
    tree = make_tree(tmp_path / "t")
    code = name(tree)
    set_ledger(tree, [entry(OLD, by="system", phase="F0", baseline=True), entry(code)])
    for mode in guard.MODES:
        v = guard.assess(code, tree, mode)
        assert (v.status, v.mode, v.before, v.after, v.stops, v.ledger_agrees, v.has_ledger) == ("UNCHANGED", mode, code, code, False, True, True)
        assert v.in_force is not None and v.covered_by is v.in_force and v.in_force.fingerprint == code


@pytest.mark.parametrize("mode", ["inform", "stop"])
def test_a_change_the_ledger_puts_in_force_is_covered_and_passes_in_both_modes(tmp_path: Path, mode: str) -> None:
    tree, code = changed_tree(tmp_path, [entry(OLD, by="system", phase="F0", baseline=True), entry("@NEW@")])
    v = guard.assess(OLD, tree, mode)
    assert (v.status, v.stops, v.ledger_agrees, v.after) == ("COVERED", False, True, code)
    assert v.covered_by is not None and (v.covered_by.fingerprint, v.covered_by.decided_by, v.covered_by.phase) == (code, "owner", "F99")
    assert v.covered_by is v.in_force


@pytest.mark.parametrize(("mode", "stops"), [("inform", False), ("stop", True)])
def test_a_change_with_no_entry_in_force_is_uncovered_and_stops_only_in_stop_mode(tmp_path: Path, mode: str, stops: bool) -> None:
    tree, code = changed_tree(tmp_path, [entry(OLD, by="system", phase="F0", baseline=True)])
    v = guard.assess(OLD, tree, mode)
    assert (v.status, v.stops, v.ledger_agrees, v.after, v.has_ledger) == ("UNCOVERED", stops, False, code, True)
    assert v.covered_by is None and v.in_force is not None and v.in_force.fingerprint == OLD, "the ledger still says the old code is in force"


@pytest.mark.parametrize("mode", ["inform", "stop"])
def test_an_entry_for_the_new_code_that_is_not_the_last_does_not_cover_it(tmp_path: Path, mode: str) -> None:
    tree, code = changed_tree(tmp_path, [entry(OLD, by="system", phase="F0", baseline=True), entry("@NEW@"), entry("mc3333333333", phase="F98")])
    v = guard.assess(OLD, tree, mode)
    assert (v.status, v.covered_by, v.stops) == ("UNCOVERED", None, mode == "stop"), "the ledger says another code is in force than the tree carries"
    assert v.in_force is not None and v.in_force.fingerprint == "mc3333333333" and v.after == code


@pytest.mark.parametrize(("entries", "has_ledger"), [(None, False), ([], True)])
def test_a_change_in_a_tree_with_no_ledger_or_an_empty_one_is_uncovered(tmp_path: Path, entries: list[str] | None, has_ledger: bool) -> None:
    tree, _ = changed_tree(tmp_path, entries)
    v = guard.assess(OLD, tree, "stop")
    assert (v.status, v.has_ledger, v.in_force, v.covered_by, v.stops) == ("UNCOVERED", has_ledger, None, None, True)


def test_the_same_code_with_a_ledger_that_names_another_is_unchanged_and_says_the_gate_would_fail(tmp_path: Path) -> None:
    tree = set_ledger(make_tree(tmp_path / "t"), [entry(OLD, by="system", phase="F0", baseline=True)])
    code = name(tree)
    v = guard.assess(code, tree, "stop")
    assert (v.status, v.stops, v.ledger_agrees, v.covered_by) == ("UNCHANGED", False, False, None)
    assert "tests/unit/test_model_code_ledger.py would fail in the gate; nothing changes in production." in guard.render(v)


def test_the_same_code_in_a_tree_without_a_ledger_is_unchanged(tmp_path: Path) -> None:
    tree = make_tree(tmp_path / "t")
    v = guard.assess(name(tree), tree, "stop")
    assert (v.status, v.stops, v.has_ledger, v.in_force) == ("UNCHANGED", False, False, None)


def test_a_mode_or_a_name_that_does_not_exist_is_refused_before_anything_is_read(tmp_path: Path) -> None:
    tree = make_tree(tmp_path / "t")
    with pytest.raises(guard.CannotCheckError, match="the mode is one of inform, stop, not 'strict'"):
        guard.assess(OLD, tree, "strict")
    for bad in ("mc123", "mc11111111111", "MC1111111111", "1111111111", "mc111111111g", "", "mc1111111111\n", " mc1111111111", "xmc1111111111", "mc111111111A"):
        with pytest.raises(guard.CannotCheckError, match="is not the name of a model code"):
            guard.assess(bad, tree)


def test_the_default_mode_is_to_inform(tmp_path: Path) -> None:
    tree, _ = changed_tree(tmp_path, [])
    assert guard.assess(OLD, tree).mode == "inform" and not guard.assess(OLD, tree).stops


def test_the_real_tree_is_unchanged_against_the_code_the_ledger_has_in_force_and_covered_against_any_other() -> None:
    in_force = promotions.in_force().fingerprint
    same = guard.assess(in_force, BACKEND, "stop")
    assert same.status == "UNCHANGED" and same.ledger_agrees and not same.stops
    other = guard.assess("mc0000000000", BACKEND, "stop")
    assert other.status == "COVERED" and not other.stops and other.covered_by is not None and other.covered_by.fingerprint == in_force


# ----------------------------------------------------------------------------------------------------------------------------------------------
# What it says
# ----------------------------------------------------------------------------------------------------------------------------------------------

def test_the_text_of_each_verdict_is_what_the_guide_and_the_log_of_a_release_quote(tmp_path: Path) -> None:
    baseline = entry(OLD, by="system", phase="F0", baseline=True, at="datetime(2026, 10, 22, 13, 0, tzinfo=UTC)")
    unchanged = make_tree(tmp_path / "u")
    code_u = name(unchanged)
    set_ledger(unchanged, [baseline, entry(code_u)])
    assert guard.render(guard.assess(code_u, unchanged)) == "\n".join([
        "model-code guard - mode inform",
        f"  production runs  {code_u}",
        f"  the release has  {code_u}",
        f"  ledger in force  {code_u} (F99, decided by owner on 2026-10-30 12:00 UTC)",
        "UNCHANGED: the release does not touch the code that decides what the models predict; no model opens a new version."])

    covered, code = changed_tree(tmp_path / "c", [baseline, entry("@NEW@")])
    assert guard.render(guard.assess(OLD, covered, "stop")) == "\n".join([
        "model-code guard - mode stop",
        f"  production runs  {OLD}",
        f"  the release has  {code}",
        f"  ledger in force  {code} (F99, decided by owner on 2026-10-30 12:00 UTC)",
        f"COVERED: THE MODEL CODE CHANGES ({OLD} -> {code}) and the ledger puts the new code in force: F99, decided by owner on "
        f"2026-10-30 12:00 UTC: {REASON}",
        "Every model opens new versions and the forecast runs with them from its next pass."])

    uncovered, code = changed_tree(tmp_path / "x", [baseline])
    lines = ["model-code guard - mode {mode}",
             f"  production runs  {OLD}",
             f"  the release has  {code}",
             f"  ledger in force  {OLD} (F0, decided by system on 2026-10-22 13:00 UTC, baseline)",
             f"UNCOVERED: THE MODEL CODE CHANGES ({OLD} -> {code}) and the ledger does not put the new code in force (its last entry is {OLD}).",
             "Every model would open new versions and the forecast would run with them from its next pass, with no decision on record.",
             "{last}"]
    assert guard.render(guard.assess(OLD, uncovered, "inform")) == "\n".join(lines).format(
        mode="inform", last="mode inform: the release goes on; the owner is told before it is deployed.")
    assert guard.render(guard.assess(OLD, uncovered, "stop")) == "\n".join(lines).format(
        mode="stop", last="mode stop: THE RELEASE STOPS HERE (exit status 4).")


def test_the_text_says_why_the_ledger_does_not_cover_a_change_with_no_ledger_and_with_an_empty_one(tmp_path: Path) -> None:
    none, code = changed_tree(tmp_path / "n", None)
    text = guard.render(guard.assess(OLD, none))
    assert "  ledger in force  none: this tree has no ledger (it is older than plan F12)\n" in text
    assert f"UNCOVERED: THE MODEL CODE CHANGES ({OLD} -> {code}) and the ledger does not put the new code in force (this tree has no ledger).\n" in text
    empty, code = changed_tree(tmp_path / "e", [])
    text = guard.render(guard.assess(OLD, empty))
    assert "  ledger in force  none: the ledger has no entries\n" in text
    assert f"UNCOVERED: THE MODEL CODE CHANGES ({OLD} -> {code}) and the ledger does not put the new code in force (the ledger has no entries).\n" in text


def test_the_text_of_an_unchanged_release_whose_ledger_names_another_code_adds_the_note(tmp_path: Path) -> None:
    tree = set_ledger(make_tree(tmp_path / "t"), [entry(OLD, by="system", phase="F0", baseline=True, at="datetime(2026, 10, 22, 13, 0, tzinfo=UTC)")])
    code = name(tree)
    assert guard.render(guard.assess(code, tree)) == "\n".join([
        "model-code guard - mode inform",
        f"  production runs  {code}",
        f"  the release has  {code}",
        f"  ledger in force  {OLD} (F0, decided by system on 2026-10-22 13:00 UTC, baseline)",
        "UNCHANGED: the release does not touch the code that decides what the models predict; no model opens a new version.",
        "note: the last entry of the ledger is not this code, so tests/unit/test_model_code_ledger.py would fail in the gate; nothing changes in "
        "production."])


def test_a_moment_is_written_in_utc_to_the_minute() -> None:
    assert guard.day(datetime(2026, 10, 30, 12, 5, 59, tzinfo=UTC)) == "2026-10-30 12:05 UTC"
    assert guard.day(datetime(2026, 10, 30, 14, 5, tzinfo=timezone(timedelta(hours=2)))) == "2026-10-30 12:05 UTC"
    assert guard.day(datetime(2026, 1, 2, 3, 4, tzinfo=timezone(timedelta(hours=-5)))) == "2026-01-02 08:04 UTC"


def test_the_reason_quoted_is_one_line_of_at_most_the_characters_the_text_allows() -> None:
    assert guard.quote("one\n  two\t three") == "one two three"
    exact = "x" * guard.REASON_CHARS
    assert guard.quote(exact) == exact, "exactly the limit is quoted whole"
    assert guard.quote(exact + "y") == exact + "...", "one more is cut and says so"
    long_words = " ".join(["word"] * 60)
    quoted = guard.quote(long_words)
    assert quoted.endswith("...") and len(quoted) <= guard.REASON_CHARS + 3 and not quoted[:-3].endswith(" ")


def test_a_decision_taken_in_another_time_zone_is_quoted_in_utc(tmp_path: Path) -> None:
    at = "_dt.datetime(2026, 10, 30, 14, 0, tzinfo=_dt.timezone(_dt.timedelta(hours=2)))"
    tree, _ = changed_tree(tmp_path, [entry("@NEW@", at=at)])
    assert "decided by owner on 2026-10-30 12:00 UTC" in guard.render(guard.assess(OLD, tree))


def test_the_long_reason_of_a_covering_entry_is_cut_in_the_text_and_whole_in_the_json(tmp_path: Path) -> None:
    long_reason = "because " + "the owner decided it after reading the guide " * 8
    tree, _ = changed_tree(tmp_path, [entry("@NEW@", reason=long_reason)])
    v = guard.assess(OLD, tree)
    text = guard.render(v)
    assert guard.quote(long_reason) in text and long_reason not in text
    assert v.as_dict()["covered_by"]["reason"] == long_reason


def test_the_verdict_as_json_has_exactly_the_keys_the_scripts_read(tmp_path: Path) -> None:
    tree, code = changed_tree(tmp_path, [entry(OLD, by="system", phase="F0", baseline=True), entry("@NEW@")])
    data = guard.assess(OLD, tree, "stop").as_dict()
    assert set(data) == {"mode", "status", "before", "after", "changes", "has_ledger", "ledger_agrees", "stops", "in_force", "covered_by"}
    assert (data["mode"], data["status"], data["before"], data["after"], data["changes"]) == ("stop", "COVERED", OLD, code, True)
    assert (data["has_ledger"], data["ledger_agrees"], data["stops"]) == (True, True, False)
    assert set(data["covered_by"]) == {"fingerprint", "decided_at", "decided_by", "phase", "baseline", "reason"}
    assert data["covered_by"] == data["in_force"] == {"fingerprint": code, "decided_at": "2026-10-30T12:00:00+00:00", "decided_by": "owner",
                                                      "phase": "F99", "baseline": False, "reason": REASON}
    same = guard.assess(code, tree).as_dict()
    assert same["changes"] is False and same["status"] == "UNCHANGED"
    none = guard.assess(OLD, set_ledger(tree, None), "stop").as_dict()
    assert (none["in_force"], none["covered_by"], none["has_ledger"], none["ledger_agrees"], none["stops"]) == (None, None, False, False, True)
    empty = guard.assess(OLD, set_ledger(tree, []), "inform").as_dict()
    assert (empty["in_force"], empty["covered_by"], empty["has_ledger"], empty["ledger_agrees"], empty["stops"]) == (None, None, True, False, False)
    set_ledger(tree, [entry(OLD, by="system", phase="F0", baseline=True)])
    uncovered = guard.assess(OLD, tree, "stop").as_dict()
    assert uncovered["covered_by"] is None and uncovered["in_force"]["fingerprint"] == OLD, "the ledger has an entry in force, and it is not this code"
    assert (uncovered["status"], uncovered["changes"], uncovered["ledger_agrees"], uncovered["stops"]) == ("UNCOVERED", True, False, True)
    json.dumps(data)


# ----------------------------------------------------------------------------------------------------------------------------------------------
# The command
# ----------------------------------------------------------------------------------------------------------------------------------------------

def test_the_command_exits_with_zero_for_a_release_that_goes_on_and_four_for_one_that_stops(tmp_path: Path, cli: Any) -> None:
    covered, _ = changed_tree(tmp_path / "c", [entry(OLD, by="system", phase="F0", baseline=True), entry("@NEW@")])
    uncovered, code = changed_tree(tmp_path / "u", [entry(OLD, by="system", phase="F0", baseline=True)])
    status, out, err = cli("check", "--before", f"label={OLD}", "--after", f"dir={covered}", "--mode", "stop")
    assert (status, err) == (0, "") and "COVERED: THE MODEL CODE CHANGES" in out
    status, out, err = cli("check", "--before", f"label={OLD}", "--after", f"dir={uncovered}", "--mode", "stop")
    assert (status, err) == (4, "") and "mode stop: THE RELEASE STOPS HERE (exit status 4)." in out
    status, out, err = cli("check", "--before", f"label={OLD}", "--after", f"dir={uncovered}", "--mode", "inform")
    assert (status, err) == (0, "") and "mode inform: the release goes on; the owner is told before it is deployed." in out
    status, out, err = cli("check", "--before", f"label={OLD}", "--after", f"dir={uncovered}")
    assert (status, err) == (0, "") and out.startswith("model-code guard - mode inform\n"), "to inform is the default"
    status, out, err = cli("check", "--before", f"label={code}", "--after", f"dir={uncovered}", "--mode", "stop")
    assert (status, err) == (0, "") and "UNCHANGED" in out


def test_the_command_prints_the_verdict_as_json_when_asked(tmp_path: Path, cli: Any) -> None:
    uncovered, code = changed_tree(tmp_path, [entry(OLD, by="system", phase="F0", baseline=True)])
    status, out, err = cli("check", "--before", f"label={OLD}", "--after", f"dir={uncovered}", "--mode", "stop", "--json")
    data = json.loads(out)
    assert status == 4 and err == "" and data["status"] == "UNCOVERED" and data["stops"] is True and data["after"] == code
    assert out == json.dumps(data, indent=1, sort_keys=True) + "\n"


def test_the_command_names_the_code_of_a_tree(tmp_path: Path, cli: Any) -> None:
    tree = make_tree(tmp_path / "t")
    assert cli("fingerprint", f"dir={tree}") == (0, name(tree) + "\n", "")
    assert cli("fingerprint", f"dir={BACKEND}") == (0, guard.label_of(BACKEND) + "\n", "")


@pytest.mark.parametrize(("argv", "message"), [
    (["check", "--before", "label=mc1111111111", "--after", "dir={missing}"], "has no src/fbi inside: a tree is a backend folder"),
    (["check", "--before", "label=mc1111111111", "--after", "dir={empty}"], "has no src/fbi inside"),
    (["check", "--before", "nonsense", "--after", "dir={tree}"], "does not name a tree: dir=<folder>, git=<tree-ish> or (for --before) label=mc<10 hex>"),
    (["check", "--before", "ftp=x", "--after", "dir={tree}"], "does not name a tree"),
    (["check", "--before", "dir=", "--after", "dir={tree}"], "does not name a tree"),
    (["check", "--before", "label=oops", "--after", "dir={tree}"], "'oops' is not the name of a model code"),
    (["check", "--before", "label=mc1111111111", "--after", "label=mc1111111111"], "is a name, not a tree: only --before takes a label"),
    (["fingerprint", "label=mc1111111111"], "is a name, not a tree: only --before takes a label"),
    (["check", "--before", "label=mc1111111111", "--after", "git=-x"], "'-x' is not a tree-ish"),
    (["check", "--before", "dir={tree}", "--after", "dir={missing}"], "has no src/fbi inside"),
])
def test_a_tree_the_command_cannot_read_is_never_a_green_light(tmp_path: Path, cli: Any, argv: list[str], message: str) -> None:
    (tmp_path / "empty").mkdir()
    tree = make_tree(tmp_path / "t")
    argv = [a.format(missing=tmp_path / "missing", empty=tmp_path / "empty", tree=tree) for a in argv]
    status, out, err = cli(*argv, "--mode", "inform") if argv[0] == "check" else cli(*argv)
    assert status == 2 and out == "", "even in inform mode: a guard that cannot look is not a guard"
    assert err.startswith("cannot check: ") and message in err and err.endswith("\n")


def test_a_ledger_that_cannot_be_read_stops_the_command_with_status_two_in_both_modes(tmp_path: Path, cli: Any) -> None:
    tree = make_tree(tmp_path / "t")
    (tree / "src" / "fbi" / "research").mkdir()
    (tree / "src" / "fbi" / "research" / "promotions.py").write_text("raise RuntimeError('boom')\n")
    for mode in guard.MODES:
        status, out, err = cli("check", "--before", f"label={OLD}", "--after", f"dir={tree}", "--mode", mode)
        assert (status, out) == (2, "") and "promotions.py does not load: RuntimeError: boom" in err


def test_an_option_that_does_not_exist_is_a_usage_error(tmp_path: Path, cli: Any) -> None:
    for argv in ([], ["check"], ["check", "--before", f"label={OLD}"], ["check", "--after", "dir=x"], ["fingerprint"],
                 ["check", "--before", f"label={OLD}", "--after", "dir=x", "--mode", "strict"], ["verify"]):
        with pytest.raises(SystemExit) as stop:
            guard.main(argv)
        assert stop.value.code == 2


def test_a_python_older_than_the_ledger_needs_is_refused_with_its_name(monkeypatch: pytest.MonkeyPatch, cli: Any, tmp_path: Path) -> None:
    tree = make_tree(tmp_path / "t")
    monkeypatch.setattr(sys, "version_info", (3, 11, 3, "final", 0))
    status, out, err = cli("fingerprint", f"dir={tree}")
    assert (status, out) == (2, "") and err == ("cannot check: this tool needs Python 3.11.4 or newer (datetime.UTC, which the ledger uses, and "
                                                "the filters of tarfile)\n")
    monkeypatch.setattr(sys, "version_info", (3, 11, 4, "final", 0))
    assert cli("fingerprint", f"dir={tree}")[0] == 0, "the oldest it supports"
    monkeypatch.setattr(sys, "version_info", guard.MIN_PYTHON)
    assert cli("fingerprint", f"dir={tree}")[0] == 0, "the floor itself goes, written as the bare three numbers: only what is below it is refused"


def test_the_spec_of_a_tree_is_a_kind_and_a_value() -> None:
    assert guard.split("dir=/a/b") == ("dir", "/a/b")
    assert guard.split("dir=/a=b/c") == ("dir", "/a=b/c"), "only the first = separates"
    assert guard.split("git=HEAD:backend") == ("git", "HEAD:backend")
    assert guard.split("label=mc1111111111") == ("label", "mc1111111111")
    for bad in ("", "dir", "dir=", "=x", "DIR=/a", "folder=/a", "git"):
        with pytest.raises(guard.CannotCheckError):
            guard.split(bad)


# ----------------------------------------------------------------------------------------------------------------------------------------------
# Trees read out of a repository
# ----------------------------------------------------------------------------------------------------------------------------------------------

needs_git = pytest.mark.skipif(shutil.which("git") is None, reason="git is not installed")
GIT_ENV = {"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_SYSTEM": "/dev/null", "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org",
           "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org", "PATH": "/usr/bin:/bin:/usr/local/bin"}


def git(repo: Path, *args: str) -> str:
    done = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True, check=True, env=GIT_ENV)
    return done.stdout.strip()


def commit_all(repo: Path, message: str) -> str:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)
    return git(repo, "rev-parse", "HEAD")


@pytest.fixture()
def history(tmp_path: Path) -> dict[str, Any]:
    """A repository whose root is a backend folder, with four commits: the baseline; a change of model code WITH its entry; a second change of model
    code WITHOUT one; a change that is not model code."""
    repo = tmp_path / "repo"
    make_tree(repo)
    git(repo.parent, "init", "-q", "-b", "main", str(repo))
    base = name(repo)
    set_ledger(repo, [entry(base, by="system", phase="F0", baseline=True)])
    first = commit_all(repo, "baseline")
    (repo / "src/fbi/models/a.py").write_text("NAME = 'models'\nX = 2\n")
    code_two = name(repo)
    set_ledger(repo, [entry(base, by="system", phase="F0", baseline=True), entry(code_two, phase="F1")])
    second = commit_all(repo, "a change with its entry")
    (repo / "src/fbi/domain/a.py").write_text("NAME = 'domain'\nY = 3\n")
    code_three = name(repo)
    third = commit_all(repo, "a change without one")
    (repo / "src/fbi/api/routes.py").write_text("ROUTES = 2\n")
    fourth = commit_all(repo, "a page")
    return {"repo": repo, "commits": (first, second, third, fourth), "codes": (base, code_two, code_three, code_three)}


@needs_git
def test_a_tree_read_from_a_commit_is_the_one_that_was_committed_not_the_one_on_disk(history: dict[str, Any], cli: Any) -> None:
    repo = history["repo"]
    base, code_two, code_three, _ = history["codes"]
    assert len({base, code_two, code_three}) == 3
    for commit, code in zip(history["commits"], history["codes"], strict=True):
        assert cli("fingerprint", f"git={commit}", "--git-dir", str(repo)) == (0, code + "\n", "")
    before = (repo / "src/fbi/models/a.py").read_text()
    (repo / "src/fbi/models/a.py").write_text("NAME = 'edited on disk, not committed'\n")
    try:
        assert cli("fingerprint", "git=HEAD", "--git-dir", str(repo)) == (0, code_three + "\n", ""), "the commit, not the working tree"
        assert cli("fingerprint", f"dir={repo}")[1] != code_three + "\n", "while a dir= is read as it lies"
    finally:
        (repo / "src/fbi/models/a.py").write_text(before)
    assert git(repo, "status", "--porcelain") == "", "and nothing was checked out or changed"


@needs_git
def test_the_three_verdicts_between_the_commits_of_a_history(history: dict[str, Any], cli: Any) -> None:
    repo = history["repo"]
    first, second, third, fourth = history["commits"]
    base, code_two, code_three, _ = history["codes"]
    common = ("--git-dir", str(repo), "--mode", "stop", "--json")

    def verdict(before: str, after: str) -> tuple[int, dict[str, Any]]:
        status, out, err = cli("check", "--before", before, "--after", after, *common)
        assert err == ""
        return status, json.loads(out)

    status, data = verdict(f"git={first}", f"git={second}")
    assert (status, data["status"], data["before"], data["after"], data["covered_by"]["phase"]) == (0, "COVERED", base, code_two, "F1")
    status, data = verdict(f"git={second}", f"git={third}")
    assert (status, data["status"], data["before"], data["after"], data["in_force"]["fingerprint"]) == (4, "UNCOVERED", code_two, code_three, code_two)
    status, data = verdict(f"git={third}", f"git={fourth}")
    assert (status, data["status"], data["changes"]) == (0, "UNCHANGED", False), "a page changed, not the models"
    status, data = verdict(f"label={code_two}", f"git={third}")
    assert (status, data["status"]) == (4, "UNCOVERED"), "production named by its label"
    status, data = verdict("git=HEAD~3", "git=HEAD")
    assert (status, data["status"], data["before"], data["after"]) == (4, "UNCOVERED", base, code_three), "revisions are read as git reads them"


@needs_git
def test_a_tree_inside_a_subfolder_of_the_repository_is_read_with_the_colon_of_git_and_by_its_tree_id(tmp_path: Path, cli: Any) -> None:
    repo = tmp_path / "mono"
    backend = make_tree(repo / "backend")
    (repo / "web").mkdir()
    (repo / "web" / "package.json").write_text("{}\n")
    git(repo.parent, "init", "-q", "-b", "main", str(repo))
    code = name(backend)
    set_ledger(backend, [entry(code, by="system", phase="F0", baseline=True)])
    commit_all(repo, "monorepo")
    tree_id = git(repo, "rev-parse", "HEAD:backend")
    for spec in ("git=HEAD:backend", f"git={tree_id}"):
        assert cli("check", "--before", f"label={code}", "--after", spec, "--git-dir", str(repo), "--json")[:1] == (0,)
        assert cli("fingerprint", spec, "--git-dir", str(repo)) == (0, code + "\n", "")


@needs_git
def test_a_tree_read_from_git_leaves_no_temporary_folder_behind_whether_it_works_or_not(history: dict[str, Any], cli: Any, tmp_path: Path,
                                                                                    monkeypatch: pytest.MonkeyPatch) -> None:
    scratch = tmp_path / "scratch"
    scratch.mkdir()
    monkeypatch.setattr(tempfile, "tempdir", str(scratch))
    repo = str(history["repo"])
    assert cli("fingerprint", "git=HEAD", "--git-dir", repo)[0] == 0
    assert list(scratch.iterdir()) == []
    assert cli("fingerprint", "git=no-such-ref", "--git-dir", repo)[0] == 2
    assert list(scratch.iterdir()) == []


@needs_git
def test_a_commit_that_does_not_exist_or_a_folder_that_is_not_a_repository_is_refused_with_what_git_said(history: dict[str, Any], cli: Any,
                                                                                                    tmp_path: Path) -> None:
    status, out, err = cli("fingerprint", "git=no-such-ref", "--git-dir", str(history["repo"]))
    assert (status, out) == (2, "") and err.startswith("cannot check: git archive no-such-ref in ") and "failed: " in err and "no-such-ref" in err
    status, out, err = cli("fingerprint", "git=HEAD", "--git-dir", str(tmp_path))
    assert (status, out) == (2, "") and "git archive HEAD in " in err and "failed" in err


def test_git_that_cannot_run_or_does_not_answer_in_time_is_refused(monkeypatch: pytest.MonkeyPatch, cli: Any, tmp_path: Path) -> None:
    asked: dict[str, Any] = {}

    def no_git(argv: list[str], **kwargs: Any) -> None:
        asked["argv"], asked["kwargs"] = argv, kwargs
        raise FileNotFoundError(2, "No such file or directory: 'git'")

    monkeypatch.setattr(subprocess, "run", no_git)
    status, out, err = cli("fingerprint", "git=HEAD", "--git-dir", str(tmp_path))
    assert (status, out) == (2, "") and err.startswith("cannot check: git could not read 'HEAD' in ") and "FileNotFoundError" in err
    argv = asked["argv"]
    assert argv[:5] == ["git", "-C", str(tmp_path), "archive", "--format=tar"] and argv[-3:] == ["HEAD", "--", "src/fbi"]
    assert len(argv) == 9 and argv[5].startswith("--output=") and argv[5].endswith("tree.tar"), "an archive of src/fbi of the tree-ish, in a file"
    assert asked["kwargs"] == {"capture_output": True, "text": True, "check": False, "timeout": 120} and guard.GIT_SECONDS == 120

    def slow_git(argv: list[str], **kwargs: Any) -> None:
        raise subprocess.TimeoutExpired(argv, 120)

    monkeypatch.setattr(subprocess, "run", slow_git)
    status, out, err = cli("fingerprint", "git=HEAD", "--git-dir", str(tmp_path))
    assert (status, out) == (2, "") and "git could not read 'HEAD'" in err and "TimeoutExpired" in err


def test_a_failing_git_says_what_it_said_or_that_it_said_nothing(monkeypatch: pytest.MonkeyPatch, cli: Any, tmp_path: Path) -> None:
    monkeypatch.setattr(subprocess, "run", lambda argv, **kwargs: subprocess.CompletedProcess(argv, 1, "", "  \n"))
    status, out, err = cli("fingerprint", "git=HEAD", "--git-dir", str(tmp_path))
    assert (status, out) == (2, "") and err.endswith("failed: no message\n")
    words = "fatal: not a valid object name: HEAD"
    monkeypatch.setattr(subprocess, "run", lambda argv, **kwargs: subprocess.CompletedProcess(argv, 128, "", f"  {words}\n"))
    status, out, err = cli("fingerprint", "git=HEAD", "--git-dir", str(tmp_path))
    assert (status, out) == (2, "") and err.endswith(f" failed: {words}\n"), "git's own words, trimmed, are what the owner reads"


@needs_git
def test_the_repository_is_the_current_folder_unless_one_is_named(history: dict[str, Any], cli: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    code_three = history["codes"][2]
    monkeypatch.chdir(history["repo"])
    assert cli("fingerprint", "git=HEAD") == (0, code_three + "\n", "")
    status, out, _ = cli("check", "--before", "git=HEAD~2", "--after", "git=HEAD", "--json")
    assert (status, json.loads(out)["status"]) == (0, "UNCOVERED"), "and for a check too (inform: it goes on)"
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    assert cli("fingerprint", "git=HEAD")[0] == 2, "the folder it is run in is not a repository"
    assert cli("fingerprint", "git=HEAD", "--git-dir", str(history["repo"])) == (0, code_three + "\n", "")


@needs_git
def test_what_is_unpacked_from_git_is_src_fbi_of_the_tree_and_nothing_warns_about_how(history: dict[str, Any], tmp_path: Path) -> None:
    import warnings
    into = tmp_path / "into"
    into.mkdir()
    with warnings.catch_warnings():
        warnings.simplefilter("error")  # tarfile warns when extractall is called without a filter
        root = guard.export(str(history["repo"]), "HEAD", into)
    assert root == into / "tree" and (root / "src" / "fbi" / "core" / "version.py").is_file()
    assert sorted(p.name for p in (root / "src" / "fbi").iterdir()) == sorted(["core", "research", "api", *MODEL_PACKAGES])
    assert guard.label_of(root) == history["codes"][2]


def test_a_folder_that_has_a_file_where_src_fbi_should_be_is_not_a_tree(tmp_path: Path, cli: Any) -> None:
    (tmp_path / "src").mkdir()
    (tmp_path / "src" / "fbi").write_text("not a folder\n")
    status, out, err = cli("fingerprint", f"dir={tmp_path}")
    assert (status, out) == (2, "") and "has no src/fbi inside" in err


# ----------------------------------------------------------------------------------------------------------------------------------------------
# The tool on its own
# ----------------------------------------------------------------------------------------------------------------------------------------------

def test_the_tool_imports_nothing_outside_the_standard_library() -> None:
    """It runs with the plain python3 of the server, before the release is built: no fbi, no third-party package."""
    tree = ast.parse(SCRIPT.read_text())
    imported = {alias.name.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.Import) for alias in node.names}
    imported |= {node.module.split(".")[0] for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module and node.level == 0}
    assert imported and imported <= set(sys.stdlib_module_names), sorted(imported - set(sys.stdlib_module_names))
    assert "fbi" not in imported


def test_the_tool_runs_as_a_script_in_a_bare_interpreter_and_exits_with_the_status_of_the_verdict(tmp_path: Path) -> None:
    covered, _ = changed_tree(tmp_path / "c", [entry(OLD, by="system", phase="F0", baseline=True), entry("@NEW@")])
    uncovered, code = changed_tree(tmp_path / "u", [entry(OLD, by="system", phase="F0", baseline=True)])
    bare = tmp_path / "bare"
    bare.mkdir()

    def launch(*argv: str) -> subprocess.CompletedProcess[str]:
        return subprocess.run([sys.executable, "-I", str(SCRIPT), *argv], capture_output=True, text=True, cwd=bare, check=False)

    done = launch("check", "--before", f"label={OLD}", "--after", f"dir={uncovered}", "--mode", "stop")
    assert done.returncode == 4 and "THE RELEASE STOPS HERE" in done.stdout and done.stderr == ""
    done = launch("check", "--before", f"label={OLD}", "--after", f"dir={uncovered}")
    assert done.returncode == 0 and "the release goes on" in done.stdout
    done = launch("check", "--before", f"label={OLD}", "--after", f"dir={covered}", "--mode", "stop")
    assert done.returncode == 0 and done.stdout.splitlines()[-2].startswith("COVERED: THE MODEL CODE CHANGES")
    done = launch("fingerprint", f"dir={uncovered}")
    assert (done.returncode, done.stdout) == (0, code + "\n")
    done = launch("fingerprint", f"dir={bare}")
    assert done.returncode == 2 and done.stderr.startswith("cannot check: ")
    done = launch("check")
    assert done.returncode == 2 and "usage: " in done.stderr


def test_the_tool_names_the_code_of_the_real_tree_the_way_the_project_does_when_run_as_a_script(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FBI_MODEL_CODE_VERSION", raising=False)
    done = subprocess.run([sys.executable, "-I", str(SCRIPT), "fingerprint", f"dir={BACKEND}"], capture_output=True, text=True, check=True)
    assert done.stdout == model_code_version.__wrapped__() + "\n"
