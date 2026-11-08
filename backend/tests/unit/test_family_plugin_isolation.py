"""The plug-in families (``fbi.plugins``, ``family-plugin-v1``) are in SHADOW: nothing that decides, publishes, stakes or serves users
imports the package - nothing outside it does at all (the example is registered by a test, at run time) - no family is installed, the
package writes nothing, and it reaches the portfolio only by the shape of its correlation provider, never by import."""

from __future__ import annotations

import ast
import re
from pathlib import Path

from fbi.plugins import registry

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "fbi"
PACKAGE = "fbi.plugins"
OWN = SRC / "plugins"


def imported(path: Path) -> set[str]:
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(a.name for a in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and not node.level:
            found.add(node.module)
            found.update(f"{node.module}.{a.name}" for a in node.names)
    return found


def imports_package(path: Path) -> bool:
    return any(n == PACKAGE or n.startswith(PACKAGE + ".") for n in imported(path))


def files(*roots: Path) -> list[Path]:
    return sorted(p for r in roots if r.exists() for p in r.rglob("*.py") if "__pycache__" not in p.parts)


def test_nothing_outside_the_package_imports_it() -> None:
    importing = [p.relative_to(ROOT).as_posix() for p in files(SRC, ROOT / "scripts", ROOT / "apps")
                 if OWN not in p.parents and imports_package(p)]
    assert not importing, f"the plug-in families are shadow-only; these modules import them: {importing}"


def test_no_family_is_installed() -> None:
    assert registry.INSTALLED == ()


def test_the_package_writes_nothing_and_reaches_no_serving_layer_nor_the_stake() -> None:
    own = files(OWN)
    assert own, "the package exists"
    writes = re.compile(r"\b(INSERT\s+INTO|UPDATE\s+[\w.]+\s+SET|DELETE\s+FROM|TRUNCATE|CREATE\s+TABLE)\b", re.IGNORECASE)
    for p in own:
        source = p.read_text(encoding="utf-8")
        assert not writes.search(source) and ".commit(" not in source, p.name
        names = imported(p)
        bad = [n for n in names if n.split(".")[1:2] and n.split(".")[1] in ("api", "notify", "messaging", "customer", "narrative",
                                                                          "parlays", "portfolio", "ai")]
        assert not bad, (p.relative_to(SRC).as_posix(), bad)
        assert not [n for n in names if n.startswith("fbi.intel.stake")], p.name


def test_the_scan_sees_every_way_of_importing_it(tmp_path: Path) -> None:
    for text in ("import fbi.plugins", "from fbi.plugins import registry", "from fbi.plugins._template.family import PLUGIN",
                 "def f():\n    from fbi.plugins.family import promote\n"):
        probe = tmp_path / "probe.py"
        probe.write_text(text, encoding="utf-8")
        assert imports_package(probe), text
