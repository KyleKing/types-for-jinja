# types-for-jinja in Neovim

Static type checking for Jinja templates, surfaced as inline diagnostics, completions, and hovers. Uses the built-in LSP client (Neovim 0.11+), so no plugin is required.

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

## Completion

Neovim does not turn LSP completion on by itself. Enable it per buffer when the server attaches, and add `menuone` so the popup still opens when only one name matches:

```lua
vim.o.completeopt = 'menu,menuone,popup'
vim.api.nvim_create_autocmd('LspAttach', {
  callback = function(args)
    vim.lsp.completion.enable(true, args.data.client_id, args.buf, { autotrigger = true })
  end,
})
```

Inside `{{ }}` or `{% %}` the popup lists the names the typed context makes available on that line, each with where it came from:

```
current_route  Variable  current_route: str (global)
item           Variable  item (loop target)
loop           Variable  loop (loop helper)
static_url     Variable  static_url: Callable[[str], str] (global)
user           Field     user: User (parameter)
```

Loop and macro variables appear only inside the body that binds them, and a `{% set %}` name only after the line that sets it. `K` (`vim.lsp.buf.hover`) reports the same description for the name under the cursor.

What gets offered follows the cursor: built-in filters after a `|` (with their return type), built-in tests after `is`, and Jinja tags right after `{%`.

```
length  Function  length -> int (built-in filter)
sort    Function  sort -> list[item] (built-in filter)
```

Attribute completion after a `.` is not offered yet; the checker still reports a bad attribute as a diagnostic.

## The command path

The shipped config runs `types-for-jinja-lsp` from `PATH`, which works when the project venv is active. For a project-local venv without activation, either point `cmd` at the absolute path (`<root>/.venv/bin/types-for-jinja-lsp`), use the `uv run` form (`cmd = { 'uv', 'run', 'types-for-jinja-lsp' }`), or use the venv-resolving function shown in the comments of `types_for_jinja.lua`.

## What it checks

The server checks the live buffer on open, on save, and once an edit settles, so unsaved edits are reflected. It falls back to the file on disk when no buffer is tracked. It runs the same checker as the CLI, so diagnostics match `types-for-jinja check`.

Edits are debounced by 300 ms because each check runs pyright, which is much slower than a keystroke. Completions and hovers are not debounced.

## Verify

`scripts/verify_lsp.sh` runs a headless Neovim over four phases: a bad template on disk, an unsaved edit to a clean template, a completion request inside a loop body, and a hover over a declared parameter. It exits non-zero unless every phase produces the expected result. Expected output:

```
phase1 (disk) diagnostics=3
  L5 C14 [types-for-jinja] Cannot access attribute "naem" for class "User" ...
  L11 C18 [types-for-jinja] Cannot access attribute "titel" for class "Item" ...
  L11 C13 [types-for-jinja] "author" is not defined
phase2 (live buffer) clean_before=0 after_edit=1
  L5 C14 [types-for-jinja] Cannot access attribute "nmae" for class "User" ...
phase3 (completion) items=5
  user -- user: User (parameter)
  ...
phase4 (hover) user: User (parameter)
phases ok: 1=true 2=true 3=true 4=true
```
