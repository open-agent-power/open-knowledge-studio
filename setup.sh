#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
CLI_DIR="$SCRIPT_DIR/cli"

echo "=== Open Knowledge Studio Setup ==="

# Install CLI tool
if command -v pip3 &>/dev/null; then
    echo "Installing oks CLI..."
    pip3 install -e "$CLI_DIR" --quiet
    echo "  oks installed. Run 'oks --help' to verify."
else
    echo "pip3 not found. Please install Python 3.10+ and run:"
    echo "  pip3 install -e $CLI_DIR"
fi

# Create .gitkeep files for empty dirs
touch "$SCRIPT_DIR/profiles/users/.gitkeep" 2>/dev/null || true
touch "$SCRIPT_DIR/profiles/projects/.gitkeep" 2>/dev/null || true
touch "$SCRIPT_DIR/drafts/.gitkeep" 2>/dev/null || true
touch "$SCRIPT_DIR/raw/articles/.gitkeep" 2>/dev/null || true
touch "$SCRIPT_DIR/raw/papers/.gitkeep" 2>/dev/null || true
touch "$SCRIPT_DIR/raw/repos/.gitkeep" 2>/dev/null || true
touch "$SCRIPT_DIR/raw/misc/.gitkeep" 2>/dev/null || true

echo ""
echo "Setup complete."
echo "  oks status   — view knowledge base overview"
echo "  oks search \"query\"  — search wiki pages"
echo "  oks --help   — see all commands"
