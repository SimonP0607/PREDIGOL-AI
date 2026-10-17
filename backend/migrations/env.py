from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# The URL always comes from the environment, never from alembic.ini.
# That way a credential can never be committed to the repository.
_url = os.environ.get("FBI_DATABASE_URL")
if not _url:
    from dotenv import load_dotenv

    load_dotenv()
    _url = os.environ.get("FBI_DATABASE_URL")
if not _url:
    raise RuntimeError("FBI_DATABASE_URL is not set")
config.set_main_option("sqlalchemy.url", _url)

target_metadata = None


def run_migrations_offline() -> None:
    context.configure(url=_url, target_metadata=target_metadata, literal_binds=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
