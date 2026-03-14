#!/usr/bin/env bash
# claude-teams-brain: bootstrap install script
#
# Workaround for a Claude Code bug where /plugin marketplace add registers
# the marketplace in known_marketplaces.json but does NOT clone the repo to
# disk. The installer then fails with "Source path does not exist".
#
# This script clones the repo to the expected location, patches
# known_marketplaces.json so the installLocation is correct, then syncs
# everything into the plugin cache — exactly what /plugin marketplace add
# should have done.
#
# Usage (one-liner, run from any directory):
#   bash <(curl -fsSL https://raw.githubusercontent.com/Gr122lyBr/claude-teams-brain/master/scripts/install.sh)
#
# Or after cloning manually (the manual workaround path):
#   bash ~/.claude/plugins/marketplaces/claude-teams-brain/scripts/install.sh

set -euo pipefail

REPO_URL="https://github.com/Gr122lyBr/claude-teams-brain.git"
REPO_URL_BARE="https://github.com/Gr122lyBr/claude-teams-brain"
PLUGINS_DIR="${HOME}/.claude/plugins"
MARKETPLACE_DIR="${PLUGINS_DIR}/marketplaces/claude-teams-brain"
KNOWN_MARKETPLACES="${PLUGINS_DIR}/known_marketplaces.json"

echo "==> claude-teams-brain bootstrap install"
echo "==> Plugins dir:     ${PLUGINS_DIR}"
echo "==> Marketplace dir: ${MARKETPLACE_DIR}"
echo ""

# --- 1. Clone marketplace repo if missing, otherwise pull latest ---
if [ ! -d "${MARKETPLACE_DIR}/.git" ]; then
  echo "==> Cloning repo to ${MARKETPLACE_DIR}..."
  mkdir -p "$(dirname "${MARKETPLACE_DIR}")"
  git clone "${REPO_URL}" "${MARKETPLACE_DIR}"
  echo "    Cloned successfully."
else
  echo "==> Repo already at ${MARKETPLACE_DIR} — pulling latest..."
  cd "${MARKETPLACE_DIR}"
  git fetch origin
  BEFORE=$(git rev-parse HEAD)
  git pull --ff-only origin "$(git symbolic-ref --short HEAD)"
  AFTER=$(git rev-parse HEAD)
  if [ "${BEFORE}" = "${AFTER}" ]; then
    echo "    Already up to date ($(git rev-parse --short HEAD))"
  else
    echo "    Updated: $(git rev-parse --short "${BEFORE}")..$(git rev-parse --short "${AFTER}")"
  fi
fi

# --- 2. Patch known_marketplaces.json so installLocation points to the cloned repo ---
# Claude Code's /plugin marketplace add writes this file but doesn't clone the repo,
# leaving installLocation pointing at a path that doesn't exist.  We fix that here.
if [ -f "${KNOWN_MARKETPLACES}" ]; then
  echo ""
  echo "==> Patching known_marketplaces.json..."
  python3 - <<PYEOF
import json, os, sys

path = "${KNOWN_MARKETPLACES}"
marketplace_dir = "${MARKETPLACE_DIR}"
repo_url = "${REPO_URL_BARE}"

with open(path, 'r') as f:
    raw = f.read().strip()

if not raw:
    data = {}
else:
    data = json.loads(raw)

def patch_entry(entry):
    entry["installLocation"] = marketplace_dir
    if "url" not in entry:
        entry["url"] = repo_url
    return entry

patched = False

# Format 1: {"marketplaces": {"claude-teams-brain": {...}}}
if isinstance(data, dict) and "marketplaces" in data and isinstance(data["marketplaces"], dict):
    m = data["marketplaces"]
    if "claude-teams-brain" not in m:
        m["claude-teams-brain"] = {"name": "claude-teams-brain", "url": repo_url}
    patch_entry(m["claude-teams-brain"])
    patched = True

# Format 2: {"marketplaces": [...]} or top-level list
elif isinstance(data, (dict, list)):
    items = data.get("marketplaces", data) if isinstance(data, dict) else data
    if isinstance(items, list):
        found = False
        for entry in items:
            if isinstance(entry, dict) and entry.get("name") == "claude-teams-brain":
                patch_entry(entry)
                found = True
        if not found:
            items.append({"name": "claude-teams-brain", "url": repo_url, "installLocation": marketplace_dir})
        patched = True
    elif isinstance(items, dict):
        if "claude-teams-brain" not in items:
            items["claude-teams-brain"] = {"name": "claude-teams-brain", "url": repo_url}
        patch_entry(items["claude-teams-brain"])
        patched = True

if patched:
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"    Patched: installLocation => {marketplace_dir}")
else:
    print(f"    WARN: Unrecognised known_marketplaces.json format — skipped patching")
    print(f"    You may need to manually set installLocation to: {marketplace_dir}")
PYEOF
else
  echo ""
  echo "    known_marketplaces.json not found — it will be created by Claude Code on next run."
