param(
    [string]$TaskName = "DuAn1_WeeklyMarketCalendarUpdate",
    [ValidateSet("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")]
    [string]$RunDay = "Monday",
    [int]$RunHour = 6,
    [int]$RunMinute = 30,
    [int]$StartYearOffset = -1,
    [int]$EndYearOffset = 2
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$scriptPath = Join-Path $projectRoot "scripts\run_weekly_market_calendar_update.ps1"

$safeHour = [Math]::Max(0, [Math]::Min(23, $RunHour))
$safeMinute = [Math]::Max(0, [Math]::Min(59, $RunMinute))
$triggerTime = [datetime]::Today.AddHours($safeHour).AddMinutes($safeMinute)

$taskArgs = ('-NoProfile -ExecutionPolicy Bypass -File "{0}" -StartYearOffset {1} -EndYearOffset {2}' -f $scriptPath, $StartYearOffset, $EndYearOffset).Trim()

Write-Host "Creating/updating weekly task: $TaskName"
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $taskArgs
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $RunDay -At $triggerTime
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null

$t = Get-ScheduledTask -TaskName $TaskName
$ti = Get-ScheduledTaskInfo -TaskName $TaskName

Write-Host "Task created/updated:"
Write-Host "  TaskName: $($t.TaskName)"
Write-Host "  State: $($t.State)"
Write-Host "  NextRunTime: $($ti.NextRunTime)"
Write-Host "  LastRunTime: $($ti.LastRunTime)"
Write-Host "  Day: $RunDay"
Write-Host ("  Time: {0:D2}:{1:D2}" -f $safeHour, $safeMinute)
Write-Host "  Action: powershell.exe $taskArgs"
Write-Host ""
Write-Host "Done. Weekly VN market calendar update is scheduled."
