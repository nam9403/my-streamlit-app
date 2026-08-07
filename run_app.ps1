# Chay Streamlit trong PowerShell:
#   .\run_app.ps1            (DEV-FAST)
#   .\run_app.ps1 -Mode prod (PROD-STRICT)
# Bo qua preflight chart: -SkipPreflight hoac $env:SKIP_PREFLIGHT="1"
param(
    [ValidateSet("dev", "prod")]
    [string]$Mode = "dev",
    [switch]$SkipPreflight
)

Set-Location $PSScriptRoot

if ($Mode -eq "prod") {
    Write-Host "[INFO] App mode: PROD-STRICT"
    $env:II_ENV = "prod"
    $env:II_SNAPSHOT_ATTACH_LIVE = "1"
    # SWR: cho phep doc disk cu + refresh nen (tranh cold scrape ~20s khi TTL het)
    $env:II_READ_STALE_DISK = "1"
    $env:II_SNAPSHOT_STALE_WHILE_REVALIDATE = "1"
    $env:II_SNAPSHOT_SWR_PRICE_OVERLAY = "1"
    $env:II_SNAPSHOT_SWR_PRICE_BUDGET_SEC = "3"
    $env:II_SNAPSHOT_SWR_MIN_REFRESH_SEC = "60"
    $env:II_QUOTE_PROVIDER_ORDER = "vndirect,cafef,vietstock"
    $env:II_CAFEF_MAX_BOARDS = "1"
    $env:II_CAFEF_TIMEOUT = "3.5"
    $env:II_HTTP_TIMEOUT = "8"
    $env:VALUE_INVESTOR_SCRAPER_TIMEOUT = "8"
    $env:II_AUTOPILOT_UNIVERSE_MODE = "rotate_full"
    $env:II_UNIVERSE_ROTATE_STYLE = "sequential"
    $env:II_SCAN_OHLCV_SESSIONS = "80"
    $env:II_VNSTOCK_TIMEOUT_SEC = "5"
    $env:II_VNSTOCK_RETRY_MAX = "1"
    $env:II_OHLCV_ALLOW_STALE_DISK_FALLBACK = "1"
    $env:VALUE_INVESTOR_PORTAL_TIMEOUT = "10"
    $env:II_PORTAL_TIMEOUT_LADDER_SEC = "2,4,6"
    $env:II_ALIGN_PRICE_WITH_OHLCV = "1"
    $env:II_UNIFIED_LIVE_PRICE = "1"
    $env:II_OHLCV_DISK_FIRST = "0"
    $env:II_OHLCV_DISK_MAX_AGE_SEC = "900"
    $env:II_FINANCIAL_DISK_FIRST = "0"
    $env:II_FINANCIAL_DISK_MAX_AGE_SEC = "1800"
    $env:II_FINANCIAL_MAX_PROBES = "2"
    $env:II_FINANCIAL_STALE_WHILE_REVALIDATE = "1"
    $env:II_FINANCIAL_SWR_MAX_AGE_SEC = "21600"
    $env:II_FINANCIAL_SWR_MIN_REFRESH_SEC = "120"
    $env:II_STRICT_REAL_FINANCIAL_DATA = "1"
    $env:II_PORTAL_LIVE_BUDGET_SEC = "15"
    $env:II_PORTAL_FAIL_FAST = "1"
    $env:II_PORTAL_FAIL_FAST_BUDGET_SEC = "6"
    $env:II_REQUIRE_APP_SECRET_KEY = "1"
    $env:II_MERGE_LIVE_FUNDAMENTALS = "1"
    $env:II_SCAN_MAX_WORKERS = "6"
    $env:II_SCAN_SYMBOL_BATCH_SIZE = "20"
    $env:II_SCAN_PREFILTER_MAX_WORKERS = "8"
    $env:II_SCAN_PRESELECT_LIMIT_CAP = "300"
    if ([string]::IsNullOrWhiteSpace($env:II_APP_SECRET_KEY)) {
        # Env var rong: chap nhan neu .env co key (app nap qua python-dotenv + kiem tra strict luc khoi dong).
        $dotenvHasKey = (Test-Path -LiteralPath ".env") -and
            (Select-String -LiteralPath ".env" -Pattern '^II_APP_SECRET_KEY=' -Quiet)
        if ($dotenvHasKey) {
            Write-Host "[INFO] II_APP_SECRET_KEY se duoc nap tu file .env khi app khoi dong."
        }
        else {
            Write-Host "[ERROR] II_APP_SECRET_KEY dang rong. Dat key truoc khi chay production."
            Write-Host '[HINT] Them vao file .env: II_APP_SECRET_KEY=your_fernet_key_here'
            Write-Host '[HINT] Hoac: setx II_APP_SECRET_KEY "your_fernet_key_here"'
            exit 1
        }
    }
}
else {
    Write-Host "[INFO] App mode: DEV-BALANCED (uu tien gia/chi so live; cache khi hop le)"
    $env:II_ENV = "dev"
    $env:II_SNAPSHOT_PREFER_LIVE = "1"
    $env:II_SNAPSHOT_ATTACH_LIVE = "1"
    $env:II_MERGE_LIVE_FUNDAMENTALS = "1"
    $env:II_READ_STALE_DISK = "1"
    $env:II_SNAPSHOT_STALE_WHILE_REVALIDATE = "1"
    $env:II_SNAPSHOT_SWR_PRICE_OVERLAY = "1"
    $env:II_SNAPSHOT_SWR_PRICE_BUDGET_SEC = "2.5"
    $env:II_SNAPSHOT_SWR_MIN_REFRESH_SEC = "60"
    $env:II_QUOTE_PROVIDER_ORDER = "vndirect,cafef,vietstock"
    $env:II_CAFEF_MAX_BOARDS = "1"
    $env:II_CAFEF_TIMEOUT = "3"
    $env:II_HTTP_TIMEOUT = "5"
    $env:VALUE_INVESTOR_SCRAPER_TIMEOUT = "6"
    $env:II_AUTOPILOT_UNIVERSE_MODE = "rotate_full"
    $env:II_UNIVERSE_ROTATE_STYLE = "sequential"
    $env:II_SCAN_OHLCV_SESSIONS = "80"
    $env:II_VNSTOCK_TIMEOUT_SEC = "3.5"
    $env:II_VNSTOCK_RETRY_MAX = "1"
    $env:II_OHLCV_ALLOW_STALE_DISK_FALLBACK = "1"
    $env:VALUE_INVESTOR_PORTAL_TIMEOUT = "4"
    $env:II_PORTAL_TIMEOUT_LADDER_SEC = "2,4"
    $env:II_ALIGN_PRICE_WITH_OHLCV = "1"
    $env:II_UNIFIED_LIVE_PRICE = "1"
    # Disk OHLCV chi dung khi con moi (~15 phut) — tranh chart/gia dong cua cu hang gio.
    $env:II_OHLCV_DISK_FIRST = "0"
    $env:II_OHLCV_DISK_MAX_AGE_SEC = "900"
    $env:II_FINANCIAL_DISK_FIRST = "1"
    $env:II_FINANCIAL_DISK_MAX_AGE_SEC = "21600"
    $env:II_FINANCIAL_MAX_PROBES = "1"
    $env:II_FINANCIAL_STALE_WHILE_REVALIDATE = "1"
    $env:II_FINANCIAL_SWR_MAX_AGE_SEC = "43200"
    $env:II_FINANCIAL_SWR_MIN_REFRESH_SEC = "90"
    $env:II_STRICT_REAL_FINANCIAL_DATA = "1"
    $env:II_PORTAL_LIVE_BUDGET_SEC = "6"
    $env:II_PORTAL_FAIL_FAST = "1"
    $env:II_PORTAL_FAIL_FAST_BUDGET_SEC = "3.5"
    $env:II_REQUIRE_APP_SECRET_KEY = "0"
    $env:II_SCAN_MAX_WORKERS = "4"
    $env:II_SCAN_SYMBOL_BATCH_SIZE = "12"
    $env:II_SCAN_PREFILTER_MAX_WORKERS = "4"
    $env:II_SCAN_PRESELECT_LIMIT_CAP = "180"
    $env:II_OHLCV_RUNTIME_SESSIONS = "700"
    $env:II_UI_LOW_MEM = "1"
    $env:II_AUTO_BG_WARM_DEFAULT = "0"
    $env:II_AUTOPILOT_MODE_DEFAULT = "1"
    $env:II_AUTOPILOT_LIMIT_DEFAULT = "15"
    $env:II_DEFER_AUTOPILOT_DEFAULT = "1"
    $env:II_BG_UNIVERSE_LIMIT_DEFAULT = "15"
    $env:II_BG_INTERVAL_DEFAULT_MIN = "12"
    $env:II_SCAN_CACHE_TTL_SEC = "300"
    $env:WATCHLIST_LIVE_MAX_SYMBOLS = "15"
}

