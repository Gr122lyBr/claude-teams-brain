---
name: brain-stats
description: |
  Show brain and session stats — tasks indexed, decisions captured, token savings.
  Trigger: /brain-stats
user_invocable: true
---

# brain-stats

Show a full stats summary for persistent memory, the current session KB, and per-role activity.

## Instructions

Run a single command that returns all stats (persistent memory, session KB, and per-role breakdown):
```
python3 ${CLAUDE_PLUGIN_ROOT}/scripts/brain_engine.py full-stats "$CLAUDE_PROJECT_DIR"
```

The response JSON has three keys: `status`, `kb`, and `roles`.

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
- Sources: X (CLAUDE.md, git-log, batch_execute output, ...)

### Per-Role Breakdown
- backend: X tasks · X files (last active: <date>)
- frontend: X tasks · X files (last active: <date>)
```

## Interpreting the numbers

- **Tasks indexed** — completed tasks stored; grows each session
- **Decisions captured** — architectural choices extracted from transcripts, tagged by type (architecture/dependency/convention/pattern/tooling)
- **Files tracked** — distinct files agents have written or edited
- **Session KB chunks** — indexed output from this session's MCP tool calls; agents can search it with `search()`
- **Per-role** — which roles have the most accumulated memory; roles with 0 tasks get no context injection

If the brain is empty, encourage running an Agent Team session or using `/brain-remember` to seed initial conventions.

**Important**: Only use the exact command shown above. Do not invent or guess other command names.
