#!/usr/bin/env python3
"""
Tests for hook_runner.py — lifecycle hooks and MCP tool routing.

Uses only Python stdlib (unittest). No external dependencies required.
Run: python3 -m pytest tests/ OR python3 tests/test_hook_runner.py
"""

import sys
import os
import unittest

# Add scripts dir to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))
import hook_runner


class TestCommandRouting(unittest.TestCase):
    """Test the 3-tier command classification (safe / block / tip)."""

    def _is_safe(self, cmd):
        """Check if a command matches the safe list."""
        cmd_lower = cmd.lower()
        return any(cmd_lower.startswith(s) or s in cmd_lower for s in hook_runner._SAFE_CMDS)

    def _is_blocked(self, cmd):
        """Check if a command matches the block list (primary command only, before pipes)."""
        cmd_lower = cmd.lower()
        primary = cmd_lower.split("|")[0].strip() if "|" in cmd_lower else cmd_lower
        return any(p in primary for p in hook_runner._BLOCK_CMDS)

    # ── Safe commands (Tier 1) ──

    def test_safe_git_status(self):
        self.assertTrue(self._is_safe("git status"))

    def test_safe_git_add(self):
        self.assertTrue(self._is_safe("git add ."))

    def test_safe_git_commit(self):
        self.assertTrue(self._is_safe("git commit -m 'test'"))

    def test_safe_git_push(self):
        self.assertTrue(self._is_safe("git push origin main"))

    def test_safe_mkdir(self):
        self.assertTrue(self._is_safe("mkdir -p tests/"))

    def test_safe_ls(self):
        self.assertTrue(self._is_safe("ls -la"))

    def test_safe_pip_install(self):
        self.assertTrue(self._is_safe("pip install requests"))

    def test_safe_npm_install(self):
        self.assertTrue(self._is_safe("npm install express"))

    def test_safe_pwd(self):
        self.assertTrue(self._is_safe("pwd"))

    def test_safe_py_compile(self):
        """python3 -c 'import py_compile; ...' should be safe."""
        self.assertTrue(self._is_safe('python3 -c "import py_compile; py_compile.compile(\'test.py\')"'))

    # ── Blocked commands (Tier 2) ──

    def test_block_npm_test(self):
        self.assertTrue(self._is_blocked("npm test"))

    def test_block_pytest(self):
        self.assertTrue(self._is_blocked("pytest -v tests/"))

    def test_block_jest(self):
        self.assertTrue(self._is_blocked("jest --coverage"))

    def test_block_grep(self):
        self.assertTrue(self._is_blocked("grep -r 'pattern' src/"))

    def test_block_rg(self):
        self.assertTrue(self._is_blocked("rg 'pattern' src/"))

    def test_block_find(self):
        self.assertTrue(self._is_blocked("find . -name '*.py'"))

    def test_block_cat(self):
        self.assertTrue(self._is_blocked("cat src/main.py"))

    def test_block_head(self):
        self.assertTrue(self._is_blocked("head -n 100 file.txt"))

    def test_block_tail(self):
        self.assertTrue(self._is_blocked("tail -f log.txt"))

    def test_block_git_log(self):
        self.assertTrue(self._is_blocked("git log --oneline"))

    def test_block_git_diff(self):
        self.assertTrue(self._is_blocked("git diff HEAD~3"))

    def test_block_git_show(self):
        self.assertTrue(self._is_blocked("git show HEAD"))

    def test_block_git_blame(self):
        self.assertTrue(self._is_blocked("git blame src/main.py"))

    def test_block_docker_logs(self):
        self.assertTrue(self._is_blocked("docker logs container_id"))

    def test_block_kubectl_get(self):
        self.assertTrue(self._is_blocked("kubectl get pods"))

    def test_block_pip_list(self):
        self.assertTrue(self._is_blocked("pip list"))

    def test_block_npm_list(self):
        self.assertTrue(self._is_blocked("npm list"))

    def test_block_cargo_test(self):
        self.assertTrue(self._is_blocked("cargo test"))

    def test_block_go_test(self):
        self.assertTrue(self._is_blocked("go test ./..."))

    # ── Pipe safety: blocked patterns in pipe segments should NOT block ──

    def test_pipe_grep_not_blocked(self):
        """grep in a pipe segment should not block the command."""
        self.assertFalse(self._is_blocked("docker compose build 2>&1 | grep error"))

    def test_pipe_tail_not_blocked(self):
        """tail in a pipe segment should not block the command."""
        self.assertFalse(self._is_blocked("docker compose build 2>&1 | tail -20"))

    def test_pipe_head_not_blocked(self):
        """head in a pipe segment should not block the command."""
        self.assertFalse(self._is_blocked("npm run build 2>&1 | head -50"))

    def test_pipe_rg_not_blocked(self):
        """rg in a pipe segment should not block the command."""
        self.assertFalse(self._is_blocked("docker compose up 2>&1 | rg error"))

    def test_pipe_cat_not_blocked(self):
        """cat in a pipe segment should not block when primary is safe."""
        self.assertFalse(self._is_blocked("docker compose build 2>&1 | cat -n"))

    def test_pipe_chain_not_blocked(self):
        """Multi-pipe chain with head + grep should not block."""
        self.assertFalse(self._is_blocked("docker compose build 2>&1 | head -50 | grep error"))

    def test_pipe_primary_still_blocked(self):
        """Primary command should still be blocked even with pipes."""
        self.assertTrue(self._is_blocked("git log --oneline | head -20"))

    def test_pipe_primary_pytest_still_blocked(self):
        """pytest as primary should still be blocked even with pipe."""
        self.assertTrue(self._is_blocked("pytest -v | grep FAILED"))

    # ── Tier 3: commands that are neither safe nor blocked ──

    def test_tier3_python_script(self):
        """General python3 commands should be tier 3 (tip, not blocked)."""
        cmd = "python3 script.py"
        self.assertFalse(self._is_safe(cmd))
        self.assertFalse(self._is_blocked(cmd))

    def test_tier3_node_script(self):
        cmd = "node server.js"
        self.assertFalse(self._is_safe(cmd))
        self.assertFalse(self._is_blocked(cmd))

    def test_tier3_curl(self):
        cmd = "curl https://api.example.com"
        self.assertFalse(self._is_safe(cmd))
        self.assertFalse(self._is_blocked(cmd))

    # ── Edge cases: safe should take priority when both match ──

    def test_safe_overrides_block_for_py_compile(self):
        """py_compile check should be safe even though it runs python3."""
        cmd = 'python3 -c "import py_compile; py_compile.compile(\'test.py\')"'
        self.assertTrue(self._is_safe(cmd))

    # ── Redirect messages ──

    def test_redirect_message_grep(self):
        """Grep commands should get specific Grep tool redirect."""
        for key, msg in hook_runner._REDIRECT_MSG.items():
            if 'grep' in key.lower() or key == 'rg ':
                self.assertIn('Grep', msg)
                break

    def test_redirect_message_cat(self):
        """Cat commands should get specific Read tool redirect."""
        msg = hook_runner._REDIRECT_MSG.get('cat ', '')
        self.assertIn('Read', msg)

    def test_redirect_message_find(self):
        """Find commands should get specific Glob tool redirect."""
        msg = hook_runner._REDIRECT_MSG.get('find ', '')
        self.assertIn('Glob', msg)


