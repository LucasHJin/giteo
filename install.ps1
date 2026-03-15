# ─────────────────────────────────────────────
#  Vit Installer — Git for Video Editing (Windows)
#  Usage: irm https://raw.githubusercontent.com/LucasHJin/giteo/main/install.ps1 | iex
# ─────────────────────────────────────────────

$ErrorActionPreference = "Stop"

$VIT_HOME = "$env:USERPROFILE\.vit"
$VIT_SRC = "$VIT_HOME\vit-src"
$REPO_URL = "https://github.com/LucasHJin/giteo.git"

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

# ── Install Python package ───────────────────

Write-Host "  Installing Vit package..."
& $PYTHON -m pip install $VIT_SRC --quiet 2>$null

# ── Install Resolve plugin scripts ───────────

Write-Host "  Installing DaVinci Resolve scripts..."
$vitCmd = Get-Command "vit" -ErrorAction SilentlyContinue
if ($vitCmd) {
    & vit install-resolve
} else {
    try {
        & $PYTHON -m vit.cli install-resolve
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
Write-Host "    2. Restart DaVinci Resolve"
Write-Host "    3. In Resolve: Workspace > Scripts > Vit"
Write-Host ""
Write-Host "  Quick start:"
Write-Host "    vit init           # Initialize a project"
Write-Host "    vit commit -m msg  # Save a version"
Write-Host "    vit branch name    # Create a branch"
Write-Host ""
