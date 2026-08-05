@echo off
cd /d "%~dp0"

set "APP_MODE=%~1"
if /I "%APP_MODE%"=="" set "APP_MODE=dev"
if /I "%APP_MODE%"=="--prod" set "APP_MODE=prod"
if /I "%APP_MODE%"=="prod" goto :PROFILE_PROD
if /I "%APP_MODE%"=="--dev" set "APP_MODE=dev"
if /I not "%APP_MODE%"=="dev" (
  echo [WARN] Mode khong hop le: %APP_MODE%
  echo [INFO] Su dung: run_app.bat ^| run_app.bat dev ^| run_app.bat prod
  set "APP_MODE=dev"
)
goto :PROFILE_DEV

:PROFILE_DEV
echo [INFO] App mode: DEV-BALANCED (uu tien gia/chi so live; cache giu khi hop le)
set "II_ENV=dev"
REM Mac dinh: lay snapshot/scrape truoc mock_json — tranh hien thi gia tu mock khi co mang
set "II_SNAPSHOT_PREFER_LIVE=1"
set "II_SNAPSHOT_ATTACH_LIVE=1"
set "II_MERGE_LIVE_FUNDAMENTALS=1"
set "II_READ_STALE_DISK=1"
set "II_SNAPSHOT_STALE_WHILE_REVALIDATE=1"
set "II_SNAPSHOT_SWR_PRICE_OVERLAY=0"
set "II_SNAPSHOT_SWR_PRICE_BUDGET_SEC=2.5"
set "II_SNAPSHOT_SWR_MIN_REFRESH_SEC=60"
set "II_QUOTE_PROVIDER_ORDER=vndirect,cafef,vietstock"
set "II_CAFEF_MAX_BOARDS=1"
set "II_CAFEF_TIMEOUT=3"
set "II_HTTP_TIMEOUT=5"
set "VALUE_INVESTOR_SCRAPER_TIMEOUT=6"
set "II_AUTOPILOT_UNIVERSE_MODE=rotate_full"
set "II_UNIVERSE_ROTATE_STYLE=sequential"
set "II_SCAN_OHLCV_SESSIONS=80"
set "II_VNSTOCK_TIMEOUT_SEC=3.5"
set "II_VNSTOCK_RETRY_MAX=1"
set "II_OHLCV_ALLOW_STALE_DISK_FALLBACK=1"
set "VALUE_INVESTOR_PORTAL_TIMEOUT=4"
set "II_PORTAL_TIMEOUT_LADDER_SEC=2,4"
set "II_ALIGN_PRICE_WITH_OHLCV=1"
set "II_UNIFIED_LIVE_PRICE=1"
set "II_OHLCV_DISK_FIRST=1"
set "II_OHLCV_DISK_MAX_AGE_SEC=7200"
set "II_FINANCIAL_DISK_FIRST=1"
set "II_FINANCIAL_DISK_MAX_AGE_SEC=21600"
set "II_FINANCIAL_MAX_PROBES=1"
set "II_FINANCIAL_STALE_WHILE_REVALIDATE=1"
set "II_FINANCIAL_SWR_MAX_AGE_SEC=43200"
set "II_FINANCIAL_SWR_MIN_REFRESH_SEC=90"
set "II_STRICT_REAL_FINANCIAL_DATA=1"
set "II_PORTAL_LIVE_BUDGET_SEC=6"
set "II_PORTAL_FAIL_FAST=1"
set "II_PORTAL_FAIL_FAST_BUDGET_SEC=3.5"
set "II_REQUIRE_APP_SECRET_KEY=0"
set "II_SCAN_MAX_WORKERS=4"
set "II_SCAN_SYMBOL_BATCH_SIZE=12"
set "II_SCAN_PREFILTER_MAX_WORKERS=4"
set "II_SCAN_PRESELECT_LIMIT_CAP=180"
set "II_OHLCV_RUNTIME_SESSIONS=700"
set "II_UI_LOW_MEM=1"
set "II_AUTO_BG_WARM_DEFAULT=0"
set "II_AUTOPILOT_MODE_DEFAULT=1"
set "II_AUTOPILOT_LIMIT_DEFAULT=15"
set "II_DEFER_AUTOPILOT_DEFAULT=1"
set "II_BG_UNIVERSE_LIMIT_DEFAULT=15"
set "II_BG_INTERVAL_DEFAULT_MIN=12"
set "II_SCAN_CACHE_TTL_SEC=300"
set "WATCHLIST_LIVE_MAX_SYMBOLS=15"
goto :PROFILE_COMMON

