.PHONY: up down logs migrate revision test lint typecheck capture report fresh
up:        ; docker compose up -d postgres api worker
down:      ; docker compose down
logs:      ; docker compose logs -f --tail=100
migrate:   ; alembic upgrade head
revision:  ; alembic revision -m "$(m)"
test:      ; pytest -q
lint:      ; ruff check . && ruff format --check .
typecheck: ; mypy
capture:   ; python -m scripts.capture_odds run --window auto
report:    ; python -m scripts.capture_odds report
fresh:     ; docker compose down -v && docker compose up -d postgres && sleep 6 && alembic upgrade head
