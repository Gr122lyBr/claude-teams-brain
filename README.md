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

### New: `/brain-learn` — Zero-setup convention learning

Run one command. The brain scans your git history and **automatically learns** your project's conventions, architecture, file coupling patterns, and code hotspots. No manual `/brain-remember` needed — your repo teaches the brain.

```
> /brain-learn

Learned from Git History (187 commits)

  Conventions Added (6 new)
  - Convention: commit messages use Conventional Commits — common scopes: api, auth, db
  - Convention: branches use prefix naming (feature/, fix/, chore/)
  - Architecture: primary stack is TypeScript (Node.js)
  - Architecture: CI/CD uses GitHub Actions
  - Architecture: uses Docker for containerization
  - Convention: tests use *.test.ts naming

  Also Indexed
  - 12 file coupling patterns (searchable via /brain-search coupling)
  - 23 code hotspots (searchable via /brain-search hotspots)
```

Install the plugin on any existing repo, run `/brain-learn`, and your teammates instantly understand the project. Works on any stack, any repo size.

---

## Installation

**Requirements:** Python 3.8+, Node.js 18+, Claude Code v2.1+

> **Works on macOS, Linux, WSL2, and native Windows.** As of v1.1.0, all hooks run via Python — no bash required.

### 1. Install the plugin

In Claude Code, run:

```
/plugin marketplace add https://github.com/Gr122lyBr/claude-teams-brain
/plugin install claude-teams-brain@claude-teams-brain
```

> **If `/plugin install` fails with "Source path does not exist":** This is a known Claude Code bug — `/plugin marketplace add` registers the marketplace but doesn't clone the repo to disk. Fix it by opening a **regular terminal** (Terminal, iTerm2, PowerShell, or WSL — not inside Claude Code) and running:
>
> ```bash
> bash <(curl -fsSL https://raw.githubusercontent.com/Gr122lyBr/claude-teams-brain/master/claude-teams-brain/scripts/install.sh)
> ```
>
> Then restart Claude Code. The script clones the repo, patches `known_marketplaces.json`, and sets up the plugin cache automatically.

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

> **Solo mode:** Agent Teams is optional. If you skip this step, claude-teams-brain runs in solo mode — memory still builds from your own sessions and previous context is injected at every session start.

### 3. Allow agent tools (required for agents to write code)

When Claude spawns Agent Team teammates to build things, those agents need permission to read and write files. Without this, agents will be blocked from using Write/Edit and silently fail.

Add `allowedTools` to `~/.claude/settings.json`:

```json
{
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
  },
  "allowedTools": [
    "Read",
    "Write",
    "Edit",
    "MultiEdit",
    "Bash",
    "Glob",
    "Grep",
    "TodoWrite",
    "TodoRead",
    "WebSearch",
    "WebFetch"
  ]
}
```

> **What this does:** `allowedTools` tells Claude Code to auto-approve these tools for all agents without prompting. This is safe for your own development machine — agents only run code you instruct them to run. Without it, background agents that need to create or edit files will be denied and report permission errors.

> **Alternative (per-session):** If you prefer to approve tools interactively, run Claude with `--dangerously-skip-permissions` for sessions where you want agents to work unattended. This skips all approval prompts for that session only.

Restart Claude Code after saving `settings.json`.

---

## Quick Start

> **Solo mode works too.** claude-teams-brain builds memory from your own sessions even without Agent Teams. But multi-agent teams produce richer, role-specific memory — the options below show how to trigger them.

### Step 0 — Bootstrap the brain (optional but recommended)

On an existing repo, run `/brain-learn` to instantly bootstrap the brain from your git history. On a new project, run `/brain-seed <profile>` instead. Either way, your teammates start informed from the very first session.

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
| `/brain-learn` | **Auto-learn conventions from git history** — detects commit style, branch naming, stack, CI/CD, test patterns, file coupling, and hotspots |
| `/brain-remember <text>` | Store a rule or convention injected into all future teammates |
| `/brain-forget <text>` | Remove a manually stored memory |
| `/brain-search <query>` | Search the full brain knowledge base directly |
| `/brain-export` | Export all brain knowledge as `CONVENTIONS.md` |
| `/brain-github-export` | Export `CONVENTIONS.md` and open a GitHub PR via `gh` CLI |
| `/brain-seed <profile>` | Seed the brain with pre-built stack conventions (e.g. `nextjs-prisma`, `fastapi`, `go-microservices`, `react-native`, `python-general`) |
| `/brain-replay [run-id]` | Replay a past session as a chronological narrative — timeline, decisions, files. Defaults to latest |
| `/brain-stats` | Full stats: persistent memory + session KB |
| `/brain-status` | Memory stats for this project |
| `/brain-query <role>` | Preview the context a new teammate would receive |
| `/brain-runs` | List past Agent Team sessions |
| `/brain-clear` | Reset all memory for this project |
| `/brain-update` | Pull the latest version from GitHub |

> **Note:** If a command does not appear in your list, prefix it with the plugin name: `/claude-teams-brain:brain-update`.

### Updating the plugin

