# Comodor installer — Windows.
#
#   irm https://comodor.ai/install.ps1 | iex
#
# The job of this script is to finish. Somebody running one line from a web
# page has not agreed to debug anything, so it installs what it needs — an
# isolated environment, a package manager, a Python — rather than stopping to
# explain what they should have had already. It gives up only when it genuinely
# cannot proceed, and then it names exactly one thing to do next.
#
# Environment:
#   COMODOR_INSTALL_REF      install from a git ref or local path instead of PyPI
#   COMODOR_FORCE_TOOL       pin the method to uv | pipx | venv | pip
#   COMODOR_NO_BOOTSTRAP     never download a tool; fail instead
#   COMODOR_NO_MODIFY_PATH   do not touch the user PATH

$ErrorActionPreference = 'Stop'

$Package = 'comodor'
$Command = 'comodor'
$PythonMinMinor = 11
$Repo = 'https://github.com/ifekri/Comodor'

$DataHome = Join-Path $env:LOCALAPPDATA 'Comodor'
$VenvDir = Join-Path $DataHome 'venv'
$BinDir = Join-Path $env:USERPROFILE '.local\bin'
$Installed = ''

# ----------------------------------------------------------------- output --

function Write-Step { param([string]$Message) Write-Host "> " -ForegroundColor DarkYellow -NoNewline; Write-Host $Message }
function Write-Note { param([string]$Message) Write-Host "  $Message" -ForegroundColor DarkGray }
function Write-Ok { param([string]$Message) Write-Host "OK " -ForegroundColor Green -NoNewline; Write-Host $Message }

function Stop-WithHelp {
    param([string]$Message, [string[]]$Hints = @())
    Write-Host ''
    Write-Host "error: $Message" -ForegroundColor Red
    foreach ($hint in $Hints) { Write-Host "  $hint" }
    Write-Host ''
    Write-Host "  Nothing was installed. Please report this at $Repo/issues"
    Write-Host '  and include the output above — it says where it stopped.'
    exit 1
}

function Test-Command {
    param([string]$Name)
    $null -ne (Get-Command $Name -ErrorAction SilentlyContinue)
}

# ----------------------------------------------------------------- lookup --

# Where tools put themselves. `irm | iex` runs without the user's profile, and
# a tool installed minutes earlier by its own installer is often on disk but
# not yet on this process's PATH. Looking only at PATH declares it missing and
# then fails on a fallback, which is exactly the wrong answer.
$ToolDirs = @(
    $BinDir,
    (Join-Path $env:USERPROFILE '.cargo\bin'),
    (Join-Path $env:LOCALAPPDATA 'Microsoft\WindowsApps'),
    (Join-Path $env:LOCALAPPDATA 'Programs\Python\Scripts'),
    (Join-Path $env:APPDATA 'Python\Scripts')
)

function Find-Tool {
    param([string]$Name)
    $found = Get-Command $Name -ErrorAction SilentlyContinue
    if ($found) { return $found.Source }
    foreach ($dir in $ToolDirs) {
        $candidate = Join-Path $dir "$Name.exe"
        if (Test-Path $candidate) { return $candidate }
    }
    return $null
}

# ----------------------------------------------------------------- system --

function Invoke-Python {
    param([string[]]$Python, [string[]]$Arguments)
    if ($Python.Count -gt 1) { & $Python[0] $Python[1] @Arguments }
    else { & $Python[0] @Arguments }
}

# Every interpreter worth considering, newest first. Deliberately not "the
# first python on PATH": a machine can carry several, and the newest is not
# necessarily the one that can build a virtual environment.
function Get-PythonCandidates {
    $found = @()

    # An active virtual environment is an explicit statement about which
    # Python is meant, so it comes first.
    if ($env:VIRTUAL_ENV) {
        $candidate = Join-Path $env:VIRTUAL_ENV 'Scripts\python.exe'
        if (Test-Path $candidate) { $found += , @($candidate) }
    }

    # The Windows launcher knows about every install on the machine, including
    # ones that were never put on PATH.
    if (Test-Command 'py') {
        foreach ($version in @('3.14', '3.13', '3.12', '3.11')) {
            try {
                & py "-$version" -c 'import sys' 2>$null | Out-Null
                if ($LASTEXITCODE -eq 0) { $found += , @('py', "-$version") }
            } catch { }
        }
    }

    foreach ($name in @('python3', 'python')) {
        $resolved = Find-Tool $name
        if (-not $resolved) { continue }
        try {
            $minor = & $resolved -c 'import sys; print(sys.version_info[1] if sys.version_info[0] == 3 else -1)' 2>$null
            if ($LASTEXITCODE -eq 0 -and [int]$minor -ge $PythonMinMinor) {
                $found += , @($resolved)
            }
        } catch { }
    }

    return $found
}