$env:II_LEGEND_PROFILE = "defensive"
$env:II_LEGEND_STRONG_BUY_MOS_MIN = "8"
$env:II_LEGEND_MAX_PEG_FOR_BUY = "1.1"
$env:II_LEGEND_WATCH_BUY_MOS_MIN = "8"

function Invoke-Python {
    param([Parameter(Mandatory = $true)][string[]]$Args)
    $py = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
    if (Test-Path -LiteralPath $py) { & $py @Args | Out-Host; return [int]$LASTEXITCODE }
    if (Get-Command py -ErrorAction SilentlyContinue) { py @Args | Out-Host; return [int]$LASTEXITCODE }
    if (Get-Command python -ErrorAction SilentlyContinue) { python @Args | Out-Host; return [int]$LASTEXITCODE }
    Write-Host "Khong tim thay Python. Cai Python 3 hoac them vao PATH."
    return 1
}

if (($env:RUN_PREFLIGHT -eq "1") -and (-not $SkipPreflight)) {
    Write-Host "[PRECHECK] Kiem tra nhanh luong render chart..."
    $preflightExit = Invoke-Python -Args @("-m", "pytest", "-q", "tests/test_candlestick_hover_compat.py")
    if ($preflightExit -ne 0) {
        Write-Host "[ERROR] Precheck chart khong dat (exit=$preflightExit). Dung app de tranh man hinh trang."
        Write-Host "[HINT] Neu can mo nhanh tam thoi, chay: .\\run_app.ps1 -SkipPreflight"
        exit $preflightExit
    }
    Write-Host "[PRECHECK] OK - Chart regression test passed."
}

if (($env:II_AUTO_START_PG_WORKER -eq "1") -and ($env:II_DB_URL -match "postgres")) {
    Write-Host "[INFO] Tu dong khoi dong PostgreSQL job worker (cua so minimize)."
    Start-Process -FilePath "cmd.exe" -ArgumentList '/c', "cd /d `"$PSScriptRoot`" && python scripts\run_pg_job_worker.py" -WindowStyle Minimized
}

$py = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
if (Test-Path -LiteralPath $py) {
    & $py -m streamlit run app.py
    exit $LASTEXITCODE
}
if (Get-Command py -ErrorAction SilentlyContinue) {
    py -m streamlit run app.py
    exit $LASTEXITCODE
}
if (Get-Command python -ErrorAction SilentlyContinue) {
    python -m streamlit run app.py
    exit $LASTEXITCODE
}
Write-Host "Khong tim thay Python. Cai Python 3 hoac them vao PATH."
exit 1
