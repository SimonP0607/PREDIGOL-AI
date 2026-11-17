"""IA-138 (AD-K06): ONE read layer over the four memories (``fbi.memoryread``). Every statement that reads a memory lives there, byte for byte
what its reader ran before (parity: the sha256 of each is pinned as it was in ``chain5-FINAL``); no other module of ``src/fbi`` reads a store,
except the writers continuing their own lineage and ks-v1; nothing reads a store the owner closed; the layer imports nothing of ours."""

from __future__ import annotations

import ast
import hashlib
from pathlib import Path

from fbi import memoryread
from fbi.ai import daily_review, patterns
from fbi.api.services import ai_layer, families, knowledge, match_memory

SRC = Path(__file__).resolve().parents[2] / "src" / "fbi"

BEFORE: dict[str, str] = {
    "AI_DAY_PATTERNS": "4ec11fb6e770ebdebc009dc8a71161ca550255f6aa91c810ff58caa588630bcc",
    "AI_WINDOW_EVENTS": "6579fcb9f4a7d783a97f63979664ae03d1a565420a917822f243001d3f313876",
    "AI_CONSOLE_EVENTS": "2fd140b5ed508a0c7bd068c1c4867ef05e47a6e5108947fd40aa386bc85c1a4c",
    "AI_CONSOLE_FINDINGS": "dad4517b42cb3f3f84452333b21098609ded4672fbd29c8d2cf4f39b811bc92d",
    "AI_EVENTS_OF_BASE_FIXTURE": "77414ce8571a6f3123ced46ddec7179e069ba8263d43132644075e8169867547",
    "ENTITY_CONSOLE_LATEST": "c22038b995a93cf1774f21742cdc48d7275b057416b5e653ef1445504f2f5268",
    "ENTITY_CONSOLE_HISTORY": "312605686419138ff404a4a3ef7dc35cc5dbb4519156eacb137340428df1b7e6",
    "ENTITY_REPORT_TEAMS": "c9449840d5dee4685e13aa36a801eb0ca1b7d795cd78cf3b0b241906ac4ee3ba",
    "ENTITY_REPORT_PLAYERS": "1f2b5d022d159796a8afb857ae42f01937775497ca44c8d68c11f460846b24d6",
    "FAMILY_CONSOLE_NEWEST": "20454cbab4f8d4a084e80a47b68a82758f1215474a4e414eb1fe35d7ecbcc536",
    "KNOWLEDGE_ROW": "693fd176ea93a91fa8a339d765ebe87250da7fab84459f68882c0f2a48fd2e87",
    "KNOWLEDGE_CHAIN": "278b10b1532f385176862d400113c142778199dc7f3c4b645f9a896c23122a90",
}
"""sha256 of each statement as its reader ran it in ``chain5-FINAL`` (before IA-138). The match memory's statement as a whole is checked below."""
MATCH_MEMORY_BEFORE = "SELECT count(*) FROM ai.memory_events e WHERE e.fixture_id = b.id"


def modules() -> dict[str, Path]:
    out = {}
    for p in sorted(SRC.rglob("*.py")):
        if "__pycache__" in p.parts:
            continue
        parts = p.relative_to(SRC.parent).with_suffix("").parts
        out[".".join(parts[:-1] if parts[-1] == "__init__" else parts)] = p
    return out


def test_every_statement_reads_what_it_read_before() -> None:
    assert {s.name: hashlib.sha256(s.sql.encode()).hexdigest() for s in memoryread.STATEMENTS} == BEFORE


def test_every_statement_reads_the_store_it_says_and_only_it() -> None:
    for s in memoryread.STATEMENTS:
        assert memoryread.stores_read(s.sql) == {s.store}, s.name
        assert s.store in memoryread.STORES and s.reader in modules(), s.name


def test_no_module_reads_a_memory_but_the_layer_and_the_listed_ones() -> None:
    reading = {name for name, path in modules().items() if memoryread.READS.search(path.read_text(encoding="utf-8"))}
    assert reading == set(memoryread.OWN_READERS), (
        f"modules that read a memory outside the layer: {sorted(reading - set(memoryread.OWN_READERS))}; "
        f"listed readers that no longer read one: {sorted(set(memoryread.OWN_READERS) - reading)}")


