"""decision-v2 (``fbi.decision``) is in SHADOW: it computes and reports, and nothing that decides, publishes, stakes or serves users may import
it. The scan reads every import (lazy ones too) of ``src/fbi``, ``apps`` and ``scripts``: outside the package itself, the only importer is its
own read-only command. A new importer fails here until someone decides it may read. The package's own imports are held too: it reaches the
signals of the market and the decision of the families only through the one module each, and never the stake."""

from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SRC = ROOT / "src" / "fbi"
PACKAGE = "fbi.decision"
ALLOWED = {"scripts/ia_decision_v2.py": "the command that prints the replay (read-only)",
           "scripts/ia_price_rule.py": "the command that prints the price rule's report, a yardstick never a pick (read-only, INT-A10)",
           "plugins/family.py": "the plug-in families (IA-018, shadow) compose the MarketFamily protocol",
           "plugins/registry.py": "the registry of plug-in families hands decision-v2 its families (shadow)",
           "plugins/_template/family.py": "the example plug-in's decision-v2 adapter (shadow, never active, not installed)",
           "shadowjobs/decision_v2.py": "the worker's door to the kept shadow (IA-093, AD-D01): its switch and one pass, which writes only "
                                        "decision-v2's own tables; only the scheduler imports it",
           "evalcycle/run.py": "the evaluation cycle's passes (IA-105, AD-D06, shadow): its E1-E4 keep their decision as a version of "
                               "decision-v2 through shadow.decide_evaluation and read the book's price again; it writes only the cycle's "
                               "tables and serves nobody (only fbi.shadowjobs.eval_cycle imports it)"}
SERVING = ("intel/", "picks/", "familydecisions/", "api/", "parlays/", "customer/", "notify/", "messaging/", "narrative/", "knowledge/",
           "apps/")
"""What decides (``intel``, ``picks``, ``familydecisions``), stakes and combines (``parlays``), publishes or serves users."""


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


def rel(path: Path) -> str:
    return path.relative_to(SRC).as_posix() if SRC in path.parents else path.relative_to(ROOT).as_posix()


def files(*roots: Path) -> list[Path]:
    return sorted(p for r in roots if r.exists() for p in r.rglob("*.py") if "__pycache__" not in p.parts)


def test_nothing_that_decides_publishes_stakes_or_serves_imports_decision_v2() -> None:
    wrong = [rel(p) for p in files(SRC, ROOT / "apps") if rel(p).startswith(SERVING) and imports_package(p)]
    assert not wrong, f"decision-v2 is shadow-only; these modules import it: {wrong}"


def test_only_its_own_command_imports_it() -> None:
    importing = {rel(p) for p in files(SRC, ROOT / "scripts", ROOT / "apps") if not rel(p).startswith("decision/") and imports_package(p)}
    assert importing == set(ALLOWED), f"unlisted importers: {sorted(importing - set(ALLOWED))}; listed but gone: {sorted(set(ALLOWED) - importing)}"


def test_the_package_reaches_the_signals_and_the_families_through_one_module_each_and_never_the_stake() -> None:
    own = {rel(p): imported(p) for p in files(SRC / "decision")}
    signals = {f for f, names in own.items() if any(n.startswith("fbi.market.signals") or n == "fbi.market.signals" for n in names)}
    assert signals == {"decision/market_inputs.py"}, signals
    families = {f for f, names in own.items() if any(n.startswith("fbi.familydecisions") for n in names)}
    assert families == {"decision/families.py"}, families
    assert not [f for f, names in own.items() if any(n.startswith("fbi.intel.stake") or n == "fbi.intel.stake" for n in names)]
    assert not [f for f, names in own.items() if any(n.split(".")[1:2] and n.split(".")[1] in ("api", "notify", "messaging", "parlays", "customer")
                                                      for n in names if n.startswith("fbi."))]


def test_the_package_reaches_the_probability_view_through_one_module_and_never_the_forecast_writer() -> None:
    """The common probability view is read as a measurement (``decision/view.py``): the same function the Match Center's forecast is written from,
    never the writer nor the stored forecast - a forecast is not an input of a decision."""
    own = {rel(p): imported(p) for p in files(SRC / "decision")}
    forecasting = {f for f, names in own.items() if any(n == "fbi.forecasting" or n.startswith("fbi.forecasting.") for n in names)}
    assert forecasting == {"decision/view.py"}, forecasting
    reached = {n for n in own["decision/view.py"] if n.startswith("fbi.forecasting")}
    # ``single_figure`` (AD-B05, IA-083): the single figure of every goals market (``forecast-v2``), pure like ``market_view`` and read
    # through ``market_reader.figures_at``; never the writer nor the stored forecast
    assert all(n.startswith(("fbi.forecasting.market_reader", "fbi.forecasting.market_view", "fbi.forecasting.single_figure"))
               for n in reached), reached
    assert not [f for f, names in own.items() if any("match_forecast" in n for n in names)]


