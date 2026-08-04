#!/usr/bin/env bash
# Headless smoke test of the types-for-jinja LSP in a real Neovim session.
#
# Builds a throwaway project from tests/backends.py so nothing lands in the repo,
# then drives nvim over it. Pass a directory to keep the project for inspection.
set -euo pipefail
repo="$(cd "$(dirname "$0")/.." && pwd)"

keep="${1:-}"
project="${1:-$(mktemp -d)}"
trap '[ -n "$keep" ] || rm -rf "$project"' EXIT

uv run --project "$repo" python "$repo/scripts/fixture_project.py" "$project"

venv_lsp="$repo/.venv/bin/types-for-jinja-lsp"
if [ -x "$venv_lsp" ]; then export TJ_LSP="$venv_lsp"; fi

cd "$project"
nvim --headless --clean -l "$repo/scripts/verify_lsp.lua"
