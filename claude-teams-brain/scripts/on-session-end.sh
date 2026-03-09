#!/usr/bin/env bash
# claude-brain: SessionEnd hook
# Generates a compressed summary of this session and stores it in the brain.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE="${SCRIPT_DIR}/brain_engine.py"
INPUT=$(cat)

PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"

SESSION_ID=$(echo "$INPUT" | python3 -c "
import sys, json
d = json.load(sys.stdin)
print(d.get('session_id', ''))
" 2>/dev/null || echo "")

if [ -n "$SESSION_ID" ]; then
    python3 "$ENGINE" summarize-run "$SESSION_ID" "$PROJECT_DIR" >/dev/null 2>&1 || true
fi

exit 0
