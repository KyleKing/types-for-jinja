# typed-jinja in Neovim

Static type checking for Jinja templates, surfaced as inline diagnostics. Uses the
built-in LSP client (Neovim 0.11+), so no plugin is required.

## Install

1. Install typed-jinja with the LSP extra so the `typed-jinja-lsp` command exists:

   ```sh
   uv pip install 'typed-jinja[lsp]'   # or: uv sync --extra lsp in this repo
   ```

2. Copy the server config into your Neovim config:

   ```sh
   cp editors/nvim/lsp/typed_jinja.lua ~/.config/nvim/lsp/typed_jinja.lua
   ```

3. Enable it and add filetype detection for templates in your `init.lua`:

   ```lua
   vim.filetype.add({
     extension = { jinja = 'jinja' },
     pattern = { ['.*%.html%.jinja'] = 'jinja' },
   })
   vim.lsp.enable('typed_jinja')
   ```

Open a template that has a `{#def ... #}` header and save it. Errors show as
diagnostics (`:lua vim.diagnostic.get(0)` to inspect, or your usual diagnostic UI).

## The command path

The shipped config runs `typed-jinja-lsp` from `PATH`, which works when the project
venv is active. For a project-local venv without activation, either point `cmd` at the
absolute path (`<root>/.venv/bin/typed-jinja-lsp`), use the `uv run` form
(`cmd = { 'uv', 'run', 'typed-jinja-lsp' }`), or use the venv-resolving function shown
in the comments of `typed_jinja.lua`.

## What it checks

The server checks the file on disk on open and on save (not unsaved buffer edits, for
now). It runs the same checker as the CLI, so diagnostics match `typed-jinja check`.

## Verify

`scripts/verify_lsp.sh` runs a headless Neovim, opens a template with known errors,
and confirms the server attaches and publishes diagnostics. Expected output:

```
attached=true ready=true diagnostics=3
  L5 C14 [typed-jinja] Cannot access attribute "naem" for class "User" ...
  L11 C18 [typed-jinja] Cannot access attribute "titel" for class "Item" ...
  L11 C13 [typed-jinja] "author" is not defined
```
