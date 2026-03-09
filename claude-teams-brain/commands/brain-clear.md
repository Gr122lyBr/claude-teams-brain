---
name: brain-clear
description: Clear all claude-teams-brain memory for this project
---

Clear all claude-teams-brain memory for this project. This is irreversible.

Before clearing, show the user the current brain stats and ask them to confirm by saying "yes, clear brain".

If confirmed, run:
`CLAUDE_BRAIN_CONFIRM_CLEAR=yes python3 ${CLAUDE_PLUGIN_ROOT}/scripts/brain_engine.py clear "$CLAUDE_PROJECT_DIR"`

After clearing, confirm success and note that the brain will start building fresh memory from the next Agent Team session.
