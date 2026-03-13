// eslint-disable-next-line no-control-regex
const ANSI_RE = /[\u001b\u009b][[()#;?]*(?:[0-9]{1,4}(?:;[0-9]{0,4})*)?[0-9A-ORZcf-nq-uy=><~]/g;
const CR_OVERWRITE_RE = /^.*\r(?!\n)/gm;

function stripAnsi(text) {
  return text.replace(ANSI_RE, '').replace(CR_OVERWRITE_RE, '');
}

const PROGRESS_PATTERNS = [
  /^\s*\d+%\s*[\|█▓▒░#=\->]+/,
  /^\s*[\|\/\-\\]\s*$/,
  /^\s*[⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏]/,
  /^\s*(Downloading|Fetching|Resolving|Linking|Unpacking)\b.*\.\.\./i,
  /^\s*npm\s+(WARN|notice)\b/,
];

const LOG_NORMALIZE = [
  [/^\d{4}[-/]\d{2}[-/]\d{2}[T ]\d{2}:\d{2}:\d{2}[.,]?\d*\s*/gm, ''],
  [/[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}/gi, '<UUID>'],
  [/0x[0-9a-f]+/gi, '<HEX>'],
  [/\b\d{4,}\b/g, '<NUM>'],
  [/\/[\w.\/\-]+/g, '<PATH>'],
];

const SEVERITY_KEYWORDS = {
  error: ['error', 'fatal', 'panic', 'exception'],
  warning: ['warn'],
  info: ['info'],
};

function classifySeverity(line) {
  const lower = line.toLowerCase();
  for (const [sev, keywords] of Object.entries(SEVERITY_KEYWORDS)) {
    if (keywords.some(kw => lower.includes(kw))) return sev;
  }
  return 'info';
}

function normalizeLine(line) {
  let n = line;
  for (const [re, rep] of LOG_NORMALIZE) {
    n = n.replace(re, rep);
  }
  return n.trim();
}

function truncLine(line, max = 100) {
  return line.length > max ? line.slice(0, max - 3) + '...' : line;
}

function deduplicateLogs(lines) {
  const groups = { error: new Map(), warning: new Map(), info: new Map() };
  const originals = { error: new Map(), warning: new Map(), info: new Map() };

  for (const line of lines) {
    const trimmed = line.trim();
    if (!trimmed) continue;
    const sev = classifySeverity(trimmed);
    const key = normalizeLine(trimmed);
    if (!key) continue;
    groups[sev].set(key, (groups[sev].get(key) || 0) + 1);
    if (!originals[sev].has(key)) originals[sev].set(key, trimmed);
  }

  const result = [];

  const errors = [...groups.error.entries()].sort((a, b) => b[1] - a[1]);
  if (errors.length > 0) {
    result.push(`## Errors (${errors.length} unique)`);
    for (const [key, count] of errors.slice(0, 10)) {
      const orig = truncLine(originals.error.get(key));
      result.push(count > 1 ? `  [x${count}] ${orig}` : `  ${orig}`);
    }
    if (errors.length > 10) result.push(`  ... +${errors.length - 10} more`);
  }

  const warnings = [...groups.warning.entries()].sort((a, b) => b[1] - a[1]);
  if (warnings.length > 0) {
    result.push(`## Warnings (${warnings.length} unique)`);
    for (const [key, count] of warnings.slice(0, 5)) {
      const orig = truncLine(originals.warning.get(key));
      result.push(count > 1 ? `  [x${count}] ${orig}` : `  ${orig}`);
    }
    if (warnings.length > 5) result.push(`  ... +${warnings.length - 5} more`);
  }

  if (groups.info.size > 0) {
    const totalInfo = [...groups.info.values()].reduce((a, b) => a + b, 0);
    result.push(`## Info: ${totalInfo} lines (${groups.info.size} unique)`);
  }

  return result.length > 0 ? result.join('\n') : null;
}

function deduplicateLines(lines) {
  const counts = new Map();
  const order = [];
  for (const line of lines) {
    const key = normalizeLine(line);
    if (!key) continue;
    if (counts.has(key)) {
      counts.set(key, counts.get(key) + 1);
    } else {
      counts.set(key, 1);
      order.push(line);
    }
  }
  return order.map(line => {
    const key = normalizeLine(line);
    const count = counts.get(key);
    return count > 1 ? `${truncLine(line, 100)} [x${count}]` : line;
  });
}

const ERROR_PATTERNS = [
  /^.*error[\s:\[].*/i,
  /^.*\berr\b.*/i,
  /^.*warning[\s:\[].*/i,
  /^.*\bwarn\b.*/i,
  /^.*failed.*/i,
  /^.*failure.*/i,
  /^.*exception.*/i,
  /^.*panic.*/i,
  /^error\[E\d+\]:.*/,
  /^\s*-->\s+.*:\d+:\d+/,
  /^Traceback.*/,
  /^\s*File ".*", line \d+.*/,
  /^\s*at\s+.*:\d+:\d+.*/,
  /^.*\.go:\d+:.*/,
];

function filterErrors(text) {
  const lines = text.split('\n');
  const result = [];
  let inError = false;
  let blankCount = 0;

  for (const line of lines) {
    const trimmed = line.trim();

    if (ERROR_PATTERNS.some(p => p.test(trimmed))) {
      inError = true;
      blankCount = 0;
      result.push(line);
      continue;
    }

    if (inError) {
      if (!trimmed) {
        blankCount++;
        if (blankCount >= 2) {
          inError = false;
        } else {
          result.push(line);
        }
        continue;
      }
      if (line.startsWith(' ') || line.startsWith('\t')) {
        blankCount = 0;
        result.push(line);
        continue;
      }
      inError = false;
      blankCount = 0;
    }
  }

  if (result.length === 0) {
    return lines.filter(l => l.trim()).slice(-10).join('\n');
  }

  if (result.length > 50) {
    return result.slice(0, 50).join('\n') + `\n... (${result.length - 50} more error lines)`;
  }
  return result.join('\n');
}

function parsePytest(output) {
  const lines = output.split('\n');
  const HEADER = 0, TEST_PROGRESS = 1, FAILURES = 2, SUMMARY = 3;
  let state = HEADER;
  const failureBlocks = [];
  let currentFailure = [];
  let summaryLines = [];
  let summaryResult = '';

  for (const line of lines) {
    const trimmed = line.trim();

    if (trimmed.startsWith('===') && trimmed.includes('test session starts')) {
      state = HEADER;
      continue;
    }
    if (trimmed.startsWith('===') && trimmed.includes('FAILURES')) {
      state = FAILURES;
      continue;
    }
    if (trimmed.startsWith('===') && trimmed.includes('short test summary')) {
      state = SUMMARY;
      continue;
    }
    if (trimmed.startsWith('===') && (trimmed.includes('passed') || trimmed.includes('failed'))) {
      summaryResult = trimmed.replace(/^=+\s*/, '').replace(/\s*=+$/, '');
      continue;
    }

    switch (state) {
      case HEADER:
        if (trimmed.startsWith('collected')) state = TEST_PROGRESS;
        break;
      case TEST_PROGRESS:
        break;
      case FAILURES:
        if (trimmed.startsWith('___')) {
          if (currentFailure.length > 0) failureBlocks.push(currentFailure);
          currentFailure = [trimmed.replace(/_/g, '').trim()];
        } else if (trimmed && !trimmed.startsWith('===')) {
          currentFailure.push(line);
        }
        break;
      case SUMMARY:
        if (trimmed.startsWith('FAILED') || trimmed.startsWith('ERROR')) {
          summaryLines.push(trimmed);
        }
        break;
    }
  }

  if (currentFailure.length > 0) failureBlocks.push(currentFailure);

  if (failureBlocks.length === 0) {
    return summaryResult || (summaryLines.length > 0 ? summaryLines.join('\n') : null);
  }

  const parts = [];
  if (summaryResult) parts.push(summaryResult);

  const maxFailures = 5;
  const shownFailures = failureBlocks.slice(0, maxFailures);
  for (const block of shownFailures) {
    const name = block[0];
    const relevant = block.slice(1).filter(l => {
      const t = l.trim();
      return t.startsWith('>') || t.startsWith('E ') ||
             t.includes('assert') || t.includes('error') || /\.py:\d+/.test(t);
    }).slice(0, 3).map(l => '  ' + truncLine(l.trim(), 100));

    parts.push(`FAILED ${name}`);
    parts.push(...relevant);
  }

  if (failureBlocks.length > maxFailures) {
    parts.push(`... +${failureBlocks.length - maxFailures} more failures`);
  }

  return parts.join('\n');
}

function parseJsTests(output) {
  const lines = output.split('\n');
  const failures = [];
  const summaryLines = [];
  let inFailure = false;
  let failureLines = [];

  const SUMMARY_RE = [/^Test Suites?:/, /^Tests?:\s+\d/, /^Time:/];
  const FAIL_START_RE = [/\s*[✗✘❌●]\s+/, /^\s*FAIL\s+/];
  const PASS_RE = [/\s*[✓✔✅]\s+/, /^\s*PASS\s+/];

  for (const line of lines) {
    const trimmed = line.trim();

    if (SUMMARY_RE.some(p => p.test(trimmed))) {
      if (inFailure && failureLines.length) {
        failures.push(...failureLines);
        failureLines = [];
        inFailure = false;
      }
      summaryLines.push(line);
      continue;
    }

    if (FAIL_START_RE.some(p => p.test(trimmed))) {
      if (inFailure && failureLines.length) failures.push(...failureLines);
      inFailure = true;
      failureLines = [line];
      continue;
    }

    if (inFailure) {
      if (PASS_RE.some(p => p.test(trimmed))) {
        failures.push(...failureLines);
        failureLines = [];
        inFailure = false;
      } else {
        failureLines.push(line);
      }
      continue;
    }

    if (PASS_RE.some(p => p.test(trimmed))) continue;

    if (/error|Error|ERROR|FAIL|exception/i.test(trimmed)) {
      failures.push(line);
    }
  }
  if (failureLines.length) failures.push(...failureLines);

  if (failures.length === 0) {
    return summaryLines.length > 0 ? summaryLines.join('\n') : null;
  }

  const capped = failures.slice(0, 10).map(l => truncLine(l, 120));
  if (failures.length > 10) capped.push(`... +${failures.length - 10} more failures`);

  const parts = [];
  if (summaryLines.length) parts.push(...summaryLines, '');
  parts.push('Failures:', ...capped);
  return parts.join('\n');
}

function parseCargoTest(output) {
  const lines = output.split('\n');
  const failures = [];
  let inFailureList = false;
  let summaryLine = '';

  for (const line of lines) {
    const trimmed = line.trim();

    if (trimmed.includes('test result:')) {
      summaryLine = trimmed;
      inFailureList = false;
      continue;
    }

    if (trimmed === 'failures:') {
      inFailureList = true;
      continue;
    }

    if (inFailureList) {
      if (trimmed.startsWith('----')) continue;
      if (trimmed && !trimmed.startsWith('test result')) {
        failures.push(truncLine(line, 120));
      }
      continue;
    }

    if (trimmed.includes('FAILED') && !trimmed.includes('test result')) {
      failures.push(truncLine(trimmed, 120));
    }
  }

  if (failures.length === 0) return summaryLine || null;

  const capped = failures.slice(0, 10);
  if (failures.length > 10) capped.push(`... +${failures.length - 10} more`);

  const parts = [];
  if (summaryLine) parts.push(summaryLine);
  parts.push('Failures:', ...capped);
  return parts.join('\n');
}

function parseGoTest(output) {
  const lines = output.split('\n');
  const failures = [];
  const summaryLines = [];
  let inFail = false;
  let failBlock = [];

  for (const line of lines) {
    const trimmed = line.trim();

    if (trimmed.startsWith('--- FAIL:')) {
      if (failBlock.length) failures.push(...failBlock);
      inFail = true;
      failBlock = [truncLine(trimmed, 120)];
      continue;
    }

    if (trimmed.startsWith('--- PASS:')) {
      if (inFail && failBlock.length) failures.push(...failBlock);
      inFail = false;
      failBlock = [];
      continue;
    }

    if (trimmed.startsWith('ok ') || trimmed.startsWith('FAIL\t')) {
      if (inFail && failBlock.length) failures.push(...failBlock);
      inFail = false;
      failBlock = [];
      summaryLines.push(trimmed);
      continue;
    }

    if (inFail) failBlock.push(truncLine(line, 120));
  }
  if (failBlock.length) failures.push(...failBlock);

  if (failures.length === 0) {
    return summaryLines.length > 0 ? summaryLines.join('\n') : null;
  }

  const capped = failures.slice(0, 10);
  if (failures.length > 10) capped.push(`... +${failures.length - 10} more`);

  const parts = [];
  if (summaryLines.length) parts.push(...summaryLines, '');
  parts.push('Failures:', ...capped);
  return parts.join('\n');
}

function filterTestOutput(output, framework) {
  let result;
  switch (framework) {
    case 'pytest': result = parsePytest(output); break;
    case 'js':     result = parseJsTests(output); break;
    case 'cargo':  result = parseCargoTest(output); break;
    case 'go':     result = parseGoTest(output); break;
    default:       result = null;
  }
  if (!result) result = filterErrors(output);
  return result;
}

function compactGitDiff(output) {
  const lines = output.split('\n');
  const result = [];
  let hunkLines = 0;
  const MAX_HUNK = 30;
  const MAX_TOTAL = 500;
  const fileStats = [];
  let currentFile = null;
  let adds = 0, dels = 0;

  for (const line of lines) {
    if (result.length >= MAX_TOTAL) {
      result.push('... (more changes truncated)');
      break;
    }

    if (line.startsWith('diff --git')) {
      if (currentFile) fileStats.push({ file: currentFile, adds, dels });
      const match = line.match(/b\/(.+)$/);
      currentFile = match ? match[1] : '?';
      adds = 0; dels = 0;
      hunkLines = 0;
      result.push(line);
      continue;
    }

    if (line.startsWith('@@')) {
      hunkLines = 0;
      const hunkInfo = line.match(/@@ .+ @@(.*)/);
      result.push(hunkInfo ? `@@ ${hunkInfo[0].match(/@@ .+ @@/)[0]} @@${hunkInfo[1] || ''}` : line);
      continue;
    }

    if (line.startsWith('---') || line.startsWith('+++') || line.startsWith('index ')) {
      result.push(line);
      continue;
    }

    if (line.startsWith('+') && !line.startsWith('+++')) adds++;
    if (line.startsWith('-') && !line.startsWith('---')) dels++;

    hunkLines++;
    if (hunkLines <= MAX_HUNK) {
      result.push(line);
    } else if (hunkLines === MAX_HUNK + 1) {
      result.push('  ... (hunk truncated)');
    }
  }

  if (currentFile) fileStats.push({ file: currentFile, adds, dels });
  if (fileStats.length === 0) return output;

  const totalAdds = fileStats.reduce((s, f) => s + f.adds, 0);
  const totalDels = fileStats.reduce((s, f) => s + f.dels, 0);
  const header = `${fileStats.length} file(s) changed, +${totalAdds}/-${totalDels}`;
  const perFile = fileStats.map(f => `  ${f.file} +${f.adds}/-${f.dels}`).join('\n');

  return `${header}\n${perFile}\n\n${result.join('\n')}`;
}

function filterBuildOutput(output) {
  const lines = output.split('\n');
  let errorCount = 0, warnCount = 0;
  const errorLines = [];

  for (const line of lines) {
    const lower = line.toLowerCase();
    if (lower.includes('error') && !lower.includes('0 error')) {
      errorCount++;
      if (errorLines.length < 5) errorLines.push(truncLine(line.trim(), 100));
    }
    if (lower.includes('warning') && !lower.includes('0 warning')) {
      warnCount++;
    }
  }

  if (errorCount === 0 && warnCount === 0) {
    return lines.filter(l => l.trim()).slice(-5).join('\n');
  }

  const parts = [];
  if (errorCount) parts.push(`${errorCount} error(s)`);
  if (warnCount) parts.push(`${warnCount} warning(s)`);

  const result = [parts.join(', ')];
  if (errorLines.length) {
    result.push('', ...errorLines);
    if (errorCount > 5) result.push(`... +${errorCount - 5} more errors`);
  }
  return result.join('\n');
}

const FILTERS = [
  {
    match: /^git\s+push\b/,
    matchOutput: [
      { pattern: /(?:Everything up-to-date|->)/s, extract: (out) => {
        const m = out.match(/([^\s]+)\s*->\s*([^\s]+)/);
        return m ? `ok ${m[2]}` : 'ok (pushed)';
      }},
    ],
    stripLines: [
      /^Enumerating objects:/, /^Counting objects:/, /^Compressing objects:/,
      /^Delta compression/, /^Writing objects:/, /^remote:\s*$/, /^Total \d/,
    ],
    onEmpty: 'ok (pushed)',
  },
  {
    match: /^git\s+pull\b/,
    stripLines: [
      /^remote:\s*(Enumerating|Counting|Compressing|Total)/,
      /^Unpacking objects:/,
    ],
    matchOutput: [
      { pattern: /Already up to date/i, extract: () => 'ok (up to date)' },
    ],
  },
  {
    match: /^git\s+add\b/,
    onEmpty: 'ok (staged)',
  },
  {
    match: /^git\s+commit\b/,
    matchOutput: [
      { pattern: /\[[\w\-/]+\s+[a-f0-9]+\]/s, extract: (out) => {
        const m = out.match(/\[([\w\-/]+)\s+([a-f0-9]+)\]\s*(.*)/);
        return m ? `ok [${m[1]} ${m[2]}] ${m[3]}` : out.split('\n')[0];
      }},
    ],
  },
  {
    match: /^git\s+fetch\b/,
    stripLines: [/^remote:\s*(Enumerating|Counting|Compressing|Total)/],
    onEmpty: 'ok (fetched)',
  },
  {
    match: /^git\s+checkout\b/,
    matchOutput: [
      { pattern: /Switched to/, extract: (out) => {
        const m = out.match(/Switched to (?:a new )?branch '([^']+)'/);
        return m ? `ok (switched to ${m[1]})` : out.split('\n')[0];
      }},
      { pattern: /Already on/, extract: (out) => out.split('\n')[0] },
    ],
  },
  {
    match: /^git\s+branch\b/,
    maxLines: 30,
    truncateLineAt: 80,
  },
  {
    match: /^git\s+stash\b/,
    matchOutput: [
      { pattern: /Saved working directory/, extract: (out) => out.split('\n')[0] },
      { pattern: /No local changes/, extract: () => 'ok (nothing to stash)' },
    ],
  },
  {
    match: /^git\s+merge\b/,
    maxLines: 30,
  },
  {
    match: /^git\s+rebase\b/,
    maxLines: 30,
  },
  {
    match: /^git\s+diff\b/,
    transform: (out) => compactGitDiff(out),
  },
  {
    match: /^git\s+log\b/,
    maxLines: 50,
    truncateLineAt: 120,
  },
  {
    match: /^git\s+show\b/,
    transform: (out) => compactGitDiff(out),
  },
  {
    match: /^git\s+status\b/,
    maxLines: 40,
  },
  {
    match: /^git\s+clone\b/,
    stripLines: [
      /^Cloning into/, /^remote:\s*(Enumerating|Counting|Compressing|Total)/,
      /^Receiving objects:/, /^Resolving deltas:/,
    ],
    onEmpty: 'ok (cloned)',
  },

  {
    match: /^(npm|pnpm|yarn)\s+install\b/,
    keepLines: [
      /^(added|removed|changed|updated)\s+\d+/i,
      /^npm\s+ERR!/,
      /ERR!|error|Error|ERROR/,
      /^up to date/i,
    ],
    onEmpty: 'ok (installed)',
  },
  {
    match: /^(npm|pnpm|yarn)\s+(run\s+)?build\b/,
    transform: (out) => filterBuildOutput(out),
  },
  {
    match: /^pip\s+install\b/,
    keepLines: [
      /^Successfully installed/,
      /^Requirement already satisfied/,
      /^ERROR:/, /^WARNING:/,
    ],
    onEmpty: 'ok (installed)',
  },
  {
    match: /^(pip|uv)\s+(list|freeze)\b/,
    maxLines: 50,
    truncateLineAt: 80,
  },
  {
    match: /^npm\s+list\b/,
    maxLines: 50,
    truncateLineAt: 100,
  },
  {
    match: /^(brew|apt|apt-get|dnf|yum)\s+install\b/,
    keepLines: [
      /install(ed|ing)|already|Pouring|Cellar|Setting up|Unpacking|error|ERROR|warning/i,
    ],
    maxLines: 20,
    onEmpty: 'ok (installed)',
  },

  {
    match: /\b(pytest|py\.test)\b/,
    transform: (out) => filterTestOutput(out, 'pytest'),
  },
  {
    match: /\b(jest|vitest|mocha)\b/,
    transform: (out) => filterTestOutput(out, 'js'),
  },
  {
    match: /\bcargo\s+test\b/,
    transform: (out) => filterTestOutput(out, 'cargo'),
  },
  {
    match: /\bgo\s+test\b/,
    transform: (out) => filterTestOutput(out, 'go'),
  },
  {
    match: /\bnpm\s+test\b/,
    transform: (out) => filterTestOutput(out, 'js'),
  },
  {
    match: /\bnpx\s+(jest|vitest|mocha|playwright)\b/,
    transform: (out) => filterTestOutput(out, 'js'),
  },
  {
    match: /\byarn\s+test\b/,
    transform: (out) => filterTestOutput(out, 'js'),
  },
  {
    match: /\bpnpm\s+test\b/,
    transform: (out) => filterTestOutput(out, 'js'),
  },

  {
    match: /\bcargo\s+build\b/,
    transform: (out) => filterBuildOutput(out),
  },
  {
    match: /\bcargo\s+clippy\b/,
    deduplicate: true,
    maxLines: 40,
    truncateLineAt: 150,
  },
  {
    match: /\b(tsc|npx\s+tsc)\b/,
    deduplicate: true,
    maxLines: 40,
    truncateLineAt: 150,
  },
  {
    match: /\b(gcc|g\+\+|clang|clang\+\+|cc)\b/,
    transform: (out) => filterErrors(out),
  },
  {
    match: /\bmake\b/,
    transform: (out) => filterBuildOutput(out),
  },
  {
    match: /\bcmake\b/,
    transform: (out) => filterBuildOutput(out),
  },

  {
    match: /\b(eslint|ruff|flake8|pylint|rubocop|golangci-lint|mypy|pyright|biome)\b/,
    deduplicate: true,
    maxLines: 40,
    truncateLineAt: 150,
  },
  {
    match: /\b(prettier|black|autopep8|gofmt|rustfmt)\b/,
    maxLines: 30,
    onEmpty: 'ok (formatted)',
  },

  {
    match: /^docker\s+build\b/,
    keepLines: [
      /^#\d+\s+(ERROR|\[)/,
      /^error/i,
      /^(Step|STEP)\s+\d/,
      /^Successfully (built|tagged)/i,
      /exporting to image/i,
      /WARN/i,
    ],
    maxLines: 40,
  },
  {
    match: /^docker\s+ps\b/,
    maxLines: 20,
    truncateLineAt: 120,
  },
  {
    match: /^docker\s+images?\b/,
    maxLines: 20,
    truncateLineAt: 120,
  },
  {
    match: /^docker\s+(logs|compose\s+logs)\b/,
    transform: (out) => deduplicateLogs(out.split('\n')) || out.split('\n').slice(-20).join('\n'),
  },
  {
    match: /^docker\s+compose\s+up\b/,
    keepLines: [
      /Creat(ed|ing)|Start(ed|ing)|Running|done|error|ERROR|failed|exited/i,
    ],
    maxLines: 20,
    onEmpty: 'ok (services started)',
  },
  {
    match: /^docker\s+compose\s+down\b/,
    keepLines: [/Stopped|Removed|error|ERROR/i],
    onEmpty: 'ok (services stopped)',
  },

  {
    match: /^kubectl\s+logs\b/,
    transform: (out) => deduplicateLogs(out.split('\n')) || out.split('\n').slice(-20).join('\n'),
  },
  {
    match: /^kubectl\s+(get|describe)\b/,
    maxLines: 60,
    truncateLineAt: 150,
  },
  {
    match: /^kubectl\s+apply\b/,
    keepLines: [/created|configured|unchanged|error|ERROR/i],
    onEmpty: 'ok (applied)',
  },
  {
    match: /^helm\s+(install|upgrade)\b/,
    keepLines: [/NAME:|NAMESPACE:|STATUS:|REVISION:|deployed|error|ERROR/i],
    maxLines: 20,
  },

  {
    match: /^(ls|find|tree)\b/,
    maxLines: 60,
    truncateLineAt: 120,
  },
  {
    match: /^(cat|head|tail)\b/,
    maxLines: 100,
    truncateLineAt: 200,
  },
  {
    match: /^(wc|du|df)\b/,
    maxLines: 30,
    truncateLineAt: 100,
  },
  {
    match: /^(tar|unzip|zip)\b/,
    headLines: 5,
    tailLines: 3,
    maxLines: 20,
    onEmpty: 'ok (archive operation complete)',
  },

  {
    match: /^(grep|rg|ripgrep|ag)\b/,
    deduplicate: true,
    maxLines: 50,
    truncateLineAt: 150,
  },

  {
    match: /^(curl|wget|http)\b/,
    stripLines: PROGRESS_PATTERNS,
    truncateLineAt: 200,
    maxLines: 100,
  },
  {
    match: /^(ssh|scp|rsync)\b/,
    stripLines: PROGRESS_PATTERNS,
    maxLines: 30,
  },
  {
    match: /^ping\b/,
    headLines: 2,
    tailLines: 4,
  },

  {
    match: /^ps\b/,
    maxLines: 30,
    truncateLineAt: 120,
  },
  {
    match: /^(top|htop)\b/,
    maxLines: 20,
    truncateLineAt: 100,
  },
  {
    match: /^(netstat|ss|lsof)\b/,
    maxLines: 30,
    truncateLineAt: 120,
  },

  {
    match: /^(python3?|node)\s+/,
    maxLines: 100,
    truncateLineAt: 200,
  },
];

function detectOutputType(command, output) {
  const cmd = command.toLowerCase();
  const out = output.toLowerCase();
  if (cmd.includes('test') || (out.includes('passed') && out.includes('failed'))) return 'test';
  if (cmd.includes('build') || cmd.includes('compile') || out.includes('compiling')) return 'build';
  if (out.includes('error:') || out.includes('warn:') || out.includes('[info]')) return 'log';
  const trimmed = output.trimStart();
  if (trimmed.startsWith('{') || trimmed.startsWith('[')) return 'json';
  return 'generic';
}

export function filterOutput(command, output, stderr = '') {
  if (!command) {
    return { filtered: output || '', rawLen: 0, filteredLen: 0, savings: 0, matched: null };
  }

  const rawOutput = output ?? '';
  const rawLen = rawOutput.length;
  let text;

  try {
    text = stripAnsi(rawOutput);

    const cmd = command.trim();
    const filter = FILTERS.find(f => f.match.test(cmd));

    if (!filter) {
      const generic = applyGenericFilters(cmd, text);
      return mkResult(generic, rawLen, null);
    }

    if (!text.trim() && filter.onEmpty) {
      return mkResult(filter.onEmpty, rawLen, filter.match.source);
    }

    if (filter.transform) {
      const transformed = filter.transform(text, stderr);
      return mkResult(transformed, rawLen, filter.match.source);
    }

    if (filter.replace) {
      for (const { pattern, replacement } of filter.replace) {
        text = text.replace(new RegExp(pattern, 'gm'), replacement);
      }
    }

    if (filter.matchOutput) {
      for (const { pattern, extract } of filter.matchOutput) {
        if (pattern.test(text)) {
          return mkResult(extract(text), rawLen, filter.match.source);
        }
      }
    }

    let lines = text.split('\n');

    if (filter.keepLines?.length > 0) {
      lines = lines.filter(line => filter.keepLines.some(p => p.test(line)));
    } else if (filter.stripLines?.length > 0) {
      lines = lines.filter(line => !filter.stripLines.some(p => p.test(line)));
    }

    lines = lines.filter(line => !PROGRESS_PATTERNS.some(p => p.test(line)));

    if (filter.deduplicate) {
      lines = deduplicateLines(lines);
    }

    if (filter.truncateLineAt) {
      const max = filter.truncateLineAt;
      lines = lines.map(line => line.length > max ? line.slice(0, max - 3) + '...' : line);
    }

    if (filter.headLines || filter.tailLines) {
      const head = filter.headLines ?? lines.length;
      const tail = filter.tailLines ?? 0;
      if (lines.length > head + tail) {
        const omitted = lines.length - head - tail;
        lines = [
          ...lines.slice(0, head),
          `... (${omitted} lines omitted)`,
          ...(tail > 0 ? lines.slice(-tail) : []),
        ];
      }
    }

    if (filter.maxLines && lines.length > filter.maxLines) {
      const omitted = lines.length - filter.maxLines;
      lines = [...lines.slice(0, filter.maxLines), `... (${omitted} more lines)`];
    }

    while (lines.length > 0 && !lines[lines.length - 1].trim()) lines.pop();

    let filtered = lines.join('\n').trim();
    if (!filtered && filter.onEmpty) filtered = filter.onEmpty;

    return mkResult(filtered, rawLen, filter.match.source);

  } catch (_err) {
    return mkResult(text || stripAnsi(rawOutput), rawLen, null);
  }
}

function mkResult(filtered, rawLen, matched) {
  const filteredLen = filtered.length;
  return {
    filtered,
    rawLen,
    filteredLen,
    savings: rawLen > 0 ? Math.round((1 - filteredLen / rawLen) * 100) : 0,
    matched,
  };
}

function applyGenericFilters(command, text) {
  const outputType = detectOutputType(command, text);
  let lines = text.split('\n');

  if (lines.length > 100) {
    switch (outputType) {
      case 'test': {
        const result = filterTestOutput(text, 'js');
        if (result) return result;
        break;
      }
      case 'build': return filterBuildOutput(text);
      case 'log': {
        const deduped = deduplicateLogs(lines);
        if (deduped) return deduped;
        break;
      }
    }
  }

  lines = lines.filter(line => !PROGRESS_PATTERNS.some(p => p.test(line)));

  const result = [];
  let blankRun = 0;
  for (const line of lines) {
    if (!line.trim()) {
      blankRun++;
      if (blankRun <= 1) result.push(line);
    } else {
      blankRun = 0;
      result.push(line);
    }
  }

  if (result.length > 200) {
    const omitted = result.length - 150;
    return [
      ...result.slice(0, 100),
      `\n... (${omitted} lines omitted)\n`,
      ...result.slice(-50),
    ].join('\n');
  }

  return result.map(line =>
    line.length > 500 ? line.slice(0, 497) + '...' : line
  ).join('\n');
}

export function estimateTokens(text) {
  return Math.ceil((text?.length ?? 0) / 4);
}
