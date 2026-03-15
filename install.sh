#!/usr/bin/env bash
set -euo pipefail

# ─────────────────────────────────────────────
#  Vit Installer — Git for Video Editing
#  Usage: curl -fsSL https://raw.githubusercontent.com/LucasHJin/giteo/main/install.sh | bash
# ─────────────────────────────────────────────

VIT_HOME="$HOME/.vit"
VIT_SRC="$VIT_HOME/vit-src"
REPO_URL="https://github.com/LucasHJin/giteo.git"

echo ""
echo "  Vit — Git for Video Editing"
echo "  ─────────────────────────────"
echo ""

# ── Check prerequisites ──────────────────────

check_command() {
    if ! command -v "$1" &>/dev/null; then
        echo "  Error: '$1' is not installed. Please install it and try again."
        exit 1
    fi
}

check_command git

# Find Python 3
PYTHON=""
for cmd in python3 python; do
    if command -v "$cmd" &>/dev/null; then
        version=$("$cmd" --version 2>&1 | grep -oE '[0-9]+\.[0-9]+')
        major=$(echo "$version" | cut -d. -f1)
        minor=$(echo "$version" | cut -d. -f2)
        if [ "$major" -ge 3 ] && [ "$minor" -ge 8 ]; then
            PYTHON="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON" ]; then
    echo "  Error: Python 3.8+ is required. Please install it and try again."
    exit 1
fi

echo "  Using: $($PYTHON --version), $(git --version)"

# Find pip
PIP=""
for cmd in pip3 pip; do
    if command -v "$cmd" &>/dev/null; then
        PIP="$cmd"
        break
    fi
done

if [ -z "$PIP" ]; then
    # Fall back to python -m pip
    if $PYTHON -m pip --version &>/dev/null; then
        PIP="$PYTHON -m pip"
    else
        echo "  Error: pip is not installed. Please install it and try again."
        exit 1
    fi
fi

# ── Download / update source ─────────────────

mkdir -p "$VIT_HOME"

if [ -d "$VIT_SRC/.git" ]; then
    echo "  Updating existing installation..."
    git -C "$VIT_SRC" pull --quiet
else
    if [ -d "$VIT_SRC" ]; then
        rm -rf "$VIT_SRC"
    fi
    echo "  Downloading Vit..."
    git clone --quiet "$REPO_URL" "$VIT_SRC"
fi

# ── Install Python package ───────────────────

echo "  Installing Vit package..."
$PIP install "$VIT_SRC" --quiet 2>/dev/null || $PIP install "$VIT_SRC" --quiet --user

# ── Install Resolve plugin scripts ───────────

echo "  Installing DaVinci Resolve scripts..."
if command -v vit &>/dev/null; then
    vit install-resolve
else
    # vit might not be on PATH yet (--user install)
    $PYTHON -m vit.cli install-resolve 2>/dev/null || {
        echo ""
        echo "  Note: Could not auto-install Resolve scripts."
        echo "  After restarting your terminal, run: vit install-resolve"
    }
fi

# ── Done ──────────────────────────────────────

echo ""
echo "  Vit installed successfully!"
echo ""
echo "  Next steps:"
echo "    1. Restart your terminal (or run: source ~/.zshrc)"
echo "    2. Restart DaVinci Resolve"
echo "    3. In Resolve: Workspace > Scripts > Vit"
echo ""
echo "  Quick start:"
echo "    vit init           # Initialize a project"
echo "    vit commit -m msg  # Save a version"
echo "    vit branch name    # Create a branch"
echo ""
