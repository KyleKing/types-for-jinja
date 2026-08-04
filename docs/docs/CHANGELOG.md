## Unreleased

### Feat

- **generate**: record each stub's template in a manifest
- **generate**: make the stubs check clean under ty, mypy, and pyright
- **lsp**: complete attributes by asking pyright what the type offers
- **lsp**: complete Jinja's own filters, tests, and tags
- support custom Jinja delimiters and package-relative template dirs
- give Jinja's built-in filters and tests real return types
- follow {% include %} context and whole {% extends %} chains
- type macro parameters from a macro's own {#def #} block
- **cli**: add `types-for-jinja wrapper` for typed render call sites
- **lsp**: complete and describe the names a template's typed context provides
- **generate**: write stubs for an existing type checker to pick up
- **layout**: align generated stubs to their template line numbers
- add stable rule codes (TJ###) and inline suppression
- **lsp**: check unsaved buffers live
- **transpile**: model macro bodies and cross-file extends/import context
- **wrapper**: enforce context types at runtime with beartype or pydantic
- **lsp**: add the language server with Neovim integration
- add the pre-commit hook and harden the transpiler
- declare Environment globals and add JSON/SARIF output
- add codegen-first checker spike

### Fix

- **lsp**: prepare the checker cache on first use, not on import
- restore the collapsed {#def #} headers and stop them silently breaking
- **deps**: bump gitpython to 3.1.57
- **tests**: satisfy mypy on the test suite
- **transpile**: rename Jinja variables that collide with Python keywords
- **check**: make the cache directory self-ignoring
- **transpile**: define the Jinja loop variable inside for bodies

### Refactor

- **transpile**: expose emitted lines and flag cross-file definitions
- split out check_source, Diagnostic, and codes/suppress seams


- rename to types-for-jinja
