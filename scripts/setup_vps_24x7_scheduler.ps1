param(
    [ValidateSet("dev", "preprod", "prod")]
    [string]$Env = "preprod",
    [string]$BackgroundTaskName = "DuAn1_BackgroundJobs",
    [string]$NightlyTaskName = "DuAn1_NightlyRuntimeCheck",
    [int]$EveryMinutes = 15,
    [string]$Watchlist = "FPT,HPG,VNM",
    [int]$UniverseLimit = 30,
    [int]$QueueJobs = 30,
    [int]$NightlyRunHour = 23,
    [int]$NightlyRunMinute = 30
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
    Write-Host ""
    Write-Host "[PASS] 24x7 scheduler setup completed." -ForegroundColor Green
    exit 0
}
catch {
    Write-Host ""
    Write-Host "[FAIL] $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
