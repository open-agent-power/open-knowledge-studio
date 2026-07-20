#!/usr/bin/env bash
# user-prompt-recall.sh — UserPromptSubmit wrapper.
# Passes the original stdin (editor JSON payload) through to the Python hook,
# and drops jieba's stderr chatter so only the clean <recalled-memory> block
# reaches stdout. Fails open (exit 0) so a prompt is never blocked.
exec python3 "$(dirname "$0")/user-prompt-recall.py" 2>/dev/null
