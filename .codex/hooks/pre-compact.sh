#!/usr/bin/env bash
# pre-compact.sh — Snapshot wiki/ and drafts/ before context compaction.
# Triggered by PreCompact hook.

set -euo pipefail

REPO_ROOT="${OKS_ROOT:-$(pwd)}"
SNAPSHOT_DIR="$REPO_ROOT/.oks/snapshots"
mkdir -p "$SNAPSHOT_DIR"

TIMESTAMP=$(date -u +"%Y%m%d-%H%M%S")
SNAPSHOT_FILE="$SNAPSHOT_DIR/pre-compact-$TIMESTAMP.md"

WIKI_COUNT=0
DRAFT_COUNT=0

if [ -d "$REPO_ROOT/wiki" ]; then
    WIKI_COUNT=$(find "$REPO_ROOT/wiki" -name "*.md" -not -name "INDEX.md" | wc -l | tr -d ' ')
fi

if [ -d "$REPO_ROOT/drafts" ]; then
    DRAFT_COUNT=$(find "$REPO_ROOT/drafts" -name "*.md" | wc -l | tr -d ' ')
fi

cat > "$SNAPSHOT_FILE" << EOF
# Pre-Compact Snapshot — $TIMESTAMP

## Knowledge Base State

- Wiki pages: $WIKI_COUNT
- Drafts: $DRAFT_COUNT

## Status

\`\`\`
$(oks status 2>/dev/null || echo "(oks not available)")
\`\`\`
EOF

echo "Snapshot saved: $SNAPSHOT_FILE"
exit 0
