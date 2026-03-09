# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/).

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
