param(
    [int]$StartYearOffset = -1,
    [int]$EndYearOffset = 2
)

$ErrorActionPreference = "Stop"

$projectRoot = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $projectRoot

$yearNow = (Get-Date).Year
$startYear = $yearNow + $StartYearOffset
$endYear = $yearNow + $EndYearOffset

if ($endYear -lt $startYear) {
    throw "End year must be greater than or equal to start year."
}

$python = Join-Path $env:LOCALAPPDATA "Programs\Python\Python312\python.exe"
if (-not (Test-Path $python)) { $python = "python" }

Write-Host "[INFO] Updating VN market calendar for years $startYear..$endYear"
& $python "scripts/update_vn_market_calendar.py" --start-year $startYear --end-year $endYear
if ($LASTEXITCODE -ne 0) {
    throw "Calendar update failed with exit code $LASTEXITCODE"
}

Write-Host "[OK] Weekly market calendar update completed."
