param(
    [ValidateSet("dev", "preprod", "prod")]
    [string]$Env = "preprod",
    [switch]$SkipAudit,
    [switch]$SkipHealth,
    [string]$OutDir = "artifacts/performance"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

Set-Location (Join-Path $PSScriptRoot "..")

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

# Baseline env for structured logs / policy resolution.
$env:II_ENV = $Env
$env:II_LOG_JSON = "1"

$readinessCmd = "python scripts/prod_readiness_check.py --env $Env"
if ($SkipAudit) {
    $readinessCmd += " --skip-audit"
}
if ($SkipHealth) {
    $readinessCmd += " --skip-health"
}

try {
    Invoke-Step -Name "Production readiness gate ($Env)" -Command $readinessCmd
    Invoke-Step -Name "Sync smart-money structured events" -Command "python scripts/smart_money_event_sync.py --symbols FPT,VNM,HPG,VCB"
    Invoke-Step -Name "DSS commercial gate strict" -Command "python scripts/dss_release_gate.py --symbol FPT --user-id default_user --strict"
    Invoke-Step -Name "Build timing dashboard" -Command "python scripts/build_timing_dashboard.py --min-samples 1"
    Invoke-Step -Name "Autopilot nightly board health" -Command "python scripts/autopilot_nightly_board_health.py --min-coverage 50"
    Invoke-Step -Name "Resolve paper trades + hitrate" -Command "python scripts/resolve_paper_trades.py"
    Invoke-Step -Name "Export pilot KPI snapshot" -Command "python scripts/export_pilot_kpi_snapshot.py --out $OutDir/pilot_kpi_snapshot_nightly.json"
    Invoke-Step -Name "Runtime alert guard snapshot" -Command "python scripts/runtime_alert_guard.py --notify-on critical --out artifacts/operations/runtime_alert_guard_nightly.json"
    Invoke-Step -Name "Live-data stability benchmark (rolling)" -Command "python scripts/live_data_stability_benchmark.py --window-days 14 --min-sessions 7"
    Invoke-Step -Name "Guardian health check" -Command "python scripts/guardian_health_check.py --in artifacts/operations/runtime_guardian_health.json --require-ok"
    Invoke-Step -Name "Live data gate report" -Command "python scripts/live_data_gate_check.py --min-live-ratio 0.25"
    Write-Host ""
    Write-Host "[PASS] Nightly runtime check completed." -ForegroundColor Green
    exit 0
}
catch {
    Write-Host ""
    Write-Host "[FAIL] $($_.Exception.Message)" -ForegroundColor Red
    exit 1
}
