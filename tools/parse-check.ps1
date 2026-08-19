# Parse install.ps1 without running it.
#
# There is no `sh -n` for PowerShell, and piping an installer into `iex` gives
# a syntax error no earlier than the moment a visitor runs it. This is the
# equivalent check, and it belongs in the repository rather than in somebody's
# shell history.

$ErrorActionPreference = 'Stop'

$script = Join-Path $PSScriptRoot '..\lib\scripts\install.ps1' | Resolve-Path

$errors = $null
$tokens = $null
[System.Management.Automation.Language.Parser]::ParseFile($script, [ref]$tokens, [ref]$errors) | Out-Null

if ($errors) {
    $errors | ForEach-Object { Write-Host "$($_.Extent.StartLineNumber): $($_.Message)" -ForegroundColor Red }
    exit 1
}

Write-Host "$($script.Path) parses cleanly" -ForegroundColor Green
