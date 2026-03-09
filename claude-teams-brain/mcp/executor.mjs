import { spawnSync } from 'node:child_process';
import { writeFileSync, mkdtempSync, rmSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';

const HARD_CAP = 10 * 1024 * 1024; // 10MB

function detectRuntime(language) {
  const check = (cmd) => {
    try { spawnSync(cmd, ['--version'], { timeout: 2000 }); return true; } catch { return false; }
  };
  if (language === 'shell') return check('bash') ? 'bash' : 'sh';
  if (language === 'javascript') return check('node') ? 'node' : null;
  if (language === 'python') return check('python3') ? 'python3' : check('python') ? 'python' : null;
  return null;
}

export async function runCode({ language, code, timeout = 30000 }) {
  const runtime = detectRuntime(language);
  if (!runtime) return { stdout: '', stderr: `Runtime not found for: ${language}`, exitCode: 1 };

  const tmpDir = mkdtempSync(join(tmpdir(), 'ctb-'));
  try {
    const ext = { shell: 'sh', javascript: 'mjs', python: 'py' }[language] ?? 'txt';
    const scriptPath = join(tmpDir, `script.${ext}`);
    writeFileSync(scriptPath, code, { mode: language === 'shell' ? 0o700 : 0o600 });

    const args = [scriptPath];
    const result = spawnSync(runtime, args, {
      timeout,
      maxBuffer: HARD_CAP,
      encoding: 'utf8',
      cwd: process.env.CLAUDE_PROJECT_DIR ?? process.cwd()
    });

    return {
      stdout: (result.stdout ?? '').slice(0, HARD_CAP),
      stderr: result.stderr ?? '',
      exitCode: result.status ?? 1,
      timedOut: result.signal === 'SIGTERM'
    };
  } finally {
    try { rmSync(tmpDir, { recursive: true }); } catch {}
  }
}

export function runShell(command, timeout = 60000) {
  const result = spawnSync('bash', ['-c', command], {
    timeout,
    maxBuffer: HARD_CAP,
    encoding: 'utf8',
    cwd: process.env.CLAUDE_PROJECT_DIR ?? process.cwd()
  });
  return {
    stdout: (result.stdout ?? '').slice(0, HARD_CAP),
    stderr: result.stderr ?? '',
    exitCode: result.status ?? 1
  };
}
