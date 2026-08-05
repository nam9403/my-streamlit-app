param(
    [string]$TaskName = "DuAn1_MonthlyAccountability",
    [int]$RunHour = 7,
    [int]$RunMinute = 30,
    [int]$DayOfMonth = 1,
    [int]$RetentionDays = 180,
    [switch]$SendEmail
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$python = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

$scriptPath = Join-Path $projectRoot "scripts\run_monthly_accountability.py"
$emailFlag = if ($SendEmail) { "--send-email" } else { "" }
$args = "`"$scriptPath`" --day-of-month $DayOfMonth --retention-days $RetentionDays $emailFlag"

$startTime = "{0:D2}:{1:D2}" -f [Math]::Max(0, [Math]::Min(23, $RunHour)), [Math]::Max(0, [Math]::Min(59, $RunMinute))

Write-Host "Creating/updating task: $TaskName"
# Run daily at fixed time; script self-gates by day-of-month.
schtasks /Create /F /SC DAILY /ST $startTime /TN $TaskName /TR "`"$python`" $args" | Out-Null

Write-Host "Task created:"
schtasks /Query /TN $TaskName /V /FO LIST
Write-Host ""
Write-Host "Done. Task runs daily at $startTime and executes monthly on day $DayOfMonth (UTC logic inside script)."
Write-Host "Retention: delete monthly markdown older than $RetentionDays day(s)."