:PROFILE_PROD
echo [INFO] App mode: PROD-STRICT (uu tien do tin cay du lieu va bao mat)
set "II_ENV=prod"
set "II_SNAPSHOT_ATTACH_LIVE=1"
REM SWR: doc disk cu + refresh nen (tranh cold scrape khi TTL het)
set "II_READ_STALE_DISK=1"
set "II_SNAPSHOT_STALE_WHILE_REVALIDATE=1"
set "II_SNAPSHOT_SWR_PRICE_OVERLAY=0"
set "II_SNAPSHOT_SWR_PRICE_BUDGET_SEC=3"
set "II_SNAPSHOT_SWR_MIN_REFRESH_SEC=60"
set "II_QUOTE_PROVIDER_ORDER=vndirect,cafef,vietstock"
set "II_CAFEF_MAX_BOARDS=1"
set "II_CAFEF_TIMEOUT=3.5"
set "II_HTTP_TIMEOUT=8"
set "VALUE_INVESTOR_SCRAPER_TIMEOUT=8"
set "II_AUTOPILOT_UNIVERSE_MODE=rotate_full"
set "II_UNIVERSE_ROTATE_STYLE=sequential"
set "II_SCAN_OHLCV_SESSIONS=80"
set "II_VNSTOCK_TIMEOUT_SEC=5"
set "II_VNSTOCK_RETRY_MAX=1"
set "II_OHLCV_ALLOW_STALE_DISK_FALLBACK=1"
set "VALUE_INVESTOR_PORTAL_TIMEOUT=10"
set "II_PORTAL_TIMEOUT_LADDER_SEC=2,4,6"
set "II_ALIGN_PRICE_WITH_OHLCV=1"
set "II_UNIFIED_LIVE_PRICE=1"
set "II_OHLCV_DISK_FIRST=0"
set "II_OHLCV_DISK_MAX_AGE_SEC=900"
set "II_FINANCIAL_DISK_FIRST=0"
set "II_FINANCIAL_DISK_MAX_AGE_SEC=1800"
set "II_FINANCIAL_MAX_PROBES=2"
set "II_FINANCIAL_STALE_WHILE_REVALIDATE=1"
set "II_FINANCIAL_SWR_MAX_AGE_SEC=21600"
set "II_FINANCIAL_SWR_MIN_REFRESH_SEC=120"
set "II_STRICT_REAL_FINANCIAL_DATA=1"
set "II_PORTAL_LIVE_BUDGET_SEC=15"
set "II_PORTAL_FAIL_FAST=1"
set "II_PORTAL_FAIL_FAST_BUDGET_SEC=6"
set "II_REQUIRE_APP_SECRET_KEY=1"
set "II_MERGE_LIVE_FUNDAMENTALS=1"
set "II_SCAN_MAX_WORKERS=6"
set "II_SCAN_SYMBOL_BATCH_SIZE=20"
set "II_SCAN_PREFILTER_MAX_WORKERS=8"
set "II_SCAN_PRESELECT_LIMIT_CAP=300"
if not "%II_APP_SECRET_KEY%"=="" goto :PROFILE_COMMON
REM Env var rong: chap nhan neu .env co II_APP_SECRET_KEY= (app se nap qua python-dotenv va kiem tra strict khi khoi dong).
if exist ".env" (
  REM Khong dung /b: file .env luu boi PowerShell/Notepad co the co BOM o dau dong 1.
  findstr /c:"II_APP_SECRET_KEY=" ".env" >nul 2>&1
  if not errorlevel 1 (
    echo [INFO] II_APP_SECRET_KEY se duoc nap tu file .env khi app khoi dong.
    goto :PROFILE_COMMON
  )
)
echo [ERROR] II_APP_SECRET_KEY dang rong. Dat key truoc khi chay production.
echo [HINT] Them vao file .env: II_APP_SECRET_KEY=your_fernet_key_here
echo [HINT] Hoac: setx II_APP_SECRET_KEY "your_fernet_key_here"
pause
exit /b 1

