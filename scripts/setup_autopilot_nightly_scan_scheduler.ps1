param(
    [string]$TaskName = "DuAn1_AutopilotNightlyScan",
    [int]$RunHour = 22,
    [int]$RunMinute = 30,
    [int]$BatchSize = 40,
    [int]$Workers = 3
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$python = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

$scanScript = Join-Path $projectRoot "scripts\run_autopilot_nightly_scan.py"
$taskArgs = "-NoProfile -ExecutionPolicy Bypass -Command `"Set-Location '$projectRoot'; & '$python' '$scanScript' --batch-size $BatchSize --workers $Workers`""

$triggerTime = [datetime]::Today.AddHours([Math]::Max(0, [Math]::Min(23, $RunHour))).AddMinutes([Math]::Max(0, [Math]::Min(59, $RunMinute)))
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $taskArgs
$trigger = New-ScheduledTaskTrigger -Daily -At $triggerTime
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -ExecutionTimeLimit (New-TimeSpan -Hours 6)
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null

Write-Host "Task created: $TaskName daily at $('{0:D2}:{1:D2}' -f $RunHour, $RunMinute)"
Write-Host "Command: python scripts/run_autopilot_nightly_scan.py --batch-size $BatchSize --workers $Workers"
