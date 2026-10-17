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

## Signing in

The app asks for an account (FastAPI + PostgreSQL sessions; no external provider). The owner's
SUPER_ADMIN credentials are in `~/.fbi/predigol-admin.txt` (mode 0600, never in Git). Accounts,
roles, languages, time zones, the QA accounts used by the E2E suite and the checklist before a
public deployment: [rebuild/PREDIGOL_ACCOUNTS_AND_EXPERIENCES.md](rebuild/PREDIGOL_ACCOUNTS_AND_EXPERIENCES.md).

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

## After the machine was off (the order used on 6 Oct 2026)

1. Docker Desktop and `fbi-postgres` first; `scripts/dev-up api web` (no worker yet). After an unclean power-off
   PostgreSQL replays its WAL by itself (`docker logs fbi-postgres`: "automatic recovery ... redo done"); run
   `ANALYZE` afterwards, because the crash recovery resets the statistics autovacuum reads.
2. Measure the gap read-only: the last finished run in `raw.ingestion_runs`, the last payload, `raw.worker_heartbeats`,
   Windows events 1074 / 41 / 6008. The worker log may end in NUL bytes (it is not synced): read it with `grep -a`.
3. Back up (`backup_label.sh PRE_...`): dump, RAW archive, checksums, tags.
4. `scripts/dev-up worker`: it closes the runs left open and its syncs, anchored on the ledger, run at once.
   Started from a tool that runs inside the Claude desktop app, the stack lives in that app's process tree and
   dies when the app updates (6 Oct 2026, 02:36 UTC). Start it outside: the logon task, or from PowerShell
   `Invoke-CimMethod -ClassName Win32_Process -MethodName Create -Arguments @{CommandLine =
   'C:\Windows\System32\wsl.exe -e bash <path>/sh_up.sh'}` (the process then hangs off WmiPrvSE.exe).
5. Audits: lineage, RAW integrity, the truth audit, the register. Windows that passed while the machine was off stay
   lost and are listed (`docs/owner/OFFLINE_RECOVERY_2026-10-06.md`), never back-filled.

The heavy jobs (fixture and results syncs, history, reference feeds, context, final pre-match prices) run on an event
loop of their own in a thread, so their database work cannot stall the in-play capture (`OWN_LOOP_JOBS` in
`apps/worker/scheduler.py`).

## Docker Desktop will not start

"starting services: ... sailor-ingest.sock ... The file cannot be accessed" after an unclean
shutdown: quit Docker Desktop, move the stale socket files out of
`%LOCALAPPDATA%\Docker\run` and `%LOCALAPPDATA%\docker-secrets-engine` (from WSL `mv` works where
Windows refuses), start it again. Never use "Reset to factory defaults": it deletes the database volume.

## `docker` inside WSL says "could not be found in this WSL 2 distro"

Docker Desktop's WSL integration is off for this distro (it can switch itself off after a
restart). The app keeps working - PostgreSQL is reached on localhost:5432 - and
`scripts.backup` falls back to the Windows client (`docker.exe`), dumping inside the container
and copying the file out with `docker cp`. `scripts/dev-up --migrate` refuses to migrate in this
state (its backup step fails, so nothing is changed) and `scripts/dev-status` prints the notice
instead of the containers. To fix: Docker Desktop -> Settings -> Resources -> WSL integration ->
enable the Ubuntu distro -> Apply & restart.
