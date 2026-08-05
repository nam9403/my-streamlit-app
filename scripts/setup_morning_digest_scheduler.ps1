param(
    [string]$TaskName = "DuAn1_MorningDigest",
    [int]$RunHour = 7,
    [int]$RunMinute = 30,
    [string]$UserId = "default_user"
)

$ErrorActionPreference = "Stop"
$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$python = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

$script = Join-Path $projectRoot "scripts\send_morning_digest.py"
$taskArgs = "-NoProfile -ExecutionPolicy Bypass -Command `"Set-Location '$projectRoot'; & '$python' '$script' --user-id $UserId`""

$triggerTime = [datetime]::Today.AddHours([Math]::Max(0, [Math]::Min(23, $RunHour))).AddMinutes([Math]::Max(0, [Math]::Min(59, $RunMinute)))
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $taskArgs
$trigger = New-ScheduledTaskTrigger -Daily -At $triggerTime
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null

Write-Host "Task created: $TaskName daily at $('{0:D2}:{1:D2}' -f $RunHour, $RunMinute) user=$UserId"
