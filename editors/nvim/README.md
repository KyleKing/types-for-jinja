# types-for-jinja in Neovim

Type checking for Jinja templates, surfaced as inline diagnostics, completions,
and hovers.
Uses the built-in LSP client (Neovim 0.11+), so no plugin manager is required.

## How it fits together

types-for-jinja does not run a type checker.
Its language server transpiles the template you are editing into a Python stub
and writes it into `_jinja_stubs/`.
Your own Python language server (pyright, ty, basedpyright, whatever you already
use) picks that file up and type-checks it, because it is ordinary Python in
your workspace.
A small Lua layer then copies those diagnostics back onto the template buffer,
on the template's own line and column.

Mirroring has to happen on the client side, because one language server cannot
read another server's diagnostics.
The column arithmetic still lives in Python, reached through a custom request,
so the editor and `types-for-jinja remap` can never disagree about where an
error belongs.

```
page.html.jinja  ──types-for-jinja-lsp──►  _jinja_stubs/page_html_jinja.py
      ▲                                              │
      │                                       your Python LSP
      └────────  mirror.lua  ◄─────────────  diagnostics
```

## Install

1. Install types-for-jinja with the LSP extra so the `types-for-jinja-lsp` command
    exists:

    ```sh
    uv pip install 'types-for-jinja[lsp]'   # or: uv sync --extra lsp in this repo
    ```

1. Copy the server config and the mirror into your Neovim config:

    ```sh
    cp editors/nvim/lsp/types_for_jinja.lua ~/.config/nvim/lsp/types_for_jinja.lua
    cp -r editors/nvim/lua/types_for_jinja ~/.config/nvim/lua/types_for_jinja
    ```

1. Enable it, add filetype detection for templates, and start the mirror:

    ```lua
    vim.filetype.add({
      extension = { jinja = 'jinja' },
      pattern = { ['.*%.html%.jinja'] = 'jinja' },
    })
    vim.lsp.enable('types_for_jinja')
    require('types_for_jinja.mirror').setup()
    ```

Open a template that has a `{#def ... #}` header.
Its stub appears under `_jinja_stubs/`, your Python language server checks it,
and the errors show up on the template.

Add `_jinja_stubs/` to `.gitignore` unless you want the stubs committed.
Committing them is a reasonable choice, because it makes template errors visible
to anyone running the project's checker without them installing types-for-jinja
at all.

## What each server reports

The types-for-jinja server publishes only what it can determine without a
checker:

- a template with no `{#def ... #}` header (warning, skipped)
- a malformed header, on the header's line
- a Jinja syntax error, on the tag Jinja's parser gave up at
- a construct the transpiler cannot model, so one odd template does not stop the
    rest

Everything about the types themselves comes from your Python language server
through the mirror:
undefined names, wrong attributes, bad indexes, argument mismatches, and
whatever else your checker is configured to report.
Its own rule codes come with it, so per-code suppression and quick fixes behave
as they do everywhere else in the project.

Hints and informational notes are not mirrored.
Those are about the generated scaffolding rather than the template, and a
template author cannot act on them.

## Completion

Neovim does not turn LSP completion on by itself.
Enable it per buffer when the server attaches, and add `menuone` so the popup
still opens when only one name matches:

```lua
vim.o.completeopt = 'menu,menuone,popup'
vim.api.nvim_create_autocmd('LspAttach', {
  callback = function(args)
    vim.lsp.completion.enable(true, args.data.client_id, args.buf, { autotrigger = true })
  end,
})
```

Inside `{{ }}` or `{% %}` the popup lists the names the typed context makes
available on that line, each with where it came from:

```
current_route  Variable  current_route: str (global)
item           Variable  item (loop target)
loop           Variable  loop (loop helper)
static_url     Variable  static_url: Callable[[str], str] (global)
user           Field     user: User (parameter)
```

Loop and macro variables appear only inside the body that binds them, and a `{%
set %}` name only after the line that sets it.
`K` (`vim.lsp.buf.hover`) reports the same description for the name under the
cursor.

What gets offered follows the cursor:
built-in filters after a `|` (with their return type), built-in tests after
`is`, and Jinja tags right after `{%`.

```
length  Function  length -> int (built-in filter)
sort    Function  sort -> list[item] (built-in filter)
```

After a `.`, the members of the expression's actual type are offered.
That answer comes from a Python language server the completion starts and
reuses, so a loop variable offers its element's attributes:

```
{{ item.      ->  title  done
```

An expression whose type cannot be resolved offers nothing rather than guessing.

## The command path

The shipped config runs `types-for-jinja-lsp` from `PATH`, which works when the
project venv is active.
For a project-local venv without activation, either point `cmd` at the absolute
path (`<root>/.venv/bin/types-for-jinja-lsp`), use the `uv run` form (`cmd = {
'uv', 'run', 'types-for-jinja-lsp' }`), or use the venv-resolving function shown
in the comments of `types_for_jinja.lua`.

## When it re-checks

The server writes the stub on open, on save, and once an edit has been idle for
300 ms. The debounce is there because each write makes your Python language
server re-check the file, and that is the expensive half.

Writing the stub from the live buffer is what makes unsaved edits visible, which
does leave the stub tree ahead of the saved template.
Closing the buffer puts the stub back to what the saved file says, so an
abandoned edit stops reporting errors the file does not have.

## Verify

`scripts/verify_lsp.sh` builds a throwaway project and runs headless Neovim over
eight phases:
a headerless template reported without a checker, a stub written on open, an
unsaved edit reaching the stub, context-name completion inside a loop body,
hover over a declared parameter, attribute completion, filter completion, and
the mirror carrying a real Python language server's diagnostics back onto the
template.
It exits non-zero unless every phase produces the expected result.
Expected output:

```
phase1 (no header) diagnostics=1
  L1 [types-for-jinja] no {#def ... #} type header; skipped
phase2 (stub written) ok=true
phase3 (unsaved edit in stub) ok=true
phase4 (context completion)
  user -- user: User (parameter)
  loop -- loop (loop helper)
  item -- item (loop target)
phase5 (hover) user: User (parameter)
phase6 (members) done,title
phase7 (filters) length=length -> int (built-in filter)
phase8 (mirrored) appeared=true count=3
  L5 C19 Cannot access attribute "naem" for class "User" | on: <h1>Hello {{ user.naem }}</h1>
  L8 C15 Cannot access attribute "titel" for class "Item" | on:   <li>{{ item.titel }} by {{ author }}</li>
  L8 C30 "author" is not defined | on:   <li>{{ item.titel }} by {{ author }}</li>
phases ok: 1=true 2=true 3=true 4=true 5=true 6=true 7=true 8=true
```

## Other editors

VS Code, Cursor, Zed, and Helix need the same client-side mirror written against
their own diagnostic APIs.
None of that is built.
See `docs/BLUE_SKY.md`.
Until then, those editors get the stub with the right line, one jump from the
template, plus every feature the types-for-jinja server provides directly.
