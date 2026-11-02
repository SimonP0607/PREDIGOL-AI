"""The release guard for the code of the models (plan F12.7, owner decision 19): does a release change the code that decides what the models
predict, and is that change on record?

    python3 scripts/model_code_guard.py fingerprint <tree>
    python3 scripts/model_code_guard.py check --before <tree> --after <tree> [--git-dir <repository>] [--mode inform|stop] [--json]

A tree is named ``dir=<folder>`` (a backend folder: the one with ``src/fbi`` inside), ``git=<tree-ish>`` (read out of the repository that
``--git-dir`` names - ``HEAD``, ``FETCH_HEAD``, a commit, ``HEAD:backend`` - without checking anything out) or, for ``--before`` only,
``label=mc<10 hex>`` (the code production forecasts with, when only its name is at hand).

The code of the models has a fingerprint (``fbi.core.version.model_code_fingerprint``): a change to any of the packages that decide what a model
predicts opens new versions of every model, and the forecast runs with them from its next pass. Since F12 the ledger ``fbi/research/promotions.py``
holds one entry per fingerprint, added in the same commit as the change, and ``tests/unit/test_model_code_ledger.py`` fails while the fingerprint of
the tree is not the last entry. That test runs in the gate of whoever builds the release and not on the server. This tool asks the same question
of the two trees a release moves between - the one production runs and the one the package carries - at the two places the release passes
through: when the package is made and, on the server, before anything moves.

Three verdicts: ``UNCHANGED`` (the same code), ``COVERED`` (the code changes and the ledger of the new tree puts exactly that code in force) and
``UNCOVERED`` (the code changes and the ledger does not). Two modes: ``inform`` (the default: the verdict is printed and the release goes on, the
owner being told) and ``stop`` (an ``UNCOVERED`` release exits with status 4). Status 2 is "could not check" - a tree that cannot be read is never a
green light. Status 0 is everything else.

A tree is read with its OWN ``version.py`` and ``promotions.py``, loaded by path: the answer is the one the code that will run would give. The tool
imports nothing of ``fbi`` and nothing outside the standard library, and touches neither the database nor the network, so it runs with the plain
``python3`` of the server before the release is built. It writes nothing; for a ``git=`` tree it unpacks ``src/fbi`` into a temporary folder it
removes.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import subprocess
import sys
import tarfile
import tempfile
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any, Final

MODES: Final = ("inform", "stop")
DEFAULT_MODE: Final = "inform"
UNCHANGED: Final = "UNCHANGED"
COVERED: Final = "COVERED"
UNCOVERED: Final = "UNCOVERED"
STATUSES: Final = (UNCHANGED, COVERED, UNCOVERED)
EXIT_GO: Final = 0
EXIT_CANNOT_CHECK: Final = 2
EXIT_STOP: Final = 4
SOURCE: Final = "src/fbi"
VERSION_FILE: Final = "src/fbi/core/version.py"
LEDGER_FILE: Final = "src/fbi/research/promotions.py"
LABEL: Final = re.compile(r"mc[0-9a-f]{10}")
FINGERPRINT: Final = re.compile(r"[0-9a-f]{12}")
KINDS: Final = ("dir", "git", "label")
REASON_CHARS: Final = 160
"""How much of the reason of an entry the text of a verdict quotes (the JSON has all of it)."""
GIT_SECONDS: Final = 120
MIN_PYTHON: Final = (3, 11, 4)
"""``datetime.UTC`` (the ledger imports it) came with 3.11 and the ``filter`` of ``tarfile.extractall`` with 3.11.4; the project itself runs 3.12."""


class CannotCheckError(Exception):
    """The tree could not be read, or the question was not well asked: never a green light."""


@dataclass(frozen=True, slots=True)
class Entry:
    """One entry of the ledger of a tree, as the guard reads it."""

    fingerprint: str
    decided_at: datetime
    decided_by: str
    phase: str
    baseline: bool
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {"fingerprint": self.fingerprint, "decided_at": self.decided_at.isoformat(), "decided_by": self.decided_by,
                "phase": self.phase, "baseline": self.baseline, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class Verdict:
    mode: str
    status: str
    before: str
    after: str
    has_ledger: bool
    in_force: Entry | None
    """The last entry of the ledger of the new tree: the code it says production forecasts with."""
    covered_by: Entry | None
    """The entry that puts exactly ``after`` in force (the last one, and it names ``after``); None when there is none."""

    @property
    def stops(self) -> bool:
        return self.mode == "stop" and self.status == UNCOVERED

    @property
    def ledger_agrees(self) -> bool:
        return self.covered_by is not None

    def as_dict(self) -> dict[str, Any]:
        return {"mode": self.mode, "status": self.status, "before": self.before, "after": self.after, "changes": self.status != UNCHANGED,
                "has_ledger": self.has_ledger, "ledger_agrees": self.ledger_agrees, "stops": self.stops,
                "in_force": self.in_force.as_dict() if self.in_force else None,
                "covered_by": self.covered_by.as_dict() if self.covered_by else None}


def load(path: Path, name: str) -> ModuleType:
    """Run the module at ``path`` under ``name`` (registered while it runs, as a dataclass needs) and give it back."""
    spec = importlib.util.spec_from_file_location(name, path) if path.is_file() else None
    if spec is None or spec.loader is None:
        raise CannotCheckError(f"{path} is not a Python file that can be loaded")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    previous, sys.dont_write_bytecode = sys.dont_write_bytecode, True  # reading a tree leaves no __pycache__ in it
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise CannotCheckError(f"{path} does not load: {type(exc).__name__}: {exc}") from exc
    finally:
        sys.dont_write_bytecode = previous
        sys.modules.pop(name, None)
    return module


def label_of(root: Path) -> str:
    """``mc`` and the first ten hex digits of the fingerprint that the ``version.py`` of the tree gives its own model packages: the way a model
    version names its code (``...@mc9a7bec97ca``)."""
    version = load(root / VERSION_FILE, "model_code_guard_version")
    try:
        packages = tuple(version.MODEL_PACKAGES)
        fingerprint = version.model_code_fingerprint()
    except Exception as exc:  # whatever the tree's own code raises, it did not give a name
        raise CannotCheckError(f"{root / VERSION_FILE} does not give a fingerprint: {type(exc).__name__}: {exc}") from exc
    for package in packages:
        if not any((root / SOURCE / package).rglob("*.py")):
            raise CannotCheckError(f"the tree has no Python source in the model package {package!r}: its fingerprint would be that of nothing")
    if not isinstance(fingerprint, str) or FINGERPRINT.fullmatch(fingerprint) is None:
        raise CannotCheckError(f"{root / VERSION_FILE} gave {fingerprint!r}, not 12 hex digits")
    return f"mc{fingerprint[:10]}"


def ledger_of(root: Path) -> tuple[Entry, ...] | None:
    """The entries of the ledger of the tree, oldest first; None when the tree has no ledger at all (it is older than plan F12)."""
    path = root / LEDGER_FILE
    if not path.is_file():
        return None
    module = load(path, "model_code_guard_ledger")
    try:
        return tuple(Entry(p.fingerprint, p.decided_at, p.decided_by, p.phase, p.baseline, p.reason) for p in module.LEDGER)
    except Exception as exc:  # no LEDGER, one that cannot be iterated, entries without the fields: not a ledger the guard can read
        raise CannotCheckError(f"{path} has a ledger the guard cannot read: {type(exc).__name__}: {exc}") from exc


def assess(before: str, after: Path, mode: str = DEFAULT_MODE) -> Verdict:
    """The code production forecasts with (``before``, a label) against the tree the release carries (``after``)."""
    if mode not in MODES:
        raise CannotCheckError(f"the mode is one of {', '.join(MODES)}, not {mode!r}")
    if LABEL.fullmatch(before) is None:
        raise CannotCheckError(f"{before!r} is not the name of a model code (mc and ten hex digits)")
    code = label_of(after)
    entries = ledger_of(after)
    in_force = entries[-1] if entries else None
    covered_by = in_force if in_force is not None and in_force.fingerprint == code else None
    status = UNCHANGED if before == code else COVERED if covered_by is not None else UNCOVERED
    return Verdict(mode, status, before, code, entries is not None, in_force, covered_by)


def day(moment: datetime) -> str:
    return moment.astimezone(UTC).strftime("%Y-%m-%d %H:%M UTC")


def quote(reason: str) -> str:
    one_line = " ".join(reason.split())
    return one_line if len(one_line) <= REASON_CHARS else one_line[:REASON_CHARS].rstrip() + "..."


def render(v: Verdict) -> str:
    """The verdict in words, for whoever reads the log of the release."""
    if v.in_force is None:
        in_force = "none: this tree has no ledger (it is older than plan F12)" if not v.has_ledger else "none: the ledger has no entries"
    else:
        in_force = (f"{v.in_force.fingerprint} ({v.in_force.phase}, decided by {v.in_force.decided_by} on {day(v.in_force.decided_at)}"
                    f"{', baseline' if v.in_force.baseline else ''})")
    lines = [f"model-code guard - mode {v.mode}",
             f"  production runs  {v.before}",
             f"  the release has  {v.after}",
             f"  ledger in force  {in_force}"]
    move = f"{v.before} -> {v.after}"
    if v.status == UNCHANGED:
        lines.append(f"{UNCHANGED}: the release does not touch the code that decides what the models predict; no model opens a new version.")
        if not v.ledger_agrees:
            lines.append("note: the last entry of the ledger is not this code, so tests/unit/test_model_code_ledger.py would fail in the gate; "
                         "nothing changes in production.")
    elif v.covered_by is not None:
        entry = v.covered_by
        lines.append(f"{COVERED}: THE MODEL CODE CHANGES ({move}) and the ledger puts the new code in force: {entry.phase}, decided by "
                     f"{entry.decided_by} on {day(entry.decided_at)}: {quote(entry.reason)}")
        lines.append("Every model opens new versions and the forecast runs with them from its next pass.")
    else:
        why = ("this tree has no ledger" if not v.has_ledger
               else "the ledger has no entries" if v.in_force is None
               else f"its last entry is {v.in_force.fingerprint}")
        lines.append(f"{UNCOVERED}: THE MODEL CODE CHANGES ({move}) and the ledger does not put the new code in force ({why}).")
        lines.append("Every model would open new versions and the forecast would run with them from its next pass, with no decision on record.")
        lines.append(f"mode stop: THE RELEASE STOPS HERE (exit status {EXIT_STOP})." if v.mode == "stop"
                     else "mode inform: the release goes on; the owner is told before it is deployed.")
    return "\n".join(lines)


def split(spec: str) -> tuple[str, str]:
    kind, _, value = spec.partition("=")
    if kind not in KINDS or not value:
        raise CannotCheckError(f"{spec!r} does not name a tree: dir=<folder>, git=<tree-ish> or (for --before) label=mc<10 hex>")
    return kind, value


def export(git_dir: str, treeish: str, into: Path) -> Path:
    """Unpack ``src/fbi`` of ``treeish`` into ``into`` and give the folder that has it. Nothing is checked out: it is read from the repository."""
    if treeish.startswith("-"):
        raise CannotCheckError(f"{treeish!r} is not a tree-ish")
    archive = into / "tree.tar"
    try:
        run = subprocess.run(["git", "-C", git_dir, "archive", "--format=tar", f"--output={archive}", treeish, "--", SOURCE],
                             capture_output=True, text=True, check=False, timeout=GIT_SECONDS)
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CannotCheckError(f"git could not read {treeish!r} in {git_dir}: {type(exc).__name__}: {exc}") from exc
    if run.returncode != 0:
        raise CannotCheckError(f"git archive {treeish} in {git_dir} failed: {run.stderr.strip() or 'no message'}")
    root = into / "tree"
    with tarfile.open(archive) as tar:
        tar.extractall(root, filter="data")
    return root


@contextmanager
def opened(spec: str, git_dir: str) -> Iterator[Path]:
    """The folder of a tree named ``dir=`` or ``git=``."""
    kind, value = split(spec)
    if kind == "label":
        raise CannotCheckError(f"{spec!r} is a name, not a tree: only --before takes a label")
    if kind == "dir":
        if not (Path(value) / SOURCE).is_dir():
            raise CannotCheckError(f"{value} has no {SOURCE} inside: a tree is a backend folder")
        yield Path(value)
        return
    with tempfile.TemporaryDirectory(prefix="model-code-guard-") as tmp:
        yield export(git_dir, value, Path(tmp))


def before_label(spec: str, git_dir: str) -> str:
    """The name of the code production forecasts with, from a label or from a tree."""
    kind, value = split(spec)
    if kind == "label":
        return value
    with opened(spec, git_dir) as root:
        return label_of(root)


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True)
    one = sub.add_parser("fingerprint", help="print the name of the model code of a tree (mc and ten hex digits)")
    one.add_argument("tree", help="dir=<folder> or git=<tree-ish>")
    one.add_argument("--git-dir", default=".", help="the repository a git= tree is read from (default: the current folder)")
    check = sub.add_parser("check", help="the code production runs against the code the release carries")
    check.add_argument("--before", required=True, help="the code in production: dir=, git= or label=")
    check.add_argument("--after", required=True, help="the code of the release: dir= or git=")
    check.add_argument("--git-dir", default=".", help="the repository the git= trees are read from (default: the current folder)")
    check.add_argument("--mode", choices=MODES, default=DEFAULT_MODE,
                       help="inform: print and go on (default); stop: exit with status 4 when the code changes and no entry puts it in force")
    check.add_argument("--json", action="store_true", help="print the verdict as JSON")
    return ap


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if sys.version_info < MIN_PYTHON:
        print(f"cannot check: this tool needs Python {'.'.join(map(str, MIN_PYTHON))} or newer (datetime.UTC, which the ledger uses, and the "
              "filters of tarfile)", file=sys.stderr)
        return EXIT_CANNOT_CHECK
    try:
        if args.command == "fingerprint":
            with opened(args.tree, args.git_dir) as root:
                print(label_of(root))
            return EXIT_GO
        before = before_label(args.before, args.git_dir)
        with opened(args.after, args.git_dir) as root:
            verdict = assess(before, root, args.mode)
    except CannotCheckError as exc:
        print(f"cannot check: {exc}", file=sys.stderr)
        return EXIT_CANNOT_CHECK
    print(json.dumps(verdict.as_dict(), indent=1, sort_keys=True) if args.json else render(verdict))
    return EXIT_STOP if verdict.stops else EXIT_GO


if __name__ == "__main__":
    raise SystemExit(main())
