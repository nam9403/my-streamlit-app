param(
    [string]$Symbols = "FPT,HPG,VNM,VCB,MWG,VRE,VHM,VIC,VPB,TCB",
    [int]$Sessions = 500,
    [int]$Stride = 5,
    [string]$Horizons = "1,5,20",
    [string]$OutputDir = "artifacts/flow_backtest",
    [switch]$SkipMarkdown
)

# Wrapper chạy backtest FlowSignal hàng tuần để auto-tune min_intensity.
# Output JSON kèm recommendation_latest.json sẽ được background_jobs đọc
# tự động qua _flow_min_intensity_env() ⇒ self-tuning loop (closed-loop).

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$python = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

$ts = Get-Date -Format "yyyyMMdd_HHmmss"
$outDir = Join-Path $projectRoot $OutputDir
if (-not (Test-Path $outDir)) {
    New-Item -ItemType Directory -Path $outDir -Force | Out-Null
}

$jsonOut = Join-Path $outDir ("flow_backtest_{0}.json" -f $ts)
$mdOut = Join-Path $outDir ("flow_backtest_{0}.md" -f $ts)

$args = @(
    "scripts/backtest_flow_signals.py",
    "--symbols", $Symbols,
    "--sessions", $Sessions,
    "--stride", $Stride,
    "--horizons", $Horizons,
    "--output", $jsonOut
)
if (-not $SkipMarkdown) {
    $args += @("--markdown", $mdOut)
}

Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Running flow backtest: $Symbols ($Sessions sessions)"
Push-Location $projectRoot
try {
    & $python @args
    if ($LASTEXITCODE -ne 0) {
        Write-Error "Backtest exited with code $LASTEXITCODE"
        exit $LASTEXITCODE
    }
}
finally {
    Pop-Location
}

Write-Host "[$(Get-Date -Format 'HH:mm:ss')] Backtest done. JSON: $jsonOut"
if (-not $SkipMarkdown) {
    Write-Host "Markdown: $mdOut"
}
Write-Host "Recommendation artifact updated: artifacts/flow_backtest/recommendation_latest.json"
Write-Host "(background_jobs._flow_min_intensity_env sẽ tự đọc khi cycle tiếp theo chạy)"
