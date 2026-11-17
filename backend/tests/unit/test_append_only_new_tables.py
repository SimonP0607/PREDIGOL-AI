"""AD-A07 (IA-059): every table a migration of the definitive architecture (revision 0138 onwards) creates in ``ai``, ``intel`` or ``news``
is append-only - a ``BEFORE UPDATE OR DELETE ... FOR EACH ROW EXECUTE FUNCTION <schema>.refuse_change()`` trigger in the same migration, the
convention of every audit table since revision 0072 - unless it is listed below with the reason it may be rewritten.

The migrations are rendered to SQL without a database (alembic's offline mode, as CI-015 does for squawk), so a trigger written in a loop
over a tuple of tables counts like one written by hand. A correction of data is a new row, never an UPDATE: a table of the plan that needs to
be rewritten must say so here, in the open, and be decided."""

from __future__ import annotations

import re
from io import StringIO
from pathlib import Path

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory

BACKEND = Path(__file__).resolve().parents[2]
FIRST = "0138"
"""The first revision of the definitive architecture's plan (IA-056)."""
SCHEMAS = ("ai", "intel", "news")
EXEMPT: dict[str, str] = {}
"""``schema.table`` -> why it may be rewritten. Empty: no table of the plan is."""

CREATE = re.compile(r"CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?(ai|intel|news)\.([a-z_][a-z0-9_]*)", re.IGNORECASE)
TRIGGER = re.compile(r"CREATE\s+TRIGGER\s+\w+\s+BEFORE\s+UPDATE\s+OR\s+DELETE\s+ON\s+(ai|intel|news)\.([a-z_][a-z0-9_]*)\s+"
                     r"FOR\s+EACH\s+ROW\s+EXECUTE\s+FUNCTION\s+\w+\.refuse_change\(\)", re.IGNORECASE)


def _config() -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND / "migrations"))
    return cfg


def rendered(cfg: Config, down: str, up: str) -> str:
    buffer = StringIO()
    cfg.output_buffer = buffer
    command.upgrade(cfg, f"{down}:{up}", sql=True)
    return buffer.getvalue()


def unguarded(sql: str) -> list[str]:
    created = {f"{s.lower()}.{t.lower()}" for s, t in CREATE.findall(sql)}
    guarded = {f"{s.lower()}.{t.lower()}" for s, t in TRIGGER.findall(sql)}
    return sorted(created - guarded - set(EXEMPT))


def plan_revisions(cfg: Config) -> list[tuple[str, str]]:
    script = ScriptDirectory.from_config(cfg)
    out = []
    for rev in script.walk_revisions():
        if isinstance(rev.down_revision, str) and rev.revision >= FIRST:
            out.append((rev.down_revision, rev.revision))
    return sorted(out, key=lambda pair: pair[1])


def test_every_new_table_of_the_plan_is_append_only(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FBI_DATABASE_URL", "postgresql+psycopg://lint@localhost/lint")  # offline mode never connects
    cfg = _config()
    revisions = plan_revisions(cfg)
    assert revisions and revisions[0][1] == FIRST, "the plan's first migration is found, or the test proves nothing"
    offenders = {up: found for down, up in revisions if (found := unguarded(rendered(cfg, down, up)))}
    assert offenders == {}, f"tables without an append-only trigger (add one, or list them in EXEMPT with why): {offenders}"


def test_the_detector_sees_triggers_written_in_a_loop_and_misses_nothing(monkeypatch: pytest.MonkeyPatch) -> None:
    """Calibration: revision 0135 writes its four triggers in a loop - all four are seen; a table without one is caught."""
    monkeypatch.setenv("FBI_DATABASE_URL", "postgresql+psycopg://lint@localhost/lint")
    sql = rendered(_config(), "0134", "0135")
    assert len(CREATE.findall(sql)) == 4 and unguarded(sql) == []
    assert unguarded("CREATE TABLE news.items (id int);") == ["news.items"]
    assert unguarded("CREATE TABLE news.items (id int); CREATE TRIGGER items_append_only BEFORE UPDATE OR DELETE ON news.items "
                     "FOR EACH ROW EXECUTE FUNCTION news.refuse_change()") == []
    assert unguarded("CREATE TABLE intel.x (id int); CREATE TRIGGER x_t BEFORE UPDATE ON intel.x "
                     "FOR EACH ROW EXECUTE FUNCTION intel.refuse_change()") == ["intel.x"], "DELETE must be refused too"
    assert all(reason.strip() for reason in EXEMPT.values())
    assert set(SCHEMAS) == {"ai", "intel", "news"}
