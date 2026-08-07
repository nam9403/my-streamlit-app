<#
.SYNOPSIS
  Bootstrap VPS Windows sau khi clone/copy dự án: đăng ký scheduler 24/7
  (background jobs + nightly check + overnight scan 17:00–07:00).

.EXAMPLE
  # Trên VPS, trong thư mục dự án:
  powershell -ExecutionPolicy Bypass -File scripts\bootstrap_vps.ps1

  # Bỏ overnight scan:
  powershell -ExecutionPolicy Bypass -File scripts\bootstrap_vps.ps1 -SkipOvernightScan
#>
param(
    [ValidateSet("dev", "preprod", "prod")]
    [string]$Env = "preprod",
    [switch]$SkipOvernightScan,
    [switch]$SkipEnvHint,
    [int]$OvernightEveryMinutes = 30,
    [int]$OvernightBatchSize = 40,
    [int]$OvernightWorkers = 3
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $projectRoot

Write-Host "=== VPS bootstrap: $projectRoot ===" -ForegroundColor Cyan

if (-not $SkipEnvHint) {
    if (-not (Test-Path -LiteralPath ".env")) {
        if (Test-Path -LiteralPath ".env.vps4gb.example") {
            Copy-Item -LiteralPath ".env.vps4gb.example" -Destination ".env"
            Write-Host "[INFO] Created .env from .env.vps4gb.example — điền II_APP_SECRET_KEY / API keys trước prod." -ForegroundColor Yellow
        }
        else {
            Write-Host "[WARN] Chưa có .env — tạo từ .env.example / .env.vps4gb.example." -ForegroundColor Yellow
        }
    }
    else {
        Write-Host "[INFO] .env đã tồn tại — giữ nguyên."
    }
}

$setupArgs = @(
    "-ExecutionPolicy", "Bypass",
    "-File", (Join-Path $projectRoot "scripts\setup_vps_24x7_scheduler.ps1"),
    "-Env", $Env,
    "-OvernightEveryMinutes", $OvernightEveryMinutes,
    "-OvernightBatchSize", $OvernightBatchSize,
    "-OvernightWorkers", $OvernightWorkers
)
if ($SkipOvernightScan) {
    $setupArgs += "-SkipOvernightScan"
}

Write-Host "> powershell $($setupArgs -join ' ')"
& powershell @setupArgs
if ($LASTEXITCODE -ne 0) {
    throw "setup_vps_24x7_scheduler.ps1 failed (exit $LASTEXITCODE)"
}

Write-Host ""
Write-Host "[PASS] VPS bootstrap xong. Overnight scan sẽ tự chạy mỗi $OvernightEveryMinutes phút trong khung 17:00–07:00." -ForegroundColor Green
Write-Host "Kiểm tra: schtasks /Query /TN DuAn1_OvernightScan /V /FO LIST"
Write-Host "App UI:     .\\run_app.ps1 -Mode prod   (hoặc run_app_prod.bat)"
