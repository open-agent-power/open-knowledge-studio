#!/usr/bin/env bash
# session-start.sh — Load knowledge base summary at session start.
# Triggered by SessionStart hook.

set -euo pipefail

REPO_ROOT="${OKS_ROOT:-$(pwd)}"

if [ ! -d "$REPO_ROOT/wiki" ]; then
    exit 0
fi

WIKI_COUNT=$(find "$REPO_ROOT/wiki" -name "*.md" -not -name "INDEX.md" 2>/dev/null | wc -l | tr -d ' ')
DRAFT_COUNT=0
RAW_COUNT=0

if [ -d "$REPO_ROOT/drafts" ]; then
    DRAFT_COUNT=$(find "$REPO_ROOT/drafts" -name "*.md" 2>/dev/null | wc -l | tr -d ' ')
fi

if [ -d "$REPO_ROOT/raw" ]; then
    RAW_COUNT=$(find "$REPO_ROOT/raw" -type f -not -name ".gitkeep" 2>/dev/null | wc -l | tr -d ' ')
fi

DOMAINS=$(ls -d "$REPO_ROOT/wiki"/*/ 2>/dev/null | xargs -I{} basename {} | grep -v "^_" | sort | tr '\n' ' ')

cat << EOF
[Knowledge Studio] $WIKI_COUNT wiki pages | $DRAFT_COUNT drafts | $RAW_COUNT raw files
Domains: $DOMAINS
Use /query to search knowledge, /ingest to triage raw files, /status for overview.
EOF

exit 0
