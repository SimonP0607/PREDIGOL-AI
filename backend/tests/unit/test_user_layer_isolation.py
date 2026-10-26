"""The user layer and PrediGol Intelligence stay apart in the code (plan UX, A0 and section 4: "importaciones prohibidas").

The user layer consumes the intelligence and never alters it, and the client's data never reaches the operational AI:

* Only the API may import the packages that hold the accounts and what clients keep (``fbi.auth``, ``fbi.userdata``, and the
  ``fbi.customer`` / ``fbi.messaging`` the plan adds in A4 and A5). Models, features, predictions, backtesting, decisions, picks,
  settlement, the AI and the ingestion never do: a package that needs them gets a listed reason here, or a design that does not.
* The console's analyst (``fbi.analyst``, a language model with tools) cannot reach a client's data: nothing it imports, at any
  depth, belongs to those packages, and no file it can load names a table of ``auth``, ``customer`` or the clients' own picks.
* No route a client opens imports a language-model client, the web search or an HTTP client: what a client reads was computed
  and stored before (the runtime proof, every user route called with the network shut, is
  ``tests/integration/test_user_layer_guards.py``).

These are AST checks over ``src/fbi`` (lazy imports inside functions count): a new import fails the test the day it is written.
"""

from __future__ import annotations

import ast
import re
from functools import cache
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "fbi"

USER_LAYER = ("auth", "userdata", "customer", "messaging")
"""Packages of ``fbi`` that hold accounts, sessions, consents, what a client saves and the messages sent to clients."""

MAY_IMPORT_THE_USER_LAYER = {
    "api": "the API serves the accounts and the client's own records (sign-in, profile, my picks); it is the user layer's door",
}
"""Packages allowed to import the user layer, each with its reason. ``fbi.customer`` (A4) and ``fbi.messaging`` (A5) are part of the
user layer itself, so their imports of ``fbi.auth`` and of each other need no reason here."""

CLIENT_TABLES = re.compile(r"\b(?:auth\.[a-z_]+|customer\.[a-z_]+|picks\.user_[a-z_]+)\b")
"""A client's data in SQL: the ``auth`` and ``customer`` schemas and the picks and parlays a client saves."""

USER_ROUTERS = ("system", "auth", "account", "product", "records", "football", "market", "center", "ai_layer",
                "forecast", "match_calendar", "knowledge", "reading", "today", "news", "customer", "messaging",
                "events", "membership", "transparency", "favorites", "support")
"""``fbi.api.routers`` modules mounted on the public and app tiers by ``create_app`` (every other router is ``/admin``)."""

CALLS_OUT = ("fbi.ai.providers", "fbi.analyst.agent", "fbi.analyst.search", "anthropic", "openai", "httpx", "requests",
             "urllib.request")
"""The clients themselves: the language-model providers, the analyst's tool loop, the web search (Exa) and the HTTP libraries.
(A pure helper of a module that also calls out - ``fbi.ai.brief.line_text``, which the AI layer's page uses to word a line -
is not a client; that no route ever calls out is what the runtime guard proves.)"""


def module_name(path: Path) -> str:
    parts = list(path.relative_to(SRC.parent).with_suffix("").parts)
    return ".".join(parts[:-1] if parts[-1] == "__init__" else parts)


@cache
def modules() -> dict[str, Path]:
    return {module_name(p): p for p in SRC.rglob("*.py") if "__pycache__" not in p.parts}


@cache
def raw_imports(name: str) -> frozenset[str]:
    """Every module name an ``import`` or ``from ... import`` in the file names, relative imports resolved."""
    path = modules()[name]
    found: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:
                base = name.split(".") if path.name == "__init__.py" else name.split(".")[:-1]
                base = base[: len(base) - (node.level - 1)]
                head = ".".join(base + ([node.module] if node.module else []))
            else:
                head = node.module or ""
            found.add(head)
            found.update(f"{head}.{alias.name}" for alias in node.names)
    return frozenset(found)


@cache
def fbi_imports(name: str) -> frozenset[str]:
    """The ``fbi`` modules a file imports (a name imported from a package resolves to the deepest module that exists)."""
    known = modules()
    resolved: set[str] = set()
    for target in raw_imports(name):
        parts = target.split(".")
        for size in range(len(parts), 0, -1):
            candidate = ".".join(parts[:size])
            if candidate in known:
                resolved.add(candidate)
                break
    return frozenset(resolved)


def closure(start: list[str]) -> set[str]:
    seen: set[str] = set()
    todo = list(start)
    while todo:
        current = todo.pop()
        if current not in seen:
            seen.add(current)
            todo.extend(fbi_imports(current) - seen)
    return seen


