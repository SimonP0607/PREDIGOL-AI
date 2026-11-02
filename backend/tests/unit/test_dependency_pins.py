"""Plan F14: the libraries of the backend image are the ones ``constraints.txt`` names, and the Dockerfile installs with that file.

Before F14 the image was built with ``pip install -e ".[analytics]"``, which only asks for lower bounds (``>=``). That layer of the image is rebuilt
whenever ``pyproject.toml`` changes (it was at the releases of F2, F3.2/F5, F7 and F10, each time the list of packages mypy checks grew), and each
rebuild took whatever was newest that day: production came to run FastAPI 0.162.0, pandas 3.1.0 and sentry-sdk 2.73.0 while the gate ran 0.159.1,
3.0.6 and 2.72.0. Nobody chose that, nothing recorded it, and the fingerprint of the model code does not see a library.

``constraints.txt`` is the freeze of the running image (minus the project itself) and the Dockerfile installs with ``-c constraints.txt``. This file
keeps the pieces tied together without the network: the file is a sorted list of exact pins; it names every library ``pyproject.toml`` asks of the
image and no other; the environment THIS run is in has those very versions - so the gate is run on what production runs, and a library upgraded
without the file (or a file edited without installing it) fails here -; the Dockerfile copies the file before ``pip`` and passes it with ``-c``;
``.dockerignore`` lets it into the build; and the owner's guide says how many libraries are fixed and which base images still are not."""

from __future__ import annotations

import fnmatch
import re
import sys
import tomllib
from importlib import metadata
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

BACKEND = Path(__file__).resolve().parents[2]
CONSTRAINTS = BACKEND / "constraints.txt"
DOCKERFILE = BACKEND / "Dockerfile"
DOCKERIGNORE = BACKEND / ".dockerignore"
GUIDE = BACKEND / "docs" / "owner" / "DEPENDENCIAS_F14.md"
PIN = re.compile(r"^(?P<name>[A-Za-z0-9][A-Za-z0-9._-]*)==(?P<version>[0-9][A-Za-z0-9.!+_-]*)$")
INSTALL_COMMAND = 'pip install -c constraints.txt -e ".[dev,analytics]"'


