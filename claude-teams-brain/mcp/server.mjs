import { spawnSync } from 'node:child_process';
import { writeFileSync, mkdtempSync, rmSync } from 'node:fs';
import { join } from 'node:path';
import { tmpdir } from 'node:os';
import { runCode, runShell } from './executor.mjs';
import { filterOutput, estimateTokens } from './output_filter.mjs';

const ENGINE = join(process.env.CLAUDE_PLUGIN_ROOT ?? '', 'scripts', 'brain_engine.py');
const PROJECT_DIR = process.env.CLAUDE_PROJECT_DIR ?? process.cwd();
const PYTHON = (() => {
  for (const p of ['python3', 'python']) {
    try { spawnSync(p, ['--version'], { timeout: 2000 }); return p; } catch {}
  }
  return 'python3';
})();

const sessionStats = {
  start: Date.now(),
  calls: {},
  bytesReturned: 0,
  bytesIndexed: 0,
  cacheHits: 0,
  filterStats: { rawBytes: 0, filteredBytes: 0, commandsFiltered: 0 },
};

// In-memory command cache with 60s TTL to avoid re-running identical commands
const commandCache = new Map();
const CACHE_TTL_MS = 60_000;

function runCached(command, timeout) {
  const now = Date.now();
  const cacheKey = `${command}::${timeout}`;
  const cached = commandCache.get(cacheKey);
  if (cached && (now - cached.ts) < CACHE_TTL_MS) {
    sessionStats.cacheHits += 1;
    return { ...cached.result, fromCache: true };
  }
  const result = runShell(command, timeout);

  // Apply RTK-style output filtering
  if (result.stdout) {
    const f = filterOutput(command, result.stdout, result.stderr);
    result.rawStdout = result.stdout;
    result.stdout = f.filtered;
    result.filterSavings = f.savings;
    result.filterMatched = f.matched;
    sessionStats.filterStats.rawBytes += f.rawLen;
    sessionStats.filterStats.filteredBytes += f.filteredLen;
    if (f.savings > 0) sessionStats.filterStats.commandsFiltered++;
  }

  commandCache.set(cacheKey, { result, ts: now });
  return result;
}

function track(toolName, bytes) {
  sessionStats.calls[toolName] = (sessionStats.calls[toolName] ?? 0) + 1;
  sessionStats.bytesReturned += bytes;
}

function runEngine(...args) {
  const r = spawnSync(PYTHON, [ENGINE, ...args], {
    timeout: 15000, encoding: 'utf8',
    env: { ...process.env, CLAUDE_PROJECT_DIR: PROJECT_DIR }
  });
  return r.stdout?.trim() ?? '';
}

function indexContent(content, source) {
  const tmpDir = mkdtempSync(join(tmpdir(), 'ctb-kb-'));
  const contentFile = join(tmpDir, 'content.txt');
  try {
    writeFileSync(contentFile, content, 'utf8');
    const out = runEngine('kb-index', PROJECT_DIR, source, contentFile);
    sessionStats.bytesIndexed += content.length;
    return JSON.parse(out || '{}');
  } finally {
    try { rmSync(tmpDir, { recursive: true }); } catch {}
  }
}

function searchKB(query, limit = 3) {
  const out = runEngine('kb-search', PROJECT_DIR, query, String(limit));
  try { return JSON.parse(out || '[]'); } catch { return []; }
}

function formatSearchResults(allResults) {
  if (!allResults.length) return '(no results found)';
  const seen = new Set();
  const parts = [];
  for (const r of allResults) {
    const key = (r.source ?? '') + '::' + (r.title ?? '') + '::' + (r.snippet ?? '').slice(0, 200);
    if (seen.has(key)) continue;
    seen.add(key);
    parts.push(`### ${r.title}\n_Source: ${r.source}_\n${r.snippet}`);
  }
  return parts.join('\n\n');
}

