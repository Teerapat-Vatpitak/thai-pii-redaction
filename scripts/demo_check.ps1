#Requires -Version 7
<#
.SYNOPSIS
    Booth-demo preflight for AI Guard: prints PASS/FAIL per check before doors open.

.DESCRIPTION
    Read-only by default. Checks:
      1. Port 8000 state: free (app will spawn its own sidecar backend) or held
         by an already-healthy AI Guard backend (GET /api/health -> status "ok").
         FAIL if something else holds the port (stale process, another app).
      2. Demo asset files exist (Thai PII sample text + demo PDF).
      3. (optional, -KillOrphans) stop stray aiguard* processes so a relaunch
         gets a clean port. Report-only unless the switch is passed.

.PARAMETER KillOrphans
    Stop any process whose name matches "aiguard*" (case-insensitive). Default
    is off; the script only reports what it finds unless you pass this switch.

.EXAMPLE
    ./scripts/demo_check.ps1
    ./scripts/demo_check.ps1 -KillOrphans
#>

[CmdletBinding()]
param(
    [switch]$KillOrphans
)

$ErrorActionPreference = 'Stop'
$RepoRoot = Split-Path -Parent $PSScriptRoot
$results = @()

function Write-Check {
    param(
        [string]$Name,
        [bool]$Passed,
        [string]$Detail = ''
    )
    $status = if ($Passed) { 'PASS' } else { 'FAIL' }
    $color = if ($Passed) { 'Green' } else { 'Red' }
    $line = "[$status] $Name"
    if ($Detail) { $line += " - $Detail" }
    Write-Host $line -ForegroundColor $color
    $script:results += [pscustomobject]@{ Name = $Name; Passed = $Passed; Detail = $Detail }
}

Write-Host "== AI Guard booth-demo preflight ==" -ForegroundColor Cyan
Write-Host ""

# ── 1. Port 8000 ────────────────────────────────────────────────────────
Write-Host "-- Port 8000 --" -ForegroundColor DarkCyan

$portInUse = $false
try {
    $conn = Get-NetTCPConnection -LocalPort 8000 -State Listen -ErrorAction SilentlyContinue
    $portInUse = [bool]$conn
} catch {
    # Get-NetTCPConnection can throw on some hosts (no NetTCPIP module); fall back.
    $test = Test-NetConnection -ComputerName 127.0.0.1 -Port 8000 -WarningAction SilentlyContinue -InformationLevel Quiet
    $portInUse = [bool]$test
}

if (-not $portInUse) {
    Write-Check -Name 'Port 8000' -Passed $true -Detail 'free; the app will spawn its own backend on launch (cold start capped at ~30s, 60 retries x 500ms)'
} else {
    try {
        $health = Invoke-RestMethod -Uri 'http://127.0.0.1:8000/api/health' -Method Get -TimeoutSec 3
        if ($health.status -eq 'ok') {
            Write-Check -Name 'Port 8000' -Passed $true -Detail "held by a healthy AI Guard backend (version $($health.version)); app will reuse it, no new sidecar spawned"
        } else {
            Write-Check -Name 'Port 8000' -Passed $false -Detail "port 8000 responded but status was '$($health.status)', not 'ok'"
        }
    } catch {
        Write-Check -Name 'Port 8000' -Passed $false -Detail "port 8000 is held but /api/health did not answer as AI Guard (something else is on the port): $($_.Exception.Message)"
    }
}

# ── 2. Optional orphan cleanup ──────────────────────────────────────────
Write-Host ""
Write-Host "-- Stray aiguard processes --" -ForegroundColor DarkCyan

$orphans = Get-Process -Name 'aiguard*' -ErrorAction SilentlyContinue
if (-not $orphans) {
    Write-Check -Name 'Stray aiguard processes' -Passed $true -Detail 'none found'
} else {
    $names = ($orphans | ForEach-Object { "$($_.ProcessName) (PID $($_.Id))" }) -join ', '
    if ($KillOrphans) {
        try {
            $orphans | Stop-Process -Force -ErrorAction Stop
            Write-Check -Name 'Stray aiguard processes' -Passed $true -Detail "stopped: $names"
        } catch {
            Write-Check -Name 'Stray aiguard processes' -Passed $false -Detail "found ($names) but failed to stop: $($_.Exception.Message)"
        }
    } else {
        Write-Check -Name 'Stray aiguard processes' -Passed $false -Detail "found: $names (re-run with -KillOrphans to stop them for a clean relaunch)"
    }
}

# ── 3. Demo assets ──────────────────────────────────────────────────────
Write-Host ""
Write-Host "-- Demo assets --" -ForegroundColor DarkCyan

$sampleText = Join-Path $RepoRoot 'tests\fixtures\demo_sample_th.txt'
$samplePdf = Join-Path $RepoRoot 'examples\sample_document.pdf'

if (Test-Path $sampleText) {
    Write-Check -Name 'Thai sample text' -Passed $true -Detail $sampleText
} else {
    Write-Check -Name 'Thai sample text' -Passed $false -Detail "missing: $sampleText"
}

if (Test-Path $samplePdf) {
    Write-Check -Name 'Demo PDF' -Passed $true -Detail $samplePdf
} else {
    Write-Check -Name 'Demo PDF' -Passed $false -Detail "missing: $samplePdf (see docs/demo/booth-checklist.md for a fallback path)"
}

# ── Summary ──────────────────────────────────────────────────────────────
Write-Host ""
$failed = $results | Where-Object { -not $_.Passed }
if ($failed.Count -eq 0) {
    Write-Host "== ALL PASS ($($results.Count) checks) ==" -ForegroundColor Green
    exit 0
} else {
    Write-Host "== $($failed.Count) FAILED of $($results.Count) checks ==" -ForegroundColor Red
    exit 1
}
