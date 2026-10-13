param(
    [double]$DurationSec = $(if ($env:SIM_DURATION) { [double]$env:SIM_DURATION } else { 0 }),
    [double]$MinIntervalSec = $(if ($env:MARKER_MIN_INTERVAL) { [double]$env:MARKER_MIN_INTERVAL } else { 1 }),
    [double]$MaxIntervalSec = $(if ($env:MARKER_MAX_INTERVAL) { [double]$env:MARKER_MAX_INTERVAL } else { 3 }),
    [string]$Compound = $(if ($env:SIM_COMPOUND) { $env:SIM_COMPOUND } else { 'psilocybin' }),
    [string]$SessionId = $(if ($env:SESSION_ID) { $env:SESSION_ID } else { '' }),
    [string]$ParticipantId = $(if ($env:PARTICIPANT_ID) { $env:PARTICIPANT_ID } else { '22222222-2222-2222-2222-222222222222' }),
    [string]$SiteId = $(if ($env:SITE_ID) { $env:SITE_ID } else { '33333333-3333-3333-3333-333333333333' }),
    [string]$SponsorId = $(if ($env:SPONSOR_ID) { $env:SPONSOR_ID } else { '44444444-4444-4444-4444-444444444444' })
)

$ErrorActionPreference = 'Stop'

function Import-DotEnv {
    param([Parameter(Mandatory = $true)][string]$Path)

    if (-not (Test-Path -LiteralPath $Path)) {
        return
    }

    foreach ($line in Get-Content -LiteralPath $Path) {
        $trimmed = $line.Trim()
        if (-not $trimmed -or $trimmed.StartsWith('#')) {
            continue
        }

        if ($trimmed -notmatch '^\s*([A-Za-z_][A-Za-z0-9_]*)=(.*)$') {
            continue
        }

        $name = $Matches[1]
        $value = $Matches[2].Trim()

        if ($value.Length -ge 2 -and $value.StartsWith('"') -and $value.EndsWith('"')) {
            $value = $value.Substring(1, $value.Length - 2)
        }

        if (-not [System.Environment]::GetEnvironmentVariable($name)) {
            [System.Environment]::SetEnvironmentVariable($name, $value, 'Process')
        }
    }
}

function Get-RepoRoot {
    return (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
}

function Get-PythonExe {
    param([Parameter(Mandatory = $true)][string]$RepoRoot)

    $candidate = Join-Path $RepoRoot '.venv\Scripts\python.exe'
    if (Test-Path -LiteralPath $candidate) {
        return $candidate
    }

    $pythonCmd = Get-Command python -ErrorAction SilentlyContinue
    $fallback = $null
    if ($pythonCmd) {
        $fallback = $pythonCmd.Source
        if (-not $fallback) {
            $fallback = $pythonCmd.Path
        }
    }
    if ($fallback) {
        return $fallback
    }

    throw "Could not find a Python interpreter. Expected '$candidate' or 'python' on PATH."
}

function Stop-ProcessTree {
    param([Parameter(Mandatory = $true)][int]$ProcessId)

    $children = Get-CimInstance Win32_Process -Filter "ParentProcessId=$ProcessId" -ErrorAction SilentlyContinue
    foreach ($child in $children) {
        Stop-ProcessTree -ProcessId ([int]$child.ProcessId)
    }

    Stop-Process -Id $ProcessId -Force -ErrorAction SilentlyContinue
}

function Start-TrackedProcess {
    param(
        [Parameter(Mandatory = $true)][string]$Name,
        [Parameter(Mandatory = $true)][string]$FilePath,
        [Parameter(Mandatory = $true)][string[]]$ArgumentList,
        [Parameter(Mandatory = $true)][string]$WorkingDirectory,
        [Parameter(Mandatory = $true)][string]$LogDir
    )

    $stdout = Join-Path $LogDir "$Name.out.log"
    $stderr = Join-Path $LogDir "$Name.err.log"

    return Start-Process `
        -FilePath $FilePath `
        -ArgumentList $ArgumentList `
        -WorkingDirectory $WorkingDirectory `
        -WindowStyle Hidden `
        -PassThru `
        -RedirectStandardOutput $stdout `
        -RedirectStandardError $stderr
}

$RepoRoot = Get-RepoRoot
Import-DotEnv -Path (Join-Path $RepoRoot '.env')

foreach ($required in @('DATABASE_URL', 'TEST_DATABASE_URL')) {
    if (-not [System.Environment]::GetEnvironmentVariable($required)) {
        throw "Missing required environment variable '$required'. Load .env or set it before running the sim."
    }
}

$env:SIMULATION_MODE = 'true'
$env:UV_CACHE_DIR = if ($env:UV_CACHE_DIR) { $env:UV_CACHE_DIR } else { Join-Path $RepoRoot '.uv-cache' }

New-Item -ItemType Directory -Force -Path $env:UV_CACHE_DIR | Out-Null
$LogDir = Join-Path $RepoRoot 'sim-logs'
New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

$PythonExe = Get-PythonExe -RepoRoot $RepoRoot
$sessionId = $SessionId
$processes = New-Object System.Collections.Generic.List[System.Diagnostics.Process]

function Cleanup {
    foreach ($proc in $processes) {
        if ($null -ne $proc -and -not $proc.HasExited) {
            Stop-ProcessTree -ProcessId $proc.Id
        }
    }
}

try {
    if (-not $sessionId) {
        $sessionId = (& $PythonExe -m capture.session_init `
            --compound $Compound `
            --site-id $SiteId `
            --sponsor-id $SponsorId `
            --participant-id $ParticipantId | Select-Object -Last 1).Trim()
    }

    if (-not $sessionId) {
        throw 'Session initialization did not return a session id.'
    }

    $env:SESSION_ID = $sessionId
    Write-Host "simulation session: $sessionId"
    Write-Host "logs: $LogDir"

    $processes.Add((Start-TrackedProcess -Name 'synthetic_board' -FilePath $PythonExe -ArgumentList @('-m', 'capture.synthetic_board') -WorkingDirectory $RepoRoot -LogDir $LogDir))
    Start-Sleep -Seconds 2
    $processes.Add((Start-TrackedProcess -Name 'marker_simulator' -FilePath $PythonExe -ArgumentList @('-m', 'capture.marker_simulator', '--min-interval', "$MinIntervalSec", '--max-interval', "$MaxIntervalSec") -WorkingDirectory $RepoRoot -LogDir $LogDir))
    $processes.Add((Start-TrackedProcess -Name 'watchdog' -FilePath $PythonExe -ArgumentList @('-m', 'capture.watchdog', '--session-id', $sessionId, '--participant-id', $ParticipantId, '--site-id', $SiteId, '--sponsor-id', $SponsorId) -WorkingDirectory $RepoRoot -LogDir $LogDir))
    $processes.Add((Start-TrackedProcess -Name 'safety' -FilePath $PythonExe -ArgumentList @('-m', 'ingestion.safety') -WorkingDirectory $RepoRoot -LogDir $LogDir))
    $processes.Add((Start-TrackedProcess -Name 'sqi' -FilePath $PythonExe -ArgumentList @('-m', 'ingestion.sqi') -WorkingDirectory $RepoRoot -LogDir $LogDir))

    if ($DurationSec -gt 0) {
        Start-Sleep -Seconds ([int][Math]::Ceiling($DurationSec))
    } else {
        $ids = $processes | ForEach-Object { $_.Id }
        if ($ids) {
            Wait-Process -Id $ids
        }
    }
}
finally {
    Cleanup
}
