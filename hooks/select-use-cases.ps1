#!/usr/bin/env pwsh
#
# Windows counterpart of select-use-cases.sh (azd preprovision hook).
#
# The POSIX script draws an interactive menu asking which use-cases to upload
# to blob storage after the deploy. This one deliberately does NOT prompt.
#
# Why no menu on Windows
# ----------------------
# The bash version talks to the terminal through /dev/tty, because azd repaints
# its progress table over anything a hook writes to stdout. Windows has no
# /dev/tty, and a hook that blocks on stdin while azd owns the console is how
# you hang a deploy with no way to answer. The upload is optional anyway: the
# backend seeds the same use-cases from the copy baked into its container image
# at startup, so skipping it costs nothing at deploy time, and the storage
# account is usually unreachable from a developer machine regardless (private
# endpoint + a policy forcing publicNetworkAccess: Disabled).
#
# Scripted runs keep full control through KRATOS_UPLOAD_USE_CASES, which works
# identically on both platforms.
#
# Never fails the deploy: any problem here just means "upload nothing".

$ErrorActionPreference = 'Continue'

$UseCasesDir = 'use-cases'

# Where the answer is handed to postdeploy. .azure/ is gitignored, and keying
# by env name keeps parallel environments from reading each other's choice.
$EnvName = if ($env:AZURE_ENV_NAME) { $env:AZURE_ENV_NAME } else { 'default' }
$SelectionDir = Join-Path '.azure' $EnvName
$SelectionFile = Join-Path $SelectionDir 'kratos-upload-selection'

function Write-Selection {
    param([string] $Value)
    try {
        if (-not (Test-Path $SelectionDir)) {
            New-Item -ItemType Directory -Path $SelectionDir -Force | Out-Null
        }
        # -NoNewline would leave postdeploy's reader with a bare token; the sh
        # version writes a trailing newline, so match it.
        Set-Content -Path $SelectionFile -Value $Value -Encoding utf8
    } catch {
        # A missing selection file simply means "upload nothing" downstream.
    }
}

if (Test-Path $SelectionFile) {
    Remove-Item $SelectionFile -Force -ErrorAction SilentlyContinue
}

if (-not (Test-Path $UseCasesDir -PathType Container)) {
    Write-Selection 'none'
    exit 0
}

# Explicit env var wins, exactly as it does on POSIX.
# Accepts: all | none | comma-separated use-case names.
if ($env:KRATOS_UPLOAD_USE_CASES) {
    Write-Selection $env:KRATOS_UPLOAD_USE_CASES
    Write-Host "Skills upload: '$($env:KRATOS_UPLOAD_USE_CASES)' (from KRATOS_UPLOAD_USE_CASES)."
    exit 0
}

# Legacy flag from before this was selectable.
if ($env:KRATOS_AUTO_UPLOAD_USE_CASES -eq '1') {
    Write-Selection 'all'
    Write-Host 'Skills upload: all (from KRATOS_AUTO_UPLOAD_USE_CASES=1).'
    exit 0
}

Write-Selection 'none'
Write-Host ''
Write-Host 'Skills upload: skipped (no prompt on Windows).'
Write-Host '  The deployed app still has every use-case — the backend seeds them'
Write-Host '  from the copy baked into its container image at startup.'
Write-Host '  To upload them to blob storage as well, re-run with:'
Write-Host '    $env:KRATOS_UPLOAD_USE_CASES = "all"; azd up'
Write-Host '  ...or afterwards:  ./hooks/postdeploy.ps1'
Write-Host ''

exit 0
