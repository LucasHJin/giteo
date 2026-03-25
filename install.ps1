# ─────────────────────────────────────────────
#  Vit Installer — Git for Video Editing (Windows)
#  Usage: irm https://raw.githubusercontent.com/LucasHJin/vit/main/install.ps1 | iex
# ─────────────────────────────────────────────

$ErrorActionPreference = "Stop"

$VIT_HOME = "$env:USERPROFILE\.vit"
$VIT_SRC = "$VIT_HOME\vit-src"
$REPO_URL = "https://github.com/LucasHJin/vit.git"

Write-Host ""
Write-Host "  Vit — Git for Video Editing"
Write-Host "  ─────────────────────────────"
Write-Host ""

# ── Check prerequisites ──────────────────────

function Check-Command($name) {
    if (-not (Get-Command $name -ErrorAction SilentlyContinue)) {
        Write-Host "  Error: '$name' is not installed. Please install it and try again."
        exit 1
    }
}

Check-Command "git"

# Find Python 3.8+
$PYTHON = $null
foreach ($cmd in @("python3", "python")) {
    $found = Get-Command $cmd -ErrorAction SilentlyContinue
    if ($found) {
        $versionOutput = & $cmd --version 2>&1
        if ($versionOutput -match "(\d+)\.(\d+)") {
            $major = [int]$Matches[1]
            $minor = [int]$Matches[2]
            if ($major -ge 3 -and $minor -ge 8) {
                $PYTHON = $cmd
                break
            }
        }
    }
}

if (-not $PYTHON) {
    Write-Host "  Error: Python 3.8+ is required. Please install it and try again."
    exit 1
}

$pyVersion = & $PYTHON --version 2>&1
$gitVersion = git --version
Write-Host "  Using: $pyVersion, $gitVersion"

# Check pip
$hasPip = $false
try {
    & $PYTHON -m pip --version 2>&1 | Out-Null
    $hasPip = $true
} catch {}

if (-not $hasPip) {
    Write-Host "  Error: pip is not installed. Please install it and try again."
    exit 1
}

# ── Download / update source ─────────────────

if (-not (Test-Path $VIT_HOME)) {
    New-Item -ItemType Directory -Path $VIT_HOME -Force | Out-Null
}

if (Test-Path "$VIT_SRC\.git") {
    Write-Host "  Updating existing installation..."
    git -C $VIT_SRC pull --quiet
} else {
    if (Test-Path $VIT_SRC) {
        Remove-Item -Recurse -Force $VIT_SRC
    }
    Write-Host "  Downloading Vit..."
    git clone --quiet $REPO_URL $VIT_SRC
}

# ── Install into venv ───────────────────────

$VIT_VENV = "$VIT_HOME\venv"

if (-not (Test-Path $VIT_VENV)) {
    Write-Host "  Creating virtual environment..."
    & $PYTHON -m venv $VIT_VENV
}

Write-Host "  Installing Vit package..."
& "$VIT_VENV\Scripts\pip.exe" install $VIT_SRC --quiet

# ── Add venv Scripts to PATH ─────────────────

$VIT_BIN = "$VIT_VENV\Scripts"
$userPath = [System.Environment]::GetEnvironmentVariable("PATH", "User")
if (-not ($userPath -split ';' | Where-Object { $_ -eq $VIT_BIN })) {
    Write-Host "  Adding $VIT_BIN to PATH..."
    $env:PATH = "$VIT_BIN;$env:PATH"
    [System.Environment]::SetEnvironmentVariable(
        "PATH",
        "$VIT_BIN;" + $userPath,
        "User"
    )
}

# ── Install Resolve plugin scripts ───────────

Write-Host "  Installing DaVinci Resolve scripts..."
$vitExe = "$VIT_BIN\vit.exe"
if (Test-Path $vitExe) {
    & $vitExe install-resolve
} else {
    try {
        & "$VIT_VENV\Scripts\python.exe" -m vit.cli install-resolve
    } catch {
        Write-Host ""
        Write-Host "  Note: Could not auto-install Resolve scripts."
        Write-Host "  After restarting your terminal, run: vit install-resolve"
    }
}

# ── Done ──────────────────────────────────────

Write-Host ""
Write-Host "  Vit installed successfully!"
Write-Host ""
Write-Host "  Next steps:"
Write-Host "    1. Restart your terminal"
Write-Host "    2. Create and open your project in DaVinci Resolve"
Write-Host "    3. Run: vit init your-project-name (in your terminal)"
Write-Host "       (creates a vit tracking folder anywhere on disk — location doesn't matter)"
Write-Host "    4. Run: vit collab setup"
Write-Host "       (connect to a GitHub repo so your team can share the project)"
Write-Host "    5. In Resolve: Workspace > Scripts > Vit"
Write-Host "       (first launch will ask you to select the vit folder you just created)"
Write-Host "    6. The panel handles everything from there (save, branch, merge, push, pull)"
Write-Host ""
