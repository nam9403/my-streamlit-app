param(
    [string]$TaskName = "DuAn1_NightlyRuntimeCheck",
    [ValidateSet("dev", "preprod", "prod")]
    [string]$Env = "preprod",
    [int]$RunHour = 23,
    [int]$RunMinute = 30,
    [switch]$SkipAudit,
    [switch]$SkipHealth
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$python = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

$scriptPath = Join-Path $projectRoot "scripts\run_nightly_runtime_check.ps1"
$auditFlag = if ($SkipAudit) { "-SkipAudit" } else { "" }
$healthFlag = if ($SkipHealth) { "-SkipHealth" } else { "" }
$taskCmd = ('powershell.exe -NoProfile -ExecutionPolicy Bypass -File "{0}" -Env {1} {2} {3}' -f $scriptPath, $Env, $auditFlag, $healthFlag).Trim()
$taskArgs = ('-NoProfile -ExecutionPolicy Bypass -File "{0}" -Env {1} {2} {3}' -f $scriptPath, $Env, $auditFlag, $healthFlag).Trim()

$startTime = "{0:D2}:{1:D2}" -f [Math]::Max(0, [Math]::Min(23, $RunHour)), [Math]::Max(0, [Math]::Min(59, $RunMinute))

Write-Host "Creating/updating task: $TaskName"
$triggerTime = [datetime]::Today.AddHours([Math]::Max(0, [Math]::Min(23, $RunHour))).AddMinutes([Math]::Max(0, [Math]::Min(59, $RunMinute)))
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $taskArgs
$trigger = New-ScheduledTaskTrigger -Daily -At $triggerTime
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null

Write-Host "Task created:"
$t = Get-ScheduledTask -TaskName $TaskName
$ti = Get-ScheduledTaskInfo -TaskName $TaskName
Write-Host "  TaskName: $($t.TaskName)"
Write-Host "  State: $($t.State)"
Write-Host "  NextRunTime: $($ti.NextRunTime)"
Write-Host "  LastRunTime: $($ti.LastRunTime)"
Write-Host "  Action: powershell.exe $taskArgs"
Write-Host ""
Write-Host "Done. Nightly runtime check runs daily at $startTime with env=$Env."