// --- Tool Definitions ---
const TOOLS = [
  {
    name: 'batch_execute',
    description: 'Run multiple shell commands, auto-index all output, search with queries. ONE call replaces many Bash calls. Use this instead of running Bash commands directly.',
    inputSchema: {
      type: 'object',
      properties: {
        commands: {
          type: 'array',
          items: { type: 'object', properties: { label: { type: 'string' }, command: { type: 'string' } }, required: ['label', 'command'] },
          description: 'List of labeled shell commands to run'
        },
        queries: {
          type: 'array', items: { type: 'string' },
          description: 'Search queries to run against the indexed output'
        },
        timeout: { type: 'number', default: 60000, description: 'Timeout per command in ms' }
      },
      required: ['commands', 'queries']
    }
  },
  {
    name: 'search',
    description: 'Search the session knowledge base. Use after batch_execute to find more details.',
    inputSchema: {
      type: 'object',
      properties: {
        queries: { type: 'array', items: { type: 'string' } },
        limit: { type: 'number', default: 3 }
      },
      required: ['queries']
    }
  },
  {
    name: 'index',
    description: 'Index content (findings, data, analysis) into the session knowledge base for later retrieval.',
    inputSchema: {
      type: 'object',
      properties: {
        content: { type: 'string', description: 'Content to index' },
        source: { type: 'string', description: 'Label for this content' }
      },
      required: ['content', 'source']
    }
  },
  {
    name: 'execute',
    description: 'Run code in a sandboxed subprocess. Output stays out of context unless returned. Use intent to auto-filter large output.',
    inputSchema: {
      type: 'object',
      properties: {
        language: { type: 'string', enum: ['shell', 'javascript', 'python'], description: 'Language to run' },
        code: { type: 'string', description: 'Code to execute' },
        timeout: { type: 'number', default: 30000 },
        intent: { type: 'string', description: 'If set and output > 5KB, auto-index and search by this intent' }
      },
      required: ['language', 'code']
    }
  },
  {
    name: 'stats',
    description: 'Show session context savings: bytes indexed vs bytes returned to context.',
    inputSchema: { type: 'object', properties: {} }
  }
];

// --- Tool Handlers ---
async function handleBatchExecute({ commands, queries, timeout = 60000 }) {
  const filteredParts = [];
  const rawParts = [];
  const cacheInfo = [];

  for (const c of commands) {
    const result = runCached(c.command, timeout);
    const out = result.stdout || '(no output)';
    const tag = result.fromCache ? ' [cached]' : '';
    const savingsTag = result.filterSavings > 5 ? ` [${result.filterSavings}% filtered]` : '';
    filteredParts.push(`# ${c.label}${tag}${savingsTag}\n${out}\n`);
    // Index raw (unfiltered) output for richer KB search
    rawParts.push(`# ${c.label}\n${result.rawStdout || out}\n`);
    cacheInfo.push(result.fromCache ? `${c.label}:cached` : `${c.label}:fresh`);
  }

  // Cap combined output at 2MB before indexing to prevent memory spikes
  const MAX_COMBINED = 2 * 1024 * 1024;
  let rawCombined = rawParts.join('\n');
  if (rawCombined.length > MAX_COMBINED) {
    rawCombined = rawCombined.slice(0, MAX_COMBINED) + '\n...[output truncated at 2MB]';
  }
  const source = `batch:${commands.map(c => c.label).join(',')}`.slice(0, 80);

  // Index the RAW output so KB search has full content
  const indexed = indexContent(rawCombined, source);
  const inventory = [`## Indexed ${indexed.chunks ?? 0} sections from ${commands.length} commands (${cacheInfo.join(', ')})\n`];

  const allResults = [];
  for (const q of queries) {
    allResults.push(...searchKB(q, 3));
  }

  const resultsText = formatSearchResults(allResults);
  const response = [...inventory, '## Search Results\n', resultsText].join('\n');
  const capped = response.slice(0, 80 * 1024);
  track('batch_execute', capped.length);
  return capped;
}

async function handleSearch({ queries, limit = 3 }) {
  const allResults = [];
  for (const q of queries) {
    allResults.push(...searchKB(q, limit));
  }
  const text = formatSearchResults(allResults);
  track('search', text.length);
  return text;
}

async function handleIndex({ content, source }) {
  const indexed = indexContent(content, source);
  const text = `Indexed into knowledge base: ${indexed.chunks ?? 0} chunks, ${indexed.bytes ?? 0} bytes. Source: "${source}". Use search() to retrieve.`;
  track('index', text.length);
  return text;
}

