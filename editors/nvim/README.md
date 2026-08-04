# types-for-jinja in Neovim

Static type checking for Jinja templates, surfaced as inline diagnostics. Uses the built-in LSP client (Neovim 0.11+), so no plugin is required.

## Install

1. Install types-for-jinja with the LSP extra so the `types-for-jinja-lsp` command exists:

    ```sh
    uv pip install 'types-for-jinja[lsp]'   # or: uv sync --extra lsp in this repo
    ```

1. Copy the server config into your Neovim config:

    ```sh
    cp editors/nvim/lsp/types_for_jinja.lua ~/.config/nvim/lsp/types_for_jinja.lua
    ```

1. Enable it and add filetype detection for templates in your `init.lua`:

    ```lua
    vim.filetype.add({
      extension = { jinja = 'jinja' },
      pattern = { ['.*%.html%.jinja'] = 'jinja' },
    })
    vim.lsp.enable('types_for_jinja')
    ```

Open a template that has a `{#def ... #}` header and save it. Errors show as diagnostics (`:lua vim.diagnostic.get(0)` to inspect, or your usual diagnostic UI).

## The command path

The shipped config runs `types-for-jinja-lsp` from `PATH`, which works when the project venv is active. For a project-local venv without activation, either point `cmd` at the absolute path (`<root>/.venv/bin/types-for-jinja-lsp`), use the `uv run` form (`cmd = { 'uv', 'run', 'types-for-jinja-lsp' }`), or use the venv-resolving function shown in the comments of `types_for_jinja.lua`.

## What it checks

The server checks the file on disk on open and on save (not unsaved buffer edits, for now). It runs the same checker as the CLI, so diagnostics match `types-for-jinja check`.

## Verify

`scripts/verify_lsp.sh` runs a headless Neovim, opens a template with known errors, and confirms the server attaches and publishes diagnostics. Expected output:

```
attached=true ready=true diagnostics=3
  L5 C14 [types-for-jinja] Cannot access attribute "naem" for class "User" ...
  L11 C18 [types-for-jinja] Cannot access attribute "titel" for class "Item" ...
  L11 C13 [types-for-jinja] "author" is not defined
```
