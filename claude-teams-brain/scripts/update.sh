#!/usr/bin/env bash
# claude-teams-brain: update script
#
# Pulls the latest version from GitHub and syncs it into the plugin cache.
# Called by the /brain-update command.

set -euo pipefail

PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PLUGINS_DIR="$(cd "${PLUGIN_ROOT}/../../../.." && pwd)"
MARKETPLACE_DIR="${PLUGINS_DIR}/marketplaces/claude-teams-brain"
REPO_URL="https://github.com/Gr122lyBr/claude-teams-brain.git"
REPO_URL_BARE="https://github.com/Gr122lyBr/claude-teams-brain"
KNOWN_MARKETPLACES="${PLUGINS_DIR}/known_marketplaces.json"

echo "==> Plugin root:     $PLUGIN_ROOT"
echo "==> Marketplace dir: $MARKETPLACE_DIR"

# --- 1. Ensure marketplace clone exists (auto-clone if missing) ---
if [ ! -d "$MARKETPLACE_DIR/.git" ]; then
  echo ""
  echo "==> Marketplace clone not found — cloning fresh..."
  echo "    (This fixes the Claude Code bug where /plugin marketplace add"
  echo "     registers the marketplace but does not clone the repo to disk.)"
  mkdir -p "$(dirname "$MARKETPLACE_DIR")"
  git clone "$REPO_URL" "$MARKETPLACE_DIR"
  echo "    Cloned successfully."
else
  echo ""
  echo "==> Pulling latest from GitHub..."
  cd "$MARKETPLACE_DIR"
  git fetch origin
  BEFORE=$(git rev-parse HEAD)
  git pull --ff-only origin "$(git symbolic-ref --short HEAD)"
  AFTER=$(git rev-parse HEAD)

  if [ "$BEFORE" = "$AFTER" ]; then
    echo "    Already up to date ($(git rev-parse --short HEAD))"
  else
    echo "    Updated: $(git rev-parse --short "$BEFORE")..$(git rev-parse --short "$AFTER")"
    CHANGED=$(git diff --name-only "$BEFORE" "$AFTER" | head -20 || echo "unknown")
    echo "    Changed files:"
    echo "$CHANGED" | sed 's/^/      /'
  fi
fi

# --- 1b. Patch known_marketplaces.json so installLocation is always correct ---
# Claude Code's /plugin marketplace add writes this file but doesn't clone the repo,
# so installLocation may point at a non-existent path. Fix it here after every update.
if [ -f "$KNOWN_MARKETPLACES" ]; then
  python3 - <<PYEOF 2>/dev/null && echo "==> Patched known_marketplaces.json (installLocation verified)" || true
import json, os

path = "${KNOWN_MARKETPLACES}"
marketplace_dir = "${MARKETPLACE_DIR}"
repo_url = "${REPO_URL_BARE}"

with open(path, 'r') as f:
    raw = f.read().strip()
if not raw:
    exit(0)
data = json.loads(raw)

def patch_entry(entry):
    entry["installLocation"] = marketplace_dir
    if "url" not in entry:
        entry["url"] = repo_url

patched = False
if isinstance(data, dict) and "marketplaces" in data and isinstance(data["marketplaces"], dict):
    m = data["marketplaces"]
    if "claude-teams-brain" not in m:
        m["claude-teams-brain"] = {"name": "claude-teams-brain", "url": repo_url}
    patch_entry(m["claude-teams-brain"])
    patched = True
else:
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
PYEOF
fi

# --- 2. Read new version from source ---
PLUGIN_SRC="${MARKETPLACE_DIR}/claude-teams-brain"
NEW_VERSION=$(node -p "require('${PLUGIN_SRC}/package.json').version" 2>/dev/null || echo "")

if [ -z "$NEW_VERSION" ]; then
  echo "ERROR: Could not read version from ${PLUGIN_SRC}/package.json"
  exit 1
fi
echo ""
echo "==> New version: $NEW_VERSION"

# --- 3. Sync to cache, creating new versioned dir if version changed ---
CACHE_BASE="${PLUGINS_DIR}/cache/claude-teams-brain/claude-teams-brain"
NEW_CACHE_DIR="${CACHE_BASE}/${NEW_VERSION}"