fi

# --- 3. Read version from source ---
PLUGIN_SRC="${MARKETPLACE_DIR}/claude-teams-brain"

if [ ! -f "${PLUGIN_SRC}/package.json" ]; then
  echo "ERROR: Plugin source not found at ${PLUGIN_SRC}/package.json"
  exit 1
fi

NEW_VERSION=$(node -p "require('${PLUGIN_SRC}/package.json').version" 2>/dev/null || python3 -c "import json; print(json.load(open('${PLUGIN_SRC}/package.json'))['version'])")

if [ -z "${NEW_VERSION}" ]; then
  echo "ERROR: Could not read version from ${PLUGIN_SRC}/package.json"
  exit 1
fi
echo ""
echo "==> Version: ${NEW_VERSION}"

# --- 4. Sync plugin source to versioned cache directory ---
CACHE_BASE="${PLUGINS_DIR}/cache/claude-teams-brain/claude-teams-brain"
NEW_CACHE_DIR="${CACHE_BASE}/${NEW_VERSION}"

mkdir -p "${NEW_CACHE_DIR}"
echo "==> Syncing to cache: ${NEW_CACHE_DIR}"

if command -v rsync &>/dev/null; then
  rsync -a --delete --exclude='.git' "${PLUGIN_SRC}/" "${NEW_CACHE_DIR}/"
else
  # Fallback for systems without rsync (e.g. bare Windows without WSL rsync)
  cp -r "${PLUGIN_SRC}/." "${NEW_CACHE_DIR}/"
fi
echo "    Sync complete."

# --- 5. Update installed_plugins.json ---
INSTALLED_JSON="${PLUGINS_DIR}/installed_plugins.json"

if [ -f "${INSTALLED_JSON}" ]; then
  echo "==> Updating installed_plugins.json..."
  python3 - <<PYEOF
import json, datetime

path = "${INSTALLED_JSON}"
new_version = "${NEW_VERSION}"
new_cache_dir = "${NEW_CACHE_DIR}"
repo_url = "${REPO_URL_BARE}"

with open(path, 'r') as f:
    data = json.load(f)

plugins = data.setdefault("plugins", {})
key = "claude-teams-brain@claude-teams-brain"
now = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.000Z')

new_entry = {
    "version": new_version,
    "installPath": new_cache_dir,
    "source": repo_url,
    "lastUpdated": now
}

if key in plugins and isinstance(plugins[key], list) and plugins[key]:
    for e in plugins[key]:
        e.update(new_entry)
    print(f"    Updated existing entry to v{new_version}")
else:
    plugins[key] = [new_entry]
    print(f"    Created new entry for v{new_version} at {new_cache_dir}")

with open(path, 'w') as f:
    json.dump(data, f, indent=2)
PYEOF
else
  echo "    installed_plugins.json not found — Claude Code will create it on next install."
fi

# --- 6. Add MCP tool permissions to ~/.claude/settings.json ---
SETTINGS_JSON="${HOME}/.claude/settings.json"
echo "==> Adding MCP tool permissions to ${SETTINGS_JSON}..."
python3 - <<PYEOF
import json, os

settings_path = "${SETTINGS_JSON}"

# Ensure directory exists
os.makedirs(os.path.dirname(settings_path), exist_ok=True)

# Read existing settings or start fresh
if os.path.exists(settings_path):
    with open(settings_path, 'r') as f:
        raw = f.read().strip()
    data = json.loads(raw) if raw else {}
else:
    data = {}

# Our MCP tool permission keys
brain_tools = [
    "mcp__plugin_claude-teams-brain_claude-teams-brain__batch_execute",
    "mcp__plugin_claude-teams-brain_claude-teams-brain__execute",
    "mcp__plugin_claude-teams-brain_claude-teams-brain__search",
    "mcp__plugin_claude-teams-brain_claude-teams-brain__index",
    "mcp__plugin_claude-teams-brain_claude-teams-brain__stats",
]

permissions = data.setdefault("permissions", {})
allow_list = permissions.setdefault("allow", [])

added = []
for tool in brain_tools:
    if tool not in allow_list:
        allow_list.append(tool)
        added.append(tool.split("__")[-1])

if added:
    with open(settings_path, 'w') as f:
        json.dump(data, f, indent=2)
    print(f"    Added permissions: {', '.join(added)}")
else:
    print("    All brain MCP tools already permitted.")
PYEOF

echo ""
echo "==> Bootstrap complete!"
echo ""
echo "Next steps:"
echo "  1. Restart Claude Code"
echo "  2. If the plugin does not appear active, run inside Claude Code:"
echo "        /plugin install claude-teams-brain@claude-teams-brain"
echo "  3. (Optional) Enable Agent Teams in ~/.claude/settings.json:"
echo '        "env": { "CLAUDE_CODE_EXPERIMENTAL_AGENT_TEAMS": "1" }'
