---
name: brain-runs
description: List past Agent Team sessions stored in claude-teams-brain
---

List all past Agent Team sessions recorded in the claude-teams-brain for this project.

Run: `python3 ${CLAUDE_PLUGIN_ROOT}/scripts/brain_engine.py list-runs "$CLAUDE_PROJECT_DIR"`

Show results as a table with columns: session ID (truncated), date, agents involved, tasks completed, and a one-line summary.
Sort newest first. If no runs are recorded yet, explain that sessions will be indexed automatically once Agent Teams are used.
