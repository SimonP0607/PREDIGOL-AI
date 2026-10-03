# Register a Windows scheduled task that runs start-fbi.ps1 when you log on,
# so the worker comes back by itself after a reboot. Run it YOURSELF, once:
#
#   powershell -ExecutionPolicy Bypass -File install-autostart.ps1
#
# Remove it with:  Unregister-ScheduledTask -TaskName "Football Intelligence" -Confirm:$false
$ErrorActionPreference = "Stop"
$script = "\\wsl.localhost\Ubuntu\home\$env:USERNAME\projects\football-intelligence-v2\scripts\windows\start-fbi.ps1"
$local = Join-Path $env:LOCALAPPDATA "football-intelligence\start-fbi.ps1"
New-Item -ItemType Directory -Force (Split-Path $local) | Out-Null
Copy-Item $script $local -Force

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$local`""
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$trigger.Delay = "PT1M"
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 15)
Register-ScheduledTask -TaskName "Football Intelligence" -Action $action -Trigger $trigger `
    -Settings $settings -Description "Starts Docker Desktop and the Football Intelligence stack at logon" -Force
Write-Host "Registered. It runs one minute after you log on."