async function handleExecute({ language, code, timeout = 30000, intent }) {
  const result = await runCode({ language, code, timeout });
  let output = result.stdout || '';
  const rawOutput = output;

  if (result.timedOut) output += '\n[TIMED OUT]';
  if (result.exitCode !== 0 && result.stderr) output += `\n[stderr]: ${result.stderr.slice(0, 500)}`;

  // Apply output filtering for shell commands
  if (language === 'shell' && output) {
    const cmd = code.trim().split('\n')[0]; // use first line as command hint
    const f = filterOutput(cmd, output, result.stderr);
    output = f.filtered;
    sessionStats.filterStats.rawBytes += f.rawLen;
    sessionStats.filterStats.filteredBytes += f.filteredLen;
    if (f.savings > 0) sessionStats.filterStats.commandsFiltered++;
  }

  const INTENT_THRESHOLD = 5000;
  if (intent && Buffer.byteLength(output) > INTENT_THRESHOLD) {
    const source = `execute:${language}`;
    // Index raw output for richer search
    indexContent(rawOutput, source);
    const results = searchKB(intent, 5);
    const text = `Output too large (${output.length} bytes) — indexed and searched by intent: "${intent}"\n\n` + formatSearchResults(results);
    track('execute', text.length);
    return text;
  }

  const text = output.slice(0, 80 * 1024);
  track('execute', text.length);
  return text;
}

function handleStats() {
  const elapsed = Math.round((Date.now() - sessionStats.start) / 1000);
  const ratio = sessionStats.bytesIndexed > 0
    ? (sessionStats.bytesIndexed / Math.max(sessionStats.bytesReturned, 1)).toFixed(1)
    : '1.0';

  const { rawBytes, filteredBytes, commandsFiltered } = sessionStats.filterStats;
  const filterSavings = rawBytes > 0
    ? Math.round((1 - filteredBytes / rawBytes) * 100)
    : 0;
  const tokensSaved = estimateTokens(rawBytes - filteredBytes);

  const lines = [
    `Session: ${elapsed}s`,
    `Calls: ${JSON.stringify(sessionStats.calls)}`,
    `Cache hits: ${sessionStats.cacheHits}`,
    `Returned to context: ${(sessionStats.bytesReturned / 1024).toFixed(1)}KB`,
    `Indexed (kept out of context): ${(sessionStats.bytesIndexed / 1024).toFixed(1)}KB`,
    `Context savings ratio: ${ratio}x (${ratio}x more indexed than returned)`,
    `Output filtering: ${commandsFiltered} commands filtered, ${filterSavings}% reduction (${(rawBytes/1024).toFixed(1)}KB → ${(filteredBytes/1024).toFixed(1)}KB, ~${tokensSaved} tokens saved)`,
  ];
  return lines.join('\n');
}

// --- MCP JSON-RPC Server ---
export function createServer() {
  let buffer = '';

  process.stdin.setEncoding('utf8');
  process.stdin.on('data', (chunk) => {
    buffer += chunk;
    const lines = buffer.split('\n');
    buffer = lines.pop() ?? '';
    for (const line of lines) {
      if (line.trim()) handleLine(line.trim());
    }
  });

  process.stdin.on('end', () => process.exit(0));

  function respond(id, result) {
    process.stdout.write(JSON.stringify({ jsonrpc: '2.0', id, result }) + '\n');
  }

  function respondError(id, code, message) {
    process.stdout.write(JSON.stringify({ jsonrpc: '2.0', id, error: { code, message } }) + '\n');
  }

  async function handleLine(line) {
    let msg;
    try { msg = JSON.parse(line); } catch { return; }

    const { id, method, params } = msg;

    if (method === 'initialize') {
      respond(id, {
        protocolVersion: '2024-11-05',
        capabilities: { tools: {} },
        serverInfo: { name: 'claude-teams-brain', version: '1.0.0' }
      });
    } else if (method === 'tools/list') {
      respond(id, { tools: TOOLS });
    } else if (method === 'tools/call') {
      const { name, arguments: toolArgs } = params ?? {};
      try {
        let text;
        if (name === 'batch_execute') text = await handleBatchExecute(toolArgs);
        else if (name === 'search') text = await handleSearch(toolArgs);
        else if (name === 'index') text = await handleIndex(toolArgs);
        else if (name === 'execute') text = await handleExecute(toolArgs);
        else if (name === 'stats') text = handleStats();
        else throw new Error(`Unknown tool: ${name}`);
        respond(id, { content: [{ type: 'text', text }] });
      } catch (err) {
        respondError(id, -32000, err.message);
      }
    } else if (method === 'notifications/initialized') {
      // no response needed
    } else {
      respondError(id, -32601, `Method not found: ${method}`);
    }
  }
}
