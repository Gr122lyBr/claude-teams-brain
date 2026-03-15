# claude-teams-brain — Full Documentation

Persistent cross-session memory + intelligent output filtering for Claude Code Agent Teams.

**Version:** 1.8.0

---

## Table of Contents

- [Installation](#installation)
- [How It Works](#how-it-works)
  - [Memory System](#memory-system)
  - [Output Filtering Pipeline](#output-filtering-pipeline)
  - [Session Warm-Up](#session-warm-up)
- [Agent Teams Best Practices](#agent-teams-best-practices)
- [What's New in v1.8](#whats-new-in-v18)
  - [Smart Command Routing](#smart-command-routing--no-more-false-blocks)
  - [Debug Mode (raw=true)](#debug-mode-rawtrue)
- [What's New in v1.5](#whats-new-in-v15)
  - [Output Filtering — 80-99% Token Reduction](#output-filtering--80-99-token-reduction)
  - [/brain-learn — Zero-Setup Convention Learning](#brain-learn--zero-setup-convention-learning)
  - [What Happens Before You Even Type](#what-happens-before-you-even-type)
- [MCP Tools](#mcp-tools)
  - [batch_execute](#batch_execute)
  - [search](#search)
  - [index](#index)
  - [execute](#execute)
  - [stats](#stats)
- [Command Reference](#command-reference)
  - [Updating the Plugin](#updating-the-plugin)
- [Project Structure](#project-structure)
- [Memory Storage](#memory-storage)
- [Tips](#tips)
- [Troubleshooting](#troubleshooting)

---

## Installation

### Option A: npx (recommended)

```bash
npx claude-teams-brain
```

### Option B: Inside Claude Code

```
/plugin marketplace add https://github.com/Gr122lyBr/claude-teams-brain
/plugin install claude-teams-brain@claude-teams-brain
```

### Option C: Bootstrap Script

If other options fail, open a **regular terminal** (not inside Claude Code) and run:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Gr122lyBr/claude-teams-brain/master/claude-teams-brain/scripts/install.sh)
```

The script will:
1. Clone the repo to `~/.claude/plugins/marketplaces/claude-teams-brain`
2. Patch `known_marketplaces.json` so the install location is correct
3. Sync the plugin into the versioned cache directory
4. Update `installed_plugins.json` with the correct version and path
5. Add MCP tool permissions to `~/.claude/settings.json`

Then restart Claude Code.

### Enable Agent Teams

Add to `~/.claude/settings.json`:

```json
{
  "env": {
    "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1"
  }
}
```

### Verify Installation

After restarting Claude Code, your first response should show:

```
🧠 claude-teams-brain active — 0 tasks · 0 decisions · 0 sessions
   KB warmed: CLAUDE.md, git-log, dir-tree
```

---

## How It Works

### Memory System

claude-teams-brain hooks into seven lifecycle events:

| Hook | What happens |
|------|-------------|
| `SessionStart` | Brain initializes; indexes CLAUDE.md, git log, directory tree, and config files; injects tool guidance for output-efficient commands |
| `SubagentStart` | Role-specific memory injected — ranked by relevance to the current task, deduplicated |
| `TaskCompleted` | Task indexed immediately; shows `🧠 Indexed: [agent] task` confirmation |
| `SubagentStop` | Rich indexing: files touched, decisions made, output summary extracted from transcript |
| `PreToolUse` | Injects context for solo-mode tasks; hard-blocks test runners, soft-tips other large-output commands with MCP suggestions |
| `TeammateIdle` | Passive checkpoint |
| `SessionEnd` | Full session compressed into a summary entry |

The `SubagentStart` hook is the core mechanism. When a teammate named `backend` spawns, the brain queries everything the backend agent has done across all past sessions — tasks completed, files owned, decisions made — ranks them by relevance to the current task description, deduplicates, and injects the result before the agent processes its first message.

### Output Filtering Pipeline

The MCP server's `batch_execute` and `execute` tools automatically filter command output through an 8-stage pipeline before returning results to Claude:

1. **ANSI stripping** — removes escape codes and carriage-return overwrites
2. **Regex replacements** — chainable substitutions
3. **Short-circuit matching** — recognizes success patterns (e.g., `git push` transfer noise → `ok main`)
4. **Line filtering** — keeps or strips lines by regex pattern per command type
5. **Line truncation** — caps individual lines at command-appropriate lengths
6. **Head/tail** — keeps first/last N lines with `... (N lines omitted)` markers
7. **Max lines** — absolute cap to prevent context flooding
8. **On-empty fallback** — returns confirmation messages like `ok (staged)` instead of empty output

Raw output is still indexed into the session knowledge base for full-text search — only the filtered version enters Claude's context window.

### Session Warm-Up

At every `SessionStart`, the brain automatically pre-indexes:

| Source | What gets indexed |
|--------|------------------|
| `CLAUDE.md` | Project instructions and conventions (if > 200 bytes) |
| `git log` | Last 20 commits |
| Directory tree | Project file structure (3 levels deep, noise excluded) |
| Config files | `package.json`, `requirements.txt`, `pyproject.toml`, `Cargo.toml`, `go.mod` |
| Convention files | `.cursorrules`, `AGENTS.md`, `CONVENTIONS.md` (if present) |

All data lives in `~/.claude-teams-brain/projects/<project-hash>/brain.db` — a local SQLite database. Nothing is sent anywhere. No external dependencies beyond Python 3.8+ stdlib.

---

## Agent Teams Best Practices

Always use agent teams for tasks that can be parallelized across concerns. Spawn specialized teammates with role-specific names rather than doing everything in a single session. Good team structures:

- **Feature work:** `backend`, `frontend`, `tests`
- **Reviews:** `security`, `performance`, `coverage`
- **Architecture:** `architect`, `devil-advocate`, `implementer`
- **Debugging:** name teammates after the hypothesis they're testing
- **Research & writing:** `researcher`, `writer`, `editor`

The claude-teams-brain plugin is active — each teammate will automatically receive memory from past sessions relevant to their role.

### Recommended CLAUDE.md additions

Add the following to your project's `CLAUDE.md` to maximize the plugin's value:

```markdown
## Agent Teams

### Memory
- Use descriptive agent names: `backend`, `frontend`, `database`, `tests`, `devops`, `security`
- Run `/brain-status` before starting a new team to review accumulated context
- Run `/brain-remember <rule>` to store conventions that all future teammates should follow
- Run `/brain-query <role>` to preview what a teammate would receive before spawning

### Context Efficiency (MCP tools)
All teammates have access to five brain MCP tools — prefer them over raw Bash:
- `batch_execute` — run multiple shell commands in one call, all output auto-indexed
- `search` — query indexed output without re-running commands
- `index` — save findings for teammates to access
- `execute(intent=...)` — run code; auto-indexes large output when intent is set
- `execute(raw=true)` — full raw output for debugging (no indexing)
- `stats` — check context savings at end of investigation

Standard workflow: `batch_execute` → `search` → `index`

### Decision Logging
The brain auto-captures decisions from agent transcripts. Help it by writing decisions clearly:
- "Decided to use X because Y"
- "Convention: always use Z"
- "Switched to X instead of Y"
- "Approach: ..."
```

---

## What's New in v1.8

### Smart Command Routing — No More False Blocks

Previously, the PreToolUse hook **hard-blocked** many common commands (`git diff`, `git log`, `docker ps`, `docker logs`, `grep`, `cat`, etc.), forcing agents to use MCP tools for everything. This caused agents to get stuck in loops when they needed output for debugging.

**v1.8 replaces aggressive blocking with a 4-tier system:**

| Tier | Action | Commands |
|------|--------|----------|
| **Safe** | Allow silently | `git status`, `git add`, `git commit`, `ls`, `mkdir`, `pip install`, etc. |
| **Hard block** | Exit 2, redirect to MCP | Test runners only: `npm test`, `pytest`, `jest`, `cargo test`, `go test` |
| **Soft tip** | Allow + inject suggestion | `git log`, `git diff`, `docker ps`, `docker logs`, `grep`, `cat`, `kubectl`, etc. |
| **Unknown** | Allow + gentle reminder | Everything else |

**What changed:**
- `git diff`, `git log`, `docker ps`, `docker logs`, `grep`, `cat`, `head`, `tail`, `kubectl` — all **allowed now** with a helpful tip suggesting MCP alternatives for token efficiency
- Only test runners (which produce megabytes of output) are still hard-blocked
- Tip messages teach agents about `execute(raw=true)` for debugging

### Debug Mode (raw=true)

The `execute` tool now supports a `raw` parameter for debugging scenarios:

```json
{
  "language": "shell",
  "code": "docker logs myapp --tail 200 2>&1",
  "raw": true
}
```

When `raw=true`, the full command output is returned directly (up to 120KB) without indexing or filtering. Use this when you need complete output for troubleshooting.

**Three execute modes:**

| Mode | When to use | Example |
|------|-------------|---------|
| **Default** | Small output, direct results | `execute(language="shell", code="git status")` |
| **intent** | Large output, token-efficient | `execute(language="shell", code="npm test", intent="failing tests")` |
| **raw** | Debugging, need full output | `execute(language="shell", code="docker logs app", raw=true)` |

---

## What's New in v1.5

### Output Filtering — 80-99% Token Reduction

Every command that runs through the brain's MCP tools is now filtered through an intelligent, command-aware pipeline before entering Claude's context window. The filters understand the structure of each command's output and strip noise while preserving signal.

**Filtering results by command:**

| Command | Raw Output | After Filtering | Savings |
|---------|-----------|----------------|---------|
| `git push` | Transfer stats, compression details, delta info | `ok main` | **98%** |
| `git add .` | (empty) | `ok (staged)` | **100%** |
| `npm install` | Warnings, notices, download bars, funding info | `added 542 packages in 12s` | **90%+** |
| `pytest` (all pass) | Session header, dots, collection info, timing | `15 passed in 2.34s` | **82%** |
| `pytest` (failures) | Full output including all passing tests | Summary + only failing tests with relevant assertion lines | **70%+** |
| `docker build` | Layer downloads, cache hits, SHA hashes | Build steps + errors only | **85%+** |
| `git diff` (large) | Full unified diff | File summary + per-hunk limits (30 lines max) | **60-90%** |
| `kubectl logs` | Thousands of repetitive log lines | Deduplicated by severity, top 10 errors with `[x5]` counts | **80%+** |
| `cargo build` | Compiling lines for every dependency | Error/warning summary with counts | **90%+** |

**60+ commands supported** across: git, npm/pnpm/yarn, pip/uv, pytest/jest/vitest/mocha, cargo, go test, docker, kubectl, helm, gcc/clang, eslint/ruff/pylint, make/cmake, grep/rg, curl/wget, brew/apt, and more.

**Specialized parsers:**

- **Pytest** — state machine parser that tracks header → progress → failures → summary, shows up to 5 failures with only the relevant assertion lines
- **Jest/Vitest/Mocha** — structured failure extraction with summary preservation
- **Cargo test / Go test** — framework-specific failure block extraction
- **Build tools** — error/warning counting with top-5 error display
- **Log dedup** — normalizes timestamps, UUIDs, hex values, paths, and numbers before deduplicating; groups by severity (error/warning/info)
- **Git diff** — compacts diffs with per-file stats, 30-line hunk limits, and a summary header

Every filter degrades gracefully — if anything goes wrong, you get the raw output back. No data is ever lost.

### /brain-learn — Zero-Setup Convention Learning

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

### What Happens Before You Even Type

Every time you open a session, the brain silently does all of this **before your first message**:

1. **Indexes your CLAUDE.md** — so Claude actually knows your project rules
2. **Reads your last 20 git commits** — Claude understands what changed recently
3. **Maps your directory tree** — Claude knows where everything lives
4. **Indexes package.json / requirements.txt / go.mod** — Claude knows your stack
5. **Loads .cursorrules, AGENTS.md, CONVENTIONS.md** — if they exist, they're searchable
6. **Auto-detects your stack** — seeds best-practice conventions on first run
7. **Loads all past decisions** — every architectural choice from previous sessions
8. **Checks for updates** — tells you if a new version is available

Without this plugin, Claude starts every session **completely blank**. With it, Claude already knows your project, your stack, your conventions, and what happened last session — all before you type a single word.

Claude confirms everything is ready in its **first response**:

```
🧠 claude-teams-brain active — 25 tasks · 17 decisions · 16 sessions
   KB warmed: CLAUDE.md, git-log, dir-tree, package.json
```

> **Note:** The status appears when Claude responds to your first message. This is a Claude Code limitation — hooks can't display output before the conversation starts. The brain is already warmed up and working by the time you see this.

---

## MCP Tools

claude-teams-brain includes an MCP server that exposes five tools to Claude and all subagents. These tools keep large command output out of context windows by filtering it through command-aware pipelines and indexing results into a searchable session knowledge base.

> **Token savings in practice:** running `npm test` or `git log` via `batch_execute` typically returns 200-500 tokens of targeted results instead of 5,000-20,000 tokens of raw output — a **90-97% reduction** per call. The output filtering adds another layer on top, stripping noise before indexing. Use `stats` at the end of a session to see your actual savings.

### batch_execute

Run multiple shell commands, auto-filter and index all output, and search with queries in a single call. Identical commands within the same session are served from a **60-second cache** — no redundant process spawns, no duplicate context.

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

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `commands` | array | Yes | Array of objects with `label` (string) and `command` (string) |
| `queries` | array | No | Search queries to run against indexed output |
| `timeout` | number | No | Timeout in milliseconds (default: 60000) |

### search

Search the session knowledge base built by previous `batch_execute` or `index` calls.

```json
{
  "queries": ["authentication middleware", "error handling patterns"],
  "limit": 3
}
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `queries` | array | Yes | Search queries to run against the KB |
| `limit` | number | No | Maximum results per query (default: 3) |

### index

Manually index content (findings, analysis, data) for later retrieval by yourself or teammates.

```json
{
  "content": "The auth module uses RS256 JWT tokens with 15-minute expiry...",
  "source": "auth-analysis"
}
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `content` | string | Yes | The content to index |
| `source` | string | Yes | Label identifying the source of this content |

### execute

Run code in a sandboxed subprocess. Supports three modes: default (direct output), intent-based (auto-index large output), and raw (full debug output).

```json
{
  "language": "shell",
  "code": "docker logs myapp --tail 200 2>&1",
  "raw": true
}
```

```json
{
  "language": "python",
  "code": "import ast; print(ast.dump(ast.parse(open('main.py').read())))",
  "intent": "find all class definitions"
}
```

**Parameters:**

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `language` | string | Yes | One of: `shell`, `javascript`, `python` |
| `code` | string | Yes | Code or shell command to execute |
| `timeout` | number | No | Timeout in milliseconds (default: 30000) |
| `intent` | string | No | If set and output > 5KB, auto-indexes and returns search results instead of raw output (token-efficient mode) |
| `raw` | boolean | No | If true, returns full raw output without indexing (up to 120KB). Use for debugging when you need complete command output (default: false) |

### stats

Show session context savings metrics including output filter performance.

```json
{}
```

Returns bytes indexed vs bytes returned, call counts, cache hits, context savings ratio, and output filter stats (commands filtered, reduction percentage, estimated tokens saved).

---

## Command Reference

All commands are available as `/brain-*` slash commands in Claude Code.

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
| `/brain-stats` | Full stats: persistent memory + session KB + output filter savings |
| `/brain-status` | Memory stats for this project |
| `/brain-query <role>` | Preview the context a new teammate would receive |
| `/brain-runs` | List past Agent Team sessions |
| `/brain-clear` | Reset all memory for this project |
| `/brain-update` | Pull the latest version from GitHub |

> **Note:** If a command does not appear in your list, prefix it with the plugin name: `/claude-teams-brain:brain-update`.

### Available Stack Profiles

Loadable via `/brain-seed <name>`:

| Profile | Stack |
|---------|-------|
| `nextjs-prisma` | Next.js 14, Prisma, TypeScript, Tailwind, shadcn/ui |
| `fastapi` | FastAPI, SQLAlchemy async, Pydantic |
| `go-microservices` | Go, chi, pgx, Docker, Kubernetes |
| `react-native` | React Native, Expo, TypeScript |
| `python-general` | Python 3.11+, modern best practices |

### Updating the Plugin

**Recommended:** Run inside Claude Code:

```
/brain-update
```

This pulls the latest from GitHub, syncs to the plugin cache, and reports what changed.

**If `/brain-update` fails**, use the bootstrap script in a regular terminal:

```bash
bash <(curl -fsSL https://raw.githubusercontent.com/Gr122lyBr/claude-teams-brain/master/claude-teams-brain/scripts/install.sh)
```

Then restart Claude Code.

**Manual alternative:**

```
/plugin marketplace remove claude-teams-brain
/plugin marketplace add https://github.com/Gr122lyBr/claude-teams-brain
/plugin install claude-teams-brain@claude-teams-brain
```

---

## Project Structure

```
claude-teams-brain/                    <- repo root (marketplace)
  .claude-plugin/
    marketplace.json
  claude-teams-brain/                  <- the plugin
    .claude-plugin/
      plugin.json
    hooks/
      hooks.json                       <- 7 lifecycle hooks (all via Python)
    mcp/
      server.mjs                       <- MCP server with 5 tools
      executor.mjs                     <- sandboxed code execution
      output_filter.mjs                <- command-aware output filtering (60+ commands)
    scripts/
      hook_runner.py                   <- cross-platform hook dispatcher
      brain_engine.py                  <- SQLite engine (pure stdlib)
      update.sh                        <- pulled by /brain-update
    profiles/                          <- stack convention profiles
      nextjs-prisma.json               <- Next.js + Prisma + TypeScript
      fastapi.json                     <- FastAPI + SQLAlchemy async
      go-microservices.json            <- Go + chi + pgx
      react-native.json                <- React Native + Expo
      python-general.json              <- Python 3.11+ modern stack
    commands/                          <- /brain-* slash commands
    skills/                            <- skill definitions
    settings.json                      <- Agent Teams env config
```

---

## Memory Storage

```
~/.claude-teams-brain/
  └── projects/
      └── <project-hash>/
          └── brain.db    <- SQLite, one file per project
```

Each project has its own isolated brain. Memory never crosses project boundaries. The SQLite file is fully inspectable with any database viewer.

The project hash is `SHA256(resolved_project_path)[:12]`, ensuring each project gets its own database.

### SQLite Schema

The `brain.db` database contains these tables:

| Table | Purpose |
|-------|---------|
| `meta` | Version, last_activity timestamps |
| `runs` | Session records (started_at, ended_at, summary) |
| `tasks` | Indexed tasks (agent_role, files_touched, decisions, output_summary) |
| `decisions` | Architectural decisions (decision, rationale, tags, agent_name) |
| `file_index` | File ownership tracking (file_path, operation, agent_name) |
| `kb_chunks` | Session KB content (source, title, content, indexed_at) |
| `kb_fts` | FTS5 full-text search virtual table (Porter stemmer) |
| `tasks_fts` | FTS5 task search index |

---

## Tips

- **Existing repo? Run `/brain-learn` first** — the brain scans your git history and auto-extracts conventions, architecture signals, file coupling, and hotspots. One command, zero config, instant context
- **New project? Run `/brain-seed` instead** — pick a stack profile (`nextjs-prisma`, `fastapi`, `go-microservices`, `react-native`, `python-general`) and teammates start informed from session one
- **Use descriptive agent names** that match their role (`backend`, `database`, `security`) — the brain routes memory by role name
- **Memory compounds** — the first session is cold, but quality improves significantly from the second session onwards
- **Use `/brain-remember`** to store project-specific conventions — teammates will receive them immediately
- **Run `/brain-query backend`** to preview exactly what context the backend agent will receive before spawning
- **Run `/brain-replay latest`** after a session to review what your AI team did — great for standups or catching up after a break
- **Run `/brain-github-export`** to open a PR with accumulated conventions — makes AI knowledge visible to your whole human team
- **CLAUDE.md, `.cursorrules`, and `AGENTS.md` are auto-indexed** at every session start — teammates can search them immediately
- **Use `stats` tool** to see output filter savings at the end of a session — track how many tokens the filters saved
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

### Version mismatch after update

If the plugin loads from an old cache directory after updating, check that the version in both `claude-teams-brain/package.json` and `claude-teams-brain/.claude-plugin/plugin.json` are in sync. Claude Code uses `plugin.json` to resolve the cache directory path. If these are out of sync, the old version keeps loading even after a successful update.

---

## Requirements

- **Claude Code** v2.1+ (Agent Teams feature)
- **Python** 3.8+ (stdlib only, no pip installs)
- **Node.js** 18+
- **Platforms:** macOS, Linux, WSL2, native Windows

---

## License

MIT