def test_the_package_reaches_the_odds_book_through_one_module_and_never_its_writers() -> None:
    """The book's price (plan INT-A06) is read as of a moment through ``decision/book_price.py`` alone: the book's rule of the answer in force
    and the reader of a RAW body, the capture's normaliser and the consensus - never the modules that write the book, ask the provider or
    extract the quotes (``fbi.odds.book``, ``book_refresh``, ``capture``, ``quote_extract.run_extraction``)."""
    own = {rel(p): imported(p) for p in files(SRC / "decision")}
    roots = ("fbi.odds", "fbi.storage", "fbi.providers")
    reaching = {f for f, names in own.items() if any(n == r or n.startswith(r + ".") for n in names for r in roots)}
    assert reaching == {"decision/book_price.py", "decision/replay.py", "decision/price_rule.py", "decision/shadow.py"}, reaching
    for f in ("decision/replay.py", "decision/price_rule.py", "decision/shadow.py"):
        assert {n for n in own[f] if n.startswith(roots)} == {"fbi.storage.payload_store", "fbi.storage.payload_store.PayloadStore"}, \
            f"{f} only names the RAW store it hands the book's reader"
    reached = {n for n in own["decision/book_price.py"] if n.startswith(roots)}
    allowed = {"fbi.odds.quote_current", "fbi.odds.quote_extract", "fbi.odds.quote_extract.load_body", "fbi.storage.payload_store",
               "fbi.storage.payload_store.PayloadStore", "fbi.providers.api_football.normalize", "fbi.providers.api_football.normalize.iter_odds"}
    current = {n for n in reached if n.startswith("fbi.odds.quote_current")}
    assert reached - current <= allowed, sorted(reached - current - allowed)
    assert not [n for n in reached if n.startswith(("fbi.odds.book", "fbi.odds.capture", "fbi.odds.book_refresh"))]
    assert "fbi.odds.quote_extract.run_extraction" not in reached


def test_the_scan_sees_every_way_of_importing_it(tmp_path: Path) -> None:
    for text in ("import fbi.decision", "import fbi.decision.engine", "from fbi.decision import engine",
                 "from fbi.decision.replay import replay_day", "def f():\n    from fbi.decision import families\n"):
        probe = tmp_path / "probe.py"
        probe.write_text(text, encoding="utf-8")
        assert imports_package(probe), text
    probe = tmp_path / "probe.py"
    probe.write_text("from fbi.intel import decision", encoding="utf-8")
    assert not imports_package(probe)


def test_the_age_rule_is_pure_data_that_reads_only_decision_v1s_thresholds() -> None:
    """The age rule of the price (``decision/price_age.py``, plan 2026 AD-B06) is versioned data and a pure check: it reads decision-v1's
    thresholds (``fbi.intel.decision``) and nothing else - no database, no odds book, no clock - so the contracts can carry it as it is."""
    names = {n for n in imported(SRC / "decision" / "price_age.py") if n.startswith("fbi.")}
    assert names == {"fbi.intel", "fbi.intel.decision"}, names


def test_the_door_of_the_kept_shadow_is_opened_by_the_worker_alone_and_only_in_a_job() -> None:
    """IA-093: ``fbi.shadowjobs.decision_v2`` is the one new importer of decision-v2. Nothing imports it but the worker's scheduler, which
    does so only inside the job and the block that schedules it (never at import time), and it imports decision-v2 only inside its pass."""
    door = "fbi.shadowjobs.decision_v2"
    importers = {rel(p) for p in files(SRC, ROOT / "scripts", ROOT / "apps")
                 if any(n == door or n.startswith(door + ".") for n in imported(p))}
    assert importers == {"apps/worker/scheduler.py"}, importers
    tree = ast.parse((ROOT / "apps" / "worker" / "scheduler.py").read_text(encoding="utf-8"))
    top = [n for n in tree.body if isinstance(n, (ast.Import, ast.ImportFrom))]
    assert not [n for n in top if isinstance(n, ast.ImportFrom) and (n.module or "").startswith(("fbi.decision", door))]
    module = ast.parse((SRC / "shadowjobs" / "decision_v2.py").read_text(encoding="utf-8"))
    assert not [n for n in module.body if isinstance(n, ast.ImportFrom) and (n.module or "").startswith("fbi.decision")], \
        "decision-v2 is imported inside the pass, not when the worker reads the switch"
