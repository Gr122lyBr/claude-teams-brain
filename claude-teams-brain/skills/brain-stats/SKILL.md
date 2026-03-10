---
name: brain-stats
description: |
  Show brain and session stats — tasks indexed, decisions captured, token savings.
  Trigger: /brain-stats
user_invocable: true
---

# brain-stats

Show a full stats summary for persistent memory and the current session KB.

## Instructions

Step 1 — Brain stats:
```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/brain_engine.py status "$CLAUDE_PROJECT_DIR"
```

Step 2 — Session KB stats:
```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/brain_engine.py kb-stats "$CLAUDE_PROJECT_DIR"
```

Display as a clean summary:

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

If the brain is empty, encourage the user to run an Agent Team session or use `/brain-remember` to add facts manually.
