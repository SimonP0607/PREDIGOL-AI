# Cloud dev environment for the Football Intelligence Platform V2.
# The cloud cluster listens on 5433 so the project's own defaults apply unchanged.
export FBI_DATABASE_URL="postgresql+psycopg://fbi:fbi_local_dev@127.0.0.1:5433/fbi"
export FBI_TEST_ADMIN_URL="postgresql://postgres:fbi_local_dev@127.0.0.1:5433/postgres"
export FBI_TEST_DB="fbi_test"
export PATH="/home/claude/fiv2/.venv/bin:$PATH"
