---
name: brain-stats
description: Show brain and session stats — tasks indexed, decisions captured, token savings
---

Show a full stats summary for this project and the current session.

Step 1 — Brain stats (persistent memory):
```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/brain_engine.py status "$CLAUDE_PROJECT_DIR"
```

Step 2 — Session KB stats (current session):
```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/brain_engine.py kb-stats "$CLAUDE_PROJECT_DIR"
```

Display both as a clean summary:

```
## 🧠 claude-teams-brain Stats

### Persistent Memory
- Tasks indexed: X across Y sessions
- Decisions captured: X
- Files tracked: X
- Agents seen: X
- Last activity: <timestamp>

### Session Knowledge Base
- Chunks indexed: X
- Data indexed: XKB
- Sources: X
```

If the brain is empty, encourage the user to run an Agent Team session.