def package_of(name: str) -> str:
    return name.split(".")[1] if name.count(".") >= 1 else ""


def test_only_the_api_imports_the_user_layer() -> None:
    importers: dict[str, set[str]] = {}
    for name in modules():
        source = package_of(name)
        if source in USER_LAYER or not source:
            continue
        for target in fbi_imports(name):
            if package_of(target) in USER_LAYER:
                importers.setdefault(source, set()).add(f"{name} -> {target}")
    unexpected = {pkg: sorted(lines) for pkg, lines in importers.items() if pkg not in MAY_IMPORT_THE_USER_LAYER}
    assert not unexpected, f"these packages import the user layer without a listed reason: {unexpected}"
    assert set(importers) == set(MAY_IMPORT_THE_USER_LAYER), (
        f"listed packages that no longer import the user layer: {sorted(set(MAY_IMPORT_THE_USER_LAYER) - set(importers))}")


def analyst_closure() -> set[str]:
    return closure([name for name in modules() if name == "fbi.analyst" or name.startswith("fbi.analyst.")])


def test_the_console_analyst_cannot_reach_a_clients_data() -> None:
    reach = analyst_closure()
    assert len(reach) > 50, "the analyst's imports were not followed"
    into_user_layer = sorted(name for name in reach if package_of(name) in USER_LAYER)
    assert not into_user_layer, f"the analyst can load the user layer: {into_user_layer}"
    naming = {name: sorted(set(CLIENT_TABLES.findall(modules()[name].read_text(encoding="utf-8"))))
              for name in sorted(reach)}
    naming = {name: tables for name, tables in naming.items() if tables}
    assert not naming, f"files the analyst can load name a client's tables: {naming}"


def user_route_modules() -> list[str]:
    """The user routers and the ``fbi.api.services`` modules they import directly (the code a client's request runs)."""
    found: set[str] = set()
    for router in USER_ROUTERS:
        name = f"fbi.api.routers.{router}"
        assert name in modules(), f"{name} does not exist: update USER_ROUTERS from create_app()"
        found.add(name)
        found.update(t for t in fbi_imports(name) if t.startswith("fbi.api.services."))
    return sorted(found)


def test_no_route_a_client_opens_imports_a_model_client_or_an_http_client() -> None:
    offending = {
        name: sorted(t for t in raw_imports(name) if any(t == c or t.startswith(c + ".") for c in CALLS_OUT))
        for name in user_route_modules()
    }
    offending = {name: hits for name, hits in offending.items() if hits}
    assert not offending, f"code a client's request runs imports a module that calls out: {offending}"


def test_the_user_routers_listed_here_are_the_ones_the_app_mounts_for_clients() -> None:
    """USER_ROUTERS follows create_app(): the routers on the public and app tiers, not the /admin ones."""
    app_source = (SRC / "api" / "app.py").read_text(encoding="utf-8")
    tiers = re.findall(r"for r in \(([^)]*)\):\s*\n\s*app\.include_router\(r, prefix=\"/api/v1\"", app_source)
    mounted = {item.strip().split(".")[0] for group in tiers for item in group.split(",") if item.strip()}
    assert mounted == set(USER_ROUTERS), (sorted(mounted), sorted(USER_ROUTERS))


def test_the_checks_see_a_violation() -> None:
    """The helpers find what they must: the API reaches the user layer, a provider module calls out."""
    assert any(package_of(t) == "auth" for t in fbi_imports("fbi.api.routers.auth"))
    assert any(t == "httpx" for t in raw_imports("fbi.ai.providers"))
    assert CLIENT_TABLES.search("SELECT email FROM auth.users") and CLIENT_TABLES.search("JOIN picks.user_picks up")
    assert not CLIENT_TABLES.search("FROM picks.picks p")


INTELLIGENCE = ("models", "features", "predictions", "backtesting", "domain", "picks", "intel", "ai", "analyst",
                "research", "families", "forecasting", "knowledge", "odds", "parlays", "truth", "validation", "market",
                "quality", "catalog", "competitions", "people", "datasets", "migration")
"""PrediGol Intelligence and the data it is built on: what the messenger (plan UX, A5) must never load."""


def test_the_messenger_reaches_no_model_and_no_decision() -> None:
    """Plan UX, A5: the messenger sends the readers' messages with the API's role, "sin acceso a modelos ni
    decisiones" - nothing it imports, at any depth, is PrediGol Intelligence."""
    reach = closure([name for name in modules() if name.startswith("fbi.messaging")])
    assert "fbi.messaging.runner" in reach and "fbi.ingestion.ledger" in reach, "the messenger's imports were not followed"
    into = sorted(name for name in reach if package_of(name) in INTELLIGENCE)
    assert not into, f"the messenger can load PrediGol Intelligence: {into}"


