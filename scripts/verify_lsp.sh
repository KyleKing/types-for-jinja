#!/usr/bin/env bash
# Headless smoke test of the typed-jinja LSP. Run from the project root.
set -euo pipefail
cd "$(dirname "$0")/.."
rm -rf .typed_jinja_cache
nvim --headless -l scripts/verify_lsp.lua
