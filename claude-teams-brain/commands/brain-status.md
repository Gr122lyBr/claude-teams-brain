---
name: brain-status
description: Show claude-teams-brain memory stats for this project
---

Show the current state of the claude-teams-brain memory index for this project.

Run: `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/brain_engine.py status "$CLAUDE_PROJECT_DIR"`

Display the results in a clear, human-readable format showing:
- Total tasks indexed
- Total runs/sessions recorded
- Number of decisions logged
- Number of files in the index
- Number of distinct agents seen
- Last activity timestamp

If the brain has data, also show the 3 most recent task summaries.
If the brain is empty, encourage the user to run an Agent Team session to start building memory.
