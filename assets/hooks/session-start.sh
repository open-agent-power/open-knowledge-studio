#!/usr/bin/env bash
# session-start.sh — Load knowledge base summary at session start.
# Triggered by SessionStart hook.

set -euo pipefail

OKS_PYTHON_CMD="${OKS_PYTHON:-python3}"
if [ -z "${OKS_PYTHON:-}" ] && [ "$OKS_PYTHON_CMD" = "python3" ]; then
    case "$(uname -s 2>/dev/null || true)" in
        MINGW*|MSYS*|CYGWIN*) OKS_PYTHON_CMD="python" ;;
    esac
fi
if ! "$OKS_PYTHON_CMD" -c 'import sys' >/dev/null 2>&1; then
    if [ -z "${OKS_PYTHON:-}" ] && [ "$OKS_PYTHON_CMD" != "python" ] && python -c 'import sys' >/dev/null 2>&1; then
        OKS_PYTHON_CMD="python"
    else
        OKS_PYTHON_CMD=""
    fi
fi

# Codex 要求 SessionStart 的 stdout 为结构化 JSON；没有可用解释器时保持
# fail-open 且不输出无效内容，避免阻塞会话启动。
if [ -z "$OKS_PYTHON_CMD" ]; then
    echo "[Knowledge Studio] SessionStart skipped: Python interpreter unavailable" >&2
    exit 0
fi

REPO_ROOT="${OKS_ROOT:-}"
if [ -z "$REPO_ROOT" ] && [ -n "$OKS_PYTHON_CMD" ]; then
    REPO_ROOT="$("$OKS_PYTHON_CMD" -c "import json,os;print(json.load(open(os.path.expanduser('~/.oks/config.json'))).get('knowledge_base_path',''))" 2>/dev/null || true)"
fi
if [ -z "$REPO_ROOT" ]; then
    REPO_ROOT="$(pwd)"
fi

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

DOMAINS=$(ls -d "$REPO_ROOT/wiki"/*/ 2>/dev/null | xargs -I{} basename {} | grep -v "^_" | sort | tr '\n' ' ' || true)
if [ -z "$DOMAINS" ]; then
    DOMAINS="none"
fi

CONTEXT=$(cat << EOF
[Knowledge Studio] $WIKI_COUNT wiki pages | $DRAFT_COUNT drafts | $RAW_COUNT raw files
Domains: $DOMAINS
Use oh-my-oks for knowledge lookup, daily goals, source intake and reviewed learning.
EOF
)

"$OKS_PYTHON_CMD" -c '
import json
import sys

json.dump(
    {
        "hookSpecificOutput": {
            "hookEventName": "SessionStart",
            "additionalContext": sys.argv[1],
        }
    },
    sys.stdout,
    ensure_ascii=False,
)
sys.stdout.write("\n")
' "$CONTEXT"

exit 0
