#!/usr/bin/env bash
set -euo pipefail

# ─────────────────────────────────────────────
#  Vit Installer — Git for Video Editing
#  Usage: curl -fsSL https://raw.githubusercontent.com/LucasHJin/vit/main/install.sh | bash
# ─────────────────────────────────────────────

VIT_HOME="$HOME/.vit"
VIT_SRC="$VIT_HOME/vit-src"
REPO_URL="https://github.com/LucasHJin/vit.git"

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

# ── Install into venv ───────────────────────

VIT_VENV="$VIT_HOME/venv"

if [ ! -d "$VIT_VENV" ]; then
    echo "  Creating virtual environment..."
    $PYTHON -m venv "$VIT_VENV"
fi

echo "  Installing Vit package..."
"$VIT_VENV/bin/pip" install "$VIT_SRC" --quiet

# ── Add venv bin to PATH ────────────────────

VIT_BIN="$VIT_VENV/bin"
if ! command -v vit &>/dev/null; then
    echo "  Adding vit to PATH..."
    export PATH="$VIT_BIN:$PATH"
    SHELL_RC=""
    if [ -f "$HOME/.zshrc" ]; then
        SHELL_RC="$HOME/.zshrc"
    elif [ -f "$HOME/.bashrc" ]; then
        SHELL_RC="$HOME/.bashrc"
    elif [ -f "$HOME/.bash_profile" ]; then
        SHELL_RC="$HOME/.bash_profile"
    fi
    if [ -n "$SHELL_RC" ] && ! grep -q "$VIT_BIN" "$SHELL_RC" 2>/dev/null; then
        echo "export PATH=\"$VIT_BIN:\$PATH\"" >> "$SHELL_RC"
    fi
fi

# ── Install Resolve plugin scripts ───────────

echo "  Installing DaVinci Resolve scripts..."
if command -v vit &>/dev/null; then
    vit install-resolve
else
    "$VIT_BIN/vit" install-resolve 2>/dev/null || {
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
echo "    2. Create and open your project in DaVinci Resolve"
echo "    3. Run: vit init your-project-name" in your terminal
echo "       (creates a vit tracking folder anywhere on disk — location doesn't matter)"
echo "    4. Run: vit collab setup"
echo "       (connect to a GitHub repo so your team can share the project)"
echo "    5. In Resolve: Workspace > Scripts > Vit"
echo "       (first launch will ask you to select the vit folder you just created)"
echo "    6. The panel handles everything from there (save, branch, merge, push, pull)"
echo ""
