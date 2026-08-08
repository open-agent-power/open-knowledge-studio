#!/usr/bin/env bash
# user-prompt-recall.sh — UserPromptSubmit wrapper.
# Passes the original stdin (editor JSON payload) through to the Python hook,
# and drops jieba's stderr chatter so only the clean <recalled-memory> block
# reaches stdout. Fails open (exit 0) so a prompt is never blocked.
# OKS_PYTHON is baked in by `oks hook install` to point at the interpreter
# that can import knowledge_studio (pipx/venv safe); falls back to python3.
exec "${OKS_PYTHON:-python3}" "$(dirname "$0")/user-prompt-recall.py" 2>/dev/null