> **On version < 1.1.2?** `/brain-update` had a bug where it silently skipped updating the install path, so after restart the old version kept loading. Skip `/brain-update` and use the bootstrap script below instead.

```
/brain-update
```

If you are on an older version, or if the update fails with a "Source path does not exist" error, run the bootstrap script instead.

**Run this in your terminal** (not inside Claude Code — open a regular terminal like Terminal, iTerm2, PowerShell, or WSL):

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Gr122lyBr/claude-teams-brain/master/claude-teams-brain/scripts/install.sh)
```

This clones/pulls the latest repo, patches `known_marketplaces.json`, and re-syncs the plugin cache. Then restart Claude Code.

If you prefer the manual steps:

```
/plugin marketplace remove claude-teams-brain
/plugin marketplace add https://github.com/Gr122lyBr/claude-teams-brain
```

Then run the bootstrap script above before running `/plugin install claude-teams-brain@claude-teams-brain`.

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
      hooks.json                       ← 7 lifecycle hooks (all via Python)
    scripts/
      hook_runner.py                   ← cross-platform hook dispatcher (macOS/Linux/Windows/WSL2)
      brain_engine.py                  ← SQLite engine (pure stdlib)
      update.sh                        ← pulled by /brain-update
    profiles/                          ← stack convention profiles
      nextjs-prisma.json               ← Next.js + Prisma + TypeScript
      fastapi.json                     ← FastAPI + SQLAlchemy async
      go-microservices.json            ← Go + chi + pgx
      react-native.json                ← React Native + Expo
      python-general.json              ← Python 3.11+ modern stack
      github-actions-conventions.yml   ← GH Actions template for auto PR
    commands/                          ← /brain-* slash commands
      brain-remember, brain-forget, brain-search
      brain-export, brain-github-export, brain-seed, brain-replay
      brain-status, brain-stats, brain-query, brain-runs, brain-clear, brain-update
    skills/
      claude-teams-brain/              ← auto-activates for agent team workflows
      brain-update/                    ← /brain-update
      brain-remember/                  ← /brain-remember
      brain-forget/                    ← /brain-forget
      brain-search/                    ← /brain-search
      brain-export/                    ← /brain-export
      brain-github-export/             ← /brain-github-export
      brain-learn/                     ← /brain-learn (auto-learn from git)
      brain-seed/                      ← /brain-seed <profile>
      brain-replay/                    ← /brain-replay [run-id]
      brain-stats/                     ← /brain-stats
    settings.json                      ← Agent Teams env var + allowedTools for agents
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

- **Existing repo? Run `/brain-learn` first** — the brain scans your git history and auto-extracts conventions, architecture signals, file coupling, and hotspots. One command, zero config, instant context
- **New project? Run `/brain-seed` instead** — pick a stack profile (`nextjs-prisma`, `fastapi`, `go-microservices`, `react-native`, `python-general`) and teammates start informed from session one, no cold start
- **Use descriptive agent names** that match their role (`backend`, `database`, `security`) — the brain routes memory by role name
- **Memory compounds** — the first session is cold, but quality improves significantly from the second session onwards
- **Use `/brain-remember`** to store project-specific conventions on top of a seeded profile — teammates will receive them immediately
- **Run `/brain-query backend`** to preview exactly what context the backend agent will receive before spawning
- **Run `/brain-replay latest`** after a session to review what your AI team did — great for standups or catching up after a break
- **Run `/brain-github-export`** to open a PR with accumulated conventions — makes AI knowledge visible to your whole human team
- **Memory is relevance-ranked** — if you describe the task clearly when spawning teammates, the brain injects the most relevant past work first
- **CLAUDE.md, `.cursorrules`, and `AGENTS.md` are auto-indexed** at every session start — teammates can search them immediately without re-reading manually
- **Use `/brain-search <query>`** to verify what the brain has indexed — great for debugging or confirming memory is building
- **Use `/brain-stats`** to see a full breakdown of indexed tasks, decisions, and session KB usage
- **Solo mode works without Agent Teams** — memory still builds from your own sessions; previous context is injected at every session start automatically

---

## Troubleshooting

### "Source path does not exist" on install or reinstall

**Cause:** Claude Code's `/plugin marketplace add` registers the marketplace in `known_marketplaces.json` but does not clone the repo to disk. The installer then can't find the source files.

**Fix:** Open a **regular terminal** (Terminal, iTerm2, PowerShell, or WSL — not inside Claude Code) and run the bootstrap script:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Gr122lyBr/claude-teams-brain/master/claude-teams-brain/scripts/install.sh)
```

Then restart Claude Code. You do not need to run `/plugin install` again — the script sets up the cache directly.

### Manual workaround (no curl)

```bash
git clone https://github.com/Gr122lyBr/claude-teams-brain.git \
  ~/.claude/plugins/marketplaces/claude-teams-brain
```

Then run `/plugin install claude-teams-brain@claude-teams-brain` inside Claude Code and restart.

### Plugin not active after update

Run `/brain-update` to re-sync. If the command isn't available, use the bootstrap script above.

---

## License

MIT