def test_the_api_never_loads_the_providers_client() -> None:
    """The API queues and previews messages; only the messenger holds the provider's HTTP client."""
    reach = closure(["fbi.api.app"])
    assert "fbi.messaging.outbox" in reach and "fbi.api.routers.messaging" in reach
    assert "fbi.messaging.email" not in reach and "fbi.messaging.runner" not in reach


USER_AI_TABLES = re.compile(r"\bai\.(?:user_narratives|evidence_translations|user_usage)\b")
"""The readers' AI (plan UX, A11): its narratives, its translations of the news and its own spend."""

USER_AI_MODULES = frozenset({"fbi.narrative.job", "fbi.ai.user_budget"})
"""The readers' AI: its job (``fbi.narrative``, outside Intelligence) and its budget, which lives beside Intelligence's in ``fbi.ai``
and is not part of it."""

MAY_NAME_USER_AI = {
    "fbi.narrative.job": "writes the narrative and the translations, reads what it answered already",
    "fbi.ai.user_budget": "the readers' budget: writes ai.user_usage and sums it",
    "fbi.api.services.reading": "shows a reader the narrative of the reading beside it",
    "fbi.api.services.news": "shows a reader an item's headline and English summary",
    "fbi.api.services.ai_layer": "the Admin Console's view of the readers' AI beside Intelligence's",
}
"""The only modules that may name those tables, each with its reason."""


def test_nothing_of_intelligence_reads_the_readers_ai() -> None:
    """Plan UX, A11: models, decisions, picks, settlement and the AI's packet never read ``ai.user_narratives``,
    ``ai.evidence_translations`` or ``ai.user_usage`` - nor load the modules that write them. Intelligence's budget sums
    ``ai.usage`` and ``analytics.ai_runs`` only (``fbi.ai.usage.SPENT_SQL``)."""
    naming = {name: sorted(set(USER_AI_TABLES.findall(path.read_text(encoding="utf-8"))))
              for name, path in modules().items()}
    naming = {name: tables for name, tables in naming.items() if tables}
    unexpected = {name: tables for name, tables in naming.items() if name not in MAY_NAME_USER_AI}
    assert not unexpected, f"these modules name the readers' AI tables without a listed reason: {unexpected}"
    assert set(naming) == set(MAY_NAME_USER_AI), f"listed modules that no longer name them: {set(MAY_NAME_USER_AI) - set(naming)}"
    intelligence = [name for name in modules() if package_of(name) in INTELLIGENCE and name not in USER_AI_MODULES]
    reach = closure(intelligence)
    assert "fbi.ai.packet" in reach and "fbi.intel.decision" in reach, "Intelligence's imports were not followed"
    assert not reach & USER_AI_MODULES, f"PrediGol Intelligence can load the readers' AI: {sorted(reach & USER_AI_MODULES)}"
    from fbi.ai import usage

    assert "ai.usage" in usage.SPENT_SQL and not USER_AI_TABLES.search(usage.SPENT_SQL)


SQL_CLIENT_TABLES = re.compile(r"(?<![\w.])(?:auth\.[a-z_]+|customer\.[a-z_]+|picks\.user_[a-z_]+)\b")
"""A client's table as SQL names it - not a module path that happens to contain one (``fbi.auth.crypto`` in a docstring)."""


def test_the_readers_ai_reads_no_clients_data() -> None:
    """The narrative's call carries the match's facts only: nothing it loads - the user layer's packages included - names a
    client's tables. (It reads the structured reading through the API's own service, which refuses with ``fbi.api.problem``,
    not with the web layer's handlers that know the accounts.)"""
    reach = closure(sorted(USER_AI_MODULES))
    assert "fbi.api.services.reading" in reach and "fbi.ai.usage" in reach, "the readers' AI's imports were not followed"
    into_user_layer = sorted(name for name in reach if package_of(name) in USER_LAYER)
    assert not into_user_layer, f"the readers' AI can load the user layer: {into_user_layer}"
    naming = {name: sorted(set(SQL_CLIENT_TABLES.findall(modules()[name].read_text(encoding="utf-8"))))
              for name in sorted(reach)}
    naming = {name: tables for name, tables in naming.items() if tables}
    assert not naming, f"files the readers' AI loads name a client's tables: {naming}"
