---
name: claude-teams-brain
description: |
  Persistent cross-session memory for Claude Code Agent Teams.
  Use when spawning agent teams, reviewing past work, or when context
  from previous sessions is needed. Auto-activates for agent team workflows.
---

# claude-teams-brain Skill

## What it does
claude-teams-brain automatically indexes everything Agent Teams produce — tasks completed, files touched, decisions made — and injects role-specific memory into each new teammate via SubagentStart hooks.

## When to use
- **Always active** during Agent Team sessions (hooks fire automatically)
- Use `/brain-status` to see what's been indexed before starting a new team
- Use `/brain-query <role>` to preview what context a new teammate would receive
- Use `/brain-runs` to review past sessions

## How to spawn a memory-aware Agent Team
When creating a team, the brain works automatically. Just spawn your team normally:

```
Create an agent team. Spawn three teammates:
- backend: implement the API endpoints
- frontend: build the React components  
- tests: write integration tests
```

Each teammate will automatically receive:
1. Their past work history (tasks they've done before in this project)
2. Key decisions the team has made across all sessions
3. Files they've previously worked on

## Tips for better memory
- Use descriptive agent names that match their role (e.g., `backend`, `database`, `security`)
- Let tasks complete naturally so TaskCompleted hook fires
- The brain gets richer with each session — first run is cold, second run onwards gets context

## MCP Tools

claude-teams-brain exposes five MCP tools that teammates can use to manage context efficiently:

| Tool | When to use |
|------|-------------|
| `mcp__claude-teams-brain__batch_execute` | Run multiple shell commands in one call. Output is auto-indexed and searched. Use instead of raw Bash for large output. |
| `mcp__claude-teams-brain__search` | Query the session knowledge base after batch_execute for follow-up details. |
| `mcp__claude-teams-brain__index` | Manually save findings, analysis, or data for later retrieval by you or teammates. |
| `mcp__claude-teams-brain__execute` | Run shell, JavaScript, or Python code in a sandbox. Set `intent` to auto-filter large output. |
| `mcp__claude-teams-brain__stats` | Check session metrics: bytes indexed vs bytes returned to context. |

These tools are automatically available to all Task subagents. The PreToolUse hook injects usage instructions into every teammate prompt.

## Memory location
All data is stored locally at `~/.claude-teams-brain/projects/<project-hash>/brain.db`
Never sent anywhere. Fully offline. SQLite format — inspectable with any SQLite viewer.

## Resetting
Use `/brain-clear` to wipe memory for this project and start fresh.