mkdir -p "$NEW_CACHE_DIR"
echo "==> Syncing to cache: $NEW_CACHE_DIR"
rsync -a --delete --exclude='.git' "${PLUGIN_SRC}/" "${NEW_CACHE_DIR}/"
echo "    Sync complete."

# --- 3c. Ensure plugin.json version matches package.json version in cache ---
python3 - <<PYEOF 2>/dev/null || true
import json, os
plugin_json_path = os.path.join("${NEW_CACHE_DIR}", ".claude-plugin", "plugin.json")
package_json_path = os.path.join("${NEW_CACHE_DIR}", "package.json")
if os.path.exists(plugin_json_path) and os.path.exists(package_json_path):
    with open(package_json_path) as f:
        pkg_version = json.load(f).get("version", "")
    with open(plugin_json_path) as f:
        plugin = json.load(f)
    if pkg_version and plugin.get("version") != pkg_version:
        plugin["version"] = pkg_version
        with open(plugin_json_path, "w") as f:
            json.dump(plugin, f, indent=2)
        print(f"    Patched plugin.json version to {pkg_version}")
PYEOF

# --- 3b. Remove old version directories ---
echo "==> Cleaning up old versions..."
for old_dir in "${CACHE_BASE}"/*/; do
  old_dir="${old_dir%/}"
  if [ "$old_dir" != "$NEW_CACHE_DIR" ] && [ -d "$old_dir" ]; then
    rm -rf "$old_dir"
    echo "    Removed: $(basename "$old_dir")"
  fi
done

# --- 4. Update installed_plugins.json with new version and path ---
# IMPORTANT: Claude Code reads installPath from this file to know which cache dir to load.
# If this update is skipped or uses the wrong key, the plugin loads the old version after restart.
INSTALLED_JSON="${PLUGINS_DIR}/installed_plugins.json"

if [ -f "$INSTALLED_JSON" ]; then
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
now = datetime.datetime.utcnow().strftime('%Y-%m-%dT%H:%M:%S.000Z')

# Try exact key first, then search for any key containing "claude-teams-brain"
canonical_key = "claude-teams-brain@claude-teams-brain"
matched_key = None

if canonical_key in plugins:
    matched_key = canonical_key
else:
    for k in plugins:
        if "claude-teams-brain" in k.lower():
            matched_key = k
            print(f"    Note: found key '{k}' (expected '{canonical_key}') — updating anyway")
            break

new_entry_fields = {
    "version": new_version,
    "installPath": new_cache_dir,
    "lastUpdated": now,
}

if matched_key:
    entries = plugins[matched_key]
    if isinstance(entries, list):
        for e in entries:
            e.update(new_entry_fields)
    else:
        plugins[matched_key] = [dict(entries, **new_entry_fields)]
    print(f"    Updated key '{matched_key}' to v{new_version}")
    print(f"    installPath => {new_cache_dir}")
else:
    # Key not found at all — create it so Claude Code loads the correct path
    plugins[canonical_key] = [{
        "version": new_version,
        "installPath": new_cache_dir,
        "source": repo_url,
        "lastUpdated": now,
    }]
    print(f"    Key not found — created '{canonical_key}' for v{new_version}")
    print(f"    installPath => {new_cache_dir}")
    print(f"    Available keys were: {list(data.get('plugins', {}).keys())}")

with open(path, 'w') as f:
    json.dump(data, f, indent=2)
PYEOF
else
  echo "WARN: installed_plugins.json not found at $INSTALLED_JSON"
  echo "      Claude Code may not load the updated plugin until you run /plugin install again."
fi

# --- 5. Add MCP tool permissions to ~/.claude/settings.json ---
SETTINGS_JSON="${HOME}/.claude/settings.json"
echo "==> Ensuring MCP tool permissions in ${SETTINGS_JSON}..."
python3 - <<PYEOF
import json, os

settings_path = "${SETTINGS_JSON}"

os.makedirs(os.path.dirname(settings_path), exist_ok=True)

if os.path.exists(settings_path):
    with open(settings_path, 'r') as f:
        raw = f.read().strip()
    data = json.loads(raw) if raw else {}
else:
    data = {}

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
echo "==> Done. Restart Claude Code to apply the update."
