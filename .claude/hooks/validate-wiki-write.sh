#!/usr/bin/env bash
# validate-wiki-write.sh — Validate frontmatter before writing to wiki/.
# Triggered by PreToolUse hook on Write operations.
# Blocks writes to wiki/ that lack required frontmatter fields.

set -euo pipefail

input=$(cat)

file_path=$(echo "$input" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    params = data.get('tool_input', data)
    path = params.get('file_path', params.get('path', ''))
    print(path)
except Exception:
    print('')
" 2>/dev/null || echo "")

if [[ "$file_path" != *"wiki/"* ]]; then
    exit 0
fi

content=$(echo "$input" | python3 -c "
import json, sys
try:
    data = json.load(sys.stdin)
    params = data.get('tool_input', data)
    content = params.get('content', params.get('new_string', ''))
    print(content)
except Exception:
    print('')
" 2>/dev/null || echo "")

if ! echo "$content" | head -1 | grep -q "^---"; then
    echo "BLOCKED: wiki/ files must start with YAML frontmatter (---)" >&2
    exit 2
fi

for field in "title:" "type:" "area:"; do
    if ! echo "$content" | grep -q "$field"; then
        echo "BLOCKED: wiki/ frontmatter missing required field: $field" >&2
        exit 2
    fi
done

exit 0
