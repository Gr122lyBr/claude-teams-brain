---
name: brain-clear
description: |
  Clear all claude-teams-brain memory for this project
user_invocable: true
---

# brain-clear

Wipe all brain memory for this project. This is irreversible.

## Instructions

1. First show the current brain stats:
   ```
   python3 ${CLAUDE_PLUGIN_ROOT}/scripts/brain_engine.py status "$CLAUDE_PROJECT_DIR"
   ```

2. Ask the user to confirm by typing **"yes, clear brain"** before proceeding.

3. Only if confirmed, run:
   ```
   CLAUDE_BRAIN_CONFIRM_CLEAR=yes python3 ${CLAUDE_PLUGIN_ROOT}/scripts/brain_engine.py clear "$CLAUDE_PROJECT_DIR"
   ```

4. Confirm success and note that the brain will start building fresh from the next Agent Team session.

**Important**: Only use the exact commands shown above (`status` and `clear`). Do not invent or guess other command names.
