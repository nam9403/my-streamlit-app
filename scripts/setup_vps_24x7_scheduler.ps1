param(
    [ValidateSet("dev", "preprod", "prod")]
    [string]$Env = "preprod",
    [string]$BackgroundTaskName = "DuAn1_BackgroundJobs",
    [string]$NightlyTaskName = "DuAn1_NightlyRuntimeCheck",
    [string]$OvernightScanTaskName = "DuAn1_OvernightScan",
    [int]$EveryMinutes = 15,
    [string]$Watchlist = "FPT,HPG,VNM",
    [int]$UniverseLimit = 30,
    [int]$QueueJobs = 30,
    [int]$NightlyRunHour = 23,
    [int]$NightlyRunMinute = 30,
    # Overnight 17:00–07:00 ON by default for VPS 24/7; pass -SkipOvernightScan to disable.
    [switch]$SkipOvernightScan,
    [int]$OvernightEveryMinutes = 30,
    [int]$OvernightBatchSize = 40,
    [int]$OvernightWorkers = 3,
    [string]$OvernightStart = "17:00",
    [string]$OvernightEnd = "07:00"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $projectRoot

function Invoke-Step {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$Command
    )
    Write-Host ""
    Write-Host "=== $Name ===" -ForegroundColor Cyan
    Write-Host "> $Command"
    Invoke-Expression $Command
    if ($LASTEXITCODE -ne 0) {
        throw "Step failed: $Name (exit code $LASTEXITCODE)"
    }
}

try {
    Invoke-Step -Name "Setup background scheduler" -Command (
        "powershell -ExecutionPolicy Bypass -File `"scripts/setup_background_scheduler.ps1`" " +
        "-TaskName `"$BackgroundTaskName`" -EveryMinutes $EveryMinutes " +
        "-Watchlist `"$Watchlist`" -UniverseLimit $UniverseLimit -QueueJobs $QueueJobs"
    )
    Invoke-Step -Name "Setup nightly runtime scheduler" -Command (
        "powershell -ExecutionPolicy Bypass -File `"scripts/setup_nightly_runtime_scheduler.ps1`" " +
        "-TaskName `"$NightlyTaskName`" -Env $Env -RunHour $NightlyRunHour -RunMinute $NightlyRunMinute"
    )
    if (-not $SkipOvernightScan) {
        Invoke-Step -Name "Setup overnight Autopilot scan (17:00-07:00, default ON)" -Command (
            "powershell -ExecutionPolicy Bypass -File `"scripts/setup_overnight_scan_scheduler.ps1`" " +
            "-TaskName `"$OvernightScanTaskName`" -EveryMinutes $OvernightEveryMinutes " +
            "-BatchSize $OvernightBatchSize -Workers $OvernightWorkers " +
            "-StartHHMM `"$OvernightStart`" -EndHHMM `"$OvernightEnd`""
        )
    }
    else {
        Write-Host ""
        Write-Host "[INFO] Overnight scan skipped (-SkipOvernightScan)." -ForegroundColor Yellow
    }
    Write-Host ""
    Write-Host "[PASS] 24x7 scheduler setup completed (overnight scan default ON)." -ForegroundColor Green
    exit 0
}
catch {
    Write-Host ""
    Write-Host "[FAIL] $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
