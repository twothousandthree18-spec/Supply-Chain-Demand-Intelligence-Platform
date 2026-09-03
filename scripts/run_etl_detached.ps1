# =====================================================================
# Supply Chain & Demand Intelligence Platform
# Phase 2 - Detached ETL launcher.
#
# Purpose: start the warehouse build ETL as an independent background
# process so it survives OpenCode's interactive execution timeout. This
# script:
#   * verifies PostgreSQL is running and the DB is reachable
#   * verifies no previous ETL process is still active
#   * records the child process PID to a file
#   * redirects stdout+stderr to a persistent log file
#   * launches via Start-Process WITHOUT -Wait
#   * returns control immediately
#
# Usage:
#   powershell -ExecutionPolicy Bypass -File scripts\run_etl_detached.ps1
#
# The ETL itself is resumable/idempotent (see src/etl/build_warehouse.py) and
# reuses already-valid staging; it marks abandoned 'running' audit rows as
# FAILED before starting a fresh run. No credentials are hardcoded here.
# =====================================================================

param(
    [switch]$SkipSchema   # pass --skip-schema to the ETL if schema already built
)

$ErrorActionPreference = "Stop"
$script:RepoRoot = Split-Path -Parent $PSScriptRoot
$Python        = Join-Path $RepoRoot ".venv\Scripts\python.exe"
$EtlEntry      = Join-Path $RepoRoot "src\etl\build_warehouse.py"
$PgBin         = "D:\Tools\PostgreSQL\pgsql\bin"
$Psql          = Join-Path $PgBin "psql.exe"
$PgIsReady     = Join-Path $PgBin "pg_isready.exe"

# Persistent outputs (kept out of git)
$RunDir   = Join-Path $RepoRoot "reports\etl"
$LogFile  = Join-Path $RunDir "etl_build.log"
$PidFile  = Join-Path $RunDir "etl.pid"
$ExitFile = Join-Path $RunDir "etl.exit"

# --- PostgreSQL connection settings (env override, never hardcoded secrets) ---
$env:PGHOST     = if ($env:PGHOST)     { $env:PGHOST }     else { "127.0.0.1" }
$env:PGPORT     = if ($env:PGPORT)     { $env:PGPORT }     else { "5432" }
$env:PGDATABASE = if ($env:PGDATABASE) { $env:PGDATABASE } else { "supply_chain_intelligence" }
$env:PGUSER     = if ($env:PGUSER)     { $env:PGUSER }     else { "postgres" }

function Log($msg) { Write-Host "[launcher] $msg" }

# 1) Verify PostgreSQL is running and reachable
if (-not (Test-Path $PgIsReady)) { throw "pg_isready not found at $PgIsReady" }
& $PgIsReady -h $env:PGHOST -p $env:PGPORT | Out-Null
if ($LASTEXITCODE -ne 0) { throw "PostgreSQL is NOT accepting connections on $($env:PGHOST):$($env:PGPORT)" }
Log "PostgreSQL accepting connections on $($env:PGHOST):$($env:PGPORT)"

# Verify DB reachable + inspect ETL run state
$dbReachable = $false
try {
    $dbReachable = (& $Psql -h $env:PGHOST -p $env:PGPORT -U $env:PGUSER -d $env:PGDATABASE -tAc "SELECT 1" 2>$null) -eq "1"
} catch { }
if (-not $dbReachable) { throw "Database $($env:PGDATABASE) is not reachable" }
Log "Database $($env:PGDATABASE) reachable"

Log "Current ETL run state (etl_run_log):"
& $Psql -h $env:PGHOST -p $env:PGPORT -U $env:PGUSER -d $env:PGDATABASE `
       -c "SELECT run_id, pipeline, status, records_loaded, started_at FROM etl_run_log ORDER BY run_id"

# 2) Verify no previous ETL process is still active
$procs = @(Get-Process -Name "python*" -ErrorAction SilentlyContinue |
           Where-Object { $_.Path -and $_.Path -eq $python })
if ($procs.Count -gt 0) {
    Log "An existing ETL python process is active (PID $($procs.Id -join ',')). Not launching again."
    exit 2
}
Log "No previous ETL process active."

# Report current staging row counts
Log "Current staging row counts:"
& $Psql -h $env:PGHOST -p $env:PGPORT -U $env:PGUSER -d $env:PGDATABASE -tAc `
    "SELECT 'calendar', count(*) FROM stg_calendar UNION ALL " +
    "SELECT 'sell_prices', count(*) FROM stg_sell_prices UNION ALL " +
    "SELECT 'sales_meta', count(*) FROM stg_sales_meta UNION ALL " +
    "SELECT 'sales_daily', count(*) FROM stg_sales_daily"

# 3) Ensure run directory exists
New-Item -ItemType Directory -Force -Path $RunDir | Out-Null

# Clear stale exit/pid markers from any previous completed run
Remove-Item -Path $ExitFile -ErrorAction SilentlyContinue
Remove-Item -Path $PidFile  -ErrorAction SilentlyContinue

# 4) Launch detached (no -Wait); redirect output to log; record PID
# NOTE: the project path contains spaces ("D:\M Projects\..."), so the ETL
# entry path MUST be explicitly double-quoted when passed to Start-Process.
# Passing an array to -ArgumentList does NOT reliably quote elements that
# contain spaces, which caused python to receive only "D:\M". We therefore
# build a single argument string with the script path wrapped in quotes.
$argStr = '"-u" "' + $EtlEntry + '"'
if ($SkipSchema) { $argStr += ' "--skip-schema"' }
$ps = Start-Process -FilePath $python `
    -ArgumentList $argStr `
    -WorkingDirectory $RepoRoot `
    -RedirectStandardOutput $LogFile `
    -RedirectStandardError "$LogFile.err" `
    -WindowStyle Hidden `
    -PassThru
$ps.Id | Set-Content -Path $PidFile -Encoding Ascii
Log "ETL launched detached (args: $argStr). PID = $($ps.Id)"
Log "Log file  = $LogFile"
Log "PID file  = $PidFile"
Log "Returned control immediately (not waiting for completion)."

exit 0
