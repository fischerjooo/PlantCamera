#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

echo "Fetching latest main branch..."
git fetch --prune origin main

echo "Switching to main branch..."
git checkout main

echo "Rebasing local main onto origin/main..."
git pull --rebase origin main

echo "Repository is now up to date with origin/main."