def test_the_guard_sees_a_statement_that_reads_a_store() -> None:
    assert memoryread.stores_read("SELECT 1 FROM intel.entity_memory_latest x JOIN ai.memory_events e ON true") == {
        "intel.entity_memory", "ai.memory_events"}
    assert memoryread.stores_read("the docstring says from intel.entity_memory in prose") == frozenset()


def test_the_readers_run_the_layers_statements() -> None:
    assert daily_review.PATTERNS_SQL is memoryread.AI_DAY_PATTERNS
    assert patterns.MEMORY_SQL is memoryread.AI_WINDOW_EVENTS
    assert ai_layer.MEMORY_SQL is memoryread.AI_CONSOLE_EVENTS and ai_layer.FINDINGS_SQL is memoryread.AI_CONSOLE_FINDINGS
    assert families.MEMORY_SQL is memoryread.FAMILY_CONSOLE_NEWEST
    assert knowledge.ROW_SQL is memoryread.KNOWLEDGE_ROW and knowledge.CHAIN_SQL is memoryread.KNOWLEDGE_CHAIN
    assert f"({MATCH_MEMORY_BEFORE}) AS events" in match_memory.SQL and "__MEMORY_EVENTS__" not in match_memory.SQL
    for reader, names in (("fbi.api.services.intelligence", ("ENTITY_CONSOLE_LATEST", "ENTITY_CONSOLE_HISTORY")),
                          ("fbi.intel.report", ("ENTITY_REPORT_TEAMS", "ENTITY_REPORT_PLAYERS"))):
        text = modules()[reader].read_text(encoding="utf-8")
        assert all(f"memoryread.{n}" in text for n in names), reader


def test_each_statement_is_run_by_the_reader_it_names_and_by_no_other() -> None:
    """The page of a finished match is the only one that runs its two statements: no reader before a kick-off reaches Match Knowledge through
    the layer (``tests/unit/test_knowledge_isolation.py`` holds the rest)."""
    users: dict[str, set[str]] = {s.name: set() for s in memoryread.STATEMENTS}
    for name, path in modules().items():
        if name == "fbi.memoryread":
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name) and node.value.id == "memoryread" and node.attr in users:
                users[node.attr].add(name)
    assert users == {s.name: {s.reader} for s in memoryread.STATEMENTS}


def test_nothing_reads_a_closed_store_and_none_is_closed_yet() -> None:
    assert all(s.closed_on is None for s in memoryread.STORES.values()), "a closure is the owner's signed retirement (AD-K07)"
    closed = {t for t, s in memoryread.STORES.items() if s.closed_on is not None}
    assert not [s.name for s in memoryread.STATEMENTS if s.store in closed]


def test_the_layer_imports_nothing_of_ours_and_writes_nothing() -> None:
    path = SRC / "memoryread" / "__init__.py"
    tree = ast.parse(path.read_text(encoding="utf-8"))
    imported = [n.module for n in ast.walk(tree) if isinstance(n, ast.ImportFrom) and n.module] + [
        a.name for n in ast.walk(tree) if isinstance(n, ast.Import) for a in n.names]
    assert not [m for m in imported if m.startswith("fbi")]
    assert not any(w in s.sql.upper() for s in memoryread.STATEMENTS for w in ("INSERT ", "UPDATE ", "DELETE ", "TRUNCATE "))


def test_the_inventory_names_the_four_stores_their_writers_and_readers() -> None:
    inv = {i["store"]: i for i in memoryread.inventory()}
    assert set(inv) == {"ai.memory_events", "intel.entity_memory", "intel.family_memory", "intel.match_knowledge"}
    assert inv["intel.entity_memory"]["readers"] == ["fbi.api.services.intelligence", "fbi.intel.report"]
    assert all(i["closed_on"] is None and i["statements"] for i in inv.values())
    for s in memoryread.STORES.values():
        assert s.writer in modules(), s.writer
