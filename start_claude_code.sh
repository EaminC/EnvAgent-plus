#!/usr/bin/env bash
set -euo pipefail

# Load nvm when available so `claude` is discoverable in non-login shells.
if [[ -s "${HOME}/.nvm/nvm.sh" ]]; then
  # shellcheck disable=SC1090
  source "${HOME}/.nvm/nvm.sh"
  nvm use --silent default >/dev/null 2>&1 || true
fi

# Export your Forge key in the shell before running this script.
# Example: export ANTHROPIC_AUTH_TOKEN="<your_forge_key>"
if [[ -z "${ANTHROPIC_AUTH_TOKEN:-}" ]]; then
  echo "ANTHROPIC_AUTH_TOKEN is not set."
  echo "Run: export ANTHROPIC_AUTH_TOKEN='<your_forge_key>'"
  exit 1
fi

if ! command -v claude >/dev/null 2>&1; then
  echo "claude command not found. Install Claude Code first (npm install -g @anthropic-ai/claude-code)."
  exit 1
fi

# Claude Code uses Anthropic-style environment names.
# Keep base URL without /v1 so the client can append paths correctly.
export ANTHROPIC_BASE_URL="${ANTHROPIC_BASE_URL:-https://api.forge.tensorblock.co}"
export ANTHROPIC_MODEL="${ANTHROPIC_MODEL:-Fireworks/accounts/fireworks/models/qwen3-coder-480b-a35b-instruct}"
export ANTHROPIC_SMALL_FAST_MODEL="${ANTHROPIC_SMALL_FAST_MODEL:-Gemini/models/gemini-2.5-flash}"

exec claude "$@"
