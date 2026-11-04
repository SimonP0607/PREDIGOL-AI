"""Where the two words of phase 5 and the role of the analyst must be written, so that none of them is forgotten when the code is deployed (plan IA, phase 5).

A word that the code reads and the templates do not name is a word the owner cannot find; a word the precheck does not know is one it would flag as unknown; a role
that the initial script, ``roles.sql`` and ``grants.sql`` do not all carry is a role a new cluster and an old one have differently.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from fbi.ai import config
from fbi.ai.agents import analyst

BACKEND = Path(__file__).resolve().parents[2]
WORDS = ("FBI_AI_PM_REVIEWER", "FBI_AI_LEARNING_ANALYST")
PRECHECK = BACKEND / "deploy" / "release" / "templates" / "server" / "step_precheck.sh"
DB = BACKEND / "deploy" / "vps" / "db"


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


@pytest.mark.parametrize("word", WORDS)
def test_each_word_is_read_by_the_configuration_and_written_in_both_templates(word: str) -> None:
    assert f'"{word}"' in text(BACKEND / "src" / "fbi" / "ai" / "config.py")
    for template in (BACKEND / ".env.example", BACKEND / "deploy" / "vps" / "app.env.example"):
        lines = [x for x in text(template).splitlines() if x.lstrip("# ").startswith(f"{word}=")]
        assert lines == [f"# {word}=0"], f"{template.name}: the word is there, commented out, and OFF"


@pytest.mark.parametrize("word", WORDS)
def test_the_precheck_knows_the_word_is_safe_to_find_in_the_servers_file(word: str) -> None:
    source = text(PRECHECK)
    pattern = re.search(r"function safe\(n\) \{ return n ~ /(.+?)/", source)
    assert pattern is not None
    assert re.search(pattern.group(1), word), f"safe() would flag {word}"
    assert not re.search(pattern.group(1), "FBI_AI_NOT_A_WORD_OF_THE_LIST"), "and the list still refuses what it does not know"


def test_the_analyst_role_is_named_the_same_everywhere() -> None:
    assert analyst.ROLE == "predigol_learning"
    for path in (DB / "roles.sql", DB / "initdb" / "10-predigol-roles.sh", DB / "grants.sql", PRECHECK):
        assert analyst.ROLE in text(path), path.name
    for path in (DB / "roles.sql", DB / "initdb" / "10-predigol-roles.sh"):
        body = text(path)
        assert f"CREATE ROLE {analyst.ROLE} NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS" in body
        assert f"GRANT {analyst.ROLE} TO predigol_worker WITH INHERIT FALSE, SET TRUE" in body, "the worker may ask for it and holds none of it until it does"


def test_the_grants_of_the_role_name_the_hypotheses_and_never_a_promotion() -> None:
    block = text(DB / "grants.sql").split("DO $learning$", 1)[1].split("$learning$;", 1)[0]
    granted = re.findall(r"GRANT\s+(.+?)\s+ON\s+(.+?)\s+TO\s+predigol_learning", block.replace("format('", "").replace("%s", "SEQ"))
    assert ("SELECT, INSERT", "analytics.research_hypotheses") in granted
    for forbidden in ("promotions", "UPDATE", "DELETE", "TRUNCATE", "ALL PRIVILEGES", "ALL TABLES"):
        assert forbidden not in re.sub(r"--.*", "", block), forbidden


def test_the_switches_are_off_unless_the_server_says_so() -> None:
    assert config.AiSettings().pm_reviewer is False and config.AiSettings().learning_analyst is False
