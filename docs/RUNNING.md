# Running the private platform

One machine (Windows + WSL Ubuntu), one URL: **http://localhost:5173**.

| Piece | Where | Started by |
|---|---|---|
| PostgreSQL 16 | Docker Desktop, container `fbi-postgres` | Docker Desktop |
| API (FastAPI, :8010) | WSL, supervised | `scripts/dev-up` |
| Worker (captures, syncs, pipeline) | WSL, supervised | `scripts/dev-up` |
| Web (Vite, :5173, proxies `/api/v1` and `/health` to the API) | WSL | `scripts/dev-up` |

```bash
scripts/dev-up              # start whatever is not running (waits for Docker up to 3 min)
scripts/dev-up --migrate    # back up, then apply pending migrations
scripts/dev-status          # what runs, and /health
scripts/dev-down [api|worker|web]
```

## What survives what

* **A crash of the API or the worker**: `scripts/run-supervised` restarts it after 5 s
  (backing off to 5 min if it keeps dying). `dev-down` stops it for good.
* **A second worker**: refused by a database lock (exit 75); the supervisor does not retry it.
* **The machine was off**: runs that were open are closed as `interrupted` when the worker
  starts again; results missed while it was off are fetched by id after the next results sync.
  Pre-match capture windows that passed while it was off are gone - they are reported, not
  back-filled with later prices.
* **A reboot**: nothing restarts by itself until you register the logon task once:
  `powershell -ExecutionPolicy Bypass -File scripts\windows\install-autostart.ps1`
  (from `\\wsl.localhost\Ubuntu\home\<you>\projects\football-intelligence-v2`). It runs
  `scripts/windows/start-fbi.ps1` one minute after logon. Docker Desktop must be allowed to start.

## Docker Desktop will not start

"starting services: ... sailor-ingest.sock ... The file cannot be accessed" after an unclean
shutdown: quit Docker Desktop, move the stale socket files out of
`%LOCALAPPDATA%\Docker\run` and `%LOCALAPPDATA%\docker-secrets-engine` (from WSL `mv` works where
Windows refuses), start it again. Never use "Reset to factory defaults": it deletes the database volume.
