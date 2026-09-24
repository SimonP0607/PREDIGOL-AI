"""Is the database at the head migration? Exit 0 if so, 3 if behind, 2 if unreachable.

    python -m scripts.schema_status

Used by scripts/dev-up and `make up` before anything starts: a worker on a
schema behind the code fails in ways that look like data problems. Migrating
is never done here - back up first (pg_dump), then `alembic upgrade head`.
"""

from __future__ import annotations

import sys
from pathlib import Path

import psycopg
from alembic.config import Config
from alembic.script import ScriptDirectory

from fbi.core.config import settings

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    heads = set(ScriptDirectory.from_config(cfg).get_heads())
    try:
        with psycopg.connect(settings.database.psycopg_url, connect_timeout=5) as conn:
            exists = conn.execute("SELECT to_regclass('public.alembic_version') IS NOT NULL").fetchone()
            current = ({r[0] for r in conn.execute("SELECT version_num FROM alembic_version")}
                       if exists and exists[0] else set())
    except psycopg.OperationalError as exc:
        print(f"schema: database not reachable ({type(exc).__name__})")
        return 2
    head = ", ".join(sorted(heads))
    if current == heads:
        print(f"schema: at head ({head})")
        return 0
    print(f"schema: at {', '.join(sorted(current)) or 'nothing'}, head is {head}. "
          "Back up (pg_dump), then run: alembic upgrade head")
    return 3


if __name__ == "__main__":
    sys.exit(main())
