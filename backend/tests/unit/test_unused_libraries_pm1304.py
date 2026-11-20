"""PM-13-04 (OPS-012): the libraries that left the production image stay out of the code the image runs.

statsmodels, duckdb, pyarrow and pandas were installed in the image (the ``analytics`` extra) and nothing imported them; lightgbm was
declared in ``ml`` and nothing imported it; polars was a base dependency that only the legacy catalogue importer reads. They moved to the
``lab`` extra (lightgbm was dropped). This walks every module of ``src/fbi``, ``apps``, ``scripts`` and ``migrations``: none imports one of
them, except polars inside the function of the legacy importer that reads the parquet files (and under ``TYPE_CHECKING`` for its types),
so the API, the worker, the messenger and every command still import without them."""

from __future__ import annotations

import ast
import subprocess
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
ROOTS = ("src/fbi", "apps", "scripts", "migrations")
LAB_ONLY = frozenset({"duckdb", "pyarrow", "statsmodels", "pandas", "polars", "lightgbm", "patsy"})
LEGACY = "src/fbi/catalog/legacy_import.py"


def imports(path: Path) -> list[tuple[str, bool]]:
    """(top-level module, imported at module level outside ``if TYPE_CHECKING``) for every import of ``path``."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    out: list[tuple[str, bool]] = []

    def walk(node: ast.AST, top: bool) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, ast.Import):
                out.extend((alias.name.split(".")[0], top) for alias in child.names)
            elif isinstance(child, ast.ImportFrom) and child.module and child.level == 0:
                out.append((child.module.split(".")[0], top))
            elif (isinstance(child, ast.If) and "TYPE_CHECKING" in ast.unparse(child.test)) or isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda)):
                walk(child, False)
            else:
                walk(child, top)

    walk(tree, True)
    return out


def test_nothing_the_image_runs_imports_a_lab_library() -> None:
    found: dict[str, list[tuple[str, bool]]] = {}
    for root in ROOTS:
        for path in sorted((BACKEND / root).rglob("*.py")):
            hits = [(name, top) for name, top in imports(path) if name in LAB_ONLY]
            if hits:
                found[path.relative_to(BACKEND).as_posix()] = hits
    assert set(found) <= {LEGACY}, f"modules that import a library the image no longer has: {sorted(set(found) - {LEGACY})}"
    assert found.get(LEGACY) and all(name == "polars" and not top for name, top in found[LEGACY]), (
        "the legacy importer imports polars only when it runs (and for its types under TYPE_CHECKING)")


def test_the_competitions_command_and_the_importer_load_without_polars() -> None:
    """``manage_competitions apply``/``probe`` run in production and import the legacy importer: with polars hidden, they still load."""
    code = (
        "import sys\n"
        "class Block:\n"
        "    def find_spec(self, name, path=None, target=None):\n"
        f"        if name.split('.')[0] in {sorted(LAB_ONLY)!r}:\n"
        "            raise ImportError('not in the image: ' + name)\n"
        "        return None\n"
        "sys.meta_path.insert(0, Block())\n"
        "import fbi.catalog.legacy_import, scripts.manage_competitions, apps.api.main, apps.worker.scheduler\n"
        "print('ok')\n"
    )
    done = subprocess.run([sys.executable, "-c", code], cwd=BACKEND, capture_output=True, text=True, timeout=180,
                          env={"PYTHONPATH": f"{BACKEND}:{BACKEND / 'src'}", "PATH": "/usr/bin:/bin", "FBI_ENV": "test"})
    assert done.returncode == 0 and done.stdout.strip().endswith("ok"), done.stderr[-2000:]
