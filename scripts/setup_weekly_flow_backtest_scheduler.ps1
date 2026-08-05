param(
    [string]$TaskName = "DuAn1_WeeklyFlowBacktest",
    [int]$DayOfWeek = 0,  # 0=Sunday ... 6=Saturday
    [int]$RunHour = 22,
    [int]$RunMinute = 0,
    [string]$Symbols = "FPT,HPG,VNM,VCB,MWG,VRE,VHM,VIC,VPB,TCB",
    [int]$Sessions = 500,
    [int]$Stride = 5,
    [string]$Horizons = "1,5,20"
)

# Tạo Windows Task Scheduler entry chạy weekly backtest cho FlowSignal —
# closed-loop self-tuning: artifact recommendation_latest.json sinh ra ở đây
# sẽ được background_jobs._flow_min_intensity_env() đọc ở cycle kế tiếp.

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$scriptPath = Join-Path $projectRoot "scripts\run_weekly_flow_backtest.ps1"
if (-not (Test-Path $scriptPath)) {
    Write-Error "run_weekly_flow_backtest.ps1 không tồn tại tại $scriptPath"
    exit 1
}

# DayOfWeek mapping cho New-ScheduledTaskTrigger -Weekly
$daysMap = @{
    0 = "Sunday"
    1 = "Monday"
    2 = "Tuesday"
    3 = "Wednesday"
    4 = "Thursday"
    5 = "Friday"
    6 = "Saturday"
}
$dayName = $daysMap[$DayOfWeek]
if (-not $dayName) {
    Write-Error "DayOfWeek phải nằm trong 0-6 (0=Sunday)"
    exit 1
}

$taskArgs = (
    '-NoProfile -ExecutionPolicy Bypass -File "{0}" -Symbols "{1}" -Sessions {2} -Stride {3} -Horizons "{4}"' -f
    $scriptPath, $Symbols, $Sessions, $Stride, $Horizons
).Trim()

$startTime = "{0:D2}:{1:D2}" -f [Math]::Max(0, [Math]::Min(23, $RunHour)), [Math]::Max(0, [Math]::Min(59, $RunMinute))

Write-Host "Creating/updating task: $TaskName ($dayName @ $startTime)"
$triggerTime = [datetime]::Today.AddHours([Math]::Max(0, [Math]::Min(23, $RunHour))).AddMinutes([Math]::Max(0, [Math]::Min(59, $RunMinute)))
$action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $taskArgs
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek $dayName -At $triggerTime
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable
Register-ScheduledTask -TaskName $TaskName -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null

Write-Host "Task created:"
$t = Get-ScheduledTask -TaskName $TaskName
$ti = Get-ScheduledTaskInfo -TaskName $TaskName
Write-Host "  TaskName: $($t.TaskName)"
Write-Host "  State: $($t.State)"
Write-Host "  NextRunTime: $($ti.NextRunTime)"
Write-Host "  Action: powershell.exe $taskArgs"
Write-Host ""
Write-Host "Done. Weekly flow backtest runs every $dayName at $startTime."
Write-Host "Recommendation artifact: artifacts/flow_backtest/recommendation_latest.json"