class TestInferRole(unittest.TestCase):
    """Test role inference from task descriptions."""

    def test_explicit_role_preserved(self):
        """Non-generic roles should be returned as-is."""
        self.assertEqual(hook_runner.infer_role("backend", "do something"), "backend")

    def test_generic_role_inferred(self):
        """Generic role should be inferred from task description."""
        result = hook_runner.infer_role("general", "write unit tests for the API")
        self.assertIn(result, ['tests', 'backend'])  # Either is valid

    def test_frontend_inference(self):
        result = hook_runner.infer_role("general", "fix the React component styling with CSS")
        self.assertEqual(result, "frontend")

    def test_database_inference(self):
        result = hook_runner.infer_role("general", "write SQL migration for the schema")
        self.assertEqual(result, "database")

    def test_devops_inference(self):
        result = hook_runner.infer_role("general", "set up Docker and Kubernetes deployment")
        self.assertEqual(result, "devops")

    def test_security_inference(self):
        result = hook_runner.infer_role("general", "implement JWT auth with OAuth")
        self.assertEqual(result, "security")

    def test_empty_desc_returns_generic(self):
        """Empty description with generic role should return 'general'."""
        result = hook_runner.infer_role("general", "")
        self.assertEqual(result, "general")


class TestExtractDecisions(unittest.TestCase):
    """Test extract_decisions_from_text pattern matching."""

    def test_decided_to(self):
        decisions = hook_runner.extract_decisions_from_text("We decided to use PostgreSQL for the database.")
        self.assertTrue(any("PostgreSQL" in d for d in decisions))

    def test_convention(self):
        decisions = hook_runner.extract_decisions_from_text("Convention: always use camelCase for variables.")
        self.assertTrue(any("camelCase" in d for d in decisions))

    def test_switched_to(self):
        decisions = hook_runner.extract_decisions_from_text("Switched to using Prisma instead of raw SQL.")
        self.assertTrue(any("Prisma" in d for d in decisions))

    def test_no_decisions(self):
        decisions = hook_runner.extract_decisions_from_text("Just a regular sentence with nothing special.")
        self.assertEqual(len(decisions), 0)

    def test_empty_text(self):
        decisions = hook_runner.extract_decisions_from_text("")
        self.assertEqual(len(decisions), 0)

    def test_max_chars_limit(self):
        """Very long decision text should be truncated."""
        long_text = "Decided to " + "x" * 1000 + " end."
        decisions = hook_runner.extract_decisions_from_text(long_text, max_chars=100)
        if decisions:
            for d in decisions:
                self.assertLessEqual(len(d), 110)  # some tolerance