def pin_lines() -> list[tuple[str, str]]:
    """(name as written, version) of every line of constraints.txt, in file order; a line that is not an exact pin fails."""
    found: list[tuple[str, str]] = []
    for number, raw in enumerate(CONSTRAINTS.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        match = PIN.match(line)
        assert match, f"constraints.txt line {number} is not an exact pin (name==version): {line!r}"
        found.append((match["name"], match["version"]))
    return found


def pins() -> dict[str, str]:
    """canonical name -> version."""
    return {canonicalize_name(name): version for name, version in pin_lines()}


def dockerfile_instructions() -> list[str]:
    """The Dockerfile without comments, each instruction on one line (continuations joined)."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    lines = [line for line in text.splitlines() if not line.lstrip().startswith("#")]
    return [re.sub(r"\s+", " ", part).strip() for part in "\n".join(lines).replace("\\\n", " ").splitlines() if part.strip()]


def installed_extras() -> list[str]:
    """The extras the Dockerfile installs (``pip install -e ".[analytics]"``): the image is what these name, and nothing else."""
    commands = [line for line in dockerfile_instructions() if "pip install" in line]
    assert len(commands) == 1, f"the image must install its libraries in one place, found {len(commands)} 'pip install'"
    command = commands[0]
    found = re.search(r'"\.\[([a-z,]+)\]"', command)
    assert found, f"the Dockerfile does not install the project with extras: {command}"
    return found[1].split(",")


def image_requirements() -> list[Requirement]:
    """What pyproject.toml asks of the image: the runtime dependencies and the extras the Dockerfile installs."""
    project = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    texts = list(project["dependencies"])
    for extra in installed_extras():
        texts += project["optional-dependencies"][extra]
    return [Requirement(text) for text in texts]


def test_constraints_is_a_sorted_list_of_exact_pins_without_repeats() -> None:
    lines = pin_lines()
    assert lines, "constraints.txt has no pin"
    names = [name for name, _ in lines]
    assert names == sorted(names, key=str.lower), "keep constraints.txt sorted by name, so that a change shows as one line"
    canonical = [canonicalize_name(name) for name in names]
    assert len(canonical) == len(set(canonical)), f"a library is pinned twice: {sorted({n for n in canonical if canonical.count(n) > 1})}"


def test_every_library_pyproject_asks_of_the_image_is_pinned_at_a_version_it_accepts() -> None:
    found = pins()
    for requirement in image_requirements():
        name = canonicalize_name(requirement.name)
        assert name in found, f"pyproject.toml asks for {requirement.name} and constraints.txt does not pin it"
        assert requirement.specifier.contains(found[name], prereleases=True), (
            f"constraints.txt pins {requirement.name}=={found[name]}, which pyproject.toml ({requirement.specifier}) does not accept"
        )


@pytest.mark.skipif(sys.platform != "linux", reason="the image is Linux: its libraries are the ones Linux installs")
def test_the_pins_are_the_libraries_the_image_installs_and_this_run_has_those_versions() -> None:
    """Walk what pip would install for the Dockerfile's command - the requirements of the installed metadata, with their extras and markers - and
    compare it with the file, library by library and version by version. So the gate really is run on what production runs; a library that a
    change of pyproject.toml brings in or drops (or that an upgrade of another one does) shows up here, with the line to add or to remove."""
    found = pins()
    installed: dict[str, str] = {}
    missing: set[str] = set()
    seen: set[tuple[str, frozenset[str]]] = set()
    todo = [(canonicalize_name(r.name), frozenset(r.extras)) for r in image_requirements()]
    while todo:
        item = todo.pop()
        if item in seen:
            continue
        seen.add(item)
        name, extras = item
        try:
            distribution = metadata.distribution(name)
        except metadata.PackageNotFoundError:
            missing.add(name)
            continue
        installed[name] = distribution.version
        for line in distribution.requires or []:
            requirement = Requirement(line)
            if requirement.marker is not None and not any(requirement.marker.evaluate({"extra": extra}) for extra in ("", *extras)):
                continue
            todo.append((canonicalize_name(requirement.name), frozenset(requirement.extras)))
    not_pinned = sorted(set(installed) - set(found))
    not_needed = sorted(set(found) - set(installed) - missing)
    other_version = {name: (installed[name], found[name]) for name in sorted(set(installed) & set(found)) if installed[name] != found[name]}
    problems = []
    if missing:
        problems.append(f"not installed here: {sorted(missing)}")
    if not_pinned:
        problems.append(f"the image would install these and constraints.txt does not pin them: {not_pinned}")
    if not_needed:
        problems.append(f"constraints.txt pins these and the image would not install them: {not_needed}")
    if other_version:
        problems.append(f"installed here at another version than the file's (installed, pinned): {other_version}")
    assert not problems, "; ".join(problems) + f". To install what the file says: {INSTALL_COMMAND}"


def test_the_dockerfile_copies_the_constraints_and_installs_with_them() -> None:
    instructions = dockerfile_instructions()
    copies = [i for i, line in enumerate(instructions) if line.startswith("COPY ") and "constraints.txt" in line and "pyproject.toml" in line]
    installs = [i for i, line in enumerate(instructions) if "pip install" in line]
    assert len(installs) == 1, f"the image must install its libraries in one place, found {len(installs)} 'pip install'"
    assert copies, "the Dockerfile does not copy constraints.txt beside pyproject.toml"
    assert copies[0] < installs[0], "constraints.txt must be copied BEFORE the pip layer"
    assert re.search(r"pip install (?:\S+ )*(?:-c|--constraint)[ =]constraints\.txt\b", instructions[installs[0]]), "pip install does not use -c constraints.txt"
    assert not [line for line in instructions if line.startswith("COPY ") and "constraints.txt" in line and "pyproject.toml" not in line], (
        "constraints.txt must be copied in the same step as pyproject.toml, so that the pip layer is rebuilt when either changes"
    )


def test_the_build_context_lets_the_constraints_in() -> None:
    patterns = [line.strip() for line in DOCKERIGNORE.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith(("#", "!"))]
    assert not [p for p in patterns if fnmatch.fnmatch("constraints.txt", p)], "a .dockerignore pattern keeps constraints.txt out of the build"


def test_the_owner_guide_says_what_the_code_does() -> None:
    """The guide: how many libraries are fixed, the command that installs them, the base image the Dockerfile uses and the one of the web."""
    if not GUIDE.is_file():
        pytest.skip(f"no {GUIDE.name} next to the code")
    doc = GUIDE.read_text(encoding="utf-8")
    assert f"**{len(pins())} bibliotecas**" in doc, "the guide must say how many libraries constraints.txt fixes"
    assert INSTALL_COMMAND in doc and "constraints.txt" in doc
    bases = [match[1] for line in DOCKERFILE.read_text(encoding="utf-8").splitlines() if (match := re.match(r"^FROM (\S+)", line))]
    web = BACKEND.parent / "web" / "Dockerfile"
    if web.is_file():
        bases += [match[1] for line in web.read_text(encoding="utf-8").splitlines() if (match := re.match(r"^FROM (\S+)", line))]
    assert bases, "no FROM line found"
    for base in bases:
        assert f"`{base}`" in doc, f"the guide must name the base image {base}: it is what still floats"
