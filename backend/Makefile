# Two ways to run the stack locally - use ONE (see docker-compose.yml):
#   host mode     make dev-up / make dev-down / make status
#   compose mode  make up / make down
.PHONY: up down logs image dev-up dev-down status migrate schema revision test format lint typecheck capture report fresh check

# The commit the image is built from, recorded in every row the code writes.
FBI_CODE_VERSION ?= $(shell git rev-parse --short=12 HEAD 2>/dev/null || echo unknown)$(shell git diff --quiet HEAD 2>/dev/null || echo -dirty)
export FBI_CODE_VERSION

image:     ; docker compose --profile stack build
up: image
	@if pgrep -f "[a]pps.worker" >/dev/null; then echo "host mode is running (scripts/dev-down first): one mode at a time"; exit 1; fi
	docker compose up -d postgres
	docker compose --profile stack run --rm --no-deps api python -m scripts.schema_status
	docker compose --profile stack up -d
down:      ; docker compose --profile stack stop api worker
logs:      ; docker compose --profile stack logs -f --tail=100

dev-up:    ; scripts/dev-up
dev-down:  ; scripts/dev-down
status:    ; scripts/dev-status

schema:    ; python -m scripts.schema_status
migrate:   ; alembic upgrade head
revision:  ; alembic revision -m "$(m)"
test:      ; pytest -q
format:    ; ruff format .
lint:      ; ruff check .
typecheck: ; mypy
check:     ; ruff check . && mypy && pytest -q
capture:   ; python -m scripts.capture_odds run --window auto
report:    ; python -m scripts.capture_odds report

# DELETES the database volume. Only for a throwaway database.
fresh:
	@test "$(CONFIRM)" = "wipe" || { echo "make fresh deletes the database volume. If that is what you want: make fresh CONFIRM=wipe"; exit 1; }
	docker compose down -v && docker compose up -d postgres && sleep 8 && alembic upgrade head