# PEP 668. Rare on Windows but not impossible — a tool-managed runtime can mark
# itself off-limits to pip, and installing into it then fails with a wall of
# text recommending `--break-system-packages`. That flag is exactly what it
# sounds like and this script will never pass it.
function Test-ExternallyManaged {
    param([string[]]$Python)
    try {
        Invoke-Python -Python $Python -Arguments @(
            '-c', 'import os, sys, sysconfig; sys.exit(0 if os.path.exists(os.path.join(sysconfig.get_path(''stdlib''), ''EXTERNALLY-MANAGED'')) else 1)') 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}

function Test-InVirtualenv {
    param([string[]]$Python)
    try {
        Invoke-Python -Python $Python -Arguments @(
            '-c', 'import sys; raise SystemExit(0 if sys.prefix != sys.base_prefix else 1)') 2>$null | Out-Null
        return ($LASTEXITCODE -eq 0)
    } catch { return $false }
}

# Whether this interpreter can actually build a working environment. The exit
# code alone is not enough — a venv can be created and still have no pip in it
# — so what gets checked is whether the result can install a package.
function Test-VenvWorks {
    param([string[]]$Python)
    $probe = Join-Path $DataHome '.venv-probe'
    if (Test-Path $probe) { Remove-Item -Recurse -Force $probe -ErrorAction SilentlyContinue }
    try {
        New-Item -ItemType Directory -Force $DataHome | Out-Null
        Invoke-Python -Python $Python -Arguments @('-m', 'venv', $probe) 2>$null | Out-Null
    } catch { }

    $result = $false
    $probePython = Join-Path $probe 'Scripts\python.exe'
    if (Test-Path $probePython) {
        try {
            & $probePython -m pip --version 2>$null | Out-Null
            $result = ($LASTEXITCODE -eq 0)
        } catch { }
    }
    if (Test-Path $probe) { Remove-Item -Recurse -Force $probe -ErrorAction SilentlyContinue }
    return $result
}

# ---------------------------------------------------------------- install --

function Get-Target {
    $ref = $env:COMODOR_INSTALL_REF
    if (-not $ref) { return $Package }
    if ($ref -like 'git+*') { return $ref }
    # A local checkout is one that is actually there. Matching on shape alone
    # fails both ways: git refs contain slashes too (`refs/tags/v1`), and a
    # Windows path looks like no POSIX path at all.
    if (Test-Path $ref) { return $ref }
    return "git+$Repo@$ref"
}

# Fetch uv when there is no other way forward. It is a single binary that needs
# no Python and can fetch a Python itself, which makes it the one tool that
# answers both "nothing here can install packages" and "there is no suitable
# Python at all".
function Install-Uv {
    if ($env:COMODOR_NO_BOOTSTRAP) { return $null }

    Write-Step 'Installing uv, a package manager Comodor needs (about 15 MB)'
    Write-Note 'from https://astral.sh/uv — it fetches a Python too, if one is missing'
    try {
        $script = Invoke-RestMethod -Uri 'https://astral.sh/uv/install.ps1' -UseBasicParsing
        Invoke-Expression $script | Out-Null
    } catch {
        return $null
    }
    return (Find-Tool 'uv')
}

# ------------------------------------------------------------------- run --

Write-Host ''
Write-Host 'Comodor' -ForegroundColor DarkYellow -NoNewline
Write-Host ' — it learns the way you correct it.'
Write-Host ''

$edition = if ($PSVersionTable.PSEdition) { $PSVersionTable.PSEdition } else { 'Desktop' }
$arch = if ([System.Environment]::Is64BitOperatingSystem) { 'x64' } else { 'x86' }
Write-Note "Windows $arch · PowerShell $($PSVersionTable.PSVersion) ($edition)"

$uv = Find-Tool 'uv'
$pipx = Find-Tool 'pipx'
$candidates = Get-PythonCandidates
$python = if ($candidates.Count -gt 0) { $candidates[0] } else { $null }

if ($python) {
    $version = (Invoke-Python -Python $python -Arguments @('--version')) 2>&1
    Write-Note "$version"
}

# The interpreter that can actually build an environment, which is not always
# the newest one.
$venvPython = $null
foreach ($candidate in $candidates) {
    if (Test-VenvWorks $candidate) { $venvPython = $candidate; break }
}

# Ordered by reliability, not speed. Every route above `pip` produces an
# isolated install that cannot break, and cannot be broken by, anything else
# on the machine.
$tool = $env:COMODOR_FORCE_TOOL
if (-not $tool) {
    if ($uv) { $tool = 'uv' }
    elseif ($pipx) { $tool = 'pipx' }
    elseif ($venvPython) { $tool = 'venv' }
    else {
        $uv = Install-Uv
        if ($uv) { $tool = 'uv' }
        elseif ($python -and -not (Test-ExternallyManaged $python)) { $tool = 'pip' }
    }
}

if (-not $tool) {
    Stop-WithHelp 'Could not find, or install, any way to put Comodor on this machine.' @(
        '',
        'Any one of these fixes it:',
        '  * install Python 3.11 or newer from https://www.python.org/downloads/',
        '    (tick "Add python.exe to PATH" in the installer)',
        '  * install uv:   irm https://astral.sh/uv/install.ps1 | iex',
        '',
        'Then run this installer again.'
    )
}

$target = Get-Target

switch ($tool) {
    'uv' {
        if (-not $uv) { $uv = Find-Tool 'uv' }
        if (-not $uv) { Stop-WithHelp 'COMODOR_FORCE_TOOL=uv, but uv is not installed.' }
        Write-Step 'Installing with uv'
        & $uv tool install --force $target
        if ($LASTEXITCODE -ne 0) {
            Stop-WithHelp "uv could not install $Package." @('The output above says why.')
        }
        $Installed = Join-Path $BinDir "$Command.exe"
    }

    'pipx' {
        if (-not $pipx) { $pipx = Find-Tool 'pipx' }
        if (-not $pipx) { Stop-WithHelp 'COMODOR_FORCE_TOOL=pipx, but pipx is not installed.' }
        Write-Step 'Installing with pipx'
        & $pipx install --force $target
        if ($LASTEXITCODE -ne 0) {
            Stop-WithHelp "pipx could not install $Package." @('The output above says why.')
        }
        $Installed = Join-Path $BinDir "$Command.exe"
    }

    'venv' {
        # The answer to a Python that refuses installs: an environment is never
        # itself externally managed. No download, no extra tool, and the result
        # is as isolated as anything pipx would have produced.
        if (-not $venvPython) {
            foreach ($candidate in $candidates) {
                if (Test-VenvWorks $candidate) { $venvPython = $candidate; break }
            }
        }
        if (-not $venvPython) {
            Stop-WithHelp "COMODOR_FORCE_TOOL=venv needs a Python that can build one." @(
                'Install Python 3.11 or newer from https://www.python.org/downloads/'
            )
        }

        Write-Step 'Creating an isolated environment for Comodor'
        Write-Note $VenvDir
        New-Item -ItemType Directory -Force $DataHome | Out-Null
        Invoke-Python -Python $venvPython -Arguments @('-m', 'venv', '--clear', $VenvDir) | Out-Null

        $venvExe = Join-Path $VenvDir 'Scripts\python.exe'
        if (-not (Test-Path $venvExe)) {
            Stop-WithHelp "Could not build an environment for $Package." @(
                'The Python found here cannot create virtual environments.'
            )
        }

        Write-Step "Installing $Package"
        & $venvExe -m pip install --quiet --upgrade pip 2>$null | Out-Null
        & $venvExe -m pip install --upgrade $target
        if ($LASTEXITCODE -ne 0) {
            Stop-WithHelp "Could not install $Package into the environment." @(
                'The output above says why.'
            )
        }

        # A shim rather than a copy, so `comodor` always runs whatever the
        # environment currently holds: an upgrade needs no relinking, and a
        # removal leaves nothing behind that pretends to still work. Windows
        # symlinks need administrator rights, so this is a one-line launcher.
        New-Item -ItemType Directory -Force $BinDir | Out-Null
        $shim = Join-Path $BinDir "$Command.cmd"
        "@echo off`r`n`"$VenvDir\Scripts\$Command.exe`" %*" |
            Set-Content -Path $shim -Encoding ASCII
        $Installed = Join-Path $VenvDir "Scripts\$Command.exe"
    }

    'pip' {
        if (-not $python) { Stop-WithHelp 'COMODOR_FORCE_TOOL=pip needs a Python 3.11 or newer.' }

        if (Test-InVirtualenv $python) {
            # The user activated an environment; that is a statement about
            # where this should go.
            Write-Step 'Installing with pip (into the active environment)'
            $pipArguments = @('-m', 'pip', 'install', '--upgrade', $target)
            $scheme = 'sysconfig.get_default_scheme()'
        } else {
            if (Test-ExternallyManaged $python) {
                Stop-WithHelp 'This Python does not allow installing into it (PEP 668).' @(
                    'Run the installer without COMODOR_FORCE_TOOL and it will build an',
                    'isolated environment instead, which that rule does not cover.'
                )
            }
            Write-Step 'Installing with pip (user site)'
            $pipArguments = @('-m', 'pip', 'install', '--user', '--upgrade', $target)
            $scheme = "'nt_user'"
        }

        Invoke-Python -Python $python -Arguments $pipArguments
        if ($LASTEXITCODE -ne 0) {
            Stop-WithHelp "pip could not install $Package." @('The output above says why.')
        }
        try {
            # Ask Python where the scripts actually landed. USER_BASE + Scripts
            # looks right and is not: the real directory carries the version,
            # as in ...\Python\Python313\Scripts.
            # Single quotes inside the snippet on purpose: Windows PowerShell
            # mangles embedded double quotes when handing arguments to a native
            # executable, and the call silently returns nothing.
            $BinDir = Invoke-Python -Python $python -Arguments @(
                '-c', "import sysconfig; print(sysconfig.get_path('scripts', $scheme))")
            $Installed = Join-Path $BinDir "$Command.exe"
        } catch { }
    }

    default { Stop-WithHelp "Unknown COMODOR_FORCE_TOOL: $tool" @('Use one of: uv, pipx, venv, pip') }
}

# An install that reports success without producing a working command is the
# failure people waste the most time on, so it is checked — by running the
# thing, at its real path, rather than by trusting PATH.
Write-Host ''
$reported = ''
if ($Installed -and (Test-Path $Installed)) {
    try { $reported = (& $Installed --version 2>$null) } catch { }
}
if (-not $reported -and (Test-Command $Command)) {
    try { $reported = (& $Command --version 2>$null) } catch { }
}

if ($reported) {
    Write-Ok "$reported"
} else {
    Stop-WithHelp "$Package was installed but will not run." @(
        'That points at a broken Python environment rather than at the package.',
        "`"$Installed`" --version shows the real error."
    )
}

# Put the directory on PATH for next time. Printing an instruction and calling
# it done is where installers lose people: the command exists, the shell cannot
# find it, and "not recognized" reads exactly like a failed install.
$onPath = ($env:PATH -split ';') -contains $BinDir
if (-not $onPath) {
    $userPath = [Environment]::GetEnvironmentVariable('PATH', 'User')
    $alreadyThere = $userPath -and (($userPath -split ';') -contains $BinDir)

    if ($env:COMODOR_NO_MODIFY_PATH) {
        Write-Host ''
        Write-Host "$Command is at " -NoNewline
        Write-Host $Installed -ForegroundColor DarkYellow
        Write-Host "  Add $BinDir to your PATH to run it by name."
    }
    elseif ($alreadyThere) {
        # `irm | iex` runs in the caller's session, so this reaches the
        # terminal somebody is standing in - which is the whole difference
        # between an installer that finishes and one that hands over a command
        # to type. The other branch already did this; this one printed the
        # instruction instead, for no reason.
        $env:PATH = "$BinDir;$env:PATH"
        Write-Host ''
        Write-Note "$BinDir was already on your PATH; this terminal started before that."
        Write-Note 'It has it now.'
    }
    else {
        try {
            # Deliberately not setx: it truncates PATH at 1024 characters and
            # has cost people their environment. This edits the user scope.
            $updated = if ($userPath) { "$userPath;$BinDir" } else { $BinDir }
            [Environment]::SetEnvironmentVariable('PATH', $updated, 'User')
            $env:PATH = "$BinDir;$env:PATH"
            Write-Host ''
            Write-Note "Added $BinDir to your PATH."
            Write-Note 'That applies to new terminals; this one has it already.'
        } catch {
            Write-Host ''
            Write-Host "  $Command is at " -NoNewline
            Write-Host $Installed -ForegroundColor DarkYellow
            Write-Host "  Add $BinDir to your PATH to run it by name."
        }
    }
}

Write-Host ''
Write-Host "  $Command" -ForegroundColor White -NoNewline
Write-Host '              start the interface'
Write-Host "  $Command --demo" -ForegroundColor White -NoNewline
Write-Host '       try it offline, no API key needed'
Write-Host "  $Command doctor" -ForegroundColor White -NoNewline
Write-Host '       check what is configured'
Write-Host ''
Write-Note 'The first run asks which provider and model to use, once.'
Write-Note $Repo
Write-Host ''
