#!/usr/bin/env bash
# PreToolUse hook: injects team memories into subagent Task prompts
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ENGINE="$SCRIPT_DIR/brain_engine.py"
PROJECT_DIR="${CLAUDE_PROJECT_DIR:-$(pwd)}"

# Read full hook event JSON from stdin
INPUT="$(cat)"

# Use Python to do all the heavy lifting (avoids shell JSON escaping issues)
python3 "$SCRIPT_DIR/pretooluse_inject.py" "$PROJECT_DIR" "$ENGINE" <<< "$INPUT"
