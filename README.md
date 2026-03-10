<p align="center">
  <img src="claude-teams-brain/assets/logo.png" alt="claude-teams-brain" width="120" />
</p>

# claude-teams-brain

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.8%2B-blue.svg)](https://python.org)
[![Node](https://img.shields.io/badge/node-18%2B-green.svg)](https://nodejs.org)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-plugin-orange.svg)](https://claude.ai/claude-code)

**Persistent cross-session memory for Claude Code Agent Teams.**

Claude Code's Agent Teams are powerful — but ephemeral. Every teammate spawns with a blank slate. Every session forgets what the last one built. claude-teams-brain fixes this by automatically indexing everything your team produces and injecting role-specific memory into every new teammate the moment they spawn.

Your AI team gets smarter with every session. No extra prompting. No manual context copying. No more starting from zero.

---

## Installation

**Requirements:** Python 3.8+, Node.js 18+, Claude Code v2.1+

> **Windows users:** WSL2 is required. The plugin scripts run in bash. Native Windows (cmd/PowerShell) is not supported.

### 1. Install the plugin

In Claude Code, run:

```
/plugin marketplace add https://github.com/Gr122lyBr/claude-teams-brain
/plugin install claude-teams-brain@claude-teams-brain
```

### 2. Enable Agent Teams

Add to `~/.claude/settings.json`:

```json
{
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
  }
}
```

If `settings.json` already has content, merge the `env` block:

```json
{
  "someExistingSetting": true,
  "env": {
    "YOUR_EXISTING_VAR": "value",
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
  }
}
```

Restart Claude Code after saving.

---

## Quick Start

> **Important:** claude-teams-brain only works when Claude spawns Agent Team teammates. If Claude works solo, no memory is built. The two options below ensure teammates are always used.

### Option A — Trigger a team manually

Paste this into Claude Code on any project:

```
Create an agent team to work on this project.
Spawn specialized teammates based on what the task needs —
for example: backend, frontend, tests, security, or architect.
Use role-specific names so claude-teams-brain can inject memory into each teammate.
```

### Option B — Make it automatic (recommended)

Add this to your project's `CLAUDE.md` file once, and Claude will always use Agent Teams without you having to ask:

```markdown
## Agent Teams

Always use agent teams for tasks that can be parallelized across concerns.
Spawn specialized teammates with role-specific names rather than doing everything
in a single session. Good team structures:

- Feature work: `backend`, `frontend`, `tests`
- Reviews: `security`, `performance`, `coverage`
- Architecture: `architect`, `devil-advocate`, `implementer`
- Debugging: name teammates after the hypothesis they're testing
- Research & writing: `researcher`, `writer`, `editor`

The claude-teams-brain plugin is active — each teammate will automatically receive
memory from past sessions relevant to their role.
```

> **Tip:** Role names are fully dynamic. Any name you use becomes a role. The brain routes memory by role name across sessions — so as long as you reuse the same names, memory builds up automatically.

---

## Why this matters

Agent Teams introduced true multi-agent parallelism to Claude Code — teammates that communicate directly, own separate file scopes, and collaborate without a single-session bottleneck. But they have one fundamental weakness:

> *Teammates exist for the duration of a session and then they're gone. No persistent identity, no memory across sessions, no `/resume`.*

This creates a compounding problem on real projects. Your backend agent spent two hours establishing architecture decisions, learning your conventions, and building the auth system. Tomorrow, a new backend agent spawns and rediscovers everything from scratch — making inconsistent decisions, touching files already settled, asking questions already answered.

claude-teams-brain solves this at the infrastructure level. It hooks into the Agent Teams lifecycle, indexes every task completion, file change, and architectural decision, and injects the relevant history directly into each new teammate's context before they write a single line of code.

---

## How it works

claude-teams-brain hooks into six lifecycle events:

| Hook | What happens |
|------|-------------|
| `SessionStart` | Brain initializes; indexes CLAUDE.md, git log, directory tree, and config files into the session KB; warns if Agent Teams env var is not set |
| `SubagentStart` | ⭐ Role-specific memory injected — ranked by relevance to the current task, deduplicated |
| `TaskCompleted` | Task indexed immediately; shows `🧠 Indexed: [agent] task` confirmation so you can see the brain working in real time |
| `SubagentStop` | Rich indexing: files touched, decisions made, output summary extracted from transcript |
| `TeammateIdle` | Passive checkpoint |
| `SessionEnd` | Full session compressed into a summary entry |

The `SubagentStart` hook is the core mechanism. When a teammate named `backend` spawns, the brain queries everything the backend agent has done across all past sessions — tasks completed, files owned, decisions made — ranks them by relevance to the current task description, deduplicates, and injects the result before the agent processes its first message. The teammate starts informed, not blank.

All data lives in `~/.claude-teams-brain/projects/<project-hash>/brain.db` — a local SQLite database. Nothing is sent anywhere. No external dependencies beyond Python 3.8+ stdlib.

### Session warm-up

At every `SessionStart`, the brain automatically pre-indexes the following so teammates can search it immediately via `batch_execute`:

| Source | What gets indexed |
|--------|------------------|
| `CLAUDE.md` | Project instructions and conventions (if > 200 bytes) |
| `git log` | Last 20 commits |
| Directory tree | Project file structure (3 levels deep, noise excluded) |
| Config files | `package.json`, `requirements.txt`, `pyproject.toml`, `Cargo.toml`, `go.mod` |

This means the first `batch_execute` call of every teammate already has project context available — no cold-start discovery needed.

---

## Usage

Once installed, the brain works silently in the background. Just use Agent Teams normally.

**First session (cold start):**
```
You: Create an agent team to build the payments module.
     backend: API endpoints and business logic
     database: schema and migrations
     tests: integration test coverage

[Agent Teams session runs — claude-teams-brain indexes everything]
```

**Second session (warm start):**
```
You: Create an agent team to add webhook support to payments.
     backend: extend the existing payment API

[backend agent spawns and immediately receives:]
  "## 🧠 claude-teams-brain: Memory for role [backend]

   ### Project Rules & Conventions
   - Always use UUID v7 for all new database tables
   - All API endpoints must include rate limiting

   ### Your Past Work
   - Built payment API endpoints in /src/payments/api.ts
   - Implemented idempotency key validation middleware

   ### Key Team Decisions
   - [database] Using UUID v7 for all payment record IDs
   - [backend] Chose RS256 over HS256 for JWT — better key rotation
   - [backend] All payment endpoints require idempotency keys

   ### Files You Own
   - /src/payments/api.ts
   - /src/payments/middleware/idempotency.ts"
```

The teammate starts with full context from day one.

---

## Commands

| Command | Description |
|---------|-------------|
| `/brain-remember <text>` | Store a rule or convention injected into all future teammates |
| `/brain-forget <text>` | Remove a manually stored memory |
| `/brain-search <query>` | Search the full brain knowledge base directly |
| `/brain-export` | Export all brain knowledge as `CONVENTIONS.md` |
| `/brain-stats` | Full stats: persistent memory + session KB |
| `/brain-status` | Memory stats for this project |
| `/brain-query <role>` | Preview the context a new teammate would receive |
| `/brain-runs` | List past Agent Team sessions |
| `/brain-clear` | Reset all memory for this project |
| `/brain-update` | Pull the latest version from GitHub |

> **Note:** If a command does not appear in your list, prefix it with the plugin name: `/claude-teams-brain:brain-update`.

### Updating the plugin

```
/brain-update
```

If you installed an older version and `/brain-update` is not yet available, re-add the marketplace:

```
/plugin marketplace remove claude-teams-brain
/plugin marketplace add https://github.com/Gr122lyBr/claude-teams-brain
/plugin install claude-teams-brain@claude-teams-brain
```

---

## MCP Tools

claude-teams-brain includes an MCP server that exposes five tools to all Task subagents. These tools keep large command output out of context windows by indexing it into a session knowledge base and returning only relevant search results.

> **Token savings in practice:** running `npm test` or `git log` via `batch_execute` typically returns 200–500 tokens of targeted results instead of 5,000–20,000 tokens of raw output — a **90–97% reduction** per call. Use `/brain-status` at the end of a session to see your actual savings.

### batch_execute

Run multiple shell commands, auto-index all output, and search with queries in a single call. Identical commands within the same session are served from a **60-second cache** — no redundant process spawns, no duplicate context.

```json
{
  "commands": [
    {"label": "git log", "command": "git log --oneline -20"},
    {"label": "test results", "command": "npm test 2>&1"}
  ],
  "queries": ["recent commits about auth", "failing tests"],
  "timeout": 60000
}
```

### search

Search the session knowledge base built by previous batch_execute or index calls.

```json
{
  "queries": ["authentication middleware", "error handling patterns"],
  "limit": 3
}
```

### index

Manually index content (findings, analysis, data) for later retrieval.

```json
{
  "content": "The auth module uses RS256 JWT tokens with 15-minute expiry...",
  "source": "auth-analysis"
}
```

### execute

Run code in a sandboxed subprocess. Set `intent` to auto-index and search large output.

```json
{
  "language": "python",
  "code": "import ast; print(ast.dump(ast.parse(open('main.py').read())))",
  "timeout": 30000,
  "intent": "find all class definitions"
}
```

Supported languages: `shell`, `javascript`, `python`.

### stats

Show session context savings metrics.

```json
{}
```

Returns bytes indexed vs bytes returned, call counts, and context savings ratio.

---

## Project structure

```
claude-teams-brain/                    ← repo root (marketplace)
  .claude-plugin/
    marketplace.json
  claude-teams-brain/                  ← the plugin
    .claude-plugin/
      plugin.json
    hooks/
      hooks.json                       ← 6 lifecycle hooks
    scripts/
      brain_engine.py                  ← SQLite engine (pure stdlib)
      on-session-start.sh
      on-subagent-start.sh             ← core: injects memory + tool guidance into teammates
      on-subagent-stop.sh              ← rich indexing from transcript
      on-task-completed.sh
      on-teammate-idle.sh
      on-session-end.sh
      update.sh                        ← pulled by /brain-update
    commands/                          ← /brain-* slash commands
      brain-remember, brain-forget, brain-search
      brain-export, brain-status, brain-stats
      brain-query, brain-runs, brain-clear, brain-update
    skills/
      claude-teams-brain/              ← auto-activates for agent team workflows
      brain-update/                    ← /brain-update
      brain-remember/                  ← /brain-remember
      brain-forget/                    ← /brain-forget
      brain-search/                    ← /brain-search
      brain-export/                    ← /brain-export
      brain-stats/                     ← /brain-stats
    settings.json                      ← enables CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS
```

---

## Memory storage

```
~/.claude-teams-brain/
  └── projects/
      └── <project-hash>/
          └── brain.db    ← SQLite, one file per project
```

Each project has its own isolated brain. Memory never crosses project boundaries. The SQLite file is fully inspectable with any database viewer.

---

## Tips

- **Use descriptive agent names** that match their role (`backend`, `database`, `security`) — the brain routes memory by role name
- **Memory compounds** — the first session is cold, but quality improves significantly from the second session onwards
- **Use `/brain-remember`** to store project conventions before your first team session — teammates will receive them immediately
- **Run `/brain-query backend`** to preview exactly what context the backend agent will receive before spawning
- **Run `/brain-export`** after a few sessions to generate a `CONVENTIONS.md` you can commit to the repo
- **Memory is relevance-ranked** — if you describe the task clearly when spawning teammates, the brain injects the most relevant past work first
- **CLAUDE.md is auto-indexed** at every session start — teammates can search it via `batch_execute` queries without re-reading it manually
- **Use `/brain-search <query>`** to verify what the brain has indexed — great for debugging or confirming memory is building
- **Use `/brain-stats`** to see a full breakdown of indexed tasks, decisions, and session KB usage
- **If you see a warning about Agent Teams** on session start, add `CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS=1` to `~/.claude/settings.json` and restart

---

## License

MIT