class TestDetectStack(unittest.TestCase):
    """Test stack detection from project files."""

    def test_returns_string(self):
        """Should always return a string, even for unknown projects."""
        result = hook_runner.detect_stack("/nonexistent/path")
        self.assertIsInstance(result, str)


class TestToolGuidance(unittest.TestCase):
    """Test that TOOL_GUIDANCE contains the right directives."""

    def test_contains_must(self):
        """Guidance should use mandatory language."""
        self.assertIn("MUST", hook_runner.TOOL_GUIDANCE)

    def test_contains_blocked_warning(self):
        """Guidance should warn about automatic blocking."""
        self.assertIn("blocked", hook_runner.TOOL_GUIDANCE.lower())

    def test_mentions_all_tools(self):
        """Guidance should mention all 5 MCP tools."""
        for tool in ['batch_execute', 'execute', 'search', 'index', 'stats']:
            self.assertIn(tool, hook_runner.TOOL_GUIDANCE)


class TestHooksJsonConsistency(unittest.TestCase):
    """Verify hooks.json matches the registered handlers."""

    def test_all_handlers_in_hooks_json(self):
        """Every pretooluse handler should have a matching hooks.json entry."""
        import json
        hooks_path = os.path.join(os.path.dirname(__file__), '..', 'hooks', 'hooks.json')
        with open(hooks_path) as f:
            config = json.load(f)

        pretooluse_matchers = {
            entry['matcher']
            for entry in config['hooks'].get('PreToolUse', [])
        }
        # Verify our expected matchers are present
        self.assertIn('Bash', pretooluse_matchers)
        self.assertIn('Read', pretooluse_matchers)
        self.assertIn('Grep', pretooluse_matchers)
        self.assertIn('Task', pretooluse_matchers)

    def test_handler_map_complete(self):
        """HANDLERS dict should include all pretooluse handlers."""
        self.assertIn('pretooluse-bash', hook_runner.HANDLERS)
        self.assertIn('pretooluse-read', hook_runner.HANDLERS)
        self.assertIn('pretooluse-grep', hook_runner.HANDLERS)
        self.assertIn('pretooluse-task', hook_runner.HANDLERS)


if __name__ == '__main__':
    unittest.main()