:PROFILE_COMMON
REM Hybrid Legend calibrated defaults (batch calibration consensus)
set "II_LEGEND_PROFILE=defensive"
set "II_LEGEND_STRONG_BUY_MOS_MIN=8"
set "II_LEGEND_MAX_PEG_FOR_BUY=1.1"
set "II_LEGEND_WATCH_BUY_MOS_MIN=8"
REM Tuyet doi KHONG hardcode API key trong file batch.
REM Cau hinh key tu Environment Variables cua may:
REM setx GROQ_API_KEYS "gsk_key_1;gsk_key_2"
REM setx OPENAI_API_KEYS "sk_key_1;sk_key_2"
REM setx GEMINI_API_KEYS "AIza_key_1;AIza_key_2"
if "%GROQ_API_KEYS%"=="" (
  echo [WARN] GROQ_API_KEYS dang rong. App van chay, nhung co the fallback/no-LLM.
)
REM AI auto routing: speed | balanced | quality
set "AI_AUTO_TASK_MODE=balanced"
REM Neu confidence du lieu thap hon nguong nay thi tu dong nang cap sang tang quality
set "AI_ESCALATE_CONFIDENCE_BELOW=70"
REM Cache ket qua LLM de giam do tre khi phan tich lap lai
set "AI_LLM_CACHE_TTL_SEC=240"
REM Thu tu uu tien provider khi preferred_llm=auto (global/default)
set "AI_AUTO_PROVIDER_ORDER=groq,openai,gemini"
REM Co the override theo mode:
REM set "AI_AUTO_PROVIDER_ORDER_SPEED=groq,gemini,openai"
REM set "AI_AUTO_PROVIDER_ORDER_BALANCED=groq,openai,gemini"
REM set "AI_AUTO_PROVIDER_ORDER_QUALITY=openai,gemini,groq"

REM Mac dinh uu tien toc do startup: bo preflight chart, chi bat khi can.
if /I "%RUN_PREFLIGHT%"=="1" goto :RUN_PREFLIGHT
if /I "%SKIP_PREFLIGHT%"=="1" goto :RUN_STREAMLIT
goto :RUN_STREAMLIT

:RUN_PREFLIGHT
echo [PRECHECK] Kiem tra nhanh luong render chart...
set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if exist "%PY%" (
  "%PY%" -m pytest -q tests/test_candlestick_hover_compat.py
  if errorlevel 1 (
    echo [ERROR] Precheck chart khong dat. Dung app de tranh man hinh trang.
    echo [HINT] set SKIP_PREFLIGHT=1 de bo qua tam thoi
    pause
    exit /b 1
  )
  set "PRECHECK_OK=1"
  goto :RUN_STREAMLIT
)
where py >nul 2>&1
if %errorlevel%==0 (
  py -m pytest -q tests/test_candlestick_hover_compat.py
  if errorlevel 1 (
    echo [ERROR] Precheck chart khong dat.
    echo [HINT] set SKIP_PREFLIGHT=1 de bo qua tam thoi
    pause
    exit /b 1
  )
  set "PRECHECK_OK=1"
  goto :RUN_STREAMLIT
)
where python >nul 2>&1
if %errorlevel%==0 (
  python -m pytest -q tests/test_candlestick_hover_compat.py
  if errorlevel 1 (
    echo [ERROR] Precheck chart khong dat.
    echo [HINT] set SKIP_PREFLIGHT=1 de bo qua tam thoi
    pause
    exit /b 1
  )
  set "PRECHECK_OK=1"
  goto :RUN_STREAMLIT
)
echo [WARN] Khong tim thay Python de chay precheck — bo qua preflight.
goto :RUN_STREAMLIT

:RUN_STREAMLIT
if /I "%II_AUTO_START_PG_WORKER%"=="1" (
  if defined II_DB_URL (
    echo %II_DB_URL% | findstr /i "postgres" >nul 2>&1
    if not errorlevel 1 (
      echo [INFO] Tu dong khoi dong PostgreSQL job worker (cua so minimize).
      start "ii-pg-job-worker" /min cmd /c "cd /d "%~dp0" && python scripts\run_pg_job_worker.py"
    )
  )
)
if /I "%SKIP_PREFLIGHT%"=="1" (
  echo [INFO] Bo qua precheck chart ^(SKIP_PREFLIGHT=1^).
) else (
  if defined PRECHECK_OK (
    echo [PRECHECK] OK — mo Streamlit.
  ) else (
    echo [INFO] Mo Streamlit.
  )
)
set "PY=%LOCALAPPDATA%\Programs\Python\Python312\python.exe"
if exist "%PY%" (
  "%PY%" -m streamlit run app.py
  if errorlevel 1 pause
  exit /b %errorlevel%
)

where py >nul 2>&1
if %errorlevel%==0 (
  py -m streamlit run app.py
  if errorlevel 1 pause
  exit /b %errorlevel%
)

where python >nul 2>&1
if %errorlevel%==0 (
  python -m streamlit run app.py
  if errorlevel 1 pause
  exit /b %errorlevel%
)

echo Khong tim thay Python. Cai Python 3 hoac them python.exe vao PATH.
pause
exit /b 1
