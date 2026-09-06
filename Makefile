.PHONY: up down logs migrate revision test format lint typecheck capture report fresh check
up:        ; docker compose up -d postgres api worker
down:      ; docker compose down
logs:      ; docker compose logs -f --tail=100
migrate:   ; alembic upgrade head
revision:  ; alembic revision -m "$(m)"
test:      ; pytest -q
format:    ; ruff format .
lint:      ; ruff check .
typecheck: ; mypy
capture:   ; python -m scripts.capture_odds run --window auto
report:    ; python -m scripts.capture_odds report
fresh:     ; docker compose down -v && docker compose up -d postgres && sleep 8 && alembic upgrade head
check:     ; ruff check . && mypy && pytest -q
