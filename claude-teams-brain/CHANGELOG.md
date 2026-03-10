# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

## [1.0.2] - 2026-03-10

### Added
- `/brain-remember <text>` — manually store rules and conventions that get injected into every future teammate
- `/brain-forget <text>` — remove a manually stored memory by partial text match
- `/brain-export` — distill all accumulated brain knowledge into a committable `CONVENTIONS.md` file
- Manual memories shown as "Project Rules & Conventions" section in teammate context (before team decisions)

## [1.0.1] - 2026-03-10

### Added
- `/brain-update` skill — pull the latest version from GitHub without reinstalling
- Version check on `SessionStart` — non-intrusive hint when a new version is available
- Token-efficient tool guidance injected into every subagent on spawn (`batch_execute`, `search`, `execute`, `index`)
- Skill files for all user commands: `brain-status`, `brain-query`, `brain-runs`, `brain-clear`
- First-run welcome message on cold start (empty brain)
- `SECURITY.md` with vulnerability reporting process
- GitHub Actions CI — validates JSON, lints shell scripts, checks Python syntax, enforces version consistency

### Fixed
- `marketplace.json` source path corrected to `./claude-teams-brain`

## [1.0.0] - 2026-02-10

### Added

- Persistent memory system for Claude Code Agent Teams
- SQLite brain engine with FTS5 full-text search (`brain_engine.py`)
- 6 lifecycle hooks: SessionStart, SubagentStart, TaskCompleted, SubagentStop, TeammateIdle, SessionEnd
- Auto-injection of context from past sessions into agent conversations
- 4 user commands: `brain-status`, `brain-query`, `brain-runs`, `brain-clear`
- Semantic memory organization by topic
- Claude Code marketplace plugin integration
- Configurable settings via `settings.json`
