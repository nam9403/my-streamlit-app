param(
    [string]$TaskName = "DuAn1_OvernightScan",
    [int]$EveryMinutes = 30,
    [int]$BatchSize = 40,
    [int]$Workers = 3,
    [string]$StartHHMM = "17:00",
    [string]$EndHHMM = "07:00",
    [string]$Timezone = "Asia/Ho_Chi_Minh",
    [ValidateSet("dynamic_liquid", "liquid", "vn30")]
    [string]$UniverseMode = "dynamic_liquid"
)

<#
.SYNOPSIS
  Đăng ký Task Scheduler: mỗi N phút gọi overnight scan tick.
  Script Python tự bỏ qua ngoài khung 17:00–07:00 (mặc định).

.EXAMPLE
  powershell -ExecutionPolicy Bypass -File scripts\setup_overnight_scan_scheduler.ps1
#>

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$python = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

$scanScript = Join-Path $projectRoot "scripts\run_overnight_scan_tick.py"
$every = [Math]::Max(5, [Math]::Min(180, $EveryMinutes))
$batch = [Math]::Max(5, [Math]::Min(120, $BatchSize))
$workersN = [Math]::Max(1, [Math]::Min(8, $Workers))

# Wrapper .cmd sets overnight window env then runs python (reliable with schtasks).
$wrapperDir = Join-Path $projectRoot "data\runtime"
New-Item -ItemType Directory -Force -Path $wrapperDir | Out-Null
$wrapperPath = Join-Path $wrapperDir "run_overnight_scan_tick.cmd"
$wrapperBody = @"
@echo off
cd /d "$projectRoot"
set "II_OVERNIGHT_SCAN_START=$StartHHMM"
set "II_OVERNIGHT_SCAN_END=$EndHHMM"
set "II_OVERNIGHT_SCAN_TZ=$Timezone"
"$python" "$scanScript" --batch-size $batch --workers $workersN --universe-mode $UniverseMode
"@
Set-Content -LiteralPath $wrapperPath -Value $wrapperBody -Encoding ASCII

Write-Host "Creating/updating task: $TaskName"
schtasks /Create /F /SC MINUTE /MO $every /TN $TaskName /TR "`"$wrapperPath`"" | Out-Null

Write-Host "Task created:"
schtasks /Query /TN $TaskName /V /FO LIST | Select-String -Pattern "TaskName|Status|Next Run|Last Run|Task To Run|Schedule Type|Repeat"
Write-Host ""
Write-Host "Done. Every $every min; Python skips outside $StartHHMM-$EndHHMM ($Timezone)."
Write-Host "Wrapper: $wrapperPath"
Write-Host "Verify: python scripts/run_overnight_scan_tick.py --force --batch-size $batch --workers $workersN"
