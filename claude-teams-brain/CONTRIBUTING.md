# Contributing to Claude Teams Brain

Thank you for your interest in contributing. This guide covers how to get involved.

## Bug Reports

Open an issue with:

- A clear, descriptive title
- Steps to reproduce the problem
- Expected vs actual behavior
- Your environment (OS, shell, Claude Code version)

## Feature Requests

Open an issue describing:

- The problem your feature would solve
- Your proposed solution
- Any alternatives you considered

## Pull Requests

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/your-feature`)
3. Make your changes
4. Commit with a clear message (see Commit Messages below)
5. Push to your fork and open a pull request

Keep PRs focused on a single change. Include a description of what changed and why.

## Code Style

- **Python**: Follow PEP 8. Run a linter before submitting.
- **Shell scripts**: Write shellcheck-compatible scripts. Use `set -euo pipefail` where appropriate.

## Development Setup

1. Clone the repo and install the plugin locally:
   ```bash
   git clone https://github.com/Gr122lyBr/claude-teams-brain
   # In Claude Code:
   /plugin marketplace add /path/to/clone
   /plugin install claude-teams-brain@claude-teams-brain
   ```
2. Make changes to scripts or the MCP server, then reload Claude Code.
3. Inspect the brain database at any time:
   ```bash
   sqlite3 ~/.claude-teams-brain/projects/<hash>/brain.db ".tables"
   ```
4. Test the brain engine directly:
   ```bash
   python3 scripts/brain_engine.py status /your/project/path
   python3 scripts/brain_engine.py query-role backend /your/project/path
   ```

**Requirements:** Python 3.8+, Node.js 18+, Claude Code v2.1+

## Testing

The project does not yet have an automated test suite. When adding new functionality, manually verify using the steps above and check brain output with `/claude-teams-brain:brain-status`.

## Commit Messages

Use the imperative mood in the subject line (e.g., "Add feature" not "Added feature"). Keep the subject under 72 characters. Use the body to explain what and why, not how.
