#!/usr/bin/env bash
# claude-teams-brain: update script
#
# Pulls the latest version from GitHub and syncs it into the plugin cache.
# Called by the /brain-update skill.

set -euo pipefail

PLUGIN_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
MARKETPLACE_DIR="$(cd "${PLUGIN_ROOT}/../../../.." && pwd)/marketplaces/claude-teams-brain"

echo "==> Plugin root:     $PLUGIN_ROOT"
echo "==> Marketplace dir: $MARKETPLACE_DIR"

# --- 1. Pull latest from GitHub ---
if [ ! -d "$MARKETPLACE_DIR/.git" ]; then
  echo "ERROR: Marketplace clone not found at $MARKETPLACE_DIR"
  echo "       Re-add the marketplace: /plugin marketplace add https://github.com/Gr122lyBr/claude-teams-brain"
  exit 1
fi

echo ""
echo "==> Pulling latest from GitHub..."
cd "$MARKETPLACE_DIR"
git fetch origin
BEFORE=$(git rev-parse HEAD)
git pull --ff-only origin "$(git symbolic-ref --short HEAD)"
AFTER=$(git rev-parse HEAD)

if [ "$BEFORE" = "$AFTER" ]; then
  echo "    Already up to date ($(git rev-parse --short HEAD))"
  CHANGED_FILES="none"
else
  echo "    Updated: $(git rev-parse --short "$BEFORE")..$(git rev-parse --short "$AFTER")"
  CHANGED_FILES=$(git diff --name-only "$BEFORE" "$AFTER" | head -20 || echo "unknown")
  echo "    Changed files:"
  echo "$CHANGED_FILES" | sed 's/^/      /'
fi

# --- 2. Locate the versioned plugin source ---
PLUGIN_SRC="${MARKETPLACE_DIR}/claude-teams-brain"
VERSION=$(node -p "require('${PLUGIN_SRC}/package.json').version" 2>/dev/null || echo "unknown")
echo ""
echo "==> Version: $VERSION"

# --- 3. Sync to plugin cache ---
CACHE_DIR="${PLUGIN_ROOT}/../../cache/claude-teams-brain/claude-teams-brain"

if [ -d "$CACHE_DIR" ]; then
  # Find the installed version directory (may differ from package.json if manually set)
  CACHE_VERSION_DIR=$(ls -d "${CACHE_DIR}/"*/ 2>/dev/null | head -1)
  if [ -n "$CACHE_VERSION_DIR" ]; then
    echo ""
    echo "==> Syncing to cache: $CACHE_VERSION_DIR"
    rsync -a --delete \
      --exclude='.git' \
      "${PLUGIN_SRC}/" "${CACHE_VERSION_DIR}"
    echo "    Sync complete."
  else
    echo "WARN: No versioned cache directory found under $CACHE_DIR — skipping sync."
    echo "      Reinstall the plugin to create the cache entry."
  fi
else
  echo "WARN: Cache directory not found — skipping sync."
  echo "      Install the plugin first: /plugin install claude-teams-brain"
fi

echo ""
echo "==> Done."
echo "    Restart Claude Code to apply any hook or settings changes."
