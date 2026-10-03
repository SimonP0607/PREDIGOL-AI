# Start the whole private platform on this Windows machine:
# Docker Desktop (PostgreSQL), then API, worker and web inside WSL.
#
#   powershell -ExecutionPolicy Bypass -File start-fbi.ps1
#
# Safe to run any number of times: whatever already runs is left alone.
$ErrorActionPreference = "Stop"

$docker = Join-Path $env:LOCALAPPDATA "Programs\DockerDesktop\Docker Desktop.exe"
if (-not (Test-Path $docker)) { $docker = "C:\Program Files\Docker\Docker\Docker Desktop.exe" }
if (-not (Get-Process -Name "Docker Desktop" -ErrorAction SilentlyContinue)) {
    if (Test-Path $docker) { Start-Process $docker } else { Write-Warning "Docker Desktop not found" }
}

# dev-up waits up to 3 minutes for the database, then starts api, worker and web.
wsl -e bash -lc "~/projects/football-intelligence-v2/scripts/dev-up < /dev/null"
Write-Host "Open http://localhost:5173"
