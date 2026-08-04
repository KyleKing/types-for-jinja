#!/usr/bin/env bash
# Headless smoke test of the types-for-jinja LSP. Run from the project root.
set -euo pipefail
cd "$(dirname "$0")/.."
rm -rf .types_for_jinja_cache
nvim --headless -l scripts/verify_lsp.lua
